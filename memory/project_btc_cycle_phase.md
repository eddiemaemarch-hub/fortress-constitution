---
name: BTC Cycle Phase Intelligence
description: Bitcoin in distribution phase as of March 2026 — System 13 regime classifier, phase-aware seasonality, weekend sentinel
type: project
---

**Current Phase (March 2026):** DISTRIBUTION at 82.2% confidence (System 13)
- MARKDOWN pressure rising at 17.8%
- ATH: $126,200 (Oct 6, 2025)
- Current: ~$71,000 (44-47% drawdown from ATH)
- 23 months post April 2024 halving
- Bull/bear threshold: $78,500-$80,000
- 200W SMA: ~$72,000 (updated March 2026 — was stale at $59,433)
- Commander outlook: Bear flag daily + 4H. Expecting further downside. Entry NOT expected until ~October 2026.

**System 13 Neural Regime Classifier:**
- Model: CalibratedEnsemble (RF300 + GB200), 95.6% CV accuracy
- 4 regimes: ACCUMULATION, MARKUP, DISTRIBUTION, MARKDOWN
- Awareness layer only — does NOT modify v2.8+ entry/exit logic
- Files: regime_classifier.py, regime_state.json, regime_model.pkl

**Phase Detection (in trader_v28.py):**
- BTC > $80K + <25% from ATH = BULL
- BTC < $80K + >40% from ATH = BEAR
- Transition zone: 200W SMA as tiebreaker

**Phase-Aware Seasonality (Month x Phase table):**
Same month means opposite things in bull vs bear. Key examples:
- Mar BULL = Very bullish, strong close | Mar BEAR = High volatility, often a bounce before drop
- Sep BULL = best buying opportunity | Sep BEAR = worst month, devastating drops
- Oct BULL = Uptober, parabolic run starts | Oct BEAR = dead cat trap
- Nov BULL = massive parabolic gains | Nov BEAR = capitulation/cycle bottom

**Morgan Stanley Four Seasons Framework:** Used alongside System 13 for macro regime context.

**High-Alert Months (2hr eval frequency):**
- Bear mode: Jun, Aug, Sep, Oct, Nov
- Bull mode: Sep, Oct, Nov

**Weekend BTC Sentinel (Local):** btc_sentinel.py runs 24/7, checks every 15 min. Monday 9:30 AM auto-eval if BTC dropped >5% over weekend.

**Weekend BTC Sentinel (Cloud):** `btc-weekend-sentinel` scheduled task runs on Anthropic's cloud every 4 hours Sat/Sun (8am/12pm/4pm/8pm ET). Monitors BTC 24/7 with cycle-aware alerts — flags >3% moves, proximity to 200W SMA (~$72K), 250W MA ($56K), 300W MA ($50K). Sends Telegram alerts with regime context and Monday early eval prep. Runs even if Mac is asleep.

**Key level:** $78,500-$80K is the bull/bear threshold. Below = bear phase seasonality applies.

**BTC Moving Average Watch Levels (awareness only, NOT entry/exit filters):**
- 200W SMA: ~$72,000 — v2.8+ arm zone (entry filter); BTC currently BELOW this
- 250W MA: ~$56,000 — capitulation watch level (historical cycle bottoms capitulate below this)
- 300W MA: ~$50,000 — absolute floor watch level
- Source: Jordan Camirand "BRACE YOURSELF" (March 31, 2026) — BTC historically dips BELOW 250W MA before next bull run

**250W MA Capitulation Thesis (Jordan Camirand, March 31 2026):**
- Historical precedent: BTC dipped below 250W MA in 2015, March 2020, and June 2022 before launching next cycle
- Current 250W MA: ~$56,000 — target capitulation zone
- Camirand projects a "fifth wave" down to ~$56K before the next bull run begins
- This aligns exactly with Commander's October 2026 entry expectation
- At $56K: BTC would be ~55% off ATH ($126,200) — consistent with prior cycle bear market depth
- **v2.8+ implication:** If BTC bottoms near $56K, it will need to reclaim $72K+ (200W SMA) on the way back up — that reclaim + MSTR 200W SMA reclaim is the entry trigger. October 2026 is the expected window.

**Proximity Zone Detection (in trader1):**
- BELOW 300W = absolute floor zone
- BELOW 250W = capitulation zone
- BELOW 200W = v2.8+ arm zone
- APPROACHING 200W (<10% above) = approaching arm zone
- NEARING 200W (<20% above) = nearing arm zone
- ABOVE ALL MAs = normal operations
- 250W and 300W are AWARENESS levels only — they do NOT trigger entries, exits, or modify v2.8+ logic

Source: DeepSeek analysis + CoinGlass/Bitbo/Bitcoin Suisse/StatMuse data + System 13 regime classifier + Jordan Camirand (250W/300W).
