"""
agents/ffmpeg_tool.py

FFmpeg as an LLM Tool — dynamic scene rendering driven by Scene Director parameters.

Each call renders ONE scene (one image → video clip) using director-specified parameters.
The orchestrator assembles all scene clips → final video.

Self-healing flow:
    try render_scene_with_ffmpeg()
    if fails → pass stderr to scene_director_agent.plan_scene_directives(error_context=stderr)
    retry with new parameters (up to MAX_FFMPEG_RETRIES times)
"""

import os
import subprocess
import traceback
from pathlib import Path
from typing import Optional

OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)

VIDEO_W  = 1920
VIDEO_H  = 1080
FPS      = 24
MAX_FFMPEG_RETRIES = 3

# ══════════════════════════════════════════════════════════════════════════════
#  ZOOM PARAMETER MAPS
#  zoompan= z='expr':x='expr':y='expr':d=frames:s=WxH:fps=FPS
# ══════════════════════════════════════════════════════════════════════════════

def _zoom_filter(zoom_type: str, intensity: str, duration_frames: int) -> str:
    d = duration_frames
    W, H = VIDEO_W, VIDEO_H

    step_map = {
        ("slow_in",     "low"):    0.0002,
        ("slow_in",     "medium"): 0.0003,
        ("slow_in",     "high"):   0.0005,
        ("fast_zoom",   "low"):    0.0006,
        ("fast_zoom",   "medium"): 0.0008,
        ("fast_zoom",   "high"):   0.0012,
        ("slow_out",    "low"):    0.0002,
        ("slow_out",    "medium"): 0.0003,
        ("slow_out",    "high"):   0.0005,
        ("drift_left",  "low"):    0.0002,
        ("drift_left",  "medium"): 0.0003,
        ("drift_left",  "high"):   0.0005,
        ("drift_right", "low"):    0.0002,
        ("drift_right", "medium"): 0.0003,
        ("drift_right", "high"):   0.0005,
        ("static",      "low"):    0.0,
        ("static",      "medium"): 0.0,
        ("static",      "high"):   0.0,
    }
    step = step_map.get((zoom_type, intensity), 0.0003)

    if zoom_type == "slow_in":
        z_expr = f"min(zoom+{step},1.3)"
        x_expr = f"iw/2-(iw/zoom/2)"
        y_expr = f"ih/2-(ih/zoom/2)"

    elif zoom_type == "fast_zoom":
        z_expr = f"min(zoom+{step},1.5)"
        x_expr = f"iw/2-(iw/zoom/2)"
        y_expr = f"ih/2-(ih/zoom/2)"

    elif zoom_type == "slow_out":
        z_expr = f"max(1.3-on*{step},1.0)"
        x_expr = f"iw/2-(iw/zoom/2)"
        y_expr = f"ih/2-(ih/zoom/2)"

    elif zoom_type == "drift_left":
        z_expr = f"min(zoom+{step/3},1.15)"
        x_expr = f"iw/2-(iw/zoom/2)+on*0.5"
        y_expr = f"ih/2-(ih/zoom/2)"

    elif zoom_type == "drift_right":
        z_expr = f"min(zoom+{step/3},1.15)"
        x_expr = f"iw/2-(iw/zoom/2)-on*0.5"
        y_expr = f"ih/2-(ih/zoom/2)"

    else:
        z_expr = "1.0"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    return (
        f"zoompan=z='{z_expr}':"
        f"x='{x_expr}':"
        f"y='{y_expr}':"
        f"d={d}:s={W}x{H}:fps={FPS}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  COLOR GRADE MAPS
#  Applied via eq + curves filters
# ══════════════════════════════════════════════════════════════════════════════

COLOR_GRADES = {
    "dark_teal": (
        "eq=contrast=1.12:saturation=0.85:brightness=-0.02:gamma=0.95,"
        "curves=r='0/0 0.5/0.42 1/0.88':g='0/0 0.5/0.5 1/0.95':b='0/0 0.5/0.58 1/1.05'"
    ),
    "warm_amber": (
        "eq=contrast=1.05:saturation=1.15:brightness=0.02,"
        "curves=r='0/0 0.5/0.55 1/1.05':g='0/0 0.5/0.5 1/0.95':b='0/0 0.5/0.42 1/0.82'"
    ),
    "cold_blue": (
        "eq=contrast=1.15:saturation=0.9:brightness=-0.01,"
        "curves=r='0/0 0.5/0.44 1/0.88':g='0/0 0.5/0.5 1/0.96':b='0/0 0.5/0.58 1/1.08'"
    ),
    "red_noir": (
        "eq=contrast=1.18:saturation=0.8:brightness=-0.03,"
        "curves=r='0/0 0.5/0.58 1/1.08':g='0/0 0.5/0.44 1/0.88':b='0/0 0.5/0.42 1/0.85'"
    ),
    "neutral": (
        "eq=contrast=1.05:saturation=1.1:brightness=0.01"
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
#  TEXT POSITION MAP (margin adjustments for subtitle ASS style)
# ══════════════════════════════════════════════════════════════════════════════

TEXT_POSITIONS = {
    "bottom_center": {"alignment": 2, "margin_v": 60,  "margin_l": 0,  "margin_r": 0},
    "bottom_left":   {"alignment": 1, "margin_v": 60,  "margin_l": 80, "margin_r": 0},
    "top_third":     {"alignment": 8, "margin_v": 220, "margin_l": 0,  "margin_r": 0},
}

# ══════════════════════════════════════════════════════════════════════════════
#  CORE TOOL FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def render_scene_with_ffmpeg(
    scene_idx:    int,
    image_path:   str,
    duration:     float,
    srt_path:     str,
    zoom_type:    str = "slow_in",
    color_grade:  str = "dark_teal",
    text_position:str = "bottom_center",
    intensity:    str = "medium",
    vignette:     bool = True,
    output_path:  Optional[str] = None,
) -> dict:
    """
    Render one scene clip from an image using Director-specified FFmpeg parameters.

    Args:
        scene_idx:     Scene index (for file naming and logging)
        image_path:    Path to source image
        duration:      Scene duration in seconds
        srt_path:      Path to .srt subtitle file
        zoom_type:     Camera movement style (from Scene Director)
        color_grade:   Color grading preset (from Scene Director)
        text_position: Subtitle position (from Scene Director)
        intensity:     Effect intensity multiplier
        vignette:      Whether to add dark vignette edges
        output_path:   Override output path (auto-generated if None)

    Returns:
        {
            "success":     bool,
            "output_path": str or None,
            "error":       str or None,   # FFmpeg stderr for self-healing
            "scene_idx":   int,
            "params_used": dict,          # what was actually used (for logging)
        }
    """
    if output_path is None:
        output_path = str(OUTPUTS_DIR / f"scene_clip_{scene_idx:02d}.mp4")

    dur_frames = max(int(duration * FPS), FPS)

    zoom_expr   = _zoom_filter(zoom_type, intensity, dur_frames)
    grade_expr  = COLOR_GRADES.get(color_grade, COLOR_GRADES["neutral"])
    pos_cfg     = TEXT_POSITIONS.get(text_position, TEXT_POSITIONS["bottom_center"])

    subtitle_style = (
        f"FontName=Arial Black,"
        f"FontSize=14,"
        f"Bold=1,"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"BackColour=&H80000000,"
        f"BorderStyle=3,"
        f"Outline=2,"
        f"Shadow=1,"
        f"Alignment={pos_cfg['alignment']},"
        f"MarginV={pos_cfg['margin_v']},"
        f"MarginL={pos_cfg['margin_l']},"
        f"MarginR={pos_cfg['margin_r']}"
    )

    abs_srt     = str(Path(srt_path).resolve())
    vignette_f  = ",vignette=PI/5" if vignette else ""
    unsharp_f   = ",unsharp=5:5:0.8" if intensity in ("medium", "high") else ""

    filter_chain = (
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},"
        f"{zoom_expr},"
        f"setpts=PTS-STARTPTS,"
        f"{grade_expr}"
        f"{unsharp_f}"
        f"{vignette_f},"
        f"subtitles='{abs_srt}':force_style='{subtitle_style}'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(duration), "-i", image_path,
        "-vf", filter_chain,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        output_path,
    ]

    params_used = {
        "zoom_type":    zoom_type,
        "color_grade":  color_grade,
        "text_position":text_position,
        "intensity":    intensity,
        "vignette":     vignette,
    }

    print(f"[FFMPEG TOOL] Scene {scene_idx:02d} | "
          f"zoom={zoom_type} grade={color_grade} intensity={intensity}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode == 0:
            print(f"[FFMPEG TOOL] ✅ Scene {scene_idx:02d} → {output_path}")
            return {
                "success":     True,
                "output_path": output_path,
                "error":       None,
                "scene_idx":   scene_idx,
                "params_used": params_used,
            }
        else:
            error_msg = result.stderr[-2000:] if result.stderr else "Unknown FFmpeg error"
            print(f"[FFMPEG TOOL] ❌ Scene {scene_idx:02d} failed:\n{error_msg[-500:]}")
            return {
                "success":     False,
                "output_path": None,
                "error":       error_msg,
                "scene_idx":   scene_idx,
                "params_used": params_used,
            }

    except subprocess.TimeoutExpired:
        error_msg = f"FFmpeg timed out after 120s on scene {scene_idx}"
        print(f"[FFMPEG TOOL] ⏱️ {error_msg}")
        return {
            "success":     False,
            "output_path": None,
            "error":       error_msg,
            "scene_idx":   scene_idx,
            "params_used": params_used,
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "success":     False,
            "output_path": None,
            "error":       str(e),
            "scene_idx":   scene_idx,
            "params_used": params_used,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  CONCAT TOOL — Assemble scene clips into final video
# ══════════════════════════════════════════════════════════════════════════════

def concat_scenes_with_audio(
    clip_paths:  list,
    audio_path:  str,
    output_path: str,
    bgm_path:    Optional[str] = None,
) -> dict:
    """
    Concatenate rendered scene clips + voice audio + optional BGM into final MP4.

    Args:
        clip_paths:  Ordered list of .mp4 scene clip paths
        audio_path:  Voice narration WAV
        output_path: Final MP4 path
        bgm_path:    Optional background music MP3

    Returns:
        {"success": bool, "output_path": str, "error": str or None}
    """
    if not clip_paths:
        return {"success": False, "output_path": None, "error": "No scene clips to concat"}

    concat_list = str(OUTPUTS_DIR / "concat_list.txt")
    with open(concat_list, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{Path(clip).resolve()}'\n")

    concat_video = str(OUTPUTS_DIR / "concat_video.mp4")
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c:v", "libx264", "-preset", "fast", "-crf", "16",
        "-pix_fmt", "yuv420p",
        concat_video,
    ]

    print(f"[FFMPEG TOOL] Concatenating {len(clip_paths)} scene clips...")
    result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        return {
            "success":     False,
            "output_path": None,
            "error":       result.stderr[-2000:],
        }

    if bgm_path and Path(bgm_path).exists():
        audio_filter = (
            f"[1:a]volume=1.0[voice];"
            f"[2:a]volume=0.15,aloop=loop=-1:size=2e+09[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first:weights=1 0.15[mixed]"
        )
        mix_cmd = [
            "ffmpeg", "-y",
            "-i", concat_video,
            "-i", audio_path,
            "-i", bgm_path,
            "-filter_complex", audio_filter,
            "-map", "0:v",
            "-map", "[mixed]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            output_path,
        ]
    else:
        mix_cmd = [
            "ffmpeg", "-y",
            "-i", concat_video,
            "-i", audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            output_path,
        ]

    print(f"[FFMPEG TOOL] Mixing audio → {output_path}")
    result = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=300)

    try:
        Path(concat_video).unlink(missing_ok=True)
        Path(concat_list).unlink(missing_ok=True)
    except Exception:
        pass

    if result.returncode == 0:
        print(f"[FFMPEG TOOL] ✅ Final video: {output_path}")
        return {"success": True, "output_path": output_path, "error": None}
    else:
        return {
            "success":     False,
            "output_path": None,
            "error":       result.stderr[-2000:],
        }
