import os
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime

import numpy as np
import soundfile as sf
from moviepy.editor import (
    VideoClip, AudioFileClip, ImageClip,
    CompositeVideoClip, ColorClip
)
from PIL import Image, ImageDraw, ImageFont
from PIL import Image

from utils.asset_manager import fetch_icon

OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)

VIDEO_SIZE = (1920, 1080)
BG_COLOR = (250, 250, 250)
FPS = 24

# ─────────────────────────────────────────────
#  VOICE PROFILES — LLM picks one via strategy
#  Keys match niche names from Director agent
# ─────────────────────────────────────────────
VOICE_PROFILES = {
    "psychology": {
        "voice": "am_echo",          # deep male
        "speed": 0.95,               # slightly slower = serious tone
        "pitch_semitones": -1.5,     # darker tone
        "reverb_room": 0.30,         # subtle space
        "bass_boost": True,
    },
    "mystery": {
        "voice": "am_echo",
        "speed": 0.90,               # slow & eerie
        "pitch_semitones": -2.5,     # very deep/dark
        "reverb_room": 0.55,         # cinematic space
        "bass_boost": True,
    },
    "motivation": {
        "voice": "am_onyx",          # energetic male
        "speed": 1.05,               # fast & punchy
        "pitch_semitones": 0.0,
        "reverb_room": 0.10,
        "bass_boost": False,
    },
    "facts": {
        "voice": "af_heart",         # clear female
        "speed": 1.0,
        "pitch_semitones": 0.5,
        "reverb_room": 0.15,
        "bass_boost": False,
    },
    "history": {
        "voice": "am_echo",
        "speed": 0.97,
        "pitch_semitones": -1.0,
        "reverb_room": 0.35,
        "bass_boost": True,
    },
    "default": {
        "voice": "am_echo",
        "speed": 1.0,
        "pitch_semitones": 0.0,
        "reverb_room": 0.20,
        "bass_boost": False,
    },
}


# ─────────────────────────────────────────────
#  KOKORO TTS
# ─────────────────────────────────────────────
def generate_kokoro_tts(script_text: str, output_path: str, voice: str = "am_echo", speed: float = 1.0):
    """
    Generate raw audio using Kokoro TTS (local, free).
    Saves as WAV for pedalboard processing.
    """
    try:
        from kokoro import KPipeline
        import soundfile as sf

        print(f"[TTS] Kokoro generating | voice={voice} speed={speed}")
        pipeline = KPipeline(lang_code='a')  # 'a' = American English

        all_audio = []
        for _, _, audio in pipeline(script_text, voice=voice, speed=speed):
            all_audio.append(audio)

        if not all_audio:
            raise ValueError("Kokoro returned empty audio")

        final_audio = np.concatenate(all_audio)
        sf.write(output_path, final_audio, 24000)
        print(f"[TTS] Kokoro saved raw audio: {output_path}")

    except Exception as e:
        print(f"[TTS] Kokoro failed: {e} — falling back to Edge-TTS")
        _edge_tts_fallback(script_text, output_path)


def _edge_tts_fallback(script_text: str, output_path: str):
    """Edge-TTS fallback if Kokoro fails."""
    import edge_tts

    async def _run():
        communicate = edge_tts.Communicate(script_text, "en-US-EricNeural", rate="+8%", pitch="-2Hz")
        await communicate.save(output_path)

    asyncio.run(_run())
    print(f"[TTS] Edge-TTS fallback saved: {output_path}")


# ─────────────────────────────────────────────
#  PEDALBOARD VOICE PROCESSOR
# ─────────────────────────────────────────────
def apply_voice_profile(input_path: str, output_path: str, profile: dict):
    """
    Apply voice profile effects using pedalboard + librosa.
    Steps: time-stretch → pitch-shift → EQ/reverb/compression
    """
    try:
        import librosa
        from pedalboard import Pedalboard, Reverb, Compressor, HighpassFilter, LowShelfFilter

        print(f"[VOICE] Applying profile: pitch={profile['pitch_semitones']}, "
              f"reverb={profile['reverb_room']}, bass={profile['bass_boost']}")

        # Load
        audio, sr = librosa.load(input_path, sr=24000, mono=True)

        # 1. Time stretch (speed)
        if profile["speed"] != 1.0:
            audio = librosa.effects.time_stretch(audio, rate=profile["speed"])

        # 2. Pitch shift
        if profile["pitch_semitones"] != 0.0:
            audio = librosa.effects.pitch_shift(audio, sr=sr, n_steps=profile["pitch_semitones"])

        # 3. Pedalboard effects chain
        chain = [
            HighpassFilter(cutoff_frequency_hz=80),        # remove low rumble
            Compressor(threshold_db=-20, ratio=3.0),       # even out dynamics
            Reverb(
                room_size=profile["reverb_room"],
                damping=0.7,
                wet_level=0.15,
                dry_level=0.85,
            ),
        ]
        if profile.get("bass_boost"):
            chain.append(LowShelfFilter(cutoff_frequency_hz=200, gain_db=3.5))

        board = Pedalboard(chain)
        processed = board(audio.reshape(1, -1), sr)

        # Save as WAV
        sf.write(output_path, processed.T, sr)
        print(f"[VOICE] Processed audio saved: {output_path}")

    except Exception as e:
        print(f"[VOICE] Pedalboard processing failed: {e} — using raw audio")
        # Just copy raw file if processing fails
        import shutil
        shutil.copy(input_path, output_path)


# ─────────────────────────────────────────────
#  MAIN AUDIO GENERATOR
# ─────────────────────────────────────────────
def generate_audio(script_text: str, topic: str, niche: str = "default") -> str:
    """
    Full pipeline:
    1. Pick voice profile based on niche
    2. Generate TTS via Kokoro
    3. Apply voice profile via Pedalboard
    Returns path to final processed WAV.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Pick profile — normalize niche to lowercase, fallback to default
    niche_key = niche.lower().strip()
    profile = VOICE_PROFILES.get(niche_key, VOICE_PROFILES["default"])

    raw_path  = str(OUTPUTS_DIR / f"audio_raw_{ts}.wav")
    final_path = str(OUTPUTS_DIR / f"audio_{ts}.wav")

    # Step 1: TTS
    generate_kokoro_tts(
        script_text,
        raw_path,
        voice=profile["voice"],
        speed=profile["speed"],   # speed handled in TTS itself for Kokoro
    )

    # Step 2: Voice processing
    # Pass speed=1.0 to pedalboard since Kokoro already handled speed
    pedalboard_profile = {**profile, "speed": 1.0}
    apply_voice_profile(raw_path, final_path, pedalboard_profile)

    # Cleanup raw file
    try:
        os.remove(raw_path)
    except Exception:
        pass

    print(f"[AUDIO] Final audio ready: {final_path}")
    return final_path


# ─────────────────────────────────────────────
#  VIDEO RENDERER (unchanged logic, accepts niche now)
# ─────────────────────────────────────────────
def render_video(
    audio_path: str,
    timeline: list,
    script_data: dict,
    topic: str,
    thumbnail_style: str = "plain_icon",
    thumbnail_colors: str = "white_bold",
    niche: str = "default",   # ← new param, passed from workflow
) -> str:
    """
    Render full video with:
    - Plain white background
    - Animated icon pop-ups at timeline marks
    - Subtitle text synchronized with sections
    - Subtle zoom/fade effects
    Returns path to final MP4.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(OUTPUTS_DIR / f"video_{ts}.mp4")

    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration

    print(f"[VIDEO] Rendering {duration:.1f}s video | thumb={thumbnail_style}/{thumbnail_colors} | niche={niche}")

    # Background
    bg = ColorClip(size=VIDEO_SIZE, color=BG_COLOR, duration=duration)
    layers = [bg]

    # Pre-fetch icons for all timeline entries
    icon_clips = []
    for entry in timeline:
        kw = entry.get("icon_keyword", "star")
        icon_path = fetch_icon(kw)
        start = entry["time_secs"]
        seg_duration = min(entry.get("duration_secs", 30), duration - start)
        if seg_duration <= 0:
            continue

        try:
            icon_img = Image.open(icon_path).convert("RGBA").resize((300, 300))
            icon_arr = np.array(icon_img)

            def make_icon_frame(t, arr=icon_arr, seg_dur=seg_duration):
                scale = min(1.0, t / 0.3) if t < 0.3 else 1.0
                if t > seg_dur - 0.3:
                    scale = max(0.0, (seg_dur - t) / 0.3)
                h, w = arr.shape[:2]
                new_w, new_h = int(w * scale), int(h * scale)
                if new_w < 1 or new_h < 1:
                    return np.zeros((h, w, 4), dtype=np.uint8)
                img = Image.fromarray(arr).resize((new_w, new_h), Image.LANCZOS)
                canvas = np.zeros((h, w, 4), dtype=np.uint8)
                ox, oy = (w - new_w) // 2, (h - new_h) // 2
                canvas[oy:oy+new_h, ox:ox+new_w] = np.array(img)
                return canvas

            ic = VideoClip(make_icon_frame, duration=seg_duration, ismask=False)
            ic = ic.set_start(start).set_position(("center", 200))
            icon_clips.append(ic)
        except Exception as e:
            print(f"[VIDEO] Icon render failed for {kw}: {e}")

    # ── Pillow text helper ────────────────────────────────────────────────────
    def _get_font(size: int):
        """Try to load a real font, fallback to PIL default."""
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
        for path in candidates:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    def _make_text_frame(text: str, font_size: int, text_color: tuple,
                         bg_color: tuple, canvas_size: tuple,
                         y_position: int, alpha: float = 1.0):
        """Render text onto a transparent RGBA canvas using Pillow."""
        W, H = canvas_size
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = _get_font(font_size)

        # Word-wrap manually
        max_w = W - 200
        words = text.split()
        lines, line = [], ""
        for word in words:
            test = (line + " " + word).strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_w:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)

        # Draw each line centered
        line_h = font_size + 8
        total_h = len(lines) * line_h
        y = y_position - total_h // 2

        for ln in lines:
            bbox = draw.textbbox((0, 0), ln, font=font)
            x = (W - (bbox[2] - bbox[0])) // 2
            # Shadow
            draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, int(120 * alpha)))
            # Text
            r, g, b = text_color
            draw.text((x, y), ln, font=font, fill=(r, g, b, int(255 * alpha)))
            y += line_h

        return np.array(img)

    def _make_subtitle_clip(text: str, start: float, clip_dur: float, y_pos: int, font_size: int = 52):
        """Create an ImageClip for subtitle text using Pillow (no ImageMagick)."""
        def make_frame(t):
            # Fade in/out alpha
            alpha = min(1.0, t / 0.25) if t < 0.25 else (
                max(0.0, (clip_dur - t) / 0.25) if t > clip_dur - 0.25 else 1.0
            )
            return _make_text_frame(
                text=text,
                font_size=font_size,
                text_color=(20, 20, 20),
                bg_color=(0, 0, 0, 0),
                canvas_size=VIDEO_SIZE,
                y_position=y_pos,
                alpha=alpha,
            )
        clip = VideoClip(make_frame, duration=clip_dur, ismask=False)
        return clip.set_start(start)

    # Subtitle clips — Pillow based, no ImageMagick
    subtitle_clips = []
    for entry in timeline:
        text = entry.get("text", "")
        if not text:
            continue
        start = entry["time_secs"]
        seg_duration = min(entry.get("duration_secs", 30), duration - start)
        if seg_duration <= 0:
            continue

        words = text.split()
        chunk_size = 10
        chunks = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]
        chunk_dur = seg_duration / max(len(chunks), 1)

        for ci, chunk in enumerate(chunks):
            try:
                sc = _make_subtitle_clip(
                    text=chunk,
                    start=start + ci * chunk_dur,
                    clip_dur=chunk_dur,
                    y_pos=VIDEO_SIZE[1] - 180,
                    font_size=52,
                )
                subtitle_clips.append(sc)
            except Exception as e:
                print(f"[VIDEO] Subtitle clip failed: {e}")

    # Title overlay (first 3s) — Pillow based
    title = script_data.get("title", topic)
    try:
        title_clip = _make_subtitle_clip(
            text=title[:60],
            start=0,
            clip_dur=3.0,
            y_pos=VIDEO_SIZE[1] // 2,
            font_size=68,
        )
        layers.append(title_clip)
    except Exception as e:
        print(f"[VIDEO] Title clip failed: {e}")

    layers.extend(icon_clips)
    layers.extend(subtitle_clips)

    final = CompositeVideoClip(layers, size=VIDEO_SIZE).set_audio(audio_clip)
    final.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        threads=2,
        logger=None,
    )

    print(f"[VIDEO] Rendered: {output_path}")
    audio_clip.close()
    final.close()
    return output_path
