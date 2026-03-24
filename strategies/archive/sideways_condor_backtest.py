"""Backtest: Iron Condor / Credit Spread Strategy for Sideways Markets
Sell OTM call spread + OTM put spread when market is range-bound.
Profit from time decay (theta). Defined risk on both sides.

Detection: ADX < 25 (no trend) + RSI 35-65 (neutral) + BB width < threshold
Universe: SPY, QQQ, IWM + high-IV individual names (AMD, TSLA, NVDA, META)
Entry: Sell 30-delta wings, 30-45 DTE
Exit: Close at 50% profit, 200% loss, or 7 DTE
"""
import os
import sys
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf

DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(DATA_DIR, exist_ok=True)

# ========== Strategy Parameters ==========
UNIVERSE = ["SPY", "QQQ", "IWM", "XLF", "XLE", "MSFT", "AAPL", "META", "AMD", "NVDA"]
STARTING_CAPITAL = 10000
MAX_POSITIONS = 6
POSITION_RISK = 400  # Max loss per spread (~$400)
WING_WIDTH = 5  # $5 wide spreads
TARGET_DTE = 21  # 21 DTE — faster theta decay, more turnover
PROFIT_TARGET = 0.50  # Close at 50% of max profit
LOSS_MULTIPLE = 1.5  # Close at 1.5x premium received
DTE_EXIT = 5  # Close at 5 DTE
CALL_DELTA = 0.12  # (only used for iron condors, not put spreads)
PUT_DELTA = 0.15  # ~15 delta short put — slightly more premium
STRATEGY_MODE = "put_spread"  # "iron_condor" or "put_spread"

# Sideways detection thresholds
ADX_THRESHOLD = 25  # ADX < 25 (loosened to get more trades)
RSI_LOW = 35
RSI_HIGH = 65
BB_WIDTH_THRESHOLD = 8  # Loosened for more opportunities


def log(msg):
    print(f"  {msg}")


# ========== Black-Scholes Approximation ==========
def norm_cdf(x):
    """Cumulative normal distribution."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_call(S, K, T, r, sigma):
    """Black-Scholes call price."""
    if T <= 0 or sigma <= 0:
        return max(0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)


def bs_put(S, K, T, r, sigma):
    """Black-Scholes put price."""
    if T <= 0 or sigma <= 0:
        return max(0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


def find_strike_by_delta(S, T, r, sigma, target_delta, option_type="call"):
    """Find strike price that gives approximately the target delta."""
    if T <= 0:
        return S
    # Binary search for strike
    low = S * 0.5
    high = S * 1.5
    for _ in range(50):
        mid = (low + high) / 2
        d1 = (math.log(S / mid) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        if option_type == "call":
            delta = norm_cdf(d1)
            if delta > target_delta:
                low = mid
            else:
                high = mid
        else:  # put
            delta = norm_cdf(d1) - 1  # put delta is negative
            if abs(delta) > target_delta:
                high = mid
            else:
                low = mid
    return round((low + high) / 2, 0)


# ========== Technical Indicators ==========
def calc_adx(high, low, close, period=14):
    """Calculate Average Directional Index."""
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    tr = pd.DataFrame({
        "hl": high - low,
        "hc": abs(high - close.shift(1)),
        "lc": abs(low - close.shift(1)),
    }).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(period).mean()
    return adx


def calc_rsi(close, period=14):
    """Calculate RSI."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def calc_bb_width(close, period=20):
    """Calculate Bollinger Band width as % of price."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return (std * 2) / sma * 100


def calc_iv(close, period=20):
    """Estimate implied volatility from historical volatility."""
    returns = np.log(close / close.shift(1))
    hv = returns.rolling(period).std() * math.sqrt(252)
    # IV is typically 1.2-1.5x HV in normal markets
    return hv * 1.3


# ========== Backtest Engine ==========
def is_sideways(adx, rsi, bb_width):
    """Check if market is in sideways/range-bound regime."""
    return (adx < ADX_THRESHOLD and
            RSI_LOW < rsi < RSI_HIGH and
            bb_width < BB_WIDTH_THRESHOLD)


def backtest_symbol(symbol):
    """Run iron condor backtest on a single symbol."""
    log(f"Downloading {symbol} data...")
    t = yf.Ticker(symbol)
    data = t.history(period="5y")

    if len(data) < 250:
        log(f"  Insufficient data for {symbol} ({len(data)} bars)")
        return None

    close = data["Close"]
    high = data["High"]
    low = data["Low"]

    # Calculate indicators
    adx = calc_adx(high, low, close)
    rsi = calc_rsi(close)
    bb_width = calc_bb_width(close)
    iv = calc_iv(close)

    trades = []
    r = 0.05  # Risk-free rate

    i = 250  # Start after enough data for indicators
    while i < len(data) - TARGET_DTE - 5:
        date = data.index[i]
        price = float(close.iloc[i])
        cur_adx = float(adx.iloc[i]) if not pd.isna(adx.iloc[i]) else 30
        cur_rsi = float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else 50
        cur_bb = float(bb_width.iloc[i]) if not pd.isna(bb_width.iloc[i]) else 10
        cur_iv = float(iv.iloc[i]) if not pd.isna(iv.iloc[i]) else 0.25

        if not is_sideways(cur_adx, cur_rsi, cur_bb):
            i += 1
            continue

        # Skip if IV too low (not worth selling)
        if cur_iv < 0.15:
            i += 1
            continue

        T = TARGET_DTE / 365.0

        # Find strikes
        short_put = find_strike_by_delta(price, T, r, cur_iv, PUT_DELTA, "put")
        long_put = short_put - WING_WIDTH

        if STRATEGY_MODE == "iron_condor":
            short_call = find_strike_by_delta(price, T, r, cur_iv, CALL_DELTA, "call")
            long_call = short_call + WING_WIDTH
            short_call_px = bs_call(price, short_call, T, r, cur_iv)
            long_call_px = bs_call(price, long_call, T, r, cur_iv)
            call_spread_credit = short_call_px - long_call_px
        else:
            short_call = 0
            long_call = 0
            call_spread_credit = 0

        short_put_px = bs_put(price, short_put, T, r, cur_iv)
        long_put_px = bs_put(price, long_put, T, r, cur_iv)
        put_spread_credit = short_put_px - long_put_px

        total_credit = call_spread_credit + put_spread_credit

        if total_credit < 0.20:  # Skip if credit too small
            i += 1
            continue

        max_loss = WING_WIDTH - total_credit
        profit_target_px = total_credit * PROFIT_TARGET

        # Simulate through DTE
        entry_date = date
        exit_date = None
        exit_price = None
        exit_reason = None

        for j in range(1, TARGET_DTE + 1):
            if i + j >= len(data):
                break

            future_price = float(close.iloc[i + j])
            days_left = TARGET_DTE - j
            T_remaining = days_left / 365.0

            # Recalculate spread value
            if T_remaining > 0:
                sp = bs_put(future_price, short_put, T_remaining, r, cur_iv)
                lp = bs_put(future_price, long_put, T_remaining, r, cur_iv)
                current_value = sp - lp
                if STRATEGY_MODE == "iron_condor":
                    sc = bs_call(future_price, short_call, T_remaining, r, cur_iv)
                    lc = bs_call(future_price, long_call, T_remaining, r, cur_iv)
                    current_value += (sc - lc)
            else:
                # At expiration
                put_spread_val = max(0, min(short_put - future_price, WING_WIDTH))
                current_value = put_spread_val
                if STRATEGY_MODE == "iron_condor":
                    call_spread_val = max(0, min(future_price - short_call, WING_WIDTH))
                    current_value += call_spread_val

            pnl = (total_credit - current_value) * 100  # Per contract

            # Check exits
            if pnl >= profit_target_px * 100:
                exit_reason = "Profit target (50%)"
                exit_price = current_value
                exit_date = data.index[i + j]
                break
            elif pnl <= -max_loss * LOSS_MULTIPLE * 100:
                exit_reason = "Stop loss (200%)"
                exit_price = current_value
                exit_date = data.index[i + j]
                break
            elif days_left <= DTE_EXIT:
                exit_reason = f"Time exit ({days_left} DTE)"
                exit_price = current_value
                exit_date = data.index[i + j]
                break

        if exit_date is None:
            # Expired — settle at intrinsic
            final_price = float(close.iloc[min(i + TARGET_DTE, len(data) - 1)])
            call_spread_val = max(0, min(final_price - short_call, WING_WIDTH))
            put_spread_val = max(0, min(short_put - final_price, WING_WIDTH))
            exit_price = call_spread_val + put_spread_val
            exit_date = data.index[min(i + TARGET_DTE, len(data) - 1)]
            exit_reason = "Expiration"

        pnl = (total_credit - exit_price) * 100
        pnl_pct = pnl / (max_loss * 100) * 100 if max_loss > 0 else 0

        trades.append({
            "symbol": symbol,
            "entry_date": str(entry_date.date()),
            "exit_date": str(exit_date.date()) if hasattr(exit_date, 'date') else str(exit_date),
            "underlying_entry": price,
            "short_call": short_call,
            "long_call": long_call,
            "short_put": short_put,
            "long_put": long_put,
            "credit": round(total_credit, 2),
            "max_loss": round(max_loss, 2),
            "exit_value": round(exit_price, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 1),
            "exit_reason": exit_reason,
            "adx": round(cur_adx, 1),
            "rsi": round(cur_rsi, 1),
            "iv": round(cur_iv * 100, 1),
            "bb_width": round(cur_bb, 1),
        })

        # Skip ahead past this trade's DTE (no overlapping trades per symbol)
        i += TARGET_DTE + 5
        continue

        i += 1

    return trades


def run_full_backtest():
    """Run backtest across all symbols and aggregate results."""
    print("=" * 60)
    print("IRON CONDOR / CREDIT SPREAD BACKTEST")
    print(f"Universe: {', '.join(UNIVERSE)}")
    print(f"Period: 5 years | Starting Capital: ${STARTING_CAPITAL:,}")
    print(f"Strategy: Sell iron condors in sideways markets (ADX < {ADX_THRESHOLD})")
    print(f"Entry: {CALL_DELTA:.0%}/{PUT_DELTA:.0%} delta wings, {TARGET_DTE} DTE")
    print(f"Exit: +{PROFIT_TARGET:.0%} profit / {LOSS_MULTIPLE:.0f}x loss / {DTE_EXIT} DTE")
    print("=" * 60)

    all_trades = []
    for symbol in UNIVERSE:
        trades = backtest_symbol(symbol)
        if trades:
            all_trades.extend(trades)
            wins = sum(1 for t in trades if t["pnl"] > 0)
            total_pnl = sum(t["pnl"] for t in trades)
            log(f"  {symbol}: {len(trades)} trades, {wins}/{len(trades)} wins "
                f"({wins/len(trades)*100:.0f}%), P&L: ${total_pnl:+,.0f}")

    if not all_trades:
        print("No trades generated!")
        return

    # Sort by date
    all_trades.sort(key=lambda t: t["entry_date"])

    # Calculate portfolio-level metrics
    wins = [t for t in all_trades if t["pnl"] > 0]
    losses = [t for t in all_trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in all_trades)
    avg_win = np.mean([t["pnl"] for t in wins]) if wins else 0
    avg_loss = np.mean([t["pnl"] for t in losses]) if losses else 0

    # Equity curve
    equity = [STARTING_CAPITAL]
    for t in all_trades:
        equity.append(equity[-1] + t["pnl"])

    peak = STARTING_CAPITAL
    max_dd = 0
    for e in equity:
        peak = max(peak, e)
        dd = (peak - e) / peak * 100
        max_dd = max(max_dd, dd)

    # Monthly returns for Sharpe
    monthly_pnl = {}
    for t in all_trades:
        month = t["entry_date"][:7]
        monthly_pnl[month] = monthly_pnl.get(month, 0) + t["pnl"]

    monthly_returns = list(monthly_pnl.values())
    if len(monthly_returns) > 1:
        sharpe = (np.mean(monthly_returns) / np.std(monthly_returns)) * math.sqrt(12) if np.std(monthly_returns) > 0 else 0
    else:
        sharpe = 0

    final_equity = equity[-1]
    total_return = (final_equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100

    # Exit reason breakdown
    exit_reasons = {}
    for t in all_trades:
        r = t["exit_reason"]
        if r not in exit_reasons:
            exit_reasons[r] = {"count": 0, "pnl": 0}
        exit_reasons[r]["count"] += 1
        exit_reasons[r]["pnl"] += t["pnl"]

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Total Trades:     {len(all_trades)}")
    print(f"Winners:          {len(wins)} ({len(wins)/len(all_trades)*100:.0f}%)")
    print(f"Losers:           {len(losses)} ({len(losses)/len(all_trades)*100:.0f}%)")
    print(f"Avg Win:          ${avg_win:+,.2f}")
    print(f"Avg Loss:         ${avg_loss:+,.2f}")
    print(f"Profit Factor:    {abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses)):.2f}" if losses and sum(t['pnl'] for t in losses) != 0 else "Profit Factor: inf")
    print(f"")
    print(f"Starting Capital: ${STARTING_CAPITAL:,}")
    print(f"Final Equity:     ${final_equity:,.0f}")
    print(f"Total P&L:        ${total_pnl:+,.0f}")
    print(f"Total Return:     {total_return:+.1f}%")
    print(f"Max Drawdown:     {max_dd:.1f}%")
    print(f"Sharpe Ratio:     {sharpe:.2f}")
    print(f"")
    print(f"Exit Reasons:")
    for reason, stats in sorted(exit_reasons.items()):
        print(f"  {reason}: {stats['count']} trades, ${stats['pnl']:+,.0f}")

    # Save results
    results = {
        "strategy": "iron_condor_sideways",
        "run_date": datetime.now().isoformat(),
        "parameters": {
            "universe": UNIVERSE,
            "starting_capital": STARTING_CAPITAL,
            "wing_width": WING_WIDTH,
            "target_dte": TARGET_DTE,
            "call_delta": CALL_DELTA,
            "put_delta": PUT_DELTA,
            "profit_target": PROFIT_TARGET,
            "loss_multiple": LOSS_MULTIPLE,
            "dte_exit": DTE_EXIT,
            "adx_threshold": ADX_THRESHOLD,
        },
        "summary": {
            "total_trades": len(all_trades),
            "win_rate": round(len(wins) / len(all_trades) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_return, 1),
            "max_drawdown_pct": round(max_dd, 1),
            "sharpe_ratio": round(sharpe, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "final_equity": round(final_equity, 2),
        },
        "exit_reasons": exit_reasons,
        "trades": all_trades,
    }

    results_file = os.path.join(DATA_DIR, "backtest_iron_condor.json")
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {results_file}")

    return results


if __name__ == "__main__":
    run_full_backtest()
