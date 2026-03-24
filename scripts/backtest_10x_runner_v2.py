"""
Backtest: Rudy 10x Momentum Runner v2
Replicates PineScript logic on high-beta moonshot tickers.
EMA stack (10/21/50) + MACD + RSI + SPY filter.
Exits: ATR stop, trend break, stack break, max bars, HWM trail.
Tiered profit taking: 25% at +100%, +300%, +500%.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

# ── Config ──────────────────────────────────────────
INITIAL_CAPITAL = 10_000
POSITION_PCT = 0.08  # 8% of equity per trade
COMMISSION_PCT = 0.001  # 0.1%

# Indicators
EMA_FAST, EMA_MID, EMA_SLOW = 10, 21, 50
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9
ATR_LEN = 14
ATR_MULT_SL = 1.8
PROFIT_TARGET = 0.15  # 15%
TRAIL_ACT = 0.08  # 8%
TRAIL_OFFSET = 0.04  # 4%
MAX_BARS = 40
HWM_LOOKBACK = 252
HWM_TRAIL_PCT = 0.30  # 30% — floor

# Profit tiers
TIERS = [(100, 0.25), (300, 0.25), (500, 0.25)]  # (gain%, sell%)

# Moonshot universe
TICKERS = ["IONQ", "RGTI", "RKLB", "JOBY", "OKLO", "ACHR", "LUNR", "SMR", "ASTS"]
SPY_TICKER = "SPY"
START_DATE = "2022-01-01"
END_DATE = "2025-12-31"


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_macd(series, fast=12, slow=26, sig=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=sig, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def backtest_ticker(ticker, df, spy_df):
    """Run backtest on a single ticker."""
    if df is None or len(df) < EMA_SLOW + 10:
        return []

    # Indicators
    df = df.copy()
    df["ema_fast"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_mid"] = df["Close"].ewm(span=EMA_MID, adjust=False).mean()
    df["ema_slow"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["rsi"] = compute_rsi(df["Close"], RSI_PERIOD)
    _, _, df["macd_hist"] = compute_macd(df["Close"], MACD_FAST, MACD_SLOW, MACD_SIG)

    # ATR
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_LEN).mean()

    # HWM
    df["hwm"] = df["High"].rolling(HWM_LOOKBACK, min_periods=1).max()
    df["hwm_stop"] = df["hwm"] * (1 - HWM_TRAIL_PCT)

    # SPY filter
    spy_ema50 = spy_df["Close"].ewm(span=50, adjust=False).mean()
    spy_bull = spy_df["Close"] > spy_ema50

    # Stacked
    df["stacked"] = (df["ema_fast"] > df["ema_mid"]) & (df["ema_mid"] > df["ema_slow"])

    trades = []
    in_trade = False
    entry_price = 0
    entry_date = None
    entry_bar = 0
    qty = 0
    original_qty = 0
    atr_stop = 0
    trail_active = False
    trail_high = 0
    tiers_hit = [False, False, False]

    for i in range(EMA_SLOW + 10, len(df)):
        date = df.index[i]
        close = df["Close"].iloc[i]
        high = df["High"].iloc[i]

        # SPY filter
        spy_ok = True
        if date in spy_bull.index:
            spy_ok = spy_bull.loc[date] if date in spy_bull.index else True

        if in_trade:
            bars_held = i - entry_bar
            gain_pct = (close - entry_price) / entry_price * 100

            # Update trail high
            if high > trail_high:
                trail_high = high

            # Check exits
            exit_reason = None
            exit_price = close

            # ATR stop
            if close <= atr_stop:
                exit_reason = "ATR Stop"
                exit_price = atr_stop

            # Trailing stop (activates at +8%, trails 4%)
            elif trail_active and close < trail_high * (1 - TRAIL_OFFSET):
                exit_reason = "Trail Stop"
                exit_price = trail_high * (1 - TRAIL_OFFSET)
            elif not trail_active and gain_pct >= TRAIL_ACT * 100:
                trail_active = True

            # Profit target (15% safety net)
            elif gain_pct >= PROFIT_TARGET * 100:
                exit_reason = "Profit Target"

            # Trend broken
            elif close < df["ema_slow"].iloc[i] and df["Close"].iloc[i-1] >= df["ema_slow"].iloc[i-1]:
                exit_reason = "Trend Lost"

            # Stack broken
            elif df["ema_mid"].iloc[i] < df["ema_slow"].iloc[i]:
                exit_reason = "Stack Broken"

            # Max bars
            elif bars_held >= MAX_BARS:
                exit_reason = "Max Hold"

            # HWM trail
            elif close < df["hwm_stop"].iloc[i]:
                exit_reason = "HWM Trail"

            # Tiered profit taking (partial sells)
            if exit_reason is None:
                for ti, (tier_pct, tier_sell) in enumerate(TIERS):
                    if gain_pct >= tier_pct and not tiers_hit[ti] and qty > 1:
                        sell_qty = max(1, int(original_qty * tier_sell))
                        sell_qty = min(sell_qty, qty - 1)
                        partial_pnl = sell_qty * (close - entry_price)
                        trades.append({
                            "ticker": ticker,
                            "entry_date": entry_date,
                            "exit_date": date,
                            "entry_price": entry_price,
                            "exit_price": close,
                            "qty": sell_qty,
                            "pnl": partial_pnl,
                            "return_pct": gain_pct,
                            "reason": f"PT{ti+1} +{tier_pct}%",
                            "partial": True,
                        })
                        qty -= sell_qty
                        tiers_hit[ti] = True

            if exit_reason:
                pnl = qty * (exit_price - entry_price)
                ret_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "ticker": ticker,
                    "entry_date": entry_date,
                    "exit_date": date,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "qty": qty,
                    "pnl": pnl,
                    "return_pct": ret_pct,
                    "reason": exit_reason,
                    "partial": False,
                })
                in_trade = False
                qty = 0

        else:
            # Entry conditions
            stacked = df["stacked"].iloc[i]
            above_ema = close > df["ema_fast"].iloc[i]
            macd_bull = df["macd_hist"].iloc[i] > 0
            rsi_val = df["rsi"].iloc[i]
            rsi_ok = 35 < rsi_val < 78

            if stacked and above_ema and macd_bull and rsi_ok and spy_ok:
                entry_price = close
                entry_date = date
                entry_bar = i
                qty = max(1, int((INITIAL_CAPITAL * POSITION_PCT) / close))
                original_qty = qty
                atr_stop = close - df["atr"].iloc[i] * ATR_MULT_SL
                trail_active = False
                trail_high = close
                tiers_hit = [False, False, False]
                in_trade = True

    return trades


def main():
    print("=" * 70)
    print("  RUDY 10X MOMENTUM RUNNER v2 — BACKTEST")
    print(f"  Universe: {', '.join(TICKERS)}")
    print(f"  Period: {START_DATE} → {END_DATE}")
    print(f"  Capital: ${INITIAL_CAPITAL:,} | Position: {POSITION_PCT*100}% per trade")
    print("=" * 70)

    # Download data
    all_tickers = TICKERS + [SPY_TICKER]
    print(f"\nDownloading data for {len(all_tickers)} tickers...")
    data = yf.download(all_tickers, start=START_DATE, end=END_DATE, group_by="ticker", progress=False)

    spy_df = data[SPY_TICKER].copy() if SPY_TICKER in data.columns.get_level_values(0) else None

    all_trades = []
    for ticker in TICKERS:
        try:
            if ticker in data.columns.get_level_values(0):
                df = data[ticker].dropna()
            else:
                df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
            trades = backtest_ticker(ticker, df, spy_df)
            all_trades.extend(trades)
            wins = [t for t in trades if t["pnl"] > 0 and not t["partial"]]
            losses = [t for t in trades if t["pnl"] <= 0 and not t["partial"]]
            full_trades = [t for t in trades if not t["partial"]]
            if full_trades:
                total_pnl = sum(t["pnl"] for t in trades)
                best = max(trades, key=lambda t: t["return_pct"])
                print(f"\n  {ticker}: {len(full_trades)} trades | "
                      f"W/L: {len(wins)}/{len(losses)} | "
                      f"P&L: ${total_pnl:,.0f} | "
                      f"Best: +{best['return_pct']:.1f}% ({best['reason']})")
            else:
                print(f"\n  {ticker}: 0 trades")
        except Exception as e:
            print(f"\n  {ticker}: ERROR — {e}")

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    full_trades = [t for t in all_trades if not t["partial"]]
    partial_trades = [t for t in all_trades if t["partial"]]

    if not all_trades:
        print("  No trades generated.")
        return

    total_pnl = sum(t["pnl"] for t in all_trades)
    wins = [t for t in full_trades if t["pnl"] > 0]
    losses = [t for t in full_trades if t["pnl"] <= 0]
    win_rate = len(wins) / len(full_trades) * 100 if full_trades else 0

    print(f"  Total trades: {len(full_trades)} full + {len(partial_trades)} partial exits")
    print(f"  Win rate: {win_rate:.1f}% ({len(wins)}W / {len(losses)}L)")
    print(f"  Total P&L: ${total_pnl:,.2f}")
    print(f"  Return: {total_pnl/INITIAL_CAPITAL*100:+.1f}%")
    print(f"  Final equity: ${INITIAL_CAPITAL + total_pnl:,.2f}")

    if wins:
        avg_win = np.mean([t["return_pct"] for t in wins])
        print(f"  Avg win: +{avg_win:.1f}%")
    if losses:
        avg_loss = np.mean([t["return_pct"] for t in losses])
        print(f"  Avg loss: {avg_loss:.1f}%")

    best = max(all_trades, key=lambda t: t["return_pct"])
    worst = min(all_trades, key=lambda t: t["return_pct"])
    print(f"\n  Best trade:  {best['ticker']} +{best['return_pct']:.1f}% "
          f"({best['entry_date'].strftime('%Y-%m-%d')} → {best['exit_date'].strftime('%Y-%m-%d')}) [{best['reason']}]")
    print(f"  Worst trade: {worst['ticker']} {worst['return_pct']:.1f}% "
          f"({worst['entry_date'].strftime('%Y-%m-%d')} → {worst['exit_date'].strftime('%Y-%m-%d')}) [{worst['reason']}]")

    # Trade log
    print("\n" + "-" * 70)
    print("  TRADE LOG (full exits)")
    print("-" * 70)
    for t in sorted(full_trades, key=lambda x: x["entry_date"]):
        print(f"  {t['ticker']:6s} | {t['entry_date'].strftime('%Y-%m-%d')} → {t['exit_date'].strftime('%Y-%m-%d')} | "
              f"${t['entry_price']:.2f} → ${t['exit_price']:.2f} | "
              f"{t['return_pct']:+.1f}% | ${t['pnl']:+,.0f} | {t['reason']}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
