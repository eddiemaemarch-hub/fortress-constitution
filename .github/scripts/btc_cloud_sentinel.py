#!/usr/bin/env python3
"""
BTC Cloud Sentinel — runs on GitHub Actions every 4 hours.

Independent of Mac mini. Monitors BTC price and 10Y Treasury yield,
sends Telegram alerts for:
  - BTC drop >5% in 4 hours
  - BTC crosses below 200W SMA (~$60,085 as of April 2026)
  - 10Y yield spikes >10bps in a day
  - Scheduled heartbeat so Commander knows it's alive

Uses public APIs only — no API keys needed except Telegram.
"""

import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

# ==== Configuration ====
BTC_200W_SMA = 60085          # from btc_sentinel memory
DROP_ALERT_PCT = 5.0          # alert if BTC drops >5%
YIELD_SPIKE_BPS = 10          # alert if 10Y jumps >10bps

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def get_btc_price():
    """CoinGecko public API (no key)."""
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    return {
        "price": d["bitcoin"]["usd"],
        "change_24h_pct": d["bitcoin"].get("usd_24h_change", 0),
    }


def get_btc_4h_change():
    """Try to compute 4h change from hourly data."""
    try:
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=1"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        prices = d.get("prices", [])
        if len(prices) >= 5:
            now_price = prices[-1][1]
            past_price = prices[-5][1]  # ~4 hours ago
            return round(((now_price - past_price) / past_price) * 100, 2)
    except Exception:
        pass
    return None


def get_10y_yield():
    """Yahoo Finance ^TNX."""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/^TNX?interval=1d&range=5d"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        result = d["chart"]["result"][0]
        meta = result["meta"]
        current = meta.get("regularMarketPrice", 0)

        # Get prev close, falling back to recent daily close if missing
        prev = meta.get("previousClose")
        if not prev or prev < 1.0:  # sanity check — 10Y won't be below 1%
            closes = [c for c in result["indicators"]["quote"][0]["close"] if c and c > 1.0]
            prev = closes[-2] if len(closes) >= 2 else current

        return {
            "yield_pct": round(current, 3),
            "prev_close": round(prev, 3),
        }
    except Exception:
        return None


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("WARNING: Telegram secrets not set — printing alert instead")
        print(text)
        return
    from urllib.parse import urlencode
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urlencode({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode()
    try:
        with urlopen(url, data=data, timeout=20) as r:
            print("Telegram sent:", r.status)
    except Exception as e:
        print("Telegram error:", e)


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] BTC Cloud Sentinel starting")

    btc = get_btc_price()
    if not btc:
        print("Failed to fetch BTC price")
        sys.exit(1)
    print(f"BTC: ${btc['price']:,.0f} | 24h: {btc['change_24h_pct']:+.2f}%")

    change_4h = get_btc_4h_change()
    if change_4h is not None:
        print(f"4h change: {change_4h:+.2f}%")

    yield_data = get_10y_yield()
    if yield_data:
        y = yield_data["yield_pct"]
        prev = yield_data["prev_close"]
        change_bps = round((y - prev) * 100, 1)
        print(f"10Y: {y}% ({change_bps:+.1f}bps)")
    else:
        y = None
        change_bps = None

    # Determine alerts
    alerts = []

    if change_4h is not None and change_4h <= -DROP_ALERT_PCT:
        alerts.append(f"📉 *BTC DUMP*: {change_4h:.2f}% in 4h")

    distance_from_200w = ((btc['price'] - BTC_200W_SMA) / BTC_200W_SMA) * 100
    if btc['price'] < BTC_200W_SMA:
        alerts.append(f"🚨 *BELOW 200W SMA* — Price ${btc['price']:,.0f} vs 200W ${BTC_200W_SMA:,.0f} ({distance_from_200w:+.1f}%) — v2.8+ ARM ZONE")
    elif distance_from_200w < 10:
        alerts.append(f"⚠️ *Approaching 200W SMA* — {distance_from_200w:+.1f}% above")

    if change_bps is not None and change_bps >= YIELD_SPIKE_BPS:
        alerts.append(f"📈 *10Y YIELD SPIKE*: +{change_bps}bps → {y}% — BTC headwind")

    # Build message
    lines = [
        "🛰 *BTC Cloud Sentinel* — GitHub Actions",
        "━━━━━━━━━━━━━━━━",
        f"💰 BTC: *${btc['price']:,.0f}*",
        f"📊 24h: {btc['change_24h_pct']:+.2f}%" + (f" | 4h: {change_4h:+.2f}%" if change_4h is not None else ""),
        f"📏 200W SMA: ${BTC_200W_SMA:,} ({distance_from_200w:+.1f}%)",
    ]
    if y is not None:
        lines.append(f"🌐 10Y: {y}% ({change_bps:+.1f}bps)")

    if alerts:
        lines.append("")
        lines.append("━━━ ALERTS ━━━")
        lines.extend(alerts)
        send_telegram("\n".join(lines))
        print("Alert sent")
    else:
        # Only send heartbeat once a day at 12:00 UTC to avoid spam
        now = datetime.now(timezone.utc)
        if now.hour == 12:
            lines.append("")
            lines.append("✅ All clear — no alerts")
            send_telegram("\n".join(lines))
            print("Heartbeat sent")
        else:
            print("No alerts, no heartbeat this hour")


if __name__ == "__main__":
    main()
