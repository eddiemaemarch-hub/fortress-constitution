#!/usr/bin/env python3
"""Paper Monitor — Rudy v2.2 Cycle-Low Signal Scanner
Runs every 5 minutes during market hours. Checks MSTR vs 200W SMA,
computes mNAV premium, tracks dip+reclaim pattern, sends Telegram alerts.

Usage:
  python3 scripts/paper_monitor.py          # Run once
  python3 scripts/paper_monitor.py --cron   # Install as cron job

Cron schedule (every 5 min, market hours M-F):
  */5 9-16 * * 1-5 cd ~/rudy && python3 scripts/paper_monitor.py >> logs/paper_monitor.log 2>&1
"""
import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from subprocess import run as subprocess_run

sys.path.insert(0, os.path.dirname(__file__))

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "paper_monitor.log")
STATE_FILE = os.path.join(DATA_DIR, "monitor_state.json")

# MSTR constants (update quarterly)
BTC_HOLDINGS = 738731
SHARES_OUT_M = 335.0  # millions

# v2.2 Production thresholds
SMA_PERIOD = 200  # weeks
PREMIUM_CAP = 1.5
GREEN_CANDLES_TO_ARM = 2
STOCH_RSI_THRESHOLD = 70


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def send_telegram(msg):
    try:
        import telegram
        telegram.send(msg)
    except Exception as e:
        log(f"  Telegram error: {e}")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "dipped_below_200w": False,
        "green_count_above_200w": 0,
        "armed": False,
        "last_alert": None,
        "last_mstr_price": 0,
        "last_btc_price": 0,
        "last_200w_sma": 0,
        "last_premium": 0,
        "entry_signals": [],
        "daily_closes": [],  # Track daily closes for green candle counting
    }


def save_state(state):
    state["last_updated"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_prices():
    """Fetch MSTR and BTC prices via free APIs."""
    import urllib.request
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    mstr_price = None
    btc_price = None

    # MSTR from Yahoo Finance
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/MSTR?range=1d&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read())
            result = data["chart"]["result"][0]
            meta = result["meta"]
            mstr_price = meta.get("regularMarketPrice", meta.get("previousClose", 0))
    except Exception as e:
        log(f"  Yahoo MSTR error: {e}")

    # BTC from CoinGecko
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read())
            btc_price = data["bitcoin"]["usd"]
    except Exception as e:
        log(f"  CoinGecko BTC error: {e}")

    return mstr_price, btc_price


def fetch_mstr_200w_sma():
    """Fetch MSTR 200-week SMA from Yahoo Finance historical data."""
    import urllib.request
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        # Get ~5 years of weekly data
        end = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=365 * 5)).timestamp())
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/MSTR?period1={start}&period2={end}&interval=1wk"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            data = json.loads(resp.read())
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]

            # Filter None values
            valid_closes = [c for c in closes if c is not None]

            if len(valid_closes) >= SMA_PERIOD:
                sma = sum(valid_closes[-SMA_PERIOD:]) / SMA_PERIOD
                return sma, valid_closes
            else:
                log(f"  Only {len(valid_closes)} weekly closes available (need {SMA_PERIOD})")
                if len(valid_closes) >= 50:
                    sma = sum(valid_closes) / len(valid_closes)
                    return sma, valid_closes
                return None, valid_closes
    except Exception as e:
        log(f"  Yahoo MSTR weekly error: {e}")
        return None, []


def compute_premium(mstr_price, btc_price):
    """Compute mNAV premium = MSTR market cap / BTC holdings value."""
    if not mstr_price or not btc_price:
        return None
    nav_per_share = (btc_price * BTC_HOLDINGS) / (SHARES_OUT_M * 1_000_000)
    if nav_per_share <= 0:
        return None
    return mstr_price / nav_per_share


def check_signals(state, mstr_price, btc_price, sma_200w, premium):
    """Check for v2.2 entry/exit signals."""
    alerts = []

    if not mstr_price or not sma_200w:
        return alerts

    below_200w = mstr_price < sma_200w
    above_200w = mstr_price > sma_200w
    was_below = state.get("dipped_below_200w", False)

    # Track daily close for green candle detection
    today = datetime.now().strftime("%Y-%m-%d")
    daily_closes = state.get("daily_closes", [])

    # Add today's close (deduplicate by date)
    daily_closes = [d for d in daily_closes if d.get("date") != today]
    daily_closes.append({"date": today, "close": mstr_price})
    # Keep last 30 days
    daily_closes = daily_closes[-30:]
    state["daily_closes"] = daily_closes

    # Detect green candle (today's close > yesterday's close)
    green_candle = False
    if len(daily_closes) >= 2:
        yesterday_close = daily_closes[-2]["close"]
        green_candle = mstr_price > yesterday_close

    # Phase 1: Track dip below 200W SMA
    if below_200w and not was_below:
        state["dipped_below_200w"] = True
        state["green_count_above_200w"] = 0
        state["armed"] = False
        alerts.append({
            "type": "DIP_BELOW_200W",
            "severity": "INFO",
            "message": (
                f"*MSTR 200W DIP DETECTED*\n\n"
                f"MSTR ${mstr_price:.2f} dropped BELOW 200W SMA ${sma_200w:.2f}\n"
                f"Cycle low zone entered. Dip flag SET.\n"
                f"Watch for reclaim + green candles above."
            )
        })

    # Phase 2: Count green candles above 200W after dip
    if was_below and above_200w:
        if green_candle:
            state["green_count_above_200w"] = state.get("green_count_above_200w", 0) + 1
            gc = state["green_count_above_200w"]

            if gc == 1:
                alerts.append({
                    "type": "RECLAIM_START",
                    "severity": "INFO",
                    "message": (
                        f"*MSTR 200W RECLAIM IN PROGRESS*\n\n"
                        f"MSTR ${mstr_price:.2f} above 200W SMA ${sma_200w:.2f}\n"
                        f"Green candle #{gc} above SMA after dip.\n"
                        f"Need {GREEN_CANDLES_TO_ARM} to ARM. Watch closely."
                    )
                })

            if gc >= GREEN_CANDLES_TO_ARM and not state.get("armed"):
                state["armed"] = True
                prem_text = f"{premium:.2f}x" if premium else "N/A"
                prem_ok = premium and premium <= PREMIUM_CAP

                alerts.append({
                    "type": "ARMED",
                    "severity": "CRITICAL",
                    "message": (
                        f"*🚨 MSTR 200W DIP+RECLAIM ARMED 🚨*\n\n"
                        f"MSTR ${mstr_price:.2f} | 200W SMA ${sma_200w:.2f}\n"
                        f"Green candles above SMA: {gc}\n"
                        f"mNAV Premium: {prem_text} {'✅ ≤1.5x' if prem_ok else '❌ >1.5x'}\n"
                        f"BTC: ${btc_price:,.0f}\n\n"
                        f"{'ENTRY GATE OPEN — Review and prepare LEAP orders!' if prem_ok else 'Premium too high — wait for compression below 1.5x.'}\n\n"
                        f"v2.2 Config: 10x LEAP mult, 25% risk capital, panic floor -25%"
                    )
                })

        elif below_200w:
            # Lost the reclaim — reset
            state["green_count_above_200w"] = 0
            state["armed"] = False
            alerts.append({
                "type": "RECLAIM_LOST",
                "severity": "WARNING",
                "message": (
                    f"*MSTR 200W RECLAIM LOST*\n\n"
                    f"MSTR ${mstr_price:.2f} dropped back BELOW 200W SMA ${sma_200w:.2f}\n"
                    f"Green counter RESET. False reclaim — continue waiting."
                )
            })

    # If armed + premium OK → FULL ENTRY SIGNAL
    if state.get("armed") and premium and premium <= PREMIUM_CAP:
        # Check if we already sent the full entry signal today
        last_entry_signal = state.get("last_entry_signal_date", "")
        if last_entry_signal != today:
            state["last_entry_signal_date"] = today
            state["entry_signals"].append({
                "date": today,
                "mstr_price": mstr_price,
                "btc_price": btc_price,
                "premium": premium,
                "sma_200w": sma_200w,
            })
            alerts.append({
                "type": "ENTRY_SIGNAL",
                "severity": "CRITICAL",
                "message": (
                    f"*🔥 MSTR CYCLE-LOW ENTRY SIGNAL 🔥*\n\n"
                    f"ALL CONDITIONS MET:\n"
                    f"✅ 200W SMA dip+reclaim confirmed\n"
                    f"✅ {state['green_count_above_200w']} green candles above SMA\n"
                    f"✅ mNAV premium: {premium:.2f}x (≤{PREMIUM_CAP}x)\n"
                    f"✅ MSTR: ${mstr_price:.2f} | BTC: ${btc_price:,.0f}\n\n"
                    f"ACTION: Review and execute LEAP entry.\n"
                    f"Size: 25% of $130k = $32,500 (first tranche 50% = $16,250)\n"
                    f"Targets: 2028/2029 far-OTM calls\n\n"
                    f"v2.2 Production — QC validated +31.2% net"
                )
            })

    # Reset dip flag after sustained run above 200W (10+ candles = new bull phase)
    if state.get("green_count_above_200w", 0) > GREEN_CANDLES_TO_ARM + 10:
        state["dipped_below_200w"] = False
        state["armed"] = False
        state["green_count_above_200w"] = 0

    # Update state
    state["last_mstr_price"] = mstr_price
    state["last_btc_price"] = btc_price
    state["last_200w_sma"] = sma_200w
    state["last_premium"] = premium

    return alerts


def install_cron():
    """Install cron job for monitoring."""
    cron_line = "*/5 9-16 * * 1-5 cd ~/rudy && /usr/bin/python3 scripts/paper_monitor.py >> logs/paper_monitor.log 2>&1"

    # Check if already installed
    result = subprocess_run(["crontab", "-l"], capture_output=True, text=True)
    current = result.stdout if result.returncode == 0 else ""

    if "paper_monitor.py" in current:
        print("Cron job already installed:")
        for line in current.strip().split("\n"):
            if "paper_monitor" in line:
                print(f"  {line}")
        return

    new_cron = current.rstrip() + "\n" + cron_line + "\n"
    proc = subprocess_run(["crontab", "-"], input=new_cron, capture_output=True, text=True)
    if proc.returncode == 0:
        print(f"✅ Cron job installed: {cron_line}")
    else:
        print(f"❌ Failed to install cron: {proc.stderr}")


def main():
    parser = argparse.ArgumentParser(description="Rudy v2.2 Paper Monitor")
    parser.add_argument("--cron", action="store_true", help="Install as cron job")
    parser.add_argument("--status", action="store_true", help="Show current state")
    args = parser.parse_args()

    if args.cron:
        install_cron()
        return

    state = load_state()

    if args.status:
        print(json.dumps(state, indent=2))
        return

    log("─── Paper Monitor Check ───")

    # Fetch prices
    mstr_price, btc_price = fetch_prices()
    if not mstr_price:
        log("  ❌ Could not fetch MSTR price — skipping")
        return
    if not btc_price:
        log("  ⚠️  Could not fetch BTC price — premium unavailable")

    # Fetch 200W SMA
    sma_200w, weekly_closes = fetch_mstr_200w_sma()
    if not sma_200w:
        log("  ⚠️  Could not compute 200W SMA — using last known")
        sma_200w = state.get("last_200w_sma", 0)
        if not sma_200w:
            log("  ❌ No 200W SMA available — skipping")
            return

    # Compute premium
    premium = compute_premium(mstr_price, btc_price)

    # Log current state
    dist_pct = ((mstr_price - sma_200w) / sma_200w * 100) if sma_200w else 0
    prem_text = f"{premium:.2f}x" if premium else "N/A"
    log(f"  MSTR: ${mstr_price:.2f} | 200W SMA: ${sma_200w:.2f} ({'+' if dist_pct > 0 else ''}{dist_pct:.1f}%)")
    log(f"  BTC: ${btc_price:,.0f}" if btc_price else "  BTC: N/A")
    log(f"  mNAV Premium: {prem_text} | Dip flag: {state.get('dipped_below_200w', False)} | Green count: {state.get('green_count_above_200w', 0)} | Armed: {state.get('armed', False)}")

    # Check signals
    alerts = check_signals(state, mstr_price, btc_price, sma_200w, premium)

    # Send alerts
    for alert in alerts:
        log(f"  🚨 ALERT [{alert['type']}]: {alert['severity']}")
        send_telegram(alert["message"])

    if not alerts:
        log("  No new signals.")

    # Save state
    save_state(state)


if __name__ == "__main__":
    main()
