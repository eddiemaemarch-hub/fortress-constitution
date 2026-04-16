---
name: MCP Server ib_insync Thread Fix
description: ib_insync must run in a ThreadPoolExecutor with a new event loop inside the MCP server — FastMCP owns the main asyncio loop
type: feedback
---

When `get_account_summary` (or any MCP tool that calls ib_insync) fails with "This event loop is already running" or "No module named 'ib_insync'":

**Rule:** `ib_insync` must run in a `concurrent.futures.ThreadPoolExecutor` thread with an explicit new event loop, because FastMCP owns the main asyncio event loop.

**Why:** FastMCP runs on asyncio. `ib_insync` also uses asyncio internally. Calling `IB().connect()` from within an already-running event loop raises "This event loop is already running". Running in a thread gives ib_insync a clean, independent loop. Fixed March 22, 2026.

**How to apply:**
```python
def _fetch_from_tws():
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    from ib_insync import IB as _IB
    ib = _IB()
    ib.connect("127.0.0.1", 7496, clientId=55, timeout=10)
    # ... do work ...
    ib.disconnect()
    return result

with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
    return executor.submit(_fetch_from_tws).result(timeout=30)
```

**Venv:** `ib_insync` must be installed in `~/rudy/scripts/.mcp_venv` (the MCP server's venv), NOT the system Python. Install with:
```
~/rudy/scripts/.mcp_venv/bin/pip install ib_insync
```
The system Python may have it but the MCP server uses the venv exclusively.
