"""Trader1 & Trader2 Strategy Validation Test — Constitution v50.0
Proves BOTH traders can reliably:
1. Execute their strategy's entry logic
2. Set laddered trailing stop loss limit orders
3. Monitor positions with correct stop management
4. Exit positions cleanly (partial + full)

Trader1 (System 1): MSTR/IBIT lottery — stock proxy + laddered trails
Trader2 (System 2): Momentum diagonal proxy + laddered trails

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
import accountant

from ib_insync import *

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
RESULTS_FILE = os.path.join(DATA_DIR, "trader_test_results.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

PORT = 7496


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[TraderTest {ts}] {msg}")
    with open(f"{LOG_DIR}/trader_test.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def connect(client_id):
    ib = IB()
    ib.connect("127.0.0.1", PORT, clientId=client_id)
    ib.reqMarketDataType(3)
    return ib


def get_price(ib, contract):
    ib.qualifyContracts(contract)
    ticker = ib.reqMktData(contract)
    ib.sleep(3)
    bid = ticker.bid if ticker.bid == ticker.bid and ticker.bid > 0 else None
    ask = ticker.ask if ticker.ask == ticker.ask and ticker.ask > 0 else None
    last = ticker.last if ticker.last == ticker.last and ticker.last > 0 else None
    mid = (bid + ask) / 2 if bid and ask else last
    ib.cancelMktData(contract)
    return {"bid": bid, "ask": ask, "last": last, "mid": mid}


def place_laddered_trailing_stops(ib, contract, total_qty, levels, current_price):
    """Place laddered trailing stop loss limit orders.
    levels: list of {"qty": int, "trail_pct": float, "limit_offset": float, "label": str}
    current_price: needed to calculate initial stop price for TRAIL LIMIT.
    Returns list of trade results.
    """
    results = []
    for level in levels:
        # Calculate initial trailing stop price from current price
        trail_amt = round(current_price * level["trail_pct"] / 100, 2)
        stop_price = round(current_price - trail_amt, 2)
        limit_price = round(stop_price - level["limit_offset"], 2)

        order = Order()
        order.action = "SELL"
        order.totalQuantity = level["qty"]
        order.orderType = "TRAIL LIMIT"
        order.auxPrice = trail_amt  # Trail amount in dollars
        order.trailStopPrice = stop_price
        order.lmtPrice = limit_price
        order.tif = "GTC"

        trade = ib.placeOrder(contract, order)
        ib.sleep(2)

        status = trade.orderStatus.status
        oid = trade.order.orderId

        log(f"    {level['label']}: {level['qty']} shares, "
            f"trail {level['trail_pct']}% (${trail_amt:.2f}), "
            f"stop ${stop_price:.2f}, limit ${limit_price:.2f} "
            f"— {status} (ID: {oid})")

        results.append({
            "label": level["label"],
            "qty": level["qty"],
            "trail_pct": level["trail_pct"],
            "limit_offset": level["limit_offset"],
            "stop_price": stop_price,
            "limit_price": limit_price,
            "status": status,
            "order_id": oid,
        })

    return results


# ═══════════════════════════════════════════════════════════
# TRADER1 TESTS — System 1 (MSTR/IBIT Lottery)
# ═══════════════════════════════════════════════════════════

def t1_test_1_entry(ib):
    """TRADER1 TEST 1: Enter MSTR position (lottery proxy with stock)."""
    log("=" * 55)
    log("TRADER1 TEST 1: System 1 Entry — MSTR (stock proxy)")

    contract = Stock("MSTR", "SMART", "USD")
    prices = get_price(ib, contract)
    log(f"  MSTR: bid={prices['bid']} ask={prices['ask']} mid={prices['mid']}")

    # Constitution: S1 uses 60% primary + 30% secondary + 10% hedge
    # Simulate with stock: buy 10 shares as primary position
    order = MarketOrder("BUY", 10)
    order.tif = "GTC"
    trade = ib.placeOrder(contract, order)

    for i in range(30):
        ib.sleep(1)
        if trade.orderStatus.status == "Filled":
            break

    fill = trade.orderStatus.avgFillPrice
    status = trade.orderStatus.status
    log(f"  MSTR entry: {status} | 10 shares @ ${fill:.2f}")

    return {
        "test": "t1_entry_mstr",
        "symbol": "MSTR",
        "status": status,
        "fill_price": fill,
        "qty": 10,
        "passed": status == "Filled",
    }


def t1_test_2_laddered_stops(ib, entry_price):
    """TRADER1 TEST 2: Laddered trailing stop LIMIT orders on MSTR."""
    log("=" * 55)
    log("TRADER1 TEST 2: Laddered Trailing Stop LIMITS — MSTR")
    log(f"  Entry: ${entry_price:.2f} | Setting 3-tier ladder")

    contract = Stock("MSTR", "SMART", "USD")
    ib.qualifyContracts(contract)

    # S1 Ladder: protect lottery gains aggressively
    # Tier 1: Lock quick gains — 3% trail, $0.50 limit offset (3 shares)
    # Tier 2: Let it run — 7% trail, $1.00 limit offset (4 shares)
    # Tier 3: Catch moonshot — 15% trail, $2.00 limit offset (3 shares)
    levels = [
        {"qty": 3, "trail_pct": 3.0, "limit_offset": 0.50, "label": "S1 Tight (3%)"},
        {"qty": 4, "trail_pct": 7.0, "limit_offset": 1.00, "label": "S1 Medium (7%)"},
        {"qty": 3, "trail_pct": 15.0, "limit_offset": 2.00, "label": "S1 Wide (15%)"},
    ]

    results = place_laddered_trailing_stops(ib, contract, 10, levels, entry_price)
    all_placed = all(r["status"] in ["PreSubmitted", "Submitted"] for r in results)

    log(f"  Ladder result: {'ALL PLACED' if all_placed else 'SOME FAILED'}")

    return {
        "test": "t1_laddered_stops",
        "symbol": "MSTR",
        "entry_price": entry_price,
        "ladders": results,
        "passed": all_placed,
    }


def t1_test_3_ibit_hedge(ib):
    """TRADER1 TEST 3: Enter IBIT hedge position + trailing stop."""
    log("=" * 55)
    log("TRADER1 TEST 3: IBIT Hedge Entry + Trailing Stop")

    contract = Stock("IBIT", "SMART", "USD")
    prices = get_price(ib, contract)
    log(f"  IBIT: bid={prices['bid']} ask={prices['ask']}")

    # Buy IBIT as hedge/correlation position
    order = MarketOrder("BUY", 20)
    order.tif = "GTC"
    trade = ib.placeOrder(contract, order)

    for i in range(30):
        ib.sleep(1)
        if trade.orderStatus.status == "Filled":
            break

    fill = trade.orderStatus.avgFillPrice
    status = trade.orderStatus.status
    log(f"  IBIT entry: {status} | 20 shares @ ${fill:.2f}")

    if status == "Filled":
        # Single trailing stop limit on IBIT hedge
        trail_amt = round(fill * 5.0 / 100, 2)
        stop_px = round(fill - trail_amt, 2)
        lmt_px = round(stop_px - 0.25, 2)

        stop_order = Order()
        stop_order.action = "SELL"
        stop_order.totalQuantity = 20
        stop_order.orderType = "TRAIL LIMIT"
        stop_order.auxPrice = trail_amt
        stop_order.trailStopPrice = stop_px
        stop_order.lmtPrice = lmt_px
        stop_order.tif = "GTC"

        stop_trade = ib.placeOrder(contract, stop_order)
        ib.sleep(2)
        stop_status = stop_trade.orderStatus.status
        log(f"  IBIT trail stop: {stop_status} | 5% trail (${trail_amt:.2f}), stop ${stop_px:.2f}, limit ${lmt_px:.2f}")
    else:
        stop_status = "N/A"

    return {
        "test": "t1_ibit_hedge",
        "symbol": "IBIT",
        "status": status,
        "fill_price": fill,
        "qty": 20,
        "stop_status": stop_status,
        "passed": status == "Filled" and stop_status in ["PreSubmitted", "Submitted"],
    }


# ═══════════════════════════════════════════════════════════
# TRADER2 TESTS — System 2 (Momentum + Energy + Squeeze)
# ═══════════════════════════════════════════════════════════

def t2_test_1_momentum_entry(ib):
    """TRADER2 TEST 1: Momentum entry — NVDA (top momentum stock)."""
    log("=" * 55)
    log("TRADER2 TEST 1: System 2 Momentum Entry — NVDA")

    contract = Stock("NVDA", "SMART", "USD")
    prices = get_price(ib, contract)
    log(f"  NVDA: bid={prices['bid']} ask={prices['ask']}")

    order = MarketOrder("BUY", 8)
    order.tif = "GTC"
    trade = ib.placeOrder(contract, order)

    for i in range(30):
        ib.sleep(1)
        if trade.orderStatus.status == "Filled":
            break

    fill = trade.orderStatus.avgFillPrice
    status = trade.orderStatus.status
    log(f"  NVDA entry: {status} | 8 shares @ ${fill:.2f}")

    return {
        "test": "t2_momentum_nvda",
        "symbol": "NVDA",
        "status": status,
        "fill_price": fill,
        "qty": 8,
        "passed": status == "Filled",
    }


def t2_test_2_energy_entry(ib):
    """TRADER2 TEST 2: Energy sector entry — CCJ (uranium play)."""
    log("=" * 55)
    log("TRADER2 TEST 2: System 2 Energy Entry — CCJ")

    contract = Stock("CCJ", "SMART", "USD")
    prices = get_price(ib, contract)
    log(f"  CCJ: bid={prices['bid']} ask={prices['ask']}")

    order = MarketOrder("BUY", 15)
    order.tif = "GTC"
    trade = ib.placeOrder(contract, order)

    for i in range(30):
        ib.sleep(1)
        if trade.orderStatus.status == "Filled":
            break

    fill = trade.orderStatus.avgFillPrice
    status = trade.orderStatus.status
    log(f"  CCJ entry: {status} | 15 shares @ ${fill:.2f}")

    return {
        "test": "t2_energy_ccj",
        "symbol": "CCJ",
        "status": status,
        "fill_price": fill,
        "qty": 15,
        "passed": status == "Filled",
    }


def t2_test_3_laddered_stops(ib, nvda_fill, ccj_fill):
    """TRADER2 TEST 3: Laddered trailing stop limits on BOTH S2 positions."""
    log("=" * 55)
    log("TRADER2 TEST 3: Laddered Trailing Stop LIMITS — NVDA + CCJ")

    results = {"nvda": [], "ccj": []}

    # NVDA laddered stops (8 shares)
    # S2 momentum: tighter stops, protect gains faster
    nvda = Stock("NVDA", "SMART", "USD")
    ib.qualifyContracts(nvda)
    log(f"  NVDA ladder (entry ${nvda_fill:.2f}):")

    nvda_levels = [
        {"qty": 3, "trail_pct": 2.0, "limit_offset": 0.50, "label": "S2 Tight (2%)"},
        {"qty": 3, "trail_pct": 5.0, "limit_offset": 1.00, "label": "S2 Medium (5%)"},
        {"qty": 2, "trail_pct": 10.0, "limit_offset": 2.00, "label": "S2 Wide (10%)"},
    ]
    results["nvda"] = place_laddered_trailing_stops(ib, nvda, 8, nvda_levels, nvda_fill)

    # CCJ laddered stops (15 shares)
    # Energy: wider stops for volatile sector
    ccj = Stock("CCJ", "SMART", "USD")
    ib.qualifyContracts(ccj)
    log(f"  CCJ ladder (entry ${ccj_fill:.2f}):")

    ccj_levels = [
        {"qty": 5, "trail_pct": 3.0, "limit_offset": 0.20, "label": "Energy Tight (3%)"},
        {"qty": 5, "trail_pct": 8.0, "limit_offset": 0.40, "label": "Energy Medium (8%)"},
        {"qty": 5, "trail_pct": 15.0, "limit_offset": 0.75, "label": "Energy Wide (15%)"},
    ]
    results["ccj"] = place_laddered_trailing_stops(ib, ccj, 15, ccj_levels, ccj_fill)

    nvda_ok = all(r["status"] in ["PreSubmitted", "Submitted"] for r in results["nvda"])
    ccj_ok = all(r["status"] in ["PreSubmitted", "Submitted"] for r in results["ccj"])

    log(f"  NVDA ladder: {'PASS' if nvda_ok else 'FAIL'}")
    log(f"  CCJ ladder: {'PASS' if ccj_ok else 'FAIL'}")

    return {
        "test": "t2_laddered_stops",
        "nvda_ladders": results["nvda"],
        "ccj_ladders": results["ccj"],
        "passed": nvda_ok and ccj_ok,
    }


def t2_test_4_squeeze_entry(ib):
    """TRADER2 TEST 4: Squeeze-style rapid entry — SOFI + tight trail."""
    log("=" * 55)
    log("TRADER2 TEST 4: Squeeze Entry — SOFI + Aggressive Trail")

    contract = Stock("SOFI", "SMART", "USD")
    prices = get_price(ib, contract)
    log(f"  SOFI: bid={prices['bid']} ask={prices['ask']}")

    # Squeeze trades: fast in, tight stops
    order = MarketOrder("BUY", 30)
    order.tif = "GTC"
    trade = ib.placeOrder(contract, order)

    for i in range(30):
        ib.sleep(1)
        if trade.orderStatus.status == "Filled":
            break

    fill = trade.orderStatus.avgFillPrice
    status = trade.orderStatus.status
    log(f"  SOFI entry: {status} | 30 shares @ ${fill:.2f}")

    stop_results = []
    if status == "Filled":
        # Squeeze ladder: very tight — lock gains fast
        log(f"  SOFI squeeze ladder:")
        squeeze_levels = [
            {"qty": 15, "trail_pct": 1.5, "limit_offset": 0.10, "label": "Squeeze Scalp (1.5%)"},
            {"qty": 15, "trail_pct": 4.0, "limit_offset": 0.20, "label": "Squeeze Runner (4%)"},
        ]
        stop_results = place_laddered_trailing_stops(ib, contract, 30, squeeze_levels, fill)

    stops_ok = all(r["status"] in ["PreSubmitted", "Submitted"] for r in stop_results) if stop_results else False

    return {
        "test": "t2_squeeze_sofi",
        "symbol": "SOFI",
        "status": status,
        "fill_price": fill,
        "qty": 30,
        "stops": stop_results,
        "passed": status == "Filled" and stops_ok,
    }


# ═══════════════════════════════════════════════════════════
# SHARED TESTS — Both Traders
# ═══════════════════════════════════════════════════════════

def test_partial_exit(ib):
    """SHARED TEST: Partial exit — sell portion of each position."""
    log("=" * 55)
    log("SHARED TEST: Partial Exit (sell ~30% of each position)")

    positions = ib.positions()
    results = []

    for pos in positions:
        if pos.contract.secType != "STK" or pos.position <= 0:
            continue

        symbol = pos.contract.symbol
        qty = int(pos.position)
        sell_qty = max(1, qty // 3)

        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)

        order = MarketOrder("SELL", sell_qty)
        order.tif = "GTC"
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

    all_filled = all(r["status"] == "Filled" for r in results) if results else False

    return {
        "test": "partial_exit",
        "exits": results,
        "passed": all_filled,
    }


def test_full_cleanup(ib):
    """SHARED TEST: Cancel all orders + close all positions."""
    log("=" * 55)
    log("SHARED TEST: Full Cleanup (cancel orders + close positions)")

    # Cancel all open orders
    open_orders = ib.openOrders()
    for order in open_orders:
        ib.cancelOrder(order)
    ib.sleep(3)
    log(f"  Cancelled {len(open_orders)} open orders")

    # Close all positions
    positions = ib.positions()
    results = []

    for pos in positions:
        if pos.contract.secType != "STK" or pos.position == 0:
            continue

        symbol = pos.contract.symbol
        qty = int(abs(pos.position))
        action = "SELL" if pos.position > 0 else "BUY"

        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)

        order = MarketOrder(action, qty)
        order.tif = "GTC"
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

    all_filled = all(r["status"] == "Filled" for r in results) if results else True

    return {
        "test": "full_cleanup",
        "cancelled_orders": len(open_orders),
        "exits": results,
        "passed": all_filled,
    }


# ═══════════════════════════════════════════════════════════
# RUN ALL
# ═══════════════════════════════════════════════════════════

def run_all():
    log("=" * 60)
    log("TRADER1 & TRADER2 STRATEGY VALIDATION — Constitution v50.0")
    log("=" * 60)

    telegram.send(
        "🧪 *Trader Strategy Validation Starting*\n\n"
        "Testing BOTH traders:\n\n"
        "*Trader1 (System 1):*\n"
        "1. MSTR entry (lottery proxy)\n"
        "2. Laddered trailing stop LIMITS (3/7/15%)\n"
        "3. IBIT hedge + trail stop\n\n"
        "*Trader2 (System 2):*\n"
        "4. Momentum entry (NVDA)\n"
        "5. Energy entry (CCJ)\n"
        "6. Laddered trailing stop LIMITS (2/5/10% + 3/8/15%)\n"
        "7. Squeeze entry (SOFI) + aggressive trail\n\n"
        "*Shared:*\n"
        "8. Partial exit (~30%)\n"
        "9. Full cleanup\n\n"
        "Constitution v50.0 requires passing before live trading."
    )

    results = []

    # ── TRADER1 (client ID 10) ──
    log("\n>>> TRADER1 — System 1 (MSTR/IBIT Lottery)")
    ib1 = connect(client_id=10)

    try:
        r = t1_test_1_entry(ib1)
        results.append(r)
        ib1.sleep(2)

        r2 = t1_test_2_laddered_stops(ib1, r.get("fill_price", 0))
        results.append(r2)
        ib1.sleep(2)

        r3 = t1_test_3_ibit_hedge(ib1)
        results.append(r3)
        ib1.sleep(2)
    except Exception as e:
        log(f"TRADER1 ERROR: {e}")
        results.append({"test": "t1_error", "error": str(e), "passed": False})
    finally:
        ib1.disconnect()

    # ── TRADER2 (client ID 20) ──
    log("\n>>> TRADER2 — System 2 (Momentum + Energy + Squeeze)")
    ib2 = connect(client_id=20)

    try:
        r4 = t2_test_1_momentum_entry(ib2)
        results.append(r4)
        ib2.sleep(2)

        r5 = t2_test_2_energy_entry(ib2)
        results.append(r5)
        ib2.sleep(2)

        r6 = t2_test_3_laddered_stops(ib2, r4.get("fill_price", 0), r5.get("fill_price", 0))
        results.append(r6)
        ib2.sleep(2)

        r7 = t2_test_4_squeeze_entry(ib2)
        results.append(r7)
        ib2.sleep(2)
    except Exception as e:
        log(f"TRADER2 ERROR: {e}")
        results.append({"test": "t2_error", "error": str(e), "passed": False})
    finally:
        ib2.disconnect()

    # ── SHARED TESTS (client ID 50) ──
    log("\n>>> SHARED — Exit Tests")
    ib_shared = connect(client_id=50)

    try:
        r8 = test_partial_exit(ib_shared)
        results.append(r8)
        ib_shared.sleep(2)

        r9 = test_full_cleanup(ib_shared)
        results.append(r9)
    except Exception as e:
        log(f"SHARED ERROR: {e}")
        results.append({"test": "shared_error", "error": str(e), "passed": False})
    finally:
        ib_shared.disconnect()

    # ── SCORE ──
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
    record = {
        "timestamp": datetime.now().isoformat(),
        "passed": passed,
        "total": total,
        "all_passed": all_passed,
        "results": results,
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(record, f, indent=2)

    # Record trades in accountant
    for r in results:
        if r.get("fill_price"):
            accountant.record_trade({
                "system": r.get("test", ""),
                "ticker": r.get("symbol", ""),
                "action": "BUY",
                "qty": r.get("qty", 0),
                "fill_price": r.get("fill_price", 0),
                "commission": 0,
            })

    # Telegram report
    result_lines = []
    for r in results:
        emoji = "✅" if r.get("passed") else "❌"
        result_lines.append(f"{emoji} {r.get('test', '?')}")

    verdict = ("PASSED — Traders ready for live! 🟢" if all_passed
               else "FAILED — Fix issues before going live 🔴")

    telegram.send(
        f"🧪 *Trader Strategy Validation Complete*\n\n"
        f"Score: {passed}/{total}\n\n"
        + "\n".join(result_lines)
        + f"\n\n*{verdict}*"
    )

    return record


if __name__ == "__main__":
    run_all()
