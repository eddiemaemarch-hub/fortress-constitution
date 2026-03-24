"""Random Walk Ladder Tests — The most important new test file.
Mirrors stop_monitor.py logic in a pure-Python LadderSimulator,
then runs invariant checks against all 14 named scenarios + 50 seeded random walks.

If any seed produces a stop loosening or a trail going backwards, it fails
with the exact seed and price sequence for reproduction.

No IBKR needed. No external dependencies.
"""
import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from stop_utils import get_laddered_trail_pct, LADDERED_TRAIL, LADDERED_SYSTEMS
from simulated_market import SCENARIOS, random_walk

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        if os.environ.get("VERBOSE"):
            print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} — {detail}")


# ─── LadderSimulator ────────────────────────────────────────────────────────
# Pure Python mirror of stop_monitor.py logic. No IBKR, no files, no side effects.

class LadderSimulator:
    """Simulates the trailing stop ladder logic from stop_monitor.py.

    Tracks high water mark, gain %, trail %, stop level, and detects:
    - Stop triggered (price <= stop_level when trail active)
    - Trail loosening (trail % going UP instead of staying flat or tightening)
    - HWM regression (high water mark going backwards)
    """

    def __init__(self, system_name, entry_price):
        self.system_name = system_name
        self.entry_price = entry_price
        self.high_water = entry_price
        self.trail_history = []     # [(step, gain_pct, trail_pct)]
        self.tightest_trail = None  # smallest non-None trail seen
        self.stopped_out = False
        self.stop_step = None
        self.stop_price = None
        self.stop_level = None
        self.violations = []        # any invariant violations

    def tick(self, step, price):
        """Process one price tick. Returns dict with current state."""
        if self.stopped_out:
            return None

        # Update HWM
        if price > self.high_water:
            self.high_water = price

        # Gain from entry to HWM (mirrors stop_monitor.py exactly)
        gain_pct = ((self.high_water - self.entry_price) / self.entry_price * 100) if self.entry_price > 0 else 0

        # Get trail %
        trail_pct = get_laddered_trail_pct(self.system_name, gain_pct)

        # Check never-loosen invariant
        if trail_pct is not None:
            if self.tightest_trail is not None and trail_pct > self.tightest_trail:
                self.violations.append(
                    f"Step {step}: Trail LOOSENED from {self.tightest_trail}% to {trail_pct}% "
                    f"(gain={gain_pct:.1f}%, price={price})"
                )
            if self.tightest_trail is None or trail_pct < self.tightest_trail:
                self.tightest_trail = trail_pct

        self.trail_history.append((step, gain_pct, trail_pct))

        # Check stop trigger
        if trail_pct is not None:
            stop_level = self.high_water * (1 - trail_pct / 100)
            if price <= stop_level:
                self.stopped_out = True
                self.stop_step = step
                self.stop_price = price
                self.stop_level = stop_level
                return {
                    "step": step, "price": price, "hw": self.high_water,
                    "gain_pct": gain_pct, "trail_pct": trail_pct,
                    "stop_level": stop_level, "status": "STOPPED"
                }
        else:
            stop_level = None

        return {
            "step": step, "price": price, "hw": self.high_water,
            "gain_pct": gain_pct, "trail_pct": trail_pct,
            "stop_level": stop_level, "status": "OK"
        }

    def run(self, prices):
        """Run through a full price series. Returns list of state dicts."""
        results = []
        for i, price in enumerate(prices):
            result = self.tick(i, price)
            if result:
                results.append(result)
            if self.stopped_out:
                break
        return results

    def print_table(self, results):
        """Print readable milestone table (only shown with --verbose)."""
        print(f"\n  {'Step':>4}  {'Price':>8}  {'HW':>8}  {'Gain%':>8}  {'Trail%':>8}  {'Stop@':>8}  {'Status'}")
        print(f"  {'─' * 4}  {'─' * 8}  {'─' * 8}  {'─' * 8}  {'─' * 8}  {'─' * 8}  {'─' * 10}")
        for r in results:
            trail_str = f"{r['trail_pct']}%" if r['trail_pct'] else "None"
            stop_str = f"${r['stop_level']:.2f}" if r['stop_level'] else "—"
            print(f"  {r['step']:>4}  ${r['price']:>7.2f}  ${r['hw']:>7.2f}  {r['gain_pct']:>7.1f}%"
                  f"  {trail_str:>8}  {stop_str:>8}  {r['status']}")


# ─── TEST 1: Named Scenario Invariants ───────────────────────────────────────

def test_named_scenarios_never_loosen():
    """Run all 14 named scenarios through moonshot ladder. Trail must never loosen."""
    print("\n=== Test 1: Named Scenarios — Never-Loosen Invariant ===")

    for name, prices in SCENARIOS.items():
        sim = LadderSimulator("mstr_moonshot", prices[0])
        sim.run(prices)
        check(f"{name}: no trail loosening",
              len(sim.violations) == 0,
              "; ".join(sim.violations))


# ─── TEST 2: Named Scenario HWM Never Regresses ─────────────────────────────

def test_named_scenarios_hwm_monotonic():
    """High water mark must never decrease across any scenario."""
    print("\n=== Test 2: Named Scenarios — HWM Monotonic ===")

    for name, prices in SCENARIOS.items():
        sim = LadderSimulator("mstr_moonshot", prices[0])
        results = sim.run(prices)
        hwm_series = [r["hw"] for r in results]
        monotonic = all(hwm_series[i] <= hwm_series[i + 1] for i in range(len(hwm_series) - 1))
        check(f"{name}: HWM never decreases", monotonic)


# ─── TEST 3: Gap Down Catches Stop ──────────────────────────────────────────

def test_gap_down_triggers():
    """Gap down that skips past the stop level must still trigger."""
    print("\n=== Test 3: Gap Down Through Stop ===")

    prices = SCENARIOS["gap_down_through_stop"]
    sim = LadderSimulator("mstr_moonshot", prices[0])
    results = sim.run(prices)

    check("Gap down triggers stop", sim.stopped_out,
          "Price gapped below stop but stop didn't trigger")

    if sim.stopped_out:
        check("Stop price below stop level",
              sim.stop_price <= sim.stop_level,
              f"price={sim.stop_price}, stop_level={sim.stop_level}")


# ─── TEST 4: Fake Breakout No Stop ──────────────────────────────────────────

def test_fake_breakout_no_stop():
    """Price reaches +290% then crashes. No stop should fire (moonshot needs +300%)."""
    print("\n=== Test 4: Fake Breakout — No Stop in Lottery Mode ===")

    prices = SCENARIOS["fake_breakout"]
    sim = LadderSimulator("mstr_moonshot", prices[0])
    sim.run(prices)

    check("No stop during fake breakout", not sim.stopped_out,
          f"Stopped at step {sim.stop_step}")


# ─── TEST 5: Choppy Sideways No Stop ────────────────────────────────────────

def test_choppy_sideways_no_stop():
    """Oscillating ±5% around entry. No tier should activate for energy_momentum (+30% first tier)."""
    print("\n=== Test 5: Choppy Sideways — No Stop ===")

    prices = SCENARIOS["choppy_sideways"]
    sim = LadderSimulator("energy_momentum", prices[0])
    results = sim.run(prices)

    # Check no trail ever activated
    any_trail = any(r["trail_pct"] is not None for r in results)
    check("No trail activates in choppy sideways", not any_trail)
    check("No stop in choppy sideways", not sim.stopped_out)


# ─── TEST 6: Whipsaw Trail Stays Active ──────────────────────────────────────

def test_whipsaw_trail_persists():
    """Once trail activates at +30%, it must stay active even if price drops back."""
    print("\n=== Test 6: Whipsaw — Trail Stays Active ===")

    prices = SCENARIOS["whipsaw_at_tier_boundary"]
    sim = LadderSimulator("energy_momentum", prices[0])
    results = sim.run(prices)

    # After tier activates, every subsequent tick should have trail_pct != None
    first_active = None
    for r in results:
        if r["trail_pct"] is not None and first_active is None:
            first_active = r["step"]
        if first_active is not None and r["trail_pct"] is None:
            check("Trail stays active after activation", False,
                  f"Trail went None at step {r['step']} after activating at step {first_active}")
            break
    else:
        if first_active is not None:
            check("Trail stays active after activation", True)
        else:
            check("Trail stays active after activation", False, "Trail never activated")


# ─── TEST 7: Single Candle Multi-Tier Jump ───────────────────────────────────

def test_single_candle_multi_tier():
    """Entry $1 → $21 in one candle (+2000%). Should land on 15% trail, not 30%."""
    print("\n=== Test 7: Single Candle Multi-Tier Jump ===")

    prices = SCENARIOS["single_candle_multi_tier"]
    sim = LadderSimulator("mstr_moonshot", prices[0])
    results = sim.run(prices)

    # Find the first tick with trail active
    active_results = [r for r in results if r["trail_pct"] is not None]
    if active_results:
        first_trail = active_results[0]["trail_pct"]
        check("Multi-tier jump lands on correct tier (15%)",
              first_trail == 15,
              f"Got {first_trail}% — should skip to 15% at +2000%")
    else:
        check("Multi-tier jump activates trail", False, "No trail activated")


# ─── TEST 8: Double Peak HWM Tracking ───────────────────────────────────────

def test_double_peak():
    """Two peaks — HWM must track the higher second peak, not reset to first."""
    print("\n=== Test 8: Double Peak HWM Tracking ===")

    prices = SCENARIOS["double_peak"]
    sim = LadderSimulator("mstr_moonshot", prices[0])
    results = sim.run(prices)

    # After second peak at $35, HWM should be 35
    hwm_at_end = results[-1]["hw"]
    check("HWM tracks second (higher) peak",
          hwm_at_end == 35.00,
          f"HWM={hwm_at_end}, expected 35.00")


# ─── TEST 9: Lottery Quick Spike ─────────────────────────────────────────────

def test_lottery_quick_spike():
    """mstr_lottery: quick +20% spike, then decline should trigger stop."""
    print("\n=== Test 9: Lottery Quick Spike ===")

    prices = SCENARIOS["lottery_quick_spike"]
    sim = LadderSimulator("mstr_lottery", prices[0])
    results = sim.run(prices)

    check("Lottery stop triggers on quick spike decline", sim.stopped_out)

    if sim.stopped_out:
        # HW should be 2.40, +20% tier → 15% trail, stop at 2.04
        check("Lottery stop level correct (~$2.04)",
              abs(sim.stop_level - 2.04) < 0.01,
              f"Got ${sim.stop_level:.4f}")


# ─── TEST 10: 50-Seed Random Walk Battery ───────────────────────────────────

def test_random_walk_battery():
    """Run 50 seeded random walks through every laddered system.
    Invariant: trail must NEVER loosen regardless of price path.
    If any seed fails, print the exact seed for reproduction.
    """
    print("\n=== Test 10: 50-Seed Random Walk Battery ===")

    systems_to_test = ["mstr_moonshot", "mstr_lottery", "energy_momentum",
                       "10x_momentum", "short_squeeze", "breakout_momentum"]
    styles = ["bull", "bear", "volatile"]
    failures = []

    for system in systems_to_test:
        for seed in range(50):
            style = styles[seed % 3]
            prices = random_walk(seed=seed, style=style, entry=5.00, steps=200)
            sim = LadderSimulator(system, prices[0])
            sim.run(prices)

            if sim.violations:
                failures.append(f"{system}/seed={seed}/{style}: {sim.violations[0]}")

    check(f"50-seed battery: 0 violations across {len(systems_to_test)} systems",
          len(failures) == 0,
          f"{len(failures)} failures: " + "; ".join(failures[:3]))

    if failures:
        print("\n  Failing seeds (for reproduction):")
        for f in failures[:10]:
            print(f"    {f}")


# ─── TEST 11: All Systems Against All Scenarios ─────────────────────────────

def test_all_systems_all_scenarios():
    """Cross-product: every system × every scenario. Trail must never loosen."""
    print("\n=== Test 11: All Systems × All Scenarios ===")

    systems = list(LADDERED_TRAIL.keys())
    violations = []

    for system in systems:
        for name, prices in SCENARIOS.items():
            sim = LadderSimulator(system, prices[0])
            sim.run(prices)
            if sim.violations:
                violations.append(f"{system}/{name}: {sim.violations[0]}")

    total = len(systems) * len(SCENARIOS)
    check(f"All systems × all scenarios ({total} combos): no loosening",
          len(violations) == 0,
          f"{len(violations)} violations: " + "; ".join(violations[:3]))


# ─── TEST 12: Full Cycle Summary Print ───────────────────────────────────────

def test_print_full_cycle_summary():
    """Run moonshot through violent_spike and print readable table (verbose only)."""
    print("\n=== Test 12: Full Cycle Table (Violent Spike → Moonshot) ===")

    prices = SCENARIOS["violent_spike"]
    sim = LadderSimulator("mstr_moonshot", prices[0])
    results = sim.run(prices)

    if os.environ.get("VERBOSE"):
        sim.print_table(results)

    check("Violent spike simulation completes", len(results) > 0)
    check("No invariant violations", len(sim.violations) == 0,
          "; ".join(sim.violations))


# ─── TEST 13: Long Flat Then Moonshot ────────────────────────────────────────

def test_long_flat_then_moonshot():
    """30 flat days then exponential rise. State must persist through boring period."""
    print("\n=== Test 13: Long Flat Then Moonshot ===")

    prices = SCENARIOS["long_flat_then_moonshot"]
    sim = LadderSimulator("mstr_moonshot", prices[0])
    results = sim.run(prices)

    # Should eventually activate a trail (price goes well past +300%)
    final_gain = results[-1]["gain_pct"]
    check("Moonshot eventually reaches high gain", final_gain > 300,
          f"Final gain: {final_gain:.0f}%")

    # Trail should be active at the end
    final_trail = results[-1]["trail_pct"]
    check("Trail active at end of moonshot", final_trail is not None,
          f"trail_pct={final_trail}")


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Set VERBOSE for full output when run directly
    if "--verbose" in sys.argv or "-v" in sys.argv:
        os.environ["VERBOSE"] = "1"

    print("=" * 60)
    print("RANDOM WALK LADDER TESTS")
    print(f"Scenarios: {len(SCENARIOS)} named + 50 random seeds × {6} systems")
    print("=" * 60)

    test_named_scenarios_never_loosen()
    test_named_scenarios_hwm_monotonic()
    test_gap_down_triggers()
    test_fake_breakout_no_stop()
    test_choppy_sideways_no_stop()
    test_whipsaw_trail_persists()
    test_single_candle_multi_tier()
    test_double_peak()
    test_lottery_quick_spike()
    test_random_walk_battery()
    test_all_systems_all_scenarios()
    test_print_full_cycle_summary()
    test_long_flat_then_moonshot()

    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES DETECTED")
    print("=" * 60)

    sys.exit(1 if FAIL > 0 else 0)
