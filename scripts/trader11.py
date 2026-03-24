#!/usr/bin/env python3
"""
RUDY v2.0 — System 11: QQQ Growth Collar
Buy QQQ LEAP calls (70 delta, 12+ months).
Sell monthly OTM calls (25 delta) for income.
Buy monthly OTM puts (15 delta) for crash protection.
Target: upside participation with hedged downside on $15k allocation.
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
SYSTEM_NAME = "System 11 — QQQ Growth Collar"
SYMBOL = "QQQ"
CLIENT_ID_SCAN = 110
CLIENT_ID_EXIT = 111
ALLOCATION = 15_000
MAX_POSITIONS = 2
LEAP_DELTA = 0.70
LEAP_MIN_DTE = 365
SHORT_CALL_DELTA = 0.25
LONG_PUT_DELTA = 0.15
SHORT_MIN_DTE = 30
SHORT_MAX_DTE = 45
ROLL_PROFIT_PCT = 0.50

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
POSITIONS_FILE = os.path.join(DATA_DIR, "trader11_positions.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [SYS11] {msg}"
    print(line)
    with open(os.path.join(LOG_DIR, "trader11.log"), "a") as f:
        f.write(line + "\n")


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {"collars": [], "total_invested": 0}


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
    ema21 = df["Close"].ewm(span=21).mean().iloc[-1]

    # RSI 14
    delta_vals = df["Close"].diff()
    gain = delta_vals.where(delta_vals > 0, 0).rolling(14).mean()
    loss = (-delta_vals.where(delta_vals < 0, 0)).rolling(14).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
    rsi = 100 - (100 / (1 + rs))

    # Volatility (20-day std annualized)
    returns = df["Close"].pct_change()
    vol_20 = returns.rolling(20).std().iloc[-1] * (252 ** 0.5)

    return {
        "close": close,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "ema21": ema21,
        "rsi": rsi,
        "vol_20": vol_20,
    }


def compute_collar_score(tech):
    """Score 0-100 for collar entry favorability."""
    score = 50

    # Want uptrend for LEAP entry
    if tech["close"] > tech["sma50"]:
        score += 10
    if tech["close"] > tech["sma200"]:
        score += 10
    if tech["sma20"] > tech["sma50"]:
        score += 5

    # RSI — prefer not overbought
    if 40 <= tech["rsi"] <= 60:
        score += 10
    elif 30 <= tech["rsi"] < 40:
        score += 5  # slightly oversold is OK for collared entry
    elif tech["rsi"] > 70:
        score -= 10

    # Higher vol = better premiums for selling calls
    if tech["vol_20"] > 0.20:
        score += 5
    if tech["vol_20"] > 0.25:
        score += 5

    return min(100, max(0, score))


def find_option(ib, symbol, right, target_delta, min_dte, max_dte):
    """Find option contract near target delta and DTE range."""
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

    target_dte = (min_dte + max_dte) // 2
    valid_expiries.sort(key=lambda x: abs(x[1] - target_dte))
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

    if right == "C" and target_delta >= 0.5:
        # ITM calls — look below spot
        candidates = [s for s in strikes if s < spot][-10:]
    elif right == "C":
        # OTM calls — look above spot
        candidates = [s for s in strikes if s > spot][:10]
    elif right == "P" and target_delta < 0.5:
        # OTM puts — look below spot
        candidates = [s for s in strikes if s < spot][-10:]
    else:
        candidates = [s for s in strikes if s > spot][:10]

    if not candidates:
        return None, None

    best_contract = None
    best_delta_diff = float("inf")
    best_premium = 0

    for strike in candidates:
        contract = Option(symbol, best_exp, strike, right, "SMART")
        ib.qualifyContracts(contract)
        opt_ticker = ib.reqMktData(contract)
        ib.sleep(1)

        greeks = opt_ticker.modelGreeks
        if greeks and greeks.delta is not None:
            opt_delta = abs(greeks.delta)
            diff = abs(opt_delta - target_delta)
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
    if not positions.get("collars"):
        return
    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(11), clientId=CLIENT_ID_EXIT)
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        return
    try:
        _check_exits(ib, positions)
    finally:
        ib.disconnect()


def _check_exits(ib, positions):
    """Check collar positions for roll/close conditions."""
    from ib_insync import Option, MarketOrder

    today = datetime.now().date()
    changes = False

    for i, collar in enumerate(positions["collars"][:]):
        leap = collar["leap"]
        short_call = collar.get("short_call")
        long_put = collar.get("long_put")

        # Check LEAP health
        leap_contract = Option(SYMBOL, leap["expiry"], leap["strike"], "C", "SMART")
        ib.qualifyContracts(leap_contract)
        leap_ticker = ib.reqMktData(leap_contract)
        ib.sleep(2)

        leap_current = (leap_ticker.bid + leap_ticker.ask) / 2 if leap_ticker.bid > 0 else leap_ticker.last
        if math.isnan(leap_current):
            leap_current = leap["premium"]
        ib.cancelMktData(leap_contract)

        leap_exp_date = datetime.strptime(leap["expiry"], "%Y%m%d").date()
        leap_dte = (leap_exp_date - today).days

        # If LEAP has less than 90 DTE, close entire position and re-enter
        if leap_dte < 90:
            log(f"LEAP {leap['strike']} only {leap_dte} DTE — closing entire collar")

            # Close short call
            if short_call:
                sc = Option(SYMBOL, short_call["expiry"], short_call["strike"], "C", "SMART")
                ib.qualifyContracts(sc)
                ib.placeOrder(sc, MarketOrder("BUY", 1))
                ib.sleep(3)

            # Close long put
            if long_put:
                lp = Option(SYMBOL, long_put["expiry"], long_put["strike"], "P", "SMART")
                ib.qualifyContracts(lp)
                ib.placeOrder(lp, MarketOrder("SELL", 1))
                ib.sleep(3)

            # Close LEAP
            ib.placeOrder(leap_contract, MarketOrder("SELL", 1))
            ib.sleep(3)

            pnl = (leap_current - leap["premium"]) * 100
            positions["collars"].pop(i)
            positions["total_invested"] -= leap["premium"] * 100
            changes = True

            msg = f"[SYS11 COLLAR] Closed entire collar — LEAP expiring | P&L ${pnl:.0f}"
            telegram.send(msg)
            log(msg)
            continue

        # Check short call for roll
        if short_call:
            sc_exp = datetime.strptime(short_call["expiry"], "%Y%m%d").date()
            sc_dte = (sc_exp - today).days

            sc_contract = Option(SYMBOL, short_call["expiry"], short_call["strike"], "C", "SMART")
            ib.qualifyContracts(sc_contract)
            sc_ticker = ib.reqMktData(sc_contract)
            ib.sleep(2)

            sc_current = (sc_ticker.bid + sc_ticker.ask) / 2 if sc_ticker.bid > 0 else sc_ticker.last
            if math.isnan(sc_current):
                sc_current = short_call["premium"]
            ib.cancelMktData(sc_contract)

            profit_pct = (short_call["premium"] - sc_current) / short_call["premium"] if short_call["premium"] > 0 else 0

            if profit_pct >= ROLL_PROFIT_PCT or sc_dte <= 21:
                reason = f"{profit_pct:.0%} profit" if profit_pct >= ROLL_PROFIT_PCT else f"{sc_dte} DTE"
                ib.placeOrder(sc_contract, MarketOrder("BUY", 1))
                ib.sleep(3)

                realized = (short_call["premium"] - sc_current) * 100
                collar["short_call"] = None
                changes = True

                msg = f"[SYS11 COLLAR] Closed short call ${short_call['strike']} ({reason}) | +${realized:.0f}"
                telegram.send(msg)
                log(msg)

        # Check long put expiry
        if long_put:
            lp_exp = datetime.strptime(long_put["expiry"], "%Y%m%d").date()
            lp_dte = (lp_exp - today).days

            if lp_dte <= 7:
                lp_contract = Option(SYMBOL, long_put["expiry"], long_put["strike"], "P", "SMART")
                ib.qualifyContracts(lp_contract)
                ib.placeOrder(lp_contract, MarketOrder("SELL", 1))
                ib.sleep(3)

                collar["long_put"] = None
                changes = True
                log(f"Closed expiring protective put ${long_put['strike']}")

    if changes:
        save_positions(positions)
    return positions


def scan_and_enter():
    """Standalone wrapper — manages own IBKR connection."""
    from ib_insync import IB
    positions = load_positions()
    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(11), clientId=CLIENT_ID_SCAN)
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        return
    try:
        _scan_and_enter(ib, positions)
    finally:
        ib.disconnect()


def _scan_and_enter(ib, positions):
    """Scan for new collar entries or replace expired legs."""

    # Re-sell short calls / re-buy puts on existing collars
    for collar in positions["collars"]:
        if collar.get("short_call") is None:
            log("Selling new short call on existing collar")
            contract, premium = find_option(ib, SYMBOL, "C", SHORT_CALL_DELTA, SHORT_MIN_DTE, SHORT_MAX_DTE)
            if contract and premium > 0:
                from ib_insync import LimitOrder
                ib.placeOrder(contract, LimitOrder("SELL", 1, round(premium, 2)))
                ib.sleep(5)
                collar["short_call"] = {
                    "strike": contract.strike,
                    "expiry": contract.lastTradeDateOrContractMonth,
                    "premium": premium,
                    "entry_date": datetime.now().isoformat()
                }
                save_positions(positions)
                msg = f"[SYS11 COLLAR] Sold call ${contract.strike} | ${premium:.2f}"
                telegram.send(msg)
                log(msg)

        if collar.get("long_put") is None:
            log("Buying new protective put on existing collar")
            contract, premium = find_option(ib, SYMBOL, "P", LONG_PUT_DELTA, SHORT_MIN_DTE, SHORT_MAX_DTE)
            if contract and premium > 0:
                from ib_insync import LimitOrder
                ib.placeOrder(contract, LimitOrder("BUY", 1, round(premium, 2)))
                ib.sleep(5)
                collar["long_put"] = {
                    "strike": contract.strike,
                    "expiry": contract.lastTradeDateOrContractMonth,
                    "premium": premium,
                    "entry_date": datetime.now().isoformat()
                }
                save_positions(positions)
                msg = f"[SYS11 COLLAR] Bought put ${contract.strike} | ${premium:.2f}"
                telegram.send(msg)
                log(msg)
            return

    # New collar entry
    if len(positions["collars"]) >= MAX_POSITIONS:
        log(f"Max collar positions ({MAX_POSITIONS}) reached")
        return

    tech = get_technicals(SYMBOL)
    if tech is None:
        log(f"Could not fetch technicals for {SYMBOL}")
        return

    score = compute_collar_score(tech)
    log(f"{SYMBOL} Collar Score: {score} | Close: ${tech['close']:.2f} | "
        f"RSI: {tech['rsi']:.1f} | Vol: {tech['vol_20']:.1%}")

    if score < 60:
        log(f"Score {score} below threshold 60 — no entry")
        return

    remaining = ALLOCATION - positions["total_invested"]
    if remaining < 2000:
        log(f"Insufficient allocation: ${remaining:.0f}")
        return

    # Buy LEAP call (70 delta)
    leap_contract, leap_premium = find_option(ib, SYMBOL, "C", LEAP_DELTA, LEAP_MIN_DTE, 550)
    if not leap_contract or leap_premium <= 0:
        log("No suitable LEAP call found")
        return

    leap_cost = leap_premium * 100
    if leap_cost > remaining:
        log(f"LEAP cost ${leap_cost:.0f} exceeds allocation ${remaining:.0f}")
        return

    from ib_insync import LimitOrder

    # Buy LEAP
    ib.placeOrder(leap_contract, LimitOrder("BUY", 1, round(leap_premium, 2)))
    ib.sleep(5)

    # Sell OTM call (25 delta)
    short_contract, short_premium = find_option(ib, SYMBOL, "C", SHORT_CALL_DELTA, SHORT_MIN_DTE, SHORT_MAX_DTE)
    short_data = None
    if short_contract and short_premium > 0:
        ib.placeOrder(short_contract, LimitOrder("SELL", 1, round(short_premium, 2)))
        ib.sleep(5)
        short_data = {
            "strike": short_contract.strike,
            "expiry": short_contract.lastTradeDateOrContractMonth,
            "premium": short_premium,
            "entry_date": datetime.now().isoformat()
        }

    # Buy OTM put (15 delta)
    put_contract, put_premium = find_option(ib, SYMBOL, "P", LONG_PUT_DELTA, SHORT_MIN_DTE, SHORT_MAX_DTE)
    put_data = None
    if put_contract and put_premium > 0:
        ib.placeOrder(put_contract, LimitOrder("BUY", 1, round(put_premium, 2)))
        ib.sleep(5)
        put_data = {
            "strike": put_contract.strike,
            "expiry": put_contract.lastTradeDateOrContractMonth,
            "premium": put_premium,
            "entry_date": datetime.now().isoformat()
        }

    collar_entry = {
        "leap": {
            "strike": leap_contract.strike,
            "expiry": leap_contract.lastTradeDateOrContractMonth,
            "premium": leap_premium,
            "entry_date": datetime.now().isoformat()
        },
        "short_call": short_data,
        "long_put": put_data
    }
    positions["collars"].append(collar_entry)
    positions["total_invested"] += leap_cost
    save_positions(positions)

    net_monthly = (short_premium or 0) - (put_premium or 0)
    msg = (f"[SYS11 COLLAR] Opened collar on {SYMBOL}\n"
           f"  LEAP: ${leap_contract.strike} @ ${leap_premium:.2f}\n"
           f"  Short call: ${short_contract.strike if short_contract else 'N/A'} @ ${short_premium:.2f if short_premium else 0}\n"
           f"  Long put: ${put_contract.strike if put_contract else 'N/A'} @ ${put_premium:.2f if put_premium else 0}\n"
           f"  Net monthly: ${net_monthly:.2f} | Score {score}")
    telegram.send(msg)
    log(msg)


def main():
    from ib_insync import IB

    log(f"{'='*60}")
    log(f"{SYSTEM_NAME} starting")
    log(f"Allocation: ${ALLOCATION:,} | Max Positions: {MAX_POSITIONS}")

    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(11), clientId=CLIENT_ID_SCAN)
        log("Connected to IBKR")
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        telegram.send(f"[SYS11] IBKR connection failed: {e}")
        return

    try:
        positions = load_positions()
        log(f"Loaded {len(positions['collars'])} collars | "
            f"Invested: ${positions['total_invested']:,.0f}")

        positions = _check_exits(ib, positions)
        _scan_and_enter(ib, positions)

    except Exception as e:
        log(f"Error: {e}")
        telegram.send(f"[SYS11] Error: {e}")
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
