"""Accountant Agent — Rudy v2.0
Tracks P&L, fees, performance metrics, and tax reporting.
"""
import json
import os
from datetime import datetime, timedelta

DATA_DIR = os.path.expanduser("~/rudy/data")
TRADES_FILE = os.path.join(DATA_DIR, "trade_history.json")
DAILY_PNL_FILE = os.path.join(DATA_DIR, "daily_pnl.json")
os.makedirs(DATA_DIR, exist_ok=True)


def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE) as f:
            return json.load(f)
    return []


def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)


def load_daily_pnl():
    if os.path.exists(DAILY_PNL_FILE):
        with open(DAILY_PNL_FILE) as f:
            return json.load(f)
    return {}


def save_daily_pnl(data):
    with open(DAILY_PNL_FILE, "w") as f:
        json.dump(data, f, indent=2)


def record_trade(trade):
    """Record a completed trade for accounting."""
    trades = load_trades()
    entry = {
        "id": len(trades) + 1,
        "timestamp": datetime.now().isoformat(),
        "system": trade.get("system", "unknown"),
        "ticker": trade.get("ticker", ""),
        "action": trade.get("action", ""),
        "qty": trade.get("qty", 0),
        "fill_price": trade.get("fill_price", 0),
        "order_type": trade.get("order_type", "market"),
        "commission": trade.get("commission", 0),
        "pnl": trade.get("pnl", None),
    }
    trades.append(entry)
    save_trades(trades)
    return entry


def record_daily_snapshot(account_data):
    """Record daily account snapshot for P&L tracking."""
    today = datetime.now().strftime("%Y-%m-%d")
    daily = load_daily_pnl()
    daily[today] = {
        "net_liq": account_data.get("net_liq", 0),
        "cash": account_data.get("cash", 0),
        "unrealized_pnl": account_data.get("unrealized_pnl", 0),
        "realized_pnl": account_data.get("realized_pnl", 0),
        "timestamp": datetime.now().isoformat(),
    }
    save_daily_pnl(daily)


def get_pnl_summary():
    """Calculate P&L summary across all trades."""
    trades = load_trades()
    if not trades:
        return {
            "total_trades": 0,
            "total_pnl": 0,
            "total_commissions": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0,
            "by_system": {},
            "by_ticker": {},
        }

    total_pnl = 0
    total_commissions = 0
    winning = 0
    losing = 0
    by_system = {}
    by_ticker = {}

    for t in trades:
        pnl = t.get("pnl") or 0
        comm = t.get("commission") or 0
        total_pnl += pnl
        total_commissions += comm

        if pnl > 0:
            winning += 1
        elif pnl < 0:
            losing += 1

        sys = t.get("system", "unknown")
        by_system.setdefault(sys, {"pnl": 0, "trades": 0, "commissions": 0})
        by_system[sys]["pnl"] += pnl
        by_system[sys]["trades"] += 1
        by_system[sys]["commissions"] += comm

        ticker = t.get("ticker", "?")
        by_ticker.setdefault(ticker, {"pnl": 0, "trades": 0})
        by_ticker[ticker]["pnl"] += pnl
        by_ticker[ticker]["trades"] += 1

    total = winning + losing
    win_rate = (winning / total * 100) if total > 0 else 0

    return {
        "total_trades": len(trades),
        "total_pnl": round(total_pnl, 2),
        "total_commissions": round(total_commissions, 2),
        "net_pnl": round(total_pnl - total_commissions, 2),
        "winning_trades": winning,
        "losing_trades": losing,
        "win_rate": round(win_rate, 1),
        "by_system": by_system,
        "by_ticker": by_ticker,
    }


def get_daily_returns():
    """Calculate daily returns from snapshots."""
    daily = load_daily_pnl()
    if len(daily) < 2:
        return []

    dates = sorted(daily.keys())
    returns = []
    for i in range(1, len(dates)):
        prev = daily[dates[i - 1]]["net_liq"]
        curr = daily[dates[i]]["net_liq"]
        if prev > 0:
            ret = (curr - prev) / prev * 100
            returns.append({
                "date": dates[i],
                "return_pct": round(ret, 2),
                "net_liq": curr,
                "change": round(curr - prev, 2),
            })
    return returns


def get_tax_lots():
    """Group trades into tax lots (FIFO) for tax reporting."""
    trades = load_trades()
    lots = {}

    for t in trades:
        ticker = t.get("ticker", "")
        action = t.get("action", "").upper()
        qty = t.get("qty", 0)
        price = t.get("fill_price", 0)

        if ticker not in lots:
            lots[ticker] = {"open": [], "closed": []}

        if action == "BUY":
            lots[ticker]["open"].append({
                "date": t["timestamp"],
                "qty": qty,
                "price": price,
                "remaining": qty,
            })
        elif action == "SELL":
            sell_remaining = qty
            for lot in lots[ticker]["open"]:
                if sell_remaining <= 0:
                    break
                if lot["remaining"] <= 0:
                    continue
                sold = min(sell_remaining, lot["remaining"])
                lot["remaining"] -= sold
                sell_remaining -= sold
                pnl = (price - lot["price"]) * sold
                lots[ticker]["closed"].append({
                    "buy_date": lot["date"],
                    "sell_date": t["timestamp"],
                    "qty": sold,
                    "buy_price": lot["price"],
                    "sell_price": price,
                    "pnl": round(pnl, 2),
                })

    return lots


def get_performance_metrics():
    """Calculate key performance metrics."""
    daily = load_daily_pnl()
    trades = load_trades()
    pnl_summary = get_pnl_summary()

    dates = sorted(daily.keys())
    if not dates:
        return {
            "total_return_pct": 0,
            "max_drawdown_pct": 0,
            "sharpe_ratio": 0,
            "avg_trade_pnl": 0,
            "largest_win": 0,
            "largest_loss": 0,
            "days_trading": 0,
        }

    # Total return
    start_val = daily[dates[0]]["net_liq"] if dates else 0
    end_val = daily[dates[-1]]["net_liq"] if dates else 0
    total_return = ((end_val - start_val) / start_val * 100) if start_val > 0 else 0

    # Max drawdown
    peak = 0
    max_dd = 0
    for d in dates:
        val = daily[d]["net_liq"]
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Trade stats
    pnls = [t.get("pnl", 0) for t in trades if t.get("pnl") is not None]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0
    largest_win = max(pnls) if pnls else 0
    largest_loss = min(pnls) if pnls else 0

    return {
        "total_return_pct": round(total_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "avg_trade_pnl": round(avg_pnl, 2),
        "largest_win": round(largest_win, 2),
        "largest_loss": round(largest_loss, 2),
        "days_trading": len(dates),
        "total_pnl": pnl_summary["total_pnl"],
        "win_rate": pnl_summary["win_rate"],
    }


def refresh_live_snapshot():
    """Pull live account data from IBKR and update daily snapshot."""
    try:
        from ib_insync import IB
        ib = IB()
        ib.connect("127.0.0.1", 7496, clientId=57)
        ib.reqMarketDataType(3)

        summary = ib.accountSummary()
        account = {}
        for item in summary:
            if item.tag == "NetLiquidation":
                account["net_liq"] = float(item.value)
            elif item.tag == "TotalCashValue":
                account["cash"] = float(item.value)
            elif item.tag == "UnrealizedPnL":
                account["unrealized_pnl"] = float(item.value)
            elif item.tag == "RealizedPnL":
                account["realized_pnl"] = float(item.value)

        # Get position-level P&L
        positions = ib.positions()
        pos_pnl = []
        for p in positions:
            if p.position != 0:
                pos_pnl.append({
                    "symbol": p.contract.symbol,
                    "secType": p.contract.secType,
                    "qty": float(p.position),
                    "avg_cost": float(p.avgCost),
                    "market_value": float(p.avgCost) * float(p.position),
                })

        ib.disconnect()

        # Save snapshot
        record_daily_snapshot(account)

        # Also save position-level data for the dashboard
        account["positions"] = pos_pnl
        account["position_count"] = len(pos_pnl)
        account["last_update"] = datetime.now().isoformat()

        snapshot_file = os.path.join(DATA_DIR, "accountant_live.json")
        with open(snapshot_file, "w") as f:
            json.dump(account, f, indent=2)

        return account
    except Exception as e:
        return {"error": str(e)}


def get_dashboard_summary():
    """Full summary for the Rudy dashboard."""
    pnl = get_pnl_summary()
    perf = get_performance_metrics()

    # Include live data if available
    live_file = os.path.join(DATA_DIR, "accountant_live.json")
    live = {}
    if os.path.exists(live_file):
        with open(live_file) as f:
            live = json.load(f)

    return {
        "pnl": pnl,
        "performance": perf,
        "recent_trades": load_trades()[-10:],
        "daily_returns": get_daily_returns()[-7:],
        "live": live,
    }
