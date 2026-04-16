---
name: IBKR is the Single Source of Truth for All Prices
description: ALL price data must come from IBKR — no hardcoded prices, no proxy prices, no external APIs
type: feedback
---

## Rule: ALL Price Data Must Come from IBKR

IBKR (Interactive Brokers TWS) is the **single source of truth** for every price in the system. No exceptions.

### What This Means

1. **ALL live prices must come from IBKR:** BTC, MSTR, SPY, options, everything
2. **Never hardcode prices:** No hardcoded ATH, 200W SMA, bull/bear thresholds, or any other price value
3. **Never use GBTC proxy as a display price:** GBTC proxy may be used internally for calculation purposes only — it must NEVER be shown to the user as "the BTC price"
4. **If IBKR is unavailable:** Display "—" or "Connecting..." — NEVER show a stale price or proxy price as if it were live

### Applies To (Every Component)
- `web/app.py` — Dashboard (all price displays)
- `trader_v28.py` — Main v2.8+ strategy daemon
- `trader2_mstr_put.py` — MSTR put ladder monitor
- `trader3_spy_put.py` — SPY put ladder monitor
- `regime_classifier.py` — System 13 Neural Regime Classifier
- `btc_sentinel.py` — BTC sentinel monitor
- All Telegram alerts — prices in messages must be IBKR-sourced

### Applies to AI Brain Grounding (March 23, 2026)
All three brains (Gemini, Grok CT, Grok Scanner) now use live web search grounding. The IBKR price rule applies to grounding too:
- **Google Search grounding (Gemini):** Used for macro/news/regulatory context ONLY. BTC/MSTR prices passed to prompts always come from `trader_v28_state.json` (IBKR-sourced state file). Grounding NEVER overrides these prices.
- **xAI web_search grounding (Grok):** Same rule. X/Twitter data and web search results are for sentiment and news context. Prices in prompts come from IBKR state files.
- In `gemini_brain.py`: PRICE RULE documented in module docstring. `btc_price`, `mstr_price`, `premium` always loaded from `trader_v28_state.json`.
- In `grok_ct_sentiment.py` / `grok_scanner.py`: Same — any price context in prompts comes from IBKR state, not from grounding results.

### Why
- Consistency: one source of truth eliminates price discrepancies across components
- Accuracy: IBKR prices reflect actual execution prices
- Safety: stale or proxy prices can trigger false signals or mislead the Commander
- Grounding safety: web search can return delayed, incorrect, or manipulated price data — IBKR is always authoritative
