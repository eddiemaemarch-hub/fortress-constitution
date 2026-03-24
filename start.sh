#!/bin/bash
# Rudy v2.0 — Master Launcher
# Constitution v50.0 — LIVE MODE

# Load environment
source ~/.agent_zero_env 2>/dev/null
export TELEGRAM_BOT_TOKEN=8708275571:AAF_PFC_WxBsWhUG9wgsUdatSHb8Dj10Ook
export TELEGRAM_CHAT_ID=6353235721
export GEMINI_API_KEY=AIzaSyCmv7Hsz8gvLd1KCWvjHDWUo1lYun-5NuQ
export GOOGLE_API_KEY=AIzaSyCmv7Hsz8gvLd1KCWvjHDWUo1lYun-5NuQ
export DEEPSEEK_API_KEY=sk-5771ec73d852484fbdb356c4ac2bd948
export QC_API_TOKEN=a5e10d30d2c0f483c2c62a124375b2fcf4e0f907d54ab3ae863e7450e50b7688
export QC_USER_ID=473242

echo "=== Rudy v2.0 — Constitution v50.0 — LIVE ==="

# Start v2.8+ Live Trading Daemon
echo "Starting v2.8+ Trend Adder daemon (LIVE)..."
python3 ~/rudy/scripts/trader_v28.py --mode live --confirm-live &
TRADER_PID=$!

# Start Command Center dashboard (port 3001)
echo "Starting Command Center on port 3001..."
python3 ~/rudy/web/app.py &
DASH_PID=$!

# Start Cloudflare Tunnel (sends URL to Telegram on start)
echo "Starting Cloudflare Tunnel..."
bash ~/rudy/scripts/tunnel_keeper.sh &
TUNNEL_PID=$!

# Start E.M. (Telegram approval bot)
echo "Starting E.M. bot..."
python3 ~/rudy/scripts/em_bot.py &
EM_PID=$!

echo ""
echo "=== ALL SYSTEMS ONLINE — LIVE TRADING ==="
echo "Strategy:   v2.8+ Trend Adder"
echo "Account:    U15746102 (LIVE)"
echo "IBKR:       TWS port 7496 (LIVE)"
echo "Dashboard:  http://localhost:3001"
echo "Tunnel:     Check Telegram for current URL"
echo "Eval:       Weekdays 3:45 PM ET"
echo "Cowork:     3x daily updates (9:30 AM, 12 PM, 4 PM)"
echo "=========================="
echo ""
echo "PIDs: trader=$TRADER_PID dash=$DASH_PID tunnel=$TUNNEL_PID em=$EM_PID"
echo "To stop: kill $TRADER_PID $DASH_PID $TUNNEL_PID $EM_PID"

wait
