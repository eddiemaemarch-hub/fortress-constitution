"""X/Twitter Influencer Tracker — Deep monitoring of finance influencers.
Uses Grok (native X access) instead of X API v2 — no Bearer Token needed.
Claude Code for signal extraction via CLI.
SQLite for storage. Telegram for alerts.
Part of Rudy v2.0 Trading System — Constitution v42.0
"""
import os
import sys
import json
import sqlite3
import subprocess
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
DB_FILE = os.path.join(DATA_DIR, "x_tracker.db")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

GROK_API_KEY = os.environ.get("GROK_API_KEY", os.environ.get("XAI_API_KEY", ""))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"

# Tracked accounts — add new ones here (one line each)
TRACKED_ACCOUNTS = {
    "nolimitgains": {"category": "insider_data", "poll_hours": 2, "priority": "high"},
    "unusual_whales": {"category": "options_flow", "poll_hours": 2, "priority": "high"},
    "DeItaone": {"category": "breaking_news", "poll_hours": 1, "priority": "high"},
    "aristotlegrowth": {"category": "education", "poll_hours": 6, "priority": "medium"},
    "CathieDWood": {"category": "ark_trades", "poll_hours": 4, "priority": "medium"},
    "michaeljburry": {"category": "macro_contrarian", "poll_hours": 6, "priority": "high"},
    "jimcramer": {"category": "sentiment_contrarian", "poll_hours": 4, "priority": "low"},
    "Mr_Derivatives": {"category": "options_flow", "poll_hours": 2, "priority": "medium"},
    "gabortrading": {"category": "trade_ideas", "poll_hours": 4, "priority": "medium"},
    "WallStreetBets": {"category": "retail_sentiment", "poll_hours": 2, "priority": "medium"},
    "optionsflow": {"category": "options_flow", "poll_hours": 2, "priority": "medium"},
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[X-Tracker {ts}] {msg}")
    with open(f"{LOG_DIR}/x_tracker.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            handle TEXT PRIMARY KEY,
            category TEXT,
            poll_hours INTEGER DEFAULT 2,
            priority TEXT DEFAULT 'medium',
            last_scanned TEXT,
            total_posts_tracked INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            handle TEXT NOT NULL,
            post_summary TEXT,
            post_date TEXT,
            tickers TEXT,
            sentiment TEXT,
            signal_level TEXT DEFAULT 'low',
            views TEXT,
            likes TEXT,
            retweets TEXT,
            links TEXT,
            raw_analysis TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(handle, post_summary)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS extracted_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            handle TEXT,
            ticker TEXT,
            signal_type TEXT,
            direction TEXT,
            confidence TEXT,
            insider_data TEXT,
            reasoning TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(post_id) REFERENCES posts(id)
        )
    """)
    conn.commit()
    return conn


def ask_grok(prompt, max_tokens=3000):
    """Call Grok API for X data access."""
    if not GROK_API_KEY:
        log("No Grok API key")
        return None
    try:
        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-fast-latest",
                "messages": [
                    {"role": "system", "content": "You are a financial intelligence analyst with native X/Twitter access. Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        data = r.json()
        if "choices" not in data:
            log(f"Grok error: {data.get('error', data)}")
            return None
        content = data["choices"][0]["message"]["content"]
        # Parse JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return json.loads(content.strip())
    except json.JSONDecodeError:
        log("Grok returned non-JSON")
        return None
    except Exception as e:
        log(f"Grok error: {e}")
        return None


def ask_gemini(prompt):
    """Use Gemini for signal extraction (free tier, saves Grok quota)."""
    if not GEMINI_API_KEY:
        return None
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return json.loads(content.strip())
    except Exception as e:
        log(f"Gemini error: {e}")
        return None


def fetch_account_posts(handle, count=20):
    """Fetch recent posts from an X account via Grok."""
    config = TRACKED_ACCOUNTS.get(handle, {})
    category = config.get("category", "general")

    prompt = f"""Look up the most recent {count} posts from @{handle} on X/Twitter.

For each post, extract:
- post_summary: the full text (or as much as you can see)
- post_date: when it was posted (YYYY-MM-DD HH:MM or approximate)
- tickers: any stock tickers mentioned ($NVDA, etc.)
- views: approximate view count
- likes: approximate like count
- retweets: approximate retweet count
- links: any URLs or images referenced
- sentiment: bullish / bearish / neutral
- signal_level: high / medium / low (how actionable is this for trading?)

This account's category is: {category}

Return JSON:
{{
    "handle": "@{handle}",
    "posts": [
        {{
            "post_summary": "full text",
            "post_date": "2026-03-11 10:00",
            "tickers": ["NVDA", "PLTR"],
            "views": "50K",
            "likes": "2.1K",
            "retweets": "500",
            "links": ["url1"],
            "sentiment": "bearish",
            "signal_level": "high"
        }}
    ],
    "account_summary": "2-3 sentence summary of what @{handle} is focused on right now"
}}

Only include real posts. Do not fabricate content."""

    return ask_grok(prompt)


def extract_signals(posts_data, handle):
    """Extract trading signals from posts using Gemini."""
    if not posts_data or not posts_data.get("posts"):
        return []

    posts_text = json.dumps(posts_data["posts"][:10], indent=2)

    prompt = f"""Analyze these X/Twitter posts from @{handle} for trading signals.

POSTS:
{posts_text}

For each post that contains actionable trading information, extract signals:
Return JSON array:
[
    {{
        "post_index": 0,
        "ticker": "SYMBOL",
        "signal_type": "insider_sell/insider_buy/options_flow/sentiment/technical/catalyst/warning",
        "direction": "bullish/bearish/neutral",
        "confidence": "high/medium/low",
        "insider_data": "Name sold $XM of TICKER on DATE (if applicable, else null)",
        "reasoning": "why this is a signal"
    }}
]

Focus on:
- Insider trading data (Form 4 filings, CEO/CFO sells/buys, amounts)
- Unusual options activity (large block trades, sweeps)
- Breaking catalysts (earnings, FDA, contracts)
- Sentiment shifts
Return ONLY the JSON array. Empty array [] if no signals found."""

    return ask_gemini(prompt) or []


def scan_account(handle):
    """Full scan of one X account."""
    log(f"Scanning @{handle}")

    posts_data = fetch_account_posts(handle)
    if not posts_data:
        log(f"No data for @{handle}")
        return None

    posts = posts_data.get("posts", [])
    log(f"@{handle}: {len(posts)} posts fetched")

    # Extract signals
    signals = extract_signals(posts_data, handle)
    log(f"@{handle}: {len(signals)} signals extracted")

    # Store in DB
    conn = init_db()
    c = conn.cursor()

    # Upsert account
    c.execute("""
        INSERT INTO accounts (handle, category, poll_hours, priority, last_scanned, total_posts_tracked)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(handle) DO UPDATE SET
            last_scanned = excluded.last_scanned,
            total_posts_tracked = total_posts_tracked + excluded.total_posts_tracked
    """, (
        handle,
        TRACKED_ACCOUNTS.get(handle, {}).get("category", "general"),
        TRACKED_ACCOUNTS.get(handle, {}).get("poll_hours", 2),
        TRACKED_ACCOUNTS.get(handle, {}).get("priority", "medium"),
        datetime.now().isoformat(),
        len(posts),
    ))

    new_posts = 0
    high_signals = []

    for i, post in enumerate(posts):
        tickers = json.dumps(post.get("tickers", []))
        try:
            c.execute("""
                INSERT OR IGNORE INTO posts (handle, post_summary, post_date, tickers, sentiment, signal_level, views, likes, retweets, links)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                handle,
                post.get("post_summary", "")[:1000],
                post.get("post_date", ""),
                tickers,
                post.get("sentiment", "neutral"),
                post.get("signal_level", "low"),
                str(post.get("views", "")),
                str(post.get("likes", "")),
                str(post.get("retweets", "")),
                json.dumps(post.get("links", [])),
            ))
            if c.rowcount > 0:
                new_posts += 1
                post_id = c.lastrowid

                # Store extracted signals for this post
                for sig in signals:
                    if sig.get("post_index") == i:
                        c.execute("""
                            INSERT INTO extracted_signals (post_id, handle, ticker, signal_type, direction, confidence, insider_data, reasoning)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            post_id, handle,
                            sig.get("ticker", ""),
                            sig.get("signal_type", ""),
                            sig.get("direction", ""),
                            sig.get("confidence", ""),
                            sig.get("insider_data"),
                            sig.get("reasoning", ""),
                        ))

                        if sig.get("confidence") == "high" or post.get("signal_level") == "high":
                            high_signals.append({
                                "handle": handle,
                                "post": post.get("post_summary", "")[:150],
                                "ticker": sig.get("ticker", ""),
                                "direction": sig.get("direction", ""),
                                "signal_type": sig.get("signal_type", ""),
                                "reasoning": sig.get("reasoning", "")[:100],
                            })
        except Exception as e:
            log(f"DB insert error: {e}")

    conn.commit()
    conn.close()

    log(f"@{handle}: {new_posts} new posts stored, {len(high_signals)} high signals")

    # Alert on high signals
    if high_signals:
        alert_lines = [f"X TRACKER HIGH SIGNAL: @{handle}"]
        for sig in high_signals[:3]:
            alert_lines.append(f"  ${sig['ticker']} {sig['direction'].upper()} ({sig['signal_type']})")
            alert_lines.append(f"  {sig['post'][:100]}")
            alert_lines.append(f"  {sig['reasoning']}")
            alert_lines.append("")
        telegram.send("\n".join(alert_lines))
        log("High signal alert sent")

    return {
        "handle": handle,
        "posts_fetched": len(posts),
        "new_posts": new_posts,
        "high_signals": len(high_signals),
        "signals": high_signals,
        "account_summary": posts_data.get("account_summary", ""),
    }


def scan_all():
    """Scan all tracked accounts."""
    log("=" * 50)
    log("Starting full X influencer scan")

    results = []
    for handle in TRACKED_ACCOUNTS:
        try:
            result = scan_account(handle)
            if result:
                results.append(result)
        except Exception as e:
            log(f"Error scanning @{handle}: {e}")

    # Save summary
    summary = {
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "accounts_scanned": len(results),
        "total_new_posts": sum(r.get("new_posts", 0) for r in results),
        "total_high_signals": sum(r.get("high_signals", 0) for r in results),
        "results": results,
    }

    summary_file = os.path.join(DATA_DIR, "x_tracker_latest.json")
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)

    log(f"Scan complete: {summary['accounts_scanned']} accounts, {summary['total_new_posts']} new posts, {summary['total_high_signals']} high signals")
    log("=" * 50)
    return summary


def quick_scan(handle):
    """Quick scan a single account."""
    return scan_account(handle)


def get_recent_signals(limit=20):
    """Get most recent extracted signals from DB."""
    conn = init_db()
    c = conn.cursor()
    c.execute("""
        SELECT s.handle, s.ticker, s.signal_type, s.direction, s.confidence,
               s.insider_data, s.reasoning, s.created_at
        FROM extracted_signals s
        ORDER BY s.created_at DESC
        LIMIT ?
    """, (limit,))
    signals = []
    for row in c.fetchall():
        signals.append({
            "handle": row[0], "ticker": row[1], "signal_type": row[2],
            "direction": row[3], "confidence": row[4],
            "insider_data": row[5], "reasoning": row[6], "time": row[7],
        })
    conn.close()
    return signals


def add_account(handle, category="general", poll_hours=2, priority="medium"):
    """Add a new account to track — one line of config."""
    TRACKED_ACCOUNTS[handle] = {
        "category": category,
        "poll_hours": poll_hours,
        "priority": priority,
    }
    log(f"Added @{handle} (category={category}, priority={priority})")


if __name__ == "__main__":
    env_file = os.path.expanduser("~/.agent_zero_env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

    if len(sys.argv) > 1:
        # Scan specific account
        result = scan_account(sys.argv[1])
        if result:
            print(json.dumps(result, indent=2))
    else:
        scan_all()
