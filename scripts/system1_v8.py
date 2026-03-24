"""System 1 v8 — Deep OTM Lottery Strategy (Production)
Constitution v50.0 | MSTR/IBIT Only
Backtested: $100k → $4.6M (2022-2026) | Sharpe 4.05

Entry: RSI < 30 + SMA50 > SMA200 (or MACD cross + RSI < 40)
Tickets: Deep OTM calls 30-60% above price, 90-365 DTE
Spread: 60% on closer strike, 30% on further OTM
Hedge: OTM puts with remaining cash
Exit: 10x rule (sell 50%), 20x moonshot (sell 25% more), RSI > 80 full exit
Losers: Let expire worthless — true lottery style
"""
import os
import sys
import json
import time
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram

from ib_insync import *
import yfinance as yf

LOG_DIR = os.path.expanduser("~/rudy/logs")
POSITIONS_FILE = os.path.expanduser("~/rudy/data/system1_positions.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)

# Constitution v50.0 parameters
CAPITAL = 100000
SURVIVAL_BREAKER = 75000
TEN_X_SELL_PCT = 0.50
TWENTY_X_SELL_PCT = 0.25
RSI_ENTRY = 30
RSI_EXIT = 80
MACD_RSI_ENTRY = 40
OTM_LOW = 1.30   # 30% OTM minimum
OTM_HIGH = 1.80  # 80% OTM maximum
OTM_FALLBACK_LOW = 1.15
OTM_FALLBACK_HIGH = 1.40
MIN_DTE = 90
MAX_DTE = 365
MIN_ASK = 0.20
MAX_ASK = 15.00
BUDGET_CALLS = 0.90  # 90% on calls
BUDGET_HEDGE = 0.50  # 50% of remaining on hedge


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[S1v8 {ts}] {msg}")
    with open(f"{LOG_DIR}/system1_v8.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def get_price(symbol):
    """Get current price from Yahoo Finance."""
    t = yf.Ticker(symbol)
    data = t.history(period="1d")
    if not data.empty:
        return float(data["Close"].iloc[-1])
    return float(t.info.get("regularMarketPrice", 0))


def get_rsi(symbol, period=14):
    """Calculate RSI from Yahoo Finance data."""
    t = yf.Ticker(symbol)
    data = t.history(period="3mo")
    if data.empty:
        return 50  # Neutral if no data

    delta = data["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def get_sma(symbol, period):
    """Calculate SMA from Yahoo Finance data."""
    t = yf.Ticker(symbol)
    data = t.history(period="1y")
    if len(data) < period:
        return 0
    return float(data["Close"].rolling(window=period).mean().iloc[-1])


def get_macd(symbol):
    """Calculate MACD from Yahoo Finance data."""
    t = yf.Ticker(symbol)
    data = t.history(period="6mo")
    if data.empty:
        return 0, 0

    ema12 = data["Close"].ewm(span=12).mean()
    ema26 = data["Close"].ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])


def check_entry_signal(symbol="MSTR"):
    """Check if entry conditions are met."""
    price = get_price(symbol)
    rsi = get_rsi(symbol)
    sma50 = get_sma(symbol, 50)
    sma200 = get_sma(symbol, 200)
    macd_line, macd_signal = get_macd(symbol)

    log(f"Signal check: {symbol} @ ${price:.2f} | RSI: {rsi:.1f} | SMA50: {sma50:.2f} | SMA200: {sma200:.2f} | MACD: {macd_line:.2f}/{macd_signal:.2f}")

    uptrend = sma50 > sma200

    # Signal 1: RSI oversold + uptrend
    if rsi < RSI_ENTRY and uptrend:
        return True, f"RSI oversold ({rsi:.1f}) + uptrend", price

    # Signal 2: MACD bullish cross + RSI under 40 + uptrend
    if macd_line > macd_signal and rsi < MACD_RSI_ENTRY and uptrend:
        return True, f"MACD cross + RSI {rsi:.1f} + uptrend", price

    return False, "No signal", price


def generate_proposal(symbol="MSTR"):
    """Generate a trade proposal for E.M. to send to Lawson."""
    signal, reason, price = check_entry_signal(symbol)

    if not signal:
        return None

    # Calculate target strikes
    deep_otm_strike = round(price * 1.40, -5) or round(price * 1.40)  # ~40% OTM
    fallback_strike = round(price * 1.20, -5) or round(price * 1.20)  # ~20% OTM
    hedge_strike = round(price * 0.80, -5) or round(price * 0.80)  # 20% OTM put

    proposal = {
        "system": "system1",
        "version": "v8",
        "ticker": symbol,
        "action": "BUY",
        "signal": reason,
        "price": price,
        "budget": CAPITAL * BUDGET_CALLS,
        "targets": {
            "primary_strike": deep_otm_strike,
            "secondary_strike": fallback_strike,
            "hedge_strike": hedge_strike,
        },
        "rules": {
            "10x_sell": "50% at 10x entry cost",
            "20x_sell": "25% more at 20x",
            "rsi_exit": f"Full exit at RSI > {RSI_EXIT}",
            "losers": "Let expire worthless",
        },
        "timestamp": datetime.now().isoformat(),
    }

    log(f"PROPOSAL GENERATED: {symbol} — {reason}")
    return proposal


def execute(ib, proposal):
    """Execute approved System 1 v8 trade via IBKR."""
    symbol = proposal["ticker"]
    price = proposal["price"]
    budget = proposal["budget"]

    log(f"EXECUTING System 1 v8: {symbol} @ ${price:.2f}")

    # Get option chain from IBKR
    stock = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(stock)

    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    if not chains:
        log("ERROR: No option chains found")
        return {"status": "error", "reason": "No option chains"}

    chain = chains[0]

    # Find suitable expiry (90-365 DTE)
    from datetime import timedelta
    today = datetime.now().date()
    valid_expiries = [
        e for e in sorted(chain.expirations)
        if MIN_DTE < (datetime.strptime(e, "%Y%m%d").date() - today).days < MAX_DTE
    ]

    if not valid_expiries:
        log("ERROR: No valid expirations found")
        return {"status": "error", "reason": "No valid expirations"}

    expiry = valid_expiries[-1]  # Furthest out
    log(f"Selected expiry: {expiry}")

    # Find deep OTM strikes
    strikes = sorted(chain.strikes)
    deep_otm = [s for s in strikes if price * OTM_LOW <= s <= price * OTM_HIGH]

    if not deep_otm:
        deep_otm = [s for s in strikes if price * OTM_FALLBACK_LOW <= s <= price * OTM_FALLBACK_HIGH]

    if not deep_otm:
        log("ERROR: No suitable OTM strikes found")
        return {"status": "error", "reason": "No OTM strikes"}

    results = []

    # Buy primary calls (60% of budget)
    strike1 = deep_otm[0]
    contract1 = Option(symbol, expiry, strike1, "C", "SMART")
    ib.qualifyContracts(contract1)
    ticker1 = ib.reqMktData(contract1)
    ib.sleep(3)
    ask1 = ticker1.ask if ticker1.ask == ticker1.ask else 5.0
    ib.cancelMktData(contract1)

    if ask1 > 0:
        qty1 = max(1, int((budget * 0.60) / (ask1 * 100)))
        order1 = MarketOrder("BUY", qty1)
        trade1 = ib.placeOrder(contract1, order1)
        ib.sleep(3)
        cost1 = ask1 * 100 * qty1
        results.append({"strike": strike1, "qty": qty1, "cost": cost1, "type": "primary"})
        log(f"PRIMARY: {qty1}x {strike1}C @ ${ask1:.2f} | Cost: ${cost1:,.0f}")

        # Constitution v44.0 — MANDATORY trailing stop at entry
        from stop_utils import place_trailing_stop
        stop_result = place_trailing_stop(ib, contract1, qty1, ask1, "system1_v8", log)
        results[-1]["trailing_stop"] = stop_result

    # Buy secondary calls further OTM (30% of budget)
    if len(deep_otm) > 2:
        strike2 = deep_otm[len(deep_otm) // 2]
        contract2 = Option(symbol, expiry, strike2, "C", "SMART")
        ib.qualifyContracts(contract2)
        ticker2 = ib.reqMktData(contract2)
        ib.sleep(3)
        ask2 = ticker2.ask if ticker2.ask == ticker2.ask else 3.0
        ib.cancelMktData(contract2)

        if ask2 > 0:
            qty2 = max(1, int((budget * 0.30) / (ask2 * 100)))
            order2 = MarketOrder("BUY", qty2)
            trade2 = ib.placeOrder(contract2, order2)
            ib.sleep(3)
            cost2 = ask2 * 100 * qty2
            results.append({"strike": strike2, "qty": qty2, "cost": cost2, "type": "secondary"})
            log(f"SECONDARY: {qty2}x {strike2}C @ ${ask2:.2f} | Cost: ${cost2:,.0f}")

            # Constitution v44.0 — MANDATORY trailing stop at entry
            from stop_utils import place_trailing_stop
            stop_result = place_trailing_stop(ib, contract2, qty2, ask2, "system1_v8", log)
            results[-1]["trailing_stop"] = stop_result

    # Buy hedge puts
    hedge_strikes = [s for s in strikes if price * 0.70 <= s <= price * 0.85]
    if hedge_strikes:
        hedge_strike = hedge_strikes[-1]
        hedge_contract = Option(symbol, expiry, hedge_strike, "P", "SMART")
        ib.qualifyContracts(hedge_contract)
        ticker_h = ib.reqMktData(hedge_contract)
        ib.sleep(3)
        ask_h = ticker_h.ask if ticker_h.ask == ticker_h.ask else 2.0
        ib.cancelMktData(hedge_contract)

        if ask_h > 0:
            remaining_cash = budget - sum(r["cost"] for r in results)
            hedge_qty = max(1, int((remaining_cash * BUDGET_HEDGE) / (ask_h * 100)))
            order_h = MarketOrder("BUY", hedge_qty)
            trade_h = ib.placeOrder(hedge_contract, order_h)
            ib.sleep(3)
            results.append({"strike": hedge_strike, "qty": hedge_qty, "type": "hedge"})
            log(f"HEDGE: {hedge_qty}x {hedge_strike}P @ ${ask_h:.2f}")

            # Constitution v44.0 — MANDATORY trailing stop at entry
            from stop_utils import place_trailing_stop
            stop_result = place_trailing_stop(ib, hedge_contract, hedge_qty, ask_h, "system1_v8", log)
            results[-1]["trailing_stop"] = stop_result

    # Save positions
    total_cost = sum(r["cost"] for r in results if "cost" in r)
    position_data = {
        "system": "system1_v8",
        "symbol": symbol,
        "entry_date": datetime.now().isoformat(),
        "entry_price": price,
        "total_cost": total_cost,
        "legs": results,
        "expiry": expiry,
        "10x_triggered": False,
        "20x_triggered": False,
    }

    save_position(position_data)

    # Notify via Telegram
    legs_msg = "\n".join(
        f"  {'🎯' if r['type']=='primary' else '🎲' if r['type']=='secondary' else '🛡️'} "
        f"${r['strike']}{'C' if r['type']!='hedge' else 'P'} x{r['qty']}"
        for r in results
    )

    telegram.send(
        f"🎰 *System 1 v8 EXECUTED*\n\n"
        f"Ticker: {symbol} @ ${price:.2f}\n"
        f"Signal: {proposal['signal']}\n\n"
        f"Lottery Tickets:\n{legs_msg}\n\n"
        f"Total Cost: ${total_cost:,.0f}\n"
        f"Expiry: {expiry}\n\n"
        f"10x rule active. Let it ride. 🚀"
    )

    # Start 10x monitor
    threading.Thread(target=monitor_10x, args=(position_data,), daemon=True).start()

    return {"status": "executed", "legs": results, "total_cost": total_cost}


def monitor_10x(position):
    """Monitor for 10x and 20x exits."""
    log("10x/20x monitor started")
    ib = IB()
    ib.connect("127.0.0.1", 7496, clientId=15)

    entry_cost = position["total_cost"]

    while True:
        try:
            # Check current value of call positions
            total_value = 0
            for leg in position["legs"]:
                if leg["type"] == "hedge":
                    continue
                contract = Option(
                    position["symbol"], position["expiry"],
                    leg["strike"], "C", "SMART"
                )
                ib.qualifyContracts(contract)
                ticker = ib.reqMktData(contract)
                ib.sleep(3)
                current = ticker.last if ticker.last == ticker.last else ticker.close
                if current and current == current:
                    total_value += current * 100 * leg["qty"]
                ib.cancelMktData(contract)

            log(f"10x check: Value ${total_value:,.0f} vs Entry ${entry_cost:,.0f} ({total_value/entry_cost:.1f}x)")

            # 10x rule
            if not position["10x_triggered"] and entry_cost > 0 and total_value >= entry_cost * 10:
                for leg in position["legs"]:
                    if leg["type"] == "hedge":
                        continue
                    sell_qty = max(1, int(leg["qty"] * TEN_X_SELL_PCT))
                    contract = Option(
                        position["symbol"], position["expiry"],
                        leg["strike"], "C", "SMART"
                    )
                    ib.qualifyContracts(contract)
                    order = MarketOrder("SELL", sell_qty)
                    ib.placeOrder(contract, order)
                    ib.sleep(3)
                    log(f"10x TRIGGERED: Sold {sell_qty}x {leg['strike']}C")

                position["10x_triggered"] = True
                profit = total_value - entry_cost
                telegram.send(
                    f"🔥 *10x RULE TRIGGERED!*\n\n"
                    f"{position['symbol']} lottery hit 10x!\n"
                    f"Entry: ${entry_cost:,.0f} → Value: ${total_value:,.0f}\n"
                    f"Sold 50% — locked ${profit/2:,.0f} profit\n"
                    f"Remainder riding free. 🚀"
                )
                save_position(position)

            # 20x moonshot
            if position["10x_triggered"] and not position.get("20x_triggered") and total_value >= entry_cost * 20:
                for leg in position["legs"]:
                    if leg["type"] == "hedge":
                        continue
                    sell_qty = max(1, int(leg["qty"] * TWENTY_X_SELL_PCT))
                    contract = Option(
                        position["symbol"], position["expiry"],
                        leg["strike"], "C", "SMART"
                    )
                    ib.qualifyContracts(contract)
                    order = MarketOrder("SELL", sell_qty)
                    ib.placeOrder(contract, order)
                    ib.sleep(3)
                    log(f"20x MOONSHOT: Sold {sell_qty}x {leg['strike']}C")

                position["20x_triggered"] = True
                telegram.send(
                    f"🌙 *20x MOONSHOT!*\n\n"
                    f"{position['symbol']} hit 20x entry!\n"
                    f"Sold 25% more. Rest riding to the moon.\n"
                    f"Value: ${total_value:,.0f}"
                )
                save_position(position)

        except Exception as e:
            log(f"Monitor error: {e}")

        time.sleep(300)  # Check every 5 minutes


def save_position(pos):
    positions = load_positions()
    # Update existing or append
    updated = False
    for i, p in enumerate(positions):
        if p.get("entry_date") == pos.get("entry_date"):
            positions[i] = pos
            updated = True
            break
    if not updated:
        positions.append(pos)
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def load_positions():
    if not os.path.exists(POSITIONS_FILE):
        return []
    with open(POSITIONS_FILE) as f:
        return json.load(f)


if __name__ == "__main__":
    print("System 1 v8 — Deep OTM Lottery")
    print("Checking entry signal...")
    signal, reason, price = check_entry_signal("MSTR")
    print(f"Signal: {signal} — {reason} @ ${price:.2f}")
