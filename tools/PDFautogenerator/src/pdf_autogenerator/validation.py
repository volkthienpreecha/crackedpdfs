from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader

from .manifest import read_manifest
from .templates import get_template


@dataclass
class ValidationResult:
    valid: bool
    page_count: int
    issues: list[str]


def validate_generated_pdf(path: Path, row: dict[str, Any]) -> ValidationResult:
    issues: list[str] = []
    if not path.exists():
        return ValidationResult(valid=False, page_count=0, issues=["missing_file"])

    try:
        page_count = len(PdfReader(str(path)).pages)
    except Exception as exc:  # pragma: no cover
        return ValidationResult(valid=False, page_count=0, issues=[f"pdf_read_error:{exc}"])

    if page_count != 1:
        issues.append("page_count")

    try:
        template = get_template(str(row["template_id"]))
    except Exception:
        template = None
        issues.append("template_id")

    if row.get("page_size") not in {"letter", "a4"}:
        issues.append("page_size")
    if template is not None and template.source_type != row.get("source_type"):
        issues.append("template_family_mismatch")
    if template is not None and template.requires_table_region and not row.get("has_table_region"):
        issues.append("missing_required_table_region")
    if template is not None and template.requires_header and not row.get("has_header"):
        issues.append("missing_required_header")
    if not row.get("font_family"):
        issues.append("font_family")

    with fitz.open(path) as document:
        page = document[0]
        text_blocks = [block for block in page.get_text("blocks") if str(block[4]).strip()]
        if not text_blocks:
            issues.append("no_text_blocks")

        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
        image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        non_white = 0
        total_pixels = image.width * image.height
        for pixel in image.getdata():
            if pixel != (255, 255, 255):
                non_white += 1
        if total_pixels == 0 or (non_white / total_pixels) < 0.001:
            issues.append("visually_empty")

    return ValidationResult(valid=not issues, page_count=page_count, issues=issues)


def validate_manifest(manifest_path: Path) -> tuple[bool, list[str]]:
    rows = read_manifest(manifest_path)
    issues: list[str] = []
    seen_doc_ids: set[str] = set()
    for index, row in enumerate(rows):
        doc_id = row.get("doc_id")
        if not doc_id:
            issues.append(f"row:{index}:missing_doc_id")
            continue
        pdf_path = row.get("pdf_path")
        if doc_id in seen_doc_ids:
            issues.append(f"row:{index}:duplicate_doc_id")
        seen_doc_ids.add(doc_id)
        if row.get("status") == "generated":
            if pdf_path is None:
                issues.append(f"row:{index}:generated_missing_pdf_path")
                continue
            result = validate_generated_pdf(Path(pdf_path), row)
            if not result.valid:
                issues.append(f"row:{index}:{'|'.join(result.issues)}")
            if int(row.get("page_count", 0)) != result.page_count:
                issues.append(f"row:{index}:page_count_mismatch")
        else:
            if row.get("pdf_path") is not None:
                issues.append(f"row:{index}:non_generated_pdf_path_present")
            if int(row.get("page_count", 0)) != 0:
                issues.append(f"row:{index}:non_generated_page_count")
    return (not issues, issues)
