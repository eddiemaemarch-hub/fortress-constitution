---
name: Update Globally Means Everything
description: When user says "update globally" they mean every single file, panel, dashboard card, constitution, PineScript, projections — leave NOTHING stale
type: feedback
---

When the user says "update globally" or "update Rudy v2.0 globally", update ALL of these:
- `/Users/eddiemae/rudy/web/app.py` — ALL dashboard cards, panels, pages (main, /positions, /projections, /pinescripts)
- `/Users/eddiemae/rudy/constitution_v39.py` — Constitution (currently v50.0)
- `/Users/eddiemae/rudy/pinescript/rudy_v28plus.pine` — PineScript header/description
- `/Users/eddiemae/rudy/strategies/pinescript_mstr_cycle_low_entry_v28plus.pine` — Strategies copy
- `/Users/eddiemae/rudy/scripts/trader_v28.py` — Main trading daemon
- `/Users/eddiemae/rudy/scripts/trader2_mstr_put.py` — MSTR put ladder
- `/Users/eddiemae/rudy/scripts/trader3_spy_put.py` — SPY put ladder
- Any other script with stale version numbers or outdated info

**Why:** The user got repeatedly frustrated when updates were only applied to 1-2 files. "This is real money!" — partial updates erode trust and can cause systems to disagree with each other.

**MSTR 8-K updates:** Treasury data (holdings, avg cost, diluted shares) is now AUTO-UPDATED weekly by `mstr_treasury_updater.py` → `mstr_treasury.json`. Trader1 reads from this JSON for live mNAV. No more manual updates to `trader_v28.py` or `constitution_v39.py` for holdings data. **PineScript files still need manual update** on new 8-K — Pine can't read JSON, so `rudy_v28plus.pine` and `pinescript_mstr_cycle_low_entry_v28plus.pine` have hardcoded holdings for TradingView.

**How to apply:** After any significant change, proactively sweep all files above. Don't wait to be asked twice.
