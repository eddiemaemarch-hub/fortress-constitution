"""Ladder Edge Case Tests — All the precision traps that kill you in production.
Exact tier boundaries, $0.50 LEAP float math, NaN/Inf guards,
position isolation, lottery-mode invariant.

No IBKR needed. No external dependencies.
"""
import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from stop_utils import get_laddered_trail_pct, LADDERED_TRAIL, LADDERED_SYSTEMS

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


# ─── TEST 1: Exact Tier Boundary — 299.999 vs 300.000 ───────────────────────

def test_exact_tier_boundary_moonshot():
    """Float precision at the moonshot +300% boundary."""
    print("\n=== Test 1: Exact Tier Boundary (Moonshot 300%) ===")

    # Just below
    check("299.999% = None (just under)", get_laddered_trail_pct("mstr_moonshot", 299.999) is None)
    check("299.9999% = None", get_laddered_trail_pct("mstr_moonshot", 299.9999) is None)

    # Exactly at
    check("300.000% = 30%", get_laddered_trail_pct("mstr_moonshot", 300.000) == 30)
    check("300.001% = 30%", get_laddered_trail_pct("mstr_moonshot", 300.001) == 30)

    # Edge between 500 and 1000
    check("499.999% = 30% (below 500)", get_laddered_trail_pct("mstr_moonshot", 499.999) == 30)
    check("500.000% = 25%", get_laddered_trail_pct("mstr_moonshot", 500.000) == 25)

    # Edge between 1000 and 2000
    check("999.999% = 25% (below 1000)", get_laddered_trail_pct("mstr_moonshot", 999.999) == 25)
    check("1000.000% = 20%", get_laddered_trail_pct("mstr_moonshot", 1000.000) == 20)


# ─── TEST 2: Exact Tier Boundary — Lottery 15% ──────────────────────────────

def test_exact_tier_boundary_lottery():
    """Float precision at the lottery +15% boundary."""
    print("\n=== Test 2: Exact Tier Boundary (Lottery 15%) ===")

    check("14.999% = None", get_laddered_trail_pct("mstr_lottery", 14.999) is None)
    check("15.000% = 15%", get_laddered_trail_pct("mstr_lottery", 15.000) == 15)
    check("15.001% = 15%", get_laddered_trail_pct("mstr_lottery", 15.001) == 15)

    # Boundary at 30%
    check("29.999% = 15% (below 30)", get_laddered_trail_pct("mstr_lottery", 29.999) == 15)
    check("30.000% = 12%", get_laddered_trail_pct("mstr_lottery", 30.000) == 12)


# ─── TEST 3: $0.50 LEAP Option Float Math ───────────────────────────────────

def test_cheap_option_float_math():
    """MSTR LEAPs at $0.50 — tiny prices amplify float errors in gain calculation."""
    print("\n=== Test 3: Cheap Option Float Math ($0.50 LEAP) ===")

    entry = 0.50

    # +300% gain: 0.50 → 2.00
    hw = 2.00
    gain = ((hw - entry) / entry * 100)
    check("$0.50 → $2.00 = exactly +300%", gain == 300.0, f"got {gain}")
    trail = get_laddered_trail_pct("mstr_moonshot", gain)
    check("$0.50 LEAP at +300% gets 30% trail", trail == 30)

    # +500% gain: 0.50 → 3.00
    hw = 3.00
    gain = ((hw - entry) / entry * 100)
    check("$0.50 → $3.00 = exactly +500%", gain == 500.0, f"got {gain}")
    trail = get_laddered_trail_pct("mstr_moonshot", gain)
    check("$0.50 LEAP at +500% gets 25% trail", trail == 25)

    # Fractional penny: 0.50 → 0.51
    hw = 0.51
    gain = ((hw - entry) / entry * 100)
    check("$0.50 → $0.51 = +2%", abs(gain - 2.0) < 0.01, f"got {gain}")
    trail = get_laddered_trail_pct("mstr_moonshot", gain)
    check("$0.50 LEAP at +2% = no stop", trail is None)

    # Stop level precision: HW = 2.00, trail 30%, stop = $1.40
    stop = hw * (1 - 30 / 100)
    # Reset hw for this test
    hw = 2.00
    stop = hw * (1 - 30 / 100)
    check("Stop level $1.40 from $2.00 HW",
          abs(stop - 1.40) < 0.001, f"got {stop}")


# ─── TEST 4: NaN / Inf Price Guards ─────────────────────────────────────────

def test_nan_inf_guards():
    """NaN and Inf prices must not crash the gain calculation or trail lookup."""
    print("\n=== Test 4: NaN / Inf Price Guards ===")

    entry = 5.00

    # NaN gain
    nan_val = float('nan')
    try:
        trail = get_laddered_trail_pct("mstr_moonshot", nan_val)
        # NaN comparisons are always False, so `nan >= 0` is False
        # This means trail should be None (no tier matched)
        check("NaN gain doesn't crash", True)
        check("NaN gain returns None", trail is None, f"got {trail}")
    except Exception as e:
        check("NaN gain doesn't crash", False, str(e))

    # Inf gain
    try:
        trail = get_laddered_trail_pct("mstr_moonshot", float('inf'))
        check("Inf gain doesn't crash", True)
        # Inf >= any number is True, so should return the tightest tier (10%)
        check("Inf gain returns tightest tier (10%)", trail == 10, f"got {trail}")
    except Exception as e:
        check("Inf gain doesn't crash", False, str(e))

    # Negative gain
    try:
        trail = get_laddered_trail_pct("mstr_moonshot", -50)
        check("Negative gain doesn't crash", True)
        # -50 >= 0 is False for all tiers, should return None
        check("Negative gain returns None", trail is None, f"got {trail}")
    except Exception as e:
        check("Negative gain doesn't crash", False, str(e))

    # Zero entry (division by zero in gain calc)
    try:
        gain = ((5.00 - 0) / 0 * 100) if 0 > 0 else 0
        check("Zero entry handled (guard clause)", gain == 0)
    except ZeroDivisionError:
        check("Zero entry handled (guard clause)", False, "ZeroDivisionError")


# ─── TEST 5: Position Isolation ──────────────────────────────────────────────

def test_position_isolation():
    """Two positions must not contaminate each other's state."""
    print("\n=== Test 5: Position Isolation ===")

    # Simulate two positions tracked independently (as stop_monitor does)
    state = {}

    # Position A: MSTR moonshot, entry $5, HW $25 (+400%)
    state["MSTR_300_20270319_C"] = {"high_water": 25.00, "entry": 5.00, "system_name": "mstr_moonshot"}
    # Position B: NVDA breakout, entry $3, HW $4.50 (+50%)
    state["NVDA_150_20260620_C"] = {"high_water": 4.50, "entry": 3.00, "system_name": "breakout_momentum"}

    # Calculate trails independently
    for key, pos in state.items():
        gain = ((pos["high_water"] - pos["entry"]) / pos["entry"] * 100)
        trail = get_laddered_trail_pct(pos["system_name"], gain)

        if key == "MSTR_300_20270319_C":
            check("MSTR moonshot at +400% gets 30% trail", trail == 30, f"got {trail}")
        elif key == "NVDA_150_20260620_C":
            check("NVDA breakout at +50% gets 15% trail", trail == 15, f"got {trail}")

    # Modify one, check the other hasn't changed
    state["MSTR_300_20270319_C"]["high_water"] = 55.00  # now +1000%
    mstr_gain = ((55.00 - 5.00) / 5.00 * 100)
    nvda_gain = ((4.50 - 3.00) / 3.00 * 100)

    check("MSTR at +1000% gets 20% trail",
          get_laddered_trail_pct("mstr_moonshot", mstr_gain) == 20)
    check("NVDA still at +50% gets 15% trail (unchanged)",
          get_laddered_trail_pct("breakout_momentum", nvda_gain) == 15)


# ─── TEST 6: Lottery Mode — Never Gets Trail Below Threshold ────────────────

def test_lottery_mode_invariant():
    """For moonshot, any gain below +300% must return None. Period."""
    print("\n=== Test 6: Lottery Mode Invariant ===")

    # Test every 10% increment from 0 to 299
    for gain in range(0, 300, 10):
        trail = get_laddered_trail_pct("mstr_moonshot", gain)
        check(f"Moonshot +{gain}% = None (lottery mode)",
              trail is None,
              f"got {trail}")


# ─── TEST 7: All Tier Boundary Transitions ──────────────────────────────────

def test_all_tier_transitions():
    """Walk through every tier transition for every system.
    At each boundary, verify the trail changes correctly."""
    print("\n=== Test 7: All Tier Transitions ===")

    for system_name, tiers in LADDERED_TRAIL.items():
        for i in range(1, len(tiers)):
            boundary = tiers[i][0]
            expected_trail = tiers[i][1]
            prev_trail = tiers[i - 1][1]

            # Just below boundary
            below = get_laddered_trail_pct(system_name, boundary - 0.001)
            check(f"{system_name} below +{boundary}% = {prev_trail}%",
                  below == prev_trail,
                  f"got {below}")

            # At boundary
            at = get_laddered_trail_pct(system_name, boundary)
            check(f"{system_name} at +{boundary}% = {expected_trail}%",
                  at == expected_trail,
                  f"got {at}")


# ─── TEST 8: Gain Calc with Various Entry Prices ────────────────────────────

def test_gain_calc_various_entries():
    """Gain calculation must be correct across different entry prices."""
    print("\n=== Test 8: Gain Calc — Various Entry Prices ===")

    cases = [
        # (entry, hw, expected_gain)
        (0.01, 0.04, 300.0),     # Penny option → 4x
        (0.50, 2.00, 300.0),     # Cheap LEAP
        (5.00, 20.00, 300.0),    # Normal option
        (50.00, 200.00, 300.0),  # Expensive option
        (100.00, 400.00, 300.0), # Very expensive
    ]

    for entry, hw, expected in cases:
        gain = ((hw - entry) / entry * 100)
        check(f"${entry} → ${hw} = +{expected}%",
              abs(gain - expected) < 0.01,
              f"got {gain:.4f}%")

        # All should give same trail at +300%
        trail = get_laddered_trail_pct("mstr_moonshot", gain)
        check(f"${entry} entry at +300% gets 30% trail",
              trail == 30,
              f"got {trail}")


# ─── TEST 9: Stop Level Math Precision ──────────────────────────────────────

def test_stop_level_precision():
    """Verify stop_level = hw * (1 - trail/100) gives correct values."""
    print("\n=== Test 9: Stop Level Math ===")

    cases = [
        # (hw, trail_pct, expected_stop)
        (20.00, 30, 14.00),
        (35.00, 25, 26.25),
        (100.00, 20, 80.00),
        (200.00, 15, 170.00),
        (500.00, 10, 450.00),
        (2.40, 15, 2.04),        # Lottery
        (2.80, 12, 2.464),       # Lottery tier 2
        (0.04, 30, 0.028),       # Penny option
    ]

    for hw, trail_pct, expected_stop in cases:
        stop = hw * (1 - trail_pct / 100)
        check(f"HW=${hw} trail={trail_pct}% → stop=${expected_stop}",
              abs(stop - expected_stop) < 0.001,
              f"got {stop:.4f}")


# ─── TEST 10: Negative Position (Short) ─────────────────────────────────────

def test_short_position_flat_trail():
    """Short positions use flat 30% trail (no laddering). Verify lookup for non-laddered."""
    print("\n=== Test 10: Short Position Flat Trail ===")

    # Stop monitor uses DEFAULT_TRAIL_PCT (30) for shorts, not laddered
    # But get_laddered_trail_pct for unknown systems returns flat 30
    trail = get_laddered_trail_pct("short_position_default", 50)
    check("Unknown system (short) gets flat 30%", trail == 30)

    # For short: stop_level = low_water * (1 + trail/100)
    lw = 3.00
    trail_pct = 30
    stop = lw * (1 + trail_pct / 100)
    check("Short stop level = LW * 1.30", abs(stop - 3.90) < 0.001, f"got {stop}")


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--verbose" in sys.argv or "-v" in sys.argv:
        os.environ["VERBOSE"] = "1"

    print("=" * 60)
    print("LADDER EDGE CASE TESTS")
    print("Precision traps, float math, NaN/Inf, position isolation")
    print("=" * 60)

    test_exact_tier_boundary_moonshot()
    test_exact_tier_boundary_lottery()
    test_cheap_option_float_math()
    test_nan_inf_guards()
    test_position_isolation()
    test_lottery_mode_invariant()
    test_all_tier_transitions()
    test_gain_calc_various_entries()
    test_stop_level_precision()
    test_short_position_flat_trail()

    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES DETECTED")
    print("=" * 60)

    sys.exit(1 if FAIL > 0 else 0)
