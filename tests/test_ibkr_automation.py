#!/usr/bin/env python3
"""
Interactive Brokers TWS/API Automation — Comprehensive Test Suite
==================================================================
Covers the three major complaint categories:
  1. Core Connectivity & Maintenance Issues
     - Mandatory daily restarts / weekly re-auth
     - Local process dependency (TWS / IB Gateway)
     - 2FA authentication friction
     - Session conflicts (TWS vs API on same account)
  2. Data & Performance Limitations
     - Aggregated tick data (not true tick-by-tick)
     - 50 msg/sec throttle → drops / bans
     - Fractional share inconsistencies
  3. Developer Experience
     - Async callback complexity (EWrapper pattern)
     - Documentation fragmentation
     - Silent order failures / phantom fills

Uses only Python standard library (unittest). No pip required.
"""
import unittest
import time
import json
import math
import random
import threading
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Callable
from unittest.mock import MagicMock, patch
from collections import deque
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════════════════════════
# DOMAIN MODELS
# ═══════════════════════════════════════════════════════════════════════════

class SessionType(Enum):
    TWS = auto()
    IB_GATEWAY = auto()
    API = auto()


class OrderStatus(Enum):
    PENDING = "PendingSubmit"
    SUBMITTED = "Submitted"
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    ERROR = "Error"
    INACTIVE = "Inactive"


@dataclass
class IBOrder:
    order_id: int
    symbol: str
    action: str  # "BUY" or "SELL"
    quantity: float
    order_type: str = "MKT"
    status: OrderStatus = OrderStatus.PENDING
    fill_price: Optional[float] = None
    error_code: Optional[int] = None
    error_msg: Optional[str] = None


@dataclass
class TickData:
    symbol: str
    price: float
    size: int
    timestamp: float
    is_aggregated: bool = True  # IBKR default: aggregated, not raw


@dataclass
class ContractSpec:
    symbol: str
    sec_type: str = "STK"
    exchange: str = "SMART"
    currency: str = "USD"
    supports_fractional: bool = False  # varies by contract


# ═══════════════════════════════════════════════════════════════════════════
# SIMULATED TWS/GATEWAY SESSION MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class TWSSessionManager:
    """
    Simulates TWS / IB Gateway session lifecycle:
    - Daily mandatory restart window
    - Weekly Sunday re-authentication
    - 2FA challenges on reconnect
    - Single-session-per-account constraint
    """

    RESTART_WINDOW_HOURS = 24  # must restart within 24 h
    WEEKLY_REAUTH_DAY = 6      # Sunday = 6

    def __init__(self):
        self.session_type: Optional[SessionType] = None
        self.is_connected = False
        self.is_authenticated = False
        self.last_restart: Optional[float] = None
        self.last_auth: Optional[float] = None
        self._2fa_pending = False
        self._active_sessions: dict[str, SessionType] = {}  # account → session
        self.uptime_hours = 0.0

    def start(self, session_type: SessionType):
        self.session_type = session_type
        self.is_connected = True
        self.last_restart = time.time()
        self.uptime_hours = 0.0

    def authenticate(self, account: str, provide_2fa: bool = False) -> bool:
        if not self.is_connected:
            return False  # Must have a running local process
        if self._2fa_pending and not provide_2fa:
            return False
        if account in self._active_sessions:
            existing = self._active_sessions[account]
            if existing != self.session_type:
                # Session conflict — detach
                return False
        self.is_authenticated = True
        self.last_auth = time.time()
        self._active_sessions[account] = self.session_type
        self._2fa_pending = False
        return True

    def trigger_2fa(self):
        self._2fa_pending = True
        self.is_authenticated = False

    def needs_restart(self) -> bool:
        return self.uptime_hours >= self.RESTART_WINDOW_HOURS

    def needs_weekly_reauth(self, current_weekday: int) -> bool:
        return current_weekday == self.WEEKLY_REAUTH_DAY

    def simulate_uptime(self, hours: float):
        self.uptime_hours += hours

    def restart(self):
        self.is_connected = False
        self.is_authenticated = False
        self._2fa_pending = True  # 2FA typically required after restart
        self.uptime_hours = 0.0
        self.last_restart = time.time()

    def disconnect_session(self, account: str):
        self._active_sessions.pop(account, None)
        self.is_connected = False


# ═══════════════════════════════════════════════════════════════════════════
# SIMULATED MESSAGE THROTTLE
# ═══════════════════════════════════════════════════════════════════════════

class IBMessageThrottle:
    """
    IBKR enforces ~50 messages/second.
    Exceeding → connection drop or temporary ban.
    """

    MAX_MSG_PER_SECOND = 50
    BAN_DURATION_SECONDS = 60

    def __init__(self):
        self._message_timestamps: deque = deque()
        self.is_banned = False
        self.ban_expires: Optional[float] = None
        self.total_sent = 0
        self.total_dropped = 0

    def send_message(self, timestamp: Optional[float] = None) -> bool:
        now = timestamp or time.time()

        if self.is_banned:
            if now < self.ban_expires:
                self.total_dropped += 1
                return False
            self.is_banned = False
            self.ban_expires = None

        # Purge messages older than 1 second
        while self._message_timestamps and self._message_timestamps[0] < now - 1.0:
            self._message_timestamps.popleft()

        if len(self._message_timestamps) >= self.MAX_MSG_PER_SECOND:
            self.is_banned = True
            self.ban_expires = now + self.BAN_DURATION_SECONDS
            self.total_dropped += 1
            return False

        self._message_timestamps.append(now)
        self.total_sent += 1
        return True


# ═══════════════════════════════════════════════════════════════════════════
# SIMULATED TICK DATA FEED
# ═══════════════════════════════════════════════════════════════════════════

class IBTickDataFeed:
    """
    Simulates IBKR's aggregated tick data vs true tick-by-tick.
    IBKR aggregates ticks into snapshots (typically ~250ms intervals).
    """

    AGGREGATION_INTERVAL_MS = 250  # IBKR aggregates ticks

    def __init__(self):
        self._raw_ticks: list[TickData] = []
        self._aggregated_ticks: list[TickData] = []

    def ingest_raw_ticks(self, ticks: list[TickData]):
        self._raw_ticks.extend(ticks)

    def aggregate(self) -> list[TickData]:
        """Group raw ticks into IBKR-style aggregated snapshots."""
        if not self._raw_ticks:
            return []

        sorted_ticks = sorted(self._raw_ticks, key=lambda t: t.timestamp)
        result = []
        bucket_start = sorted_ticks[0].timestamp
        bucket_ticks = []

        for tick in sorted_ticks:
            if (tick.timestamp - bucket_start) * 1000 < self.AGGREGATION_INTERVAL_MS:
                bucket_ticks.append(tick)
            else:
                if bucket_ticks:
                    agg = TickData(
                        symbol=bucket_ticks[0].symbol,
                        price=bucket_ticks[-1].price,  # last price in window
                        size=sum(t.size for t in bucket_ticks),
                        timestamp=bucket_ticks[-1].timestamp,
                        is_aggregated=True,
                    )
                    result.append(agg)
                bucket_start = tick.timestamp
                bucket_ticks = [tick]

        # Final bucket
        if bucket_ticks:
            agg = TickData(
                symbol=bucket_ticks[0].symbol,
                price=bucket_ticks[-1].price,
                size=sum(t.size for t in bucket_ticks),
                timestamp=bucket_ticks[-1].timestamp,
                is_aggregated=True,
            )
            result.append(agg)

        self._aggregated_ticks = result
        return result

    @property
    def raw_count(self):
        return len(self._raw_ticks)

    @property
    def aggregated_count(self):
        return len(self._aggregated_ticks)


# ═══════════════════════════════════════════════════════════════════════════
# SIMULATED FRACTIONAL SHARE HANDLER
# ═══════════════════════════════════════════════════════════════════════════

class IBFractionalShareHandler:
    """
    Simulates IBKR's inconsistent fractional share behaviour:
    - Some contracts support fractional, others don't
    - Rounding down without error on some
    - Outright failure on others
    """

    # Contracts that support fractional shares (subset)
    FRACTIONAL_SUPPORTED = {"AAPL", "MSFT", "AMZN", "GOOGL", "TSLA"}

    def place_order(self, contract: ContractSpec, quantity: float) -> IBOrder:
        order = IBOrder(
            order_id=random.randint(1000, 9999),
            symbol=contract.symbol,
            action="BUY",
            quantity=quantity,
        )

        is_fractional = quantity != int(quantity)

        if not is_fractional:
            order.status = OrderStatus.FILLED
            order.fill_price = 150.0  # mock
            return order

        if contract.symbol in self.FRACTIONAL_SUPPORTED:
            # Sometimes rounds down silently
            if quantity < 0.1:
                # Very small fractions get rounded to 0 → silent failure
                order.quantity = 0
                order.status = OrderStatus.INACTIVE
                order.error_msg = "Order quantity rounded to zero"
                return order
            order.status = OrderStatus.FILLED
            order.fill_price = 150.0
            return order
        else:
            # Contract doesn't support fractional
            order.status = OrderStatus.ERROR
            order.error_code = 404
            order.error_msg = f"Fractional shares not supported for {contract.symbol}"
            return order


# ═══════════════════════════════════════════════════════════════════════════
# SIMULATED EWRAPPER CALLBACK SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

class EWrapperCallbackSystem:
    """
    Simulates IBKR's async EWrapper callback pattern.
    Requests are sent, responses arrive asynchronously via callbacks.
    """

    def __init__(self):
        self._callbacks: dict[str, list[Callable]] = {}
        self._pending_requests: dict[int, str] = {}  # reqId → event_name
        self._received_responses: list[dict] = []
        self._errors: list[dict] = []
        self.next_req_id = 1

    def register_callback(self, event_name: str, callback: Callable):
        self._callbacks.setdefault(event_name, []).append(callback)

    def send_request(self, event_name: str) -> int:
        req_id = self.next_req_id
        self.next_req_id += 1
        self._pending_requests[req_id] = event_name
        return req_id

    def deliver_response(self, req_id: int, data: dict):
        event_name = self._pending_requests.pop(req_id, None)
        if event_name and event_name in self._callbacks:
            for cb in self._callbacks[event_name]:
                cb(req_id, data)
            self._received_responses.append({"req_id": req_id, "data": data})
        else:
            # Response with no registered callback — silently lost
            pass

    def deliver_error(self, req_id: int, error_code: int, error_msg: str):
        self._errors.append({
            "req_id": req_id, "code": error_code, "msg": error_msg,
        })
        # Error might arrive even for a filled order (silent order failure)

    @property
    def pending_count(self):
        return len(self._pending_requests)

    @property
    def received_count(self):
        return len(self._received_responses)

    @property
    def error_count(self):
        return len(self._errors)


# ═══════════════════════════════════════════════════════════════════════════
# SIMULATED SILENT ORDER FAILURE SCENARIO
# ═══════════════════════════════════════════════════════════════════════════

class IBOrderManager:
    """
    Simulates the scenario where IBKR returns an error for an order
    that was actually filled, or fails to provide timely status updates.
    """

    def __init__(self, ewrapper: EWrapperCallbackSystem):
        self.ew = ewrapper
        self.orders: dict[int, IBOrder] = {}

    def submit_order(self, symbol: str, action: str, qty: float,
                     simulate_phantom_fill: bool = False,
                     simulate_delayed_status: bool = False) -> int:
        req_id = self.ew.send_request("orderStatus")
        order = IBOrder(
            order_id=req_id, symbol=symbol, action=action, quantity=qty,
        )
        self.orders[req_id] = order

        if simulate_phantom_fill:
            # Order actually fills, but API returns an error
            order.status = OrderStatus.FILLED
            order.fill_price = 155.0
            self.ew.deliver_error(req_id, 201, "Order rejected")
            # The error is misleading — order was actually filled
        elif simulate_delayed_status:
            # Status update never arrives (stays pending)
            order.status = OrderStatus.PENDING
            # No callback delivered — silent
        else:
            order.status = OrderStatus.FILLED
            order.fill_price = 150.0
            self.ew.deliver_response(req_id, {"status": "Filled", "fill_price": 150.0})

        return req_id


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 1: CORE CONNECTIVITY & MAINTENANCE
# ═══════════════════════════════════════════════════════════════════════════

class Test_1_1_MandatoryRestarts(unittest.TestCase):
    """TWS/Gateway require daily restart; weekly manual re-auth on Sunday."""

    def setUp(self):
        self.mgr = TWSSessionManager()
        self.mgr.start(SessionType.TWS)

    def test_no_restart_needed_within_24h(self):
        self.mgr.simulate_uptime(12.0)
        self.assertFalse(self.mgr.needs_restart())

    def test_restart_required_after_24h(self):
        self.mgr.simulate_uptime(24.0)
        self.assertTrue(self.mgr.needs_restart())

    def test_restart_resets_uptime(self):
        self.mgr.simulate_uptime(25.0)
        self.assertTrue(self.mgr.needs_restart())
        self.mgr.restart()
        self.assertEqual(self.mgr.uptime_hours, 0.0)
        self.assertFalse(self.mgr.needs_restart())

    def test_restart_drops_connection(self):
        self.mgr.authenticate("U12345")
        self.assertTrue(self.mgr.is_connected)
        self.assertTrue(self.mgr.is_authenticated)
        self.mgr.restart()
        self.assertFalse(self.mgr.is_connected)
        self.assertFalse(self.mgr.is_authenticated)

    def test_weekly_reauth_on_sunday(self):
        self.assertTrue(self.mgr.needs_weekly_reauth(6))   # Sunday
        self.assertFalse(self.mgr.needs_weekly_reauth(0))  # Monday
        self.assertFalse(self.mgr.needs_weekly_reauth(3))  # Thursday

    def test_consecutive_restarts_accumulate_downtime(self):
        """Each restart cycle = auth time + 2FA. Over a week that adds up."""
        restart_overhead_minutes = 3  # optimistic per restart
        restarts_per_week = 7 + 1  # daily + Sunday re-auth
        total_downtime = restart_overhead_minutes * restarts_per_week
        self.assertEqual(total_downtime, 24)  # 24 min/week of forced downtime


class Test_1_2_LocalProcessDependency(unittest.TestCase):
    """Must run TWS or IB Gateway locally as a bridge."""

    def test_tws_session_starts(self):
        mgr = TWSSessionManager()
        mgr.start(SessionType.TWS)
        self.assertTrue(mgr.is_connected)
        self.assertEqual(mgr.session_type, SessionType.TWS)

    def test_gateway_session_starts(self):
        mgr = TWSSessionManager()
        mgr.start(SessionType.IB_GATEWAY)
        self.assertTrue(mgr.is_connected)
        self.assertEqual(mgr.session_type, SessionType.IB_GATEWAY)

    def test_no_session_without_local_process(self):
        """Without starting TWS/Gateway, there's no connection."""
        mgr = TWSSessionManager()
        self.assertFalse(mgr.is_connected)
        self.assertIsNone(mgr.session_type)

    def test_api_cannot_connect_directly(self):
        """API session alone (no TWS/Gateway) means no authentication path."""
        mgr = TWSSessionManager()
        # Not starting any local process
        result = mgr.authenticate("U12345")
        self.assertFalse(result)  # Can't auth without a running session


class Test_1_3_TwoFactorAuthFriction(unittest.TestCase):
    """2FA challenges trigger on restart or randomly."""

    def setUp(self):
        self.mgr = TWSSessionManager()
        self.mgr.start(SessionType.IB_GATEWAY)

    def test_2fa_blocks_auth_without_code(self):
        self.mgr.trigger_2fa()
        result = self.mgr.authenticate("U12345", provide_2fa=False)
        self.assertFalse(result)
        self.assertFalse(self.mgr.is_authenticated)

    def test_2fa_passes_with_code(self):
        self.mgr.trigger_2fa()
        result = self.mgr.authenticate("U12345", provide_2fa=True)
        self.assertTrue(result)
        self.assertTrue(self.mgr.is_authenticated)

    def test_restart_triggers_2fa(self):
        self.mgr.authenticate("U12345")
        self.assertTrue(self.mgr.is_authenticated)
        self.mgr.restart()
        self.assertTrue(self.mgr._2fa_pending)
        self.assertFalse(self.mgr.is_authenticated)

    def test_headless_server_blocked_by_2fa(self):
        """On a headless cloud server, 2FA with no human = dead automation."""
        self.mgr.restart()
        # Headless: cannot provide 2FA
        result = self.mgr.authenticate("U12345", provide_2fa=False)
        self.assertFalse(result, "Headless server cannot satisfy 2FA")

    def test_random_2fa_mid_session(self):
        """2FA can trigger randomly during an active session."""
        self.mgr.authenticate("U12345")
        self.assertTrue(self.mgr.is_authenticated)
        # Random 2FA challenge
        self.mgr.trigger_2fa()
        self.assertFalse(self.mgr.is_authenticated)


class Test_1_4_SessionConflicts(unittest.TestCase):
    """TWS + API on same account causes detach."""

    def test_tws_then_api_on_same_account_fails(self):
        # First: TWS session authenticates
        tws = TWSSessionManager()
        tws.start(SessionType.TWS)
        tws.authenticate("U12345")

        # Second: API session tries same account
        api = TWSSessionManager()
        api.start(SessionType.API)
        # Simulate shared state
        api._active_sessions = tws._active_sessions
        result = api.authenticate("U12345")
        self.assertFalse(result, "API should be blocked — TWS already holds session")

    def test_same_session_type_on_same_account_ok(self):
        mgr = TWSSessionManager()
        mgr.start(SessionType.TWS)
        result = mgr.authenticate("U12345")
        self.assertTrue(result)
        # Re-auth same session type should work
        result2 = mgr.authenticate("U12345")
        self.assertTrue(result2)

    def test_different_accounts_no_conflict(self):
        mgr = TWSSessionManager()
        mgr.start(SessionType.TWS)
        self.assertTrue(mgr.authenticate("U12345"))
        # Different account on same session
        mgr2 = TWSSessionManager()
        mgr2.start(SessionType.API)
        self.assertTrue(mgr2.authenticate("U67890"))

    def test_disconnect_frees_account(self):
        mgr = TWSSessionManager()
        mgr.start(SessionType.TWS)
        mgr.authenticate("U12345")

        api = TWSSessionManager()
        api.start(SessionType.API)
        api._active_sessions = mgr._active_sessions
        self.assertFalse(api.authenticate("U12345"))

        # Disconnect TWS
        mgr.disconnect_session("U12345")
        api._active_sessions = mgr._active_sessions
        self.assertTrue(api.authenticate("U12345"))


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 2: DATA & PERFORMANCE LIMITATIONS
# ═══════════════════════════════════════════════════════════════════════════

class Test_2_1_AggregatedTickData(unittest.TestCase):
    """IBKR provides aggregated snapshots, not true tick-by-tick."""

    def _make_raw_ticks(self, symbol, n, base_price, interval_ms):
        """Generate n raw ticks spaced interval_ms apart."""
        base_time = 1000000.0
        return [
            TickData(
                symbol=symbol,
                price=base_price + random.uniform(-0.5, 0.5),
                size=random.randint(1, 100),
                timestamp=base_time + i * (interval_ms / 1000),
                is_aggregated=False,
            )
            for i in range(n)
        ]

    def test_aggregation_reduces_tick_count(self):
        random.seed(42)
        feed = IBTickDataFeed()
        # 100 raw ticks, 10ms apart = 1 second total
        raw = self._make_raw_ticks("AAPL", 100, 150.0, 10)
        feed.ingest_raw_ticks(raw)
        agg = feed.aggregate()

        self.assertEqual(feed.raw_count, 100)
        self.assertLess(feed.aggregated_count, 100)
        # 1000ms / 250ms interval = ~4 buckets
        self.assertLessEqual(feed.aggregated_count, 5)

    def test_aggregated_ticks_marked_correctly(self):
        random.seed(42)
        feed = IBTickDataFeed()
        raw = self._make_raw_ticks("AAPL", 50, 150.0, 10)
        feed.ingest_raw_ticks(raw)
        agg = feed.aggregate()

        for tick in agg:
            self.assertTrue(tick.is_aggregated)

    def test_hft_misses_intra_aggregate_moves(self):
        """Within a 250ms window, price can spike and revert — HFT misses it."""
        feed = IBTickDataFeed()
        base = 1000000.0
        # Rapid price spike within one aggregation window
        ticks = [
            TickData("AAPL", 150.0, 10, base + 0.00, is_aggregated=False),
            TickData("AAPL", 155.0, 50, base + 0.05, is_aggregated=False),  # spike!
            TickData("AAPL", 150.5, 20, base + 0.10, is_aggregated=False),  # reverts
        ]
        feed.ingest_raw_ticks(ticks)
        agg = feed.aggregate()

        # All 3 ticks fall in one 250ms bucket → only last price visible
        self.assertEqual(len(agg), 1)
        self.assertAlmostEqual(agg[0].price, 150.5)
        # The 155.0 spike is invisible to anyone using aggregated data
        self.assertNotAlmostEqual(agg[0].price, 155.0)

    def test_aggregated_size_is_cumulative(self):
        feed = IBTickDataFeed()
        base = 1000000.0
        ticks = [
            TickData("AAPL", 150.0, 10, base + 0.00, is_aggregated=False),
            TickData("AAPL", 150.5, 20, base + 0.05, is_aggregated=False),
            TickData("AAPL", 151.0, 30, base + 0.10, is_aggregated=False),
        ]
        feed.ingest_raw_ticks(ticks)
        agg = feed.aggregate()

        self.assertEqual(len(agg), 1)
        self.assertEqual(agg[0].size, 60)  # 10 + 20 + 30


class Test_2_2_MessageThrottle(unittest.TestCase):
    """50 msg/sec limit; exceeding → connection drop or ban."""

    def test_under_limit_all_succeed(self):
        throttle = IBMessageThrottle()
        base = 1000000.0
        results = [throttle.send_message(base + i * 0.05) for i in range(40)]
        self.assertTrue(all(results))
        self.assertEqual(throttle.total_sent, 40)

    def test_exactly_50_in_one_second_succeeds(self):
        throttle = IBMessageThrottle()
        base = 1000000.0
        results = [throttle.send_message(base + i * 0.019) for i in range(50)]
        self.assertTrue(all(results))

    def test_51st_message_triggers_ban(self):
        throttle = IBMessageThrottle()
        base = 1000000.0
        for i in range(50):
            throttle.send_message(base + i * 0.019)
        result = throttle.send_message(base + 0.98)
        self.assertFalse(result)
        self.assertTrue(throttle.is_banned)

    def test_ban_lasts_60_seconds(self):
        throttle = IBMessageThrottle()
        base = 1000000.0
        for i in range(51):
            throttle.send_message(base + i * 0.019)
        self.assertTrue(throttle.is_banned)

        # 30 seconds later — still banned
        self.assertFalse(throttle.send_message(base + 30))

        # 61 seconds later — ban lifted
        self.assertTrue(throttle.send_message(base + 61))
        self.assertFalse(throttle.is_banned)

    def test_messages_during_ban_are_dropped(self):
        throttle = IBMessageThrottle()
        base = 1000000.0
        for i in range(51):
            throttle.send_message(base + i * 0.019)

        # Send 10 messages during ban
        for i in range(10):
            throttle.send_message(base + 5 + i * 0.1)

        self.assertEqual(throttle.total_dropped, 11)  # 1 trigger + 10 during ban

    def test_burst_during_volatility(self):
        """High-vol event causes burst of market data requests → throttle."""
        throttle = IBMessageThrottle()
        base = 1000000.0
        # Simulate 100 rapid-fire requests in 0.5 seconds
        results = [throttle.send_message(base + i * 0.005) for i in range(100)]
        successes = sum(1 for r in results if r)
        self.assertEqual(successes, 50)
        self.assertTrue(throttle.is_banned)


class Test_2_3_FractionalShares(unittest.TestCase):
    """Fractional share handling is inconsistent across contracts."""

    def setUp(self):
        self.handler = IBFractionalShareHandler()

    def test_whole_shares_always_work(self):
        contract = ContractSpec(symbol="AAPL")
        order = self.handler.place_order(contract, 10)
        self.assertEqual(order.status, OrderStatus.FILLED)

    def test_fractional_supported_contract_fills(self):
        contract = ContractSpec(symbol="AAPL")
        order = self.handler.place_order(contract, 0.5)
        self.assertEqual(order.status, OrderStatus.FILLED)

    def test_fractional_unsupported_contract_errors(self):
        contract = ContractSpec(symbol="BRK.A")
        order = self.handler.place_order(contract, 0.5)
        self.assertEqual(order.status, OrderStatus.ERROR)
        self.assertIn("not supported", order.error_msg)

    def test_very_small_fraction_rounds_to_zero(self):
        """Tiny fractional orders silently round to 0 → inactive."""
        contract = ContractSpec(symbol="AAPL")
        order = self.handler.place_order(contract, 0.05)
        self.assertEqual(order.status, OrderStatus.INACTIVE)
        self.assertEqual(order.quantity, 0)
        self.assertIn("rounded to zero", order.error_msg)

    def test_inconsistency_across_supported_contracts(self):
        """Same fractional qty: works on AAPL, fails on obscure stock."""
        aapl = ContractSpec(symbol="AAPL")
        obscure = ContractSpec(symbol="XYZ_MICRO")

        order_aapl = self.handler.place_order(aapl, 0.5)
        order_obscure = self.handler.place_order(obscure, 0.5)

        self.assertEqual(order_aapl.status, OrderStatus.FILLED)
        self.assertEqual(order_obscure.status, OrderStatus.ERROR)

    def test_no_error_on_silent_round_down(self):
        """The API doesn't raise an error — it just sets qty to 0."""
        contract = ContractSpec(symbol="TSLA")
        order = self.handler.place_order(contract, 0.05)
        self.assertIsNone(order.error_code)  # No error code!
        self.assertEqual(order.quantity, 0)


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 3: DEVELOPER EXPERIENCE
# ═══════════════════════════════════════════════════════════════════════════

class Test_3_1_AsyncCallbackComplexity(unittest.TestCase):
    """Async EWrapper pattern is harder than REST request-response."""

    def setUp(self):
        self.ew = EWrapperCallbackSystem()

    def test_request_response_flow(self):
        """Basic: send request, receive callback."""
        received = []
        self.ew.register_callback("marketData", lambda rid, d: received.append(d))
        req_id = self.ew.send_request("marketData")
        self.assertEqual(self.ew.pending_count, 1)

        self.ew.deliver_response(req_id, {"price": 150.0})
        self.assertEqual(self.ew.pending_count, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["price"], 150.0)

    def test_unregistered_callback_loses_response(self):
        """If no callback registered, response is silently dropped."""
        req_id = self.ew.send_request("historicalData")
        self.ew.deliver_response(req_id, {"bars": []})
        self.assertEqual(self.ew.received_count, 0)  # lost!

    def test_multiple_pending_requests(self):
        """Developer must track req_ids manually — easy to mix up."""
        self.ew.register_callback("marketData", lambda rid, d: None)
        ids = [self.ew.send_request("marketData") for _ in range(5)]
        self.assertEqual(self.ew.pending_count, 5)
        self.assertEqual(len(set(ids)), 5)  # all unique

    def test_out_of_order_responses(self):
        """Responses can arrive in any order — developer must handle."""
        results = {}
        self.ew.register_callback("marketData",
            lambda rid, d: results.update({rid: d}))

        id1 = self.ew.send_request("marketData")
        id2 = self.ew.send_request("marketData")
        id3 = self.ew.send_request("marketData")

        # Deliver out of order
        self.ew.deliver_response(id3, {"symbol": "MSFT"})
        self.ew.deliver_response(id1, {"symbol": "AAPL"})
        self.ew.deliver_response(id2, {"symbol": "GOOGL"})

        self.assertEqual(results[id1]["symbol"], "AAPL")
        self.assertEqual(results[id2]["symbol"], "GOOGL")
        self.assertEqual(results[id3]["symbol"], "MSFT")

    def test_error_callback_separate_from_data(self):
        """Errors arrive through a different channel than data responses."""
        self.ew.register_callback("orderStatus", lambda rid, d: None)
        req_id = self.ew.send_request("orderStatus")
        self.ew.deliver_error(req_id, 201, "Order rejected")

        self.assertEqual(self.ew.error_count, 1)
        self.assertEqual(self.ew.received_count, 0)  # no data response


class Test_3_2_DocumentationFragmentation(unittest.TestCase):
    """Docs scattered across multiple sites with inconsistent formats."""

    def test_input_format_inconsistency(self):
        """Same concept uses different formats across endpoints."""
        # Some endpoints use string dates, others use epoch
        date_formats_in_use = [
            "20260314 09:30:00",      # TWS API historicalData
            "2026-03-14T09:30:00Z",   # Web API / REST
            1710408600,                # epoch seconds
            1710408600000,             # epoch milliseconds
        ]
        # All represent roughly the same moment but in 4 different formats
        self.assertEqual(len(date_formats_in_use), 4)
        # A developer must know which format each endpoint expects

    def test_order_type_naming_inconsistency(self):
        """Order type strings differ between docs and actual API."""
        doc_names = {"MARKET", "LIMIT", "STOP", "STOP_LIMIT"}
        api_names = {"MKT", "LMT", "STP", "STP LMT"}

        # None of the doc names match the API names
        self.assertEqual(len(doc_names & api_names), 0)

    def test_error_code_not_in_main_docs(self):
        """Some error codes only appear in forum posts, not official docs."""
        official_error_codes = {200, 201, 202, 203, 321, 322}
        forum_only_codes = {10147, 10148, 2104, 2106, 2158}

        # These codes are real but undocumented (or poorly documented)
        self.assertTrue(forum_only_codes.isdisjoint(official_error_codes))

    def test_multiple_doc_sources(self):
        """Users must check multiple URLs for complete information."""
        doc_sources = [
            "interactivebrokers.github.io/tws-api/",
            "interactivebrokers.com/api/doc.html",
            "interactivebrokers.com/campus/",
            "groups.io/g/twsapi/",
        ]
        self.assertGreater(len(doc_sources), 2,
            "Documentation is fragmented across too many sources")


class Test_3_3_SilentOrderFailures(unittest.TestCase):
    """API returns error for filled orders, or no status at all."""

    def setUp(self):
        self.ew = EWrapperCallbackSystem()
        self.ew.register_callback("orderStatus", lambda rid, d: None)
        self.om = IBOrderManager(self.ew)

    def test_normal_order_fills_correctly(self):
        req_id = self.om.submit_order("AAPL", "BUY", 10)
        order = self.om.orders[req_id]
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.fill_price, 150.0)
        self.assertEqual(self.ew.error_count, 0)

    def test_phantom_fill_error_on_filled_order(self):
        """Order fills, but API returns error — developer thinks it failed."""
        req_id = self.om.submit_order("AAPL", "BUY", 10,
                                       simulate_phantom_fill=True)
        order = self.om.orders[req_id]

        # Order actually filled
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.fill_price, 155.0)

        # But the error channel says "rejected"
        self.assertEqual(self.ew.error_count, 1)
        self.assertEqual(self.ew._errors[0]["msg"], "Order rejected")

        # Developer sees error, might try to re-submit → double fill!

    def test_delayed_status_no_callback(self):
        """Order submitted but status update never arrives."""
        req_id = self.om.submit_order("AAPL", "BUY", 10,
                                       simulate_delayed_status=True)
        order = self.om.orders[req_id]

        self.assertEqual(order.status, OrderStatus.PENDING)
        self.assertEqual(self.ew.received_count, 0)  # no callback received
        self.assertEqual(self.ew.pending_count, 1)    # still pending

    def test_phantom_fill_double_submit_risk(self):
        """
        Scenario: Error on fill → developer retries → double execution.
        """
        # First attempt: phantom fill (filled but error returned)
        id1 = self.om.submit_order("AAPL", "BUY", 100,
                                    simulate_phantom_fill=True)
        # Developer sees error, retries
        id2 = self.om.submit_order("AAPL", "BUY", 100)

        order1 = self.om.orders[id1]
        order2 = self.om.orders[id2]

        # Both filled! 200 shares instead of 100
        self.assertEqual(order1.status, OrderStatus.FILLED)
        self.assertEqual(order2.status, OrderStatus.FILLED)
        total_qty = order1.quantity + order2.quantity
        self.assertEqual(total_qty, 200, "Double fill — 2× intended quantity")

    def test_high_volatility_increases_phantom_risk(self):
        """During high vol, more orders hit phantom-fill scenarios."""
        phantom_count = 0
        for i in range(20):
            # Simulate: 30% chance of phantom fill during high vol
            phantom = (i % 3 == 0)
            req_id = self.om.submit_order(
                "SPY", "BUY", 50, simulate_phantom_fill=phantom
            )
            if phantom:
                phantom_count += 1

        self.assertEqual(phantom_count, 7)  # 7 out of 20 = 35%
        self.assertGreater(self.ew.error_count, 0)


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION: CROSS-CATEGORY SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════

class Test_Integration_RealWorldScenarios(unittest.TestCase):
    """End-to-end scenarios combining multiple failure modes."""

    def test_restart_during_open_order(self):
        """Mandatory restart happens while an order is pending."""
        mgr = TWSSessionManager()
        mgr.start(SessionType.IB_GATEWAY)
        mgr.authenticate("U12345")

        ew = EWrapperCallbackSystem()
        ew.register_callback("orderStatus", lambda rid, d: None)
        om = IBOrderManager(ew)

        # Submit order
        req_id = om.submit_order("AAPL", "BUY", 50,
                                  simulate_delayed_status=True)

        # Mandatory restart hits
        mgr.restart()
        self.assertFalse(mgr.is_connected)

        # Order status unknown — still pending from our perspective
        self.assertEqual(om.orders[req_id].status, OrderStatus.PENDING)
        self.assertEqual(ew.pending_count, 1)

    def test_throttle_hit_during_market_open(self):
        """50 msg/sec limit + market open data burst → data loss."""
        throttle = IBMessageThrottle()
        base = 1000000.0
        # Market open: 200 messages in 2 seconds
        results = []
        for i in range(200):
            t = base + i * 0.01  # 100 msg/sec attempted
            results.append(throttle.send_message(t))

        sent = sum(1 for r in results if r)
        dropped = sum(1 for r in results if not r)

        self.assertLessEqual(sent, 100)  # max ~50/sec × 2sec
        self.assertGreater(dropped, 0)

    def test_2fa_plus_session_conflict_on_sunday(self):
        """Sunday: weekly re-auth + 2FA + possible session conflict."""
        mgr = TWSSessionManager()
        mgr.start(SessionType.IB_GATEWAY)
        mgr.authenticate("U12345")

        # Sunday re-auth required
        self.assertTrue(mgr.needs_weekly_reauth(6))
        mgr.restart()
        self.assertTrue(mgr._2fa_pending)

        # Without 2FA → locked out
        self.assertFalse(mgr.authenticate("U12345", provide_2fa=False))


# ═══════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
