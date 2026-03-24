"""Simulated Market Scenarios — 14 named price series for ladder testing.
Each scenario is designed to catch a specific class of bug in stop_monitor logic.

Usage:
    from simulated_market import SCENARIOS, random_walk

    for name, prices in SCENARIOS.items():
        # run through your ladder simulator
        ...

    # Seeded random walks for regression
    prices = random_walk(seed=42, style="bull")
"""
import random
import math


def _slow_grind_up():
    """Steady 2% daily gains for 60 days. Tests that trail never activates prematurely
    on a system that needs +300% before first stop."""
    price = 5.00
    prices = [price]
    for _ in range(60):
        price *= 1.02
        prices.append(round(price, 2))
    return prices


def _violent_spike():
    """Flat at $5 for 10 days, then 10x spike in 3 days, then slow bleed.
    Tests tier jump from None → 30% → 25% in rapid succession."""
    prices = [5.00] * 10
    # Spike: 5 → 15 → 35 → 55
    prices.extend([15.00, 35.00, 55.00])
    # Slow bleed from peak
    price = 55.00
    for _ in range(20):
        price *= 0.97
        prices.append(round(price, 2))
    return prices


def _fake_breakout():
    """Rises to just under tier activation (+290% for moonshot), then crashes.
    Tests that no stop fires when we're still in lottery mode."""
    entry = 5.00
    prices = [entry]
    # Climb to $19.49 (+289.8%) — MUST stay under +300%
    price = entry
    for _ in range(14):
        price += 1.00
        prices.append(round(price, 2))
    prices.append(19.49)  # cap just under +300%
    # Crash back to entry
    price = 19.49
    for _ in range(10):
        price *= 0.90
        prices.append(round(price, 2))
    return prices


def _gap_down_through_stop():
    """Climbs to +400%, then gaps down 40% overnight — below the 30% trail.
    Tests that the stop triggers even though price skipped over the stop level."""
    entry = 5.00
    prices = [entry]
    price = entry
    # Climb to $25 (+400%)
    for _ in range(10):
        price += 2.00
        prices.append(round(price, 2))
    # Gap down 40% (from $25 → $15)
    # HW = 25, trail 30% = stop at $17.50, gap to $15 = below stop
    prices.append(15.00)
    return prices


def _gap_up_overnight():
    """Entry at $5, overnight gap to +350%. Tests tier activation on the first
    price bar after a gap — should immediately activate 30% trail."""
    return [5.00, 5.00, 5.00, 22.50, 23.00, 24.00, 25.00, 20.00, 16.00]


def _choppy_sideways():
    """Oscillates ±5% around entry for 40 bars. Tests that no stop activates
    when gains never reach any tier threshold (for systems with +30% first tier)."""
    entry = 5.00
    prices = []
    for i in range(40):
        offset = 0.05 * math.sin(i * 0.5) * entry
        prices.append(round(entry + offset, 2))
    return prices


def _whipsaw_at_tier_boundary():
    """For energy_momentum: oscillates around +30% gain boundary.
    Price hits +30%, activates 20% trail, drops to just above stop, then rises again.
    Tests that trail stays active (never loosens) even when price goes back up."""
    entry = 5.00
    prices = [entry]
    # Rise to +30% = $6.50
    prices.extend([5.50, 6.00, 6.50])
    # Drop to just above stop: HW=6.50, 20% trail → stop at $5.20
    prices.extend([6.00, 5.50, 5.30])
    # Rise again past +50% = $7.50
    prices.extend([6.00, 7.00, 7.50])
    # Drop — now at +50% tier, 15% trail, stop = 7.50 * 0.85 = $6.375
    prices.extend([7.00, 6.50])
    return prices


def _single_candle_multi_tier():
    """Entry at $1, single candle jumps to $21 (+2000% for moonshot).
    Should activate 15% trail immediately — skipping 30%, 25%, 20% tiers."""
    return [1.00, 1.00, 21.00, 20.00, 18.50, 17.85]  # 17.85 = exactly at 15% trail from $21


def _long_flat_then_moonshot():
    """30 days flat, then exponential rise over 10 days.
    Tests that state persists correctly through a long boring period."""
    prices = [5.00] * 30
    price = 5.00
    for _ in range(10):
        price *= 1.50
        prices.append(round(price, 2))
    return prices


def _lottery_quick_spike():
    """For mstr_lottery: quick 20% spike then gradual decline.
    Tests the tighter lottery tiers (+15% → 15% trail)."""
    entry = 2.00
    prices = [entry, 2.10, 2.20, 2.30, 2.40]  # +20%
    # Decline — HW=2.40, +20% tier → 15% trail, stop = 2.40 * 0.85 = $2.04
    prices.extend([2.30, 2.20, 2.10, 2.05, 2.03])
    return prices


def _double_peak():
    """Two peaks with a valley. Tests that HWM tracks the second (higher) peak,
    not the first one. Valley stays above the trailing stop level so sim survives.
    For moonshot: first peak $20 (+300%) → 30% trail → stop at $14.
    Valley at $15 is above $14, so survives to reach second peak at $35."""
    return [5.00, 10.00, 15.00, 20.00, 17.00, 15.00, 20.00, 25.00, 35.00, 28.00, 27.00]


def random_walk(seed=42, style="bull", entry=5.00, steps=100):
    """Generate a seeded random walk with a directional bias.

    Args:
        seed: Random seed for reproducibility
        style: "bull" (upward bias), "bear" (downward bias), "volatile" (wild swings)
        entry: Starting price
        steps: Number of price ticks

    Returns:
        list[float] of prices
    """
    rng = random.Random(seed)
    price = entry
    prices = [price]

    if style == "bull":
        drift = 0.003   # slight upward bias
        vol = 0.05
    elif style == "bear":
        drift = -0.002
        vol = 0.04
    elif style == "volatile":
        drift = 0.001
        vol = 0.12
    else:
        drift = 0.0
        vol = 0.05

    for _ in range(steps):
        ret = drift + vol * rng.gauss(0, 1)
        price *= (1 + ret)
        price = max(price, 0.01)  # can't go below 1 cent
        prices.append(round(price, 4))

    return prices


# ─── Named Scenarios ─────────────────────────────────────────────────────────

SCENARIOS = {
    "slow_grind_up": _slow_grind_up(),
    "violent_spike": _violent_spike(),
    "fake_breakout": _fake_breakout(),
    "gap_down_through_stop": _gap_down_through_stop(),
    "gap_up_overnight": _gap_up_overnight(),
    "choppy_sideways": _choppy_sideways(),
    "whipsaw_at_tier_boundary": _whipsaw_at_tier_boundary(),
    "single_candle_multi_tier": _single_candle_multi_tier(),
    "long_flat_then_moonshot": _long_flat_then_moonshot(),
    "lottery_quick_spike": _lottery_quick_spike(),
    "double_peak": _double_peak(),
    "random_walk_bull": random_walk(seed=1, style="bull"),
    "random_walk_bear": random_walk(seed=2, style="bear"),
    "random_walk_volatile": random_walk(seed=3, style="volatile"),
}

# Quick sanity: all scenarios have at least 2 prices
assert all(len(v) >= 2 for v in SCENARIOS.values()), "All scenarios must have 2+ prices"
