---
name: 10Y Treasury Yield Tracker
description: Macro signal daemon tracking 10-year Treasury yield from Yahoo Finance (^TNX) hourly. Rising yield = BTC headwind, falling = tailwind.
type: project
---

### 10Y Treasury Yield Tracker v1.0 (2026-04-15)

**Why:** 10Y Treasury yield is a leading macro indicator for risk assets. Rising yields raise opportunity cost for non-yielding BTC; falling yields are supportive. Added as awareness layer — does NOT modify v2.8+ entry/exit logic (per Commander's rule).

**How to apply:** Check macro regime before deployment decisions. If regime is HIGH or EXTREME_HIGH, expect BTC headwinds. Regime data is on dashboard and available via `/api/treasury-yield`.

### Files
- Script: `scripts/treasury_yield_tracker.py`
- LaunchAgent: `com.rudy.treasury-yield` (every 3600s / 1 hour)
- State: `data/treasury_yield.json`
- Log: `logs/treasury_yield.log`
- API: `GET /api/treasury-yield`

### Data Source
Yahoo Finance `^TNX` (CBOE 10-Year Treasury Note Yield Index). No API key required.

### Macro Regime Thresholds
| Yield | Regime | BTC Implication |
|-------|--------|-----------------|
| ≥5.0% | EXTREME_HIGH | Strong headwind, risk-off pressure |
| ≥4.5% | HIGH | Headwind — monitor flows |
| ≥4.0% | ELEVATED | Mild headwind |
| ≥3.5% | NEUTRAL | Neutral |
| ≥3.0% | SUPPORTIVE | Tailwind for risk assets |
| <3.0% | LOW | Strong tailwind, liquidity supportive |

### Current Reading (2026-04-15)
- 10Y: 4.275% | Change: +1.9bps today
- Regime: ELEVATED (mild BTC headwind)
- Aligns with DISTRIBUTION phase defensive posture

### v2.8+ Integration (awareness only, v2.8+ logic unchanged)
1. **HITL Entry Approval Alerts** — `trader_v28.py _request_entry_approval()` now includes a `🌐 Macro (awareness)` section showing 10Y yield, regime, and BTC implication so Commander has macro context before approving YES/NO.
2. **Dashboard Panel** — `📉 10Y Treasury — Macro` card in sidebar. Shows yield, change in bps, regime color-coded (red=HIGH/EXTREME_HIGH, green=SUPPORTIVE/LOW), BTC implication, last update. Refreshes every 60s.
3. **No filter/threshold modifications** — v2.8+ entry filters and exit logic remain untouched per Commander's Article XI rule.
