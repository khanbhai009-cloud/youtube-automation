import os
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID")
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")
CHANNEL_ID    = os.getenv("YOUTUBE_CHANNEL_ID", "")   # optional, auto-detected if empty

# Niche keyword mapping for video-to-niche classification
_NICHE_KEYWORDS = {
    "psychology": ["psychology", "psych", "brain", "mind", "manipulation", "cognitive",
                   "behavior", "behaviour", "narcissism", "emotional", "persuasion"],
    "facts":      ["facts", "science", "history", "space", "animal", "body", "world",
                   "record", "ancient", "civilization"],
    "listicles":  ["list", "top ", "things you", "habits", "signs", "ways to", "types of",
                   "tips", "tricks", "hacks"],
}


def _get_analytics():
    creds = Credentials(
        token=None, refresh_token=REFRESH_TOKEN,
        client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


def _get_youtube():
    creds = Credentials(
        token=None, refresh_token=REFRESH_TOKEN,
        client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _classify_niche(title: str) -> str:
    """Classify a video title into a niche using keyword matching."""
    title_lower = title.lower()
    for niche, keywords in _NICHE_KEYWORDS.items():
        if any(kw in title_lower for kw in keywords):
            return niche
    return "facts"  # default niche


def compute_niche_scores(analytics: dict) -> dict:
    """
    Compute a performance score for each niche based on the last 5 videos.

    Score formula per video:
        niche_score = (views * 0.4) + (likes * 0.3) + (watch_time_percentage * 0.3)

    Returns:
        {"facts": 8.2, "psychology": 6.1, "listicles": 5.0}
        Empty dict if analytics unavailable or no top_videos.
    """
    if not analytics.get("available") or not analytics.get("top_videos"):
        return {}

    top_videos = analytics["top_videos"][:5]
    recent_titles = analytics.get("recent_titles", [])

    niche_scores_raw: dict[str, list] = {}

    for i, video in enumerate(top_videos):
        views       = video.get("views", 0)
        likes       = video.get("likes", 0)
        watch_pct   = video.get("avg_view_pct", 0.0)

        # Try to match title from recent_titles list (same order as top_videos)
        title = recent_titles[i] if i < len(recent_titles) else ""
        niche = _classify_niche(title)

        # Normalize: scale views and likes to 0-10 range relative to list max
        raw_score = (views * 0.4) + (likes * 0.3) + (watch_pct * 0.3)
        niche_scores_raw.setdefault(niche, []).append(raw_score)

    if not niche_scores_raw:
        return {}

    # Average per niche, then normalize to 0-10 scale
    all_avgs = {}
    for niche, scores in niche_scores_raw.items():
        all_avgs[niche] = sum(scores) / len(scores)

    max_val = max(all_avgs.values()) if all_avgs else 1.0
    if max_val == 0:
        return {}

    normalized = {
        niche: round((avg / max_val) * 10, 1)
        for niche, avg in all_avgs.items()
    }

    print(f"[ANALYTICS] Niche scores: {normalized}")
    return normalized


def fetch_channel_analytics(days: int = 28) -> dict:
    """
    Returns a structured snapshot of channel performance.
    Falls back to empty defaults if API unavailable.
    """
    end   = datetime.now(timezone.utc).date()
    start = (datetime.now(timezone.utc) - timedelta(days=days)).date()

    try:
        ya = _get_analytics()
        yt = _get_youtube()

        # Overall metrics
        overall = ya.reports().query(
            ids="channel==MINE",
            startDate=str(start),
            endDate=str(end),
            metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,annotationClickThroughRate",
            dimensions="day",
        ).execute()

        # Per-video performance
        video_perf = ya.reports().query(
            ids="channel==MINE",
            startDate=str(start),
            endDate=str(end),
            metrics="views,averageViewPercentage,likes,comments,estimatedMinutesWatched",
            dimensions="video",
            sort="-views",
            maxResults=10,
        ).execute()

        # Traffic source / device split
        traffic = ya.reports().query(
            ids="channel==MINE",
            startDate=str(start),
            endDate=str(end),
            metrics="views",
            dimensions="trafficSourceType",
        ).execute()

        # Best upload hours (from video publish times vs view spikes)
        hour_perf = ya.reports().query(
            ids="channel==MINE",
            startDate=str(start),
            endDate=str(end),
            metrics="views",
            dimensions="hour",
            sort="-views",
            maxResults=5,
        ).execute()

        # Recent video titles + stats
        recent_videos = yt.search().list(
            part="snippet",
            channelId=CHANNEL_ID or "mine",
            order="date",
            maxResults=10,
            type="video",
        ).execute()

        # Parse top performing video data
        top_videos = []
        for row in (video_perf.get("rows") or [])[:5]:
            vid_id, views, avg_pct, likes, comments, watch_mins = row
            top_videos.append({
                "video_id":    vid_id,
                "views":       int(views),
                "avg_view_pct": round(float(avg_pct), 1),
                "likes":       int(likes),
                "comments":    int(comments),
                "watch_mins":  int(watch_mins),
            })

        # Best upload hours
        best_hours = []
        for row in (hour_perf.get("rows") or []):
            best_hours.append({"hour_utc": int(row[0]), "views": int(row[1])})

        # Traffic sources
        traffic_map = {}
        for row in (traffic.get("rows") or []):
            traffic_map[row[0]] = int(row[1])

        # Recent video titles for pattern analysis
        recent_titles = [
            item["snippet"]["title"]
            for item in (recent_videos.get("items") or [])
        ]

        print(f"[ANALYTICS] Fetched {days}d data. Top video views: {top_videos[0]['views'] if top_videos else 0}")
        return {
            "top_videos":      top_videos,
            "best_hours_utc":  best_hours,
            "traffic_sources": traffic_map,
            "recent_titles":   recent_titles,
            "period_days":     days,
            "available":       True,
        }

    except Exception as e:
        print(f"[ANALYTICS] API failed: {e}. Using defaults.")
        return {
            "top_videos":      [],
            "best_hours_utc":  [{"hour_utc": 1, "views": 0}],
            "traffic_sources": {},
            "recent_titles":   [],
            "period_days":     days,
            "available":       False,
            "error":           str(e),
        }
