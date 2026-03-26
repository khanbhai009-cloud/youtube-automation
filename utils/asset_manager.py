import os
import re
import requests
import hashlib
from pathlib import Path

ASSETS_DIR = Path("outputs/assets")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")

def _sanitize(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower())

def fetch_icon(keyword: str) -> str:
    """Returns local path to a PNG icon for the given keyword."""
    safe = _sanitize(keyword)
    cache_path = ASSETS_DIR / f"{safe}.png"
    if cache_path.exists():
        return str(cache_path)

    # --- Primary: RapidAPI Icons8 / Flaticon ---
    if RAPIDAPI_KEY:
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
            print(f"[ASSET] Icon fetched via RapidAPI: {keyword}")
            return str(cache_path)
        except Exception as e:
            print(f"[ASSET] RapidAPI failed: {e}. Using SVG fallback...")

    # --- Fallback: Generate colored SVG circle with initial letter ---
    _generate_fallback_icon(keyword, cache_path)
    return str(cache_path)


def _generate_fallback_icon(keyword: str, path: Path):
    from PIL import Image, ImageDraw, ImageFont
    import io

    colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
              "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9"]
    color = colors[int(hashlib.md5(keyword.encode()).hexdigest(), 16) % len(colors)]
    letter = keyword[0].upper() if keyword else "?"

    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([10, 10, 246, 246], fill=color)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), letter, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((256 - tw) / 2, (256 - th) / 2 - 10), letter, fill="white", font=font)
    img.save(str(path), "PNG")
    print(f"[ASSET] Fallback icon generated for: {keyword}")
