---
name: BTC Cycle Phase Intelligence
description: Bitcoin in distribution phase — System 13 regime classifier, phase-aware seasonality, 5-signal confluence to $51-53K bottom
type: project
---

**Current Phase (April 2026):** DISTRIBUTION at 97.7% confidence (System 13, retrained April 28)
- MARKDOWN pressure at 2.3%
- ATH: $126,200 (Oct 6, 2025)
- Current: ~$76,500 (39% drawdown from ATH)
- ~24 months post April 2024 halving
- Bull/bear threshold: $78,500-$80,000
- 200W SMA: ~$60,675 (Kraken live)

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
- **Apr BULL = Continuation, steady gains (+18%) | Apr BEAR = Relief rally trap (-2%) | Apr DISTRIBUTION = Dead cat bounce, double top setup (+6%)**
- **May BULL = Pause before summer (+2%) | May BEAR = Severe sell-off, capitulation events (-12%) | May DISTRIBUTION = Sharp reversal, distribution climax (-15%)**
- **Jun BULL = Shallow pullback, BUY opportunity (-3%) | Jun BEAR = WORST month, forced liquidations, cascading (-15%) | Jun DISTRIBUTION = Cascading sells, support breaking (-10%)**
- Sep BULL = best buying opportunity | Sep BEAR = worst month, devastating drops
- Oct BULL = Uptober, parabolic run starts | Oct BEAR = dead cat trap
- Nov BULL = massive parabolic gains | Nov BEAR = capitulation/cycle bottom

**Current Thesis Alignment (April 2026):**
System 13 reads DISTRIBUTION at 82.2% confidence. April–June in DISTRIBUTION phase = dangerous stretch: April dead cat bounce (+6%) lures late buyers before May distribution climax (-15%) and June cascading sells (-10%). This aligns with the defensive posture — no new entries, tighten stops, capital preservation. If regime shifts to MARKDOWN, April–June becomes even worse (relief trap → capitulation → forced liquidations).

**Morgan Stanley Four Seasons Framework:** Used alongside System 13 for macro regime context.

**High-Alert Months (2hr eval frequency):**
- Bear mode: Jun, Aug, Sep, Oct, Nov
- Bull mode: Sep, Oct, Nov

**Weekend BTC Sentinel (Local):** btc_sentinel.py runs 24/7, checks every 15 min. Monday 9:30 AM auto-eval if BTC dropped >5% over weekend.

**Weekend BTC Sentinel (Cloud):** `btc-weekend-sentinel` scheduled task runs on Anthropic's cloud every 4 hours Sat/Sun (8am/12pm/4pm/8pm ET). Monitors BTC 24/7 with cycle-aware alerts — flags >3% moves, proximity to 200W SMA ($59,433), 250W MA ($56K), 300W MA ($50K). Sends Telegram alerts with regime context and Monday early eval prep. Runs even if Mac is asleep.

**Key level:** $78,500-$80K is the bull/bear threshold. Below = bear phase seasonality applies.

**BTC Moving Average Watch Levels (awareness only, NOT entry/exit filters):**
- 200W SMA: ~$59,433 — v2.8+ arm zone (entry filter)
- 250W MA: ~$56,000 — capitulation watch level (historical cycle bottoms capitulate below this)
- 300W MA: ~$50,000 — absolute floor watch level
- Source: Jordan Camirand analysis (March 21, 2026) — BTC bottoms historically capitulate below 250W MA

**Proximity Zone Detection (in trader1):**
- BELOW 300W = absolute floor zone
- BELOW 250W = capitulation zone
- BELOW 200W = v2.8+ arm zone
- APPROACHING 200W (<10% above) = approaching arm zone
- NEARING 200W (<20% above) = nearing arm zone
- ABOVE ALL MAs = normal operations
- 250W and 300W are AWARENESS levels only — they do NOT trigger entries, exits, or modify v2.8+ logic

Source: DeepSeek analysis + CoinGlass/Bitbo/Bitcoin Suisse/StatMuse data + System 13 regime classifier + Jordan Camirand (250W/300W).

### BTC Cycle Projection Table (April 2026)

**Commander's target: $288K next ATH** — backed by 85% R² fit on monthly LRC.

| Bottom Scenario | Target | Next ATH (5x from bottom) |
|---|---|---|
| **$51-53K (H&S + Monthly LRC)** | Primary | **~$255-265K** |
| **$56-58K (250W MA / Camirand)** | Secondary | **~$280-290K** |
| **$34K (deep capitulation)** | Extreme | **~$204K** |

**Monthly LRC (Lower Red Channel):**
- $51-53K support zone = strongest historical BTC channel
- 85% R² fit — this is pattern recognition, not a guess
- Aligns with Head & Shoulders neckline target
- Aligns with Commander's thesis (expects further decline)
- Aligns with Camirand 250W MA capitulation zone ($53-56K)

**5-Signal Confluence → $51-53K BTC / $67.50 MSTR bottom zone:**
1. Monthly LRC support ($51-53K) — 85% R² fit
2. Head & Shoulders measured move target ($51-53K)
3. Commander's independent thesis (expects further decline)
4. Jordan Camirand 250W MA analysis ($53-56K capitulation)
5. **mNAV analysis** — at BTC $51-53K, MSTR drops to ~$67.50, mNAV 0.57-0.62x (historical capitulation extreme, independently derived from NAV math)

### MSTR mNAV at Bottom Scenarios (April 30, 2026)
| BTC Bottom | MSTR NAV/share | MSTR Price | mNAV |
|---|---|---|---|
| $51K | $109 | ~$67.50 | 0.62x |
| $53K | $113 | ~$67.50 | 0.60x |
| $55K | $118 | ~$67.50 | 0.57x |

### ⚠️ Kill Switch Flag
mNAV kill switch fires at **<0.75x** → triggers at ~MSTR $100-110, well before $67.50 bottom.
- Phase 1 LEAP gets stopped out during drawdown at ~$100-110
- This PROTECTS capital for re-entry instead of riding to zero
- Puts go deep ITM during same drop → fund re-entry at actual bottom
- Phase 3 ($130K) arrives Aug-Oct → deploy at max discount (mNAV 0.57-0.62x)

**Convergence thesis updated:** Phase 1 is a scout position that may get stopped out. The real deployment happens when all three phases converge at the cycle bottom — puts fund it, $130K arrives, and mNAV is at historical extreme discount.

**Implication for v2.8+:**
- Phase 1 LEAP deployed at $75K BTC — may get stopped out by kill switch if BTC drops to $51-53K
- Puts reverse hard during same drop → massive gains → fund Phase 2 scale-in
- Phase 3 ($130K) arrives Aug-Oct 2026 → deploy at or near cycle bottom
- Re-entry at mNAV 0.57-0.62x = generational opportunity
- All three capital phases converge at maximum opportunity zone

**Daily Telegram Report (added 2026-04-29):**
The daily status report (3x/day: 9:35, 12:00, 16:05 ET) now includes:
- BTC Bottom Scanner score/20 with active signals and alert level
- 10Y Treasury yield with macro regime and BTC implication
- Helps Commander track bottom approach and macro headwinds without checking dashboard
