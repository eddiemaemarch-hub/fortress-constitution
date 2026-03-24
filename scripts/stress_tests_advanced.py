#!/usr/bin/env python3
"""Rudy v2.8+ Advanced Stress Tests — Simulation Only (No Live Trading)

Three stress tests:
1. Flash Crash Liquidity Stress (Gap-and-Trap)
2. Monte Carlo Path Dependency (Bootstrap Shuffle)
3. mNAV Mean Reversion Apocalypse

Results saved to ~/rudy/data/ as JSON files.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta

import numpy as np

DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(DATA_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════
#  SYSTEM PARAMETERS (from trader_v28.py)
# ══════════════════════════════════════════════════════════════

# Account
ACCOUNT_NLV = 7900.0

# Current positions
POSITIONS = {
    "MSTR_PUT": {
        "symbol": "MSTR",
        "type": "Put",
        "strike": 50,
        "expiry": "2028-01-21",
        "cost_basis": 1253.05,
        "contracts": 1,
        "multiplier": 100,
    },
    "SPY_PUT": {
        "symbol": "SPY",
        "type": "Put",
        "strike": 430,
        "expiry": "2027-01-15",
        "cost_basis": 494.99,
        "contracts": 1,
        "multiplier": 100,
    },
}

# Trail stop tiers (peak_gain_pct, trail_pct)
LADDER_TIERS = [
    (10000, 12.0),
    (5000, 20.0),
    (2000, 25.0),
    (1000, 30.0),
    (500, 35.0),
]

# Premium bands for strike engine
PREMIUM_BANDS = {
    "DISCOUNT": {"range": (0, 0.5), "safety_strikes": [100, 200], "safety_wt": 0.30,
                 "spec_strikes": [500, 800], "spec_wt": 0.70, "block": False},
    "DEPRESSED": {"range": (0.5, 1.0), "safety_strikes": [100, 200, 500], "safety_wt": 0.45,
                  "spec_strikes": [800, 1000], "spec_wt": 0.55, "block": False},
    "FAIR": {"range": (1.0, 2.0), "safety_strikes": [100, 200, 500], "safety_wt": 0.35,
             "spec_strikes": [1000, 1500], "spec_wt": 0.65, "block": False},
    "ELEVATED": {"range": (2.0, 2.5), "safety_strikes": [200, 500], "safety_wt": 0.50,
                 "spec_strikes": [800, 1000], "spec_wt": 0.50, "block": False},
    "EUPHORIC": {"range": (2.5, 999), "safety_strikes": [], "safety_wt": 0,
                 "spec_strikes": [], "spec_wt": 0, "block": True},
}

# Risk limits
DAILY_LOSS_LIMIT_PCT = 2.0
CONSECUTIVE_LOSS_LIMIT = 5
PANIC_FLOOR_PCT = -35.0
INITIAL_FLOOR_PCT = 0.65

# mNAV parameters (2026 values from trader)
BTC_HOLDINGS_2026 = 738731
DILUTED_SHARES_2026 = 374_000_000

# Barbell LEAP portfolio structure
BARBELL = {
    "safety_pool": {
        "strikes": [100, 200, 500],
        "description": "Deep ITM safety LEAPs",
        "weight": 0.30,
    },
    "spec_pool": {
        "strikes": [1000, 1500],
        "description": "OTM speculative LEAPs",
        "weight": 0.70,
    },
}

# Dynamic LEAP multiplier bands
def get_leap_multiplier(premium):
    if premium < 0.7:
        return 7.2
    elif premium < 1.0:
        return 6.5
    elif premium <= 1.3:
        return 4.8
    else:
        return 3.3


def get_premium_band(premium):
    for name, band in PREMIUM_BANDS.items():
        lo, hi = band["range"]
        if lo <= premium < hi:
            return name, band
    return "EUPHORIC", PREMIUM_BANDS["EUPHORIC"]


def compute_mstr_premium(mstr_price, btc_price):
    nav_per_share = (btc_price * BTC_HOLDINGS_2026) / DILUTED_SHARES_2026
    if nav_per_share <= 0:
        return 999
    return mstr_price / nav_per_share


def compute_mstr_price_from_premium(premium, btc_price):
    nav_per_share = (btc_price * BTC_HOLDINGS_2026) / DILUTED_SHARES_2026
    return premium * nav_per_share


# ══════════════════════════════════════════════════════════════
#  Black-Scholes for option pricing
# ══════════════════════════════════════════════════════════════

def norm_cdf(x):
    """Standard normal CDF approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def black_scholes_put(S, K, T, r, sigma):
    """Black-Scholes put price. S=spot, K=strike, T=years, r=risk-free, sigma=vol."""
    if T <= 0:
        return max(K - S, 0)
    if S <= 0:
        return K * math.exp(-r * T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


def black_scholes_call(S, K, T, r, sigma):
    """Black-Scholes call price."""
    if T <= 0:
        return max(S - K, 0)
    if S <= 0:
        return 0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)


# ══════════════════════════════════════════════════════════════
#  TEST 1: FLASH CRASH LIQUIDITY STRESS
# ══════════════════════════════════════════════════════════════

def test_flash_crash():
    print("\n" + "=" * 70)
    print("TEST 1: FLASH CRASH LIQUIDITY STRESS (Gap-and-Trap)")
    print("=" * 70)

    # Assume current prices (approximate)
    mstr_current = 350.0
    btc_current = 85000.0
    spy_current = 570.0

    # MSTR implied vol ~100%, SPY ~15%
    mstr_vol = 1.00
    spy_vol = 0.15
    risk_free = 0.045

    # Time to expiry
    today = datetime(2026, 3, 20)
    mstr_put_expiry = datetime(2028, 1, 21)
    spy_put_expiry = datetime(2027, 1, 15)
    mstr_T = (mstr_put_expiry - today).days / 365.25
    spy_T = (spy_put_expiry - today).days / 365.25

    gap_scenarios = [-0.10, -0.15, -0.20, -0.25, -0.30]

    # Simulate an existing MSTR stock position for trail stop analysis
    # Assume entry at $300, current HWM at $380
    entry_price = 300.0
    hwm = 380.0
    stock_gain_from_hwm = ((hwm - entry_price) / entry_price) * 100  # ~26.7%
    leap_mult = get_leap_multiplier(compute_mstr_premium(mstr_current, btc_current))
    peak_leap_gain = stock_gain_from_hwm * leap_mult  # used for tier selection

    results = {
        "test_name": "Flash Crash Liquidity Stress (Gap-and-Trap)",
        "timestamp": datetime.now().isoformat(),
        "baseline": {
            "mstr_price": mstr_current,
            "btc_price": btc_current,
            "spy_price": spy_current,
            "account_nlv": ACCOUNT_NLV,
            "mstr_put_value": round(black_scholes_put(mstr_current, 50, mstr_T, risk_free, mstr_vol), 2),
            "spy_put_value": round(black_scholes_put(spy_current, 430, spy_T, risk_free, spy_vol), 2),
            "assumed_entry": entry_price,
            "assumed_hwm": hwm,
            "peak_leap_gain_pct": round(peak_leap_gain, 1),
        },
        "scenarios": [],
    }

    print(f"\nBaseline: MSTR=${mstr_current} | BTC=${btc_current:,} | Account=${ACCOUNT_NLV:,}")
    print(f"Position: MSTR $50P Jan28 (cost $1253.05) | SPY $430P Jan27 (cost $494.99)")
    print(f"Assumed stock entry: ${entry_price} | HWM: ${hwm} | Peak LEAP gain: {peak_leap_gain:.1f}%")
    print("-" * 70)

    for gap in gap_scenarios:
        gap_pct = abs(gap) * 100
        mstr_gap_price = mstr_current * (1 + gap)
        # Correlated: BTC also drops ~40% of MSTR move, SPY drops ~20% of MSTR move
        btc_gap_price = btc_current * (1 + gap * 0.4)
        spy_gap_price = spy_current * (1 + gap * 0.2)

        # Option values after gap (vol spikes in crash - add vol premium)
        vol_spike = mstr_vol * (1 + abs(gap) * 3)  # vol roughly triples in a -30% gap
        spy_vol_spike = spy_vol * (1 + abs(gap) * 2)

        mstr_put_val = black_scholes_put(mstr_gap_price, 50, mstr_T, risk_free, vol_spike) * 100
        spy_put_val = black_scholes_put(spy_gap_price, 430, spy_T, risk_free, spy_vol_spike) * 100

        # P&L on puts
        mstr_put_pnl = mstr_put_val - POSITIONS["MSTR_PUT"]["cost_basis"]
        spy_put_pnl = spy_put_val - POSITIONS["SPY_PUT"]["cost_basis"]

        # Trail stop analysis
        # Find which tier we're in based on peak_leap_gain
        trail_pct = 0
        tier_name = "NONE"
        for threshold, trail in LADDER_TIERS:
            if peak_leap_gain >= threshold:
                trail_pct = trail
                tier_name = f"+{threshold}%"
                break

        stop_level = hwm * (1 - trail_pct / 100) if trail_pct > 0 else 0
        slippage_from_stop = ((stop_level - mstr_gap_price) / stop_level * 100) if stop_level > 0 else 0

        # Actual fill would be at gap open price (worse than stop)
        gap_through = mstr_gap_price < stop_level if stop_level > 0 else False
        actual_fill = mstr_gap_price if gap_through else stop_level

        # Premium compression alert check
        new_premium = compute_mstr_premium(mstr_gap_price, btc_gap_price)
        old_premium = compute_mstr_premium(mstr_current, btc_current)
        prem_drop_pct = ((old_premium - new_premium) / old_premium * 100) if old_premium > 0 else 0
        compression_alert = prem_drop_pct > 15

        # Strike adjustment engine
        band_name, band_info = get_premium_band(new_premium)
        roll_triggered = band_name != get_premium_band(old_premium)[0]

        # LEAP gain at gap price
        stock_gain_gap = ((mstr_gap_price - entry_price) / entry_price) * 100
        leap_gain_gap = stock_gain_gap * get_leap_multiplier(new_premium)

        # Panic floor check
        panic_floor_hit = leap_gain_gap <= PANIC_FLOOR_PCT
        initial_floor_hit = mstr_gap_price < entry_price * INITIAL_FLOOR_PCT

        # Net portfolio impact
        total_position_value = mstr_put_val + spy_put_val
        total_cost = POSITIONS["MSTR_PUT"]["cost_basis"] + POSITIONS["SPY_PUT"]["cost_basis"]
        net_portfolio_pnl = (mstr_put_pnl + spy_put_pnl)
        portfolio_impact_pct = (net_portfolio_pnl / ACCOUNT_NLV) * 100

        scenario = {
            "gap_pct": f"-{gap_pct:.0f}%",
            "mstr_gap_price": round(mstr_gap_price, 2),
            "btc_gap_price": round(btc_gap_price, 0),
            "spy_gap_price": round(spy_gap_price, 2),
            "mstr_put_value": round(mstr_put_val, 2),
            "spy_put_value": round(spy_put_val, 2),
            "mstr_put_pnl": round(mstr_put_pnl, 2),
            "spy_put_pnl": round(spy_put_pnl, 2),
            "trail_stop": {
                "tier": tier_name,
                "trail_pct": trail_pct,
                "stop_level": round(stop_level, 2),
                "gap_through": gap_through,
                "slippage_pct": round(slippage_from_stop, 2) if gap_through else 0,
                "actual_fill": round(actual_fill, 2),
                "damage_vs_stop": round(stop_level - actual_fill, 2) if gap_through else 0,
            },
            "premium_analysis": {
                "new_premium": round(new_premium, 3),
                "old_premium": round(old_premium, 3),
                "premium_drop_pct": round(prem_drop_pct, 1),
                "compression_alert_fires": compression_alert,
                "new_band": band_name,
                "roll_recommended": roll_triggered,
            },
            "leap_impact": {
                "stock_gain_pct": round(stock_gain_gap, 1),
                "leap_gain_pct": round(leap_gain_gap, 1),
                "panic_floor_hit": panic_floor_hit,
                "initial_floor_hit": initial_floor_hit,
                "exit_trigger": "PANIC_FLOOR" if panic_floor_hit else ("INITIAL_FLOOR" if initial_floor_hit else "NONE"),
            },
            "portfolio_impact": {
                "total_position_value": round(total_position_value, 2),
                "net_pnl": round(net_portfolio_pnl, 2),
                "portfolio_impact_pct": round(portfolio_impact_pct, 1),
                "account_value_after": round(ACCOUNT_NLV + net_portfolio_pnl, 2),
                "survival": ACCOUNT_NLV + net_portfolio_pnl > 0,
            },
            "verdict": "PASS" if (not gap_through or slippage_from_stop < 10) else "FAIL",
        }

        # Determine overall scenario verdict
        if gap_through and slippage_from_stop > 15:
            scenario["verdict"] = "FAIL"
        elif gap_through and slippage_from_stop > 5:
            scenario["verdict"] = "CONDITIONAL PASS"
        elif panic_floor_hit:
            scenario["verdict"] = "CONDITIONAL PASS"
        else:
            scenario["verdict"] = "PASS"

        results["scenarios"].append(scenario)

        # Print summary
        status = scenario["verdict"]
        print(f"\nGap: {gap_pct:.0f}% → MSTR=${mstr_gap_price:.0f} | Premium={new_premium:.2f}x | Band={band_name}")
        print(f"  Trail: tier={tier_name} stop=${stop_level:.0f} | Gap-through={'YES' if gap_through else 'NO'} | Slip={slippage_from_stop:.1f}%")
        print(f"  LEAP impact: stock={stock_gain_gap:.1f}% leap={leap_gain_gap:.1f}% | Floor={'HIT' if panic_floor_hit or initial_floor_hit else 'OK'}")
        print(f"  Puts: MSTR P&L=${mstr_put_pnl:.0f} SPY P&L=${spy_put_pnl:.0f}")
        print(f"  Portfolio: ${ACCOUNT_NLV + net_portfolio_pnl:.0f} ({portfolio_impact_pct:+.1f}%) → [{status}]")

    # Key question answer
    graceful = all(s["trail_stop"]["slippage_pct"] < 15 for s in results["scenarios"])
    fails = sum(1 for s in results["scenarios"] if s["verdict"] == "FAIL")

    results["summary"] = {
        "graceful_handling_15pct_gap": graceful,
        "scenarios_passed": sum(1 for s in results["scenarios"] if s["verdict"] == "PASS"),
        "scenarios_conditional": sum(1 for s in results["scenarios"] if s["verdict"] == "CONDITIONAL PASS"),
        "scenarios_failed": fails,
        "critical_gap_threshold": next(
            (s["gap_pct"] for s in results["scenarios"] if s["verdict"] == "FAIL"), "NONE"
        ),
        "worst_portfolio_impact_pct": min(s["portfolio_impact"]["portfolio_impact_pct"] for s in results["scenarios"]),
        "overall_verdict": "PASS" if fails == 0 else ("CONDITIONAL PASS" if fails <= 1 else "FAIL"),
    }

    print(f"\n{'─' * 70}")
    print(f"SUMMARY: {results['summary']['overall_verdict']}")
    print(f"  Graceful at -15%: {'YES' if graceful else 'NO'}")
    print(f"  Pass/Conditional/Fail: {results['summary']['scenarios_passed']}/{results['summary']['scenarios_conditional']}/{fails}")
    print(f"  Worst portfolio impact: {results['summary']['worst_portfolio_impact_pct']:.1f}%")

    # Save
    path = os.path.join(DATA_DIR, "flash_crash_stress.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {path}")

    return results


# ══════════════════════════════════════════════════════════════
#  TEST 2: MONTE CARLO PATH DEPENDENCY
# ══════════════════════════════════════════════════════════════

def test_monte_carlo():
    print("\n" + "=" * 70)
    print("TEST 2: MONTE CARLO PATH DEPENDENCY (Bootstrap Shuffle)")
    print("=" * 70)

    np.random.seed(42)
    N_SIMS = 5000
    N_WEEKS = 260  # 5 years

    # Generate realistic MSTR weekly returns
    # Known stats: ~80% annual vol, ~50% annual return, fat tails kurtosis ~5
    annual_vol = 0.80
    annual_return = 0.50
    weekly_vol = annual_vol / np.sqrt(52)
    weekly_mu = (1 + annual_return) ** (1 / 52) - 1

    # Use Student-t for fat tails (df ~5 gives kurtosis ~5 for standardized)
    df_t = 5
    # Generate base returns from t-distribution, scale to match moments
    raw_returns = np.random.standard_t(df_t, size=N_WEEKS)
    # Scale: t(df) has variance df/(df-2), so scale to get weekly_vol
    t_scale = weekly_vol / np.sqrt(df_t / (df_t - 2))
    base_weekly_returns = raw_returns * t_scale + weekly_mu

    print(f"\nGenerated {N_WEEKS} weekly returns | mu={weekly_mu*100:.2f}%/wk | vol={weekly_vol*100:.2f}%/wk")
    print(f"Empirical stats: mean={np.mean(base_weekly_returns)*100:.2f}% | std={np.std(base_weekly_returns)*100:.2f}%")
    print(f"  kurtosis={float(kurtosis_calc(base_weekly_returns)):.2f} | skew={float(skew_calc(base_weekly_returns)):.2f}")
    print(f"Running {N_SIMS} bootstrap simulations...")

    # Strategy parameters
    sma_200w_period = 200

    results_paths = []
    max_drawdowns = []
    final_returns = []
    daily_loss_triggers = 0
    consecutive_loss_triggers = 0
    dip_reclaim_fires = []

    for sim in range(N_SIMS):
        # Shuffle the weekly returns (bootstrap)
        shuffled = np.random.choice(base_weekly_returns, size=N_WEEKS, replace=True)

        # Build price path from $100 start
        prices = [100.0]
        for r in shuffled:
            prices.append(prices[-1] * (1 + r))
        prices = np.array(prices)

        # Track max drawdown
        peak = np.maximum.accumulate(prices)
        drawdowns = (peak - prices) / peak * 100
        max_dd = float(np.max(drawdowns))
        max_drawdowns.append(max_dd)
        final_returns.append((prices[-1] / prices[0] - 1) * 100)

        # Simulate strategy signals
        # Track 200W SMA dip+reclaim
        dip_reclaim_count = 0
        armed = False
        dipped = False
        green_weeks = 0

        for w in range(sma_200w_period, len(prices)):
            sma200 = np.mean(prices[w - sma_200w_period:w])
            current = prices[w]
            prev = prices[w - 1]

            if current < sma200:
                dipped = True
                green_weeks = 0
                armed = False
            elif dipped and current > sma200 and current > prev:
                green_weeks += 1
                if green_weeks >= 2 and not armed:
                    armed = True
                    dip_reclaim_count += 1

        dip_reclaim_fires.append(dip_reclaim_count)

        # Simulate daily loss limit triggers
        # Convert weekly to approximate daily: each week has 5 days
        daily_prices = []
        for w in range(1, len(prices)):
            for d in range(5):
                frac = d / 5.0
                daily_prices.append(prices[w - 1] + frac * (prices[w] - prices[w - 1]))

        # Check how many days would have >2% intraday loss
        daily_loss_count = 0
        consec_losses = 0
        max_consec = 0
        prev_val = daily_prices[0] if daily_prices else 100

        for i in range(5, len(daily_prices), 5):  # Weekly evaluation
            week_return = (daily_prices[i] / daily_prices[i - 5] - 1)
            if week_return < -0.02:
                daily_loss_count += 1
            if week_return < 0:
                consec_losses += 1
                max_consec = max(max_consec, consec_losses)
            else:
                consec_losses = 0

        if daily_loss_count > 0:
            daily_loss_triggers += 1
        if max_consec >= CONSECUTIVE_LOSS_LIMIT:
            consecutive_loss_triggers += 1

        results_paths.append({
            "max_dd": max_dd,
            "final_return": (prices[-1] / prices[0] - 1) * 100,
            "dip_reclaim_fires": dip_reclaim_count,
        })

    max_drawdowns = np.array(max_drawdowns)
    final_returns = np.array(final_returns)

    # Percentiles
    dd_percentiles = {
        "p5": round(float(np.percentile(max_drawdowns, 5)), 2),
        "p25": round(float(np.percentile(max_drawdowns, 25)), 2),
        "p50": round(float(np.percentile(max_drawdowns, 50)), 2),
        "p75": round(float(np.percentile(max_drawdowns, 75)), 2),
        "p95": round(float(np.percentile(max_drawdowns, 95)), 2),
        "p99": round(float(np.percentile(max_drawdowns, 99)), 2),
    }

    ret_percentiles = {
        "p5": round(float(np.percentile(final_returns, 5)), 2),
        "p25": round(float(np.percentile(final_returns, 25)), 2),
        "p50": round(float(np.percentile(final_returns, 50)), 2),
        "p75": round(float(np.percentile(final_returns, 75)), 2),
        "p95": round(float(np.percentile(final_returns, 95)), 2),
    }

    exceed_40_dd = float(np.mean(max_drawdowns > 40) * 100)
    exceed_50_dd = float(np.mean(max_drawdowns > 50) * 100)
    exceed_60_dd = float(np.mean(max_drawdowns > 60) * 100)
    daily_loss_pct = daily_loss_triggers / N_SIMS * 100
    consec_loss_pct = consecutive_loss_triggers / N_SIMS * 100

    # 70/30 barbell survival: does the position sizing hold for 95% of paths?
    # The barbell survives if max DD < 70% (safety pool provides floor)
    barbell_survives_95 = float(np.percentile(max_drawdowns, 95)) < 70
    barbell_survives_99 = float(np.percentile(max_drawdowns, 99)) < 70

    results = {
        "test_name": "Monte Carlo Path Dependency (Bootstrap Shuffle)",
        "timestamp": datetime.now().isoformat(),
        "parameters": {
            "n_simulations": N_SIMS,
            "n_weeks": N_WEEKS,
            "annual_vol": annual_vol,
            "annual_return": annual_return,
            "weekly_vol": round(weekly_vol, 4),
            "weekly_mu": round(weekly_mu, 4),
            "fat_tail_df": df_t,
        },
        "max_drawdown_percentiles": dd_percentiles,
        "final_return_percentiles": ret_percentiles,
        "drawdown_exceedance": {
            "exceed_40pct": round(exceed_40_dd, 2),
            "exceed_50pct": round(exceed_50_dd, 2),
            "exceed_60pct": round(exceed_60_dd, 2),
        },
        "risk_limit_triggers": {
            "daily_2pct_loss_trigger_pct": round(daily_loss_pct, 2),
            "consecutive_5_loss_trigger_pct": round(consec_loss_pct, 2),
        },
        "dip_reclaim_stats": {
            "mean_fires_per_path": round(float(np.mean(dip_reclaim_fires)), 2),
            "median_fires": round(float(np.median(dip_reclaim_fires)), 1),
            "paths_with_zero_fires_pct": round(float(np.mean(np.array(dip_reclaim_fires) == 0) * 100), 2),
        },
        "barbell_analysis": {
            "survives_95th_percentile": barbell_survives_95,
            "survives_99th_percentile": barbell_survives_99,
            "p95_max_dd": dd_percentiles["p95"],
            "p99_max_dd": dd_percentiles["p99"],
            "positive_return_pct": round(float(np.mean(final_returns > 0) * 100), 2),
        },
        "overall_verdict": "PASS" if (exceed_40_dd < 30 and barbell_survives_95) else
                          ("CONDITIONAL PASS" if exceed_40_dd < 50 else "FAIL"),
    }

    print(f"\nMax Drawdown Distribution:")
    for k, v in dd_percentiles.items():
        print(f"  {k}: {v:.1f}%")
    print(f"\nPaths exceeding 40% DD: {exceed_40_dd:.1f}%")
    print(f"Paths exceeding 50% DD: {exceed_50_dd:.1f}%")
    print(f"Paths exceeding 60% DD: {exceed_60_dd:.1f}%")
    print(f"\nFinal Return Distribution:")
    for k, v in ret_percentiles.items():
        print(f"  {k}: {v:.1f}%")
    print(f"\nRisk Triggers:")
    print(f"  Daily 2% loss trigger: {daily_loss_pct:.1f}% of paths")
    print(f"  5-consecutive-loss shutdown: {consec_loss_pct:.1f}% of paths")
    print(f"\n200W Dip+Reclaim Signals:")
    print(f"  Mean fires per path: {np.mean(dip_reclaim_fires):.1f}")
    print(f"  Paths with zero fires: {np.mean(np.array(dip_reclaim_fires) == 0) * 100:.1f}%")
    print(f"\n70/30 Barbell Survival:")
    print(f"  Survives 95th percentile: {'YES' if barbell_survives_95 else 'NO'} (p95 DD={dd_percentiles['p95']:.1f}%)")
    print(f"  Survives 99th percentile: {'YES' if barbell_survives_99 else 'NO'} (p99 DD={dd_percentiles['p99']:.1f}%)")
    print(f"\nPositive return paths: {np.mean(final_returns > 0) * 100:.1f}%")
    print(f"\n{'─' * 70}")
    print(f"OVERALL VERDICT: {results['overall_verdict']}")

    path = os.path.join(DATA_DIR, "monte_carlo_stress.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {path}")

    return results


def kurtosis_calc(x):
    """Excess kurtosis."""
    n = len(x)
    m = np.mean(x)
    s = np.std(x, ddof=0)
    if s == 0:
        return 0
    return np.mean(((x - m) / s) ** 4) - 3


def skew_calc(x):
    """Skewness."""
    m = np.mean(x)
    s = np.std(x, ddof=0)
    if s == 0:
        return 0
    return np.mean(((x - m) / s) ** 3)


# ══════════════════════════════════════════════════════════════
#  TEST 3: mNAV MEAN REVERSION APOCALYPSE
# ══════════════════════════════════════════════════════════════

def test_mnav_apocalypse():
    print("\n" + "=" * 70)
    print("TEST 3: mNAV MEAN REVERSION APOCALYPSE")
    print("=" * 70)

    btc_flat = 70000.0
    nav_per_share = (btc_flat * BTC_HOLDINGS_2026) / DILUTED_SHARES_2026
    print(f"\nBTC fixed at ${btc_flat:,} | NAV/share = ${nav_per_share:.2f}")

    # Current premium level (starting point)
    starting_premium = 2.5
    starting_mstr = starting_premium * nav_per_share

    premium_scenarios = [2.0, 1.5, 1.0, 0.5, 0.25]
    decay_timelines = [30, 60, 90]  # days

    # LEAP portfolio (hypothetical, based on barbell structure)
    # Assume ~$5000 total LEAP portfolio, 30% safety / 70% spec
    leap_portfolio_value = 5000.0

    # Safety pool LEAPs: $100, $200, $500 strike calls, Jan 2028
    # Spec pool LEAPs: $1000, $1500 strike calls, Jan 2028
    safety_strikes = [100, 200, 500]
    spec_strikes = [1000, 1500]

    mstr_vol = 1.00
    risk_free = 0.045
    T_base = 1.84  # ~22 months to Jan 2028

    results = {
        "test_name": "mNAV Mean Reversion Apocalypse",
        "timestamp": datetime.now().isoformat(),
        "parameters": {
            "btc_price": btc_flat,
            "nav_per_share": round(nav_per_share, 2),
            "starting_premium": starting_premium,
            "starting_mstr": round(starting_mstr, 2),
            "leap_portfolio": leap_portfolio_value,
            "safety_strikes": safety_strikes,
            "spec_strikes": spec_strikes,
        },
        "scenarios": [],
        "timeline_decay": [],
    }

    print(f"Starting MSTR=${starting_mstr:.2f} at {starting_premium}x premium")
    print(f"LEAP portfolio: ${leap_portfolio_value:,.0f} (30% safety / 70% spec)")
    print("-" * 70)

    # Scenario analysis at each premium level
    zero_intrinsic_level = None

    for target_premium in premium_scenarios:
        mstr_price = target_premium * nav_per_share
        premium_drop_pct = ((starting_premium - target_premium) / starting_premium) * 100

        # Price LEAP calls at this MSTR level
        safety_values = {}
        safety_total = 0
        for strike in safety_strikes:
            val = black_scholes_call(mstr_price, strike, T_base, risk_free, mstr_vol) * 100
            intrinsic = max(mstr_price - strike, 0) * 100
            safety_values[str(strike)] = {
                "bs_value": round(val, 2),
                "intrinsic": round(intrinsic, 2),
                "has_intrinsic": intrinsic > 0,
            }
            safety_total += val

        spec_values = {}
        spec_total = 0
        for strike in spec_strikes:
            val = black_scholes_call(mstr_price, strike, T_base, risk_free, mstr_vol) * 100
            intrinsic = max(mstr_price - strike, 0) * 100
            spec_values[str(strike)] = {
                "bs_value": round(val, 2),
                "intrinsic": round(intrinsic, 2),
                "has_intrinsic": intrinsic > 0,
            }
            spec_total += val

        # Reference values at starting premium
        safety_start = sum(
            black_scholes_call(starting_mstr, s, T_base, risk_free, mstr_vol) * 100
            for s in safety_strikes
        )
        spec_start = sum(
            black_scholes_call(starting_mstr, s, T_base, risk_free, mstr_vol) * 100
            for s in spec_strikes
        )

        safety_loss_pct = ((safety_start - safety_total) / safety_start * 100) if safety_start > 0 else 100
        spec_loss_pct = ((spec_start - spec_total) / spec_start * 100) if spec_start > 0 else 100

        # Weighted portfolio impact
        portfolio_loss_pct = safety_loss_pct * 0.30 + spec_loss_pct * 0.70

        # Premium compression alert
        compression_fires = premium_drop_pct > 15

        # Strike adjustment engine
        band_name, band_info = get_premium_band(target_premium)
        old_band, _ = get_premium_band(starting_premium)
        roll_triggered = band_name != old_band

        # Constitution v50.0 strike roll logic
        # Roll triggers when band changes AND spec strikes move
        constitution_roll = roll_triggered and band_info["spec_strikes"] != PREMIUM_BANDS.get(old_band, {}).get("spec_strikes", [])

        # Check if all LEAPs lose intrinsic value
        all_leaps_zero_intrinsic = all(
            max(mstr_price - s, 0) == 0 for s in safety_strikes + spec_strikes
        )

        # Safety net failure: when safety pool LEAPs lose >90% of value
        safety_net_failed = safety_loss_pct > 90

        if all_leaps_zero_intrinsic and zero_intrinsic_level is None:
            zero_intrinsic_level = target_premium

        scenario = {
            "premium": target_premium,
            "mstr_price": round(mstr_price, 2),
            "premium_drop_pct": round(premium_drop_pct, 1),
            "safety_pool": {
                "strikes": safety_values,
                "total_value": round(safety_total, 2),
                "loss_from_start_pct": round(safety_loss_pct, 1),
            },
            "spec_pool": {
                "strikes": spec_values,
                "total_value": round(spec_total, 2),
                "loss_from_start_pct": round(spec_loss_pct, 1),
            },
            "barbell_impact": {
                "weighted_loss_pct": round(portfolio_loss_pct, 1),
                "safety_pnl": round(safety_total - safety_start, 2),
                "spec_pnl": round(spec_total - spec_start, 2),
            },
            "alerts": {
                "compression_alert_fires": compression_fires,
                "band_shift": f"{old_band} -> {band_name}",
                "roll_recommended": roll_triggered,
                "constitution_roll": constitution_roll,
                "recommended_strikes": {
                    "safety": band_info["safety_strikes"],
                    "spec": band_info["spec_strikes"],
                },
            },
            "failure_checks": {
                "all_leaps_zero_intrinsic": all_leaps_zero_intrinsic,
                "safety_net_failed": safety_net_failed,
                "entry_blocked": band_info["block"],
            },
            "verdict": "PASS" if not safety_net_failed else
                      ("CONDITIONAL PASS" if not all_leaps_zero_intrinsic else "FAIL"),
        }
        results["scenarios"].append(scenario)

        print(f"\nPremium {target_premium}x → MSTR=${mstr_price:.2f} (drop={premium_drop_pct:.0f}%) | Band={band_name}")
        print(f"  Safety pool: ${safety_total:.0f} (loss {safety_loss_pct:.1f}%)")
        print(f"  Spec pool:   ${spec_total:.0f} (loss {spec_loss_pct:.1f}%)")
        print(f"  Barbell weighted loss: {portfolio_loss_pct:.1f}%")
        print(f"  Alerts: compression={'YES' if compression_fires else 'NO'} | roll={'YES' if roll_triggered else 'NO'} | blocked={'YES' if band_info['block'] else 'NO'}")
        print(f"  All LEAPs zero intrinsic: {'YES' if all_leaps_zero_intrinsic else 'NO'} | Safety net failed: {'YES' if safety_net_failed else 'NO'}")
        print(f"  → [{scenario['verdict']}]")

    # Timeline decay analysis
    print(f"\n{'─' * 70}")
    print("TIMELINE ANALYSIS: Premium decay over time")

    for days in decay_timelines:
        T_remaining = T_base - days / 365.25
        if T_remaining <= 0:
            T_remaining = 0.01

        timeline_result = {
            "decay_days": days,
            "T_remaining_years": round(T_remaining, 3),
            "scenarios": [],
        }

        for target_premium in [2.0, 1.0, 0.5]:
            mstr_price = target_premium * nav_per_share

            # With time decay, vol stays high but theta eats
            safety_val = sum(
                black_scholes_call(mstr_price, s, T_remaining, risk_free, mstr_vol) * 100
                for s in safety_strikes
            )
            spec_val = sum(
                black_scholes_call(mstr_price, s, T_remaining, risk_free, mstr_vol) * 100
                for s in spec_strikes
            )

            safety_start_t = sum(
                black_scholes_call(starting_mstr, s, T_base, risk_free, mstr_vol) * 100
                for s in safety_strikes
            )
            spec_start_t = sum(
                black_scholes_call(starting_mstr, s, T_base, risk_free, mstr_vol) * 100
                for s in spec_strikes
            )

            total_loss = ((safety_start_t + spec_start_t) - (safety_val + spec_val)) / (safety_start_t + spec_start_t) * 100

            timeline_result["scenarios"].append({
                "premium": target_premium,
                "mstr_price": round(mstr_price, 2),
                "safety_value": round(safety_val, 2),
                "spec_value": round(spec_val, 2),
                "total_loss_pct": round(total_loss, 1),
            })

            print(f"  {days}d decay | {target_premium}x | MSTR=${mstr_price:.0f} | "
                  f"Safety=${safety_val:.0f} Spec=${spec_val:.0f} | Loss={total_loss:.1f}%")

        results["timeline_decay"].append(timeline_result)

    # Summary
    fails = sum(1 for s in results["scenarios"] if s["verdict"] == "FAIL")
    safety_fail_level = next(
        (s["premium"] for s in results["scenarios"] if s["failure_checks"]["safety_net_failed"]),
        None
    )

    results["summary"] = {
        "zero_intrinsic_premium": zero_intrinsic_level,
        "safety_net_fail_premium": safety_fail_level,
        "compression_alert_fires_at": next(
            (s["premium"] for s in results["scenarios"] if s["alerts"]["compression_alert_fires"]),
            None
        ),
        "scenarios_passed": sum(1 for s in results["scenarios"] if s["verdict"] == "PASS"),
        "scenarios_conditional": sum(1 for s in results["scenarios"] if s["verdict"] == "CONDITIONAL PASS"),
        "scenarios_failed": fails,
        "critical_finding": (
            f"Safety net fails at {safety_fail_level}x premium" if safety_fail_level
            else "Safety net holds across all scenarios"
        ),
        "overall_verdict": "PASS" if fails == 0 else ("CONDITIONAL PASS" if fails <= 1 else "FAIL"),
    }

    print(f"\n{'─' * 70}")
    print(f"SUMMARY: {results['summary']['overall_verdict']}")
    print(f"  Safety net fail level: {safety_fail_level}x" if safety_fail_level else "  Safety net holds")
    print(f"  All LEAPs zero intrinsic at: {zero_intrinsic_level}x" if zero_intrinsic_level else "  LEAPs retain value")
    print(f"  Pass/Conditional/Fail: {results['summary']['scenarios_passed']}/{results['summary']['scenarios_conditional']}/{fails}")

    path = os.path.join(DATA_DIR, "mnav_apocalypse_stress.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {path}")

    return results


# ══════════════════════════════════════════════════════════════
#  MAIN — Run all tests
# ══════════════════════════════════════════════════════════════

def main():
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  RUDY v2.8+ ADVANCED STRESS TESTS — SIMULATION ONLY             ║")
    print("║  Research mode — no live trading code modified                    ║")
    print("╚════════════════════════════════════════════════════════════════════╝")

    r1 = test_flash_crash()
    r2 = test_monte_carlo()
    r3 = test_mnav_apocalypse()

    # Combined summary
    print("\n" + "=" * 70)
    print("COMBINED STRESS TEST RESULTS")
    print("=" * 70)

    verdicts = {
        "Flash Crash": r1["summary"]["overall_verdict"],
        "Monte Carlo": r2["overall_verdict"],
        "mNAV Apocalypse": r3["summary"]["overall_verdict"],
    }

    print(f"\n{'Test':<25} {'Verdict':<20} {'Key Finding'}")
    print("─" * 70)
    print(f"{'Flash Crash':<25} {verdicts['Flash Crash']:<20} "
          f"Worst impact: {r1['summary']['worst_portfolio_impact_pct']:.1f}%")
    print(f"{'Monte Carlo':<25} {verdicts['Monte Carlo']:<20} "
          f"P95 DD: {r2['max_drawdown_percentiles']['p95']:.1f}% | "
          f"40% DD: {r2['drawdown_exceedance']['exceed_40pct']:.1f}% of paths")
    print(f"{'mNAV Apocalypse':<25} {verdicts['mNAV Apocalypse']:<20} "
          f"Safety fail: {r3['summary']['safety_net_fail_premium']}x | "
          f"Critical: {r3['summary']['critical_finding']}")

    # Overall
    all_pass = all(v == "PASS" for v in verdicts.values())
    any_fail = any(v == "FAIL" for v in verdicts.values())
    overall = "PASS" if all_pass else ("FAIL" if any_fail else "CONDITIONAL PASS")

    print(f"\n{'─' * 70}")
    print(f"OVERALL SYSTEM VERDICT: {overall}")
    print(f"{'─' * 70}")

    if overall == "CONDITIONAL PASS":
        print("\nConditional items require attention:")
        for test, v in verdicts.items():
            if v != "PASS":
                print(f"  - {test}: {v}")

    print("\nFiles saved:")
    print(f"  - {DATA_DIR}/flash_crash_stress.json")
    print(f"  - {DATA_DIR}/monte_carlo_stress.json")
    print(f"  - {DATA_DIR}/mnav_apocalypse_stress.json")


if __name__ == "__main__":
    main()
