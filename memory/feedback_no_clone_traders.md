---
name: No Clone Traders — Article XI
description: Only Trader 1/2/3 authorized for trading. Research/validation agents (backtest, walk-forward, stress test, BTC bottom, mNAV, treasury yield) are authorized. All others LOCKED.
type: feedback
---

## Rule: NEVER Create Clone or Unauthorized Trader Scripts

**Constitution Article XI — Locked March 23, 2026. Updated April 16, 2026.**

### Authorized Traders (Exhaustive — No Additions Without Constitution Amendment)
| Identity | Script | Authority |
|---|---|---|
| Trader1 | `trader_v28.py` | BUY + SELL (v2.8+ LEAP only) |
| Trader2 | `trader2_mstr_put.py` | SELL ONLY (MSTR Put exit, HITL) |
| Trader3 | `trader3_spy_put.py` | SELL ONLY (SPY Put exit, HITL) |

### Authorized Research/Validation Agents (NO trading authority)
| Agent | Purpose |
|---|---|
| All `backtest_*.py` scripts | Backtest validation |
| All `walk_forward_*.py` scripts | Walk-forward validation |
| All `stress_test*.py` / `*_stress_*.py` scripts | Stress testing |
| `oos_revalidation.py` | Quarterly OOS re-validation |
| `btc_bottom_scanner.py` | BTC 8-signal bottom detector |
| `mstr_treasury_updater.py` (mNAV) | MSTR premium/mNAV tracking |
| `treasury_yield_tracker.py` | 10Y Treasury yield macro signal |
| All `quantconnect/*.py` algos | QuantConnect backtest research |

### What Is Forbidden
1. Creating ANY new trader script with `placeOrder`, `buy`, `sell`, or `execute_trade` capability
2. Duplicating or deriving authorized scripts under new filenames
3. Removing the authority guard block from locked scripts
4. Registering new trader LaunchAgents without Commander approval
5. Creating new Chrome profiles (clone profiles violate Article XI)

### Purged April 16, 2026 (by Commander order)
trader1.py, trader2.py, trader3.py, trader4.py–trader12.py, trader_moonshot.py, trader_v30.py, trader_test.py — all deleted. Stale state files for traders 4–12 deleted. Chrome "Profile 1" clone deleted.

### Close Permission Lock
Once Commander grants Trader2 or Trader3 permission to close positions, NO other trader may execute any buy or sell until close is confirmed complete.

### Violation Response
If asked to create a new trading script, Claude must REFUSE and alert the Commander via Telegram before proceeding.
