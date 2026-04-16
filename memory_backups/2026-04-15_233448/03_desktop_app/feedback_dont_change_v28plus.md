---
name: Don't Change v2.8+ Strategy Logic
description: User explicitly said do NOT modify v2.8+ entry/exit logic — add safety layers and intelligence around it, not to it
type: feedback
---

"I don't want to change v2.8+ if it's really successful but I want some of these safety measures"

The v2.8+ entry/exit logic is LOCKED:
- Entry: 200W SMA dip+reclaim + BTC>200W + StochRSI<70
- Exit: BTC death cross, max hold, target, floor, trail, euphoria, premium compression
- Trend adder: 50W EMA > 200W SMA for 4 weeks → additional 25% capital

**Why:** The strategy is walk-forward validated (WFE 1.18, 7/7 windows). Changing it risks introducing curve-fitting or breaking proven mechanics.

**How to apply:** Safety infrastructure, cycle intelligence, evaluation frequency, alerts — all fine to add/modify. But NEVER touch the entry filters, exit conditions, or position sizing formulas in trader_v28.py.

**System 13 note (March 2026):** The Neural Regime Classifier (System 13) is an AWARENESS LAYER ONLY. It provides regime context (ACCUMULATION/MARKUP/DISTRIBUTION/MARKDOWN) to the dashboard and alerts, but does NOT modify v2.8+ entry/exit logic. It sits alongside, not inside, the trading engine.

**Kalman filter note (March 2026):** Kalman filter tested as 200W SMA replacement — FAILED catastrophically (WFE -4.29 vs 1.20, -96.4% return). The 200W SMA's lag is the feature, not a bug. Do not replace with adaptive filters.

**Stealth execution note (March 21, 2026):** `build_stealth_order()` replaces MarketOrder with adaptive LimitOrder at the EXECUTION layer only. It does NOT change entry/exit logic — only HOW orders are placed (price jitter, avoid round numbers, internal stops). This is an execution improvement, not a strategy change.

**250W/300W MA note (March 21, 2026):** BTC 250W MA (~$56K) and 300W MA (~$50K) are AWARENESS LEVELS ONLY. They provide proximity zone context in Telegram alerts and dashboard, but do NOT modify v2.8+ entry/exit logic. Only the 200W SMA remains an actual entry filter.
