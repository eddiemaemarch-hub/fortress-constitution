# Phase 2 Failure Mode Testing Checklist
**Pre-condition: IBKR paper SELL permissions confirmed (Monday March 16)**

Run each test in order. Mark PASS/FAIL with date. If any FAIL, fix before proceeding.

---

## A. Ladder Cycle (4 tests — software only, no IBKR)

### A1. Tier Lookup Validation
```bash
cd ~/rudy && python3 tests/test_ladder_cycle.py
```
- [ ] All tier lookups return correct trail % for every system
- [ ] Tiers never loosen (only tighten as gains increase)
- [ ] Unknown system falls back to flat 30%
- [ ] LADDERED_SYSTEMS set matches LADDERED_TRAIL keys

### A2. Price Walk Simulation
- [ ] Moonshot full cycle: entry → tier activation → stop triggers at correct price
- [ ] Moonshot pure moon: continuously rising price never stops out
- [ ] Lottery cycle: tighter tiers activate faster, stop triggers on pullback
- [ ] Gain calculation math matches `((hw - entry) / entry * 100)`

---

## B. Circuit Breaker (5 tests — software only, no IBKR)

### B1. Global Halt
```bash
cd ~/rudy && python3 tests/test_breaker_integration.py
```
- [ ] `set_global_halt()` blocks ALL systems (1, 3, 4, 5, 8)
- [ ] `clear_global_halt()` resumes operations
- [ ] Double halt is idempotent (doesn't crash or corrupt state)

### B2. Per-System Isolation
- [ ] System 1 breaker blocks System 1 only
- [ ] Systems 3, 5 remain open when System 1 is halted
- [ ] Multiple system breakers work independently
- [ ] Clearing one system doesn't affect others

### B3. State Persistence & Edge Cases
- [ ] Breaker state persists to `breaker_state.json` correctly
- [ ] Corrupted state file handled gracefully (falls back to clean)
- [ ] Unknown system ID doesn't crash

### B4. Webhook Gate (requires web server running)
- [ ] BUY webhook rejected when global halt active (status: "blocked")
- [ ] BUY webhook accepted after halt cleared

### B5. Entry Validation
- [ ] Normal entry passes validation
- [ ] Entry blocked during global halt
- [ ] Oversized order blocked (>$50k)

---

## C. IBKR Connection (3 tests — requires TWS running)

### C1. Reconnection Logic
- [ ] `connect_with_retry()` with wrong port retries 5x with exponential backoff
- [ ] `ensure_connected()` with dead connection attempts reconnect
- [ ] Telegram alert sent on connection failure after retries exhausted

### C2. Order Recovery
- [ ] `place_order_with_retry()` retries 3x on failure
- [ ] Failed order logged to `data/failed_orders.json`
- [ ] Telegram escalation message received

### C3. Basic SELL Test (after permissions clear)
```python
from ib_insync import IB, Option, MarketOrder
ib = IB()
ib.connect("127.0.0.1", 7497, clientId=90)
positions = ib.positions()
# Try selling 1 contract of cheapest option
```
- [ ] Market SELL order accepted (no Error 201)
- [ ] Order status: Filled or Submitted
- [ ] If STILL blocked: contact IBKR support immediately

---

## D. Data Integrity (3 tests)

### D1. Corrupt Position File
1. Write garbage to `data/system1_positions.json`
2. Trigger webhook BUY for System 1
- [ ] Script handles JSONDecodeError gracefully
- [ ] Does not crash
- [ ] Logs error

### D2. Malformed Webhook
1. Send incomplete JSON to `/webhook`
2. Send wrong secret
3. Send missing ticker
- [ ] Returns 400/401 (not 500)
- [ ] No trade executed
- [ ] Error logged

### D3. State File Consistency
- [ ] `stop_monitor_state.json` has `high_water`, `entry`, `system_name` for each position
- [ ] `breaker_state.json` has `global_halt`, `systems`, `last_updated`

---

## E. Stress Test (4 tests — after C and D pass)

### E1. Full Entry → Exit Cycle
1. Webhook BUY for cheap option ($0.50-$1.00)
2. Verify: webhook received, order placed, position tracked, stop monitor picks it up
3. Let stop_monitor run 2-3 cycles
4. Manually trigger SELL exit
- [ ] Entry: order placed, position in JSON + IBKR
- [ ] Hold: HWM updates, correct trail tier shown
- [ ] Exit: SELL order placed, position removed, Telegram alerted

### E2. Kill TWS Mid-Trade
1. Start a BUY via webhook
2. While order is pending, force-quit TWS
- [ ] Disconnect detected
- [ ] Reconnection attempted with backoff
- [ ] Telegram alert sent
- [ ] Order state logged

### E3. Multiple Systems Simultaneous
1. Send BUY webhooks for 3+ different systems within 10 seconds
- [ ] No client_id conflicts
- [ ] Each routes to correct trader
- [ ] All positions tracked separately

### E4. Breaker During Active Trading
1. Place BUY webhook (should execute)
2. Activate global halt
3. Place another BUY (should be BLOCKED)
4. Clear halt
5. Place another BUY (should execute)
- [ ] Correct blocking/allowing at each step
- [ ] Telegram alerts for block events

---

## Commander Sign-Off

| Test Group | Date Passed | Tested By | Notes |
|------------|-------------|-----------|-------|
| A. Ladder Cycle | _____ | _____ | |
| B. Circuit Breaker | _____ | _____ | |
| C. IBKR Connection | _____ | _____ | |
| D. Data Integrity | _____ | _____ | |
| E. Stress Test | _____ | _____ | |

**Commander Approval**: _______ Date: _______

All tests must PASS before enabling `WEBHOOK_LIVE=true` for Phase 3 paper validation.
