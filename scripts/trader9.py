#!/usr/bin/env python3
"""
RUDY v2.0 — System 9: SCHD Income PMCC (OPTIONS ONLY)
Poor Man's Covered Call on SCHD — conservative income via options.
NO stock ownership. ALL options.

Strategy:
  1. Buy deep ITM LEAP call (80+ delta, 12+ months DTE)
  2. Sell monthly OTM calls against it (25-30 delta, 30-45 DTE)
  3. Roll short call at 50% profit or 21 DTE
  4. Close if LEAP drops 30%
  Target: 1-1.5% monthly income on LEAP cost
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
SYSTEM_NAME = "System 9 — SCHD Income PMCC"
SYMBOL = "SCHD"
CLIENT_ID_SCAN = 90
CLIENT_ID_EXIT = 91
ALLOCATION = 25_000
MAX_POSITIONS = 3  # max 3 PMCC spreads
LEAP_TARGET_DELTA = 0.80
SHORT_TARGET_DELTA = 0.25
LEAP_MIN_DTE = 300  # 10+ months
SHORT_MIN_DTE = 30
SHORT_MAX_DTE = 45
ROLL_PROFIT_PCT = 0.50
ROLL_DTE = 21
LEAP_STOP_LOSS = -0.30  # close if LEAP drops 30%

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
POSITIONS_FILE = os.path.join(DATA_DIR, "trader9_positions.json")
INCOME_FILE = os.path.join(DATA_DIR, "wheel_income.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [SYS9] {msg}"
    print(line)
    with open(os.path.join(LOG_DIR, "trader9.log"), "a") as f:
        f.write(line + "\n")


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {"leaps": [], "short_calls": [], "capital_used": 0}


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2, default=str)


def load_income():
    if os.path.exists(INCOME_FILE):
        with open(INCOME_FILE) as f:
            return json.load(f)
    return {"total_premium": 0, "trades": [], "monthly": {}}


def save_income(income):
    with open(INCOME_FILE, "w") as f:
        json.dump(income, f, indent=2, default=str)


def record_premium(amount, trade_type, strike, expiry):
    income = load_income()
    month_key = datetime.now().strftime("%Y-%m")
    income["total_premium"] += amount
    income["trades"].append({
        "date": datetime.now().isoformat(),
        "type": trade_type,
        "strike": strike,
        "expiry": expiry,
        "premium": amount
    })
    if month_key not in income["monthly"]:
        income["monthly"][month_key] = 0
    income["monthly"][month_key] += amount
    save_income(income)


def get_technicals(symbol):
    """Fetch price data and compute signals."""
    tk = yf.Ticker(symbol)
    df = tk.history(period="6mo", interval="1d")
    if df.empty or len(df) < 50:
        return None

    close = df["Close"].iloc[-1]
    sma20 = df["Close"].rolling(20).mean().iloc[-1]
    sma50 = df["Close"].rolling(50).mean().iloc[-1]
    ema21 = df["Close"].ewm(span=21).mean().iloc[-1]
    ema50 = df["Close"].ewm(span=50).mean().iloc[-1]

    # RSI 14
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
    rsi = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd = ema12.iloc[-1] - ema26.iloc[-1]
    signal = (ema12 - ema26).ewm(span=9).mean().iloc[-1]

    return {
        "close": close,
        "sma20": sma20,
        "sma50": sma50,
        "ema21": ema21,
        "ema50": ema50,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": signal,
    }


def score_entry(tech):
    """Score 0-10 for PMCC entry favorability. Need >= 5 to enter."""
    score = 0

    # Bullish trend
    if tech["close"] > tech["ema50"]:
        score += 2
    if tech["ema21"] > tech["ema50"]:
        score += 2

    # MACD bullish
    if tech["macd"] > tech["macd_signal"]:
        score += 1.5

    # RSI not overbought
    if 35 <= tech["rsi"] <= 65:
        score += 2
    elif tech["rsi"] < 35:
        score += 2.5  # oversold = good entry

    # Price above SMA20
    if tech["close"] > tech["sma20"]:
        score += 1

    # Price above SMA50
    if tech["close"] > tech["sma50"]:
        score += 1

    return min(10, score)


def find_option(ib, symbol, right, target_delta, min_dte, max_dte=None):
    """Find option near target delta in DTE range."""
    from ib_insync import Stock, Option

    stock = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(stock)
    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    if not chains:
        return None, None

    chain = chains[0]
    today = datetime.now().date()
    if max_dte is None:
        max_dte = min_dte + 180

    valid_expiries = []
    for exp_str in chain.expirations:
        exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
        dte = (exp_date - today).days
        if min_dte <= dte <= max_dte:
            valid_expiries.append((exp_str, dte))

    if not valid_expiries:
        return None, None

    # Pick expiry closest to midpoint
    target_dte = (min_dte + max_dte) // 2
    valid_expiries.sort(key=lambda x: abs(x[1] - target_dte))
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

    strikes = sorted(chain.strikes)

    if right == "C" and target_delta >= 0.7:
        # Deep ITM call — look below spot
        valid_strikes = [s for s in strikes if s < spot][-8:]
    elif right == "C":
        # OTM call — look above spot
        valid_strikes = [s for s in strikes if s > spot][:8]
    else:
        valid_strikes = [s for s in strikes if s < spot][-8:]

    if not valid_strikes:
        return None, None

    best_contract = None
    best_delta_diff = float("inf")
    best_premium = 0

    for strike in valid_strikes:
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
    """Check existing positions for roll, stop, or close conditions."""
    from ib_insync import IB, Option, MarketOrder

    positions = load_positions()
    if not positions["leaps"] and not positions["short_calls"]:
        log("No open positions")
        return

    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(9), clientId=CLIENT_ID_EXIT)
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        return

    today = datetime.now().date()
    changes = False

    # Check LEAPs for stop loss
    for i, pos in enumerate(positions["leaps"][:]):
        contract = Option(SYMBOL, pos["expiry"], pos["strike"], "C", "SMART")
        ib.qualifyContracts(contract)
        ticker = ib.reqMktData(contract)
        ib.sleep(2)

        current = (ticker.bid + ticker.ask) / 2 if ticker.bid > 0 else ticker.last
        if math.isnan(current):
            ib.cancelMktData(contract)
            continue

        pnl_pct = (current - pos["entry_price"]) / pos["entry_price"]
        ib.cancelMktData(contract)

        if pnl_pct <= LEAP_STOP_LOSS:
            log(f"LEAP ${pos['strike']} at {pnl_pct:.0%} — STOP LOSS hit")
            order = MarketOrder("SELL", 1)
            ib.placeOrder(contract, order)
            ib.sleep(3)

            positions["leaps"].pop(i)
            positions["capital_used"] -= pos["entry_price"] * 100
            changes = True

            # Close associated short call
            for j, sc in enumerate(positions["short_calls"][:]):
                if sc.get("leap_id") == pos.get("id"):
                    sc_contract = Option(SYMBOL, sc["expiry"], sc["strike"], "C", "SMART")
                    ib.qualifyContracts(sc_contract)
                    ib.placeOrder(sc_contract, MarketOrder("BUY", 1))
                    ib.sleep(2)
                    positions["short_calls"].pop(j)

            msg = f"[SYS9 PMCC] STOP LOSS: Closed LEAP {SYMBOL} ${pos['strike']} at {pnl_pct:.0%}"
            telegram.send(msg)
            log(msg)

    # Check short calls for roll/close
    for i, pos in enumerate(positions["short_calls"][:]):
        exp_date = datetime.strptime(pos["expiry"], "%Y%m%d").date()
        dte_remaining = (exp_date - today).days
        entry_premium = pos["premium"]

        contract = Option(SYMBOL, pos["expiry"], pos["strike"], "C", "SMART")
        ib.qualifyContracts(contract)
        ticker = ib.reqMktData(contract)
        ib.sleep(2)

        current = (ticker.bid + ticker.ask) / 2 if ticker.bid > 0 else ticker.last
        if math.isnan(current):
            current = entry_premium
        ib.cancelMktData(contract)

        profit_pct = (entry_premium - current) / entry_premium if entry_premium > 0 else 0

        if profit_pct >= ROLL_PROFIT_PCT:
            log(f"Short CALL ${pos['strike']} at {profit_pct:.0%} profit — closing")
            ib.placeOrder(contract, MarketOrder("BUY", 1))
            ib.sleep(3)

            realized = (entry_premium - current) * 100
            record_premium(realized, "short_call_profit", pos["strike"], pos["expiry"])
            positions["short_calls"].pop(i)
            changes = True

            msg = f"[SYS9 PMCC] Closed short CALL {SYMBOL} ${pos['strike']} +${realized:.0f}"
            telegram.send(msg)
            log(msg)

        elif dte_remaining <= ROLL_DTE:
            log(f"Short CALL ${pos['strike']} at {dte_remaining} DTE — rolling")
            ib.placeOrder(contract, MarketOrder("BUY", 1))
            ib.sleep(3)

            realized = (entry_premium - current) * 100
            record_premium(realized, "short_call_roll", pos["strike"], pos["expiry"])
            positions["short_calls"].pop(i)
            changes = True

    if changes:
        save_positions(positions)

    ib.disconnect()


def scan_and_enter():
    """Scan for new PMCC entries or sell new short calls against existing LEAPs."""
    from ib_insync import IB, LimitOrder
    import uuid

    positions = load_positions()
    tech = get_technicals(SYMBOL)
    if tech is None:
        log(f"Could not fetch technicals for {SYMBOL}")
        return

    score = score_entry(tech)
    log(f"{SYMBOL} Score: {score:.1f}/10 | Close: ${tech['close']:.2f} | "
        f"RSI: {tech['rsi']:.1f} | EMA21>50: {tech['ema21'] > tech['ema50']}")

    # Check if any LEAP needs a new short call
    needs_short = []
    for leap in positions["leaps"]:
        has_short = any(sc.get("leap_id") == leap.get("id") for sc in positions["short_calls"])
        if not has_short:
            needs_short.append(leap)

    if not needs_short and score < 5:
        log(f"Score {score:.1f} below 5 and no shorts needed — no action")
        return

    if not needs_short and len(positions["leaps"]) >= MAX_POSITIONS:
        log(f"Max positions ({MAX_POSITIONS}) reached — no new LEAPs")
        return

    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(9), clientId=CLIENT_ID_SCAN)
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        return

    try:
        # Sell short calls against LEAPs that need them
        for leap in needs_short:
            contract, premium = find_option(ib, SYMBOL, "C", SHORT_TARGET_DELTA,
                                            SHORT_MIN_DTE, SHORT_MAX_DTE)
            if contract and premium > 0:
                order = LimitOrder("SELL", 1, round(premium, 2))
                ib.placeOrder(contract, order)
                ib.sleep(5)

                positions["short_calls"].append({
                    "strike": contract.strike,
                    "expiry": contract.lastTradeDateOrContractMonth,
                    "premium": premium,
                    "entry_date": datetime.now().isoformat(),
                    "leap_id": leap.get("id"),
                })
                record_premium(premium * 100, "short_call_sold",
                               contract.strike, contract.lastTradeDateOrContractMonth)
                save_positions(positions)

                msg = (f"[SYS9 PMCC] Sold short CALL {SYMBOL} ${contract.strike} "
                       f"exp {contract.lastTradeDateOrContractMonth} | Premium ${premium:.2f}")
                telegram.send(msg)
                log(msg)

        # Enter new PMCC if score is good
        if score >= 5 and len(positions["leaps"]) < MAX_POSITIONS:
            cost_per_leap = tech["close"] * 100 * 0.75  # approximate deep ITM LEAP cost
            if positions["capital_used"] + cost_per_leap > ALLOCATION:
                log(f"Insufficient capital for new LEAP")
            else:
                contract, premium = find_option(ib, SYMBOL, "C", LEAP_TARGET_DELTA,
                                                LEAP_MIN_DTE, LEAP_MIN_DTE + 180)
                if contract and premium > 0:
                    order = LimitOrder("BUY", 1, round(premium, 2))
                    ib.placeOrder(contract, order)
                    ib.sleep(5)

                    leap_id = str(uuid.uuid4())[:8]
                    positions["leaps"].append({
                        "id": leap_id,
                        "strike": contract.strike,
                        "expiry": contract.lastTradeDateOrContractMonth,
                        "entry_price": premium,
                        "entry_date": datetime.now().isoformat(),
                    })
                    positions["capital_used"] += premium * 100
                    save_positions(positions)

                    msg = (f"[SYS9 PMCC] Bought LEAP CALL {SYMBOL} ${contract.strike} "
                           f"exp {contract.lastTradeDateOrContractMonth} | Cost ${premium:.2f} | Score {score:.1f}")
                    telegram.send(msg)
                    log(msg)

                    # Immediately sell short call against it
                    sc_contract, sc_premium = find_option(ib, SYMBOL, "C", SHORT_TARGET_DELTA,
                                                          SHORT_MIN_DTE, SHORT_MAX_DTE)
                    if sc_contract and sc_premium > 0:
                        sc_order = LimitOrder("SELL", 1, round(sc_premium, 2))
                        ib.placeOrder(sc_contract, sc_order)
                        ib.sleep(5)

                        positions["short_calls"].append({
                            "strike": sc_contract.strike,
                            "expiry": sc_contract.lastTradeDateOrContractMonth,
                            "premium": sc_premium,
                            "entry_date": datetime.now().isoformat(),
                            "leap_id": leap_id,
                        })
                        record_premium(sc_premium * 100, "short_call_sold",
                                       sc_contract.strike, sc_contract.lastTradeDateOrContractMonth)
                        save_positions(positions)

                        msg = (f"[SYS9 PMCC] Sold short CALL {SYMBOL} ${sc_contract.strike} "
                               f"against LEAP | Premium ${sc_premium:.2f}")
                        telegram.send(msg)
                        log(msg)

    except Exception as e:
        log(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ib.disconnect()
        log("Disconnected")


if __name__ == "__main__":
    env_file = os.path.expanduser("~/.agent_zero_env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--check":
        check_exits()
    else:
        check_exits()
        scan_and_enter()
