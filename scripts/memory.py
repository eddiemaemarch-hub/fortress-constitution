"""Memory — Persistent Trading Memory System for Rudy v2.0
Uses both Gemini and Claude (via Grok as proxy) to process, store, and recall
trading lessons, patterns, mistakes, and market context.
Stores memories in ~/rudy/data/memory/ with semantic categories.
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram

LOG_DIR = os.path.expanduser("~/rudy/logs")
MEMORY_DIR = os.path.expanduser("~/rudy/data/memory")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

# Memory category files
CATEGORIES = {
    "trades": "trade_lessons.json",       # Lessons from wins/losses
    "patterns": "pattern_memory.json",    # Recurring chart/signal patterns
    "regime": "regime_history.json",      # Market regime transitions
    "mistakes": "mistakes.json",          # Trading mistakes to avoid
    "signals": "signal_quality.json",     # Signal accuracy tracking
    "catalysts": "catalyst_history.json", # Catalyst outcomes
    "sentiment": "sentiment_log.json",    # X/YouTube sentiment vs price outcomes
    "context": "market_context.json",     # Broader market context snapshots
}

# API setup
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_URL = "https://api.x.ai/v1/chat/completions"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Memory {ts}] {msg}")
    with open(f"{LOG_DIR}/memory.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def _load_category(category):
    """Load a memory category file."""
    filename = CATEGORIES.get(category)
    if not filename:
        return []
    filepath = os.path.join(MEMORY_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return []


def _save_category(category, data):
    """Save a memory category file."""
    filename = CATEGORIES.get(category)
    if not filename:
        return
    filepath = os.path.join(MEMORY_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def _ask_gemini(prompt, max_tokens=1500):
    """Use Gemini for memory analysis."""
    if not GEMINI_API_KEY:
        return None
    try:
        r = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": max_tokens},
            },
            timeout=30,
        )
        data = r.json()
        if "candidates" not in data:
            return None
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        # Try JSON parse
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        try:
            return json.loads(content.strip())
        except Exception:
            return {"text": content.strip()}
    except Exception as e:
        log(f"Gemini error: {e}")
        return None


def _ask_grok(prompt, max_tokens=1500):
    """Use Grok for memory analysis (has real-time X context)."""
    if not GROK_API_KEY:
        return None
    try:
        r = requests.post(
            GROK_URL,
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-fast-latest",
                "messages": [
                    {"role": "system", "content": "You are a trading memory analyst. Respond in JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        data = r.json()
        if "choices" not in data:
            return None
        content = data["choices"][0]["message"]["content"]
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        try:
            return json.loads(content.strip())
        except Exception:
            return {"text": content.strip()}
    except Exception as e:
        log(f"Grok error: {e}")
        return None


def remember_trade(trade_data):
    """Analyze and store a completed trade as a memory.
    Uses Gemini for pattern analysis + Grok for market context.
    """
    log(f"Remembering trade: {trade_data.get('ticker', '?')} {trade_data.get('action', '?')}")

    trade_str = json.dumps(trade_data, indent=2)

    # Gemini: pattern analysis
    gemini_analysis = _ask_gemini(f"""Analyze this completed trade and extract lessons:
{trade_str}

Respond in JSON:
{{
    "lesson": "one sentence trading lesson from this trade",
    "pattern": "the technical pattern that was present",
    "what_worked": "what went right",
    "what_failed": "what went wrong (if loss)",
    "grade": "A/B/C/D/F based on execution quality",
    "would_take_again": true/false
}}""")

    # Grok: market context at time of trade
    grok_context = _ask_grok(f"""What was the market context around this trade?
{trade_str}

Check X/Twitter for what was being discussed about {trade_data.get('ticker', '')} around that time.
Respond in JSON:
{{
    "market_mood": "bullish/bearish/neutral at time of trade",
    "x_sentiment": "what X was saying about this ticker",
    "hindsight": "with hindsight, was this a good or bad entry/exit?"
}}""")

    memory = {
        "timestamp": datetime.now().isoformat(),
        "trade": trade_data,
        "gemini_analysis": gemini_analysis or {},
        "grok_context": grok_context or {},
    }

    trades = _load_category("trades")
    trades.append(memory)
    trades = trades[-200:]  # Keep last 200
    _save_category("trades", trades)

    # If it was a mistake, also log it
    pnl = trade_data.get("pnl", 0)
    if pnl < 0 and gemini_analysis and gemini_analysis.get("grade") in ["D", "F"]:
        remember_mistake(trade_data, gemini_analysis.get("lesson", ""))

    log(f"Trade memory saved. Grade: {gemini_analysis.get('grade', '?') if gemini_analysis else '?'}")
    return memory


def remember_mistake(trade_data, lesson):
    """Store a trading mistake to avoid repeating it."""
    mistake = {
        "timestamp": datetime.now().isoformat(),
        "ticker": trade_data.get("ticker", "?"),
        "system": trade_data.get("system", "?"),
        "pnl": trade_data.get("pnl", 0),
        "lesson": lesson,
    }
    mistakes = _load_category("mistakes")
    mistakes.append(mistake)
    mistakes = mistakes[-100:]
    _save_category("mistakes", mistakes)
    log(f"Mistake logged: {lesson[:80]}")


def remember_signal(ticker, system, signal_type, score, outcome_pnl=None):
    """Track signal quality over time."""
    signal = {
        "timestamp": datetime.now().isoformat(),
        "ticker": ticker,
        "system": system,
        "signal_type": signal_type,  # "bullish_call", "bearish_put", etc.
        "score": score,
        "outcome_pnl": outcome_pnl,
    }
    signals = _load_category("signals")
    signals.append(signal)
    signals = signals[-500:]
    _save_category("signals", signals)


def remember_regime(regime, details=None):
    """Log market regime transition."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "regime": regime,
        "details": details or {},
    }
    history = _load_category("regime")
    history.append(entry)
    history = history[-100:]
    _save_category("regime", history)
    log(f"Regime logged: {regime}")


def remember_catalyst(ticker, catalyst, outcome=None):
    """Log catalyst and its market impact."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "ticker": ticker,
        "catalyst": catalyst,
        "outcome": outcome,
    }
    catalysts = _load_category("catalysts")
    catalysts.append(entry)
    catalysts = catalysts[-200:]
    _save_category("catalysts", catalysts)


def remember_sentiment(source, ticker, sentiment, price_at_time=None):
    """Log sentiment reading from X/YouTube for later accuracy tracking."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "source": source,  # "grok", "youtube", "gronk"
        "ticker": ticker,
        "sentiment": sentiment,
        "price_at_time": price_at_time,
    }
    log_data = _load_category("sentiment")
    log_data.append(entry)
    log_data = log_data[-500:]
    _save_category("sentiment", log_data)


def snapshot_context():
    """Take a market context snapshot using both Gemini and Grok."""
    log("Taking market context snapshot")

    gemini_ctx = _ask_gemini("""Give a brief market context snapshot right now.
Respond in JSON:
{
    "sp500_trend": "bullish/bearish/sideways",
    "vix_level": "low/medium/high/extreme",
    "fed_stance": "hawkish/dovish/neutral",
    "key_themes": ["list of 3-5 current market themes"],
    "risk_level": "low/medium/high"
}""")

    grok_ctx = _ask_grok("""What's the current market mood on X/Twitter right now?
Respond in JSON:
{
    "x_mood": "bullish/bearish/fearful/euphoric/neutral",
    "trending_tickers": ["top 5 tickers being discussed"],
    "key_narratives": ["what stories are driving markets"],
    "fear_greed": "extreme fear/fear/neutral/greed/extreme greed"
}""")

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "gemini": gemini_ctx or {},
        "grok": grok_ctx or {},
    }

    context = _load_category("context")
    context.append(snapshot)
    context = context[-100:]
    _save_category("context", context)

    log("Context snapshot saved")
    return snapshot


def recall(category, n=5):
    """Recall last N memories from a category."""
    data = _load_category(category)
    return data[-n:] if data else []


def recall_mistakes(n=10):
    """Recall recent mistakes to avoid repeating them."""
    return recall("mistakes", n)


def recall_for_ticker(ticker, n=10):
    """Recall all memories related to a specific ticker."""
    memories = []
    for cat in CATEGORIES:
        data = _load_category(cat)
        for entry in data:
            # Check various fields for ticker match
            if (entry.get("ticker") == ticker or
                    entry.get("trade", {}).get("ticker") == ticker or
                    ticker in str(entry)):
                memories.append({"category": cat, **entry})
    memories.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return memories[:n]


def get_memory_stats():
    """Get counts for all memory categories."""
    stats = {}
    for cat in CATEGORIES:
        data = _load_category(cat)
        stats[cat] = len(data)
    stats["total"] = sum(stats.values())
    return stats


def daily_reflection():
    """End-of-day reflection using both AI engines."""
    log("Running daily reflection")

    # Gather today's data
    trades = _load_category("trades")
    today = datetime.now().strftime("%Y-%m-%d")
    today_trades = [t for t in trades if t.get("timestamp", "").startswith(today)]

    signals = _load_category("signals")
    today_signals = [s for s in signals if s.get("timestamp", "").startswith(today)]

    summary = {
        "date": today,
        "trades_analyzed": len(today_trades),
        "signals_fired": len(today_signals),
    }

    # Gemini reflection
    gemini_ref = _ask_gemini(f"""Reflect on today's trading activity:
Trades analyzed: {len(today_trades)}
Signals fired: {len(today_signals)}

Recent mistakes to keep in mind:
{json.dumps(recall_mistakes(5), indent=2)}

Respond in JSON:
{{
    "overall_grade": "A/B/C/D/F",
    "key_takeaway": "one sentence",
    "tomorrow_focus": "what to watch for tomorrow",
    "adjust_parameters": true/false
}}""")

    summary["gemini_reflection"] = gemini_ref or {}

    # Save
    context = _load_category("context")
    context.append({"type": "daily_reflection", **summary})
    context = context[-100:]
    _save_category("context", context)

    log(f"Daily reflection complete. Grade: {gemini_ref.get('overall_grade', '?') if gemini_ref else '?'}")

    # Telegram summary
    try:
        grade = gemini_ref.get("overall_grade", "?") if gemini_ref else "?"
        takeaway = gemini_ref.get("key_takeaway", "N/A") if gemini_ref else "N/A"
        telegram.send(
            f"🧠 *Daily Reflection*\n\n"
            f"Grade: {grade}\n"
            f"Trades analyzed: {len(today_trades)}\n"
            f"Signals: {len(today_signals)}\n"
            f"Takeaway: {takeaway}"
        )
    except Exception:
        pass

    return summary


if __name__ == "__main__":
    stats = get_memory_stats()
    print(f"Memory Stats: {json.dumps(stats, indent=2)}")
    print(f"\nMemory directory: {MEMORY_DIR}")
    print(f"Categories: {', '.join(CATEGORIES.keys())}")

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "snapshot":
            snapshot_context()
        elif cmd == "reflect":
            daily_reflection()
        elif cmd == "recall" and len(sys.argv) > 2:
            ticker = sys.argv[2]
            memories = recall_for_ticker(ticker)
            print(f"\nMemories for {ticker}:")
            print(json.dumps(memories, indent=2))
        elif cmd == "mistakes":
            mistakes = recall_mistakes()
            print("\nRecent mistakes:")
            print(json.dumps(mistakes, indent=2))
