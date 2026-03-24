#!/bin/bash
# Tunnel Keeper — restarts Cloudflare tunnel and sends URL to Telegram
# Runs as a daemon, auto-restarts tunnel if it dies

ENV_FILE="$HOME/.agent_zero_env"
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

LOG="/Users/eddiemae/rudy/logs/tunnel_keeper.log"
TUNNEL_LOG="/tmp/cloudflared_3001.log"

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\": \"${TELEGRAM_CHAT_ID}\", \"text\": \"$1\", \"parse_mode\": \"Markdown\"}" > /dev/null
}

while true; do
    # Kill any existing tunnel on 3001
    pkill -f "cloudflared tunnel --url http://localhost:3001" 2>/dev/null
    sleep 2

    # Start tunnel
    cloudflared tunnel --url http://localhost:3001 > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    echo "[$(date)] Tunnel started PID=$TUNNEL_PID" >> "$LOG"

    # Wait for URL to appear
    for i in $(seq 1 15); do
        sleep 1
        URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" | head -1)
        if [ -n "$URL" ]; then
            break
        fi
    done

    if [ -n "$URL" ]; then
        echo "[$(date)] Tunnel URL: $URL" >> "$LOG"
        # Save URL to file for other scripts
        echo "$URL" > /Users/eddiemae/rudy/data/tunnel_url.txt
        # Send to Telegram
        send_telegram "📱 *Command Center Link Updated*%0A${URL}%0A%0ABookmark this on your iPhone"
    else
        echo "[$(date)] ERROR: No URL captured" >> "$LOG"
        send_telegram "⚠️ Cloudflare tunnel failed to start — no URL captured"
    fi

    # Wait for tunnel process to die
    wait $TUNNEL_PID
    echo "[$(date)] Tunnel died — restarting in 10s" >> "$LOG"
    sleep 10
done
