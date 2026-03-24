"""Insider Trading Scanner — Form 4 / Corporate Insider Activity for Rudy v2.0
Tracks CEO, CFO, director, and major shareholder buys/sells.
Data: SEC EDGAR Form 4 filings via Tavily + Grok (real-time X context).
Key metric: Buy/Sell ratio — when selling accelerates vs buying, it's a bearish signal.
Part of Rudy v2.0 Trading System — Constitution v42.0
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
INSIDER_INTEL_FILE = os.path.join(DATA_DIR, "insider_intel.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
GROK_API_KEY = os.environ.get("GROK_API_KEY", os.environ.get("XAI_API_KEY", ""))

# Our universe — flag if insiders are trading these
OUR_UNIVERSE = [
    "MSTR", "IBIT", "NVDA", "TSLA", "AMD", "META", "AVGO", "PLTR", "NFLX", "AMZN",
    "CCJ", "UEC", "LEU", "VST", "CEG", "XOM", "CVX", "OXY", "DVN", "FANG", "SMR",
    "GLD", "GDX", "NEM", "SLV", "MP", "REMX",
    "RKLB", "ASTS", "LUNR", "GOOGL", "LMT", "NOC",
    "JOBY", "IONQ", "QUBT", "OKLO", "DNA", "CRSP", "BBAI", "SOUN",
    "COIN", "MARA", "RIOT", "GME", "AMC", "SOFI", "RIVN",
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Insider {ts}] {msg}")
    with open(f"{LOG_DIR}/insider.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def tavily_search(query, max_results=10):
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
                "openinsider.com", "secform4.com", "finviz.com",
                "dataroma.com", "sec.gov", "insidertracking.com",
                "benzinga.com", "reuters.com", "cnbc.com",
                "unusualwhales.com", "capitoltrades.com",
            ],
        }, timeout=30)
        data = resp.json()
        return data.get("results", [])
    except Exception as e:
        log(f"Tavily error: {e}")
        return []


def ask_gemini(prompt):
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


def scan_insiders():
    """Full scan of corporate insider trading activity."""
    log("Starting insider trading scan")

    # Search for recent insider trades
    results_general = tavily_search("largest insider stock sales this week 2026 Form 4 SEC")
    results_buys = tavily_search("insider buying stocks 2026 CEO CFO director purchases")
    results_ratio = tavily_search("insider sell buy ratio 2026 accelerating selling corporate")

    # Also check our universe specifically
    universe_sample = ", ".join(OUR_UNIVERSE[:15])
    results_universe = tavily_search(f"insider trading {universe_sample} Form 4 2026")

    all_results = results_general + results_buys + results_ratio + results_universe

    if not all_results:
        log("No insider data found")
        return None

    trade_texts = []
    for r in all_results[:20]:
        trade_texts.append(f"[{r.get('url', '')}]\n{r.get('content', '')[:500]}")

    combined = "\n\n---\n\n".join(trade_texts)

    # Gemini analysis
    gemini_prompt = f"""Analyze this insider trading data. Focus on the BUY vs SELL ratio and what it signals.

DATA:
{combined}

Return JSON:
{{
    "buy_sell_ratio": "<ratio like '1:8' meaning 1 buy for every 8 sells>",
    "signal": "BULLISH/BEARISH/NEUTRAL",
    "signal_strength": "STRONG/MODERATE/WEAK",
    "total_sell_volume": "<estimated total $ sold this week/period>",
    "total_buy_volume": "<estimated total $ bought this week/period>",
    "sell_pace": "ACCELERATING/NORMAL/DECELERATING",
    "biggest_sells": [
        {{
            "insider": "Name, Title",
            "company": "Company Name",
            "ticker": "SYMBOL",
            "amount": "$XXM",
            "date": "YYYY-MM-DD or approximate"
        }}
    ],
    "biggest_buys": [
        {{
            "insider": "Name, Title",
            "company": "Company Name",
            "ticker": "SYMBOL",
            "amount": "$XXM",
            "date": "YYYY-MM-DD or approximate"
        }}
    ],
    "universe_overlap": ["tickers from our list that have insider activity: {', '.join(OUR_UNIVERSE[:20])}"],
    "ai_analysis": "<3-4 sentence analysis: what does this insider activity pattern mean for the market? Is this routine or unusual? What should a trader do with this info?>",
    "context": "<note whether selling could be routine (10b5-1 plans, tax planning, diversification) vs panic selling>"
}}

Be specific with names, amounts, and dates. If the data shows heavy selling with minimal buying, flag it clearly.
IMPORTANT: Return ONLY the JSON object. No explanation, no markdown, no text before or after. Just valid JSON starting with {{ and ending with }}."""

    gemini_raw = ask_gemini(gemini_prompt)
    log(f"Gemini response: {gemini_raw[:200]}")

    # Parse JSON
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
            "signal": "UNKNOWN",
            "ai_analysis": gemini_raw[:300],
            "biggest_sells": [],
            "biggest_buys": [],
        }

    # Grok X context — what's the chatter about insider selling?
    grok_prompt = f"""What's X/Twitter saying about corporate insider selling right now?
Specifically check:
- @nolimitgains posts about insider sell/buy ratios
- @unusual_whales insider trade alerts
- Any viral posts about CEO/CFO dumping stock
- Overall sentiment about insider selling as a market signal
Current insider signal: {intel.get('signal', 'UNKNOWN')}, ratio: {intel.get('buy_sell_ratio', '?')}
Top sellers: {', '.join(s.get('ticker', '?') for s in intel.get('biggest_sells', [])[:5])}
Give 2-3 sentences on what X thinks about this."""

    grok_context = ask_grok(grok_prompt)
    intel["x_reaction"] = grok_context
    intel["scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Save
    history = []
    if os.path.exists(INSIDER_INTEL_FILE):
        with open(INSIDER_INTEL_FILE) as f:
            history = json.load(f)
    history.append(intel)
    history = history[-50:]
    with open(INSIDER_INTEL_FILE, "w") as f:
        json.dump(history, f, indent=2)

    log(f"Insider scan complete: signal={intel.get('signal')}, ratio={intel.get('buy_sell_ratio')}")

    # Alert on strong bearish signals
    signal = intel.get("signal", "").upper()
    strength = intel.get("signal_strength", "").upper()
    if signal == "BEARISH" and strength == "STRONG":
        alert = format_alert(intel)
        telegram.send(alert)
        log("STRONG BEARISH insider signal — Telegram alert sent")
    elif intel.get("universe_overlap"):
        alert = format_alert(intel)
        telegram.send(alert)
        log("Universe overlap detected — Telegram alert sent")

    return intel


def quick_scan(ticker=None):
    """Quick scan insider activity for a specific ticker via Grok."""
    log(f"Quick scan: {ticker or 'market-wide'}")

    prompt = f"""Summarize the latest insider trading activity{' for $' + ticker if ticker else ' across the market'} in plain English.

DO NOT copy/paste raw tables or HTML. Write 3-5 natural sentences covering: who bought/sold (name + title), how much ($), when, and whether the pattern is bullish or bearish. Include any X/Twitter buzz about these insider moves."""

    result = ask_grok(prompt)
    if not result or "error" in result.lower():
        return f"No insider data found{' for ' + ticker if ticker else ''}"

    label = f"INSIDER TRADES{': $' + ticker if ticker else ''}"
    return f"{label}\n{result[:500]}"


def format_alert(intel):
    """Format insider intel for Telegram."""
    signal = intel.get("signal", "UNKNOWN")
    emoji = "🔴" if signal == "BEARISH" else "🟢" if signal == "BULLISH" else "🟡"

    lines = [
        f"{emoji} INSIDER TRADING INTELLIGENCE",
        f"Signal: {signal} ({intel.get('signal_strength', '?')})",
        f"Buy/Sell Ratio: {intel.get('buy_sell_ratio', '?')}",
        f"Sell Pace: {intel.get('sell_pace', '?')}",
        f"Sell Volume: {intel.get('total_sell_volume', '?')} | Buy Volume: {intel.get('total_buy_volume', '?')}",
        "",
    ]

    sells = intel.get("biggest_sells", [])
    if sells:
        lines.append("TOP SELLS:")
        for s in sells[:5]:
            lines.append(f"  {s.get('insider', '?')} — ${s.get('ticker', '?')} {s.get('amount', '?')}")
        lines.append("")

    buys = intel.get("biggest_buys", [])
    if buys:
        lines.append("TOP BUYS:")
        for b in buys[:3]:
            lines.append(f"  {b.get('insider', '?')} — ${b.get('ticker', '?')} {b.get('amount', '?')}")
        lines.append("")

    if intel.get("universe_overlap"):
        lines.append(f"OUR UNIVERSE: {', '.join(intel['universe_overlap'])}")
        lines.append("")

    if intel.get("ai_analysis"):
        lines.append(intel["ai_analysis"][:300])

    return "\n".join(lines)


if __name__ == "__main__":
    env_file = os.path.expanduser("~/.agent_zero_env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
    scan_insiders()
