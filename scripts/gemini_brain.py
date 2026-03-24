"""
Gemini Brain — Rudy v2.0
Uses Google Gemini API for:
1. Independent regime cross-check (vs System 13) — Google Search grounded
2. Daily news digest for morning Telegram briefing — Google Search grounded
3. Backup alerting when Claude Cloud is unavailable

Google Search grounding: Gemini uses live web search for macro/news context.
PRICE RULE: BTC/MSTR prices always come from IBKR state files, NEVER from
Google Search results. Grounding is for news/macro/regulatory context only.

Writes to ~/rudy/data/gemini_analysis.json
Schedule: Daily via scheduled task or LaunchAgent.
"""
import os
import sys
import json
import requests
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DATA_DIR = os.path.expanduser("~/rudy/data")
STATE_FILE = os.path.join(DATA_DIR, "gemini_analysis.json")
LOG_FILE = os.path.expanduser("~/rudy/logs/gemini_brain.log")

# ── Gemini API (raw REST — fallback) ──
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# ── Google GenAI SDK client (grounded queries) ──
_grounded_client = None

def _init_grounded_client():
    """Initialize the google-genai SDK client for grounded queries."""
    global _grounded_client
    if _grounded_client is not None:
        return _grounded_client
    try:
        from google import genai
        _grounded_client = genai.Client(api_key=GEMINI_API_KEY)
        log("Google GenAI client initialized (Google Search grounding enabled)")
        return _grounded_client
    except Exception as e:
        log(f"google-genai SDK unavailable ({e}) — falling back to raw REST")
        return None


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def query_gemini(prompt):
    """Query Gemini via raw REST — no grounding. Used as fallback."""
    url = f"{GEMINI_BASE_URL}/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 4096
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        log(f"Gemini API error: {e}")
        return None


def query_gemini_grounded(prompt, log_sources=True):
    """Query Gemini with live Google Search grounding.

    Use for: news/macro/regulatory context, regime analysis.
    Do NOT use for prices — BTC/MSTR prices always come from IBKR state files.

    Falls back to raw REST if google-genai SDK unavailable.
    """
    client = _init_grounded_client()
    if client is None:
        log("Grounded client unavailable — falling back to ungrounded query")
        return query_gemini(prompt)

    try:
        from google.genai import types
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[grounding_tool],
                temperature=0.3,
                max_output_tokens=4096,
            )
        )

        # Log sources used by Google Search
        if log_sources:
            try:
                meta = response.candidates[0].grounding_metadata
                if meta and meta.grounding_chunks:
                    sources = [c.web.uri for c in meta.grounding_chunks if hasattr(c, 'web') and c.web]
                    if sources:
                        log(f"Grounding sources ({len(sources)}): {', '.join(sources[:3])}")
            except Exception:
                pass

        return response.text

    except Exception as e:
        log(f"Grounded query error ({e}) — falling back to raw REST")
        return query_gemini(prompt)


def regime_crosscheck():
    """Independent regime classification — compare with System 13."""
    # Load current System 13 state
    regime_file = os.path.join(DATA_DIR, "regime_state.json")
    s13 = {}
    if os.path.exists(regime_file):
        try:
            with open(regime_file) as f:
                s13 = json.load(f)
        except Exception:
            pass

    # Load trader state for live data
    trader_file = os.path.join(DATA_DIR, "trader_v28_state.json")
    trader = {}
    if os.path.exists(trader_file):
        try:
            with open(trader_file) as f:
                trader = json.load(f)
        except Exception:
            pass

    btc_price = trader.get("last_btc_price", 0)
    mstr_price = trader.get("last_mstr_price", 0)
    premium = trader.get("last_premium", 0)
    stoch_rsi = trader.get("last_stoch_rsi", 0)
    s13_regime = s13.get("current_regime", "UNKNOWN")
    s13_confidence = s13.get("confidence", 0)

    prompt = f"""You are a Bitcoin market cycle analyst. Based on these current data points, classify the BTC market regime.

Current Data (March 2026):
- BTC Price: ${btc_price:,.0f}
- BTC All-Time High: $126,200 (October 2025)
- Drawdown from ATH: ~{((126200 - btc_price) / 126200 * 100):.1f}%
- MSTR Price: ${mstr_price:.2f}
- mNAV Premium: {premium:.2f}x
- StochRSI (weekly): {stoch_rsi:.0f}
- Last BTC halving: April 2024 (~23 months ago)
- 200W SMA: ~$59,433
- 250W MA: ~$56,000

Classify into ONE of these 4 regimes:
- ACCUMULATION: Post-capitulation, smart money buying, low sentiment
- MARKUP: Clear uptrend confirmed, momentum building
- DISTRIBUTION: Post-peak, profit-taking, weakening rallies
- MARKDOWN: Active downtrend, capitulation risk, fear dominant

Respond as JSON only:
{{"regime": "X", "confidence": N, "reasoning": "1-2 sentences", "btc_outlook_30d": "brief", "key_risk": "brief", "key_opportunity": "brief"}}"""

    log("Running Gemini regime cross-check...")
    raw = query_gemini_grounded(prompt)
    if not raw:
        return None

    try:
        import re
        cleaned = raw.strip()
        # Try multiple extraction methods
        # Method 1: regex for ```json ... ```
        match = re.search(r'```(?:json)?\s*\n(.*?)\n```', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
        # Method 2: find first { to last }
        elif '{' in cleaned:
            start = cleaned.index('{')
            end = cleaned.rindex('}') + 1
            cleaned = cleaned[start:end]
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        log(f"Failed to parse Gemini response ({e}): {raw[:300]}")
        return None

    data["timestamp"] = datetime.now().isoformat()
    data["source"] = "gemini"
    data["model"] = "gemini-2.5-flash"

    # Compare with System 13
    data["system13_regime"] = s13_regime
    data["system13_confidence"] = s13_confidence
    data["consensus"] = data.get("regime", "") == s13_regime

    return data


def news_digest():
    """Generate morning news digest for Telegram."""
    # Load trader state
    trader_file = os.path.join(DATA_DIR, "trader_v28_state.json")
    trader = {}
    if os.path.exists(trader_file):
        try:
            with open(trader_file) as f:
                trader = json.load(f)
        except Exception:
            pass

    btc_price = trader.get("last_btc_price", 0)

    prompt = f"""As a concise market analyst, provide a 3-bullet morning briefing for a Bitcoin/MSTR investor.

Current context: BTC is at ${btc_price:,.0f}, down ~45% from ATH of $126,200 (Oct 2025). We are ~23 months post-halving. MSTR holds ~500K+ BTC on its balance sheet.

Focus on:
1. What happened overnight in crypto/macro (any major moves, news, Fed, regulatory)
2. Key level to watch today for BTC
3. One sentence on risk or opportunity today

Format: 3 bullet points, each 1-2 sentences max. No headers, no fluff. Start each bullet with an emoji."""

    log("Generating Gemini news digest...")
    raw = query_gemini_grounded(prompt)
    if not raw:
        return None

    return {
        "digest": raw.strip(),
        "timestamp": datetime.now().isoformat(),
        "source": "gemini",
        "btc_at_time": btc_price
    }


def save_state(regime_data, digest_data):
    """Save analysis results."""
    state = {
        "regime_crosscheck": regime_data,
        "news_digest": digest_data,
        "last_updated": datetime.now().isoformat()
    }

    # Preserve history
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                old = json.load(f)
            history = old.get("regime_history", [])
        except Exception:
            history = []
    else:
        history = []

    if regime_data:
        history.append({
            "regime": regime_data.get("regime", ""),
            "confidence": regime_data.get("confidence", 0),
            "consensus": regime_data.get("consensus", False),
            "timestamp": regime_data.get("timestamp", "")
        })
    history = history[-30:]  # 30 days
    state["regime_history"] = history

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    log("Saved Gemini analysis")


def send_alerts(regime_data, digest_data):
    """Send Telegram alerts."""
    messages = []

    # Morning digest
    if digest_data and digest_data.get("digest"):
        messages.append(
            f"🧠 *Gemini Morning Brief*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{digest_data['digest']}"
        )

    # Regime consensus check
    if regime_data:
        gemini_regime = regime_data.get("regime", "?")
        s13_regime = regime_data.get("system13_regime", "?")
        consensus = regime_data.get("consensus", False)
        confidence = regime_data.get("confidence", 0)

        if consensus:
            messages.append(
                f"✅ *Regime Consensus: {gemini_regime}*\n"
                f"System 13: {s13_regime} | Gemini: {gemini_regime} ({confidence}%)\n"
                f"Both brains agree."
            )
        else:
            # DISAGREEMENT — important alert
            messages.append(
                f"⚠️ *REGIME DISAGREEMENT*\n"
                f"System 13: *{s13_regime}*\n"
                f"Gemini: *{gemini_regime}* ({confidence}%)\n"
                f"Reason: {regime_data.get('reasoning', 'N/A')}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Review manually — models disagree on cycle phase."
            )

        # Key risk/opportunity
        risk = regime_data.get("key_risk", "")
        opp = regime_data.get("key_opportunity", "")
        if risk or opp:
            messages.append(
                f"📊 *Gemini Outlook*\n"
                f"30d: {regime_data.get('btc_outlook_30d', 'N/A')}\n"
                f"Risk: {risk}\n"
                f"Opportunity: {opp}"
            )

    for msg in messages:
        telegram.send(msg)
        log(f"Telegram sent: {msg[:60]}...")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Gemini Brain — Rudy v2.0")
    parser.add_argument("--regime-only", action="store_true", help="Only run regime cross-check")
    parser.add_argument("--digest-only", action="store_true", help="Only run news digest")
    parser.add_argument("--silent", action="store_true", help="Don't send Telegram alerts")
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        log("ERROR: GEMINI_API_KEY not set in ~/.agent_zero_env")
        sys.exit(1)

    regime_data = None
    digest_data = None

    if not args.digest_only:
        regime_data = regime_crosscheck()
        if regime_data:
            log(
                f"Regime: {regime_data.get('regime', '?')} ({regime_data.get('confidence', '?')}%) | "
                f"S13: {regime_data.get('system13_regime', '?')} | "
                f"Consensus: {'YES' if regime_data.get('consensus') else 'NO'}"
            )

    if not args.regime_only:
        digest_data = news_digest()
        if digest_data:
            log(f"Digest generated ({len(digest_data.get('digest', ''))} chars)")

    save_state(regime_data, digest_data)

    if not args.silent:
        send_alerts(regime_data, digest_data)

    log("Gemini Brain complete")


if __name__ == "__main__":
    main()
