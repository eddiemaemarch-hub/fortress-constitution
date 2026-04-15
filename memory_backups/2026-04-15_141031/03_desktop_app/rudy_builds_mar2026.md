# Rudy Builds — March 22, 2026

## 1. OOS Re-Validation System
- **File**: `~/rudy/scripts/oos_revalidation.py`
- Auto-detects last completed quarter (e.g., Q4 2025 → IS: 2016→Sep30, OOS: Oct1→Dec31)
- Runs full 27-param IS grid (3×3×3), same combos as original walk-forward
- Runs 1 OOS backtest with best params to confirm non-overfitting
- Drift detection: PASS ≥90% / WARN 75-89% / DRIFT ALERT <75% of winner
- WFE ratio check: OOS/IS must exceed 0.50
- Telegram verdict with top 5 rankings
- Never auto-updates live params — report only, Commander decides
- **Schedule**: First Monday of Jan/Apr/Jul/Oct 6AM

## 2. LEAP Expiry Extension — Approval Loop Closed
- trader2_mstr_put.py + trader3_spy_put.py: Added approval polling at top of check_position()
- Reads `expiry_roll_commander_approved/rejected` flags from state
- mcp_server.py: Added `approve_expiry_roll(trader, action)` MCP tool
- Flow: Telegram alert → Commander approves via MCP → daemon rolls on next cycle

## 3. Grok CT Fixes
- Stuck-score bug fixed (was stuck at 35 for 4 runs)
- GREED threshold raised: >30 → >50
- Prompt anchored to "last 2 hours only"
- Stale alert added to Telegram
- grok-intel-scan LaunchAgent registered (weekdays 8 AM)

## 4. Global Memory Updated
- MEMORY.md, project_rudy_v2_architecture.md, reference_key_files.md, project_stress_tests.md
