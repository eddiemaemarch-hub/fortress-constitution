"""Shadow Dashboard — Terminal display for shadow broker state.
Run in a second terminal window. Refreshes every 30 seconds.

Usage:
    cd ~/rudy && python scripts/shadow_dashboard.py
    cd ~/rudy && python scripts/shadow_dashboard.py --once   # single snapshot
"""
import os
import sys
import json
import time
from datetime import datetime

DATA_DIR = os.path.expanduser("~/rudy/data")
STATE_FILE = os.path.join(DATA_DIR, "shadow_positions.json")
BREAKER_FILE = os.path.join(DATA_DIR, "breaker_state.json")


def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def load_breaker():
    if not os.path.exists(BREAKER_FILE):
        return {"global_halt": False, "systems": {}}
    try:
        with open(BREAKER_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"global_halt": False, "systems": {}}


def format_pnl(val):
    if val >= 0:
        return f"\033[32m${val:+,.2f}\033[0m"  # green
    return f"\033[31m${val:+,.2f}\033[0m"  # red


def render(state, breaker):
    os.system("clear" if os.name != "nt" else "cls")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated = state.get("last_updated", "?")[:19] if state else "never"

    print("=" * 70)
    print(f"  RUDY v2.0 — SHADOW DASHBOARD")
    print(f"  Now: {ts}  |  State: {updated}")
    print("=" * 70)

    if not state:
        print("\n  No shadow state found. Start the system with RUDY_MODE=shadow")
        print(f"  Expected file: {STATE_FILE}")
        return

    # ─── Breaker Status ──────────────────────────────────────────────
    halt = breaker.get("global_halt", False)
    if halt:
        reason = breaker.get("halt_reason", "unknown")
        print(f"\n  \033[41;37m GLOBAL HALT ACTIVE \033[0m  {reason}")
    else:
        active_breakers = [k for k, v in breaker.get("systems", {}).items()
                          if v.get("breaker_active")]
        if active_breakers:
            print(f"\n  \033[43;30m SYSTEM BREAKERS: {', '.join(active_breakers)} \033[0m")
        else:
            print(f"\n  Breakers: \033[32mALL CLEAR\033[0m")

    # ─── P&L Summary ────────────────────────────────────────────────
    realized = state.get("realized_pnl", 0)
    unrealized = state.get("unrealized_pnl", 0)
    positions = state.get("positions", [])

    # Recalculate unrealized from positions
    unrealized = sum(
        (p.get("current_price", 0) - p.get("entry_price", 0)) * p.get("qty", 0) * 100
        for p in positions
    )
    total = realized + unrealized

    print(f"\n  Realized P&L:   {format_pnl(realized)}")
    print(f"  Unrealized P&L: {format_pnl(unrealized)}")
    print(f"  Total P&L:      {format_pnl(total)}")

    # ─── Open Positions ──────────────────────────────────────────────
    print(f"\n  Open Positions: {len(positions)}")
    if positions:
        print(f"  {'Symbol':<8} {'System':<20} {'Qty':>4} {'Entry':>8} {'Current':>8} {'HW':>8} {'Gain%':>8}")
        print(f"  {'─' * 8} {'─' * 20} {'─' * 4} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8}")
        for p in positions:
            entry = p.get("entry_price", 0)
            current = p.get("current_price", 0)
            hw = p.get("high_water", 0)
            gain = ((hw - entry) / entry * 100) if entry > 0 else 0
            print(f"  {p.get('symbol', '?'):<8} {p.get('system', '?'):<20} "
                  f"{p.get('qty', 0):>4} ${entry:>7.2f} ${current:>7.2f} ${hw:>7.2f} {gain:>+7.1f}%")

    # ─── Recent Exits ───────────────────────────────────────────────
    exits = state.get("exits", [])
    if exits:
        print(f"\n  Recent Exits (last {min(5, len(exits))}):")
        print(f"  {'Symbol':<8} {'System':<16} {'Entry':>8} {'Exit':>8} {'P&L':>10} {'Reason'}")
        print(f"  {'─' * 8} {'─' * 16} {'─' * 8} {'─' * 8} {'─' * 10} {'─' * 20}")
        for ex in exits[-5:]:
            pnl = ex.get("pnl", 0)
            pnl_str = f"${pnl:+,.0f}"
            print(f"  {ex.get('symbol', '?'):<8} {ex.get('system', '?'):<16} "
                  f"${ex.get('entry_price', 0):>7.2f} ${ex.get('exit_price', 0):>7.2f} "
                  f"{pnl_str:>10} {ex.get('reason', '')[:20]}")

    # ─── Storm Alerts ────────────────────────────────────────────────
    storms = state.get("storms", [])
    if storms:
        print(f"\n  \033[33mStorm Alerts ({len(storms)}):\033[0m")
        for s in storms[-3:]:
            print(f"    {s.get('time', '?')[:19]}  {s.get('symbol', '?')} × {s.get('count', '?')} signals")

    print(f"\n{'=' * 70}")


def main():
    once = "--once" in sys.argv

    while True:
        state = load_state()
        breaker = load_breaker()
        render(state, breaker)

        if once:
            break

        print(f"  Refreshing in 30s... (Ctrl+C to exit)")
        try:
            time.sleep(30)
        except KeyboardInterrupt:
            print("\n  Dashboard stopped.")
            break


if __name__ == "__main__":
    main()
