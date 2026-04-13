"""
graph/workflow.py

LangGraph StateGraph wrapper around the Agentic Pipeline v2.

This file maintains the LangGraph interface expected by app.py and the scheduler,
but delegates all agent logic to main_agent_loop.py where the full multi-agent
architecture lives (Critic loops, Scene Director tool-calls, self-healing FFmpeg).

State additions from v1 → v2:
  critic_feedback     List[dict]  — all Critic Agent reviews
  critic_iterations   int         — how many critic loops ran
  best_critic_score   int         — highest score achieved
  scene_directives    List[dict]  — FFmpeg tool calls per scene (Scene Director)
  scene_clips         List[str]   — per-scene rendered MP4 clip paths
  production_status   str         — "pending" | "rendering" | "done" | "failed"
  ffmpeg_error        str|None    — last FFmpeg stderr (for self-healing)
  ffmpeg_retry_count  int         — total FFmpeg self-healing retries
"""

from __future__ import annotations
import time
import traceback
import operator
from pathlib import Path
from typing import TypedDict, Optional, List, Annotated

from langgraph.graph import StateGraph, END

from main_agent_loop import (
    _initial_state,
    phase_director,
    phase_research,
    phase_script,
    phase_critic_loop,
    phase_scene_director,
    phase_production_prep,
    phase_render_scenes,
    phase_final_assembly,
    phase_upload,
    AgentState,
)


# ── Thin LangGraph node wrappers ──────────────────────────────────────────────

def director_node(state: AgentState) -> dict:
    updated = phase_director(dict(state))
    return {k: v for k, v in updated.items() if k in AgentState.__annotations__}


def research_node(state: AgentState) -> dict:
    updated = phase_research(dict(state))
    return {k: v for k, v in updated.items() if k in AgentState.__annotations__}


def script_node(state: AgentState) -> dict:
    updated = phase_script(dict(state))
    return {k: v for k, v in updated.items() if k in AgentState.__annotations__}


def critic_loop_node(state: AgentState) -> dict:
    updated = phase_critic_loop(dict(state))
    return {k: v for k, v in updated.items() if k in AgentState.__annotations__}


def scene_director_node(state: AgentState) -> dict:
    updated = phase_scene_director(dict(state))
    return {k: v for k, v in updated.items() if k in AgentState.__annotations__}


def production_prep_node(state: AgentState) -> dict:
    updated = phase_production_prep(dict(state))
    return {k: v for k, v in updated.items() if k in AgentState.__annotations__}


def render_scenes_node(state: AgentState) -> dict:
    updated = phase_render_scenes(dict(state))
    return {k: v for k, v in updated.items() if k in AgentState.__annotations__}


def final_assembly_node(state: AgentState) -> dict:
    updated = phase_final_assembly(dict(state))
    return {k: v for k, v in updated.items() if k in AgentState.__annotations__}


def upload_node(state: AgentState) -> dict:
    updated = phase_upload(dict(state))
    return {k: v for k, v in updated.items() if k in AgentState.__annotations__}


# ── Routing helpers ───────────────────────────────────────────────────────────

def _route_after_research(state: AgentState) -> str:
    return "error_end" if state.get("error") else "script"

def _route_after_script(state: AgentState) -> str:
    return "error_end" if state.get("error") else "critic_loop"

def _route_after_prep(state: AgentState) -> str:
    return "error_end" if state.get("error") else "render_scenes"

def _route_after_render(state: AgentState) -> str:
    return "error_end" if state.get("error") else "final_assembly"

def _route_after_assembly(state: AgentState) -> str:
    if state.get("error"):
        return "error_end"
    if state.get("video_path") and Path(state["video_path"]).exists():
        return "upload"
    return "error_end"


def error_end_node(state: AgentState) -> dict:
    print(f"[WORKFLOW] Pipeline ended with error: {state.get('error')}")
    return {}


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_workflow():
    g = StateGraph(AgentState)

    for name, fn in [
        ("director",        director_node),
        ("research",        research_node),
        ("script",          script_node),
        ("critic_loop",     critic_loop_node),
        ("scene_director",  scene_director_node),
        ("production_prep", production_prep_node),
        ("render_scenes",   render_scenes_node),
        ("final_assembly",  final_assembly_node),
        ("upload",          upload_node),
        ("error_end",       error_end_node),
    ]:
        g.add_node(name, fn)

    g.set_entry_point("director")
    g.add_edge("director", "research")
    g.add_conditional_edges("research", _route_after_research,
                            {"script": "script", "error_end": "error_end"})
    g.add_conditional_edges("script", _route_after_script,
                            {"critic_loop": "critic_loop", "error_end": "error_end"})
    g.add_edge("critic_loop", "scene_director")
    g.add_edge("scene_director", "production_prep")
    g.add_conditional_edges("production_prep", _route_after_prep,
                            {"render_scenes": "render_scenes", "error_end": "error_end"})
    g.add_conditional_edges("render_scenes", _route_after_render,
                            {"final_assembly": "final_assembly", "error_end": "error_end"})
    g.add_conditional_edges("final_assembly", _route_after_assembly,
                            {"upload": "upload", "error_end": "error_end"})
    g.add_edge("upload",    END)
    g.add_edge("error_end", END)

    return g.compile()


# ── Public API (used by app.py scheduler and /run endpoint) ──────────────────

def run_pipeline(niche: str = "auto", schedule_upload: bool = True) -> dict:
    """
    Drop-in replacement for the old run_pipeline().
    Now uses the full Agentic v2 pipeline with Critic loops and Scene Director.
    """
    from main_agent_loop import run_agentic_pipeline
    return run_agentic_pipeline(niche=niche, schedule_upload=schedule_upload)
