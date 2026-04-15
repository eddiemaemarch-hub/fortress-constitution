---
name: BTC Bear Market Bottom Detector
description: 8-signal composite BTC cycle bottom detector — QC backtest validated (100% win rate at t=10), live scanner daemon, walk-forward + stress test pipeline
type: project
---

### BTC Bottom Detector v1.0 (March 30, 2026)

**Why:** Need independent multi-signal BTC cycle bottom detection beyond the single 200W SMA indicator in v2.8+. Feeds into deployment timing for MSTR LEAP entries.

**How to apply:** Use live scanner alerts (Telegram) to confirm accumulation zones. Score ≥10 = strong bottom, ≥13 = max conviction. Do NOT auto-trade on signals — Commander decides.

### 8-Signal Composite (max 20 pts)

| Signal | Max | Source |
|--------|-----|--------|
| 200W SMA Proximity | 3 | Price vs 200-week SMA |
| Weekly RSI | 3 | RSI(14) oversold on weekly |
| Pi Cycle Bottom | 3 | 111DMA vs 350DMA×2 |
| MVRV Z-Score Proxy | 2 | Price vs 200-day mean |
| Puell Multiple Proxy | 2 | Volume collapse proxy |
| Volume Capitulation | 2 | Weekly volume spike |
| Bollinger Band | 2 | Weekly lower BB(20,2) |
| MACD Histogram | 3 | Weekly momentum reversal |

### Backtest Results (production: threshold=10, 3 signals, 2-week confirm)
- 5 trades over 11 years, **100% win rate**, 96.3% avg gain
- 18.9% max drawdown, Sharpe 0.616, +304% net profit

### Files
- QC Algo: `quantconnect/BTCBottomDetector_v1.py`
- Runner: `scripts/run_qc_bottom_detector.py`
- Walk-Forward: `scripts/walk_forward_bottom_detector.py` (running in background)
- Stress Tests: `scripts/stress_test_bottom_detector.py` (running in background)
- Live Scanner: `scripts/btc_bottom_scanner.py` (LaunchAgent: com.rudy.btc-bottom-scanner, 6h interval)
- Data: `data/btc_bottom_scanner_state.json`, `data/btc_weekly_cache.json`

### Alert Levels
- 0-6: NONE
- 7-9: ELEVATED (early accumulation)
- 10-12: HIGH (strong bottom — prepare deployment)
- 13+: EXTREME (max conviction)

### Current Reading (2026-03-30)
- Score: 7/20 ELEVATED
- Active: RSI_DEEP, PI_DEEP, MVRV_LOW, MACD_RISING
- BTC: ~$67,364

### QC Note
- Crypto uses QuoteBar (no .Volume attribute) — fixed with try/except fallback
- SPY added as scheduling anchor (crypto has no market hours)
- Walk-forward uses same 7 anchored windows as v2.8+ but from 2015
