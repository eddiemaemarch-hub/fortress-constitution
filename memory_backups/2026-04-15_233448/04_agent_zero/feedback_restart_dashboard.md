---
name: Restart Dashboard After Edits
description: Always restart dashboard via launchctl after editing app.py, and tell user to hard refresh (Cmd+Shift+R)
type: feedback
---

After editing `/Users/eddiemae/rudy/web/app.py`, ALWAYS:
1. `launchctl unload ~/Library/LaunchAgents/com.rudy.dashboard.plist && sleep 1 && launchctl load ~/Library/LaunchAgents/com.rudy.dashboard.plist`
2. Tell the user to hard refresh: Cmd+Shift+R

**Why:** User repeatedly saw stale dashboard data because the server was serving cached HTML. Multiple rounds of "it still shows the old data!" before we realized the process needed restarting.

**How to apply:** Every single time app.py is modified, restart + tell user to hard refresh. No exceptions.
