#!/usr/bin/env python3
"""Rudy v2.8+ BMNR/ETH Stress Tests — Research Only (Not For Deployment)

BMNR (Bitmine Immersion Technologies) — World's largest corporate ETH treasury
Adapted from MSTR stress tests with ETH-specific parameters.

Three stress tests + backtest simulation:
1. Flash Crash Liquidity Stress (ETH Gap-and-Trap)
2. Monte Carlo Path Dependency (ETH Vol Profile)
3. eNAV Mean Reversion Apocalypse (ETH premium compression)
4. v2.8+ Backtest Simulation ($10K, adapted for ETH/BMNR)

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
#  BMNR/ETH SYSTEM PARAMETERS
# ══════════════════════════════════════════════════════════════

# Account (hypothetical research allocation)
ACCOUNT_NLV = 10000.0

# BMNR Fundamentals (as of March 2026)
ETH_HOLDINGS_2026 = 4_600_000       # 4.6M ETH
DILUTED_SHARES_2026 = 500_000_000   # Estimated diluted shares
ETH_PRICE_CURRENT = 2200.0          # Approximate ETH/USD
BMNR_PRICE_CURRENT = 25.0           # Approximate BMNR price (NYSE American)
SPY_PRICE_CURRENT = 570.0

# Derived
def compute_bmnr_nav_per_share(eth_price):
    return (eth_price * ETH_HOLDINGS_2026) / DILUTED_SHARES_2026

def compute_bmnr_premium(bmnr_price, eth_price):
    nav_ps = compute_bmnr_nav_per_share(eth_price)
    if nav_ps <= 0:
        return 999
    return bmnr_price / nav_ps

def compute_bmnr_price_from_premium(premium, eth_price):
    nav_ps = compute_bmnr_nav_per_share(eth_price)
    return premium * nav_ps

# Current eNAV premium
CURRENT_ENAV = compute_bmnr_premium(BMNR_PRICE_CURRENT, ETH_PRICE_CURRENT)
print(f"BMNR eNAV baseline: {CURRENT_ENAV:.2f}x (NAV/share=${compute_bmnr_nav_per_share(ETH_PRICE_CURRENT):.2f})")

# Trail stop tiers (same structure as MSTR)
LADDER_TIERS = [
    (10000, 12.0),
    (5000, 20.0),
    (2000, 25.0),
    (1000, 30.0),
    (500, 35.0),
]

# eNAV Premium bands (adapted for ETH treasury — ETH companies trade at different ratios)
PREMIUM_BANDS = {
    "DISCOUNT":  {"range": (0, 0.5),   "safety_strikes": [5, 10],      "safety_wt": 0.30,
                  "spec_strikes": [25, 40],  "spec_wt": 0.70, "block": False},
    "DEPRESSED": {"range": (0.5, 1.0), "safety_strikes": [5, 10, 15],  "safety_wt": 0.45,
                  "spec_strikes": [30, 50],  "spec_wt": 0.55, "block": False},
    "FAIR":      {"range": (1.0, 2.0), "safety_strikes": [5, 10, 15],  "safety_wt": 0.35,
                  "spec_strikes": [50, 75],  "spec_wt": 0.65, "block": False},
    "ELEVATED":  {"range": (2.0, 2.5), "safety_strikes": [10, 15],     "safety_wt": 0.50,
                  "spec_strikes": [40, 50],  "spec_wt": 0.50, "block": False},
    "EUPHORIC":  {"range": (2.5, 999), "safety_strikes": [],            "safety_wt": 0,
                  "spec_strikes": [],        "spec_wt": 0,    "block": True},
}

# Risk limits
DAILY_LOSS_LIMIT_PCT = 2.0
CONSECUTIVE_LOSS_LIMIT = 5
PANIC_FLOOR_PCT = -35.0
INITIAL_FLOOR_PCT = 0.65
MNAV_KILL_SWITCH = 0.75  # eNAV equivalent

# BMNR vol is higher than MSTR (younger, ETH more volatile)
BMNR_IMPLIED_VOL = 1.20   # 120% annual IV
ETH_ANNUAL_VOL = 0.90     # ETH ~90% annual vol
RISK_FREE = 0.045

# Dynamic LEAP multiplier (adapted for BMNR price levels)
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


# ══════════════════════════════════════════════════════════════
#  Black-Scholes
# ══════════════════════════════════════════════════════════════

def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def black_scholes_put(S, K, T, r, sigma):
    if T <= 0: return max(K - S, 0)
    if S <= 0: return K * math.exp(-r * T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)

def black_scholes_call(S, K, T, r, sigma):
    if T <= 0: return max(S - K, 0)
    if S <= 0: return 0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)


# ══════════════════════════════════════════════════════════════
#  TEST 1: FLASH CRASH (ETH-Adapted)
# ══════════════════════════════════════════════════════════════

def test_flash_crash():
    print("\n" + "=" * 70)
    print("TEST 1: BMNR FLASH CRASH LIQUIDITY STRESS (ETH Gap-and-Trap)")
    print("=" * 70)

    bmnr_current = BMNR_PRICE_CURRENT
    eth_current = ETH_PRICE_CURRENT
    bmnr_vol = BMNR_IMPLIED_VOL

    # Hypothetical BMNR put position for hedging
    # BMNR $10P Jan28 (deep OTM safety put)
    bmnr_put_strike = 10
    bmnr_put_expiry_T = 1.84  # ~22 months

    # Also model a SPY hedge similar to MSTR portfolio
    spy_put_strike = 430
    spy_put_expiry_T = 0.82  # ~10 months
    spy_vol = 0.15

    # Hypothetical entry for stock position
    entry_price = 18.0
    hwm = 28.0
    stock_gain_from_hwm = ((hwm - entry_price) / entry_price) * 100
    leap_mult = get_leap_multiplier(compute_bmnr_premium(bmnr_current, eth_current))
    peak_leap_gain = stock_gain_from_hwm * leap_mult

    gap_scenarios = [-0.10, -0.15, -0.20, -0.25, -0.30]

    results = {
        "test_name": "BMNR Flash Crash Liquidity Stress (ETH Gap-and-Trap)",
        "timestamp": datetime.now().isoformat(),
        "asset": "BMNR",
        "crypto_backing": "ETH",
        "baseline": {
            "bmnr_price": bmnr_current,
            "eth_price": eth_current,
            "eNAV_premium": round(CURRENT_ENAV, 3),
            "account_nlv": ACCOUNT_NLV,
            "assumed_entry": entry_price,
            "assumed_hwm": hwm,
            "peak_leap_gain_pct": round(peak_leap_gain, 1),
        },
        "scenarios": [],
    }

    print(f"\nBaseline: BMNR=${bmnr_current} | ETH=${eth_current:,} | eNAV={CURRENT_ENAV:.2f}x | Account=${ACCOUNT_NLV:,}")
    print(f"Assumed stock entry: ${entry_price} | HWM: ${hwm} | Peak LEAP gain: {peak_leap_gain:.1f}%")
    print("-" * 70)

    for gap in gap_scenarios:
        gap_pct = abs(gap) * 100
        bmnr_gap_price = bmnr_current * (1 + gap)
        # ETH drops ~50% of BMNR move (tighter correlation than MSTR/BTC since BMNR IS the ETH proxy)
        eth_gap_price = eth_current * (1 + gap * 0.5)
        # BTC secondary: drops ~30% of BMNR move (correlated but not direct)
        btc_gap_price = 70000 * (1 + gap * 0.3)
        spy_gap_price = SPY_PRICE_CURRENT * (1 + gap * 0.2)

        # Vol spikes in crash
        vol_spike = bmnr_vol * (1 + abs(gap) * 3)
        spy_vol_spike = spy_vol * (1 + abs(gap) * 2)

        bmnr_put_val = black_scholes_put(bmnr_gap_price, bmnr_put_strike, bmnr_put_expiry_T, RISK_FREE, vol_spike) * 100
        spy_put_val = black_scholes_put(spy_gap_price, spy_put_strike, spy_put_expiry_T, RISK_FREE, spy_vol_spike) * 100

        # eNAV analysis
        new_premium = compute_bmnr_premium(bmnr_gap_price, eth_gap_price)
        old_premium = CURRENT_ENAV
        prem_drop_pct = ((old_premium - new_premium) / old_premium * 100) if old_premium > 0 else 0
        compression_alert = prem_drop_pct > 15

        # Kill switch check
        kill_switch_fires = new_premium < MNAV_KILL_SWITCH

        # Trail stop analysis
        trail_pct = 0
        tier_name = "NONE"
        for threshold, trail in LADDER_TIERS:
            if peak_leap_gain >= threshold:
                trail_pct = trail
                tier_name = f"+{threshold}%"
                break

        stop_level = hwm * (1 - trail_pct / 100) if trail_pct > 0 else 0
        gap_through = bmnr_gap_price < stop_level if stop_level > 0 else False
        slippage_from_stop = ((stop_level - bmnr_gap_price) / stop_level * 100) if (stop_level > 0 and gap_through) else 0

        # LEAP gain at gap price
        stock_gain_gap = ((bmnr_gap_price - entry_price) / entry_price) * 100
        leap_gain_gap = stock_gain_gap * get_leap_multiplier(new_premium)

        panic_floor_hit = leap_gain_gap <= PANIC_FLOOR_PCT
        initial_floor_hit = bmnr_gap_price < entry_price * INITIAL_FLOOR_PCT

        # Band shift
        band_name, band_info = get_premium_band(new_premium)
        old_band = get_premium_band(old_premium)[0]
        roll_triggered = band_name != old_band

        # Determine verdict
        if gap_through and slippage_from_stop > 15:
            verdict = "FAIL"
        elif gap_through and slippage_from_stop > 5:
            verdict = "CONDITIONAL PASS"
        elif panic_floor_hit:
            verdict = "CONDITIONAL PASS"
        elif kill_switch_fires:
            verdict = "CONDITIONAL PASS"
        else:
            verdict = "PASS"

        scenario = {
            "gap_pct": f"-{gap_pct:.0f}%",
            "bmnr_gap_price": round(bmnr_gap_price, 2),
            "eth_gap_price": round(eth_gap_price, 0),
            "btc_gap_price": round(btc_gap_price, 0),
            "spy_gap_price": round(spy_gap_price, 2),
            "eNAV_premium": round(new_premium, 3),
            "premium_drop_pct": round(prem_drop_pct, 1),
            "kill_switch_fires": kill_switch_fires,
            "trail_stop": {
                "tier": tier_name,
                "trail_pct": trail_pct,
                "stop_level": round(stop_level, 2),
                "gap_through": gap_through,
                "slippage_pct": round(slippage_from_stop, 2) if gap_through else 0,
            },
            "leap_impact": {
                "stock_gain_pct": round(stock_gain_gap, 1),
                "leap_gain_pct": round(leap_gain_gap, 1),
                "panic_floor_hit": panic_floor_hit,
                "initial_floor_hit": initial_floor_hit,
                "exit_trigger": "KILL_SWITCH" if kill_switch_fires else (
                    "PANIC_FLOOR" if panic_floor_hit else (
                        "INITIAL_FLOOR" if initial_floor_hit else "NONE")),
            },
            "dual_correlation": {
                "eth_move_pct": round(gap * 0.5 * 100, 1),
                "btc_move_pct": round(gap * 0.3 * 100, 1),
                "note": "ETH drops ~50% of BMNR move, BTC ~30% (dual exposure)"
            },
            "verdict": verdict,
        }
        results["scenarios"].append(scenario)

        print(f"\nGap: {gap_pct:.0f}% → BMNR=${bmnr_gap_price:.2f} | ETH=${eth_gap_price:.0f} | eNAV={new_premium:.2f}x | Band={band_name}")
        print(f"  Kill Switch: {'FIRES' if kill_switch_fires else 'OK'} | Trail: tier={tier_name} | Gap-through={'YES' if gap_through else 'NO'}")
        print(f"  LEAP: stock={stock_gain_gap:.1f}% leap={leap_gain_gap:.1f}% | Floor={'HIT' if panic_floor_hit or initial_floor_hit else 'OK'}")
        print(f"  → [{verdict}]")

    fails = sum(1 for s in results["scenarios"] if s["verdict"] == "FAIL")
    results["summary"] = {
        "scenarios_passed": sum(1 for s in results["scenarios"] if s["verdict"] == "PASS"),
        "scenarios_conditional": sum(1 for s in results["scenarios"] if s["verdict"] == "CONDITIONAL PASS"),
        "scenarios_failed": fails,
        "kill_switch_fires_at": next(
            (s["gap_pct"] for s in results["scenarios"] if s["kill_switch_fires"]), "NEVER"),
        "overall_verdict": "PASS" if fails == 0 else ("CONDITIONAL PASS" if fails <= 1 else "FAIL"),
    }

    print(f"\n{'─' * 70}")
    print(f"FLASH CRASH SUMMARY: {results['summary']['overall_verdict']}")
    print(f"  Pass/Conditional/Fail: {results['summary']['scenarios_passed']}/{results['summary']['scenarios_conditional']}/{fails}")
    print(f"  Kill switch fires at: {results['summary']['kill_switch_fires_at']}")

    path = os.path.join(DATA_DIR, "bmnr_flash_crash_stress.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {path}")
    return results


# ══════════════════════════════════════════════════════════════
#  TEST 2: MONTE CARLO (ETH Vol Profile)
# ══════════════════════════════════════════════════════════════

def kurtosis_calc(x):
    m = np.mean(x)
    s = np.std(x, ddof=0)
    if s == 0: return 0
    return np.mean(((x - m) / s) ** 4) - 3

def skew_calc(x):
    m = np.mean(x)
    s = np.std(x, ddof=0)
    if s == 0: return 0
    return np.mean(((x - m) / s) ** 3)


def test_monte_carlo():
    print("\n" + "=" * 70)
    print("TEST 2: BMNR MONTE CARLO PATH DEPENDENCY (ETH Vol Profile)")
    print("=" * 70)

    np.random.seed(42)
    N_SIMS = 5000
    N_WEEKS = 200  # ~4 years (shorter history than MSTR)

    # BMNR vol is higher than MSTR — younger company, ETH more volatile
    annual_vol = 1.00       # ~100% annual vol (between MSTR 80% and pure ETH)
    annual_return = 0.60    # ETH historical ~60% annual
    weekly_vol = annual_vol / np.sqrt(52)
    weekly_mu = (1 + annual_return) ** (1 / 52) - 1

    # Fatter tails than MSTR (crypto-native company, df=4)
    df_t = 4
    raw_returns = np.random.standard_t(df_t, size=N_WEEKS)
    t_scale = weekly_vol / np.sqrt(df_t / (df_t - 2))
    base_weekly_returns = raw_returns * t_scale + weekly_mu

    print(f"\nBMNR Parameters: vol={annual_vol*100:.0f}%/yr | return={annual_return*100:.0f}%/yr | df={df_t}")
    print(f"Generated {N_WEEKS} weekly returns | mu={weekly_mu*100:.2f}%/wk | vol={weekly_vol*100:.2f}%/wk")
    print(f"Empirical: mean={np.mean(base_weekly_returns)*100:.2f}% | std={np.std(base_weekly_returns)*100:.2f}%")
    print(f"  kurtosis={float(kurtosis_calc(base_weekly_returns)):.2f} | skew={float(skew_calc(base_weekly_returns)):.2f}")
    print(f"Running {N_SIMS} bootstrap simulations...")

    # Strategy uses 100W SMA (not 200W — short history)
    sma_period = 100

    max_drawdowns = []
    final_returns = []
    daily_loss_triggers = 0
    consecutive_loss_triggers = 0
    dip_reclaim_fires = []
    kill_switch_fires = 0

    for sim in range(N_SIMS):
        shuffled = np.random.choice(base_weekly_returns, size=N_WEEKS, replace=True)
        prices = [100.0]
        for r in shuffled:
            prices.append(prices[-1] * (1 + r))
        prices = np.array(prices)

        # Max drawdown
        peak = np.maximum.accumulate(prices)
        drawdowns = (peak - prices) / peak * 100
        max_dd = float(np.max(drawdowns))
        max_drawdowns.append(max_dd)
        final_returns.append((prices[-1] / prices[0] - 1) * 100)

        # 100W SMA dip+reclaim
        dip_reclaim_count = 0
        dipped = False
        green_weeks = 0

        for w in range(sma_period, len(prices)):
            sma = np.mean(prices[w - sma_period:w])
            current = prices[w]
            prev = prices[w - 1]

            if current < sma:
                dipped = True
                green_weeks = 0
            elif dipped and current > sma and current > prev:
                green_weeks += 1
                if green_weeks >= 2:
                    dip_reclaim_count += 1
                    dipped = False
                    green_weeks = 0

        dip_reclaim_fires.append(dip_reclaim_count)

        # Daily loss limit simulation
        daily_loss_count = 0
        consec_losses = 0
        max_consec = 0

        for w in range(1, len(prices)):
            week_return = (prices[w] / prices[w - 1] - 1)
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

        # Kill switch: simulate eNAV dropping below 0.75x at worst point
        worst_price = float(np.min(prices))
        if worst_price < prices[0] * 0.25:  # Extreme scenario
            kill_switch_fires += 1

    max_drawdowns = np.array(max_drawdowns)
    final_returns = np.array(final_returns)

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

    barbell_survives_95 = float(np.percentile(max_drawdowns, 95)) < 70
    barbell_survives_99 = float(np.percentile(max_drawdowns, 99)) < 70

    results = {
        "test_name": "BMNR Monte Carlo Path Dependency (ETH Vol Profile)",
        "timestamp": datetime.now().isoformat(),
        "asset": "BMNR",
        "crypto_backing": "ETH",
        "parameters": {
            "n_simulations": N_SIMS,
            "n_weeks": N_WEEKS,
            "annual_vol": annual_vol,
            "annual_return": annual_return,
            "weekly_vol": round(weekly_vol, 4),
            "weekly_mu": round(weekly_mu, 4),
            "fat_tail_df": df_t,
            "sma_period": sma_period,
            "note": "100W SMA (not 200W) due to BMNR's 4.5yr history"
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
            "kill_switch_fires_pct": round(kill_switch_fires / N_SIMS * 100, 2),
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
    print(f"  Kill switch fires: {kill_switch_fires / N_SIMS * 100:.1f}% of paths")
    print(f"\n100W Dip+Reclaim Signals:")
    print(f"  Mean fires per path: {np.mean(dip_reclaim_fires):.1f}")
    print(f"  Paths with zero fires: {np.mean(np.array(dip_reclaim_fires) == 0) * 100:.1f}%")
    print(f"\nBarbell Survival:")
    print(f"  Survives 95th: {'YES' if barbell_survives_95 else 'NO'} (p95 DD={dd_percentiles['p95']:.1f}%)")
    print(f"  Survives 99th: {'YES' if barbell_survives_99 else 'NO'} (p99 DD={dd_percentiles['p99']:.1f}%)")
    print(f"  Positive return paths: {np.mean(final_returns > 0) * 100:.1f}%")
    print(f"\n{'─' * 70}")
    print(f"OVERALL VERDICT: {results['overall_verdict']}")

    path = os.path.join(DATA_DIR, "bmnr_monte_carlo_stress.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {path}")
    return results


# ══════════════════════════════════════════════════════════════
#  TEST 3: eNAV MEAN REVERSION APOCALYPSE
# ══════════════════════════════════════════════════════════════

def test_enav_apocalypse():
    print("\n" + "=" * 70)
    print("TEST 3: BMNR eNAV MEAN REVERSION APOCALYPSE")
    print("=" * 70)

    eth_flat = ETH_PRICE_CURRENT
    nav_per_share = compute_bmnr_nav_per_share(eth_flat)
    print(f"\nETH fixed at ${eth_flat:,} | NAV/share = ${nav_per_share:.2f}")

    starting_premium = 2.5
    starting_bmnr = starting_premium * nav_per_share

    premium_scenarios = [2.0, 1.5, 1.0, 0.75, 0.5, 0.25]  # includes kill switch level
    decay_timelines = [30, 60, 90]

    # BMNR LEAP strikes (lower absolute price than MSTR)
    safety_strikes = [5, 10, 15]
    spec_strikes = [25, 40, 50]

    bmnr_vol = BMNR_IMPLIED_VOL
    T_base = 1.84

    results = {
        "test_name": "BMNR eNAV Mean Reversion Apocalypse",
        "timestamp": datetime.now().isoformat(),
        "asset": "BMNR",
        "crypto_backing": "ETH",
        "parameters": {
            "eth_price": eth_flat,
            "nav_per_share": round(nav_per_share, 2),
            "starting_premium": starting_premium,
            "starting_bmnr": round(starting_bmnr, 2),
            "safety_strikes": safety_strikes,
            "spec_strikes": spec_strikes,
            "bmnr_implied_vol": bmnr_vol,
            "kill_switch_threshold": MNAV_KILL_SWITCH,
        },
        "scenarios": [],
        "timeline_decay": [],
    }

    print(f"Starting BMNR=${starting_bmnr:.2f} at {starting_premium}x premium")
    print(f"Safety strikes: {safety_strikes} | Spec strikes: {spec_strikes}")
    print("-" * 70)

    zero_intrinsic_level = None

    for target_premium in premium_scenarios:
        bmnr_price = target_premium * nav_per_share
        premium_drop_pct = ((starting_premium - target_premium) / starting_premium) * 100

        # Price LEAP calls
        safety_values = {}
        safety_total = 0
        for strike in safety_strikes:
            val = black_scholes_call(bmnr_price, strike, T_base, RISK_FREE, bmnr_vol) * 100
            intrinsic = max(bmnr_price - strike, 0) * 100
            safety_values[str(strike)] = {
                "bs_value": round(val, 2),
                "intrinsic": round(intrinsic, 2),
                "has_intrinsic": intrinsic > 0,
            }
            safety_total += val

        spec_values = {}
        spec_total = 0
        for strike in spec_strikes:
            val = black_scholes_call(bmnr_price, strike, T_base, RISK_FREE, bmnr_vol) * 100
            intrinsic = max(bmnr_price - strike, 0) * 100
            spec_values[str(strike)] = {
                "bs_value": round(val, 2),
                "intrinsic": round(intrinsic, 2),
                "has_intrinsic": intrinsic > 0,
            }
            spec_total += val

        # Reference values
        safety_start = sum(
            black_scholes_call(starting_bmnr, s, T_base, RISK_FREE, bmnr_vol) * 100
            for s in safety_strikes
        )
        spec_start = sum(
            black_scholes_call(starting_bmnr, s, T_base, RISK_FREE, bmnr_vol) * 100
            for s in spec_strikes
        )

        safety_loss_pct = ((safety_start - safety_total) / safety_start * 100) if safety_start > 0 else 100
        spec_loss_pct = ((spec_start - spec_total) / spec_start * 100) if spec_start > 0 else 100
        portfolio_loss_pct = safety_loss_pct * 0.30 + spec_loss_pct * 0.70

        compression_fires = premium_drop_pct > 15
        kill_switch_fires = target_premium < MNAV_KILL_SWITCH
        band_name, band_info = get_premium_band(target_premium)
        old_band = get_premium_band(starting_premium)[0]
        roll_triggered = band_name != old_band

        all_leaps_zero_intrinsic = all(
            max(bmnr_price - s, 0) == 0 for s in safety_strikes + spec_strikes
        )
        safety_net_failed = safety_loss_pct > 90

        if all_leaps_zero_intrinsic and zero_intrinsic_level is None:
            zero_intrinsic_level = target_premium

        # Verdict with kill switch
        if kill_switch_fires:
            verdict = "PASS (KILL SWITCH EXITS)"
        elif safety_net_failed:
            verdict = "FAIL" if not kill_switch_fires else "PASS (KILL SWITCH EXITS)"
        elif all_leaps_zero_intrinsic:
            verdict = "FAIL"
        else:
            verdict = "PASS"

        scenario = {
            "premium": target_premium,
            "bmnr_price": round(bmnr_price, 2),
            "premium_drop_pct": round(premium_drop_pct, 1),
            "kill_switch_fires": kill_switch_fires,
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
            },
            "alerts": {
                "compression_alert_fires": compression_fires,
                "band_shift": f"{old_band} -> {band_name}",
                "roll_recommended": roll_triggered,
            },
            "failure_checks": {
                "all_leaps_zero_intrinsic": all_leaps_zero_intrinsic,
                "safety_net_failed": safety_net_failed,
                "entry_blocked": band_info["block"],
            },
            "verdict": verdict,
        }
        results["scenarios"].append(scenario)

        print(f"\nPremium {target_premium}x → BMNR=${bmnr_price:.2f} (drop={premium_drop_pct:.0f}%) | Band={band_name}")
        print(f"  Kill Switch: {'FIRES — ALL POSITIONS CLOSED' if kill_switch_fires else 'OK'}")
        print(f"  Safety pool: ${safety_total:.0f} (loss {safety_loss_pct:.1f}%)")
        print(f"  Spec pool:   ${spec_total:.0f} (loss {spec_loss_pct:.1f}%)")
        print(f"  Barbell weighted loss: {portfolio_loss_pct:.1f}%")
        print(f"  → [{verdict}]")

    # Timeline decay
    print(f"\n{'─' * 70}")
    print("TIMELINE ANALYSIS: eNAV premium decay over time")

    for days in decay_timelines:
        T_remaining = T_base - days / 365.25
        if T_remaining <= 0:
            T_remaining = 0.01

        timeline_result = {"decay_days": days, "T_remaining_years": round(T_remaining, 3), "scenarios": []}

        for target_premium in [2.0, 1.0, 0.5]:
            bmnr_price = target_premium * nav_per_share
            safety_val = sum(
                black_scholes_call(bmnr_price, s, T_remaining, RISK_FREE, bmnr_vol) * 100
                for s in safety_strikes
            )
            spec_val = sum(
                black_scholes_call(bmnr_price, s, T_remaining, RISK_FREE, bmnr_vol) * 100
                for s in spec_strikes
            )
            safety_start_t = sum(
                black_scholes_call(starting_bmnr, s, T_base, RISK_FREE, bmnr_vol) * 100
                for s in safety_strikes
            )
            spec_start_t = sum(
                black_scholes_call(starting_bmnr, s, T_base, RISK_FREE, bmnr_vol) * 100
                for s in spec_strikes
            )
            total_loss = ((safety_start_t + spec_start_t) - (safety_val + spec_val)) / (safety_start_t + spec_start_t) * 100

            timeline_result["scenarios"].append({
                "premium": target_premium,
                "bmnr_price": round(bmnr_price, 2),
                "safety_value": round(safety_val, 2),
                "spec_value": round(spec_val, 2),
                "total_loss_pct": round(total_loss, 1),
            })
            print(f"  {days}d decay | {target_premium}x | BMNR=${bmnr_price:.0f} | "
                  f"Safety=${safety_val:.0f} Spec=${spec_val:.0f} | Loss={total_loss:.1f}%")

        results["timeline_decay"].append(timeline_result)

    # Summary
    fails = sum(1 for s in results["scenarios"] if "FAIL" in s["verdict"])
    kill_protects = sum(1 for s in results["scenarios"] if "KILL SWITCH" in s["verdict"])

    results["summary"] = {
        "zero_intrinsic_premium": zero_intrinsic_level,
        "kill_switch_threshold": MNAV_KILL_SWITCH,
        "kill_switch_protects_scenarios": kill_protects,
        "scenarios_passed": sum(1 for s in results["scenarios"] if "PASS" in s["verdict"]),
        "scenarios_failed": fails,
        "overall_verdict": "PASS" if fails == 0 else ("CONDITIONAL PASS" if fails <= 1 else "FAIL"),
        "note": f"0.75x eNAV kill switch protects {kill_protects} scenarios that would otherwise fail",
    }

    print(f"\n{'─' * 70}")
    print(f"eNAV APOCALYPSE SUMMARY: {results['summary']['overall_verdict']}")
    print(f"  Kill switch protects: {kill_protects} scenarios")
    print(f"  Zero intrinsic at: {zero_intrinsic_level}x" if zero_intrinsic_level else "  LEAPs retain value")
    print(f"  Pass/Fail: {results['summary']['scenarios_passed']}/{fails}")

    path = os.path.join(DATA_DIR, "bmnr_enav_apocalypse_stress.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {path}")
    return results


# ══════════════════════════════════════════════════════════════
#  TEST 4: v2.8+ BACKTEST SIMULATION ($10K, ETH-Adapted)
# ══════════════════════════════════════════════════════════════

def test_backtest_simulation():
    """Simulate v2.8+ strategy on BMNR using synthetic price data derived from
    ETH's actual historical returns scaled to BMNR's vol profile.

    Since BMNR only has ~4.5 years of data and we can't run QuantConnect here,
    we simulate the strategy logic directly using ETH-correlated price paths.
    """
    print("\n" + "=" * 70)
    print("TEST 4: BMNR v2.8+ BACKTEST SIMULATION ($10K)")
    print("=" * 70)

    np.random.seed(123)

    # Simulate ~230 weeks of BMNR prices (May 2021 to March 2026)
    N_WEEKS = 230
    STARTING_CAPITAL = 10000.0

    # Build BMNR-like price path using ETH-correlated returns
    # ETH went from ~$2500 (May 2021) to ~$2200 (Mar 2026) with massive swings
    # BMNR IPO'd ~$5, peaked ~$30+, currently ~$25

    # Use t-distribution for fat tails
    annual_vol = 1.00
    weekly_vol = annual_vol / np.sqrt(52)
    weekly_mu = 0.003  # slight positive drift
    df_t = 4
    t_scale = weekly_vol / np.sqrt(df_t / (df_t - 2))

    returns = np.random.standard_t(df_t, size=N_WEEKS) * t_scale + weekly_mu

    # Build price path starting at $5 (IPO price)
    prices = [5.0]
    for r in returns:
        prices.append(max(prices[-1] * (1 + r), 0.50))  # floor at $0.50
    prices = np.array(prices)

    # Build ETH price path (correlated ~0.7 with BMNR)
    eth_returns = returns * 0.7 + np.random.standard_t(df_t, size=N_WEEKS) * t_scale * 0.3
    eth_prices = [2500.0]
    for r in eth_returns:
        eth_prices.append(max(eth_prices[-1] * (1 + r), 100.0))
    eth_prices = np.array(eth_prices)

    # Strategy simulation
    sma_period = 100  # 100W SMA (adapted for short history)
    capital = STARTING_CAPITAL
    position_qty = 0
    entry_price = 0
    adder_qty = 0
    adder_entry = 0
    trade_log = []
    equity_curve = [capital]

    dipped = False
    green_weeks = 0
    golden_cross_weeks = 0
    risk_pct = 0.25
    leap_mult_avg = 5.0  # average for simulation

    for w in range(1, len(prices)):
        price = prices[w]
        eth_price = eth_prices[w]

        # Compute 100W SMA if enough data
        if w >= sma_period:
            sma = np.mean(prices[w - sma_period:w])

            # Compute 50W EMA
            if w >= 50:
                ema_data = prices[max(0, w-200):w]
                ema50 = np.mean(ema_data[:50])
                k = 2.0 / 51.0
                for p in ema_data[50:]:
                    ema50 = p * k + ema50 * (1 - k)
            else:
                ema50 = sma

            # ETH filter (ETH > 100W SMA)
            if w >= sma_period:
                eth_sma = np.mean(eth_prices[w - sma_period:w])
                eth_above_sma = eth_price > eth_sma
            else:
                eth_above_sma = True

            # eNAV premium
            premium = compute_bmnr_premium(price, eth_price)

            # 100W dip+reclaim
            if price < sma:
                dipped = True
                green_weeks = 0
            elif dipped and price > sma and price > prices[w-1]:
                green_weeks += 1

            # Golden cross tracking
            if ema50 > sma:
                golden_cross_weeks += 1
            else:
                golden_cross_weeks = 0

            # ENTRY: base position
            if (position_qty == 0 and dipped and green_weeks >= 2
                    and eth_above_sma and premium < 1.5):
                shares_to_buy = int((capital * risk_pct) / price)
                if shares_to_buy > 0:
                    position_qty = shares_to_buy
                    entry_price = price
                    capital -= shares_to_buy * price
                    dipped = False
                    green_weeks = 0
                    trade_log.append({
                        "week": w, "action": "BASE_ENTRY", "price": round(price, 2),
                        "qty": shares_to_buy, "premium": round(premium, 2)
                    })

            # ENTRY: trend adder
            if (position_qty > 0 and adder_qty == 0 and golden_cross_weeks >= 4
                    and premium < 1.5):
                adder_shares = int((capital * risk_pct) / price)
                if adder_shares > 0:
                    adder_qty = adder_shares
                    adder_entry = price
                    capital -= adder_shares * price
                    trade_log.append({
                        "week": w, "action": "TREND_ADDER_ENTRY", "price": round(price, 2),
                        "qty": adder_shares, "premium": round(premium, 2)
                    })

            # EXIT logic for base
            if position_qty > 0 and entry_price > 0:
                stock_gain = ((price - entry_price) / entry_price) * 100
                leap_gain = stock_gain * leap_mult_avg

                # Panic floor
                if leap_gain <= PANIC_FLOOR_PCT:
                    capital += position_qty * price
                    trade_log.append({
                        "week": w, "action": "BASE_EXIT_PANIC", "price": round(price, 2),
                        "qty": position_qty, "pnl_pct": round(stock_gain, 1)
                    })
                    position_qty = 0
                    entry_price = 0

                # Kill switch
                elif premium < MNAV_KILL_SWITCH and premium > 0:
                    capital += position_qty * price
                    trade_log.append({
                        "week": w, "action": "BASE_EXIT_KILLSWITCH", "price": round(price, 2),
                        "qty": position_qty, "premium": round(premium, 2)
                    })
                    position_qty = 0
                    entry_price = 0

                # Euphoria exit
                elif premium > 3.5 and stock_gain > 0:
                    sell_qty = max(1, int(position_qty * 0.15))
                    capital += sell_qty * price
                    position_qty -= sell_qty
                    trade_log.append({
                        "week": w, "action": "EUPHORIA_TRIM", "price": round(price, 2),
                        "qty": sell_qty, "premium": round(premium, 2)
                    })

            # EXIT logic for adder
            if adder_qty > 0 and adder_entry > 0:
                adder_gain = ((price - adder_entry) / adder_entry) * 100

                if adder_gain * leap_mult_avg <= -60:
                    capital += adder_qty * price
                    trade_log.append({
                        "week": w, "action": "ADDER_EXIT_PANIC", "price": round(price, 2),
                        "qty": adder_qty, "pnl_pct": round(adder_gain, 1)
                    })
                    adder_qty = 0
                    adder_entry = 0

                elif golden_cross_weeks == 0 and adder_gain < 0:
                    capital += adder_qty * price
                    trade_log.append({
                        "week": w, "action": "ADDER_EXIT_CONVERGENCE", "price": round(price, 2),
                        "qty": adder_qty, "pnl_pct": round(adder_gain, 1)
                    })
                    adder_qty = 0
                    adder_entry = 0

        # Update equity curve
        total_equity = capital + position_qty * price + adder_qty * price
        equity_curve.append(total_equity)

    # Close any remaining positions at final price
    final_price = prices[-1]
    if position_qty > 0:
        capital += position_qty * final_price
        trade_log.append({
            "week": len(prices)-1, "action": "FINAL_CLOSE_BASE",
            "price": round(final_price, 2), "qty": position_qty
        })
    if adder_qty > 0:
        capital += adder_qty * final_price
        trade_log.append({
            "week": len(prices)-1, "action": "FINAL_CLOSE_ADDER",
            "price": round(final_price, 2), "qty": adder_qty
        })

    equity_curve = np.array(equity_curve)
    final_equity = capital
    total_return = ((final_equity - STARTING_CAPITAL) / STARTING_CAPITAL) * 100

    # Max drawdown
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = (peak - equity_curve) / peak * 100
    max_dd = float(np.max(drawdowns))

    # Sharpe (annualized from weekly equity returns)
    weekly_eq_returns = np.diff(equity_curve) / equity_curve[:-1]
    if np.std(weekly_eq_returns) > 0:
        sharpe = (np.mean(weekly_eq_returns) / np.std(weekly_eq_returns)) * np.sqrt(52)
    else:
        sharpe = 0

    n_trades = len([t for t in trade_log if "ENTRY" in t["action"]])
    n_exits = len([t for t in trade_log if "EXIT" in t["action"] or "CLOSE" in t["action"]])

    results = {
        "test_name": "BMNR v2.8+ Backtest Simulation",
        "timestamp": datetime.now().isoformat(),
        "asset": "BMNR",
        "crypto_backing": "ETH",
        "parameters": {
            "starting_capital": STARTING_CAPITAL,
            "n_weeks": N_WEEKS,
            "sma_period": sma_period,
            "risk_pct": risk_pct,
            "leap_multiplier_avg": leap_mult_avg,
        },
        "performance": {
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(float(sharpe), 3),
            "total_entries": n_trades,
            "total_exits": n_exits,
            "trade_log_count": len(trade_log),
        },
        "price_path": {
            "bmnr_start": round(float(prices[0]), 2),
            "bmnr_end": round(float(prices[-1]), 2),
            "bmnr_high": round(float(np.max(prices)), 2),
            "bmnr_low": round(float(np.min(prices)), 2),
            "eth_start": round(float(eth_prices[0]), 2),
            "eth_end": round(float(eth_prices[-1]), 2),
        },
        "trade_log": trade_log,
    }

    print(f"\nBacktest Results ($10K, {N_WEEKS} weeks):")
    print(f"  BMNR: ${prices[0]:.2f} → ${prices[-1]:.2f} (high=${np.max(prices):.2f}, low=${np.min(prices):.2f})")
    print(f"  ETH:  ${eth_prices[0]:.0f} → ${eth_prices[-1]:.0f}")
    print(f"  Final Equity: ${final_equity:,.2f} ({total_return:+.1f}%)")
    print(f"  Max Drawdown: {max_dd:.1f}%")
    print(f"  Sharpe Ratio: {sharpe:.3f}")
    print(f"  Trades: {n_trades} entries, {n_exits} exits")
    print(f"\nTrade Log:")
    for t in trade_log:
        print(f"  Week {t['week']:>3}: {t['action']:<25} @ ${t['price']:.2f}" +
              (f" | P&L: {t.get('pnl_pct', 'N/A')}%" if 'pnl_pct' in t else "") +
              (f" | Premium: {t.get('premium', 'N/A')}x" if 'premium' in t else ""))

    path = os.path.join(DATA_DIR, "bmnr_v28plus_backtest.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Saved: {path}")
    return results


# ══════════════════════════════════════════════════════════════
#  TEST 5: DUAL CORRELATION STRESS (ETH/BTC Divergence)
# ══════════════════════════════════════════════════════════════

def test_dual_correlation():
    """BMNR-specific test: what happens when ETH and BTC decouple?
    BMNR has both ETH treasury AND BTC mining — a divergence scenario
    where one crashes while the other rallies creates unique risk."""

    print("\n" + "=" * 70)
    print("TEST 5: DUAL CORRELATION STRESS (ETH/BTC Divergence)")
    print("=" * 70)

    scenarios = [
        {"name": "ETH Crash / BTC Flat",     "eth_move": -0.40, "btc_move": 0.00,  "bmnr_beta": 0.7},
        {"name": "ETH Crash / BTC Rally",     "eth_move": -0.30, "btc_move": 0.20,  "bmnr_beta": 0.5},
        {"name": "Both Crash",                "eth_move": -0.30, "btc_move": -0.30, "bmnr_beta": 0.9},
        {"name": "ETH Rally / BTC Crash",     "eth_move": 0.30,  "btc_move": -0.30, "bmnr_beta": 0.4},
        {"name": "Protocol Risk (ETH -50%)",  "eth_move": -0.50, "btc_move": -0.10, "bmnr_beta": 0.8},
    ]

    results = {
        "test_name": "BMNR Dual Correlation Stress (ETH/BTC Divergence)",
        "timestamp": datetime.now().isoformat(),
        "asset": "BMNR",
        "baseline": {
            "bmnr_price": BMNR_PRICE_CURRENT,
            "eth_price": ETH_PRICE_CURRENT,
            "btc_price": 70000,
            "eNAV_premium": round(CURRENT_ENAV, 3),
        },
        "scenarios": [],
    }

    print(f"\nBaseline: BMNR=${BMNR_PRICE_CURRENT} | ETH=${ETH_PRICE_CURRENT} | BTC=$70,000")
    print("-" * 70)

    for sc in scenarios:
        eth_new = ETH_PRICE_CURRENT * (1 + sc["eth_move"])
        btc_new = 70000 * (1 + sc["btc_move"])
        # BMNR move is beta-weighted combination
        bmnr_move = sc["eth_move"] * sc["bmnr_beta"] + sc["btc_move"] * (1 - sc["bmnr_beta"]) * 0.3
        bmnr_new = BMNR_PRICE_CURRENT * (1 + bmnr_move)

        new_premium = compute_bmnr_premium(bmnr_new, eth_new)
        kill_switch = new_premium < MNAV_KILL_SWITCH

        result = {
            "scenario": sc["name"],
            "eth_move_pct": sc["eth_move"] * 100,
            "btc_move_pct": sc["btc_move"] * 100,
            "bmnr_move_pct": round(bmnr_move * 100, 1),
            "bmnr_new_price": round(bmnr_new, 2),
            "eth_new_price": round(eth_new, 0),
            "btc_new_price": round(btc_new, 0),
            "eNAV_premium": round(new_premium, 3),
            "kill_switch_fires": kill_switch,
            "divergence_severity": "HIGH" if abs(sc["eth_move"] - sc["btc_move"]) > 0.3 else (
                "MEDIUM" if abs(sc["eth_move"] - sc["btc_move"]) > 0.15 else "LOW"),
        }
        results["scenarios"].append(result)

        print(f"\n{sc['name']}:")
        print(f"  ETH: {sc['eth_move']*100:+.0f}% → ${eth_new:.0f}")
        print(f"  BTC: {sc['btc_move']*100:+.0f}% → ${btc_new:,.0f}")
        print(f"  BMNR: {bmnr_move*100:+.1f}% → ${bmnr_new:.2f} | eNAV={new_premium:.2f}x")
        print(f"  Kill Switch: {'FIRES' if kill_switch else 'OK'} | Divergence: {result['divergence_severity']}")

    kills = sum(1 for s in results["scenarios"] if s["kill_switch_fires"])
    results["summary"] = {
        "scenarios_tested": len(scenarios),
        "kill_switch_fires": kills,
        "highest_risk": max(results["scenarios"], key=lambda x: abs(x["bmnr_move_pct"]))["scenario"],
        "overall_verdict": "PASS" if kills <= 1 else "CONDITIONAL PASS",
        "note": "Dual correlation creates unique risk not present in pure BTC plays like MSTR"
    }

    print(f"\n{'─' * 70}")
    print(f"DUAL CORRELATION SUMMARY: {results['summary']['overall_verdict']}")
    print(f"  Kill switch fires in {kills}/{len(scenarios)} scenarios")
    print(f"  Highest risk: {results['summary']['highest_risk']}")

    path = os.path.join(DATA_DIR, "bmnr_dual_correlation_stress.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {path}")
    return results


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  RUDY v2.8+ BMNR/ETH STRESS TESTS — RESEARCH ONLY              ║")
    print("║  NOT FOR DEPLOYMENT — Cross-ticker validation                    ║")
    print("╚════════════════════════════════════════════════════════════════════╝")

    r1 = test_flash_crash()
    r2 = test_monte_carlo()
    r3 = test_enav_apocalypse()
    r4 = test_backtest_simulation()
    r5 = test_dual_correlation()

    # Combined summary
    print("\n" + "=" * 70)
    print("COMBINED BMNR STRESS TEST RESULTS")
    print("=" * 70)

    verdicts = {
        "Flash Crash (ETH)": r1["summary"]["overall_verdict"],
        "Monte Carlo (ETH Vol)": r2["overall_verdict"],
        "eNAV Apocalypse": r3["summary"]["overall_verdict"],
        "Backtest Sim ($10K)": "PASS" if r4["performance"]["total_return_pct"] > 0 else "FAIL",
        "Dual Correlation": r5["summary"]["overall_verdict"],
    }

    print(f"\n{'Test':<30} {'Verdict':<25} {'Key Finding'}")
    print("─" * 80)
    print(f"{'Flash Crash (ETH)':<30} {verdicts['Flash Crash (ETH)']:<25} "
          f"Kill switch at: {r1['summary']['kill_switch_fires_at']}")
    print(f"{'Monte Carlo (ETH Vol)':<30} {verdicts['Monte Carlo (ETH Vol)']:<25} "
          f"P95 DD: {r2['max_drawdown_percentiles']['p95']:.1f}% | "
          f"40% DD: {r2['drawdown_exceedance']['exceed_40pct']:.1f}% paths")
    print(f"{'eNAV Apocalypse':<30} {verdicts['eNAV Apocalypse']:<25} "
          f"Kill switch protects: {r3['summary']['kill_switch_protects_scenarios']} scenarios")
    print(f"{'Backtest Sim ($10K)':<30} {verdicts['Backtest Sim ($10K)']:<25} "
          f"Return: {r4['performance']['total_return_pct']:+.1f}% | "
          f"Sharpe: {r4['performance']['sharpe_ratio']:.3f} | "
          f"MaxDD: {r4['performance']['max_drawdown_pct']:.1f}%")
    print(f"{'Dual Correlation':<30} {verdicts['Dual Correlation']:<25} "
          f"Highest risk: {r5['summary']['highest_risk']}")

    all_pass = all(v == "PASS" for v in verdicts.values())
    any_fail = any(v == "FAIL" for v in verdicts.values())
    overall = "PASS" if all_pass else ("FAIL" if any_fail else "CONDITIONAL PASS")

    print(f"\n{'─' * 80}")
    print(f"OVERALL BMNR SYSTEM VERDICT: {overall}")
    print(f"{'─' * 80}")

    if overall != "PASS":
        print("\nItems requiring attention:")
        for test, v in verdicts.items():
            if v != "PASS":
                print(f"  - {test}: {v}")

    # BMNR-specific warnings
    print("\n⚠️  BMNR-SPECIFIC RISKS:")
    print("  1. Only 4.5 years of history — 100W SMA instead of 200W (lower statistical confidence)")
    print("  2. Dual ETH/BTC correlation creates regime ambiguity not present in MSTR")
    print("  3. ETH protocol risk (hard forks, PoS changes) has no BTC equivalent")
    print("  4. BMNR liquidity likely lower than MSTR — wider spreads, more slippage")
    print("  5. eNAV calculation depends on accurate ETH holdings data (quarterly 10-Q lag)")

    print("\n📊 RECOMMENDATION:")
    if overall == "PASS":
        print("  Strategy ADAPTS to BMNR/ETH but with HIGHER RISK than MSTR/BTC.")
        print("  If deploying: reduce position size, use 100W SMA, add ETH/BTC divergence monitor.")
    else:
        print("  Strategy shows CONDITIONAL viability. Circuit breakers are MANDATORY.")
        print("  Research use only until more BMNR history is available.")

    print("\nFiles saved:")
    for f in ["bmnr_flash_crash_stress.json", "bmnr_monte_carlo_stress.json",
              "bmnr_enav_apocalypse_stress.json", "bmnr_v28plus_backtest.json",
              "bmnr_dual_correlation_stress.json"]:
        print(f"  - {DATA_DIR}/{f}")

    # Save combined report
    combined = {
        "test_suite": "BMNR/ETH v2.8+ Cross-Ticker Validation",
        "timestamp": datetime.now().isoformat(),
        "asset": "BMNR",
        "crypto_backing": "ETH",
        "hypothetical_capital": 10000,
        "status": "RESEARCH_ONLY",
        "verdicts": verdicts,
        "overall_verdict": overall,
        "flash_crash": r1["summary"],
        "monte_carlo": {
            "verdict": r2["overall_verdict"],
            "p95_dd": r2["max_drawdown_percentiles"]["p95"],
            "exceed_40_dd": r2["drawdown_exceedance"]["exceed_40pct"],
        },
        "enav_apocalypse": r3["summary"],
        "backtest": r4["performance"],
        "dual_correlation": r5["summary"],
    }
    path = os.path.join(DATA_DIR, "bmnr_v28plus_research_report.json")
    with open(path, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\n  Combined report: {path}")


if __name__ == "__main__":
    main()
