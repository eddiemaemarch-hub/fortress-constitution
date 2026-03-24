#!/usr/bin/env python3
"""
RUDY v2.0 — System 12: TQQQ Momentum
Momentum-based directional options on TQQQ with VCA (value cost averaging).
Buy ATM calls in uptrend, puts in downtrend.
$10k allocation, $500 max per position, 30-60 DTE.
Hard stop -40%, profit target +60%.
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
import accountant

# ── Constants ──────────────────────────────────────────────
SYSTEM_NAME = "System 12 — TQQQ Momentum"
SYMBOL = "TQQQ"
QQQ_SYMBOL = "QQQ"
CLIENT_ID_SCAN = 120
CLIENT_ID_EXIT = 121
ALLOCATION = 10_000
MAX_POSITIONS = 3
MAX_PER_POSITION = 500
VCA_ADD_AMOUNT = 200  # add $200 if position drops 20%
VCA_TRIGGER = -0.20
MIN_DTE = 30
MAX_DTE = 60
STOP_LOSS = -0.40
PROFIT_TARGET = 0.60

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
POSITIONS_FILE = os.path.join(DATA_DIR, "trader12_positions.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [SYS12] {msg}"
    print(line)
    with open(os.path.join(LOG_DIR, "trader12.log"), "a") as f:
        f.write(line + "\n")


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {"positions": [], "total_invested": 0, "closed_pnl": 0}


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2, default=str)


def get_technicals(symbol):
    """Fetch price data and compute momentum signals."""
    tk = yf.Ticker(symbol)
    df = tk.history(period="6mo", interval="1d")
    if df.empty or len(df) < 50:
        return None

    close = df["Close"].iloc[-1]
    ema50 = df["Close"].ewm(span=50).mean().iloc[-1]
    ema20 = df["Close"].ewm(span=20).mean().iloc[-1]
    sma200 = df["Close"].rolling(200).mean().iloc[-1] if len(df) >= 200 else ema50

    # RSI 14
    delta_vals = df["Close"].diff()
    gain = delta_vals.where(delta_vals > 0, 0).rolling(14).mean()
    loss = (-delta_vals.where(delta_vals < 0, 0)).rolling(14).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
    rsi = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd = ema12.iloc[-1] - ema26.iloc[-1]
    signal = (ema12 - ema26).ewm(span=9).mean().iloc[-1]
    macd_hist = macd - signal

    # Rate of change 10-day
    roc = (close / df["Close"].iloc[-11] - 1) * 100 if len(df) >= 11 else 0

    return {
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "sma200": sma200,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": signal,
        "macd_hist": macd_hist,
        "roc": roc,
    }


def compute_momentum_score(tqqq_tech, qqq_tech):
    """
    Score from -100 (strong bearish) to +100 (strong bullish).
    Positive = buy calls, Negative = buy puts, Near zero = stay out.
    """
    score = 0

    # TQQQ above/below 50 EMA
    if tqqq_tech["close"] > tqqq_tech["ema50"]:
        score += 20
    else:
        score -= 20

    # TQQQ above/below 20 EMA
    if tqqq_tech["close"] > tqqq_tech["ema20"]:
        score += 10
    else:
        score -= 10

    # QQQ RSI signals
    qqq_rsi = qqq_tech["rsi"]
    if qqq_rsi > 60:
        score += 15
    elif qqq_rsi > 50:
        score += 10
    elif qqq_rsi < 40:
        score -= 20
    elif qqq_rsi < 50:
        score -= 10

    # MACD momentum
    if tqqq_tech["macd_hist"] > 0:
        score += 10
    else:
        score -= 10

    # Rate of change
    if tqqq_tech["roc"] > 5:
        score += 10
    elif tqqq_tech["roc"] < -5:
        score -= 10

    # QQQ trend
    if qqq_tech["close"] > qqq_tech["ema50"]:
        score += 10
    else:
        score -= 10

    return max(-100, min(100, score))


def find_atm_option(ib, symbol, right, min_dte, max_dte):
    """Find ATM option for directional trade."""
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

    # Target 45 DTE
    valid_expiries.sort(key=lambda x: abs(x[1] - 45))
    best_exp, best_dte = valid_expiries[0]

    ticker = ib.reqMktData(stock)
    ib.sleep(2)
    spot = ticker.marketPrice()
    if math.isnan(spot):
        spot = ticker.close
    ib.cancelMktData(stock)

    if math.isnan(spot) or spot <= 0:
        return None, None

    # Find ATM strike (closest to spot)
    strikes = sorted(chain.strikes)
    atm_strike = min(strikes, key=lambda s: abs(s - spot))

    contract = Option(symbol, best_exp, atm_strike, right, "SMART")
    ib.qualifyContracts(contract)
    opt_ticker = ib.reqMktData(contract)
    ib.sleep(2)

    mid = (opt_ticker.bid + opt_ticker.ask) / 2 if opt_ticker.bid > 0 else opt_ticker.last
    premium = mid if not math.isnan(mid) else 0
    ib.cancelMktData(contract)

    return contract, premium


def check_exits():
    """Standalone wrapper — manages own IBKR connection."""
    from ib_insync import IB
    positions = load_positions()
    if not positions.get("positions"):
        return
    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(12), clientId=CLIENT_ID_EXIT)
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        return
    try:
        _check_exits(ib, positions)
    finally:
        ib.disconnect()


def _check_exits(ib, positions):
    """Check positions for stop loss, profit target, or VCA opportunity."""
    from ib_insync import Option, MarketOrder, LimitOrder

    changes = False
    today = datetime.now().date()

    for i, pos in enumerate(positions["positions"][:]):
        contract = Option(SYMBOL, pos["expiry"], pos["strike"], pos["right"], "SMART")
        ib.qualifyContracts(contract)
        ticker = ib.reqMktData(contract)
        ib.sleep(2)

        current_mid = (ticker.bid + ticker.ask) / 2 if ticker.bid > 0 else ticker.last
        if math.isnan(current_mid):
            current_mid = pos["avg_cost"]
        ib.cancelMktData(contract)

        pnl_pct = (current_mid - pos["avg_cost"]) / pos["avg_cost"] if pos["avg_cost"] > 0 else 0
        pnl_dollar = (current_mid - pos["avg_cost"]) * pos["quantity"] * 100

        exp_date = datetime.strptime(pos["expiry"], "%Y%m%d").date()
        dte_remaining = (exp_date - today).days

        # ── Tiered Profit-Taking (partial sells) ──
        original_quantity = pos.get("original_quantity", pos["quantity"])
        opt_label = f"{pos['right']} ${pos['strike']} exp {pos['expiry']}"

        # Tier 1: +50% gain → sell 33%
        if pnl_pct >= 0.50 and not pos.get("profit_take_50"):
            sell_qty = max(1, int(original_quantity * 0.33))
            if sell_qty > 0 and pos["quantity"] > sell_qty:
                log(f"PROFIT TAKE 50%: {opt_label} — selling {sell_qty} of {pos['quantity']} (+{pnl_pct:.0%})")
                pt_order = MarketOrder("SELL", sell_qty)
                pt_order.tif = "GTC"
                ib.placeOrder(contract, pt_order)
                ib.sleep(3)
                pt_pnl = (current_mid - pos["avg_cost"]) * sell_qty * 100
                pos["profit_take_50"] = True
                pos["quantity"] -= sell_qty
                changes = True
                accountant.record_trade({
                    "system": "tqqq_momentum",
                    "ticker": SYMBOL,
                    "action": "SELL",
                    "qty": sell_qty,
                    "fill_price": current_mid,
                    "pnl": pt_pnl,
                    "option": opt_label,
                    "commission": 0,
                    "note": "profit_take_50pct",
                })
                telegram.send(
                    f"💰 *[SYS12 TQQQ] Profit Take +50% {opt_label}*\n\n"
                    f"SELL {sell_qty}x @ ${current_mid:.2f} (of {original_quantity} original)\n"
                    f"P&L on partial: ${pt_pnl:+,.2f} (+{pnl_pct:.0%})\n"
                    f"Remaining: {pos['quantity']} contracts"
                )

        # Tier 2: +100% gain → sell 33% more
        if pnl_pct >= 1.00 and not pos.get("profit_take_100"):
            sell_qty = max(1, int(original_quantity * 0.33))
            if sell_qty > 0 and pos["quantity"] > sell_qty:
                log(f"PROFIT TAKE 100%: {opt_label} — selling {sell_qty} of {pos['quantity']} (+{pnl_pct:.0%})")
                pt_order = MarketOrder("SELL", sell_qty)
                pt_order.tif = "GTC"
                ib.placeOrder(contract, pt_order)
                ib.sleep(3)
                pt_pnl = (current_mid - pos["avg_cost"]) * sell_qty * 100
                pos["profit_take_100"] = True
                pos["quantity"] -= sell_qty
                changes = True
                accountant.record_trade({
                    "system": "tqqq_momentum",
                    "ticker": SYMBOL,
                    "action": "SELL",
                    "qty": sell_qty,
                    "fill_price": current_mid,
                    "pnl": pt_pnl,
                    "option": opt_label,
                    "commission": 0,
                    "note": "profit_take_100pct",
                })
                telegram.send(
                    f"💰💰 *[SYS12 TQQQ] Profit Take +100% {opt_label}*\n\n"
                    f"SELL {sell_qty}x @ ${current_mid:.2f} (of {original_quantity} original)\n"
                    f"P&L on partial: ${pt_pnl:+,.2f} (+{pnl_pct:.0%})\n"
                    f"Remaining: {pos['quantity']} contracts — letting winners ride!"
                )

        # Hard stop loss
        if pnl_pct <= STOP_LOSS:
            log(f"STOP LOSS: {pos['right']} ${pos['strike']} at {pnl_pct:.0%}")
            order = MarketOrder("SELL", pos["quantity"])
            ib.placeOrder(contract, order)
            ib.sleep(3)

            positions["closed_pnl"] += pnl_dollar
            positions["total_invested"] -= pos["total_cost"]
            positions["positions"].pop(i)
            changes = True

            msg = (f"[SYS12 TQQQ] STOP LOSS {pos['right']} ${pos['strike']} "
                   f"| {pnl_pct:.0%} | ${pnl_dollar:.0f}")
            telegram.send(msg)
            log(msg)
            continue

        # Profit target
        if pnl_pct >= PROFIT_TARGET:
            log(f"PROFIT TARGET: {pos['right']} ${pos['strike']} at {pnl_pct:.0%}")
            order = MarketOrder("SELL", pos["quantity"])
            ib.placeOrder(contract, order)
            ib.sleep(3)

            positions["closed_pnl"] += pnl_dollar
            positions["total_invested"] -= pos["total_cost"]
            positions["positions"].pop(i)
            changes = True

            msg = (f"[SYS12 TQQQ] PROFIT TARGET {pos['right']} ${pos['strike']} "
                   f"| +{pnl_pct:.0%} | +${pnl_dollar:.0f}")
            telegram.send(msg)
            log(msg)
            continue

        # Close if < 7 DTE
        if dte_remaining <= 7:
            log(f"Closing {pos['right']} ${pos['strike']} — only {dte_remaining} DTE")
            order = MarketOrder("SELL", pos["quantity"])
            ib.placeOrder(contract, order)
            ib.sleep(3)

            positions["closed_pnl"] += pnl_dollar
            positions["total_invested"] -= pos["total_cost"]
            positions["positions"].pop(i)
            changes = True

            msg = (f"[SYS12 TQQQ] Closed {pos['right']} ${pos['strike']} "
                   f"at {dte_remaining} DTE | {pnl_pct:.0%} | ${pnl_dollar:.0f}")
            telegram.send(msg)
            log(msg)
            continue

        # VCA: add $200 if position drops 20%
        if pnl_pct <= VCA_TRIGGER and not pos.get("vca_added"):
            remaining_alloc = ALLOCATION - positions["total_invested"]
            if remaining_alloc >= VCA_ADD_AMOUNT and current_mid > 0:
                add_qty = max(1, int(VCA_ADD_AMOUNT / (current_mid * 100)))
                add_cost = current_mid * add_qty * 100

                if add_cost <= remaining_alloc:
                    log(f"VCA: Adding {add_qty} contracts at ${current_mid:.2f}")
                    order = LimitOrder("BUY", add_qty, round(current_mid, 2))
                    ib.placeOrder(contract, order)
                    ib.sleep(5)

                    # Update position average
                    old_total = pos["avg_cost"] * pos["quantity"]
                    new_total = old_total + (current_mid * add_qty)
                    pos["quantity"] += add_qty
                    pos["avg_cost"] = new_total / pos["quantity"]
                    pos["total_cost"] += add_cost
                    pos["vca_added"] = True
                    positions["total_invested"] += add_cost
                    changes = True

                    msg = (f"[SYS12 TQQQ] VCA +{add_qty} {pos['right']} ${pos['strike']} "
                           f"@ ${current_mid:.2f} | New avg: ${pos['avg_cost']:.2f}")
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
        ib.connect("127.0.0.1", deployer.get_port(12), clientId=CLIENT_ID_SCAN)
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        return
    try:
        _scan_and_enter(ib, positions)
    finally:
        ib.disconnect()


def _scan_and_enter(ib, positions):
    """Scan for momentum entry signals."""
    if len(positions["positions"]) >= MAX_POSITIONS:
        log(f"Max positions ({MAX_POSITIONS}) reached")
        return

    remaining = ALLOCATION - positions["total_invested"]
    if remaining < MAX_PER_POSITION:
        log(f"Insufficient allocation: ${remaining:.0f}")
        return

    tqqq_tech = get_technicals(SYMBOL)
    qqq_tech = get_technicals(QQQ_SYMBOL)

    if tqqq_tech is None or qqq_tech is None:
        log("Could not fetch technicals")
        return

    score = compute_momentum_score(tqqq_tech, qqq_tech)
    log(f"Momentum Score: {score} | TQQQ ${tqqq_tech['close']:.2f} | "
        f"QQQ RSI: {qqq_tech['rsi']:.1f} | TQQQ vs EMA50: "
        f"{'ABOVE' if tqqq_tech['close'] > tqqq_tech['ema50'] else 'BELOW'}")

    # Determine direction
    if score >= 40:
        direction = "C"
        log(f"BULLISH signal (score {score}) — looking for calls")
    elif score <= -40:
        direction = "P"
        log(f"BEARISH signal (score {score}) — looking for puts")
    else:
        log(f"Neutral score {score} — no entry (need >= 40 or <= -40)")
        return

    # Check for conflicting positions
    for pos in positions["positions"]:
        if pos["right"] != direction:
            log(f"Already have {pos['right']} position — conflicting signal, skip")
            return

    # Find ATM option
    contract, premium = find_atm_option(ib, SYMBOL, direction, MIN_DTE, MAX_DTE)
    if not contract or premium <= 0:
        log(f"No suitable {direction} option found")
        return

    # Size: max $500 per position
    cost_per_contract = premium * 100
    quantity = max(1, int(MAX_PER_POSITION / cost_per_contract))
    total_cost = cost_per_contract * quantity

    if total_cost > remaining:
        quantity = max(1, int(remaining / cost_per_contract))
        total_cost = cost_per_contract * quantity

    if total_cost > remaining or total_cost <= 0:
        log(f"Cannot afford: ${total_cost:.0f} > ${remaining:.0f}")
        return

    from ib_insync import LimitOrder
    order = LimitOrder("BUY", quantity, round(premium, 2))
    trade = ib.placeOrder(contract, order)
    ib.sleep(5)

    new_pos = {
        "right": direction,
        "strike": contract.strike,
        "expiry": contract.lastTradeDateOrContractMonth,
        "quantity": quantity,
        "avg_cost": premium,
        "total_cost": total_cost,
        "entry_date": datetime.now().isoformat(),
        "entry_score": score,
        "vca_added": False,
        "original_quantity": quantity,
        "profit_take_50": False,
        "profit_take_100": False,
    }

    # Constitution v44.0 — MANDATORY trailing stop at entry
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(__file__))
    from stop_utils import place_trailing_stop
    stop_result = place_trailing_stop(ib, contract, quantity, premium, "tqqq_momentum", log)
    new_pos["trailing_stop"] = stop_result

    positions["positions"].append(new_pos)
    positions["total_invested"] += total_cost
    save_positions(positions)

    right_name = "CALL" if direction == "C" else "PUT"
    msg = (f"[SYS12 TQQQ] Bought {quantity}x {right_name} ${contract.strike} "
           f"exp {contract.lastTradeDateOrContractMonth} @ ${premium:.2f}\n"
           f"  Cost: ${total_cost:.0f} | Score: {score}")
    telegram.send(msg)
    log(msg)


def main():
    from ib_insync import IB

    log(f"{'='*60}")
    log(f"{SYSTEM_NAME} starting")
    log(f"Allocation: ${ALLOCATION:,} | Max Positions: {MAX_POSITIONS}")

    ib = IB()
    try:
        ib.connect("127.0.0.1", deployer.get_port(12), clientId=CLIENT_ID_SCAN)
        log("Connected to IBKR")
    except Exception as e:
        log(f"IBKR connection failed: {e}")
        telegram.send(f"[SYS12] IBKR connection failed: {e}")
        return

    try:
        positions = load_positions()
        log(f"Loaded {len(positions['positions'])} positions | "
            f"Invested: ${positions['total_invested']:,.0f} | "
            f"Closed P&L: ${positions['closed_pnl']:,.0f}")

        positions = _check_exits(ib, positions)
        _scan_and_enter(ib, positions)

    except Exception as e:
        log(f"Error: {e}")
        telegram.send(f"[SYS12] Error: {e}")
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
