import os
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ── OAuth2 config ────────────────────────────────────────────────────────────
CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")

# USA prime time zones (Eastern): 8 PM EST = 01:00 UTC next day
USA_UPLOAD_HOUR_UTC = 1   # 8 PM Eastern = 01:00 UTC
USA_UPLOAD_MINUTE_UTC = 0


def _get_youtube_service():
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _get_next_publish_time() -> str:
    """Returns ISO 8601 datetime for next USA prime time slot."""
    now = datetime.now(timezone.utc)
    publish = now.replace(hour=USA_UPLOAD_HOUR_UTC, minute=USA_UPLOAD_MINUTE_UTC, second=0, microsecond=0)
    if publish <= now:
        publish += timedelta(days=1)
    return publish.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    schedule: bool = True,
) -> dict:
    """
    Uploads video to YouTube.
    Returns: { "video_id": ..., "url": ..., "status": ... }
    """
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        raise ValueError("YouTube OAuth credentials not set in env vars")
    
    print(f"[UPLOAD] Starting upload: {title}")
    youtube = _get_youtube_service()
    
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags[:15],
            "categoryId": "27",  # Education
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "private" if schedule else "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    
    if schedule:
        body["status"]["publishAt"] = _get_next_publish_time()
        body["status"]["privacyStatus"] = "private"
        print(f"[UPLOAD] Scheduled for: {body['status']['publishAt']}")
    
    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024,  # 5MB chunks
    )
    
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )
    
    response = None
    retry = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"[UPLOAD] Progress: {pct}%")
        except Exception as e:
            if retry < 3:
                retry += 1
                print(f"[UPLOAD] Chunk error (retry {retry}): {e}")
                time.sleep(2 ** retry)
            else:
                raise
    
    video_id = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"[UPLOAD] Done! {url}")
    
    return {"video_id": video_id, "url": url, "status": "scheduled" if schedule else "public"}


def add_thumbnail(video_id: str, thumbnail_path: str):
    """Upload custom thumbnail to the video."""
    if not Path(thumbnail_path).exists():
        print(f"[UPLOAD] Thumbnail not found: {thumbnail_path}")
        return
    try:
        youtube = _get_youtube_service()
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
        ).execute()
        print(f"[UPLOAD] Thumbnail added to video {video_id}")
    except Exception as e:
        print(f"[UPLOAD] Thumbnail upload failed: {e}")
