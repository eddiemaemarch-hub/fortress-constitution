"""Backtest — Systems 6 & 7 (Metals Momentum + SpaceX IPO Proxies)
Simulates options-like returns using historical data + leverage multiplier.
Supports both CALL and PUT entries.
"""
import os
import json
import math
import numpy as np
import yfinance as yf
from datetime import datetime

DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(DATA_DIR, exist_ok=True)


def get_data(symbol, period="5y"):
    """Download historical data."""
    try:
        t = yf.Ticker(symbol)
        data = t.history(period=period)
        if len(data) < 50:
            return None
        return data
    except Exception:
        return None


def compute_signals(data, use_ema200=True):
    """Compute technical signals. Returns DataFrame with signals.
    use_ema200=True for System 6 (golden cross EMA50/EMA200)
    use_ema200=False for System 7 (EMA20/EMA50)
    """
    close = data["Close"].copy()
    volume = data["Volume"].copy()

    if use_ema200:
        ema_fast = close.ewm(span=50).mean()
        ema_slow = close.ewm(span=200).mean()
    else:
        ema_fast = close.ewm(span=20).mean()
        ema_slow = close.ewm(span=50).mean()

    sma50 = close.rolling(50).mean()

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss_s = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss_s
    rsi = 100 - 100 / (1 + rs)

    # Volume avg
    vol_avg = volume.rolling(20).mean()

    data = data.copy()
    data["ema_fast"] = ema_fast
    data["ema_slow"] = ema_slow
    data["sma50"] = sma50
    data["macd"] = macd_line
    data["macd_signal"] = signal_line
    data["rsi"] = rsi
    data["vol_avg"] = vol_avg
    return data


def score_day_bullish(row, prev_row, use_ema200=True):
    """Score a single day for bullish (CALL) setup."""
    score = 0
    if row["ema_fast"] > row["ema_slow"]:
        score += 2
    if row["macd"] > row["macd_signal"] and prev_row["macd"] <= prev_row["macd_signal"]:
        score += 1
    if row["rsi"] < 30:
        score += 1
    if row["Close"] > row["sma50"]:
        score += 1
    threshold = 1.5 if use_ema200 else 2.0
    if row["Volume"] > row["vol_avg"] * threshold:
        score += 0.5 if use_ema200 else 1
    return score


def score_day_bearish(row, prev_row, use_ema200=True):
    """Score a single day for bearish (PUT) setup."""
    score = 0
    if row["ema_fast"] < row["ema_slow"]:
        score += 2
    if row["macd"] < row["macd_signal"] and prev_row["macd"] >= prev_row["macd_signal"]:
        score += 1
    if row["rsi"] > 70:
        score += 1
    if row["Close"] < row["sma50"]:
        score += 1
    threshold = 1.5 if use_ema200 else 2.0
    if row["Volume"] > row["vol_avg"] * threshold:
        score += 0.5 if use_ema200 else 1
    return score


def backtest_system(universe, capital, position_size, max_positions, profit_target,
                    loss_stop, leverage, min_score, hold_days, use_ema200, name):
    """Run backtest for a system."""
    print(f"\n{'='*60}")
    print(f"BACKTESTING: {name}")
    print(f"Universe: {', '.join(universe)}")
    print(f"Capital: ${capital:,} | Position size: ${position_size} | Leverage: {leverage}x")
    print(f"{'='*60}")

    all_trades = []
    equity = capital
    peak = capital
    max_dd = 0

    for symbol in universe:
        print(f"  Loading {symbol}...", end=" ")
        data = get_data(symbol, "5y" if use_ema200 else "3y")
        if data is None or len(data) < (200 if use_ema200 else 50):
            print("SKIP (insufficient data)")
            continue

        data = compute_signals(data, use_ema200)
        data = data.dropna()
        if len(data) < 10:
            print("SKIP (no signals)")
            continue

        print(f"{len(data)} days")

        in_trade = False
        trade_entry = 0
        trade_dir = None
        trade_day = 0
        entry_idx = 0

        for i in range(1, len(data)):
            row = data.iloc[i]
            prev = data.iloc[i - 1]

            if not in_trade:
                # Check bullish
                bull_score = score_day_bullish(row, prev, use_ema200)
                bear_score = score_day_bearish(row, prev, use_ema200)

                if bull_score >= min_score:
                    in_trade = True
                    trade_entry = row["Close"]
                    trade_dir = "CALL"
                    trade_day = 0
                    entry_idx = i
                elif bear_score >= min_score:
                    in_trade = True
                    trade_entry = row["Close"]
                    trade_dir = "PUT"
                    trade_day = 0
                    entry_idx = i
            else:
                trade_day += 1
                price = row["Close"]

                if trade_dir == "CALL":
                    raw_return = (price - trade_entry) / trade_entry
                else:
                    raw_return = (trade_entry - price) / trade_entry

                leveraged_return = raw_return * leverage

                # Check exits
                exit_reason = None
                if leveraged_return >= profit_target:
                    exit_reason = "profit_target"
                elif leveraged_return <= loss_stop:
                    exit_reason = "stop_loss"
                elif trade_day >= hold_days:
                    exit_reason = "time_exit"
                else:
                    # Signal reversal
                    if trade_dir == "CALL" and row["ema_fast"] < row["ema_slow"]:
                        exit_reason = "signal_reversal"
                    elif trade_dir == "PUT" and row["ema_fast"] > row["ema_slow"]:
                        exit_reason = "signal_reversal"

                if exit_reason:
                    pnl = position_size * leveraged_return
                    equity += pnl
                    if equity > peak:
                        peak = equity
                    dd = (peak - equity) / peak * 100
                    if dd > max_dd:
                        max_dd = dd

                    all_trades.append({
                        "symbol": symbol,
                        "direction": trade_dir,
                        "entry_price": trade_entry,
                        "exit_price": price,
                        "raw_return": raw_return,
                        "leveraged_return": leveraged_return,
                        "pnl": pnl,
                        "hold_days": trade_day,
                        "exit_reason": exit_reason,
                        "entry_date": str(data.index[entry_idx].date()),
                        "exit_date": str(data.index[i].date()),
                    })
                    in_trade = False

    # Results
    if not all_trades:
        print(f"\n  NO TRADES GENERATED")
        return None

    total_pnl = sum(t["pnl"] for t in all_trades)
    winners = [t for t in all_trades if t["pnl"] > 0]
    losers = [t for t in all_trades if t["pnl"] <= 0]
    win_rate = len(winners) / len(all_trades) * 100
    avg_win = sum(t["pnl"] for t in winners) / len(winners) if winners else 0
    avg_loss = sum(t["pnl"] for t in losers) / len(losers) if losers else 0
    total_return = (equity - capital) / capital * 100

    # Sharpe (approximate — annualized)
    returns = [t["leveraged_return"] for t in all_trades]
    if len(returns) > 1:
        avg_r = np.mean(returns)
        std_r = np.std(returns)
        trades_per_year = len(all_trades) / 5  # ~5 years
        sharpe = (avg_r / std_r) * math.sqrt(trades_per_year) if std_r > 0 else 0
    else:
        sharpe = 0

    call_trades = [t for t in all_trades if t["direction"] == "CALL"]
    put_trades = [t for t in all_trades if t["direction"] == "PUT"]

    result = {
        "system": name,
        "capital": capital,
        "final_equity": round(equity, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_return, 1),
        "total_trades": len(all_trades),
        "call_trades": len(call_trades),
        "put_trades": len(put_trades),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown_pct": round(max_dd, 1),
        "sharpe_ratio": round(sharpe, 2),
        "trades": all_trades,
        "timestamp": datetime.now().isoformat(),
    }

    print(f"\n  RESULTS: {name}")
    print(f"  ${capital:,} → ${equity:,.0f} (+{total_return:.0f}%)")
    print(f"  Trades: {len(all_trades)} ({len(call_trades)} calls, {len(put_trades)} puts)")
    print(f"  Win rate: {win_rate:.0f}% | Avg win: ${avg_win:,.0f} | Avg loss: ${avg_loss:,.0f}")
    print(f"  Max DD: {max_dd:.0f}% | Sharpe: {sharpe:.2f}")

    return result


def run_backtests():
    print("\n" + "=" * 60)
    print("RUDY v2.0 — NEW SYSTEMS BACKTEST")
    print("=" * 60)

    # System 6: Metals Momentum
    metals = backtest_system(
        universe=["GLD", "GDX", "NEM", "GOLD", "SLV", "PAAS", "AG", "HL", "MP", "REMX", "LAC"],
        capital=15000,
        position_size=600,
        max_positions=5,
        profit_target=0.60,
        loss_stop=-0.40,
        leverage=3,
        min_score=3.0,
        hold_days=60,  # ~60 day hold (matching 45-90 DTE options)
        use_ema200=True,
        name="System 6 — Metals Momentum",
    )

    if metals:
        with open(os.path.join(DATA_DIR, "backtest_metals.json"), "w") as f:
            json.dump(metals, f, indent=2)
        print(f"  Saved to {DATA_DIR}/backtest_metals.json")

    # System 7: SpaceX IPO Proxies
    spacex = backtest_system(
        universe=["RKLB", "ASTS", "BKSY", "LUNR", "GOOGL", "LMT", "NOC", "RTX"],
        capital=10000,
        position_size=500,
        max_positions=4,
        profit_target=0.50,
        loss_stop=-0.30,
        leverage=3,
        min_score=3.0,
        hold_days=45,
        use_ema200=False,  # Uses EMA20/EMA50
        name="System 7 — SpaceX IPO Proxies",
    )

    if spacex:
        with open(os.path.join(DATA_DIR, "backtest_spacex.json"), "w") as f:
            json.dump(spacex, f, indent=2)
        print(f"  Saved to {DATA_DIR}/backtest_spacex.json")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if metals:
        print(f"System 6 Metals Momentum: ${metals['capital']:,} → ${metals['final_equity']:,.0f} "
              f"(+{metals['total_return_pct']:.0f}%) | Sharpe: {metals['sharpe_ratio']:.2f} | "
              f"Max DD: {metals['max_drawdown_pct']:.0f}% | Win Rate: {metals['win_rate']:.0f}%")
    if spacex:
        print(f"System 7 SpaceX Proxies: ${spacex['capital']:,} → ${spacex['final_equity']:,.0f} "
              f"(+{spacex['total_return_pct']:.0f}%) | Sharpe: {spacex['sharpe_ratio']:.2f} | "
              f"Max DD: {spacex['max_drawdown_pct']:.0f}% | Win Rate: {spacex['win_rate']:.0f}%")
    print("=" * 60)


if __name__ == "__main__":
    run_backtests()
