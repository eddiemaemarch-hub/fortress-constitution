#!/usr/bin/env python3
"""
backtest_ema_stoch_reversal.py
EMA Ribbon (21/34/144) + Stochastic Oscillator (7,3,3) reversal strategy.
Tested standalone AND as additive filter on v2.8+ crossover signal.

Strategy rules (Long/Bullish):
  1. Price crosses above EMA 144 (major trend flip)
  2. EMA 21 > EMA 144 and EMA 34 > EMA 144 (ribbon aligns above)
  3. EMA 21 > EMA 34 (white above orange — momentum confirmed)
  4. Wait for first pullback: Stoch K% drops below 20 (oversold)
  5. Trigger: K% crosses above D% and closes above 20
  6. FIRST pullback only — reset after each new alignment event

v2.8+ core entry/exit logic NOT modified. Research only.
Constitution compliant — requires Commander approval before live use.

Usage:
    python3 backtest_ema_stoch_reversal.py           # full comparison
    python3 backtest_ema_stoch_reversal.py --walk-forward
    python3 backtest_ema_stoch_reversal.py --stress
    python3 backtest_ema_stoch_reversal.py --all
"""

import argparse
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

warnings.filterwarnings("ignore")

# ── CONFIG ─────────────────────────────────────────────────────────────────────
START_DATE   = "2015-01-01"
END_DATE     = datetime.now().strftime("%Y-%m-%d")

# v2.8+ locked params
MA_200W      = 200
TRAIL_STOP   = 0.65
POSITION_PCT = 0.25
LEAP_LEV     = 4.0
INITIAL_CAP  = 10_000.0

# EMA ribbon
EMA_FAST     = 21    # white — minor momentum
EMA_MID      = 34    # orange — minor momentum
EMA_SLOW     = 144   # green — major trend filter

# Stochastic (7, 3, 3)
STOCH_K      = 7
STOCH_SMOOTH = 3
STOCH_OB     = 80    # overbought
STOCH_OS     = 20    # oversold

WF_IS_WEEKS  = 24 * 4
WF_OOS_WEEKS = 6  * 4

STRESS_PERIODS = [
    ("2018 Bear",      "2018-01-01", "2018-12-31"),
    ("2019 Chop",      "2019-01-01", "2019-12-31"),
    ("2020 COVID",     "2020-01-01", "2020-12-31"),
    ("2021 Bull Peak", "2021-01-01", "2021-12-31"),
    ("2022 Bear",      "2022-01-01", "2022-12-31"),
    ("2023 Recovery",  "2023-01-01", "2023-12-31"),
    ("2024 Bull Run",  "2024-01-01", "2024-12-31"),
    ("Full History",   START_DATE,   END_DATE),
]


# ── DATA ──────────────────────────────────────────────────────────────────────

def fetch_data() -> pd.DataFrame:
    print("  Fetching BTC-USD weekly...")
    btc  = yf.download("BTC-USD", start=START_DATE, end=END_DATE,
                        interval="1wk", progress=False, auto_adjust=True)
    print("  Fetching MSTR weekly...")
    mstr = yf.download("MSTR", start=START_DATE, end=END_DATE,
                        interval="1wk", progress=False, auto_adjust=True)

    def col(df, c):
        return df[c].iloc[:, 0] if isinstance(df.columns, pd.MultiIndex) else df[c]

    data = pd.DataFrame({
        "btc_open":   col(btc,  "Open"),
        "btc_high":   col(btc,  "High"),
        "btc_low":    col(btc,  "Low"),
        "btc_close":  col(btc,  "Close"),
        "mstr_open":  col(mstr, "Open"),
        "mstr_close": col(mstr, "Close"),
    }).dropna()
    return data


# ── INDICATORS ────────────────────────────────────────────────────────────────

def stochastic(high, low, close, k_period=7, smooth=3):
    """Stochastic Oscillator — K% and D%."""
    lowest_low   = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    raw_k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-9)
    k = raw_k.rolling(smooth).mean()
    d = k.rolling(smooth).mean()
    return k, d


def add_indicators(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()

    # EMA ribbon on BTC
    df["ema_fast"] = df["btc_close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_mid"]  = df["btc_close"].ewm(span=EMA_MID,  adjust=False).mean()
    df["ema_slow"] = df["btc_close"].ewm(span=EMA_SLOW, adjust=False).mean()

    # Stochastic on BTC weekly
    df["stoch_k"], df["stoch_d"] = stochastic(
        df["btc_high"], df["btc_low"], df["btc_close"],
        k_period=STOCH_K, smooth=STOCH_SMOOTH
    )

    # Ribbon alignment flags
    df["ribbon_bull"] = (
        (df["btc_close"] > df["ema_slow"]) &
        (df["ema_fast"]  > df["ema_slow"]) &
        (df["ema_mid"]   > df["ema_slow"]) &
        (df["ema_fast"]  > df["ema_mid"])
    )
    df["ribbon_bear"] = (
        (df["btc_close"] < df["ema_slow"]) &
        (df["ema_fast"]  < df["ema_slow"]) &
        (df["ema_mid"]   < df["ema_slow"]) &
        (df["ema_fast"]  < df["ema_mid"])
    )

    # 200W SMA for v2.8+ baseline
    df["ma_200w"]    = df["btc_close"].rolling(MA_200W, min_periods=50).mean()
    df["below_200w"] = df["btc_close"] < df["ma_200w"]
    df["btc_green"]  = df["btc_close"] > df["btc_open"]

    return df


# ── SIGNALS ───────────────────────────────────────────────────────────────────

def v28_signal(df: pd.DataFrame) -> pd.Series:
    """v2.8+ baseline: dip below 200W SMA + green weekly reclaim."""
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


def ema_stoch_signal(df: pd.DataFrame) -> pd.Series:
    """
    EMA ribbon + Stoch reversal — STANDALONE (not additive to v2.8+).
    Long only (bullish reversal). First pullback after ribbon alignment only.

    State machine:
      WAIT_ALIGN  → waiting for ribbon to flip bullish
      WAIT_OS     → ribbon aligned, waiting for stoch to dip below 20
      WAIT_CROSS  → stoch was OS, waiting for K cross above D above 20
    """
    sig   = pd.Series(False, index=df.index)
    state = "WAIT_ALIGN"
    prev_aligned = False

    for i in range(EMA_SLOW + STOCH_K + STOCH_SMOOTH * 2, len(df)):
        aligned = bool(df["ribbon_bull"].iloc[i])
        k       = float(df["stoch_k"].iloc[i])
        d       = float(df["stoch_d"].iloc[i])
        k_prev  = float(df["stoch_k"].iloc[i-1])

        # Detect fresh alignment (was not aligned last bar)
        fresh_align = aligned and not prev_aligned

        if state == "WAIT_ALIGN":
            if fresh_align:
                state = "WAIT_OS"

        elif state == "WAIT_OS":
            if not aligned:
                state = "WAIT_ALIGN"   # ribbon broke — reset
            elif k < STOCH_OS:
                state = "WAIT_CROSS"   # pullback started

        elif state == "WAIT_CROSS":
            if not aligned:
                state = "WAIT_ALIGN"   # ribbon broke — reset
            elif k > STOCH_OB:
                state = "WAIT_OS"      # went overbought without trigger — wait again
            elif k > d and k_prev <= d and k > STOCH_OS:
                sig.iloc[i] = True
                state = "WAIT_ALIGN"   # fired — wait for next fresh alignment

        prev_aligned = aligned

    return sig


def ema_stoch_as_v28_filter(df: pd.DataFrame) -> pd.Series:
    """
    EMA+Stoch as additive filter on v2.8+:
    Both v2.8+ signal AND ribbon+stoch signal within ±4 weeks.
    """
    base  = v28_signal(df)
    stoch = ema_stoch_signal(df)

    # Allow stoch signal within 4 weeks before/after v2.8+ signal
    combined = pd.Series(False, index=df.index)
    base_idx  = base[base].index
    stoch_idx = stoch[stoch].index

    for bi in base_idx:
        bi_loc = df.index.get_loc(bi)
        window = df.index[max(0, bi_loc-4): min(len(df), bi_loc+5)]
        if any(si in window for si in stoch_idx):
            combined.iloc[bi_loc] = True

    return combined


VARIANTS = [
    ("v2.8+ BASELINE",          v28_signal),
    ("EMA+Stoch STANDALONE",    ema_stoch_signal),
    ("EMA+Stoch AS v2.8+ FILTER", ema_stoch_as_v28_filter),
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
            pos_val = max(entry_cap * (1 + ret * LEAP_LEV), 0)
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
        n        = len(df),
        wr       = len(wins) / len(df) * 100,
        ret      = ret,
        sharpe   = sh,
        dd       = dd,
        pf       = gp / gl,
        avg_win  = wins["pnl"].mean() if len(wins) else 0,
        avg_loss = loss["pnl"].mean() if len(loss) else 0,
    )


def verdict(m: dict, base: dict) -> str:
    improved = sum([
        m["sharpe"] > base["sharpe"],
        m["wr"]     > base["wr"],
        m["dd"]     > base["dd"],
        m["pf"]     > base["pf"],
    ])
    return f"✓ ADD ({improved}/4)" if improved >= 3 else f"✗ REJ ({improved}/4)"


# ── FULL BACKTEST ─────────────────────────────────────────────────────────────

def run_full_backtest(df: pd.DataFrame):
    print(f"\n{'═'*72}")
    print(f"  FULL BACKTEST — {df.index[0].date()} → {df.index[-1].date()}")
    print(f"{'═'*72}")
    print(f"  {'Variant':<30} {'N':>3} {'WR%':>6} {'Ret%':>7} {'DD%':>7} "
          f"{'Sharpe':>7} {'PF':>5} {'Verdict':>12}")
    print(f"  {'─'*30} {'─'*3} {'─'*6} {'─'*7} {'─'*7} {'─'*7} {'─'*5} {'─'*12}")

    results = []
    for label, fn in VARIANTS:
        t, e = run_backtest(df, fn)
        m = calc_metrics(t, e)
        results.append((label, m))

    base = results[0][1]
    for i, (label, m) in enumerate(results):
        v = "  (baseline)" if i == 0 else f"  {verdict(m, base)}"
        print(f"  {label:<30} {m['n']:>3} {m['wr']:>5.1f}% {m['ret']:>6.1f}% "
              f"{m['dd']:>6.1f}% {m['sharpe']:>7.3f} {m['pf']:>5.2f}{v}")

    # Detail on best non-baseline
    best = max(results[1:], key=lambda x: x[1]["sharpe"], default=None)
    if best:
        label, m = best
        print(f"\n  ── Best non-baseline: {label}")
        print(f"     Trades: {m['n']}  |  Win Rate: {m['wr']:.1f}%  |  "
              f"Return: {m['ret']:.1f}%  |  Sharpe: {m['sharpe']:.3f}")
        print(f"     Avg Win: ${m['avg_win']:.0f}  |  Avg Loss: ${m['avg_loss']:.0f}  |  "
              f"PF: {m['pf']:.2f}  |  Max DD: {m['dd']:.1f}%")


# ── WALK FORWARD ──────────────────────────────────────────────────────────────

def run_walk_forward(df: pd.DataFrame):
    print(f"\n{'═'*72}")
    print(f"  WALK-FORWARD  (IS={WF_IS_WEEKS//4}mo / OOS={WF_OOS_WEEKS//4}mo rolling)")
    print(f"{'═'*72}")

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
        print(f"  {'Variant':<30} {'N':>3} {'WR%':>6} {'Ret%':>7} {'Sharpe':>7} {'ΔSharpe':>9}")
        print(f"  {'─'*64}")

        base_sh = None
        for label, fn in VARIANTS:
            t, e = run_backtest(oos, fn)
            m = calc_metrics(t, e)
            agg[label].append(m)
            if base_sh is None:
                base_sh = m["sharpe"]
                delta_str = "  (baseline)"
            else:
                delta_str = f"  {m['sharpe']-base_sh:>+8.3f}"
            print(f"  {label:<30} {m['n']:>3} {m['wr']:>5.1f}% "
                  f"{m['ret']:>6.1f}% {m['sharpe']:>7.3f}{delta_str}")

        idx += WF_OOS_WEEKS

    if win_num > 0:
        print(f"\n  {'═'*72}")
        print(f"  AGGREGATE OOS  ({win_num} windows)")
        print(f"  {'─'*72}")
        print(f"  {'Variant':<30} {'Avg N':>5} {'Avg WR%':>8} {'Avg Ret%':>9} "
              f"{'Avg Sh':>7} {'Avg DD%':>8} {'Avg PF':>7}")
        print(f"  {'─'*30} {'─'*5} {'─'*8} {'─'*9} {'─'*7} {'─'*8} {'─'*7}")
        for label, _ in VARIANTS:
            ms = agg[label]
            if not ms:
                continue
            print(f"  {label:<30} "
                  f"{np.mean([m['n'] for m in ms]):>5.1f} "
                  f"{np.mean([m['wr'] for m in ms]):>7.1f}% "
                  f"{np.mean([m['ret'] for m in ms]):>8.1f}% "
                  f"{np.mean([m['sharpe'] for m in ms]):>7.3f} "
                  f"{np.mean([m['dd'] for m in ms]):>7.1f}% "
                  f"{np.mean([m['pf'] for m in ms]):>7.2f}")

        best = max(
            [(lb, np.mean([m["sharpe"] for m in agg[lb]])) for lb, _ in VARIANTS],
            key=lambda x: x[1]
        )
        print(f"\n  ══ BEST OOS SHARPE: {best[0]} ({best[1]:.3f}) ══")


# ── STRESS TESTS ──────────────────────────────────────────────────────────────

def run_stress_tests(df: pd.DataFrame):
    print(f"\n{'═'*72}")
    print(f"  STRESS TESTS  ({len(STRESS_PERIODS)} scenarios × {len(VARIANTS)} variants)")
    print(f"{'═'*72}")

    for scenario, start, end in STRESS_PERIODS:
        subset = df[start:end]
        if len(subset) < 20:
            print(f"\n  [{scenario}]  insufficient data")
            continue

        print(f"\n  [{scenario}]")
        print(f"  {'Variant':<30} {'N':>3} {'WR%':>6} {'Ret%':>7} "
              f"{'DD%':>7} {'Sharpe':>7} {'PF':>5}")
        print(f"  {'─'*64}")

        base_sh = None
        for label, fn in VARIANTS:
            t, e = run_backtest(subset, fn)
            m = calc_metrics(t, e)
            if base_sh is None:
                base_sh = m["sharpe"]
                marker = ""
            else:
                delta = m["sharpe"] - base_sh
                marker = f"  {'✓' if delta > 0 else '✗'}{delta:>+.3f}"
            print(f"  {label:<30} {m['n']:>3} {m['wr']:>5.1f}% "
                  f"{m['ret']:>6.1f}% {m['dd']:>6.1f}% "
                  f"{m['sharpe']:>7.3f} {m['pf']:>5.2f}{marker}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="EMA Ribbon + Stoch Reversal × v2.8+ research backtest"
    )
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--stress",       action="store_true")
    parser.add_argument("--all",          action="store_true")
    args = parser.parse_args()

    run_bt = not (args.walk_forward or args.stress) or args.all
    run_wf = args.walk_forward or args.all
    run_st = args.stress or args.all

    print("=" * 72)
    print("  EMA RIBBON (21/34/144) + STOCHASTIC (7,3,3) REVERSAL BACKTEST")
    print("  Standalone + v2.8+ filter comparison")
    print("  Core v2.8+ logic unchanged — Constitution compliant")
    print("=" * 72)

    df = fetch_data()
    df = add_indicators(df)
    print(f"\n  Data: {df.index[0].date()} → {df.index[-1].date()} ({len(df)} weekly bars)")
    print(f"  EMA: {EMA_FAST}/{EMA_MID}/{EMA_SLOW} | Stoch: {STOCH_K},{STOCH_SMOOTH},{STOCH_SMOOTH}")
    print(f"  Oversold: <{STOCH_OS} | Overbought: >{STOCH_OB} | First pullback only\n")

    if run_bt:
        run_full_backtest(df)
    if run_wf:
        run_walk_forward(df)
    if run_st:
        run_stress_tests(df)

    print(f"\n{'═'*72}")
    print("  RESEARCH NOTE: LOCAL yfinance sim. MSTR LEAP leverage ~4x.")
    print("  EMA+Stoch runs on BTC weekly. Entry executes on MSTR LEAP.")
    print("  Do NOT deploy without QC API walk-forward confirmation.")
    print(f"{'═'*72}\n")


if __name__ == "__main__":
    main()
