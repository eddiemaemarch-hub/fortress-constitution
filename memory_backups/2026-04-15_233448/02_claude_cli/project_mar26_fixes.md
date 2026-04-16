---
name: March 25-27 2026 — Complete System Overhaul
description: Dashboard real-time, HITL entry, LEAP execution, Gemini/Grok fixes, premium bug, verify alerts, backtests, Bollinger research
type: project
---

Major session March 25-27, 2026:

**Dashboard — Real-Time Fix (March 27):**
- All endpoints share ONE IBKR connection via `_ibkr_cache` with 15s TTL
- `/api/account-live` is single source of truth — fresh IBKR query every 15s
- `/api/status`, `/api/positions`, `/api/status-dump` all read from shared cache
- Strike engine (`updateSAE`) computes premium live from cached prices
- DeepSeek panel computes premium live (was showing 0.0x)
- DeepSeek 200W SMA status shows below/reclaiming/above correctly
- Equity chart card added (shared charts.py module)
- Grok stale flag now computed in JS (fresh/stale with age)

**HITL Entry + LEAP Execution (March 26):**
- `_request_entry_approval()` sends Telegram with full details, waits for YES/NO
- `_check_pending_entry()` reads approval flag each eval cycle
- `_execute_entry()` buys MSTR CALL LEAPs (barbell: safety + spec strikes), NOT stock
- `_get_leap_expiry()` targets January ~2yr out
- em_bot.py handles YES/NO for v2.8+ entries
- Dashboard: `/api/entry/approve`, `/api/entry/reject`
- Constitution Article XI Section 1A: NO STOCK PURCHASES, options only

**Grok CT Sentiment Fix (March 26-27):**
- xAI deprecated `live_search` → migrated to `search` API with X + web sources
- Temperature raised to 1.0 for variance
- Live data injection: Fear & Greed Index (alternative.me), BTC 24h change + volume + trending + dominance (CoinGecko) — all fetched and fed into prompt
- Randomized prompt openers to prevent caching
- Precision instruction (don't round to multiples of 5)
- Stale detection threshold raised to 5 consecutive identical scores

**Gemini Second Brain Fix (March 26):**
- Added MSTR 200W SMA status to prompt (below = resistance, not support)
- Added drawdown thresholds (>25% from ATH = MARKDOWN, not DISTRIBUTION)
- Told Gemini to weight System 13's ML call heavily
- Fixed regime_crosscheck returning null (now always populated)

**Other Fixes:**
- Premium persistence bug in trader_v28.py (string "0.76x" → float)
- Check 18 (strike recommendation) now computes live from current prices — never stale
- Position audit: Trader2/3 state recognition, shared telegram module
- Verify alerts: pre-market threshold 18h, Telegram logging, file locks
- Daily status: System 13 regime + 200W SMA status in Telegram
- Health check: socket probe for IBKR, 120s TTL, fallback-aware

**Backtests Run (all REJECTED — v2.8+ baseline untouchable):**
- HA RSI filter: 0 trades, blocked all signals
- MA Bounce/Breakout (5 variants): all worse than baseline
- EMA+Stoch Reversal (standalone + filter): negative Sharpe standalone, 0 trades as filter
- Bollinger Band (5 variants, weekly): best was BB Exit +380% vs baseline +703%
- Bollinger Band (5 variants, daily): best was BB Exit +538% vs baseline +779%
- Bollinger Band × Trend Adder (5 variants): baseline +490% Sharpe 1.267, all variants worse

**How to apply:** If dashboard panels freeze → check `_ibkr_cache["_last_query_ts"]`. If premium 0.0 → check for trailing "x". If Grok stale → check FnG API + CoinGecko reachability. If strike rec stale → check 18 now auto-refreshes live.
