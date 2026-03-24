"""IBKR Utilities — Phase 1 Hardening
Reconnection with exponential backoff, order error recovery, entry validation.
Constitution v45.0 — bulletproof execution loop.
"""
import os
import sys
import json
import time
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
FAILED_ORDERS_FILE = os.path.join(DATA_DIR, "failed_orders.json")


# ─── IBKR Reconnection with Exponential Backoff ─────────────────────────────

def connect_with_retry(host="127.0.0.1", port=7496, client_id=1, max_retries=5, log_func=None):
    """Connect to IBKR TWS/Gateway with exponential backoff.

    Args:
        host: TWS host
        port: TWS port (7496=paper, 7496=live)
        client_id: Unique client ID
        max_retries: Maximum connection attempts
        log_func: Optional logging function

    Returns:
        Connected IB instance, or None on failure
    """
    from ib_insync import IB

    def _log(msg):
        if log_func:
            log_func(msg)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(f"{LOG_DIR}/ibkr_connection.log", "a") as f:
            f.write(f"[{ts}] {msg}\n")

    delays = [1, 2, 4, 8, 16, 30, 60]  # exponential backoff
    ib = IB()

    for attempt in range(1, max_retries + 1):
        try:
            ib.connect(host, port, clientId=client_id)
            ib.reqMarketDataType(3)
            _log(f"Connected to IBKR {host}:{port} (client {client_id}) on attempt {attempt}")
            return ib
        except Exception as e:
            delay = delays[min(attempt - 1, len(delays) - 1)]
            _log(f"Connection attempt {attempt}/{max_retries} failed: {e} — retrying in {delay}s")
            if attempt < max_retries:
                time.sleep(delay)

    _log(f"FAILED to connect after {max_retries} attempts")
    _alert_connection_failure(host, port, client_id, max_retries)
    return None


def ensure_connected(ib, host="127.0.0.1", port=7496, client_id=1, log_func=None):
    """Health check — reconnect if disconnected. Call before every order.

    Returns:
        Connected IB instance (same or new), or None on failure
    """
    try:
        if ib and ib.isConnected():
            return ib
    except Exception:
        pass

    if log_func:
        log_func("IBKR disconnected — attempting reconnect")
    return connect_with_retry(host, port, client_id, max_retries=3, log_func=log_func)


def _alert_connection_failure(host, port, client_id, attempts):
    """Send Telegram alert on connection failure."""
    try:
        import telegram
        telegram.send(
            f"*IBKR CONNECTION FAILED*\n\n"
            f"Host: {host}:{port} (client {client_id})\n"
            f"Attempts: {attempts}\n"
            f"Action required: Check TWS/Gateway status"
        )
    except Exception:
        pass


# ─── Order Error Recovery ────────────────────────────────────────────────────

def place_order_with_retry(ib, contract, order, max_retries=3, delay=2, log_func=None):
    """Place order with retry logic and Telegram escalation on failure.

    Args:
        ib: Connected IB instance
        contract: Qualified contract
        order: Order object
        max_retries: Retry attempts
        delay: Seconds between retries
        log_func: Optional logging function

    Returns:
        Trade object on success, None on failure
    """
    def _log(msg):
        if log_func:
            log_func(msg)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(f"{LOG_DIR}/order_recovery.log", "a") as f:
            f.write(f"[{ts}] {msg}\n")

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            trade = ib.placeOrder(contract, order)
            ib.sleep(3)
            status = trade.orderStatus.status

            if status in ("Filled", "Submitted", "PreSubmitted"):
                _log(f"Order SUCCESS (attempt {attempt}): {contract.symbol} {order.action} x{order.totalQuantity} — {status}")
                return trade
            elif status in ("Cancelled", "Inactive", "ApiCancelled"):
                _log(f"Order REJECTED (attempt {attempt}): {contract.symbol} — {status}")
                last_error = f"Order status: {status}"
            else:
                _log(f"Order PENDING (attempt {attempt}): {contract.symbol} — {status}")
                return trade  # still potentially valid

        except Exception as e:
            last_error = str(e)
            _log(f"Order ERROR (attempt {attempt}/{max_retries}): {contract.symbol} — {e}")

        if attempt < max_retries:
            time.sleep(delay)

    # All retries exhausted — log and escalate
    _log_failed_order(contract, order, last_error)
    _escalate_order_failure(contract, order, last_error, max_retries)
    return None


def _log_failed_order(contract, order, error):
    """Log failed order to data/failed_orders.json."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "symbol": contract.symbol,
        "secType": contract.secType,
        "action": order.action,
        "quantity": int(order.totalQuantity),
        "orderType": order.orderType,
        "error": error,
    }
    if hasattr(contract, "strike"):
        entry["strike"] = contract.strike
        entry["right"] = contract.right
        entry["expiry"] = contract.lastTradeDateOrContractMonth

    try:
        if os.path.exists(FAILED_ORDERS_FILE):
            with open(FAILED_ORDERS_FILE) as f:
                failed = json.load(f)
        else:
            failed = []
        failed.append(entry)
        # Keep last 200
        if len(failed) > 200:
            failed = failed[-200:]
        with open(FAILED_ORDERS_FILE, "w") as f:
            json.dump(failed, f, indent=2)
    except Exception:
        pass


def _escalate_order_failure(contract, order, error, attempts):
    """Send Telegram escalation on order failure."""
    try:
        import telegram
        strike_info = ""
        if hasattr(contract, "strike"):
            strike_info = f" ${contract.strike}{contract.right}"
        telegram.send(
            f"*ORDER FAILED — ESCALATION*\n\n"
            f"{contract.symbol}{strike_info}\n"
            f"Action: {order.action} x{int(order.totalQuantity)}\n"
            f"Type: {order.orderType}\n"
            f"Error: {error}\n"
            f"Attempts: {attempts}\n\n"
            f"Logged to failed_orders.json\n"
            f"Commander action may be required."
        )
    except Exception:
        pass


# ─── Entry Execution Validation ──────────────────────────────────────────────

def validate_entry(ticker, system_id, qty, price, log_func=None, **kwargs):
    """Pre-trade validation checks. Run BEFORE placing any entry order.

    Checks:
    1. Circuit breaker status
    2. Max order size
    3. Duplicate position prevention
    4. Portfolio concentration limits

    Args:
        ticker: Stock symbol
        system_id: System number
        qty: Number of contracts
        price: Estimated entry price per contract

    Returns:
        (approved, reason) — (True, "OK") or (False, "rejection reason")
    """
    import auditor

    def _log(msg):
        if log_func:
            log_func(msg)

    # 1. Circuit breaker check
    blocked, reason = auditor.is_breaker_active(system_id)
    if blocked:
        _log(f"ENTRY BLOCKED: {ticker} — {reason}")
        return False, reason

    # 2. Max order size ($50k per single trade)
    total_cost = qty * price * 100  # options are 100 shares per contract
    max_trade = 50000
    if total_cost > max_trade:
        msg = f"Order too large: {qty}x @ ${price} = ${total_cost:,.0f} exceeds ${max_trade:,.0f} max"
        _log(f"ENTRY BLOCKED: {ticker} — {msg}")
        return False, msg

    # 3. Duplicate position check
    sys_info = auditor.SYSTEMS.get(system_id, {})
    pos_file = os.path.join(DATA_DIR, f"trader{system_id}_positions.json")
    if os.path.exists(pos_file):
        try:
            with open(pos_file) as f:
                positions = json.load(f)
            open_same = [p for p in positions
                         if p.get("symbol", "").upper() == ticker.upper()
                         and p.get("status", "open") == "open"]
            if open_same:
                msg = f"Duplicate: already have {len(open_same)} open {ticker} position(s) in system {system_id}"
                _log(f"ENTRY BLOCKED: {ticker} — {msg}")
                return False, msg
        except (json.JSONDecodeError, IOError):
            pass

    # 4. Concentration limit (max 40% of system capital in one ticker)
    sys_capital = sys_info.get("capital", 100000)
    max_concentration = sys_capital * 0.40
    if total_cost > max_concentration:
        msg = f"Concentration: ${total_cost:,.0f} exceeds 40% of system capital (${max_concentration:,.0f})"
        _log(f"ENTRY BLOCKED: {ticker} — {msg}")
        return False, msg

    # 5. Premium cap check (v2.2 — max 1.5x mNAV for MSTR entries)
    premium_cap = 1.5
    if ticker.upper() == "MSTR" and kwargs.get("premium_pct"):
        prem = kwargs["premium_pct"]
        if prem > premium_cap:
            msg = f"Premium cap: mNAV {prem:.2f}x exceeds {premium_cap}x limit"
            _log(f"ENTRY BLOCKED: {ticker} — {msg}")
            return False, msg

    _log(f"ENTRY APPROVED: {ticker} {qty}x @ ${price} (system {system_id})")
    return True, "OK"
