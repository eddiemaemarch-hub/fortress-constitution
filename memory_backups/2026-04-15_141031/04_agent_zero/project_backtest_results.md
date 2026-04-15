---
name: Backtest Results — All Filters Rejected (March 2026)
description: 6 backtest suites tested against v2.8+ baseline — all REJECTED. Baseline Sharpe 0.895-1.267 untouchable.
type: project
---

All research backtests run March 25-27, 2026. v2.8+ baseline wins every test.

**Why:** Commander requested testing various technical indicators as additive filters or standalone strategies. None improved on the 200W SMA dip+reclaim (base) or golden cross 4-week confirm (trend adder).

**Results Summary:**

| Test | Variants | Best Alternative | Baseline | Verdict |
|---|---|---|---|---|
| HA RSI Filter | 1 | 0 trades (blocked all) | Sharpe 0.280 | REJECT |
| MA Bounce/Breakout | 4 | Slope (identical) | Sharpe 0.280 | REJECT |
| EMA+Stoch Reversal | 2 | Standalone -0.520 Sharpe | Sharpe 0.280 | REJECT |
| Bollinger Weekly | 4 | BB Exit Sharpe 0.472 | Sharpe 0.895 | REJECT |
| Bollinger Daily | 4 | BB Exit Sharpe 0.556 | Sharpe 0.913 | REJECT |
| Bollinger × Trend Adder | 4 | BB Timing Sharpe 0.984 | Sharpe 1.267 | REJECT |

**Key Insight:** v2.8+ signals are rare by design (2-4 trades over 10 years). Adding filters either blocks the few good signals or adds noise. The 200W SMA is the optimal cycle-bottom detector for MSTR/BTC — no technical overlay improves it.

**How to apply:** When asked to test new indicators, run against v2.8+ baseline. Must beat on BOTH Sharpe AND profit factor to qualify. All scripts saved in ~/rudy/scripts/backtest_*.py for reproducibility.
