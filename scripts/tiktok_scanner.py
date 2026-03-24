"""TikTok Scanner — FinTok Intelligence for Rudy v2.0
Scans TikTok for trending stock picks, 10X moonshot calls, and retail sentiment.
Uses Tavily web search (TikTok has no public API) + Gemini for analysis.
Part of Rudy v2.0 Trading System — Constitution v41.0
"""
import os
import sys
import json
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
TT_INTEL_FILE = os.path.join(DATA_DIR, "tiktok_intel.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_URL = "https://api.x.ai/v1/chat/completions"

# 10X hunter search queries for TikTok
SEARCH_QUERIES = [
    "tiktok stock picks 2026",
    "tiktok 10x stock moonshot",
    "tiktok best stock to buy now",
    "fintok trending stocks",
    "tiktok penny stock going viral",
    "tiktok JOBY stock eVTOL",
    "tiktok quantum computing stock",
    "tiktok AI stock small cap",
    "tiktok meme stock next squeeze",
    "tiktok nuclear energy stock SMR",
    "tiktok space stock RKLB LUNR",
]

# Known 10X candidate tickers to always check
TEN_X_UNIVERSE = [
    "JOBY", "ACHR", "LILM",       # eVTOL
    "IONQ", "RGTI", "QUBT",       # Quantum
    "SMR", "OKLO",                 # Nuclear/SMR
    "RKLB", "LUNR", "ASTS",       # Space
    "PLTR", "SOFI", "HOOD",       # Fintech/AI
    "MARA", "RIOT", "COIN",       # Crypto
    "DNA", "CRSP", "BEAM",        # Biotech/Genomics
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[TikTok {ts}] {msg}")
    with open(f"{LOG_DIR}/tiktok.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def tavily_search(query, max_results=5):
    """Search TikTok content via Tavily."""
    if not TAVILY_API_KEY:
        log("No TAVILY_API_KEY set")
        return []

    try:
        r = requests.post(TAVILY_URL, json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_domains": ["tiktok.com", "reddit.com/r/wallstreetbets",
                                "stocktwits.com", "benzinga.com"],
        }, timeout=15)
        data = r.json()
        results = []
        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", "")[:400],
                "source": "tiktok" if "tiktok.com" in item.get("url", "") else "social",
            })
        return results
    except Exception as e:
        log(f"Tavily search error: {e}")
        return []


def ask_gemini(prompt, max_tokens=2000):
    """Use Gemini for TikTok content analysis."""
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
            log(f"Gemini error: {data.get('error', data)}")
            return None
        content = data["candidates"][0]["content"]["parts"][0]["text"]
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
            return {"raw_text": cleaned}
    except Exception as e:
        log(f"Gemini error: {e}")
        return None


def ask_grok(prompt, max_tokens=2000):
    """Use Grok for cross-referencing TikTok picks with X sentiment."""
    if not GROK_API_KEY:
        return None
    try:
        r = requests.post(
            GROK_URL,
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-fast-latest",
                "messages": [
                    {"role": "system", "content": "You are a trading analyst cross-referencing TikTok stock picks with X/Twitter sentiment. Respond in JSON."},
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


def scan_tiktok():
    """Full TikTok scan for trending stock picks and 10X candidates."""
    log("=" * 50)
    log("Starting TikTok/FinTok intelligence scan")

    all_results = []
    seen_urls = set()

    for query in SEARCH_QUERIES:
        log(f"Searching: {query}")
        results = tavily_search(query, max_results=3)
        for r in results:
            if r["url"] not in seen_urls:
                all_results.append(r)
                seen_urls.add(r["url"])

    # Also search specific 10X tickers on TikTok
    for ticker in TEN_X_UNIVERSE[:8]:  # Top 8 to save API calls
        results = tavily_search(f"tiktok {ticker} stock analysis", max_results=2)
        for r in results:
            if r["url"] not in seen_urls:
                r["ticker_search"] = ticker
                all_results.append(r)
                seen_urls.add(r["url"])

    if not all_results:
        log("No TikTok/social results found")
        return None

    log(f"Found {len(all_results)} results ({sum(1 for r in all_results if r['source'] == 'tiktok')} from TikTok)")

    # Build content for AI analysis
    content_text = "\n".join(
        f"- [{r['source'].upper()}] \"{r['title']}\": {r['content']}"
        for r in all_results[:25]
    )

    # Gemini: analyze for trading signals
    gemini_result = ask_gemini(f"""You are a trading intelligence analyst. Analyze this TikTok/social media content
about stocks and extract actionable signals. Focus on finding potential 10X moonshot stocks.

Social media content:
{content_text}

Our 10X watchlist sectors: eVTOL (JOBY, ACHR, LILM), Quantum (IONQ, RGTI, QUBT),
Nuclear (SMR, OKLO), Space (RKLB, LUNR, ASTS), Crypto (MARA, RIOT, COIN), Biotech (DNA, CRSP, BEAM)

Respond in this exact JSON format:
{{
    "summary": "3-5 sentence overview of what FinTok is buzzing about",
    "overall_sentiment": "bullish/bearish/neutral/euphoric",
    "viral_picks": [
        {{
            "ticker": "SYMBOL",
            "hype_level": "viral/trending/emerging",
            "bull_case": "why TikTok thinks this will moon",
            "sector": "eVTOL/quantum/nuclear/space/AI/biotech/meme/other",
            "ten_x_potential": "high/medium/low",
            "risk_warning": "what could go wrong"
        }}
    ],
    "signals": [
        {{
            "ticker": "SYMBOL",
            "signal": "buy/sell/watch",
            "confidence": "high/medium/low",
            "reason": "why this signal matters"
        }}
    ],
    "hot_tickers": ["most mentioned tickers on FinTok"],
    "meme_stocks": ["stocks getting meme treatment"],
    "catalysts": ["catalysts being discussed"],
    "risks": ["contrarian warnings or risks"]
}}

Be skeptical of pure hype — flag real catalysts vs FOMO. Do not fabricate.""")

    # Grok: cross-reference TikTok picks with X/Twitter
    tickers_found = []
    if gemini_result and gemini_result.get("viral_picks"):
        tickers_found = [p["ticker"] for p in gemini_result["viral_picks"][:10]]
    if gemini_result and gemini_result.get("hot_tickers"):
        tickers_found.extend(gemini_result["hot_tickers"][:5])
    tickers_found = list(set(tickers_found))

    grok_cross = None
    if tickers_found:
        grok_cross = ask_grok(f"""These tickers are trending on TikTok/FinTok right now: {', '.join(tickers_found)}

Cross-reference with X/Twitter: Are these same tickers also trending on X?
For each ticker, check if X sentiment agrees or disagrees with TikTok hype.

Respond in JSON:
{{
    "cross_reference": [
        {{
            "ticker": "SYMBOL",
            "tiktok_hype": "high/medium/low",
            "x_sentiment": "bullish/bearish/neutral",
            "x_agrees_with_tiktok": true/false,
            "x_evidence": "what X users are saying",
            "smart_money_signal": "are institutions/whales also interested? yes/no/unknown"
        }}
    ],
    "divergences": ["tickers where TikTok and X disagree — these are important"],
    "confirmed_picks": ["tickers where BOTH TikTok and X are bullish"]
}}""")

    # Build final result
    if not gemini_result:
        gemini_result = {
            "summary": f"Found {len(all_results)} social media posts about stocks.",
            "overall_sentiment": "unknown",
            "viral_picks": [],
            "signals": [],
            "hot_tickers": [],
            "meme_stocks": [],
            "catalysts": [],
            "risks": [],
        }

    result = gemini_result
    result.setdefault("summary", "")
    result.setdefault("overall_sentiment", "neutral")
    result.setdefault("viral_picks", [])
    result.setdefault("signals", [])
    result.setdefault("hot_tickers", [])
    result.setdefault("meme_stocks", [])
    result.setdefault("catalysts", [])
    result.setdefault("risks", [])
    result["grok_cross_reference"] = grok_cross or {}
    result["timestamp"] = datetime.now().isoformat()
    result["scanner"] = "tiktok"
    result["posts_found"] = len(all_results)

    # Save intel
    _save_intel(result)

    # Telegram alert
    alert = format_alert(result)
    log(alert)
    try:
        telegram.send(alert)
    except Exception:
        pass

    log("TikTok scan complete")
    log("=" * 50)
    return result


def quick_scan(ticker):
    """Quick TikTok scan for a single ticker."""
    log(f"Quick scan: {ticker}")

    results = tavily_search(f"tiktok {ticker} stock", max_results=8)
    if not results:
        msg = f"No TikTok results for {ticker}"
        log(msg)
        return msg

    content_text = "\n".join(
        f"- [{r['source'].upper()}] \"{r['title']}\": {r['content']}"
        for r in results[:8]
    )

    gemini_result = ask_gemini(f"""Analyze TikTok/social content about ${ticker}:
{content_text}

Respond in JSON:
{{
    "ticker": "{ticker}",
    "summary": "2-3 sentences on TikTok sentiment",
    "sentiment": "bullish/bearish/neutral/euphoric",
    "hype_level": "viral/trending/emerging/none",
    "ten_x_potential": "high/medium/low",
    "bull_case": "why TikTok likes it",
    "risks": ["risks or red flags"],
    "signals": [
        {{
            "signal": "buy/sell/watch",
            "confidence": "high/medium/low",
            "reason": "explanation"
        }}
    ]
}}""", max_tokens=1000)

    if not gemini_result:
        lines = [f"TIKTOK SCAN: ${ticker}", f"Found {len(results)} results", ""]
        for r in results[:5]:
            lines.append(f"  [{r['source']}] {r['title'][:80]}")
        alert = "\n".join(lines)
        try:
            telegram.send(alert)
        except Exception:
            pass
        return alert

    gemini_result.setdefault("ticker", ticker)
    gemini_result.setdefault("summary", "No data")
    gemini_result.setdefault("sentiment", "neutral")

    # Save
    intel = {
        "timestamp": datetime.now().isoformat(),
        "scanner": "tiktok",
        "type": "quick_scan",
        "ticker": ticker,
        "overall_sentiment": gemini_result.get("sentiment", "neutral"),
        "summary": gemini_result.get("summary", ""),
        "signals": gemini_result.get("signals", []),
        "viral_picks": [{
            "ticker": ticker,
            "hype_level": gemini_result.get("hype_level", "unknown"),
            "ten_x_potential": gemini_result.get("ten_x_potential", "unknown"),
            "bull_case": gemini_result.get("bull_case", ""),
        }],
        "hot_tickers": [ticker],
        "posts_found": len(results),
    }
    _save_intel(intel)

    lines = [
        f"TIKTOK SCAN: ${ticker}",
        f"Sentiment: {gemini_result.get('sentiment', '?').upper()}",
        f"Hype: {gemini_result.get('hype_level', '?').upper()}",
        f"10X Potential: {gemini_result.get('ten_x_potential', '?').upper()}",
        "",
        gemini_result.get("summary", ""),
    ]

    if gemini_result.get("bull_case"):
        lines.append(f"\nBull case: {gemini_result['bull_case'][:150]}")

    for s in gemini_result.get("signals", []):
        lines.append(f"  {s.get('signal', '?').upper()} ({s.get('confidence', '?')}) — {s.get('reason', '')[:100]}")

    if gemini_result.get("risks"):
        lines.append(f"\nRisks: {', '.join(gemini_result['risks'][:3])}")

    alert = "\n".join(lines)
    try:
        telegram.send(alert)
    except Exception:
        pass
    return alert


def format_alert(intel):
    """Format TikTok intelligence for Telegram."""
    lines = [
        "TIKTOK / FINTOK INTELLIGENCE",
        f"Sentiment: {intel.get('overall_sentiment', 'N/A').upper()}",
        f"Posts scanned: {intel.get('posts_found', 0)}",
        "",
        intel.get("summary", "")[:400],
        "",
    ]

    # Viral picks with 10X potential
    viral = intel.get("viral_picks", [])
    high_potential = [v for v in viral if v.get("ten_x_potential") == "high"]
    if high_potential:
        lines.append("10X MOONSHOT PICKS:")
        for v in high_potential[:5]:
            lines.append(f"  ${v['ticker']} [{v.get('sector', '?')}] — {v.get('hype_level', '?').upper()}")
            lines.append(f"    {v.get('bull_case', '')[:100]}")
            if v.get("risk_warning"):
                lines.append(f"    ⚠ {v['risk_warning'][:80]}")

    # Medium potential
    med_potential = [v for v in viral if v.get("ten_x_potential") == "medium"]
    if med_potential:
        lines.append("\nWATCHLIST (medium potential):")
        for v in med_potential[:5]:
            lines.append(f"  ${v['ticker']} [{v.get('sector', '?')}] — {v.get('bull_case', '')[:80]}")

    # Grok cross-reference
    grok = intel.get("grok_cross_reference", {})
    confirmed = grok.get("confirmed_picks", [])
    if confirmed:
        lines.append(f"\nCONFIRMED (TikTok + X agree): {', '.join(confirmed)}")
    divergences = grok.get("divergences", [])
    if divergences:
        lines.append(f"DIVERGENCES (TikTok vs X): {', '.join(divergences[:5])}")

    # Hot tickers
    if intel.get("hot_tickers"):
        lines.append(f"\nHot on FinTok: {', '.join(intel['hot_tickers'][:10])}")

    # Meme stocks
    if intel.get("meme_stocks"):
        lines.append(f"Meme alert: {', '.join(intel['meme_stocks'][:5])}")

    if intel.get("risks"):
        lines.append(f"\nRisks: {', '.join(intel['risks'][:3])}")

    return "\n".join(lines)


def get_latest_intel():
    """Read latest TikTok intel."""
    if not os.path.exists(TT_INTEL_FILE):
        return None
    try:
        with open(TT_INTEL_FILE) as f:
            history = json.load(f)
        return history[-1] if history else None
    except Exception:
        return None


def _save_intel(intel):
    """Save intelligence report (keep last 50)."""
    history = []
    if os.path.exists(TT_INTEL_FILE):
        try:
            with open(TT_INTEL_FILE) as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(intel)
    history = history[-50:]
    with open(TT_INTEL_FILE, "w") as f:
        json.dump(history, f, indent=2)
    log(f"Intel saved to {TT_INTEL_FILE}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = quick_scan(sys.argv[1])
        print(result)
    else:
        scan_tiktok()
