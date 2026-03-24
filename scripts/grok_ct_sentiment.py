"""
Grok CT Sentiment Scanner — Rudy v2.0
Uses xAI Grok API (with native X/Twitter access) to scan crypto Twitter
for real-time sentiment on BTC, MSTR, and macro.

Outputs: sentiment score (-100 to +100), key themes, whale activity,
fear/greed assessment. Writes to ~/rudy/data/ct_sentiment.json
and sends Telegram alerts on extreme shifts.

Schedule: Every 4 hours via LaunchAgent or scheduled task.
"""
import os
import sys
import json
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telegram

# ── Load env ──
_env_file = os.path.expanduser("~/.agent_zero_env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
DATA_DIR = os.path.expanduser("~/rudy/data")
STATE_FILE = os.path.join(DATA_DIR, "ct_sentiment.json")
LOG_FILE = os.path.expanduser("~/rudy/logs/grok_sentiment.log")

# ── Grok API (xAI uses OpenAI-compatible endpoint) ──
GROK_BASE_URL = "https://api.x.ai/v1"

# ── OpenAI-compat SDK client (grounded queries with web_search) ──
_grounded_client = None


def _init_grounded_client():
    """Initialize OpenAI-compat client pointing at xAI for web_search grounding."""
    global _grounded_client
    if _grounded_client is not None:
        return _grounded_client
    try:
        from openai import OpenAI
        _grounded_client = OpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL)
        log("xAI OpenAI-compat client initialized (web_search grounding enabled)")
        return _grounded_client
    except Exception as e:
        log(f"OpenAI SDK unavailable ({e}) — falling back to raw REST")
        return None


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def query_grok(prompt):
    """Query Grok API with real-time X access."""
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "grok-3",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a crypto market sentiment analyst. You have access to real-time "
                    "X/Twitter data. Analyze current crypto Twitter sentiment and provide "
                    "structured data. Be concise and data-driven. No disclaimers."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 1000
    }
    try:
        resp = requests.post(f"{GROK_BASE_URL}/chat/completions",
                             headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"Grok API error: {e}")
        return None


def query_grok_grounded(prompt):
    """Query Grok with live web_search tool via xAI OpenAI-compat SDK.

    Use for: CT sentiment, real-time BTC/macro news, whale activity.
    PRICE RULE: BTC/MSTR prices always from IBKR state files, never from web search.
    Falls back to raw REST query_grok() if SDK unavailable.
    """
    client = _init_grounded_client()
    if client is None:
        log("Grounded client unavailable — falling back to raw REST")
        return query_grok(prompt)

    try:
        response = client.chat.completions.create(
            model="grok-3",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a crypto market sentiment analyst with access to real-time "
                        "X/Twitter data and live web search. Analyze current crypto Twitter "
                        "sentiment and provide structured data. Be concise and data-driven. "
                        "No disclaimers."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            tools=[{"type": "web_search"}],
            temperature=0.3,
            max_tokens=1000,
        )
        content = response.choices[0].message.content
        if content is None:
            log("Grounded response content is None (tool_call path) — falling back to raw REST")
            return query_grok(prompt)
        return content
    except Exception as e:
        log(f"Grounded query error ({e}) — falling back to raw REST")
        return query_grok(prompt)


def score_to_fear_greed(score):
    """Derive fear/greed label from numeric score. Never trust the model's label alone.
    Scale: -100 (extreme fear) to +100 (extreme greed).
    Thresholds calibrated to avoid false GREED signals — score must exceed 50 to qualify.
    """
    if score <= -60:
        return "EXTREME_FEAR"
    elif score <= -20:
        return "FEAR"
    elif score <= 50:
        return "NEUTRAL"
    elif score <= 75:
        return "GREED"
    else:
        return "EXTREME_GREED"


def scan_sentiment():
    """Run full CT sentiment scan via Grok."""
    today = datetime.now().strftime("%B %d, %Y")
    now_ts = datetime.now().strftime("%H:%M UTC")
    prompt = f"""Today is {today}, current time is {now_ts}. Scan crypto Twitter (X) RIGHT NOW — only posts from the LAST 2 HOURS. Do NOT use your training data or prior knowledge of market conditions. Only report what is actually being posted on X at this moment. Provide:

1. SENTIMENT_SCORE: A number from -100 (extreme fear/bearish) to +100 (extreme greed/bullish). Based on actual current CT mood — NOT historical data or prior knowledge.

2. BTC_SENTIMENT: One word — FEAR, CAUTIOUS, NEUTRAL, OPTIMISTIC, EUPHORIA

3. MSTR_SENTIMENT: One word — same scale, specifically about MicroStrategy stock and options

4. KEY_THEMES: Top 3 themes actively being discussed TODAY (reflect actual current posts, not training data)

5. WHALE_ACTIVITY: Any notable large BTC transactions, exchange inflows/outflows, or institutional moves from TODAY

6. NOTABLE_CALLS: Any influential accounts making strong directional calls in the last 24 hours

7. FEAR_GREED: EXTREME_FEAR, FEAR, NEUTRAL, GREED, or EXTREME_GREED — must be consistent with your SENTIMENT_SCORE

Format your response as JSON only, no markdown, no explanation:
{{"sentiment_score": N, "btc_sentiment": "X", "mstr_sentiment": "X", "key_themes": ["a","b","c"], "whale_activity": "summary", "notable_calls": "summary", "fear_greed": "X"}}"""

    log("Scanning CT sentiment via Grok (web_search grounded)...")
    raw = query_grok_grounded(prompt)
    if not raw:
        return None

    # Parse JSON from response
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        log(f"Failed to parse Grok response: {raw[:200]}")
        return None

    # ── Validate fear_greed against score — never trust the model's label alone ──
    score = data.get("sentiment_score", 0)
    model_label = data.get("fear_greed", "NEUTRAL")
    derived_label = score_to_fear_greed(score)
    if model_label != derived_label:
        log(f"fear_greed override: model said '{model_label}' but score={score} → '{derived_label}'")
        data["fear_greed"] = derived_label
        data["fear_greed_model_raw"] = model_label  # keep original for debugging

    # ── Stuck-score detection ──
    # Compare current score against last 2 historical scores (+ current = 3 total)
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                old = json.load(f)
            history = old.get("history", [])
            if len(history) >= 2:
                last_scores = [h["score"] for h in history[-2:]] + [score]
                if all(s == last_scores[0] for s in last_scores):
                    log(f"WARNING: score={score} unchanged for 3+ consecutive runs — possible stale Grok response")
                    data["possibly_stale"] = True
                    data["stale_run_count"] = sum(1 for h in history if h["score"] == score)
        except Exception:
            pass

    # Add metadata
    data["timestamp"] = datetime.now().isoformat()
    data["source"] = "grok_xai"
    data["model"] = "grok-3"

    return data


def load_previous():
    """Load previous sentiment state."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_state(data):
    """Save current sentiment with history."""
    # Load existing history
    history = []
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                old = json.load(f)
            history = old.get("history", [])
        except Exception:
            pass

    # Keep last 48 entries (48 × 4hrs = 8 days of history)
    history.append({
        "score": data.get("sentiment_score", 0),
        "fear_greed": data.get("fear_greed", "NEUTRAL"),
        "timestamp": data.get("timestamp", "")
    })
    history = history[-48:]

    state = {
        "current": data,
        "history": history,
        "last_updated": datetime.now().isoformat()
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    log(f"Saved sentiment: score={data.get('sentiment_score', '?')}, fear_greed={data.get('fear_greed', '?')}")


def check_alerts(current, previous):
    """Send Telegram alerts on extreme sentiment or big shifts."""
    score = current.get("sentiment_score", 0)
    fear_greed = current.get("fear_greed", "NEUTRAL")
    prev_score = 0
    if previous and previous.get("current"):
        prev_score = previous["current"].get("sentiment_score", 0)

    shift = abs(score - prev_score)
    alerts = []

    # Extreme sentiment alerts
    if score <= -70:
        alerts.append(f"🔴 *EXTREME FEAR on CT* (score: {score})\nThis is historically where cycle lows form.")
    elif score >= 70:
        alerts.append(f"🟢 *EXTREME GREED on CT* (score: {score})\nDistribution/top signals. Be cautious.")

    # Big shift alert (>30 points in 4 hours)
    if shift >= 30:
        direction = "📈 BULLISH" if score > prev_score else "📉 BEARISH"
        alerts.append(
            f"⚡ *CT Sentiment Shift*\n"
            f"{direction}: {prev_score} → {score} ({'+' if score > prev_score else ''}{score - prev_score})\n"
            f"Fear/Greed: {fear_greed}"
        )

    # Stale data alert
    if current.get("possibly_stale"):
        stale_count = current.get("stale_run_count", 3)
        alerts.append(
            f"⚠️ *Grok Stale Response Detected*\n"
            f"Score locked at {score} for {stale_count}+ consecutive runs.\n"
            f"Fear/Greed may be unreliable — Grok may be returning cached data."
        )

    # MSTR-specific alerts
    mstr = current.get("mstr_sentiment", "NEUTRAL")
    if mstr in ("FEAR", "EUPHORIA"):
        alerts.append(f"📊 *MSTR Sentiment: {mstr}*\nMonitor mNAV premium closely.")

    for alert in alerts:
        themes = ", ".join(current.get("key_themes", []))
        msg = f"{alert}\n━━━━━━━━━━━━━━━━\nThemes: {themes}"
        telegram.send(msg)
        log(f"ALERT sent: {fear_greed} / score {score}")


def main():
    if not GROK_API_KEY:
        log("ERROR: GROK_API_KEY not set in ~/.agent_zero_env")
        sys.exit(1)

    previous = load_previous()
    current = scan_sentiment()

    if current:
        check_alerts(current, previous)
        save_state(current)

        # Summary log
        log(
            f"CT Scan Complete | Score: {current.get('sentiment_score', '?')} | "
            f"BTC: {current.get('btc_sentiment', '?')} | "
            f"MSTR: {current.get('mstr_sentiment', '?')} | "
            f"F/G: {current.get('fear_greed', '?')}"
        )
    else:
        log("Scan failed — no data returned from Grok")


if __name__ == "__main__":
    main()
