---
name: Position Audit Fixed 2026-03-25
description: Fixed position_audit.py to recognize Trader2/3 state files and use shared telegram module
type: project
---

On 2026-03-25, position_audit.py had two bugs:
1. get_rudy_positions() only checked trader_v28_state.json and old trader*_position*.json files — missed trader2_state.json and trader3_state.json, causing false ORPHAN alerts for the MSTR and SPY puts
2. send_telegram() tried to read ~/rudy/config/config.json which doesn't exist — fixed to use the shared scripts/telegram.py module (reads creds from ~/.agent_zero_env)

**Why:** The orphan false positives masked real audit value; broken Telegram meant no alerts on actual mismatches.

**How to apply:** If new traders are added, their state files must also be registered in get_rudy_positions().
