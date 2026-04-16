---
name: OpenCLI-RS Web Intelligence Tool
description: opencli-rs installed at ~/bin/ — turns 55+ websites into CLI commands via Chrome session reuse. Intel scanner daemon at com.rudy.opencli-intel.
type: reference
---

### OpenCLI-RS v0.1.3 (installed 2026-03-30)

**Binary:** `~/bin/opencli-rs`
**GitHub:** https://github.com/nashsu/opencli-rs
**Intel Script:** `scripts/opencli_intel.py` (LaunchAgent: com.rudy.opencli-intel, 30-min loop)
**Data:** `data/opencli_intel.json`

### Working Public-Mode Sources (no Chrome)
- `hackernews top/search` — crypto sentiment, trending tech
- `devto tag bitcoin/crypto` — developer crypto articles
- `bloomberg markets/economics/main` — RSS feeds (may timeout)
- `bbc news` — macro headlines (may timeout)

### Browser-Mode Sources (needs Chrome + extension)
- `reddit subreddit bitcoin/cryptocurrency` — BTC/crypto sentiment
- `twitter search bitcoin/MSTR` — social mentions
- `yahoo-finance quote MSTR/BTC-USD` — price quotes
- `reuters search bitcoin` — financial news

### Chrome Extension Setup (not yet installed)
1. Download extension from GitHub releases
2. chrome://extensions → Developer mode → Load unpacked
3. Keep Chrome open while scanner runs

### CLI Usage
```bash
~/bin/opencli-rs hackernews top --limit 10 --format json
~/bin/opencli-rs bloomberg markets --format json
~/bin/opencli-rs reddit subreddit bitcoin --limit 10 --format json
```

### Python Integration
```python
result = subprocess.run(["opencli-rs", "site", "cmd", "--format", "json"], capture_output=True, text=True)
data = json.loads(result.stdout)
```
