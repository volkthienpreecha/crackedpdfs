"""crackedpdfs-altinjector.

A second, independent implementation of hidden-text injection into existing PDFs,
built for cross-generator evaluation: detectors trained on the project's primary
injector are tested against the distinct artefacts this package produces. It uses
pypdf and reportlab (and optionally Playwright's Chromium) and shares no code with
the primary injector.
"""

from __future__ import annotations

import random
from importlib import metadata
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from . import chromium_backend, reportlab_backend, verify
from .techniques import BACKEND_SUPPORT, STRENGTHS, TECHNIQUES, VISIBILITY, PlacementSpec, make_spec

__all__ = [
    "BACKEND_SUPPORT",
    "STRENGTHS",
    "TECHNIQUES",
    "VISIBILITY",
    "PlacementSpec",
    "InjectionError",
    "inject",
    "library_versions",
    "make_spec",
    "page_size",
]

__version__ = "0.1.0"

BACKENDS = ("reportlab", "chromium")

_VERSION_PACKAGES = (
    "pypdf",
    "reportlab",
    "pdfminer.six",
    "pypdfium2",
    "numpy",
    "playwright",
)


class InjectionError(RuntimeError):
    """Raised when an injection cannot be produced or fails verification."""


def library_versions() -> dict[str, str]:
    """Return installed versions of the libraries that shape the output."""
    versions: dict[str, str] = {}
    for name in _VERSION_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def page_size(pdf_path: str | Path) -> tuple[float, float]:
    """Return the ``(width, height)`` of page one in PDF points."""
    reader = PdfReader(str(pdf_path))
    media_box = reader.pages[0].mediabox
    return float(media_box.width), float(media_box.height)


def _merge_overlay(source_path: str | Path, overlay_bytes: bytes, out_path: str | Path) -> None:
    """Merge a one page overlay onto page one of the source and write the result."""
    reader = PdfReader(str(source_path))
    overlay_reader = PdfReader(BytesIO(overlay_bytes))
    writer = PdfWriter()

    base_page = reader.pages[0]
    base_page.merge_page(overlay_reader.pages[0])
    writer.add_page(base_page)
    for page in reader.pages[1:]:
        writer.add_page(page)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        writer.write(handle)


def _expectation(technique: str) -> str | None:
    """Return the geometric expectation to verify for a technique."""
    if technique == "off_page":
        return "outside"
    if technique == "visible":
        return "inside"
    return None


def _build_record(
    *,
    source_path: str | Path,
    out_path: str | Path,
    spec: PlacementSpec,
    backend: str,
    seed: int | None,
    page_box: tuple[float, float, float, float],
    bbox: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    """Assemble the JSON record describing a realised injection."""
    return {
        "in": str(source_path),
        "out": str(out_path),
        "text": spec.text,
        "technique": spec.technique,
        "strength": spec.strength,
        "backend": backend,
        "seed": seed,
        "page_box": [page_box[0], page_box[1], page_box[2], page_box[3]],
        "text_bbox": list(bbox) if bbox is not None else None,
        "font_size": spec.font_size,
        "color": list(spec.color),
        "render_mode": spec.render_mode,
        "opacity": spec.opacity,
        "visibility": VISIBILITY[spec.technique],
        "library_versions": library_versions(),
        "verified": True,
    }


def inject(
    source_path: str | Path,
    out_path: str | Path,
    text: str,
    technique: str,
    strength: str = "medium",
    backend: str = "reportlab",
    seed: int | None = None,
) -> dict[str, Any]:
    """Inject hidden text into a PDF and verify the result.

    Args:
        source_path: Path to the source PDF.
        out_path: Path for the injected output PDF.
        text: The payload string to inject.
        technique: One of :data:`crackedpdfs_altinjector.techniques.TECHNIQUES`.
        strength: One of ``weak``, ``medium``, or ``strong``.
        backend: ``reportlab`` or ``chromium``.
        seed: Optional seed for reproducible placement jitter.

    Returns:
        The JSON record describing the realised placement.

    Raises:
        InjectionError: If inputs are invalid or verification fails.
    """
    if backend not in BACKENDS:
        raise InjectionError(f"Unknown backend: {backend}")
    if technique not in TECHNIQUES:
        raise InjectionError(f"Unknown technique: {technique}")
    if strength not in STRENGTHS:
        raise InjectionError(f"Unknown strength: {strength}")
    if technique not in BACKEND_SUPPORT[backend]:
        raise InjectionError(f"Backend '{backend}' does not support technique '{technique}'.")

    width, height = page_size(source_path)
    rng = random.Random(seed)
    spec = make_spec(technique, text, width, height, strength, rng=rng)

    if backend == "reportlab":
        overlay_bytes = reportlab_backend.build_overlay(spec, width, height)
    else:
        try:
            overlay_bytes = chromium_backend.build_overlay(spec, width, height)
        except RuntimeError as exc:
            raise InjectionError(str(exc)) from exc

    _merge_overlay(source_path, overlay_bytes, out_path)

    page_box = (0.0, 0.0, width, height)
    overlay_glyphs = verify.extract_glyphs(overlay_bytes)
    expectation = _expectation(technique)
    if not verify.verify_geometry(overlay_glyphs, page_box, expectation):
        raise InjectionError(f"Geometry check failed for technique '{technique}' (expected {expectation}).")

    output_glyphs = verify.extract_glyphs(out_path)
    if not verify.verify_extractable(text, output_glyphs):
        raise InjectionError(f"Injected text is not extractable from the output for technique '{technique}'.")

    bbox = verify.text_bbox(overlay_glyphs)
    return _build_record(
        source_path=source_path,
        out_path=out_path,
        spec=spec,
        backend=backend,
        seed=seed,
        page_box=page_box,
        bbox=bbox,
    )
