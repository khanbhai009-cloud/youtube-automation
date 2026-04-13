# YouTube AI Factory — Agentic Architecture v2

Fully Autonomous Multi-Agent System with feedback loops, state management, and tool-calling.
Generates and uploads 3-4 minute niche YouTube videos (psychology, facts, listicles) hands-free.

## Agent Roster

```
┌─────────────────────────────────────────────────────────────┐
│  1. Director Agent     → strategy brief + niche selection   │
│  2. Research Agent     → Tavily deep search + Google Trends │
│  3. Script Agent       → viral script JSON generation       │
│  4. Critic Agent ◄──┐  → quality evaluation (score 1-10)   │
│     Script Agent ───┘  ← rewrite loop (max 3 iterations)   │
│  5. Scene Director     → FFmpeg tool calls per scene (LLM)  │
│  6. Production Engine  → TTS + Whisper + images             │
│     FFmpeg Tool ────── → per-scene render (self-healing)    │
│  7. Upload Agent       → YouTube Data API                   │
└─────────────────────────────────────────────────────────────┘
```

## Feedback Loops

**Loop A — Script Quality (Critic):**
- Script Agent generates JSON script
- Critic Agent LLM evaluates on 10 dimensions (hook, retention, tone, banned phrases...)
- Score < 7 → sends `rewrite_instructions` back to Script Agent
- Loops up to 3 times. Best version (highest score) always saved.

**Loop B — FFmpeg Self-Healing:**
- Scene Director LLM reads script emotions → issues JSON tool calls per scene
- FFmpeg Tool executes each call (zoom_type, color_grade, text_position, intensity)
- On failure → stderr sent back to Scene Director → re-issues fixed tool calls
- Up to 3 retries per scene. Safe fallback (static+neutral) used if all fail.

## Shared State

All agents read/write a central `AgentState` TypedDict in `main_agent_loop.py`:

```python
AgentState:
  # Director/Research/Script inputs
  niche, strategy_brief, topic, keywords, research_snippets
  
  # Script + Critic loop
  script_data, critic_feedback, critic_iterations
  best_script_data, best_critic_score  # highest-scored version
  
  # Scene Director (FFmpeg tool calls)
  scene_directives  # List[{scene_idx, zoom_type, color_grade, ...}]
  
  # Production
  production_status, audio_path, srt_path
  scene_timeline, scene_clips, video_path
  ffmpeg_error, ffmpeg_retry_count   # self-healing state
  
  # Upload
  youtube_url, upload_status
  
  # Bookkeeping
  active_title, error, logs
```

## File Structure

```
main_agent_loop.py          NEW orchestrator — wires all agents with feedback loops
graph/workflow.py           LangGraph wrapper around main_agent_loop phases
app.py                      FastAPI dashboard + APScheduler

agents/
  director_agent.py         Strategy brief (niche, topic, upload time, A/B test)
  research_agent.py         Trending topics via Tavily + pytrends (lazy init)
  script_agent.py           Viral script JSON + rewrite_instructions support
  critic_agent.py           NEW — Script quality evaluation LLM (score 1-10)
  scene_director_agent.py   NEW — FFmpeg tool-call planner LLM per scene
  ffmpeg_tool.py            NEW — Dynamic FFmpeg renderer (self-healing)
  production_agent.py       TTS, Whisper timestamps, scene sync, SRT
  upload_agent.py           YouTube Data API upload
  analytics_agent.py        YouTube Analytics (optional)
  image_manager.py          Google Imagen + Pollinations.ai fallback

utils/
  llm_client.py             Groq + Cerebras (lazy init, no crash without keys)
  sheets_client.py          Google Sheets logging (graceful skip if unconfigured)

static/index.html           Dashboard UI with Agent Intelligence panel
```

## FFmpeg Tool Parameters (Scene Director)

```
zoom_type:    slow_in | fast_zoom | slow_out | drift_left | drift_right | static
color_grade:  dark_teal | warm_amber | cold_blue | red_noir | neutral
text_position:bottom_center | bottom_left | top_third
intensity:    low | medium | high
vignette:     true | false
```

## Backend

- FastAPI + Uvicorn on port 5000
- APScheduler: psychology (Mon/Wed/Fri 8am), facts (Tue/Thu 8am), lists (Sat 9am)
- All API clients lazy-initialized — app starts without any keys configured

## Required Secrets

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | LLM (primary) + Whisper timestamps |
| `CEREBRAS_API_KEY` | LLM fallback |
| `TAVILY_API_KEY` | Research/search |
| `YOUTUBE_CLIENT_ID` | YouTube OAuth |
| `YOUTUBE_CLIENT_SECRET` | YouTube OAuth |
| `YOUTUBE_REFRESH_TOKEN` | YouTube OAuth |
| `YOUTUBE_TOKEN_JSON` | Google Sheets auth |
| `SPREADSHEET_ID` | Google Sheets tracking |
| `YOUTUBE_CHANNEL_ID` | Channel analytics |
| `GOOGLE_API_KEY` | Google Imagen (optional) |
