---
name: Rudy v2.0 System Architecture
description: Overview of the Rudy trading automation framework — 3 authorized traders, Constitution v50.0, IBKR live on port 7496
type: project
---

Rudy v2.0 is a live automated trading system governed by Constitution v50.0.

**Why:** Manages MSTR LEAP entries/exits and defensive put hedges with human-in-the-loop (HITL) approval via Telegram.

**How to apply:**
- 3 authorized traders: Trader1 (trader_v28.py — MSTR LEAP, primary active), Trader2 (trader2_mstr_put.py — MSTR $50P Jan28, SELL ONLY), Trader3 (trader3_spy_put.py — SPY $430P Jan27, SELL ONLY)
- All daemons run as macOS LaunchAgents, poll every 5 min during market hours
- IBKR TWS on port 7496 (live), account U15746102
- System checks: auditor.py (Constitution audit), execution_path_verify.py (19-point Trader1 check), execution_path_verify_t23.py (Trader2/3 ladder check), execution_audit.py (signal-to-order), position_audit.py (IBKR vs JSON reconciliation)
- Telegram module at scripts/telegram.py reads creds from ~/.agent_zero_env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
- State files in ~/rudy/data/, logs in ~/rudy/logs/
