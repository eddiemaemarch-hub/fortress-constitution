#!/usr/bin/env python3
"""
MSTR Bitcoin Bull Run Moonshot / Lottery Strategy Backtest
==========================================================
Strategy: Deploy $100k into deep OTM MSTR LEAP calls during BTC Q4 bull cycles.
MSTR beta ~3.63x to BTC. Far OTM calls create 50-200x lottery multipliers.

Author: Rudy v2.0 Trading System
"""

import warnings
warnings.filterwarnings("ignore")

import datetime as dt
import math
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

# ── Configuration ────────────────────────────────────────────────────────────

CAPITAL = 100_000
SLIPPAGE_ENTRY = 0.075       # 7.5% average slippage on entry
SLIPPAGE_EXIT  = 0.075       # 7.5% average slippage on exit
RISK_FREE_RATE = 0.045       # approximate T-bill rate
CONTRACT_MULT  = 100         # shares per contract

# Strike multipliers to test
STRIKE_MULTIPLIERS = [3.0, 4.0, 4.8, 5.5, 6.0, 7.0]

# IV assumptions for far OTM MSTR LEAPs (annualized)
IV_BY_STRIKE = {
    3.0: 1.00,
    4.0: 1.15,
    4.8: 1.30,
    5.5: 1.40,
    6.0: 1.50,
    7.0: 1.60,
}

# Historical MSTR beta to BTC (rolling, but we use a central estimate)
MSTR_BTC_BETA = 3.63

# ── Black-Scholes ────────────────────────────────────────────────────────────

def bs_call_price(S, K, T, r, sigma):
    """European call price via Black-Scholes."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def bs_delta(S, K, T, r, sigma):
    """Black-Scholes call delta."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1)


def bs_theta(S, K, T, r, sigma):
    """Black-Scholes call theta (per day)."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    theta = (- (S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
             - r * K * math.exp(-r * T) * norm.cdf(d2))
    return theta / 365.0


def bs_gamma(S, K, T, r, sigma):
    """Black-Scholes call gamma."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return norm.pdf(d1) / (S * sigma * math.sqrt(T))


# ── Data Download ────────────────────────────────────────────────────────────

def fetch_data():
    """Download MSTR and BTC-USD from yfinance."""
    print("Fetching MSTR and BTC-USD data from Yahoo Finance...")
    mstr = yf.download("MSTR", start="2020-01-01", auto_adjust=True, progress=False)
    btc  = yf.download("BTC-USD", start="2020-01-01", auto_adjust=True, progress=False)

    # Flatten MultiIndex columns if present
    if isinstance(mstr.columns, pd.MultiIndex):
        mstr.columns = mstr.columns.get_level_values(0)
    if isinstance(btc.columns, pd.MultiIndex):
        btc.columns = btc.columns.get_level_values(0)

    mstr = mstr[["Close"]].rename(columns={"Close": "MSTR"})
    btc  = btc[["Close"]].rename(columns={"Close": "BTC"})
    df = mstr.join(btc, how="inner").dropna()
    print(f"  -> {len(df)} trading days loaded  ({df.index[0].date()} to {df.index[-1].date()})\n")
    return df


# ── Beta Calculation ─────────────────────────────────────────────────────────

def compute_rolling_beta(df, window=60):
    """Compute rolling beta of MSTR to BTC."""
    ret = df.pct_change().dropna()
    cov  = ret["MSTR"].rolling(window).cov(ret["BTC"])
    var  = ret["BTC"].rolling(window).var()
    beta = cov / var
    return beta.dropna()


# ── Define Entry Points ──────────────────────────────────────────────────────

def identify_entries(df):
    """
    Identify Q4 entry dates aligned with BTC halving cycles.
    BTC halvings: Jul 2016, May 2020, Apr 2024.
    Post-halving bull years: 2017, 2021, 2025.
    We enter ~Oct 1 of the bull year (or prior Q4).
    Also test entries in accumulation years for comparison.
    """
    entries = []

    # 2020-Q4: BTC breaking out post-halving, MSTR started buying BTC in Aug 2020
    entries.append({
        "label": "2020-Q4 (Post-Halving Breakout)",
        "entry_date": "2020-10-01",
        "hold_months": 16,   # LEAP ~16 months out
        "cycle": "2020-2021 Bull",
    })

    # 2021-Q4: Cycle top / late entry test (stress test)
    entries.append({
        "label": "2021-Q4 (Cycle Peak — Stress Test)",
        "entry_date": "2021-10-01",
        "hold_months": 16,
        "cycle": "2021 Late / Bear Entry",
    })

    # 2023-Q4: Accumulation before 2024 halving
    entries.append({
        "label": "2023-Q4 (Pre-Halving Accumulation)",
        "entry_date": "2023-10-01",
        "hold_months": 16,
        "cycle": "2023-2024 Pre-Halving",
    })

    # 2024-Q4: Post-halving momentum (Apr 2024 halving)
    entries.append({
        "label": "2024-Q4 (Post-Halving Momentum)",
        "entry_date": "2024-10-01",
        "hold_months": 16,
        "cycle": "2024-2025 Bull",
    })

    return entries


# ── Simulate a Single Trade ──────────────────────────────────────────────────

def simulate_trade(df, entry_date_str, hold_months, strike_mult, iv):
    """
    Simulate buying deep OTM MSTR call LEAPs.
    Returns dict with trade metrics.
    """
    entry_date = pd.Timestamp(entry_date_str)

    # Find nearest trading day
    mask = df.index >= entry_date
    if not mask.any():
        return None
    idx_entry = df.index[mask][0]

    # Expiration
    exp_date = entry_date + pd.DateOffset(months=hold_months)
    mask_exp = df.index >= exp_date
    if mask_exp.any():
        idx_exit = df.index[mask_exp][0]
    else:
        idx_exit = df.index[-1]  # use latest available

    S_entry = float(df.loc[idx_entry, "MSTR"])
    S_exit  = float(df.loc[idx_exit, "MSTR"])
    K       = round(S_entry * strike_mult, 2)
    T_entry = hold_months / 12.0
    T_exit  = max((idx_exit - idx_entry).days, 0) / 365.0
    T_remaining = max(T_entry - T_exit, 0.001)

    btc_entry = float(df.loc[idx_entry, "BTC"])
    btc_exit  = float(df.loc[idx_exit, "BTC"])

    # Option price at entry
    premium_entry = bs_call_price(S_entry, K, T_entry, RISK_FREE_RATE, iv)
    if premium_entry < 0.10:
        premium_entry = 0.10  # floor

    # Apply entry slippage (pay more)
    premium_entry *= (1 + SLIPPAGE_ENTRY)

    # Number of contracts
    num_contracts = int(CAPITAL / (premium_entry * CONTRACT_MULT))
    if num_contracts < 1:
        num_contracts = 1
    total_cost = num_contracts * premium_entry * CONTRACT_MULT

    # Greeks at entry
    delta_entry = bs_delta(S_entry, K, T_entry, RISK_FREE_RATE, iv)
    theta_entry = bs_theta(S_entry, K, T_entry, RISK_FREE_RATE, iv)
    gamma_entry = bs_gamma(S_entry, K, T_entry, RISK_FREE_RATE, iv)

    # Option price at exit (or expiration)
    actual_days_held = (idx_exit - idx_entry).days
    T_at_exit = max(T_entry - actual_days_held / 365.0, 0.0)

    if T_at_exit <= 0:
        # Expired — intrinsic value only
        premium_exit = max(S_exit - K, 0.0)
    else:
        # IV crush / expansion: assume IV drops 15% as option approaches expiry
        iv_exit = iv * 0.85
        premium_exit = bs_call_price(S_exit, K, T_at_exit, RISK_FREE_RATE, iv_exit)

    # Apply exit slippage (receive less)
    premium_exit *= (1 - SLIPPAGE_EXIT)

    total_proceeds = num_contracts * premium_exit * CONTRACT_MULT
    pnl = total_proceeds - total_cost
    pnl_pct = (pnl / total_cost) * 100
    multiple = total_proceeds / total_cost if total_cost > 0 else 0

    mstr_move = (S_exit / S_entry - 1) * 100
    btc_move  = (btc_exit / btc_entry - 1) * 100

    # Peak value during hold (for max drawdown from peak)
    hold_slice = df.loc[idx_entry:idx_exit, "MSTR"]
    peak_price = float(hold_slice.max())
    trough_price = float(hold_slice.min())

    # Estimate peak option value
    peak_day_idx = hold_slice.idxmax()
    days_to_peak = (peak_day_idx - idx_entry).days
    T_at_peak = max(T_entry - days_to_peak / 365.0, 0.001)
    peak_opt = bs_call_price(peak_price, K, T_at_peak, RISK_FREE_RATE, iv)
    peak_portfolio = num_contracts * peak_opt * CONTRACT_MULT

    # Max drawdown from portfolio peak
    if peak_portfolio > 0:
        max_dd = (1 - total_proceeds / peak_portfolio) * 100 if total_proceeds < peak_portfolio else 0
    else:
        max_dd = 100.0

    return {
        "entry_date": idx_entry.date(),
        "exit_date": idx_exit.date(),
        "days_held": actual_days_held,
        "S_entry": S_entry,
        "S_exit": S_exit,
        "K": K,
        "strike_mult": strike_mult,
        "iv": iv,
        "T_entry": T_entry,
        "premium_entry": premium_entry,
        "premium_exit": premium_exit,
        "num_contracts": num_contracts,
        "total_cost": total_cost,
        "total_proceeds": total_proceeds,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "multiple": multiple,
        "mstr_move_pct": mstr_move,
        "btc_move_pct": btc_move,
        "btc_entry": btc_entry,
        "btc_exit": btc_exit,
        "delta": delta_entry,
        "theta_day": theta_entry,
        "gamma": gamma_entry,
        "peak_portfolio": peak_portfolio,
        "max_dd_pct": max_dd,
    }


# ── Path Simulation: Daily Mark-to-Market ────────────────────────────────────

def daily_mtm(df, entry_date_str, hold_months, strike_mult, iv):
    """Return a daily mark-to-market Series for a trade."""
    entry_date = pd.Timestamp(entry_date_str)
    mask = df.index >= entry_date
    if not mask.any():
        return pd.Series(dtype=float)
    idx_entry = df.index[mask][0]
    exp_date = entry_date + pd.DateOffset(months=hold_months)
    mask_exp = df.index >= exp_date
    idx_exit = df.index[mask_exp][0] if mask_exp.any() else df.index[-1]

    S_entry = float(df.loc[idx_entry, "MSTR"])
    K = round(S_entry * strike_mult, 2)
    T_entry = hold_months / 12.0

    premium_entry = bs_call_price(S_entry, K, T_entry, RISK_FREE_RATE, iv)
    if premium_entry < 0.10:
        premium_entry = 0.10
    premium_entry *= (1 + SLIPPAGE_ENTRY)
    num_contracts = int(CAPITAL / (premium_entry * CONTRACT_MULT))
    if num_contracts < 1:
        num_contracts = 1

    hold_slice = df.loc[idx_entry:idx_exit, "MSTR"]
    values = []
    for date, price in hold_slice.items():
        days_elapsed = (date - idx_entry).days
        T_rem = max(T_entry - days_elapsed / 365.0, 0.001)
        opt_val = bs_call_price(float(price), K, T_rem, RISK_FREE_RATE, iv)
        portfolio_val = num_contracts * opt_val * CONTRACT_MULT
        values.append(portfolio_val)

    return pd.Series(values, index=hold_slice.index)


# ── Sharpe Ratio ─────────────────────────────────────────────────────────────

def sharpe_from_trades(results):
    """Annualized Sharpe from trade returns."""
    rets = [r["pnl_pct"] / 100.0 for r in results]
    if len(rets) < 2:
        return float("nan")
    avg_hold_years = np.mean([r["days_held"] / 365.0 for r in results])
    ann_rets = [(1 + r) ** (1.0 / max(avg_hold_years, 0.5)) - 1 for r in rets]
    excess = np.array(ann_rets) - RISK_FREE_RATE
    if np.std(excess) == 0:
        return float("nan")
    return float(np.mean(excess) / np.std(excess))


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    hdr = """
================================================================================
    MSTR BITCOIN BULL RUN MOONSHOT / LOTTERY STRATEGY BACKTEST
    Deep OTM LEAP Calls  |  Capital: $100,000  |  No Leverage
================================================================================
"""
    print(hdr)

    df = fetch_data()

    # ── Beta Analysis ────────────────────────────────────────────────────
    beta = compute_rolling_beta(df, window=60)
    print("=" * 80)
    print("  MSTR vs BTC BETA ANALYSIS (60-day rolling)")
    print("=" * 80)
    print(f"  Current beta:    {beta.iloc[-1]:.2f}")
    print(f"  Mean beta:       {beta.mean():.2f}")
    print(f"  Median beta:     {beta.median():.2f}")
    print(f"  Max beta:        {beta.max():.2f}")
    print(f"  Min beta:        {beta.min():.2f}")

    # Correlation
    ret = df.pct_change().dropna()
    corr = ret["MSTR"].corr(ret["BTC"])
    print(f"  MSTR-BTC corr:   {corr:.3f}")
    print()

    # ── Entry Points ─────────────────────────────────────────────────────
    entries = identify_entries(df)

    # ── Run Trades Across Strike Multipliers ─────────────────────────────
    # Focus on the sweet-spot strike (4.8x) for the main table, then show
    # a sensitivity matrix across all strikes.

    SWEET_SPOT = 4.8

    print("=" * 80)
    print(f"  TRADE-BY-TRADE RESULTS  (Strike = {SWEET_SPOT}x Spot)")
    print("=" * 80)

    iv = IV_BY_STRIKE[SWEET_SPOT]
    main_results = []

    for entry in entries:
        res = simulate_trade(df, entry["entry_date"], entry["hold_months"], SWEET_SPOT, iv)
        if res is None:
            continue
        res["label"] = entry["label"]
        res["cycle"] = entry["cycle"]
        main_results.append(res)

    # Print each trade
    for i, r in enumerate(main_results, 1):
        winner = "WIN" if r["pnl"] > 0 else "LOSS"
        print(f"\n  Trade #{i}: {r['label']}")
        print(f"  {'─' * 70}")
        print(f"  Cycle:            {r['cycle']}")
        print(f"  Entry:            {r['entry_date']}  |  Exit: {r['exit_date']}  ({r['days_held']} days)")
        print(f"  MSTR at entry:    ${r['S_entry']:>10,.2f}   ->  ${r['S_exit']:>10,.2f}  ({r['mstr_move_pct']:+.1f}%)")
        print(f"  BTC at entry:     ${r['btc_entry']:>10,.0f}   ->  ${r['btc_exit']:>10,.0f}  ({r['btc_move_pct']:+.1f}%)")
        print(f"  Strike (K):       ${r['K']:>10,.2f}   ({r['strike_mult']}x spot)")
        print(f"  IV:               {r['iv']*100:.0f}%")
        print(f"  Premium (entry):  ${r['premium_entry']:>10,.2f} /share   (incl. {SLIPPAGE_ENTRY*100:.1f}% slippage)")
        print(f"  Premium (exit):   ${r['premium_exit']:>10,.2f} /share   (incl. {SLIPPAGE_EXIT*100:.1f}% slippage)")
        print(f"  Contracts:        {r['num_contracts']:>10,}")
        print(f"  Total cost:       ${r['total_cost']:>12,.2f}")
        print(f"  Total proceeds:   ${r['total_proceeds']:>12,.2f}")
        print(f"  P&L:              ${r['pnl']:>12,.2f}  ({r['pnl_pct']:+.1f}%)  [{winner}]")
        print(f"  Return multiple:  {r['multiple']:.2f}x")
        print(f"  Peak portfolio:   ${r['peak_portfolio']:>12,.2f}")
        print(f"  Max DD from peak: {r['max_dd_pct']:.1f}%")
        print(f"  Entry Greeks:     delta={r['delta']:.4f}  theta/day=${r['theta_day']:.4f}  gamma={r['gamma']:.6f}")

    # ── Summary Stats ────────────────────────────────────────────────────
    print("\n")
    print("=" * 80)
    print(f"  PORTFOLIO SUMMARY  (Strike = {SWEET_SPOT}x,  IV = {iv*100:.0f}%)")
    print("=" * 80)

    wins = [r for r in main_results if r["pnl"] > 0]
    losses = [r for r in main_results if r["pnl"] <= 0]
    total_pnl = sum(r["pnl"] for r in main_results)
    avg_return = np.mean([r["pnl_pct"] for r in main_results])
    avg_multiple = np.mean([r["multiple"] for r in main_results])
    max_dd = max(r["max_dd_pct"] for r in main_results)
    sharpe = sharpe_from_trades(main_results)

    # If we deployed $100k each cycle sequentially
    cumulative = CAPITAL
    for r in main_results:
        cumulative = cumulative * r["multiple"]

    print(f"  Trades:              {len(main_results)}")
    print(f"  Winners:             {len(wins)}")
    print(f"  Losers:              {len(losses)}")
    print(f"  Win rate:            {len(wins)/len(main_results)*100:.1f}%")
    print(f"  Avg return:          {avg_return:+.1f}%")
    print(f"  Avg multiple:        {avg_multiple:.2f}x")
    print(f"  Best trade:          {max(r['pnl_pct'] for r in main_results):+.1f}%  ({max(r['multiple'] for r in main_results):.2f}x)")
    print(f"  Worst trade:         {min(r['pnl_pct'] for r in main_results):+.1f}%  ({min(r['multiple'] for r in main_results):.2f}x)")
    print(f"  Max drawdown:        {max_dd:.1f}%  (from peak portfolio value)")
    print(f"  Sharpe ratio:        {sharpe:.2f}")
    print(f"  Sequential compound: ${CAPITAL:,.0f} -> ${cumulative:,.2f}  ({cumulative/CAPITAL:.1f}x)")
    print()

    # ── Strike Sensitivity Matrix ────────────────────────────────────────
    print("=" * 80)
    print("  STRIKE SENSITIVITY MATRIX  (Return Multiple by Entry & Strike)")
    print("=" * 80)

    # Header
    header = f"  {'Entry':<38}"
    for sm in STRIKE_MULTIPLIERS:
        header += f"  {sm:.1f}x"
        header += " " * max(0, 8 - len(f"{sm:.1f}x"))
    print(header)
    print("  " + "─" * (38 + len(STRIKE_MULTIPLIERS) * 10))

    matrix_results = {}  # (entry_label, strike) -> result

    for entry in entries:
        row = f"  {entry['label']:<38}"
        for sm in STRIKE_MULTIPLIERS:
            iv_sm = IV_BY_STRIKE[sm]
            res = simulate_trade(df, entry["entry_date"], entry["hold_months"], sm, iv_sm)
            if res is None:
                row += f"  {'N/A':<8}"
            else:
                mult = res["multiple"]
                matrix_results[(entry["label"], sm)] = res
                if mult >= 10:
                    row += f"  \033[92m{mult:>6.1f}x\033[0m"
                elif mult >= 2:
                    row += f"  \033[93m{mult:>6.1f}x\033[0m"
                elif mult < 0.5:
                    row += f"  \033[91m{mult:>6.1f}x\033[0m"
                else:
                    row += f"  {mult:>6.1f}x"
        print(row)

    # Average row
    avg_row = f"  {'AVERAGE':<38}"
    for sm in STRIKE_MULTIPLIERS:
        mults = [matrix_results[(e["label"], sm)]["multiple"]
                 for e in entries if (e["label"], sm) in matrix_results]
        if mults:
            avg_row += f"  {np.mean(mults):>6.1f}x"
        else:
            avg_row += f"  {'N/A':<8}"
    print("  " + "─" * (38 + len(STRIKE_MULTIPLIERS) * 10))
    print(avg_row)
    print()

    # ── P&L Table by Strike ──────────────────────────────────────────────
    print("=" * 80)
    print("  P&L TABLE  ($100k capital per trade)")
    print("=" * 80)

    header2 = f"  {'Entry':<38}  {'Strike':>8}  {'Cost':>12}  {'Proceeds':>12}  {'P&L':>12}  {'Mult':>6}"
    print(header2)
    print("  " + "─" * 96)

    for entry in entries:
        for sm in [3.0, 4.8, 7.0]:  # show 3 key strikes
            key = (entry["label"], sm)
            if key in matrix_results:
                r = matrix_results[key]
                print(f"  {entry['label']:<38}  {sm:>6.1f}x  ${r['total_cost']:>10,.0f}  ${r['total_proceeds']:>10,.0f}  ${r['pnl']:>10,.0f}  {r['multiple']:>5.1f}x")
        print()

    # ── Scenario Analysis ────────────────────────────────────────────────
    print("=" * 80)
    print("  SCENARIO ANALYSIS: BTC MOVE -> MSTR MOVE -> OPTION PAYOFF")
    print("=" * 80)
    print(f"  Assumptions: MSTR beta = {MSTR_BTC_BETA}x  |  Strike = 4.8x  |  IV = 130%")
    print(f"  Entry MSTR = $300 (illustrative)  |  K = $1,440  |  T = 1.33yr\n")

    scenarios = [
        ("BTC +50%",   0.50),
        ("BTC +100%",  1.00),
        ("BTC +150%",  1.50),
        ("BTC +200%",  2.00),
        ("BTC +300%",  3.00),
        ("BTC -30%",  -0.30),
        ("BTC -50%",  -0.50),
    ]

    S_base = 300.0
    K_base = S_base * 4.8
    T_base = 1.33
    iv_base = 1.30

    entry_prem = bs_call_price(S_base, K_base, T_base, RISK_FREE_RATE, iv_base)
    entry_prem_slip = entry_prem * (1 + SLIPPAGE_ENTRY)
    contracts_base = int(CAPITAL / (entry_prem_slip * CONTRACT_MULT))

    print(f"  {'Scenario':<16}  {'MSTR Move':>10}  {'MSTR Price':>11}  {'Opt Value':>10}  {'Portfolio':>12}  {'Return':>8}  {'Multiple':>8}")
    print("  " + "─" * 87)

    for label, btc_move in scenarios:
        mstr_move = btc_move * MSTR_BTC_BETA
        S_new = S_base * (1 + mstr_move)
        T_exit = 0.25  # assume ~3 months before expiry
        iv_exit = iv_base * 0.85
        opt_new = bs_call_price(max(S_new, 0.01), K_base, T_exit, RISK_FREE_RATE, iv_exit)
        opt_new_slip = opt_new * (1 - SLIPPAGE_EXIT)
        port_val = contracts_base * opt_new_slip * CONTRACT_MULT
        cost = contracts_base * entry_prem_slip * CONTRACT_MULT
        ret = (port_val / cost - 1) * 100
        mult = port_val / cost

        print(f"  {label:<16}  {mstr_move*100:>+9.0f}%  ${S_new:>9,.0f}  ${opt_new_slip:>8,.2f}  ${port_val:>10,.0f}  {ret:>+7.0f}%  {mult:>6.1f}x")

    print()

    # ── Risk Summary ─────────────────────────────────────────────────────
    print("=" * 80)
    print("  RISK ANALYSIS")
    print("=" * 80)

    # Probability of total loss (option expires worthless)
    total_loss_trades = [r for r in main_results if r["multiple"] < 0.05]
    print(f"  Total loss trades (>95% loss):  {len(total_loss_trades)} / {len(main_results)}")
    print(f"  Max single-trade loss:          ${min(r['pnl'] for r in main_results):,.0f}")
    print(f"  Max capital at risk per trade:  ${CAPITAL:,}")
    print(f"  Time decay risk (theta):        ${abs(main_results[0]['theta_day']):,.4f} /day at entry")
    print(f"  Key risk: 100% capital loss if BTC doesn't rally strongly in cycle window")
    print(f"  Mitigation: Only enter during confirmed post-halving Q4 momentum")
    print()

    # ── Final Verdict ────────────────────────────────────────────────────
    print("=" * 80)
    print("  FINAL VERDICT")
    print("=" * 80)

    best = max(main_results, key=lambda r: r["multiple"])
    worst = min(main_results, key=lambda r: r["multiple"])

    print(f"""
  This is a HIGH-CONVICTION LOTTERY strategy. Historical backtest shows:

  - Best case:    {best['label']}
                  ${CAPITAL:,} -> ${best['total_proceeds']:,.0f}  ({best['multiple']:.1f}x)
  - Worst case:   {worst['label']}
                  ${CAPITAL:,} -> ${worst['total_proceeds']:,.0f}  ({worst['multiple']:.1f}x)
  - Win rate:     {len(wins)/len(main_results)*100:.0f}%  (profitable trades / total trades)
  - Sweet spot:   4.8x strike, Q4 post-halving entry, 14-18mo expiry

  The strategy is BINARY: you either catch a massive BTC cycle move that sends
  MSTR up 3-10x (making the deep OTM calls worth 10-100x), or the options
  expire near-worthless. Cycle timing is everything.
""")
    print("=" * 80)


if __name__ == "__main__":
    main()
