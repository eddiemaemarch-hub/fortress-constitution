"""Daily Report — Rudy v2.0
Runs at market close (4:05 PM ET). Snapshots the paper account,
calculates daily P&L, and sends a report to Telegram.
Tracks performance over the 6-month paper trading period.
Constitution v50.0: Must prove profitability before live trading (Oct 2026).
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram
import accountant

from ib_insync import IB

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
PAPER_TRACK_FILE = os.path.join(DATA_DIR, "paper_track.json")
os.makedirs(DATA_DIR, exist_ok=True)

PORT = 7496
START_DATE = "2026-03-10"
GO_LIVE_EARLIEST = "2026-09-15"
ALLOCATION = 240000  # Constitution v43.0: $240k total across all systems


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[DailyReport {ts}] {msg}")
    with open(f"{LOG_DIR}/daily_report.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def load_paper_track():
    if os.path.exists(PAPER_TRACK_FILE):
        with open(PAPER_TRACK_FILE) as f:
            return json.load(f)
    return {
        "start_date": START_DATE,
        "go_live_earliest": GO_LIVE_EARLIEST,
        "starting_balance": None,
        "days": {},
    }


def save_paper_track(data):
    with open(PAPER_TRACK_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_account_snapshot():
    """Get current account state from IBKR."""
    ib = IB()
    ib.connect("127.0.0.1", PORT, clientId=55)
    ib.reqMarketDataType(3)

    summary = ib.accountSummary()
    account = {}
    for item in summary:
        if item.tag == "NetLiquidation":
            account["net_liq"] = float(item.value)
        elif item.tag == "TotalCashValue":
            account["cash"] = float(item.value)
        elif item.tag == "BuyingPower":
            account["buying_power"] = float(item.value)
        elif item.tag == "UnrealizedPnL":
            account["unrealized_pnl"] = float(item.value)
        elif item.tag == "RealizedPnL":
            account["realized_pnl"] = float(item.value)

    # Get positions
    positions = ib.positions()
    pos_list = []
    for p in positions:
        if p.position != 0:
            pos_list.append({
                "symbol": p.contract.symbol,
                "secType": p.contract.secType,
                "qty": float(p.position),
                "avg_cost": float(p.avgCost),
            })
    account["positions"] = pos_list
    account["position_count"] = len(pos_list)

    ib.disconnect()
    return account


def run_daily_report():
    """Generate and send the daily paper trading report."""
    today = datetime.now().strftime("%Y-%m-%d")
    log(f"Running daily report for {today}")

    # Get account snapshot
    try:
        snapshot = get_account_snapshot()
    except Exception as e:
        log(f"ERROR getting account: {e}")
        telegram.send(f"Daily report error: {e}")
        return

    account_net_liq = snapshot.get("net_liq", 0)
    cash = snapshot.get("cash", 0)
    unrealized = snapshot.get("unrealized_pnl", 0)
    realized = snapshot.get("realized_pnl", 0)

    # Record in accountant
    accountant.record_daily_snapshot(snapshot)

    # Track in paper_track
    track = load_paper_track()

    # Constitution v43.0: $240k allocation across all systems
    if track["starting_balance"] is None:
        track["starting_balance"] = ALLOCATION
        track["account_start_liq"] = account_net_liq
        log(f"Allocation set: ${ALLOCATION:,.0f} (account: ${account_net_liq:,.2f})")

    start_bal = ALLOCATION
    account_start = track.get("account_start_liq", account_net_liq)

    # P&L = change in full account value
    account_change = account_net_liq - account_start
    net_liq = ALLOCATION + account_change

    # Yesterday's data for daily change
    dates = sorted(track["days"].keys())
    if dates:
        prev_liq = track["days"][dates[-1]]["net_liq"]
        # Daily change = today's account value - yesterday's account value
        prev_account_change = prev_liq - ALLOCATION
        prev_account_liq = account_start + prev_account_change
        daily_account_change = account_net_liq - prev_account_liq
        daily_change = daily_account_change
    else:
        prev_liq = start_bal
        daily_change = net_liq - prev_liq
    daily_pct = (daily_change / prev_liq * 100) if prev_liq > 0 else 0
    total_change = net_liq - start_bal
    total_pct = (total_change / start_bal * 100) if start_bal > 0 else 0

    # Trading days elapsed
    trading_days = len(track["days"]) + 1
    # Days until earliest go-live
    go_live_date = datetime.strptime(GO_LIVE_EARLIEST, "%Y-%m-%d")
    days_remaining = (go_live_date - datetime.now()).days

    # Peak and drawdown
    all_liq = [d["net_liq"] for d in track["days"].values()] + [net_liq]
    peak = max(all_liq) if all_liq else net_liq
    drawdown = (peak - net_liq) / peak * 100 if peak > 0 else 0

    # Win/loss streak
    recent_changes = []
    for d in sorted(track["days"].keys())[-10:]:
        day_data = track["days"][d]
        if "daily_change" in day_data:
            recent_changes.append(day_data["daily_change"])
    recent_changes.append(daily_change)

    streak = 0
    for c in reversed(recent_changes):
        if c >= 0 and streak >= 0:
            streak += 1
        elif c < 0 and streak <= 0:
            streak -= 1
        else:
            break

    # Save today
    track["days"][today] = {
        "net_liq": net_liq,
        "cash": cash,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "daily_change": daily_change,
        "daily_pct": round(daily_pct, 2),
        "total_change": total_change,
        "total_pct": round(total_pct, 2),
        "positions": snapshot.get("position_count", 0),
        "peak": peak,
        "drawdown_pct": round(drawdown, 2),
    }
    save_paper_track(track)

    log(f"Net Liq: ${net_liq:,.2f} | Day: {daily_change:+,.2f} ({daily_pct:+.2f}%) | "
        f"Total: {total_change:+,.2f} ({total_pct:+.2f}%)")

    # Build Telegram report
    day_emoji = "🟢" if daily_change >= 0 else "🔴"
    total_emoji = "🟢" if total_change >= 0 else "🔴"
    streak_emoji = "🔥" if streak >= 3 else ("❄️" if streak <= -3 else "")

    pos_lines = ""
    for p in snapshot.get("positions", []):
        pos_lines += f"  {p['symbol']}: {p['qty']:g} @ ${p['avg_cost']:,.2f}\n"
    if not pos_lines:
        pos_lines = "  No open positions\n"

    telegram.send(
        f"📊 *Daily Paper Trading Report*\n"
        f"*{today}* — Day {trading_days}\n\n"
        f"*Account:*\n"
        f"  Net Liq: ${net_liq:,.2f}\n"
        f"  Cash: ${cash:,.2f}\n\n"
        f"*Today:* {day_emoji} {daily_change:+,.2f} ({daily_pct:+.2f}%)\n"
        f"*Total:* {total_emoji} {total_change:+,.2f} ({total_pct:+.2f}%)\n"
        f"*Peak:* ${peak:,.2f} | *DD:* {drawdown:.1f}%\n"
        f"*Streak:* {streak:+d} days {streak_emoji}\n\n"
        f"*Positions:*\n{pos_lines}\n"
        f"*Go-Live:* {days_remaining} days remaining\n"
        f"_Paper trading since {START_DATE}_"
    )

    return track["days"][today]


if __name__ == "__main__":
    run_daily_report()
