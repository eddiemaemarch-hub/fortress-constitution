---
name: Rudy v2.0 Architecture
description: Complete system architecture — v2.8+ live trading, 3 divisions, all active daemons, safety infrastructure, System 13 regime classifier
type: project
---

## Rudy v2.0 — Autonomous Trading System
**Constitution:** v50.0 (file: `constitution_v39.py`)
**Strategy:** v2.8+ Trend Adder — MSTR Cycle-Low LEAP (LIVE on IBKR U15746102)
**Dashboard:** Command Center at localhost:3001, accessible via Cloudflare tunnel on iPhone

### Three Business Divisions (est. v32.0)
1. **Trading Division** — MSTR LEAPs via v2.8+, governed by all risk parameters
2. **Nomad Public Business** — Content/social monetization, independent of trading
3. **CyberCab Fleet Division** — Tesla Robotaxi (research/pre-launch)

### Active Daemons (ALL via LaunchAgents, KeepAlive:true)
- `trader_v28.py` — Main v2.8+ strategy daemon (evaluates daily/weekly at 3:45 PM, 2hr during high-alert months) — LaunchAgent: `com.rudy.trader1.plist` — **Identity: Trader1**
- `trader2_mstr_put.py` — MSTR $50P Jan28 ladder monitor (clientId=12, activates at +150% gain, proceeds → v2.8+) — **Identity: Trader2**
- `trader3_spy_put.py` — SPY $430P Jan27 ladder monitor (clientId=13, activates at +100% gain, proceeds → v2.8+) — **Identity: Trader3**
- `btc_sentinel.py` — 24/7 BTC/USD monitor (15-min checks, Telegram alerts)
- `web/app.py` — Dashboard on port 3001 (clientId=53 for Trader2 panel, clientId=54 for Trader3 panel — fixed March 23 to avoid collision)
- `cloudflared` — Tunnel for iPhone access
- `auditor.py` — Daily post-market audit (4:00 PM Mon-Fri) — verifies T1/T2/T3 state, Constitution v50.0 compliance, clone prohibition, daily loss cap — sends Telegram report — LaunchAgent: `com.rudy.auditor.plist`
- `execution_path_verify.py` — **Trader1 execution path verifier** (19 checks, Mon-Fri 9:20 AM + 3:45 PM) — every step from signal detection to order submission including LEAP expiry countdown — LaunchAgent: `com.rudy.execution-verify.plist`
- `execution_path_verify_t23.py` — **Trader2 + Trader3 execution path verifier** (31 checks, Mon-Fri 9:20 AM + 3:45 PM) — ladder trail math, pending sell, profit-taking sequence, expiry roll, clone prohibition — LaunchAgent: `com.rudy.execution-verify-t23.plist`

**All trading/dashboard/audit/verify daemons** now managed via LaunchAgents. Zero daemons should ever be started manually.

### Execution Path Verification (March 23, 2026) — Runs Until Position Fires
Twice-daily checks that every component from signal detection to order submission is ready. Continue running Mon-Fri at 9:20 AM and 3:45 PM **until Trader1 fires its entry**, then continue to monitor the active position.

**Trader1 — 19 checks (`execution_path_verify.py`):**
1. Daemon alive | 2. LaunchAgent registered | 3. IBKR port 7496 | 4. Eval freshness (<26h) | 5. State valid+writable | 6. Filter status (dipped/green weeks/armed) | 7. Telegram HITL reachable | 8. Clone prohibition (Article XI) | 9. PID lock | 10. Entry/exit code importable | 11. IBKR position matches state | 12. Trail stop/HWM floor integrity (entry×0.65) | 13. Pending sell/approval check | 14. Profit-taking roadmap (10x/20x/50x/100x + trend adder + euphoria) | 15. Execute sell path (all exit methods callable) | 16. LEAP expiry countdown | 17. Entry sizing (NLV×25%×50%) | 18. Strike recommendation freshness | **19. LEAP Expiry Roll Protocol** — live IBKR scan for MSTR CALL positions + days to expiry + protocol callable + pending roll status

**Trader2 + Trader3 — 31 checks (`execution_path_verify_t23.py`):**
- Shared (3): IBKR connection, Telegram HITL, Clone prohibition
- Per-trader (13 each): Daemon, LaunchAgent, State freshness, State valid, IBKR position, Ladder status, Trail stop math (peak×(1-trail%)), Pending sell (FAIL if >30min unanswered), Profit-taking sequence (missed tier detection), Execute sell path (all methods callable), Expiry roll protocol, PID lock, Exit code importable

### Authorized Trader Registry (Article XI — Constitution v50.0)
| Identity | Script | Authority |
|---|---|---|
| **Trader1** | `trader_v28.py` | BUY + SELL (v2.8+ LEAP only) |
| **Trader2** | `trader2_mstr_put.py` | SELL ONLY (MSTR Put exit, HITL required) |
| **Trader3** | `trader3_spy_put.py` | SELL ONLY (SPY Put exit, HITL required) |

**All other trader scripts are LOCKED (authority guard block at top):** trader1.py, trader2.py, trader3.py, trader4–12.py, trader_moonshot.py, trader_v30.py. These exit immediately on run.

**Clone Prohibition (Article XI, March 23, 2026):** System is PERMANENTLY FORBIDDEN from creating new trader scripts with buy/sell authority, duplicating authorized scripts, or registering new trader LaunchAgents without explicit Commander approval and a constitution amendment.

**Close Permission Authority Lock:** Once Commander grants Trader2 or Trader3 permission to close, NO other trader may execute any buy or sell until close is confirmed complete.

**Socket disconnect (March 20, 2026):** Trader1 lost IBKR socket connection and did not auto-restart because it was the last daemon running without a LaunchAgent (started via manual nohup). Fixed March 22 by creating `com.rudy.trader1.plist` with KeepAlive:true. Auto-reconnect with one retry also wired into trader1 code.

### Weekend Behavior (Normal)
- MSTR price shows $0 and positions show empty on weekends — this is expected (IBKR has no live market data Sat/Sun)
- Dashboard still shows NLV/cash from Friday close
- Do not treat weekend $0 prices or empty positions as errors

### System 13: Neural Regime Classifier (March 2026)
- **Model:** CalibratedEnsemble (RandomForest 300 + GradientBoosting 200)
- **CV Accuracy:** 95.6%
- **4 Regimes:** ACCUMULATION, MARKUP, DISTRIBUTION, MARKDOWN
- **Current (March 2026):** DISTRIBUTION at 82.2% confidence, MARKDOWN pressure rising at 17.8%
- **Role:** Awareness layer for trader1; regime-adaptive trailing stops for trader2/trader3. Does NOT modify v2.8+ entry/exit logic.
- **Wired into ALL 3 traders:**
  - **Trader1 (v2.8+):** PRIMARY phase detection (replaces crude $80K threshold), regime logged at every eval (`FILTERS: ... | Regime=DISTRIBUTION(82%)`), regime context included in Telegram alerts, Monday 9:30 AM early eval on >5% BTC weekend move, last_regime + last_regime_confidence saved to state, falls back to threshold if stale >7d
  - **Trader2 (MSTR Put):** Regime-adaptive trail width — MARKDOWN +5%, DISTRIBUTION +2%, MARKUP -3% (ACCUMULATION 0%). Logic: puts profit from drops, so MARKDOWN = widen trail (let winners run), MARKUP = tighten (protect gains). Trail floor at 5% regardless of adjustment.
  - **Trader3 (SPY Put):** Same regime-adaptive trail width as Trader2 (MARKDOWN +5%, DISTRIBUTION +2%, MARKUP -3%, floor 5%).
- **RL Layer:** Experience replay buffer records every prediction; outcomes evaluated 4 weeks later against actual BTC returns; per-regime confidence adjustment (0.0-1.0x); auto-retrain after 50 experiences; rolling accuracy with 0.95 decay; Telegram alert if accuracy <60%
- **Files:** `regime_classifier.py`, `regime_state.json`, `regime_model.pkl`, `btc_seasonality.json`, `rl_experience.json`

### MSTR Treasury Data (as of March 22, 2026)
- **Holdings:** 761,068 BTC (~3.5% of total supply) at avg cost $66,384.56/coin
- **Shares:** 293.1M diluted
- **mNAV Premium:** ~1.007x = trading near NAV = historically cheap
- **Wall Street:** 14 analysts "Strong Buy", $349 avg target (+157% upside)
- **Reflexivity loop:** BTC up -> MSTR up -> cheaper capital raises -> more BTC -> loop accelerates
- **Update cadence:** Strategy buys BTC every Monday — holdings numbers change weekly
- **AUTO-UPDATED weekly** (Monday 8:30 AM) via `mstr_treasury_updater.py` scheduled task (`mstr-treasury-update`, 9th scheduled task)
  - Sources: bitbo.io (BTC holdings + avg cost from SEC filings), stockanalysis.com (diluted shares)
  - Writes to `mstr_treasury.json`, which `trader_v28.py` reads for live mNAV calculation
  - No more hardcoded holdings — trader reads from treasury JSON first, falls back to internal dict for historical backtest only
- **PineScript still manual:** Pine can't read JSON, so `rudy_v28plus.pine` and `pinescript_mstr_cycle_low_entry_v28plus.pine` still need manual update on new 8-K filings

### Core Rule: IBKR is the Single Source of Truth for All Prices
- Codified in constitution: `IBKR_IS_PRICE_TRUTH = True`
- ALL price data (BTC, MSTR, SPY, options) must come from IBKR — no exceptions
- Never hardcode prices (ATH, 200W SMA, bull/bear thresholds)
- GBTC proxy may be used for internal calculations only — never as a display price
- If IBKR is unavailable, show "—" or "Connecting..." — never stale or proxy prices
- Applies to: dashboard, trader1, trader2, trader3, regime classifier, sentinel, all Telegram alerts
- **MCP Query Rule (March 23, 2026):** When asked any account or position question, ALWAYS call `mcp__rudy-trading__get_account_summary` FIRST — NEVER read state files for live account data. State files are daemon snapshots (can be hours stale). MCP tool hits live TWS. Lesson: state files showed -21% for MSTR put; live IBKR showed -25%. The MCP is always right.

### Stealth Execution Intelligence (March 21, 2026)
- All 3 traders (trader1, trader2, trader3) now use stealth execution via `build_stealth_order()`
- Converts MarketOrders to adaptive LimitOrders at the execution layer — does NOT change entry/exit logic
- Uses live IBKR bid/ask mid price + random offset + penny jitter
- Never places orders at round number prices (.00 or .50) to avoid institutional detection
- All trailing stops are INTERNAL (code-evaluated), not exchange stop orders — invisible to institutional VWAP/TWAP algos
- Falls back to MarketOrder only if bid/ask spread unavailable
- Rationale: institutional algos exploit predictable retail stop placement and round-number clustering
- Constitution constants: `STEALTH_EXECUTION_ENABLED`, offset ranges defined in constitution

### Safety Infrastructure (6 Circuit Breakers + Expiry Protocol)
1. Daily Loss Limit: 2% NLV daily cap
2. Consecutive Loss Shutdown: 5 stop-outs → halt
3. mNAV Kill Switch: premium < 0.75x → close ALL, DEFCON 1
4. Premium Compression Alert: >15% mNAV drop → Telegram + HITL strike roll
5. Self-Evaluation: 4-hour loop
6. PID Lockfiles: All daemons protected against cloning

**⚠️ mNAV WATCH (March 23, 2026):** Last 4 consecutive readings: 0.7519x / 0.7517x / 0.7508x / 0.7519x — holding just above the 0.75x kill switch. One compression event away from DEFCON 1. Monitor every eval cycle. MSTR trading near NAV historically means accumulation zone, but the kill switch doesn't care about historical context — it fires automatically at <0.75x.

### LEAP Expiry Extension Protocol (March 2026) — FULLY OPERATIONAL — ALL 3 TRADERS
Prevents losing positions to time decay when the market is flat.
- **Trigger:** Within 180d or 90d of expiry AND position is flat (not yet activated / printing)
- **180d warning:** Early alert — proposes rolling forward, HITL required
- **90d urgent:** Hard alert — must roll or accept expiry loss
- **Action:** Sell current contract, buy same strike at next LEAP expiry (+2yr). HITL YES/NO via Telegram. **Fully automated after approval** — Commander taps YES on phone, bot executes sell-old/buy-new on IBKR directly.
- **Proposed targets:** MSTR $50P Jan28 → Jan30 ("20300117") | SPY $430P Jan27 → Jan29 ("20290119") | T1 MSTR CALL — dynamic from IBKR scan
- **State fields (all 3):** `pending_expiry_roll`, `expiry_roll_alerted_180d`, `expiry_roll_alerted_90d`, `expiry_roll_commander_approved`, `expiry_roll_commander_rejected`, `roll_history`
- **Methods in ALL 3 traders:** `_check_expiry_extension()`, `approve_expiry_roll()`, `reject_expiry_roll()`
- **Trader1 difference (March 23, 2026):** T1 trades MSTR stock; Commander holds MSTR CALL LEAPs manually based on T1 strike recommendations. `_check_expiry_extension()` scans IBKR for live MSTR CALL positions — if found and approaching expiry, sends HITL alert. `approve_expiry_roll()` auto-executes on IBKR (same as T2/T3). Uses `Option("MSTR", expiry, strike, "C", "SMART")` contract + `build_stealth_order()` + `execute_with_confirmation()`. Partial-fill guard: if sell fills but buy fails, screams for manual intervention.
- **Trader2 / Trader3:** Fixed `EXPIRY` + `STRIKE` constants, only fires when flat (gain < 50% of activation threshold). T2 bridges into `execute_roll()` infrastructure.
- **MCP Tool:** `approve_expiry_roll(trader, action)` — trader='trader1'/'trader2'/'trader3', action='approve'/'reject'. Writes flag to state JSON. Daemon picks up on next eval cycle.
- **Approval flow (complete loop):** Telegram HITL alert → Commander taps YES → MCP `approve_expiry_roll` writes `expiry_roll_commander_approved=True` → next eval cycle (9:20 AM or 3:45 PM): sell old contract → buy new contract → confirmation Telegram → alert flags reset for new expiry
- **Verified twice daily:** check_19 in `execution_path_verify.py` scans IBKR for live MSTR CALL position, shows exact days to expiry, FAILs if urgent roll unanswered

### Capital Deployment Plan (March 2026)
- Phase 1: ~$7,900 (current balance) → enter on early v2.8+ signal
- Phase 2: Put proceeds (MSTR $50P $1,253 cost + SPY $430P $495 cost) → roll into v2.8+ when trailing ladder closes them. NOT for new hedges.
- Phase 3: $130K (arriving Aug-Oct 2026) → full scale-in
- Total: ~$139,650 all feeding ONE v2.8+ MSTR LEAP position
- Constitution updated with V28_CAPITAL_PHASE variables

### v2.8+ Live Signal State (March 26, 2026)
- **Armed:** No
- **Dipped below 200W SMA:** YES ✅ — condition met, clock started
- **Green weeks:** 0/2 — needs 2 consecutive Friday closes above MSTR 200W SMA
- **BTC price:** $71,001
- **Regime:** DISTRIBUTION 79.2% confidence
- **Status:** Waiting for MSTR to close above its 200W SMA on two consecutive Fridays → ENTRY fires
- **Note:** 200W SMA in memory (~$59,433) was STALE. Actual BTC 200W SMA is ~$72K (confirmed from chart). MSTR 200W SMA is the reclaim trigger for green week count.

### BTC Cycle Intelligence
- Phase: Distribution → Early Winter (BTC ~$71K, -44% from $126K ATH)
- System 13 regime: DISTRIBUTION at 79.2%, updated March 26, 2026
- Phase detection: System 13 regime maps to bull/bear (ACCUMULATION/MARKUP → bull, DISTRIBUTION/MARKDOWN → bear), falls back to threshold if stale
- ATH tracked dynamically in trader state (`btc_ath`), not hardcoded
- Phase-aware monthly seasonality table (Month x Phase) wired into trader1
- High-alert months: Bear = Jun/Aug/Sep/Oct/Nov, Bull = Sep/Oct/Nov
- Weekend sentinel: 24/7 BTC monitoring, Monday 9:30 AM early eval (approved, building)
- BTC 250W MA (~$56K) and 300W MA (~$50K) watch levels added to trader1 and dashboard (March 21, 2026)
- Proximity zone alerts included in Telegram context (BELOW 300W / BELOW 250W / BELOW 200W / APPROACHING / NEARING / ABOVE ALL)
- Dashboard BTC Cycle Intelligence card shows distance to all 3 MAs (200W, 250W, 300W)
- 250W and 300W are awareness levels ONLY — not entry/exit filters

### Dashboard Real-Time Fix (March 23, 2026)
**Root causes fixed:**
1. **`_get_live_position_value()` was opening live IBKR connections in Trader2/3 every 15s** — 8-second timeout blocked Flask thread, causing ALL panels (account, feed, regime, intelligence) to freeze/queue
   - Fix: Added `_get_cached_position_value()` that reads from `_ibkr_cache["positions"]` (background feed, 10s fresh)
   - `api_trader2_status()` and `api_trader3_status()` now use cache-first with live IBKR as fallback (cache miss only)
   - Response time: was 2-8 seconds → now 11-34ms
2. **Grok CT Sentiment and Gemini Brain were bundled inside `fetchRegime()` JS function** — not truly independent polling
   - Fix: Extracted into standalone `fetchGrokSentiment()` and `fetchGeminiBrain()` functions
   - Each has own `setInterval(30000)` and initial call
   - `fetchRegime()` now only handles `/api/regime`

**Intelligence Scanner LaunchAgents (all created March 23, 2026):**
- `com.rudy.gronk-scan` → `gronk.py` (Mon-Fri 8am)
- `com.rudy.youtube-scan` → `youtube_scanner.py` (Mon-Fri 8am)
- `com.rudy.tiktok-scan` → `tiktok_scanner.py` (Mon-Fri 8am)
- `com.rudy.congress-scan` → `congress_scanner.py` (Mon-Fri 8am)
- `com.rudy.insider-scan` → `insider_scanner.py` (Mon-Fri 8am)
- `com.rudy.x-tracker-scan` → `x_tracker.py` (Mon-Fri 8am)
- `com.rudy.truth-scan` → `truth_scanner.py` (Mon-Fri 8am)
- `com.rudy.grok-intel-scan` → `grok_scanner.py` (Mon-Fri 8am)
- **`com.rudy.grok-ct-sentiment`** → `grok_ct_sentiment.py` (every 4 hours, 7 days — BTC never sleeps)
- **`com.rudy.gemini-brain`** → `gemini_brain.py` (Mon-Fri 9am + 8pm)
- **`com.rudy.deepseek-analyst`** → `deepseek_analyst.py` (Mon-Fri 8:30am + 3:30pm)
- **`com.rudy.regime-classifier`** → `regime_classifier.py --evaluate` (Mon-Fri 8:45am + Sunday 8pm)
- **`com.rudy.position-audit`** → `position_audit.py` (Mon-Fri 4:15pm — IBKR vs state reconciliation)
- **`com.rudy.mstr-treasury`** → `mstr_treasury_updater.py` (Monday 8:30am — local backup to Cloud task)
- **`com.rudy.scanner`** → `scanner.py` (Mon-Fri 9:25am/11am/1pm/3:25pm/4:05pm)

### Equity Curve Charts — matplotlib + seaborn (March 25, 2026)
- **Libraries:** `matplotlib` + `seaborn` installed via pip into Rudy Python environment
- **Data source:** `/Users/eddiemae/rudy/data/pnl_history.json` — appended daily by auditor at 4 PM (date, T2 value, T2 pct, T3 value, T3 pct, NLV)
- **Feature 1 — Auditor Telegram chart:** After daily audit at 4 PM, auditor logs snapshot to pnl_history.json then generates 2-panel equity curve (top: T2/T3 position values with cost basis lines; bottom: NLV fill). Sent via Telegram `sendPhoto`. Dark theme (#1a1a2e background). Only sends if ≥2 data points exist.
- **Feature 2 — Dashboard endpoint:** `/api/equity_chart` — returns PNG image directly (Content-Type: image/png, no-cache). Reads pnl_history.json. Embedded in Command Center dashboard as `<img src="/api/equity_chart">`. Returns 404 JSON if insufficient data.
- **Shared helper:** `generate_equity_chart_bytes(history)` — single function used by both auditor and app.py. Non-interactive backend (`matplotlib.use('Agg')`).

### Dashboard Updates (March 2026)
- Capital Deployment Plan card added
- Positions panel fixed to show ALL IBKR positions (removed old filter that hid some)
- Meta display glasses integration via Telegram notification mirroring (discussed)
- **Trader1 panel added (March 23, 2026):** Shows v2.8+ live state — armed status, dipped below 200W, green week count, MSTR price, position qty, entry price, peak gain, last eval. API: `/api/trader1/status`
- **Trader2/3 clientId collision fixed (March 23, 2026):** Both panels were sharing clientId=53 → race condition at page load caused Trader3 to show "—". Fixed: Trader2=clientId=53, Trader3=clientId=54.
- **Description sections updated (March 22, 2026):** v2.8+ card, Safety Infrastructure, Trader2/3, Auditor cards all updated with LEAP Expiry Extension, quarterly OOS re-validation, HITL expiry roll, Grok stale flag
- **Candlestick backtest completed (March 23, 2026):** Tested 4 modes (none/strict/window_3/high_prob) × 7 WF windows. Result: candlestick filters REDUCE performance in all modes. Baseline (no filter) wins at avg +13.9% OOS. DO NOT ADD candlestick filters to v2.8+.

### Claude Cloud Integration (March 2026)
9 scheduled tasks running on Anthropic's cloud infrastructure (NOT on the Mac — runs even if Mac is asleep):

**Weekday Command Center:**
- **command-center-morning** (9:30 AM ET, Mon-Fri): Full morning briefing — account summary, positions, System 13 regime, BTC cycle levels (200W/250W/300W), signal status, filter states, phase-aware seasonality context
- **command-center-midday** (12:00 PM ET, Mon-Fri): Midday update — account summary, positions, regime check, BTC proximity alerts, selling pressure detection
- **command-center-close** (4:00 PM ET, Mon-Fri): Full daily report — account summary, P&L, positions, regime, cycle intelligence, filter status, circuit breaker health, weekend prep on Fridays

**v2.8+ Eval Support:**
- **pre-eval-check** (3:30 PM ET, Mon-Fri): Pre-flight — verify IBKR connected, all 3 daemons alive, circuit breakers clear, 15 min before v2.8+ eval
- **post-eval-report** (4:00 PM ET, Mon-Fri): What v2.8+ decided — all filter results, plain English assessment, error reporting

**Weekly Summary:**
- **weekly-report** (4:30 PM ET, Fridays only): Full week summary — regime changes, signal proximity, capital plan status, RL confidence

**Weekend Monitoring:**
- **btc-weekend-sentinel** (every 4 hours Sat/Sun — 8am/12pm/4pm/8pm ET): Weekend BTC monitoring — alert on >3% moves, proximity to 200W SMA ($59,433), 250W MA ($56K), 300W MA ($50K), Monday early eval prep

**Daily Maintenance + Self-Repair:**
- **daily-maintenance** (8:00 AM daily, every day including weekends): Full system health check — verifies all 3 daemons alive, IBKR connected, circuit breakers clear, both put positions exist, BTC/MSTR prices not stale, sends ONE Telegram report with pass/fail status. Weekend-aware (doesn't flag $0 prices on Sat/Sun). Now includes self-repair: detected issues trigger a Telegram repair proposal with YES/NO inline buttons for Commander approval before execution.

**MSTR Treasury Auto-Update:**
- **mstr-treasury-update** (Monday 8:30 AM): Scrapes bitbo.io for BTC holdings + avg cost (SEC filing data), stockanalysis.com for diluted shares. Writes `mstr_treasury.json`. Trader1 reads this for live mNAV — no more hardcoded holdings.

**All tasks:**
- Send reports/alerts via Telegram (MCP `send_telegram` tool)
- Include System 13 regime, seasonality context, BTC cycle levels
- Run on Anthropic cloud — no dependency on Mac uptime

**MCP Server venv:** `~/rudy/scripts/.mcp_venv/` — Python 3.12. Deps installed here (not system Python). Fixed March 22, 2026: `ib_insync` was missing from venv (installed v0.9.86). Also fixed asyncio conflict: `get_account_summary` now runs ib_insync in a `ThreadPoolExecutor` + `asyncio.new_event_loop()` because FastMCP owns the main event loop.

**MCP Tools (available from any Claude session — iPhone, web, terminal):**
- `get_account_summary` — IBKR account: NLV, cash, positions, P&L (runs in thread to avoid asyncio conflict with FastMCP)
- `get_system_status` — v2.8+ armed state, last eval, prices, premium
- `get_filter_status` — All v2.8+ entry filter states
- `get_market_intel` — System 13 regime, sentiment
- `send_telegram` — Send message via Rudy's Telegram bot
- `force_evaluation` — Trigger immediate v2.8+ filter evaluation
- `approve_trade` — HITL trade approval
- `approve_strike_roll` — HITL strike roll approval (different strike, same expiry)
- `approve_expiry_roll(trader, action)` — HITL expiry extension approval (same strike, later expiry). trader='trader1'/'trader2'/'trader3', action='approve'/'reject'. Daemon auto-executes sell-old/buy-new on IBKR after approval.

**Scheduled task files:** `~/.claude/scheduled-tasks/{task-id}/SKILL.md`

### Self-Repair System (March 2026)
- Daily maintenance agent (8:00 AM) now has self-repair capability
- **Flow:** Detects issue → proposes fix via Telegram with YES/NO inline buttons → on YES: executes repair immediately → on NO: skips repair, logs rejection
- **Repair API endpoints:** `/api/repair/propose`, `/api/repair/status`, `/api/repair/execute`
- **Telegram callback handler** processes `repair_approve_*` and `repair_reject_*` callbacks
- **Supported repair actions:** `restart_trader1`, `restart_trader2`, `restart_trader3`, `restart_dashboard`, `force_eval`
- **Execution:** Daemon restarts via `launchctl`, force eval via existing mechanism
- **Repair state:** stored in `~/rudy/data/pending_repairs.json`
- **Safety rules:**
  - Safe repairs (force_eval, daemon restart) can auto-execute on Commander YES
  - Dangerous repairs (circuit breaker reset, position changes) require full HITL approval flow
  - Circuit breakers NEVER auto-reset — Commander must approve manually regardless of self-repair

### Multi-Brain Intelligence (March 2026)
Three AI brains provide independent analysis alongside System 13. All three are now live-search grounded (March 23, 2026).

**PRICE RULE (all brains):** BTC/MSTR prices ALWAYS from IBKR state files (`trader_v28_state.json`). Web search / Google Search grounding is for news/macro/regulatory context ONLY — never for prices.

**Grok CT (xAI) — CT Sentiment Scanner:**
- Native X/Twitter access + live web_search grounding (March 23, 2026)
- Scores -100 to +100, fear/greed classification (GREED threshold >50, calibrated March 22)
- Tracks whale activity, MSTR-specific sentiment
- Runs every 4 hours via scheduled task (`grok-ct-sentiment`)
- Sends Telegram alerts on extreme fear/greed and stale-score detection
- **Grounding:** `query_grok_grounded()` via `openai` SDK v2.26.0 + `base_url="https://api.x.ai/v1"` + `tools=[{"type": "web_search"}]`
  - Note: `xai_sdk` not on PyPI — `openai` SDK used as OpenAI-compatible drop-in (same capability)
  - Falls back to raw REST `query_grok()` if SDK unavailable or content is None
- Script: `grok_ct_sentiment.py` | Data: `ct_sentiment.json`
- Dashboard: Grok CT Sentiment card (blue)

**Grok Scanner (xAI) — X/Twitter Broad Market Intel:**
- Full X scan: signals, influencers, hot tickers, viral posts, 10x picks
- Runs weekdays 8 AM via LaunchAgent (`com.rudy.grok-intel-scan.plist`)
- **Grounding:** `ask_grok_grounded()` via `openai` SDK + `tools=[{"type": "web_search"}]`
  - Wired into: `scan_realtime()`, `quick_scan()`, `scan_influencer()`
  - Falls back to raw REST `ask_grok()` if unavailable
- Script: `grok_scanner.py` | Data: `grok_intel.json` (list, latest = `data[-1]`)
- Dashboard: Grok Intel card (blue)

**Gemini (Google) — Regime Cross-Check & News Digest:**
- Independent regime classification cross-checked against System 13
- Morning news digest with macro/crypto summary
- Consensus/disagreement alerts (when Gemini regime != System 13 regime)
- Runs daily at 9 AM via scheduled task (`gemini-brain`)
- Sends Telegram alerts on regime disagreements
- **Grounding:** `query_gemini_grounded()` via `google-genai` SDK v1.47.0, `gemini-2.0-flash`
  - Uses `types.Tool(google_search=types.GoogleSearch())` — live Google Search
  - Logs up to 3 grounding source URLs per query
  - Both `regime_crosscheck()` and `news_digest()` call `query_gemini_grounded()`
  - Falls back to `gemini-2.5-flash` raw REST if SDK unavailable
- Script: `gemini_brain.py` | Data: `gemini_analysis.json`
- Dashboard: Gemini Second Brain card (blue)

**DeepSeek — Pre-Trade Analyst & Regime Detector:**
- Pre-trade verdict (APPROVE/REJECT/CAUTION) on proposed trades
- Market regime classification (BULL_STRONG → CRASH scale) with position size multiplier
- Strategy optimization on closed trade history
- Called by `scanner.py` for regime checks; also used directly for trade analysis
- **Grounding:** `ask_deepseek_grounded()` via `openai` SDK + `base_url="https://api.deepseek.com/v1"` + `tools=[{"type": "web_search"}]`
  - Wired into: `analyze_trade()` and `detect_regime()`. `optimize_strategies()` intentionally ungrounded (analyzes historical data only)
  - Falls back to raw REST `ask_deepseek()` → Gemini REST fallback if all else fails
  - Env now loaded from `~/.agent_zero_env` (added March 23, 2026 for consistency)
- Script: `deepseek_analyst.py` | Data: `trade_analysis.json`, `market_regime.json`, `strategy_review.json`

**All four brains:** Awareness layers ONLY — do NOT modify v2.8+ entry/exit logic. All send Telegram alerts on extreme conditions or cross-brain disagreements.

### Quarterly OOS Re-Validation System (March 22, 2026)
Closes the "locked parameters" gap — validates that v2.8+ trend adder parameters remain optimal as new data arrives.
- **Script:** `~/rudy/scripts/oos_revalidation.py`
- **Schedule:** First Monday of Jan/Apr/Jul/Oct at 6 AM (`quarterly-oos-revalidation` scheduled task — register in fresh session)
- **What it does:** Auto-detects last completed quarter, runs full 27-param IS grid on all prior data (2016→quarter start), runs OOS on that quarter, compares `standard_medium_safety` vs all 27 combos
- **Drift thresholds:** PASS = live params rank #1 or within 90% of winner | WARN = 75–90% | DRIFT ALERT = <75% of winner or different param wins decisively
- **Output:** `~/rudy/data/oos_revalidation_YYYY_QN.json` + Telegram verdict (PASS/WARN/DRIFT ALERT)
- **Safety:** NEVER auto-updates live parameters. Reports only. Commander approves changes manually via full walk-forward.
- **Usage:** `python3 oos_revalidation.py` (auto-quarter) | `--quarter Q3 --year 2025` | `--report` | `--dry-run`

### Grok CT Sentiment Fixes (March 22, 2026)
- **Bug fixed:** Stuck-score detection had logic error — checked only saved history, not counting current run → score of 35 stuck across 4 consecutive runs undetected
- **Fix:** Now compares last 2 history + current = 3-run window (correctly triggers `possibly_stale = True`)
- **GREED threshold raised:** Was >30 = GREED (too loose). Now >50 = GREED. Score of 35 = NEUTRAL.
- **Stale prompt fix:** Prompt now anchors to "last 2 hours only, current time HH:MM UTC" to force fresh X data
- **Stale Telegram alert added:** When `possibly_stale=True`, sends `⚠️ Grok Stale Response Detected` alert
- **grok-intel-scan LaunchAgent:** Registered as persistent launchd agent, runs `grok_scanner.py` every weekday at 8 AM

### Live Search Grounding — All Three Brains (March 23, 2026)
All three external AI brains now use live web search grounding for real-time context.
- **Gemini:** `google-genai` SDK v1.47.0 (`pip3 install google-genai`) — `query_gemini_grounded()` added. Both `regime_crosscheck()` and `news_digest()` upgraded to grounded queries. Uses `gemini-2.0-flash` + `types.Tool(google_search=types.GoogleSearch())`. Logs grounding source URLs.
- **Grok CT:** `query_grok_grounded()` added to `grok_ct_sentiment.py`. `scan_sentiment()` now grounded. Uses `openai` SDK pointing at xAI endpoint + `tools=[{"type": "web_search"}]`.
- **Grok Scanner:** `ask_grok_grounded()` added to `grok_scanner.py`. `scan_realtime()`, `quick_scan()`, `scan_influencer()` now grounded. Same openai SDK mechanism.
- **DeepSeek:** `ask_deepseek_grounded()` added to `deepseek_analyst.py`. `analyze_trade()` and `detect_regime()` now grounded. `optimize_strategies()` intentionally NOT grounded (historical data only). Uses `openai` SDK + `base_url="https://api.deepseek.com/v1"` + `tools=[{"type": "web_search"}]`. Fallback chain: grounded SDK → raw REST → Gemini REST.
- **Fallback chain (all brains):** grounded SDK call → raw REST if SDK fails or content is None.
- **PRICE RULE preserved:** BTC/MSTR prices always from IBKR state files — grounding is for news/macro/regulatory context only.

### Research Only (NOT deployed)
- AVGO: +501.5%, Sharpe 0.888 — cross-ticker validation only
- BMNR: Discussed but NOT implemented — research only
- WhatsApp integration for Meta glasses — discussed, not yet implemented
- **Heikin Ashi RSI Oscillator — REJECTED (March 25, 2026):** Tested as additive entry filter on v2.8+ via `backtest_ha_rsi_v28plus.py`. Too restrictive — filtered out ALL 4 baseline trades, generating zero entries across 20 walk-forward windows and 8 stress scenarios. Baseline v2.8+: 4 trades, 50% WR, +58% return, 0.28 Sharpe, 3.25 PF. HA RSI: 0 trades. Do NOT add to v2.8+ signal logic.

### Future Roadmap — DEAP (Genetic Programming / Evolutionary Algorithms)
- **Library:** DEAP (Distributed Evolutionary Algorithms in Python) — `pip install deap`
- **Docs:** https://deap.readthedocs.io/en/master/tutorials/advanced/gp.html
- **Intended use:** Strategy discovery engine — evolve new trading rules from scratch via genetic programming. NOT for modifying v2.8+ (constitutionally locked). Candidate uses:
  - Evolve new entry/exit filter combinations for future trader candidates
  - Optimize System 13 feature selection via evolutionary search
  - Symbolic regression on MSTR/BTC price relationships
  - Generate Pine Script strategy candidates for TradingView backtesting
- **Constitutional requirement:** Any DEAP-evolved strategy that trades real capital requires a new authorized trader (Article XI constitution amendment + Commander approval). DEAP output = research only until constitution updated.
- **Status:** Planned — not yet installed or implemented (March 25, 2026)
