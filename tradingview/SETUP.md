# Rudy v2.0 — TradingView Setup Guide

## The Automated Flow
```
TradingView Alert fires
    → Webhook hits ngrok URL
    → ngrok forwards to localhost:5555
    → Webhook server processes signal
    → E.M. sends Telegram proposal
    → You reply Yes/No
    → Trader1 executes via IBKR
    → 10x monitor runs automatically
```

Your only job: **say Yes or No on Telegram.**

---

## Step 1: Start ngrok

```bash
ngrok http 5555
```

Copy the HTTPS URL it gives you (e.g., `https://abc123.ngrok-free.app`).

Note: Free ngrok URLs change every restart. If you restart ngrok, update your TradingView alert webhook URLs.

---

## Step 2: Add Pine Script Indicators to TradingView

### System 1 (MSTR/IBIT only):
1. Open TradingView → Pine Editor (bottom panel)
2. Delete default code
3. Copy/paste contents of `system1_mstr_lottery.pine`
4. Click "Add to chart"
5. Apply to MSTR and/or IBIT charts

### System 2 (any ticker EXCEPT MSTR/IBIT):
1. Open Pine Editor
2. Copy/paste contents of `system2_conservative_diagonal.pine`
3. Click "Add to chart"
4. Apply to any ticker you trade (AAPL, TSLA, NVDA, etc.)
5. If you accidentally apply it to MSTR or IBIT, it will show a red BLOCKED warning

---

## Step 3: Create Alerts with Webhooks

For each indicator/chart:

1. Click the **Alert** button (clock icon) on TradingView
2. **Condition**: Select the Rudy indicator (System 1 or System 2)
3. **Alert action**: Select the specific signal (e.g., "S1 Quarter Entry" or "S2 Bullish Diagonal Entry")
4. **Expiration**: Set to "Open-ended" (Premium feature)
5. **Webhook URL**: Paste your ngrok HTTPS URL
6. **Message**: The alert message is already built into the Pine Script — leave it as-is
7. Click **Create**

### If you want to create alerts manually (without Pine Scripts):
Use the templates from `alert_templates.json`. Copy the `message` value and paste into the alert Message field.

---

## Step 4: Start Rudy

```bash
cd ~/rudy && bash start.sh
```

This starts:
- Webhook server on port 5555
- E.M. Telegram bot

---

## System Rules (Constitution v50.0)

| | System 1 | System 2 |
|---|---|---|
| Tickers | MSTR, IBIT only | Everything EXCEPT MSTR, IBIT |
| Strategy | Deep OTM calls (lottery) | Conservative diagonals |
| Capital | $100k/quarter | $10k total, $250 max/trade |
| Frequency | Quarterly | As signals appear |

---

## Troubleshooting

**Alert not firing?**
- Make sure the indicator is on the chart
- Check alert hasn't expired
- Verify the condition matches (e.g., RSI must actually be oversold)

**Webhook not received?**
- Is ngrok running? (`ngrok http 5555`)
- Is the webhook server running? (`python3 ~/rudy/scripts/webhook_server.py 5555`)
- Did the ngrok URL change? Update it in TradingView alerts

**E.M. not sending Telegram?**
- Check `~/rudy/logs/em.log` for errors
- Make sure E.M. bot is running: `python3 ~/rudy/scripts/em_bot.py`

**Trade not executing?**
- Is TWS Desktop open and logged in?
- Is API enabled in TWS? (File → Global Config → API → Settings → Enable)
- Check `~/rudy/logs/trader1.log`
