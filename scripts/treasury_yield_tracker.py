#!/usr/bin/env python3
"""
10-Year Treasury Yield Tracker
Fetches 10Y Treasury yield from Yahoo Finance and tracks daily changes.
Used as a macro signal for BTC/risk asset positioning.

Rising 10Y yield → higher opportunity cost → headwind for BTC
Falling 10Y yield → supportive for risk assets
"""

import json
import os
import sys
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError

STATE_FILE = os.path.expanduser("~/rudy/data/treasury_yield.json")
LOG_FILE = os.path.expanduser("~/rudy/logs/treasury_yield.log")


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def fetch_10y_yield():
    """Fetch current 10Y Treasury yield from Yahoo Finance (^TNX)."""
    # ^TNX is the CBOE 10-Year Treasury Note Yield Index (yield × 10, so divide by 10 for %)
    url = "https://query1.finance.yahoo.com/v8/finance/chart/^TNX?interval=1d&range=5d"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        result = data["chart"]["result"][0]
        meta = result["meta"]
        quotes = result["indicators"]["quote"][0]
        closes = [c for c in quotes["close"] if c is not None]
    except (URLError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        log(f"Fetch error: {e}", "ERROR")
        return None

    current = meta.get("regularMarketPrice")
    prev_close = meta.get("previousClose") or (closes[-2] if len(closes) >= 2 else None)
    day_high = meta.get("regularMarketDayHigh")
    day_low = meta.get("regularMarketDayLow")

    return {
        "yield_pct": round(current, 3) if current else None,
        "prev_close_pct": round(prev_close, 3) if prev_close else None,
        "day_high_pct": round(day_high, 3) if day_high else None,
        "day_low_pct": round(day_low, 3) if day_low else None,
        "recent_closes": [round(c, 3) for c in closes[-5:]],
    }


def classify_macro(y):
    """Classify macro regime from 10Y yield level and trend."""
    if y is None:
        return "UNKNOWN"
    if y >= 5.0:
        return "EXTREME_HIGH"      # severe pressure on risk assets
    if y >= 4.5:
        return "HIGH"              # headwind for BTC
    if y >= 4.0:
        return "ELEVATED"          # mild headwind
    if y >= 3.5:
        return "NEUTRAL"
    if y >= 3.0:
        return "SUPPORTIVE"        # tailwind for risk
    return "LOW"                   # strong tailwind


def main():
    log("=" * 60)
    log("10Y Treasury Yield Tracker — scan start")

    data = fetch_10y_yield()
    if not data or data["yield_pct"] is None:
        log("No data returned", "ERROR")
        sys.exit(1)

    y = data["yield_pct"]
    prev = data["prev_close_pct"]
    if prev is not None and prev != 0:
        change_bps = round((y - prev) * 100, 1)  # basis points
        change_pct = round(((y - prev) / prev) * 100, 2)
    else:
        change_bps = None
        change_pct = None

    regime = classify_macro(y)

    state = {
        "last_updated": datetime.now().isoformat(),
        "yield_pct": y,
        "prev_close_pct": prev,
        "change_bps": change_bps,
        "change_pct": change_pct,
        "day_high_pct": data["day_high_pct"],
        "day_low_pct": data["day_low_pct"],
        "recent_closes": data["recent_closes"],
        "macro_regime": regime,
        "btc_implication": {
            "EXTREME_HIGH": "Strong headwind — risk-off pressure",
            "HIGH": "Headwind for BTC — monitor flows",
            "ELEVATED": "Mild headwind",
            "NEUTRAL": "Neutral",
            "SUPPORTIVE": "Tailwind for risk assets",
            "LOW": "Strong tailwind — liquidity supportive",
            "UNKNOWN": "Insufficient data",
        }[regime],
    }

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    sign = "+" if (change_bps or 0) >= 0 else ""
    log(f"10Y: {y}% | Change: {sign}{change_bps}bps ({sign}{change_pct}%) | Regime: {regime}")
    log(f"BTC implication: {state['btc_implication']}")
    log("Scan complete")


if __name__ == "__main__":
    main()
