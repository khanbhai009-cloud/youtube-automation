"""
main_agent_loop.py
══════════════════════════════════════════════════════════════════════════════

FULLY AUTONOMOUS MULTI-AGENT SYSTEM WITH FEEDBACK LOOPS
YouTube AI Factory — Agentic Architecture v2

AGENT ROSTER:
┌─────────────────────────────────────────────────────────────┐
│  1. Director Agent     → strategy brief + niche selection   │
│  2. Research Agent     → trending topics + Tavily snippets  │
│  3. Script Agent       → initial script JSON generation     │
│  4. Critic Agent ◄──┐  → quality evaluation (score 1-10)   │
│     Script Agent ───┘  ← rewrite loop (max 3 iterations)   │
│  5. Scene Director     → FFmpeg tool calls per scene        │
│  6. Production Engine  → TTS + Whisper + images + FFmpeg    │
│     FFmpeg Tool   ──── → per-scene render (self-healing)    │
│  7. Upload Agent       → YouTube API                        │
└─────────────────────────────────────────────────────────────┘

FEEDBACK LOOPS:
  Loop A (Script Quality):
    Script Agent → Critic Agent → [score < 7] → Script Agent (rewrite)
    Maximum 3 iterations. If still < 7 after 3x, best version passes.

  Loop B (FFmpeg Self-Healing):
    Scene Director → FFmpeg Tool → [fails] → Scene Director (error context)
    Scene Director re-issues tool calls. Maximum 3 retries per scene.

SHARED STATE:
    All agents read/write a central AgentState TypedDict.
    No agent operates on stale data — state is the single source of truth.
"""

from __future__ import annotations
import traceback
from datetime import datetime
from pathlib import Path
from typing import TypedDict, Optional, List, Annotated
import operator

# ── Agent imports ──────────────────────────────────────────────────────────────

from agents.director_agent    import run_director
from agents.research_agent    import get_trending_topic
from agents.script_agent      import generate_script, build_timeline, get_full_script_text
from agents.critic_agent      import critique_script
from agents.scene_director_agent import plan_scene_directives
from agents.production_agent  import (
    generate_audio,
    get_word_timestamps,
    match_paragraphs_to_time,
    create_srt,
    download_bgm,
    download_scene_image,
)
from agents.ffmpeg_tool       import render_scene_with_ffmpeg, concat_scenes_with_audio
from agents.upload_agent      import upload_video
from utils.sheets_client      import log_video, update_status

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_CRITIC_LOOPS    = 3
MAX_FFMPEG_RETRIES  = 3
CRITIC_PASS_SCORE   = 7
OUTPUTS_DIR         = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED STATE SCHEMA
#  Every agent reads from and writes back to this dictionary.
#  The orchestrator is the only entity that mutates it between agent calls.
# ══════════════════════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    # ── Pipeline inputs ──────────────────────────────────────────
    niche:              str
    schedule_upload:    bool

    # ── Director outputs ─────────────────────────────────────────
    strategy_brief:     dict
    analytics_raw:      dict
    trends_raw:         dict

    # ── Research outputs ─────────────────────────────────────────
    topic:              str
    keywords:           List[str]
    research_snippets:  List[str]

    # ── Script + Critic Loop state ───────────────────────────────
    script_data:        dict          # current script (rewritten each loop)
    critic_feedback:    List[dict]    # all critique results so far
    critic_iterations:  int           # how many times critic has run
    best_script_data:   dict          # highest-scored version
    best_critic_score:  int           # score of best version

    # ── Scene Director outputs ───────────────────────────────────
    scene_directives:   List[dict]    # FFmpeg tool calls per scene

    # ── Production state ─────────────────────────────────────────
    production_status:  str           # "pending" | "rendering" | "done" | "failed"
    audio_path:         str
    srt_path:           str
    scene_timeline:     List[dict]
    scene_clips:        List[str]     # per-scene rendered clip paths
    video_path:         str
    ffmpeg_error:       Optional[str] # last FFmpeg error (for self-healing)
    ffmpeg_retry_count: int

    # ── Upload outputs ───────────────────────────────────────────
    youtube_url:        str
    upload_status:      str

    # ── Orchestrator bookkeeping ──────────────────────────────────
    active_title:       str
    error:              Optional[str]
    logs:               Annotated[List[str], operator.add]


def _initial_state(niche: str, schedule_upload: bool) -> AgentState:
    return AgentState(
        niche=niche,
        schedule_upload=schedule_upload,
        strategy_brief={},
        analytics_raw={},
        trends_raw={},
        topic="",
        keywords=[],
        research_snippets=[],
        script_data={},
        critic_feedback=[],
        critic_iterations=0,
        best_script_data={},
        best_critic_score=0,
        scene_directives=[],
        production_status="pending",
        audio_path="",
        srt_path="",
        scene_timeline=[],
        scene_clips=[],
        video_path="",
        ffmpeg_error=None,
        ffmpeg_retry_count=0,
        youtube_url="",
        upload_status="",
        active_title="",
        error=None,
        logs=[],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 0 — DIRECTOR
# ══════════════════════════════════════════════════════════════════════════════

def phase_director(state: AgentState) -> AgentState:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 0: DIRECTOR AGENT            ║")
    print("╚══════════════════════════════════════╝")
    try:
        result        = run_director()
        brief         = result["strategy_brief"]
        state["strategy_brief"] = brief
        state["analytics_raw"]  = result["analytics_raw"]
        state["trends_raw"]     = result["trends_raw"]
        state["niche"]          = brief.get("niche", state["niche"])
        state["logs"].append(
            f"🎬 Director → [{brief['niche'].upper()}] {brief.get('topic','')}"
        )
        print(f"[DIRECTOR] ✅ Strategy brief ready: {brief.get('topic','')}")
    except Exception as e:
        traceback.print_exc()
        state["logs"].append(f"⚠️ Director failed ({e}), using defaults")
        print(f"[DIRECTOR] ⚠️ Failed: {e} — continuing with defaults")
    return state


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — RESEARCH
# ══════════════════════════════════════════════════════════════════════════════

def phase_research(state: AgentState) -> AgentState:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 1: RESEARCH AGENT            ║")
    print("╚══════════════════════════════════════╝")
    try:
        brief   = state.get("strategy_brief", {})
        niche   = state.get("niche", "psychology")
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

        state["topic"]             = data["topic"]
        state["keywords"]          = data["keywords"]
        state["research_snippets"] = data["research_snippets"]
        state["logs"].append(
            f"✅ Research: {data['topic']} | {len(data['keywords'])} keywords"
        )
    except Exception as e:
        traceback.print_exc()
        state["error"] = f"Research failed: {e}"
        state["logs"].append(f"❌ Research error: {e}")
    return state


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2A — SCRIPT GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def phase_script(state: AgentState, rewrite_instructions: str = "") -> AgentState:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 2A: SCRIPT AGENT             ║")
    print("╚══════════════════════════════════════╝")
    try:
        brief = state.get("strategy_brief", {})
        research_data = {
            "topic":             state["topic"],
            "keywords":          state["keywords"],
            "research_snippets": state["research_snippets"],
        }
        style_hints = {
            "video_format":       brief.get("video_format", "shocking_facts"),
            "title_formula":      brief.get("title_formula", "dark_truth"),
            "target_length_secs": brief.get("target_length_secs", 210),
            "ab_test":            brief.get("ab_test", {}),
            "rewrite_instructions": rewrite_instructions,
        }

        script_data = generate_script(research_data, style_hints=style_hints)
        state["script_data"] = script_data

        iteration_label = f"(iteration {state['critic_iterations'] + 1})"
        state["logs"].append(
            f"✅ Script {iteration_label}: {script_data.get('title','')}"
        )
        print(f"[SCRIPT] ✅ Generated: {script_data.get('title','')}")
    except Exception as e:
        traceback.print_exc()
        state["error"] = f"Script failed: {e}"
        state["logs"].append(f"❌ Script error: {e}")
    return state


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2B — CRITIC FEEDBACK LOOP
#  Loop: Script Agent → Critic → [score < 7] → Script Agent (rewrite)
#  Max MAX_CRITIC_LOOPS iterations. Best version always saved.
# ══════════════════════════════════════════════════════════════════════════════

def phase_critic_loop(state: AgentState) -> AgentState:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 2B: CRITIC FEEDBACK LOOP     ║")
    print("╚══════════════════════════════════════╝")

    rewrite_instructions = ""

    for iteration in range(MAX_CRITIC_LOOPS):
        state["critic_iterations"] = iteration

        if iteration > 0:
            print(f"\n[CRITIC LOOP] Rewrite #{iteration} — applying: {rewrite_instructions[:80]}...")
            state = phase_script(state, rewrite_instructions=rewrite_instructions)
            if state.get("error"):
                print(f"[CRITIC LOOP] Script rewrite failed — keeping best version")
                break

        critique = critique_script(
            script_data=state["script_data"],
            topic=state["topic"],
            iteration=iteration,
        )

        state["critic_feedback"].append(critique)

        score = critique.get("score", 0)
        if score > state.get("best_critic_score", 0):
            state["best_critic_score"] = score
            state["best_script_data"]  = dict(state["script_data"])
            print(f"[CRITIC LOOP] New best score: {score}/10 ✅")

        state["logs"].append(
            f"🎯 Critic iteration {iteration + 1}: score={score}/10 | "
            f"approved={critique['approved']} | risk={critique['retention_risk']}"
        )

        if critique.get("approved") or score >= CRITIC_PASS_SCORE:
            print(f"[CRITIC LOOP] ✅ APPROVED at iteration {iteration + 1} (score {score}/10)")
            state["script_data"] = state["best_script_data"]
            break
        else:
            rewrite_instructions = critique.get("rewrite_instructions", "")
            print(f"[CRITIC LOOP] ❌ Score {score}/10 — sending back for rewrite")
            print(f"[CRITIC LOOP] Instructions: {rewrite_instructions[:100]}")

            if iteration == MAX_CRITIC_LOOPS - 1:
                print(f"[CRITIC LOOP] Max iterations reached — using best version (score {state['best_critic_score']}/10)")
                state["script_data"] = state["best_script_data"]
                state["logs"].append(
                    f"⚠️ Max critic loops reached. Best score: {state['best_critic_score']}/10"
                )

    brief = state.get("strategy_brief", {})
    ab    = brief.get("ab_test", {})
    import time
    if ab.get("enabled") and ab.get("title_a") and ab.get("title_b"):
        use_b        = int(time.time()) % 2 == 1
        active_title = ab["title_b"] if use_b else ab["title_a"]
    else:
        active_title = state["script_data"].get("title", state["topic"])
    state["active_title"] = active_title

    try:
        log_video({
            "topic":         state["topic"],
            "script":        get_full_script_text(state["script_data"]),
            "audio_path":    "",
            "thumbnail_url": "",
            "status":        f"Scripted (critic_score={state['best_critic_score']})",
            "youtube_url":   "",
            "tags":          state["script_data"].get("tags", []),
        })
    except Exception as e:
        print(f"[CRITIC LOOP] Sheets log skipped: {e}")

    return state


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3A — SCENE DIRECTOR (FFmpeg Tool Planning)
# ══════════════════════════════════════════════════════════════════════════════

def phase_scene_director(state: AgentState, error_context: str = "") -> AgentState:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 3A: SCENE DIRECTOR           ║")
    print("╚══════════════════════════════════════╝")
    try:
        directives = plan_scene_directives(
            script_data=state["script_data"],
            error_context=error_context,
        )
        state["scene_directives"] = directives
        state["logs"].append(
            f"🎬 Scene Director: {len(directives)} scene tool calls issued"
        )
    except Exception as e:
        traceback.print_exc()
        state["logs"].append(f"⚠️ Scene Director failed ({e}) — using fallback directives")
        from agents.scene_director_agent import _fallback_directives
        state["scene_directives"] = _fallback_directives(
            state["script_data"].get("sections", [])
        )
    return state


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3B — PRODUCTION ENGINE
#  TTS → Whisper → Scene sync → SRT
# ══════════════════════════════════════════════════════════════════════════════

def phase_production_prep(state: AgentState) -> AgentState:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 3B: PRODUCTION PREP          ║")
    print("╚══════════════════════════════════════╝")
    try:
        state["production_status"] = "rendering"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        full_text = get_full_script_text(state["script_data"])
        print(f"[PRODUCTION] Script words: {len(full_text.split())}")

        print("[PRODUCTION] Step 1/3 — Kokoro TTS...")
        audio_path = generate_audio(full_text)
        state["audio_path"] = audio_path

        print("[PRODUCTION] Step 2/3 — Groq Whisper timestamps...")
        words = get_word_timestamps(audio_path)

        print("[PRODUCTION] Step 3/3 — Scene sync + SRT...")
        sections       = state["script_data"].get("sections", [])
        scene_timeline = match_paragraphs_to_time(sections, words)
        state["scene_timeline"] = scene_timeline

        srt_path = str(OUTPUTS_DIR / f"captions_{ts}.srt")
        create_srt(words, srt_path, words_per_caption=4)
        state["srt_path"] = srt_path

        state["logs"].append(
            f"✅ Production prep done | {len(words)} words | {len(scene_timeline)} scenes"
        )
    except Exception as e:
        traceback.print_exc()
        state["error"]             = f"Production prep failed: {e}"
        state["production_status"] = "failed"
        state["logs"].append(f"❌ Production prep error: {e}")
    return state


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3C — SCENE RENDER LOOP (FFmpeg Tool, Self-Healing)
#  For each scene: call render_scene_with_ffmpeg()
#  If failure → send error to Scene Director → retry up to MAX_FFMPEG_RETRIES
# ══════════════════════════════════════════════════════════════════════════════

def phase_render_scenes(state: AgentState) -> AgentState:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 3C: SCENE RENDER (FFMPEG)    ║")
    print("╚══════════════════════════════════════╝")
    try:
        scene_timeline = state["scene_timeline"]
        directives     = state["scene_directives"]
        srt_path       = state["srt_path"]
        clip_paths     = []

        for i, scene in enumerate(scene_timeline):
            image_path = download_scene_image(scene.get("image_prompt", ""), i)

            directive = directives[i] if i < len(directives) else {
                "zoom_type": "slow_in", "color_grade": "dark_teal",
                "text_position": "bottom_center", "intensity": "medium", "vignette": True
            }

            duration = max(round(scene["end"] - scene["start"], 3), 1.5)
            render_result = None

            for ffmpeg_attempt in range(MAX_FFMPEG_RETRIES):
                render_result = render_scene_with_ffmpeg(
                    scene_idx=i,
                    image_path=image_path,
                    duration=duration,
                    srt_path=srt_path,
                    zoom_type=directive.get("zoom_type",    "slow_in"),
                    color_grade=directive.get("color_grade", "dark_teal"),
                    text_position=directive.get("text_position", "bottom_center"),
                    intensity=directive.get("intensity",   "medium"),
                    vignette=directive.get("vignette",     True),
                )

                if render_result["success"]:
                    clip_paths.append(render_result["output_path"])
                    state["logs"].append(
                        f"✅ Scene {i:02d} rendered | "
                        f"zoom={directive.get('zoom_type')} grade={directive.get('color_grade')}"
                    )
                    break

                else:
                    error_msg = render_result["error"]
                    state["ffmpeg_error"]       = error_msg
                    state["ffmpeg_retry_count"] += 1

                    print(f"\n[SELF-HEAL] Scene {i} FFmpeg failed (attempt {ffmpeg_attempt + 1})")
                    print(f"[SELF-HEAL] Error: {error_msg[-300:]}")

                    if ffmpeg_attempt < MAX_FFMPEG_RETRIES - 1:
                        print(f"[SELF-HEAL] Sending error to Scene Director for fix...")
                        state["logs"].append(
                            f"⚠️ Scene {i:02d} FFmpeg failed — self-healing attempt {ffmpeg_attempt + 2}"
                        )

                        new_directives = plan_scene_directives(
                            script_data=state["script_data"],
                            error_context=f"Scene {i} failed: {error_msg[-500:]}",
                        )
                        if i < len(new_directives):
                            directive = new_directives[i]
                            print(f"[SELF-HEAL] New params: zoom={directive.get('zoom_type')} grade={directive.get('color_grade')}")
                    else:
                        print(f"[SELF-HEAL] All {MAX_FFMPEG_RETRIES} retries failed for scene {i} — using safe fallback")
                        state["logs"].append(
                            f"❌ Scene {i:02d} failed after {MAX_FFMPEG_RETRIES} retries — safe fallback render"
                        )
                        fallback_result = render_scene_with_ffmpeg(
                            scene_idx=i,
                            image_path=image_path,
                            duration=duration,
                            srt_path=srt_path,
                            zoom_type="static",
                            color_grade="neutral",
                            text_position="bottom_center",
                            intensity="low",
                            vignette=False,
                        )
                        if fallback_result["success"]:
                            clip_paths.append(fallback_result["output_path"])
                        break

        state["scene_clips"] = clip_paths
        print(f"\n[RENDER] {len(clip_paths)}/{len(scene_timeline)} scenes rendered successfully")

    except Exception as e:
        traceback.print_exc()
        state["error"]             = f"Scene render failed: {e}"
        state["production_status"] = "failed"
        state["logs"].append(f"❌ Scene render error: {e}")

    return state


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3D — FINAL ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════

def phase_final_assembly(state: AgentState) -> AgentState:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 3D: FINAL ASSEMBLY           ║")
    print("╚══════════════════════════════════════╝")
    try:
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(OUTPUTS_DIR / f"video_{ts}.mp4")

        bgm_mood = state["script_data"].get("bgm_mood", "dark_suspense")
        bgm_path = None
        try:
            from agents.production_agent import download_bgm
            bgm_path = download_bgm(bgm_mood)
        except Exception as e:
            print(f"[ASSEMBLY] BGM download failed: {e}")

        result = concat_scenes_with_audio(
            clip_paths=state["scene_clips"],
            audio_path=state["audio_path"],
            output_path=output_path,
            bgm_path=bgm_path,
        )

        if result["success"]:
            state["video_path"]        = result["output_path"]
            state["production_status"] = "done"
            size_mb = round(Path(output_path).stat().st_size / 1024 / 1024, 1)
            state["logs"].append(f"✅ Final video: {output_path} ({size_mb}MB)")
            print(f"[ASSEMBLY] ✅ Done: {output_path} ({size_mb}MB)")

            try:
                update_status(state["topic"], "Rendered")
            except Exception as e:
                print(f"[ASSEMBLY] Sheets update skipped: {e}")

            _cleanup_scene_clips(state["scene_clips"])
        else:
            raise RuntimeError(f"Concat failed: {result['error']}")

    except Exception as e:
        traceback.print_exc()
        state["error"]             = f"Assembly failed: {e}"
        state["production_status"] = "failed"
        state["logs"].append(f"❌ Assembly error: {e}")

    return state


def _cleanup_scene_clips(clip_paths: list):
    for p in clip_paths:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 4 — UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def phase_upload(state: AgentState) -> AgentState:
    print("\n╔══════════════════════════════════════╗")
    print("║  PHASE 4: UPLOAD AGENT              ║")
    print("╚══════════════════════════════════════╝")
    try:
        video_path = state.get("video_path", "")
        if not video_path or not Path(video_path).exists():
            raise FileNotFoundError(f"Video file missing: {video_path}")

        brief       = state.get("strategy_brief", {})
        script_data = state["script_data"]
        result      = upload_video(
            video_path=video_path,
            title=state.get("active_title") or script_data.get("title", state["topic"]),
            description=script_data.get("description", ""),
            tags=script_data.get("tags", []),
            schedule=state.get("schedule_upload", True),
            upload_hour_utc=brief.get("upload_hour_utc", 1),
        )

        state["youtube_url"]   = result["url"]
        state["upload_status"] = result["status"]
        state["logs"].append(f"✅ Uploaded → {result['url']}")

        try:
            update_status(state["topic"], "Posted", result["url"])
        except Exception as e:
            print(f"[UPLOAD] Sheets update skipped: {e}")

    except Exception as e:
        traceback.print_exc()
        state["error"]         = f"Upload failed: {e}"
        state["upload_status"] = "failed"
        state["logs"].append(f"❌ Upload error: {e}")

    return state


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR — run_agentic_pipeline()
#  Wires all agents with feedback loops and shared state.
# ══════════════════════════════════════════════════════════════════════════════

def run_agentic_pipeline(
    niche:           str  = "auto",
    schedule_upload: bool = True,
) -> dict:
    """
    Entry point for the fully autonomous multi-agent pipeline.

    Args:
        niche:           "psychology" | "facts" | "lists" | "auto"
        schedule_upload: Whether to schedule YouTube upload or post immediately

    Returns:
        Final AgentState as dict with all results, logs, and metadata.
    """
    resolved_niche = "psychology" if niche == "auto" else niche
    state = _initial_state(resolved_niche, schedule_upload)

    print("\n" + "═" * 60)
    print("  YOUTUBE AI FACTORY — AGENTIC PIPELINE v2")
    print("  Multi-Agent | Feedback Loops | Self-Healing FFmpeg")
    print("═" * 60)

    # ── Phase 0: Director ──────────────────────────────────────────
    state = phase_director(state)

    # ── Phase 1: Research ──────────────────────────────────────────
    state = phase_research(state)
    if state.get("error"):
        return _abort(state, "Research failed")

    # ── Phase 2A: Initial Script ───────────────────────────────────
    state = phase_script(state)
    if state.get("error"):
        return _abort(state, "Script generation failed")

    # ── Phase 2B: Critic Feedback Loop ────────────────────────────
    state = phase_critic_loop(state)
    state["error"] = None

    # ── Phase 3A: Scene Director (FFmpeg tool planning) ───────────
    state = phase_scene_director(state)

    # ── Phase 3B: Production Prep (TTS, Whisper, SRT) ─────────────
    state = phase_production_prep(state)
    if state.get("error"):
        return _abort(state, "Production prep failed")

    # ── Phase 3C: Scene Render Loop (FFmpeg, self-healing) ────────
    state = phase_render_scenes(state)
    if state.get("error"):
        return _abort(state, "Scene rendering failed")

    # ── Phase 3D: Final Assembly ───────────────────────────────────
    state = phase_final_assembly(state)
    if state.get("error"):
        return _abort(state, "Final assembly failed")

    # ── Phase 4: Upload ────────────────────────────────────────────
    if state.get("video_path") and Path(state["video_path"]).exists():
        state = phase_upload(state)

    _print_summary(state)
    return dict(state)


def _abort(state: AgentState, reason: str) -> dict:
    print(f"\n[PIPELINE] ❌ ABORTED: {reason}")
    state["logs"].append(f"❌ Pipeline aborted: {reason} | error={state.get('error')}")
    return dict(state)


def _print_summary(state: AgentState):
    print(f"""
{'═' * 60}
  PIPELINE COMPLETE ✅
{'═' * 60}
  Topic:          {state.get('topic','')}
  Title:          {state.get('active_title','')}
  Critic Score:   {state.get('best_critic_score',0)}/10
  Critic Loops:   {state.get('critic_iterations',0) + 1}
  Scene Clips:    {len(state.get('scene_clips',[]))}
  FFmpeg Retries: {state.get('ffmpeg_retry_count',0)}
  Video:          {state.get('video_path','')}
  YouTube:        {state.get('youtube_url','—')}
  Status:         {state.get('upload_status','—')}
{'═' * 60}
PIPELINE LOGS:
""" + "\n".join(f"  {l}" for l in state.get("logs", [])) + "\n" + "═" * 60)


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    niche = sys.argv[1] if len(sys.argv) > 1 else "auto"
    run_agentic_pipeline(niche=niche, schedule_upload=True)
