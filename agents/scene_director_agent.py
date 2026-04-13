"""
agents/scene_director_agent.py

The Scene Director — an LLM that reads the approved script's emotional arc
and issues precise FFmpeg tool-call parameters for every scene.

This is pure tool-calling architecture:
    1. Director LLM reads each section (emotion, pacing, topic)
    2. Outputs a JSON array of "tool calls" — one per scene
    3. Each tool call maps to render_scene_with_ffmpeg() parameters
    4. If FFmpeg fails → Director receives the error and retries with fixed params

Tool call schema (per scene):
{
  "scene_idx":    0,
  "section":      "hook",
  "zoom_type":    "slow_in" | "fast_zoom" | "slow_out" | "drift_left" | "drift_right" | "static",
  "color_grade":  "dark_teal" | "warm_amber" | "cold_blue" | "red_noir" | "neutral",
  "text_position":"bottom_center" | "bottom_left" | "top_third",
  "intensity":    "low" | "medium" | "high",
  "vignette":     true | false,
  "reasoning":    "why this combination for this scene emotion"
}
"""

import json
import re
from utils.llm_client import LLMClient

llm = LLMClient()

SCENE_DIRECTOR_SYSTEM = """You are the Scene Director for a YouTube AI production engine.
You have access to one tool: render_scene_with_ffmpeg()

Your job: read the approved script's emotional arc, then issue a JSON array of tool calls.
One tool call per scene — each specifying the exact cinematic parameters for that scene.

AVAILABLE TOOL PARAMETERS:

zoom_type (controls camera movement energy):
  - "slow_in"     → gradual slow zoom IN (0.0003/frame) — best for: suspense build, psychology reveals
  - "fast_zoom"   → aggressive zoom IN (0.001/frame) — best for: shocking stats, hook openings
  - "slow_out"    → slow zoom OUT (reverse) — best for: revelations, emotional payoffs, callbacks
  - "drift_left"  → horizontal pan left — best for: storytelling, "here's what happened"
  - "drift_right" → horizontal pan right — best for: transitions, open loops, "but wait..."
  - "static"      → no movement — best for: important single statements, CTA outros

color_grade (cinematic color filter):
  - "dark_teal"   → cold, dark, psychological horror feel — eq+curves → deep shadow, teal shadows
  - "warm_amber"  → warm revelation lighting — eq+curves → lifted blacks, orange tones
  - "cold_blue"   → factual, clinical — eq+curves → blue shadows, high contrast
  - "red_noir"    → danger, warning, manipulation — eq+curves → red channel boost, dark
  - "neutral"     → clean, honest — minimal correction

text_position:
  - "bottom_center" → standard captions, best for most scenes
  - "bottom_left"   → dramatic offset for important points
  - "top_third"     → use SPARINGLY for re-hook moments only

intensity (controls strength of all effects):
  - "low"    → subtle, background
  - "medium" → standard cinematic
  - "high"   → aggressive, dramatic

vignette: true or false — adds dark edge fade. Use on dark/suspenseful scenes.

EMOTIONAL MAPPING RULES:
- hook → fast_zoom + dark_teal + high intensity + vignette
- open_loop → drift_right + dark_teal + medium + vignette  
- psychology/manipulation point → slow_in + dark_teal OR red_noir + high + vignette
- shocking stat/fact → fast_zoom + cold_blue + high + vignette
- story/example → drift_left + warm_amber OR neutral + medium
- revelation/callback → slow_out + warm_amber + high + vignette
- warning section → static OR slow_in + red_noir + high + vignette
- outro/CTA → static + neutral + low + no vignette

OUTPUT: VALID JSON ARRAY ONLY. No markdown. No explanation.
Array of exactly one tool call object per scene.
Start with [ and end with ]"""


def plan_scene_directives(script_data: dict, error_context: str = "") -> list:
    """
    Director LLM reads script → outputs tool call parameters for every scene.

    Args:
        script_data:   Approved script from script_agent / critic_agent loop
        error_context: If FFmpeg failed, pass the error here for self-healing retry

    Returns:
        List of directive dicts, one per scene
    """
    sections = script_data.get("sections", [])
    topic    = script_data.get("title", "unknown topic")

    scene_summary = []
    for i, sec in enumerate(sections):
        scene_summary.append(
            f"Scene {i} | section={sec.get('section','')} | "
            f"heading={sec.get('heading','')} | "
            f"body_preview={sec.get('body','')[:80]}..."
        )

    scenes_text = "\n".join(scene_summary)

    if error_context:
        error_block = f"""
⚠️ SELF-HEALING MODE ACTIVE ⚠️
Previous FFmpeg render failed with this error:
{error_context}

Analyze the error. The most common causes:
- Invalid filter expression → use simpler zoom parameters
- Color grade conflict → switch to "neutral" for problematic scenes
- Text position issue → revert to "bottom_center"

Adjust your tool calls to avoid this error. Keep the cinematic feel where safe."""
    else:
        error_block = ""

    user_msg = f"""Topic: {topic}
Total scenes: {len(sections)}

Scene breakdown:
{scenes_text}
{error_block}

Issue one tool call per scene. Output ONLY a raw JSON array.
Start with [ and end with ]"""

    messages = [
        {"role": "system", "content": SCENE_DIRECTOR_SYSTEM},
        {"role": "user",   "content": user_msg},
    ]

    print(f"[SCENE DIRECTOR] Planning cinematic parameters for {len(sections)} scenes...")
    if error_context:
        print(f"[SCENE DIRECTOR] Self-healing mode — fixing FFmpeg error")

    raw     = llm.complete(messages, max_tokens=1500, temperature=0.5)
    cleaned = re.sub(r"```json|```", "", raw).strip()

    if not cleaned.startswith("["):
        start = cleaned.find("[")
        if start != -1:
            cleaned = cleaned[start:]

    try:
        directives = json.loads(cleaned)
        directives = _validate_directives(directives, sections)
        _print_directives(directives)
        return directives
    except json.JSONDecodeError as e:
        print(f"[SCENE DIRECTOR] JSON parse failed: {e} — using safe defaults")
        return _fallback_directives(sections)


def _validate_directives(directives: list, sections: list) -> list:
    valid_zoom   = {"slow_in", "fast_zoom", "slow_out", "drift_left", "drift_right", "static"}
    valid_grade  = {"dark_teal", "warm_amber", "cold_blue", "red_noir", "neutral"}
    valid_pos    = {"bottom_center", "bottom_left", "top_third"}
    valid_intens = {"low", "medium", "high"}

    defaults_by_section = {
        "hook":      ("fast_zoom",   "dark_teal",  "bottom_center", "high",   True),
        "open_loop": ("drift_right", "dark_teal",  "bottom_center", "medium", True),
        "callback":  ("slow_out",    "warm_amber",  "bottom_center", "high",   True),
        "outro":     ("static",      "neutral",    "bottom_center", "low",    False),
    }

    validated = []
    for i, sec in enumerate(sections):
        sec_name = sec.get("section", f"point_{i}")
        d_zoom, d_grade, d_pos, d_intens, d_vig = defaults_by_section.get(
            sec_name, ("slow_in", "dark_teal", "bottom_center", "medium", True)
        )

        if i < len(directives):
            d = directives[i]
        else:
            d = {}

        validated.append({
            "scene_idx":    i,
            "section":      sec_name,
            "zoom_type":    d.get("zoom_type",    d_zoom)    if d.get("zoom_type")    in valid_zoom   else d_zoom,
            "color_grade":  d.get("color_grade",  d_grade)   if d.get("color_grade")  in valid_grade  else d_grade,
            "text_position":d.get("text_position",d_pos)     if d.get("text_position") in valid_pos   else d_pos,
            "intensity":    d.get("intensity",    d_intens)  if d.get("intensity")    in valid_intens else d_intens,
            "vignette":     bool(d.get("vignette", d_vig)),
            "reasoning":    d.get("reasoning", f"Default cinematic for {sec_name}"),
        })

    return validated


def _fallback_directives(sections: list) -> list:
    section_map = {
        "hook":      ("fast_zoom",   "dark_teal",  "high",   True),
        "open_loop": ("drift_right", "dark_teal",  "medium", True),
        "callback":  ("slow_out",    "warm_amber", "high",   True),
        "outro":     ("static",      "neutral",    "low",    False),
    }
    result = []
    for i, sec in enumerate(sections):
        name = sec.get("section", f"point_{i}")
        zoom, grade, intens, vig = section_map.get(name, ("slow_in", "dark_teal", "medium", True))
        result.append({
            "scene_idx":     i,
            "section":       name,
            "zoom_type":     zoom,
            "color_grade":   grade,
            "text_position": "bottom_center",
            "intensity":     intens,
            "vignette":      vig,
            "reasoning":     "Fallback directive",
        })
    return result


def _print_directives(directives: list):
    print("[SCENE DIRECTOR] ═══ SCENE DIRECTIVES ═══")
    for d in directives:
        print(
            f"  Scene {d['scene_idx']:02d} [{d['section']:<12}] "
            f"zoom={d['zoom_type']:<12} grade={d['color_grade']:<12} "
            f"intensity={d['intensity']:<6} vignette={d['vignette']}"
        )
    print("══════════════════════════════════════════")
