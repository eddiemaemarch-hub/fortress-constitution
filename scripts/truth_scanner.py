"""Truth Social Scanner — Trump Post Intelligence for Rudy v2.0
Monitors President Trump's Truth Social posts for market-moving content.
Scans for: tariff announcements, trade deals, company mentions, policy shifts,
crypto/Bitcoin commentary, Fed criticism, sector-specific impacts.
Uses: CNN archive (updates every 5 min) + Grok (real-time X reaction) + Gemini (analysis).
Part of Rudy v2.0 Trading System — Constitution v42.0
"""
import os
import sys
import json
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import telegram

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
TRUTH_INTEL_FILE = os.path.join(DATA_DIR, "truth_intel.json")
LAST_POST_FILE = os.path.join(DATA_DIR, "truth_last_seen.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# CNN-hosted Trump Truth Social archive (updates every 5 min)
TRUTH_ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_URL = "https://api.x.ai/v1/chat/completions"

# Market-moving keywords to flag
MARKET_KEYWORDS = [
    # Tariffs & Trade
    "tariff", "tariffs", "trade", "trade deal", "trade war", "import", "export",
    "china", "eu", "europe", "mexico", "canada", "japan",
    # Sectors
    "oil", "energy", "drill", "gas", "coal", "nuclear", "solar",
    "tech", "big tech", "apple", "google", "amazon", "microsoft", "meta",
    "bank", "banking", "wall street", "fed", "federal reserve", "interest rate",
    "crypto", "bitcoin", "btc", "digital", "cbdc",
    "pharma", "drug", "fda", "health",
    "auto", "car", "ev", "electric vehicle",
    "defense", "military", "pentagon", "lockheed", "boeing",
    "space", "spacex", "nasa", "starlink",
    # Market signals
    "stock", "market", "dow", "s&p", "nasdaq", "rally", "crash",
    "regulation", "deregulation", "executive order",
    "tax", "taxes", "tax cut",
    "sanctions", "ban", "restrict",
    "deal", "agreement", "partnership",
    # Companies Trump mentions
    "truth social", "djt", "tmtg",
]

# Hours to look back for posts
LOOKBACK_HOURS = 24


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Truth {ts}] {msg}")
    with open(f"{LOG_DIR}/truth.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def fetch_truth_archive():
    """Fetch Trump's recent Truth Social posts from CNN archive."""
    try:
        r = requests.get(TRUTH_ARCHIVE_URL, timeout=15)
        if r.status_code != 200:
            log(f"Archive fetch failed: {r.status_code}")
            return []

        posts = r.json()
        if not isinstance(posts, list):
            log("Unexpected archive format")
            return []

        # Filter to recent posts
        cutoff = datetime.utcnow() - timedelta(hours=LOOKBACK_HOURS)
        recent = []
        for post in posts:
            try:
                created = post.get("created_at", "")
                if not created:
                    continue
                # Parse ISO format
                post_time = datetime.fromisoformat(created.replace("Z", "+00:00").replace("+00:00", ""))
                if post_time > cutoff:
                    recent.append({
                        "id": post.get("id", ""),
                        "created_at": created,
                        "content": post.get("content", ""),
                        "replies": post.get("replies_count", 0),
                        "reblogs": post.get("reblogs_count", 0),
                        "favorites": post.get("favourites_count", 0),
                    })
            except Exception:
                continue

        log(f"Fetched {len(recent)} posts from last {LOOKBACK_HOURS}h (total archive: {len(posts)})")
        return recent

    except Exception as e:
        log(f"Archive fetch error: {e}")
        return []


def tavily_truth_search():
    """Fallback: search for Trump Truth Social posts via Tavily."""
    if not TAVILY_API_KEY:
        return []

    queries = [
        "Trump Truth Social post today stock market",
        "Trump Truth Social tariff announcement",
        "Trump Truth Social latest post",
    ]

    all_results = []
    for query in queries:
        try:
            r = requests.post(TAVILY_URL, json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": 5,
                "search_depth": "basic",
            }, timeout=15)
            data = r.json()
            for item in data.get("results", []):
                all_results.append({
                    "title": item.get("title", ""),
                    "content": item.get("content", "")[:500],
                    "url": item.get("url", ""),
                })
        except Exception:
            continue

    return all_results


def filter_market_posts(posts):
    """Filter posts that contain market-moving keywords."""
    market_posts = []
    for post in posts:
        content_lower = post.get("content", "").lower()
        # Strip HTML tags
        import re
        content_clean = re.sub(r"<[^>]+>", "", content_lower)
        matched_keywords = [kw for kw in MARKET_KEYWORDS if kw in content_clean]
        if matched_keywords:
            post["matched_keywords"] = matched_keywords
            post["content_clean"] = re.sub(r"<[^>]+>", "", post.get("content", ""))
            market_posts.append(post)
    return market_posts


def ask_gemini(prompt, max_tokens=2000):
    """Use Gemini for post analysis."""
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
            timeout=60,
        )
        data = r.json()
        if "candidates" not in data:
            return None
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        try:
            return json.loads(content.strip())
        except Exception:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start:end])
                except Exception:
                    pass
            return {"raw_text": content.strip()}
    except Exception as e:
        log(f"Gemini error: {e}")
        return None


def ask_grok(prompt, max_tokens=2000):
    """Use Grok for real-time X reaction to Trump posts."""
    if not GROK_API_KEY:
        return None
    try:
        r = requests.post(
            GROK_URL,
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-fast-latest",
                "messages": [
                    {"role": "system", "content": "You are a financial analyst tracking how Trump's Truth Social posts move markets. You have real-time X/Twitter access. Respond in JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
            timeout=60,
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
            return {"raw_text": content.strip()}
    except Exception as e:
        log(f"Grok error: {e}")
        return None


def scan_truth():
    """Full Truth Social scan for market-moving Trump posts."""
    log("=" * 50)
    log("Starting Truth Social scan")

    # Fetch posts from archive
    posts = fetch_truth_archive()

    # Fallback to Tavily if archive fails
    tavily_results = []
    if not posts:
        log("Archive empty — falling back to Tavily")
        tavily_results = tavily_truth_search()

    # Filter for market-moving content
    market_posts = filter_market_posts(posts) if posts else []
    log(f"Market-relevant posts: {len(market_posts)} of {len(posts)}")

    # Check for new posts since last scan
    last_seen = _load_last_seen()
    new_posts = [p for p in market_posts if p.get("id") and p["id"] != last_seen]
    if market_posts:
        _save_last_seen(market_posts[0].get("id", ""))

    # Build content for AI analysis
    if market_posts:
        posts_text = "\n\n".join(
            f"[{p.get('created_at', '?')}] (replies:{p.get('replies',0)} reblogs:{p.get('reblogs',0)} likes:{p.get('favorites',0)})\n"
            f"Keywords: {', '.join(p.get('matched_keywords', []))}\n"
            f"{p.get('content_clean', '')[:500]}"
            for p in market_posts[:15]
        )
    elif tavily_results:
        posts_text = "\n\n".join(
            f"[{r['title']}]\n{r['content']}"
            for r in tavily_results[:10]
        )
    else:
        log("No market-moving posts found")
        result = {
            "timestamp": datetime.now().isoformat(),
            "scanner": "truth_social",
            "summary": "No market-moving Trump posts in the last 24 hours.",
            "overall_impact": "neutral",
            "signals": [],
            "posts_scanned": len(posts),
            "market_posts": 0,
        }
        _save_intel(result)
        return result

    # Gemini: analyze posts for trading signals
    gemini_result = ask_gemini(f"""Analyze these recent Truth Social posts from President Trump for trading signals.
Focus on: tariff changes, trade deals, company mentions, sector impacts, policy shifts, crypto commentary.

Posts:
{posts_text}

Our trading systems cover: MSTR/IBIT (Bitcoin), energy (CCJ,UEC,XOM,CVX,OXY), metals (GLD,SLV,NEM),
space (RKLB,LUNR,ASTS), 10X stocks (JOBY,IONQ,SMR,OKLO), defense (LMT,NOC,RTX).

Respond in JSON:
{{
    "summary": "3-5 sentence overview of Trump's recent market-moving posts",
    "overall_impact": "bullish/bearish/neutral/mixed",
    "key_posts": [
        {{
            "content_summary": "what Trump said",
            "market_impact": "bullish/bearish/neutral",
            "impact_magnitude": "high/medium/low",
            "affected_sectors": ["sectors impacted"],
            "affected_tickers": ["specific tickers"],
            "recommended_action": "what to do about it"
        }}
    ],
    "signals": [
        {{
            "ticker": "SYMBOL",
            "signal": "buy/sell/watch",
            "confidence": "high/medium/low",
            "reason": "why this signal based on Trump's post"
        }}
    ],
    "tariff_update": {{
        "new_tariffs": true/false,
        "details": "what changed",
        "winners": ["tickers that benefit"],
        "losers": ["tickers that suffer"]
    }},
    "sectors_impacted": ["list of sectors affected"],
    "urgency": "immediate/today/this_week/background"
}}""")

    # Grok: real-time X reaction to Trump's posts
    grok_result = ask_grok(f"""Check X/Twitter RIGHT NOW for reactions to Trump's latest Truth Social posts.

Trump's recent market-relevant posts:
{posts_text[:2000]}

What is X saying about these posts? How are traders reacting?
Are futures moving? Any immediate market impact being discussed?

Respond in JSON:
{{
    "x_reaction": "bullish/bearish/panic/euphoric/neutral",
    "trader_sentiment": "what traders on X are saying",
    "futures_impact": "are futures/pre-market moving on this?",
    "key_x_posts": [
        {{
            "handle": "@account",
            "reaction": "what they said about Trump's post",
            "ticker_mentioned": "SYMBOL or null"
        }}
    ],
    "consensus_trade": "what X thinks the smart trade is right now",
    "contrarian_view": "any notable contrarian takes"
}}""")

    # Build result
    if not gemini_result:
        gemini_result = {}

    result = gemini_result
    result.setdefault("summary", "")
    result.setdefault("overall_impact", "neutral")
    result.setdefault("key_posts", [])
    result.setdefault("signals", [])
    result.setdefault("tariff_update", {})
    result.setdefault("sectors_impacted", [])
    result.setdefault("urgency", "background")
    result["x_reaction"] = grok_result or {}
    result["timestamp"] = datetime.now().isoformat()
    result["scanner"] = "truth_social"
    result["posts_scanned"] = len(posts)
    result["market_posts"] = len(market_posts)
    result["new_posts"] = len(new_posts)

    _save_intel(result)

    # Telegram alert — only if urgent or high-impact
    alert = format_alert(result)
    log(alert)
    urgency = result.get("urgency", "background")
    high_impact = any(p.get("impact_magnitude") == "high" for p in result.get("key_posts", []))

    if urgency in ("immediate", "today") or high_impact or new_posts:
        try:
            telegram.send(alert)
        except Exception:
            pass

    log("Truth Social scan complete")
    log("=" * 50)
    return result


def quick_scan(topic=None):
    """Quick scan Truth Social for a specific topic via Grok."""
    log(f"Quick scan: {topic or 'latest'}")

    prompt = f"""Check real-time X/Twitter and your knowledge for the latest Truth Social posts from Trump{' about ' + topic if topic else ''}.

Look for: market-moving statements, tariff announcements, policy changes, economic commentary, trade war escalation, and anything that could affect stock prices.

Return a concise 3-5 sentence summary of the most important recent posts, their market impact, and what traders should watch for. Include specific tickers if mentioned."""

    result = ask_grok(prompt)
    if not result:
        return f"No Truth Social posts found{' about ' + topic if topic else ''}"

    # ask_grok returns dict or None — extract readable text
    if isinstance(result, dict):
        data = result.get("data", result)
        if isinstance(data, dict):
            text = data.get("summary", "") or data.get("raw_text", "") or data.get("analysis", "")
            if not text:
                # Fallback: join all string values
                text = ". ".join(str(v) for v in data.values() if isinstance(v, str) and len(str(v)) > 10)
        else:
            text = str(data)
    else:
        text = str(result)

    label = f"TRUTH SOCIAL{': ' + topic.upper() if topic else ''}"
    return f"{label}\n{text[:500]}"


# Alias for dashboard API
search_topic = quick_scan


def format_alert(intel):
    """Format Truth Social intelligence for Telegram."""
    lines = [
        "TRUTH SOCIAL INTELLIGENCE",
        f"Impact: {intel.get('overall_impact', 'N/A').upper()}",
        f"Urgency: {intel.get('urgency', 'N/A').upper()}",
        f"Posts: {intel.get('market_posts', 0)} market-relevant / {intel.get('posts_scanned', 0)} total",
        "",
        intel.get("summary", "")[:400],
        "",
    ]

    # High-impact posts
    high_posts = [p for p in intel.get("key_posts", []) if p.get("impact_magnitude") == "high"]
    if high_posts:
        lines.append("HIGH IMPACT POSTS:")
        for p in high_posts[:3]:
            lines.append(f"  [{p.get('market_impact', '?').upper()}] {p.get('content_summary', '')[:150]}")
            if p.get("affected_tickers"):
                lines.append(f"    Tickers: {', '.join(p['affected_tickers'][:8])}")
            if p.get("recommended_action"):
                lines.append(f"    Action: {p['recommended_action'][:100]}")

    # Signals
    signals = intel.get("signals", [])
    high_sigs = [s for s in signals if s.get("confidence") == "high"]
    if high_sigs:
        lines.append("\nTRADING SIGNALS:")
        for s in high_sigs[:5]:
            lines.append(f"  {s['ticker']} -> {s['signal'].upper()} — {s.get('reason', '')[:100]}")

    # Tariff update
    tariff = intel.get("tariff_update", {})
    if tariff.get("new_tariffs"):
        lines.append(f"\nTARIFF ALERT: {tariff.get('details', 'New tariff action')[:150]}")
        if tariff.get("winners"):
            lines.append(f"  Winners: {', '.join(tariff['winners'][:5])}")
        if tariff.get("losers"):
            lines.append(f"  Losers: {', '.join(tariff['losers'][:5])}")

    # X reaction
    x = intel.get("x_reaction", {})
    if x.get("x_reaction"):
        lines.append(f"\nX REACTION: {x.get('x_reaction', '?').upper()}")
        if x.get("trader_sentiment"):
            lines.append(f"  {x['trader_sentiment'][:150]}")
        if x.get("consensus_trade"):
            lines.append(f"  Consensus: {x['consensus_trade'][:100]}")

    # Sectors
    if intel.get("sectors_impacted"):
        lines.append(f"\nSectors hit: {', '.join(intel['sectors_impacted'][:8])}")

    return "\n".join(lines)


def get_latest_intel():
    if not os.path.exists(TRUTH_INTEL_FILE):
        return None
    try:
        with open(TRUTH_INTEL_FILE) as f:
            history = json.load(f)
        return history[-1] if history else None
    except Exception:
        return None


def _save_intel(intel):
    history = []
    if os.path.exists(TRUTH_INTEL_FILE):
        try:
            with open(TRUTH_INTEL_FILE) as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(intel)
    history = history[-50:]
    with open(TRUTH_INTEL_FILE, "w") as f:
        json.dump(history, f, indent=2)
    log(f"Intel saved to {TRUTH_INTEL_FILE}")


def _load_last_seen():
    if os.path.exists(LAST_POST_FILE):
        try:
            with open(LAST_POST_FILE) as f:
                return json.load(f).get("last_id", "")
        except Exception:
            pass
    return ""


def _save_last_seen(post_id):
    with open(LAST_POST_FILE, "w") as f:
        json.dump({"last_id": post_id, "timestamp": datetime.now().isoformat()}, f)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = quick_scan(sys.argv[1])
        print(result)
    else:
        scan_truth()
