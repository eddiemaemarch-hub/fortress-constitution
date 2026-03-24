#!/usr/bin/env python3
"""
RUDY v2.0 — ETF Strategy Backtester
Backtests all 4 ETF income strategies using yfinance historical data.
Simulates option premium income with realistic approximations.

Strategies:
  1. SCHD Wheel — monthly put/call premium ~1.5% of strike
  2. SPY PMCC — monthly short call premium ~1% of LEAP cost
  3. QQQ Collar — net debit ~0.3%/month for protection
  4. TQQQ Momentum — directional calls/puts with 4x leverage approx
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [BACKTEST-ETF] {msg}"
    print(line)
    with open(os.path.join(LOG_DIR, "backtest_etf.log"), "a") as f:
        f.write(line + "\n")


def fetch_data(symbol, start="2010-01-01", end="2025-12-31"):
    """Fetch historical daily data from yfinance."""
    log(f"Fetching {symbol} data from {start} to {end}")
    tk = yf.Ticker(symbol)
    df = tk.history(start=start, end=end, interval="1d")
    if df.empty:
        log(f"WARNING: No data for {symbol}")
        return None
    log(f"  Got {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")
    return df


def compute_rsi(series, period=14):
    """Compute RSI."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def backtest_wheel(df, start_capital=25_000):
    """
    SCHD Wheel Strategy backtest.
    Sell monthly puts at ~30 delta (5% OTM).
    Premium approximation: 1.5% of strike per month.
    If price drops below strike -> assigned, then sell calls.
    """
    log("Running SCHD Wheel backtest...")
    capital = start_capital
    shares = 0
    peak = capital
    max_dd = 0
    monthly_returns = []
    wins = 0
    total_trades = 0

    close = df["Close"].values
    dates = df.index

    # Monthly rebalance
    month_start_capital = capital
    current_month = dates[0].month

    for i in range(50, len(df)):
        price = close[i]
        month = dates[i].month

        if month != current_month:
            # End of month — settle and open new position
            monthly_ret = (capital + shares * price - month_start_capital) / month_start_capital
            monthly_returns.append(monthly_ret)
            total_trades += 1
            if monthly_ret > 0:
                wins += 1

            current_month = month
            month_start_capital = capital + shares * price

            if shares == 0:
                # Sell cash-secured put: strike = 95% of current price
                strike = price * 0.95
                premium = strike * 0.015  # 1.5% monthly premium
                contracts = min(2, int(capital / (strike * 100)))

                if contracts > 0:
                    capital += premium * contracts * 100  # collect premium

                    # Check if assigned (price dropped below strike)
                    if price < strike:
                        # Assigned: buy shares at strike
                        cost = strike * contracts * 100
                        if cost <= capital:
                            capital -= cost
                            shares += contracts * 100
            else:
                # Have shares: sell covered calls at 105% of price
                strike = price * 1.05
                premium = strike * 0.012  # 1.2% premium for calls
                contracts = shares // 100

                if contracts > 0:
                    capital += premium * contracts * 100

                    # Check if called away (price rose above strike)
                    if price > strike:
                        capital += strike * contracts * 100
                        shares -= contracts * 100

        # Track drawdown
        total_value = capital + shares * price
        peak = max(peak, total_value)
        dd = (total_value - peak) / peak
        max_dd = min(max_dd, dd)

    end_value = capital + shares * close[-1]
    return _compute_stats("SCHD Wheel", start_capital, end_value, monthly_returns,
                          max_dd, wins, total_trades, df)


def backtest_pmcc(df, start_capital=20_000):
    """
    SPY PMCC Strategy backtest.
    Buy deep ITM LEAP (simulate as 0.80 delta exposure).
    Sell monthly OTM calls for ~1% of LEAP cost.
    """
    log("Running SPY PMCC backtest...")
    capital = start_capital
    leap_value = 0
    leap_delta = 0.80
    leap_cost_basis = 0
    peak = capital
    max_dd = 0
    monthly_returns = []
    wins = 0
    total_trades = 0

    close = df["Close"].values
    dates = df.index
    current_month = dates[0].month
    month_start = capital

    for i in range(50, len(df)):
        price = close[i]
        month = dates[i].month

        if month != current_month:
            current_month = month

            if leap_value == 0 and capital > 5000:
                # Buy LEAP: cost ~15% of 100 shares
                leap_cost = price * 0.15 * 100
                num_leaps = min(2, int(capital * 0.8 / leap_cost))
                if num_leaps > 0:
                    leap_cost_basis = leap_cost * num_leaps
                    capital -= leap_cost_basis
                    leap_value = leap_cost_basis

            if leap_value > 0:
                # LEAP P&L approximation: delta * price change
                if i > 50:
                    price_change = close[i] - close[i - 21] if i >= 21 else 0
                    leap_pnl = price_change * leap_delta * (leap_cost_basis / (price * 0.15 * 100))
                    leap_value += leap_pnl

                # Sell monthly call: ~1% of LEAP cost
                call_premium = leap_cost_basis * 0.01
                capital += call_premium

                # Stop loss: close if LEAP drops 30%
                if leap_value < leap_cost_basis * 0.70:
                    capital += max(0, leap_value)
                    leap_value = 0
                    leap_cost_basis = 0

            total_value = capital + leap_value
            monthly_ret = (total_value - month_start) / month_start if month_start > 0 else 0
            monthly_returns.append(monthly_ret)
            total_trades += 1
            if monthly_ret > 0:
                wins += 1
            month_start = total_value

        total_value = capital + leap_value
        peak = max(peak, total_value)
        dd = (total_value - peak) / peak if peak > 0 else 0
        max_dd = min(max_dd, dd)

    end_value = capital + leap_value
    return _compute_stats("SPY PMCC", start_capital, end_value, monthly_returns,
                          max_dd, wins, total_trades, df)


def backtest_collar(df, start_capital=15_000):
    """
    QQQ Growth Collar backtest.
    LEAP call (70 delta) + sell call (25 delta) + buy put (15 delta).
    Net monthly cost ~0.3% for protection.
    """
    log("Running QQQ Collar backtest...")
    capital = start_capital
    leap_value = 0
    leap_delta = 0.70
    leap_cost_basis = 0
    peak = capital
    max_dd = 0
    monthly_returns = []
    wins = 0
    total_trades = 0

    close = df["Close"].values
    dates = df.index
    current_month = dates[0].month
    month_start = capital

    for i in range(50, len(df)):
        price = close[i]
        month = dates[i].month

        if month != current_month:
            current_month = month

            if leap_value == 0 and capital > 3000:
                # Buy LEAP call
                leap_cost = price * 0.12 * 100
                num_leaps = min(2, int(capital * 0.7 / leap_cost))
                if num_leaps > 0:
                    leap_cost_basis = leap_cost * num_leaps
                    capital -= leap_cost_basis
                    leap_value = leap_cost_basis

            if leap_value > 0:
                # LEAP P&L
                if i > 50:
                    price_change = close[i] - close[i - 21] if i >= 21 else 0
                    leap_pnl = price_change * leap_delta * (leap_cost_basis / (price * 0.12 * 100))
                    leap_value += leap_pnl

                # Collar: sell call premium - buy put premium = net ~0.3% cost
                call_premium = leap_cost_basis * 0.008  # ~0.8% from selling call
                put_cost = leap_cost_basis * 0.005  # ~0.5% for buying put
                net_income = call_premium - put_cost
                capital += net_income

                # Collar protection: limit downside to ~10% per month
                if i >= 21:
                    monthly_move = (close[i] - close[i - 21]) / close[i - 21]
                    if monthly_move < -0.10:
                        # Put kicks in, limiting loss
                        excess_loss = (monthly_move + 0.10) * leap_cost_basis * 0.5
                        leap_value -= excess_loss  # reduce the excess loss

                # Close if LEAP < 90 DTE equivalent (every 12 months, roll)
                if leap_value < leap_cost_basis * 0.50:
                    capital += max(0, leap_value)
                    leap_value = 0
                    leap_cost_basis = 0

            total_value = capital + leap_value
            monthly_ret = (total_value - month_start) / month_start if month_start > 0 else 0
            monthly_returns.append(monthly_ret)
            total_trades += 1
            if monthly_ret > 0:
                wins += 1
            month_start = total_value

        total_value = capital + leap_value
        peak = max(peak, total_value)
        dd = (total_value - peak) / peak if peak > 0 else 0
        max_dd = min(max_dd, dd)

    end_value = capital + leap_value
    return _compute_stats("QQQ Collar", start_capital, end_value, monthly_returns,
                          max_dd, wins, total_trades, df)


def backtest_tqqq_momentum(df_tqqq, df_qqq, start_capital=10_000):
    """
    TQQQ Momentum backtest.
    Buy calls when TQQQ > 50 EMA and QQQ RSI > 50.
    Buy puts when TQQQ < 50 EMA and QQQ RSI < 40.
    4x leverage approximation via options.
    """
    log("Running TQQQ Momentum backtest...")

    # Align dataframes
    common_idx = df_tqqq.index.intersection(df_qqq.index)
    df_tqqq = df_tqqq.loc[common_idx]
    df_qqq = df_qqq.loc[common_idx]

    capital = start_capital
    positions = []  # list of {direction, entry_price, cost, leverage}
    peak = capital
    max_dd = 0
    monthly_returns = []
    wins = 0
    total_trades = 0

    tqqq_close = df_tqqq["Close"].values
    qqq_close = df_qqq["Close"].values
    dates = df_tqqq.index

    ema50_tqqq = df_tqqq["Close"].ewm(span=50).mean().values
    rsi_qqq = compute_rsi(df_qqq["Close"]).values

    current_month = dates[0].month
    month_start = capital

    for i in range(60, len(df_tqqq)):
        price = tqqq_close[i]
        above_ema = price > ema50_tqqq[i]
        qqq_rsi = rsi_qqq[i] if not np.isnan(rsi_qqq[i]) else 50
        month = dates[i].month

        # Check exits on existing positions
        for j, pos in enumerate(positions[:]):
            if pos["direction"] == "call":
                pnl_pct = (price - pos["entry_price"]) / pos["entry_price"] * 4  # 4x leverage
            else:
                pnl_pct = (pos["entry_price"] - price) / pos["entry_price"] * 4

            # Stop loss -40%
            if pnl_pct <= -0.40:
                realized = pos["cost"] * (1 + pnl_pct)
                capital += max(0, realized)
                total_trades += 1
                if pnl_pct > 0:
                    wins += 1
                positions.remove(pos)
                continue

            # Profit target +60%
            if pnl_pct >= 0.60:
                realized = pos["cost"] * (1 + pnl_pct)
                capital += realized
                total_trades += 1
                wins += 1
                positions.remove(pos)
                continue

            # DTE check (30 bars ~ 1 month)
            bars_held = i - pos["entry_bar"]
            if bars_held >= 45:
                realized = pos["cost"] * (1 + pnl_pct)
                capital += max(0, realized)
                total_trades += 1
                if pnl_pct > 0:
                    wins += 1
                positions.remove(pos)

        # Entry signals
        if len(positions) < 3 and capital > 500:
            entry_cost = min(500, capital * 0.15)

            if above_ema and qqq_rsi > 50:
                # Bullish: buy calls
                positions.append({
                    "direction": "call",
                    "entry_price": price,
                    "cost": entry_cost,
                    "entry_bar": i,
                })
                capital -= entry_cost

            elif not above_ema and qqq_rsi < 40:
                # Bearish: buy puts
                positions.append({
                    "direction": "put",
                    "entry_price": price,
                    "cost": entry_cost,
                    "entry_bar": i,
                })
                capital -= entry_cost

        # Monthly tracking
        if month != current_month:
            pos_value = 0
            for pos in positions:
                if pos["direction"] == "call":
                    pnl_pct = (price - pos["entry_price"]) / pos["entry_price"] * 4
                else:
                    pnl_pct = (pos["entry_price"] - price) / pos["entry_price"] * 4
                pos_value += pos["cost"] * max(0, 1 + pnl_pct)

            total_value = capital + pos_value
            monthly_ret = (total_value - month_start) / month_start if month_start > 0 else 0
            monthly_returns.append(monthly_ret)
            month_start = total_value
            current_month = month

        # Drawdown
        pos_value = sum(
            p["cost"] * max(0, 1 + ((price - p["entry_price"]) / p["entry_price"] * 4
                                     if p["direction"] == "call"
                                     else (p["entry_price"] - price) / p["entry_price"] * 4))
            for p in positions
        )
        total_value = capital + pos_value
        peak = max(peak, total_value)
        dd = (total_value - peak) / peak if peak > 0 else 0
        max_dd = min(max_dd, dd)

    # Close remaining positions
    final_price = tqqq_close[-1]
    for pos in positions:
        if pos["direction"] == "call":
            pnl_pct = (final_price - pos["entry_price"]) / pos["entry_price"] * 4
        else:
            pnl_pct = (pos["entry_price"] - final_price) / pos["entry_price"] * 4
        realized = pos["cost"] * max(0, 1 + pnl_pct)
        capital += realized

    end_value = capital
    return _compute_stats("TQQQ Momentum", start_capital, end_value, monthly_returns,
                          max_dd, wins, total_trades, df_tqqq)


def _compute_stats(name, start_cap, end_cap, monthly_returns, max_dd, wins, total_trades, df):
    """Compute final statistics."""
    years = len(df) / 252
    cagr = (end_cap / start_cap) ** (1 / years) - 1 if years > 0 and end_cap > 0 else 0

    monthly_arr = np.array(monthly_returns) if monthly_returns else np.array([0])
    avg_monthly = np.mean(monthly_arr)
    std_monthly = np.std(monthly_arr)
    sharpe = (avg_monthly * 12) / (std_monthly * np.sqrt(12)) if std_monthly > 0 else 0
    win_rate = wins / total_trades if total_trades > 0 else 0

    return {
        "strategy": name,
        "start_capital": start_cap,
        "end_capital": round(end_cap, 2),
        "cagr": round(cagr * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate * 100, 1),
        "avg_monthly_yield": round(avg_monthly * 100, 2),
        "total_trades": total_trades,
        "years": round(years, 1),
    }


def print_results_table(results):
    """Print formatted results table."""
    print("\n" + "=" * 110)
    print("RUDY v2.0 — ETF STRATEGY BACKTEST RESULTS")
    print("=" * 110)

    headers = ["Strategy", "Start $", "End $", "CAGR %", "Max DD %", "Sharpe",
               "Win Rate %", "Mo Yield %", "Trades", "Years"]
    widths = [18, 10, 12, 8, 9, 7, 10, 10, 7, 6]

    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    print("-" * 110)

    for r in results:
        row = [
            r["strategy"],
            f"${r['start_capital']:,.0f}",
            f"${r['end_capital']:,.0f}",
            f"{r['cagr']:.1f}%",
            f"{r['max_drawdown']:.1f}%",
            f"{r['sharpe']:.2f}",
            f"{r['win_rate']:.1f}%",
            f"{r['avg_monthly_yield']:.2f}%",
            str(r["total_trades"]),
            str(r["years"]),
        ]
        row_line = " | ".join(str(v).ljust(w) for v, w in zip(row, widths))
        print(row_line)

    print("=" * 110)

    total_start = sum(r["start_capital"] for r in results)
    total_end = sum(r["end_capital"] for r in results)
    total_return = (total_end / total_start - 1) * 100
    print(f"\nCombined: ${total_start:,.0f} -> ${total_end:,.0f} "
          f"({total_return:+.1f}% total return)")
    print(f"Total allocation: $70,000 across 4 strategies")
    print()


def main():
    log("=" * 60)
    log("ETF Strategy Backtester starting")

    # Fetch all data
    df_schd = fetch_data("SCHD", "2012-01-01", "2025-12-31")  # SCHD IPO ~2011
    df_spy = fetch_data("SPY", "2010-01-01", "2025-12-31")
    df_qqq = fetch_data("QQQ", "2010-01-01", "2025-12-31")
    df_tqqq = fetch_data("TQQQ", "2010-03-01", "2025-12-31")  # TQQQ IPO Feb 2010

    results = []

    # 1. SCHD Wheel
    if df_schd is not None and len(df_schd) > 100:
        r = backtest_wheel(df_schd, 25_000)
        results.append(r)
        log(f"Wheel: ${r['start_capital']:,} -> ${r['end_capital']:,.0f} | CAGR {r['cagr']:.1f}%")
    else:
        log("SCHD data unavailable — skipping Wheel backtest")

    # 2. SPY PMCC
    if df_spy is not None and len(df_spy) > 100:
        r = backtest_pmcc(df_spy, 20_000)
        results.append(r)
        log(f"PMCC: ${r['start_capital']:,} -> ${r['end_capital']:,.0f} | CAGR {r['cagr']:.1f}%")
    else:
        log("SPY data unavailable — skipping PMCC backtest")

    # 3. QQQ Collar
    if df_qqq is not None and len(df_qqq) > 100:
        r = backtest_collar(df_qqq, 15_000)
        results.append(r)
        log(f"Collar: ${r['start_capital']:,} -> ${r['end_capital']:,.0f} | CAGR {r['cagr']:.1f}%")
    else:
        log("QQQ data unavailable — skipping Collar backtest")

    # 4. TQQQ Momentum
    if df_tqqq is not None and df_qqq is not None and len(df_tqqq) > 100:
        r = backtest_tqqq_momentum(df_tqqq, df_qqq, 10_000)
        results.append(r)
        log(f"TQQQ: ${r['start_capital']:,} -> ${r['end_capital']:,.0f} | CAGR {r['cagr']:.1f}%")
    else:
        log("TQQQ/QQQ data unavailable — skipping Momentum backtest")

    if results:
        print_results_table(results)

        # Save results
        results_file = os.path.join(DATA_DIR, "backtest_etf_results.json")
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        log(f"Results saved to {results_file}")

    log("Backtester complete")


if __name__ == "__main__":
    main()
