"""Pixel evidence: what a reader actually sees, and what lies beyond the page."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pikepdf
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

from .geometry import Box, Glyph, placement_class, visibility_reasons

PIXEL_DELTA_THRESHOLD = 32

PALETTE = {
    "canvas": (244, 239, 230),
    "hatch": (230, 222, 208),
    "page_edge": (24, 24, 27),
    "off_page": (228, 87, 46),
    "clipped_by_page_edge": (243, 167, 18),
    "invisible_render_mode": (123, 97, 255),
    "tiny_font": (41, 161, 156),
    "low_contrast_fill": (141, 153, 174),
    "likely_visible": (17, 17, 17),
    "ink": (39, 39, 42),
}


def render_page(pdf: str | Path | bytes, page_index: int = 0, dpi: float = 72.0) -> Image.Image:
    document = pdfium.PdfDocument(pdf)
    try:
        page = document[page_index]
        image = page.render(scale=dpi / 72.0).to_pil().convert("RGB")
        page.close()
        return image
    finally:
        document.close()


def page_count(pdf: str | Path | bytes) -> int:
    document = pdfium.PdfDocument(pdf)
    try:
        return len(document)
    finally:
        document.close()


@dataclass
class PixelDiff:
    """Rendered difference across the whole document, page by page.

    changed_pixels is the document total. changed_pixels_by_page keeps the
    per-page counts, and the mismatch fields say where a comparison could not
    be made rather than silently reporting zero.
    """

    changed_pixels: int
    total_pixels: int
    dpi: float
    changed_pixels_by_page: list[int]
    compared_pages: int
    candidate_pages: int
    reference_pages: int
    dimension_mismatch_pages: list[int]

    @property
    def changed_fraction(self) -> float:
        return self.changed_pixels / self.total_pixels if self.total_pixels else 0.0

    @property
    def page_count_mismatch(self) -> bool:
        return self.candidate_pages != self.reference_pages


def pixel_diff(candidate: str | Path, reference: str | Path, dpi: float = 72.0) -> PixelDiff | None:
    """Count pixels that differ visibly between two renders, over every page."""
    candidate_pages = page_count(candidate)
    reference_pages = page_count(reference)
    per_page: list[int] = []
    dimension_mismatch: list[int] = []
    total_pixels = 0
    for index in range(min(candidate_pages, reference_pages)):
        left = np.asarray(render_page(candidate, page_index=index, dpi=dpi), dtype=np.int16)
        right = np.asarray(render_page(reference, page_index=index, dpi=dpi), dtype=np.int16)
        if left.shape != right.shape:
            dimension_mismatch.append(index + 1)
            per_page.append(0)
            continue
        per_page.append(int((np.abs(left - right).max(axis=2) > PIXEL_DELTA_THRESHOLD).sum()))
        total_pixels += int(left.shape[0] * left.shape[1])
    if not per_page and not dimension_mismatch:
        return None
    return PixelDiff(
        changed_pixels=sum(per_page),
        total_pixels=total_pixels,
        dpi=dpi,
        changed_pixels_by_page=per_page,
        compared_pages=len(per_page),
        candidate_pages=candidate_pages,
        reference_pages=reference_pages,
        dimension_mismatch_pages=dimension_mismatch,
    )


def _glyph_color(glyph: Glyph, page_box: Box) -> tuple[int, int, int]:
    reasons = visibility_reasons(glyph, page_box)
    for reason in (
        "invisible_render_mode",
        "off_page",
        "clipped_by_page_edge",
        "tiny_font",
        "low_contrast_fill",
    ):
        if reason in reasons:
            return PALETTE[reason]
    return PALETTE["likely_visible"]


def reveal(
    pdf_path: str | Path,
    glyphs: tuple[Glyph, ...],
    page_box: Box,
    output_png: str | Path,
    max_side_px: int = 1600,
    max_expansion_pages: float = 1.5,
    title: str | None = None,
) -> Path:
    """Render the page on an expanded canvas so off-page text becomes visible.

    The MediaBox and CropBox are widened to cover the flagged glyphs (bounded to
    max_expansion_pages page sizes in each direction), then every flagged glyph
    box is outlined in the colour of its strongest hiding mechanism.
    """
    width = page_box[2] - page_box[0]
    height = page_box[3] - page_box[1]
    limit = (
        page_box[0] - max_expansion_pages * width,
        page_box[1] - max_expansion_pages * height,
        page_box[2] + max_expansion_pages * width,
        page_box[3] + max_expansion_pages * height,
    )
    canvas_box = list(page_box)
    beyond = 0
    for glyph in glyphs:
        x0, y0, x1, y1 = glyph.bbox
        if x1 < limit[0] or x0 > limit[2] or y1 < limit[1] or y0 > limit[3]:
            beyond += 1
            continue
        canvas_box = [
            min(canvas_box[0], x0),
            min(canvas_box[1], y0),
            max(canvas_box[2], x1),
            max(canvas_box[3], y1),
        ]
    pad = 0.04 * max(width, height)
    canvas_box = [canvas_box[0] - pad, canvas_box[1] - pad, canvas_box[2] + pad, canvas_box[3] + pad]

    with pikepdf.open(pdf_path) as pdf:
        page = pdf.pages[0]
        page.MediaBox = pikepdf.Array(canvas_box)
        page.CropBox = pikepdf.Array(canvas_box)
        buffer = io.BytesIO()
        pdf.save(buffer)

    canvas_width = canvas_box[2] - canvas_box[0]
    canvas_height = canvas_box[3] - canvas_box[1]
    scale = max_side_px / max(canvas_width, canvas_height)
    image = render_page(buffer.getvalue(), dpi=72.0 * scale)

    def to_px(x: float, y: float) -> tuple[float, float]:
        return ((x - canvas_box[0]) * scale, (canvas_box[3] - y) * scale)

    # Tint everything outside the real page so the page edge reads at a glance.
    mask = Image.new("L", image.size, 255)
    draw_mask = ImageDraw.Draw(mask)
    px0, py1 = to_px(page_box[0], page_box[1])
    px1, py0 = to_px(page_box[2], page_box[3])
    draw_mask.rectangle([px0, py0, px1, py1], fill=0)
    tint = Image.new("RGB", image.size, PALETTE["canvas"])
    hatch = ImageDraw.Draw(tint)
    step = max(8, int(14 * scale))
    for offset in range(-image.size[1], image.size[0], step):
        hatch.line([(offset, 0), (offset + image.size[1], image.size[1])], fill=PALETTE["hatch"], width=1)
    image = Image.composite(Image.blend(image, tint, 0.55), image, mask)

    draw = ImageDraw.Draw(image)
    for glyph in glyphs:
        gx0, gy1 = to_px(glyph.bbox[0], glyph.bbox[1])
        gx1, gy0 = to_px(glyph.bbox[2], glyph.bbox[3])
        draw.rectangle(
            [gx0, gy0, max(gx1, gx0 + 1), max(gy1, gy0 + 1)], outline=_glyph_color(glyph, page_box), width=1
        )
    draw.rectangle([px0, py0, px1, py1], outline=PALETTE["page_edge"], width=max(2, int(2 * scale)))

    counts: dict[str, int] = {}
    for glyph in glyphs:
        reasons = visibility_reasons(glyph, page_box) or ["likely_visible"]
        counts[reasons[0]] = counts.get(reasons[0], 0) + 1
        if placement_class(glyph.bbox, page_box) == "outside" and reasons[0] != "off_page":
            counts["off_page"] = counts.get("off_page", 0) + 1

    legend_height = 76
    framed = Image.new("RGB", (image.size[0], image.size[1] + legend_height), (250, 248, 244))
    framed.paste(image, (0, 0))
    draw = ImageDraw.Draw(framed)
    try:
        font = ImageFont.load_default(size=18)
        small = ImageFont.load_default(size=15)
    except TypeError:  # Pillow < 10.1
        font = small = ImageFont.load_default()
    top = image.size[1] + 12
    draw.text((16, top), title or Path(pdf_path).name, fill=PALETTE["ink"], font=font)
    x = 16
    for key in (
        "off_page",
        "clipped_by_page_edge",
        "invisible_render_mode",
        "tiny_font",
        "low_contrast_fill",
        "likely_visible",
    ):
        if key not in counts:
            continue
        draw.rectangle([x, top + 32, x + 14, top + 46], fill=PALETTE[key])
        label = f"{key.replace('_', ' ')} {counts[key]:,}"
        draw.text((x + 20, top + 30), label, fill=PALETTE["ink"], font=small)
        x += 34 + int(draw.textlength(label, font=small))
    if beyond:
        draw.text(
            (x, top + 30), f"+{beyond:,} glyphs beyond the drawn canvas", fill=PALETTE["off_page"], font=small
        )

    output = Path(output_png)
    output.parent.mkdir(parents=True, exist_ok=True)
    framed.save(output)
    return output
