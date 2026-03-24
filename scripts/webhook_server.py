"""TradingView Webhook Receiver — Rudy v2.0
Listens for TradingView alerts and forwards trade proposals via Telegram.
"""
import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram
import system1_v8
import system2_v4

LOG_DIR = os.path.expanduser("~/rudy/logs")
os.makedirs(LOG_DIR, exist_ok=True)

CONSTITUTION = {
    "system1_exclusives": ["MSTR", "IBIT"],
    "system2_exclusions": ["MSTR", "IBIT"],
    "system2_max_risk": 250,
    "survival_breaker_s1": 75000,
    "survival_breaker_s2": 7500,
}


def log_signal(signal):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(f"{LOG_DIR}/signals.log", "a") as f:
        f.write(f"[{ts}] {json.dumps(signal)}\n")


def validate_system2(signal):
    """Pre-flight check per Constitution v50.0"""
    ticker = signal.get("ticker", "").upper()
    if ticker in CONSTITUTION["system2_exclusions"]:
        return False, f"{ticker} is exclusive to System 1 — rejected"
    risk = signal.get("risk", 0)
    if risk > CONSTITUTION["system2_max_risk"]:
        return False, f"Risk ${risk} exceeds System 2 max ${CONSTITUTION['system2_max_risk']}"
    return True, "OK"


def process_signal(signal):
    """Process incoming TradingView signal and send proposal via Telegram."""
    log_signal(signal)

    system = signal.get("system", "").lower()
    ticker = signal.get("ticker", "UNKNOWN")
    action = signal.get("action", "").upper()

    if system == "system1":
        # System 1 v8: Deep OTM Lottery — generate proposal via V8 engine
        symbol = signal.get("ticker", "MSTR")
        proposal = system1_v8.generate_proposal(symbol)

        if proposal:
            # Save as pending trade for E.M. approval
            pending_file = os.path.expanduser("~/rudy/data/pending_trade.json")
            os.makedirs(os.path.dirname(pending_file), exist_ok=True)
            with open(pending_file, "w") as f:
                json.dump(proposal, f, indent=2)

            targets = proposal["targets"]
            telegram.send(
                f"🎰 *System 1 v8 — Lottery Proposal*\n\n"
                f"Ticker: {symbol} @ ${proposal['price']:.2f}\n"
                f"Signal: {proposal['signal']}\n\n"
                f"Primary: ${targets['primary_strike']} call (60%)\n"
                f"Secondary: ${targets['secondary_strike']} call (30%)\n"
                f"Hedge: ${targets['hedge_strike']} put\n\n"
                f"Budget: ${proposal['budget']:,.0f}\n\n"
                f"Reply *Yes* to execute or *No* to skip."
            )
            return {"status": "proposal_sent", "system": "system1_v8"}
        else:
            telegram.send(f"📊 Signal received for {symbol} but entry conditions not met.")
            return {"status": "no_signal", "system": "system1"}

    elif system == "squeeze":
        # Short squeeze signal from TradingView
        ticker = signal.get("ticker", "UNKNOWN").upper()
        data = system2_v4.get_squeeze_data(ticker)
        if data:
            signal_ok, reason, _ = system2_v4.check_squeeze(ticker)
            if signal_ok:
                proposal = system2_v4.generate_squeeze_proposal(ticker, data)
                pending_file = os.path.expanduser("~/rudy/data/pending_trade.json")
                os.makedirs(os.path.dirname(pending_file), exist_ok=True)
                with open(pending_file, "w") as f:
                    json.dump(proposal, f, indent=2)

                gap_pct = (data["price"] - data["prev_close"]) / data["prev_close"]
                vol_ratio = data["volume"] / data["avg_volume_20"] if data["avg_volume_20"] > 0 else 0
                telegram.send(
                    f"🚀 *Squeeze Signal — {ticker}*\n\n"
                    f"Price: ${data['price']:.2f}\n"
                    f"Gap: +{gap_pct:.1%} | Volume: {vol_ratio:.1f}x\n\n"
                    f"Reply *Yes* to execute or *No* to skip."
                )
                return {"status": "proposal_sent", "system": "squeeze"}
        return {"status": "no_signal", "system": "squeeze"}

    elif system == "system2":
        # System 2 v4: Get Rich — validate then generate proposal
        valid, reason = validate_system2(signal)
        if not valid:
            telegram.send(f"❌ *System 2 Rejected*\n{ticker}: {reason}")
            return {"status": "rejected", "reason": reason}

        # Check entry conditions via V4 engine
        signal_ok, entry_reason, tech = system2_v4.check_entry(ticker)
        if signal_ok and tech:
            proposal = system2_v4.generate_proposal(ticker, tech)

            # Save as pending trade
            pending_file = os.path.expanduser("~/rudy/data/pending_trade.json")
            os.makedirs(os.path.dirname(pending_file), exist_ok=True)
            with open(pending_file, "w") as f:
                json.dump(proposal, f, indent=2)

            telegram.send(
                f"💰 *System 2 v4 — Get Rich Proposal*\n\n"
                f"Ticker: {ticker} @ ${tech['price']:.2f}\n"
                f"Signal: {entry_reason}\n"
                f"Score: {proposal.get('score', 0):.1f}\n"
                f"RSI: {tech['rsi']:.1f}\n\n"
                f"Allocation: {system2_v4.ALLOCATION_PER:.0%} of portfolio\n"
                f"Pyramids: +15% and +40%\n"
                f"Profit take: +100%\n\n"
                f"Reply *Yes* to execute or *No* to skip."
            )
            return {"status": "proposal_sent", "system": "system2_v4"}
        else:
            telegram.send(f"📊 {ticker} signal received but V4 conditions not met: {entry_reason}")
            return {"status": "no_signal", "system": "system2"}

    else:
        # Generic alert
        telegram.send(
            f"📡 *TradingView Alert*\n{action} {ticker}\n"
            f"Price: ${signal.get('price', 'N/A')}\n"
            f"Note: {signal.get('message', '')}"
        )
        return {"status": "alert_sent"}


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            signal = json.loads(body)
            result = process_signal(signal)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, format, *args):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(f"{LOG_DIR}/webhook.log", "a") as f:
            f.write(f"[{ts}] {args[0]}\n")


def start(port=5555):
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"Webhook server listening on port {port}")
    telegram.send(f"📡 Webhook server started on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5555
    start(port)
