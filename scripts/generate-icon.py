#!/usr/bin/env python3
"""
generate-icon.py — draw the Whisper Transcriber app icon.

Produces a modern macOS (Big Sur+) style icon: a rounded-square "squircle"
sitting inside the standard Apple icon grid (824 px shape centered in a
1024 px canvas with transparent margins — filling the full canvas is what
makes an icon look oversized next to native apps in the Dock), with a
gradient background and a white microphone + sound-bar glyph.

Requires Pillow:  pip3 install pillow

Writes, relative to the repo root:
    whisper_icon.png                                     (1024 px preview/source)
    whisper_icon.icns
    Whisper Transcriber.app/Contents/Resources/icon.icns
"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Everything is drawn at 4x and downsampled for smooth edges.
S = 4
CANVAS = 1024 * S
SHAPE = 824 * S                      # Apple's standard icon-grid shape size
MARGIN = (CANVAS - SHAPE) // 2
RADIUS = int(SHAPE * 0.2237)         # Big Sur squircle corner ratio (~185/824)

GRAD_TOP = (77, 159, 255)            # light sky blue
GRAD_BOTTOM = (40, 84, 222)          # deep indigo-blue
WHITE = (255, 255, 255, 255)


def px(v: float) -> int:
    """1024-space coordinate -> supersampled canvas coordinate."""
    return int(v * S)


def build_background() -> Image.Image:
    """Vertical gradient clipped to the squircle, transparent outside."""
    grad_mask = Image.linear_gradient("L").resize((CANVAS, CANVAS))
    top = Image.new("RGB", (CANVAS, CANVAS), GRAD_TOP)
    bottom = Image.new("RGB", (CANVAS, CANVAS), GRAD_BOTTOM)
    gradient = Image.composite(bottom, top, grad_mask)

    shape_mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(shape_mask).rounded_rectangle(
        (MARGIN, MARGIN, MARGIN + SHAPE, MARGIN + SHAPE),
        radius=RADIUS, fill=255)

    icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    icon.paste(gradient, (0, 0), shape_mask)
    return icon


def draw_glyph(icon: Image.Image) -> None:
    d = ImageDraw.Draw(icon)
    cx = 512

    # Mic capsule body
    d.rounded_rectangle((px(cx - 92), px(288), px(cx + 92), px(556)),
                        radius=px(92), fill=WHITE)

    # U-shaped holder: bottom half of a circle centered at (512, 524)
    r = 168
    d.arc((px(cx - r), px(524 - r), px(cx + r), px(524 + r)),
          start=0, end=180, fill=WHITE, width=px(40))
    # Round the arc's cut ends with small caps
    for ex in (cx - r + 20, cx + r - 20):
        d.ellipse((px(ex - 20), px(504), px(ex + 20), px(544)), fill=WHITE)

    # Stem and base
    d.rounded_rectangle((px(cx - 20), px(688), px(cx + 20), px(768)),
                        radius=px(20), fill=WHITE)
    d.rounded_rectangle((px(cx - 104), px(752), px(cx + 104), px(792)),
                        radius=px(20), fill=WHITE)

    # Sound bars flanking the mic
    for bx in (cx - 262, cx + 262):
        d.rounded_rectangle((px(bx - 17), px(376), px(bx + 17), px(496)),
                            radius=px(17), fill=WHITE)


def main() -> None:
    icon = build_background()
    draw_glyph(icon)
    final = icon.resize((1024, 1024), Image.LANCZOS)

    png_path = os.path.join(ROOT, "whisper_icon.png")
    icns_path = os.path.join(ROOT, "whisper_icon.icns")
    bundle_icns = os.path.join(
        ROOT, "Whisper Transcriber.app", "Contents", "Resources", "icon.icns")

    final.save(png_path)
    final.save(icns_path, format="ICNS")
    final.save(bundle_icns, format="ICNS")
    print(f"Wrote {png_path}")
    print(f"Wrote {icns_path}")
    print(f"Wrote {bundle_icns}")


if __name__ == "__main__":
    main()
