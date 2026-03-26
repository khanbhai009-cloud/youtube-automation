import os
import json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")

_client = None

def _get_sheet():
    global _client
    if _client is None:
        creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")
        if not creds_json:
            raise ValueError("GOOGLE_SHEETS_CREDENTIALS env var not set")
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client.open_by_key(SPREADSHEET_ID).sheet1

def ensure_headers():
    try:
        sheet = _get_sheet()
        first_row = sheet.row_values(1)
        headers = ["Topic", "Script_Text", "Audio_Path", "Thumbnail_URL",
                   "Status", "Upload_Time", "YouTube_URL", "Tags"]
        if first_row != headers:
            sheet.insert_row(headers, 1)
    except Exception as e:
        print(f"[SHEETS] Header check failed: {e}")

def log_video(data: dict):
    """
    data keys: topic, script, audio_path, thumbnail_url,
                status, youtube_url, tags
    """
    try:
        sheet = _get_sheet()
        row = [
            data.get("topic", ""),
            data.get("script", "")[:500] + "...",  # truncate for sheet
            data.get("audio_path", ""),
            data.get("thumbnail_url", ""),
            data.get("status", "Draft"),
            datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            data.get("youtube_url", ""),
            ", ".join(data.get("tags", [])),
        ]
        sheet.append_row(row)
        print(f"[SHEETS] Logged: {data.get('topic')}")
    except Exception as e:
        print(f"[SHEETS] Log failed: {e}")

def update_status(topic: str, status: str, youtube_url: str = ""):
    try:
        sheet = _get_sheet()
        records = sheet.get_all_records()
        for i, row in enumerate(records, start=2):
            if row.get("Topic") == topic:
                sheet.update_cell(i, 5, status)
                if youtube_url:
                    sheet.update_cell(i, 7, youtube_url)
                print(f"[SHEETS] Updated status for: {topic} -> {status}")
                break
    except Exception as e:
        print(f"[SHEETS] Status update failed: {e}")
