# 🎬 USA YouTube AI Factory

Autonomous multi-agent system that generates and uploads 3-4 minute psychology/facts/list videos to YouTube — fully hands-free.

## Stack
| Component | Tool |
|-----------|------|
| Orchestration | LangGraph StateGraph |
| LLM | Groq (primary) → Cerebras (fallback) |
| Research | Tavily + Google Trends (pytrends) |
| Audio | Edge-TTS (en-US-GuyNeural) |
| Video | MoviePy + FFmpeg |
| Upload | YouTube Data API v3 |
| Logging | Google Sheets API |
| Scheduler | APScheduler |
| Backend | FastAPI |

## HuggingFace Spaces Setup

### 1. Create Space
- Type: **Docker** or **Gradio** (pick Docker)
- Hardware: **CPU Basic** (2 vCPU, 16GB RAM) ✅

### 2. Add Secrets (Settings > Variables and Secrets)
Copy all keys from `.env.example` and add them as secrets.

### 3. Get YouTube Refresh Token
```bash
# On your PC (one-time):
pip install google-auth-oauthlib
python get_youtube_token.py
# Copy the refresh_token from the output
```

### 4. Google Sheets Setup
1. Create a Google Sheet with any name
2. Create a Service Account in Google Cloud Console
3. Share the sheet with the service account email
4. Copy the JSON key content → `GOOGLE_SHEETS_CREDENTIALS` secret
5. Copy the Sheet ID from URL → `SPREADSHEET_ID` secret

## Auto Schedule (USA EST)
| Niche | Days | Time |
|-------|------|------|
| Psychology | Mon, Wed, Fri | 8:00 AM |
| Facts | Tue, Thu | 8:00 AM |
| Lists | Saturday | 9:00 AM |

## Manual Trigger
Hit the dashboard at your Space URL and click **Generate Video Now**.

## API Endpoints
- `GET /` — Dashboard
- `POST /run` — Trigger pipeline `{"niche": "psychology", "schedule_upload": true}`
- `GET /status` — Current pipeline status
- `GET /history` — Last 20 videos
- `GET /schedule` — Upcoming scheduled jobs
- `GET /health` — Health check

## Video Style: "Plain & Paint"
- White background
- Colored illustrated icons (pop-up animation)
- Bold subtitles synced to voiceover
- 1920×1080 @ 24fps
- USA accent TTS (Edge-TTS)
