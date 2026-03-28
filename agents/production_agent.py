import os
import json
import time
import signal
import asyncio
import shutil
import subprocess
import traceback
from pathlib import Path
from datetime import datetime

import numpy as np
import soundfile as sf
from PIL import Image

OUTPUTS_DIR  = Path("outputs")
TEMPLATE_PATH = Path("templates/video_template.html")
OUTPUTS_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────
#  COLOR SCHEME MAP  (matches video_template.html)
# ─────────────────────────────────────────────
COLOR_SCHEME_MAP = {
    "red_black":         "red_black",
    "neon_dark":         "neon_dark",
    "white_bold":        "white_bold",
    "blue_professional": "blue_professional",
    "gold_dark":         "gold_dark",
}

# ─────────────────────────────────────────────
#  VOICE PROFILES
# ─────────────────────────────────────────────
VOICE_PROFILES = {
    "psychology": {"voice":"am_echo",  "speed":0.95, "pitch_semitones":-1.5, "reverb_room":0.30, "bass_boost":True},
    "mystery":    {"voice":"am_echo",  "speed":0.90, "pitch_semitones":-2.5, "reverb_room":0.55, "bass_boost":True},
    "motivation": {"voice":"am_onyx",  "speed":1.05, "pitch_semitones": 0.0, "reverb_room":0.10, "bass_boost":False},
    "facts":      {"voice":"af_heart", "speed":1.0,  "pitch_semitones": 0.5, "reverb_room":0.15, "bass_boost":False},
    "history":    {"voice":"am_echo",  "speed":0.97, "pitch_semitones":-1.0, "reverb_room":0.35, "bass_boost":True},
    "default":    {"voice":"am_echo",  "speed":1.0,  "pitch_semitones": 0.0, "reverb_room":0.20, "bass_boost":False},
}

# Emoji map for keywords
EMOJI_MAP = {
    "brain":"🧠","heart":"❤️","mask":"🎭","eye":"👁️","fire":"🔥","lock":"🔒",
    "key":"🗝️","star":"⭐","warning":"⚠️","check":"✅","arrow":"➡️","money":"💰",
    "people":"👥","thought":"💭","power":"⚡","dark":"🌑","light":"💡","time":"⏰",
    "success":"🏆","habit":"📋","mind":"🧩","emotion":"😤","manipulation":"🕵️",
    "trust":"🤝","fear":"😨","control":"🎮","anger":"😡","love":"💕","stress":"😰",
}


# ══════════════════════════════════════════════
#  PHASE 1 — AUDIO (Kokoro + Pedalboard)
# ══════════════════════════════════════════════

def generate_kokoro_tts(script_text: str, output_path: str, voice: str = "am_echo", speed: float = 1.0):
    try:
        from kokoro import KPipeline
        print(f"[TTS] Kokoro generating | voice={voice} speed={speed}")
        pipeline = KPipeline(lang_code='a')
        chunks = []
        for _, _, audio in pipeline(script_text, voice=voice, speed=speed):
            chunks.append(audio)
        if not chunks:
            raise ValueError("Kokoro returned empty audio")
        sf.write(output_path, np.concatenate(chunks), 24000)
        print(f"[TTS] Kokoro saved: {output_path}")
    except Exception as e:
        print(f"[TTS] Kokoro failed: {e} — falling back to gTTS")
        traceback.print_exc()
        _gtts_fallback(script_text, output_path)


def _gtts_fallback(script_text: str, output_path: str):
    try:
        from gtts import gTTS
        import librosa
        print("[TTS] Using gTTS fallback...")
        mp3 = output_path.replace(".wav", "_gtts.mp3")
        gTTS(text=script_text, lang='en', slow=False).save(mp3)
        audio, sr = librosa.load(mp3, sr=24000)
        sf.write(output_path, audio, sr)
        os.remove(mp3)
        print(f"[TTS] gTTS saved: {output_path}")
    except Exception as e:
        print(f"[TTS] gTTS also failed: {e}")
        traceback.print_exc()


def apply_voice_profile(input_path: str, output_path: str, profile: dict):
    try:
        import librosa
        from pedalboard import Pedalboard, Reverb, Compressor, HighpassFilter, LowShelfFilter
        print(f"[VOICE] Applying profile: pitch={profile['pitch_semitones']}, reverb={profile['reverb_room']}, bass={profile['bass_boost']}")
        audio, sr = librosa.load(input_path, sr=24000, mono=True)
        if profile["speed"] != 1.0:
            audio = librosa.effects.time_stretch(audio, rate=profile["speed"])
        if profile["pitch_semitones"] != 0.0:
            audio = librosa.effects.pitch_shift(audio, sr=sr, n_steps=profile["pitch_semitones"])
        chain = [
            HighpassFilter(cutoff_frequency_hz=80),
            Compressor(threshold_db=-20, ratio=3.0),
            Reverb(room_size=profile["reverb_room"], damping=0.7, wet_level=0.15, dry_level=0.85),
        ]
        if profile.get("bass_boost"):
            from pedalboard import LowShelfFilter
            chain.append(LowShelfFilter(cutoff_frequency_hz=200, gain_db=3.5))
        board = Pedalboard(chain)
        processed = board(audio.reshape(1, -1), sr)
        sf.write(output_path, processed.T, sr)
        print(f"[VOICE] Processed: {output_path}")
    except Exception as e:
        print(f"[VOICE] Pedalboard failed: {e} — using raw")
        traceback.print_exc()
        shutil.copy(input_path, output_path)


def generate_audio(script_text: str, topic: str, niche: str = "default") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    profile = VOICE_PROFILES.get(niche.lower().strip(), VOICE_PROFILES["default"])
    raw_path   = str(OUTPUTS_DIR / f"audio_raw_{ts}.wav")
    final_path = str(OUTPUTS_DIR / f"audio_{ts}.wav")

    generate_kokoro_tts(script_text, raw_path, voice=profile["voice"], speed=profile["speed"])
    apply_voice_profile(raw_path, final_path, {**profile, "speed": 1.0})

    try:
        os.remove(raw_path)
    except Exception:
        pass

    print(f"[AUDIO] Ready: {final_path}")
    return final_path


# ══════════════════════════════════════════════
#  PHASE 2 — HTML GENERATION
#  Converts script_data + timeline → CONFIG JSON
#  injected into video_template.html
# ══════════════════════════════════════════════

def _get_emoji(keyword: str) -> str:
    kw = keyword.lower()
    for k, v in EMOJI_MAP.items():
        if k in kw:
            return v
    return "🧠"


def _build_config(script_data: dict, timeline: list, topic: str,
                  niche: str, color_scheme: str, channel: str) -> dict:
    """
    Convert LangGraph script_data + timeline into CONFIG dict for HTML template.

    script_data keys expected:
      title, sections (list of {heading, body, tag?}), description, tags
    timeline keys expected:
      time_secs, duration_secs, text, icon_keyword
    """
    sections = script_data.get("sections", [])
    title    = script_data.get("title", topic)

    # Split title into max 3 lines of ~15 chars each for Bebas Neue display
    words = title.upper().split()
    lines, line = [], ""
    for w in words:
        if len(line) + len(w) + 1 <= 16:
            line = (line + " " + w).strip()
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    lines = lines[:3]  # max 3

    # ── Intro scene ──
    intro_scene = {
        "type": "intro",
        "duration_ms": 7000,
        "title_lines": lines,
        "eyebrow": niche.capitalize(),
        "subtitle": script_data.get("description", "")[:140] or f"Everything you need to know about <strong>{topic}</strong>.",
        "count": str(len(sections)) if sections else "",
        "count_label": "Key Points" if sections else "",
    }

    # ── Point scenes (from sections) ──
    point_scenes = []
    for i, sec in enumerate(sections):
        # match to timeline entry if possible
        tl_entry = timeline[i] if i < len(timeline) else {}
        kw = tl_entry.get("icon_keyword", sec.get("heading", "brain"))
        dur_ms = int(tl_entry.get("duration_secs", 22) * 1000)
        dur_ms = max(dur_ms, 12000)  # minimum 12s per point

        point_scenes.append({
            "type": "point",
            "duration_ms": dur_ms,
            "num": str(i + 1).zfill(2),
            "heading": sec.get("heading", f"Point {i+1}").upper(),
            "body": sec.get("body", tl_entry.get("text", "")),
            "tag": sec.get("tag", "Key Insight"),
            "emoji": _get_emoji(kw),
        })

    # Fallback: if no sections, build from timeline
    if not point_scenes:
        for i, entry in enumerate(timeline):
            point_scenes.append({
                "type": "point",
                "duration_ms": max(int(entry.get("duration_secs", 22) * 1000), 12000),
                "num": str(i + 1).zfill(2),
                "heading": entry.get("text", f"Point {i+1}")[:40].upper(),
                "body": entry.get("text", ""),
                "tag": "Key Insight",
                "emoji": _get_emoji(entry.get("icon_keyword", "brain")),
            })

    # ── Outro scene ──
    outro_scene = {
        "type": "outro",
        "duration_ms": 7000,
        "heading": "FOLLOW FOR MORE",
        "sub": f"New videos every week — {niche.capitalize()} & Psychology",
        "cta": "👍  Like · Subscribe · Share",
        "icons": [
            {"emoji": "🔔", "label": "Subscribe"},
            {"emoji": "👍", "label": "Like"},
            {"emoji": "📤", "label": "Share"},
        ],
    }

    return {
        "topic":        topic,
        "niche":        niche.capitalize(),
        "channel":      channel,
        "color_scheme": COLOR_SCHEME_MAP.get(color_scheme, "red_black"),
        "scenes":       [intro_scene] + point_scenes + [outro_scene],
    }


def generate_html(script_data: dict, timeline: list, topic: str,
                  niche: str = "psychology", color_scheme: str = "red_black",
                  channel: str = "AI Channel") -> str:
    """
    Inject CONFIG into video_template.html → write to outputs/ → return path.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = str(OUTPUTS_DIR / f"video_{ts}.html")

    config = _build_config(script_data, timeline, topic, niche, color_scheme, channel)
    config_json = json.dumps(config, ensure_ascii=False, indent=2)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("__CONFIG__", config_json)

    Path(out_path).write_text(html, encoding="utf-8")
    print(f"[HTML] Generated: {out_path} | {len(config['scenes'])} scenes | total={sum(s['duration_ms'] for s in config['scenes'])//1000}s")
    return out_path


# ══════════════════════════════════════════════
#  PHASE 3 — RECORD (Playwright + Xvfb + ffmpeg)
# ══════════════════════════════════════════════

def _start_xvfb(display: str = ":99") -> subprocess.Popen:
    """Start virtual display."""
    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1920x1080x24", "-ac"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)  # wait for Xvfb to init
    print(f"[XVFB] Started on display {display} (PID {proc.pid})")
    return proc


def _start_ffmpeg(display: str, output_path: str, duration: int) -> subprocess.Popen:
    """Start ffmpeg screen capture (video only, audio merged later)."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "x11grab",
        "-r", "24",
        "-s", "1920x1080",
        "-i", f"{display}.0",
        "-t", str(duration + 3),  # +3s buffer
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        output_path,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    print(f"[FFMPEG] Recording started → {output_path}")
    return proc


def _open_browser(html_path: str, display: str):
    """Open Chromium browser on virtual display."""
    abs_path = Path(html_path).resolve()
    env = os.environ.copy()
    env["DISPLAY"] = display

    proc = subprocess.Popen(
        [
            "chromium-browser",  # or "chromium" or "google-chrome"
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--window-size=1920,1080",
            "--window-position=0,0",
            "--start-fullscreen",
            "--kiosk",
            "--noerrdialogs",
            "--disable-infobars",
            f"file://{abs_path}",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"[BROWSER] Opened (PID {proc.pid})")
    return proc


def _merge_audio_video(video_path: str, audio_path: str, output_path: str):
    """Merge ffmpeg-captured video with Kokoro audio."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        print(f"[MERGE] ffmpeg error: {result.stderr.decode()[:300]}")
    else:
        print(f"[MERGE] Final video: {output_path}")


def record_video(html_path: str, audio_path: str, output_path: str, duration: int) -> str:
    """
    Full recording pipeline:
    Xvfb → ffmpeg screen capture → Chromium plays HTML → merge audio
    """
    display   = ":99"
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_video = str(OUTPUTS_DIR / f"raw_video_{ts}.mp4")

    xvfb_proc    = None
    ffmpeg_proc  = None
    browser_proc = None

    try:
        # 1. Virtual display
        xvfb_proc = _start_xvfb(display)

        # 2. ffmpeg recorder
        ffmpeg_proc = _start_ffmpeg(display, raw_video, duration)

        # 3. Browser
        browser_proc = _open_browser(html_path, display)

        # 4. Wait for video duration + 1s buffer
        print(f"[RECORD] Recording {duration}s of video...")
        time.sleep(duration + 1)

    finally:
        # Kill browser
        if browser_proc:
            try:
                browser_proc.terminate()
                browser_proc.wait(timeout=5)
            except Exception:
                pass

        # Stop ffmpeg gracefully
        if ffmpeg_proc:
            try:
                ffmpeg_proc.send_signal(signal.SIGINT)
                ffmpeg_proc.wait(timeout=10)
            except Exception:
                ffmpeg_proc.kill()

        # Kill Xvfb
        if xvfb_proc:
            try:
                xvfb_proc.terminate()
                xvfb_proc.wait(timeout=5)
            except Exception:
                pass

    # 5. Merge video + audio
    if Path(raw_video).exists():
        _merge_audio_video(raw_video, audio_path, output_path)
        try:
            os.remove(raw_video)
        except Exception:
            pass
    else:
        print(f"[RECORD] ❌ Raw video not found: {raw_video}")

    return output_path


# ══════════════════════════════════════════════
#  MAIN ENTRY — called from workflow.py
# ══════════════════════════════════════════════

def render_video(
    audio_path: str,
    timeline: list,
    script_data: dict,
    topic: str,
    thumbnail_style: str  = "plain_icon",
    thumbnail_colors: str = "red_black",
    niche: str            = "default",
    channel: str          = "AI Channel",
) -> str:
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(OUTPUTS_DIR / f"video_{ts}.mp4")

    # 1. Calculate total video duration from timeline
    if timeline:
        last = max(timeline, key=lambda x: x.get("time_secs", 0) + x.get("duration_secs", 0))
        duration = int(last.get("time_secs", 0) + last.get("duration_secs", 30)) + 14  # +7s intro +7s outro
    else:
        duration = 210  # default 3.5min

    print(f"[VIDEO] Generating HTML+Playwright video | duration={duration}s | niche={niche}")

    # 2. Build HTML
    html_path = generate_html(
        script_data=script_data,
        timeline=timeline,
        topic=topic,
        niche=niche,
        color_scheme=thumbnail_colors,
        channel=channel,
    )

    # 3. Record
    record_video(
        html_path=html_path,
        audio_path=audio_path,
        output_path=output_path,
        duration=duration,
    )

    print(f"[VIDEO] Rendered: {output_path}")
    return output_path
