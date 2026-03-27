import os
import re
import requests
import hashlib
from pathlib import Path

ASSETS_DIR = Path("outputs/assets")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")

# Iconify icon sets to search — ordered by visual quality
ICONIFY_SETS = ["fluent-emoji-flat", "twemoji", "noto", "mdi"]

def _sanitize(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower())


# ─────────────────────────────────────────────
#  SOURCE 1: Iconify (free, no API key, 200k+ icons)
# ─────────────────────────────────────────────
def _fetch_iconify(keyword: str, cache_path: Path) -> bool:
    """
    Search Iconify for keyword, download as PNG.
    Tries emoji sets first (colorful), then flat icons.
    """
    try:
        # Search across all sets
        search_url = "https://api.iconify.design/search"
        params = {"query": keyword, "limit": 8, "pretty": 0}
        r = requests.get(search_url, params=params, timeout=8)
        data = r.json()

        icons = data.get("icons", [])
        if not icons:
            return False

        # Prefer emoji/colorful sets
        chosen = None
        for icon in icons:
            prefix = icon.split(":")[0]
            if prefix in ("fluent-emoji-flat", "twemoji", "noto", "emojione"):
                chosen = icon
                break
        if not chosen:
            chosen = icons[0]  # fallback to first result

        prefix, name = chosen.split(":", 1)

        # Download PNG directly from Iconify CDN
        png_url = f"https://api.iconify.design/{prefix}/{name}.png?width=256&height=256"
        img_r = requests.get(png_url, timeout=10)

        if img_r.status_code == 200 and img_r.headers.get("content-type", "").startswith("image"):
            cache_path.write_bytes(img_r.content)
            print(f"[ASSET] Iconify icon: {chosen} → {keyword}")
            return True

        return False

    except Exception as e:
        print(f"[ASSET] Iconify failed: {e}")
        return False


# ─────────────────────────────────────────────
#  SOURCE 2: RapidAPI Flaticon (if key available)
# ─────────────────────────────────────────────
def _fetch_rapidapi(keyword: str, cache_path: Path) -> bool:
    if not RAPIDAPI_KEY:
        return False
    try:
        url = "https://flaticon.p.rapidapi.com/v3/icons/search"
        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": "flaticon.p.rapidapi.com",
        }
        params = {"q": keyword, "limit": 1, "styleColor": "1"}
        r = requests.get(url, headers=headers, params=params, timeout=8)
        data = r.json()
        icon_url = data["data"][0]["images"]["256"]
        img_bytes = requests.get(icon_url, timeout=10).content
        cache_path.write_bytes(img_bytes)
        print(f"[ASSET] RapidAPI icon fetched: {keyword}")
        return True
    except Exception as e:
        print(f"[ASSET] RapidAPI failed: {e}")
        return False


# ─────────────────────────────────────────────
#  SOURCE 3: Pillow fallback (always works)
# ─────────────────────────────────────────────
def _generate_fallback_icon(keyword: str, path: Path):
    from PIL import Image, ImageDraw, ImageFont

    colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
              "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9"]
    color = colors[int(hashlib.md5(keyword.encode()).hexdigest(), 16) % len(colors)]
    letter = keyword[0].upper() if keyword else "?"

    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Gradient-like double circle for better look
    draw.ellipse([0, 0, 255, 255], fill=color)
    draw.ellipse([15, 15, 240, 240], fill=color)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), letter, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Shadow
    draw.text(((256 - tw) / 2 + 3, (256 - th) / 2 - 7), letter, fill=(0, 0, 0, 60), font=font)
    # Letter
    draw.text(((256 - tw) / 2, (256 - th) / 2 - 10), letter, fill="white", font=font)

    img.save(str(path), "PNG")
    print(f"[ASSET] Pillow fallback icon generated for: {keyword}")


# ─────────────────────────────────────────────
#  MAIN ENTRY
# ─────────────────────────────────────────────
def fetch_icon(keyword: str) -> str:
    """
    Returns local path to a 256x256 PNG icon for the given keyword.
    Priority: Cache → Iconify (free) → RapidAPI → Pillow fallback
    """
    safe = _sanitize(keyword)
    cache_path = ASSETS_DIR / f"{safe}.png"

    # Return cached version
    if cache_path.exists():
        return str(cache_path)

    # 1. Iconify — free, no key, colorful emoji icons
    if _fetch_iconify(keyword, cache_path):
        return str(cache_path)

    # 2. RapidAPI — if key available
    if _fetch_rapidapi(keyword, cache_path):
        return str(cache_path)

    # 3. Pillow fallback — always works
    _generate_fallback_icon(keyword, cache_path)
    return str(cache_path)
