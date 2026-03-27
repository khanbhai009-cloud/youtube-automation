from __future__ import annotations
import traceback
import time
from typing import TypedDict, Optional, List, Annotated
import operator

from langgraph.graph import StateGraph, END

from agents.director_agent import run_director
from agents.research_agent import get_trending_topic
from agents.script_agent import generate_script, build_timeline, get_full_script_text
from agents.production_agent import generate_audio, render_video
from agents.upload_agent import upload_video
from utils.sheets_client import log_video, update_status


# ── State ─────────────────────────────────────────────────────────────────────

class VideoState(TypedDict):
    strategy_brief: dict
    analytics_raw: dict
    trends_raw: dict
    niche: str
    topic: str
    keywords: List[str]
    research_snippets: List[str]
    script_data: dict
    timeline: List[dict]
    script_text: str
    audio_path: str
    video_path: str
    youtube_url: str
    upload_status: str
    active_title: str
    error: Optional[str]
    retry_count: int
    logs: Annotated[List[str], operator.add]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def director_node(state: VideoState) -> dict:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 0: DIRECTOR — FULL ANALYSIS  ║")
    print("╚══════════════════════════════════════╝")
    try:
        result = run_director()
        brief  = result["strategy_brief"]
        return {
            "strategy_brief": brief,
            "analytics_raw":  result["analytics_raw"],
            "trends_raw":     result["trends_raw"],
            "niche":          brief["niche"],
            "topic":          brief.get("topic", ""),
            "error": None,
            "logs": [
                f"🎬 Director → [{brief['niche'].upper()}] {brief['topic']}",
                f"📐 Format: {brief['video_format']} | Thumb: {brief['thumbnail_style']}",
                f"⏰ Upload UTC {brief['upload_hour_utc']:02d}:00 | A/B: {'✅' if brief['ab_test'].get('enabled') else '❌'}",
                f"📊 Diagnosis: {brief['channel_diagnosis']} | {brief['reasoning']}",
            ],
        }
    except Exception as e:
        return {
            "error": f"Director failed: {e}",
            "strategy_brief": {}, "analytics_raw": {}, "trends_raw": {},
            "niche": "psychology", "topic": "",
            "logs": [f"❌ Director error: {e}"],
        }


def research_node(state: VideoState) -> dict:
    print("\n═══ PHASE 1: RESEARCH ═══")
    try:
        brief  = state.get("strategy_brief", {})
        niche  = state.get("niche", "psychology")
        d_topic = brief.get("topic", "")

        trends_raw = state.get("trends_raw", {})
        if niche in trends_raw and trends_raw[niche].get("keywords"):
            data = dict(trends_raw[niche])
            if d_topic:
                data["topic"] = d_topic
            print(f"[RESEARCH] Reusing Director trends: {data['topic']}")
        else:
            data = get_trending_topic(niche)
            if d_topic:
                data["topic"] = d_topic

        return {
            "topic": data["topic"],
            "keywords": data["keywords"],
            "research_snippets": data["research_snippets"],
            "error": None,
            "logs": [f"✅ Research: {data['topic']} | {len(data['keywords'])} keywords"],
        }
    except Exception as e:
        return {"error": f"Research failed: {e}", "logs": [f"❌ Research error: {e}"]}


def script_node(state: VideoState) -> dict:
    print("\n═══ PHASE 2: SCRIPTING ═══")
    try:
        brief = state.get("strategy_brief", {})
        research_data = {
            "topic": state["topic"],
            "keywords": state["keywords"],
            "research_snippets": state["research_snippets"],
        }
        style_hints = {
            "video_format":       brief.get("video_format", "shocking_facts"),
            "title_formula":      brief.get("title_formula", "dark_truth"),
            "target_length_secs": brief.get("target_length_secs", 210),
            "ab_test":            brief.get("ab_test", {}),
        }
        script_data = generate_script(research_data, style_hints=style_hints)
        timeline    = build_timeline(script_data)
        script_text = get_full_script_text(script_data)

        # A/B title selection
        ab = brief.get("ab_test", {})
        if ab.get("enabled") and ab.get("title_a") and ab.get("title_b"):
            use_b = int(time.time()) % 2 == 1
            active_title = ab["title_b"] if use_b else ab["title_a"]
            variant = "B" if use_b else "A"
        else:
            active_title = script_data.get("title", state["topic"])
            variant = "A"

        log_video({
            "topic": state["topic"], "script": script_text,
            "audio_path": "", "thumbnail_url": "",
            "status": f"Scripted (title_{variant})",
            "youtube_url": "", "tags": script_data.get("tags", []),
        })
        return {
            "script_data": script_data, "timeline": timeline,
            "script_text": script_text, "active_title": active_title,
            "error": None,
            "logs": [
                f"✅ Script ready | Format: {style_hints['video_format']}",
                f"🅰️🅱️ Title variant {variant}: {active_title}",
            ],
        }
    except Exception as e:
        return {"error": f"Script failed: {e}", "logs": [f"❌ Script error: {e}"]}


def production_node(state: VideoState) -> dict:
    print("\n═══ PHASE 3: PRODUCTION ═══")
    try:
        brief = state.get("strategy_brief", {})
        audio_path = generate_audio(state["script_text"], state["topic"])
        video_path = render_video(
            audio_path, state["timeline"], state["script_data"], state["topic"],
            thumbnail_style=brief.get("thumbnail_style", "plain_icon"),
            thumbnail_colors=brief.get("thumbnail_color_scheme", "white_bold"),
        )
        update_status(state["topic"], "Rendered")
        return {
            "audio_path": audio_path, "video_path": video_path, "error": None,
            "logs": [f"✅ Rendered | 🎨 {brief.get('thumbnail_style')} / {brief.get('thumbnail_color_scheme')}"],
        }
    except Exception as e:
        return {"error": f"Production failed: {e}", "logs": [f"❌ Production error: {e}"]}


def upload_node(state: VideoState) -> dict:
    print("\n═══ PHASE 4: UPLOAD ═══")
    try:
        brief       = state.get("strategy_brief", {})
        script_data = state["script_data"]
        upload_hour = brief.get("upload_hour_utc", 1)

        result = upload_video(
            video_path=state["video_path"],
            title=state.get("active_title") or script_data.get("title", state["topic"]),
            description=script_data.get("description", ""),
            tags=script_data.get("tags", []),
            upload_hour_utc=upload_hour,
        )
        update_status(state["topic"], "Posted", result["url"])
        return {
            "youtube_url": result["url"], "upload_status": result["status"], "error": None,
            "logs": [f"✅ Uploaded → {result['url']} | ⏰ UTC {upload_hour:02d}:00"],
        }
    except Exception as e:
        return {"error": f"Upload failed: {e}", "upload_status": "failed", "logs": [f"❌ Upload error: {e}"]}


def error_handler_node(state: VideoState) -> dict:
    retry = state.get("retry_count", 0)
    print(f"\n[ERROR HANDLER] Retry #{retry + 1}")
    return {"retry_count": retry + 1, "error": None, "logs": [f"⚠️ Retry #{retry + 1}"]}


# ── Routing ───────────────────────────────────────────────────────────────────

def _route(state: VideoState, next_node: str) -> str:
    if state.get("error"):
        return "retry" if state.get("retry_count", 0) < 2 else "give_up"
    return next_node

EDGE_MAP = {"research": "research", "script": "script", "production": "production",
            "upload": "upload", "retry": "error_handler", "give_up": END}


def build_workflow():
    g = StateGraph(VideoState)
    for name, fn in [("director", director_node), ("research", research_node),
                     ("script", script_node), ("production", production_node),
                     ("upload", upload_node), ("error_handler", error_handler_node)]:
        g.add_node(name, fn)

    g.set_entry_point("director")
    g.add_conditional_edges("director",   lambda s: _route(s, "research"),   EDGE_MAP)
    g.add_conditional_edges("research",   lambda s: _route(s, "script"),     EDGE_MAP)
    g.add_conditional_edges("script",     lambda s: _route(s, "production"), EDGE_MAP)
    g.add_conditional_edges("production", lambda s: _route(s, "upload"),     EDGE_MAP)
    g.add_edge("upload",        END)
    g.add_edge("error_handler", "director")   # full restart from Director on retry
    return g.compile()


def run_pipeline(niche: str = "auto", schedule_upload: bool = True) -> dict:
    workflow = build_workflow()
    initial: VideoState = {
        "strategy_brief": {}, "analytics_raw": {}, "trends_raw": {},
        "niche": "psychology" if niche == "auto" else niche,
        "topic": "", "keywords": [], "research_snippets": [],
        "script_data": {}, "timeline": [], "script_text": "",
        "audio_path": "", "video_path": "",
        "youtube_url": "", "upload_status": "", "active_title": "",
        "error": None, "retry_count": 0, "logs": [],
    }
    return workflow.invoke(initial)
