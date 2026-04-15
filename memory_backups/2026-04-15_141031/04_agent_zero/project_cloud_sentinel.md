---
name: BTC Cloud Sentinel (GitHub Actions)
description: Cloud-based BTC + 10Y monitor running on GitHub Actions every 4 hours. Independent backup for local btc_sentinel daemon — runs even when Mac mini is off.
type: project
---

### BTC Cloud Sentinel v1.0 (2026-04-15)

**Why:** Local `btc_sentinel.py` only runs when the Mac mini is on. Commander needed cloud-based redundancy that survives power outages, Mac restarts, etc. GitHub Actions was chosen over Claude Routines because it's free, faster, and doesn't depend on Anthropic uptime.

**How to apply:** Runs autonomously every 4 hours. Sends Telegram alerts on critical events. Daily heartbeat at 12:00 UTC confirms it's alive. No intervention needed unless workflow fails (check https://github.com/eddiemaemarch-hub/fortress-constitution/actions).

### Files
- Script: `.github/scripts/btc_cloud_sentinel.py`
- Workflow: `.github/workflows/btc-cloud-sentinel.yml`
- Schedule: Every 4 hours UTC (`0 */4 * * *`)

### Alert Triggers
1. **BTC drop >5% in 4 hours** — panic signal
2. **BTC crosses below 200W SMA (~$60,085)** — v2.8+ arm zone, critical
3. **BTC within 10% of 200W SMA** — approaching arm zone
4. **10Y Treasury yield spike >10bps** — BTC headwind

### Data Sources (all free, no API keys)
- BTC: CoinGecko public API
- 10Y: Yahoo Finance ^TNX
- Alerts: Telegram bot API

### GitHub Secrets Required
- `TELEGRAM_BOT_TOKEN` — already set 2026-04-15
- `TELEGRAM_CHAT_ID` — already set 2026-04-15

### Manual Trigger
```bash
cd ~/fortress-constitution && gh workflow run btc-cloud-sentinel.yml
```

### First Run Result (2026-04-15 17:30 UTC)
- BTC: $74,177 | 24h: -0.79% | 4h: +0.13%
- 200W SMA: $60,085 (+23.4%)
- 10Y: 4.282% (+2.6bps)
- No alerts — system nominal
