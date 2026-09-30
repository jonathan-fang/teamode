"""Deterministically generate TeaMode's Discord art asset candidates.

Produces three design candidates each for the app icon, app banner and bot
avatar, written to a review folder (``--out``, default ``.debug-images`` at
the repo root) as:

- ``app-icon-{1,2,3}.png``   (1024x1024, 1:1)
- ``app-banner-{1,2,3}.png`` (680x240, 17:6)
- ``app-avatar-{1,2,3}.png`` (1024x1024, 1:1, tuned for circular display)

Candidate N of each asset type shares one design idea so a matching set can
be picked together:

1. A flat teacup-and-saucer composition (handle attached to the cup body,
   cup base seated on the saucer) with translucent steam curls.
2. A kettle pouring a stream of tea into a smaller cup, with steam above it.
3. A monoline teacup badge: a circular outline mark on a dark steeping-forest
   ground, for a calmer, high-contrast mark that reads well very small.

No randomness, no network access, and no external images or fetched fonts:
the banner's "TeaMode" wordmark is only drawn when a system TrueType font is
found (probed under common paths); otherwise the banner renders without
text. Everything is drawn at 4x resolution and downsampled with
``Image.Resampling.LANCZOS`` for anti-aliasing, so re-running this script
produces byte-identical PNGs.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

type RGBColor = tuple[int, int, int]
type BoxF = tuple[float, float, float, float]
type BoxI = tuple[int, int, int, int]
type SceneFn = Callable[[Image.Image, BoxI, float], None]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / ".debug-images"

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


def _unit_mappers(
    box: BoxI, content_scale: float
) -> tuple[
    Callable[[float, float], tuple[float, float]],
    Callable[[float, float, float, float], BoxF],
]:
    """Build ``pt``/``rect`` helpers mapping a unit square into ``box``.

    ``content_scale`` shrinks the whole composition toward the box's center,
    which is how the icon/avatar keep their subject inside the ~80% diameter
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

    return pt, rect


def draw_cup_saucer_scene(
    canvas: Image.Image,
    box: BoxI,
    content_scale: float = 0.8,
) -> None:
    """Candidate 1: teacup seated on its saucer, handle attached to the body."""
    x0, y0, x1, y1 = box
    side = x1 - x0
    pt, rect = _unit_mappers(box, content_scale)

    draw = ImageDraw.Draw(canvas)

    # Saucer, drawn first so the cup sits on top of (in front of) it.
    draw.ellipse(rect(0.12, 0.70, 0.88, 0.86), fill=OOLONG_AMBER)

    # Cup body. Its base (uy=0.76) now overlaps the saucer top (uy=0.70), so
    # the cup visibly rests in the saucer instead of merely touching it.
    radius = 0.05 * side * content_scale
    cup_box = rect(0.22, 0.42, 0.78, 0.76)
    draw.rounded_rectangle(cup_box, radius=radius, fill=STEEPING_FOREST)

    # Tea surface (the cup's opening).
    draw.ellipse(rect(0.24, 0.38, 0.76, 0.46), fill=OOLONG_AMBER)
    rim_width = max(1, int(0.01 * side * content_scale))
    draw.ellipse(
        rect(0.24, 0.38, 0.76, 0.46), outline=lighten(MATCHA_SAGE, 0.3), width=rim_width
    )

    # Handle. The arc's bounding box is centered on the cup's right edge
    # (ux=0.78), so both endpoints land just inside the cup body instead of
    # floating beside it with a gap.
    handle_width = max(1, int(0.035 * side * content_scale))
    draw.arc(
        rect(0.66, 0.46, 0.90, 0.68),
        start=-100,
        end=100,
        fill=MATCHA_SAGE,
        width=handle_width,
    )

    _draw_steam(
        canvas,
        pt,
        side,
        content_scale,
        curls=((0.38, 0.0, 150), (0.50, 1.4, 190), (0.62, 2.8, 150)),
    )


def _draw_steam(
    canvas: Image.Image,
    pt: Callable[[float, float], tuple[float, float]],
    side: float,
    content_scale: float,
    curls: tuple[tuple[float, float, int], ...],
    y_top: float = 0.36,
    rise: float = 0.26,
    amplitude: float = 0.045,
) -> None:
    """Draw translucent wavy steam strokes on their own layer over ``canvas``."""
    steam_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    steam_draw = ImageDraw.Draw(steam_layer)
    stroke = max(1, int(0.018 * side * content_scale))
    steps = 40
    for x_center, phase, alpha in curls:
        points: list[tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            ux = x_center + amplitude * math.sin(t * 2 * math.pi + phase)
            uy = y_top - t * rise
            points.append(pt(ux, uy))
        steam_draw.line(points, fill=(*MUTED_GREY, alpha), width=stroke, joint="curve")
    canvas.alpha_composite(steam_layer)


def draw_kettle_pour_scene(
    canvas: Image.Image,
    box: BoxI,
    content_scale: float = 0.85,
) -> None:
    """Candidate 2: a kettle pouring a stream of tea into a small cup."""
    x0, y0, x1, y1 = box
    side = x1 - x0
    pt, rect = _unit_mappers(box, content_scale)
    draw = ImageDraw.Draw(canvas)

    # Kettle handle, attached the same way as the candidate 1 cup handle:
    # centered on the kettle body's top edge so the endpoints sit inside it.
    kettle_handle_width = max(1, int(0.03 * side * content_scale))
    draw.arc(
        rect(0.14, 0.04, 0.42, 0.32),
        start=200,
        end=340,
        fill=MATCHA_SAGE,
        width=kettle_handle_width,
    )

    # Kettle body.
    kettle_radius = 0.06 * side * content_scale
    draw.rounded_rectangle(
        rect(0.10, 0.22, 0.46, 0.58), radius=kettle_radius, fill=STEEPING_FOREST
    )

    # Kettle lid knob.
    draw.ellipse(rect(0.23, 0.16, 0.33, 0.24), fill=MATCHA_SAGE)

    # Spout: a simple polygon reaching down-right from the body.
    draw.polygon(
        [pt(0.44, 0.30), pt(0.64, 0.40), pt(0.60, 0.46), pt(0.44, 0.40)],
        fill=OOLONG_AMBER,
    )

    # Pour stream from the spout tip down into the cup opening.
    stream_width = max(1, int(0.022 * side * content_scale))
    draw.line(
        [pt(0.62, 0.42), pt(0.70, 0.52), pt(0.74, 0.60)],
        fill=OOLONG_AMBER,
        width=stream_width,
        joint="curve",
    )
    draw.ellipse(rect(0.715, 0.585, 0.765, 0.625), fill=OOLONG_AMBER)

    # Small cup catching the pour, lower right, seated on its own saucer.
    draw.ellipse(rect(0.56, 0.78, 0.94, 0.90), fill=OOLONG_AMBER)
    small_radius = 0.035 * side * content_scale
    draw.rounded_rectangle(
        rect(0.62, 0.60, 0.90, 0.82), radius=small_radius, fill=STEEPING_FOREST
    )
    draw.ellipse(rect(0.64, 0.56, 0.88, 0.64), fill=OOLONG_AMBER)
    small_rim_width = max(1, int(0.008 * side * content_scale))
    draw.ellipse(
        rect(0.64, 0.56, 0.88, 0.64),
        outline=lighten(MATCHA_SAGE, 0.3),
        width=small_rim_width,
    )
    small_handle_width = max(1, int(0.025 * side * content_scale))
    draw.arc(
        rect(0.80, 0.64, 1.00, 0.82),
        start=-100,
        end=100,
        fill=MATCHA_SAGE,
        width=small_handle_width,
    )

    _draw_steam(
        canvas,
        pt,
        side,
        content_scale,
        curls=((0.72, 0.6, 170), (0.80, 2.2, 150)),
        y_top=0.54,
        rise=0.16,
        amplitude=0.03,
    )


def draw_monoline_badge_scene(
    canvas: Image.Image,
    box: BoxI,
    content_scale: float = 0.8,
    line_color: RGBColor = MATCHA_SAGE,
    accent_color: RGBColor = OOLONG_AMBER,
) -> None:
    """Candidate 3: a monoline teacup mark inside a circular badge outline.

    Assumes ``canvas`` was already filled with a dark ground (steeping
    forest); this only draws the light outline mark on top.
    """
    x0, y0, x1, y1 = box
    side = x1 - x0
    pt, rect = _unit_mappers(box, content_scale)
    draw = ImageDraw.Draw(canvas)

    badge_width = max(2, int(0.02 * side * content_scale))
    draw.ellipse(rect(0.04, 0.04, 0.96, 0.96), outline=line_color, width=badge_width)

    line_width = max(2, int(0.028 * side * content_scale))

    # Cup body outline.
    cup_radius = 0.05 * side * content_scale
    draw.rounded_rectangle(
        rect(0.32, 0.46, 0.68, 0.72),
        radius=cup_radius,
        outline=line_color,
        width=line_width,
    )

    # Tea surface: a filled accent ellipse with a matching outline.
    draw.ellipse(rect(0.34, 0.42, 0.66, 0.50), fill=accent_color)
    draw.ellipse(
        rect(0.34, 0.42, 0.66, 0.50), outline=line_color, width=max(1, line_width // 2)
    )

    # Handle, centered on the cup's right edge (ux=0.68) so it reads as one
    # continuous stroke with the cup outline rather than a separate shape.
    draw.arc(
        rect(0.56, 0.50, 0.80, 0.68),
        start=-100,
        end=100,
        fill=line_color,
        width=max(1, line_width - int(0.006 * side * content_scale)),
    )

    # Two thin steam strokes above the tea surface.
    thin_stroke = max(1, line_width // 2)
    steps = 30
    for x_center, phase in ((0.44, 0.0), (0.56, 2.4)):
        points: list[tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            ux = x_center + 0.035 * math.sin(t * 2 * math.pi + phase)
            uy = 0.40 - t * 0.18
            points.append(pt(ux, uy))
        draw.line(points, fill=line_color, width=thin_stroke, joint="curve")


def light_background() -> RGBColor:
    """The light, warm-neutral sage tint used by candidates 1 and 2."""
    return lighten(MATCHA_SAGE, 0.85)


def dark_background() -> RGBColor:
    """The dark steeping-forest ground used by candidate 3."""
    return STEEPING_FOREST


def light_text_on_dark() -> RGBColor:
    """A light tint used for the wordmark against the candidate 3 ground."""
    return lighten(MATCHA_SAGE, 0.85)


def render_square(
    path: Path,
    dimension: int,
    background: RGBColor,
    scene: SceneFn,
    content_scale: float,
) -> None:
    supersize = dimension * SUPERSAMPLE
    canvas = Image.new("RGBA", (supersize, supersize), (*background, 255))
    scene(canvas, (0, 0, supersize, supersize), content_scale)
    final = canvas.convert("RGB").resize(
        (dimension, dimension), Image.Resampling.LANCZOS
    )
    final.save(path, format="PNG")


def render_banner(
    path: Path,
    width: int,
    height: int,
    background: RGBColor,
    scene: SceneFn,
    content_scale: float,
    text_color: RGBColor,
) -> None:
    super_w, super_h = width * SUPERSAMPLE, height * SUPERSAMPLE
    canvas = Image.new("RGBA", (super_w, super_h), (*background, 255))

    margin = int(super_h * 0.08)
    scene_side = super_h - 2 * margin
    scene_box = (margin, margin, margin + scene_side, margin + scene_side)
    scene(canvas, scene_box, content_scale)

    font = find_font(int(super_h * 0.30))
    if font is not None:
        draw = ImageDraw.Draw(canvas)
        text = "TeaMode"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_h = bbox[3] - bbox[1]
        text_x = scene_box[2] + int(super_h * 0.12)
        text_y = (super_h - text_h) / 2 - bbox[1]
        draw.text((text_x, text_y), text, font=font, fill=text_color)

    final = canvas.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
    final.save(path, format="PNG")


# --- Candidate definitions ---------------------------------------------------
#
# Each candidate pairs a background with a scene-drawing function and the
# content_scale/text-color tuning for icon, avatar and banner use.


class Candidate:
    def __init__(
        self,
        candidate_id: int,
        background: RGBColor,
        scene: SceneFn,
        icon_scale: float,
        avatar_scale: float,
        banner_scale: float,
        text_color: RGBColor,
    ) -> None:
        self.candidate_id = candidate_id
        self.background = background
        self.scene = scene
        self.icon_scale = icon_scale
        self.avatar_scale = avatar_scale
        self.banner_scale = banner_scale
        self.text_color = text_color


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        candidate_id=1,
        background=light_background(),
        scene=draw_cup_saucer_scene,
        icon_scale=0.8,
        avatar_scale=0.88,
        banner_scale=0.85,
        text_color=STEEPING_FOREST,
    ),
    Candidate(
        candidate_id=2,
        background=light_background(),
        scene=draw_kettle_pour_scene,
        icon_scale=0.82,
        avatar_scale=0.90,
        banner_scale=0.85,
        text_color=STEEPING_FOREST,
    ),
    Candidate(
        candidate_id=3,
        background=dark_background(),
        scene=draw_monoline_badge_scene,
        icon_scale=0.78,
        avatar_scale=0.86,
        banner_scale=0.8,
        text_color=light_text_on_dark(),
    ),
)


def generate_all(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for candidate in CANDIDATES:
        n = candidate.candidate_id
        render_square(
            out_dir / f"app-icon-{n}.png",
            1024,
            candidate.background,
            candidate.scene,
            candidate.icon_scale,
        )
        render_square(
            out_dir / f"app-avatar-{n}.png",
            1024,
            candidate.background,
            candidate.scene,
            candidate.avatar_scale,
        )
        render_banner(
            out_dir / f"app-banner-{n}.png",
            680,
            240,
            candidate.background,
            candidate.scene,
            candidate.banner_scale,
            candidate.text_color,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="directory to write the nine candidate PNGs into",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generate_all(args.out)


if __name__ == "__main__":
    main()
