---
name: Use Shared Telegram Module
description: All scripts must use ~/rudy/scripts/telegram.py for sending messages, not raw os.environ.get for credentials
type: feedback
---

All Telegram sends MUST use the shared module at `~/rudy/scripts/telegram.py`, which loads credentials from `~/.agent_zero_env`.

Do NOT use `os.environ.get("TELEGRAM_BOT_TOKEN")` directly — LaunchAgent-managed daemons don't inherit shell env vars, so this approach silently fails.

**Why:** trader2, trader3, and btc_sentinel all had broken Telegram for days because they used os.environ.get() instead of the shared module. The user went an entire day without receiving a single update.

**How to apply:** Any new script that needs Telegram should do:
```python
sys.path.insert(0, os.path.expanduser("~/rudy/scripts"))
import telegram as tg
tg.send(msg)
```
