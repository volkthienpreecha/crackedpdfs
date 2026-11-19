"""Chromium overlay backend.

Renders an HTML overlay with Playwright's Chromium to a single page PDF whose
page size matches the source, then returns it as PDF bytes for merging. The CSS
equivalents of the PDF hiding techniques are used: transparent colour for an
invisible render mode and ``opacity: 0`` for a zero opacity fill.

Setup requires the ``chromium`` extra and a browser install::

    uv pip install -e .[chromium]
    playwright install chromium

If Playwright or its browser cannot be installed, the module still imports; the
missing dependency is reported only when :func:`build_overlay` is called.
"""

from __future__ import annotations

import html

from .techniques import PlacementSpec


def _css_color(spec: PlacementSpec) -> str:
    """Return the CSS colour value for a placement."""
    if spec.technique == "render_mode_invisible":
        return "transparent"
    r, g, b = (round(channel * 255) for channel in spec.color)
    return f"rgb({r}, {g}, {b})"


def build_overlay_html(spec: PlacementSpec, page_width: float, page_height: float) -> str:
    """Build the HTML document for a placement overlay.

    Args:
        spec: The placement specification to realise.
        page_width: Overlay page width in PDF points.
        page_height: Overlay page height in PDF points.

    Returns:
        A complete HTML document as a string.
    """
    # CSS uses a top left origin, so convert the PDF baseline (lower left origin)
    # to a CSS top offset. Points map one to one onto CSS pt units.
    css_top = page_height - spec.y - spec.font_size * 0.80
    css_left = spec.x
    color = _css_color(spec)
    payload = html.escape(spec.text)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
        "html, body { margin: 0; padding: 0; }"
        f"body {{ width: {page_width}pt; height: {page_height}pt; background: #ffffff; }}"
        "#payload {"
        " position: absolute;"
        f" left: {css_left}pt;"
        f" top: {css_top}pt;"
        " font-family: Helvetica, Arial, sans-serif;"
        f" font-size: {spec.font_size}pt;"
        f" color: {color};"
        f" opacity: {spec.opacity};"
        " white-space: nowrap;"
        " }"
        "</style></head><body>"
        f'<div id="payload">{payload}</div>'
        "</body></html>"
    )


def build_overlay(spec: PlacementSpec, page_width: float, page_height: float) -> bytes:
    """Render a one page overlay for a placement and return it as PDF bytes.

    Args:
        spec: The placement specification to realise.
        page_width: Overlay page width in PDF points (matches the source page).
        page_height: Overlay page height in PDF points (matches the source page).

    Returns:
        The overlay PDF encoded as bytes.

    Raises:
        RuntimeError: If Playwright or its Chromium browser is not available.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "The chromium backend requires the 'chromium' extra: "
            "install with 'uv pip install -e .[chromium]' and run 'playwright install chromium'."
        ) from exc

    document = build_overlay_html(spec, page_width, page_height)
    width_in = page_width / 72.0
    height_in = page_height / 72.0
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(document, wait_until="load")
                pdf_bytes = page.pdf(
                    width=f"{width_in}in",
                    height=f"{height_in}in",
                    print_background=True,
                    margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                )
            finally:
                browser.close()
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"Chromium rendering failed: {exc}") from exc
    return pdf_bytes
