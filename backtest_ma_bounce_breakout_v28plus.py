#!/usr/bin/env python3
"""
backtest_ma_bounce_breakout_v28plus.py
Tests three additive MA filters on top of v2.8+ crossover signal:

  1. BOUNCE  — after 200W SMA reclaim, price pulls back to MA and bounces
               (confirms 200W SMA now acting as dynamic support)
  2. BREAKOUT — 50W MA crosses above 200W SMA (Golden Cross variant)
               (confirms broader trend change, reduces false reclaims)
  3. SLOPE   — 200W SMA slope must be flat/rising at entry
               (declining MA = unreliable support)

v2.8+ core entry/exit logic is NOT modified.
Research only — requires Commander approval before live use.

Usage:
    python3 backtest_ma_bounce_breakout_v28plus.py           # all 5 variants
    python3 backtest_ma_bounce_breakout_v28plus.py --walk-forward
    python3 backtest_ma_bounce_breakout_v28plus.py --stress
    python3 backtest_ma_bounce_breakout_v28plus.py --all
"""

import argparse
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

warnings.filterwarnings("ignore")

# ── CONFIG ─────────────────────────────────────────────────────────────────────
START_DATE      = "2015-01-01"
END_DATE        = datetime.now().strftime("%Y-%m-%d")

# v2.8+ locked params
MA_200W         = 200
TRAIL_STOP      = 0.65
POSITION_PCT    = 0.25
LEAP_LEVERAGE   = 4.0
INITIAL_CAP     = 10_000.0

# MA filter params (research — tunable)
MA_50W          = 50            # shorter MA for Golden Cross
BOUNCE_ZONE_PCT = 0.03          # price within 3% of 200W SMA = "at the MA"
BOUNCE_LOOKBACK = 6             # weeks to look back for a bounce setup
SLOPE_PERIOD    = 8             # weeks to measure 200W SMA slope direction

WF_IS_WEEKS     = 24 * 4
WF_OOS_WEEKS    = 6  * 4

STRESS_PERIODS = [
    ("2018 Bear",          "2018-01-01", "2018-12-31"),
    ("2019 Chop",          "2019-01-01", "2019-12-31"),
    ("2020 COVID",         "2020-01-01", "2020-12-31"),
    ("2021 Bull Peak",     "2021-01-01", "2021-12-31"),
    ("2022 Bear",          "2022-01-01", "2022-12-31"),
    ("2023 Recovery",      "2023-01-01", "2023-12-31"),
    ("2024 Bull Run",      "2024-01-01", "2024-12-31"),
    ("Full History",       START_DATE,   END_DATE),
]


# ── DATA ──────────────────────────────────────────────────────────────────────

def fetch_data() -> pd.DataFrame:
    print("  Fetching BTC-USD weekly...")
    btc  = yf.download("BTC-USD", start=START_DATE, end=END_DATE,
                        interval="1wk", progress=False, auto_adjust=True)
    print("  Fetching MSTR weekly...")
    mstr = yf.download("MSTR",    start=START_DATE, end=END_DATE,
                        interval="1wk", progress=False, auto_adjust=True)

    def col(df, c):
        return df[c].iloc[:, 0] if isinstance(df.columns, pd.MultiIndex) else df[c]

    data = pd.DataFrame({
        "btc_open":   col(btc,  "Open"),
        "btc_close":  col(btc,  "Close"),
        "mstr_open":  col(mstr, "Open"),
        "mstr_close": col(mstr, "Close"),
    }).dropna()
    return data


# ── INDICATORS ────────────────────────────────────────────────────────────────

def add_indicators(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()

    # Core MAs
    df["ma_200w"] = df["btc_close"].rolling(MA_200W, min_periods=50).mean()
    df["ma_50w"]  = df["btc_close"].rolling(MA_50W,  min_periods=20).mean()

    # Trend flags
    df["below_200w"]    = df["btc_close"] < df["ma_200w"]
    df["btc_green"]     = df["btc_close"] > df["btc_open"]
    df["above_200w"]    = df["btc_close"] > df["ma_200w"]

    # Golden Cross: 50W above 200W
    df["golden_cross"]  = df["ma_50w"] > df["ma_200w"]

    # 200W SMA slope: positive if MA is higher than N weeks ago
    df["ma_200w_slope"] = df["ma_200w"] - df["ma_200w"].shift(SLOPE_PERIOD)
    df["slope_flat_up"] = df["ma_200w_slope"] >= 0   # flat or rising = valid

    # Bounce setup: price came within 3% of 200W SMA from above, then closed green
    df["near_200w"]     = (
        (df["btc_close"] >= df["ma_200w"] * (1 - BOUNCE_ZONE_PCT)) &
        (df["btc_close"] <= df["ma_200w"] * (1 + BOUNCE_ZONE_PCT * 2))
    )

    return df


# ── SIGNALS ───────────────────────────────────────────────────────────────────

def v28_base_signal(df: pd.DataFrame) -> pd.Series:
    """Existing v2.8+ signal: dip below 200W + green weekly reclaim."""
    sig = pd.Series(False, index=df.index)
    dipped = False
    for i in range(MA_200W, len(df)):
        if df["below_200w"].iloc[i]:
            dipped = True
        if dipped and not df["below_200w"].iloc[max(0, i-12):i].any():
            dipped = False
        if dipped and df["btc_green"].iloc[i] and not df["below_200w"].iloc[i]:
            sig.iloc[i] = True
            dipped = False
    return sig


def bounce_filter(df: pd.DataFrame) -> pd.Series:
    """
    Bounce filter: after initial reclaim of 200W SMA, wait for price
    to pull back near the MA and then close green off it (MA as support).
    Fires within BOUNCE_LOOKBACK weeks of the base signal.
    """
    base = v28_base_signal(df)
    filt = pd.Series(False, index=df.index)
    in_bounce_watch = False
    watch_start = 0

    for i in range(1, len(df)):
        if base.iloc[i]:
            in_bounce_watch = True
            watch_start = i
            # If already near MA at crossover — count it immediately
            if df["near_200w"].iloc[i] and df["btc_green"].iloc[i]:
                filt.iloc[i] = True
                in_bounce_watch = False

        elif in_bounce_watch:
            weeks_since = i - watch_start
            if weeks_since > BOUNCE_LOOKBACK:
                in_bounce_watch = False  # window expired
            elif df["near_200w"].iloc[i] and df["btc_green"].iloc[i]:
                filt.iloc[i] = True
                in_bounce_watch = False

    return filt


def breakout_filter(df: pd.DataFrame) -> pd.Series:
    """
    Breakout filter: base signal AND 50W MA is above 200W MA (Golden Cross).
    Confirms the shorter trend is bullish relative to long-term trend.
    """
    base = v28_base_signal(df)
    return base & df["golden_cross"]


def slope_filter(df: pd.DataFrame) -> pd.Series:
    """
    Slope filter: base signal AND 200W SMA slope is flat or rising.
    Declining 200W SMA = price may just be a dead-cat bounce off resistance.
    """
    base = v28_base_signal(df)
    return base & df["slope_flat_up"]


def combined_filter(df: pd.DataFrame) -> pd.Series:
    """All three filters: bounce + breakout (golden cross) + slope."""
    bounce   = bounce_filter(df)
    breakout = breakout_filter(df)
    slope    = slope_filter(df)
    # Combined: bounce OR (breakout AND slope) — flexible entry
    return bounce | (breakout & slope)


VARIANTS = [
    ("v2.8+ BASELINE",          v28_base_signal),
    ("+ BOUNCE filter",         bounce_filter),
    ("+ BREAKOUT (GoldenCross)",breakout_filter),
    ("+ SLOPE filter",          slope_filter),
    ("+ ALL COMBINED",          combined_filter),
]


# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────

def run_backtest(df: pd.DataFrame, signal_fn) -> tuple:
    entries = signal_fn(df)
    capital = INITIAL_CAP
    equity  = [capital]
    trades  = []
    in_trade = False
    entry_price = entry_cap = hwm = 0.0
    entry_date  = None

    for i in range(len(df)):
        bar  = df.index[i]
        mstr = float(df["mstr_close"].iloc[i])

        if not in_trade:
            if entries.iloc[i]:
                in_trade    = True
                entry_price = mstr
                entry_cap   = capital * POSITION_PCT
                hwm         = entry_cap
                entry_date  = bar
        else:
            ret     = (mstr - entry_price) / entry_price if entry_price else 0
            pos_val = max(entry_cap * (1 + ret * LEAP_LEVERAGE), 0)
            hwm     = max(hwm, pos_val)

            exit_reason = None
            if pos_val <= hwm * TRAIL_STOP:
                exit_reason = "trail_stop"
            elif pos_val >= entry_cap * 10:
                exit_reason = "10x_target"

            if exit_reason:
                pnl = pos_val - entry_cap
                capital += pnl
                trades.append({
                    "entry_date":  entry_date,
                    "exit_date":   bar,
                    "pnl":         pnl,
                    "win":         pnl > 0,
                    "exit_reason": exit_reason,
                })
                in_trade = False
                hwm = 0.0

        equity.append(capital)

    return trades, equity


# ── METRICS ───────────────────────────────────────────────────────────────────

def calc_metrics(trades: list, equity: list) -> dict:
    eq = pd.Series(equity, dtype=float)
    if not trades:
        return dict(n=0, wr=0, ret=0, sharpe=0, dd=0, pf=0, avg_win=0, avg_loss=0)
    df   = pd.DataFrame(trades)
    wins = df[df["win"]]
    loss = df[~df["win"]]
    ret  = (eq.iloc[-1] - eq.iloc[0]) / eq.iloc[0] * 100
    r    = eq.pct_change().dropna()
    sh   = (r.mean() / r.std() * np.sqrt(52)) if r.std() > 0 else 0
    dd   = ((eq - eq.cummax()) / eq.cummax() * 100).min()
    gp   = wins["pnl"].sum() if len(wins) else 0
    gl   = abs(loss["pnl"].sum()) if len(loss) else 1e-9
    return dict(
        n       = len(df),
        wr      = len(wins) / len(df) * 100,
        ret     = ret,
        sharpe  = sh,
        dd      = dd,
        pf      = gp / gl,
        avg_win = wins["pnl"].mean() if len(wins) else 0,
        avg_loss= loss["pnl"].mean() if len(loss) else 0,
    )


# ── FULL BACKTEST ─────────────────────────────────────────────────────────────

def run_full_backtest(df: pd.DataFrame):
    print(f"\n{'═'*70}")
    print(f"  FULL BACKTEST — all 5 variants ({df.index[0].date()} → {df.index[-1].date()})")
    print(f"{'═'*70}")
    print(f"  {'Variant':<28} {'N':>3} {'WR%':>6} {'Ret%':>7} {'DD%':>7} {'Sharpe':>7} {'PF':>5}")
    print(f"  {'─'*28} {'─'*3} {'─'*6} {'─'*7} {'─'*7} {'─'*7} {'─'*5}")

    results = []
    for label, fn in VARIANTS:
        t, e = run_backtest(df, fn)
        m = calc_metrics(t, e)
        results.append((label, m))
        marker = " ◄ baseline" if label == "v2.8+ BASELINE" else ""
        print(f"  {label:<28} {m['n']:>3} {m['wr']:>5.1f}% {m['ret']:>6.1f}% "
              f"{m['dd']:>6.1f}% {m['sharpe']:>7.3f} {m['pf']:>5.2f}{marker}")

    # Delta table vs baseline
    base = results[0][1]
    print(f"\n  {'─'*70}")
    print(f"  DELTA vs BASELINE")
    print(f"  {'─'*70}")
    print(f"  {'Variant':<28} {'ΔN':>4} {'ΔWR%':>6} {'ΔRet%':>7} {'ΔDD%':>7} {'ΔSharpe':>8} {'ΔPF':>6}")
    print(f"  {'─'*28} {'─'*4} {'─'*6} {'─'*7} {'─'*7} {'─'*8} {'─'*6}")
    for label, m in results[1:]:
        improved = sum([
            m['sharpe'] > base['sharpe'],
            m['wr']     > base['wr'],
            m['dd']     > base['dd'],
            m['pf']     > base['pf'],
        ])
        verdict = "✓ ADD" if improved >= 3 else "✗ REJ"
        print(f"  {label:<28} {m['n']-base['n']:>+4} {m['wr']-base['wr']:>+5.1f}% "
              f"{m['ret']-base['ret']:>+6.1f}% {m['dd']-base['dd']:>+6.1f}% "
              f"{m['sharpe']-base['sharpe']:>+8.3f} {m['pf']-base['pf']:>+6.2f}  {verdict} ({improved}/4)")

    # Best variant
    best = max(results, key=lambda x: x[1]['sharpe'])
    print(f"\n  ══ BEST SHARPE: {best[0]} ({best[1]['sharpe']:.3f}) ══")


# ── WALK FORWARD ──────────────────────────────────────────────────────────────

def run_walk_forward(df: pd.DataFrame):
    print(f"\n{'═'*70}")
    print(f"  WALK-FORWARD  (IS={WF_IS_WEEKS//4}mo / OOS={WF_OOS_WEEKS//4}mo rolling)")
    print(f"{'═'*70}")

    agg = {label: [] for label, _ in VARIANTS}
    idx = 0
    win_num = 0

    while idx + WF_IS_WEEKS + WF_OOS_WEEKS <= len(df):
        oos = df.iloc[idx + WF_IS_WEEKS: idx + WF_IS_WEEKS + WF_OOS_WEEKS]
        if len(oos) < 10:
            break
        p1 = df.index[idx + WF_IS_WEEKS].strftime("%Y-%m")
        p2 = df.index[min(idx + WF_IS_WEEKS + WF_OOS_WEEKS - 1, len(df)-1)].strftime("%Y-%m")
        win_num += 1
        print(f"\n  Window {win_num}: OOS {p1} → {p2}")
        print(f"  {'Variant':<28} {'N':>3} {'WR%':>6} {'Ret%':>7} {'Sharpe':>7} {'ΔSharpe':>9}")
        print(f"  {'─'*62}")

        base_sharpe = None
        for label, fn in VARIANTS:
            t, e = run_backtest(oos, fn)
            m = calc_metrics(t, e)
            agg[label].append(m)
            if base_sharpe is None:
                base_sharpe = m['sharpe']
                delta_str = "  (baseline)"
            else:
                delta_str = f"  {m['sharpe']-base_sharpe:>+8.3f}"
            print(f"  {label:<28} {m['n']:>3} {m['wr']:>5.1f}% "
                  f"{m['ret']:>6.1f}% {m['sharpe']:>7.3f}{delta_str}")

        idx += WF_OOS_WEEKS

    if win_num > 0:
        print(f"\n  {'═'*70}")
        print(f"  AGGREGATE OOS  ({win_num} windows)")
        print(f"  {'─'*70}")
        print(f"  {'Variant':<28} {'Avg N':>5} {'Avg WR%':>8} {'Avg Ret%':>9} "
              f"{'Avg Sharpe':>11} {'Avg DD%':>8} {'Avg PF':>7}")
        print(f"  {'─'*28} {'─'*5} {'─'*8} {'─'*9} {'─'*11} {'─'*8} {'─'*7}")
        for label, _ in VARIANTS:
            ms = agg[label]
            if not ms:
                continue
            print(f"  {label:<28} "
                  f"{np.mean([m['n'] for m in ms]):>5.1f} "
                  f"{np.mean([m['wr'] for m in ms]):>7.1f}% "
                  f"{np.mean([m['ret'] for m in ms]):>8.1f}% "
                  f"{np.mean([m['sharpe'] for m in ms]):>11.3f} "
                  f"{np.mean([m['dd'] for m in ms]):>7.1f}% "
                  f"{np.mean([m['pf'] for m in ms]):>7.2f}")

        # Best OOS variant
        best_label = max(
            [(label, np.mean([m['sharpe'] for m in agg[label]])) for label, _ in VARIANTS],
            key=lambda x: x[1]
        )
        print(f"\n  ══ BEST OOS SHARPE: {best_label[0]} ({best_label[1]:.3f}) ══")


# ── STRESS TESTS ──────────────────────────────────────────────────────────────

def run_stress_tests(df: pd.DataFrame):
    print(f"\n{'═'*70}")
    print(f"  STRESS TESTS  ({len(STRESS_PERIODS)} scenarios × 5 variants)")
    print(f"{'═'*70}")

    for scenario, start, end in STRESS_PERIODS:
        subset = df[start:end]
        if len(subset) < 15:
            print(f"\n  [{scenario}]  insufficient data")
            continue

        print(f"\n  [{scenario}]")
        print(f"  {'Variant':<28} {'N':>3} {'WR%':>6} {'Ret%':>7} {'DD%':>7} {'Sharpe':>7} {'PF':>5}")
        print(f"  {'─'*62}")

        base_sharpe = None
        for label, fn in VARIANTS:
            t, e = run_backtest(subset, fn)
            m = calc_metrics(t, e)
            if base_sharpe is None:
                base_sharpe = m['sharpe']
                marker = ""
            else:
                delta = m['sharpe'] - base_sharpe
                mark  = "✓" if delta > 0 else "✗"
                marker = f"  {mark}{delta:>+.3f}"
            print(f"  {label:<28} {m['n']:>3} {m['wr']:>5.1f}% {m['ret']:>6.1f}% "
                  f"{m['dd']:>6.1f}% {m['sharpe']:>7.3f} {m['pf']:>5.2f}{marker}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MA Bounce/Breakout × v2.8+ research backtest")
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--stress",       action="store_true")
    parser.add_argument("--all",          action="store_true")
    args = parser.parse_args()

    run_bt = not (args.walk_forward or args.stress) or args.all
    run_wf = args.walk_forward or args.all
    run_st = args.stress or args.all

    print("=" * 70)
    print("  MA BOUNCE / BREAKOUT / SLOPE × v2.8+ RESEARCH BACKTEST")
    print("  Tests 3 additive filters on v2.8+ crossover signal")
    print("  Core v2.8+ logic unchanged — Constitution compliant")
    print("=" * 70)

    df = fetch_data()
    df = add_indicators(df)
    print(f"\n  Data: {df.index[0].date()} → {df.index[-1].date()} ({len(df)} weekly bars)")
    print(f"  Variants: {', '.join(v[0] for v in VARIANTS)}\n")

    if run_bt:
        run_full_backtest(df)
    if run_wf:
        run_walk_forward(df)
    if run_st:
        run_stress_tests(df)

    print(f"\n{'═'*70}")
    print("  RESEARCH NOTE: LOCAL yfinance sim. MSTR LEAP leverage ~4x stock.")
    print("  Bounce zone: ±3% of 200W SMA. Golden Cross: 50W > 200W.")
    print("  Slope: 200W SMA direction over last 8 weeks.")
    print("  Do NOT deploy without QC API walk-forward confirmation.")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    main()
