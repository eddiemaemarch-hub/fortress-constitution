"""Trader8 — 10X Moonshot Options Engine
Strategy: Hunt for multi-bagger stocks. Calls on breakout momentum, puts on breakdown.
Focus on high-growth sectors: eVTOL, Quantum, Nuclear/SMR, Space, Biotech/Genomics.
Small position sizes, wide stops, letting winners run for massive upside.
Exit: +150% profit target (let it run), -50% loss stop, or 14 DTE.
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
POSITIONS_FILE = os.path.join(DATA_DIR, "trader8_positions.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

PORT = deployer.get_port(8)
CLIENT_ID = 80
MONITOR_CLIENT_ID = 81

# 10X Moonshot universe by sector
UNIVERSE = {
    "eVTOL": ["JOBY", "ACHR", "LILM"],
    "quantum": ["IONQ", "RGTI", "QUBT"],
    "nuclear": ["SMR", "OKLO"],
    "space": ["RKLB", "LUNR", "ASTS"],
    "biotech": ["DNA", "CRSP", "BEAM"],
    "AI_smallcap": ["BBAI", "SOUN", "BFLY"],
}
ALL_TICKERS = [t for tickers in UNIVERSE.values() for t in tickers]

CAPITAL = 10000  # $10k allocation — high risk, small bets
MAX_POSITIONS = 6
POSITION_SIZE = 300  # ~$300 per position — lottery ticket sizing
MIN_SCORE = 3.0

# Options parameters — longer DTE, wider targets for moonshots
TARGET_DTE_MIN = 60   # Minimum days to expiration
TARGET_DTE_MAX = 120  # Maximum days to expiration (give it time)
STRIKE_OFFSET = 0.05  # 5% OTM (cheaper premium, more leverage)
PROFIT_TARGET = 1.50  # Close at +150% (let winners run big)
LOSS_STOP = -0.50     # Close at -50%
DTE_EXIT = 14         # Close if less than 14 DTE remaining

# Trail stop: once up +80%, trail at 40% from peak
TRAIL_ACTIVATE = 0.80
TRAIL_PERCENT = 0.40


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Trader8 {ts}] {msg}")
    with open(f"{LOG_DIR}/trader8.log", "a") as f:
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


def get_sector(symbol):
    """Get which sector a ticker belongs to."""
    for sector, tickers in UNIVERSE.items():
        if symbol in tickers:
            return sector
    return "unknown"


def get_technicals(symbol):
    """Get momentum technicals. Only needs 50 days for these growth stocks."""
    try:
        t = yf.Ticker(symbol)
        data = t.history(period="1y")
        if len(data) < 50:
            return None
        close = data["Close"]
        volume = data["Volume"]
        price = float(close.iloc[-1])
        ema10 = float(close.ewm(span=10).mean().iloc[-1])
        ema21 = float(close.ewm(span=21).mean().iloc[-1])
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
        loss_s = (-rsi_delta.where(rsi_delta < 0, 0)).rolling(14).mean()
        rs = gain / loss_s
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])
        # Volume
        vol_avg = float(volume.rolling(20).mean().iloc[-1])
        vol_current = float(volume.iloc[-1])
        # 52-week high/low
        high_52w = float(close.max())
        low_52w = float(close.min())
        pct_from_high = (price - high_52w) / high_52w * 100
        pct_from_low = (price - low_52w) / low_52w * 100
        # Momentum: 1-month and 3-month returns
        mom_1m = (price / float(close.iloc[-21]) - 1) * 100 if len(close) >= 21 else 0
        mom_3m = (price / float(close.iloc[-63]) - 1) * 100 if len(close) >= 63 else 0
        return {
            "price": price, "ema10": ema10, "ema21": ema21, "ema50": ema50,
            "sma50": sma50,
            "macd": macd, "macd_signal": macd_signal,
            "macd_prev": macd_prev, "signal_prev": signal_prev,
            "rsi": rsi, "vol_avg": vol_avg, "vol_current": vol_current,
            "high_52w": high_52w, "low_52w": low_52w,
            "pct_from_high": pct_from_high, "pct_from_low": pct_from_low,
            "mom_1m": mom_1m, "mom_3m": mom_3m,
        }
    except Exception:
        return None


def score_bullish(tech):
    """Score bullish setup for CALL entry — optimized for breakout momentum."""
    score = 0
    reasons = []
    # EMA stack aligned (10 > 21 > 50 = strong uptrend)
    if tech["ema10"] > tech["ema21"] > tech["ema50"]:
        score += 2
        reasons.append("EMA stack aligned (10>21>50)")
    elif tech["ema10"] > tech["ema21"]:
        score += 1
        reasons.append("EMA10 > EMA21")
    # MACD bullish crossover
    if tech["macd"] > tech["macd_signal"] and tech["macd_prev"] <= tech["signal_prev"]:
        score += 1.5
        reasons.append("MACD bullish crossover")
    # RSI rising from oversold (best entry for moonshots)
    if 30 < tech["rsi"] < 50:
        score += 1
        reasons.append(f"RSI recovering ({tech['rsi']:.0f})")
    elif tech["rsi"] < 30:
        score += 0.5
        reasons.append(f"RSI oversold ({tech['rsi']:.0f})")
    # Volume explosion (2x+ average = institutional interest)
    if tech["vol_current"] > tech["vol_avg"] * 3:
        score += 1.5
        reasons.append(f"Volume explosion ({tech['vol_current']/tech['vol_avg']:.1f}x)")
    elif tech["vol_current"] > tech["vol_avg"] * 2:
        score += 1
        reasons.append(f"Volume spike ({tech['vol_current']/tech['vol_avg']:.1f}x)")
    # Price momentum (up >20% in 1 month = breakout)
    if tech["mom_1m"] > 20:
        score += 1
        reasons.append(f"1M momentum +{tech['mom_1m']:.0f}%")
    # Near 52-week low (contrarian value play)
    if tech["pct_from_low"] < 30:
        score += 0.5
        reasons.append(f"Near 52w low (+{tech['pct_from_low']:.0f}%)")
    return score, reasons


def score_bearish(tech):
    """Score bearish setup for PUT entry."""
    score = 0
    reasons = []
    if tech["ema10"] < tech["ema21"] < tech["ema50"]:
        score += 2
        reasons.append("EMA stack bearish (10<21<50)")
    elif tech["ema10"] < tech["ema21"]:
        score += 1
        reasons.append("EMA10 < EMA21")
    if tech["macd"] < tech["macd_signal"] and tech["macd_prev"] >= tech["signal_prev"]:
        score += 1.5
        reasons.append("MACD bearish crossover")
    if tech["rsi"] > 75:
        score += 1
        reasons.append(f"RSI overbought ({tech['rsi']:.0f})")
    if tech["vol_current"] > tech["vol_avg"] * 2:
        score += 1
        reasons.append(f"Volume spike on selloff ({tech['vol_current']/tech['vol_avg']:.1f}x)")
    if tech["mom_1m"] < -20:
        score += 1
        reasons.append(f"1M momentum {tech['mom_1m']:.0f}%")
    return score, reasons


def find_option_contract(ib, symbol, price, direction="C"):
    """Find option: 60-120 DTE, 5% OTM for max leverage."""
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
    sector = get_sector(symbol)

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

    log(f"ENTERING {symbol} [{sector}]: {qty}x {opt_info['expiry']} ${opt_info['strike']}{direction} "
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

    log(f"  FILLED: {qty}x {symbol} {opt_info['expiry']} ${opt_info['strike']}{direction} @ ${fill:.2f}")

    position = {
        "system": "10x_moonshot",
        "symbol": symbol,
        "sector": sector,
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
        "peak_price": fill,
        "trailing_active": False,
        "status": "open",
        "original_qty": qty,
        "profit_take_100": False,
        "profit_take_300": False,
        "profit_take_500": False,
    }

    positions = load_positions()
    positions.append(position)
    save_positions(positions)

    # Constitution v44.0 — MANDATORY trailing stop at entry (40% for moonshots)
    from stop_utils import place_trailing_stop
    stop_result = place_trailing_stop(ib, contract, qty, fill, "10x_moonshot", log)
    position["trailing_stop"] = stop_result

    ib.cancelMktData(contract)

    accountant.record_trade({
        "system": "10x_moonshot",
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
        f"{emoji} *10X Moonshot {opt_type} — {symbol}* [{sector}]\n\n"
        f"BUY {qty}x {opt_info['expiry']} ${opt_info['strike']}{direction} @ ${fill:.2f}\n"
        f"Cost: ${fill * 100 * qty:,.0f} | DTE: {opt_info['dte']}\n"
        f"Targets: +150% (${position['profit_target']:.2f}) / -50% (${position['loss_stop']:.2f})\n"
        f"Trail: activates at +80%, trails 40% from peak"
    )

    ib.disconnect()
    return position


def scan_and_enter():
    """Scan 10X universe for breakout momentum."""
    positions = load_positions()
    open_positions = [p for p in positions if p["status"] == "open"]
    open_symbols = [(p["symbol"], p.get("direction", "C")) for p in open_positions]

    if len(open_positions) >= MAX_POSITIONS:
        log(f"At max positions ({len(open_positions)}/{MAX_POSITIONS})")
        return []

    slots = MAX_POSITIONS - len(open_positions)
    candidates = []

    for symbol in ALL_TICKERS:
        tech = get_technicals(symbol)
        if not tech:
            log(f"  No data: {symbol}")
            continue

        sector = get_sector(symbol)

        # Check bullish (CALL)
        if (symbol, "C") not in open_symbols:
            bull_score, bull_reasons = score_bullish(tech)
            if bull_score >= MIN_SCORE:
                candidates.append((symbol, "C", bull_score, ", ".join(bull_reasons), tech, sector))
                log(f"  BULL SIGNAL: {symbol} [{sector}] — score {bull_score} — {', '.join(bull_reasons)}")

        # Check bearish (PUT)
        if (symbol, "P") not in open_symbols:
            bear_score, bear_reasons = score_bearish(tech)
            if bear_score >= MIN_SCORE:
                candidates.append((symbol, "P", bear_score, ", ".join(bear_reasons), tech, sector))
                log(f"  BEAR SIGNAL: {symbol} [{sector}] — score {bear_score} — {', '.join(bear_reasons)}")

        if not any(c[0] == symbol for c in candidates):
            log(f"  No signal: {symbol} [{sector}]")

    # Sort by score, prefer diversity across sectors
    candidates.sort(key=lambda x: x[2], reverse=True)
    entered = []
    sectors_entered = set()

    for symbol, direction, score, reason, tech, sector in candidates:
        if len(entered) >= slots:
            break
        # Prefer sector diversity — skip if already entered same sector this cycle
        if sector in sectors_entered and len(candidates) > slots:
            continue
        pos = execute_entry(symbol, tech, direction)
        if pos:
            entered.append(pos)
            sectors_entered.add(sector)

    return entered


def check_exits():
    """Check exits with trailing stop logic for moonshots."""
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
        sector = pos.get("sector", "?")

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

        # Update peak price for trailing stop
        peak = pos.get("peak_price", entry)
        if current > peak:
            pos["peak_price"] = current
            peak = current

        # Check DTE
        today = datetime.now().date()
        exp_date = datetime.strptime(expiry, "%Y%m%d").date()
        dte_remaining = (exp_date - today).days

        # ── Tiered Profit-Taking (aggressive moonshot: 25% at each tier) ──
        original_qty = pos.get("original_qty", pos["qty"])
        opt_label = f"{expiry} ${strike}{direction}"

        # Tier 1: +100% gain → sell 25%
        if pnl_pct >= 1.00 and not pos.get("profit_take_100"):
            sell_qty = max(1, int(original_qty * 0.25))
            if sell_qty > 0 and pos["qty"] > sell_qty:
                log(f"PROFIT TAKE 100%: {symbol} [{sector}] — selling {sell_qty} of {pos['qty']} (+{pnl_pct*100:.0f}%)")
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
                    "system": "10x_moonshot",
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
                    f"💰 *Moonshot +100% — {symbol} [{sector}] {opt_label}*\n\n"
                    f"SELL {sell_qty}x @ ${pt_fill:.2f} (25% of {original_qty})\n"
                    f"P&L on partial: ${pt_pnl:+,.2f} (+{pnl_pct*100:.0f}%)\n"
                    f"Remaining: {pos['qty']} contracts — letting it run!"
                )

        # Tier 2: +300% gain → sell 25% more
        if pnl_pct >= 3.00 and not pos.get("profit_take_300"):
            sell_qty = max(1, int(original_qty * 0.25))
            if sell_qty > 0 and pos["qty"] > sell_qty:
                log(f"PROFIT TAKE 300%: {symbol} [{sector}] — selling {sell_qty} of {pos['qty']} (+{pnl_pct*100:.0f}%)")
                pt_order = MarketOrder("SELL", sell_qty)
                pt_order.tif = "GTC"
                pt_trade = ib.placeOrder(contract, pt_order)
                for _ in range(15):
                    ib.sleep(1)
                    if pt_trade.orderStatus.status == "Filled":
                        break
                pt_fill = pt_trade.orderStatus.avgFillPrice
                pt_pnl = (pt_fill - entry) * 100 * sell_qty
                pos["profit_take_300"] = True
                pos["qty"] -= sell_qty
                accountant.record_trade({
                    "system": "10x_moonshot",
                    "ticker": symbol,
                    "action": "SELL",
                    "qty": sell_qty,
                    "fill_price": pt_fill,
                    "pnl": pt_pnl,
                    "option": opt_label,
                    "commission": 0,
                    "note": "profit_take_300pct",
                })
                telegram.send(
                    f"💰💰 *Moonshot +300% — {symbol} [{sector}] {opt_label}*\n\n"
                    f"SELL {sell_qty}x @ ${pt_fill:.2f} (25% of {original_qty})\n"
                    f"P&L on partial: ${pt_pnl:+,.2f} (+{pnl_pct*100:.0f}%)\n"
                    f"Remaining: {pos['qty']} contracts — 🌙 moon territory!"
                )

        # Tier 3: +500% gain → sell 25% more
        if pnl_pct >= 5.00 and not pos.get("profit_take_500"):
            sell_qty = max(1, int(original_qty * 0.25))
            if sell_qty > 0 and pos["qty"] > sell_qty:
                log(f"PROFIT TAKE 500%: {symbol} [{sector}] — selling {sell_qty} of {pos['qty']} (+{pnl_pct*100:.0f}%)")
                pt_order = MarketOrder("SELL", sell_qty)
                pt_order.tif = "GTC"
                pt_trade = ib.placeOrder(contract, pt_order)
                for _ in range(15):
                    ib.sleep(1)
                    if pt_trade.orderStatus.status == "Filled":
                        break
                pt_fill = pt_trade.orderStatus.avgFillPrice
                pt_pnl = (pt_fill - entry) * 100 * sell_qty
                pos["profit_take_500"] = True
                pos["qty"] -= sell_qty
                accountant.record_trade({
                    "system": "10x_moonshot",
                    "ticker": symbol,
                    "action": "SELL",
                    "qty": sell_qty,
                    "fill_price": pt_fill,
                    "pnl": pt_pnl,
                    "option": opt_label,
                    "commission": 0,
                    "note": "profit_take_500pct",
                })
                telegram.send(
                    f"💰💰💰 *Moonshot +500% — {symbol} [{sector}] {opt_label}*\n\n"
                    f"SELL {sell_qty}x @ ${pt_fill:.2f} (25% of {original_qty})\n"
                    f"P&L on partial: ${pt_pnl:+,.2f} (+{pnl_pct*100:.0f}%)\n"
                    f"Remaining: {pos['qty']} contracts with 40% trailing stop"
                )

        # ── Full Exit Logic (safety net) ──
        exit_reason = None

        # Trailing stop check (activates at +80%)
        if pnl_pct >= TRAIL_ACTIVATE:
            pos["trailing_active"] = True
            trail_floor = peak * (1 - TRAIL_PERCENT)
            if current <= trail_floor:
                exit_reason = f"Trailing stop ({pnl_pct*100:+.0f}%, peak ${peak:.2f}, floor ${trail_floor:.2f})"

        # Fixed targets
        if not exit_reason:
            if pnl_pct >= PROFIT_TARGET:
                exit_reason = f"Profit target hit (+{pnl_pct*100:.0f}%)"
            elif pnl_pct <= LOSS_STOP:
                exit_reason = f"Stop loss hit ({pnl_pct*100:.0f}%)"
            elif dte_remaining <= DTE_EXIT:
                exit_reason = f"Time exit ({dte_remaining} DTE remaining)"
            else:
                # Signal reversal
                tech = get_technicals(symbol)
                if tech:
                    if direction == "C" and tech["ema10"] < tech["ema21"] < tech["ema50"]:
                        exit_reason = "Full bearish reversal (close CALL)"
                    elif direction == "P" and tech["ema10"] > tech["ema21"] > tech["ema50"]:
                        exit_reason = "Full bullish reversal (close PUT)"

        if exit_reason:
            opt_type = "CALL" if direction == "C" else "PUT"
            log(f"EXIT: {symbol} [{sector}] {expiry} ${strike}{direction} — {exit_reason}")

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
                "system": "10x_moonshot",
                "ticker": symbol,
                "action": "SELL",
                "qty": pos["qty"],
                "fill_price": fill,
                "pnl": pnl,
                "option": f"{expiry} ${strike}{direction}",
                "commission": 0,
            })

            emoji = "🟢" if pnl >= 0 else "🔴"
            pnl_emoji = "🌙" if pnl > 0 and pnl_pct >= 1.0 else emoji
            telegram.send(
                f"{pnl_emoji} *10X Exit — {symbol} [{sector}] {expiry} ${strike}{direction}*\n\n"
                f"SELL {pos['qty']}x @ ${fill:.2f}\n"
                f"Entry: ${entry:.2f} | P&L: ${pnl:+,.2f} ({pnl_pct*100:+.0f}%)\n"
                f"Reason: {exit_reason}"
            )

        ib.cancelMktData(contract)

    save_positions(positions)
    ib.disconnect()


if __name__ == "__main__":
    log("Trader8 — 10X Moonshot OPTIONS Engine (Calls + Puts)")
    log(f"Sectors: {', '.join(UNIVERSE.keys())}")
    log(f"Universe: {', '.join(ALL_TICKERS)}")
    log(f"Capital: ${CAPITAL:,} | Max positions: {MAX_POSITIONS} | ~${POSITION_SIZE}/position")
    log(f"Targets: +150% / -50% | Trail: +80% activate, 40% trail")
    log("Scanning...")
    scan_and_enter()
