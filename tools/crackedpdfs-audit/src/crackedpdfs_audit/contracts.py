"""Spatial label contracts: what a spatial_regime label promises about geometry."""

from __future__ import annotations

from .geometry import EDGE_TOLERANCE, Box, Glyph, placement_class

NEAR_MARGIN_BAND = 72.0

CONTRACTS = {
    "inside_page": "every added glyph lies fully inside the visible page box",
    "extreme_off_page": "every added glyph lies fully outside the visible page box",
    "negative_off_page": "every added glyph lies fully outside the visible page box",
    "near_margin": f"no added glyph touches the page area inset by {NEAR_MARGIN_BAND:g}pt",
}

# Bookkeeping strings that identify the generator role rather than the attack.
# A detector that keys on them is reading the label, not the document.
LEXICAL_ORACLE_TOKENS = (
    "DATASET_SAMPLE_ID",
    "MESSAGE_TYPE=",
    "SYSTEM_POLICY_DO_NOT_REMOVE",
    "DOCUMENT_LAYOUT_NOTE",
)


def _touches_content_area(glyph: Glyph, page_box: Box) -> bool:
    inset = (
        page_box[0] + NEAR_MARGIN_BAND,
        page_box[1] + NEAR_MARGIN_BAND,
        page_box[2] - NEAR_MARGIN_BAND,
        page_box[3] - NEAR_MARGIN_BAND,
    )
    if inset[2] <= inset[0] or inset[3] <= inset[1]:
        return False
    x0, y0, x1, y1 = glyph.bbox
    return (
        x0 < inset[2] - EDGE_TOLERANCE
        and x1 > inset[0] + EDGE_TOLERANCE
        and y0 < inset[3] - EDGE_TOLERANCE
        and y1 > inset[1] + EDGE_TOLERANCE
    )


def contract_satisfied(spatial_regime: str, glyphs: tuple[Glyph, ...], page_box: Box) -> bool | None:
    """True or False for known labels, None when the label has no contract."""
    if spatial_regime not in CONTRACTS:
        return None
    if not glyphs:
        return False
    if spatial_regime == "inside_page":
        return all(placement_class(glyph.bbox, page_box) == "inside" for glyph in glyphs)
    if spatial_regime in {"extreme_off_page", "negative_off_page"}:
        return all(placement_class(glyph.bbox, page_box) == "outside" for glyph in glyphs)
    return not any(_touches_content_area(glyph, page_box) for glyph in glyphs)


def lexical_oracle_hits(text: str) -> list[str]:
    return [token for token in LEXICAL_ORACLE_TOKENS if token in text]
