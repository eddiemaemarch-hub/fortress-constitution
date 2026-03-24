"""Trader3 — Energy Momentum Options Engine
Backtested signal: $10k → $61.5k (+516%, Sharpe 0.98)
Strategy: Buy CALLS when EMA50 > SMA200 (golden cross), 45-60 DTE, ATM/slightly OTM.
Universe: CCJ, UEC, XOM, CVX, OXY, DVN, FANG, VST, CEG, LEU
Exit: 50% profit target, 50% loss stop, or 21 DTE (whichever first).
"""
# ══════════════════════════════════════════════════════════════
# AUTHORITY LOCK — Rudy v2.0 Constitution v50.0
# This script is NOT authorized to execute trades.
# Authorized traders: trader_v28.py (Trader1/v2.8+),
#                     trader2_mstr_put.py (Trader2),
#                     trader3_spy_put.py (Trader3)
# To re-authorize this script, edit this block explicitly.
# ══════════════════════════════════════════════════════════════
import sys as _sys
_sys.exit(0)
import os
import sys
import json
import math
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import deployer
import telegram
import accountant
import auditor

from ib_insync import *
import yfinance as yf

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
POSITIONS_FILE = os.path.join(DATA_DIR, "trader3_positions.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

PORT = deployer.get_port(3)
CLIENT_ID = 30
MONITOR_CLIENT_ID = 31

# Energy Momentum parameters
UNIVERSE = ["CCJ", "UEC", "XOM", "CVX", "OXY", "DVN", "FANG", "VST", "CEG", "LEU"]
CAPITAL = 20000  # $20k allocation
MAX_POSITIONS = 5
POSITION_SIZE = 800  # ~$800 per options position (leveraged)
MIN_SCORE = 3.0

# Options parameters
TARGET_DTE_MIN = 35  # Minimum days to expiration
TARGET_DTE_MAX = 75  # Maximum days to expiration
STRIKE_OFFSET = 0.02  # 2% OTM (slightly out of the money)
PROFIT_TARGET = 0.50  # Close at +50%
LOSS_STOP = -0.50  # Close at -50%
DTE_EXIT = 21  # Close if less than 21 DTE remaining


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Trader3 {ts}] {msg}")
    with open(f"{LOG_DIR}/trader3.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def connect(client_id=CLIENT_ID):
    ib = IB()
    ib.connect("127.0.0.1", PORT, clientId=client_id)
    ib.reqMarketDataType(3)
    log(f"Connected (client {client_id})")
    return ib


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return []


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def get_technicals(symbol):
    """Get momentum technicals from Yahoo Finance."""
    try:
        t = yf.Ticker(symbol)
        data = t.history(period="1y")
        if len(data) < 200:
            return None
        close = data["Close"]
        price = float(close.iloc[-1])
        ema50 = float(close.ewm(span=50).mean().iloc[-1])
        sma200 = float(close.rolling(200).mean().iloc[-1])
        ema21 = float(close.ewm(span=21).mean().iloc[-1])
        rsi_delta = close.diff()
        gain = rsi_delta.where(rsi_delta > 0, 0).rolling(14).mean()
        loss = (-rsi_delta.where(rsi_delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])
        momentum = (price - sma200) / sma200 * 100
        return {
            "price": price, "ema50": ema50, "sma200": sma200,
            "ema21": ema21, "rsi": rsi, "momentum": momentum,
        }
    except:
        return None


def check_entry(symbol):
    """Check if energy stock has golden cross entry signal."""
    tech = get_technicals(symbol)
    if not tech:
        return False, "No data", None

    if tech["ema50"] <= tech["sma200"]:
        return False, f"No golden cross (EMA50 ${tech['ema50']:.2f} < SMA200 ${tech['sma200']:.2f})", tech

    if tech["rsi"] > 75:
        return False, f"Overbought RSI {tech['rsi']:.1f}", tech

    if tech["price"] < tech["ema21"]:
        return False, f"Below EMA21", tech

    score = 0
    score += 2 if tech["ema50"] > tech["sma200"] else 0
    score += 1 if tech["rsi"] < 65 else 0
    score += 1 if tech["momentum"] > 5 else 0
    score += 1 if tech["price"] > tech["ema21"] else 0

    if score < MIN_SCORE:
        return False, f"Score {score} < {MIN_SCORE}", tech

    return True, f"Golden cross, score {score}, momentum +{tech['momentum']:.1f}%", tech


def find_option_contract(ib, symbol, price):
    """Find a suitable call option: 45-60 DTE, slightly OTM."""
    stock = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(stock)

    # Get option chains
    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    if not chains:
        log(f"  No option chains for {symbol}")
        return None, None

    # Find SMART exchange chain (or first available)
    chain = None
    for c in chains:
        if c.exchange == "SMART":
            chain = c
            break
    if not chain:
        chain = chains[0]

    # Find expiration 45-75 DTE
    today = datetime.now().date()
    target_min = today + timedelta(days=TARGET_DTE_MIN)
    target_max = today + timedelta(days=TARGET_DTE_MAX)

    valid_exps = []
    for exp in sorted(chain.expirations):
        exp_date = datetime.strptime(exp, "%Y%m%d").date()
        if target_min <= exp_date <= target_max:
            valid_exps.append(exp)

    if not valid_exps:
        # Fallback: nearest expiration after target_min
        for exp in sorted(chain.expirations):
            exp_date = datetime.strptime(exp, "%Y%m%d").date()
            if exp_date >= target_min:
                valid_exps.append(exp)
                break

    if not valid_exps:
        log(f"  No suitable expiration for {symbol}")
        return None, None

    expiry = valid_exps[0]
    dte = (datetime.strptime(expiry, "%Y%m%d").date() - today).days

    # Find strike: slightly OTM (2% above current price)
    target_strike = price * (1 + STRIKE_OFFSET)
    strikes = sorted(chain.strikes)
    best_strike = min(strikes, key=lambda s: abs(s - target_strike))

    contract = Option(symbol, expiry, best_strike, "C", "SMART")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        log(f"  Could not qualify option {symbol} {expiry} {best_strike}C")
        return None, None

    log(f"  Found option: {symbol} {expiry} ${best_strike}C ({dte} DTE)")
    return contract, {"expiry": expiry, "strike": best_strike, "dte": dte}


def execute_entry(symbol, tech):
    """Buy call option on golden cross signal."""
    ib = connect()

    price = tech["price"]

    # Find option contract
    contract, opt_info = find_option_contract(ib, symbol, price)
    if not contract:
        log(f"  No suitable option found for {symbol}")
        ib.disconnect()
        return None

    # Get option price
    ib.reqMarketDataType(3)
    ticker = ib.reqMktData(contract, "", False, False)
    ib.sleep(3)

    opt_price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
    if not opt_price or opt_price <= 0:
        opt_price = ticker.modelGreeks.optPrice if ticker.modelGreeks else None
    if not opt_price or opt_price <= 0:
        log(f"  Cannot get option price for {symbol}")
        ib.cancelMktData(contract)
        ib.disconnect()
        return None

    # Calculate quantity (each contract = 100 shares)
    contract_cost = opt_price * 100
    qty = max(1, int(POSITION_SIZE / contract_cost))

    log(f"ENTERING {symbol}: {qty} contracts {opt_info['expiry']} ${opt_info['strike']}C "
        f"@ ${opt_price:.2f} (${qty * contract_cost:,.0f})")

    order = MarketOrder("BUY", qty)
    order.tif = "GTC"
    trade = ib.placeOrder(contract, order)

    for i in range(30):
        ib.sleep(1)
        if trade.orderStatus.status == "Filled":
            break

    fill = trade.orderStatus.avgFillPrice
    status = trade.orderStatus.status

    if status != "Filled":
        log(f"  ENTRY FAILED: {status}")
        ib.cancelMktData(contract)
        ib.disconnect()
        return None

    log(f"  FILLED: {qty}x {symbol} {opt_info['expiry']} ${opt_info['strike']}C @ ${fill:.2f}")

    position = {
        "system": "energy_momentum",
        "symbol": symbol,
        "type": "CALL",
        "qty": qty,
        "strike": opt_info["strike"],
        "expiry": opt_info["expiry"],
        "dte_at_entry": opt_info["dte"],
        "entry_price": fill,
        "entry_date": datetime.now().isoformat(),
        "entry_value": fill * 100 * qty,
        "underlying_price": price,
        "technicals": tech,
        "profit_target": round(fill * (1 + PROFIT_TARGET), 2),
        "loss_stop": round(fill * (1 + LOSS_STOP), 2),
        "status": "open",
        "original_qty": qty,
        "profit_take_50": False,
        "profit_take_100": False,
    }

    positions = load_positions()
    positions.append(position)
    save_positions(positions)

    # Constitution v44.0 — MANDATORY trailing stop at entry
    from stop_utils import place_trailing_stop
    stop_result = place_trailing_stop(ib, contract, qty, fill, "energy_momentum", log)
    position["trailing_stop"] = stop_result

    ib.cancelMktData(contract)

    accountant.record_trade({
        "system": "energy_momentum",
        "ticker": symbol,
        "action": "BUY",
        "qty": qty,
        "fill_price": fill,
        "order_type": "market",
        "option": f"{opt_info['expiry']} ${opt_info['strike']}C",
        "commission": 0,
    })

    telegram.send(
        f"⚡ *Energy Momentum CALL — {symbol}*\n\n"
        f"BUY {qty}x {opt_info['expiry']} ${opt_info['strike']}C @ ${fill:.2f}\n"
        f"Cost: ${fill * 100 * qty:,.0f} | DTE: {opt_info['dte']}\n"
        f"Signal: EMA50 {tech['ema50']:.2f} > SMA200 {tech['sma200']:.2f}\n"
        f"RSI: {tech['rsi']:.1f} | Momentum: +{tech['momentum']:.1f}%\n\n"
        f"Targets: +50% (${position['profit_target']:.2f}) / -50% (${position['loss_stop']:.2f})"
    )

    ib.disconnect()
    return position


def scan_and_enter():
    """Scan universe and enter top candidates."""
    positions = load_positions()
    open_positions = [p for p in positions if p["status"] == "open"]
    open_symbols = [p["symbol"] for p in open_positions]

    if len(open_positions) >= MAX_POSITIONS:
        log(f"At max positions ({len(open_positions)}/{MAX_POSITIONS})")
        return []

    slots = MAX_POSITIONS - len(open_positions)
    candidates = []

    for symbol in UNIVERSE:
        if symbol in open_symbols:
            continue
        signal, reason, tech = check_entry(symbol)
        if signal and tech:
            candidates.append((symbol, tech["momentum"], reason, tech))
            log(f"  SIGNAL: {symbol} — {reason}")
        else:
            log(f"  No signal: {symbol} — {reason}")

    candidates.sort(key=lambda x: x[1], reverse=True)
    entered = []

    for symbol, momentum, reason, tech in candidates[:slots]:
        pos = execute_entry(symbol, tech)
        if pos:
            entered.append(pos)

    return entered


def check_exits():
    """Check if options positions should be closed (profit/loss/time)."""
    positions = load_positions()
    open_positions = [p for p in positions if p["status"] == "open"]

    if not open_positions:
        return

    ib = connect(client_id=MONITOR_CLIENT_ID)

    for pos in open_positions:
        symbol = pos["symbol"]
        expiry = pos["expiry"]
        strike = pos["strike"]

        contract = Option(symbol, expiry, strike, "C", "SMART")
        try:
            ib.qualifyContracts(contract)
        except:
            continue

        ticker = ib.reqMktData(contract, "", False, False)
        ib.sleep(3)

        current = ticker.last if ticker.last and ticker.last > 0 else ticker.close
        if not current or current <= 0:
            ib.cancelMktData(contract)
            continue

        entry = pos["entry_price"]
        pnl_pct = (current - entry) / entry

        # Check DTE
        today = datetime.now().date()
        exp_date = datetime.strptime(expiry, "%Y%m%d").date()
        dte_remaining = (exp_date - today).days

        # ── Tiered Profit-Taking (partial sells) ──
        original_qty = pos.get("original_qty", pos["qty"])

        # Tier 1: +50% gain → sell 33%
        if pnl_pct >= 0.50 and not pos.get("profit_take_50"):
            sell_qty = max(1, int(original_qty * 0.33))
            if sell_qty > 0 and pos["qty"] > sell_qty:
                log(f"PROFIT TAKE 50%: {symbol} — selling {sell_qty} of {pos['qty']} contracts (+{pnl_pct*100:.0f}%)")
                pt_order = MarketOrder("SELL", sell_qty)
                pt_order.tif = "GTC"
                pt_trade = ib.placeOrder(contract, pt_order)
                for _ in range(15):
                    ib.sleep(1)
                    if pt_trade.orderStatus.status == "Filled":
                        break
                pt_fill = pt_trade.orderStatus.avgFillPrice
                pt_pnl = (pt_fill - entry) * 100 * sell_qty
                pos["profit_take_50"] = True
                pos["qty"] -= sell_qty
                accountant.record_trade({
                    "system": "energy_momentum",
                    "ticker": symbol,
                    "action": "SELL",
                    "qty": sell_qty,
                    "fill_price": pt_fill,
                    "pnl": pt_pnl,
                    "option": f"{expiry} ${strike}C",
                    "commission": 0,
                    "note": "profit_take_50pct",
                })
                telegram.send(
                    f"💰 *Profit Take +50% — {symbol} {expiry} ${strike}C*\n\n"
                    f"SELL {sell_qty}x @ ${pt_fill:.2f} (of {original_qty} original)\n"
                    f"P&L on partial: ${pt_pnl:+,.2f} (+{pnl_pct*100:.0f}%)\n"
                    f"Remaining: {pos['qty']} contracts riding with trailing stop"
                )

        # Tier 2: +100% gain → sell 33% more
        if pnl_pct >= 1.00 and not pos.get("profit_take_100"):
            sell_qty = max(1, int(original_qty * 0.33))
            if sell_qty > 0 and pos["qty"] > sell_qty:
                log(f"PROFIT TAKE 100%: {symbol} — selling {sell_qty} of {pos['qty']} contracts (+{pnl_pct*100:.0f}%)")
                pt_order = MarketOrder("SELL", sell_qty)
                pt_order.tif = "GTC"
                pt_trade = ib.placeOrder(contract, pt_order)
                for _ in range(15):
                    ib.sleep(1)
                    if pt_trade.orderStatus.status == "Filled":
                        break
                pt_fill = pt_trade.orderStatus.avgFillPrice
                pt_pnl = (pt_fill - entry) * 100 * sell_qty
                pos["profit_take_100"] = True
                pos["qty"] -= sell_qty
                accountant.record_trade({
                    "system": "energy_momentum",
                    "ticker": symbol,
                    "action": "SELL",
                    "qty": sell_qty,
                    "fill_price": pt_fill,
                    "pnl": pt_pnl,
                    "option": f"{expiry} ${strike}C",
                    "commission": 0,
                    "note": "profit_take_100pct",
                })
                telegram.send(
                    f"💰💰 *Profit Take +100% — {symbol} {expiry} ${strike}C*\n\n"
                    f"SELL {sell_qty}x @ ${pt_fill:.2f} (of {original_qty} original)\n"
                    f"P&L on partial: ${pt_pnl:+,.2f} (+{pnl_pct*100:.0f}%)\n"
                    f"Remaining: {pos['qty']} contracts — letting winners ride!"
                )

        # ── Full Exit Logic (safety net) ──
        exit_reason = None
        if pnl_pct >= PROFIT_TARGET:
            exit_reason = f"Profit target hit (+{pnl_pct*100:.0f}%)"
        elif pnl_pct <= LOSS_STOP:
            exit_reason = f"Stop loss hit ({pnl_pct*100:.0f}%)"
        elif dte_remaining <= DTE_EXIT:
            exit_reason = f"Time exit ({dte_remaining} DTE remaining)"
        else:
            # Also check death cross
            tech = get_technicals(symbol)
            if tech and tech["ema50"] < tech["sma200"]:
                exit_reason = "Death cross (EMA50 < SMA200)"

        if exit_reason:
            log(f"EXIT: {symbol} {expiry} ${strike}C — {exit_reason}")

            order = MarketOrder("SELL", pos["qty"])
            order.tif = "GTC"
            trade = ib.placeOrder(contract, order)

            for i in range(15):
                ib.sleep(1)
                if trade.orderStatus.status == "Filled":
                    break

            fill = trade.orderStatus.avgFillPrice
            pnl = (fill - entry) * 100 * pos["qty"]

            pos["status"] = "closed"
            pos["exit_price"] = fill
            pos["exit_date"] = datetime.now().isoformat()
            pos["pnl"] = pnl
            pos["exit_reason"] = exit_reason

            accountant.record_trade({
                "system": "energy_momentum",
                "ticker": symbol,
                "action": "SELL",
                "qty": pos["qty"],
                "fill_price": fill,
                "pnl": pnl,
                "option": f"{expiry} ${strike}C",
                "commission": 0,
            })

            emoji = "🟢" if pnl >= 0 else "🔴"
            telegram.send(
                f"{emoji} *Energy Exit — {symbol} {expiry} ${strike}C*\n\n"
                f"SELL {pos['qty']}x @ ${fill:.2f}\n"
                f"Entry: ${entry:.2f} | P&L: ${pnl:+,.2f}\n"
                f"Reason: {exit_reason}"
            )

        ib.cancelMktData(contract)

    save_positions(positions)
    ib.disconnect()


if __name__ == "__main__":
    log("Trader3 — Energy Momentum OPTIONS Engine")
    log(f"Universe: {', '.join(UNIVERSE)}")
    log(f"Capital: ${CAPITAL:,} | Max positions: {MAX_POSITIONS} | ~${POSITION_SIZE}/position")
    log("Scanning...")
    scan_and_enter()
