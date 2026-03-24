# Rudy v2.0 — Build Status for Next Claude Code Session
**Date: March 14, 2026 | Target: October 2026 Live Entry**

---

## WHERE WE ARE

The system is **~80% production-ready**. Phase 1 core hardening is COMPLETE (except IBKR permissions — waiting Monday).

### WHAT'S DONE (working today)

| Component | Status | Notes |
|-----------|--------|-------|
| **PineScript Strategies** | DONE | 12 strategies on TradingView, all with position-HWM trailing stops, laddered tiers, 0.5% commission + 5-tick slippage |
| **Webhook Pipeline** | DONE | TradingView → Flask webhook → trader dispatch. TEST MODE by default (safe). Set `WEBHOOK_LIVE=true` to go live |
| **Position Tracking** | DONE | JSON-based per-system position files + IBKR native `ib.positions()` sync |
| **Trailing Stop Monitor** | DONE | `stop_monitor.py` runs every 5 min via cron. **Now uses per-system laddered tiers** (not flat 30%) |
| **Telegram Alerts** | DONE | All trade entries, exits, breaker alerts, daily summaries flowing to chat 6353235721 |
| **Paper Trading** | DONE | Port 7497, 25 open positions, all paper tests passed, running autonomously |
| **Web Dashboard** | DONE | Full dashboard with buttons for all 12 traders, scanners, PineScript copy/paste, projections |
| **Intel Scanners** | DONE | YouTube (with channel search + yt-dlp fallback), Grok/X, TikTok, Truth Social, Congress, Insider, Playlist |
| **Constitution** | DONE | v45.0 — all rules, breaker thresholds, laddered tiers, spread management defined |
| **BTC Regime Filter** | DONE | SMA200 + EMA50 golden cross detection, death cross exit trigger |
| **Moonshot LEAP Trader** | DONE | `trader_moonshot.py` — deep OTM strike selection, entry execution, gain monitoring |

### PHASE 1 HARDENING — COMPLETED March 14, 2026

| Fix | Status | Details |
|-----|--------|---------|
| **Laddered Tier Integration** | DONE | `stop_monitor.py` now uses `stop_utils.get_laddered_trail_pct(system_name, gain_pct)` instead of flat 30%. Each position tagged with system_name. TICKER_TO_SYSTEM mapping for 40+ tickers. Entry price tracked for gain calculation |
| **Circuit Breaker Gate** | DONE | `auditor.is_breaker_active(system_id)` reads `breaker_state.json`. Blocks ALL new entries when breaker active. Global halt + per-system breakers. Wired into webhook dispatch. API endpoints: `/api/breaker/halt`, `/api/breaker/resume`, `/api/breaker/status` |
| **IBKR Reconnection** | DONE | `ibkr_utils.connect_with_retry()` — exponential backoff (1s→2s→4s→8s→16s→30s→60s). `ensure_connected()` health check before orders. Telegram alert on connection failure |
| **Order Error Recovery** | DONE | `ibkr_utils.place_order_with_retry()` — 3x retry with 2s delay. Failed orders logged to `data/failed_orders.json`. Telegram escalation on exhausted retries |
| **Entry Validation** | DONE | `ibkr_utils.validate_entry()` — pre-trade checks: circuit breaker status, max order size ($50k), duplicate position prevention, concentration limits (40% of system capital) |

### WHAT'S BLOCKED

| Issue | Impact | Resolution |
|-------|--------|------------|
| **IBKR Paper SELL Orders** | Error 201 rejects ALL option sell orders on paper account DUA724990. Can't close positions, can't place trailing stops via IBKR. Software monitor is the only backstop | Switched cash → margin + Level 4 on March 13. Check Monday March 16 |

### WHAT'S NOT STARTED (and shouldn't be until core is solid)

- Live account (port 7496) deployment
- Multi-account support
- Advanced order types (bracket orders, OCA groups)
- Real-time P&L dashboard streaming
- Automated roll management for expiring LEAPs

---

## CRITICAL PATH TO OCTOBER 2026

### Phase 1: Core Hardening (March 2026) — COMPLETE
All 5 hardening items built. IBKR permissions waiting Monday.

### Phase 2: End-to-End Testing (June - July 2026)
**Goal: Full lifecycle validation on paper**

1. **Entry → Hold → Ladder → Exit cycle test**
   - Manually trigger entry on paper account
   - Wait for gain to hit each tier threshold
   - Confirm trail % changes at each tier
   - Confirm partial sells fire at correct levels
   - Confirm full exit on trail stop trigger

2. **Failure mode testing**
   - Kill TWS during order → confirm recovery
   - Corrupt position file → confirm graceful handling
   - Send malformed webhook → confirm rejection
   - Hit survival breaker → confirm all entries blocked
   - Network outage during market hours → confirm alert + recovery

3. **Multi-system stress test**
   - Run all 12 traders simultaneously on paper
   - 50+ positions across all systems
   - Confirm no client_id conflicts
   - Confirm stop_monitor handles all systems correctly

### Phase 3: Paper Validation (August - September 2026)
**Goal: 6-8 weeks of hands-off autonomous paper trading**

1. **Deploy full system with `WEBHOOK_LIVE=true` on paper**
2. **Monitor daily: entry accuracy, stop execution, ladder escalation**
3. **Track metrics: fill quality, slippage, false signals, missed entries**
4. **Fix any issues found — NO new features**
5. **Commander approval gate: must sign off before live deployment**

### Phase 4: Live Deployment (October 2026)
**Goal: MSTR LEAP entry window opens**

1. Switch port 7497 → 7496 (live)
2. First trade: MSTR deep OTM LEAP calls (moonshot entry)
3. Verify fill, position tracking, stop placement
4. Monitor first 48 hours with zero automation changes
5. If stable: enable full autonomous mode

---

## THE 5 THINGS THAT MUST WORK FLAWLESSLY ON DAY ONE

1. **Entry execution** — Place MSTR deep OTM LEAP call order on IBKR live. Correct strike, correct quantity, correct expiration.
2. **Position tracking** — Know exactly what we own, entry price, current value, gain %.
3. **Trailing stop monitoring** — Check MSTR closing price every 5 min. Track position peak. Apply correct ladder tier.
4. **Ladder tier escalation** — At +300% peak gain, activate 30% trail. At +500%, tighten to 25%. Never loosen. Partial sell at each tier.
5. **Emergency halt** — If BTC drops below 200-week MA, if breaker hit, if TWS disconnects: alert Commander immediately, halt all new entries, protect open positions.

Everything else — scanners, YouTube intel, projections dashboard, TikTok monitoring — is enhancement. Nice to have, not mission critical.

---

## PHASE 1 FIX DETAILS (for next Claude Code session)

### 1. Laddered Tiers in stop_monitor.py
- **File**: `scripts/stop_monitor.py`
- **What changed**: Replaced flat 30% trail with per-system laddered tiers
- **Key additions**:
  - `TICKER_TO_SYSTEM` dict mapping 40+ tickers to system names
  - `get_system_name(symbol, contract)` — distinguishes mstr_lottery vs mstr_moonshot by DTE (>365 days = moonshot)
  - State now stores `system_name` and `entry` price for each position
  - Gain calculation: `gain_pct = ((hw - entry_price) / entry_price * 100)`
  - Trail lookup: `get_laddered_trail_pct(system_name, gain_pct)` → returns tier-appropriate trail % or None (lottery mode)
  - Short positions still use flat 30% trail

### 2. Circuit Breaker Gate in auditor.py
- **File**: `scripts/auditor.py`
- **What changed**: Added real kill switch that BLOCKS entries, not just alerts
- **Key functions**:
  - `is_breaker_active(system_id)` — fast file check, returns `(blocked, reason)`
  - `set_global_halt(reason)` / `clear_global_halt()` — master kill switch
  - `set_system_breaker(system_id)` / `clear_system_breaker(system_id)` — per-system
  - `get_breaker_status()` — dashboard-ready status for all systems
- **State file**: `data/breaker_state.json`
- **Wired into**: webhook dispatch in `web/app.py` — BUY signals checked against breaker before execution

### 3. IBKR Reconnection Hardening
- **File**: `scripts/ibkr_utils.py` (NEW)
- **Key functions**:
  - `connect_with_retry(host, port, client_id, max_retries)` — exponential backoff 1s→60s
  - `ensure_connected(ib, ...)` — health check before every order, auto-reconnect
- **Telegram alert** on connection failure after all retries exhausted

### 4. Order Error Recovery
- **File**: `scripts/ibkr_utils.py`
- **Key function**: `place_order_with_retry(ib, contract, order, max_retries=3, delay=2)`
- **On failure**: logs to `data/failed_orders.json` + Telegram escalation
- **Accepts**: Filled, Submitted, PreSubmitted as success; retries on Cancelled/Inactive

### 5. Entry Execution Validation
- **File**: `scripts/ibkr_utils.py`
- **Key function**: `validate_entry(ticker, system_id, qty, price)`
- **Checks**: circuit breaker, max order size ($50k), duplicate positions, concentration (40% of system capital)

### 6. Dashboard API Endpoints
- `GET /api/breaker/status` — full breaker status for all systems
- `POST /api/breaker/halt` — activate global halt (body: `{"reason": "..."}`)
- `POST /api/breaker/resume` — clear global halt
- `POST /api/breaker/system/<id>/halt` — halt specific system
- `POST /api/breaker/system/<id>/resume` — resume specific system
- `GET /build-status` — this assessment page with copy button

---

## FILE MAP (for next Claude Code session)

```
/Users/eddiemae/rudy/
├── constitution_v39.py          # Trading rules, breaker thresholds, laddered tiers
├── web/app.py                   # Dashboard, webhooks, API routes, projections, breaker endpoints
├── scripts/
│   ├── system1_v8.py            # MSTR Lottery trader (System 1)
│   ├── trader_moonshot.py       # MSTR Moonshot LEAP trader (System 5)
│   ├── trader[3-12].py          # Individual system traders
│   ├── stop_monitor.py          # Trailing stop enforcement — laddered tiers per system
│   ├── stop_utils.py            # Laddered trail tiers + IBKR stop placement
│   ├── ibkr_utils.py            # NEW — reconnection, order retry, entry validation
│   ├── auditor.py               # System auditor, circuit breaker gate
│   ├── scanner.py               # Master scanner orchestrator
│   ├── telegram.py              # Alert system
│   ├── youtube_scanner.py       # YouTube intel (yt-dlp + API + Gemini + channel search)
│   ├── grok_scanner.py          # X/Twitter via Grok
│   └── [other scanners]
├── strategies/
│   ├── pinescript_mstr_moonshot.pine   # MSTR Moonshot LEAP (TradingView)
│   ├── pinescript_lottery.pine         # MSTR Lottery (TradingView)
│   ├── pinescript_btc_moonshot.pine    # BTC/USD Moonshot (TradingView)
│   └── pinescript_[11 others].pine
├── data/
│   ├── system1_positions.json         # Open positions per system
│   ├── stop_monitor_state.json        # HWM tracking for all positions
│   ├── breaker_state.json             # NEW — circuit breaker state
│   ├── failed_orders.json             # NEW — failed order log
│   └── [intel files].json
└── logs/
    ├── ibkr_connection.log            # NEW — connection attempt history
    ├── order_recovery.log             # NEW — order retry history
    └── [per-system logs]
```

## ENVIRONMENT
- Paper: TWS port 7497, account DUA724990
- Secrets: `~/.agent_zero_env` (no export prefix, no quotes)
- Telegram: Bot 8708275571, Chat 6353235721
- APIs: Google/YouTube (new key), Gemini, Grok/xAI, Tavily (usage exceeded)
- Memory: `~/.claude/projects/-Users-eddiemae/memory/`
- Build Status Page: `http://localhost:3000/build-status`
