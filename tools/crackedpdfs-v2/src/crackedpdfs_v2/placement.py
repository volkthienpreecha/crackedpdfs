"""Find blank page area for flowed in-page payloads.

The primary injector flows an in-page payload from an anchor to the right
margin of the page. On a synthetic base page the default anchor sits in empty
space, but on a real document it often lands on body text, figures, or shaded
boxes. White or low-contrast text drawn there leaves render traces, so the
"hidden" member is not hidden. This module ranks candidate anchors by how much
ink a rendered page has under the box the payload will occupy, so the builder
can pass a blank one to the injector's ``anchor`` key.

Everything here works on a grayscale render of the page (0 = black, 255 =
white) so it stays independent of the renderer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Helvetica metrics used by the injector's flow layout.
HELVETICA_ASCENT = 0.718
HELVETICA_DESCENT = 0.207
HELVETICA_MEAN_ADVANCE = 0.53  # mean advance width of English text, in em
LEADING = 1.2
PAGE_SAFE_MARGIN = 18.0  # matches the injector's margin cap, in points
MIN_WIDTH_FRACTION = 0.45  # the injector never narrows the box below this


@dataclass(frozen=True)
class Anchor:
    x: float  # fraction of the visible page width
    y: float  # fraction of the visible page height, from the bottom (first baseline)
    ink: int  # inked pixels under the estimated payload box


def estimate_lines(text_length: int, font_size: float, box_width: float) -> int:
    """Lines the flow layout needs, with one line of slack for word wrapping."""
    text_width = text_length * HELVETICA_MEAN_ADVANCE * font_size
    return max(1, math.ceil(text_width / max(box_width, 1.0))) + 1


def blank_anchors(
    gray: np.ndarray,
    page_size: tuple[float, float],
    text_length: int,
    font_size: float,
    *,
    threshold: int = 245,
    pad: float = 2.0,
    steps: int = 24,
    limit: int = 5,
) -> list[Anchor]:
    """Candidate anchors ordered from least to most ink under the payload box.

    ``gray`` is the rendered visible page box; ``page_size`` is its width and
    height in points. The box runs from the anchor to the right margin and
    down by the estimated number of lines, padded by ``pad`` points.
    """
    height_px, width_px = gray.shape
    width_pt, height_pt = page_size
    sx, sy = width_px / width_pt, height_px / height_pt
    ink = np.pad((gray < threshold).astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def ink_in(x0: float, top: float, x1: float, bottom: float) -> int:
        # Points to pixel indices; ``top`` and ``bottom`` are measured from the page top.
        c0, c1 = max(0, int(x0 * sx)), min(width_px, math.ceil(x1 * sx))
        r0, r1 = max(0, int(top * sy)), min(height_px, math.ceil(bottom * sy))
        if c1 <= c0 or r1 <= r0:
            return 0
        return int(ink[r1, c1] - ink[r0, c1] - ink[r1, c0] + ink[r0, c0])

    margin = min(PAGE_SAFE_MARGIN, 0.05 * min(width_pt, height_pt))
    right = width_pt - margin
    max_x = right - MIN_WIDTH_FRACTION * width_pt
    leading = LEADING * font_size
    candidates = []
    for i in range(steps):
        x = margin + (max_x - margin) * i / max(steps - 1, 1)
        lines = estimate_lines(text_length, font_size, right - x)
        block = HELVETICA_ASCENT * font_size + leading * (lines - 1) + HELVETICA_DESCENT * font_size
        for j in range(steps):
            # First baseline, from the page bottom; the whole block must fit.
            low = margin + block - HELVETICA_ASCENT * font_size
            high = height_pt - margin - HELVETICA_ASCENT * font_size
            if high < low:
                continue
            baseline = low + (high - low) * j / max(steps - 1, 1)
            top = height_pt - (baseline + HELVETICA_ASCENT * font_size) - pad
            bottom = top + block + 2 * pad
            candidates.append(Anchor(x / width_pt, baseline / height_pt, ink_in(x - pad, top, right + pad, bottom)))
    candidates.sort(key=lambda a: (a.ink, -a.y, a.x))
    return candidates[:limit]
