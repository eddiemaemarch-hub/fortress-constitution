---
name: Equity Chart Feature Added 2026-03-25
description: Daily equity curve chart — logs PnL to pnl_history.json, sends chart to Telegram, dashboard endpoint /api/equity_chart
type: project
---

On 2026-03-25, added equity curve charting to Rudy v2.0:

**Why:** Commander wants visual tracking of put hedge values and account NLV over time.

**How to apply:**
- `daily_status.py` now logs T2/T3 values + NLV to `data/pnl_history.json` on every run (3x daily: open, midday, close)
- After logging, generates a dark-themed matplotlib chart and sends it to Telegram via sendPhoto API
- Dashboard serves the chart at `/api/equity_chart` (rendered on-demand from pnl_history.json)
- Equity Curve card added to dashboard HTML between Trader3 and Auditor cards
- Uses matplotlib (Agg backend), seaborn darkgrid theme
- Chart shows: T2 MSTR $50P (red) + T3 SPY $430P (teal) position values with cost basis lines, and NLV area fill (gold)
- Need 2+ data points before chart renders; onerror hides the img tag gracefully
