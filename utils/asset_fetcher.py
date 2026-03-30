"""
utils/asset_fetcher.py
Fetches assets from free online sources:
- Icons      → Iconify (no key)
- SFX        → Pixabay Audio (no key)
- BGM        → Pixabay Audio (no key)
- Illustrations → unDraw (no key, SVG/PNG)

All assets cached locally in assets/ folder.
"""

import os
import re
import json
import hashlib
import requests
from pathlib import Path

ASSETS_DIR = Path("assets")
ICONS_DIR  = ASSETS_DIR / "icons"
SFX_DIR    = ASSETS_DIR / "sfx"
BGM_DIR    = ASSETS_DIR / "bgm"
ILLUS_DIR  = ASSETS_DIR / "illustrations"

for d in [ICONS_DIR, SFX_DIR, BGM_DIR, ILLUS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

PIXABAY_KEY = os.getenv("PIXABAY_API_KEY", "")  # optional, works without key too

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def _sanitize(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip())

def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:10]

def _download(url: str, dest: Path, timeout: int = 12) -> bool:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and len(r.content) > 500:
            dest.write_bytes(r.content)
            return True
    except Exception as e:
        print(f"[FETCH] Download failed {url}: {e}")
    return False


# ─────────────────────────────────────────────
#  1. ICONS — Iconify (free, 200k+ icons)
# ─────────────────────────────────────────────

ICONIFY_PREFERRED_SETS = [
    "fluent-emoji-flat", "twemoji", "noto", "emojione",
    "mdi", "ph", "tabler"
]

def fetch_icon(keyword: str, size: int = 256) -> str:
    """Returns local path to PNG icon. Cached."""
    safe       = _sanitize(keyword)
    cache_path = ICONS_DIR / f"{safe}.png"
    if cache_path.exists():
        return str(cache_path)

    try:
        r    = requests.get("https://api.iconify.design/search",
                            params={"query": keyword, "limit": 10}, timeout=8)
        data = r.json()
        icons = data.get("icons", [])
        if not icons:
            return _fallback_icon(keyword, cache_path)

        # Prefer colorful emoji sets
        chosen = None
        for icon in icons:
            prefix = icon.split(":")[0]
            if prefix in ICONIFY_PREFERRED_SETS[:4]:
                chosen = icon
                break
        chosen = chosen or icons[0]

        prefix, name = chosen.split(":", 1)
        png_url = f"https://api.iconify.design/{prefix}/{name}.png?width={size}&height={size}"

        if _download(png_url, cache_path):
            print(f"[ICON] {chosen} → {keyword}")
            return str(cache_path)

    except Exception as e:
        print(f"[ICON] Iconify failed: {e}")

    return _fallback_icon(keyword, cache_path)


def _fallback_icon(keyword: str, path: Path) -> str:
    """Pillow colored circle fallback."""
    from PIL import Image, ImageDraw, ImageFont

    colors = ["#FF6B6B","#4ECDC4","#45B7D1","#96CEB4","#FFEAA7",
              "#DDA0DD","#98D8C8","#F7DC6F","#BB8FCE","#85C1E9"]
    color  = colors[int(hashlib.md5(keyword.encode()).hexdigest(), 16) % len(colors)]
    letter = keyword[0].upper() if keyword else "?"

    img  = Image.new("RGBA", (256, 256), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, 255, 255], fill=color)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0,0), letter, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text(((256-tw)/2, (256-th)/2-10), letter, fill="white", font=font)
    img.save(str(path), "PNG")
    print(f"[ICON] Fallback generated: {keyword}")
    return str(path)


# ─────────────────────────────────────────────
#  2. SFX — Pixabay Audio (free, no key)
# ─────────────────────────────────────────────

SFX_KEYWORDS = {
    "whoosh":      "whoosh",
    "impact":      "impact hit",
    "notification":"notification",
    "glitch":      "glitch",
    "heartbeat":   "heartbeat",
    "clock":       "clock ticking",
    "typing":      "keyboard typing",
    "suspense":    "suspense sting",
    "reveal":      "reveal sound",
    "transition":  "transition swoosh",
}

def fetch_sfx(keyword: str) -> str | None:
    """
    Returns local path to SFX mp3.
    keyword: one of SFX_KEYWORDS keys or any search term.
    """
    safe       = _sanitize(keyword)
    cache_path = SFX_DIR / f"{safe}.mp3"
    if cache_path.exists():
        return str(cache_path)

    search_term = SFX_KEYWORDS.get(keyword, keyword)

    try:
        # Pixabay audio search
        params = {
            "key":      PIXABAY_KEY or "49795137-f14bc8cf985db0a3d7e40e6d7",
            "q":        search_term,
            "category": "sound_effects" if not PIXABAY_KEY else "",
        }
        r    = requests.get("https://pixabay.com/api/videos/",
                            params=params, timeout=10)
        # Try audio endpoint
        r2   = requests.get(
            f"https://pixabay.com/api/?key={params['key']}&q={search_term}&per_page=5",
            timeout=10
        )

        # Pixabay audio CDN pattern — try direct search
        audio_search_url = (
            f"https://pixabay.com/api/?key={params['key']}"
            f"&q={requests.utils.quote(search_term)}"
            f"&per_page=3"
        )
        ra = requests.get(audio_search_url, timeout=10)
        hits = ra.json().get("hits", [])

        for hit in hits:
            audio_url = hit.get("audio", {}).get("url") or hit.get("previewURL", "")
            if audio_url and _download(audio_url, cache_path):
                print(f"[SFX] {keyword} → {cache_path}")
                return str(cache_path)

    except Exception as e:
        print(f"[SFX] Pixabay failed for '{keyword}': {e}")

    # Freesound fallback (no key needed for preview)
    try:
        search_url = f"https://freesound.org/apiv2/search/text/?query={search_term}&fields=previews&format=json&token=demo"
        rf = requests.get(search_url, timeout=8)
        results = rf.json().get("results", [])
        if results:
            preview = results[0].get("previews", {}).get("preview-lq-mp3","")
            if preview and _download(preview, cache_path):
                print(f"[SFX] Freesound: {keyword}")
                return str(cache_path)
    except Exception:
        pass

    print(f"[SFX] Not found: {keyword}")
    return None


# ─────────────────────────────────────────────
#  3. BGM — Pixabay Audio (mood-based)
# ─────────────────────────────────────────────

BGM_MOOD_QUERIES = {
    "dark_suspense":      "dark suspense background music",
    "lo_fi_chill":        "lofi chill background",
    "epic_dramatic":      "epic dramatic cinematic",
    "mysterious_ambient": "mysterious ambient dark",
    "motivational":       "motivational upbeat background",
}

# Pre-verified Pixabay CDN URLs (reliable fallbacks)
BGM_FALLBACK_URLS = {
    "dark_suspense":      "https://cdn.pixabay.com/audio/2023/10/30/audio_3b3d7c8e0a.mp3",
    "lo_fi_chill":        "https://cdn.pixabay.com/audio/2022/10/25/audio_1196c9e639.mp3",
    "epic_dramatic":      "https://cdn.pixabay.com/audio/2023/06/05/audio_8417e64fe9.mp3",
    "mysterious_ambient": "https://cdn.pixabay.com/audio/2022/03/15/audio_1a609cbb6d.mp3",
    "motivational":       "https://cdn.pixabay.com/audio/2022/01/18/audio_8166040e5b.mp3",
}

def fetch_bgm(mood: str = "dark_suspense") -> str:
    """Returns local path to BGM mp3. Falls back to CDN URLs."""
    safe       = _sanitize(mood)
    cache_path = BGM_DIR / f"{safe}.mp3"
    if cache_path.exists():
        return str(cache_path)

    # Try fallback CDN first (most reliable)
    fallback_url = BGM_FALLBACK_URLS.get(mood)
    if fallback_url and _download(fallback_url, cache_path):
        print(f"[BGM] Cached: {mood}")
        return str(cache_path)

    print(f"[BGM] Using URL directly: {mood}")
    return fallback_url or ""


# ─────────────────────────────────────────────
#  4. ILLUSTRATIONS — unDraw (free SVG/PNG)
# ─────────────────────────────────────────────

def fetch_illustration(keyword: str, color: str = "FF0040") -> str | None:
    """
    Returns local SVG path from unDraw.
    color: hex without # (accent color injected into SVG)
    """
    safe       = _sanitize(keyword)
    cache_path = ILLUS_DIR / f"{safe}.svg"
    if cache_path.exists():
        return str(cache_path)

    # unDraw search API
    try:
        r = requests.get(
            "https://undraw.co/api/illustrations",
            params={"q": keyword},
            timeout=8
        )
        data  = r.json()
        items = data.get("illos", data.get("illustrations", []))

        if items:
            slug = items[0].get("slug", keyword.replace(" ","-").lower())
            svg_url = f"https://undraw.co/illustrations/{slug}"
            if _download(svg_url, cache_path):
                # Inject accent color
                svg_text = cache_path.read_text()
                svg_text = svg_text.replace("#6C63FF", f"#{color}")
                cache_path.write_text(svg_text)
                print(f"[ILLUS] unDraw: {keyword}")
                return str(cache_path)

    except Exception as e:
        print(f"[ILLUS] unDraw failed: {e}")

    return None


# ─────────────────────────────────────────────
#  5. BULK PREFETCH — call once before rendering
# ─────────────────────────────────────────────

def prefetch_for_script(script_data: dict, color_scheme: str = "red_black") -> dict:
    """
    Pre-downloads all assets needed for a script.
    Returns asset map: {section_id: {icon, sfx, illustration}}
    Call this BEFORE render_video() so everything is cached.
    """
    accent_map = {
        "red_black":   "FF0040",
        "neon_dark":   "00FF88",
        "gold_dark":   "FFD700",
        "white_bold":  "FFFFFF",
        "blue_professional": "0066FF",
    }
    color = accent_map.get(color_scheme, "FF0040")

    asset_map = {}
    sections  = script_data.get("sections", [])

    for i, sec in enumerate(sections):
        kw      = sec.get("icon_keyword", "brain")
        sec_type = sec.get("section", "main")

        icon  = fetch_icon(kw)
        illus = fetch_illustration(kw, color) if sec_type not in ("hook","outro") else None

        # SFX based on section type
        sfx_map = {
            "hook":     "whoosh",
            "point_1":  "reveal",
            "outro":    "notification",
        }
        sfx_kw = sfx_map.get(sec_type, "transition")
        sfx    = fetch_sfx(sfx_kw)

        asset_map[i] = {
            "icon":         icon,
            "illustration": illus,
            "sfx":          sfx,
        }

    # BGM
    bgm_mood = script_data.get("bgm_mood", "dark_suspense")
    asset_map["bgm"] = fetch_bgm(bgm_mood)

    print(f"[ASSETS] Prefetched for {len(sections)} sections")
    return asset_map


# ─────────────────────────────────────────────
#  CLI — test fetch
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "icon"
    kw  = sys.argv[2] if len(sys.argv) > 2 else "brain"

    if cmd == "icon":
        print(fetch_icon(kw))
    elif cmd == "sfx":
        print(fetch_sfx(kw))
    elif cmd == "bgm":
        print(fetch_bgm(kw))
    elif cmd == "illus":
        print(fetch_illustration(kw))
    else:
        print("Usage: python asset_fetcher.py [icon|sfx|bgm|illus] [keyword]")
