"""Deterministically generate TeaMode's Discord art assets.

Produces three flat, geometric teacup/steam compositions in the TeaMode
palette:

- ``assets/app-icon.png``   (1024x1024, 1:1)
- ``assets/app-banner.png`` (680x240, 17:6)
- ``assets/avatar.png``     (1024x1024, 1:1, centered for circular display)

No randomness, no network access, and no external images or fetched fonts:
the banner's "TeaMode" wordmark is only drawn when a system TrueType font is
found (probed under common paths); otherwise the banner renders without
text. Everything is drawn at 4x resolution and downsampled with
``Image.Resampling.LANCZOS`` for anti-aliasing, so re-running this script
produces byte-identical PNGs.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

type RGBColor = tuple[int, int, int]
type BoxF = tuple[float, float, float, float]

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "assets"

# Draw at 4x and downsample for anti-aliasing.
SUPERSAMPLE = 4

# --- Palette ----------------------------------------------------------------

MATCHA_SAGE: RGBColor = (0x7B, 0x9D, 0x6F)
STEEPING_FOREST: RGBColor = (0x3F, 0x5E, 0x4A)
OOLONG_AMBER: RGBColor = (0xC9, 0x7B, 0x53)
MUTED_GREY: RGBColor = (0x8A, 0x8A, 0x8A)

# Common DejaVu install locations on Debian/Ubuntu (WSL default). Probed in
# order; the banner renders without text if none exist.
FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def lighten(color: RGBColor, factor: float) -> RGBColor:
    """Blend ``color`` toward white by ``factor`` (0 = unchanged, 1 = white)."""
    r, g, b = color
    return (
        int(r + (255 - r) * factor),
        int(g + (255 - g) * factor),
        int(b + (255 - b) * factor),
    )


def find_font(size: int) -> ImageFont.FreeTypeFont | None:
    """Return the first available candidate TrueType font at ``size``, or None."""
    for path in FONT_CANDIDATES:
        candidate = Path(path)
        if not candidate.is_file():
            continue
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    return None


def draw_teacup_scene(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    content_scale: float = 0.8,
) -> None:
    """Draw a centered teacup-and-steam composition into ``box`` (a square).

    ``content_scale`` shrinks the whole composition toward the box's center,
    which is how the avatar keeps its subject inside the ~80% diameter
    circular safe area Discord uses for round display.
    """
    x0, y0, x1, y1 = box
    side = x1 - x0

    def pt(ux: float, uy: float) -> tuple[float, float]:
        sx = 0.5 + (ux - 0.5) * content_scale
        sy = 0.5 + (uy - 0.5) * content_scale
        return (x0 + sx * side, y0 + sy * side)

    def rect(ux0: float, uy0: float, ux1: float, uy1: float) -> BoxF:
        px0, py0 = pt(ux0, uy0)
        px1, py1 = pt(ux1, uy1)
        return (px0, py0, px1, py1)

    draw = ImageDraw.Draw(canvas)

    # Saucer.
    draw.ellipse(rect(0.12, 0.74, 0.88, 0.86), fill=OOLONG_AMBER)

    # Cup body.
    radius = 0.05 * side * content_scale
    draw.rounded_rectangle(
        rect(0.22, 0.42, 0.78, 0.74), radius=radius, fill=STEEPING_FOREST
    )

    # Tea surface (the cup's opening).
    draw.ellipse(rect(0.24, 0.38, 0.76, 0.46), fill=OOLONG_AMBER)
    rim_width = max(1, int(0.01 * side * content_scale))
    draw.ellipse(
        rect(0.24, 0.38, 0.76, 0.46), outline=lighten(MATCHA_SAGE, 0.3), width=rim_width
    )

    # Handle.
    handle_width = max(1, int(0.035 * side * content_scale))
    draw.arc(
        rect(0.74, 0.46, 0.96, 0.68),
        start=-100,
        end=100,
        fill=MATCHA_SAGE,
        width=handle_width,
    )

    # Steam: three translucent wavy strokes, drawn on their own layer so they
    # blend softly over whatever sits behind them.
    steam_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    steam_draw = ImageDraw.Draw(steam_layer)
    stroke = max(1, int(0.018 * side * content_scale))
    steps = 40
    curls: tuple[tuple[float, float, int], ...] = (
        (0.38, 0.0, 150),
        (0.50, 1.4, 190),
        (0.62, 2.8, 150),
    )
    for x_center, phase, alpha in curls:
        points: list[tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            ux = x_center + 0.045 * math.sin(t * 2 * math.pi + phase)
            uy = 0.36 - t * 0.26
            points.append(pt(ux, uy))
        steam_draw.line(points, fill=(*MUTED_GREY, alpha), width=stroke, joint="curve")
    canvas.alpha_composite(steam_layer)


def background_color() -> RGBColor:
    """A light, warm-neutral sage tint derived from the palette."""
    return lighten(MATCHA_SAGE, 0.85)


def render_square(path: Path, dimension: int) -> None:
    supersize = dimension * SUPERSAMPLE
    bg = background_color()
    canvas = Image.new("RGBA", (supersize, supersize), (*bg, 255))
    draw_teacup_scene(canvas, (0, 0, supersize, supersize), content_scale=0.8)
    final = canvas.convert("RGB").resize(
        (dimension, dimension), Image.Resampling.LANCZOS
    )
    final.save(path, format="PNG")


def render_banner(path: Path, width: int, height: int) -> None:
    super_w, super_h = width * SUPERSAMPLE, height * SUPERSAMPLE
    bg = background_color()
    canvas = Image.new("RGBA", (super_w, super_h), (*bg, 255))

    margin = int(super_h * 0.08)
    scene_side = super_h - 2 * margin
    scene_box = (margin, margin, margin + scene_side, margin + scene_side)
    draw_teacup_scene(canvas, scene_box, content_scale=0.85)

    font = find_font(int(super_h * 0.30))
    if font is not None:
        draw = ImageDraw.Draw(canvas)
        text = "TeaMode"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_h = bbox[3] - bbox[1]
        text_x = scene_box[2] + int(super_h * 0.12)
        text_y = (super_h - text_h) / 2 - bbox[1]
        draw.text((text_x, text_y), text, font=font, fill=STEEPING_FOREST)

    final = canvas.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
    final.save(path, format="PNG")


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    render_square(ASSETS_DIR / "app-icon.png", 1024)
    render_square(ASSETS_DIR / "avatar.png", 1024)
    render_banner(ASSETS_DIR / "app-banner.png", 680, 240)


if __name__ == "__main__":
    main()
