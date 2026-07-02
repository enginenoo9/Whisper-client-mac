#!/usr/bin/env python3
"""
generate-icon.py — build the app's .icns files from assets/icon-source.png.

Takes the icon artwork (a rounded-square image, any size, transparent
background) and normalizes it onto the standard Apple icon grid: the shape
is scaled to 824 px and centered in a 1024 px canvas with transparent
margins. Skipping that normalization is what makes an icon look oversized
next to native apps in the Dock — macOS does NOT add the margins for you.

Requires Pillow:  pip3 install pillow

Reads:   assets/icon-source.png
Writes:  whisper_icon.png                                  (1024 px, on-grid)
         whisper_icon.icns
         Whisper Transcriber.app/Contents/Resources/icon.icns
"""

import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CANVAS = 1024
SHAPE = 824          # Apple's standard icon-grid shape size


def main() -> None:
    src_path = os.path.join(ROOT, "assets", "icon-source.png")
    if not os.path.exists(src_path):
        sys.exit(f"✗ {src_path} not found — add the icon artwork there first.")

    src = Image.open(src_path).convert("RGBA")

    # Crop to the artwork's actual content (non-transparent bounding box),
    # so any margins already present in the source don't stack with ours.
    bbox = src.getbbox()
    if bbox is None:
        sys.exit("✗ Source image is fully transparent.")
    content = src.crop(bbox)

    scale = SHAPE / max(content.size)
    new_size = (round(content.width * scale), round(content.height * scale))
    content = content.resize(new_size, Image.LANCZOS)

    icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    icon.paste(content, ((CANVAS - content.width) // 2,
                         (CANVAS - content.height) // 2), content)

    outputs = [
        (os.path.join(ROOT, "whisper_icon.png"), "PNG"),
        (os.path.join(ROOT, "whisper_icon.icns"), "ICNS"),
        (os.path.join(ROOT, "Whisper Transcriber.app", "Contents",
                      "Resources", "icon.icns"), "ICNS"),
    ]
    for path, fmt in outputs:
        icon.save(path, format=fmt)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
