---
name: HITL Entry Approval + Options Only — No Stock Purchases
description: ALL entries require Commander YES/NO approval. Only option (LEAP/PUT) buys allowed — absolutely no stock purchases.
type: feedback
---

ALL entry orders require Commander approval via Telegram YES/NO before execution. The system must NEVER auto-execute a buy without explicit approval.

Additionally: ABSOLUTELY NO STOCK PURCHASES. Only option (LEAP/PUT) buys are authorized. trader_v28.py must buy MSTR CALL LEAPs, not MSTR stock shares.

**Why:** Commander wants full control over every capital deployment decision. The system recommends and asks — the Commander decides. Stock purchases were never intended; the strike recommendation engine already picks LEAP strikes.

**How to apply:**
- trader_v28.py now uses `_request_entry_approval()` instead of `_execute_entry()` when signal fires
- Pending entry stored in state as `pending_entry`, approved via `entry_approved` flag
- em_bot.py handles YES/NO replies for v2.8+ entries
- Dashboard has /api/entry/approve and /api/entry/reject endpoints
- Constitution Article XI Section 1A codifies this rule
- `_execute_entry()` now buys MSTR CALL LEAPs (barbell: safety + spec strikes) via IBKR Option contracts
- `_get_leap_expiry()` targets January ~2 years out (e.g., Jan 2028 for 2026 entry)
- Each strike gets proportional capital allocation based on safety/spec weights
- All filled contracts stored in state as `leap_contracts` array with type/strike/expiry/qty/price/cost
- Telegram confirmation shows every filled contract with costs
- **IMMEDIATE EXECUTION on approval (March 28, 2026):** When Commander replies YES, entry executes NOW — not on next eval cycle. Bot calls dashboard `/api/entry/approve` which spawns `_execute_entry()` in background thread. Fallback: if dashboard unreachable, sets flag for next eval.

**Entry timeline (current):**
- Week 1: MSTR closes green above 200W → green_count=1
- Week 2 (Fri 3:45 PM): green_count=2 → ARMED → Telegram asks YES/NO
- Commander replies YES → LEAP order executes IMMEDIATELY at live price
- No more waiting until Week 3. Gap reduced from 1 week to however long Commander takes to reply.
