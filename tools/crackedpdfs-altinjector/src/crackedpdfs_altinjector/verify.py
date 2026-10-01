"""Verification helpers.

After an overlay is merged onto a source page, the output is re-opened with
pdfminer.six to confirm the injected text is extractable and that its glyph
geometry matches what the technique promised.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar, LTContainer

Glyph = tuple[str, tuple[float, float, float, float]]

# Tolerance in points when deciding whether a glyph lies inside or outside a box.
EDGE_TOLERANCE = 1.0


class VerificationError(RuntimeError):
    """Raised when an injected output fails a verification check."""


def _iter_chars(container: object):
    """Yield every :class:`LTChar` nested anywhere inside a layout container."""
    if isinstance(container, LTChar):
        yield container
        return
    if isinstance(container, LTContainer):
        for child in container:
            yield from _iter_chars(child)


def extract_glyphs(source: bytes | str | Path, page_index: int = 0) -> list[Glyph]:
    """Extract characters and their bounding boxes from one page.

    Args:
        source: A PDF path or in memory PDF bytes.
        page_index: The zero based page index to read.

    Returns:
        A list of ``(character, (x0, y0, x1, y1))`` tuples in PDF points.
    """
    stream = BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    glyphs: list[Glyph] = []
    for index, page_layout in enumerate(extract_pages(stream)):
        if index != page_index:
            continue
        for char in _iter_chars(page_layout):
            glyphs.append((char.get_text(), (char.x0, char.y0, char.x1, char.y1)))
        break
    return glyphs


def _normalise(text: str) -> str:
    """Collapse all whitespace so spacing differences do not defeat matching."""
    return "".join(text.split())


def verify_extractable(text: str, glyphs: list[Glyph]) -> bool:
    """Return whether the payload is recoverable from extracted glyphs.

    Whitespace is ignored on both sides because extraction can reorder or drop
    spaces while preserving the visible characters.
    """
    target = _normalise(text)
    if not target:
        return True
    recovered = _normalise("".join(glyph[0] for glyph in glyphs))
    return target in recovered


def _is_inside(box: tuple[float, float, float, float], page_box: tuple[float, float, float, float]) -> bool:
    """Return whether a glyph box lies fully within the page box."""
    px0, py0, px1, py1 = page_box
    x0, y0, x1, y1 = box
    return (
        x0 >= px0 - EDGE_TOLERANCE
        and y0 >= py0 - EDGE_TOLERANCE
        and x1 <= px1 + EDGE_TOLERANCE
        and y1 <= py1 + EDGE_TOLERANCE
    )


def _is_outside(box: tuple[float, float, float, float], page_box: tuple[float, float, float, float]) -> bool:
    """Return whether a glyph box lies fully outside the page box."""
    px0, py0, px1, py1 = page_box
    x0, y0, x1, y1 = box
    return (
        x1 <= px0 + EDGE_TOLERANCE
        or x0 >= px1 - EDGE_TOLERANCE
        or y1 <= py0 + EDGE_TOLERANCE
        or y0 >= py1 - EDGE_TOLERANCE
    )


def verify_geometry(
    glyphs: list[Glyph],
    page_box: tuple[float, float, float, float],
    expect: str | None,
) -> bool:
    """Check that every injected glyph satisfies a geometric expectation.

    Args:
        glyphs: Extracted glyphs for the injected overlay.
        page_box: The page box as ``(x0, y0, x1, y1)`` in PDF points.
        expect: ``"inside"``, ``"outside"``, or ``None`` for no constraint.

    Returns:
        ``True`` if the expectation holds (and at least one glyph exists when a
        constraint is requested), otherwise ``False``.
    """
    if expect is None:
        return True
    if not glyphs:
        return False
    if expect == "inside":
        return all(_is_inside(box, page_box) for _, box in glyphs)
    if expect == "outside":
        return all(_is_outside(box, page_box) for _, box in glyphs)
    raise ValueError(f"Unknown expectation: {expect}")


def text_bbox(glyphs: list[Glyph]) -> tuple[float, float, float, float] | None:
    """Return the union bounding box of all glyphs, or ``None`` when empty."""
    if not glyphs:
        return None
    x0 = min(box[0] for _, box in glyphs)
    y0 = min(box[1] for _, box in glyphs)
    x1 = max(box[2] for _, box in glyphs)
    y1 = max(box[3] for _, box in glyphs)
    return (x0, y0, x1, y1)
