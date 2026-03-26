---
name: Capital Deployment Plan
description: Three-phase capital deployment — all feeds into ONE v2.8+ MSTR LEAP position, $130K arriving Aug-Oct 2026
type: project
---

Three-phase deployment. All capital converges into ONE v2.8+ position.

**Phase 1 (Now → October 2026):** **$7,832.62 net liq (live IBKR, March 23, 2026)** → enter immediately if v2.8+ signal fires. Do NOT wait for full $130K.

**Phase 2 (On put close):** MSTR $50P Jan28 ($1,253.05 avg cost, currently **-25.0% / $940 value**, activates at +150% = $3,132) + SPY $430P Jan27 ($494.99 avg cost, currently **+20.6% / $597 value**, activates at +100% = $990) proceeds → stay in account for v2.8+. Do NOT withdraw. Do NOT open new puts. Put proceeds are v2.8+ fuel, not hedge replacements. The trailing ladder will close these positions automatically. Put proceeds message added to trader2 and trader3 sell confirmations.

**Live position status (March 23, 2026) — STALE, update from live dashboard:**
- MSTR $50P: $940 current | needs +233% more to hit Tier 1 ($2,192 away)
- SPY $430P: $597 current | needs +66% more to hit Tier 1 ($393 away)
- Neither put near activation — both in hold-and-watch mode
- **mNAV WARNING:** 4 consecutive readings at ~0.751x — 0.1% above kill switch (fires at <0.75x). Monitor closely.

**⚡ v2.8+ SIGNAL STATUS (March 26, 2026):**
- Dipped below 200W SMA: YES — BTC at $71,001, below ~$72K 200W SMA
- Armed: NO — waiting for 2 consecutive Friday MSTR closes above MSTR 200W SMA
- Green weeks: 0/2
- **Entry could fire as soon as next Friday if MSTR reclaims its 200W SMA**

**Phase 3 (Aug-Oct 2026):** $130,000 external capital injection → full scale-in via trend adder / second entry.

**Total: ~$139,650**

**Critical rule:** If signal fires before $130K arrives, enter with what's available. Never let the buy window close because "we're waiting for more capital." The 50/50 scale-in is designed for exactly this — Phase 1 catches the dip+reclaim, Phase 3 becomes the scale-in.

**Put proceeds policy:** MSTR $50P and SPY $430P proceeds feed INTO v2.8+ — they are not withdrawn, not used for new hedges, not reallocated. They are v2.8+ fuel.

**Constitution integration:** V28_CAPITAL_PHASE variables added to constitution_v39.py to track which deployment phase is active.

### MSTR Price Scenario Projections (March 2026)
- **BTC $80K** -> MSTR ~$185-$210 (+32-50% from current)
- **BTC $100K** -> MSTR ~$280-$330 (+100-135%)
- **BTC $126K ATH** -> MSTR parabolic (3x+ multiplier)
- **Standard Chartered forecast:** $150K BTC by end-2026
- Note: MSTR mNAV at ~1.007x (near NAV) = historically cheap entry. Reflexivity loop amplifies BTC moves.
- **Avg cost basis:** $66,384.56/BTC (bitbo.io SEC filing data — more accurate than $75,696 previously reported from video sources)

**Regime-adaptive trailing stops (March 2026):** MSTR $50P and SPY $430P trailing stops are now regime-adaptive via System 13. Trail width adjusts by regime (MARKDOWN +5%, DISTRIBUTION +2%, MARKUP -3%, floor 5%). This lets put winners run longer during market drops and protects gains during bull phases.
