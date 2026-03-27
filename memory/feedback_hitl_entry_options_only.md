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
- `_execute_entry()` still buys MSTR stock — needs to be updated to buy MSTR CALL LEAPs using the strike recommendation engine output
