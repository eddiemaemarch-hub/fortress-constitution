#!/usr/bin/env python3
"""
backtest_ha_rsi_v28plus.py
Heikin Ashi RSI Oscillator filter — research test against v2.8+ MSTR LEAP strategy.

Tests whether HA RSI as an entry confirmation filter improves v2.8+ performance.
v2.8+ core entry/exit logic is NOT modified — HA RSI is tested as an additive filter only.
Constitution Article: research only until Commander approves adding to live signal.

Usage:
    python3 backtest_ha_rsi_v28plus.py                  # backtest only
    python3 backtest_ha_rsi_v28plus.py --walk-forward   # walk-forward only
    python3 backtest_ha_rsi_v28plus.py --stress         # stress tests only
    python3 backtest_ha_rsi_v28plus.py --all            # everything
"""

import argparse
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

warnings.filterwarnings("ignore")

# ── CONFIG (do not touch v2.8+ params) ────────────────────────────────────────
START_DATE        = "2015-01-01"
END_DATE          = datetime.now().strftime("%Y-%m-%d")
MA_200W_PERIOD    = 200        # weeks — v2.8+ locked
TRAIL_STOP_PCT    = 0.65       # 65% of HWM — v2.8+ locked
POSITION_PCT      = 0.25       # 25% NLV per entry — v2.8+ locked
LEAP_LEVERAGE     = 4.0        # approx MSTR LEAP vs stock leverage

RSI_PERIOD        = 14         # HA RSI period
HA_OVERSOLD       = 30         # green zone threshold
HA_OVERBOUGHT     = 70         # red zone threshold
HA_LOOKBACK       = 3          # weeks to allow HA RSI signal to precede v2.8+

WF_IS_WEEKS       = 24 * 4    # 24-month in-sample
WF_OOS_WEEKS      = 6  * 4    # 6-month out-of-sample
INITIAL_CAPITAL   = 10_000.0


# ── DATA ──────────────────────────────────────────────────────────────────────

def fetch_data() -> pd.DataFrame:
    print("  Fetching BTC-USD weekly...")
    btc = yf.download("BTC-USD", start=START_DATE, end=END_DATE,
                       interval="1wk", progress=False, auto_adjust=True)
    print("  Fetching MSTR weekly...")
    mstr = yf.download("MSTR", start=START_DATE, end=END_DATE,
                        interval="1wk", progress=False, auto_adjust=True)

    # Handle yfinance multi-level columns
    def extract(df, col):
        if isinstance(df.columns, pd.MultiIndex):
            return df[col].iloc[:, 0]
        return df[col]

    data = pd.DataFrame({
        "btc_open":   extract(btc, "Open"),
        "btc_close":  extract(btc, "Close"),
        "mstr_open":  extract(mstr, "Open"),
        "mstr_close": extract(mstr, "Close"),
    }).dropna()

    return data


# ── INDICATORS ────────────────────────────────────────────────────────────────

def add_indicators(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()

    # 200W SMA on BTC
    df["ma_200w"] = df["btc_close"].rolling(MA_200W_PERIOD, min_periods=50).mean()
    df["below_200w"] = df["btc_close"] < df["ma_200w"]
    df["btc_green"] = df["btc_close"] > df["btc_open"]

    # RSI
    delta = df["btc_close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # Heikin Ashi transformation on RSI
    ha_close = df["rsi"].copy()
    ha_open  = df["rsi"].copy()
    for i in range(1, len(df)):
        ha_close.iloc[i] = (df["rsi"].iloc[i] + df["rsi"].iloc[i - 1]) / 2
        ha_open.iloc[i]  = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2
    df["ha_rsi_close"] = ha_close
    df["ha_rsi_open"]  = ha_open

    df["ha_green_candle"] = df["ha_rsi_close"] > df["ha_rsi_open"]
    df["ha_red_candle"]   = df["ha_rsi_close"] < df["ha_rsi_open"]
    df["ha_in_green_zone"]= df["ha_rsi_close"] < HA_OVERSOLD

    return df


# ── SIGNALS ───────────────────────────────────────────────────────────────────

def v28_entry_signal(df: pd.DataFrame) -> pd.Series:
    """
    Base v2.8+ signal:
      - BTC dipped below 200W SMA at some point
      - Current week: green candle (reclaim) AND not below 200W
    Reset dipped flag after signal fires or after 12 clean weeks above.
    """
    signals = pd.Series(False, index=df.index)
    dipped = False
    for i in range(MA_200W_PERIOD, len(df)):
        if df["below_200w"].iloc[i]:
            dipped = True
        if dipped and not df["below_200w"].iloc[max(0, i - 12):i].any():
            dipped = False  # 12 clean weeks above = reset
        if dipped and df["btc_green"].iloc[i] and not df["below_200w"].iloc[i]:
            signals.iloc[i] = True
            dipped = False
    return signals


def ha_rsi_filter(df: pd.DataFrame) -> pd.Series:
    """
    HA RSI entry filter:
      - HA RSI was in oversold zone within last HA_LOOKBACK weeks
      - Current or recent candle flipped green after red
    Looser than a pure same-bar filter to accommodate the known RSI lag.
    """
    filt = pd.Series(False, index=df.index)
    for i in range(1, len(df)):
        window = slice(max(0, i - HA_LOOKBACK), i + 1)
        was_in_zone   = df["ha_in_green_zone"].iloc[window].any()
        green_flip    = (df["ha_green_candle"].iloc[i]
                         and df["ha_red_candle"].iloc[i - 1])
        recent_flip   = df["ha_green_candle"].iloc[max(0, i - HA_LOOKBACK):i].any()
        if was_in_zone and (green_flip or recent_flip):
            filt.iloc[i] = True
    return filt


# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────

def run_backtest(df: pd.DataFrame, use_ha_rsi: bool = False) -> tuple:
    base_sig = v28_entry_signal(df)
    if use_ha_rsi:
        filt     = ha_rsi_filter(df)
        entries  = base_sig & filt
    else:
        entries  = base_sig

    capital      = INITIAL_CAPITAL
    equity       = [capital]
    trades       = []
    in_trade     = False
    entry_price  = 0.0
    entry_cap    = 0.0
    hwm          = 0.0
    entry_date   = None

    for i in range(len(df)):
        bar   = df.index[i]
        mstr  = float(df["mstr_close"].iloc[i])

        if not in_trade:
            if entries.iloc[i]:
                in_trade    = True
                entry_price = mstr
                entry_cap   = capital * POSITION_PCT
                hwm         = entry_cap

        else:
            ret      = (mstr - entry_price) / entry_price if entry_price > 0 else 0
            pos_val  = entry_cap * (1 + ret * LEAP_LEVERAGE)
            pos_val  = max(pos_val, 0)

            if pos_val > hwm:
                hwm = pos_val

            trail_lvl = hwm * TRAIL_STOP_PCT
            ten_x     = entry_cap * 10

            exit_reason = None
            if pos_val <= trail_lvl:
                exit_reason = "trail_stop"
            elif pos_val >= ten_x:
                exit_reason = "10x_target"

            if exit_reason:
                pnl      = pos_val - entry_cap
                capital += pnl
                trades.append({
                    "entry_date":  entry_date,
                    "exit_date":   bar,
                    "mstr_ret":    ret,
                    "lev_ret":     ret * LEAP_LEVERAGE,
                    "pnl":         pnl,
                    "win":         pnl > 0,
                    "exit_reason": exit_reason,
                })
                in_trade = False
                hwm      = 0.0

            entry_date = entry_date or bar  # set on first bar after entry

        equity.append(capital)

    return trades, equity


# ── METRICS ───────────────────────────────────────────────────────────────────

def metrics(trades: list, equity: list, label: str) -> dict:
    eq = pd.Series(equity, dtype=float)
    if not trades:
        return dict(label=label, n=0, wr=0, ret=0, sharpe=0, dd=0,
                    avg_win=0, avg_loss=0, pf=0)
    df    = pd.DataFrame(trades)
    wins  = df[df["win"]]
    loss  = df[~df["win"]]
    total_ret  = (eq.iloc[-1] - eq.iloc[0]) / eq.iloc[0] * 100
    rets  = eq.pct_change().dropna()
    sharpe = (rets.mean() / rets.std() * np.sqrt(52)) if rets.std() > 0 else 0
    roll_max = eq.cummax()
    max_dd   = ((eq - roll_max) / roll_max * 100).min()
    gp = wins["pnl"].sum() if len(wins) else 0
    gl = abs(loss["pnl"].sum()) if len(loss) else 1e-9
    return dict(
        label    = label,
        n        = len(df),
        wr       = len(wins) / len(df) * 100,
        ret      = total_ret,
        sharpe   = sharpe,
        dd       = max_dd,
        avg_win  = wins["pnl"].mean() if len(wins) else 0,
        avg_loss = loss["pnl"].mean() if len(loss) else 0,
        pf       = gp / gl,
    )


def print_metrics(m: dict):
    print(f"\n  ┌─ {m['label']}")
    print(f"  │  Trades:        {m['n']}")
    print(f"  │  Win Rate:      {m['wr']:.1f}%")
    print(f"  │  Total Return:  {m['ret']:.1f}%")
    print(f"  │  Sharpe:        {m['sharpe']:.3f}")
    print(f"  │  Max Drawdown:  {m['dd']:.1f}%")
    print(f"  │  Avg Win $:     ${m['avg_win']:.0f}")
    print(f"  │  Avg Loss $:    ${m['avg_loss']:.0f}")
    print(f"  └  Profit Factor: {m['pf']:.2f}")


def compare(m_base: dict, m_ha: dict):
    print(f"\n  {'─'*52}")
    print(f"  DELTA  (HA RSI vs Baseline)")
    print(f"  {'─'*52}")
    print(f"  Trades filtered:   {m_base['n'] - m_ha['n']}")
    print(f"  Win Rate:          {m_ha['wr']  - m_base['wr']:+.1f}%")
    print(f"  Total Return:      {m_ha['ret'] - m_base['ret']:+.1f}%")
    print(f"  Sharpe:            {m_ha['sharpe'] - m_base['sharpe']:+.3f}")
    print(f"  Max Drawdown:      {m_ha['dd']  - m_base['dd']:+.1f}%")
    print(f"  Profit Factor:     {m_ha['pf']  - m_base['pf']:+.2f}")

    improved = sum([
        m_ha['sharpe'] > m_base['sharpe'],
        m_ha['wr']     > m_base['wr'],
        m_ha['dd']     > m_base['dd'],   # less negative = better
        m_ha['pf']     > m_base['pf'],
    ])
    verdict = "ADD AS FILTER" if improved >= 3 else "REJECT"
    print(f"\n  ══ VERDICT: {verdict} ({improved}/4 metrics improved) ══")
    if verdict == "ADD AS FILTER":
        print("  HA RSI improves 3+ metrics → worth adding as awareness filter.")
        print("  Requires Commander approval + constitution note before live use.")
    else:
        print("  HA RSI does not consistently improve v2.8+ → do not add.")


# ── WALK FORWARD ──────────────────────────────────────────────────────────────

def walk_forward(df: pd.DataFrame):
    print(f"\n{'═'*54}")
    print(f"  WALK-FORWARD  (IS={WF_IS_WEEKS//4}mo / OOS={WF_OOS_WEEKS//4}mo rolling)")
    print(f"{'═'*54}")

    base_agg, ha_agg = [], []
    idx = 0
    win_num = 0

    while idx + WF_IS_WEEKS + WF_OOS_WEEKS <= len(df):
        oos = df.iloc[idx + WF_IS_WEEKS : idx + WF_IS_WEEKS + WF_OOS_WEEKS]
        if len(oos) < 10:
            break

        t_b, e_b = run_backtest(oos, use_ha_rsi=False)
        t_h, e_h = run_backtest(oos, use_ha_rsi=True)
        m_b = metrics(t_b, e_b, "base")
        m_h = metrics(t_h, e_h, "ha")

        p1 = df.index[idx + WF_IS_WEEKS].strftime("%Y-%m")
        p2 = df.index[min(idx + WF_IS_WEEKS + WF_OOS_WEEKS - 1, len(df) - 1)].strftime("%Y-%m")
        win_num += 1

        print(f"\n  Window {win_num}: OOS {p1} → {p2}")
        print(f"  {'Metric':<18} {'Baseline':>10} {'HA RSI':>10} {'Δ':>8}")
        print(f"  {'─'*48}")
        for key, label, fmt in [
            ("n",      "Trades",      "{:>10.0f}"),
            ("wr",     "Win Rate %",  "{:>9.1f}%"),
            ("ret",    "Return %",    "{:>9.1f}%"),
            ("sharpe", "Sharpe",      "{:>10.3f}"),
            ("dd",     "Max DD %",    "{:>9.1f}%"),
            ("pf",     "Prof Factor", "{:>10.2f}"),
        ]:
            bv, hv = m_b[key], m_h[key]
            delta  = hv - bv
            print(f"  {label:<18} {fmt.format(bv)} {fmt.format(hv)} {delta:>+8.2f}")

        base_agg.append(m_b)
        ha_agg.append(m_h)
        idx += WF_OOS_WEEKS

    if base_agg:
        print(f"\n  {'═'*54}")
        print(f"  AGGREGATE  ({win_num} OOS windows)")
        print(f"  {'─'*54}")
        for key, label in [("wr","Win Rate %"),("ret","Return %"),
                            ("sharpe","Sharpe"),("dd","Max DD %"),("pf","Prof Factor")]:
            avg_b = np.mean([r[key] for r in base_agg])
            avg_h = np.mean([r[key] for r in ha_agg])
            print(f"  {label:<18}  Base {avg_b:>8.2f}  |  HA {avg_h:>8.2f}  |  Δ {avg_h-avg_b:>+7.2f}")


# ── STRESS TESTS ──────────────────────────────────────────────────────────────

STRESS_PERIODS = [
    ("2018 Bear",          "2018-01-01", "2018-12-31"),
    ("2019 Chop/Recovery", "2019-01-01", "2019-12-31"),
    ("2020 COVID Crash",   "2020-01-01", "2020-12-31"),
    ("2021 Bull Peak",     "2021-01-01", "2021-12-31"),
    ("2022 Bear",          "2022-01-01", "2022-12-31"),
    ("2023 Recovery",      "2023-01-01", "2023-12-31"),
    ("2024 Bull Run",      "2024-01-01", "2024-12-31"),
    ("Full History",       START_DATE,   END_DATE),
]


def stress_tests(df: pd.DataFrame):
    print(f"\n{'═'*54}")
    print(f"  STRESS TESTS  ({len(STRESS_PERIODS)} scenarios)")
    print(f"{'═'*54}")
    print(f"\n  {'Scenario':<24} {'N':>3} {'WR%':>6} {'Ret%':>7} {'DD%':>7} "
          f"{'Sh':>6}  |  {'N':>3} {'WR%':>6} {'Ret%':>7} {'DD%':>7} {'Sh':>6}  {'Δ':>5}")
    print(f"  {'─'*24} {'─'*3} {'─'*6} {'─'*7} {'─'*7} {'─'*6}  "
          f"{'─'*3} {'─'*6} {'─'*7} {'─'*7} {'─'*6}  {'─'*5}")
    print(f"  {'(Baseline)':>55}  {'(HA RSI)':>35}")

    for label, start, end in STRESS_PERIODS:
        subset = df[start:end]
        if len(subset) < 15:
            print(f"  {label:<24}  insufficient data")
            continue

        t_b, e_b = run_backtest(subset, use_ha_rsi=False)
        t_h, e_h = run_backtest(subset, use_ha_rsi=True)
        m_b = metrics(t_b, e_b, label)
        m_h = metrics(t_h, e_h, label)

        delta_sharpe = m_h["sharpe"] - m_b["sharpe"]
        mark = "✓" if delta_sharpe > 0 else "✗"

        print(f"  {label:<24} {m_b['n']:>3} {m_b['wr']:>5.1f}% {m_b['ret']:>6.1f}% "
              f"{m_b['dd']:>6.1f}% {m_b['sharpe']:>6.2f}  |  "
              f"{m_h['n']:>3} {m_h['wr']:>5.1f}% {m_h['ret']:>6.1f}% "
              f"{m_h['dd']:>6.1f}% {m_h['sharpe']:>6.2f}  {mark}{delta_sharpe:>+4.2f}")

    print(f"\n  ✓ = HA RSI improved Sharpe  |  ✗ = HA RSI reduced Sharpe")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="HA RSI × v2.8+ research backtest")
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--stress",       action="store_true")
    parser.add_argument("--all",          action="store_true")
    args = parser.parse_args()

    run_bt = not (args.walk_forward or args.stress) or args.all
    run_wf = args.walk_forward or args.all
    run_st = args.stress or args.all

    print("=" * 54)
    print("  HA RSI OSCILLATOR × v2.8+ RESEARCH BACKTEST")
    print("  Core v2.8+ logic unchanged — filter tested additively")
    print("=" * 54)

    df = fetch_data()
    df = add_indicators(df)
    print(f"\n  Data: {df.index[0].date()} → {df.index[-1].date()} ({len(df)} weekly bars)\n")

    if run_bt:
        print("=" * 54)
        print("  FULL BACKTEST COMPARISON")
        print("=" * 54)
        t_b, e_b = run_backtest(df, use_ha_rsi=False)
        t_h, e_h = run_backtest(df, use_ha_rsi=True)
        m_b = metrics(t_b, e_b, "v2.8+ BASELINE  (no HA RSI filter)")
        m_h = metrics(t_h, e_h, "v2.8+ + HA RSI  (additive filter)")
        print_metrics(m_b)
        print_metrics(m_h)
        compare(m_b, m_h)

    if run_wf:
        walk_forward(df)

    if run_st:
        stress_tests(df)

    print(f"\n{'═'*54}")
    print("  RESEARCH NOTE: Results are LOCAL yfinance sim.")
    print("  MSTR LEAP leverage approximated at 4x stock.")
    print("  Do NOT deploy without QC API confirmation.")
    print(f"{'═'*54}\n")


if __name__ == "__main__":
    main()
