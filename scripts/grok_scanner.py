"""Grok Scanner — Real-time X/Twitter Intelligence via xAI Grok
Grok has native access to X/Twitter data, providing real-time market intelligence
without needing Tavily as a middleman.
Part of Rudy v2.0 Trading System — Constitution v40.0
"""
import os
import sys
import json
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram

# Load env vars from ~/.agent_zero_env if not already set (under launchctl,
# the user's shell env is NOT inherited, so GROK_API_KEY would otherwise be empty)
_env_file = os.path.expanduser("~/.agent_zero_env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
GROK_INTEL_FILE = os.path.join(DATA_DIR, "grok_intel.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_URL = "https://api.x.ai/v1/chat/completions"
GROK_BASE_URL = "https://api.x.ai/v1"
GROK_MODEL = "grok-3-fast-latest"

# ── OpenAI-compat SDK client (grounded queries with live_search) ──
_grounded_client = None


def _init_grounded_client():
    """Initialize OpenAI-compat client pointing at xAI for live_search grounding."""
    global _grounded_client
    if _grounded_client is not None:
        return _grounded_client
    try:
        from openai import OpenAI
        _grounded_client = OpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL)
        log("xAI OpenAI-compat client initialized (live_search grounding enabled)")
        return _grounded_client
    except Exception as e:
        log(f"OpenAI SDK unavailable ({e}) — falling back to raw REST")
        return None

WATCHLIST = {
    "v28_core": ["MSTR", "BTC", "Bitcoin", "MicroStrategy"],  # Primary: v2.8+ cycle-low LEAP
    "trader2_hedge": ["MSTR", "SPY"],                          # Put ladder positions
    "macro": ["DXY", "GLD", "TLT", "VIX"],                    # Macro context
    "btc_proxies": ["IBIT", "GBTC", "MARA", "RIOT", "CLSK"], # BTC ecosystem
}

INFLUENCERS = [
    "nolimitgains", "honeydripnetwor", "aristotlegrowth", "unusual_whales",
    "DeItaone", "jimcramer", "michaeljburry", "CathieDWood", "optionsflow",
    "TikTokInvestors", "WallStreetBets", "Mr_Derivatives", "gabortrading",
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Grok {ts}] {msg}")
    with open(f"{LOG_DIR}/grok.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def ask_grok(system_prompt, user_prompt, max_tokens=3000):
    """Call the xAI Grok API. Returns parsed JSON or None."""
    if not GROK_API_KEY:
        log("No GROK_API_KEY set")
        return None

    try:
        r = requests.post(
            GROK_URL,
            headers={
                "Authorization": f"Bearer {GROK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        data = r.json()
        if "choices" not in data:
            log(f"Grok API error: {data.get('error', data)}")
            return None

        content = data["choices"][0]["message"]["content"]
        log("Grok responded")

        # Extract JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        cleaned = content.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start:end])
                except:
                    pass
            log("Could not parse JSON, returning raw text")
            return {"raw_text": cleaned}

    except Exception as e:
        log(f"Grok API error: {e}")
        return None


def ask_grok_grounded(system_prompt, user_prompt, max_tokens=3000):
    """Call xAI Grok with live web_search tool via OpenAI-compat SDK.

    Same return contract as ask_grok() — returns parsed JSON dict or None.
    Falls back to ask_grok() if SDK unavailable or response can't be parsed.
    """
    client = _init_grounded_client()
    if client is None:
        log("Grounded client unavailable — falling back to raw REST")
        return ask_grok(system_prompt, user_prompt, max_tokens)

    try:
        response = client.chat.completions.create(
            model=GROK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=[{"type": "live_search"}],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        if content is None:
            log("Grounded response content is None (tool_call path) — falling back to raw REST")
            return ask_grok(system_prompt, user_prompt, max_tokens)

        log("Grok grounded response received")

        # Extract JSON (same logic as ask_grok)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        cleaned = content.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start:end])
                except Exception:
                    pass
            log("Could not parse grounded JSON — falling back to raw REST")
            return ask_grok(system_prompt, user_prompt, max_tokens)

    except Exception as e:
        log(f"Grounded query error ({e}) — falling back to raw REST")
        return ask_grok(system_prompt, user_prompt, max_tokens)


def scan_realtime(watchlist=None):
    """Full real-time X/Twitter scan via Grok's built-in access."""
    log("=" * 50)
    log("Starting Grok real-time X scan")

    wl = watchlist or WATCHLIST

    # Build flat ticker list for the prompt
    all_tickers = []
    for system, tickers in wl.items():
        all_tickers.extend(tickers)
    ticker_str = ", ".join(all_tickers)
    influencer_str = ", ".join(f"@{h}" for h in INFLUENCERS)

    # Build watchlist context
    wl_context = "\n".join(
        f"- {sys}: {', '.join(tks)}" for sys, tks in wl.items()
    )

    system_prompt = (
        "You are Grok, a real-time financial intelligence analyst with native access to X/Twitter. "
        "Always respond with valid JSON. Be specific — cite actual posts, accounts, and data points."
    )

    today = datetime.now().strftime("%B %d, %Y")
    user_prompt = f"""Today is {today}. You have real-time access to X/Twitter. Scan for the latest posts and chatter about these tickers:
{ticker_str}

Our watchlist by trading system:
{wl_context}

Also check for recent posts from these accounts: {influencer_str}

Look for:
- Unusual options activity mentions
- Whale moves (large block trades, 13F filings, insider buys/sells)
- Breaking catalysts (earnings surprises, FDA decisions, contracts, partnerships)
- Sentiment shifts (sudden bullish/bearish turns)
- Short squeeze chatter (high short interest, borrow rate spikes)
- Earnings whispers (pre-announcement leaks, guidance rumors)
- Insider activity (Form 4 filings, CEO buying/selling)
- Macro signals (Fed commentary, CPI/jobs data reactions, yield curve)
- **10X POTENTIAL STOCKS**: Scan for small/mid cap stocks that people are calling potential 10-baggers. Look for: eVTOL (JOBY, ACHR, LILM), quantum computing (IONQ, RGTI, QUBT), nuclear/SMR (SMR, OKLO), space (RKLB, LUNR, ASTS), and any other tickers X users are hyping as multi-baggers. We want early-stage high-conviction plays.

Respond in this exact JSON format:
{{
    "summary": "3-5 sentence overview of what X is buzzing about right now",
    "overall_sentiment": "bullish/bearish/neutral/mixed",
    "signals": [
        {{
            "ticker": "SYMBOL",
            "signal": "buy/sell/watch",
            "confidence": "high/medium/low",
            "reason": "specific explanation citing posts or data",
            "source_account": "@handle or 'multiple' or 'general chatter'"
        }}
    ],
    "hot_tickers": ["tickers getting the most X attention right now"],
    "catalysts": ["specific upcoming catalysts mentioned on X"],
    "risks": ["specific risks or bearish signals being discussed"],
    "ten_bagger_picks": [
        {{
            "ticker": "SYMBOL",
            "sector": "eVTOL/quantum/nuclear/space/AI/biotech/other",
            "bull_case": "why X thinks this could 10x",
            "current_hype_level": "high/medium/low",
            "key_catalyst": "what could trigger the move",
            "source_accounts": ["@handles talking about it"]
        }}
    ],
    "influencer_alerts": [
        {{
            "handle": "@account",
            "summary": "what they posted recently about stocks/trading",
            "tickers_mentioned": ["SYMBOL"],
            "sentiment": "bullish/bearish/neutral"
        }}
    ],
    "viral_posts": [
        {{
            "handle": "@account",
            "post_summary": "what they said (quote key parts)",
            "tickers": ["SYMBOL"],
            "engagement": "high/medium (estimate likes/retweets if visible)",
            "trading_relevance": "why this matters for trading",
            "url_hint": "the post URL if you can determine it"
        }}
    ]
}}

IMPORTANT: Surface specific VIRAL POSTS — high-engagement tweets about stocks, options plays, trade ideas, earnings reactions. We want to see the actual posts people are sharing, not just summaries. Prioritize posts from our influencer list: {influencer_str}. Include posts with specific trade setups, unusual options flow screenshots, or breaking stock news. Do not fabricate posts or accounts."""

    result = ask_grok_grounded(system_prompt, user_prompt)
    if not result:
        log("Grok scan failed — no response")
        return None

    # Ensure required fields
    result.setdefault("summary", "")
    result.setdefault("overall_sentiment", "neutral")
    result.setdefault("signals", [])
    result.setdefault("hot_tickers", [])
    result.setdefault("catalysts", [])
    result.setdefault("risks", [])
    result.setdefault("influencer_alerts", [])
    result.setdefault("viral_posts", [])

    # Add metadata
    result["timestamp"] = datetime.now().isoformat()
    result["scanner"] = "grok"

    # Save intel
    _save_intel(result)

    # Send Telegram alert
    alert = format_alert(result)
    log(alert)
    try:
        telegram.send(alert)
    except:
        pass

    log("Grok scan complete")
    log("=" * 50)
    return result


def quick_scan(ticker):
    """Quick scan for a single ticker via Grok's real-time X access."""
    log(f"Quick scan: {ticker}")

    system_prompt = (
        "You are Grok, a real-time financial intelligence analyst with native access to X/Twitter. "
        "Always respond with valid JSON."
    )

    user_prompt = f"""Check real-time X/Twitter chatter for ${ticker} right now.

Look for: price action discussion, options flow, analyst upgrades/downgrades, insider activity,
earnings whispers, short squeeze potential, breaking news, and sentiment from key accounts.

Respond in this exact JSON format:
{{
    "ticker": "{ticker}",
    "summary": "2-3 sentence overview of current X chatter",
    "sentiment": "bullish/bearish/neutral/mixed",
    "signals": [
        {{
            "signal": "buy/sell/watch",
            "confidence": "high/medium/low",
            "reason": "specific explanation",
            "source_account": "@handle or 'general chatter'"
        }}
    ],
    "key_posts": ["notable posts or takes about this ticker"],
    "catalysts": ["upcoming catalysts"],
    "risks": ["risks being discussed"]
}}

Only include real evidence from X. Do not fabricate."""

    result = ask_grok_grounded(system_prompt, user_prompt, max_tokens=1500)
    if not result:
        return f"Grok scan failed for {ticker} — check API key"

    result.setdefault("ticker", ticker)
    result.setdefault("summary", "No data")
    result.setdefault("sentiment", "neutral")
    result.setdefault("signals", [])

    # Save to intel history
    intel = {
        "timestamp": datetime.now().isoformat(),
        "scanner": "grok",
        "type": "quick_scan",
        "ticker": ticker,
        "overall_sentiment": result.get("sentiment", "neutral"),
        "summary": result.get("summary", ""),
        "signals": result.get("signals", []),
        "catalysts": result.get("catalysts", []),
        "risks": result.get("risks", []),
        "hot_tickers": [ticker],
        "influencer_alerts": [],
    }
    _save_intel(intel)

    # Format output
    lines = [
        f"GROK SCAN: ${ticker}",
        f"Sentiment: {result['sentiment'].upper()}",
        "",
        result["summary"],
    ]

    for s in result.get("signals", []):
        lines.append(f"  {s.get('signal', '?').upper()} ({s.get('confidence', '?')}) — {s.get('reason', '')[:100]}")

    if result.get("catalysts"):
        lines.append(f"\nCatalysts: {', '.join(result['catalysts'][:5])}")
    if result.get("risks"):
        lines.append(f"Risks: {', '.join(result['risks'][:3])}")

    alert = "\n".join(lines)
    try:
        telegram.send(alert)
    except:
        pass

    return alert


def scan_influencer(handle):
    """Check what a specific X account has been posting about stocks/trading."""
    log(f"Influencer scan: @{handle}")

    system_prompt = (
        "You are Grok, a real-time financial intelligence analyst with native access to X/Twitter. "
        "Always respond with valid JSON."
    )

    user_prompt = f"""Check the recent posts from @{handle} on X/Twitter.

Focus on anything related to stocks, options, trading, markets, crypto, or economic data.

Respond in this exact JSON format:
{{
    "handle": "@{handle}",
    "recent_takes": [
        {{
            "summary": "what they said",
            "tickers_mentioned": ["SYMBOL"],
            "sentiment": "bullish/bearish/neutral",
            "importance": "high/medium/low"
        }}
    ],
    "overall_stance": "bullish/bearish/neutral/mixed",
    "notable_calls": ["any specific trade ideas or price targets they shared"]
}}

Only include real posts. Do not fabricate."""

    result = ask_grok_grounded(system_prompt, user_prompt, max_tokens=1500)
    if not result:
        return f"Grok scan failed for @{handle} — check API key"

    result.setdefault("handle", f"@{handle}")
    result.setdefault("recent_takes", [])
    result.setdefault("overall_stance", "neutral")

    # Format output
    lines = [
        f"INFLUENCER SCAN: @{handle}",
        f"Stance: {result['overall_stance'].upper()}",
        "",
    ]

    for take in result.get("recent_takes", []):
        tickers = ", ".join(take.get("tickers_mentioned", []))
        lines.append(f"  [{take.get('importance', '?').upper()}] {take.get('summary', '')[:150]}")
        if tickers:
            lines.append(f"    Tickers: {tickers}")

    if result.get("notable_calls"):
        lines.append(f"\nNotable calls: {'; '.join(result['notable_calls'][:5])}")

    return "\n".join(lines)


def format_alert(intel):
    """Format Grok intelligence for Telegram alert."""
    lines = [
        "GROK X INTELLIGENCE REPORT",
        f"Sentiment: {intel.get('overall_sentiment', 'N/A').upper()}",
        "",
        intel.get("summary", "")[:400],
        "",
    ]

    # High confidence signals
    high_signals = [s for s in intel.get("signals", []) if s.get("confidence") == "high"]
    if high_signals:
        lines.append("HIGH CONFIDENCE SIGNALS:")
        for s in high_signals[:5]:
            src = s.get("source_account", "")
            lines.append(f"  {s['ticker']} -> {s['signal'].upper()} ({src})")
            lines.append(f"    {s.get('reason', '')[:120]}")

    # Medium signals
    med_signals = [s for s in intel.get("signals", []) if s.get("confidence") == "medium"]
    if med_signals:
        lines.append("\nMEDIUM SIGNALS:")
        for s in med_signals[:5]:
            lines.append(f"  {s['ticker']} -> {s['signal'].upper()} — {s.get('reason', '')[:80]}")

    # Hot tickers
    if intel.get("hot_tickers"):
        lines.append(f"\nHot: {', '.join(intel['hot_tickers'][:10])}")

    # Catalysts
    if intel.get("catalysts"):
        lines.append(f"\nCatalysts: {', '.join(intel['catalysts'][:5])}")

    # Risks
    if intel.get("risks"):
        lines.append(f"\nRisks: {', '.join(intel['risks'][:3])}")

    # Influencer alerts
    if intel.get("influencer_alerts"):
        lines.append("\nINFLUENCER ALERTS:")
        for ia in intel["influencer_alerts"][:6]:
            tickers = ", ".join(ia.get("tickers_mentioned", []))
            lines.append(f"  {ia.get('handle', '?')} ({ia.get('sentiment', '?')}): {ia.get('summary', '')[:100]}")
            if tickers:
                lines.append(f"    Tickers: {tickers}")

    return "\n".join(lines)


def get_latest_intel():
    """Read the latest Grok intel from file."""
    if not os.path.exists(GROK_INTEL_FILE):
        return None
    try:
        with open(GROK_INTEL_FILE) as f:
            history = json.load(f)
        return history[-1] if history else None
    except:
        return None


def _save_intel(intel):
    """Save intelligence report to history file (keep last 50)."""
    history = []
    if os.path.exists(GROK_INTEL_FILE):
        try:
            with open(GROK_INTEL_FILE) as f:
                history = json.load(f)
        except:
            history = []

    history.append(intel)
    history = history[-50:]

    with open(GROK_INTEL_FILE, "w") as f:
        json.dump(history, f, indent=2)
    log(f"Intel saved to {GROK_INTEL_FILE}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = quick_scan(sys.argv[1])
        print(result)
    else:
        scan_realtime()
