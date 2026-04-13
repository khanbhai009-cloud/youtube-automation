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
CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID")
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")

# USA prime time zones (Eastern): 8 PM EST = 01:00 UTC next day
USA_UPLOAD_HOUR_UTC   = 1
USA_UPLOAD_MINUTE_UTC = 0

_TOKEN_VALIDATE_URL = "https://www.googleapis.com/youtube/v3/channels?part=id&mine=true"
_TOKEN_REFRESH_URL  = "https://oauth2.googleapis.com/token"


def _refresh_access_token() -> str:
    """
    Use the refresh token to obtain a new access token.
    Returns the new access token string, or raises on failure.
    """
    resp = httpx.post(
        _TOKEN_REFRESH_URL,
        data={
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
            "grant_type":    "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise ValueError(f"Token refresh returned no access_token: {data}")
    return token


def _validate_token(access_token: str) -> bool:
    """
    Check whether an access token is still valid.
    Returns True if valid (HTTP 200), False on 401.
    """
    try:
        resp = httpx.get(
            _TOKEN_VALIDATE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _get_youtube_service(access_token: str = None):
    """
    Build a YouTube API service.
    If access_token is provided, use it directly; otherwise use refresh token flow.
    """
    if access_token:
        creds = Credentials(token=access_token)
    else:
        creds = Credentials(
            token=None,
            refresh_token=REFRESH_TOKEN,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            token_uri=_TOKEN_REFRESH_URL,
        )
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _get_next_publish_time(hour_utc: int = None) -> str:
    """Returns ISO 8601 datetime for next USA prime time slot."""
    now      = datetime.now(timezone.utc)
    use_hour = hour_utc if hour_utc is not None else USA_UPLOAD_HOUR_UTC
    publish  = now.replace(hour=use_hour, minute=USA_UPLOAD_MINUTE_UTC, second=0, microsecond=0)
    if publish <= now:
        publish += timedelta(days=1)
    return publish.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _do_upload(youtube, video_path: str, body: dict) -> dict:
    """Execute the chunked upload and return the API response."""
    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024,
    )

    request  = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    retry    = 0

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

    return response


def upload_video(
    video_path:     str,
    title:          str,
    description:    str,
    tags:           list,
    schedule:       bool = True,
    upload_hour_utc: int = 1,
    state:          dict = None,
) -> dict:
    """
    Uploads video to YouTube with automatic token validation and refresh.

    Token flow (Step 8):
      1. Build credentials via refresh token
      2. Validate token with a lightweight GET to YouTube API
      3. If 401 → refresh token, retry once
      4. If refresh also fails → set upload_status = UPLOAD_FAILED, never fake URL

    Returns: { "video_id": ..., "url": ..., "status": ... }
    """
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        err = "YouTube OAuth credentials not set in env vars"
        if state is not None:
            state["upload_status"] = "UPLOAD_FAILED"
            state["youtube_url"]   = None
            state.setdefault("logs", []).append(f"❌ Upload skipped: {err}")
        raise ValueError(err)

    print(f"[UPLOAD] Starting upload: {title}")

    # ── Step 8: Token validation + refresh ───────────────────────────────────
    access_token = None
    try:
        # Get initial access token via refresh token
        access_token = _refresh_access_token()
        print("[UPLOAD] Token obtained successfully")

        # Validate token
        if not _validate_token(access_token):
            print("[UPLOAD] Token validation failed (401) — refreshing...")
            access_token = _refresh_access_token()
            if not _validate_token(access_token):
                raise PermissionError("Token refresh succeeded but validation still fails")

        print("[UPLOAD] Token validated ✅")

    except Exception as token_err:
        print(f"[UPLOAD] Token error: {token_err}")
        if state is not None:
            state["upload_status"] = "UPLOAD_FAILED"
            state["youtube_url"]   = None
            state.setdefault("logs", []).append(f"❌ Upload failed (token): {token_err}")
        raise RuntimeError(f"YouTube token error: {token_err}") from token_err

    # ── Build upload body ─────────────────────────────────────────────────────
    body = {
        "snippet": {
            "title":                title[:100],
            "description":          description,
            "tags":                 tags[:15],
            "categoryId":           "27",
            "defaultLanguage":      "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus":           "private" if schedule else "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    if schedule:
        body["status"]["publishAt"]     = _get_next_publish_time(upload_hour_utc)
        body["status"]["privacyStatus"] = "private"
        print(f"[UPLOAD] Scheduled for: {body['status']['publishAt']}")

    # ── Upload with retry on token expiry mid-upload ──────────────────────────
    try:
        youtube  = _get_youtube_service(access_token=access_token)
        response = _do_upload(youtube, video_path, body)

    except Exception as upload_err:
        err_str = str(upload_err)
        # If the error is auth-related, retry once with a fresh token
        if "401" in err_str or "invalid_grant" in err_str or "unauthorized" in err_str.lower():
            print(f"[UPLOAD] Auth error during upload — refreshing token and retrying...")
            try:
                access_token = _refresh_access_token()
                youtube      = _get_youtube_service(access_token=access_token)
                response     = _do_upload(youtube, video_path, body)
            except Exception as retry_err:
                if state is not None:
                    state["upload_status"] = "UPLOAD_FAILED"
                    state["youtube_url"]   = None
                    state.setdefault("logs", []).append(f"❌ Upload failed after token refresh: {retry_err}")
                raise RuntimeError(f"Upload failed after token refresh: {retry_err}") from retry_err
        else:
            if state is not None:
                state["upload_status"] = "UPLOAD_FAILED"
                state["youtube_url"]   = None
                state.setdefault("logs", []).append(f"❌ Upload error: {upload_err}")
            raise

    video_id = response["id"]
    url      = f"https://www.youtube.com/watch?v={video_id}"
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
