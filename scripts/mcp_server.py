"""Rudy v2.8+ MCP Server — Claude Cowork Integration

Exposes Rudy's trading state, positions, performance, and controls
as MCP tools for Claude Desktop / Cowork.

v2.8+ = v2.8 Dynamic Blend + Trend Adder (golden cross scale-up).
History-seeded 200W SMA, stress tested, execution validated.

Usage:
    Runs via stdio transport (Claude Desktop launches it).
    Register in ~/Library/Application Support/Claude/claude_desktop_config.json

Dependencies (install into .mcp_venv):
    .mcp_venv/bin/pip install mcp ib_insync requests

IMPORTANT — asyncio note:
    FastMCP owns the main event loop. Any ib_insync call MUST run in a
    ThreadPoolExecutor thread with asyncio.set_event_loop(asyncio.new_event_loop())
    called first, or it will fail with "This event loop is already running".
"""
import json
import os
import sys
from datetime import datetime

# Add rudy scripts to path for imports
sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))

from mcp.server.fastmcp import FastMCP

DATA_DIR = os.path.expanduser("~/rudy/data")
LOGS_DIR = os.path.expanduser("~/rudy/logs")

mcp = FastMCP("rudy-trading")


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _load(filename):
    """Load a JSON file from the data directory."""
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _tail(filepath, n=50):
    """Read last n lines from a file."""
    if not os.path.exists(filepath):
        return f"File not found: {filepath}"
    with open(filepath, "rb") as f:
        # Seek from end for efficiency
        try:
            f.seek(0, 2)
            fsize = f.tell()
            # Read last chunk (generous buffer)
            buf_size = min(fsize, n * 200)
            f.seek(max(fsize - buf_size, 0))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except Exception as e:
            return f"Error reading file: {e}"


# ══════════════════════════════════════════════════════════════
#  READ-ONLY TOOLS — MONITORING
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def get_system_status() -> dict:
    """Get Rudy v2.8+ current status — armed state, last eval, MSTR/BTC prices, premium, position summary."""
    state = _load("trader_v28_state.json")
    if not state:
        return {"error": "No state file found. Is trader_v28 running?"}

    in_position = state.get("position_qty", 0) > 0
    result = {
        "system": "Rudy v2.8+ Trend Adder",
        "armed": state.get("is_armed", False),
        "dipped_below_200w": state.get("dipped_below_200w", False),
        "green_week_count": state.get("green_week_count", 0),
        "last_eval": state.get("last_eval", "never"),
        "mstr_price": state.get("last_mstr_price"),
        "btc_price": state.get("last_btc_price"),
        "in_position": in_position,
    }

    if in_position:
        result["position_qty"] = state.get("position_qty")
        result["entry_price"] = state.get("entry_price")
        result["position_hwm"] = state.get("position_hwm")
        result["peak_gain_pct"] = state.get("peak_gain_pct")
        result["bars_in_trade"] = state.get("bars_in_trade")
        result["euphoria_sell_done"] = state.get("euphoria_sell_done")
        result["profit_tier_hits"] = state.get("pt_hits")

    # Premium from recent history
    prem_hist = state.get("premium_history", [])
    if prem_hist:
        result["current_premium"] = round(prem_hist[-1], 4)

    return result


@mcp.tool()
def get_position() -> dict:
    """Get current v2.8+ position details — entry price, qty, P&L, LEAP gain %, bars held, HWM, trail tier."""
    state = _load("trader_v28_state.json")
    if not state:
        return {"error": "No state file found"}

    qty = state.get("position_qty", 0)
    if qty == 0:
        return {"status": "NO POSITION", "message": "Rudy is not currently in a trade."}

    entry = state.get("entry_price", 0)
    mstr = state.get("last_mstr_price", 0)
    stock_gain_pct = ((mstr - entry) / entry * 100) if entry > 0 else 0

    # Estimate LEAP gain using v2.8 dynamic blend multiplier.
    # SOURCE OF TRUTH: trader_v28.py:801 get_dynamic_leap_multiplier(). Keep aligned.
    prem_hist = state.get("premium_history", [])
    premium = prem_hist[-1] if prem_hist else 1.0
    if premium < 0.7:
        mult = 7.2  # LOW (<0.7)
    elif premium < 1.0:
        mult = 6.5  # FAIR (0.7–1.0)
    elif premium <= 1.3:
        mult = 4.8  # ELEVATED (1.0–1.3)
    else:
        mult = 3.3  # EUPHORIC (>1.3)
    leap_gain_pct = stock_gain_pct * mult

    # Active trail tier — SOURCE OF TRUTH: trader_v28.py:196 self.ladder_tiers. Keep aligned.
    ladder = [(10000, 12.0), (5000, 20.0), (2000, 25.0), (1000, 30.0), (500, 35.0)]
    active_trail = "None (below 5x)"
    for threshold, trail in ladder:
        if leap_gain_pct >= threshold:
            active_trail = f"{trail}% trail (LEAP gain >= {threshold/100:.0f}x)"
            break

    return {
        "status": "IN POSITION",
        "entry_price": entry,
        "current_price": mstr,
        "position_qty": qty,
        "stock_gain_pct": round(stock_gain_pct, 2),
        "estimated_leap_gain_pct": round(leap_gain_pct, 2),
        "leap_multiplier": mult,
        "premium_zone": "LOW" if premium < 0.7 else "FAIR" if premium < 1.0 else "ELEVATED" if premium <= 1.3 else "EUPHORIC",
        "position_hwm": state.get("position_hwm"),
        "peak_gain_pct": state.get("peak_gain_pct"),
        "bars_in_trade": state.get("bars_in_trade"),
        "active_trail": active_trail,
        "profit_tier_hits": state.get("pt_hits"),
        "euphoria_sell_done": state.get("euphoria_sell_done"),
        "first_entry_done": state.get("first_entry_done"),
        "second_entry_done": state.get("second_entry_done"),
    }


@mcp.tool()
def get_account_summary() -> dict:
    """Get IBKR account summary — net liquidation, cash, unrealized/realized P&L, ALL positions live from TWS."""
    from datetime import datetime as _dt
    import concurrent.futures

    def _fetch_from_tws():
        import asyncio
        asyncio.set_event_loop(asyncio.new_event_loop())
        from ib_insync import IB as _IB
        ib = _IB()
        # Use live port (7496) — paper trading is disabled
        ib.connect("127.0.0.1", 7496, clientId=55, timeout=10)

        # Account values
        summary = ib.accountSummary()
        acct_vals = {}
        for item in summary:
            acct_vals[item.tag] = item.value
        net_liq = float(acct_vals.get("NetLiquidation", 0))
        cash = float(acct_vals.get("TotalCashValue", 0))
        unrealized = float(acct_vals.get("UnrealizedPnL", 0))
        realized = float(acct_vals.get("RealizedPnL", 0))

        # ALL positions — every individual contract
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
                "exchange": c.exchange,
                "conId": c.conId,
            })

        # Check open orders for close order tracking
        open_trades = ib.openTrades()
        close_order_conids = set()
        for t in open_trades:
            close_order_conids.add(t.contract.conId)

        for p in pos_list:
            p["has_close_order"] = p.get("conId") in close_order_conids

        open_order_count = len(open_trades)

        ib.disconnect()

        return {
            "net_liq": net_liq,
            "cash": cash,
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "position_count": len(pos_list),
            "positions": pos_list,
            "open_orders": open_order_count,
            "last_update": _dt.now().isoformat(),
            "source": "LIVE_TWS",
        }

    try:
        # Run in a thread so ib_insync gets a clean event loop (MCP already owns the main one)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(_fetch_from_tws).result(timeout=30)
    except Exception as e:
        # Fallback to stale JSON if TWS unavailable
        acct = _load("accountant_live.json")
        if acct:
            acct["source"] = "STALE_JSON"
            acct["tws_error"] = str(e)
            return acct
        return {"error": f"TWS connection failed and no cached data: {e}"}


@mcp.tool()
def get_performance() -> dict:
    """Get trading performance metrics — Sharpe, max drawdown, win rate, total P&L, avg trade."""
    try:
        import accountant
        metrics = accountant.get_performance_metrics()
        pnl = accountant.get_pnl_summary()
        return {
            "total_return_pct": metrics.get("total_return_pct"),
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "avg_trade_pnl": metrics.get("avg_trade_pnl"),
            "largest_win": metrics.get("largest_win"),
            "largest_loss": metrics.get("largest_loss"),
            "days_trading": metrics.get("days_trading"),
            "total_pnl": pnl.get("total_pnl"),
            "total_trades": pnl.get("total_trades"),
            "win_rate": pnl.get("win_rate"),
            "winning_trades": pnl.get("winning_trades"),
            "losing_trades": pnl.get("losing_trades"),
            "by_system": pnl.get("by_system"),
        }
    except Exception as e:
        return {"error": f"Failed to load accountant: {e}"}


@mcp.tool()
def get_trade_history(limit: int = 20) -> list:
    """Get recent trade history with P&L, ticker, system, and dates.

    Args:
        limit: Number of recent trades to return (default 20)
    """
    trades = _load("trade_history.json")
    if isinstance(trades, list):
        return trades[-limit:]
    return []


@mcp.tool()
def get_filter_status() -> dict:
    """Get all v2.8+ entry filter states — 200W SMA armed, BTC>200W, StochRSI, death cross, position."""
    state = _load("trader_v28_state.json")
    if not state:
        return {"error": "No state file found"}

    in_position = state.get("position_qty", 0) > 0
    btc_closes = state.get("btc_weekly_closes", [])
    btc_price = state.get("last_btc_price", 0)

    # Compute BTC 200W SMA from stored closes
    btc_above_200w = None
    if len(btc_closes) >= 200:
        btc_200w = sum(btc_closes[-200:]) / 200
        btc_above_200w = btc_price > btc_200w

    return {
        "filter_1_armed": state.get("is_armed", False),
        "filter_1_detail": f"Dipped below 200W: {state.get('dipped_below_200w')}, Green weeks: {state.get('green_week_count')}",
        "filter_2_btc_above_200w": btc_above_200w,
        "filter_3_stoch_rsi": "Checked at eval time (< 70 required)",
        "filter_4_no_death_cross": "Checked at eval time (BTC 50D > 200D required)",
        "filter_5_no_position": not in_position,
        "already_entered_this_cycle": state.get("already_entered_this_cycle", False),
        "last_eval": state.get("last_eval"),
    }


@mcp.tool()
def get_breaker_status() -> dict:
    """Get circuit breaker status — global halt flag, per-system halts, halt reason."""
    breaker = _load("breaker_state.json")
    if not breaker:
        return {"global_halt": False, "message": "No breaker state file (all systems normal)"}
    return {
        "global_halt": breaker.get("global_halt", False),
        "halt_reason": breaker.get("halt_reason"),
        "systems": breaker.get("systems", {}),
        "last_updated": breaker.get("last_updated"),
    }


@mcp.tool()
def get_logs(lines: int = 50) -> str:
    """Get last N lines from the v2.8+ trader log.

    Args:
        lines: Number of log lines to return (default 50)
    """
    return _tail(os.path.join(LOGS_DIR, "trader_v28.log"), n=lines)


@mcp.tool()
def get_market_intel() -> dict:
    """Get latest market regime classification and sentiment data."""
    regime = _load("market_regime.json")
    if not regime:
        return {"message": "No market regime data available"}
    # Return a summary, not the full payload
    if isinstance(regime, dict):
        return {
            "regime": regime.get("regime", regime.get("classification", "unknown")),
            "confidence": regime.get("confidence"),
            "last_updated": regime.get("last_updated", regime.get("timestamp")),
            "summary": regime.get("summary", regime.get("analysis", "")),
        }
    return regime


# ══════════════════════════════════════════════════════════════
#  ACTION TOOLS
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def approve_trade(trade_id: str, notes: str = "") -> str:
    """Approve a pending trade proposal for execution.

    Args:
        trade_id: Identifier for the pending trade (e.g. 'mstr_entry_1')
        notes: Optional notes from the Commander
    """
    approval = {
        "trade_id": trade_id,
        "approved": True,
        "approved_at": datetime.now().isoformat(),
        "approved_by": "Commander via Cowork",
        "notes": notes,
    }
    path = os.path.join(DATA_DIR, "cowork_approval.json")
    with open(path, "w") as f:
        json.dump(approval, f, indent=2)
    return f"Trade '{trade_id}' approved. Written to {path}. Trader will pick up on next loop."


@mcp.tool()
def approve_strike_roll(action: str = "approve") -> str:
    """Approve or reject a pending strike roll recommendation (HITL).

    When premium compresses significantly, Rudy recommends rolling LEAP strikes
    to protect against payout haircuts. This tool lets the Commander approve or
    reject that recommendation.

    Args:
        action: 'approve' to execute the roll, 'reject' to keep current strikes
    """
    state_path = os.path.join(DATA_DIR, "trader_v28_state.json")
    try:
        with open(state_path) as f:
            state = json.load(f)
    except Exception as e:
        return f"Error reading state: {e}"

    pending = state.get("pending_strike_roll")
    if not pending:
        return "No pending strike roll. System is clean."

    if action.lower() not in ("approve", "reject"):
        return "Invalid action. Use 'approve' or 'reject'."

    if action.lower() == "approve":
        state.setdefault("approved_strike_rolls", [])
        pending["approved_at"] = datetime.now().isoformat()
        pending["status"] = "APPROVED"
        state["approved_strike_rolls"].append(pending)
        state["last_strike_recommendation"] = {
            "band": pending["new_band"],
            "safety_strikes": pending["new_safety_strikes"],
            "safety_weight": 0.45,
            "spec_strikes": pending["new_spec_strikes"],
            "spec_weight": 0.55,
            "premium_at_entry": state.get("last_premium", 0),
            "timestamp": datetime.now().isoformat(),
            "rolled_from": pending["old_band"]
        }
        state.pop("pending_strike_roll", None)
        msg = f"✅ Strike roll APPROVED: {pending['old_band']} → {pending['new_band']}"
    else:
        state.setdefault("rejected_strike_rolls", [])
        pending["rejected_at"] = datetime.now().isoformat()
        pending["status"] = "REJECTED"
        state["rejected_strike_rolls"].append(pending)
        state.pop("pending_strike_roll", None)
        msg = f"❌ Strike roll REJECTED — keeping current strikes"

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, default=str)

    # Telegram notification
    try:
        from telegram import send
        send(msg)
    except Exception:
        pass

    return msg


@mcp.tool()
def approve_expiry_roll(trader: str = "trader2", action: str = "approve") -> str:
    """Approve or reject a pending LEAP expiry extension roll (HITL).

    When a LEAP put approaches expiry in a flat/non-activated market, the trader
    proposes rolling to a later expiry at the same strike to preserve the thesis.
    This tool signals that approval (or rejection) to the daemon.

    Args:
        trader: 'trader2' (MSTR $50P Jan28 → Jan30) or 'trader3' (SPY $430P Jan27 → Jan29)
        action: 'approve' to execute the roll, 'reject' to keep current expiry
    """
    trader_map = {
        "trader2": "trader2_state.json",
        "trader3": "trader3_state.json",
    }
    if trader.lower() not in trader_map:
        return f"Unknown trader '{trader}'. Use 'trader2' or 'trader3'."
    if action.lower() not in ("approve", "reject"):
        return "Invalid action. Use 'approve' or 'reject'."

    state_path = os.path.join(DATA_DIR, trader_map[trader.lower()])
    try:
        with open(state_path) as f:
            state = json.load(f)
    except Exception as e:
        return f"Error reading {trader} state: {e}"

    pending = state.get("pending_expiry_roll")
    if not pending:
        return f"No pending expiry roll for {trader}. System is clean."

    roll_summary = (
        f"{pending.get('old_expiry', '?')} → {pending.get('new_expiry', '?')} | "
        f"Strike: ${pending.get('strike', '?')} | "
        f"{pending.get('days_left', '?')}d remaining"
    )

    if action.lower() == "approve":
        state["expiry_roll_commander_approved"] = True
        state["expiry_roll_commander_rejected"] = False
        msg = f"✅ Expiry roll APPROVED for {trader.upper()}: {roll_summary}\nDaemon will execute on next check cycle."
    else:
        state["expiry_roll_commander_approved"] = False
        state["expiry_roll_commander_rejected"] = True
        msg = f"❌ Expiry roll REJECTED for {trader.upper()}: {roll_summary}\nKeeping current expiry."

    try:
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        return f"Error writing {trader} state: {e}"

    try:
        from telegram import send
        send(msg)
    except Exception:
        pass

    return msg


@mcp.tool()
def force_evaluation() -> str:
    """Trigger an immediate v2.8+ filter evaluation on the next trader loop."""
    signal = {
        "requested_at": datetime.now().isoformat(),
        "requested_by": "Commander via Cowork",
    }
    path = os.path.join(DATA_DIR, "force_eval.json")
    with open(path, "w") as f:
        json.dump(signal, f, indent=2)
    return f"Force evaluation signal written. Trader will run filters on next loop iteration."


@mcp.tool()
def send_telegram(message: str) -> str:
    """Send a message via Rudy's Telegram bot.

    Args:
        message: The message text to send (supports Markdown)
    """
    try:
        import telegram
        result = telegram.send(message)
        if result.get("ok"):
            return "Telegram message sent successfully."
        else:
            return f"Telegram send failed: {result}"
    except Exception as e:
        return f"Error sending Telegram: {e}"


# ══════════════════════════════════════════════════════════════
#  ENTRYPOINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run(transport="stdio")
