import os
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID")
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")
CHANNEL_ID    = os.getenv("YOUTUBE_CHANNEL_ID", "")   # optional, auto-detected if empty


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

        # ── Overall metrics ───────────────────────────────────────────────
        overall = ya.reports().query(
            ids="channel==MINE",
            startDate=str(start),
            endDate=str(end),
            metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,annotationClickThroughRate",
            dimensions="day",
        ).execute()

        # ── Per-video performance ─────────────────────────────────────────
        video_perf = ya.reports().query(
            ids="channel==MINE",
            startDate=str(start),
            endDate=str(end),
            metrics="views,averageViewPercentage,likes,comments,estimatedMinutesWatched",
            dimensions="video",
            sort="-views",
            maxResults=10,
        ).execute()

        # ── Traffic source / device split ─────────────────────────────────
        traffic = ya.reports().query(
            ids="channel==MINE",
            startDate=str(start),
            endDate=str(end),
            metrics="views",
            dimensions="trafficSourceType",
        ).execute()

        # ── Best upload hours (from video publish times vs view spikes) ───
        hour_perf = ya.reports().query(
            ids="channel==MINE",
            startDate=str(start),
            endDate=str(end),
            metrics="views",
            dimensions="hour",
            sort="-views",
            maxResults=5,
        ).execute()

        # ── Recent video titles + stats ───────────────────────────────────
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
                "video_id": vid_id,
                "views": int(views),
                "avg_view_pct": round(float(avg_pct), 1),
                "likes": int(likes),
                "comments": int(comments),
                "watch_mins": int(watch_mins),
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
            "top_videos": top_videos,
            "best_hours_utc": best_hours,
            "traffic_sources": traffic_map,
            "recent_titles": recent_titles,
            "period_days": days,
            "available": True,
        }

    except Exception as e:
        print(f"[ANALYTICS] API failed: {e}. Using defaults.")
        return {
            "top_videos": [],
            "best_hours_utc": [{"hour_utc": 1, "views": 0}],   # 8 PM EST default
            "traffic_sources": {},
            "recent_titles": [],
            "period_days": days,
            "available": False,
            "error": str(e),
        }
