"""Telegram alerts for Rudy v2.0 — Constitution v50.0"""
import os
import requests

# Load env vars from ~/.agent_zero_env if not already set
_env_file = os.path.expanduser("~/.agent_zero_env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send(text, parse_mode="Markdown", reply_markup=None):
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return requests.post(f"{API}/sendMessage", json=payload).json()


def send_hitl_approval(text):
    """Send a message with inline YES/NO buttons for HITL approval."""
    markup = {
        "inline_keyboard": [[
            {"text": "✅ YES — Approve Roll", "callback_data": "hitl_approve"},
            {"text": "❌ NO — Keep Current", "callback_data": "hitl_reject"}
        ]]
    }
    return send(text, reply_markup=markup)


def trade_alert(action, symbol, qty, price, reason=""):
    emoji = "🟢" if action.upper() == "BUY" else "🔴"
    msg = f"{emoji} *{action.upper()} {symbol}*\nQty: {qty}\nPrice: ${price:,.2f}\nValue: ${qty * price:,.2f}"
    if reason:
        msg += f"\nReason: {reason}"
    return send(msg)


def system1_proposal(strikes, hedge_cost, total):
    msg = (
        "📋 *System 1 Quarterly Deployment*\n\n"
        + "\n".join(f"Strike {i+1}: {s}" for i, s in enumerate(strikes))
        + f"\nTail Hedge: ${hedge_cost:,.0f}"
        + f"\n*Total: ~${total:,.0f}*"
        + "\n\nReply Yes/No"
    )
    return send(msg)


def system2_proposal(ticker, structure, risk):
    msg = (
        f"📋 *System 2 Setup*\n\n"
        f"Ticker: {ticker}\n"
        f"Structure: {structure}\n"
        f"Risk: ${risk:,.0f}\n\n"
        f"Reply Yes/No"
    )
    return send(msg)


def breaker_alert(system_name, equity, floor):
    msg = (
        f"🚨 *SURVIVAL BREAKER — {system_name}*\n\n"
        f"Equity: ${equity:,.0f}\n"
        f"Floor: ${floor:,.0f}\n"
        f"*ALL NEW ENTRIES HALTED*"
    )
    return send(msg)


def daily_summary(pnl, positions, btc_price):
    emoji = "📈" if pnl >= 0 else "📉"
    msg = f"{emoji} *Daily Summary*\n\nP&L: ${pnl:+,.2f}\nBTC: ${btc_price:,.0f}\n"
    if positions:
        msg += "\n*Positions:*\n"
        for p in positions:
            msg += f"  {p['symbol']}: {p['qty']} @ ${p['price']:,.2f}\n"
    return send(msg)


if __name__ == "__main__":
    send("🤖 *Rudy v2.0 online.* Constitution v50.0 loaded.")
