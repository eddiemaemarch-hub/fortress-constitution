#!/usr/bin/env python3
"""
RUDY v2.0 — System 10: S&P PMCC (SPY)
Poor Man's Covered Call on SPY.
Buy deep ITM LEAP call (80+ delta, 12+ months out).
Sell monthly OTM calls against it (20-30 delta, 30-45 DTE).
Target: 1.5% monthly on LEAP cost with $20k allocation.
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
import time
import math
import yfinance as yf
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import deployer
import telegram

# ── Constants ──────────────────────────────────────────────
SYSTEM_NAME = "System 10 — S&P PMCC"
SYMBOL = "SPY"
CLIENT_ID_SCAN = 100
CLIENT_ID_EXIT = 101
ALLOCATION = 20_000
MAX_POSITIONS = 2  # max 2 PMCC spreads
LEAP_DELTA = 0.80
LEAP_MIN_DTE = 365
SHORT_DELTA = 0.25
SHORT_MIN_DTE = 30
SHORT_MAX_DTE = 45
ROLL_PROFIT_PCT = 0.50
LEAP_STOP_LOSS = 0.30  # close if LEAP drops 30%

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
POSITIONS_FILE = os.path.join(DATA_DIR, "trader10_positions.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [SYS10] {msg}"
    print(line)
    with open(os.path.join(LOG_DIR, "trader10.log"), "a") as f:
        f.write(line + "\n")


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {"pmcc_spreads": [], "total_invested": 0}


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2, default=str)


def get_technicals(symbol):
    """Fetch price data and compute signals."""
    tk = yf.Ticker(symbol)
    df = tk.history(period="6mo", interval="1d")
    if df.empty or len(df) < 50:
        return None

    close = df["Close"].iloc[-1]
    sma20 = df["Close"].rolling(20).mean().iloc[-1]
    sma50 = df["Close"].rolling(50).mean().iloc[-1]
    sma200 = df["Close"].rolling(200).mean().iloc[-1] if len(df) >= 200 else sma50

    # RSI 14
    delta_vals = df["Close"].diff()
    gain = delta_vals.where(delta_vals > 0, 0).rolling(14).mean()
    loss = (-delta_vals.where(delta_vals < 0, 0)).rolling(14).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
    rsi = 100 - (100 / (1 + rs))

    # EMA 21
    ema21 = df["Close"].ewm(span=21).mean().iloc[-1]

    return {
        "close": close,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "ema21": ema21,
        "rsi": rsi,
    }


def compute_pmcc_score(tech):
    """Score 0-100 for PMCC entry favorability."""
    score = 50

    # Uptrend bias needed for PMCC
    if tech["close"] > tech["sma50"]:
        score += 10
    if tech["close"] > tech["sma200"]:
        score += 10
    if tech["sma20"] > tech["sma50"]:
        score += 5
    if tech["close"] > tech["ema21"]:
        score += 5

    # RSI — prefer neutral, not overbought
    if 40 <= tech["rsi"] <= 55:
        score += 10
    elif 55 < tech["rsi"] <= 65:
        score += 5
    elif tech["rsi"] > 70:
        score -= 10

    return min(100, max(0, score))


def find_leap_call(ib, symbol, target_delta):
    """Find deep ITM LEAP call with 80+ delta, 12+ months out."""
    from ib_insync import Stock, Option

    stock = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(stock)
    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    if not chains:
        return None, None

    chain = chains[0]
    today = datetime.now().date()

    # Find expiry 12+ months out
    valid_expiries = []
    for exp_str in chain.expirations:
        exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
        dte = (exp_date - today).days
        if dte >= LEAP_MIN_DTE:
            valid_expiries.append((exp_str, dte))

    if not valid_expiries:
        return None, None

    # Pick closest to 15 months
    valid_expiries.sort(key=lambda x: abs(x[1] - 450))
    best_exp, best_dte = valid_expiries[0]

    # Get spot price
    ticker = ib.reqMktData(stock)
    ib.sleep(2)
    spot = ticker.marketPrice()
    if math.isnan(spot):
        spot = ticker.close
    ib.cancelMktData(stock)

    if math.isnan(spot) or spot <= 0:
        return None, None

    # Deep ITM: strike ~20% below spot for 80 delta
    target_strike = spot * 0.85
    strikes = sorted(chain.strikes)
    itm_strikes = [s for s in strikes if s < spot * 0.95]

    if not itm_strikes:
        return None, None

    best_contract = None
    best_delta_diff = float("inf")
    best_premium = 0

    # Check last 8 ITM strikes
    for strike in itm_strikes[-8:]:
        contract = Option(symbol, best_exp, strike, "C", "SMART")
        ib.qualifyContracts(contract)
        opt_ticker = ib.reqMktData(contract)
        ib.sleep(1)

        greeks = opt_ticker.modelGreeks
        if greeks and greeks.delta is not None:
            diff = abs(greeks.delta - target_delta)
            if diff < best_delta_diff:
                best_delta_diff = diff
                best_contract = contract
                mid = (opt_ticker.bid + opt_ticker.ask) / 2 if opt_ticker.bid > 0 else opt_ticker.last
                best_premium = mid if not math.isnan(mid) else 0

        ib.cancelMktData(contract)

    return best_contract, best_premium


def find_short_call(ib, symbol, target_delta, min_dte, max_dte):
    """Find OTM call to sell against LEAP."""
    from ib_insync import Stock, Option

    stock = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(stock)
    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    if not chains:
        return None, None

    chain = chains[0]
    today = datetime.now().date()

    valid_expiries = []
    for exp_str in chain.expirations:
        exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
        dte = (exp_date - today).days
        if min_dte <= dte <= max_dte:
            valid_expiries.append((exp_str, dte))

    if not valid_expiries:
        return None, None

    valid_expiries.sort(key=lambda x: abs(x[1] - 35))
    best_exp, best_dte = valid_expiries[0]

    ticker = ib.reqMktData(stock)
    ib.sleep(2)
    spot = ticker.marketPrice()
    if math.isnan(spot):
        spot = ticker.close
    ib.cancelMktData(stock)

    if math.isnan(spot) or spot <= 0:
        return None, None

    strikes = sorted(chain.strikes)
    otm_strikes = [s for s in strikes if s > spot][:10]

    if not otm_strikes:
        return None, None

    best_contract = None
    best_delta_diff = float("inf")
    best_premium = 0

    for strike in otm_strikes:
        contract = Option(symbol, best_exp, strike, "C", "SMART")
        ib.qualifyContracts(contract)
        opt_ticker = ib.reqMktData(contract)
        ib.sleep(1)

        greeks = opt_ticker.modelGreeks
        if greeks and greeks.delta is not None:
            diff = abs(greeks.delta - target_delta)
            if diff < best_delta_diff:
                best_delta_diff = diff
                best_contract = contract
                mid = (opt_ticker.bid + opt_ticker.ask) / 2 if opt_ticker.bid > 0 else opt_ticker.last
                best_premium = mid if not math.isnan(mid) else 0

        ib.cancelMktData(contract)

    return best_contract, best_premium


def check_exits():
    """Standalone wrapper — manages own IBKR connection."""
    from ib_insync import IB
    positions = load_positions()
    if not positions.get("pmcc_spreads"):
        return
    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(10), clientId=CLIENT_ID_EXIT)
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        return
    try:
        _check_exits(ib, positions)
    finally:
        ib.disconnect()


def _check_exits(ib, positions):
    """Check PMCC positions for roll/stop conditions."""
    from ib_insync import Option, MarketOrder

    today = datetime.now().date()
    changes = False

    for i, spread in enumerate(positions["pmcc_spreads"][:]):
        leap = spread["leap"]
        short = spread.get("short_call")

        # Check LEAP stop loss
        leap_contract = Option(SYMBOL, leap["expiry"], leap["strike"], "C", "SMART")
        ib.qualifyContracts(leap_contract)
        leap_ticker = ib.reqMktData(leap_contract)
        ib.sleep(2)

        leap_current = (leap_ticker.bid + leap_ticker.ask) / 2 if leap_ticker.bid > 0 else leap_ticker.last
        if math.isnan(leap_current):
            leap_current = leap["premium"]
        ib.cancelMktData(leap_contract)

        leap_pnl_pct = (leap_current - leap["premium"]) / leap["premium"]

        if leap_pnl_pct <= -LEAP_STOP_LOSS:
            log(f"LEAP ${leap['strike']} dropped {leap_pnl_pct:.0%} — STOP LOSS triggered")

            # Close short call first if exists
            if short:
                short_contract = Option(SYMBOL, short["expiry"], short["strike"], "C", "SMART")
                ib.qualifyContracts(short_contract)
                order = MarketOrder("BUY", 1)
                ib.placeOrder(short_contract, order)
                ib.sleep(3)

            # Close LEAP
            order = MarketOrder("SELL", 1)
            ib.placeOrder(leap_contract, order)
            ib.sleep(3)

            loss = (leap_current - leap["premium"]) * 100
            positions["pmcc_spreads"].pop(i)
            positions["total_invested"] -= leap["premium"] * 100
            changes = True

            msg = (f"[SYS10 PMCC] STOP LOSS — Closed LEAP ${leap['strike']} "
                   f"| Loss: ${loss:.0f} ({leap_pnl_pct:.0%})")
            telegram.send(msg)
            log(msg)
            continue

        # Check short call for roll
        if short:
            exp_date = datetime.strptime(short["expiry"], "%Y%m%d").date()
            dte_remaining = (exp_date - today).days

            short_contract = Option(SYMBOL, short["expiry"], short["strike"], "C", "SMART")
            ib.qualifyContracts(short_contract)
            short_ticker = ib.reqMktData(short_contract)
            ib.sleep(2)

            short_current = (short_ticker.bid + short_ticker.ask) / 2 if short_ticker.bid > 0 else short_ticker.last
            if math.isnan(short_current):
                short_current = short["premium"]
            ib.cancelMktData(short_contract)

            profit_pct = (short["premium"] - short_current) / short["premium"] if short["premium"] > 0 else 0

            if profit_pct >= ROLL_PROFIT_PCT or dte_remaining <= 21:
                reason = f"{profit_pct:.0%} profit" if profit_pct >= ROLL_PROFIT_PCT else f"{dte_remaining} DTE"
                log(f"Short call ${short['strike']} — closing ({reason})")

                order = MarketOrder("BUY", 1)
                ib.placeOrder(short_contract, order)
                ib.sleep(3)

                realized = (short["premium"] - short_current) * 100
                spread["short_call"] = None
                changes = True

                msg = (f"[SYS10 PMCC] Closed short call ${short['strike']} "
                       f"({reason}) | +${realized:.0f}")
                telegram.send(msg)
                log(msg)

    if changes:
        save_positions(positions)
    return positions


def scan_and_enter():
    """Standalone wrapper — manages own IBKR connection."""
    from ib_insync import IB
    positions = load_positions()
    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(10), clientId=CLIENT_ID_SCAN)
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        return
    try:
        _scan_and_enter(ib, positions)
    finally:
        ib.disconnect()


def _scan_and_enter(ib, positions):
    """Scan for new PMCC entries or sell new short calls."""

    # First: check if any existing PMCC needs a new short call
    for spread in positions["pmcc_spreads"]:
        if spread.get("short_call") is None:
            log("Existing PMCC needs new short call — selling")
            contract, premium = find_short_call(ib, SYMBOL, SHORT_DELTA, SHORT_MIN_DTE, SHORT_MAX_DTE)
            if contract and premium > 0:
                from ib_insync import LimitOrder
                order = LimitOrder("SELL", 1, round(premium, 2))
                ib.placeOrder(contract, order)
                ib.sleep(5)

                spread["short_call"] = {
                    "strike": contract.strike,
                    "expiry": contract.lastTradeDateOrContractMonth,
                    "premium": premium,
                    "entry_date": datetime.now().isoformat()
                }
                save_positions(positions)

                msg = (f"[SYS10 PMCC] Sold short call ${contract.strike} "
                       f"exp {contract.lastTradeDateOrContractMonth} | "
                       f"Premium ${premium:.2f}")
                telegram.send(msg)
                log(msg)
            return

    # New PMCC entry
    if len(positions["pmcc_spreads"]) >= MAX_POSITIONS:
        log(f"Max PMCC positions ({MAX_POSITIONS}) reached")
        return

    tech = get_technicals(SYMBOL)
    if tech is None:
        log(f"Could not fetch technicals for {SYMBOL}")
        return

    score = compute_pmcc_score(tech)
    log(f"{SYMBOL} PMCC Score: {score} | Close: ${tech['close']:.2f} | "
        f"RSI: {tech['rsi']:.1f}")

    if score < 65:
        log(f"Score {score} below threshold 65 — no entry")
        return

    # Check allocation
    remaining = ALLOCATION - positions["total_invested"]
    if remaining < 3000:
        log(f"Insufficient allocation remaining: ${remaining:.0f}")
        return

    # Buy LEAP
    leap_contract, leap_premium = find_leap_call(ib, SYMBOL, LEAP_DELTA)
    if not leap_contract or leap_premium <= 0:
        log("No suitable LEAP found")
        return

    leap_cost = leap_premium * 100
    if leap_cost > remaining:
        log(f"LEAP cost ${leap_cost:.0f} exceeds remaining allocation ${remaining:.0f}")
        return

    from ib_insync import LimitOrder
    order = LimitOrder("BUY", 1, round(leap_premium, 2))
    trade = ib.placeOrder(leap_contract, order)
    ib.sleep(5)

    # Sell short call against it
    short_contract, short_premium = find_short_call(ib, SYMBOL, SHORT_DELTA, SHORT_MIN_DTE, SHORT_MAX_DTE)
    short_data = None
    if short_contract and short_premium > 0:
        order = LimitOrder("SELL", 1, round(short_premium, 2))
        ib.placeOrder(short_contract, order)
        ib.sleep(5)

        short_data = {
            "strike": short_contract.strike,
            "expiry": short_contract.lastTradeDateOrContractMonth,
            "premium": short_premium,
            "entry_date": datetime.now().isoformat()
        }

    positions["pmcc_spreads"].append({
        "leap": {
            "strike": leap_contract.strike,
            "expiry": leap_contract.lastTradeDateOrContractMonth,
            "premium": leap_premium,
            "entry_date": datetime.now().isoformat()
        },
        "short_call": short_data
    })
    positions["total_invested"] += leap_cost
    save_positions(positions)

    msg = (f"[SYS10 PMCC] Opened PMCC on {SYMBOL}\n"
           f"  LEAP: ${leap_contract.strike} exp {leap_contract.lastTradeDateOrContractMonth} "
           f"@ ${leap_premium:.2f}\n"
           f"  Short: ${short_contract.strike if short_contract else 'N/A'} "
           f"@ ${short_premium:.2f if short_premium else 0}\n"
           f"  Net debit: ${(leap_premium - (short_premium or 0)):.2f} | Score {score}")
    telegram.send(msg)
    log(msg)


def main():
    from ib_insync import IB

    log(f"{'='*60}")
    log(f"{SYSTEM_NAME} starting")
    log(f"Allocation: ${ALLOCATION:,} | Max Positions: {MAX_POSITIONS}")

    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(10), clientId=CLIENT_ID_SCAN)
        log("Connected to IBKR")
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        telegram.send(f"[SYS10] IBKR connection failed: {e}")
        return

    try:
        positions = load_positions()
        log(f"Loaded {len(positions['pmcc_spreads'])} PMCC spreads | "
            f"Invested: ${positions['total_invested']:,.0f}")

        positions = _check_exits(ib, positions)
        _scan_and_enter(ib, positions)

    except Exception as e:
        log(f"Error: {e}")
        telegram.send(f"[SYS10] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ib.disconnect()
        log("Disconnected from IBKR")
        log(f"{SYSTEM_NAME} complete")


if __name__ == "__main__":
    env_file = os.path.expanduser("~/.agent_zero_env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

    main()
