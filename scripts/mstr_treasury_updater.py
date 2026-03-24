#!/usr/bin/env python3
"""
MSTR Treasury Auto-Updater — Fetches live holdings from public sources.
Runs weekly (Monday 8:30 AM) via scheduled task.
Updates trader_v28_state.json with latest holdings/shares for mNAV calculation.

Sources:
  - BTC Holdings + Avg Cost: bitbo.io/treasuries/microstrategy/
  - Diluted Shares: stockanalysis.com/stocks/mstr/financials/

IBKR_IS_PRICE_TRUTH still applies — this only updates HOLDINGS data,
not prices. All prices come from IBKR.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.expanduser("~/rudy/data")
STATE_FILE = os.path.join(DATA_DIR, "mstr_treasury.json")
LOG_FILE = os.path.expanduser("~/rudy/logs/treasury_updater.log")

# Import telegram for alerts
try:
    from telegram import send as send_telegram
except ImportError:
    def send_telegram(msg):
        print(f"[TELEGRAM] {msg}")


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def fetch_url(url):
    """Fetch URL content as string."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Rudy/2.0"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_bitbo_holdings():
    """Fetch BTC holdings and avg cost from bitbo.io.
    Bitbo renders data in HTML with patterns like:
      - Holdings: "761,068 BTC" or "761,068 bitcoin"
      - Dollar amounts: "$66,384.56" (avg cost per BTC)
      - Total cost: "$33.139 billion" or "$33.13"
    """
    try:
        html = fetch_url("https://bitbo.io/treasuries/microstrategy/")
        holdings = None
        avg_cost = None

        # Holdings: "761,068" followed by BTC/bitcoin
        holdings_match = re.findall(r'([\d,]{5,10})\s*(?:BTC|bitcoin)', html, re.IGNORECASE)
        if holdings_match:
            holdings = int(holdings_match[0].replace(",", ""))
            log(f"Parsed holdings from bitbo: {holdings:,} BTC")

        # Avg cost: dollar amounts in $XX,XXX.XX format (5-6 digit range = per-BTC cost)
        dollar_amounts = re.findall(r'\$([\d,]+\.\d{2})', html)
        for amt in dollar_amounts:
            val = float(amt.replace(",", ""))
            # Per-BTC avg cost is typically $40K-$120K range
            if 30000 < val < 150000:
                avg_cost = val
                log(f"Parsed avg cost from bitbo: ${avg_cost:,.2f}")
                break

        return holdings, avg_cost
    except Exception as e:
        log(f"Bitbo fetch failed: {e}", "ERROR")
        return None, None


def fetch_shares_outstanding():
    """Fetch diluted shares from stockanalysis.com.
    The data is embedded as JSON in the HTML: sharesDiluted:[293157000,277660000,...]
    First element is most recent (TTM or latest fiscal year).
    """
    try:
        html = fetch_url("https://stockanalysis.com/stocks/mstr/financials/")
        # Extract from embedded JSON data blob
        shares_match = re.search(r'sharesDiluted:\[(\d{6,12})', html)
        if shares_match:
            shares = int(shares_match.group(1))
            log(f"Parsed diluted shares from embedded data: {shares:,}")
            return shares
        # Fallback: try sharesBasic
        basic_match = re.search(r'sharesBasic:\[(\d{6,12})', html)
        if basic_match:
            shares = int(basic_match.group(1))
            log(f"Parsed basic shares from embedded data: {shares:,}")
            return shares
        log("Could not parse shares from stockanalysis HTML", "WARN")
        return None
    except Exception as e:
        log(f"StockAnalysis fetch failed: {e}", "ERROR")
        return None


def load_current():
    """Load current treasury state."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state):
    """Save treasury state."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def update_trader_state(holdings, shares):
    """Update trader_v28_state.json with latest holdings for live mNAV calc."""
    trader_state_file = os.path.join(DATA_DIR, "trader_v28_state.json")
    if not os.path.exists(trader_state_file):
        log("trader_v28_state.json not found — skipping", "WARN")
        return

    with open(trader_state_file) as f:
        state = json.load(f)

    state["mstr_btc_holdings"] = holdings
    state["mstr_diluted_shares"] = shares
    state["treasury_updated"] = datetime.now().isoformat()

    with open(trader_state_file, "w") as f:
        json.dump(state, f, indent=2)
    log(f"Updated trader state: {holdings:,} BTC, {shares:,} shares")


def run():
    """Main update routine."""
    log("=" * 50)
    log("MSTR Treasury Update — Starting")

    current = load_current()
    old_holdings = current.get("btc_holdings", 0)
    old_shares = current.get("diluted_shares", 0)

    # Fetch latest data
    holdings, avg_cost = fetch_bitbo_holdings()
    shares = fetch_shares_outstanding()

    # Fallback: if fetches fail, try alternative sources or keep current
    if holdings is None:
        log("Could not fetch holdings from bitbo — keeping current", "WARN")
        holdings = old_holdings

    if shares is None:
        log("Could not fetch shares from stockanalysis — keeping current", "WARN")
        shares = old_shares

    if holdings == 0 and shares == 0:
        log("No data available — aborting", "ERROR")
        send_telegram("🔴 *TREASURY UPDATER FAILED*\nCould not fetch MSTR holdings from any source.")
        return

    # Calculate changes
    btc_delta = holdings - old_holdings if old_holdings > 0 else 0
    shares_delta = shares - old_shares if old_shares > 0 else 0

    # Save new state
    new_state = {
        "btc_holdings": holdings,
        "avg_cost_per_btc": avg_cost or current.get("avg_cost_per_btc", 0),
        "diluted_shares": shares,
        "last_updated": datetime.now().isoformat(),
        "source_holdings": "bitbo.io",
        "source_shares": "stockanalysis.com",
        "btc_delta_from_last": btc_delta,
        "shares_delta_from_last": shares_delta,
    }
    save_state(new_state)

    # Update trader state for live mNAV calculation
    if holdings > 0 and shares > 0:
        update_trader_state(holdings, shares)

    # Alert if significant change
    if btc_delta > 0:
        msg = (
            f"📊 *MSTR Treasury Update*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"BTC Holdings: {holdings:,} (+{btc_delta:,} new)\n"
            f"Avg Cost: ${avg_cost:,.2f}\n" if avg_cost else f"BTC Holdings: {holdings:,} (+{btc_delta:,} new)\n"
            f"Diluted Shares: {shares:,}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"mNAV data updated for trader1"
        )
        send_telegram(msg)
        log(f"Holdings increased: {old_holdings:,} → {holdings:,} (+{btc_delta:,} BTC)")
    elif btc_delta == 0 and old_holdings > 0:
        log(f"No change in holdings: {holdings:,} BTC, {shares:,} shares")
    else:
        log(f"Initial load: {holdings:,} BTC, {shares:,} shares")
        send_telegram(
            f"📊 *MSTR Treasury — Initial Load*\n"
            f"BTC: {holdings:,} | Shares: {shares:,}\n"
            f"mNAV data live for trader1"
        )

    log("MSTR Treasury Update — Complete")


if __name__ == "__main__":
    run()
