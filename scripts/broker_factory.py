"""Broker Factory — Mode switch for Rudy v2.0.
Reads RUDY_MODE from environment. Returns the correct broker implementation.

RUDY_MODE=shadow → ShadowBroker  (no IBKR, simulated fills)
RUDY_MODE=paper  → IBKRBroker    (port 7496, paper account)
RUDY_MODE=live   → IBKRBroker    (port 7496, real money) + second confirmation

Usage:
    from broker_factory import get_broker, Order
    broker = get_broker()
    fill = broker.place_order(Order(symbol="MSTR", action="BUY", qty=5, ...))
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from broker_base import Order, Fill, Position


def get_broker():
    """Return the correct broker based on RUDY_MODE environment variable.

    Returns:
        BrokerBase implementation (ShadowBroker or IBKRBroker)

    Raises:
        RuntimeError if RUDY_MODE=live but RUDY_LIVE_CONFIRMED is not set
    """
    # Load env from ~/.agent_zero_env if not already set
    env_file = os.path.expanduser("~/.agent_zero_env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

    mode = os.environ.get("RUDY_MODE", "shadow").lower().strip()

    if mode == "shadow":
        from shadow_broker import ShadowBroker
        broker = ShadowBroker()
        _log(f"Broker: SHADOW mode (no IBKR, simulated fills)")
        return broker

    elif mode == "paper":
        from ibkr_broker import IBKRBroker
        broker = IBKRBroker(port=7496, mode="paper")
        _log(f"Broker: PAPER mode (port 7496)")
        return broker

    elif mode == "live":
        # Double confirmation gate — one wrong env var cannot go live
        confirmed = os.environ.get("RUDY_LIVE_CONFIRMED", "")
        if confirmed != "yes_i_understand_real_money":
            raise RuntimeError(
                "RUDY_MODE=live requires RUDY_LIVE_CONFIRMED=yes_i_understand_real_money\n"
                "This is a safety gate. Set both env vars to trade with real money.\n"
                "A copy-paste of your .env to a new machine will NOT accidentally go live."
            )
        from ibkr_broker import IBKRBroker
        broker = IBKRBroker(port=7496, mode="live")
        _log(f"Broker: LIVE mode (port 7496) — REAL MONEY")

        try:
            import telegram
            telegram.send("⚠️ *RUDY LIVE MODE ACTIVATED*\nReal money orders enabled.")
        except Exception:
            pass

        return broker

    else:
        _log(f"Unknown RUDY_MODE='{mode}' — defaulting to shadow")
        from shadow_broker import ShadowBroker
        return ShadowBroker()


def _log(msg):
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[BrokerFactory {ts}] {msg}")
