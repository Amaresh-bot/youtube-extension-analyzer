"""
app.py — YouTube Activity Analyzer Backend v4
=============================================
Run:
    pip install fastapi uvicorn python-dotenv google-api-python-client groq
    uvicorn app:app --reload --port 8001

Endpoints:
    GET  /            → serves dashboard.html
    GET  /tracking    → returns youtube_tracking.json (absolute path safe)
    POST /analyze     → live YouTube stats for a video_id
    POST /narrative   → Groq AI narrative for a video_id
"""

import os
import json
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from googleapiclient.discovery import build
from groq import Groq

load_dotenv()

YT_API_KEY   = os.getenv("YT_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not YT_API_KEY:
    raise RuntimeError("YT_API_KEY is not set in your .env file")

# Always resolve files relative to this script, not the cwd
BASE_DIR       = Path(__file__).parent.resolve()
TRACKING_FILE  = BASE_DIR / "youtube_tracking.json"
DASHBOARD_FILE = BASE_DIR / "dashboard.html"

app = FastAPI(title="YouTube Activity Analyzer", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ─── Schemas ──────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    video_id: str

class NarrativeRequest(BaseModel):
    video_id: str

class AnalyzeResponse(BaseModel):
    video_id: str
    title: str
    channel: str
    views: int
    likes: int
    comments: int
    engagement_rate: float
    insight: str

# ─── YouTube helpers ──────────────────────────────────────────────────────────

def get_youtube_service():
    return build("youtube", "v3", developerKey=YT_API_KEY)


def compute_insight(engagement_rate: float) -> str:
    if engagement_rate > 5.0:
        return "High engagement"
    elif engagement_rate >= 1.0:
        return "Average performance"
    else:
        return "Low engagement"


def fetch_video_stats(video_id: str) -> dict:
    youtube = get_youtube_service()
    try:
        response = youtube.videos().list(
            part="snippet,statistics",
            id=video_id
        ).execute()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"YouTube API error: {exc}")

    items = response.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail=f"Video '{video_id}' not found")

    item       = items[0]
    snippet    = item["snippet"]
    statistics = item.get("statistics", {})

    views    = int(statistics.get("viewCount",    0))
    likes    = int(statistics.get("likeCount",    0))
    comments = int(statistics.get("commentCount", 0))
    engagement_rate = round((likes + comments) / views * 100, 2) if views > 0 else 0.0

    return {
        "video_id":        video_id,
        "title":           snippet.get("title", "Unknown"),
        "channel":         snippet.get("channelTitle", "Unknown"),
        "views":           views,
        "likes":           likes,
        "comments":        comments,
        "engagement_rate": engagement_rate,
        "insight":         compute_insight(engagement_rate),
    }

# ─── Groq helpers ─────────────────────────────────────────────────────────────

def build_prompt(stats: dict, history: list) -> str:
    """Build a rich prompt from live stats + historical tracking data."""
    trend_summary = ""
    if len(history) >= 2:
        first  = history[0]
        latest = history[-1]
        view_growth = latest["view_count"] - first["view_count"]
        try:
            days = max(1, (
                datetime.fromisoformat(latest["timestamp"]) -
                datetime.fromisoformat(first["timestamp"])
            ).days)
        except Exception:
            days = 1
        daily_avg = view_growth // days if days > 0 else view_growth
        trend_summary = f"""
Historical tracking ({len(history)} data points over {days} days):
- Total view growth : +{view_growth:,} views
- Daily average     : ~{daily_avg:,} views/day
- Interactions (first → latest): {first['like_count'] + first['comment_count']:,} → {latest['like_count'] + latest['comment_count']:,}
"""

    return f"""You are a YouTube analytics expert. Analyze this video's performance and write a concise, actionable 3-4 sentence narrative.

Video  : {stats['title']}
Channel: {stats['channel']}
Views  : {stats['views']:,}
Likes  : {stats['likes']:,}
Comments: {stats['comments']:,}
Engagement rate: {stats['engagement_rate']}%
{trend_summary}
Cover:
1. How this video is performing and why
2. What the engagement rate reveals about the audience
3. One concrete, specific recommendation for the creator

Be direct. No generic filler. Max 4 sentences."""


def call_groq(prompt: str) -> str:
    """Call Groq API using llama-3.3-70b-versatile — fast and free."""
    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",   # best free Groq model
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=300,
    )
    return response.choices[0].message.content.strip()

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    if not DASHBOARD_FILE.exists():
        raise HTTPException(status_code=404, detail="dashboard.html not found next to app.py")
    return HTMLResponse(content=DASHBOARD_FILE.read_text(encoding="utf-8"))


@app.get("/tracking")
def get_tracking_data():
    """Return youtube_tracking.json resolved relative to app.py."""
    if not TRACKING_FILE.exists():
        return JSONResponse(content={})
    with open(TRACKING_FILE, "r", encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    video_id = request.video_id.strip()
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id must not be empty")
    return AnalyzeResponse(**fetch_video_stats(video_id))


@app.post("/narrative")
def narrative(request: NarrativeRequest):
    """
    Generate a Groq AI narrative for a video.
    Combines live YouTube stats + historical tracking for richer analysis.
    Returns: { "narrative": "...", "video_id": "...", "stats": {...} }
    """
    if not GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY not set in .env")

    video_id = request.video_id.strip()
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id must not be empty")

    # Fetch live stats
    stats = fetch_video_stats(video_id)

    # Load historical tracking data for this video if available
    history = []
    if TRACKING_FILE.exists():
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            tracking = json.load(f)
        history = tracking.get(video_id, [])

    # Call Groq
    try:
        prompt = build_prompt(stats, history)
        narrative_text = call_groq(prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc}")

    return {"video_id": video_id, "narrative": narrative_text, "stats": stats}


# ─── Auto-track endpoint ──────────────────────────────────────────────────────

class TrackRequest(BaseModel):
    video_id: str


@app.post("/track")
def track_video(request: TrackRequest):
    """
    Called automatically by the Chrome extension every time the user
    opens a YouTube video. Fetches live stats and appends a timestamped
    snapshot to youtube_tracking.json — exactly like youtube_data.py does,
    but triggered by browsing instead of a manual script run.

    Returns: { video_id, title, total_snapshots }
    """
    video_id = request.video_id.strip()
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id must not be empty")

    # Fetch live stats from YouTube API
    stats = fetch_video_stats(video_id)

    # Build the snapshot (same structure as youtube_data.py)
    from datetime import datetime
    snapshot = {
        "timestamp":     datetime.now().isoformat(),
        "title":         stats["title"],
        "channel_title": stats["channel"],
        "view_count":    stats["views"],
        "like_count":    stats["likes"],
        "comment_count": stats["comments"],
    }

    # Load existing tracking data
    if TRACKING_FILE.exists():
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            tracking = json.load(f)
    else:
        tracking = {}

    # Append snapshot under this video's ID
    if video_id not in tracking:
        tracking[video_id] = []
        print(f"[Track] New video added to tracking: {stats['title']}")
    else:
        print(f"[Track] Snapshot appended for: {stats['title']} ({len(tracking[video_id])+1} total)")

    tracking[video_id].append(snapshot)

    # Save back to file
    with open(TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(tracking, f, indent=2, ensure_ascii=False)

    return {
        "video_id":        video_id,
        "title":           stats["title"],
        "total_snapshots": len(tracking[video_id]),
        "engagement_rate": stats["engagement_rate"],
        "insight":         stats["insight"],
    }