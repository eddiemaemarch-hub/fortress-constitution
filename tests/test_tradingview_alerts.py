#!/usr/bin/env python3
"""
TradingView Alert Automation — Comprehensive Test Suite
========================================================
Covers all four categories of common complaints:
  1. Signal Reliability & Webhook Failures
  2. Execution Latency
  3. Platform Constraints & Logic Issues
  4. Configuration Pitfalls
Uses only the standard-library `unittest` module (no pip needed).
"""
import unittest
import json
import time
import math
import re
import statistics
from unittest.mock import MagicMock
from dataclasses import dataclass, field
from typing import Optional
# ═══════════════════════════════════════════════════════════════════════════
# DOMAIN MODELS
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class WebhookPayload:
    action: str
    ticker: str
    price: float
    timestamp: float = field(default_factory=time.time)
    order_id: Optional[str] = None
    extra: dict = field(default_factory=dict)
    def to_json(self) -> str:
        return json.dumps(self.__dict__)
    @classmethod
    def from_json(cls, raw: str) -> "WebhookPayload":
        data = json.loads(raw)
        return cls(**data)
@dataclass
class AlertEvent:
    alert_id: str
    indicator: str
    message: str
    fired_at: float
    bar_close_price: Optional[float] = None
    is_repaint: bool = False
@dataclass
class WebhookDeliveryResult:
    success: bool
    status_code: Optional[int] = None
    latency_ms: float = 0.0
    retries: int = 0
    error: Optional[str] = None
# ═══════════════════════════════════════════════════════════════════════════
# SIMULATED TRADINGVIEW ENGINE
# ═══════════════════════════════════════════════════════════════════════════
class TradingViewWebhookDispatcher:
    TIMEOUT_SECONDS = 3.0
    MAX_ALERTS_PER_3MIN = 15
    def __init__(self):
        self._alert_count = 0
        self._window_start = time.time()
        self._delivery_log: list = []
        self._disabled = False
    @property
    def is_disabled(self):
        return self._disabled
    def reset_window(self):
        self._alert_count = 0
        self._window_start = time.time()
    def _check_rate_limit(self):
        now = time.time()
        if now - self._window_start > 180:
            self.reset_window()
        self._alert_count += 1
        if self._alert_count > self.MAX_ALERTS_PER_3MIN:
            self._disabled = True
            return False
        return True
    def dispatch(self, url, payload, send_fn=None, server_delay=0.0):
        if not self._check_rate_limit():
            r = WebhookDeliveryResult(success=False, error="rate_limit_exceeded_alert_disabled")
            self._delivery_log.append(r)
            return r
        start = time.monotonic()
        try:
            if send_fn is None:
                raise ConnectionError("No send function configured")
            if server_delay > self.TIMEOUT_SECONDS:
                raise TimeoutError("Webhook timed out")
            send_fn(url, payload.to_json())
            latency = (time.monotonic() - start) * 1000
            r = WebhookDeliveryResult(success=True, status_code=200, latency_ms=latency)
        except TimeoutError:
            r = WebhookDeliveryResult(success=False, error="timeout",
                                       latency_ms=self.TIMEOUT_SECONDS * 1000)
        except Exception as e:
            r = WebhookDeliveryResult(success=False, error=str(e))
        self._delivery_log.append(r)
        return r
    @property
    def delivery_log(self):
        return list(self._delivery_log)
class IndicatorEngine:
    def __init__(self, version=1):
        self.version = version
        self._signal_history = []
    def evaluate_bar(self, bar_open, bar_high, bar_low, bar_close, is_realtime=False):
        signal = bar_close > bar_open
        repainted = False
        if is_realtime:
            signal = bar_high > bar_open * 1.001
            repainted = True
        if signal:
            evt = AlertEvent(
                alert_id=f"alert-{len(self._signal_history)}",
                indicator=f"test_indicator_v{self.version}",
                message="BUY", fired_at=time.time(),
                bar_close_price=bar_close, is_repaint=repainted,
            )
            self._signal_history.append(evt)
            return evt
        return None
    def upgrade(self, new_version):
        self.version = new_version
class AlertSnapshot:
    def __init__(self, engine):
        self.frozen_version = engine.version
    def matches_current(self, engine):
        return self.frozen_version == engine.version
class CloudScriptRunner:
    MEMORY_LIMIT_BARS = 10_000
    def __init__(self):
        self.status = "active"
        self.error_log = []
    def run(self, bar_count, complexity_factor=1.0):
        effective_load = bar_count * complexity_factor
        if effective_load > self.MEMORY_LIMIT_BARS:
            self.status = "inactive"
            self.error_log.append(f"Memory limit exceeded: {effective_load:.0f}")
            return False
        return True
# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def simulate_chain_latency(dispatch_ms, network_ms, broker_api_ms):
    return dispatch_ms + network_ms + broker_api_ms
def heikin_ashi_ohlc(prev_ha_open, prev_ha_close, real_o, real_h, real_l, real_c):
    ha_close = (real_o + real_h + real_l + real_c) / 4
    ha_open = (prev_ha_open + prev_ha_close) / 2
    ha_high = max(real_h, ha_open, ha_close)
    ha_low = min(real_l, ha_open, ha_close)
    return ha_open, ha_high, ha_low, ha_close
def renko_bricks(prices, brick_size):
    if not prices:
        return []
    bricks = [prices[0]]
    for p in prices[1:]:
        while p >= bricks[-1] + brick_size:
            bricks.append(bricks[-1] + brick_size)
        while p <= bricks[-1] - brick_size:
            bricks.append(bricks[-1] - brick_size)
    return bricks
def simulate_spike_latencies(base_ms, spike_factor, n):
    import random
    random.seed(42)
    return [base_ms * spike_factor * (1 + random.random() * 0.5) for _ in range(n)]
# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 1: SIGNAL RELIABILITY & WEBHOOK FAILURES
# ═══════════════════════════════════════════════════════════════════════════
class Test_1_1_MissingWebhooks(unittest.TestCase):
    """Alert fires in TV log but webhook never received."""
    def setUp(self):
        self.dispatcher = TradingViewWebhookDispatcher()
        self.payload = WebhookPayload(action="buy", ticker="AAPL", price=189.50)
    def test_unreachable_server(self):
        def unreachable(url, body):
            raise ConnectionError("Connection refused")
        r = self.dispatcher.dispatch("https://broker.example.com/wh", self.payload, unreachable)
        self.assertFalse(r.success)
        self.assertIn("Connection refused", r.error)
    def test_empty_webhook_url(self):
        def fail_empty(url, body):
            if not url:
                raise ValueError("Empty URL")
        r = self.dispatcher.dispatch("", self.payload, fail_empty)
        self.assertFalse(r.success)
    def test_dispatch_count_matches_alert_count(self):
        ok = MagicMock()
        for i in range(5):
            p = WebhookPayload(action="buy", ticker="AAPL", price=190 + i)
            self.dispatcher.dispatch("https://x.com/wh", p, ok)
        self.assertEqual(ok.call_count, 5)
        self.assertTrue(all(r.success for r in self.dispatcher.delivery_log))
class Test_1_2_SingleAttemptTimeout(unittest.TestCase):
    """TV makes ONE attempt with ~3 s timeout."""
    def setUp(self):
        self.dispatcher = TradingViewWebhookDispatcher()
        self.payload = WebhookPayload(action="buy", ticker="AAPL", price=189.50)
    def test_within_timeout_succeeds(self):
        r = self.dispatcher.dispatch("https://x.com/wh", self.payload, MagicMock(), server_delay=1.0)
        self.assertTrue(r.success)
    def test_exceeds_timeout_fails(self):
        r = self.dispatcher.dispatch("https://x.com/wh", self.payload, MagicMock(), server_delay=5.0)
        self.assertFalse(r.success)
        self.assertEqual(r.error, "timeout")
    def test_no_retry_after_timeout(self):
        fn = MagicMock()
        r = self.dispatcher.dispatch("https://x.com/wh", self.payload, fn, server_delay=5.0)
        self.assertFalse(r.success)
        self.assertEqual(r.retries, 0)
        fn.assert_not_called()
    def test_no_retry_on_500(self):
        count = {"n": 0}
        def flaky(url, body):
            count["n"] += 1
            raise ConnectionError("HTTP 500")
        self.dispatcher.dispatch("https://x.com/wh", self.payload, flaky)
        self.assertEqual(count["n"], 1)
class Test_1_3_InvisibleFailures(unittest.TestCase):
    """No integrated log for delivery success/failure."""
    def setUp(self):
        self.dispatcher = TradingViewWebhookDispatcher()
    def test_failure_captured_in_log(self):
        p = WebhookPayload(action="buy", ticker="AAPL", price=190)
        def timeout(url, body):
            raise TimeoutError("timed out")
        self.dispatcher.dispatch("https://x.com/wh", p, timeout, server_delay=5.0)
        log = self.dispatcher.delivery_log
        self.assertEqual(len(log), 1)
        self.assertFalse(log[0].success)
    def test_interleaved_success_and_failure(self):
        ok = MagicMock()
        def fail(url, body):
            raise ConnectionError("refused")
        p = WebhookPayload(action="buy", ticker="AAPL", price=190)
        self.dispatcher.dispatch("https://x.com/wh", p, ok)
        self.dispatcher.dispatch("https://x.com/wh", p, fail)
        self.dispatcher.dispatch("https://x.com/wh", p, ok)
        self.assertEqual([r.success for r in self.dispatcher.delivery_log], [True, False, True])
    def test_failed_has_no_status_code(self):
        p = WebhookPayload(action="buy", ticker="AAPL", price=190)
        def fail(url, body):
            raise ConnectionError("refused")
        r = self.dispatcher.dispatch("https://x.com/wh", p, fail)
        self.assertIsNone(r.status_code)
class Test_1_4_ServerBusy(unittest.TestCase):
    """Momentarily busy servers cause silent cancellation."""
    def setUp(self):
        self.dispatcher = TradingViewWebhookDispatcher()
    def test_brief_overload_causes_timeout(self):
        p = WebhookPayload(action="buy", ticker="SPY", price=500)
        r = self.dispatcher.dispatch("https://x.com/wh", p, MagicMock(), server_delay=4.0)
        self.assertFalse(r.success)
    def test_burst_during_overload_all_fail(self):
        results = []
        for i in range(5):
            p = WebhookPayload(action="buy", ticker="SPY", price=500 + i)
            results.append(self.dispatcher.dispatch("https://x.com/wh", p, MagicMock(), server_delay=4.0))
        self.assertTrue(all(not r.success for r in results))
        self.assertTrue(all(r.error == "timeout" for r in results))
# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 2: EXECUTION LATENCY
# ═══════════════════════════════════════════════════════════════════════════
class Test_2_1_TransmissionDelays(unittest.TestCase):
    """Alerts can lag from seconds to minutes."""
    def test_delay_acceptability_for_scalping(self):
        THRESHOLD = 3000
        cases = [(50, True), (500, True), (3000, True), (15000, False), (120000, False)]
        for delay_ms, acceptable in cases:
            with self.subTest(delay_ms=delay_ms):
                self.assertEqual(delay_ms <= THRESHOLD, acceptable)
    def test_normal_latency_under_1s(self):
        d = TradingViewWebhookDispatcher()
        p = WebhookPayload(action="buy", ticker="AAPL", price=190)
        r = d.dispatch("https://x.com/wh", p, MagicMock(), server_delay=0.0)
        self.assertTrue(r.success)
        self.assertLess(r.latency_ms, 1000)
    def test_chain_latency_calculation(self):
        total = simulate_chain_latency(200, 80, 150)
        self.assertEqual(total, 430)
        self.assertLess(total, 1000)
class Test_2_2_HighVolumeSpikes(unittest.TestCase):
    """Delays worsen during market open / NFP."""
    def test_market_open_spike(self):
        normal = simulate_spike_latencies(100, 1.0, 50)
        spike = simulate_spike_latencies(100, 3.5, 50)
        self.assertGreater(statistics.mean(spike), 2 * statistics.mean(normal))
    def test_nfp_extreme_outliers(self):
        lats = simulate_spike_latencies(100, 15.0, 100)
        p99 = sorted(lats)[int(0.99 * len(lats))]
        self.assertGreater(p99, 1000)
    def test_variance_increases(self):
        normal = simulate_spike_latencies(100, 1.0, 100)
        spike = simulate_spike_latencies(100, 5.0, 100)
        self.assertGreater(statistics.variance(spike), statistics.variance(normal))
class Test_2_3_NetworkChainLatency(unittest.TestCase):
    """End-to-end: TV → network → broker."""
    def test_chain_within_budget(self):
        cases = [(100, 50, 100, 500), (500, 200, 300, 1500), (2000, 500, 1000, 5000)]
        for d, n, b, mx in cases:
            with self.subTest(dispatch=d, network=n, broker=b):
                self.assertLessEqual(simulate_chain_latency(d, n, b), mx)
    def test_broker_api_is_bottleneck(self):
        d, n, b = 150, 80, 800
        total = simulate_chain_latency(d, n, b)
        self.assertGreater(b / total * 100, 50)
    def test_two_hop_slower_than_single(self):
        hop1 = simulate_chain_latency(200, 60, 100)
        hop2 = simulate_chain_latency(50, 60, 200)
        single = simulate_chain_latency(200, 60, 200)
        self.assertGreater(hop1 + hop2, single)
# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 3: PLATFORM CONSTRAINTS & LOGIC ISSUES
# ═══════════════════════════════════════════════════════════════════════════
class Test_3_1_FrequencyLimit(unittest.TestCase):
    """15 alerts / 3 min then auto-disable."""
    def setUp(self):
        self.dispatcher = TradingViewWebhookDispatcher()
    def test_exactly_15_allowed(self):
        ok = MagicMock()
        for i in range(15):
            p = WebhookPayload(action="buy", ticker="SPY", price=500 + i)
            r = self.dispatcher.dispatch("https://x.com/wh", p, ok)
            self.assertTrue(r.success)
        self.assertFalse(self.dispatcher.is_disabled)
    def test_16th_disables(self):
        ok = MagicMock()
        for i in range(15):
            self.dispatcher.dispatch("https://x.com/wh",
                WebhookPayload(action="buy", ticker="SPY", price=500 + i), ok)
        r = self.dispatcher.dispatch("https://x.com/wh",
            WebhookPayload(action="buy", ticker="SPY", price=515), ok)
        self.assertFalse(r.success)
        self.assertEqual(r.error, "rate_limit_exceeded_alert_disabled")
        self.assertTrue(self.dispatcher.is_disabled)
    def test_reset_after_3_min(self):
        ok = MagicMock()
        for i in range(15):
            self.dispatcher.dispatch("https://x.com/wh",
                WebhookPayload(action="buy", ticker="SPY", price=500 + i), ok)
        self.dispatcher.reset_window()
        self.dispatcher._disabled = False
        r = self.dispatcher.dispatch("https://x.com/wh",
            WebhookPayload(action="buy", ticker="SPY", price=520), ok)
        self.assertTrue(r.success)
    def test_high_vol_burst_hits_limit(self):
        ok = MagicMock()
        results = []
        for i in range(25):
            results.append(self.dispatcher.dispatch("https://x.com/wh",
                WebhookPayload(action="buy", ticker="SPY", price=500 + i), ok))
        self.assertEqual(sum(1 for r in results if r.success), 15)
        self.assertEqual(sum(1 for r in results if not r.success), 10)
class Test_3_2_Repainting(unittest.TestCase):
    """Repaint: signal in realtime, gone on bar close."""
    def setUp(self):
        self.indicator = IndicatorEngine(version=1)
    def test_realtime_fires(self):
        evt = self.indicator.evaluate_bar(100, 102, 99, 99.5, is_realtime=True)
        self.assertIsNotNone(evt)
        self.assertTrue(evt.is_repaint)
    def test_bar_close_no_signal(self):
        evt = self.indicator.evaluate_bar(100, 102, 99, 99.5, is_realtime=False)
        self.assertIsNone(evt)
    def test_false_automation_trigger(self):
        rt = self.indicator.evaluate_bar(100, 101.5, 99.8, 99.9, is_realtime=True)
        self.assertIsNotNone(rt, "Realtime should fire")
        hist = self.indicator.evaluate_bar(100, 101.5, 99.8, 99.9, is_realtime=False)
        self.assertIsNone(hist, "Historical should NOT fire — repaint trap")
    def test_non_repainting_consistent(self):
        eng = IndicatorEngine(version=1)
        rt = eng.evaluate_bar(100, 105, 99, 103, is_realtime=True)
        hist = eng.evaluate_bar(100, 105, 99, 103, is_realtime=False)
        self.assertIsNotNone(rt)
        self.assertIsNotNone(hist)
class Test_3_3_OutdatedAlertCode(unittest.TestCase):
    """Alerts freeze script version at creation."""
    def test_snapshot_matches_at_creation(self):
        eng = IndicatorEngine(version=1)
        snap = AlertSnapshot(eng)
        self.assertTrue(snap.matches_current(eng))
    def test_mismatch_after_upgrade(self):
        eng = IndicatorEngine(version=1)
        snap = AlertSnapshot(eng)
        eng.upgrade(2)
        self.assertFalse(snap.matches_current(eng))
    def test_recreate_alert_after_change(self):
        eng = IndicatorEngine(version=1)
        old = AlertSnapshot(eng)
        eng.upgrade(3)
        self.assertFalse(old.matches_current(eng))
        new = AlertSnapshot(eng)
        self.assertTrue(new.matches_current(eng))
    def test_multiple_upgrades(self):
        eng = IndicatorEngine(version=1)
        snap = AlertSnapshot(eng)
        for v in range(2, 6):
            eng.upgrade(v)
        self.assertEqual(snap.frozen_version, 1)
        self.assertEqual(eng.version, 5)
        self.assertFalse(snap.matches_current(eng))
class Test_3_4_CalculationErrors(unittest.TestCase):
    """Cloud memory limits → silent deactivation."""
    def test_normal_bars_ok(self):
        r = CloudScriptRunner()
        self.assertTrue(r.run(5000))
        self.assertEqual(r.status, "active")
    def test_excessive_bars_deactivates(self):
        r = CloudScriptRunner()
        self.assertFalse(r.run(15_000))
        self.assertEqual(r.status, "inactive")
    def test_complexity_multiplier(self):
        r = CloudScriptRunner()
        self.assertFalse(r.run(6000, complexity_factor=2.0))
        self.assertEqual(r.status, "inactive")
    def test_local_passes_cloud_fails(self):
        cloud = CloudScriptRunner()
        self.assertTrue(True)  # local always passes
        self.assertFalse(cloud.run(15_000))
        self.assertEqual(cloud.status, "inactive")
    def test_no_notification(self):
        r = CloudScriptRunner()
        r.run(20_000)
        self.assertEqual(r.status, "inactive")
        self.assertFalse(hasattr(r, "notification_sent"))
# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 4: CONFIGURATION PITFALLS
# ═══════════════════════════════════════════════════════════════════════════
class Test_4_1_JsonFormatting(unittest.TestCase):
    """~18.7% of failures from bad JSON."""
    def test_valid_json(self):
        data = json.loads('{"action": "buy", "ticker": "AAPL", "price": 189.50}')
        self.assertEqual(data["action"], "buy")
    def test_malformed_json_variants(self):
        bad = [
            '{"action": "buy", "ticker": "AAPL", price: 189.50}',
            "{'action': 'buy'}",
            '{"action": "buy",}',
            '',
            '{"action": "buy", "price": }',
            'action=buy&ticker=AAPL&price=189.50',
        ]
        for s in bad:
            with self.subTest(payload=s[:30]):
                with self.assertRaises((json.JSONDecodeError, ValueError)):
                    d = json.loads(s)
                    if d is None:
                        raise ValueError("null")
    def test_round_trip(self):
        orig = WebhookPayload(action="buy", ticker="AAPL", price=189.50)
        restored = WebhookPayload.from_json(orig.to_json())
        self.assertEqual(restored.action, orig.action)
        self.assertEqual(restored.ticker, orig.ticker)
        self.assertEqual(restored.price, orig.price)
    def test_missing_required_field(self):
        data = json.loads('{"ticker": "AAPL", "price": 189.50}')
        missing = {"action", "ticker", "price"} - set(data.keys())
        self.assertIn("action", missing)
    def test_extra_fields_tolerated(self):
        data = json.loads('{"action":"buy","ticker":"AAPL","price":190,"custom":"ok"}')
        self.assertEqual(data["action"], "buy")
        self.assertIn("custom", data)
    def test_unicode_in_payload(self):
        raw = json.dumps({"action": "buy", "ticker": "BTC/USDT₮", "price": 65000})
        data = json.loads(raw)
        self.assertIn("₮", data["ticker"])
    def test_failure_rate_statistic(self):
        expected = 1000 * 0.187
        self.assertGreater(expected, 180)
        self.assertLess(expected, 195)
class Test_4_2_WebhookUrlValidation(unittest.TestCase):
    """Incorrect URLs are a common misconfiguration."""
    def _valid(self, url):
        return bool(re.match(r'^https?://[^\s]+\.[^\s]+/?\S*$', url))
    def test_url_validation(self):
        cases = [
            ("https://broker.example.com/webhook", True),
            ("http://broker.example.com/webhook", True),
            ("https://broker.example.com/webhook?token=abc", True),
            ("ftp://broker.example.com/webhook", False),
            ("broker.example.com/webhook", False),
            ("", False),
            ("https://", False),
            ("https:// broker.example.com/webhook", False),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(self._valid(url), expected)
    def test_placeholder_token_detected(self):
        url = "https://broker.example.com/webhook?token=YOUR_TOKEN_HERE"
        self.assertIn("YOUR_TOKEN_HERE", url)
class Test_4_3_NonStandardCharts(unittest.TestCase):
    """Renko / HA cause price discrepancies."""
    def test_ha_close_differs(self):
        _, _, _, ha_c = heikin_ashi_ohlc(99, 101, 100, 105, 98, 103)
        self.assertNotEqual(ha_c, 103)
        self.assertAlmostEqual(ha_c, 101.5)
    def test_ha_price_gap(self):
        real_close, ha_close = 103.0, 101.5
        gap_pct = abs(real_close - ha_close) / real_close * 100
        self.assertGreater(gap_pct, 0)
        self.assertAlmostEqual(gap_pct, 1.456, places=2)
    def test_renko_ignores_small_moves(self):
        prices = [100, 100.5, 101, 100.8, 100.3, 102, 103]
        self.assertEqual(renko_bricks(prices, 1.0), [100, 101, 102, 103])
    def test_renko_brick_timing(self):
        prices = [100, 100.2, 100.8, 101.0, 101.5, 102.0]
        bricks = renko_bricks(prices, 1.0)
        self.assertIn(101, bricks)
        self.assertEqual(prices.index(101.0), 3)
    def test_renko_vs_standard_signal_count(self):
        """Renko filters out small moves, so signal counts diverge."""
        prices = [100, 100.3, 100.7, 101, 100.6, 100.9, 101.5, 102, 101.7, 102.3, 103]
        # Standard: every close > prev close is a signal
        std = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i - 1])
        # Renko: only whole-brick moves count
        bricks = renko_bricks(prices, 1.0)
        renko_up = sum(1 for i in range(1, len(bricks)) if bricks[i] > bricks[i - 1])
        # Renko produces fewer signals because it ignores sub-brick noise
        self.assertNotEqual(std, renko_up)
        self.assertLess(renko_up, std, "Renko should filter more aggressively")
# ═══════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    unittest.main(verbosity=2)
