---
name: Use launchctl Not nohup
description: All daemons managed by macOS LaunchAgents — never use nohup or manual process launching
type: feedback
---

All Rudy daemons are managed by macOS LaunchAgents with KeepAlive:true. To restart a daemon:
```
launchctl unload ~/Library/LaunchAgents/com.rudy.<name>.plist
launchctl load ~/Library/LaunchAgents/com.rudy.<name>.plist
```

NEVER use `nohup python3 script.py &` — this creates duplicate processes that compete with the LaunchAgent-managed instance.

**Why:** User discovered 4 trader processes running instead of 2 because manual nohup launches competed with LaunchAgent instances.

**How to apply:** Always use launchctl for start/stop/restart. Current LaunchAgents:
- `com.rudy.trader1` — trader_v28.py (created March 22, 2026 — was the LAST daemon without a LaunchAgent)
- `com.rudy.trader2` — trader2_mstr_put.py
- `com.rudy.trader3` — trader3_spy_put.py
- `com.rudy.dashboard` — web/app.py (port 3001)
- `com.rudy.cloudflared` — Cloudflare tunnel
- `com.rudy.btc-sentinel` — btc_sentinel.py (24/7 BTC monitor)

**March 22 fix:** Trader1 was the last daemon running without a LaunchAgent (started via manual nohup). It lost its IBKR socket on March 20 and did not auto-restart. Fixed by creating `com.rudy.trader1.plist` with KeepAlive:true. Now ALL daemons have LaunchAgents — zero daemons should ever be started manually again.
