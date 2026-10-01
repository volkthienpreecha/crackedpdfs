"""reportlab overlay backend.

Draws a single page overlay with reportlab's canvas and returns it as PDF bytes.
The overlay is later merged onto the source page by the package core. This module
never imports pikepdf and shares no code with the project's primary injector.
"""

from __future__ import annotations

from io import BytesIO

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .techniques import PlacementSpec

FONT_NAME = "Helvetica"


def _draw(c: canvas.Canvas, spec: PlacementSpec) -> None:
    """Draw a single placement onto an open reportlab canvas."""
    c.saveState()
    if spec.clipped:
        # A zero area clip path: the text operators remain in the content
        # stream and stay extractable, but nothing is painted.
        path = c.beginPath()
        path.rect(spec.x, spec.y, 0.0, 0.0)
        c.clipPath(path, stroke=0, fill=0)

    if spec.opacity < 1.0:
        c.setFillAlpha(spec.opacity)
    c.setFillColorRGB(*spec.color)

    text_object = c.beginText(spec.x, spec.y)
    text_object.setFont(FONT_NAME, spec.font_size)
    text_object.setTextRenderMode(spec.render_mode)
    text_object.textOut(spec.text)
    c.drawText(text_object)
    c.restoreState()

    if spec.cover_rect:
        # Paint an opaque white rectangle over the text, leaving the glyphs in
        # the content stream (extractable) but hidden under the cover.
        c.saveState()
        c.setFillAlpha(1.0)
        c.setFillColorRGB(1.0, 1.0, 1.0)
        width = stringWidth(spec.text, FONT_NAME, spec.font_size)
        descent = 0.25 * spec.font_size
        ascent = 0.80 * spec.font_size
        c.rect(
            spec.x - 2.0,
            spec.y - descent - 1.0,
            width + 4.0,
            ascent + descent + 2.0,
            stroke=0,
            fill=1,
        )
        c.restoreState()


def build_overlay(spec: PlacementSpec, page_width: float, page_height: float) -> bytes:
    """Render a one page overlay for a placement and return it as PDF bytes.

    Args:
        spec: The placement specification to realise.
        page_width: Overlay page width in PDF points (matches the source page).
        page_height: Overlay page height in PDF points (matches the source page).

    Returns:
        The overlay PDF encoded as bytes.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    _draw(c, spec)
    c.showPage()
    c.save()
    return buffer.getvalue()
