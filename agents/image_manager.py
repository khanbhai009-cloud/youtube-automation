"""
agents/image_manager.py

PRIMARY:  Google AI Studio — Imagen 3 (free tier: 10 req/min)
FALLBACK: Pollinations.ai  — completely free, no key

STRATEGY:
- Sequential requests — ek ke baad ek, response aane tak wait
- 429 ya timeout → same provider retry (3x, backoff)
- Sirf tab fallback jab primary 3 baar laga ke fail ho
- Kabhi bhi black frame nahi
"""

import os
import time
import requests
import subprocess
from pathlib import Path

OUTPUTS_DIR = Path("outputs")
VIDEO_W     = 1920
VIDEO_H     = 1080

# ── Google Imagen config ──────────────────────────────────────────────────
GOOGLE_API_KEY  = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/imagen-4.0-generate-001:predict"
)
GOOGLE_MAX_RETRIES    = 3
GOOGLE_RETRY_WAIT     = 12   # 12 sec between retries (stays under 10/min)
GOOGLE_TIMEOUT        = 60   # wait up to 60s for response

# ── Pollinations config ───────────────────────────────────────────────────
POLL_MAX_RETRIES = 3
POLL_RETRY_WAIT  = 8
POLL_TIMEOUT     = 90


# ══════════════════════════════════════════════
#  GOOGLE IMAGEN — PRIMARY
# ══════════════════════════════════════════════

def _google_imagen(prompt: str, idx: int) -> bytes | None:
    """
    Call Google Imagen 3 API.
    Waits for full response before returning.
    Returns raw image bytes or None if all retries fail.
    """
    if not GOOGLE_API_KEY:
        print("[IMG] GOOGLE_API_KEY not set — skipping Google")
        return None

    full_prompt = (
        f"{prompt}, cinematic, photorealistic, dramatic lighting, "
        f"4K, wide establishing shot, no text, no watermarks"
    )

    payload = {
        "instances": [{"prompt": full_prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "16:9",
            "safetyFilterLevel": "block_only_high",
        }
    }
    url     = f"{GOOGLE_ENDPOINT}?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}

    for attempt in range(1, GOOGLE_MAX_RETRIES + 1):
        print(f"[IMG] Google Imagen — Scene {idx+1} attempt {attempt}/{GOOGLE_MAX_RETRIES}")
        try:
            # Block until response arrives (no timeout skip)
            resp = requests.post(
                url, json=payload, headers=headers,
                timeout=GOOGLE_TIMEOUT
            )

            if resp.status_code == 200:
                data = resp.json()
                # Extract base64 image
                b64 = (
                    data
                    .get("predictions", [{}])[0]
                    .get("bytesBase64Encoded", "")
                )
                if b64:
                    import base64
                    print(f"[IMG] ✅ Google Imagen Scene {idx+1}")
                    return base64.b64decode(b64)
                else:
                    print(f"[IMG] Google returned empty image — retry")

            elif resp.status_code == 429:
                wait = GOOGLE_RETRY_WAIT * attempt
                print(f"[IMG] Google 429 rate limit — waiting {wait}s then retry")
                time.sleep(wait)

            elif resp.status_code in (500, 503):
                wait = GOOGLE_RETRY_WAIT
                print(f"[IMG] Google server error {resp.status_code} — waiting {wait}s")
                time.sleep(wait)

            else:
                print(f"[IMG] Google error {resp.status_code}: {resp.text[:200]}")
                # Don't retry on 4xx client errors except 429
                if resp.status_code < 500 and resp.status_code != 429:
                    return None

        except requests.Timeout:
            print(f"[IMG] Google timeout after {GOOGLE_TIMEOUT}s — retry {attempt}")
            time.sleep(GOOGLE_RETRY_WAIT)

        except Exception as e:
            print(f"[IMG] Google exception: {e} — retry {attempt}")
            time.sleep(GOOGLE_RETRY_WAIT)

    print(f"[IMG] Google failed after {GOOGLE_MAX_RETRIES} attempts")
    return None


# ══════════════════════════════════════════════
#  POLLINATIONS.AI — FALLBACK
# ══════════════════════════════════════════════

def _pollinations(prompt: str, idx: int) -> bytes | None:
    """
    Pollinations.ai fallback — free, no key needed.
    Sequential — waits for full response.
    """
    full_prompt = (
        f"{prompt}, cinematic, photorealistic, dramatic lighting, "
        f"4K, wide establishing shot, no text, no watermarks, no faces"
    )
    url = (
        f"https://image.pollinations.ai/prompt/{requests.utils.quote(full_prompt)}"
        f"?width={VIDEO_W}&height={VIDEO_H}&nologo=true&enhance=true&seed={idx * 137 + 42}"
    )

    for attempt in range(1, POLL_MAX_RETRIES + 1):
        print(f"[IMG] Pollinations fallback — Scene {idx+1} attempt {attempt}/{POLL_MAX_RETRIES}")
        try:
            # Wait fully for response — no premature switch
            resp = requests.get(url, timeout=POLL_TIMEOUT)

            if resp.status_code == 200 and len(resp.content) > 1000:
                print(f"[IMG] ✅ Pollinations Scene {idx+1}")
                return resp.content

            elif resp.status_code == 429:
                wait = POLL_RETRY_WAIT * attempt
                print(f"[IMG] Pollinations 429 — waiting {wait}s")
                time.sleep(wait)

            else:
                print(f"[IMG] Pollinations {resp.status_code} — retry {attempt}")
                time.sleep(POLL_RETRY_WAIT)

        except requests.Timeout:
            print(f"[IMG] Pollinations timeout — retry {attempt}")
            time.sleep(POLL_RETRY_WAIT)

        except Exception as e:
            print(f"[IMG] Pollinations exception: {e} — retry {attempt}")
            time.sleep(POLL_RETRY_WAIT)

    print(f"[IMG] Pollinations also failed after {POLL_MAX_RETRIES} attempts")
    return None


# ══════════════════════════════════════════════
#  BLACK FRAME — LAST RESORT ONLY
# ══════════════════════════════════════════════

def _black_frame(path: str) -> str:
    """Only called if BOTH providers completely fail."""
    print(f"[IMG] ⚠️ Both providers failed — black frame last resort")
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=black:s={VIDEO_W}x{VIDEO_H}:d=1",
        "-frames:v", "1", path
    ], capture_output=True)
    return path


# ══════════════════════════════════════════════
#  MAIN — download_scene_image()
#  Called by production_agent.py
# ══════════════════════════════════════════════

def download_scene_image(prompt: str, idx: int) -> str:
    """
    Download one scene image.

    Flow:
    1. Try Google Imagen (primary) — retry up to 3x on failure
    2. Only if Google fails → try Pollinations — retry up to 3x
    3. Only if both fail → black frame (should never happen)

    Sequential: blocks until image is received before returning.
    No timeout skipping — we wait for the actual response.
    """
    path = str(OUTPUTS_DIR / f"scene_{idx:02d}.jpg")

    # ── Try Google first ──────────────────────
    image_bytes = _google_imagen(prompt, idx)

    # ── Fallback to Pollinations ──────────────
    if image_bytes is None:
        print(f"[IMG] Switching to Pollinations fallback for Scene {idx+1}")
        image_bytes = _pollinations(prompt, idx)

    # ── Save or black frame ───────────────────
    if image_bytes:
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path
    else:
        return _black_frame(path)
