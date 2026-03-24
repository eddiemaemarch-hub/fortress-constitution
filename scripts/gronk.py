"""Gronk — X/Twitter Investment Intelligence Scanner
Uses Tavily to search X for financial posts and DeepSeek to analyze sentiment/signals.
Scans for: earnings whispers, whale moves, sector rotation, breaking catalysts,
short squeeze chatter, insider activity, and macro signals.
Feeds actionable intelligence to Rudy's trading systems.
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
INTEL_FILE = os.path.join(DATA_DIR, "gronk_intel.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Tickers we care about across all systems
WATCHLIST = {
    "system1": ["MSTR", "IBIT", "BTC", "Bitcoin"],
    "trader3": ["CCJ", "UEC", "XOM", "CVX", "OXY", "DVN", "FANG", "VST", "CEG", "LEU", "uranium", "energy"],
    "trader4": ["GME", "AMC", "SOFI", "RIVN", "LCID", "COIN", "MARA", "RIOT", "PLTR", "short squeeze"],
    "trader5": ["NVDA", "AMZN", "GOOGL", "TSLA", "NFLX", "CRM", "AVGO", "AMD", "SHOP", "SQ", "breakout"],
}

# High-value X accounts to prioritize
INFLUENCERS = [
    "NoLimitGaines", "honeydripnetwor", "aristotlegrowth", "unusual_whales", "DeItaone", "zabormeister", "jimcramer",
    "michaeljburry", "elonmusk", "CathieDWood", "chaaborz",
    "WallStJesus", "optionsflow", "TradeAlgo", "SenWarren",
    "GoldmanSachs", "federalreserve", "SEC_Enforcement",
]

# Search queries for different signal types
SCAN_QUERIES = [
    # Ticker-specific
    "site:x.com {ticker} stock price target",
    "site:x.com {ticker} options unusual activity",
    "site:x.com {ticker} earnings whisper",
    # Thematic
    "site:x.com short squeeze candidates 2026",
    "site:x.com uranium stocks catalyst",
    "site:x.com bitcoin MSTR options",
    "site:x.com energy stocks breakout",
    "site:x.com unusual options activity today",
    "site:x.com fed rate decision market impact",
    "site:x.com insider buying stocks",
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Gronk {ts}] {msg}")
    with open(f"{LOG_DIR}/gronk.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def tavily_search(query, max_results=5):
    """Search the web/X via Tavily API."""
    if not TAVILY_API_KEY:
        log("No Tavily API key")
        return []

    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_domains": ["x.com", "twitter.com"],
            },
            timeout=15,
        )
        data = r.json()
        results = []
        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", "")[:500],
                "score": item.get("score", 0),
            })
        return results
    except Exception as e:
        log(f"Tavily error: {e}")
        return []


def tavily_search_general(query, max_results=5):
    """Search broader web for financial news about tickers."""
    if not TAVILY_API_KEY:
        return []

    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_domains": [
                    "x.com", "twitter.com", "reddit.com",
                    "stocktwits.com", "finance.yahoo.com",
                    "seekingalpha.com", "benzinga.com",
                ],
            },
            timeout=15,
        )
        data = r.json()
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", "")[:500],
                "score": item.get("score", 0),
            }
            for item in data.get("results", [])
        ]
    except Exception as e:
        log(f"Tavily general error: {e}")
        return []


def deepseek_analyze(posts, context=""):
    """Use DeepSeek to analyze X posts for trading signals."""
    if not DEEPSEEK_API_KEY:
        log("No DeepSeek API key")
        return None

    posts_text = "\n\n".join(
        f"[{p.get('title', 'Post')}]\n{p['content']}\nURL: {p['url']}"
        for p in posts if p.get("content")
    )

    if not posts_text.strip():
        return None

    prompt = f"""You are Gronk, a financial intelligence analyst. Analyze these X/Twitter posts and social media content for actionable trading signals.

CONTEXT: {context}

OUR WATCHLIST:
- System 1 (Lottery): MSTR, IBIT, Bitcoin
- Trader 3 (Energy): CCJ, UEC, XOM, CVX, OXY, DVN, FANG, VST, CEG, LEU
- Trader 4 (Squeeze): GME, AMC, SOFI, RIVN, LCID, COIN, MARA, RIOT, PLTR
- Trader 5 (Breakout): NVDA, AMZN, GOOGL, TSLA, NFLX, CRM, AVGO, AMD, SHOP, SQ

POSTS TO ANALYZE:
{posts_text}

Provide your analysis in this exact JSON format:
{{
    "summary": "2-3 sentence overview of what X is saying",
    "sentiment": "bullish/bearish/neutral/mixed",
    "signals": [
        {{
            "ticker": "SYMBOL",
            "signal": "buy/sell/watch",
            "confidence": "high/medium/low",
            "reason": "brief explanation",
            "system": "which trading system this applies to"
        }}
    ],
    "catalysts": ["list of upcoming catalysts mentioned"],
    "risks": ["list of risks or bearish signals"],
    "hot_tickers": ["tickers getting the most attention"]
}}

Only include signals with real evidence from the posts. Do not fabricate."""

    try:
        # Try DeepSeek first, fall back to Gemini
        content = None
        if DEEPSEEK_API_KEY:
            try:
                r = requests.post(
                    DEEPSEEK_URL,
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": "You are Gronk, a sharp financial intelligence analyst. Always respond with valid JSON."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1500,
                    },
                    timeout=30,
                )
                data = r.json()
                if "choices" in data:
                    content = data["choices"][0]["message"]["content"]
            except:
                pass

        if not content and GEMINI_API_KEY:
            r = requests.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1500},
                },
                timeout=30,
            )
            data = r.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]

        if not content:
            log("No AI engine available")
            return None

        # Extract JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        # Try to parse JSON from response
        cleaned = content.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0]

        # Fix common JSON issues
        cleaned = cleaned.strip()
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
            # Last resort: build a basic response from the text
            log(f"Could not parse JSON, using raw text")
            return {
                "summary": content[:300],
                "sentiment": "neutral",
                "signals": [],
                "catalysts": [],
                "risks": [],
                "hot_tickers": [],
            }
    except Exception as e:
        log(f"Analysis error: {e}")
        return None


def scan_x():
    """Run full X/Twitter scan across all watchlist tickers."""
    log("=" * 50)
    log("Starting X intelligence scan")

    all_posts = []
    all_analysis = []

    # Scan each system's tickers
    for system, tickers in WATCHLIST.items():
        log(f"--- Scanning {system} tickers ---")
        for ticker in tickers[:5]:  # Top 5 per system to stay within rate limits
            query = f"site:x.com {ticker} stock trading 2026"
            posts = tavily_search(query, max_results=3)
            if not posts:
                # Fallback to broader search
                posts = tavily_search_general(f"{ticker} stock trading news today", max_results=3)
            if posts:
                log(f"  {ticker}: {len(posts)} posts found")
                all_posts.extend(posts)

    # Scan key influencers
    log("--- Scanning influencers ---")
    for handle in INFLUENCERS[:8]:  # Top 8 to stay within rate limits
        posts = tavily_search(f"site:x.com from:{handle} stocks trading", max_results=3)
        if not posts:
            posts = tavily_search_general(f"x.com {handle} stocks trading", max_results=3)
        if posts:
            log(f"  @{handle}: {len(posts)} posts found")
            all_posts.extend(posts)

    # Scan thematic queries
    log("--- Scanning thematic queries ---")
    thematic_queries = [
        "unusual options activity today stocks",
        "short squeeze candidates stocks 2026",
        "uranium energy stocks catalyst news",
        "bitcoin MSTR institutional buying",
        "NVDA TSLA AMZN breakout momentum",
        "fed interest rate market impact stocks",
    ]

    for query in thematic_queries:
        posts = tavily_search_general(query, max_results=3)
        if posts:
            log(f"  Thematic: {len(posts)} results for '{query[:40]}...'")
            all_posts.extend(posts)

    if not all_posts:
        log("No posts found — check API keys")
        return None

    # Deduplicate by URL
    seen = set()
    unique_posts = []
    for p in all_posts:
        if p["url"] not in seen:
            seen.add(p["url"])
            unique_posts.append(p)
    all_posts = unique_posts

    log(f"Total unique posts: {len(all_posts)}")

    # Analyze in batches of 10 with DeepSeek
    batch_size = 10
    for i in range(0, len(all_posts), batch_size):
        batch = all_posts[i:i + batch_size]
        log(f"Analyzing batch {i // batch_size + 1} ({len(batch)} posts)...")
        analysis = deepseek_analyze(batch, context=f"Batch {i // batch_size + 1} of {len(all_posts)} total posts")
        if analysis:
            all_analysis.append(analysis)

    if not all_analysis:
        log("DeepSeek analysis failed")
        return None

    # Merge analyses
    merged = {
        "timestamp": datetime.now().isoformat(),
        "total_posts_scanned": len(all_posts),
        "summary": " | ".join(a.get("summary", "") for a in all_analysis if a.get("summary")),
        "overall_sentiment": _merge_sentiment([a.get("sentiment", "neutral") for a in all_analysis]),
        "signals": [],
        "catalysts": [],
        "risks": [],
        "hot_tickers": [],
    }

    for a in all_analysis:
        merged["signals"].extend(a.get("signals", []))
        merged["catalysts"].extend(a.get("catalysts", []))
        merged["risks"].extend(a.get("risks", []))
        merged["hot_tickers"].extend(a.get("hot_tickers", []))

    # Deduplicate
    merged["catalysts"] = list(set(merged["catalysts"]))
    merged["risks"] = list(set(merged["risks"]))
    merged["hot_tickers"] = list(set(merged["hot_tickers"]))

    # Save intel
    save_intel(merged)

    # Send Telegram alert
    alert = format_alert(merged)
    log(alert)
    try:
        telegram.send(alert)
    except:
        pass

    log("X scan complete")
    log("=" * 50)
    return merged


def _merge_sentiment(sentiments):
    """Merge multiple sentiment readings."""
    bull = sum(1 for s in sentiments if s == "bullish")
    bear = sum(1 for s in sentiments if s == "bearish")
    if bull > bear:
        return "bullish"
    elif bear > bull:
        return "bearish"
    return "mixed"


def save_intel(intel):
    """Save intelligence report to file."""
    # Load existing
    history = []
    if os.path.exists(INTEL_FILE):
        try:
            with open(INTEL_FILE) as f:
                history = json.load(f)
        except:
            history = []

    history.append(intel)
    # Keep last 50 reports
    history = history[-50:]

    with open(INTEL_FILE, "w") as f:
        json.dump(history, f, indent=2)
    log(f"Intel saved to {INTEL_FILE}")


def format_alert(intel):
    """Format intelligence for Telegram alert."""
    lines = [
        "🔍 GRONK X INTELLIGENCE REPORT",
        f"📊 Posts scanned: {intel['total_posts_scanned']}",
        f"📈 Sentiment: {intel['overall_sentiment'].upper()}",
        "",
        intel["summary"][:300],
        "",
    ]

    # Top signals
    high_signals = [s for s in intel.get("signals", []) if s.get("confidence") == "high"]
    if high_signals:
        lines.append("⚡ HIGH CONFIDENCE SIGNALS:")
        for s in high_signals[:5]:
            lines.append(f"  {s['ticker']} → {s['signal'].upper()} ({s.get('system', '?')})")
            lines.append(f"    {s['reason'][:100]}")

    # Hot tickers
    if intel.get("hot_tickers"):
        lines.append(f"\n🔥 Hot: {', '.join(intel['hot_tickers'][:10])}")

    # Catalysts
    if intel.get("catalysts"):
        lines.append(f"\n📅 Catalysts: {', '.join(intel['catalysts'][:5])}")

    # Risks
    if intel.get("risks"):
        lines.append(f"\n⚠️ Risks: {', '.join(intel['risks'][:3])}")

    return "\n".join(lines)


def get_latest_intel():
    """Get the most recent intelligence report."""
    if not os.path.exists(INTEL_FILE):
        return None
    try:
        with open(INTEL_FILE) as f:
            history = json.load(f)
        return history[-1] if history else None
    except:
        return None


def quick_scan(ticker):
    """Quick scan for a single ticker."""
    log(f"Quick scan: {ticker}")
    posts = tavily_search(f"site:x.com {ticker} stock", max_results=5)
    if not posts:
        posts = tavily_search_general(f"{ticker} stock news today", max_results=5)
    if not posts:
        return f"No X chatter found for {ticker}"

    analysis = deepseek_analyze(posts, context=f"Quick scan for {ticker}")
    if analysis:
        save_intel({
            "timestamp": datetime.now().isoformat(),
            "total_posts_scanned": len(posts),
            "type": "quick_scan",
            "ticker": ticker,
            **analysis,
        })
        return format_alert({
            "total_posts_scanned": len(posts),
            "overall_sentiment": analysis.get("sentiment", "neutral"),
            "summary": analysis.get("summary", ""),
            **analysis,
        })
    return f"Found {len(posts)} posts for {ticker} but analysis failed"


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1:
        # Quick scan mode: python gronk.py NVDA
        result = quick_scan(_sys.argv[1])
        print(result)
    else:
        # Full scan
        scan_x()
