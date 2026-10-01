"""Shared pytest fixtures: a one page source PDF and a rasteriser."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# The injector places inside-page text in the upper body of the page. Keep the
# fixture's own content in the lower half so the injection region is white and
# pixel-invisibility checks are meaningful.
PAGE_WIDTH, PAGE_HEIGHT = letter


@pytest.fixture
def source_pdf(tmp_path: Path) -> Path:
    """Create a plain one page PDF whose upper body is blank white."""
    path = tmp_path / "source.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFillColorRGB(0.0, 0.0, 0.0)
    c.setFont("Helvetica", 12)
    c.drawString(72, 200, "CrackedPDFs alt-injector test fixture.")
    c.drawString(72, 180, "This body text sits in the lower half of the page.")
    c.showPage()
    c.save()
    return path


def render_page(pdf_path: str | Path, dpi: int = 72) -> np.ndarray:
    """Rasterise page one to an RGB numpy array at the requested DPI."""
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[0]
        bitmap = page.render(scale=dpi / 72.0)
        image = bitmap.to_numpy()
    finally:
        document.close()
    if image.ndim == 3 and image.shape[2] == 4:
        image = image[:, :, :3]
    return np.ascontiguousarray(image)


def changed_fraction(before: np.ndarray, after: np.ndarray) -> float:
    """Return the fraction of pixels that differ between two equal sized rasters."""
    if before.shape != after.shape:
        raise AssertionError(f"raster shape mismatch: {before.shape} vs {after.shape}")
    differing = np.any(before != after, axis=-1)
    return float(np.count_nonzero(differing)) / float(differing.size)
