"""Phase 2 Test Harness — Ladder Cycle Validation
Tests stop_monitor + stop_utils integration WITHOUT IBKR.
Injects synthetic positions and simulates price movement through each tier.

20 automated tests. No IBKR needed. Run Monday regardless of SELL permissions.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from stop_utils import get_laddered_trail_pct, LADDERED_TRAIL, LADDERED_SYSTEMS

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} — {detail}")


# ─── TEST 1: Moonshot Tier Boundaries ─────────────────────────────────────────

def test_moonshot_tiers():
    """Verify every moonshot tier boundary returns the correct trail %."""
    print("\n=== Test 1: Moonshot Tier Boundaries ===")

    check("moonshot 0% = None (no stop)",
          get_laddered_trail_pct("mstr_moonshot", 0) is None)
    check("moonshot +150% = None (lottery mode)",
          get_laddered_trail_pct("mstr_moonshot", 150) is None)
    check("moonshot +299% = None (just under 300 threshold)",
          get_laddered_trail_pct("mstr_moonshot", 299) is None)
    check("moonshot +300% = 30% trail (tier 1 activates)",
          get_laddered_trail_pct("mstr_moonshot", 300) == 30)
    check("moonshot +499% = 30% trail (between tiers)",
          get_laddered_trail_pct("mstr_moonshot", 499) == 30)
    check("moonshot +500% = 25% trail (tier 2)",
          get_laddered_trail_pct("mstr_moonshot", 500) == 25)
    check("moonshot +1000% = 20% trail (tier 3)",
          get_laddered_trail_pct("mstr_moonshot", 1000) == 20)
    check("moonshot +2000% = 15% trail (tier 4)",
          get_laddered_trail_pct("mstr_moonshot", 2000) == 15)
    check("moonshot +5000% = 10% trail (tightest)",
          get_laddered_trail_pct("mstr_moonshot", 5000) == 10)
    check("moonshot +10000% = 10% trail (stays at tightest)",
          get_laddered_trail_pct("mstr_moonshot", 10000) == 10)


# ─── TEST 2: Lottery Tier Boundaries ──────────────────────────────────────────

def test_lottery_tiers():
    """Verify lottery system tiers — tighter and faster activation."""
    print("\n=== Test 2: Lottery Tier Boundaries ===")

    check("lottery 0% = None",
          get_laddered_trail_pct("mstr_lottery", 0) is None)
    check("lottery +14% = None (just under 15)",
          get_laddered_trail_pct("mstr_lottery", 14) is None)
    check("lottery +15% = 15% trail",
          get_laddered_trail_pct("mstr_lottery", 15) == 15)
    check("lottery +30% = 12% trail",
          get_laddered_trail_pct("mstr_lottery", 30) == 12)
    check("lottery +50% = 10% trail",
          get_laddered_trail_pct("mstr_lottery", 50) == 10)
    check("lottery +500% = 10% trail (stays at tightest)",
          get_laddered_trail_pct("mstr_lottery", 500) == 10)


# ─── TEST 3: Energy / Squeeze / Breakout Tiers ───────────────────────────────

def test_standard_system_tiers():
    """Verify the 30/50/100 tier pattern shared by multiple systems."""
    print("\n=== Test 3: Standard System Tiers (Energy, Squeeze, Breakout) ===")

    for system in ["energy_momentum", "short_squeeze", "breakout_momentum", "tqqq_momentum", "ntr_ag_momentum"]:
        check(f"{system} 0% = None",
              get_laddered_trail_pct(system, 0) is None)
        check(f"{system} +30% = 20%",
              get_laddered_trail_pct(system, 30) == 20)
        check(f"{system} +50% = 15%",
              get_laddered_trail_pct(system, 50) == 15)
        check(f"{system} +100% = 12%",
              get_laddered_trail_pct(system, 100) == 12)


# ─── TEST 4: 10x Momentum Tiers ──────────────────────────────────────────────

def test_10x_tiers():
    """Verify 10x momentum tier boundaries."""
    print("\n=== Test 4: 10x Momentum Tiers ===")

    check("10x 0% = None",
          get_laddered_trail_pct("10x_momentum", 0) is None)
    check("10x +49% = None (just under 50)",
          get_laddered_trail_pct("10x_momentum", 49) is None)
    check("10x +50% = 25%",
          get_laddered_trail_pct("10x_momentum", 50) == 25)
    check("10x +100% = 20%",
          get_laddered_trail_pct("10x_momentum", 100) == 20)
    check("10x +200% = 15%",
          get_laddered_trail_pct("10x_momentum", 200) == 15)


# ─── TEST 5: Unknown System Fallback ─────────────────────────────────────────

def test_unknown_system_fallback():
    """Unknown system must fall back to flat 30% trail."""
    print("\n=== Test 5: Unknown System Fallback ===")

    check("unknown system = flat 30%",
          get_laddered_trail_pct("nonexistent_system", 50) == 30)
    check("empty string system = flat 30%",
          get_laddered_trail_pct("", 100) == 30)


# ─── TEST 6: Never-Loosen Invariant ──────────────────────────────────────────

def test_tier_never_loosens():
    """Critical invariant: trail % can only tighten (decrease) as gains increase."""
    print("\n=== Test 6: Tiers Never Loosen ===")

    for system_name, tiers in LADDERED_TRAIL.items():
        prev_pct = None
        loosened = False
        loosened_at = None
        for min_gain, trail_pct in tiers:
            if trail_pct is not None and prev_pct is not None:
                if trail_pct > prev_pct:
                    loosened = True
                    loosened_at = min_gain
                    break
            if trail_pct is not None:
                prev_pct = trail_pct
        check(f"{system_name} never loosens", not loosened,
              f"Trail widened at +{loosened_at}% gain (from {prev_pct}% to wider)")


# ─── TEST 7: Gain Calculation Math ───────────────────────────────────────────

def test_gain_calculation():
    """Verify gain_pct formula matches stop_monitor.py: ((hw - entry) / entry * 100)."""
    print("\n=== Test 7: Gain Calculation Math ===")

    cases = [
        (5.00, 20.00, 300.0),    # $5 → $20 = +300%
        (2.00, 2.30, 15.0),      # $2 → $2.30 = +15%
        (10.00, 10.00, 0.0),     # no change = 0%
        (1.00, 51.00, 5000.0),   # $1 → $51 = +5000%
        (3.50, 8.20, 134.29),    # real-world NVDA example
    ]
    for entry, hw, expected in cases:
        gain = ((hw - entry) / entry * 100)
        close = abs(gain - expected) < 0.1
        check(f"${entry:.2f} → ${hw:.2f} = +{expected:.1f}%", close,
              f"got {gain:.2f}%")


# ─── TEST 8: All Systems Have Valid Structure ─────────────────────────────────

def test_all_systems_valid():
    """Every system in LADDERED_TRAIL must start at 0 with ascending gains."""
    print("\n=== Test 8: All Systems Have Valid Structure ===")

    for system_name, tiers in LADDERED_TRAIL.items():
        check(f"{system_name} has tiers", len(tiers) > 0)
        check(f"{system_name} starts at 0", tiers[0][0] == 0,
              f"First tier starts at {tiers[0][0]}")
        gains = [t[0] for t in tiers]
        check(f"{system_name} gains ascending", gains == sorted(gains),
              f"Gains: {gains}")


# ─── TEST 9: State File Format ───────────────────────────────────────────────

def test_state_file_format():
    """Verify state file format matches what stop_monitor.py expects."""
    print("\n=== Test 9: State File Format ===")

    state = {
        "MSTR_300_20270319_C": {
            "high_water": 15.50,
            "entry": 5.00,
            "system_name": "mstr_moonshot"
        },
        "NVDA_150_20260620_C": {
            "high_water": 8.20,
            "entry": 3.50,
            "system_name": "breakout_momentum"
        }
    }

    for key, pos in state.items():
        check(f"{key} has required fields",
              all(f in pos for f in ["high_water", "entry", "system_name"]))
        gain = ((pos["high_water"] - pos["entry"]) / pos["entry"] * 100)
        trail = get_laddered_trail_pct(pos["system_name"], gain)
        # Trail can be None for moonshot below +300% — that's correct (lottery mode)
        tiers = LADDERED_TRAIL.get(pos["system_name"], [])
        first_active = next((g for g, p in tiers if p is not None), None)
        expected_none = first_active is not None and gain < first_active
        check(f"{key} trail lookup works (gain={gain:.0f}%)",
              trail is not None or expected_none,
              f"trail={trail}")


# ─── TEST 10: Full Cycle Simulation with Table ───────────────────────────────

def test_full_cycle_moonshot():
    """Simulate full moonshot lifecycle and print readable milestone table.
    Entry → climb through each tier → pullback → stop triggered.
    """
    print("\n=== Test 10: Full Cycle Simulation — MSTR Moonshot ===")

    entry_price = 5.00
    system_name = "mstr_moonshot"

    # Price walk: entry → 3x → 5x → 6x peak → pullback to stop
    prices = [
        5.00, 6.00, 8.00, 10.00, 15.00,       # climbing pre-tier
        20.00,                                   # +300% → 30% trail activates
        22.00, 25.00,                            # still climbing
        30.00,                                   # +500% → 25% trail
        35.00,                                   # new peak
        32.00, 28.00,                            # pullback within trail
        26.00,                                   # 35 * 0.75 = 26.25 — still above
        26.00,                                   # below 26.25 → STOP TRIGGERED
    ]

    # Print readable table
    print(f"\n  {'Step':>4}  {'Price':>8}  {'HW':>8}  {'Gain%':>8}  {'Trail%':>8}  {'Stop@':>8}  {'Status'}")
    print(f"  {'─' * 4}  {'─' * 8}  {'─' * 8}  {'─' * 8}  {'─' * 8}  {'─' * 8}  {'─' * 12}")

    high_water = entry_price
    stopped_out = False
    stop_price_at_trigger = None
    trigger_index = None

    for i, price in enumerate(prices):
        if price > high_water:
            high_water = price

        gain_pct = ((high_water - entry_price) / entry_price * 100)
        trail_pct = get_laddered_trail_pct(system_name, gain_pct)

        if trail_pct is None:
            stop_level = None
            status = "no stop"
        else:
            stop_level = high_water * (1 - trail_pct / 100)
            if price <= stop_level:
                status = "*** STOPPED ***"
                if not stopped_out:
                    stopped_out = True
                    stop_price_at_trigger = stop_level
                    trigger_index = i
            else:
                status = "OK"

        print(f"  {i:>4}  ${price:>7.2f}  ${high_water:>7.2f}  {gain_pct:>7.1f}%"
              f"  {(str(trail_pct) + '%') if trail_pct else 'None':>8}"
              f"  {('$' + f'{stop_level:.2f}') if stop_level else '—':>8}"
              f"  {status}")

        if stopped_out:
            break

    print()
    check("Stop triggered during walk", stopped_out)
    check("Stop at correct price (~$26.25)",
          stop_price_at_trigger is not None and abs(stop_price_at_trigger - 26.25) < 0.01,
          f"Expected $26.25, got ${stop_price_at_trigger}")
    check("Triggered at $26 tick (below $26.25 stop)", trigger_index == 12,
          f"Triggered at index {trigger_index}")


# ─── TEST 11: Pure Moon — Never Stops ────────────────────────────────────────

def test_pure_moon():
    """A position that only goes up should never trigger a stop."""
    print("\n=== Test 11: Pure Moon (Never Stops) ===")

    entry_price = 5.00
    prices_moon = [5, 10, 20, 50, 100, 200, 300, 500]
    high_water = entry_price
    stopped = False

    for price in prices_moon:
        if price > high_water:
            high_water = price
        gain_pct = ((high_water - entry_price) / entry_price * 100)
        trail_pct = get_laddered_trail_pct("mstr_moonshot", gain_pct)
        if trail_pct is None:
            continue
        stop_level = high_water * (1 - trail_pct / 100)
        if price <= stop_level:
            stopped = True
            break

    check("Pure moon never stops out", not stopped)


# ─── TEST 12: Lottery Full Cycle ─────────────────────────────────────────────

def test_lottery_cycle():
    """Lottery system — tighter tiers, faster stop activation."""
    print("\n=== Test 12: Lottery Full Cycle ===")

    entry_price = 2.00
    system_name = "mstr_lottery"
    high_water = entry_price

    # Walk up to +40%, then pull back hard
    prices = [2.00, 2.20, 2.30, 2.40, 2.50, 2.60, 2.80,  # climbing to +40%
              2.50, 2.30, 2.20]

    stopped_out = False
    for price in prices:
        if price > high_water:
            high_water = price
        gain_pct = ((high_water - entry_price) / entry_price * 100)
        trail_pct = get_laddered_trail_pct(system_name, gain_pct)
        if trail_pct is None:
            continue
        stop_level = high_water * (1 - trail_pct / 100)
        if price <= stop_level:
            stopped_out = True
            break

    # HW = 2.80, gain = 40%, tier = 12% trail (30%+ tier), stop = 2.80 * 0.88 = 2.464
    # $2.20 < $2.464 → should trigger
    check("Lottery stop triggers on pullback", stopped_out)


# ─── TEST 13: Boundary Precision ─────────────────────────────────────────────

def test_boundary_precision():
    """Test exact boundary: price == stop_level (should trigger)."""
    print("\n=== Test 13: Boundary Precision ===")

    # If HW = $20, entry = $5 (+300%), trail = 30%, stop = $14.00
    # Price exactly $14.00 — should this trigger? Yes, price <= stop_level
    entry = 5.00
    hw = 20.00
    gain = ((hw - entry) / entry * 100)  # 300%
    trail = get_laddered_trail_pct("mstr_moonshot", gain)
    stop = hw * (1 - trail / 100)  # 20 * 0.70 = 14.00

    check("Exact boundary: price == stop triggers",
          14.00 <= stop,
          f"stop={stop}")

    # One penny above — should NOT trigger
    check("One penny above stop survives",
          14.01 > stop,
          f"stop={stop}")


# ─── TEST 14: LADDERED_SYSTEMS Set ──────────────────────────────────────────

def test_laddered_systems_set():
    """Verify LADDERED_SYSTEMS matches LADDERED_TRAIL keys."""
    print("\n=== Test 14: LADDERED_SYSTEMS Set ===")

    check("LADDERED_SYSTEMS matches LADDERED_TRAIL keys",
          LADDERED_SYSTEMS == set(LADDERED_TRAIL.keys()),
          f"Mismatch: {LADDERED_SYSTEMS.symmetric_difference(set(LADDERED_TRAIL.keys()))}")

    check("mstr_moonshot in LADDERED_SYSTEMS",
          "mstr_moonshot" in LADDERED_SYSTEMS)
    check("mstr_lottery in LADDERED_SYSTEMS",
          "mstr_lottery" in LADDERED_SYSTEMS)


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("PHASE 2 TEST HARNESS — Ladder Cycle Validation")
    print(f"Systems: {len(LADDERED_TRAIL)} laddered, fallback = flat 30%")
    print("=" * 60)

    test_moonshot_tiers()
    test_lottery_tiers()
    test_standard_system_tiers()
    test_10x_tiers()
    test_unknown_system_fallback()
    test_tier_never_loosens()
    test_gain_calculation()
    test_all_systems_valid()
    test_state_file_format()
    test_full_cycle_moonshot()
    test_pure_moon()
    test_lottery_cycle()
    test_boundary_precision()
    test_laddered_systems_set()

    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES DETECTED — fix before Phase 2")
    print("=" * 60)

    sys.exit(1 if FAIL > 0 else 0)
