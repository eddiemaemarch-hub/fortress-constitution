#!/usr/bin/env python3
"""Rudy Position Audit — Daily IBKR vs JSON Reconciliation

Compares actual IBKR positions against Rudy's state files.
Catches: ORPHAN (in IBKR, not Rudy), GHOST (in Rudy, not IBKR), QUANTITY mismatch.
Sends Telegram alert on any discrepancy.

Usage:
    python3 position_audit.py                # Full audit with Telegram report
    python3 position_audit.py --quiet        # Only alert on mismatches
    python3 position_audit.py --port 7496    # Live trading port
"""

import os
import sys
import json
import glob
import argparse
import logging
from datetime import datetime

# ── Logging ──
LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "position_audit.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("audit")


def send_telegram(msg):
    """Send Telegram alert."""
    try:
        config_path = os.path.expanduser("~/rudy/config/config.json")
        with open(config_path) as f:
            config = json.load(f)
        token = config.get("telegram_bot_token")
        chat_id = config.get("telegram_chat_id")
        if not token or not chat_id:
            return
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"Telegram error: {e}")


def get_ibkr_positions(port=7496):
    """Connect to IBKR and get ALL positions."""
    from ib_insync import IB
    ib = IB()
    ib.connect("127.0.0.1", port, clientId=56, timeout=15)

    # Account summary
    summary = ib.accountSummary()
    acct = {}
    for item in summary:
        acct[item.tag] = item.value
    net_liq = float(acct.get("NetLiquidation", 0))
    cash = float(acct.get("TotalCashValue", 0))
    unrealized = float(acct.get("UnrealizedPnL", 0))

    # All positions
    positions = ib.positions()
    pos_list = []
    for p in positions:
        c = p.contract
        pos_list.append({
            "symbol": c.symbol,
            "secType": c.secType,
            "qty": float(p.position),
            "avg_cost": float(p.avgCost),
            "strike": float(c.strike) if hasattr(c, "strike") and c.strike else None,
            "expiry": c.lastTradeDateOrContractMonth if hasattr(c, "lastTradeDateOrContractMonth") else None,
            "right": c.right if hasattr(c, "right") and c.right else None,
            "conId": c.conId,
        })

    # Open orders
    open_trades = ib.openTrades()
    open_orders = []
    for t in open_trades:
        open_orders.append({
            "symbol": t.contract.symbol,
            "action": t.order.action,
            "qty": float(t.order.totalQuantity),
            "status": t.orderStatus.status,
            "type": t.order.orderType,
        })

    ib.disconnect()

    return {
        "net_liq": net_liq,
        "cash": cash,
        "unrealized_pnl": unrealized,
        "positions": pos_list,
        "open_orders": open_orders,
    }


def get_rudy_positions():
    """Read all Rudy position/state JSON files."""
    rudy_positions = []

    # v2.8 state
    v28_state_file = os.path.join(DATA_DIR, "trader_v28_state.json")
    if os.path.exists(v28_state_file):
        with open(v28_state_file) as f:
            state = json.load(f)
        qty = state.get("position_qty", 0)
        if qty > 0:
            rudy_positions.append({
                "source": "trader_v28",
                "symbol": "MSTR",
                "secType": "STK",
                "qty": qty,
                "entry_price": state.get("entry_price", 0),
                "status": "OPEN",
            })

    # Old trader position files (traders 3-8)
    for pattern in ["trader*_position.json", "trader*_positions.json"]:
        files = glob.glob(os.path.join(DATA_DIR, pattern))
        for f_path in files:
            try:
                with open(f_path) as f:
                    data = json.load(f)

                # Handle both single position and list of positions
                positions = data if isinstance(data, list) else [data]
                for pos in positions:
                    status = pos.get("status", "").lower()
                    if status in ("open", "active"):
                        rudy_positions.append({
                            "source": os.path.basename(f_path),
                            "symbol": pos.get("symbol", pos.get("ticker", "?")),
                            "secType": pos.get("secType", "OPT"),
                            "qty": pos.get("qty", pos.get("quantity", 0)),
                            "status": "OPEN",
                        })
            except Exception as e:
                log.warning(f"Error reading {f_path}: {e}")

    return rudy_positions


def run_audit(port=7496, quiet=False):
    """Execute the position audit."""
    log.info("=" * 60)
    log.info("📋 POSITION AUDIT STARTING")
    log.info("=" * 60)

    # Get IBKR truth
    try:
        ibkr = get_ibkr_positions(port)
    except Exception as e:
        msg = f"❌ Position audit FAILED — cannot connect to TWS: {e}"
        log.error(msg)
        send_telegram(msg)
        return 1

    # Get Rudy state
    rudy = get_rudy_positions()

    # ── Compare ──
    mismatches = []

    # Build lookup: symbol → IBKR positions
    ibkr_by_symbol = {}
    for p in ibkr["positions"]:
        sym = p["symbol"]
        if sym not in ibkr_by_symbol:
            ibkr_by_symbol[sym] = []
        ibkr_by_symbol[sym].append(p)

    rudy_symbols = set(p["symbol"] for p in rudy)

    # Check for ORPHANS (in IBKR, not in Rudy)
    for sym, positions in ibkr_by_symbol.items():
        if sym not in rudy_symbols:
            for p in positions:
                mismatches.append({
                    "type": "ORPHAN",
                    "symbol": sym,
                    "detail": f"In IBKR ({p['secType']} qty={p['qty']}) but NOT tracked by Rudy",
                })

    # Check for GHOSTS (in Rudy, not in IBKR)
    ibkr_symbols = set(ibkr_by_symbol.keys())
    for p in rudy:
        if p["symbol"] not in ibkr_symbols:
            mismatches.append({
                "type": "GHOST",
                "symbol": p["symbol"],
                "detail": f"In Rudy ({p['source']}, qty={p['qty']}) but NOT in IBKR",
            })

    # Check for QUANTITY mismatches (same symbol, different qty)
    for p in rudy:
        sym = p["symbol"]
        if sym in ibkr_by_symbol:
            ibkr_total = sum(abs(ip["qty"]) for ip in ibkr_by_symbol[sym]
                          if ip["secType"] == p.get("secType", "STK"))
            rudy_qty = abs(p["qty"])
            if ibkr_total != rudy_qty:
                mismatches.append({
                    "type": "QUANTITY",
                    "symbol": sym,
                    "detail": f"Rudy says {rudy_qty}, IBKR shows {ibkr_total}",
                })

    # ── Build Report ──
    status = "✅ CLEAN" if not mismatches else f"⚠️ {len(mismatches)} MISMATCHES"

    report = {
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "account": {
            "net_liq": ibkr["net_liq"],
            "cash": ibkr["cash"],
            "unrealized_pnl": ibkr["unrealized_pnl"],
        },
        "ibkr_positions": ibkr["positions"],
        "ibkr_position_count": len(ibkr["positions"]),
        "rudy_positions": rudy,
        "rudy_position_count": len(rudy),
        "open_orders": ibkr["open_orders"],
        "open_order_count": len(ibkr["open_orders"]),
        "mismatches": mismatches,
        "mismatch_count": len(mismatches),
    }

    # Save report
    report_file = os.path.join(LOG_DIR, f"audit_{datetime.now().strftime('%Y-%m-%d')}.json")
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    log.info(f"Report saved: {report_file}")

    # ── Log Results ──
    log.info(f"Account: NLV=${ibkr['net_liq']:,.2f} | Cash=${ibkr['cash']:,.2f} | "
             f"UnrealizedPnL=${ibkr['unrealized_pnl']:,.2f}")
    log.info(f"IBKR positions: {len(ibkr['positions'])} | Rudy positions: {len(rudy)} | "
             f"Open orders: {len(ibkr['open_orders'])}")
    log.info(f"Status: {status}")

    if mismatches:
        for m in mismatches:
            log.warning(f"  [{m['type']}] {m['symbol']}: {m['detail']}")

    # ── Telegram ──
    if mismatches or not quiet:
        msg = f"📋 *POSITION AUDIT — {status}*\n"
        msg += f"NLV: ${ibkr['net_liq']:,.2f}\n"
        msg += f"IBKR positions: {len(ibkr['positions'])}\n"
        msg += f"Open orders: {len(ibkr['open_orders'])}\n"

        if mismatches:
            msg += f"\n⚠️ *{len(mismatches)} MISMATCHES:*\n"
            for m in mismatches:
                emoji = {"ORPHAN": "👻", "GHOST": "💀", "QUANTITY": "📊"}.get(m["type"], "❓")
                msg += f"  {emoji} [{m['type']}] {m['symbol']}: {m['detail']}\n"
        else:
            msg += "\n✅ All positions reconciled"

        send_telegram(msg)

    log.info("Audit complete")
    return 1 if mismatches else 0


def main():
    parser = argparse.ArgumentParser(description="Rudy Position Audit")
    parser.add_argument("--port", type=int, default=7496, help="TWS port")
    parser.add_argument("--quiet", action="store_true", help="Only alert on mismatches")
    args = parser.parse_args()

    exit_code = run_audit(port=args.port, quiet=args.quiet)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
