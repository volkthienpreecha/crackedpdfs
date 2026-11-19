"""Hiding techniques and their placement specifications.

Each technique maps a text payload and a page geometry to a :class:`PlacementSpec`,
a backend independent description of where and how the text should be drawn. The
backends consume the same spec, so a technique is defined once and realised by
either the reportlab or the chromium renderer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

STRENGTHS = ("weak", "medium", "strong")

TECHNIQUES = (
    "white_text",
    "low_contrast",
    "tiny_font",
    "off_page",
    "render_mode_invisible",
    "zero_opacity",
    "clipped",
    "behind_image",
    "visible",
)

# Which backend can faithfully realise each technique. The chromium backend
# rasterises an HTML overlay through a print pipeline that clips anything outside
# the page box and drops geometry that is never painted. Techniques that rely on
# off page placement, zero area clipping, or an opaque cover rectangle cannot be
# reproduced there while keeping the text extractable. A fully transparent fill
# (``opacity: 0``) is also dropped from the printed PDF, so the zero_opacity
# technique is reportlab only; its chromium analogue would be a transparent
# colour, which is already covered by render_mode_invisible.
BACKEND_SUPPORT: dict[str, set[str]] = {
    "reportlab": set(TECHNIQUES),
    "chromium": {
        "white_text",
        "low_contrast",
        "tiny_font",
        "render_mode_invisible",
        "visible",
    },
}

# Expected visual salience of each technique when rendered over a white page.
# "invisible" techniques must not perceptibly change the rasterised page,
# "low" techniques leave a faint but real mark, and "visible" is the control.
VISIBILITY: dict[str, str] = {
    "white_text": "invisible",
    "low_contrast": "low",
    "tiny_font": "invisible",
    "off_page": "invisible",
    "render_mode_invisible": "invisible",
    "zero_opacity": "invisible",
    "clipped": "invisible",
    "behind_image": "invisible",
    "visible": "visible",
}

# Low contrast grey level per strength: lighter (closer to white) is weaker.
_LOW_CONTRAST_GREY = {"weak": 0.97, "medium": 0.93, "strong": 0.90}

# Font size in points per strength for the tiny_font technique.
_TINY_FONT_SIZE = {"weak": 2.0, "medium": 1.0, "strong": 0.5}

# How far beyond the page edge off_page text is pushed, in points, per strength.
_OFF_PAGE_DISTANCE = {"weak": 20.0, "medium": 120.0, "strong": 320.0}

_DEFAULT_FONT_SIZE = 10.0


@dataclass(frozen=True)
class PlacementSpec:
    """A backend independent description of a single text placement.

    Attributes:
        text: The payload string to draw.
        x: Left/baseline x coordinate in PDF points (origin at the lower left).
        y: Baseline y coordinate in PDF points (origin at the lower left).
        font_size: Font size in points.
        color: Fill colour as an RGB triple with channels in ``[0, 1]``.
        render_mode: PDF text render mode (0 for fill, 3 for invisible).
        opacity: Fill alpha in ``[0, 1]``.
        clipped: Whether the text is drawn inside a zero area clip path.
        cover_rect: Whether an opaque white rectangle is painted over the text.
        technique: The technique name that produced this spec.
        strength: The requested strength level.
    """

    text: str
    x: float
    y: float
    font_size: float
    color: tuple[float, float, float]
    render_mode: int
    opacity: float
    clipped: bool
    cover_rect: bool
    technique: str
    strength: str


def _font_size(technique: str, strength: str) -> float:
    """Return the font size in points for a technique and strength."""
    if technique == "tiny_font":
        return _TINY_FONT_SIZE[strength]
    return _DEFAULT_FONT_SIZE


def _color(technique: str, strength: str) -> tuple[float, float, float]:
    """Return the fill colour as an RGB triple for a technique and strength."""
    if technique == "white_text":
        return (1.0, 1.0, 1.0)
    if technique == "low_contrast":
        grey = _LOW_CONTRAST_GREY[strength]
        return (grey, grey, grey)
    return (0.0, 0.0, 0.0)


def make_spec(
    technique: str,
    text: str,
    page_width: float,
    page_height: float,
    strength: str,
    rng: random.Random | None = None,
) -> PlacementSpec:
    """Build a :class:`PlacementSpec` for a technique over a given page.

    Args:
        technique: One of :data:`TECHNIQUES`.
        text: The payload string.
        page_width: Page width in PDF points.
        page_height: Page height in PDF points.
        strength: One of :data:`STRENGTHS`.
        rng: Optional seeded random source for reproducible placement jitter.

    Returns:
        A fully resolved placement specification.

    Raises:
        ValueError: If the technique or strength is unknown.
    """
    if technique not in TECHNIQUES:
        raise ValueError(f"Unknown technique: {technique}")
    if strength not in STRENGTHS:
        raise ValueError(f"Unknown strength: {strength}")

    rng = rng or random.Random()
    size = _font_size(technique, strength)
    color = _color(technique, strength)
    render_mode = 3 if technique == "render_mode_invisible" else 0
    opacity = 0.0 if technique == "zero_opacity" else 1.0
    clipped = technique == "clipped"
    cover_rect = technique == "behind_image"

    if technique == "off_page":
        distance = _OFF_PAGE_DISTANCE[strength]
        x = page_width + distance + rng.uniform(0.0, 10.0)
        y = page_height - 72.0 + rng.uniform(-10.0, 10.0)
    else:
        # Keep inside placements in the upper body of the page, well away from
        # the margins, so the realised glyphs stay within the page box.
        x = rng.uniform(50.0, 120.0)
        y = page_height - rng.uniform(60.0, 120.0)

    return PlacementSpec(
        text=text,
        x=x,
        y=y,
        font_size=size,
        color=color,
        render_mode=render_mode,
        opacity=opacity,
        clipped=clipped,
        cover_rect=cover_rect,
        technique=technique,
        strength=strength,
    )
