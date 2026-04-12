# YouTube AI Factory

An autonomous multi-agent system that generates and uploads 3-4 minute niche YouTube videos (psychology, facts, listicles) fully hands-free.

## Architecture

- **Backend**: FastAPI + Uvicorn, served on port 5000
- **Orchestration**: LangGraph StateGraph pipeline
- **LLMs**: Groq (primary) + Cerebras (fallback)
- **Audio**: Kokoro TTS (local) + gTTS fallback
- **Video**: FFmpeg for assembly, Ken Burns effects, subtitle burn-in
- **Research**: Tavily API + pytrends (Google Trends)
- **Image Gen**: Google Imagen + Pollinations.ai fallback
- **Tracking**: Google Sheets API
- **Scheduler**: APScheduler (cron jobs per niche)

## Project Layout

```
app.py               - FastAPI entrypoint + scheduler
graph/workflow.py    - LangGraph pipeline definition
agents/
  director_agent.py  - Strategic niche/topic selection
  research_agent.py  - Trending topic research (Tavily + pytrends)
  script_agent.py    - Script generation + timeline
  production_agent.py- TTS, image gen, FFmpeg rendering
  upload_agent.py    - YouTube Data API upload
  analytics_agent.py - YouTube Analytics fetching
  image_manager.py   - Image generation (Imagen/Pollinations)
utils/
  llm_client.py      - Groq + Cerebras LLM wrapper (lazy init)
  sheets_client.py   - Google Sheets logging
tools/xml_analyzer.py- Alight Motion XML → GSAP animation parser
static/index.html    - Dashboard UI
```

## Environment Variables Required

Set these in Secrets to enable full functionality:

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | LLM (primary) |
| `CEREBRAS_API_KEY` | LLM (fallback) |
| `TAVILY_API_KEY` | Research/search |
| `YOUTUBE_CLIENT_ID` | YouTube OAuth |
| `YOUTUBE_CLIENT_SECRET` | YouTube OAuth |
| `YOUTUBE_REFRESH_TOKEN` | YouTube OAuth |
| `YOUTUBE_TOKEN_JSON` | Google Sheets auth |
| `SPREADSHEET_ID` | Google Sheets ID |
| `YOUTUBE_CHANNEL_ID` | Channel analytics |
| `RAPIDAPI_KEY` | Optional image APIs |

## Workflow

The app starts with `uvicorn app:app --host 0.0.0.0 --port 5000 --reload` in development.

All API clients are lazily initialized — the app starts and serves the dashboard even without API keys configured.

## Pipeline Stages

1. **Director** → Analyzes trends + channel analytics, picks niche/topic/strategy
2. **Research** → Google Trends + Tavily deep research
3. **Script** → LLM generates script + visual timeline
4. **Production** → TTS narration → Whisper timestamps → AI images → FFmpeg video
5. **Upload** → YouTube Data API (scheduled or immediate)
