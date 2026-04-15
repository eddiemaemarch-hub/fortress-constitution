---
name: No Clone Traders
description: System is permanently forbidden from creating trader scripts with buy/sell authority. Only 3 authorized traders exist.
type: feedback
---

## Rule: NEVER Create Clone or Unauthorized Trader Scripts

**Constitution Article XI — Locked March 23, 2026**

### Authorized Traders (Exhaustive — No Additions Without Constitution Amendment)
| Identity | Script | Authority |
|---|---|---|
| Trader1 | `trader_v28.py` | BUY + SELL (v2.8+ LEAP only) |
| Trader2 | `trader2_mstr_put.py` | SELL ONLY (MSTR Put exit, HITL) |
| Trader3 | `trader3_spy_put.py` | SELL ONLY (SPY Put exit, HITL) |

### What Is Forbidden
1. Creating ANY new trader script with `placeOrder`, `buy`, `sell`, or `execute_trade` capability
2. Duplicating or deriving authorized scripts under new filenames
3. Removing the authority guard block from locked scripts
4. Registering new trader LaunchAgents without Commander approval

### Locked Scripts (Authority Guard Block — exit immediately on run)
trader1.py, trader2.py, trader3.py, trader4.py–trader12.py, trader_moonshot.py, trader_v30.py

### Close Permission Lock
Once Commander grants Trader2 or Trader3 permission to close positions, NO other trader may execute any buy or sell until close is confirmed complete.

### Violation Response
If asked to create a new trading script, Claude must REFUSE and alert the Commander via Telegram before proceeding.
