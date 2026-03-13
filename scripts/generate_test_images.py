"""Download or generate kitchen scenario images for vision testing.

Attempts to download real food photos from Pexels (free, no auth for CDN).
Falls back to Pillow-generated synthetic images with realistic colors
and descriptive labels if downloads fail.

Usage:
    python scripts/generate_test_images.py
"""

import io
import os
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "harness" / "fixtures" / "images"
WIDTH, HEIGHT = 640, 480

PEXELS_IMAGES = {
    "raw_chicken_thighs.jpg": {
        "url": "https://images.pexels.com/photos/616354/pexels-photo-616354.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "raw chicken thighs on a cutting board",
        "bg_color": (220, 190, 170),
        "fg_color": (200, 160, 130),
        "label": "RAW CHICKEN\nTHIGHS",
    },
    "garlic_butter_ingredients.jpg": {
        "url": "https://images.pexels.com/photos/1435901/pexels-photo-1435901.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "garlic, butter, and chicken ingredients on counter",
        "bg_color": (200, 180, 160),
        "fg_color": (240, 220, 180),
        "label": "GARLIC + BUTTER\n+ CHICKEN",
    },
    "cold_pan_oil.jpg": {
        "url": "https://images.pexels.com/photos/4252137/pexels-photo-4252137.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "oil in a cold stainless steel pan, no shimmer",
        "bg_color": (180, 180, 185),
        "fg_color": (220, 215, 100),
        "label": "COLD PAN\nWITH OIL",
    },
    "hot_pan_shimmer.jpg": {
        "url": "https://images.pexels.com/photos/4252139/pexels-photo-4252139.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "oil shimmering in a hot pan, ready to cook",
        "bg_color": (150, 150, 155),
        "fg_color": (255, 240, 100),
        "label": "HOT PAN\nOIL SHIMMER",
    },
    "poor_knife_grip.jpg": {
        "url": "https://images.pexels.com/photos/8477972/pexels-photo-8477972.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "hand mincing garlic with poor knife grip, fingers exposed",
        "bg_color": (200, 180, 150),
        "fg_color": (170, 130, 100),
        "label": "POOR KNIFE\nGRIP",
    },
    "good_knife_grip.jpg": {
        "url": "https://images.pexels.com/photos/4259140/pexels-photo-4259140.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "hand with proper claw grip chopping on cutting board",
        "bg_color": (180, 160, 130),
        "fg_color": (210, 190, 160),
        "label": "PROPER CLAW\nKNIFE GRIP",
    },
    "chicken_searing.jpg": {
        "url": "https://images.pexels.com/photos/3298063/pexels-photo-3298063.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "chicken thighs searing skin-side down in a hot pan",
        "bg_color": (100, 90, 80),
        "fg_color": (220, 180, 120),
        "label": "CHICKEN\nSEARING",
    },
    "golden_brown_sear.jpg": {
        "url": "https://images.pexels.com/photos/2673353/pexels-photo-2673353.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "golden-brown seared chicken thighs in pan",
        "bg_color": (120, 100, 70),
        "fg_color": (210, 170, 80),
        "label": "GOLDEN BROWN\nSEARED",
    },
    "burnt_food.jpg": {
        "url": "https://images.pexels.com/photos/6419736/pexels-photo-6419736.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "burnt food in a smoking pan, overcooked",
        "bg_color": (60, 40, 30),
        "fg_color": (30, 20, 10),
        "label": "BURNT FOOD\nOVERCOOKED",
    },
    "non_food.jpg": {
        "url": "https://images.pexels.com/photos/303383/pexels-photo-303383.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&dpr=1",
        "description": "a laptop on a desk, non-food item",
        "bg_color": (200, 200, 210),
        "fg_color": (100, 100, 120),
        "label": "LAPTOP\nON DESK",
    },
}


def download_image(url: str, target_path: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SousChefTest/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
        img.save(str(target_path), "JPEG", quality=85)
        return True
    except Exception as e:
        print(f"  Download failed: {e}")
        return False


def generate_fallback(info: dict, target_path: Path) -> None:
    """Create a synthetic image with color blocks and text labels."""
    img = Image.new("RGB", (WIDTH, HEIGHT), info["bg_color"])
    draw = ImageDraw.Draw(img)

    cx, cy = WIDTH // 2, HEIGHT // 2
    r = min(WIDTH, HEIGHT) // 4
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=info["fg_color"])

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        except (OSError, IOError):
            font = ImageFont.load_default()

    draw.multiline_text((cx, cy), info["label"], fill=(255, 255, 255),
                        font=font, anchor="mm", align="center")

    desc_font_size = 18
    try:
        desc_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", desc_font_size)
    except (OSError, IOError):
        try:
            desc_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", desc_font_size)
        except (OSError, IOError):
            desc_font = ImageFont.load_default()

    draw.text((WIDTH // 2, HEIGHT - 30), info["description"],
              fill=(255, 255, 255), font=desc_font, anchor="mm")

    img.save(str(target_path), "JPEG", quality=85)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating test images in {OUT_DIR}")

    for filename, info in PEXELS_IMAGES.items():
        target = OUT_DIR / filename
        print(f"\n{filename}:")

        if target.exists():
            size = target.stat().st_size
            if size > 5000:
                print(f"  Already exists ({size:,} bytes), skipping")
                continue

        print(f"  Downloading from Pexels...")
        if download_image(info["url"], target):
            print(f"  OK ({target.stat().st_size:,} bytes)")
        else:
            print(f"  Generating synthetic fallback...")
            generate_fallback(info, target)
            print(f"  OK ({target.stat().st_size:,} bytes)")

    print(f"\nDone. {len(PEXELS_IMAGES)} images in {OUT_DIR}")


if __name__ == "__main__":
    main()
