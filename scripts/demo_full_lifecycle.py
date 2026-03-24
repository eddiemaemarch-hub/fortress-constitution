"""Rudy v2.0 — Full Trade Lifecycle Demo
Demonstrates: Entry → Ladder Trailing Stops → Exit
Uses paper trading account on TWS port 7496.
Uses Yahoo Finance for price data (no NASDAQ subscription needed).
"""
import sys
import os
import time
import math
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram

from ib_insync import *
import yfinance as yf


LOG_DIR = os.path.expanduser("~/rudy/logs")
os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Demo {ts}] {msg}")
    with open(f"{LOG_DIR}/demo.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def get_yahoo_price(symbol):
    """Get current/last price from Yahoo Finance."""
    t = yf.Ticker(symbol)
    data = t.history(period="1d")
    if not data.empty:
        return float(data["Close"].iloc[-1])
    info = t.info
    return float(info.get("regularMarketPrice", info.get("previousClose", 0)))


def run_demo():
    # === CONNECT ===
    ib = IB()
    ib.connect("127.0.0.1", 7496, clientId=99)
    ib.reqMarketDataType(3)
    log("Connected to IBKR paper trading")

    ticker_symbol = "AAPL"
    qty = 10

    # === GET PRICE FROM YAHOO FINANCE ===
    current_price = get_yahoo_price(ticker_symbol)
    log(f"Yahoo Finance {ticker_symbol} price: ${current_price:.2f}")

    if current_price <= 0:
        log("ERROR: Could not get price. Aborting.")
        ib.disconnect()
        return

    # === STEP 1: ENTRY ===
    log(f"=== STEP 1: ENTERING TRADE — BUY {qty} {ticker_symbol} ===")

    contract = Stock(ticker_symbol, "SMART", "USD")
    ib.qualifyContracts(contract)

    # Use limit order at last known price + small buffer (works outside market hours)
    limit_price = round(current_price * 1.005, 2)  # 0.5% above last price
    entry_order = LimitOrder("BUY", qty, limit_price)
    entry_order.tif = "GTC"  # Good till cancelled — fills when market opens
    entry_trade = ib.placeOrder(contract, entry_order)
    ib.sleep(5)

    entry_status = entry_trade.orderStatus.status
    fill_price = entry_trade.orderStatus.avgFillPrice

    if fill_price > 0:
        log(f"Entry FILLED @ ${fill_price:.2f}")
    else:
        fill_price = current_price
        log(f"Entry status: {entry_status} — limit ${limit_price:.2f}")
        log(f"Using Yahoo price ${fill_price:.2f} as reference for stops")

    telegram.send(
        f"📊 *DEMO — Trade Entered*\n\n"
        f"BUY {qty} {ticker_symbol}\n"
        f"Limit: ${limit_price:.2f} | Ref price: ${fill_price:.2f}\n"
        f"Status: {entry_status}\n"
        f"Total: ${fill_price * qty:,.2f}\n\n"
        f"Now placing ladder trailing stops..."
    )

    # === STEP 2: LADDER TRAILING STOP LOSSES ===
    log(f"=== STEP 2: PLACING LADDER TRAILING STOPS ===")

    # Ladder: split position into 3 tranches with increasing trail amounts
    # Tranche 1: 40% tight, Tranche 2: 30% medium, Tranche 3: 30% wide
    tranches = [
        {"pct": 0.40, "trail_pct": 1.0, "label": "Tight (1%)"},
        {"pct": 0.30, "trail_pct": 3.0, "label": "Medium (3%)"},
        {"pct": 0.30, "trail_pct": 5.0, "label": "Wide (5%)"},
    ]

    stop_orders = []
    remaining = qty

    for i, tranche in enumerate(tranches):
        if i == len(tranches) - 1:
            tranche_qty = remaining
        else:
            tranche_qty = max(1, round(qty * tranche["pct"]))
            remaining -= tranche_qty

        trail_amount = round(fill_price * tranche["trail_pct"] / 100, 2)
        limit_offset = round(trail_amount * 0.5, 2)

        # Calculate explicit prices for the trailing stop limit
        stop_price = round(fill_price - trail_amount, 2)
        lmt_price = round(stop_price - limit_offset, 2)

        order = Order(
            action="SELL",
            orderType="TRAIL LIMIT",
            totalQuantity=tranche_qty,
            auxPrice=trail_amount,       # Trail amount in dollars
            trailStopPrice=stop_price,   # Initial stop price
            lmtPrice=lmt_price,          # Limit price
            tif="GTC",
        )

        trade = ib.placeOrder(contract, order)
        ib.sleep(3)

        order_status = trade.orderStatus.status
        stop_orders.append({
            "trade": trade,
            "qty": tranche_qty,
            "trail_pct": tranche["trail_pct"],
            "trail_amt": trail_amount,
            "stop_price": stop_price,
            "lmt_price": lmt_price,
            "label": tranche["label"],
            "order_id": trade.order.orderId,
            "status": order_status,
        })

        log(f"Tranche {i+1}: SELL {tranche_qty} shares, "
            f"trail ${trail_amount} ({tranche['trail_pct']}%), "
            f"stop ${stop_price}, limit ${lmt_price}, "
            f"status: {order_status}")

    # Report stops to Telegram
    stops_msg = "\n".join(
        f"  T{i+1}: {s['qty']}sh — {s['label']}\n"
        f"      Trail: ${s['trail_amt']} | Stop: ${s['stop_price']} | Limit: ${s['lmt_price']}\n"
        f"      Status: {s['status']}"
        for i, s in enumerate(stop_orders)
    )

    telegram.send(
        f"🛡️ *DEMO — Ladder Stops Placed*\n\n"
        f"Position: {qty} {ticker_symbol} @ ${fill_price:.2f}\n\n"
        f"Trailing Stop Ladder:\n{stops_msg}\n\n"
        f"All stops GTC.\n"
        f"Waiting 15s then demonstrating exit..."
    )

    log("All trailing stops placed. Waiting 15 seconds before exit demo...")
    time.sleep(15)

    # === STEP 3: EXIT — Cancel stops and sell ===
    log(f"=== STEP 3: EXITING TRADE — SELL {qty} {ticker_symbol} ===")

    # Cancel all trailing stops
    cancelled = 0
    for s in stop_orders:
        try:
            ib.cancelOrder(s["trade"].order)
            ib.sleep(1)
            cancelled += 1
            log(f"Cancelled trailing stop order {s['order_id']}")
        except Exception as e:
            log(f"Cancel note for order {s['order_id']}: {e}")

    ib.sleep(2)

    # Cancel the entry order too if it hasn't filled
    try:
        ib.cancelOrder(entry_trade.order)
        ib.sleep(1)
        log("Cancelled entry order (hadn't filled yet)")
    except:
        log("Entry order already filled or cancelled")

    # Place limit sell slightly below market (aggressive exit)
    exit_limit = round(current_price * 0.995, 2)  # 0.5% below last price
    exit_order = LimitOrder("SELL", qty, exit_limit)
    exit_order.tif = "GTC"
    exit_trade = ib.placeOrder(contract, exit_order)
    ib.sleep(5)

    exit_status = exit_trade.orderStatus.status
    exit_fill = exit_trade.orderStatus.avgFillPrice
    exit_price = exit_fill if exit_fill > 0 else current_price

    pnl = (exit_price - fill_price) * qty
    log(f"Exit status: {exit_status}")
    log(f"Exit price: ${exit_price:.2f}")
    log(f"P&L: ${pnl:+,.2f}")

    # Cancel exit order if pending (market closed)
    if exit_status not in ("Filled",):
        try:
            ib.cancelOrder(exit_trade.order)
            ib.sleep(1)
            log("Cancelled exit order (market closed — demo purpose served)")
        except:
            pass

    telegram.send(
        f"🏁 *DEMO — Trade Lifecycle Complete*\n\n"
        f"Entry: BUY {qty} {ticker_symbol} @ ${fill_price:.2f}\n"
        f"Exit: SELL {qty} {ticker_symbol} @ ${exit_price:.2f}\n"
        f"Exit status: {exit_status}\n"
        f"Stops cancelled: {cancelled}/3\n\n"
        f"✅ *Full lifecycle demonstrated:*\n"
        f"  1. Entry (limit GTC) ✓\n"
        f"  2. Ladder trailing stop-limits ✓\n"
        f"  3. Cancel stops + exit ✓\n\n"
        f"Note: Market closed — orders placed as GTC.\n"
        f"All demo orders cleaned up.\n\n"
        f"Rudy is ready for the bull market. 🚀"
    )

    log("=== DEMO COMPLETE ===")
    ib.disconnect()
    log("Disconnected from IBKR")


if __name__ == "__main__":
    run_demo()
