import os
import json
import time
import shutil
import subprocess
import traceback
from pathlib import Path
from datetime import datetime

import numpy as np
import soundfile as sf

OUTPUTS_DIR   = Path("outputs")
TEMPLATE_PATH = Path("templates/video_template.html")
OUTPUTS_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────
#  COLOR SCHEME MAP
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
    "psychology": {"voice": "am_echo",  "speed": 0.95, "pitch_semitones": -1.5, "reverb_room": 0.30, "bass_boost": True},
    "mystery":    {"voice": "am_echo",  "speed": 0.90, "pitch_semitones": -2.5, "reverb_room": 0.55, "bass_boost": True},
    "motivation": {"voice": "am_onyx",  "speed": 1.05, "pitch_semitones":  0.0, "reverb_room": 0.10, "bass_boost": False},
    "facts":      {"voice": "af_heart", "speed": 1.0,  "pitch_semitones":  0.5, "reverb_room": 0.15, "bass_boost": False},
    "history":    {"voice": "am_echo",  "speed": 0.97, "pitch_semitones": -1.0, "reverb_room": 0.35, "bass_boost": True},
    "default":    {"voice": "am_echo",  "speed": 1.0,  "pitch_semitones":  0.0, "reverb_room": 0.20, "bass_boost": False},
}

EMOJI_MAP = {
    "brain": "🧠", "heart": "❤️", "mask": "🎭", "eye": "👁️", "fire": "🔥",
    "lock": "🔒", "key": "🗝️", "star": "⭐", "warning": "⚠️", "money": "💰",
    "people": "👥", "thought": "💭", "power": "⚡", "dark": "🌑", "light": "💡",
    "success": "🏆", "habit": "📋", "mind": "🧩", "emotion": "😤",
    "manipulation": "🕵️", "trust": "🤝", "fear": "😨", "control": "🎮",
    "anger": "😡", "love": "💕", "stress": "😰", "time": "⏰",
}


# ══════════════════════════════════════════════
#  PHASE 1 — AUDIO (Kokoro + Pedalboard)
# ══════════════════════════════════════════════

def generate_kokoro_tts(script_text: str, output_path: str,
                        voice: str = "am_echo", speed: float = 1.0):
    try:
        from kokoro import KPipeline
        print(f"[TTS] Kokoro | voice={voice} speed={speed}")
        pipeline = KPipeline(lang_code='a')
        chunks = [audio for _, _, audio in pipeline(script_text, voice=voice, speed=speed)]
        if not chunks:
            raise ValueError("Kokoro returned empty audio")
        sf.write(output_path, np.concatenate(chunks), 24000)
        print(f"[TTS] Kokoro saved: {output_path}")
    except Exception as e:
        print(f"[TTS] Kokoro failed: {e} — using gTTS fallback")
        traceback.print_exc()
        _gtts_fallback(script_text, output_path)


def _gtts_fallback(script_text: str, output_path: str):
    try:
        from gtts import gTTS
        import librosa
        print("[TTS] gTTS fallback...")
        mp3 = output_path.replace(".wav", "_tmp.mp3")
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
        print(f"[VOICE] pitch={profile['pitch_semitones']} reverb={profile['reverb_room']} bass={profile['bass_boost']}")
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
            chain.append(LowShelfFilter(cutoff_frequency_hz=200, gain_db=3.5))
        processed = Pedalboard(chain)(audio.reshape(1, -1), sr)
        sf.write(output_path, processed.T, sr)
        print(f"[VOICE] Processed: {output_path}")
    except Exception as e:
        print(f"[VOICE] Pedalboard failed: {e} — using raw")
        traceback.print_exc()
        shutil.copy(input_path, output_path)


def generate_audio(script_text: str, topic: str, niche: str = "default") -> str:
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    profile = VOICE_PROFILES.get(niche.lower().strip(), VOICE_PROFILES["default"])
    raw     = str(OUTPUTS_DIR / f"audio_raw_{ts}.wav")
    final   = str(OUTPUTS_DIR / f"audio_{ts}.wav")

    generate_kokoro_tts(script_text, raw, voice=profile["voice"], speed=profile["speed"])
    apply_voice_profile(raw, final, {**profile, "speed": 1.0})

    try:
        os.remove(raw)
    except Exception:
        pass

    print(f"[AUDIO] Ready: {final}")
    return final


# ══════════════════════════════════════════════
#  PHASE 2 — HTML GENERATION
# ══════════════════════════════════════════════

def _get_emoji(keyword: str) -> str:
    kw = keyword.lower()
    for k, v in EMOJI_MAP.items():
        if k in kw:
            return v
    return "🧠"


def _build_config(script_data: dict, timeline: list, topic: str,
                  niche: str, color_scheme: str, channel: str) -> dict:
    sections = script_data.get("sections", [])
    title    = script_data.get("title", topic)

    # Break title into ≤3 display lines
    words = title.upper().split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if len(test) <= 16:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    lines = lines[:3]

    # Intro
    intro = {
        "type":        "intro",
        "duration_ms": 7000,
        "title_lines": lines,
        "eyebrow":     niche.capitalize(),
        "subtitle":    (script_data.get("description", "") or
                        f"Everything you need to know about <strong>{topic}</strong>.")[:140],
        "count":       str(len(sections)) if sections else "",
        "count_label": "Key Points" if sections else "",
    }

    # Points
    points = []
    src = sections if sections else []
    for i, sec in enumerate(src):
        tl    = timeline[i] if i < len(timeline) else {}
        kw    = tl.get("icon_keyword", sec.get("heading", "brain"))
        dur   = max(int(tl.get("duration_secs", 22) * 1000), 12000)
        points.append({
            "type":        "point",
            "duration_ms": dur,
            "num":         str(i + 1).zfill(2),
            "heading":     sec.get("heading", f"Point {i+1}").upper(),
            "body":        sec.get("body", tl.get("text", "")),
            "tag":         sec.get("tag", "Key Insight"),
            "emoji":       _get_emoji(kw),
        })

    # Fallback — build from timeline if no sections
    if not points:
        for i, entry in enumerate(timeline):
            points.append({
                "type":        "point",
                "duration_ms": max(int(entry.get("duration_secs", 22) * 1000), 12000),
                "num":         str(i + 1).zfill(2),
                "heading":     entry.get("text", f"Point {i+1}")[:40].upper(),
                "body":        entry.get("text", ""),
                "tag":         "Key Insight",
                "emoji":       _get_emoji(entry.get("icon_keyword", "brain")),
            })

    # Outro
    outro = {
        "type":        "outro",
        "duration_ms": 7000,
        "heading":     "FOLLOW FOR MORE",
        "sub":         f"New videos every week — {niche.capitalize()}",
        "cta":         "👍  Like · Subscribe · Share",
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
        "scenes":       [intro] + points + [outro],
    }


def generate_html(script_data: dict, timeline: list, topic: str,
                  niche: str = "psychology", color_scheme: str = "red_black",
                  channel: str = "AI Channel") -> str:
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = str(OUTPUTS_DIR / f"video_{ts}.html")

    config      = _build_config(script_data, timeline, topic, niche, color_scheme, channel)
    config_json = json.dumps(config, ensure_ascii=False, indent=2)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    Path(out).write_text(template.replace("__CONFIG__", config_json), encoding="utf-8")

    total_s = sum(s["duration_ms"] for s in config["scenes"]) // 1000
    print(f"[HTML] {out} | {len(config['scenes'])} scenes | {total_s}s total")
    return out


# ══════════════════════════════════════════════
#  PHASE 3 — RECORD  (Playwright screenshot → ffmpeg)
# ══════════════════════════════════════════════

FPS = 24   # frames per second


def _frames_to_video(frames_dir: Path, raw_video: str):
    """Convert PNG frames → raw MP4 via ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        raw_video,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frames→video failed: {result.stderr.decode()[:400]}")
    print(f"[FFMPEG] Frames → {raw_video}")


def _merge_audio_video(video_path: str, audio_path: str, output_path: str):
    """Merge video + audio → final MP4."""
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
        raise RuntimeError(f"ffmpeg merge failed: {result.stderr.decode()[:400]}")
    print(f"[MERGE] Final: {output_path}")


def record_video(html_path: str, audio_path: str,
                 output_path: str, duration: int) -> str:
    """
    Playwright headless Chromium → screenshot every frame →
    ffmpeg encode → merge Kokoro audio → final MP4.
    No Xvfb needed. Works on HF free CPU tier.
    """
    from playwright.sync_api import sync_playwright

    ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
    frames_dir = OUTPUTS_DIR / f"frames_{ts}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    raw_video  = str(OUTPUTS_DIR / f"raw_{ts}.mp4")

    abs_path     = str(Path(html_path).resolve())
    total_frames = duration * FPS
    frame_ms     = 1000 // FPS   # ~41ms per frame

    print(f"[RECORD] {duration}s × {FPS}fps = {total_frames} frames")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--allow-file-access-from-files",
            ])
            page = browser.new_page(viewport={"width": 1920, "height": 1080})

            # Load HTML and wait for fonts/animations to init
            page.goto(f"file://{abs_path}", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(800)

            # ── Frame capture loop ──
            for i in range(total_frames):
                frame_path = str(frames_dir / f"frame_{i:05d}.png")
                page.screenshot(path=frame_path, full_page=False)

                # Advance animation time by 1 frame
                page.evaluate(f"""
                    (() => {{
                        // Nudge CSS animations forward
                        if (!window.__frameTime) window.__frameTime = 0;
                        window.__frameTime += {frame_ms};
                    }})()
                """)

                if i % (FPS * 5) == 0:
                    elapsed_s = i // FPS
                    print(f"[RECORD] {elapsed_s}s / {duration}s ({i}/{total_frames} frames)")

            browser.close()
            print(f"[RECORD] All {total_frames} frames captured")

    except Exception as e:
        shutil.rmtree(frames_dir, ignore_errors=True)
        raise RuntimeError(f"Playwright capture failed: {e}") from e

    # ── Encode frames → video ──
    try:
        _frames_to_video(frames_dir, raw_video)
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)

    # ── Merge audio ──
    _merge_audio_video(raw_video, audio_path, output_path)
    try:
        os.remove(raw_video)
    except Exception:
        pass

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

    # Total duration from timeline + 14s (7s intro + 7s outro)
    if timeline:
        last     = max(timeline, key=lambda x: x.get("time_secs", 0) + x.get("duration_secs", 0))
        duration = int(last.get("time_secs", 0) + last.get("duration_secs", 30)) + 14
    else:
        duration = 210

    print(f"[VIDEO] HTML+Playwright pipeline | {duration}s | niche={niche}")

    # 1. Build animated HTML
    html_path = generate_html(
        script_data=script_data,
        timeline=timeline,
        topic=topic,
        niche=niche,
        color_scheme=thumbnail_colors,
        channel=channel,
    )

    # 2. Record
    record_video(
        html_path=html_path,
        audio_path=audio_path,
        output_path=output_path,
        duration=duration,
    )

    print(f"[VIDEO] Done: {output_path}")
    return output_path
