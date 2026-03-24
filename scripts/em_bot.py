"""E.M. — Telegram Approval Bot for Rudy v2.0
Listens for Yes/No replies from Lawson and triggers Trader1 execution.
"""
import json
import os
import sys
import time
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram
import trader1
import trader2
import system1_v8
import system2_v4
import auditor
import accountant

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
LOG_DIR = os.path.expanduser("~/rudy/logs")
PENDING_FILE = os.path.expanduser("~/rudy/data/pending_trade.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(f"{LOG_DIR}/em.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}")


def save_pending(trade):
    with open(PENDING_FILE, "w") as f:
        json.dump(trade, f, indent=2)
    log(f"Pending trade saved: {trade.get('ticker', 'unknown')}")


def load_pending():
    if not os.path.exists(PENDING_FILE):
        return None
    with open(PENDING_FILE) as f:
        return json.load(f)


def clear_pending():
    if os.path.exists(PENDING_FILE):
        os.remove(PENDING_FILE)


def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(f"{API}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except:
        return []


def process_reply(text):
    """Process Yes/No reply from Lawson."""
    text = text.strip().lower()

    pending = load_pending()
    if not pending:
        telegram.send("No pending trade to approve.")
        return

    ticker = pending.get("ticker", "")
    system = pending.get("system", "")

    if text in ["yes", "y", "go", "execute"]:
        # Auditor check before execution
        approved, violations, warnings = auditor.audit_trade(pending)
        if not approved:
            v_text = "\n".join(violations)
            telegram.send(f"🚫 *Auditor BLOCKED trade:*\n{v_text}")
            log(f"AUDITOR BLOCKED: {system} — {ticker}: {violations}")
            clear_pending()
            return
        if warnings:
            w_text = "\n".join(warnings)
            telegram.send(f"⚠️ *Auditor warnings:*\n{w_text}")

        log(f"APPROVED: {system} — {ticker}")
        telegram.send(f"✅ *Approved.* Executing {ticker}...")

        try:
            if system == "system1" and pending.get("version") == "v8":
                # System 1 v8: Deep OTM Lottery — use V8 engine
                ib = trader1.connect()
                result = system1_v8.execute(ib, pending)
                telegram.send(
                    f"🎰 *System 1 v8 Executed*\n"
                    f"Ticker: {ticker}\n"
                    f"Legs: {len(result.get('legs', []))}\n"
                    f"Total Cost: ${result.get('total_cost', 0):,.0f}\n"
                    f"10x monitor: Active"
                )
            elif system == "system2" and pending.get("version") in ["v4", "v5"]:
                # System 2: Momentum or Squeeze — use Trader2 engine
                trade_type = pending.get("type", "diagonal")
                result = trader2.execute_entry(pending)

                if trade_type == "squeeze":
                    telegram.send(
                        f"🚀 *Squeeze Trade Executed*\n"
                        f"Ticker: {ticker}\n"
                        f"Type: {result.get('type', 'squeeze')}\n"
                        f"Fill: ${result.get('fill_price', result.get('leap_fill', 0)):.2f}\n"
                        f"Trader2 monitoring: Active"
                    )
                else:
                    telegram.send(
                        f"💰 *System 2 v5 Executed*\n"
                        f"Ticker: {ticker}\n"
                        f"Type: {trade_type}\n"
                        f"Fill: ${result.get('fill_price', result.get('leap_fill', 0)):.2f}\n"
                        f"Trader2 monitoring: Active"
                    )
            else:
                result = trader1.execute_trade(pending)
                telegram.send(
                    f"🎯 *Trade Executed*\n"
                    f"System: {system}\n"
                    f"Ticker: {ticker}\n"
                    f"Result: {result.get('status', 'unknown')}\n"
                    f"Fill: {result.get('fill_price', 'pending')}"
                )
            # Record trade in accountant
            accountant.record_trade(pending)

        except Exception as e:
            telegram.send(f"❌ *Execution failed:* {str(e)}")
            log(f"EXECUTION ERROR: {e}")

        clear_pending()

    elif text in ["no", "n", "skip", "pass"]:
        log(f"REJECTED: {system} — {ticker}")
        telegram.send(f"⏭️ *Skipped.* {ticker} trade cancelled.")
        clear_pending()

    else:
        telegram.send("Reply *Yes* or *No* to the pending trade.")


def run():
    """Main polling loop — E.M. listens for Lawson's commands."""
    log("E.M. bot started")
    telegram.send("🧠 *E.M. online.* Listening for approvals.")

    offset = None
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = msg.get("text", "")

            if chat_id != CHAT_ID:
                continue

            if text.startswith("/"):
                handle_command(text)
            else:
                process_reply(text)


def handle_command(text):
    cmd = text.strip().lower()

    if cmd == "/status":
        pending = load_pending()
        if pending:
            telegram.send(
                f"📋 *Pending Trade*\n"
                f"System: {pending.get('system')}\n"
                f"Ticker: {pending.get('ticker')}\n"
                f"Risk: ${pending.get('risk', 0):,.0f}\n\n"
                f"Reply Yes/No"
            )
        else:
            telegram.send("No pending trades. All clear.")

    elif cmd == "/positions":
        try:
            positions = trader1.get_positions()
            if positions:
                msg = "📊 *Current Positions*\n\n"
                for p in positions:
                    msg += f"{p['symbol']}: {p['qty']} @ ${p['avg_price']:,.2f}\n"
                telegram.send(msg)
            else:
                telegram.send("No open positions.")
        except Exception as e:
            telegram.send(f"Error fetching positions: {e}")

    elif cmd == "/pnl":
        try:
            summary = trader1.get_account_summary()
            telegram.send(
                f"💰 *Account Summary*\n\n"
                f"Net Liq: ${summary['net_liq']:,.2f}\n"
                f"Cash: ${summary['cash']:,.2f}\n"
                f"Buying Power: ${summary['buying_power']:,.2f}"
            )
        except Exception as e:
            telegram.send(f"Error: {e}")

    elif cmd == "/s2" or cmd == "/system2":
        try:
            s2_positions = trader2.get_s2_positions()
            if s2_positions:
                msg = "📈 *System 2 v4 Positions*\n\n"
                for p in s2_positions:
                    emoji = "🟢" if p["gain_pct"] > 0 else "🔴"
                    msg += (
                        f"{emoji} {p['symbol']}: {p['qty']} shares\n"
                        f"   Entry: ${p['entry']:.2f} → ${p['current']:.2f} ({p['gain_pct']:+.1f}%)\n"
                        f"   Pyramids: {p['pyramids']}/2\n\n"
                    )
                telegram.send(msg)
            else:
                telegram.send("No open System 2 positions.")
        except Exception as e:
            telegram.send(f"Error: {e}")

    elif cmd == "/scan":
        try:
            telegram.send("🔍 Scanning all universes...")

            # Momentum scan (tech + energy)
            candidates = system2_v4.scan_universe()
            if candidates:
                msg = "📊 *Momentum — Top Candidates*\n\n"
                for sym, score, reason, tech in candidates[:5]:
                    sector = "⚡" if sym in system2_v4.UNIVERSE_ENERGY else "💻"
                    msg += f"{sector} *{sym}* — Score {score:.1f}\n  ${tech['price']:.2f} | RSI {tech['rsi']:.1f}\n\n"
                telegram.send(msg)
            else:
                telegram.send("No momentum signals.")

            # Squeeze scan
            squeezes = system2_v4.scan_squeeze_universe()
            if squeezes:
                msg = "🚀 *Squeeze Candidates*\n\n"
                for sym, score, reason, data in squeezes[:3]:
                    msg += f"*{sym}* @ ${data['price']:.2f}\n  {reason}\n\n"
                telegram.send(msg)
            else:
                telegram.send("No squeeze signals.")

        except Exception as e:
            telegram.send(f"Scan error: {e}")

    elif cmd == "/energy":
        try:
            telegram.send("⚡ Scanning energy sector...")
            energy_candidates = []
            for sym in system2_v4.UNIVERSE_ENERGY:
                signal, reason, tech = system2_v4.check_entry(sym)
                if tech:
                    score = system2_v4.score_stock(tech)
                    status = "✅ SIGNAL" if signal else "⏸️"
                    energy_candidates.append((sym, score, tech, status))

            energy_candidates.sort(key=lambda x: x[1], reverse=True)
            msg = "⚡ *Energy Sector Scan*\n\n"
            for sym, score, tech, status in energy_candidates:
                msg += f"{status} *{sym}* Score:{score:.1f} | ${tech['price']:.2f} | RSI {tech['rsi']:.1f}\n"
            telegram.send(msg)
        except Exception as e:
            telegram.send(f"Energy scan error: {e}")

    elif cmd == "/help":
        telegram.send(
            "🤖 *E.M. Commands*\n\n"
            "*Trading*\n"
            "/status — Check pending trades\n"
            "/positions — View IBKR positions\n"
            "/pnl — Account summary\n\n"
            "*System 2 v5*\n"
            "/s2 — System 2 positions & gains\n"
            "/scan — Scan all universes (momentum + squeeze)\n"
            "/energy — Energy sector scan (uranium/oil/nuclear)\n\n"
            "*Universes*\n"
            "Tech: NVDA TSLA AMD META AVGO PLTR NFLX AMZN\n"
            "Energy: CCJ UEC XOM CVX OXY DVN FANG VST CEG\n"
            "Squeeze: GME AMC TSLA NVDA AMD PLTR SOFI MARA COIN\n\n"
            "Reply *Yes/No* to approve/reject trades."
        )

    else:
        telegram.send(f"Unknown command: {cmd}\nType /help for options.")


if __name__ == "__main__":
    run()
