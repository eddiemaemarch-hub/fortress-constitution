#!/usr/bin/env python3
"""Rudy Kill Switch — Emergency Flatten All Positions

Cancels ALL open orders, closes ALL positions, verifies zero.
Sends Telegram alerts at start and end.

Usage:
    python3 kill_switch.py                  # Interactive (asks for confirmation)
    python3 kill_switch.py --force          # No confirmation prompt
    python3 kill_switch.py --port 7496      # Live trading port
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime

# ── Logging ──
LOG_DIR = os.path.expanduser("~/rudy/logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "kill_switch.log")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("kill_switch")


def send_telegram(msg):
    """Send Telegram alert."""
    try:
        config_path = os.path.expanduser("~/rudy/config/config.json")
        with open(config_path) as f:
            config = json.load(f)
        token = config.get("telegram_bot_token")
        chat_id = config.get("telegram_chat_id")
        if not token or not chat_id:
            log.warning("Telegram not configured")
            return
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        if r.status_code == 200:
            log.info("Telegram sent")
        else:
            log.warning(f"Telegram failed: {r.status_code}")
    except Exception as e:
        log.warning(f"Telegram error: {e}")


def kill_switch(port=7496, force=False):
    """Execute the kill switch."""
    from ib_insync import IB, MarketOrder

    log.info("=" * 60)
    log.info("🚨 KILL SWITCH ACTIVATED")
    log.info(f"Port: {port} | Force: {force}")
    log.info("=" * 60)

    send_telegram("🚨 *KILL SWITCH ACTIVATED*\nCancelling all orders, closing all positions...")

    # ── Connect ──
    ib = IB()
    try:
        ib.connect("127.0.0.1", port, clientId=99, timeout=15)
        log.info(f"Connected to TWS port {port}")
    except Exception as e:
        msg = f"❌ Kill switch FAILED — cannot connect to TWS port {port}: {e}"
        log.error(msg)
        send_telegram(msg)
        return 1

    # ── Step 1: Global Cancel All Orders ──
    log.info("Step 1: Cancelling ALL open orders...")
    ib.reqGlobalCancel()
    ib.sleep(3)

    # Verify no open orders
    open_trades = ib.openTrades()
    if open_trades:
        log.warning(f"  {len(open_trades)} orders still open after global cancel, waiting...")
        ib.sleep(5)
        open_trades = ib.openTrades()
        if open_trades:
            log.warning(f"  Still {len(open_trades)} orders — proceeding anyway")
    else:
        log.info("  ✅ All orders cancelled")

    # ── Step 2: Close ALL positions ──
    results = []
    max_retries = 3

    for attempt in range(max_retries):
        positions = ib.positions()
        if not positions:
            log.info(f"  ✅ FLAT — zero positions (attempt {attempt + 1})")
            break

        log.info(f"Step 2 (attempt {attempt + 1}/{max_retries}): Closing {len(positions)} positions...")

        # Cancel any orders that might interfere
        if attempt > 0:
            ib.reqGlobalCancel()
            ib.sleep(3)

        ordered_conids = set()
        trades_placed = []

        for p in positions:
            cid = p.contract.conId
            if cid in ordered_conids:
                continue

            contract = p.contract
            contract.exchange = "SMART"
            try:
                ib.qualifyContracts(contract)
            except Exception:
                pass

            qty = p.position
            if qty < 0:
                order = MarketOrder("BUY", abs(qty))
            elif qty > 0:
                order = MarketOrder("SELL", abs(qty))
            else:
                continue

            order.tif = "GTC"

            try:
                trade = ib.placeOrder(contract, order)
                trades_placed.append((p, trade))
                ordered_conids.add(cid)
                log.info(f"  {contract.symbol} {contract.secType} qty={qty} → {order.action} {order.totalQuantity}")
            except Exception as e:
                log.error(f"  ❌ Failed to place order for {contract.symbol}: {e}")

            ib.sleep(1)

        # ── Step 3: Poll for fills ──
        log.info(f"Step 3: Polling for fills ({len(trades_placed)} orders)...")
        poll_start = time.time()
        poll_timeout = 60

        while time.time() - poll_start < poll_timeout:
            ib.sleep(2)
            all_done = True
            for pos, trade in trades_placed:
                status = trade.orderStatus.status
                if status in ("Filled",):
                    fill = trade.orderStatus.avgFillPrice
                    results.append({
                        "symbol": pos.contract.symbol,
                        "secType": pos.contract.secType,
                        "qty": float(pos.position),
                        "action": "BUY" if pos.position < 0 else "SELL",
                        "fill_price": fill,
                        "status": "Filled",
                    })
                elif status in ("PreSubmitted", "Submitted"):
                    all_done = False
                elif status in ("Cancelled", "Inactive"):
                    results.append({
                        "symbol": pos.contract.symbol,
                        "secType": pos.contract.secType,
                        "qty": float(pos.position),
                        "status": status,
                        "error": trade.log[-1].message if trade.log else "",
                    })
                else:
                    all_done = False

            if all_done:
                break

        # Check for PreSubmitted (market closed)
        for pos, trade in trades_placed:
            status = trade.orderStatus.status
            if status == "PreSubmitted":
                results.append({
                    "symbol": pos.contract.symbol,
                    "secType": pos.contract.secType,
                    "qty": float(pos.position),
                    "status": "PreSubmitted (will fill at open)",
                })

        ib.sleep(2)

    # ── Step 4: Final verification ──
    log.info("Step 4: Final position check...")
    final_positions = ib.positions()

    # Build summary
    filled = [r for r in results if r.get("status") == "Filled"]
    presubmitted = [r for r in results if "PreSubmitted" in str(r.get("status", ""))]
    failed = [r for r in results if r.get("status") in ("Cancelled", "Inactive")]

    summary = (
        f"{'🟢' if not final_positions else '⚠️'} *KILL SWITCH COMPLETE*\n"
        f"Filled: {len(filled)}\n"
        f"Queued (market closed): {len(presubmitted)}\n"
        f"Failed: {len(failed)}\n"
        f"Remaining positions: {len(final_positions)}\n"
    )

    if filled:
        summary += "\n*Fills:*\n"
        for r in filled:
            summary += f"  {r['symbol']} {r['action']} {abs(r['qty']):.0f} @ ${r['fill_price']:.2f}\n"

    if presubmitted:
        summary += "\n*Queued for open:*\n"
        for r in presubmitted:
            summary += f"  {r['symbol']} qty={abs(r['qty']):.0f}\n"

    if failed:
        summary += "\n*FAILED:*\n"
        for r in failed:
            summary += f"  ❌ {r['symbol']}: {r.get('error', 'unknown')}\n"

    if final_positions:
        summary += f"\n⚠️ *{len(final_positions)} POSITIONS STILL OPEN*"
        for p in final_positions:
            summary += f"\n  {p.contract.symbol} qty={p.position}"

    log.info(summary.replace("*", ""))
    send_telegram(summary)

    # Save report
    report = {
        "timestamp": datetime.now().isoformat(),
        "port": port,
        "results": results,
        "final_positions": len(final_positions),
        "filled": len(filled),
        "presubmitted": len(presubmitted),
        "failed": len(failed),
    }
    report_file = os.path.join(LOG_DIR, f"kill_switch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    log.info(f"Report saved: {report_file}")

    ib.disconnect()

    if final_positions and not presubmitted:
        return 1  # positions remain and nothing queued
    return 0


def main():
    parser = argparse.ArgumentParser(description="Rudy Kill Switch — Emergency Flatten")
    parser.add_argument("--port", type=int, default=7496, help="TWS port (7496=paper, 7496=live)")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if not args.force:
        print("\n🚨 KILL SWITCH — This will:")
        print("  1. Cancel ALL open orders")
        print("  2. Close ALL positions at market")
        print("  3. Flatten the entire account")
        print(f"\n  Port: {args.port} ({'PAPER' if args.port == 7496 else 'LIVE'})")
        confirm = input("\n  Type 'KILL' to confirm: ")
        if confirm.strip() != "KILL":
            print("Aborted.")
            return 0

    exit_code = kill_switch(port=args.port, force=args.force)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
