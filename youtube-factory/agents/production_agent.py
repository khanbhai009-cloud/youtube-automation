import os
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime

import edge_tts
from moviepy.editor import (
    VideoClip, AudioFileClip, ImageClip, TextClip,
    CompositeVideoClip, ColorClip
)
from moviepy.video.fx.all import resize, fadein, fadeout
from PIL import Image
import numpy as np

from utils.asset_manager import fetch_icon

OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)

# USA accent voices
VOICES = ["en-US-GuyNeural", "en-US-ChristopherNeural", "en-US-EricNeural"]
BG_COLOR = (250, 250, 250)  # Near-white "Plain & Paint" background
VIDEO_SIZE = (1920, 1080)
FPS = 24


async def _generate_tts(text: str, output_path: str, voice: str = "en-US-GuyNeural"):
    communicate = edge_tts.Communicate(text, voice, rate="+8%", pitch="-2Hz")
    await communicate.save(output_path)


def generate_audio(script_text: str, topic: str) -> str:
    """Generate voiceover MP3, returns file path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = str(OUTPUTS_DIR / f"audio_{ts}.mp3")
    voice = VOICES[hash(topic) % len(VOICES)]
    
    print(f"[AUDIO] Generating TTS with voice: {voice}")
    asyncio.run(_generate_tts(script_text, audio_path, voice))
    print(f"[AUDIO] Audio saved: {audio_path}")
    return audio_path


def render_video(audio_path: str, timeline: list, script_data: dict, topic: str, thumbnail_style: str = "plain_icon", thumbnail_colors: str = "white_bold") -> str:
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
    
    print(f"[VIDEO] Rendering {duration:.1f}s video | thumb={thumbnail_style}/{thumbnail_colors}")
    
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
        
        # Icon clip - centered, animated pop-up
        try:
            icon_img = Image.open(icon_path).convert("RGBA").resize((300, 300))
            icon_arr = np.array(icon_img)
            
            def make_icon_frame(t, arr=icon_arr, seg_dur=seg_duration):
                # Scale animation: 0.3s pop-in
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
    
    # Subtitle clips
    subtitle_clips = []
    for entry in timeline:
        text = entry.get("text", "")
        if not text:
            continue
        start = entry["time_secs"]
        seg_duration = min(entry.get("duration_secs", 30), duration - start)
        if seg_duration <= 0:
            continue
        
        # Split into 2-line chunks for readability
        words = text.split()
        chunk_size = 10
        chunks = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]
        chunk_dur = seg_duration / max(len(chunks), 1)
        
        for ci, chunk in enumerate(chunks):
            try:
                tc = (TextClip(
                    chunk,
                    fontsize=48,
                    color="black",
                    font="DejaVu-Sans-Bold",
                    method="caption",
                    size=(VIDEO_SIZE[0] - 200, None),
                    align="center",
                )
                .set_start(start + ci * chunk_dur)
                .set_duration(chunk_dur)
                .set_position(("center", VIDEO_SIZE[1] - 220))
                .fadein(0.3)
                .fadeout(0.3))
                subtitle_clips.append(tc)
            except Exception as e:
                print(f"[VIDEO] Subtitle clip failed: {e}")
    
    # Title overlay at start (3 seconds)
    title = script_data.get("title", topic)
    try:
        title_clip = (TextClip(
            title[:50],
            fontsize=64,
            color="black",
            font="DejaVu-Sans-Bold",
            method="caption",
            size=(VIDEO_SIZE[0] - 100, None),
            align="center",
        )
        .set_duration(3)
        .set_position("center")
        .fadein(0.5)
        .fadeout(0.5))
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
