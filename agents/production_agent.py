"""
agents/production_agent.py
Full pipeline:
  1. Kokoro TTS (af_nicole, voice blending, -- pauses)
  2. HTML generation (Three.js + GSAP template)
     → queries effects_library.db for real XML animations
     → injects per-scene GSAP code from your Alight Motion XMLs
  3. Playwright recording → ffmpeg merge → final MP4
"""

import os
import json
import sqlite3
import shutil
import subprocess
import traceback
from pathlib import Path
from datetime import datetime

import numpy as np
import soundfile as sf

OUTPUTS_DIR   = Path("outputs")
TEMPLATE_PATH = Path("templates/video_template.html")
DB_PATH       = Path("effects_library.db")
OUTPUTS_DIR.mkdir(exist_ok=True)

COLOR_SCHEME_MAP = {
    "red_black":         "red_black",
    "neon_dark":         "neon_dark",
    "white_bold":        "white_bold",
    "blue_professional": "blue_professional",
    "gold_dark":         "gold_dark",
}

# ── Gemini-confirmed: Raw Kokoro > filtered. No pitch/reverb.
VOICE_PROFILES = {
    "psychology": {"voice": "af_nicole",            "speed": 1.0},
    "mystery":    {"voice": "af_nicole:0.8,am_adam:0.2", "speed": 1.0},
    "motivation": {"voice": "am_echo",              "speed": 1.0},
    "facts":      {"voice": "af_nicole",            "speed": 1.0},
    "history":    {"voice": "am_echo",              "speed": 1.0},
    "default":    {"voice": "af_nicole",            "speed": 1.0},
}

BGM_FALLBACKS = {
    "dark_suspense":      "https://cdn.pixabay.com/audio/2023/10/30/audio_3b3d7c8e0a.mp3",
    "lo_fi_chill":        "https://cdn.pixabay.com/audio/2022/10/25/audio_1196c9e639.mp3",
    "epic_dramatic":      "https://cdn.pixabay.com/audio/2023/06/05/audio_8417e64fe9.mp3",
    "mysterious_ambient": "https://cdn.pixabay.com/audio/2022/03/15/audio_1a609cbb6d.mp3",
}

EMOJI_MAP = {
    "brain":"🧠","heart":"❤️","mask":"🎭","eye":"👁️","fire":"🔥",
    "lock":"🔒","key":"🗝️","star":"⭐","warning":"⚠️","money":"💰",
    "people":"👥","thought":"💭","power":"⚡","dark":"🌑","light":"💡",
    "success":"🏆","habit":"📋","mind":"🧩","emotion":"😤","share":"📤",
    "manipulation":"🕵️","trust":"🤝","fear":"😨","control":"🎮","anger":"😡",
}

# ── Vibe tag per section type ──────────────────────────────
SECTION_VIBE_MAP = {
    "hook":     ["scale_pop", "quick_pop", "bounce_in"],
    "open_loop":["slide_horizontal", "wipe_transition"],
    "point_1":  ["bounce_in", "slide_vertical", "fade_in"],
    "point_2":  ["slide_horizontal", "bounce_in", "scale_pop"],
    "point_3":  ["wipe_transition", "slide_vertical", "bounce_in"],
    "point_4":  ["bounce_in", "scale_pop", "fade_in"],
    "point_5":  ["slide_horizontal", "bounce_in", "glow_reveal"],
    "point_6":  ["wipe_transition", "scale_pop", "bounce_in"],
    "point_7":  ["bounce_in", "slide_vertical", "fade_in"],
    "callback": ["glow_reveal", "fade_in", "short_anim"],
    "outro":    ["fade_in", "glow_reveal"],
    "main":     ["bounce_in", "slide_horizontal", "scale_pop"],
}


# ══════════════════════════════════════════════
#  EFFECTS DB QUERY
# ══════════════════════════════════════════════

def _query_gsap(vibe_tags: list, max_dur_ms: int = 5000) -> str:
    """
    Query effects_library.db for a GSAP animation matching vibe.
    Returns gsap_code string with {el} placeholder.
    """
    if not DB_PATH.exists():
        return ""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        for vibe in vibe_tags:
            row = conn.execute("""
                SELECT gsap_code FROM effects_library
                WHERE vibe_tag = ?
                  AND duration_ms <= ?
                  AND gsap_code != ''
                ORDER BY RANDOM() LIMIT 1
            """, (vibe, max_dur_ms)).fetchone()
            if row and row[0]:
                conn.close()
                return row[0]
        conn.close()
    except Exception as e:
        print(f"[DB] Query failed: {e}")
    return ""


# ══════════════════════════════════════════════
#  AUDIO PIPELINE (Kokoro raw, no filters)
# ══════════════════════════════════════════════

def generate_kokoro_tts(script_text: str, output_path: str,
                        voice: str = "af_nicole", speed: float = 1.0):
    try:
        from kokoro import KPipeline
        import torch

        if ':' in voice and ',' in voice:
            # Voice blending: "af_nicole:0.8,am_adam:0.2"
            print(f"[TTS] Kokoro blend: {voice}")
            parts    = [p.strip().split(':') for p in voice.split(',')]
            voice_ws = [(p[0].strip(), float(p[1])) for p in parts]
            pipeline = KPipeline(lang_code='a')
            blended  = None
            for v_name, weight in voice_ws:
                try:
                    vt      = pipeline.load_voice(v_name)
                    blended = vt*weight if blended is None else blended+vt*weight
                except Exception as ve:
                    print(f"[TTS] Voice {v_name} failed: {ve}")
            if blended is None:
                raise ValueError("All blends failed")
            chunks = [a for _,_,a in pipeline(script_text, voice=blended, speed=speed)]
        else:
            print(f"[TTS] Kokoro | voice={voice} speed={speed}")
            pipeline = KPipeline(lang_code='a')
            chunks   = [a for _,_,a in pipeline(script_text, voice=voice, speed=speed)]

        if not chunks:
            raise ValueError("Empty audio")

        sf.write(output_path, np.concatenate(chunks), 24000)
        print(f"[TTS] Saved: {output_path}")

    except Exception as e:
        print(f"[TTS] Kokoro failed: {e}")
        traceback.print_exc()
        _gtts_fallback(script_text, output_path)


def _gtts_fallback(script_text: str, output_path: str):
    try:
        from gtts import gTTS
        import librosa
        mp3 = output_path.replace(".wav","_tmp.mp3")
        gTTS(text=script_text, lang='en', slow=False).save(mp3)
        audio, sr = librosa.load(mp3, sr=24000)
        sf.write(output_path, audio, sr)
        os.remove(mp3)
        print(f"[TTS] gTTS saved: {output_path}")
    except Exception as e:
        print(f"[TTS] gTTS failed: {e}")
        traceback.print_exc()


def generate_audio(script_text: str, topic: str, niche: str = "default") -> str:
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    profile = VOICE_PROFILES.get(niche.lower().strip(), VOICE_PROFILES["default"])
    path    = str(OUTPUTS_DIR / f"audio_{ts}.wav")

    generate_kokoro_tts(script_text, path,
                        voice=profile["voice"],
                        speed=profile["speed"])
    print(f"[AUDIO] Ready: {path}")
    return path


# ══════════════════════════════════════════════
#  HTML CONFIG BUILDER
#  Injects real XML GSAP animations per scene
# ══════════════════════════════════════════════

def _get_emoji(kw: str) -> str:
    for k, v in EMOJI_MAP.items():
        if k in kw.lower(): return v
    return "🧠"


def _build_config(script_data: dict, timeline: list, topic: str,
                  niche: str, color_scheme: str, channel: str) -> dict:

    title    = script_data.get("title", topic)
    bgm_mood = script_data.get("bgm_mood", "dark_suspense")
    bgm_url  = BGM_FALLBACKS.get(bgm_mood, BGM_FALLBACKS["dark_suspense"])

    # Title → 3 display lines
    words = title.upper().split()
    lines, line = [], ""
    for w in words:
        test = (line+" "+w).strip()
        if len(test) <= 16: line = test
        else:
            if line: lines.append(line)
            line = w
    if line: lines.append(line)
    lines = lines[:3]

    sections = script_data.get("sections", [])

    # ── INTRO SCENE ──
    intro = {
        "type":        "intro",
        "duration_ms": 7000,
        "title_lines": lines,
        "eyebrow":     niche.capitalize(),
        "subtitle":    (script_data.get("description","") or "")[:120],
        "count":       str(len([s for s in sections if "point" in s.get("section","")])),
        "count_label": "Key Points",
        # XML animation injected from DB
        "gsap_intro":  _query_gsap(["bounce_in","scale_pop","slide_horizontal"], 4000),
    }

    # ── POINT SCENES ──
    point_scenes = []
    for i, sec in enumerate(sections):
        sec_type = sec.get("section", "main")
        if sec_type == "outro": continue

        tl     = timeline[i] if i < len(timeline) else {}
        kw     = tl.get("icon_keyword", sec.get("icon_keyword","brain"))
        dur_ms = max(int(sec.get("duration_secs",22)*1000), 10000)

        # Pick vibe tags for this section type
        vibes     = SECTION_VIBE_MAP.get(sec_type, SECTION_VIBE_MAP["main"])
        gsap_code = _query_gsap(vibes, dur_ms)

        point_scenes.append({
            "type":        "point",
            "duration_ms": dur_ms,
            "num":         str(i+1).zfill(2),
            "heading":     sec.get("heading", f"Point {i+1}").upper(),
            "body":        sec.get("body", tl.get("text","")),
            "tag":         sec.get("section","insight").replace("_"," ").title(),
            "emoji":       sec.get("emoji") or _get_emoji(kw),
            "gsap_anim":   gsap_code,   # ← Real XML animation from DB
        })

    # ── OUTRO SCENE ──
    outro = {
        "type":        "outro",
        "duration_ms": 8000,
        "heading":     "FOLLOW FOR MORE",
        "sub":         f"New videos every week — {niche.capitalize()}",
        "cta":         "👍  Like · Subscribe · Share",
        "icons":       [
            {"emoji":"🔔","label":"Subscribe"},
            {"emoji":"👍","label":"Like"},
            {"emoji":"📤","label":"Share"},
        ],
        "gsap_outro": _query_gsap(["fade_in","glow_reveal"], 5000),
    }

    db_loaded = DB_PATH.exists()
    print(f"[HTML] DB animations: {'✅ loaded' if db_loaded else '⚠️ DB not found, using fallback GSAP'}")

    return {
        "topic":        topic,
        "niche":        niche.capitalize(),
        "channel":      channel,
        "color_scheme": COLOR_SCHEME_MAP.get(color_scheme,"red_black"),
        "bgm_url":      bgm_url,
        "scenes":       [intro] + point_scenes + [outro],
    }


def generate_html(script_data: dict, timeline: list, topic: str,
                  niche: str = "psychology", color_scheme: str = "red_black",
                  channel: str = "AI Channel") -> str:
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = str(OUTPUTS_DIR / f"video_{ts}.html")

    config      = _build_config(script_data, timeline, topic, niche, color_scheme, channel)
    config_json = json.dumps(config, ensure_ascii=False, indent=2)
    template    = TEMPLATE_PATH.read_text(encoding="utf-8")

    Path(out).write_text(template.replace("__CONFIG__", config_json), encoding="utf-8")

    total_s = sum(s["duration_ms"] for s in config["scenes"]) // 1000
    print(f"[HTML] {out} | {len(config['scenes'])} scenes | {total_s}s")
    return out


# ══════════════════════════════════════════════
#  PLAYWRIGHT RECORDING
# ══════════════════════════════════════════════

FPS = 24

def _frames_to_video(frames_dir: Path, raw_video: str):
    cmd = ["ffmpeg","-y","-framerate",str(FPS),
           "-i",str(frames_dir/"frame_%05d.png"),
           "-c:v","libx264","-preset","fast","-pix_fmt","yuv420p","-crf","18",raw_video]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg frames→video: {r.stderr.decode()[:300]}")
    print(f"[FFMPEG] Encoded: {raw_video}")


def _merge_audio_video(video: str, audio: str, output: str):
    cmd = ["ffmpeg","-y","-i",video,"-i",audio,
           "-c:v","copy","-c:a","aac","-shortest",output]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg merge: {r.stderr.decode()[:300]}")
    print(f"[MERGE] Final: {output}")


def record_video(html_path: str, audio_path: str,
                 output_path: str, duration: int) -> str:
    from playwright.sync_api import sync_playwright

    ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
    frames_dir   = OUTPUTS_DIR / f"frames_{ts}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    raw_video    = str(OUTPUTS_DIR / f"raw_{ts}.mp4")
    abs_path     = str(Path(html_path).resolve())
    total_frames = duration * FPS

    print(f"[RECORD] {duration}s × {FPS}fps = {total_frames} frames")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=[
                "--no-sandbox","--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--allow-file-access-from-files",
            ])
            page = browser.new_page(viewport={"width":1920,"height":1080})
            page.goto(f"file://{abs_path}", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(800)

            for i in range(total_frames):
                page.screenshot(path=str(frames_dir/f"frame_{i:05d}.png"), full_page=False)
                if i % (FPS*5) == 0:
                    print(f"[RECORD] {i//FPS}s / {duration}s ({i}/{total_frames})")

            browser.close()
        print(f"[RECORD] All {total_frames} frames captured")

    except Exception as e:
        shutil.rmtree(frames_dir, ignore_errors=True)
        raise RuntimeError(f"Playwright failed: {e}") from e

    try:
        _frames_to_video(frames_dir, raw_video)
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)

    _merge_audio_video(raw_video, audio_path, output_path)
    try: os.remove(raw_video)
    except: pass

    return output_path


# ══════════════════════════════════════════════
#  MAIN ENTRY
# ══════════════════════════════════════════════

def render_video(
    audio_path: str, timeline: list, script_data: dict, topic: str,
    thumbnail_style: str  = "plain_icon",
    thumbnail_colors: str = "red_black",
    niche: str            = "default",
    channel: str          = "AI Channel",
) -> str:
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = str(OUTPUTS_DIR / f"video_{ts}.mp4")

    if timeline:
        last     = max(timeline, key=lambda x: x.get("time_secs",0)+x.get("duration_secs",0))
        duration = int(last.get("time_secs",0)+last.get("duration_secs",30))+15
    else:
        duration = 210

    print(f"[VIDEO] {duration}s | niche={niche} | XML animations: {'✅' if DB_PATH.exists() else '❌ run xml_analyzer first'}")

    html_path = generate_html(
        script_data=script_data, timeline=timeline, topic=topic,
        niche=niche, color_scheme=thumbnail_colors, channel=channel,
    )
    record_video(html_path=html_path, audio_path=audio_path,
                 output_path=out, duration=duration)
    print(f"[VIDEO] Done: {out}")
    return out
