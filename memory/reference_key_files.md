---
name: Key File Locations
description: Critical file paths for Rudy v2.0 — scripts, config, data, logs, LaunchAgents
type: reference
---

### MCP Server
- `/Users/eddiemae/rudy/scripts/mcp_server.py` — MCP server (FastMCP, stdio transport, launched by Claude Desktop)
- `/Users/eddiemae/rudy/scripts/.mcp_venv/` — MCP server's Python venv (Python 3.12). Install deps here, NOT system Python: `.mcp_venv/bin/pip install mcp ib_insync requests`
- **asyncio rule:** Any ib_insync call in MCP must run in `ThreadPoolExecutor` + `asyncio.set_event_loop(asyncio.new_event_loop())` — FastMCP owns the main loop
- **⚡ LIVE DATA RULE (March 23, 2026):** For ANY account balance, position value, unrealized P&L, or price question — call `mcp__rudy-trading__get_account_summary` FIRST. NEVER answer from state files. State files = daemon snapshots (hours stale). MCP = live TWS. Proven: state said -21.2% MSTR put, live IBKR said -25.0%.

### Scripts
- `/Users/eddiemae/rudy/scripts/trader_v28.py` — Main v2.8+ trading daemon (includes BTC_250W_MA_APPROX and BTC_300W_MA_APPROX constants for proximity zone detection). **LEAP Expiry Extension Protocol added March 23, 2026:** `EXPIRY_ROLL_WARNING_DAYS=180`, `EXPIRY_ROLL_URGENT_DAYS=90`, `Option` imported from ib_insync, `_check_expiry_extension()` scans IBKR for MSTR CALL positions, `approve_expiry_roll()` auto-executes sell-old/buy-new on IBKR, `reject_expiry_roll()`, hook in `manage_position()`. All 3 expiry roll methods now parity with T2/T3.
- `/Users/eddiemae/rudy/scripts/trader2_mstr_put.py` — MSTR $50P ladder
- `/Users/eddiemae/rudy/scripts/trader3_spy_put.py` — SPY $430P ladder
- `/Users/eddiemae/rudy/scripts/btc_sentinel.py` — 24/7 BTC monitor
- `/Users/eddiemae/rudy/scripts/telegram.py` — Shared Telegram module (loads creds from ~/.agent_zero_env)
- `/Users/eddiemae/rudy/scripts/auditor.py` — **REWRITTEN March 23, 2026.** Daily post-market audit (4 PM Mon-Fri). Checks T1/T2/T3 state files only (no direct IBKR), Constitution v50.0 rules, clone prohibition, daily loss cap. Sends Telegram summary. Old version had wrong SYSTEMS dict (Systems 1-14, v43.0), paper test violations, no LaunchAgent.
- `/Users/eddiemae/rudy/scripts/execution_path_verify.py` — **NEW March 23, 2026.** Trader1 19-check execution path verifier. Runs Mon-Fri 9:20 AM + 3:45 PM. Checks 1-19: daemon, LaunchAgent, IBKR, eval freshness, state, filters, Telegram HITL, clone prohibition, PID lock, entry/exit code, IBKR position, trail stop math, pending sell, profit-taking roadmap, execute sell path, LEAP expiry, entry sizing, strike recommendation, **LEAP expiry roll protocol (check 19: live IBKR CALL scan + days countdown + protocol callable + pending roll status)**
- `/Users/eddiemae/rudy/scripts/execution_path_verify_t23.py` — **NEW March 23, 2026.** Trader2+Trader3 31-check execution path verifier. Runs Mon-Fri 9:20 AM + 3:45 PM. Shared: IBKR, Telegram HITL, clone prohibition. Per-trader (×2): daemon, LaunchAgent, state fresh, state valid, IBKR position, ladder status, trail stop math, pending sell (FAIL >30min), profit-taking sequence, execute sell path, expiry roll, PID lock, exit code.

### Stealth Execution
- `build_stealth_order()` exists in all 3 trader scripts (trader_v28.py, trader2_mstr_put.py, trader3_spy_put.py) — no separate file, integrated into each trader

### Web
- `/Users/eddiemae/rudy/web/app.py` — Dashboard (port 3001, ALL HTML/JS/CSS inline)

### Config
- `/Users/eddiemae/rudy/constitution_v39.py` — Constitution v50.0
- `/Users/eddiemae/.agent_zero_env` — Telegram bot token + chat ID (DO NOT commit)

### PineScript
- `/Users/eddiemae/rudy/pinescript/rudy_v28plus.pine` — Primary PineScript
- `/Users/eddiemae/rudy/strategies/pinescript_mstr_cycle_low_entry_v28plus.pine` — Strategies copy

### MSTR Treasury Auto-Updater
- `/Users/eddiemae/rudy/scripts/mstr_treasury_updater.py` — Weekly scraper (bitbo.io + stockanalysis.com), writes treasury JSON
- `/Users/eddiemae/rudy/data/mstr_treasury.json` — Live treasury data (holdings, avg cost, diluted shares), read by trader_v28.py
- `~/.claude/scheduled-tasks/mstr-treasury-update/SKILL.md` — Monday 8:30 AM scheduled task

### MSTR Holdings Data (PineScript — still manual on new 8-K)
- `/Users/eddiemae/rudy/pinescript/rudy_v28plus.pine` — PineScript holdings data (hardcoded, Pine can't read JSON)
- `/Users/eddiemae/rudy/strategies/pinescript_mstr_cycle_low_entry_v28plus.pine` — Strategies PineScript holdings data (hardcoded)

### System 13 (Regime Classifier)
- `/Users/eddiemae/rudy/scripts/regime_classifier.py` — Neural Regime Classifier (CalibratedEnsemble RF300+GB200)
- `/Users/eddiemae/rudy/data/regime_state.json` — Current regime state (DISTRIBUTION 82.2%)
- `/Users/eddiemae/rudy/data/regime_model.pkl` — Trained model pickle
- `/Users/eddiemae/rudy/data/btc_seasonality.json` — Phase-aware seasonality table (Month x Phase)
- `/Users/eddiemae/rudy/data/rl_experience.json` — RL experience replay buffer (predictions + outcomes)

### Data (state files)
**WARNING: State files are daemon snapshots — can be hours stale. Use MCP `get_account_summary` for live data.**
- `/Users/eddiemae/rudy/data/trader_v28_state.json` — v2.8+ state. New expiry roll fields (March 23): `pending_expiry_roll`, `expiry_roll_alerted_180d`, `expiry_roll_alerted_90d`, `expiry_roll_commander_approved`, `expiry_roll_commander_rejected`, `roll_history`
- `/Users/eddiemae/rudy/data/trader2_state.json` — MSTR put state. **Live position (March 23):** $50P Jan28 (expiry 20280121), conId 816983615, avg cost $1,253.05, 1 contract, -25.0% unrealized
- `/Users/eddiemae/rudy/data/trader3_state.json` — SPY put state. **Live position (March 23):** $430P Jan27 (expiry 20270115), conId 730443288, avg cost $494.99, 1 contract, +20.6% unrealized
- `/Users/eddiemae/rudy/data/btc_sentinel_state.json` — Sentinel state
- `/Users/eddiemae/rudy/data/breaker_state.json` — Circuit breaker state
- `/Users/eddiemae/rudy/data/pending_repairs.json` — Self-repair proposals and history

### Logs
- `/Users/eddiemae/rudy/logs/execution_path_verify.log` — Trader1 19-check verifier log (runs 2×/day)
- `/Users/eddiemae/rudy/logs/execution_path_verify_err.log` — Trader1 verifier stderr
- `/Users/eddiemae/rudy/logs/execution_path_verify_t23.log` — T2+T3 31-check verifier log (runs 2×/day)
- `/Users/eddiemae/rudy/logs/execution_path_verify_t23_err.log` — T2+T3 verifier stderr
- `/Users/eddiemae/rudy/logs/auditor.log` — Daily post-market audit log (4 PM Mon-Fri)
- `/Users/eddiemae/rudy/logs/auditor_err.log` — Auditor stderr
- `/Users/eddiemae/rudy/logs/trader_v28.log` — Trader1 daemon log
- `/Users/eddiemae/rudy/logs/trader2.log` — Trader2 daemon log
- `/Users/eddiemae/rudy/logs/trader3.log` — Trader3 daemon log

### LaunchAgents
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.trader1.plist` (created March 22, 2026)
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.trader2.plist`
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.trader3.plist`
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.dashboard.plist`
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.cloudflared.plist`
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.btc-sentinel.plist`
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.auditor.plist` — auditor.py Mon-Fri 4:00 PM ET
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.execution-verify.plist` — execution_path_verify.py Mon-Fri 9:20 AM + 3:45 PM ET
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.execution-verify-t23.plist` — execution_path_verify_t23.py Mon-Fri 9:20 AM + 3:45 PM ET
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.execution-audit.plist` — execution_audit.py Mon-Fri 9:00 AM
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.daily-status.plist` — daily_status.py Mon-Fri 9:35 AM / 12 PM / 4:05 PM
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.gronk-scan.plist` — gronk.py Mon-Fri 8am
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.youtube-scan.plist` — youtube_scanner.py Mon-Fri 8am
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.tiktok-scan.plist` — tiktok_scanner.py Mon-Fri 8am
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.congress-scan.plist` — congress_scanner.py Mon-Fri 8am
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.insider-scan.plist` — insider_scanner.py Mon-Fri 8am
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.x-tracker-scan.plist` — x_tracker.py Mon-Fri 8am
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.truth-scan.plist` — truth_scanner.py Mon-Fri 8am
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.grok-intel-scan.plist` — grok_scanner.py Mon-Fri 8am
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.grok-ct-sentiment.plist` (NEW March 23) — grok_ct_sentiment.py every 4h 7 days
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.gemini-brain.plist` (NEW March 23) — gemini_brain.py Mon-Fri 9am + 8pm
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.deepseek-analyst.plist` (NEW March 23) — deepseek_analyst.py Mon-Fri 8:30am + 3:30pm
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.regime-classifier.plist` (NEW March 23) — regime_classifier.py --evaluate Mon-Fri 8:45am + Sun 8pm
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.position-audit.plist` (NEW March 23) — position_audit.py Mon-Fri 4:15pm
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.mstr-treasury.plist` (NEW March 23) — mstr_treasury_updater.py Monday 8:30am (local backup to Cloud task)
- `/Users/eddiemae/Library/LaunchAgents/com.rudy.scanner.plist` (NEW March 23) — scanner.py Mon-Fri 9:25am/11am/1pm/3:25pm/4:05pm

### Claude Cloud Scheduled Tasks
- `~/.claude/scheduled-tasks/command-center-morning/SKILL.md` — Morning briefing (9:30 AM ET weekdays)
- `~/.claude/scheduled-tasks/command-center-midday/SKILL.md` — Midday update (12:00 PM ET weekdays)
- `~/.claude/scheduled-tasks/pre-eval-check/SKILL.md` — Pre-flight check (3:30 PM ET weekdays, 15 min before v2.8+ eval)
- `~/.claude/scheduled-tasks/post-eval-report/SKILL.md` — Post-eval report (4:00 PM ET weekdays)
- `~/.claude/scheduled-tasks/command-center-close/SKILL.md` — Close-of-day report (4:00 PM ET weekdays)
- `~/.claude/scheduled-tasks/weekly-report/SKILL.md` — Weekly summary (4:30 PM ET Fridays)
- `~/.claude/scheduled-tasks/btc-weekend-sentinel/SKILL.md` — Weekend BTC monitoring (every 4hrs Sat/Sun)
- `~/.claude/scheduled-tasks/daily-maintenance/SKILL.md` — Daily system health check (8:00 AM daily, including weekends)
- `~/.claude/scheduled-tasks/mstr-treasury-update/SKILL.md` — MSTR treasury auto-update (Monday 8:30 AM)

### Multi-Brain Intelligence
- `/Users/eddiemae/rudy/scripts/grok_ct_sentiment.py` — Grok CT Sentiment Scanner (xAI, every 4hrs) — FIXED March 22: stuck-score detection bug, GREED threshold raised to >50, stale prompt fix. GROUNDED March 23: `query_grok_grounded()` via openai SDK + xAI base_url + `tools=[{"type": "web_search"}]`
- `/Users/eddiemae/rudy/scripts/grok_scanner.py` — Grok X/Twitter broad market scanner (daily 8 AM via LaunchAgent). GROUNDED March 23: `ask_grok_grounded()` wired into scan_realtime(), quick_scan(), scan_influencer()
- `/Users/eddiemae/rudy/scripts/gemini_brain.py` — Gemini Second Brain (Google, daily 9 AM). GROUNDED March 23: `query_gemini_grounded()` via google-genai SDK v1.47.0 + Google Search. Both regime_crosscheck() and news_digest() use grounded queries.
- `/Users/eddiemae/rudy/data/ct_sentiment.json` — Grok sentiment scores + history (48-entry rolling)
- `/Users/eddiemae/rudy/data/grok_intel.json` — Grok broad market intel (list, latest entry is most recent = `data[-1]`)
- `/Users/eddiemae/rudy/data/gemini_analysis.json` — Gemini regime cross-check and news digest
- `~/.claude/scheduled-tasks/grok-ct-sentiment/SKILL.md` — Grok CT sentiment scheduled task
- `~/.claude/scheduled-tasks/gemini-brain/SKILL.md` — Gemini scheduled task
- `~/Library/LaunchAgents/com.rudy.grok-intel-scan.plist` — Grok broad intel LaunchAgent (weekdays 8 AM)

- `/Users/eddiemae/rudy/scripts/deepseek_analyst.py` — DeepSeek Pre-Trade Analyst + Regime Detector. GROUNDED March 23: `ask_deepseek_grounded()` wired into analyze_trade() and detect_regime(). env loading added. optimize_strategies() intentionally ungrounded (historical data only).
- `/Users/eddiemae/rudy/data/trade_analysis.json` — DeepSeek trade verdicts (last 100)
- `/Users/eddiemae/rudy/data/market_regime.json` — DeepSeek regime + history (90 days)
- `/Users/eddiemae/rudy/data/strategy_review.json` — DeepSeek strategy optimization results

### Grounding SDKs Installed
- `google-genai` v1.47.0 — Gemini Google Search grounding (`pip3 install google-genai`)
- `openai` v2.26.0 — xAI + DeepSeek web_search grounding (already installed)
  - xAI: `base_url="https://api.x.ai/v1"` — Note: `xai_sdk` NOT on PyPI, openai SDK used as drop-in
  - DeepSeek: `base_url="https://api.deepseek.com/v1"`

### Quarterly OOS Re-Validation
- `/Users/eddiemae/rudy/scripts/oos_revalidation.py` — Quarterly parameter health check (27-param IS grid + OOS, PASS/WARN/DRIFT ALERT)
- `/Users/eddiemae/rudy/data/oos_revalidation_YYYY_QN.json` — Per-quarter results (e.g., oos_revalidation_Q4_2025.json)
- `/Users/eddiemae/rudy/logs/oos_revalidation.log` — Validation run log

### Authority Lock — Disabled Trader Scripts
All of the following exit immediately (authority guard block at top). DO NOT remove the guard without a constitution amendment:
- `/Users/eddiemae/rudy/scripts/trader1.py` — LOCKED (old execution engine, Systems 1/2)
- `/Users/eddiemae/rudy/scripts/trader2.py` — LOCKED (old diagonal spread engine)
- `/Users/eddiemae/rudy/scripts/trader3.py` — LOCKED (old energy momentum engine)
- `/Users/eddiemae/rudy/scripts/trader4.py` through `trader12.py` — ALL LOCKED
- `/Users/eddiemae/rudy/scripts/trader_moonshot.py` — LOCKED
- `/Users/eddiemae/rudy/scripts/trader_v30.py` — LOCKED

### Research / Backtests
- `/Users/eddiemae/rudy/scripts/kalman_backtest.py` — Kalman filter vs 200W SMA backtest (FAILED, March 2026)
- `/Users/eddiemae/rudy/data/kalman_backtest_results.json` — Kalman backtest results (WFE -4.29, NOT ADOPTED)
- `/Users/eddiemae/rudy/scripts/backtest_candlestick_v28plus.py` — Candlestick filter WF backtest (REJECTED, March 23, 2026)
- `/Users/eddiemae/rudy/data/candlestick_wf_results.json` — Candlestick backtest results (all modes worse than baseline)

### Stress Test Data
- `/Users/eddiemae/rudy/data/flash_crash_stress.json`
- `/Users/eddiemae/rudy/data/monte_carlo_stress.json`
- `/Users/eddiemae/rudy/data/mnav_apocalypse_stress.json`
- `/Users/eddiemae/rudy/data/mnav_apocalypse_v2_killswitch.json`
