"""Sanitizer variants built on the frozen detector's text preprocessing.

The frozen ``apply_text_preprocessing`` deletes the whole
``DOCUMENT_LAYOUT_NOTE`` block, which is the confounder's entire added
text, while keeping the contents of the injected ``SYSTEM_POLICY`` block.
The symmetric variant removes the ``DOCUMENT_LAYOUT_NOTE`` tags before the
frozen function runs, so the block regex never matches and both roles keep
their contents. Every other step is the frozen code, unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from crackedpdfs_reanalysis import detector  # noqa: F401  (adds the frozen detector to sys.path)

from src.models.text_preprocessing import (
    _spaced_token_pattern,
    apply_text_preprocessing,
    build_text_preprocessing_config,
)

SCAFFOLD_TAGS = ("DOCUMENT_LAYOUT_NOTE",)


def strip_scaffold_tags(text: str) -> str:
    """Remove scaffold tags (exact and letter-spaced) but keep what they enclose."""
    cleaned = text or ""
    for tag in SCAFFOLD_TAGS:
        cleaned = re.sub(r"<\s*/?\s*" + re.escape(tag) + r"\s*>", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"<\s*/?\s*" + _spaced_token_pattern(tag) + r"\s*>", " ", cleaned, flags=re.IGNORECASE
        )
    return cleaned


def build_preprocessing(text_cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Frozen preprocessing config plus the ``strip_scaffold_block_contents`` switch (default true)."""
    cfg = dict(text_cfg or {})
    preprocessing = build_text_preprocessing_config(cfg)
    preprocessing["strip_scaffold_block_contents"] = bool(cfg.get("strip_scaffold_block_contents", True))
    return preprocessing


def sanitize(text: str, preprocessing: dict[str, Any]) -> str:
    """Apply the frozen sanitizer, optionally keeping scaffold block contents for both roles."""
    if not preprocessing.get("strip_scaffold_block_contents", True):
        text = strip_scaffold_tags(text)
    return apply_text_preprocessing(text, preprocessing)
