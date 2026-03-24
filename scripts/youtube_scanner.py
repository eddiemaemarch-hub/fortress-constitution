"""YouTube Scanner — Financial YouTube Intelligence for Rudy v2.0
Scans YouTube for recent videos about watchlist tickers from top finance channels.
Uses YouTube Data API v3 for search + Gemini for summarization/sentiment.
Part of Rudy v2.0 Trading System — Constitution v50.0
"""
import os
import sys
import json
import subprocess
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import telegram

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
YT_INTEL_FILE = os.path.join(DATA_DIR, "youtube_intel.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
YT_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

WATCHLIST = {
    "system1": ["MSTR", "IBIT", "Bitcoin", "MicroStrategy"],
    "trader3": ["CCJ", "UEC", "uranium", "XOM", "CVX", "OXY", "energy stocks"],
    "trader4": ["GME", "AMC", "SOFI", "RIVN", "short squeeze"],
    "trader5": ["NVDA", "TSLA", "AMD", "META", "AMZN", "NFLX"],
    "10x_hunters": [
        "10x stock 2026", "best growth stock to buy now", "stock that could 10x",
        "next Tesla stock", "penny stock breakout", "small cap moonshot",
        "JOBY stock", "eVTOL stocks", "AI penny stocks", "quantum computing stocks",
        "space stocks IPO", "biotech breakout", "next big thing stock",
    ],
}

# Investment & trader-focused YouTube channels
FINANCE_CHANNELS = [
    # Options / Active Trading
    "InTheMoney", "tastylive", "Unusual Whales", "ClayTrader",
    "Humbled Trader", "Ross Cameron", "SMB Capital", "Option Alpha",
    "Sky View Trading", "projectfinance", "Trading Fraternity",
    # Investment / Macro Analysis
    "Meet Kevin", "Steven Van Metre", "Patrick Boyle", "Adam Khoo",
    "Tom Nash", "Financial Education", "Andrei Jikh",
    # Energy / Uranium / Commodities
    "Crux Investor", "Brandon Munro", "Mike Alkin",
    # Meme / Squeeze
    "Trey's Trades", "Matt Kohrs", "Kenan Grace",
    # MSTR / Bitcoin
    "Simply Bitcoin", "Bitcoin Magazine",
    # Priority — Aristotle Investments
    "Aristotle Investments",
]

# Priority channels to always search by name (ensures we catch their latest uploads)
PRIORITY_CHANNELS = [
    "Aristotle Investments",
]

# Hours to look back for videos
LOOKBACK_HOURS = 24


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[YouTube {ts}] {msg}")
    with open(f"{LOG_DIR}/youtube.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"

# yt-dlp binary — check common locations
import shutil
YTDLP_BIN = shutil.which("yt-dlp") or os.path.expanduser("~/Library/Python/3.9/bin/yt-dlp")
if not os.path.isfile(YTDLP_BIN):
    YTDLP_BIN = "yt-dlp"  # hope it's on PATH


def youtube_search(query, max_results=5, lookback_hours=None):
    """Search YouTube for recent videos. Tries YouTube API first, falls back to Tavily, then yt-dlp."""
    # Try YouTube Data API v3 first
    videos = _youtube_api_search(query, max_results, lookback_hours=lookback_hours)
    if videos:
        return videos

    # Fallback: use Tavily to search YouTube
    videos = _tavily_youtube_search(query, max_results)
    if videos:
        return videos

    # Final fallback: yt-dlp search
    return _ytdlp_search(query, max_results)


def channel_search(channel_name, max_results=10):
    """Search for recent videos FROM a specific YouTube channel.
    Uses YouTube API channelId lookup, then lists their uploads.
    Falls back to Tavily, then yt-dlp."""
    if not GOOGLE_API_KEY:
        log(f"No GOOGLE_API_KEY — falling back to yt-dlp for channel search")
        videos = _ytdlp_channel_videos(channel_name, max_results)
        if videos:
            return videos
        return _tavily_youtube_search(f"{channel_name} youtube channel", max_results)

    # Step 1: Find the channel ID
    try:
        r = requests.get(YT_SEARCH_URL, params={
            "part": "snippet",
            "q": channel_name,
            "type": "channel",
            "maxResults": 3,
            "key": GOOGLE_API_KEY,
        }, timeout=15)
        data = r.json()

        if "error" in data:
            log(f"YouTube API error on channel search — falling back to yt-dlp")
            videos = _ytdlp_channel_videos(channel_name, max_results)
            if videos:
                return videos
            return _tavily_youtube_search(f"{channel_name} youtube channel latest video", max_results)

        channel_id = None
        for item in data.get("items", []):
            channel_id = item["snippet"]["channelId"]
            found_name = item["snippet"]["channelTitle"]
            log(f"Found channel: {found_name} (ID: {channel_id})")
            break

        if not channel_id:
            log(f"No channel found for '{channel_name}' — trying yt-dlp")
            videos = _ytdlp_channel_videos(channel_name, max_results)
            if videos:
                return videos
            return youtube_search(channel_name, max_results, lookback_hours=168)

    except Exception as e:
        log(f"Channel lookup error: {e}")
        videos = _ytdlp_channel_videos(channel_name, max_results)
        if videos:
            return videos
        return _tavily_youtube_search(f"{channel_name} youtube channel latest video", max_results)

    # Step 2: Get recent videos from this channel (last 7 days)
    try:
        published_after = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(YT_SEARCH_URL, params={
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "publishedAfter": published_after,
            "maxResults": max_results,
            "key": GOOGLE_API_KEY,
        }, timeout=15)
        data = r.json()

        if "error" in data:
            log(f"YouTube API error listing channel videos: {data['error']}")
            return []

        videos = []
        for item in data.get("items", []):
            snippet = item["snippet"]
            videos.append({
                "video_id": item["id"]["videoId"],
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "published": snippet["publishedAt"],
                "description": snippet["description"][:300],
            })

        log(f"Found {len(videos)} recent videos from channel '{channel_name}'")
        return videos

    except Exception as e:
        log(f"Channel video list error: {e}")
        return []


def _youtube_api_search(query, max_results=5, lookback_hours=None):
    """Search via YouTube Data API v3."""
    if not GOOGLE_API_KEY:
        return []

    hours = lookback_hours or LOOKBACK_HOURS
    published_after = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        r = requests.get(YT_SEARCH_URL, params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "date",
            "publishedAfter": published_after,
            "maxResults": max_results,
            "relevanceLanguage": "en",
            "key": GOOGLE_API_KEY,
        }, timeout=15)
        data = r.json()

        if "error" in data:
            log(f"YouTube API blocked/error — falling back to Tavily")
            return []

        videos = []
        for item in data.get("items", []):
            snippet = item["snippet"]
            videos.append({
                "video_id": item["id"]["videoId"],
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "published": snippet["publishedAt"],
                "description": snippet["description"][:300],
            })
        return videos

    except Exception as e:
        log(f"YouTube API error: {e}")
        return []


def _tavily_youtube_search(query, max_results=5):
    """Fallback: search YouTube via Tavily web search."""
    if not TAVILY_API_KEY:
        log("No TAVILY_API_KEY set — cannot search YouTube")
        return []

    try:
        r = requests.post(TAVILY_URL, json={
            "api_key": TAVILY_API_KEY,
            "query": f"site:youtube.com {query}",
            "max_results": max_results,
            "search_depth": "basic",
            "include_domains": ["youtube.com"],
        }, timeout=15)
        data = r.json()

        videos = []
        for item in data.get("results", []):
            url = item.get("url", "")
            # Extract video ID from YouTube URL
            vid_id = ""
            if "watch?v=" in url:
                vid_id = url.split("watch?v=")[1].split("&")[0]
            elif "youtu.be/" in url:
                vid_id = url.split("youtu.be/")[1].split("?")[0]

            if not vid_id:
                continue

            title = item.get("title", "")
            # Try to extract channel from title (often "Title - Channel")
            channel = "Unknown"
            if " - YouTube" in title:
                title = title.replace(" - YouTube", "")

            videos.append({
                "video_id": vid_id,
                "title": title,
                "channel": channel,
                "published": datetime.utcnow().isoformat() + "Z",
                "description": item.get("content", "")[:300],
            })

        log(f"Tavily found {len(videos)} YouTube results for: {query}")
        return videos

    except Exception as e:
        log(f"Tavily YouTube search error: {e}")
        return []


def _ytdlp_search(query, max_results=5):
    """Final fallback: use yt-dlp to search YouTube directly (no API key needed)."""
    try:
        cmd = [
            YTDLP_BIN, f"ytsearch{max_results}:{query}",
            "--dump-json", "--flat-playlist", "--no-download",
            "--no-warnings", "--quiet",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log(f"yt-dlp search failed: {result.stderr[:200]}")
            return []

        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                videos.append({
                    "video_id": data.get("id", ""),
                    "title": data.get("title", ""),
                    "channel": data.get("channel", data.get("uploader", "Unknown")),
                    "published": data.get("upload_date", ""),
                    "description": (data.get("description") or "")[:300],
                })
            except json.JSONDecodeError:
                continue

        log(f"yt-dlp found {len(videos)} results for: {query}")
        return videos

    except subprocess.TimeoutExpired:
        log("yt-dlp search timed out")
        return []
    except FileNotFoundError:
        log("yt-dlp not installed")
        return []
    except Exception as e:
        log(f"yt-dlp search error: {e}")
        return []


def _ytdlp_channel_videos(channel_name, max_results=10):
    """Use yt-dlp to get recent videos from a YouTube channel (no API key needed)."""
    try:
        # Search for the channel first, then get their uploads
        cmd = [
            YTDLP_BIN, f"ytsearch1:{channel_name} youtube channel",
            "--dump-json", "--flat-playlist", "--no-download",
            "--no-warnings", "--quiet",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # Try to get channel URL from the first result
        channel_url = None
        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout.strip().split("\n")[0])
                channel_url = data.get("channel_url") or data.get("uploader_url")
            except (json.JSONDecodeError, IndexError):
                pass

        if not channel_url:
            # Try direct channel URL format
            slug = channel_name.replace(" ", "")
            channel_url = f"https://www.youtube.com/@{slug}"

        # Get recent uploads from channel
        cmd = [
            YTDLP_BIN, f"{channel_url}/videos",
            "--dump-json", "--flat-playlist", "--no-download",
            "--no-warnings", "--quiet",
            "--playlist-end", str(max_results),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if result.returncode != 0:
            log(f"yt-dlp channel fetch failed: {result.stderr[:200]}")
            return []

        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                videos.append({
                    "video_id": data.get("id", ""),
                    "title": data.get("title", ""),
                    "channel": data.get("channel", data.get("uploader", "Unknown")),
                    "published": data.get("upload_date", ""),
                    "description": (data.get("description") or "")[:300],
                })
            except json.JSONDecodeError:
                continue

        log(f"yt-dlp found {len(videos)} channel videos for: {channel_name}")
        return videos

    except subprocess.TimeoutExpired:
        log("yt-dlp channel fetch timed out")
        return []
    except FileNotFoundError:
        log("yt-dlp not installed")
        return []
    except Exception as e:
        log(f"yt-dlp channel error: {e}")
        return []


def get_video_stats(video_ids):
    """Get view counts for videos."""
    if not video_ids or not GOOGLE_API_KEY:
        return {}

    try:
        r = requests.get(YT_VIDEOS_URL, params={
            "part": "statistics",
            "id": ",".join(video_ids),
            "key": GOOGLE_API_KEY,
        }, timeout=15)
        data = r.json()

        stats = {}
        for item in data.get("items", []):
            s = item["statistics"]
            stats[item["id"]] = {
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
            }
        return stats

    except Exception as e:
        log(f"Video stats error: {e}")
        return {}


def ask_gemini(prompt, max_tokens=2000):
    """Call Gemini for summarization/sentiment analysis."""
    api_key = GEMINI_API_KEY or GOOGLE_API_KEY
    if not api_key:
        log("No Gemini/Google API key")
        return None

    try:
        r = requests.post(
            f"{GEMINI_URL}?key={api_key}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": max_tokens,
                },
            },
            timeout=60,
        )
        data = r.json()

        if "candidates" not in data:
            log(f"Gemini error: {data.get('error', data)}")
            return None

        content = data["candidates"][0]["content"]["parts"][0]["text"]

        # Extract JSON
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
            log("Could not parse Gemini JSON")
            return {"raw_text": cleaned}

    except Exception as e:
        log(f"Gemini error: {e}")
        return None


def scan_youtube():
    """Full YouTube scan for all watchlist tickers."""
    log("=" * 50)
    log("Starting YouTube intelligence scan")

    all_videos = []
    seen_ids = set()

    # Priority channels — always grab their latest videos
    for channel in PRIORITY_CHANNELS:
        log(f"Priority channel search: {channel}")
        videos = youtube_search(channel, max_results=5)
        for v in videos:
            if v["video_id"] not in seen_ids:
                v["system"] = "priority"
                v["search_term"] = channel
                v["priority"] = True
                all_videos.append(v)
                seen_ids.add(v["video_id"])

    # Search for each system's tickers
    for system, terms in WATCHLIST.items():
        for term in terms:
            query = f"{term} stock analysis"
            log(f"Searching: {query}")
            videos = youtube_search(query, max_results=3)
            for v in videos:
                if v["video_id"] not in seen_ids:
                    v["system"] = system
                    v["search_term"] = term
                    all_videos.append(v)
                    seen_ids.add(v["video_id"])

    if not all_videos:
        log("No recent videos found")
        return None

    log(f"Found {len(all_videos)} unique videos")

    # Get view stats
    stats = get_video_stats([v["video_id"] for v in all_videos])
    for v in all_videos:
        s = stats.get(v["video_id"], {})
        v["views"] = s.get("views", 0)
        v["likes"] = s.get("likes", 0)

    # Sort by views (most popular first)
    all_videos.sort(key=lambda x: x["views"], reverse=True)

    # Use Gemini to analyze the video titles/descriptions for trading signals
    video_summaries = []
    for v in all_videos[:20]:  # Top 20 by views
        video_summaries.append(
            f"- [{v['channel']}] \"{v['title']}\" ({v['views']:,} views) "
            f"[{v['system']}/{v['search_term']}]: {v['description']}"
        )

    prompt = f"""You are a trading intelligence analyst. Analyze these recent YouTube finance videos
and extract actionable trading signals for our options trading system.

Our watchlist systems:
- system1: MSTR/IBIT lottery calls & bear puts
- trader3: Energy/Uranium momentum options (CCJ, UEC, XOM, CVX, OXY)
- trader4: Short squeeze options (GME, AMC, SOFI, RIVN)
- trader5: Breakout momentum options (NVDA, TSLA, AMD, META, AMZN, NFLX)

Recent YouTube videos (last {LOOKBACK_HOURS}h):
{chr(10).join(video_summaries)}

Respond in this exact JSON format:
{{
    "summary": "3-5 sentence overview of what finance YouTube is buzzing about",
    "overall_sentiment": "bullish/bearish/neutral/mixed",
    "signals": [
        {{
            "ticker": "SYMBOL",
            "signal": "buy/sell/watch",
            "confidence": "high/medium/low",
            "reason": "why this signal matters, citing specific videos/channels",
            "source_channel": "channel name"
        }}
    ],
    "hot_tickers": ["tickers getting the most YouTube coverage"],
    "catalysts": ["upcoming catalysts mentioned in videos"],
    "risks": ["bearish signals or risks discussed"],
    "notable_videos": [
        {{
            "title": "video title",
            "channel": "channel name",
            "ticker": "primary ticker discussed",
            "sentiment": "bullish/bearish/neutral",
            "views": 12345
        }}
    ]
}}

Only generate signals supported by the video content. Do not fabricate."""

    result = ask_gemini(prompt)
    if not result:
        # Fallback: just report the raw videos without AI analysis
        log("Gemini analysis failed — sending raw video report")
        result = {
            "summary": f"Found {len(all_videos)} recent finance videos. Gemini analysis unavailable.",
            "overall_sentiment": "unknown",
            "signals": [],
            "hot_tickers": list(set(v["search_term"] for v in all_videos[:10])),
            "catalysts": [],
            "risks": [],
            "notable_videos": [
                {
                    "title": v["title"],
                    "channel": v["channel"],
                    "ticker": v["search_term"],
                    "sentiment": "unknown",
                    "views": v["views"],
                }
                for v in all_videos[:10]
            ],
        }

    # Ensure required fields
    result.setdefault("summary", "")
    result.setdefault("overall_sentiment", "neutral")
    result.setdefault("signals", [])
    result.setdefault("hot_tickers", [])
    result.setdefault("catalysts", [])
    result.setdefault("risks", [])
    result.setdefault("notable_videos", [])

    # Add metadata
    result["timestamp"] = datetime.now().isoformat()
    result["scanner"] = "youtube"
    result["videos_found"] = len(all_videos)

    # Save intel
    _save_intel(result)

    # Send Telegram alert
    alert = format_alert(result)
    log(alert)
    try:
        telegram.send(alert)
    except Exception:
        pass

    log("YouTube scan complete")
    log("=" * 50)
    return result


def _is_channel_name(query):
    """Detect if query looks like a channel name vs a stock ticker.
    Channel names: multiple words, lowercase, spaces, special chars.
    Tickers: 1-5 uppercase letters."""
    q = query.strip()
    if len(q) <= 5 and q.isalpha() and q.isupper():
        return False  # Looks like a ticker (MSTR, NVDA, etc.)
    if " " in q or len(q) > 6 or not q.isalpha():
        return True  # Multi-word or special chars = channel name
    return False


def quick_scan(ticker):
    """Quick YouTube scan for a single ticker or channel name."""
    log(f"Quick scan: {ticker}")

    # Detect channel name vs ticker
    if _is_channel_name(ticker):
        log(f"Detected channel name: {ticker} — using channel search")
        videos = channel_search(ticker, max_results=10)
        if not videos:
            # Broaden: try as a general query with 7-day lookback
            videos = youtube_search(ticker, max_results=10, lookback_hours=168)
        if not videos:
            msg = f"No recent YouTube videos from channel '{ticker}'"
            log(msg)
            return msg
    else:
        videos = youtube_search(f"{ticker} stock analysis", max_results=10)
        if not videos:
            msg = f"No recent YouTube videos for {ticker}"
            log(msg)
            return msg

    stats = get_video_stats([v["video_id"] for v in videos])
    for v in videos:
        s = stats.get(v["video_id"], {})
        v["views"] = s.get("views", 0)
        v["likes"] = s.get("likes", 0)

    videos.sort(key=lambda x: x["views"], reverse=True)

    video_text = "\n".join(
        f"- [{v['channel']}] \"{v['title']}\" ({v['views']:,} views): {v['description']}"
        for v in videos[:10]
    )

    prompt = f"""Analyze these recent YouTube videos about ${ticker} for trading signals.

Videos:
{video_text}

Respond in JSON:
{{
    "ticker": "{ticker}",
    "summary": "2-3 sentence overview",
    "sentiment": "bullish/bearish/neutral/mixed",
    "signals": [
        {{
            "signal": "buy/sell/watch",
            "confidence": "high/medium/low",
            "reason": "specific explanation citing videos",
            "source_channel": "channel name"
        }}
    ],
    "catalysts": ["upcoming catalysts mentioned"],
    "risks": ["risks discussed"]
}}"""

    result = ask_gemini(prompt, max_tokens=1500)
    if not result:
        # Fallback without AI
        lines = [f"YOUTUBE SCAN: ${ticker}", f"Found {len(videos)} recent videos", ""]
        for v in videos[:5]:
            lines.append(f"  [{v['channel']}] {v['title']} ({v['views']:,} views)")
        alert = "\n".join(lines)
        try:
            telegram.send(alert)
        except Exception:
            pass
        return alert

    result.setdefault("ticker", ticker)
    result.setdefault("summary", "No data")
    result.setdefault("sentiment", "neutral")
    result.setdefault("signals", [])

    # Save
    intel = {
        "timestamp": datetime.now().isoformat(),
        "scanner": "youtube",
        "type": "quick_scan",
        "ticker": ticker,
        "overall_sentiment": result.get("sentiment", "neutral"),
        "summary": result.get("summary", ""),
        "signals": result.get("signals", []),
        "catalysts": result.get("catalysts", []),
        "risks": result.get("risks", []),
        "hot_tickers": [ticker],
        "notable_videos": [],
        "videos_found": len(videos),
    }
    _save_intel(intel)

    # Format
    lines = [
        f"YOUTUBE SCAN: ${ticker}",
        f"Sentiment: {result['sentiment'].upper()}",
        f"Videos: {len(videos)}",
        "",
        result["summary"],
    ]

    for s in result.get("signals", []):
        lines.append(f"  {s.get('signal', '?').upper()} ({s.get('confidence', '?')}) — {s.get('reason', '')[:100]}")
        if s.get("source_channel"):
            lines.append(f"    via {s['source_channel']}")

    if result.get("catalysts"):
        lines.append(f"\nCatalysts: {', '.join(result['catalysts'][:5])}")
    if result.get("risks"):
        lines.append(f"Risks: {', '.join(result['risks'][:3])}")

    alert = "\n".join(lines)
    try:
        telegram.send(alert)
    except Exception:
        pass

    return alert


def analyze_video(video_url_or_id):
    """Deep-analyze a YouTube video: pull transcript, send to Grok for strategy extraction.
    Accepts a full URL (https://youtu.be/xxx or https://youtube.com/watch?v=xxx) or just a video ID.
    """
    import re
    # Extract video ID
    vid = video_url_or_id
    m = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", video_url_or_id)
    if m:
        vid = m.group(1)

    log(f"Deep analyzing video: {vid}")

    # Get transcript
    transcript_text = ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(vid)
        transcript_text = " ".join(snippet.text for snippet in transcript.snippets[:500])
        log(f"Transcript: {len(transcript_text)} chars")
    except Exception as e:
        log(f"Transcript error: {e}")

    # Get video title/description via yt-dlp
    title = ""
    description = ""
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--skip-download", "--print", "%(title)s|||%(description)s",
             f"https://youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=15,
        )
        parts = result.stdout.strip().split("|||", 1)
        title = parts[0] if parts else ""
        description = parts[1][:500] if len(parts) > 1 else ""
    except Exception as e:
        log(f"yt-dlp metadata error: {e}")

    if not transcript_text and not title:
        return "Could not fetch video content"

    # Send to Grok for analysis
    grok_key = os.environ.get("GROK_API_KEY", os.environ.get("XAI_API_KEY", ""))
    if not grok_key:
        # Fallback to Gemini
        prompt = f"""Analyze this YouTube finance video for trading signals and strategy ideas.

Title: {title}
Description: {description[:300]}
Transcript (first ~3000 chars):
{transcript_text[:3000]}

Return JSON:
{{
    "title": "{title}",
    "summary": "3-5 sentence summary of the video's key points",
    "tickers_mentioned": ["TICKER1", "TICKER2"],
    "strategies_discussed": ["strategy 1 description", "strategy 2 description"],
    "sentiment": "bullish/bearish/neutral/mixed",
    "key_data_points": ["data point 1", "data point 2"],
    "actionable_ideas": ["specific trade idea 1", "specific trade idea 2"],
    "relevance_to_options": "how this applies to options trading"
}}
Return ONLY valid JSON."""

        result = ask_gemini(prompt)
        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2) if result else "Analysis failed"

    # Grok analysis
    try:
        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {grok_key}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-fast-latest",
                "messages": [
                    {"role": "system", "content": "You are a financial video analyst. Extract trading strategies, tickers, and actionable insights from YouTube finance video transcripts."},
                    {"role": "user", "content": f"""Analyze this YouTube finance video:

Title: {title}
Description: {description[:300]}
Transcript:
{transcript_text[:4000]}

Extract:
1. All tickers/stocks mentioned
2. Specific strategies discussed (entry/exit rules, allocations)
3. Key data points and statistics cited
4. Bullish/bearish arguments made
5. How this applies to options trading
6. Actionable trade ideas

Be specific and detailed. Format as structured JSON:
{{
    "title": "video title",
    "summary": "3-5 sentences",
    "tickers_mentioned": ["TICKER1"],
    "strategies_discussed": ["detailed strategy 1"],
    "sentiment": "bullish/bearish/neutral/mixed",
    "key_data_points": ["stat 1"],
    "actionable_ideas": ["trade idea 1"],
    "relevance_to_options": "how this applies to our options trading"
}}"""},
                ],
                "temperature": 0.3,
                "max_tokens": 2000,
            },
            timeout=60,
        )
        data = r.json()
        content = data["choices"][0]["message"]["content"]

        # Parse JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content.strip())
        log(f"Video analysis complete: {result.get('title', vid)}")

        # Format for return
        lines = [
            f"VIDEO ANALYSIS: {result.get('title', title)}",
            f"Sentiment: {result.get('sentiment', 'N/A').upper()}",
            f"Tickers: {', '.join(result.get('tickers_mentioned', []))}",
            "",
            result.get("summary", ""),
            "",
        ]
        for s in result.get("strategies_discussed", []):
            lines.append(f"Strategy: {s}")
        for i in result.get("actionable_ideas", []):
            lines.append(f"Idea: {i}")
        if result.get("relevance_to_options"):
            lines.append(f"\nOptions: {result['relevance_to_options']}")

        return "\n".join(lines)

    except Exception as e:
        log(f"Grok video analysis error: {e}")
        return f"Analysis error: {e}"


def format_alert(intel):
    """Format YouTube intelligence for Telegram alert."""
    lines = [
        "YOUTUBE INTELLIGENCE REPORT",
        f"Sentiment: {intel.get('overall_sentiment', 'N/A').upper()}",
        f"Videos scanned: {intel.get('videos_found', 0)}",
        "",
        intel.get("summary", "")[:400],
        "",
    ]

    # High confidence signals
    high_signals = [s for s in intel.get("signals", []) if s.get("confidence") == "high"]
    if high_signals:
        lines.append("HIGH CONFIDENCE SIGNALS:")
        for s in high_signals[:5]:
            ch = s.get("source_channel", "")
            lines.append(f"  {s['ticker']} -> {s['signal'].upper()} (via {ch})")
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

    # Notable videos
    if intel.get("notable_videos"):
        lines.append("\nTOP VIDEOS:")
        for v in intel["notable_videos"][:5]:
            lines.append(f"  [{v.get('channel', '?')}] {v.get('title', '')[:80]}")
            lines.append(f"    {v.get('sentiment', '?').upper()} | {v.get('views', 0):,} views")

    # Catalysts / Risks
    if intel.get("catalysts"):
        lines.append(f"\nCatalysts: {', '.join(intel['catalysts'][:5])}")
    if intel.get("risks"):
        lines.append(f"\nRisks: {', '.join(intel['risks'][:3])}")

    return "\n".join(lines)


def get_latest_intel():
    """Read the latest YouTube intel from file."""
    if not os.path.exists(YT_INTEL_FILE):
        return None
    try:
        with open(YT_INTEL_FILE) as f:
            history = json.load(f)
        return history[-1] if history else None
    except Exception:
        return None


def _save_intel(intel):
    """Save intelligence report to history file (keep last 50)."""
    history = []
    if os.path.exists(YT_INTEL_FILE):
        try:
            with open(YT_INTEL_FILE) as f:
                history = json.load(f)
        except Exception:
            history = []

    history.append(intel)
    history = history[-50:]

    with open(YT_INTEL_FILE, "w") as f:
        json.dump(history, f, indent=2)
    log(f"Intel saved to {YT_INTEL_FILE}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = quick_scan(sys.argv[1])
        print(result)
    else:
        scan_youtube()
