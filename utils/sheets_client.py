import os
import json
from datetime import datetime
import gspread
from google.oauth2.credentials import Credentials

# Scopes wahi rahenge jo token mein hain
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")

_client = None

def _get_sheet():
    global _client
    if _client is None:
        # Ab hum 'YOUTUBE_TOKEN_JSON' secret se data uthayenge
        token_json = os.getenv("YOUTUBE_TOKEN_JSON", "")
        if not token_json:
            raise ValueError("❌ YOUTUBE_TOKEN_JSON env var not set in Secrets!")
        
        try:
            creds_dict = json.loads(token_json)
            # YAHAN CHANGE HAI: Service account ki jagah User OAuth use kar rahe hain
            creds = Credentials.from_authorized_user_info(creds_dict, scopes=SCOPES)
            _client = gspread.authorize(creds)
            print("✅ [SHEETS] Authorized successfully using User OAuth Token!")
        except Exception as e:
            print(f"❌ [SHEETS] Auth failed: {e}")
            raise

    return _client.open_by_key(SPREADSHEET_ID).sheet1

def ensure_headers():
    try:
        sheet = _get_sheet()
        first_row = sheet.row_values(1)
        headers = ["Topic", "Script_Text", "Audio_Path", "Thumbnail_URL",
                   "Status", "Upload_Time", "YouTube_URL", "Tags"]
        if first_row != headers:
            # Agar sheet khali hai ya headers alag hain, toh naya insert karo
            sheet.insert_row(headers, 1)
            print("✅ [SHEETS] Headers ensured.")
    except Exception as e:
        print(f"[SHEETS] Header check failed: {e}")

def log_video(data: dict):
    try:
        sheet = _get_sheet()
        row = [
            data.get("topic", ""),
            data.get("script", "")[:500] + "...",  # Chhota kar diya sheet ke liye
            data.get("audio_path", ""),
            data.get("thumbnail_url", ""),
            data.get("status", "Draft"),
            datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            data.get("youtube_url", ""),
            ", ".join(data.get("tags", [])) if isinstance(data.get("tags"), list) else data.get("tags", ""),
        ]
        sheet.append_row(row)
        print(f"[SHEETS] Logged: {data.get('topic')}")
    except Exception as e:
        print(f"[SHEETS] Log failed: {e}")

def update_status(topic: str, status: str, youtube_url: str = ""):
    try:
        sheet = _get_sheet()
        records = sheet.get_all_records()
        # Row 2 se start kyunki 1 mein headers hain
        for i, row in enumerate(records, start=2):
            if row.get("Topic") == topic:
                # Column 5 'Status' hai aur Column 7 'YouTube_URL'
                sheet.update_cell(i, 5, status)
                if youtube_url:
                    sheet.update_cell(i, 7, youtube_url)
                print(f"[SHEETS] Updated status for: {topic} -> {status}")
                break
    except Exception as e:
        print(f"[SHEETS] Status update failed: {e}")
