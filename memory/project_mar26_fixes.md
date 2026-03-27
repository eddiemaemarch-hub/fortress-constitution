---
name: March 26 2026 — Dashboard, Gemini, Premium, Verify Fixes
description: Major fixes across dashboard live values, Gemini prompt accuracy, premium persistence, and morning Telegram alerts
type: project
---

Session on 2026-03-25 to 2026-03-26 — comprehensive system fixes:

**Why:** Multiple panels showing stale/incorrect data, morning Telegram alerts missing, Gemini hallucinating.

**Fixes applied:**

1. **position_audit.py** — Added Trader2/3 state file recognition (was showing false ORPHAN alerts). Fixed Telegram to use shared telegram.py module instead of missing config/config.json.

2. **execution_path_verify_t23.py** — Pre-market state freshness threshold raised to 18h (was failing at 9:20 AM because traders only poll during market hours). Added Telegram send logging. Added file lock to prevent duplicate runs.

3. **execution_path_verify.py** — Added Telegram send logging + file lock.

4. **daily_status.py** — Added System 13 regime display + MSTR 200W SMA status (below/reclaiming/above) to Telegram. Added equity chart generation + Telegram photo send. Uses shared charts.py module.

5. **charts.py** — New shared chart module (GitHub-dark theme, monospace font, annotated values, cost basis lines).

6. **web/app.py (dashboard)** — Fixed /api/status to use live IBKR position lookups instead of stale state files. Fixed DeepSeek panel to compute premium live from IBKR+sentinel prices instead of stale eval state. Added 200W SMA status (below/reclaiming/above) to DeepSeek panel JS. Added equity chart card + /api/equity_chart endpoint. Added make_response import. Added reqAccountUpdates to IBKR background feed.

7. **trader_v28.py** — Fixed premium persistence bug: filters dict stored premium as "0.76x" (string), float() conversion failed silently → stored 0.0. Now strips trailing "x" before converting.

8. **gemini_brain.py** — Added MSTR 200W SMA status to prompt. Added resistance/support rule (below MA = resistance, not support). Added clearer regime definitions with drawdown thresholds (>25% = MARKDOWN not DISTRIBUTION). Told Gemini to weight System 13's ML call heavily.

9. **Backtests run:** HA RSI (REJECTED), MA Bounce/Breakout 5 variants (all REJECTED), EMA+Stoch Reversal standalone+filter (REJECTED). v2.8+ baseline remains untouchable.

**How to apply:** If dashboard panels show stale data, check: (1) IBKR background feed connected (dashboard.log), (2) trader daemon state file timestamps fresh, (3) premium not 0.0 in state file.
