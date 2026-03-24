"""Signal Scanner — Rudy v2.0
Periodically checks for System 1 v8, System 2 v5 (momentum + squeeze) entry signals.
Runs alongside the webhook server as a backup signal source.
Generates proposals and sends to E.M. for approval.

Scans:
  System 1: MSTR/IBIT (lottery)
  System 2 Momentum: 17-stock universe (tech + energy)
  System 2 Squeeze: 9-stock universe (gap + volume + EMA cross)
"""
import os
import sys
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram
import system1_v8
import system2_v4

LOG_DIR = os.path.expanduser("~/rudy/logs")
PENDING_FILE = os.path.expanduser("~/rudy/data/pending_trade.json")
SCAN_INTERVAL = 3600  # Check every hour during market hours

os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Scanner {ts}] {msg}")
    with open(f"{LOG_DIR}/scanner.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def is_market_hours():
    """Check if US market is open (9:30 AM - 4:00 PM ET, Mon-Fri)."""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hour = now.hour
    minute = now.minute
    return (hour > 9 or (hour == 9 and minute >= 30)) and hour < 16


def has_pending_trade():
    return os.path.exists(PENDING_FILE)


def save_pending(proposal):
    os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
    with open(PENDING_FILE, "w") as f:
        json.dump(proposal, f, indent=2)


def scan_system1():
    """Scan MSTR/IBIT for System 1 v8 lottery entries."""
    for symbol in ["MSTR", "IBIT"]:
        signal, reason, price = system1_v8.check_entry_signal(symbol)

        if signal:
            log(f"S1 SIGNAL: {symbol} — {reason} @ ${price:.2f}")
            proposal = system1_v8.generate_proposal(symbol)

            if proposal:
                save_pending(proposal)
                targets = proposal["targets"]
                telegram.send(
                    f"🎰 *System 1 v8 — Signal Detected!*\n\n"
                    f"Ticker: {symbol} @ ${price:.2f}\n"
                    f"Signal: {reason}\n\n"
                    f"Primary: ${targets['primary_strike']} call\n"
                    f"Secondary: ${targets['secondary_strike']} call\n"
                    f"Hedge: ${targets['hedge_strike']} put\n\n"
                    f"Budget: ${proposal['budget']:,.0f}\n\n"
                    f"Reply *Yes* to execute or *No* to skip."
                )
                return True
        else:
            log(f"S1 no signal: {symbol} — {reason} @ ${price:.2f}")
    return False


def scan_system2():
    """Scan universe for System 2 momentum entries (tech + energy)."""
    open_positions = system2_v4.get_open_positions()
    open_symbols = [p["symbol"] for p in open_positions]

    if len(open_positions) >= system2_v4.MAX_POSITIONS:
        log(f"S2: Already at max positions ({len(open_positions)}/{system2_v4.MAX_POSITIONS})")
        return False

    # Scan and rank
    candidates = system2_v4.scan_universe()

    # Filter out already-held stocks
    candidates = [(sym, score, reason, tech) for sym, score, reason, tech in candidates
                  if sym not in open_symbols]

    if candidates:
        sym, score, reason, tech = candidates[0]
        proposal = system2_v4.generate_proposal(sym, tech)

        # Tag energy vs tech
        sector = "Energy" if sym in system2_v4.UNIVERSE_ENERGY else "Tech"

        save_pending(proposal)
        telegram.send(
            f"💰 *System 2 v5 — Momentum Signal!*\n\n"
            f"Ticker: {sym} ({sector}) @ ${tech['price']:.2f}\n"
            f"Signal: {reason}\n"
            f"Score: {score:.1f} | RSI: {tech['rsi']:.1f}\n\n"
            f"Structure: Diagonal spread (LEAP + short call)\n"
            f"Max risk: ${system2_v4.MAX_RISK_PER_TRADE}\n\n"
            f"Reply *Yes* to execute or *No* to skip."
        )
        return True
    else:
        log("S2 Momentum: No entry signals in universe")
        return False


def scan_squeeze():
    """Scan for short squeeze signals."""
    if has_pending_trade():
        return False

    open_positions = system2_v4.get_open_positions()
    open_symbols = [p["symbol"] for p in open_positions]

    candidates = system2_v4.scan_squeeze_universe()
    candidates = [(sym, score, reason, data) for sym, score, reason, data in candidates
                  if sym not in open_symbols]

    if candidates:
        sym, score, reason, data = candidates[0]
        proposal = system2_v4.generate_squeeze_proposal(sym, data)

        save_pending(proposal)
        gap_pct = (data["price"] - data["prev_close"]) / data["prev_close"]
        vol_ratio = data["volume"] / data["avg_volume_20"] if data["avg_volume_20"] > 0 else 0

        telegram.send(
            f"🚀 *System 2 v5 — SQUEEZE DETECTED!*\n\n"
            f"Ticker: {sym} @ ${data['price']:.2f}\n"
            f"Gap: +{gap_pct:.1%} | Volume: {vol_ratio:.1f}x avg\n"
            f"Signal: EMA21 breakout on massive volume\n\n"
            f"Strategy: Buy calls / leveraged long\n"
            f"Take profit: +50% | Stop: -25%\n"
            f"Max risk: ${system2_v4.MAX_RISK_PER_TRADE}\n\n"
            f"Reply *Yes* to execute or *No* to skip."
        )
        return True
    else:
        log("S2 Squeeze: No squeeze signals")
        return False


def run():
    log("Signal scanner started — S1 (MSTR/IBIT) + S2 Momentum (17 stocks) + S2 Squeeze (9 stocks)")
    telegram.send(
        "📡 *Signal scanner online*\n"
        "System 1: MSTR/IBIT lottery (hourly)\n"
        "System 2 Momentum: Tech + Energy (hourly)\n"
        "System 2 Squeeze: 9-stock detector (every 15 min)"
    )

    last_squeeze_scan = 0
    squeeze_interval = 900  # Squeeze checks every 15 min (time-sensitive)

    while True:
        try:
            if not is_market_hours():
                log("Market closed — sleeping")
                time.sleep(900)
                continue

            if has_pending_trade():
                log("Pending trade exists — skipping scan")
                time.sleep(300)
                continue

            now = time.time()

            # Squeeze scan every 15 min (squeezes are time-critical)
            if now - last_squeeze_scan >= squeeze_interval:
                log("Scanning for squeezes...")
                if scan_squeeze():
                    last_squeeze_scan = now
                    time.sleep(300)
                    continue
                last_squeeze_scan = now

            # System 1 (lottery takes priority)
            if scan_system1():
                time.sleep(SCAN_INTERVAL)
                continue

            # System 2 momentum (tech + energy)
            scan_system2()

        except Exception as e:
            log(f"Scanner error: {e}")

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
