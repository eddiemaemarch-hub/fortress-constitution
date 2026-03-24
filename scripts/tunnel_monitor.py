"""Cloudflare Tunnel Monitor — detects URL changes and notifies via Telegram.
Saves current webhook URL to ~/rudy/data/webhook_url.txt for reference.
Also restarts tunnel if it's down.
"""
import os
import sys
import re
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram

DATA_DIR = os.path.expanduser("~/rudy/data")
URL_FILE = os.path.join(DATA_DIR, "webhook_url.txt")
LOG_DIR = os.path.expanduser("~/rudy/logs")
CF_LOG = os.path.join(LOG_DIR, "cloudflared.log")


def get_tunnel_url():
    """Get current Cloudflare tunnel URL from log file."""
    if not os.path.exists(CF_LOG):
        return None
    with open(CF_LOG) as f:
        content = f.read()
    matches = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', content)
    return matches[-1] if matches else None


def is_tunnel_running():
    """Check if cloudflared process is running."""
    try:
        result = subprocess.run(["pgrep", "-f", "cloudflared tunnel"], capture_output=True, text=True)
        return bool(result.stdout.strip())
    except:
        return False


def start_tunnel():
    """Start cloudflare quick tunnel."""
    # Clear old log
    with open(CF_LOG, "w") as f:
        f.write("")
    subprocess.Popen(
        ["/opt/homebrew/bin/cloudflared", "tunnel", "--url", "http://localhost:3000"],
        stdout=open(CF_LOG, "w"),
        stderr=subprocess.STDOUT,
    )


def get_saved_url():
    if os.path.exists(URL_FILE):
        with open(URL_FILE) as f:
            return f.read().strip()
    return None


def save_url(url):
    with open(URL_FILE, "w") as f:
        f.write(url)


def check_and_notify():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Restart tunnel if down
    if not is_tunnel_running():
        print(f"[{ts}] Tunnel down — restarting...")
        start_tunnel()
        import time
        time.sleep(8)

    url = get_tunnel_url()
    if not url:
        print(f"[{ts}] No tunnel URL found")
        return

    saved = get_saved_url()
    if url != saved:
        save_url(url)
        webhook_url = f"{url}/webhook"

        telegram.send(
            f"*WEBHOOK URL UPDATED*\n\n"
            f"New TradingView webhook URL:\n`{webhook_url}`\n\n"
            f"Update your TradingView alerts to use this URL.\n"
            f"Time: {ts}"
        )

        with open(f"{LOG_DIR}/tunnel.log", "a") as f:
            f.write(f"[{ts}] URL changed: {webhook_url}\n")

        print(f"[{ts}] New webhook URL: {webhook_url}")
    else:
        print(f"[{ts}] Tunnel OK: {url}")


if __name__ == "__main__":
    check_and_notify()
