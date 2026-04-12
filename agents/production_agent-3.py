"""
agents/production_agent.py

PIPELINE:
  1. Kokoro TTS  → full audio WAV
     Voice: am_adam:0.8,am_echo:0.2 | speed: 0.95 (LOCKED)
  2. Groq Whisper → word-level timestamps
  3. Paragraph ↔ timestamp matching → scene timeline
  4. Pollinations.ai → cinematic AI image per scene (FREE, no key)
  5. SRT captions (4 words/caption, UPPERCASE, Arial Black)
  6. ffmpeg:
       - Each image stretched to exact scene duration
       - Ken Burns slow zoom
       - Cinematic color grade
       - Captions burn-in (bottom center)
       - BGM mix at 15% volume
       - Final MP4

ENV VARS REQUIRED:
  GROQ_API_KEY  → for Whisper word timestamps

NO KEY NEEDED:
  Pollinations.ai → completely free image generation
  Kokoro TTS      → local model, no API
  ffmpeg          → local binary
"""

import os
import re
import json
import shutil
import subprocess
import traceback
import requests
from pathlib import Path
from datetime import datetime

import numpy as np
import soundfile as sf

# ─────────────────────────────────────────────────────────
OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)

VIDEO_W = 1920
VIDEO_H = 1080
FPS     = 24

# ══════════════════════════════════════════════
#  VOICE CONFIG — LOCKED
#  am_adam:0.8,am_echo:0.2 | speed 0.95
#  Deep dark authoritative + slight energy
#  Do NOT change without re-testing
# ══════════════════════════════════════════════

ACTIVE_VOICE = "am_adam:0.8,am_echo:0.2"
ACTIVE_SPEED = 0.95

BGM_URLS = {
    "dark_suspense":      "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Interloper.mp3",
    "lo_fi_chill":        "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Relaxing%20Piano%20Music.mp3",
    "epic_dramatic":      "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Cylinder%20Five.mp3",
    "mysterious_ambient": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Phantom%20from%20Space.mp3",
}


# ══════════════════════════════════════════════
#  STEP 1 — KOKORO TTS
# ══════════════════════════════════════════════

def _gtts_fallback(text: str, path: str):
    """Emergency fallback if Kokoro fails."""
    try:
        from gtts import gTTS
        import librosa
        mp3 = path.replace(".wav", "_tmp.mp3")
        gTTS(text=text, lang="en", slow=False).save(mp3)
        audio, sr = librosa.load(mp3, sr=24000)
        sf.write(path, audio, sr)
        os.remove(mp3)
        print(f"[TTS] gTTS fallback saved: {path}")
    except Exception as e:
        print(f"[TTS] gTTS also failed: {e}")
        traceback.print_exc()


def generate_kokoro_tts(text: str, path: str,
                        voice: str = ACTIVE_VOICE,
                        speed: float = ACTIVE_SPEED):
    try:
        from kokoro import KPipeline

        if ":" in voice and "," in voice:
            print(f"[TTS] Blend: {voice} | speed={speed}")
            pipeline = KPipeline(lang_code="a")
            blended  = None
            for part in voice.split(","):
                v, w = part.strip().split(":")
                vt   = pipeline.load_voice(v.strip())
                blended = vt * float(w) if blended is None else blended + vt * float(w)
            if blended is None:
                raise ValueError("All voice blends failed")
            chunks = [a for _, _, a in pipeline(text, voice=blended, speed=speed)]
        else:
            print(f"[TTS] Single voice: {voice} | speed={speed}")
            pipeline = KPipeline(lang_code="a")
            chunks   = [a for _, _, a in pipeline(text, voice=voice, speed=speed)]

        if not chunks:
            raise ValueError("Kokoro returned empty audio")

        sf.write(path, np.concatenate(chunks), 24000)
        print(f"[TTS] ✅ Saved: {path}")

    except Exception as e:
        print(f"[TTS] Kokoro failed: {e} — gTTS fallback")
        traceback.print_exc()
        _gtts_fallback(text, path)


def generate_audio(full_text: str) -> str:
    """Generate full narration audio using locked voice profile."""
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(OUTPUTS_DIR / f"audio_{ts}.wav")
    print(f"[AUDIO] Voice={ACTIVE_VOICE} Speed={ACTIVE_SPEED}")
    generate_kokoro_tts(full_text, path, voice=ACTIVE_VOICE, speed=ACTIVE_SPEED)
    return path


# ══════════════════════════════════════════════
#  STEP 2 — GROQ WHISPER
#  Requires: GROQ_API_KEY in environment
# ══════════════════════════════════════════════

def get_word_timestamps(audio_path: str) -> list:
    """
    Transcribe audio → word-level timestamps via Groq Whisper.
    Returns: [{"word": "they", "start": 0.0, "end": 0.3}, ...]
    Free tier: 7200 seconds/day — plenty for 2 videos/week.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY not found in environment. "
            "Add it to your HuggingFace Space secrets."
        )

    from groq import Groq
    client = Groq(api_key=api_key)

    print("[WHISPER] Transcribing with Groq whisper-large-v3...")
    with open(audio_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            file=f,
            model="whisper-large-v3",
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    raw_words = resp.words or []

    # Groq returns either objects or dicts depending on version — handle both
    def _extract(w):
        if isinstance(w, dict):
            return {"word": w["word"], "start": w["start"], "end": w["end"]}
        return {"word": w.word, "start": w.start, "end": w.end}

    words = [_extract(w) for w in raw_words]
    print(f"[WHISPER] ✅ {len(words)} word timestamps")
    return words


# ══════════════════════════════════════════════
#  STEP 3 — PARAGRAPH → SCENE TIMELINE
# ══════════════════════════════════════════════

def _clean_word(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def match_paragraphs_to_time(sections: list, words: list) -> list:
    """
    Match each section's body text to Whisper word timestamps.
    Returns scene_timeline with start/end seconds per section.
    Uses 'image_prompt' from script_agent sections directly.
    """
    if not words:
        raise ValueError("Whisper returned no words — check audio file")

    total_dur  = words[-1]["end"]
    word_list  = [(_clean_word(w["word"]), w["start"], w["end"]) for w in words]
    timeline   = []
    cursor     = 0

    for i, sec in enumerate(sections):
        body        = sec.get("body", sec.get("text", ""))
        para_words  = body.split()
        first_clean = _clean_word(para_words[0])  if para_words else ""
        last_clean  = _clean_word(para_words[-1]) if para_words else ""

        # Find start timestamp
        start_time = None
        for j in range(cursor, len(word_list)):
            if word_list[j][0].startswith(first_clean[:4]):
                start_time = word_list[j][1]
                cursor     = j
                break

        # Find end timestamp
        end_time = None
        search_limit = min(cursor + len(para_words) + 10, len(word_list))
        for j in range(cursor, search_limit):
            if word_list[j][0].startswith(last_clean[:4]):
                end_time = word_list[j][2]
                cursor   = j + 1
                break

        # Fallbacks
        if start_time is None:
            start_time = timeline[-1]["end"] if timeline else 0.0
        if end_time is None:
            end_time = start_time + sec.get("duration_secs", 20)

        timeline.append({
            "section":      sec.get("section", f"point_{i+1}"),
            "heading":      sec.get("heading", ""),
            "body":         body,
            "image_prompt": sec.get("image_prompt", "Cinematic dark atmospheric scene, dramatic lighting, 4K"),
            "start":        round(start_time, 3),
            "end":          round(end_time + 0.3, 3),
        })
        print(f"[SYNC] Scene {i+1} '{sec.get('section','')}': "
              f"{start_time:.1f}s → {end_time:.1f}s")

    # Last scene always reaches audio end
    if timeline:
        timeline[-1]["end"] = round(total_dur, 3)

    return timeline


# ══════════════════════════════════════════════
#  STEP 4 — POLLINATIONS.AI IMAGES
#  Free — no API key needed
# ══════════════════════════════════════════════

def download_scene_image(prompt: str, idx: int) -> str:
    """Delegates to image_manager — Google Imagen primary, Pollinations fallback."""
    from agents.image_manager import download_scene_image as _dl
    return _dl(prompt, idx)


# ══════════════════════════════════════════════
#  STEP 5 — SRT CAPTIONS
# ══════════════════════════════════════════════

def _srt_ts(secs: float) -> str:
    h  = int(secs // 3600)
    m  = int((secs % 3600) // 60)
    s  = int(secs % 60)
    ms = int((secs % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def create_srt(words: list, output_path: str,
               words_per_caption: int = 4) -> str:
    """
    Group words → SRT captions.
    UPPERCASE for that viral Shorts style.
    4 words per caption — readable on mobile.
    """
    chunks = [
        words[i:i + words_per_caption]
        for i in range(0, len(words), words_per_caption)
    ]
    lines = []
    for idx, chunk in enumerate(chunks, 1):
        start = chunk[0]["start"]
        end   = chunk[-1]["end"]
        text  = " ".join(w["word"] for w in chunk).upper()
        lines.append(f"{idx}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{text}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[SRT] ✅ {len(chunks)} captions → {output_path}")
    return output_path


# ══════════════════════════════════════════════
#  STEP 6 — BGM DOWNLOAD
# ══════════════════════════════════════════════

def download_bgm(bgm_mood: str) -> str | None:
    url  = BGM_URLS.get(bgm_mood, BGM_URLS["dark_suspense"])
    path = str(OUTPUTS_DIR / f"bgm_{bgm_mood}.mp3")

    if Path(path).exists():
        print(f"[BGM] Cached: {path}")
        return path

    try:
        print(f"[BGM] Downloading: {bgm_mood}")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        print(f"[BGM] ✅ {path}")
        return path
    except Exception as e:
        print(f"[BGM] ⚠️ Failed: {e} — no BGM")
        return None


# ══════════════════════════════════════════════
#  STEP 7 — FFMPEG FINAL ASSEMBLY
# ══════════════════════════════════════════════

def build_final_video(
    scene_timeline: list,
    audio_path:     str,
    srt_path:       str,
    output_path:    str,
    bgm_path:       str | None = None,
):
    """
    ffmpeg pipeline:
    - Download AI images (Pollinations)
    - Ken Burns zoom per scene
    - Concat all scenes
    - Cinematic color grade
    - Captions burn-in
    - Voice + optional BGM mix
    - Final MP4
    """

    # ── Download images ───────────────────────
    image_paths = []
    for i, scene in enumerate(scene_timeline):
        img = download_scene_image(scene["image_prompt"], i)
        image_paths.append(img)

    # ── Build ffmpeg inputs + filters ─────────
    inputs       = []
    filter_parts = []

    for i, (scene, img) in enumerate(zip(scene_timeline, image_paths)):
        dur = max(round(scene["end"] - scene["start"], 3), 1.0)
        d   = int(dur * FPS)

        inputs += ["-loop", "1", "-t", str(dur), "-i", img]

        filter_parts.append(
            f"[{i}:v]"
            f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_W}:{VIDEO_H},"
            f"zoompan="
            f"z='min(zoom+0.0005,1.2)':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={d}:s={VIDEO_W}x{VIDEO_H}:fps={FPS},"
            f"setpts=PTS-STARTPTS"
            f"[v{i}]"
        )

    # Concat scenes
    n         = len(scene_timeline)
    concat_in = "".join(f"[v{i}]" for i in range(n))
    filter_parts.append(f"{concat_in}concat=n={n}:v=1:a=0[concat_v]")

    # Cinematic grade + subtitle INSIDE filter_complex (critical!)
    # Can't use -vf when output comes from -filter_complex
    abs_srt = str(Path(srt_path).resolve())
    # Linux path — no escaping needed on HF Space
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
        f"Alignment=2,"
        f"MarginV=60"
    )
    filter_parts.append(
        "[concat_v]"
        "eq=contrast=1.08:saturation=1.2:brightness=0.01,"
        "unsharp=5:5:0.8,"
        "vignette=PI/5,"
        f"subtitles='{abs_srt}':force_style='{subtitle_style}'"
        "[final_v]"
    )

    filter_complex = "; ".join(filter_parts)

    # ── Audio: voice + optional BGM mix ───────
    voice_idx    = n
    audio_inputs = ["-i", audio_path]

    if bgm_path:
        bgm_idx = n + 1
        audio_inputs += ["-i", bgm_path]
        filter_complex += (
            f"; [{bgm_idx}:a]volume=0.15,"
            f"aloop=loop=-1:size=2e+09[bgm_looped]"
            f"; [{voice_idx}:a][bgm_looped]"
            f"amix=inputs=2:duration=first:weights=1 0.15[mixed_a]"
        )
        audio_map = "[mixed_a]"
    else:
        audio_map = f"{voice_idx}:a"

    # ── Final command ─────────────────────────
    # NO -vf here — subtitles already inside filter_complex → [final_v]
    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + audio_inputs
        + ["-filter_complex", filter_complex]
        + ["-map", "[final_v]"]
        + ["-map", audio_map]
        + ["-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p"]
        + ["-c:a", "aac", "-b:a", "192k"]
        + ["-shortest", output_path]
    )

    print(f"[FFMPEG] Rendering {n} scenes → {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[FFMPEG ERROR]\n{result.stderr[-1500:]}")
        raise RuntimeError("ffmpeg failed — see logs above")

    # ── Cleanup temp images ───────────────────
    for i in range(n):
        img = OUTPUTS_DIR / f"scene_{i:02d}.jpg"
        if img.exists():
            img.unlink()

    print(f"[FFMPEG] ✅ Done: {output_path}")


# ══════════════════════════════════════════════
#  MAIN ENTRY — render_video()
# ══════════════════════════════════════════════

def render_video(
    script_data: dict,
    topic:       str,
    niche:       str  = "default",
    channel:     str  = "AI Channel",
    use_bgm:     bool = True,
) -> str:
    """
    Main entry. Call from workflow/graph node.

    Expects script_data from script_agent:
    {
      "title":    "...",
      "bgm_mood": "dark_suspense",
      "sections": [
        {
          "section":       "hook",
          "heading":       "YOUR BRAIN IS LYING",
          "body":          "Right now your brain is lying...",
          "image_prompt":  "Dark corridor, fog, cinematic...",
          "duration_secs": 12,
          "emoji":         "🧠"
        }, ...
      ]
    }

    Returns: absolute path to final MP4
    """
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(OUTPUTS_DIR / f"video_{ts}.mp4")
    srt_path    = str(OUTPUTS_DIR / f"captions_{ts}.srt")

    sections = script_data.get("sections", [])
    if not sections:
        raise ValueError("[RENDER] script_data has no sections")

    print(f"\n{'='*50}")
    print(f"[PIPELINE] Topic: {topic}")
    print(f"[PIPELINE] Sections: {len(sections)}")
    print(f"[PIPELINE] Voice: {ACTIVE_VOICE} | Speed: {ACTIVE_SPEED}")
    print(f"{'='*50}\n")

    # ── 1. Build full narration text ──────────
    from agents.script_agent import get_full_script_text
    full_text = get_full_script_text(script_data)
    print(f"[PIPELINE] Script: {len(full_text.split())} words")

    # ── 2. TTS ────────────────────────────────
    print("\n[PIPELINE] Step 1/5 — Kokoro TTS")
    audio_path = generate_audio(full_text)

    # ── 3. Whisper timestamps ─────────────────
    print("\n[PIPELINE] Step 2/5 — Groq Whisper")
    words = get_word_timestamps(audio_path)

    # ── 4. Scene sync ─────────────────────────
    print("\n[PIPELINE] Step 3/5 — Scene Timeline")
    scene_timeline = match_paragraphs_to_time(sections, words)

    # ── 5. Captions ───────────────────────────
    print("\n[PIPELINE] Step 4/5 — SRT Captions")
    create_srt(words, srt_path, words_per_caption=4)

    # ── 6. BGM ────────────────────────────────
    bgm_path = None
    if use_bgm:
        bgm_mood = script_data.get("bgm_mood", "dark_suspense")
        bgm_path = download_bgm(bgm_mood)

    # ── 7. Render ─────────────────────────────
    print("\n[PIPELINE] Step 5/5 — ffmpeg Render")
    build_final_video(
        scene_timeline=scene_timeline,
        audio_path=audio_path,
        srt_path=srt_path,
        output_path=output_path,
        bgm_path=bgm_path,
    )

    print(f"\n{'='*50}")
    print(f"[DONE] ✅ {output_path}")
    print(f"{'='*50}\n")

    return output_path
