"""YouTube Playlist Tracker — Monitors a playlist for changes over time.
Tracks: new videos, removed videos, view/engagement changes.
Uses: YouTube Data API v3 (with Tavily fallback).
Data stored in SQLite for historical tracking.
Part of Rudy v2.0 Trading System — Constitution v42.0
"""
import os
import sys
import json
import sqlite3
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import telegram

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
DB_FILE = os.path.join(DATA_DIR, "playlist_tracker.db")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"

# Tracked playlists
PLAYLISTS = {
    "main": "PLWHksn0KVTjLHcsf1aiYqL_VGis4Ycf4V",
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Playlist {ts}] {msg}")
    with open(f"{LOG_DIR}/playlist_tracker.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def init_db():
    """Initialize SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT NOT NULL,
            playlist_id TEXT NOT NULL,
            title TEXT,
            description TEXT,
            published_at TEXT,
            channel_title TEXT,
            position INTEGER,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            removed INTEGER DEFAULT 0,
            removed_at TEXT,
            PRIMARY KEY (video_id, playlist_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            playlist_id TEXT NOT NULL,
            snapshot_time TEXT DEFAULT CURRENT_TIMESTAMP,
            view_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id TEXT NOT NULL,
            scan_time TEXT DEFAULT CURRENT_TIMESTAMP,
            total_videos INTEGER,
            new_videos INTEGER DEFAULT 0,
            removed_videos INTEGER DEFAULT 0,
            summary TEXT
        )
    """)
    conn.commit()
    return conn


def fetch_playlist_api(playlist_id):
    """Fetch all videos from a YouTube playlist via Data API v3."""
    if not GOOGLE_API_KEY:
        log("No Google API key")
        return None

    videos = []
    next_page = None

    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
            "key": GOOGLE_API_KEY,
        }
        if next_page:
            params["pageToken"] = next_page

        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/playlistItems",
                params=params,
                timeout=15,
            )
            data = resp.json()

            if "error" in data:
                log(f"YouTube API error: {data['error'].get('message', data['error'])}")
                return None

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                vid = {
                    "video_id": snippet.get("resourceId", {}).get("videoId", ""),
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", "")[:500],
                    "published_at": snippet.get("publishedAt", ""),
                    "channel_title": snippet.get("channelTitle", ""),
                    "position": snippet.get("position", 0),
                }
                if vid["video_id"]:
                    videos.append(vid)

            next_page = data.get("nextPageToken")
            if not next_page:
                break
        except Exception as e:
            log(f"API fetch error: {e}")
            return None

    return videos


def fetch_video_stats(video_ids):
    """Fetch view/like/comment counts for a batch of videos."""
    if not GOOGLE_API_KEY or not video_ids:
        return {}

    stats = {}
    # API allows 50 IDs per request
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "statistics",
                    "id": ",".join(batch),
                    "key": GOOGLE_API_KEY,
                },
                timeout=15,
            )
            data = resp.json()
            for item in data.get("items", []):
                s = item.get("statistics", {})
                stats[item["id"]] = {
                    "view_count": int(s.get("viewCount", 0)),
                    "like_count": int(s.get("likeCount", 0)),
                    "comment_count": int(s.get("commentCount", 0)),
                }
        except Exception as e:
            log(f"Stats fetch error: {e}")

    return stats


def fetch_playlist_ytdlp(playlist_id):
    """Fallback: extract playlist data via yt-dlp (no API key needed)."""
    import subprocess as sp
    try:
        result = sp.run(
            [
                sys.executable, "-m", "yt_dlp", "--flat-playlist", "--dump-json",
                f"https://www.youtube.com/playlist?list={playlist_id}",
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log(f"yt-dlp error: {result.stderr[:200]}")
            return None

        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                videos.append({
                    "video_id": entry.get("id", ""),
                    "title": entry.get("title", ""),
                    "description": entry.get("description", "")[:500] if entry.get("description") else "",
                    "published_at": entry.get("upload_date", ""),
                    "channel_title": entry.get("channel", entry.get("uploader", "")),
                    "position": len(videos),
                })
            except json.JSONDecodeError:
                continue

        log(f"yt-dlp: {len(videos)} videos extracted")
        return videos if videos else None
    except Exception as e:
        log(f"yt-dlp error: {e}")
        return None


def diff_playlist(conn, playlist_id, current_videos):
    """Compare current videos against stored state. Returns changes."""
    c = conn.cursor()

    # Get previously known videos
    c.execute(
        "SELECT video_id, title FROM videos WHERE playlist_id = ? AND removed = 0",
        (playlist_id,)
    )
    known = {row[0]: row[1] for row in c.fetchall()}
    known_ids = set(known.keys())
    current_ids = {v["video_id"] for v in current_videos}

    # New videos
    new_ids = current_ids - known_ids
    new_videos = [v for v in current_videos if v["video_id"] in new_ids]

    # Removed videos
    removed_ids = known_ids - current_ids
    removed_videos = [{"video_id": vid, "title": known[vid]} for vid in removed_ids]

    return {
        "new": new_videos,
        "removed": removed_videos,
        "total_current": len(current_videos),
        "total_known": len(known_ids),
    }


def save_snapshot(conn, playlist_id, videos, stats):
    """Save current state to database."""
    c = conn.cursor()
    now = datetime.now().isoformat()

    for v in videos:
        # Upsert video
        c.execute("""
            INSERT INTO videos (video_id, playlist_id, title, description, published_at, channel_title, position, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id, playlist_id) DO UPDATE SET
                title = excluded.title,
                position = excluded.position,
                last_seen = excluded.last_seen,
                removed = 0,
                removed_at = NULL
        """, (
            v["video_id"], playlist_id, v["title"], v.get("description", ""),
            v.get("published_at", ""), v.get("channel_title", ""), v.get("position", 0), now
        ))

        # Save stats snapshot
        vid_stats = stats.get(v["video_id"], {})
        if vid_stats:
            c.execute("""
                INSERT INTO snapshots (video_id, playlist_id, snapshot_time, view_count, like_count, comment_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                v["video_id"], playlist_id, now,
                vid_stats.get("view_count", 0),
                vid_stats.get("like_count", 0),
                vid_stats.get("comment_count", 0),
            ))

    conn.commit()


def mark_removed(conn, playlist_id, removed_ids):
    """Mark videos as removed."""
    c = conn.cursor()
    now = datetime.now().isoformat()
    for vid in removed_ids:
        c.execute(
            "UPDATE videos SET removed = 1, removed_at = ? WHERE video_id = ? AND playlist_id = ?",
            (now, vid, playlist_id)
        )
    conn.commit()


def get_engagement_changes(conn, playlist_id, video_ids):
    """Get view count changes since last snapshot."""
    c = conn.cursor()
    changes = []

    for vid in video_ids[:20]:  # Limit to avoid huge queries
        c.execute("""
            SELECT view_count, like_count, snapshot_time
            FROM snapshots
            WHERE video_id = ? AND playlist_id = ?
            ORDER BY snapshot_time DESC
            LIMIT 2
        """, (vid, playlist_id))
        rows = c.fetchall()
        if len(rows) >= 2:
            current, previous = rows[0], rows[1]
            view_delta = current[0] - previous[0]
            like_delta = current[1] - previous[1]
            if view_delta > 0 or like_delta > 0:
                c.execute(
                    "SELECT title FROM videos WHERE video_id = ? AND playlist_id = ?",
                    (vid, playlist_id)
                )
                title_row = c.fetchone()
                changes.append({
                    "video_id": vid,
                    "title": title_row[0] if title_row else vid,
                    "view_delta": view_delta,
                    "like_delta": like_delta,
                    "total_views": current[0],
                })

    # Sort by view delta
    changes.sort(key=lambda x: x["view_delta"], reverse=True)
    return changes


def scan_playlist(playlist_name="main"):
    """Full scan of a tracked playlist."""
    playlist_id = PLAYLISTS.get(playlist_name)
    if not playlist_id:
        log(f"Unknown playlist: {playlist_name}")
        return None

    log(f"Scanning playlist: {playlist_name} ({playlist_id})")

    conn = init_db()

    # Fetch current videos
    videos = fetch_playlist_api(playlist_id)
    if videos is None:
        log("API failed, trying yt-dlp fallback")
        videos = fetch_playlist_ytdlp(playlist_id)
        if not videos:
            log("Both API and yt-dlp failed")
            conn.close()
            return None

    log(f"Fetched {len(videos)} videos from playlist")

    # Diff against stored state
    changes = diff_playlist(conn, playlist_id, videos)

    # Fetch stats
    video_ids = [v["video_id"] for v in videos]
    stats = fetch_video_stats(video_ids)
    log(f"Fetched stats for {len(stats)} videos")

    # Save snapshot
    save_snapshot(conn, playlist_id, videos, stats)

    # Mark removed
    if changes["removed"]:
        mark_removed(conn, playlist_id, [v["video_id"] for v in changes["removed"]])

    # Get engagement changes
    engagement = get_engagement_changes(conn, playlist_id, video_ids)

    # Log scan
    summary_parts = []
    if changes["new"]:
        summary_parts.append(f"{len(changes['new'])} new")
    if changes["removed"]:
        summary_parts.append(f"{len(changes['removed'])} removed")
    if engagement:
        summary_parts.append(f"{len(engagement)} with view changes")
    summary = ", ".join(summary_parts) if summary_parts else "No changes"

    c = conn.cursor()
    c.execute("""
        INSERT INTO scan_log (playlist_id, scan_time, total_videos, new_videos, removed_videos, summary)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        playlist_id, datetime.now().isoformat(), len(videos),
        len(changes["new"]), len(changes["removed"]), summary
    ))
    conn.commit()

    # Build report
    report = {
        "playlist": playlist_name,
        "playlist_id": playlist_id,
        "total_videos": len(videos),
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "changes": summary,
        "new_videos": [
            {"title": v["title"], "video_id": v["video_id"], "channel": v.get("channel_title", "")}
            for v in changes["new"]
        ],
        "removed_videos": changes["removed"],
        "top_engagement": engagement[:5],
    }

    log(f"Scan complete: {summary}")

    # Alert on new or removed videos
    if changes["new"] or changes["removed"]:
        alert_lines = [f"PLAYLIST TRACKER: {playlist_name}"]
        if changes["new"]:
            alert_lines.append(f"\nNEW ({len(changes['new'])}):")
            for v in changes["new"][:5]:
                alert_lines.append(f"  + {v['title']}")
        if changes["removed"]:
            alert_lines.append(f"\nREMOVED ({len(changes['removed'])}):")
            for v in changes["removed"][:5]:
                alert_lines.append(f"  - {v['title']}")
        telegram.send("\n".join(alert_lines))
        log("Telegram alert sent")

    conn.close()
    return report


def get_status(playlist_name="main"):
    """Get current status of a tracked playlist."""
    playlist_id = PLAYLISTS.get(playlist_name)
    if not playlist_id:
        return {"error": f"Unknown playlist: {playlist_name}"}

    conn = init_db()
    c = conn.cursor()

    c.execute(
        "SELECT COUNT(*) FROM videos WHERE playlist_id = ? AND removed = 0",
        (playlist_id,)
    )
    total = c.fetchone()[0]

    c.execute(
        "SELECT scan_time, summary FROM scan_log WHERE playlist_id = ? ORDER BY scan_time DESC LIMIT 1",
        (playlist_id,)
    )
    last_scan = c.fetchone()

    c.execute("""
        SELECT v.title, s.view_count, s.like_count
        FROM snapshots s JOIN videos v ON s.video_id = v.video_id AND s.playlist_id = v.playlist_id
        WHERE s.playlist_id = ?
        ORDER BY s.snapshot_time DESC, s.view_count DESC
        LIMIT 5
    """, (playlist_id,))
    top = [{"title": r[0], "views": r[1], "likes": r[2]} for r in c.fetchall()]

    conn.close()

    return {
        "playlist": playlist_name,
        "total_videos": total,
        "last_scan": last_scan[0] if last_scan else "Never",
        "last_summary": last_scan[1] if last_scan else "No scans yet",
        "top_videos": top,
    }


def add_playlist(name, playlist_id):
    """Add a new playlist to track."""
    PLAYLISTS[name] = playlist_id
    log(f"Added playlist: {name} = {playlist_id}")


if __name__ == "__main__":
    env_file = os.path.expanduser("~/.agent_zero_env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
    scan_playlist()
