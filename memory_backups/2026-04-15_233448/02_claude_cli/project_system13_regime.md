---
name: System 13 — Neural Regime Classifier
description: CalibratedEnsemble regime classifier (RF300+GB200), 95.6% CV, 4 regimes — awareness layer only, does NOT modify v2.8+
type: project
---

## System 13: Neural Regime Classifier

**Purpose:** Classify the current BTC/MSTR market regime to provide context awareness for the Commander and dashboard. This is an AWARENESS LAYER ONLY — it does NOT modify v2.8+ entry/exit logic.

### Model Architecture
- **Type:** CalibratedEnsemble
- **Components:** RandomForest (300 estimators) + GradientBoosting (200 estimators)
- **CV Accuracy:** 95.6%
- **Calibrated:** Yes — confidence scores are meaningful probabilities

### Four Regimes
1. **ACCUMULATION** — Smart money buying, prices consolidating near lows
2. **MARKUP** — Trending up, bull market confirmation
3. **DISTRIBUTION** — Smart money selling, prices topping out
4. **MARKDOWN** — Trending down, bear market

### Current State (March 2026)
- **Regime:** DISTRIBUTION at 82.2% confidence
- **Secondary:** MARKDOWN pressure rising at 17.8%
- **BTC:** ~$70,500 (44-47% drawdown from $126,200 ATH Oct 2025)
- **Implication:** We are in late distribution / early markdown territory. v2.8+ entry signal has NOT fired yet — waiting for 200W SMA dip+reclaim.

### Integration (Wired into Trader1 — March 21, 2026)
- **BTC price must come from IBKR** (`last_btc_price` in trader state) — NOT from GBTC proxy. GBTC proxy is internal calculation data only, never a display or decision price. See `feedback_ibkr_price_source.md`.
- **trader_v28.py reads regime_state.json** as PRIMARY phase detection (replaces crude $80K threshold)
- Regime logged at every evaluation: `FILTERS: ... | Regime=DISTRIBUTION(82%)`
- Regime + confidence saved to trader state (`last_regime`, `last_regime_confidence`)
- System 13 ML regime maps to bull/bear for seasonality: ACCUMULATION/MARKUP → bull, DISTRIBUTION/MARKDOWN → bear
- Falls back to threshold detection if System 13 data is stale (>7 days)
- High-alert months use 2-hour eval frequency based on detected phase
- Monday 9:30 AM sentinel check triggers early eval on >5% BTC weekend move
- Displayed on dashboard Command Center (System 13 card, auto-refresh 30s)
- Telegram alerts when regime transitions occur
- Does NOT gate or modify v2.8+ entries/exits (per feedback_dont_change_v28plus.md)

### Key Files
- `/Users/eddiemae/rudy/scripts/regime_classifier.py` — Classifier script
- `/Users/eddiemae/rudy/data/regime_state.json` — Current regime + confidence
- `/Users/eddiemae/rudy/data/regime_model.pkl` — Trained model pickle
- `/Users/eddiemae/rudy/data/btc_seasonality.json` — Phase-aware seasonality data

### Reinforcement Learning Layer (March 2026)
System 13 now LEARNS from its own mistakes instead of relying on static historical labels.

- **Experience Replay Buffer:** Every prediction recorded to `rl_experience.json`
- **Outcome Evaluation:** 4 weeks after each prediction, actual BTC returns are scored:
  - ACCUMULATION: >-5% return
  - MARKUP: >+5% return
  - DISTRIBUTION: -10% to +10% return
  - MARKDOWN: <-5% return
- **Per-Regime Confidence Adjustment:** 0.0-1.0x multiplier applied per regime based on historical accuracy
- **Auto-Retrain:** After 50 experiences accumulated, retrains with experience-weighted samples
- **Rolling Accuracy:** Tracked with 0.95 decay factor (recent predictions weighted more heavily)
- **Telegram Alert:** Fires if rolling accuracy drops below 60%
- **Commands:** `--rl-status` (view RL state), `--train --rl` (force RL retrain)
- **Key File:** `/Users/eddiemae/rudy/data/rl_experience.json`

### Integration with All Traders (March 2026)
All 3 traders now read `regime_state.json` for regime-aware behavior.

- **Trader1 (v2.8+):** Regime used for phase detection, Telegram context, and seasonality mapping. Does NOT modify entry/exit logic.
- **Trader2 (MSTR Put) & Trader3 (SPY Put):** Regime-adaptive trailing stop width via `REGIME_TRAIL_ADJUST` dict:
  - `MARKDOWN: +5%` — widen trail, let put winners run during drops
  - `DISTRIBUTION: +2%` — slightly widen, market weakening
  - `ACCUMULATION: 0%` — no adjustment
  - `MARKUP: -3%` — tighten trail, protect put gains during bull runs
- **Trail width formula:** `effective_trail = max(5, base_trail + regime_adjustment)`
  - Floor at 5% regardless of adjustment (prevents overly tight stops)
- **Logging:** Every check cycle logs: `Regime=DISTRIBUTION(82%) | TrailAdj: +2%`
- **Logic:** Puts benefit from market drops, so MARKDOWN = widen (let winners run), MARKUP = tighten (protect gains)

### Gemini Cross-Check (March 2026)
Gemini (Google) provides an independent regime classification as a cross-check against System 13. When both System 13 and Gemini agree on the current regime, confidence is higher. When they disagree, a Telegram alert is sent for Commander review. See `project_rudy_v2_architecture.md` Multi-Brain Intelligence section for full details.

### Stress Test Results
- 95.6% cross-validation accuracy
- Validated against 5 historical regime periods (0/5 false positives)
- Part of the broader v2.8+ stress testing suite (March 2026)
