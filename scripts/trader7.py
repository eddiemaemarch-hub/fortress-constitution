"""Trader7 — SpaceX IPO Options Engine
Strategy: Pre-IPO proxy plays (CALLS + PUTS) + Post-IPO direct SpaceX options.
Pre-IPO Universe: RKLB, ASTS, BKSY, LUNR, MNTS, GOOGL, LMT, NOC, RTX
Post-IPO: Direct SpaceX options once listed.
Exit: 50% profit target, 30% loss stop, or 21 DTE (whichever first).
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
POSITIONS_FILE = os.path.join(DATA_DIR, "trader7_positions.json")
IPO_STATUS_FILE = os.path.join(DATA_DIR, "spacex_ipo_status.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

PORT = deployer.get_port(7)
CLIENT_ID = 70
MONITOR_CLIENT_ID = 71

# SpaceX IPO parameters
PRE_IPO_UNIVERSE = ["RKLB", "ASTS", "BKSY", "LUNR", "MNTS", "GOOGL", "LMT", "NOC", "RTX"]
POST_IPO_TICKER = "SPACEX"  # placeholder — update when actual ticker is known
CAPITAL_PRE = 10000  # $10k pre-IPO proxy plays
CAPITAL_POST = 25000  # $25k post-IPO direct options
MAX_POSITIONS_PRE = 4
MAX_POSITIONS_POST = 3
POSITION_SIZE = 500  # ~$500 per options position (leveraged)
MIN_SCORE = 3.0

# Options parameters
TARGET_DTE_MIN = 45
TARGET_DTE_MAX = 90
STRIKE_OFFSET = 0.02  # 2% OTM
PROFIT_TARGET = 0.50  # Close at +50%
LOSS_STOP = -0.30  # Close at -30%
DTE_EXIT = 21


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Trader7 {ts}] {msg}")
    with open(f"{LOG_DIR}/trader7.log", "a") as f:
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


def get_ipo_mode():
    """Check current IPO mode from status file."""
    if os.path.exists(IPO_STATUS_FILE):
        with open(IPO_STATUS_FILE) as f:
            status = json.load(f)
        return status.get("mode", "PRE_IPO")
    return "PRE_IPO"


def check_ipo_status():
    """Check if SpaceX has IPO'd and update mode accordingly."""
    mode = get_ipo_mode()
    if mode == "POST_IPO":
        log(f"IPO Mode: POST_IPO (ticker: {POST_IPO_TICKER})")
        return mode

    # Try to see if SpaceX ticker exists on IBKR
    try:
        ib = connect()
        stock = Stock(POST_IPO_TICKER, "SMART", "USD")
        qualified = ib.qualifyContracts(stock)
        ib.disconnect()
        if qualified:
            log("SpaceX ticker found on IBKR — switching to POST_IPO mode!")
            status = {
                "mode": "POST_IPO",
                "detected_date": datetime.now().isoformat(),
                "ticker": POST_IPO_TICKER,
            }
            with open(IPO_STATUS_FILE, "w") as f:
                json.dump(status, f, indent=2)
            telegram.send(
                "🚀 *SPACEX IPO DETECTED*\n\n"
                f"Ticker {POST_IPO_TICKER} is now live on IBKR!\n"
                f"Switching to POST_IPO mode. $25k budget activated."
            )
            return "POST_IPO"
    except Exception:
        pass

    log(f"IPO Mode: PRE_IPO (scanning proxies)")
    return "PRE_IPO"


def get_technicals(symbol):
    """Get momentum technicals from Yahoo Finance."""
    try:
        t = yf.Ticker(symbol)
        data = t.history(period="1y")
        if len(data) < 50:
            return None
        close = data["Close"]
        volume = data["Volume"]
        price = float(close.iloc[-1])
        ema20 = float(close.ewm(span=20).mean().iloc[-1])
        ema50 = float(close.ewm(span=50).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1])
        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        macd = float(macd_line.iloc[-1])
        macd_signal = float(signal_line.iloc[-1])
        macd_prev = float(macd_line.iloc[-2])
        signal_prev = float(signal_line.iloc[-2])
        # RSI
        rsi_delta = close.diff()
        gain = rsi_delta.where(rsi_delta > 0, 0).rolling(14).mean()
        loss = (-rsi_delta.where(rsi_delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])
        # Volume
        vol_avg = float(volume.rolling(20).mean().iloc[-1])
        vol_current = float(volume.iloc[-1])
        return {
            "price": price, "ema20": ema20, "ema50": ema50, "sma50": sma50,
            "macd": macd, "macd_signal": macd_signal,
            "macd_prev": macd_prev, "signal_prev": signal_prev,
            "rsi": rsi, "vol_avg": vol_avg, "vol_current": vol_current,
        }
    except Exception:
        return None


def score_bullish(tech):
    """Score bullish setup for CALL entry."""
    score = 0
    reasons = []
    if tech["ema20"] > tech["ema50"]:
        score += 2
        reasons.append("EMA20 > EMA50")
    if tech["macd"] > tech["macd_signal"] and tech["macd_prev"] <= tech["signal_prev"]:
        score += 1
        reasons.append("MACD bullish crossover")
    if tech["rsi"] < 30:
        score += 1
        reasons.append(f"RSI oversold ({tech['rsi']:.0f})")
    if tech["price"] > tech["sma50"]:
        score += 1
        reasons.append("Price > SMA50")
    if tech["vol_current"] > tech["vol_avg"] * 2:
        score += 1
        reasons.append("Volume spike >2x")
    return score, reasons


def score_bearish(tech):
    """Score bearish setup for PUT entry."""
    score = 0
    reasons = []
    if tech["ema20"] < tech["ema50"]:
        score += 2
        reasons.append("EMA20 < EMA50 (death cross)")
    if tech["macd"] < tech["macd_signal"] and tech["macd_prev"] >= tech["signal_prev"]:
        score += 1
        reasons.append("MACD bearish crossover")
    if tech["rsi"] > 70:
        score += 1
        reasons.append(f"RSI overbought ({tech['rsi']:.0f})")
    if tech["price"] < tech["sma50"]:
        score += 1
        reasons.append("Price < SMA50")
    if tech["vol_current"] > tech["vol_avg"] * 2:
        score += 1
        reasons.append("Volume spike >2x")
    return score, reasons


def find_option_contract(ib, symbol, price, direction="C"):
    """Find a suitable option: 45-90 DTE, slightly OTM."""
    stock = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(stock)

    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    if not chains:
        log(f"  No option chains for {symbol}")
        return None, None

    chain = None
    for c in chains:
        if c.exchange == "SMART":
            chain = c
            break
    if not chain:
        chain = chains[0]

    today = datetime.now().date()
    target_min = today + timedelta(days=TARGET_DTE_MIN)
    target_max = today + timedelta(days=TARGET_DTE_MAX)

    valid_exps = []
    for exp in sorted(chain.expirations):
        exp_date = datetime.strptime(exp, "%Y%m%d").date()
        if target_min <= exp_date <= target_max:
            valid_exps.append(exp)

    if not valid_exps:
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

    if direction == "C":
        target_strike = price * (1 + STRIKE_OFFSET)
    else:
        target_strike = price * (1 - STRIKE_OFFSET)

    strikes = sorted(chain.strikes)
    best_strike = min(strikes, key=lambda s: abs(s - target_strike))

    contract = Option(symbol, expiry, best_strike, direction, "SMART")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        log(f"  Could not qualify option {symbol} {expiry} {best_strike}{direction}")
        return None, None

    log(f"  Found option: {symbol} {expiry} ${best_strike}{direction} ({dte} DTE)")
    return contract, {"expiry": expiry, "strike": best_strike, "dte": dte}


def execute_entry(symbol, tech, direction="C"):
    """Buy call or put option on signal."""
    ib = connect()
    price = tech["price"]

    contract, opt_info = find_option_contract(ib, symbol, price, direction)
    if not contract:
        log(f"  No suitable option found for {symbol}")
        ib.disconnect()
        return None

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

    contract_cost = opt_price * 100
    qty = max(1, int(POSITION_SIZE / contract_cost))
    opt_type = "CALL" if direction == "C" else "PUT"
    mode = get_ipo_mode()

    log(f"ENTERING {symbol}: {qty} contracts {opt_info['expiry']} ${opt_info['strike']}{direction} "
        f"@ ${opt_price:.2f} (${qty * contract_cost:,.0f}) [{mode}]")

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

    log(f"  FILLED: {qty}x {symbol} {opt_info['expiry']} ${opt_info['strike']}{direction} @ ${fill:.2f}")

    position = {
        "system": "spacex_ipo",
        "mode": mode,
        "symbol": symbol,
        "type": opt_type,
        "direction": direction,
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
    stop_result = place_trailing_stop(ib, contract, qty, fill, "spacex_ipo", log)
    position["trailing_stop"] = stop_result

    ib.cancelMktData(contract)

    accountant.record_trade({
        "system": "spacex_ipo",
        "ticker": symbol,
        "action": "BUY",
        "qty": qty,
        "fill_price": fill,
        "order_type": "market",
        "option": f"{opt_info['expiry']} ${opt_info['strike']}{direction}",
        "commission": 0,
    })

    emoji = "🚀" if direction == "C" else "🔻"
    telegram.send(
        f"{emoji} *SpaceX {opt_type} — {symbol}* [{mode}]\n\n"
        f"BUY {qty}x {opt_info['expiry']} ${opt_info['strike']}{direction} @ ${fill:.2f}\n"
        f"Cost: ${fill * 100 * qty:,.0f} | DTE: {opt_info['dte']}\n"
        f"Targets: +50% (${position['profit_target']:.2f}) / -30% (${position['loss_stop']:.2f})"
    )

    ib.disconnect()
    return position


def scan_and_enter():
    """Scan universe for both bullish (CALL) and bearish (PUT) setups."""
    mode = get_ipo_mode()
    universe = [POST_IPO_TICKER] if mode == "POST_IPO" else PRE_IPO_UNIVERSE
    max_pos = MAX_POSITIONS_POST if mode == "POST_IPO" else MAX_POSITIONS_PRE

    positions = load_positions()
    open_positions = [p for p in positions if p["status"] == "open"]
    open_symbols = [(p["symbol"], p.get("direction", "C")) for p in open_positions]

    if len(open_positions) >= max_pos:
        log(f"At max positions ({len(open_positions)}/{max_pos}) [{mode}]")
        return []

    slots = max_pos - len(open_positions)
    candidates = []

    for symbol in universe:
        tech = get_technicals(symbol)
        if not tech:
            log(f"  No data: {symbol}")
            continue

        # Check bullish (CALL)
        if (symbol, "C") not in open_symbols:
            bull_score, bull_reasons = score_bullish(tech)
            if bull_score >= MIN_SCORE:
                candidates.append((symbol, "C", bull_score, ", ".join(bull_reasons), tech))
                log(f"  BULL SIGNAL: {symbol} — score {bull_score} — {', '.join(bull_reasons)}")

        # Check bearish (PUT)
        if (symbol, "P") not in open_symbols:
            bear_score, bear_reasons = score_bearish(tech)
            if bear_score >= MIN_SCORE:
                candidates.append((symbol, "P", bear_score, ", ".join(bear_reasons), tech))
                log(f"  BEAR SIGNAL: {symbol} — score {bear_score} — {', '.join(bear_reasons)}")

        if not any(c[0] == symbol for c in candidates):
            log(f"  No signal: {symbol}")

    candidates.sort(key=lambda x: x[2], reverse=True)
    entered = []

    for symbol, direction, score, reason, tech in candidates[:slots]:
        pos = execute_entry(symbol, tech, direction)
        if pos:
            entered.append(pos)

    return entered


def check_exits():
    """Check if options positions should be closed (profit/loss/time/reversal)."""
    positions = load_positions()
    open_positions = [p for p in positions if p["status"] == "open"]

    if not open_positions:
        return

    ib = connect(client_id=MONITOR_CLIENT_ID)

    for pos in open_positions:
        symbol = pos["symbol"]
        expiry = pos["expiry"]
        strike = pos["strike"]
        direction = pos.get("direction", "C")

        contract = Option(symbol, expiry, strike, direction, "SMART")
        try:
            ib.qualifyContracts(contract)
        except Exception:
            continue

        ticker = ib.reqMktData(contract, "", False, False)
        ib.sleep(3)

        current = ticker.last if ticker.last and ticker.last > 0 else ticker.close
        if not current or current <= 0:
            ib.cancelMktData(contract)
            continue

        entry = pos["entry_price"]
        pnl_pct = (current - entry) / entry

        today = datetime.now().date()
        exp_date = datetime.strptime(expiry, "%Y%m%d").date()
        dte_remaining = (exp_date - today).days

        # ── Tiered Profit-Taking (partial sells) ──
        original_qty = pos.get("original_qty", pos["qty"])
        opt_label = f"{expiry} ${strike}{direction}"

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
                    "system": "spacex_ipo",
                    "ticker": symbol,
                    "action": "SELL",
                    "qty": sell_qty,
                    "fill_price": pt_fill,
                    "pnl": pt_pnl,
                    "option": opt_label,
                    "commission": 0,
                    "note": "profit_take_50pct",
                })
                telegram.send(
                    f"💰 *Profit Take +50% — {symbol} {opt_label}*\n\n"
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
                    "system": "spacex_ipo",
                    "ticker": symbol,
                    "action": "SELL",
                    "qty": sell_qty,
                    "fill_price": pt_fill,
                    "pnl": pt_pnl,
                    "option": opt_label,
                    "commission": 0,
                    "note": "profit_take_100pct",
                })
                telegram.send(
                    f"💰💰 *Profit Take +100% — {symbol} {opt_label}*\n\n"
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
            tech = get_technicals(symbol)
            if tech:
                if direction == "C" and tech["ema20"] < tech["ema50"]:
                    exit_reason = "EMA20 < EMA50 reversal (close CALL)"
                elif direction == "P" and tech["ema20"] > tech["ema50"]:
                    exit_reason = "EMA20 > EMA50 reversal (close PUT)"

        if exit_reason:
            opt_type = "CALL" if direction == "C" else "PUT"
            log(f"EXIT: {symbol} {expiry} ${strike}{direction} — {exit_reason}")

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
                "system": "spacex_ipo",
                "ticker": symbol,
                "action": "SELL",
                "qty": pos["qty"],
                "fill_price": fill,
                "pnl": pnl,
                "option": f"{expiry} ${strike}{direction}",
                "commission": 0,
            })

            emoji = "🟢" if pnl >= 0 else "🔴"
            telegram.send(
                f"{emoji} *SpaceX Exit — {symbol} {expiry} ${strike}{direction}*\n\n"
                f"SELL {pos['qty']}x @ ${fill:.2f}\n"
                f"Entry: ${entry:.2f} | P&L: ${pnl:+,.2f}\n"
                f"Reason: {exit_reason}"
            )

        ib.cancelMktData(contract)

    save_positions(positions)
    ib.disconnect()


if __name__ == "__main__":
    mode = get_ipo_mode()
    log(f"Trader7 — SpaceX IPO OPTIONS Engine (Calls + Puts) [{mode}]")
    if mode == "PRE_IPO":
        log(f"Pre-IPO Universe: {', '.join(PRE_IPO_UNIVERSE)}")
        log(f"Capital: ${CAPITAL_PRE:,} | Max positions: {MAX_POSITIONS_PRE} | ~${POSITION_SIZE}/position")
    else:
        log(f"Post-IPO Ticker: {POST_IPO_TICKER}")
        log(f"Capital: ${CAPITAL_POST:,} | Max positions: {MAX_POSITIONS_POST}")
    log("Scanning...")
    check_ipo_status()
    scan_and_enter()
