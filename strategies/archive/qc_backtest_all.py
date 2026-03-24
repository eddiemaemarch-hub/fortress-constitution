"""Run all strategy backtests on QuantConnect.
Tests signal logic on equity (QC options chains are unreliable).
Cross-validates with our custom Python backtests and Pine Script.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import quantconnect as qc

DATA_DIR = os.path.expanduser("~/rudy/data")

# QuantConnect strategy code for each system

ENERGY_MOMENTUM = '''from AlgorithmImports import *

class EnergyMomentum(QCAlgorithm):
    """Trader3 — Energy Momentum (Golden Cross)
    Buy when EMA50 > SMA200, RSI < 75, price > EMA21.
    Exit on death cross or trailing stop.
    """
    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(20000)

        self.tickers = ["CCJ", "UEC", "XOM", "CVX", "OXY", "DVN", "FANG", "VST", "CEG", "LEU"]
        self.symbols = {}
        self.indicators = {}

        for ticker in self.tickers:
            equity = self.add_equity(ticker, Resolution.DAILY)
            sym = equity.symbol
            self.symbols[ticker] = sym
            self.indicators[ticker] = {
                "ema50": self.ema(sym, 50, Resolution.DAILY),
                "sma200": self.sma(sym, 200, Resolution.DAILY),
                "ema21": self.ema(sym, 21, Resolution.DAILY),
                "rsi": self.rsi(sym, 14, MovingAverageType.WILDERS, Resolution.DAILY),
            }

        self.max_positions = 5
        self.position_pct = 0.18

    def on_data(self, data):
        invested_count = sum(1 for t in self.tickers if self.portfolio[self.symbols[t]].invested)

        for ticker in self.tickers:
            sym = self.symbols[ticker]
            ind = self.indicators[ticker]

            if not ind["sma200"].is_ready:
                continue
            if not data.contains_key(sym) or data[sym] is None:
                continue

            price = data[sym].close
            if price is None or price == 0:
                continue
            ema50 = ind["ema50"].current.value
            sma200 = ind["sma200"].current.value
            ema21 = ind["ema21"].current.value
            rsi = ind["rsi"].current.value

            if self.portfolio[sym].invested:
                # Death cross exit
                if ema50 < sma200:
                    self.liquidate(sym, "Death Cross")
                    self.log(f"EXIT {ticker} — death cross")
            else:
                # Golden cross entry
                if invested_count >= self.max_positions:
                    continue

                if ema50 <= sma200:
                    continue
                if rsi > 75:
                    continue
                if price < ema21:
                    continue

                score = 0
                score += 2 if ema50 > sma200 else 0
                score += 1 if rsi < 65 else 0
                momentum = (price - sma200) / sma200 * 100
                score += 1 if momentum > 5 else 0
                score += 1 if price > ema21 else 0

                if score >= 3:
                    self.set_holdings(sym, self.position_pct)
                    invested_count += 1
                    self.log(f"BUY {ticker} @ {price:.2f}, score={score}, momentum={momentum:.1f}%")
'''

SHORT_SQUEEZE = '''from AlgorithmImports import *
import numpy as np

class ShortSqueeze(QCAlgorithm):
    """Trader4 — Short Squeeze Detection
    Buy on volume surge + gap up + EMA21 > EMA50.
    Exit when momentum fades (price < EMA21 and 5-day momentum < -3%).
    """
    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(10000)

        self.tickers = ["GME", "AMC", "SOFI", "RIVN", "LCID", "COIN", "MARA", "RIOT", "PLTR"]
        self.symbols = {}
        self.indicators = {}
        self.history_windows = {}

        for ticker in self.tickers:
            try:
                equity = self.add_equity(ticker, Resolution.DAILY)
                sym = equity.symbol
                self.symbols[ticker] = sym
                self.indicators[ticker] = {
                    "ema21": self.ema(sym, 21, Resolution.DAILY),
                    "ema50": self.ema(sym, 50, Resolution.DAILY),
                    "rsi": self.rsi(sym, 14, MovingAverageType.WILDERS, Resolution.DAILY),
                    "sma_vol": self.sma(sym, 20, Resolution.DAILY, Field.VOLUME),
                }
                self.history_windows[ticker] = RollingWindow[TradeBar](6)
            except:
                pass

        self.max_positions = 4
        self.position_pct = 0.20

    def on_data(self, data):
        invested_count = sum(1 for t in self.symbols if self.portfolio[self.symbols[t]].invested)

        for ticker in list(self.indicators.keys()):
            sym = self.symbols.get(ticker)
            if sym is None:
                continue
            if not data.contains_key(sym) or data[sym] is None:
                continue

            bar = data[sym]
            if bar is None:
                continue
            self.history_windows[ticker].add(bar)

            ind = self.indicators[ticker]
            if not ind["ema50"].is_ready:
                continue

            price = bar.close
            ema21 = ind["ema21"].current.value
            ema50 = ind["ema50"].current.value
            rsi = ind["rsi"].current.value

            # Volume ratio
            avg_vol = ind["sma_vol"].current.value
            vol_ratio = bar.volume / avg_vol if avg_vol > 0 else 1

            # Gap %
            if self.history_windows[ticker].count >= 2:
                prev_close = self.history_windows[ticker][1].close
                gap_pct = (price - prev_close) / prev_close * 100
            else:
                gap_pct = 0

            # 5-day momentum
            if self.history_windows[ticker].count >= 6:
                price_5d_ago = self.history_windows[ticker][5].close
                momentum_5d = (price - price_5d_ago) / price_5d_ago * 100
            else:
                momentum_5d = 0

            if self.portfolio[sym].invested:
                # Exit if momentum fading
                if price < ema21 and momentum_5d < -3:
                    self.liquidate(sym, "Momentum Fading")
                    self.log(f"EXIT {ticker} — momentum fading")
            else:
                if invested_count >= self.max_positions:
                    continue
                if price < ema21:
                    continue
                if rsi > 80:
                    continue

                score = 0
                if vol_ratio > 1.5: score += 2
                elif vol_ratio > 1.2: score += 1
                if gap_pct > 3: score += 2
                elif gap_pct > 1: score += 1
                if ema21 > ema50: score += 1
                if price > ema21: score += 1
                if momentum_5d > 2: score += 1

                if score >= 3:
                    self.set_holdings(sym, self.position_pct)
                    invested_count += 1
                    self.log(f"BUY {ticker} @ {price:.2f}, score={score}, vol={vol_ratio:.1f}x, gap={gap_pct:.1f}%")
'''

BREAKOUT_MOMENTUM = '''from AlgorithmImports import *

class BreakoutMomentum(QCAlgorithm):
    """Trader5 - Breakout Momentum
    Buy when price breaks 52-week high with volume confirmation.
    Exit on +80% profit, -50% stop, or price < EMA21.
    """
    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(10000)

        ticker_list = ["NVDA", "AMZN", "GOOGL", "TSLA", "NFLX", "CRM", "AVGO", "AMD", "SHOP", "SQ"]
        self.sym_map = {}
        self.ind_map = {}
        self.high_windows = {}

        for t in ticker_list:
            equity = self.add_equity(t, Resolution.DAILY)
            s = equity.symbol
            self.sym_map[t] = s
            ema21_ind = self.ema(s, 21, Resolution.DAILY)
            ema50_ind = self.ema(s, 50, Resolution.DAILY)
            rsi_ind = self.rsi(s, 14, MovingAverageType.WILDERS, Resolution.DAILY)
            sma_vol_ind = self.sma(s, 20, Resolution.DAILY, Field.VOLUME)
            self.ind_map[t] = {"ema21": ema21_ind, "ema50": ema50_ind, "rsi": rsi_ind, "sma_vol": sma_vol_ind}
            self.high_windows[t] = RollingWindow[TradeBar](252)

        self.max_pos = 4
        self.position_pct = 0.25
        self.profit_target = 0.80
        self.stop_loss = 0.50

    def on_data(self, data):
        invested_count = sum(1 for t in self.sym_map if self.portfolio[self.sym_map[t]].invested)

        for ticker, sym in self.sym_map.items():
            if ticker not in self.ind_map:
                continue
            if not data.contains_key(sym) or data[sym] is None:
                continue

            bar = data[sym]
            self.high_windows[ticker].add(bar)

            ind = self.ind_map[ticker]
            if not ind["ema50"].is_ready:
                continue
            if self.high_windows[ticker].count < 252:
                continue

            price = bar.close
            if price is None or price == 0:
                continue

            # 52-week high
            high_52w = max(self.high_windows[ticker][i].high for i in range(self.high_windows[ticker].count))
            dist_from_high = (high_52w - price) / high_52w if high_52w > 0 else 1
            near_high = dist_from_high <= 0.01

            ema21 = ind["ema21"].current.value
            ema50 = ind["ema50"].current.value
            rsi = ind["rsi"].current.value
            avg_vol = ind["sma_vol"].current.value
            vol_ratio = bar.volume / avg_vol if avg_vol > 0 else 1

            if self.portfolio[sym].invested:
                entry_price = self.portfolio[sym].average_price
                pnl_pct = (price - entry_price) / entry_price

                if pnl_pct >= self.profit_target:
                    self.liquidate(sym, "Profit Target")
                    self.log(f"PROFIT {ticker} +{pnl_pct*100:.1f}%")
                elif pnl_pct <= -self.stop_loss:
                    self.liquidate(sym, "Stop Loss")
                    self.log(f"STOP {ticker} {pnl_pct*100:.1f}%")
                elif price < ema21:
                    self.liquidate(sym, "Trend Break")
                    self.log(f"TREND EXIT {ticker} below EMA21")
            else:
                if invested_count >= self.max_pos:
                    continue
                if not near_high:
                    continue
                if vol_ratio < 1.5:
                    continue
                if rsi > 80:
                    continue
                if ema21 <= ema50:
                    continue

                score = 0
                score += 2 if dist_from_high <= 0.005 else 1
                score += 2 if vol_ratio >= 2.0 else 1
                score += 1 if ema21 > ema50 else 0
                score += 1 if rsi < 70 else 0

                if score >= 3:
                    self.set_holdings(sym, self.position_pct)
                    invested_count += 1
                    self.log(f"BUY {ticker} @ {price:.2f}, score={score}, vol={vol_ratio:.1f}x, dist={dist_from_high*100:.1f}%")
'''


def run_all_backtests():
    """Submit all strategies to QuantConnect for backtesting."""
    print("=" * 60)
    print("QUANTCONNECT BACKTESTS — ALL STRATEGIES")
    print("=" * 60)

    # Authenticate first
    auth = qc.authenticate()
    if not auth.get("success"):
        print(f"Authentication failed: {auth}")
        print("Check QC_USER_ID and QC_API_TOKEN in ~/.agent_zero_env")
        return

    strategies = [
        ("Rudy_Energy_Momentum_v2", ENERGY_MOMENTUM),
        ("Rudy_Short_Squeeze_v2", SHORT_SQUEEZE),
        ("Rudy_Breakout_Momentum_v2", BREAKOUT_MOMENTUM),
    ]

    results = {}
    for name, code in strategies:
        print(f"\n--- {name} ---")
        result = qc.run_backtest(name, code)
        print(result)
        results[name] = result
        time.sleep(2)

    # Save results
    results_file = os.path.join(DATA_DIR, "qc_backtest_results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    run_all_backtests()
