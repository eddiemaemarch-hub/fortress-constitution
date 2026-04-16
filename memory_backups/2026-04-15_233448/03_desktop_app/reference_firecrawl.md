---
name: Firecrawl Integration
description: Live web scraping via Firecrawl API — feeds headlines into Grok CT + Gemini brain prompts
type: reference
---

Firecrawl API key stored in `~/.agent_zero_env` as `FIRECRAWL_API_KEY`.
Module: `~/rudy/scripts/firecrawl_intel.py`

**Scrape functions (30min cache):**
- `scrape_crypto_headlines()` — CoinDesk, Cointelegraph, Decrypt
- `scrape_fear_greed_detail()` — alternative.me FnG with historical values
- `scrape_mstr_news()` — Google news search for MicroStrategy
- `scrape_btc_onchain()` — blockchain.com mempool
- `get_full_intel()` — all of the above in one call

**Integrated into:**
- `grok_ct_sentiment.py` — scraped headlines added to prompt for richer sentiment grounding
- `gemini_brain.py` — news_digest() feeds headlines + MSTR news into Gemini prompt

**Cache:** `~/rudy/data/firecrawl_cache.json` (30min TTL per source)
