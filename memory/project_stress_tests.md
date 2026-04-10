---
name: v2.8+ Stress Test Results
description: All stress tests completed March 2026 — Flash Crash PASS, Monte Carlo CONDITIONAL, mNAV Apocalypse PASS, System 13 95.6% CV
type: project
---

### Stress Tests Completed March 20, 2026

**Walk-Forward:** WFE 1.18-1.20, 7/7 windows, +6,750.6% stitched OOS
**Regime Stress:** 0/5 false positives (2018 winter, 2021 top, 2022 bear, COVID crash, bear rally traps)
**Execution:** Survives 200bps slippage (Sharpe 0.171)

**Advanced Tests:**
1. **Flash Crash Gap-and-Trap:** PASS — simulated -10% to -30% MSTR gap-downs. Put positions BENEFIT from crashes.
2. **Monte Carlo Bootstrap:** CONDITIONAL — 5,000 shuffles, 80% annual vol. 40%+ drawdown near-certain WITHOUT circuit breakers. Circuit breakers (2% daily cap + 5-loss shutdown) = survival. Proves safety mechanisms are REQUIRED.
3. **mNAV Apocalypse:** PASS (was FAIL before kill switch) — BTC flat, MSTR de-rates 2.5x→0.25x. 0.75x kill switch saves 2x capital at 0.5x, 7.5x at 0.25x.

**System 13 Neural Regime Classifier:**
- CV Accuracy: 95.6% (CalibratedEnsemble RF300+GB200)
- 4 regimes validated: ACCUMULATION, MARKUP, DISTRIBUTION, MARKDOWN

**Cross-Ticker Validation:**
- AVGO: +501.5%, Sharpe 0.888 (research only, NOT deployed)
- MARA: FAILED — no structural edge

**Lookahead Audit:** Clean (March 2026)

## Stealth Execution (March 21, 2026)
- Stealth Execution layer added — defends against institutional front-running and stop-hunt patterns
- `build_stealth_order()` in all 3 traders converts MarketOrders to adaptive LimitOrders with jitter
- Internal trailing stops (not exchange stop orders) prevent institutional algo exploitation

## Kalman Filter Backtest (March 21, 2026) — FAILED
- Replaced 200W SMA with adaptive Kalman filter for trend estimation
- Result: -96.4% return vs original -64.7%, Sharpe -0.15 vs 0.65
- WFE: -4.29 (catastrophic OOS failure) vs original WFE 1.20
- The Kalman filter's faster adaptation generates false dip+reclaim signals
- The 200W SMA's extreme slowness is the FEATURE — only fires on genuine cycle lows
- Verdict: NOT ADOPTED. Original v2.8+ 200W SMA logic confirmed as optimal.
- Script: /Users/eddiemae/rudy/scripts/kalman_backtest.py
- Results: /Users/eddiemae/rudy/data/kalman_backtest_results.json

## Candlestick Filter Backtest (March 23, 2026) — REJECTED
- Tested "All Candlestick" indicator integration with v2.8+ across 4 modes × 7 WF windows
- Modes: none (baseline), strict (Hammer+Engulfing+Morning Star), window_3 (3-bar confirmation), high_prob (Hammer+Engulfing only)
- Result: ALL candlestick modes reduce performance vs baseline
  - none (baseline): avg OOS +13.9%, Sharpe 0.011 ← WINNER
  - strict: +4.3%, Sharpe -0.844 (Δ -9.6%)
  - window_3: +2.4%, Sharpe -0.559 (Δ -11.5%)
  - high_prob: -1.0%, Sharpe -1.402 (Δ -14.9%)
- Reason: v2.8+ filters already encode context that candlesticks detect. Adding patterns over-filters and blocks valid entries (especially W4 2023-07→2024-12 +70.9% baseline vs -4.1% high_prob)
- Verdict: DO NOT add candlestick filters to v2.8+. Script: `backtest_candlestick_v28plus.py`

## Quarterly OOS Re-Validation (March 22, 2026) — OPERATIONAL
- Gap identified: v2.8+ trend adder parameters (standard_medium_safety) were validated once on original 7 WF windows but never re-checked as new data arrived
- Fix: `oos_revalidation.py` — quarterly script runs full 27-param IS grid + OOS on latest completed quarter
- Drift thresholds: PASS (live params ≥90% of winner) | WARN (75–89%) | DRIFT_ALERT (<75% or different winner dominates)
- WFE ratio check: OOS/IS score must exceed 0.50 to confirm non-overfitting
- Scheduled: First Monday of each quarter at 6 AM (register via fresh Claude session as `quarterly-oos-revalidation`)
- Current Q4 2025 dry run: confirmed 28 backtests planned (27 IS + 1 OOS)

### Enhanced Diagnostics (March 28, 2026)
Four risk mitigations added per external review:
1. **Rolling 4Q OOS average** — smooths single-quarter anomalies, prevents false alerts from outlier quarters
2. **Grid winner stability tracking** — flags if >2 unique winners in last 4 quarters (noise-fitting signal)
3. **Consecutive drift alert escalation** — 1=monitor, 2=mandatory walk-forward review, 3+=re-optimize or pause strategy. Persistent tracker in `data/oos_revalidation_history.json`
4. **Regime-aware verdict** — MARKDOWN/DISTRIBUTION regimes soften DRIFT_ALERT→WARN if rolling avg still positive (distinguishes decay from temporary adverse conditions)
- IS development set is **rolling anchored**: fixed start 2016-01-01, expanding end each quarter
