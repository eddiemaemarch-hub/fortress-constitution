"""Backtest — System 8 (10X Moonshot)
Simulates options-like returns on high-growth small/mid caps.
Calls on breakout, puts on breakdown. Trail stop at +80%.
"""
import os
import json
import math
import numpy as np
import yfinance as yf
from datetime import datetime

DATA_DIR = os.path.expanduser("~/rudy/data")

UNIVERSE = {
    "eVTOL": ["JOBY", "ACHR", "LILM"],
    "quantum": ["IONQ", "RGTI", "QUBT"],
    "nuclear": ["SMR", "OKLO"],
    "space": ["RKLB", "LUNR", "ASTS"],
    "biotech": ["DNA", "CRSP", "BEAM"],
    "AI_smallcap": ["BBAI", "SOUN", "BFLY"],
}
ALL_TICKERS = [t for tickers in UNIVERSE.values() for t in tickers]

CAPITAL = 10000
POSITION_SIZE = 300
LEVERAGE = 4  # Higher leverage for OTM moonshot options
PROFIT_TARGET = 1.50
LOSS_STOP = -0.50
TRAIL_ACTIVATE = 0.80
TRAIL_PERCENT = 0.40
HOLD_DAYS = 90
MIN_SCORE = 3.0


def get_data(symbol):
    try:
        t = yf.Ticker(symbol)
        data = t.history(period="3y")
        if len(data) < 50:
            return None
        return data
    except Exception:
        return None


def compute_signals(data):
    close = data["Close"].copy()
    volume = data["Volume"].copy()
    data = data.copy()
    data["ema10"] = close.ewm(span=10).mean()
    data["ema21"] = close.ewm(span=21).mean()
    data["ema50"] = close.ewm(span=50).mean()
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    data["macd"] = ema12 - ema26
    data["macd_signal"] = data["macd"].ewm(span=9).mean()
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss_s = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss_s
    data["rsi"] = 100 - 100 / (1 + rs)
    data["vol_avg"] = volume.rolling(20).mean()
    data["mom_1m"] = close.pct_change(21) * 100
    return data.dropna()


def score_bull(row, prev):
    score = 0
    if row["ema10"] > row["ema21"] > row["ema50"]:
        score += 2
    elif row["ema10"] > row["ema21"]:
        score += 1
    if row["macd"] > row["macd_signal"] and prev["macd"] <= prev["macd_signal"]:
        score += 1.5
    if 30 < row["rsi"] < 50:
        score += 1
    elif row["rsi"] < 30:
        score += 0.5
    if row["Volume"] > row["vol_avg"] * 3:
        score += 1.5
    elif row["Volume"] > row["vol_avg"] * 2:
        score += 1
    if row.get("mom_1m", 0) > 20:
        score += 1
    return score


def score_bear(row, prev):
    score = 0
    if row["ema10"] < row["ema21"] < row["ema50"]:
        score += 2
    elif row["ema10"] < row["ema21"]:
        score += 1
    if row["macd"] < row["macd_signal"] and prev["macd"] >= prev["macd_signal"]:
        score += 1.5
    if row["rsi"] > 75:
        score += 1
    if row["Volume"] > row["vol_avg"] * 2:
        score += 1
    if row.get("mom_1m", 0) < -20:
        score += 1
    return score


def backtest():
    print("=" * 60)
    print("BACKTESTING: System 8 — 10X Moonshot")
    print(f"Universe: {', '.join(ALL_TICKERS)}")
    print(f"Capital: ${CAPITAL:,} | Position: ${POSITION_SIZE} | Leverage: {LEVERAGE}x")
    print(f"Targets: +{PROFIT_TARGET*100:.0f}% / {LOSS_STOP*100:.0f}% | Trail: +{TRAIL_ACTIVATE*100:.0f}%/{TRAIL_PERCENT*100:.0f}%")
    print("=" * 60)

    all_trades = []
    equity = CAPITAL
    peak_equity = CAPITAL
    max_dd = 0

    for symbol in ALL_TICKERS:
        print(f"  Loading {symbol}...", end=" ")
        data = get_data(symbol)
        if data is None:
            print("SKIP")
            continue
        data = compute_signals(data)
        if len(data) < 10:
            print("SKIP (short)")
            continue
        print(f"{len(data)} days")

        in_trade = False
        trade_entry = 0
        trade_dir = None
        trade_day = 0
        entry_idx = 0
        peak_return = 0

        for i in range(1, len(data)):
            row = data.iloc[i]
            prev = data.iloc[i - 1]

            if not in_trade:
                bull = score_bull(row, prev)
                bear = score_bear(row, prev)
                if bull >= MIN_SCORE:
                    in_trade = True
                    trade_entry = row["Close"]
                    trade_dir = "CALL"
                    trade_day = 0
                    entry_idx = i
                    peak_return = 0
                elif bear >= MIN_SCORE:
                    in_trade = True
                    trade_entry = row["Close"]
                    trade_dir = "PUT"
                    trade_day = 0
                    entry_idx = i
                    peak_return = 0
            else:
                trade_day += 1
                price = row["Close"]
                if trade_dir == "CALL":
                    raw_return = (price - trade_entry) / trade_entry
                else:
                    raw_return = (trade_entry - price) / trade_entry

                lev_return = raw_return * LEVERAGE
                if lev_return > peak_return:
                    peak_return = lev_return

                exit_reason = None
                # Trail stop
                if peak_return >= TRAIL_ACTIVATE:
                    trail_floor = peak_return * (1 - TRAIL_PERCENT)
                    if lev_return <= trail_floor:
                        exit_reason = "trailing_stop"

                if not exit_reason:
                    if lev_return >= PROFIT_TARGET:
                        exit_reason = "profit_target"
                    elif lev_return <= LOSS_STOP:
                        exit_reason = "stop_loss"
                    elif trade_day >= HOLD_DAYS:
                        exit_reason = "time_exit"
                    elif trade_dir == "CALL" and row["ema10"] < row["ema21"] < row["ema50"]:
                        exit_reason = "signal_reversal"
                    elif trade_dir == "PUT" and row["ema10"] > row["ema21"] > row["ema50"]:
                        exit_reason = "signal_reversal"

                if exit_reason:
                    pnl = POSITION_SIZE * lev_return
                    equity += pnl
                    if equity > peak_equity:
                        peak_equity = equity
                    dd = (peak_equity - equity) / peak_equity * 100
                    if dd > max_dd:
                        max_dd = dd

                    sector = "unknown"
                    for s, tickers in UNIVERSE.items():
                        if symbol in tickers:
                            sector = s
                            break

                    all_trades.append({
                        "symbol": symbol,
                        "sector": sector,
                        "direction": trade_dir,
                        "entry_price": trade_entry,
                        "exit_price": price,
                        "raw_return": raw_return,
                        "leveraged_return": lev_return,
                        "peak_return": peak_return,
                        "pnl": pnl,
                        "hold_days": trade_day,
                        "exit_reason": exit_reason,
                        "entry_date": str(data.index[entry_idx].date()),
                        "exit_date": str(data.index[i].date()),
                    })
                    in_trade = False

    if not all_trades:
        print("\n  NO TRADES GENERATED")
        return

    total_pnl = sum(t["pnl"] for t in all_trades)
    winners = [t for t in all_trades if t["pnl"] > 0]
    losers = [t for t in all_trades if t["pnl"] <= 0]
    win_rate = len(winners) / len(all_trades) * 100
    avg_win = sum(t["pnl"] for t in winners) / len(winners) if winners else 0
    avg_loss = sum(t["pnl"] for t in losers) / len(losers) if losers else 0
    total_return = (equity - CAPITAL) / CAPITAL * 100
    call_trades = [t for t in all_trades if t["direction"] == "CALL"]
    put_trades = [t for t in all_trades if t["direction"] == "PUT"]
    moonshots = [t for t in all_trades if t["leveraged_return"] >= 1.0]
    trail_exits = [t for t in all_trades if t["exit_reason"] == "trailing_stop"]

    returns = [t["leveraged_return"] for t in all_trades]
    if len(returns) > 1:
        avg_r = np.mean(returns)
        std_r = np.std(returns)
        trades_per_year = len(all_trades) / 3
        sharpe = (avg_r / std_r) * math.sqrt(trades_per_year) if std_r > 0 else 0
    else:
        sharpe = 0

    # Best trades
    best = sorted(all_trades, key=lambda t: t["pnl"], reverse=True)[:5]

    # Sector breakdown
    sector_pnl = {}
    for t in all_trades:
        s = t["sector"]
        sector_pnl[s] = sector_pnl.get(s, 0) + t["pnl"]

    result = {
        "system": "System 8 — 10X Moonshot",
        "capital": CAPITAL,
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
        "moonshot_trades": len(moonshots),
        "trail_stop_exits": len(trail_exits),
        "sector_pnl": {k: round(v, 2) for k, v in sector_pnl.items()},
        "best_trades": [{
            "symbol": t["symbol"], "sector": t["sector"], "direction": t["direction"],
            "pnl": round(t["pnl"], 2), "return": f"{t['leveraged_return']*100:+.0f}%",
            "dates": f"{t['entry_date']} → {t['exit_date']}"
        } for t in best],
        "trades": all_trades,
        "timestamp": datetime.now().isoformat(),
    }

    with open(os.path.join(DATA_DIR, "backtest_10x.json"), "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n  RESULTS: System 8 — 10X Moonshot")
    print(f"  ${CAPITAL:,} → ${equity:,.0f} (+{total_return:.0f}%)")
    print(f"  Trades: {len(all_trades)} ({len(call_trades)} calls, {len(put_trades)} puts)")
    print(f"  Win rate: {win_rate:.0f}% | Avg win: ${avg_win:,.0f} | Avg loss: ${avg_loss:,.0f}")
    print(f"  Max DD: {max_dd:.0f}% | Sharpe: {sharpe:.2f}")
    print(f"  Moonshot trades (100%+): {len(moonshots)} | Trail stop exits: {len(trail_exits)}")
    print(f"\n  SECTOR BREAKDOWN:")
    for s, pnl in sorted(sector_pnl.items(), key=lambda x: x[1], reverse=True):
        emoji = "+" if pnl >= 0 else ""
        print(f"    {s}: ${emoji}{pnl:,.0f}")
    print(f"\n  TOP 5 TRADES:")
    for t in best:
        ret = f"{t['leveraged_return']*100:+.0f}%"
        dates = f"{t['entry_date']} → {t['exit_date']}"
        print(f"    {t['symbol']} [{t['sector']}] {t['direction']}: ${t['pnl']:+,.0f} ({ret}) {dates}")
    print(f"\n  Saved to {DATA_DIR}/backtest_10x.json")


if __name__ == "__main__":
    backtest()
