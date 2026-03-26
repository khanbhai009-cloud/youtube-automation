from __future__ import annotations
import traceback
from typing import TypedDict, Optional, List, Annotated
import operator

from langgraph.graph import StateGraph, END

from agents.research_agent import get_trending_topic
from agents.script_agent import generate_script, build_timeline, get_full_script_text
from agents.production_agent import generate_audio, render_video
from agents.upload_agent import upload_video
from utils.sheets_client import log_video, update_status


# ── State ────────────────────────────────────────────────────────────────────

class VideoState(TypedDict):
    # Input
    niche: str
    schedule_upload: bool

    # Research
    topic: str
    keywords: List[str]
    research_snippets: List[str]

    # Script
    script_data: dict
    timeline: List[dict]
    script_text: str

    # Production
    audio_path: str
    video_path: str

    # Upload
    youtube_url: str
    upload_status: str

    # Control flow
    error: Optional[str]
    retry_count: int
    logs: Annotated[List[str], operator.add]


# ── Nodes ────────────────────────────────────────────────────────────────────

def research_node(state: VideoState) -> dict:
    print("\n═══ PHASE 1: RESEARCH ═══")
    try:
        data = get_trending_topic(state["niche"])
        return {
            "topic": data["topic"],
            "keywords": data["keywords"],
            "research_snippets": data["research_snippets"],
            "error": None,
            "logs": [f"✅ Research done: {data['topic']}"],
        }
    except Exception as e:
        tb = traceback.format_exc()
        return {
            "error": f"Research failed: {e}",
            "logs": [f"❌ Research error: {e}"],
        }


def script_node(state: VideoState) -> dict:
    print("\n═══ PHASE 2: SCRIPTING ═══")
    try:
        research_data = {
            "topic": state["topic"],
            "keywords": state["keywords"],
            "research_snippets": state["research_snippets"],
        }
        script_data = generate_script(research_data)
        timeline = build_timeline(script_data)
        script_text = get_full_script_text(script_data)
        
        # Log initial entry to Sheets
        log_video({
            "topic": state["topic"],
            "script": script_text,
            "audio_path": "",
            "thumbnail_url": "",
            "status": "Scripted",
            "youtube_url": "",
            "tags": script_data.get("tags", []),
        })
        
        return {
            "script_data": script_data,
            "timeline": timeline,
            "script_text": script_text,
            "error": None,
            "logs": [f"✅ Script: {script_data['title']}"],
        }
    except Exception as e:
        return {
            "error": f"Script failed: {e}",
            "logs": [f"❌ Script error: {e}"],
        }


def production_node(state: VideoState) -> dict:
    print("\n═══ PHASE 3: PRODUCTION ═══")
    try:
        audio_path = generate_audio(state["script_text"], state["topic"])
        video_path = render_video(
            audio_path,
            state["timeline"],
            state["script_data"],
            state["topic"],
        )
        update_status(state["topic"], "Rendered")
        return {
            "audio_path": audio_path,
            "video_path": video_path,
            "error": None,
            "logs": [f"✅ Video rendered: {video_path}"],
        }
    except Exception as e:
        return {
            "error": f"Production failed: {e}",
            "logs": [f"❌ Production error: {e}"],
        }


def upload_node(state: VideoState) -> dict:
    print("\n═══ PHASE 4: UPLOAD ═══")
    try:
        script_data = state["script_data"]
        result = upload_video(
            video_path=state["video_path"],
            title=script_data["title"],
            description=script_data["description"],
            tags=script_data.get("tags", []),
            schedule=state.get("schedule_upload", True),
        )
        update_status(state["topic"], "Posted", result["url"])
        return {
            "youtube_url": result["url"],
            "upload_status": result["status"],
            "error": None,
            "logs": [f"✅ Uploaded: {result['url']}"],
        }
    except Exception as e:
        return {
            "error": f"Upload failed: {e}",
            "upload_status": "upload_failed",
            "logs": [f"❌ Upload error: {e}"],
        }


def error_handler_node(state: VideoState) -> dict:
    retry = state.get("retry_count", 0)
    print(f"\n[ERROR HANDLER] Error: {state['error']} | Retry: {retry}")
    return {
        "retry_count": retry + 1,
        "logs": [f"⚠️ Retrying... attempt {retry + 1}"],
    }


# ── Routing ──────────────────────────────────────────────────────────────────

def should_retry(state: VideoState) -> str:
    if state.get("error") and state.get("retry_count", 0) < 2:
        return "retry"
    elif state.get("error"):
        return "give_up"
    return "continue"


def after_research(state: VideoState) -> str:
    return should_retry(state) if state.get("error") else "script"


def after_script(state: VideoState) -> str:
    return should_retry(state) if state.get("error") else "production"


def after_production(state: VideoState) -> str:
    return should_retry(state) if state.get("error") else "upload"


def after_upload(state: VideoState) -> str:
    return END


# ── Build Graph ──────────────────────────────────────────────────────────────

def build_workflow():
    g = StateGraph(VideoState)

    g.add_node("research", research_node)
    g.add_node("script", script_node)
    g.add_node("production", production_node)
    g.add_node("upload", upload_node)
    g.add_node("error_handler", error_handler_node)

    g.set_entry_point("research")

    g.add_conditional_edges("research", after_research, {
        "script": "script",
        "retry": "error_handler",
        "give_up": END,
    })
    g.add_conditional_edges("script", after_script, {
        "production": "production",
        "retry": "error_handler",
        "give_up": END,
    })
    g.add_conditional_edges("production", after_production, {
        "upload": "upload",
        "retry": "error_handler",
        "give_up": END,
    })
    g.add_edge("upload", END)
    g.add_edge("error_handler", "research")  # restart from research on retry

    return g.compile()


# ── Entry point ──────────────────────────────────────────────────────────────

def run_pipeline(niche: str = "psychology", schedule_upload: bool = True) -> dict:
    """Run the full video generation pipeline."""
    workflow = build_workflow()
    
    initial_state: VideoState = {
        "niche": niche,
        "schedule_upload": schedule_upload,
        "topic": "",
        "keywords": [],
        "research_snippets": [],
        "script_data": {},
        "timeline": [],
        "script_text": "",
        "audio_path": "",
        "video_path": "",
        "youtube_url": "",
        "upload_status": "",
        "error": None,
        "retry_count": 0,
        "logs": [],
    }
    
    final_state = workflow.invoke(initial_state)
    return final_state
