"""Stop Loss Monitor — Software-based trailing stop for positions where IBKR
rejects native stop orders (spreads, paper account permission issues).
Runs via cron every 5 minutes during market hours.
Constitution v44.0 — MANDATORY stop enforcement.
"""
import os
import sys
import json
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram
from stop_utils import get_laddered_trail_pct, LADDERED_SYSTEMS, TRAIL_PCT as FLAT_TRAIL_PCT

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
STOP_STATE_FILE = os.path.join(DATA_DIR, "stop_monitor_state.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# Load env
env_file = os.path.expanduser("~/.agent_zero_env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

# Ticker → system mapping for laddered trail tiers
TICKER_TO_SYSTEM = {
    "MSTR": "mstr_lottery", "IBIT": "mstr_lottery",
    "CCJ": "energy_momentum", "UEC": "energy_momentum", "LEU": "energy_momentum",
    "XOM": "energy_momentum", "CVX": "energy_momentum", "OXY": "energy_momentum",
    "DVN": "energy_momentum", "FANG": "energy_momentum", "VST": "energy_momentum",
    "CEG": "energy_momentum", "SMR": "energy_momentum",
    "GME": "short_squeeze", "AMC": "short_squeeze", "SOFI": "short_squeeze",
    "RIVN": "short_squeeze", "LCID": "short_squeeze",
    "NVDA": "breakout_momentum", "AMZN": "breakout_momentum", "GOOGL": "breakout_momentum",
    "TSLA": "breakout_momentum", "AMD": "breakout_momentum", "META": "breakout_momentum",
    "NFLX": "breakout_momentum",
    "GLD": "ntr_ag_momentum", "GDX": "ntr_ag_momentum", "NEM": "ntr_ag_momentum",
    "SLV": "ntr_ag_momentum", "AG": "ntr_ag_momentum", "GOLD": "ntr_ag_momentum",
    "PAAS": "ntr_ag_momentum", "MP": "ntr_ag_momentum", "REMX": "ntr_ag_momentum",
    "TQQQ": "tqqq_momentum",
    "JOBY": "10x_momentum", "IONQ": "10x_momentum", "RGTI": "10x_momentum",
    "QUBT": "10x_momentum", "OKLO": "10x_momentum", "DNA": "10x_momentum",
    "SOUN": "10x_momentum", "BFLY": "10x_momentum", "BBAI": "10x_momentum",
    "ACHR": "10x_momentum",
    "RKLB": "10x_momentum", "ASTS": "10x_momentum", "LUNR": "10x_momentum",
    "BKSY": "10x_momentum",
    "COIN": "short_squeeze", "MARA": "short_squeeze", "RIOT": "short_squeeze",
}
DEFAULT_TRAIL_PCT = 30  # fallback for unknown tickers


def get_system_name(symbol, contract=None):
    """Determine system name from ticker. For MSTR/IBIT, check DTE to distinguish
    lottery (short-dated) from moonshot (LEAP >365 DTE)."""
    base = TICKER_TO_SYSTEM.get(symbol, "default")
    if base == "mstr_lottery" and contract:
        try:
            from datetime import datetime as dt
            exp = dt.strptime(contract.lastTradeDateOrContractMonth, "%Y%m%d")
            dte = (exp - dt.now()).days
            if dte > 365:
                return "mstr_moonshot"
        except Exception:
            pass
    return base


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[StopMon {ts}] {msg}")
    with open(f"{LOG_DIR}/stop_monitor.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def load_state():
    if os.path.exists(STOP_STATE_FILE):
        with open(STOP_STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STOP_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_position_key(symbol, strike, expiry, right):
    return f"{symbol}_{strike}_{expiry}_{right}"


def monitor():
    asyncio.set_event_loop(asyncio.new_event_loop())
    from ib_insync import IB, Option, Stock, MarketOrder, ComboLeg, Contract

    ib = IB()
    ib.connect("127.0.0.1", 7496, clientId=79)
    ib.reqMarketDataType(3)

    state = load_state()  # {key: {"high_water": float, "entry": float}}
    positions = ib.positions()
    closed = []

    for p in positions:
        c = p.contract
        if c.secType != "OPT":
            continue

        qty = abs(p.position)
        is_long = p.position > 0
        is_short = p.position < 0
        entry = p.avgCost / 100

        ib.qualifyContracts(c)
        ticker = ib.reqMktData(c)
        ib.sleep(2)

        mid = None
        if ticker.bid == ticker.bid and ticker.ask == ticker.ask and ticker.bid > 0:
            mid = (ticker.bid + ticker.ask) / 2
        elif ticker.last == ticker.last and ticker.last > 0:
            mid = ticker.last
        elif ticker.close == ticker.close and ticker.close > 0:
            mid = ticker.close
        ib.cancelMktData(c)

        if not mid or mid <= 0:
            continue

        key = get_position_key(c.symbol, c.strike, c.lastTradeDateOrContractMonth, c.right)

        # Check if this position already has an IBKR trailing stop
        has_ibkr_stop = False
        for t in ib.openTrades():
            tc = t.contract
            if (tc.symbol == c.symbol and tc.strike == c.strike and
                tc.lastTradeDateOrContractMonth == c.lastTradeDateOrContractMonth and
                tc.right == c.right and t.order.orderType == "TRAIL"):
                has_ibkr_stop = True
                break

        if has_ibkr_stop:
            continue  # IBKR is handling this one

        # Software trailing stop
        system_name = get_system_name(c.symbol, c)
        if key not in state:
            state[key] = {"high_water": mid, "entry": entry, "system_name": system_name}
        else:
            # Backfill system_name and entry for old state entries
            if "system_name" not in state[key]:
                state[key]["system_name"] = system_name
            if "entry" not in state[key]:
                state[key]["entry"] = entry

        hw = state[key]["high_water"]
        entry_price = state[key].get("entry", entry)

        if is_long:
            # Update high water mark
            if mid > hw:
                state[key]["high_water"] = mid
                hw = mid

            # Calculate gain from entry to HWM (peak gain, not current)
            gain_pct = ((hw - entry_price) / entry_price * 100) if entry_price > 0 else 0

            # Get laddered trail % for this system and gain level
            trail_pct = get_laddered_trail_pct(system_name, gain_pct)

            if trail_pct is None:
                # No stop at this gain level (lottery mode — system needs room)
                log(f"OK: {c.symbol} {c.strike}{c.right} | Now:{mid:.2f} | HW:{hw:.2f} | Entry:{entry_price:.2f} | Gain:+{gain_pct:.0f}% | {system_name} | NO STOP (lottery mode)")
                continue

            stop_level = hw * (1 - trail_pct / 100)
            if mid <= stop_level:
                log(f"STOP TRIGGERED: {c.symbol} {c.strike}{c.right} | Price {mid:.2f} <= stop {stop_level:.2f} ({trail_pct}% below HW {hw:.2f}) | {system_name}")
                order = MarketOrder("SELL", int(qty))
                order.tif = "GTC"
                t = ib.placeOrder(c, order)
                ib.sleep(5)
                status = t.orderStatus.status
                fill = t.orderStatus.avgFillPrice
                log(f"CLOSED: {c.symbol} {c.strike}{c.right} x{int(qty)} @ {fill} | Status: {status}")
                closed.append(f"{c.symbol} {c.strike}{c.right} x{int(qty)} @ ${fill}")
                telegram.send(
                    f"*STOP LOSS TRIGGERED*\n\n"
                    f"{c.symbol} ${c.strike}{c.right} x{int(qty)}\n"
                    f"Entry: ${entry_price:.2f} | High: ${hw:.2f} | Exit: ${mid:.2f}\n"
                    f"P&L: {((mid - entry_price) / entry_price * 100):+.1f}%\n"
                    f"System: {system_name} | Trail: {trail_pct}%\n"
                    f"Reason: Laddered trailing stop from peak"
                )
                del state[key]
            else:
                log(f"OK: {c.symbol} {c.strike}{c.right} | Now:{mid:.2f} | HW:{hw:.2f} | Entry:{entry_price:.2f} | Gain:+{gain_pct:.0f}% | {system_name} | {trail_pct}% trail | Stop:{stop_level:.2f}")

        elif is_short:
            # For short positions, stop triggers on price RISE
            if mid < hw:
                state[key]["high_water"] = mid
                hw = mid

            # Shorts use flat trail (laddered doesn't apply to short positions)
            trail_pct = DEFAULT_TRAIL_PCT
            stop_level = hw * (1 + trail_pct / 100)
            if mid >= stop_level:
                log(f"STOP TRIGGERED (SHORT): {c.symbol} {c.strike}{c.right} | Price {mid:.2f} >= stop {stop_level:.2f} | {system_name}")
                order = MarketOrder("BUY", int(qty))
                order.tif = "GTC"
                t = ib.placeOrder(c, order)
                ib.sleep(5)
                status = t.orderStatus.status
                fill = t.orderStatus.avgFillPrice
                log(f"CLOSED: {c.symbol} {c.strike}{c.right} x{int(qty)} @ {fill} | Status: {status}")
                closed.append(f"{c.symbol} {c.strike}{c.right} x{int(qty)} @ ${fill}")
                telegram.send(
                    f"*STOP LOSS TRIGGERED (SHORT)*\n\n"
                    f"{c.symbol} ${c.strike}{c.right} x{int(qty)}\n"
                    f"Exit: ${mid:.2f}\n"
                    f"System: {system_name} | Trail: {trail_pct}%\n"
                    f"Reason: Trailing stop from low water mark"
                )
                del state[key]

    save_state(state)

    if closed:
        log(f"Closed {len(closed)} positions: {closed}")
    else:
        log(f"All positions within stop limits. Monitoring {len(state)} software stops.")

    ib.disconnect()


if __name__ == "__main__":
    monitor()
