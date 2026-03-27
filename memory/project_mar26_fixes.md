---
name: March 25-27 2026 — Complete System Overhaul
description: Dashboard real-time, HITL entry, LEAP execution, Gemini/Grok fixes, premium bug, verify alerts, backtests
type: project
---

Major session March 25-27, 2026:

**Why:** Dashboard panels stale, entries auto-executing without approval, buying stock instead of LEAPs, Gemini/Grok hallucinating.

**Dashboard — Real-Time Fix (March 27):**
- All endpoints now share ONE IBKR connection via `_ibkr_cache` with 15s TTL
- `/api/account-live` is the single source of truth — queries IBKR fresh every 15s
- `/api/status`, `/api/positions`, `/api/status-dump` all read from shared cache
- No more separate clientId connections per endpoint (was causing IBKR connection limits)
- Strike engine (`updateSAE`) computes premium live from cached MSTR/BTC prices
- BTC price from sentinel (15min) overlaid on top

**HITL Entry + LEAP Execution (March 26):**
- `_request_entry_approval()` sends Telegram with full details, waits for YES/NO
- `_check_pending_entry()` reads approval flag each eval cycle
- `_execute_entry()` rewritten: buys MSTR CALL LEAPs (barbell: safety + spec strikes), NOT stock
- `_get_leap_expiry()` targets January ~2yr out
- em_bot.py handles YES/NO for v2.8+ entries
- Dashboard: `/api/entry/approve`, `/api/entry/reject`
- Constitution Article XI Section 1A: NO STOCK PURCHASES, options only

**Other Fixes:**
- Premium persistence bug (string "0.76x" → float)
- Gemini prompt: resistance/support rule, drawdown thresholds, S13 weighting
- Grok CT: migrated to `search` API, temp 0.7, live price grounding, randomized prompts
- Position audit: Trader2/3 state recognition, shared telegram module
- Verify alerts: pre-market threshold, Telegram logging, file locks
- Equity chart: shared charts.py, Telegram + dashboard
- Daily status: System 13 regime + 200W SMA status in Telegram

**How to apply:** If dashboard panels freeze, check `_ibkr_cache["_last_query_ts"]` age. If premium shows 0.0, check trader_v28_state.json `last_premium` field for trailing "x" string.
