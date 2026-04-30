---
name: Capital Deployment Plan
description: Three-phase capital deployment — all feeds into ONE v2.8+ MSTR LEAP position, $130K arriving Aug-Oct 2026
type: project
---

Three-phase deployment. All capital converges into ONE v2.8+ position.

**Phase 1 — DEPLOYED (April 29, 2026):** Entry fired. MSTR $157.48 | BTC $75,420 | $913 deployed (25%×50% of NLV $7,306). Commander approved YES 3:47 PM. Strike: Safety 100/200/500 (45%) + Spec 800/1000 (55%). LEAPs will face drawdown if BTC drops to $51-53K — time value (2+ years) keeps position alive through the bottom.

**Phase 2 (On put close):** MSTR $50P Jan28 ($1,253.05 avg cost, activates at +150% = $3,132) + SPY $430P Jan27 ($494.99 avg cost, activates at +100% = $990) proceeds → stay in account for v2.8+. Do NOT withdraw. Do NOT open new puts. Put proceeds are v2.8+ fuel.
- **If BTC drops to $51-53K (working bottom target), both puts recover hard and hit activation — Phase 2 capital becomes available exactly when Phase 3 is scaling in near the bottom**
- MSTR $50P currently -43.1% | SPY $430P currently -33.8% — deeply underwater but positioned correctly for the next leg down

**Live position status (April 27, 2026) — FROM TELEGRAM BOT:**
- MSTR $50P: **-43.1%** | activates at +150%
- SPY $430P: **-34.2%** | activates at +100%
- Both puts deeply underwater — MSTR/BTC rallied hard since March

**⚡ v2.8+ SIGNAL STATUS (April 27, 2026) — 🚨 ARMED:**
- **ARMED: YES ✅ — all filters green**
- BTC: $77,653 — above 200W SMA (~$72K), reclaim confirmed
- MSTR: $171.46
- 2 consecutive Friday closes above MSTR 200W SMA: ✅ MET
- Status: Waiting for daily eval trigger
- **⚠️ CRITICAL: Eval Freshness FAILING (check 4/19) — must fix or entry cannot execute**
- All other 18/19 checks passed

**Phase 3 (Aug-Oct 2026):** $130,000 external capital injection → full scale-in via trend adder / second entry.

**Total: ~$139,650**

**Critical rule:** If signal fires before $130K arrives, enter with what's available. Never let the buy window close because "we're waiting for more capital." The 50/50 scale-in is designed for exactly this — Phase 1 catches the dip+reclaim, Phase 3 becomes the scale-in.

**Put proceeds policy:** MSTR $50P and SPY $430P proceeds feed INTO v2.8+ — they are not withdrawn, not used for new hedges, not reallocated. They are v2.8+ fuel.

**Constitution integration:** V28_CAPITAL_PHASE variables added to constitution_v39.py to track which deployment phase is active.

### BTC Cycle Bottom & Next ATH Predictions (April 8, 2026)
| Source | Bottom | Next ATH |
|---|---|---|
| Claude (math extrapolation) | ~$34,100 (73% drop) | ~$204,000 (6x from bottom) |
| Commander (intuition) | ~$35,300 (72% drop) | — |
| Camirand 250W MA thesis | ~$56,000 | — |
| H&S chart targets | $48,000-$52,000 | — |
- Diminishing returns pattern: drops getting shallower each cycle (87% → 84% → 77% → ~73%), gains compressing (131x → 22x → 8x → ~6x)
- All scenarios: v2.8+ fires on MSTR 200W SMA reclaim on the way back up — bottom depth doesn't change entry logic

### MSTR Price Scenario Projections (March 2026)
- **BTC $80K** -> MSTR ~$185-$210 (+32-50% from current)
- **BTC $100K** -> MSTR ~$280-$330 (+100-135%)
- **BTC $126K ATH** -> MSTR parabolic (3x+ multiplier)
- **Standard Chartered forecast:** $150K BTC by end-2026
- Note: MSTR mNAV at ~1.007x (near NAV) = historically cheap entry. Reflexivity loop amplifies BTC moves.
- **Avg cost basis:** $66,384.56/BTC (bitbo.io SEC filing data — more accurate than $75,696 previously reported from video sources)

**Regime-adaptive trailing stops (March 2026):** MSTR $50P and SPY $430P trailing stops are now regime-adaptive via System 13. Trail width adjusts by regime (MARKDOWN +5%, DISTRIBUTION +2%, MARKUP -3%, floor 5%). This lets put winners run longer during market drops and protects gains during bull phases.
