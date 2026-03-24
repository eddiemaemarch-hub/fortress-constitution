"""Scanner — Autonomous Market Scanner for All Systems
Runs hourly during market hours + pre-market + end-of-day.
Constitution v43.0 — ALL systems, ALL scanners, EVERY day.
"""
import os
import sys
import time
from datetime import datetime
import pytz

sys.path.insert(0, os.path.dirname(__file__))

LOG_DIR = os.path.expanduser("~/rudy/logs")
os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Scanner {ts}] {msg}")
    with open(f"{LOG_DIR}/scanner.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def is_market_hours():
    """Check if US market is open (9:30 AM - 4:00 PM ET, weekdays)."""
    et = pytz.timezone("US/Eastern")
    now = datetime.now(et)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0)
    market_close = now.replace(hour=16, minute=0, second=0)
    return market_open <= now <= market_close


def run_intel_scanners():
    """Run all intelligence/data scanners — works anytime, no IBKR needed."""
    # Accountant — Live account snapshot
    try:
        import accountant
        log("--- Accountant: Live Snapshot ---")
        accountant.refresh_live_snapshot()
    except Exception as e:
        log(f"Accountant error: {e}")

    # DeepSeek — Market Regime Detection
    try:
        import deepseek_analyst
        log("--- DeepSeek: Market Regime Check ---")
        deepseek_analyst.detect_regime()
    except Exception as e:
        log(f"DeepSeek regime error: {e}")

    # Grok — Real-time X/Twitter Intelligence (primary)
    try:
        import grok_scanner
        log("--- Grok: Real-time X Intelligence ---")
        grok_scanner.scan_realtime()
    except Exception as e:
        log(f"Grok error: {e}")

    # Gronk — X/Twitter Intelligence Scanner (backup via Tavily)
    try:
        import gronk
        log("--- Gronk: X Intelligence Scan ---")
        gronk.scan_x()
    except Exception as e:
        log(f"Gronk error: {e}")

    # YouTube — Finance YouTube Intelligence
    try:
        import youtube_scanner
        log("--- YouTube: Finance Video Intelligence ---")
        youtube_scanner.scan_youtube()
    except Exception as e:
        log(f"YouTube error: {e}")

    # Truth Social — Trump Post Intelligence
    try:
        import truth_scanner
        log("--- Truth Social: Trump Intelligence ---")
        truth_scanner.scan_truth()
    except Exception as e:
        log(f"Truth Social error: {e}")

    # TikTok — FinTok Intelligence & 10X Hunters
    try:
        import tiktok_scanner
        log("--- TikTok: FinTok Intelligence ---")
        tiktok_scanner.scan_tiktok()
    except Exception as e:
        log(f"TikTok error: {e}")

    # Insider — Corporate Insider Buy/Sell Tracking
    try:
        import insider_scanner
        log("--- Insider: Corporate Insider Trades ---")
        insider_scanner.scan_insiders()
    except Exception as e:
        log(f"Insider error: {e}")

    # Congress — Congressional Stock Trade Intelligence
    try:
        import congress_scanner
        log("--- Congress: Stock Trade Scan ---")
        congress_scanner.scan_congress()
    except Exception as e:
        log(f"Congress error: {e}")

    # X Tracker — Influencer Post Intelligence
    try:
        import x_tracker
        log("--- X Tracker: Influencer Scan ---")
        x_tracker.scan_all()
    except Exception as e:
        log(f"X Tracker error: {e}")

    # Playlist Tracker — YouTube Playlist Monitoring
    try:
        import playlist_tracker
        log("--- Playlist: YouTube Monitoring ---")
        playlist_tracker.scan_playlist()
    except Exception as e:
        log(f"Playlist error: {e}")

    # Memory — Market Context Snapshot
    try:
        import memory
        log("--- Memory: Context Snapshot ---")
        memory.snapshot_context()
    except Exception as e:
        log(f"Memory error: {e}")


def run_traders():
    """Run all trader systems — DISABLED as of v2.4.
    All legacy traders (3-12) turned off. Only v2.4 MSTR Cycle-Low LEAP runs via TradingView/IBKR.
    Intel + monitoring remain active."""
    log("Traders 3-12 DISABLED (v2.4 — only MSTR Cycle-Low LEAP active via TradingView)")
    return
    # === LEGACY TRADERS BELOW — DISABLED ===
    # Trader3 — Energy Momentum Options
    try:
        import trader3
        log("--- Trader3: Energy Momentum ---")
        trader3.check_exits()
        trader3.scan_and_enter()
    except Exception as e:
        log(f"Trader3 error: {e}")

    # Trader4 — Short Squeeze Options
    try:
        import trader4
        log("--- Trader4: Short Squeeze ---")
        trader4.check_exits()
        trader4.scan_and_enter()
    except Exception as e:
        log(f"Trader4 error: {e}")

    # Trader5 — Breakout Momentum Options
    try:
        import trader5
        log("--- Trader5: Breakout Momentum ---")
        trader5.check_exits()
        trader5.scan_and_enter()
    except Exception as e:
        log(f"Trader5 error: {e}")

    # Trader6 — Metals Momentum Options
    try:
        import trader6
        log("--- Trader6: Metals Momentum ---")
        trader6.check_exits()
        trader6.scan_and_enter()
    except Exception as e:
        log(f"Trader6 error: {e}")

    # Trader7 — SpaceX IPO Options
    try:
        import trader7
        log("--- Trader7: SpaceX IPO ---")
        trader7.check_ipo_status()
        trader7.check_exits()
        trader7.scan_and_enter()
    except Exception as e:
        log(f"Trader7 error: {e}")

    # Trader8 — 10X Moonshot Options
    try:
        import trader8
        log("--- Trader8: 10X Moonshot ---")
        trader8.check_exits()
        trader8.scan_and_enter()
    except Exception as e:
        log(f"Trader8 error: {e}")

    # Trader9 — SCHD Income PMCC
    try:
        import trader9
        log("--- Trader9: SCHD Income PMCC ---")
        trader9.check_exits()
        trader9.scan_and_enter()
    except Exception as e:
        log(f"Trader9 error: {e}")

    # Trader10 — SPY PMCC
    try:
        import trader10
        log("--- Trader10: SPY PMCC ---")
        trader10.check_exits()
        trader10.scan_and_enter()
    except Exception as e:
        log(f"Trader10 error: {e}")

    # Trader11 — QQQ Growth Collar
    try:
        import trader11
        log("--- Trader11: QQQ Growth Collar ---")
        trader11.check_exits()
        trader11.scan_and_enter()
    except Exception as e:
        log(f"Trader11 error: {e}")

    # Trader12 — TQQQ Momentum
    try:
        import trader12
        log("--- Trader12: TQQQ Momentum ---")
        trader12.check_exits()
        trader12.scan_and_enter()
    except Exception as e:
        log(f"Trader12 error: {e}")


def run_scan(mode="market"):
    """Run scans based on mode.

    Modes:
        market  — Full scan (traders + intel) during market hours
        intel   — Intel scanners only (pre-market, post-market, weekends)
        force   — Everything regardless of market hours
        eod     — End-of-day: intel + daily report + auditor
    """
    log("=" * 50)
    log(f"Starting scan cycle (mode={mode})")

    if mode == "market":
        if not is_market_hours():
            log("Market closed — skipping market scan")
            log("=" * 50)
            return
        run_traders()
        run_intel_scanners()

    elif mode == "intel":
        run_intel_scanners()

    elif mode == "force":
        run_traders()
        run_intel_scanners()

    elif mode == "eod":
        run_intel_scanners()
        # Daily report
        try:
            import daily_report
            log("--- Daily Report ---")
            daily_report.run_daily_report()
        except Exception as e:
            log(f"Daily report error: {e}")
        # Auditor
        try:
            import auditor
            log("--- Auditor: Daily Audit ---")
            auditor.run_daily_audit()
        except Exception as e:
            log(f"Auditor error: {e}")

    log("Scan cycle complete")
    log("=" * 50)


if __name__ == "__main__":
    import sys as _sys
    mode = "market"
    if len(_sys.argv) > 1:
        arg = _sys.argv[1].lstrip("-")
        if arg in ("force", "intel", "eod", "market"):
            mode = arg
        elif arg == "force":
            mode = "force"
    run_scan(mode)
