#!/usr/bin/env python3
"""BTC Sentinel — 24/7 BTC/USD Monitor with Telegram Alerts
=============================================================
Monitors BTC/USD around the clock (including weekends/holidays) via
CoinGecko free API and sends Telegram alerts when significant moves
happen relative to the last market-close anchor price.

Alerts fire at -5%, -10%, -15%, -20%, -25%, -30% from anchor (once each).
Thresholds reset at Monday 9:30 AM ET (market open).
Also monitors BTC vs 200-week SMA and estimates MSTR / mNAV impact.

Usage:
    python3 btc_sentinel.py              # Run as daemon (15-min loop)
    python3 btc_sentinel.py --status     # Print current state and exit

Author: Rudy v2.0
"""

import argparse
import atexit
import json
import os
import sys
import time
import traceback
from datetime import datetime

import requests

# ── Paths ──────────────────────────────────────────────────────────────
BASE = os.path.expanduser("~/rudy")
DATA = os.path.join(BASE, "data")
LOGS = os.path.join(BASE, "logs")
STATE_FILE = os.path.join(DATA, "btc_sentinel_state.json")
TRADER_STATE = os.path.join(DATA, "trader_v28_state.json")
LOG_FILE = os.path.join(LOGS, "btc_sentinel.log")
PID_FILE = os.path.join(DATA, "btc_sentinel.pid")

os.makedirs(DATA, exist_ok=True)
os.makedirs(LOGS, exist_ok=True)

# ── Constants ──────────────────────────────────────────────────────────
CHECK_INTERVAL_SEC = 15 * 60  # 15 minutes

DROP_THRESHOLDS = [-5, -10, -15, -20, -25, -30]  # % from anchor
MNAV_KILL_THRESHOLD = 0.75
MSTR_BTC_MULTIPLIER_LOW = 1.5
MSTR_BTC_MULTIPLIER_HIGH = 2.0

# Hardcoded 200W SMA fallback — used only when live Kraken fetch fails.
# CONSTITUTION RULE: IBKR is the single source of truth for prices. This
# fallback is stale-by-design. Recompute and update each quarter from the
# Kraken weekly history. As of early 2026 the 200-week SMA sits ~$42,000.
# TODO(quarterly): refresh this constant from `kraken_btc_200w.json` cache.
HARDCODED_200W_SMA = 42_000

# ── Logging ────────────────────────────────────────────────────────────
def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_telegram(msg):
    """Send a Telegram message using the shared telegram module."""
    try:
        sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
        import telegram as tg
        tg.send(msg)
        log(f"Telegram sent: {msg[:80]}...")
    except Exception as e:
        log(f"Telegram error: {e}", "ERROR")


def send_telegram_with_chart(msg, symbol="BTCUSD", timeframe="1D"):
    """Send Telegram message followed by a TradingView chart screenshot."""
    send_telegram(msg)
    try:
        sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
        import tradingview_cdp
        if tradingview_cdp.is_running():
            import telegram as tg
            png = tradingview_cdp.capture_chart(symbol=symbol, timeframe=timeframe)
            if png:
                tg.send_photo(png, caption=f"📊 *{symbol} {timeframe}* — BTC Sentinel Alert")
                log("TradingView chart attached to alert")
    except Exception as e:
        log(f"Chart capture skipped: {e}", "WARN")


# ── State Management ──────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return default_state()


def default_state():
    return {
        "anchor_price": None,
        "anchor_time": None,
        "alerts_sent": [],
        "btc_was_above_200w": None,
        "below_200w_alerted": False,
        "last_check": None,
        "premium_at_anchor": None,
    }


def save_state(state):
    state["last_check"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── ET Time Helpers ───────────────────────────────────────────────────
def get_et_now():
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York"))


def is_monday_market_open(now_et):
    """True at Monday 9:30 AM ET (within a 15-min window)."""
    if now_et.weekday() != 0:
        return False
    t = now_et.hour * 60 + now_et.minute
    return 570 <= t < 585  # 9:30 .. 9:44


def is_friday_after_close(now_et):
    """True on Friday between 4:00 PM and 4:30 PM ET."""
    if now_et.weekday() != 4:
        return False
    return now_et.hour == 16 and now_et.minute < 30


def is_weekday_after_close(now_et):
    """True on any weekday between 4:00 PM and 4:15 PM ET."""
    if now_et.weekday() >= 5:
        return False
    return now_et.hour == 16 and now_et.minute < 15


# ── Price Fetching ────────────────────────────────────────────────────
def fetch_btc_price():
    """Get current BTC/USD from CoinGecko (free, no auth)."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()["bitcoin"]["usd"]
    except Exception as e:
        log(f"CoinGecko fetch failed: {e}", "WARN")
        # Fallback: Binance
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": "BTCUSDT"},
                timeout=10,
            )
            return float(r.json()["price"])
        except Exception as e2:
            log(f"Binance fallback also failed: {e2}", "ERROR")
            return None


def fetch_btc_200w_sma():
    """Compute BTC 200W SMA from Kraken weekly candles.

    Falls back to Binance US, then to the hardcoded constant.
    """
    # Primary: Kraken OHLC (free, no auth)
    try:
        r = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": "XBTUSD", "interval": 10080},
            timeout=15,
        )
        data = r.json()
        if "result" in data:
            key = [k for k in data["result"] if k != "last"][0]
            candles = data["result"][key]
            weekly_closes = [float(c[4]) for c in candles]
            if len(weekly_closes) >= 200:
                sma = sum(weekly_closes[-200:]) / 200
                log(f"BTC 200W SMA (Kraken): ${sma:,.0f} ({len(weekly_closes)} weeks)")
                return sma
    except Exception as e:
        log(f"Kraken weekly klines failed: {e}", "WARN")

    # Fallback: Binance US
    try:
        r = requests.get(
            "https://api.binance.us/api/v3/klines",
            params={"symbol": "BTCUSD", "interval": "1w", "limit": 250},
            timeout=15,
        )
        klines = r.json()
        if isinstance(klines, list) and len(klines) >= 200:
            weekly_closes = [float(k[4]) for k in klines]
            sma = sum(weekly_closes[-200:]) / 200
            log(f"BTC 200W SMA (Binance US): ${sma:,.0f} ({len(weekly_closes)} weeks)")
            return sma
    except Exception as e:
        log(f"Binance US weekly klines failed: {e}", "WARN")

    # Hardcoded fallback — update periodically
    log(f"Using hardcoded 200W SMA: ${HARDCODED_200W_SMA:,}", "WARN")
    return HARDCODED_200W_SMA


def get_last_premium():
    """Read latest mNAV premium from trader_v28 state file.
    Returns None if unavailable or zero — caller treats None as 'no data, skip mNAV estimate'.
    """
    try:
        with open(TRADER_STATE) as f:
            trader = json.load(f)
        # Also try premium_history as fallback
        val = trader.get("last_premium") or (
            trader["premium_history"][-1] if trader.get("premium_history") else None
        )
        return val if val and val > 0 else None
    except Exception:
        return None


# ── Impact Calculations ───────────────────────────────────────────────
def estimate_mstr_impact(btc_change_pct):
    """MSTR roughly moves 1.5-2x BTC % moves."""
    low = btc_change_pct * MSTR_BTC_MULTIPLIER_LOW
    high = btc_change_pct * MSTR_BTC_MULTIPLIER_HIGH
    return low, high


def estimate_mnav(btc_change_pct, premium_at_anchor):
    """Rough mNAV premium estimate after BTC move."""
    # Treat None or 0 as no data — do not compute (prevents false kill switch from missing premium)
    if not premium_at_anchor:
        return None
    mstr_change = btc_change_pct * MSTR_BTC_MULTIPLIER_LOW
    return premium_at_anchor * (1 + mstr_change / 100)


def mnav_risk_label(est_premium):
    """Human-readable mNAV risk status."""
    if est_premium is None:
        return "UNKNOWN"
    if est_premium < MNAV_KILL_THRESHOLD:
        return f"DANGER (est. ~{est_premium:.2f}x)"
    if est_premium < 0.90:
        return f"ELEVATED (est. ~{est_premium:.2f}x)"
    return f"SAFE (premium ~{est_premium:.2f}x)"


# ── Alert Formatting ──────────────────────────────────────────────────
def format_threshold_alert(btc_now, anchor, change_pct, threshold, sma_200w, est_premium):
    """Build the standard threshold alert message."""
    severity = "\u26a0\ufe0f"
    if abs(threshold) >= 15:
        severity = "\U0001f6a8"
    if abs(threshold) >= 25:
        severity = "\U0001f6a8\U0001f6a8\U0001f6a8"

    mstr_low, mstr_high = estimate_mstr_impact(change_pct)
    next_thresholds = [t for t in DROP_THRESHOLDS if t < threshold]
    next_thresh = next_thresholds[0] if next_thresholds else None

    sma_status = f"${sma_200w:,.0f}" if sma_200w else "$42,000 (est.)"
    above_sma = btc_now > (sma_200w or HARDCODED_200W_SMA)

    lines = [
        f"{severity} BTC WEEKEND ALERT",
        f"BTC/USD: ${btc_now:,.0f} ({change_pct:+.1f}% from ${anchor:,.0f})",
        "\u2501" * 18,
        f"Est. MSTR impact: {mstr_low:+.1f}% to {mstr_high:+.1f}%",
        f"Current mNAV risk: {mnav_risk_label(est_premium)}",
        f"200W SMA: {sma_status} \u2014 BTC " + ("still above \u2705" if above_sma else "BELOW \u274c"),
        "\u2501" * 18,
    ]

    if next_thresh is not None:
        lines.append(f"Next alert threshold: {next_thresh}%")

    if est_premium is not None and est_premium < MNAV_KILL_THRESHOLD:
        lines.append(f"\u26a1 mNAV KILL SWITCH RISK \u2014 est. below {MNAV_KILL_THRESHOLD}x!")

    return "\n".join(lines)


def format_critical_200w_alert(btc_now, sma_200w):
    """Critical alert when BTC drops below 200-week SMA."""
    return "\n".join([
        "\U0001f6a8\U0001f6a8\U0001f6a8 BTC CRITICAL ALERT",
        "BTC dropped below 200-week SMA!",
        f"BTC/USD: ${btc_now:,.0f} | 200W SMA: ${sma_200w:,.0f}",
        "\u2501" * 18,
        "\u26a1 v2.8+ entry signal may ARM soon",
        "\u26a1 mNAV kill switch risk: CHECK MONDAY",
        "\u2501" * 18,
        "ACTION: Monitor closely before Monday open",
    ])


# ── Core Check Logic ─────────────────────────────────────────────────
def run_check(state):
    """Run one monitoring cycle. Returns updated state."""
    now_et = get_et_now()

    # ── Monday 9:30 AM ET: reset thresholds ──
    if is_monday_market_open(now_et):
        if state.get("alerts_sent"):
            log("Monday market open — resetting alert thresholds")
            state["alerts_sent"] = []
            state["below_200w_alerted"] = False

    # ── Record anchor price ──
    # Friday after close: snapshot as weekend anchor
    if is_friday_after_close(now_et):
        btc = fetch_btc_price()
        if btc:
            state["anchor_price"] = btc
            state["anchor_time"] = now_et.isoformat()
            state["alerts_sent"] = []
            state["below_200w_alerted"] = False
            state["premium_at_anchor"] = get_last_premium()
            state["last_price"] = btc  # dashboard display
            log(f"Friday close anchor: BTC ${btc:,.0f}")
        save_state(state)
        return state

    # Other weekdays after close: refresh anchor for overnight monitoring
    if is_weekday_after_close(now_et):
        btc = fetch_btc_price()
        if btc:
            state["anchor_price"] = btc
            state["anchor_time"] = now_et.isoformat()
            state["alerts_sent"] = []
            state["below_200w_alerted"] = False
            state["premium_at_anchor"] = get_last_premium()
            state["last_price"] = btc  # dashboard display
            log(f"Market close anchor: BTC ${btc:,.0f}")
        save_state(state)
        return state

    # ── Fetch current price ──
    btc_now = fetch_btc_price()
    if btc_now is None:
        log("Could not fetch BTC price — skipping cycle", "WARN")
        save_state(state)
        return state

    log(f"BTC/USD: ${btc_now:,.0f}")

    # If no anchor yet, use current price
    anchor = state.get("anchor_price")
    if not anchor:
        state["anchor_price"] = btc_now
        state["anchor_time"] = now_et.isoformat()
        state["premium_at_anchor"] = get_last_premium()
        state["last_price"] = btc_now  # dashboard display
        log(f"No anchor price — recording current BTC ${btc_now:,.0f} as anchor")
        save_state(state)
        return state

    change_pct = (btc_now - anchor) / anchor * 100
    alerts_sent = state.get("alerts_sent", [])
    premium = state.get("premium_at_anchor")
    est_premium = estimate_mnav(change_pct, premium)

    # ── Fetch 200W SMA ──
    sma_200w = fetch_btc_200w_sma()

    # ── Check drop thresholds ──
    for threshold in DROP_THRESHOLDS:
        key = f"drop_{abs(threshold)}"
        if change_pct <= threshold and key not in alerts_sent:
            msg = format_threshold_alert(
                btc_now, anchor, change_pct, threshold, sma_200w, est_premium
            )
            send_telegram_with_chart(msg, symbol="BTCUSD", timeframe="1D")
            alerts_sent.append(key)
            state["alerts_sent"] = alerts_sent
            log(f"ALERT SENT: BTC {change_pct:+.1f}% (threshold: {threshold}%)")

    # ── BTC below 200W SMA — critical alert ──
    if sma_200w and btc_now < sma_200w:
        was_above = state.get("btc_was_above_200w", True)
        already_alerted = state.get("below_200w_alerted", False)

        if (was_above or not already_alerted) and not already_alerted:
            msg = format_critical_200w_alert(btc_now, sma_200w)
            send_telegram_with_chart(msg, symbol="BTCUSD", timeframe="1W")
            state["below_200w_alerted"] = True
            log(f"CRITICAL ALERT: BTC ${btc_now:,.0f} below 200W SMA ${sma_200w:,.0f}")

        state["btc_was_above_200w"] = False
    elif sma_200w:
        if state.get("btc_was_above_200w") is False:
            log(f"BTC reclaimed 200W SMA: ${btc_now:,.0f} > ${sma_200w:,.0f}")
        state["btc_was_above_200w"] = True
        state["below_200w_alerted"] = False

    # ── mNAV kill switch proximity ──
    if est_premium is not None and est_premium < MNAV_KILL_THRESHOLD:
        kill_key = "mnav_kill_risk"
        if kill_key not in alerts_sent:
            msg = "\n".join([
                "\U0001f6a8\U0001f6a8\U0001f6a8 mNAV KILL SWITCH WARNING",
                f"Est. mNAV premium: {est_premium:.2f}x (threshold: {MNAV_KILL_THRESHOLD}x)",
                f"BTC: ${btc_now:,.0f} ({change_pct:+.1f}% from anchor)",
                "\u2501" * 18,
                "Review position exposure before Monday open!",
            ])
            send_telegram_with_chart(msg, symbol="BTCUSD", timeframe="1D")
            alerts_sent.append(kill_key)
            state["alerts_sent"] = alerts_sent
            log(f"KILL SWITCH WARNING: est. premium {est_premium:.2f}x")

    state["last_price"] = btc_now  # dashboard display — always current
    save_state(state)
    log(f"Check complete. BTC ${btc_now:,.0f} | {change_pct:+.1f}% from anchor ${anchor:,.0f}")
    return state


# ── Status Display ────────────────────────────────────────────────────
def show_status():
    """Print current sentinel state without starting the loop."""
    state = load_state()
    anchor = state.get("anchor_price")
    anchor_time = state.get("anchor_time", "N/A")
    alerts = state.get("alerts_sent", [])
    last_check = state.get("last_check", "N/A")
    premium = state.get("premium_at_anchor")

    print("=" * 50)
    print("BTC SENTINEL STATUS")
    print("=" * 50)
    print(f"Anchor price:     ${anchor:,.0f}" if anchor else "Anchor price:     Not set")
    print(f"Anchor time:      {anchor_time}")
    print(f"Premium at anchor:{f' {premium:.2f}x' if premium else ' N/A'}")
    print(f"Last check:       {last_check}")
    print(f"Alerts sent:      {alerts if alerts else 'None'}")
    print(f"200W SMA status:  {'Above' if state.get('btc_was_above_200w') else 'Below/Unknown'}")
    print(f"PID file:         {PID_FILE}")
    print()

    # Fetch live price for comparison
    btc = fetch_btc_price()
    if btc and anchor:
        change = (btc - anchor) / anchor * 100
        print(f"Live BTC/USD:     ${btc:,.0f} ({change:+.1f}% from anchor)")
        mstr_low, mstr_high = estimate_mstr_impact(change)
        print(f"Est. MSTR impact: {mstr_low:+.1f}% to {mstr_high:+.1f}%")
        est_prem = estimate_mnav(change, premium)
        if est_prem:
            print(f"Est. mNAV:        {est_prem:.2f}x — {mnav_risk_label(est_prem)}")
    elif btc:
        print(f"Live BTC/USD:     ${btc:,.0f}")
    print("=" * 50)


# ── Daemon Loop ───────────────────────────────────────────────────────
def run_daemon():
    """Continuous monitoring loop — checks every 15 minutes."""
    log("=" * 50)
    log("BTC SENTINEL — Starting daemon loop")
    log(f"Check interval: {CHECK_INTERVAL_SEC}s ({CHECK_INTERVAL_SEC // 60} min)")
    log("=" * 50)

    state = load_state()

    while True:
        try:
            state = run_check(state)
        except Exception as e:
            log(f"Check cycle error: {e}", "ERROR")
            log(traceback.format_exc(), "ERROR")
            # Don't crash — wait and retry next cycle

        try:
            time.sleep(CHECK_INTERVAL_SEC)
        except KeyboardInterrupt:
            log("Keyboard interrupt — shutting down")
            break


# ── Entry Point ───────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="BTC Sentinel — 24/7 BTC/USD Monitor")
    parser.add_argument("--status", action="store_true", help="Show current state and exit")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    # ── PID LOCKFILE — prevent duplicate daemons ──
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)  # Check if still alive
            log(f"ABORT: BTC Sentinel already running (PID {old_pid}). Delete {PID_FILE} to override.", "ERROR")
            sys.exit(1)
        except (ProcessLookupError, ValueError, PermissionError):
            pass  # Old process is dead/inaccessible, safe to continue

    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.remove(PID_FILE) if os.path.exists(PID_FILE) else None)
    log(f"PID lockfile created: {PID_FILE} (PID {os.getpid()})")

    run_daemon()


if __name__ == "__main__":
    main()
