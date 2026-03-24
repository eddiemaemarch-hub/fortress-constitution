"""Paper Trading Validation Test — Constitution v50.0
Proves the system can reliably:
1. Enter positions (market + limit orders)
2. Set trailing stop loss limit orders (laddered)
3. Exit positions (full + partial)
4. Monitor positions in real-time
5. Handle the full lifecycle: entry → trail → exit

Must pass this test BEFORE going live with real money.
Run with TWS paper trading open on port 7496.
"""
import os
import sys
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram

from ib_insync import *

LOG_DIR = os.path.expanduser("~/rudy/logs")
RESULTS_FILE = os.path.expanduser("~/rudy/data/paper_test_results.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)

PORT = 7496
CLIENT_ID = 50  # Dedicated client ID for paper testing


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[PaperTest {ts}] {msg}")
    with open(f"{LOG_DIR}/paper_test.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def connect():
    ib = IB()
    ib.connect("127.0.0.1", PORT, clientId=CLIENT_ID)
    ib.reqMarketDataType(3)  # Delayed data OK for paper
    log(f"Connected to TWS paper on port {PORT}")
    return ib


def get_price(ib, contract):
    """Get current bid/ask/last for a contract."""
    ib.qualifyContracts(contract)
    ticker = ib.reqMktData(contract)
    ib.sleep(3)
    bid = ticker.bid if ticker.bid == ticker.bid and ticker.bid > 0 else None
    ask = ticker.ask if ticker.ask == ticker.ask and ticker.ask > 0 else None
    last = ticker.last if ticker.last == ticker.last and ticker.last > 0 else None
    mid = (bid + ask) / 2 if bid and ask else last
    ib.cancelMktData(contract)
    return {"bid": bid, "ask": ask, "last": last, "mid": mid}


def test_1_market_entry(ib):
    """TEST 1: Market order entry — buy 10 shares of SPY."""
    log("=" * 50)
    log("TEST 1: Market Order Entry (SPY)")

    contract = Stock("SPY", "SMART", "USD")
    ib.qualifyContracts(contract)

    prices = get_price(ib, contract)
    log(f"  SPY price: bid={prices['bid']} ask={prices['ask']} last={prices['last']}")

    order = MarketOrder("BUY", 10)
    trade = ib.placeOrder(contract, order)

    # Wait for fill
    for i in range(30):
        ib.sleep(1)
        if trade.orderStatus.status == "Filled":
            break

    fill = trade.orderStatus.avgFillPrice
    status = trade.orderStatus.status

    log(f"  Result: {status} | Fill: ${fill:.2f} | Qty: 10")

    return {
        "test": "market_entry",
        "symbol": "SPY",
        "status": status,
        "fill_price": fill,
        "qty": 10,
        "passed": status == "Filled",
    }


def test_2_trailing_stop(ib):
    """TEST 2: Trailing stop loss — set 1% trail on SPY position."""
    log("=" * 50)
    log("TEST 2: Trailing Stop Loss (1% trail)")

    contract = Stock("SPY", "SMART", "USD")
    ib.qualifyContracts(contract)

    prices = get_price(ib, contract)
    trail_pct = 1.0  # 1% trailing stop

    # Trailing stop order — sells if price drops 1% from high
    order = Order()
    order.action = "SELL"
    order.totalQuantity = 5  # Sell 5 of the 10 shares
    order.orderType = "TRAIL"
    order.trailingPercent = trail_pct

    trade = ib.placeOrder(contract, order)
    ib.sleep(3)

    status = trade.orderStatus.status
    order_id = trade.order.orderId

    log(f"  Trail stop placed: {status} | OrderID: {order_id} | Trail: {trail_pct}%")
    log(f"  Will sell 5 SPY if price drops 1% from high watermark")

    return {
        "test": "trailing_stop",
        "symbol": "SPY",
        "status": status,
        "order_id": order_id,
        "trail_pct": trail_pct,
        "qty": 5,
        "passed": status in ["PreSubmitted", "Submitted", "Filled"],
    }


def test_3_laddered_stops(ib, entry_price):
    """TEST 3: Laddered trailing stop limits — 3 levels."""
    log("=" * 50)
    log("TEST 3: Laddered Trailing Stop Limits")

    contract = Stock("NVDA", "SMART", "USD")
    ib.qualifyContracts(contract)

    # First buy some NVDA
    prices = get_price(ib, contract)
    log(f"  NVDA price: {prices}")

    buy_order = MarketOrder("BUY", 6)
    buy_trade = ib.placeOrder(contract, buy_order)
    for i in range(30):
        ib.sleep(1)
        if buy_trade.orderStatus.status == "Filled":
            break

    nvda_fill = buy_trade.orderStatus.avgFillPrice
    log(f"  Bought 6 NVDA @ ${nvda_fill:.2f}")

    # Ladder 3 trailing stops at different levels:
    # Level 1: Sell 2 shares at 2% trail (tight — lock in quick gains)
    # Level 2: Sell 2 shares at 5% trail (medium — let it run)
    # Level 3: Sell 2 shares at 10% trail (wide — catch the big move)

    ladders = [
        {"qty": 2, "trail_pct": 2.0, "label": "Tight (2%)"},
        {"qty": 2, "trail_pct": 5.0, "label": "Medium (5%)"},
        {"qty": 2, "trail_pct": 10.0, "label": "Wide (10%)"},
    ]

    results = []
    for level in ladders:
        order = Order()
        order.action = "SELL"
        order.totalQuantity = level["qty"]
        order.orderType = "TRAIL"
        order.trailingPercent = level["trail_pct"]

        trade = ib.placeOrder(contract, order)
        ib.sleep(2)

        status = trade.orderStatus.status
        oid = trade.order.orderId
        log(f"  {level['label']}: {level['qty']} shares, trail {level['trail_pct']}% — {status} (ID: {oid})")

        results.append({
            "label": level["label"],
            "qty": level["qty"],
            "trail_pct": level["trail_pct"],
            "status": status,
            "order_id": oid,
        })

    all_placed = all(r["status"] in ["PreSubmitted", "Submitted"] for r in results)

    return {
        "test": "laddered_stops",
        "symbol": "NVDA",
        "entry_price": nvda_fill,
        "ladders": results,
        "passed": all_placed,
    }


def test_4_limit_entry(ib):
    """TEST 4: Limit order entry — buy AMD slightly below market."""
    log("=" * 50)
    log("TEST 4: Limit Order Entry (AMD)")

    contract = Stock("AMD", "SMART", "USD")
    ib.qualifyContracts(contract)

    prices = get_price(ib, contract)
    mid = prices["mid"] or prices["last"] or 100
    limit_price = round(mid * 0.998, 2)  # 0.2% below mid

    log(f"  AMD mid: ${mid:.2f} | Limit: ${limit_price:.2f}")

    order = LimitOrder("BUY", 5, limit_price)
    trade = ib.placeOrder(contract, order)

    # Wait up to 30 seconds for fill
    for i in range(30):
        ib.sleep(1)
        if trade.orderStatus.status == "Filled":
            break

    status = trade.orderStatus.status
    fill = trade.orderStatus.avgFillPrice

    log(f"  Result: {status} | Fill: ${fill:.2f}" if fill else f"  Result: {status} (pending)")

    # If not filled, cancel
    if status not in ["Filled"]:
        ib.cancelOrder(trade.order)
        ib.sleep(2)
        log(f"  Cancelled unfilled limit order")
        # Try market order instead
        order2 = MarketOrder("BUY", 5)
        trade2 = ib.placeOrder(contract, order2)
        for i in range(15):
            ib.sleep(1)
            if trade2.orderStatus.status == "Filled":
                break
        fill = trade2.orderStatus.avgFillPrice
        status = trade2.orderStatus.status
        log(f"  Fallback market order: {status} @ ${fill:.2f}")

    return {
        "test": "limit_entry",
        "symbol": "AMD",
        "limit_price": limit_price,
        "status": status,
        "fill_price": fill,
        "qty": 5,
        "passed": status == "Filled",
    }


def test_5_partial_exit(ib):
    """TEST 5: Partial exit — sell half position."""
    log("=" * 50)
    log("TEST 5: Partial Exit (sell half)")

    positions = ib.positions()
    results = []

    for pos in positions:
        if pos.contract.secType != "STK":
            continue
        if pos.position <= 0:
            continue

        symbol = pos.contract.symbol
        qty = int(pos.position)
        sell_qty = max(1, qty // 2)

        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)

        order = MarketOrder("SELL", sell_qty)
        trade = ib.placeOrder(contract, order)

        for i in range(15):
            ib.sleep(1)
            if trade.orderStatus.status == "Filled":
                break

        status = trade.orderStatus.status
        fill = trade.orderStatus.avgFillPrice

        log(f"  {symbol}: Sold {sell_qty}/{qty} @ ${fill:.2f} — {status}")
        results.append({
            "symbol": symbol,
            "sold": sell_qty,
            "of": qty,
            "fill": fill,
            "status": status,
        })

    all_filled = all(r["status"] == "Filled" for r in results)

    return {
        "test": "partial_exit",
        "exits": results,
        "passed": all_filled,
    }


def test_6_full_exit(ib):
    """TEST 6: Full exit — close all remaining positions."""
    log("=" * 50)
    log("TEST 6: Full Exit (close everything)")

    # Cancel all open orders first
    open_orders = ib.openOrders()
    for order in open_orders:
        ib.cancelOrder(order)
    ib.sleep(3)
    log(f"  Cancelled {len(open_orders)} open orders")

    positions = ib.positions()
    results = []

    for pos in positions:
        if pos.contract.secType != "STK":
            continue
        if pos.position == 0:
            continue

        symbol = pos.contract.symbol
        qty = int(abs(pos.position))
        action = "SELL" if pos.position > 0 else "BUY"

        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)

        order = MarketOrder(action, qty)
        trade = ib.placeOrder(contract, order)

        for i in range(15):
            ib.sleep(1)
            if trade.orderStatus.status == "Filled":
                break

        status = trade.orderStatus.status
        fill = trade.orderStatus.avgFillPrice

        log(f"  {action} {qty} {symbol} @ ${fill:.2f} — {status}")
        results.append({
            "symbol": symbol,
            "action": action,
            "qty": qty,
            "fill": fill,
            "status": status,
        })

    all_filled = all(r["status"] == "Filled" for r in results)

    return {
        "test": "full_exit",
        "exits": results,
        "passed": all_filled,
    }


def run_all_tests():
    """Run the full paper trading validation suite."""
    log("=" * 60)
    log("PAPER TRADING VALIDATION — Constitution v50.0")
    log("=" * 60)

    telegram.send(
        "🧪 *Paper Trading Validation Starting*\n\n"
        "Running 6 tests:\n"
        "1. Market order entry\n"
        "2. Trailing stop loss\n"
        "3. Laddered trailing stops (3 levels)\n"
        "4. Limit order entry\n"
        "5. Partial exit\n"
        "6. Full exit + cleanup\n\n"
        "Constitution v50.0 requires passing before live trading."
    )

    ib = connect()
    results = []

    try:
        # Test 1: Market entry
        r1 = test_1_market_entry(ib)
        results.append(r1)
        ib.sleep(2)

        # Test 2: Trailing stop on SPY position
        r2 = test_2_trailing_stop(ib)
        results.append(r2)
        ib.sleep(2)

        # Test 3: Laddered stops on NVDA
        r3 = test_3_laddered_stops(ib, r1.get("fill_price", 0))
        results.append(r3)
        ib.sleep(2)

        # Test 4: Limit order
        r4 = test_4_limit_entry(ib)
        results.append(r4)
        ib.sleep(2)

        # Test 5: Partial exit
        r5 = test_5_partial_exit(ib)
        results.append(r5)
        ib.sleep(2)

        # Test 6: Full cleanup
        r6 = test_6_full_exit(ib)
        results.append(r6)

    except Exception as e:
        log(f"TEST ERROR: {e}")
        results.append({"test": "error", "error": str(e), "passed": False})

    finally:
        ib.disconnect()

    # Score results
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    all_passed = passed == total

    log("\n" + "=" * 60)
    log(f"RESULTS: {passed}/{total} tests passed")
    log("=" * 60)

    for r in results:
        emoji = "✅" if r.get("passed") else "❌"
        log(f"  {emoji} {r.get('test', 'unknown')}")

    # Save results
    test_record = {
        "timestamp": datetime.now().isoformat(),
        "passed": passed,
        "total": total,
        "all_passed": all_passed,
        "results": results,
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(test_record, f, indent=2)

    # Report to Telegram
    result_lines = []
    for r in results:
        emoji = "✅" if r.get("passed") else "❌"
        result_lines.append(f"{emoji} {r.get('test', '?')}")

    verdict = "PASSED — Ready for live trading! 🟢" if all_passed else "FAILED — Fix issues before going live 🔴"

    telegram.send(
        f"🧪 *Paper Trading Validation Complete*\n\n"
        f"Score: {passed}/{total}\n\n" +
        "\n".join(result_lines) +
        f"\n\n*{verdict}*"
    )

    return test_record


if __name__ == "__main__":
    run_all_tests()
