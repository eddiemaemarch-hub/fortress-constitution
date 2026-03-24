#!/usr/bin/env python3
"""
Daily Status Reporter — Rudy v2.0 (Constitution v50.0)
======================================================
Sends scheduled Telegram status updates so the Commander always knows
what's happening — even when there's no trade activity.

Schedule (via LaunchAgent calendar intervals):
  - 9:35 AM ET  — Market open briefing (positions, filters, account)
  - 12:00 PM ET — Midday check-in (position P&L, any filter changes)
  - 4:05 PM ET  — Market close summary (day's activity, final P&L)

Reads from existing state files — no IBKR connection needed.
"""

import json
import os
import sys
from datetime import datetime

# ── Paths ──
BASE = os.path.expanduser("~/rudy")
DATA = os.path.join(BASE, "data")
LOGS = os.path.join(BASE, "logs")
TRADER_STATE = os.path.join(DATA, "trader_v28_state.json")
TRADER2_STATE = os.path.join(DATA, "trader2_state.json")
TRADER3_STATE = os.path.join(DATA, "trader3_state.json")
ACCT_STATE = os.path.join(DATA, "accountant_live.json")
BREAKER_STATE = os.path.join(DATA, "breaker_state.json")
LOG_FILE = os.path.join(LOGS, "daily_status.log")

# ── Telegram ──
sys.path.insert(0, os.path.join(BASE, "scripts"))
try:
    import telegram
except ImportError:
    telegram = None


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_telegram(text):
    if telegram:
        try:
            telegram.send(text)
            log(f"Telegram sent ({len(text)} chars)")
        except Exception as e:
            log(f"Telegram send failed: {e}", "ERROR")
    else:
        log("Telegram module not available", "WARN")


def _load(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_update_type():
    """Determine which update to send based on current ET time."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/New_York"))
    hour = now.hour

    if hour < 10:
        return "open"
    elif hour < 14:
        return "midday"
    else:
        return "close"


def build_status_message(update_type):
    """Build the Telegram status message from all state files."""

    # Load all states
    trader = _load(TRADER_STATE)
    trader2 = _load(TRADER2_STATE)
    trader3 = _load(TRADER3_STATE)
    acct = _load(ACCT_STATE)
    breaker = _load(BREAKER_STATE)

    now_str = datetime.now().strftime("%I:%M %p ET")

    # Header
    if update_type == "open":
        header = f"☀️ *MARKET OPEN BRIEFING* — {now_str}"
    elif update_type == "midday":
        header = f"🕛 *MIDDAY CHECK-IN* — {now_str}"
    else:
        header = f"🌙 *MARKET CLOSE SUMMARY* — {now_str}"

    msg = f"{header}\n"

    # ── Account ──
    nlv = trader.get("safety", {}).get("nlv_open")
    if nlv:
        msg += f"\n💰 *Account*: ${nlv:,.2f}"
    if acct.get("net_liq"):
        msg += f" (NLV: ${acct['net_liq']:,.2f})"
    msg += "\n"

    # ── MSTR / BTC Prices ──
    mstr = trader.get("last_mstr_price")
    btc = trader.get("last_btc_price")
    premium = trader.get("last_premium", 0)
    if mstr:
        msg += f"\n📊 MSTR: ${mstr:.2f}"
    if btc:
        msg += f" | BTC: ${btc:,.0f}"
    if premium:
        msg += f" | mNAV: {premium:.2f}x"
    msg += "\n"

    # ── v2.8+ Status ──
    armed = trader.get("is_armed", False)
    in_position = trader.get("position_qty", 0) > 0
    stoch_rsi = trader.get("last_stoch_rsi")

    msg += f"\n🎯 *v2.8+ Status*\n"
    msg += f"  Armed: {'✅ YES' if armed else '❌ No'}\n"
    msg += f"  In Position: {'✅ YES' if in_position else '❌ No'}\n"
    if stoch_rsi is not None:
        msg += f"  StochRSI: {stoch_rsi} ({'✅ <70' if stoch_rsi < 70 else '❌ ≥70'})\n"

    if in_position:
        entry = trader.get("entry_price", 0)
        peak = trader.get("peak_gain_pct", 0)
        msg += f"  Entry: ${entry:.2f} | Peak Gain: {peak:.1f}%\n"

    # ── Put Positions ──
    msg += f"\n📉 *Put Hedges*\n"

    if trader2:
        t2_gain = trader2.get("last_gain_pct", 0)
        t2_value = trader2.get("last_value", 0)
        t2_emoji = "🟢" if t2_gain >= 0 else "🔴"
        msg += f"  {t2_emoji} MSTR $50P: ${t2_value:,.0f} ({t2_gain:+.1f}%)"
        if trader2.get("activated"):
            msg += f" | Trail T{trader2.get('current_tier', 0)} active"
        msg += "\n"

    if trader3:
        t3_gain = trader3.get("last_gain_pct", 0)
        t3_value = trader3.get("last_value", 0)
        t3_emoji = "🟢" if t3_gain >= 0 else "🔴"
        msg += f"  {t3_emoji} SPY $430P: ${t3_value:,.0f} ({t3_gain:+.1f}%)"
        if trader3.get("activated"):
            msg += f" | Trail T{trader3.get('current_tier', 0)} active"
        msg += "\n"

    # ── Circuit Breakers ──
    halt = breaker.get("global_halt", False)
    kill = trader.get("mnav_kill_triggered", False)

    if halt or kill:
        msg += f"\n🚨 *ALERTS*\n"
        if halt:
            msg += f"  ⛔ GLOBAL HALT ACTIVE — {breaker.get('halt_reason', 'unknown')}\n"
        if kill:
            msg += f"  ⚡ mNAV KILL SWITCH TRIGGERED\n"
    else:
        msg += f"\n✅ All circuit breakers clear\n"

    # ── Last Eval ──
    last_eval = trader.get("last_eval")
    if last_eval:
        try:
            eval_dt = datetime.fromisoformat(last_eval)
            msg += f"\n🕐 Last eval: {eval_dt.strftime('%I:%M %p')}"
        except Exception:
            pass

    # ── Close-specific: day summary ──
    if update_type == "close":
        daily_loss = 0
        if nlv:
            # We'd need current NLV to compute, but just note it
            msg += f"\n📋 NLV at open: ${nlv:,.2f}"
        msg += "\n\n_Next eval: Monday 3:45 PM ET_" if datetime.now().weekday() == 4 else "\n\n_Next eval: Tomorrow 3:45 PM ET_"

    return msg


def main():
    log("=" * 50)
    log("DAILY STATUS REPORTER — Running")
    log("=" * 50)

    update_type = get_update_type()
    log(f"Update type: {update_type}")

    msg = build_status_message(update_type)
    send_telegram(msg)

    log("Done")


if __name__ == "__main__":
    main()
