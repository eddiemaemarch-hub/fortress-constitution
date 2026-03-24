"""Breaker Mid-Execution Tests — The gap all three models flagged.
Tests the actual scenario: fills happening → breaker fires → next signal blocked.
Plus concurrent threading test, Telegram spam prevention, and performance.

Uses temp directory for isolation. No IBKR needed.
"""
import os
import sys
import json
import time
import tempfile
import shutil
import threading
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import auditor

PASS = 0
FAIL = 0

_TEMP_DIR = None
_ORIG_BREAKER_FILE = None
_ORIG_DATA_DIR = None


def setup_temp():
    global _TEMP_DIR, _ORIG_BREAKER_FILE, _ORIG_DATA_DIR
    _TEMP_DIR = tempfile.mkdtemp(prefix="rudy_test_mid_exec_")
    _ORIG_BREAKER_FILE = auditor.BREAKER_STATE_FILE
    _ORIG_DATA_DIR = auditor.DATA_DIR
    auditor.BREAKER_STATE_FILE = os.path.join(_TEMP_DIR, "breaker_state.json")
    auditor.DATA_DIR = _TEMP_DIR


def teardown_temp():
    global _TEMP_DIR
    if _TEMP_DIR and os.path.exists(_TEMP_DIR):
        shutil.rmtree(_TEMP_DIR)
    auditor.BREAKER_STATE_FILE = _ORIG_BREAKER_FILE
    auditor.DATA_DIR = _ORIG_DATA_DIR
    _TEMP_DIR = None


def cleanup():
    auditor.clear_global_halt()
    for sys_id in auditor.SYSTEMS:
        auditor.clear_system_breaker(sys_id)


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        if os.environ.get("VERBOSE"):
            print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} — {detail}")


# ─── TEST 1: Mid-Execution Kill Switch ──────────────────────────────────────

def test_mid_execution_kill():
    """Simulates: 2 BUY signals fill → breaker fires → 3rd signal blocked.
    This is the real-world scenario where you're processing a batch of webhooks
    and the breaker fires mid-batch.
    """
    print("\n=== Test 1: Mid-Execution Kill Switch ===")
    cleanup()

    # Simulate 3 incoming BUY signals
    signals = [
        {"ticker": "MSTR", "system_id": 1, "action": "BUY"},
        {"ticker": "NVDA", "system_id": 13, "action": "BUY"},
        {"ticker": "GME", "system_id": 4, "action": "BUY"},
    ]

    results = []
    for i, signal in enumerate(signals):
        # Check breaker BEFORE each execution (as webhook dispatch does)
        blocked, reason = auditor.is_breaker_active(signal["system_id"])

        if blocked:
            results.append({"signal": signal, "status": "BLOCKED", "reason": reason})
        else:
            results.append({"signal": signal, "status": "FILLED"})

            # After signal 2 fills, Commander fires the breaker
            if i == 1:
                auditor.set_global_halt("Market crash — halt everything")

    check("Signal 1 (MSTR) fills", results[0]["status"] == "FILLED")
    check("Signal 2 (NVDA) fills", results[1]["status"] == "FILLED")
    check("Signal 3 (GME) BLOCKED by mid-execution halt",
          results[2]["status"] == "BLOCKED",
          f"Got: {results[2]['status']}")
    check("Block reason mentions halt",
          "HALT" in results[2].get("reason", "").upper(),
          results[2].get("reason", ""))

    cleanup()


# ─── TEST 2: System-Specific Mid-Execution ──────────────────────────────────

def test_system_specific_mid_execution():
    """Breaker fires on System 1 only. System 13 signals should still fill."""
    print("\n=== Test 2: System-Specific Mid-Execution ===")
    cleanup()

    # Signal 1 fills for System 1
    blocked, _ = auditor.is_breaker_active(1)
    check("System 1 open initially", not blocked)

    # Breaker fires on System 1 only
    auditor.set_system_breaker(1, "System 1 survival breaker hit")

    # System 1 next signal blocked
    blocked, reason = auditor.is_breaker_active(1)
    check("System 1 next signal blocked", blocked)

    # System 13 (breakout) still open
    blocked, _ = auditor.is_breaker_active(13)
    check("System 13 still fills", not blocked)

    # System 4 still open
    blocked, _ = auditor.is_breaker_active(4)
    check("System 4 still fills", not blocked)

    cleanup()


# ─── TEST 3: Concurrent Thread Safety ───────────────────────────────────────

def test_concurrent_breaker_check():
    """Multiple threads checking breaker status simultaneously.
    Must not crash, corrupt state, or give inconsistent results.
    """
    print("\n=== Test 3: Concurrent Thread Safety ===")
    cleanup()

    auditor.set_global_halt("Concurrency test")

    errors = []
    results = []
    lock = threading.Lock()

    def check_breaker(thread_id):
        try:
            for _ in range(100):
                blocked, reason = auditor.is_breaker_active()
                with lock:
                    results.append(blocked)
                if not blocked:
                    with lock:
                        errors.append(f"Thread {thread_id}: got unblocked during halt")
        except Exception as e:
            with lock:
                errors.append(f"Thread {thread_id}: {e}")

    threads = []
    for i in range(5):
        t = threading.Thread(target=check_breaker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=10)

    check("No thread errors", len(errors) == 0, "; ".join(errors[:3]))
    check("All checks returned blocked", all(results),
          f"{sum(1 for r in results if not r)} false negatives out of {len(results)}")
    check("500 total checks completed", len(results) == 500, f"got {len(results)}")

    cleanup()


# ─── TEST 4: Halt + Resume + Halt Rapid Cycle ───────────────────────────────

def test_rapid_halt_resume_cycle():
    """Rapidly halt → resume → halt. State must be consistent at each step."""
    print("\n=== Test 4: Rapid Halt/Resume Cycle ===")
    cleanup()

    for cycle in range(10):
        auditor.set_global_halt(f"Cycle {cycle}")
        blocked, _ = auditor.is_breaker_active()
        check(f"Cycle {cycle}: blocked after halt", blocked)

        auditor.clear_global_halt()
        blocked, _ = auditor.is_breaker_active()
        check(f"Cycle {cycle}: unblocked after resume", not blocked)

    cleanup()


# ─── TEST 5: Performance — 10k Breaker Checks ───────────────────────────────

def test_breaker_check_performance():
    """10,000 is_breaker_active() calls must complete in under 2 seconds.
    This matters because stop_monitor calls it for every position every 5 min.
    """
    print("\n=== Test 5: Performance — 10k Breaker Checks ===")
    cleanup()

    # With halt active (reads file + parses JSON)
    auditor.set_global_halt("Perf test")

    start = time.time()
    for _ in range(10000):
        auditor.is_breaker_active(1)
    elapsed = time.time() - start

    check(f"10k checks in {elapsed:.2f}s (< 2.0s)", elapsed < 2.0,
          f"Took {elapsed:.2f}s — too slow for production")

    # Per-call average
    per_call_us = (elapsed / 10000) * 1_000_000
    check(f"Per-call avg: {per_call_us:.0f}µs (< 200µs)", per_call_us < 200,
          f"Got {per_call_us:.0f}µs")

    cleanup()


# ─── TEST 6: Breaker State File Atomicity ───────────────────────────────────

def test_state_file_written_correctly():
    """After halt, the state file must contain valid JSON with correct fields."""
    print("\n=== Test 6: State File Atomicity ===")
    cleanup()

    auditor.set_global_halt("Atomicity test")
    auditor.set_system_breaker(1, "System 1 test")
    auditor.set_system_breaker(8, "System 8 test")

    # Read file directly
    with open(auditor.BREAKER_STATE_FILE) as f:
        raw = f.read()

    # Must be valid JSON
    try:
        state = json.loads(raw)
        check("State file is valid JSON", True)
    except json.JSONDecodeError as e:
        check("State file is valid JSON", False, str(e))
        return

    check("global_halt is True", state.get("global_halt") is True)
    check("halt_reason set", state.get("halt_reason") == "Atomicity test")
    check("halt_time is ISO format",
          state.get("halt_time") is not None and "T" in state.get("halt_time", ""))
    check("System 1 breaker in file", state.get("systems", {}).get("1", {}).get("breaker_active") is True)
    check("System 8 breaker in file", state.get("systems", {}).get("8", {}).get("breaker_active") is True)
    check("last_updated set", state.get("last_updated") is not None)

    cleanup()


# ─── TEST 7: Webhook Route + Breaker Integration ────────────────────────────

def test_webhook_mid_batch():
    """Simulate a batch of webhooks with breaker firing mid-batch.
    Tests the actual route_tv_signal flow if available.
    """
    print("\n=== Test 7: Webhook Mid-Batch ===")
    cleanup()

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))
        from app import route_tv_signal

        # Batch of 4 signals
        batch = [
            {"ticker": "MSTR", "action": "BUY", "strategy": "MSTR Lottery", "price": 5.00},
            {"ticker": "NVDA", "action": "BUY", "strategy": "Breakout", "price": 10.00},
            {"ticker": "GME", "action": "BUY", "strategy": "Squeeze", "price": 3.00},
            {"ticker": "TSLA", "action": "BUY", "strategy": "Breakout", "price": 8.00},
        ]

        results = []
        for i, signal in enumerate(batch):
            signal["test"] = True  # Paper mode
            signal["secret"] = os.environ.get("WEBHOOK_SECRET", "rudy_tv_secret_2026")
            result = route_tv_signal(signal)
            results.append(result)

            # After signal 2, fire global halt
            if i == 1:
                auditor.set_global_halt("Webhook mid-batch test")

        # Signals 1-2: should route (test_mode or routed)
        check("Signal 1 not blocked",
              results[0].get("status") != "blocked",
              f"Got: {results[0]}")
        check("Signal 2 not blocked",
              results[1].get("status") != "blocked",
              f"Got: {results[1]}")

        # Signals 3-4: should be blocked
        check("Signal 3 blocked by mid-batch halt",
              results[2].get("status") == "blocked",
              f"Got: {results[2]}")
        check("Signal 4 blocked by mid-batch halt",
              results[3].get("status") == "blocked",
              f"Got: {results[3]}")

    except ImportError as e:
        print(f"  SKIP: app.py not importable ({e}) — webhook mid-batch tests skipped")

    cleanup()


# ─── TEST 8: Breaker Doesn't Block SELL Orders ──────────────────────────────

def test_breaker_allows_sells():
    """Circuit breaker must only block BUY orders. SELL/EXIT must always go through.
    This is critical — you must always be able to close positions.
    """
    print("\n=== Test 8: Breaker Allows SELL Orders ===")
    cleanup()

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))
        from app import route_tv_signal

        auditor.set_global_halt("SELL test")

        sell_signal = {
            "ticker": "MSTR", "action": "SELL", "strategy": "MSTR Lottery",
            "price": 15.00, "test": True,
            "secret": os.environ.get("WEBHOOK_SECRET", "rudy_tv_secret_2026"),
        }
        result = route_tv_signal(sell_signal)

        check("SELL not blocked during halt",
              result.get("status") != "blocked",
              f"Got: {result}")

    except ImportError as e:
        print(f"  SKIP: app.py not importable ({e}) — SELL bypass test skipped")

    cleanup()


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--verbose" in sys.argv or "-v" in sys.argv:
        os.environ["VERBOSE"] = "1"

    print("=" * 60)
    print("BREAKER MID-EXECUTION TESTS")
    print("Kill switch during active trading, threading, performance")
    print("=" * 60)

    setup_temp()
    try:
        test_mid_execution_kill()
        test_system_specific_mid_execution()
        test_concurrent_breaker_check()
        test_rapid_halt_resume_cycle()
        test_breaker_check_performance()
        test_state_file_written_correctly()
        test_webhook_mid_batch()
        test_breaker_allows_sells()
    finally:
        teardown_temp()

    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES DETECTED")
    print("=" * 60)

    sys.exit(1 if FAIL > 0 else 0)
