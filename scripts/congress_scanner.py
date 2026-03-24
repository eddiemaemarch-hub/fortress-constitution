"""Congress Stock Scanner — Congressional Trading Intelligence for Rudy v2.0
Monitors stock trades by members of Congress (Pelosi, Tuberville, Crenshaw, etc.).
Uses: Tavily (web search) + Gemini (analysis) + Grok (X context).
Data sources: Capitol Trades, Quiver Quantitative, House/Senate STOCK Act disclosures.
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
CONGRESS_INTEL_FILE = os.path.join(DATA_DIR, "congress_intel.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
GROK_API_KEY = os.environ.get("GROK_API_KEY", os.environ.get("XAI_API_KEY", ""))

# Key members to track (known active traders)
TRACKED_MEMBERS = [
    "Nancy Pelosi", "Paul Pelosi",
    "Tommy Tuberville",
    "Dan Crenshaw",
    "Marjorie Taylor Greene",
    "Josh Gottheimer",
    "Michael McCaul",
    "Mark Green",
    "Ro Khanna",
    "Pat Fallon",
    "Virginia Foxx",
    "Austin Scott",
]

# Our universe tickers — flag if Congress is trading these
OUR_UNIVERSE = [
    "MSTR", "IBIT", "NVDA", "TSLA", "AMD", "META", "AVGO", "PLTR", "NFLX", "AMZN",
    "CCJ", "UEC", "LEU", "VST", "CEG", "XOM", "CVX", "OXY", "SMR",
    "GLD", "GDX", "NEM", "SLV", "MP", "REMX",
    "RKLB", "ASTS", "LUNR", "GOOGL", "LMT", "NOC",
    "JOBY", "IONQ", "QUBT", "OKLO", "DNA", "CRSP", "BBAI", "SOUN",
    "COIN", "MARA", "RIOT",
    "GME", "AMC", "SOFI", "RIVN",
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Congress {ts}] {msg}")
    with open(f"{LOG_DIR}/congress.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def tavily_search(query, max_results=10):
    """Search for Congress stock trades via Tavily."""
    if not TAVILY_API_KEY:
        log("No Tavily API key")
        return []
    try:
        resp = requests.post(TAVILY_URL, json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_domains": [
                "capitoltrades.com", "quiverquant.com", "unusualwhales.com",
                "senatestockwatcher.com", "housestockwatcher.com",
                "reuters.com", "cnbc.com", "bloomberg.com",
            ],
        }, timeout=30)
        data = resp.json()
        return data.get("results", [])
    except Exception as e:
        log(f"Tavily error: {e}")
        return []


def ask_gemini(prompt):
    """Analyze Congress trades with Gemini."""
    if not GEMINI_API_KEY:
        return "No Gemini API key"
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        log(f"Gemini error: {e}")
        return f"Gemini error: {e}"


def ask_grok(prompt):
    """Get Grok's real-time X context on Congress trades."""
    if not GROK_API_KEY:
        return "No Grok API key"
    try:
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-fast-latest",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=30,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"Grok error: {e}")
        return f"Grok error: {e}"


def scan_congress():
    """Full scan of recent Congressional stock trades."""
    log("Starting Congress stock scan")

    # Search for recent trades
    results = tavily_search("Congress stock trades this week 2026 disclosure STOCK Act")
    pelosi_results = tavily_search("Pelosi stock trades 2026 options disclosure")
    all_results = results + pelosi_results

    if not all_results:
        log("No Congress trade data found")
        return

    # Compile trade summaries
    trade_texts = []
    for r in all_results[:15]:
        trade_texts.append(f"[{r.get('url', 'N/A')}]\n{r.get('content', '')[:500]}")

    combined = "\n\n---\n\n".join(trade_texts)

    # Gemini analysis
    gemini_prompt = f"""Analyze these Congressional stock trade disclosures for trading signals.

DATA:
{combined}

Return JSON:
{{
    "total_trades": <number of trades found>,
    "recent_buys": <count of buy transactions>,
    "recent_sells": <count of sell transactions>,
    "top_ticker": "<most traded ticker>",
    "hot_tickers": ["TICKER1", "TICKER2", ...],
    "notable_trades": [
        "Member: ACTION $TICKER ($amount) on DATE",
        ...
    ],
    "overlap_with_universe": ["tickers that overlap with: {', '.join(OUR_UNIVERSE[:20])}..."],
    "ai_analysis": "<2-3 sentence analysis of what Congress is buying/selling and why it matters>",
    "pelosi_activity": "<summary of Pelosi/Paul Pelosi recent trades if any>",
    "signals": ["BULLISH: ticker - reason", "BEARISH: ticker - reason", ...]
}}

Focus on: large trades (>$100k), options activity, unusual timing near legislation,
and any overlap with our trading universe."""

    gemini_raw = ask_gemini(gemini_prompt)
    log(f"Gemini response: {gemini_raw[:200]}")

    # Parse Gemini JSON
    intel = {}
    try:
        cleaned = gemini_raw.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0]
        intel = json.loads(cleaned.strip())
    except Exception as e:
        log(f"JSON parse error: {e}")
        intel = {
            "total_trades": 0,
            "ai_analysis": gemini_raw[:300],
            "hot_tickers": [],
            "notable_trades": [],
        }

    # Grok X context
    grok_prompt = f"""What's the latest X/Twitter buzz about Congressional stock trading?
Focus on: Pelosi trades, STOCK Act violations, unusual options activity by members of Congress.
Hot tickers from Congress: {', '.join(intel.get('hot_tickers', [])[:10])}
Any insider trading accusations or upcoming legislation affecting these stocks?
Be specific with tickers and member names. 2-3 sentences."""

    grok_context = ask_grok(grok_prompt)
    intel["x_reaction"] = grok_context
    intel["scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Check overlap with our universe
    overlap = []
    for ticker in intel.get("hot_tickers", []):
        if ticker.upper() in OUR_UNIVERSE:
            overlap.append(ticker.upper())
    intel["universe_overlap"] = overlap

    # Save intel
    history = []
    if os.path.exists(CONGRESS_INTEL_FILE):
        with open(CONGRESS_INTEL_FILE) as f:
            history = json.load(f)
    history.append(intel)
    history = history[-50:]  # keep last 50
    with open(CONGRESS_INTEL_FILE, "w") as f:
        json.dump(history, f, indent=2)

    log(f"Congress scan complete: {intel.get('total_trades', 0)} trades, hot: {intel.get('hot_tickers', [])}")

    # Alert on significant findings
    if intel.get("universe_overlap") or intel.get("signals"):
        alert = format_alert(intel)
        telegram.send(alert)
        log("Telegram alert sent")

    return intel


def quick_scan(ticker=None):
    """Quick scan Congress trades for a specific ticker via Grok."""
    log(f"Quick scan: {ticker or 'all'}")

    query = f"recent Congressional stock trades for ${ticker} disclosure STOCK Act" if ticker else "latest Congressional stock trades disclosure STOCK Act this week"

    prompt = f"""Summarize the latest Congressional stock trades{' involving $' + ticker if ticker else ''} in plain English.

DO NOT copy/paste raw tables, HTML, or website content. Write 3-5 natural sentences covering: which Congress members traded (name + party), what they bought/sold, trade sizes, and dates. Focus on Pelosi, Tuberville, and any trades that look suspicious. Include any X/Twitter buzz about Congressional insider trading."""

    result = ask_grok(prompt)
    if not result or "error" in result.lower():
        return f"No Congress trade data found{' for ' + ticker if ticker else ''}"

    label = f"CONGRESS TRADES{': $' + ticker if ticker else ''}"
    return f"{label}\n{result[:500]}"


def format_alert(intel):
    """Format Congress intel for Telegram."""
    lines = [
        "CONGRESS STOCK INTELLIGENCE",
        f"Trades: {intel.get('total_trades', 0)} | Buys: {intel.get('recent_buys', 0)} | Sells: {intel.get('recent_sells', 0)}",
        f"Hot: {', '.join(intel.get('hot_tickers', [])[:8])}",
        "",
    ]

    if intel.get("universe_overlap"):
        lines.append(f"OUR UNIVERSE OVERLAP: {', '.join(intel['universe_overlap'])}")
        lines.append("")

    if intel.get("notable_trades"):
        lines.append("Notable:")
        for t in intel["notable_trades"][:5]:
            lines.append(f"  {t}")
        lines.append("")

    if intel.get("pelosi_activity"):
        lines.append(f"Pelosi: {intel['pelosi_activity'][:200]}")
        lines.append("")

    if intel.get("ai_analysis"):
        lines.append(intel["ai_analysis"][:300])

    return "\n".join(lines)


if __name__ == "__main__":
    import subprocess
    subprocess.run("set -a && source ~/.agent_zero_env && set +a", shell=True, executable="/bin/zsh")
    # Re-read env vars
    env_file = os.path.expanduser("~/.agent_zero_env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
    scan_congress()
