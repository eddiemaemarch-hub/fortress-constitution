# Shadow Mode Integration Guide
**Rudy v2.0 | Drop-in broker adapter**

## Architecture
```
RUDY_MODE=shadow → broker_factory.py → ShadowBroker  (no IBKR)
RUDY_MODE=paper  → broker_factory.py → IBKRBroker    (port 7497)
RUDY_MODE=live   → broker_factory.py → IBKRBroker    (port 7496) + second confirmation
```

Every trader script calls `broker.place_order(order)`. The factory decides what happens.

---

## Files Added
```
scripts/
├── broker_base.py       ← Order/Fill/Position dataclasses + abstract interface
├── broker_factory.py    ← Mode switch (reads RUDY_MODE env)
├── shadow_broker.py     ← Shadow engine (simulated fills, ladder, storms)
├── ibkr_broker.py       ← IBKR wrapper (delegates to ibkr_utils)
└── shadow_dashboard.py  ← Terminal dashboard (run separately)
```

---

## Integration Changes Required

### 1. trader_moonshot.py — execute_entry()

**Before (line 293-295):**
```python
order = MarketOrder("BUY", qty)
order.tif = "GTC"
trade = ib.placeOrder(contract, order)
```

**After:**
```python
from broker_factory import get_broker, Order
broker = get_broker()

# Replace ib.placeOrder with:
fill = broker.place_order(Order(
    symbol=SYMBOL,
    action="BUY",
    qty=qty,
    order_type="MKT",
    system="mstr_moonshot",
    limit_price=opt_price,
    strike=lc["strike"],
    expiry=lc["expiry"],
    right="C",
))

if not fill.is_success:
    log(f"  ENTRY FAILED: {fill.reason}")
    continue

fill_price = fill.fill_price
```

**Also update the SELL orders in monitor_gains() (lines 441-443):**
```python
# Before:
order = MarketOrder("SELL", leg["qty"])
order.tif = "GTC"
trade = ib.placeOrder(contract, order)

# After:
fill = broker.place_order(Order(
    symbol=SYMBOL, action="SELL", qty=leg["qty"],
    system="mstr_moonshot", limit_price=current_price,
    strike=leg["strike"], expiry=leg["expiry"],
    comment="Laddered stop triggered",
))
```

### 2. system1_v8.py — execute_buy/sell

Same pattern. Replace `ib.placeOrder(contract, order)` with `broker.place_order(Order(...))`.

### 3. All other trader scripts (trader3.py - trader12.py)

Add to the top of each:
```python
from broker_factory import get_broker, Order
broker = get_broker()
```

Replace every `ib.placeOrder(contract, order)` with the equivalent `broker.place_order()` call.

### 4. web/app.py — webhook dispatch

**In route_tv_signal() (after the circuit breaker check):**

No changes needed to the webhook dispatch itself. The breaker gate already works.
When you're ready to integrate shadow mode into the webhook flow:

```python
from broker_factory import get_broker, Order
broker = get_broker()

# In the execution path after routing:
fill = broker.place_order(Order(
    symbol=ticker,
    action=action,
    qty=signal.get("qty", 1),
    order_type="MKT",
    system=route.get("system", "unknown"),
    limit_price=price,
))
```

### 5. stop_monitor.py — price feed

**Add after getting the current price (line 131):**
```python
# Feed prices into shadow engine for ladder tracking
try:
    from broker_factory import get_broker
    _broker = get_broker()
    if hasattr(_broker, 'update_price'):
        _broker.update_price(c.symbol, mid, system_name)
except Exception:
    pass
```

---

## Mode Switch

Add to `~/.agent_zero_env`:
```
RUDY_MODE=shadow
```

**Shadow mode (now):**
```bash
export RUDY_MODE=shadow
python web/app.py
```

**Paper mode (when SELL permissions clear):**
```bash
export RUDY_MODE=paper
python web/app.py
```

**Live mode (October — requires double confirmation):**
```bash
export RUDY_MODE=live
export RUDY_LIVE_CONFIRMED=yes_i_understand_real_money
python web/app.py
```

---

## Run the Dashboard

```bash
cd ~/rudy && python scripts/shadow_dashboard.py
```

---

## Timeline
| Week | Mode | Action |
|------|------|--------|
| Now → Week 1 | shadow | Signals flow, zero capital risk |
| Week 2 | shadow | Confirm no storms, no races, ladder correct |
| Week 3 | paper | RUDY_MODE=paper, IBKR paper fills |
| Week 4+ | paper | Shadow + paper simultaneously, compare fills |
| October | live | Switch when BTC entry window opens |
