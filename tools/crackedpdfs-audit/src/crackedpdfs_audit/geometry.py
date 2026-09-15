"""Glyph-level geometry and visibility evidence from a PDF content stream.

Everything here is measured from the file itself with pdfminer.six. Nothing is
read from generator metadata, so the result can be used to check a label
instead of repeating it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from pdfminer.converter import PDFLayoutAnalyzer
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.utils import apply_matrix_pt

EDGE_TOLERANCE = 0.05
TINY_FONT_POINTS = 2.0
LOW_CONTRAST_RATIO = 1.5
INVISIBLE_RENDER_MODES = frozenset({3, 7})

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Glyph:
    text: str
    bbox: Box
    font: str
    size: float
    render_mode: int
    fill_rgb: tuple[float, float, float] | None

    def key(self) -> tuple[str, float, float, str]:
        return (self.text, round(self.bbox[0], 1), round(self.bbox[1], 1), self.font)


@dataclass(frozen=True)
class PageGlyphs:
    page_number: int
    page_box: Box
    glyphs: tuple[Glyph, ...]


def _normalize_box(raw: Iterable[float]) -> Box:
    x0, y0, x1, y1 = (float(value) for value in raw)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _user_space_visible_box(page: PDFPage) -> Box:
    """MediaBox intersected with CropBox in default user space (pre-rotation)."""
    media = _normalize_box(page.mediabox)
    crop = _normalize_box(page.cropbox) if page.cropbox else media
    box = (max(media[0], crop[0]), max(media[1], crop[1]), min(media[2], crop[2]), min(media[3], crop[3]))
    if box[2] <= box[0] or box[3] <= box[1]:
        return media
    return box


def visible_page_box(page: PDFPage, ctm=None) -> Box:
    """The region a viewer can display, in the same coordinate frame as glyphs.

    pdfminer maps glyph coordinates through the page ctm, which folds in
    /Rotate and a nonzero MediaBox origin so the visible page starts at (0, 0)
    and reads upright. The visible box must be transformed by that same ctm, or
    a rotated or shifted page compares glyphs against the wrong rectangle.
    """
    box = _user_space_visible_box(page)
    if ctm is None:
        return box
    corners = [
        apply_matrix_pt(ctm, (box[0], box[1])),
        apply_matrix_pt(ctm, (box[2], box[1])),
        apply_matrix_pt(ctm, (box[2], box[3])),
        apply_matrix_pt(ctm, (box[0], box[3])),
    ]
    xs = [x for x, _ in corners]
    ys = [y for _, y in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _to_rgb(color: object, colorspace_name: str | None) -> tuple[float, float, float] | None:
    if color is None:
        return None
    if isinstance(color, (int, float)):
        gray = float(color)
        return (gray, gray, gray)
    if isinstance(color, (list, tuple)):
        values = [float(value) for value in color if isinstance(value, (int, float))]
        if len(values) == 1:
            return (values[0], values[0], values[0])
        if len(values) == 3:
            return (values[0], values[1], values[2])
        if len(values) == 4:
            c, m, y, k = values
            return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


class _GlyphDevice(PDFLayoutAnalyzer):
    def __init__(self, resource_manager: PDFResourceManager) -> None:
        super().__init__(resource_manager)
        self.glyphs: list[Glyph] = []
        self.page_box: Box | None = None
        self._render_mode = 0

    def begin_page(self, page, ctm):  # type: ignore[override]
        super().begin_page(page, ctm)
        self.page_box = visible_page_box(page, ctm)

    def render_string(self, textstate, seq, ncs, graphicstate):  # type: ignore[override]
        self._render_mode = int(getattr(textstate, "render", 0) or 0)
        return super().render_string(textstate, seq, ncs, graphicstate)

    def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate, *args):  # type: ignore[override]
        advance = super().render_char(matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate, *args)
        item = self.cur_item._objs[-1]
        self.glyphs.append(
            Glyph(
                text=item.get_text(),
                bbox=tuple(float(value) for value in item.bbox),  # type: ignore[arg-type]
                font=str(getattr(font, "basefont", "") or getattr(font, "fontname", "")),
                size=float(item.size),
                render_mode=self._render_mode,
                fill_rgb=_to_rgb(getattr(graphicstate, "ncolor", None), getattr(ncs, "name", None)),
            )
        )
        return advance


def extract_glyphs(pdf_path: str | Path) -> list[PageGlyphs]:
    """Return every glyph pdfminer interprets, including glyphs off the page."""
    pages: list[PageGlyphs] = []
    with open(pdf_path, "rb") as handle:
        for number, page in enumerate(PDFPage.get_pages(handle), start=1):
            manager = PDFResourceManager(caching=True)
            device = _GlyphDevice(manager)
            PDFPageInterpreter(manager, device).process_page(page)
            page_box = device.page_box or visible_page_box(page)
            pages.append(PageGlyphs(number, page_box, tuple(device.glyphs)))
    return pages


def added_glyphs(candidate: PageGlyphs, reference: PageGlyphs | None) -> tuple[Glyph, ...]:
    """Glyphs present in candidate but not reference (multiset difference)."""
    if reference is None:
        return candidate.glyphs
    remaining = Counter(glyph.key() for glyph in reference.glyphs)
    extra: list[Glyph] = []
    for glyph in candidate.glyphs:
        key = glyph.key()
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            extra.append(glyph)
    return tuple(extra)


def placement_class(bbox: Box, page_box: Box) -> str:
    gx0, gy0, gx1, gy1 = bbox
    px0, py0, px1, py1 = page_box
    tol = EDGE_TOLERANCE
    if gx0 >= px0 - tol and gy0 >= py0 - tol and gx1 <= px1 + tol and gy1 <= py1 + tol:
        return "inside"
    if gx1 <= px0 + tol or gx0 >= px1 - tol or gy1 <= py0 + tol or gy0 >= py1 - tol:
        return "outside"
    return "clipped"


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        value = min(1.0, max(0.0, value))
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_against_white(rgb: tuple[float, float, float] | None) -> float | None:
    """WCAG contrast ratio of the fill color against a white page."""
    if rgb is None:
        return None
    return 1.05 / (_relative_luminance(rgb) + 0.05)


def visibility_reasons(glyph: Glyph, page_box: Box) -> list[str]:
    """Why a glyph would not be seen by a reader. Empty means likely visible."""
    reasons: list[str] = []
    placement = placement_class(glyph.bbox, page_box)
    if placement == "outside":
        reasons.append("off_page")
    elif placement == "clipped":
        reasons.append("clipped_by_page_edge")
    if glyph.render_mode in INVISIBLE_RENDER_MODES:
        reasons.append("invisible_render_mode")
    if glyph.size < TINY_FONT_POINTS:
        reasons.append("tiny_font")
    contrast = contrast_against_white(glyph.fill_rgb)
    if contrast is not None and contrast < LOW_CONTRAST_RATIO and glyph.render_mode in {0, 2, 4, 6}:
        reasons.append("low_contrast_fill")
    return reasons


@dataclass
class GlyphSetSummary:
    glyphs: int
    inside: int
    clipped: int
    outside: int
    below_page: int
    above_page: int
    left_of_page: int
    right_of_page: int
    invisible_render_mode: int
    tiny_font: int
    low_contrast_fill: int
    likely_visible: int
    realized_spatial_class: str
    bbox: Box | None
    text_preview: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def summarize_glyphs(glyphs: Iterable[Glyph], page_box: Box, preview_chars: int = 120) -> GlyphSetSummary:
    counts: Counter[str] = Counter()
    bbox: Box | None = None
    text: list[str] = []
    total = 0
    for glyph in glyphs:
        total += 1
        placement = placement_class(glyph.bbox, page_box)
        counts[placement] += 1
        if placement == "outside":
            gx0, gy0, gx1, gy1 = glyph.bbox
            if gy1 <= page_box[1] + EDGE_TOLERANCE:
                counts["below_page"] += 1
            elif gy0 >= page_box[3] - EDGE_TOLERANCE:
                counts["above_page"] += 1
            elif gx1 <= page_box[0] + EDGE_TOLERANCE:
                counts["left_of_page"] += 1
            else:
                counts["right_of_page"] += 1
        reasons = visibility_reasons(glyph, page_box)
        for reason in ("invisible_render_mode", "tiny_font", "low_contrast_fill"):
            if reason in reasons:
                counts[reason] += 1
        if not reasons:
            counts["likely_visible"] += 1
        bbox = (
            glyph.bbox
            if bbox is None
            else (
                min(bbox[0], glyph.bbox[0]),
                min(bbox[1], glyph.bbox[1]),
                max(bbox[2], glyph.bbox[2]),
                max(bbox[3], glyph.bbox[3]),
            )
        )
        if len(text) < preview_chars:
            text.append(glyph.text)

    if total == 0:
        realized = "empty"
    elif counts["inside"] == total:
        realized = "inside_page"
    elif counts["outside"] == total:
        realized = "off_page"
    else:
        realized = "straddles_page_edge"

    return GlyphSetSummary(
        glyphs=total,
        inside=counts["inside"],
        clipped=counts["clipped"],
        outside=counts["outside"],
        below_page=counts["below_page"],
        above_page=counts["above_page"],
        left_of_page=counts["left_of_page"],
        right_of_page=counts["right_of_page"],
        invisible_render_mode=counts["invisible_render_mode"],
        tiny_font=counts["tiny_font"],
        low_contrast_fill=counts["low_contrast_fill"],
        likely_visible=counts["likely_visible"],
        realized_spatial_class=realized,
        bbox=tuple(round(value, 3) for value in bbox) if bbox else None,  # type: ignore[arg-type]
        text_preview="".join(text),
    )
