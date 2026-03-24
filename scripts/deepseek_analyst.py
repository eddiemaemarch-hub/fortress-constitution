"""DeepSeek Analyst — Pre-trade analysis, market regime detection, and strategy optimization.
Uses DeepSeek API with Google Search grounding (via openai SDK) for live web context.
Gemini fallback if DeepSeek unavailable.
Part of Rudy v2.0 Trading System — Constitution v50.0

Google Search grounding: DeepSeek uses live web search for macro/news/catalyst context.
PRICE RULE: BTC/MSTR prices always come from IBKR state files, NEVER from web search results.
"""
import os
import sys
import json
import requests
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
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

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_URL = f"{DEEPSEEK_BASE_URL}/chat/completions"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# ── OpenAI-compat SDK client (grounded queries with web_search) ──
_grounded_client = None


def _init_grounded_client():
    """Initialize OpenAI-compat client pointing at DeepSeek for web_search grounding."""
    global _grounded_client
    if _grounded_client is not None:
        return _grounded_client
    try:
        from openai import OpenAI
        _grounded_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        log("DeepSeek OpenAI-compat client initialized (web_search grounding enabled)")
        return _grounded_client
    except Exception as e:
        log(f"OpenAI SDK unavailable ({e}) — falling back to raw REST")
        return None

TRADE_ANALYSIS_FILE = os.path.join(DATA_DIR, "trade_analysis.json")
MARKET_REGIME_FILE = os.path.join(DATA_DIR, "market_regime.json")
STRATEGY_REVIEW_FILE = os.path.join(DATA_DIR, "strategy_review.json")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[DeepSeek {ts}] {msg}")
    with open(f"{LOG_DIR}/deepseek.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def ask_deepseek(system_prompt, user_prompt, max_tokens=2000):
    """Send a prompt to DeepSeek (with Gemini fallback). Returns parsed JSON or raw text."""
    content = None

    # Try DeepSeek first
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
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": max_tokens,
                },
                timeout=30,
            )
            data = r.json()
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]
                log("DeepSeek responded")
        except Exception as e:
            log(f"DeepSeek error: {e}")

    # Fallback to Gemini
    if not content and GEMINI_API_KEY:
        try:
            r = requests.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": max_tokens},
                },
                timeout=30,
            )
            data = r.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            log("Gemini fallback responded")
        except Exception as e:
            log(f"Gemini fallback error: {e}")

    if not content:
        log("No AI engine available")
        return None

    # Extract JSON from response
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
            except:
                pass
        log("Could not parse JSON, returning raw text")
        return {"raw_text": cleaned}


def ask_deepseek_grounded(system_prompt, user_prompt, max_tokens=2000):
    """Call DeepSeek with live web_search tool via OpenAI-compat SDK.

    Same return contract as ask_deepseek() — returns parsed JSON dict or None.
    Use for: live trade analysis, regime detection with real-time macro context.
    PRICE RULE: BTC/MSTR prices always from IBKR state files, not from web search.
    Falls back to ask_deepseek() (raw REST + Gemini fallback) if SDK unavailable.
    """
    client = _init_grounded_client()
    if client is None:
        log("Grounded client unavailable — falling back to raw REST")
        return ask_deepseek(system_prompt, user_prompt, max_tokens)

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=[{"type": "web_search"}],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        if content is None:
            log("Grounded response content is None (tool_call path) — falling back to raw REST")
            return ask_deepseek(system_prompt, user_prompt, max_tokens)

        log("DeepSeek grounded response received")

        # Extract JSON (same logic as ask_deepseek)
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
            return ask_deepseek(system_prompt, user_prompt, max_tokens)

    except Exception as e:
        log(f"Grounded query error ({e}) — falling back to raw REST")
        return ask_deepseek(system_prompt, user_prompt, max_tokens)


# ---------------------------------------------------------------------------
# 1. Pre-Trade Analyst
# ---------------------------------------------------------------------------

def analyze_trade(ticker, strategy, entry_price, option_type=None, strike=None, dte=None):
    """Analyze a proposed trade and return verdict with supporting analysis."""
    log(f"Analyzing trade: {ticker} {strategy} @ ${entry_price}")

    option_info = ""
    if option_type:
        option_info = f"\nOption Type: {option_type}\nStrike: {strike}\nDTE: {dte}"

    system_prompt = (
        "You are a senior options and equities analyst for an algorithmic trading system. "
        "Provide rigorous, data-driven analysis. Always respond with valid JSON."
    )

    user_prompt = f"""Analyze this proposed trade and provide your assessment:

Ticker: {ticker}
Strategy: {strategy}
Entry Price: ${entry_price}{option_info}

Provide your analysis in this exact JSON format:
{{
    "verdict": "APPROVE or REJECT or CAUTION",
    "confidence": 0-100,
    "analysis": "2-4 sentence technical and fundamental overview",
    "key_levels": {{
        "support": [list of key support prices],
        "resistance": [list of key resistance prices]
    }},
    "risks": ["list of specific risks for this trade"],
    "catalysts": ["list of upcoming catalysts that could move this ticker"],
    "risk_reward": "assessment of risk/reward ratio",
    "options_pricing": "fair/expensive/cheap with brief reasoning (if applicable)"
}}

Be honest and critical. If the trade looks bad, say so."""

    result = ask_deepseek_grounded(system_prompt, user_prompt)
    if not result:
        log("Trade analysis failed — no AI response")
        return None

    # Ensure required fields
    result.setdefault("verdict", "CAUTION")
    result.setdefault("confidence", 50)
    result.setdefault("analysis", "")
    result.setdefault("key_levels", {"support": [], "resistance": []})
    result.setdefault("risks", [])
    result.setdefault("catalysts", [])

    # Add metadata
    result["ticker"] = ticker
    result["strategy"] = strategy
    result["entry_price"] = entry_price
    result["timestamp"] = datetime.now().isoformat()

    # Save to history
    history = []
    if os.path.exists(TRADE_ANALYSIS_FILE):
        try:
            with open(TRADE_ANALYSIS_FILE) as f:
                history = json.load(f)
        except:
            history = []

    history.append(result)
    history = history[-100:]  # Keep last 100

    with open(TRADE_ANALYSIS_FILE, "w") as f:
        json.dump(history, f, indent=2)

    log(f"Trade verdict: {result['verdict']} (confidence {result['confidence']})")

    # Send Telegram alert on REJECT
    if result["verdict"] == "REJECT":
        try:
            msg = (
                f"🚫 *TRADE REJECTED by DeepSeek*\n\n"
                f"Ticker: {ticker}\n"
                f"Strategy: {strategy}\n"
                f"Entry: ${entry_price}\n"
                f"Confidence: {result['confidence']}\n\n"
                f"{result.get('analysis', '')[:300]}"
            )
            telegram.send(msg)
        except:
            pass

    return result


# ---------------------------------------------------------------------------
# 2. Market Regime Detector
# ---------------------------------------------------------------------------

def detect_regime(vix=None, sp500_change=None, breadth=None):
    """Classify current market regime and return recommended adjustments."""
    log(f"Detecting regime — VIX={vix}, SP500={sp500_change}, breadth={breadth}")

    data_points = []
    if vix is not None:
        data_points.append(f"VIX: {vix}")
    if sp500_change is not None:
        data_points.append(f"S&P 500 recent change: {sp500_change}%")
    if breadth is not None:
        data_points.append(f"Market breadth (advance/decline): {breadth}")

    data_str = "\n".join(data_points) if data_points else "No specific data provided — use general market knowledge."

    system_prompt = (
        "You are a market regime classifier for a systematic trading operation. "
        "Always respond with valid JSON."
    )

    user_prompt = f"""Based on the following market data, classify the current market regime.

{data_str}

Possible regimes: BULL_STRONG, BULL_WEAK, SIDEWAYS, BEAR_WEAK, BEAR_STRONG, CRASH

Respond in this exact JSON format:
{{
    "regime": "one of the regimes above",
    "confidence": 0-100,
    "reasoning": "2-3 sentence explanation",
    "adjustments": {{
        "position_size_mult": 0.0 to 1.5 (1.0 = normal),
        "aggression": "conservative or normal or aggressive",
        "avoid_entries": true/false,
        "hedge_up": true/false
    }},
    "outlook": "1-2 sentence forward outlook"
}}"""

    result = ask_deepseek_grounded(system_prompt, user_prompt)
    if not result:
        log("Regime detection failed — no AI response")
        return None

    # Ensure required fields
    result.setdefault("regime", "SIDEWAYS")
    result.setdefault("confidence", 50)
    result.setdefault("reasoning", "")
    result.setdefault("adjustments", {
        "position_size_mult": 1.0,
        "aggression": "normal",
        "avoid_entries": False,
        "hedge_up": False,
    })

    result["timestamp"] = datetime.now().isoformat()
    result["inputs"] = {"vix": vix, "sp500_change": sp500_change, "breadth": breadth}

    # Save — overwrite current, append to history
    regime_data = {"current": result, "history": []}
    if os.path.exists(MARKET_REGIME_FILE):
        try:
            with open(MARKET_REGIME_FILE) as f:
                existing = json.load(f)
            regime_data["history"] = existing.get("history", [])
        except:
            pass

    regime_data["history"].append(result)
    regime_data["history"] = regime_data["history"][-90:]  # Keep last 90 days

    with open(MARKET_REGIME_FILE, "w") as f:
        json.dump(regime_data, f, indent=2)

    log(f"Regime: {result['regime']} (confidence {result['confidence']})")
    return result


def get_current_regime():
    """Read the current market regime from file."""
    if not os.path.exists(MARKET_REGIME_FILE):
        return None
    try:
        with open(MARKET_REGIME_FILE) as f:
            data = json.load(f)
        return data.get("current")
    except:
        return None


# ---------------------------------------------------------------------------
# 3. Strategy Optimizer
# ---------------------------------------------------------------------------

def optimize_strategies(closed_trades):
    """Analyze closed trades for patterns and suggest parameter changes."""
    if not closed_trades:
        log("No closed trades to optimize")
        return None

    log(f"Optimizing strategies — {len(closed_trades)} closed trades")

    trades_text = json.dumps(closed_trades[:50], indent=2, default=str)  # Cap at 50

    system_prompt = (
        "You are a quantitative trading strategist reviewing closed trade performance. "
        "Find patterns and suggest specific parameter improvements. Always respond with valid JSON."
    )

    user_prompt = f"""Analyze these closed trades and identify what's working and what's failing.

CLOSED TRADES:
{trades_text}

Each trade has: ticker, strategy, entry_date, exit_date, pnl, pnl_pct, entry_reason, exit_reason

Respond in this exact JSON format:
{{
    "overall_grade": "A through F",
    "winning_patterns": [
        "pattern 1 that correlates with winning trades",
        "pattern 2..."
    ],
    "losing_patterns": [
        "pattern 1 that correlates with losing trades",
        "pattern 2..."
    ],
    "recommendations": [
        {{
            "parameter": "specific parameter to change",
            "current": "what it seems to be now",
            "suggested": "what it should be",
            "reasoning": "why this change would help"
        }}
    ],
    "strategy_breakdown": {{
        "strategy_name": {{
            "win_rate": "estimated %",
            "avg_pnl": "estimated average",
            "verdict": "keep/modify/drop"
        }}
    }},
    "summary": "2-3 sentence overall assessment"
}}"""

    result = ask_deepseek(system_prompt, user_prompt, max_tokens=3000)
    if not result:
        log("Strategy optimization failed — no AI response")
        return None

    # Ensure required fields
    result.setdefault("overall_grade", "C")
    result.setdefault("winning_patterns", [])
    result.setdefault("losing_patterns", [])
    result.setdefault("recommendations", [])

    result["timestamp"] = datetime.now().isoformat()
    result["trades_analyzed"] = len(closed_trades)

    with open(STRATEGY_REVIEW_FILE, "w") as f:
        json.dump(result, f, indent=2)

    log(f"Strategy grade: {result['overall_grade']} — {len(result['recommendations'])} recommendations")
    return result


# ---------------------------------------------------------------------------
# Main — demo regime detection
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log("=" * 50)
    log("DeepSeek Analyst — demo regime detection")

    regime = detect_regime(vix=18.5, sp500_change=-0.3, breadth=1.2)
    if regime:
        print(f"\nRegime: {regime['regime']}")
        print(f"Confidence: {regime['confidence']}")
        print(f"Reasoning: {regime.get('reasoning', '')}")
        adj = regime.get("adjustments", {})
        print(f"Position size mult: {adj.get('position_size_mult', 1.0)}")
        print(f"Aggression: {adj.get('aggression', 'normal')}")
        print(f"Avoid entries: {adj.get('avoid_entries', False)}")
        print(f"Hedge up: {adj.get('hedge_up', False)}")
    else:
        print("Regime detection failed — check API keys")

    log("=" * 50)
