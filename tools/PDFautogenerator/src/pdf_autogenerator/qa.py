from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher
import hashlib
import json
import re

import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader

from .config import GeneratorConfig
from .fonts import FONT_DEFINITIONS
from .manifest import read_manifest
from .templates import TEMPLATES, get_template, resolve_templates


REQUIRED_FIELDS = [
    "doc_id",
    "source_type",
    "template_id",
    "font_family",
    "page_size",
    "margin_preset",
    "density_preset",
    "has_header",
    "has_footer",
    "has_small_text",
    "column_mode",
    "has_table_region",
    "seed",
    "status",
]

SUSPICIOUS_KEYWORDS = [
    "ignore previous",
    "system prompt",
    "prompt injection",
    "developer message",
    "follow these instructions",
    "jailbreak",
]


@dataclass(frozen=True)
class QAThresholds:
    min_template_count: int = 2
    max_family_share: float = 0.30
    max_template_share: float = 0.18
    near_duplicate_threshold: float = 0.94
    repeated_line_share: float = 0.15
    min_nonwhite_ratio: float = 0.02
    max_nonwhite_ratio: float = 0.15
    min_char_count: int = 150
    max_char_count: int = 5000


@dataclass(frozen=True)
class QAExpectations:
    families: set[str]
    template_ids: set[str]
    font_families: set[str]
    page_sizes: set[str]
    margin_presets: set[str]
    density_presets: set[str]
    header_values: set[bool]
    footer_values: set[bool]
    small_text_values: set[bool]
    table_values: set[bool]
    column_values: set[str]
    mode: str
    warnings: tuple[str, ...] = ()


def _check(passed: bool, details: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": "pass" if passed else "fail",
        "details": details,
        "warnings": warnings or [],
    }


def _manual(details: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "manual",
        "details": details,
        "warnings": [],
    }


def _expected_boolean_values(*, required_any: bool, optional_any: bool, probability: float) -> set[bool]:
    values: set[bool] = set()
    if required_any:
        values.add(True)
    if optional_any:
        if probability > 0:
            values.add(True)
        if probability < 1:
            values.add(False)
    return values or {False}


def _expected_table_values(templates: list[Any], probability: float) -> set[bool]:
    values: set[bool] = set()
    if any(template.requires_table_region for template in templates):
        values.add(True)
    if any(template.supports_table_region and not template.requires_table_region for template in templates):
        if probability > 0:
            values.add(True)
        if probability < 1:
            values.add(False)
    if any(not template.requires_table_region and not template.supports_table_region for template in templates):
        values.add(False)
    return values or {False}


def _build_expectations(
    generated_rows: list[dict[str, Any]],
    config: GeneratorConfig | None,
) -> QAExpectations:
    if config is None:
        return QAExpectations(
            families={row.get("source_type") for row in generated_rows if row.get("source_type")},
            template_ids={row.get("template_id") for row in generated_rows if row.get("template_id")},
            font_families={row.get("font_family") for row in generated_rows if row.get("font_family")},
            page_sizes={row.get("page_size") for row in generated_rows if row.get("page_size")},
            margin_presets={row.get("margin_preset") for row in generated_rows if row.get("margin_preset")},
            density_presets={row.get("density_preset") for row in generated_rows if row.get("density_preset")},
            header_values={row.get("has_header") for row in generated_rows if row.get("has_header") is not None},
            footer_values={row.get("has_footer") for row in generated_rows if row.get("has_footer") is not None},
            small_text_values={row.get("has_small_text") for row in generated_rows if row.get("has_small_text") is not None},
            table_values={row.get("has_table_region") for row in generated_rows if row.get("has_table_region") is not None},
            column_values={row.get("column_mode") for row in generated_rows if row.get("column_mode")},
            mode="inferred",
            warnings=("qa_expectations_inferred_from_manifest",),
        )

    expected_templates = [
        template
        for template in resolve_templates(config.template_allowlist)
        if config.family_weights.get(template.source_type, 0) > 0
    ]
    return QAExpectations(
        families={template.source_type for template in expected_templates},
        template_ids={template.template_id for template in expected_templates},
        font_families={FONT_DEFINITIONS[key].display_name for key in config.font_allowlist},
        page_sizes={page_size for page_size, weight in config.page_size_weights.items() if weight > 0},
        margin_presets=set(config.margin_presets),
        density_presets=set(config.density_presets),
        header_values=_expected_boolean_values(
            required_any=any(template.requires_header for template in expected_templates),
            optional_any=any(not template.requires_header for template in expected_templates),
            probability=config.header_probability,
        ),
        footer_values=_expected_boolean_values(
            required_any=False,
            optional_any=True,
            probability=config.footer_probability,
        ),
        small_text_values=_expected_boolean_values(
            required_any=False,
            optional_any=True,
            probability=config.small_text_probability,
        ),
        table_values=_expected_table_values(expected_templates, config.table_region_probability),
        column_values=(
            {"single", "double"} if any(template.allows_two_columns for template in expected_templates) else {"single"}
        ),
        mode="config",
    )


def run_qa(
    manifest_path: Path,
    config: GeneratorConfig | None = None,
    thresholds: QAThresholds | None = None,
    sample_per_family: int = 5,
) -> dict[str, Any]:
    thresholds = thresholds or QAThresholds()
    rows = read_manifest(manifest_path)
    generated_rows = [row for row in rows if row.get("status") == "generated"]
    expectations = _build_expectations(generated_rows, config)
    allowed_families = expectations.families
    allowed_fonts = expectations.font_families
    expected_templates = expectations.template_ids
    allowed_double = {template.template_id for template in TEMPLATES if template.allows_two_columns}

    issues: defaultdict[str, list[Any]] = defaultdict(list)
    reader_ok_count = 0
    fitz_ok_count = 0
    file_hashes: Counter[str] = Counter()
    texts: dict[str, str] = {}
    char_counts: list[tuple[str, int]] = []
    nonwhite_ratios: list[tuple[str, float]] = []
    font_sizes: list[float] = []
    small_text_sizes: list[float] = []
    xref_lengths: list[int] = []
    resource_font_counts: list[int] = []
    top_y: list[float] = []
    footer_lines: list[str] = []
    first_lines: list[str] = []
    line_counter: Counter[str] = Counter()
    annotations: list[str] = []
    acroform_docs: list[str] = []
    embedded_file_docs: list[str] = []
    artifact_hits: list[str] = []
    tr_hits: list[tuple[str, list[int]]] = []
    white_text_hits: list[str] = []
    offpage_hits: list[tuple[str, list[float]]] = []
    keyword_hits: list[tuple[str, list[str]]] = []
    extractor_mismatch: list[tuple[str, float]] = []

    family_counts = Counter(row.get("source_type") for row in generated_rows)
    template_counts = Counter(row.get("template_id") for row in generated_rows)
    font_counts = Counter(row.get("font_family") for row in generated_rows)
    page_size_counts = Counter(row.get("page_size") for row in generated_rows)
    margin_counts = Counter(row.get("margin_preset") for row in generated_rows)
    density_counts = Counter(row.get("density_preset") for row in generated_rows)
    header_counts = Counter(row.get("has_header") for row in generated_rows)
    footer_counts = Counter(row.get("has_footer") for row in generated_rows)
    small_text_counts = Counter(row.get("has_small_text") for row in generated_rows)
    table_counts = Counter(row.get("has_table_region") for row in generated_rows)
    column_counts = Counter(row.get("column_mode") for row in generated_rows)

    doc_ids = [row.get("doc_id") for row in rows]
    if len(doc_ids) != len(set(doc_ids)):
        issues["duplicate_doc_id"] = [doc_id for doc_id, count in Counter(doc_ids).items() if count > 1]

    for row in rows:
        doc_id = row.get("doc_id")
        for field in REQUIRED_FIELDS:
            if field not in row:
                issues["missing_required_field"].append((doc_id, field))
            elif row[field] is None:
                issues["null_required_field"].append((doc_id, field))

        if row.get("status") != "generated":
            if row.get("pdf_path") is not None or int(row.get("page_count", 0)) != 0:
                issues["non_generated_row_shape"].append(doc_id)
            continue

        pdf_path_value = row.get("pdf_path")
        if not pdf_path_value:
            issues["missing_file"].append(doc_id)
            continue
        pdf_path = Path(pdf_path_value)
        if not pdf_path.exists():
            issues["missing_file"].append(doc_id)
            continue

        file_hashes[hashlib.sha256(pdf_path.read_bytes()).hexdigest()] += 1

        try:
            reader = PdfReader(str(pdf_path))
            reader_ok_count += 1
            if len(reader.pages) != 1:
                issues["page_count_not_1"].append((doc_id, len(reader.pages)))
            pypdf_text = (reader.pages[0].extract_text() or "").strip()
            if not pypdf_text:
                issues["empty_extraction_pypdf"].append(doc_id)
        except Exception as exc:  # pragma: no cover - defensive
            issues["pypdf_open_error"].append((doc_id, str(exc)))
            continue

        try:
            document = fitz.open(pdf_path)
            fitz_ok_count += 1
            page = document[0]
            fitz_text = page.get_text("text").strip()
            texts[doc_id] = fitz_text
            char_counts.append((doc_id, len(fitz_text)))
            if not fitz_text:
                issues["empty_extraction_fitz"].append(doc_id)
            if pypdf_text and fitz_text:
                ratio = SequenceMatcher(None, pypdf_text[:4000], fitz_text[:4000]).ratio()
                if ratio < 0.55:
                    extractor_mismatch.append((doc_id, round(ratio, 3)))

            blocks = [block for block in page.get_text("blocks") if str(block[4]).strip()]
            if not blocks:
                issues["no_text_blocks"].append(doc_id)
            else:
                top_y.append(min(block[1] for block in blocks))
                if row.get("has_footer"):
                    bottom_block = max(blocks, key=lambda item: item[3])
                    footer_lines.append(" ".join(bottom_block[4].split()))
                for block in blocks:
                    x0, y0, x1, y1 = block[:4]
                    if x0 < -1 or y0 < -1 or x1 > page.rect.width + 1 or y1 > page.rect.height + 1:
                        offpage_hits.append((doc_id, [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]))

            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = float(span.get("size", 0.0))
                        font_sizes.append(size)
                        if size <= 8.1:
                            small_text_sizes.append(size)
                        if span.get("color", 0) == 16777215:
                            white_text_hits.append(doc_id)

            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            total_pixels = image.width * image.height
            non_white = sum(1 for pixel in image.getdata() if pixel != (255, 255, 255))
            nonwhite_ratios.append((doc_id, non_white / total_pixels if total_pixels else 0.0))

            lines = [line.strip() for line in fitz_text.splitlines() if line.strip()]
            if lines:
                first_lines.append(lines[0])
                for line in lines:
                    normalized_line = " ".join(line.split())
                    if len(normalized_line) >= 20:
                        line_counter[normalized_line] += 1

            lowered = fitz_text.lower()
            matched_keywords = [keyword for keyword in SUSPICIOUS_KEYWORDS if keyword in lowered]
            if matched_keywords:
                keyword_hits.append((doc_id, matched_keywords))

            contents = reader.pages[0].get_contents()
            if isinstance(contents, list):
                raw_stream = b"".join(content.get_data() for content in contents)
            elif contents is None:
                raw_stream = b""
            else:
                raw_stream = contents.get_data()
            if b"/Artifact" in raw_stream:
                artifact_hits.append(doc_id)
            tr_matches = re.findall(rb"(?<!\\d)([1-7])\\s+Tr", raw_stream)
            if tr_matches:
                tr_hits.append((doc_id, sorted({int(match) for match in tr_matches})))

            if "/Annots" in reader.pages[0]:
                annotations.append(doc_id)
            root = reader.trailer["/Root"]
            if "/AcroForm" in root:
                acroform_docs.append(doc_id)
            names = root.get("/Names")
            if names and "/EmbeddedFiles" in names.get_object():
                embedded_file_docs.append(doc_id)
            xref_lengths.append(document.xref_length())
            resources = reader.pages[0].get("/Resources", {})
            if hasattr(resources, "get_object"):
                resources = resources.get_object()
            fonts = resources.get("/Font", {}) if resources else {}
            if hasattr(fonts, "get_object"):
                fonts = fonts.get_object()
            resource_font_counts.append(len(fonts))
            document.close()
        except Exception as exc:  # pragma: no cover - defensive
            issues["fitz_open_error"].append((doc_id, str(exc)))

        if row.get("column_mode") == "double" and row.get("template_id") not in allowed_double:
            issues["invalid_double_column_template"].append(doc_id)

    duplicate_file_contents = [digest for digest, count in file_hashes.items() if count > 1]
    near_duplicates: list[tuple[str, str, float]] = []
    text_items = list(texts.items())
    for index, (doc_a, text_a) in enumerate(text_items):
        for doc_b, text_b in text_items[index + 1 :]:
            ratio = SequenceMatcher(None, text_a, text_b).ratio()
            if ratio >= thresholds.near_duplicate_threshold:
                near_duplicates.append((doc_a, doc_b, round(ratio, 3)))

    repeated_line_cutoff = max(3, ceil(max(len(generated_rows), 1) * thresholds.repeated_line_share))
    repeated_lines = [
        (line, count)
        for line, count in line_counter.most_common()
        if count >= repeated_line_cutoff
    ]

    missing_families = sorted(family for family in allowed_families if family_counts[family] == 0)
    missing_templates = sorted(template_id for template_id in expected_templates if template_counts[template_id] == 0)
    templates_below_min = [
        template_id
        for template_id in expected_templates
        if template_counts[template_id] < thresholds.min_template_count
    ]
    family_template_variants = {
        family: len(
            {
                template_id
                for template_id, count in template_counts.items()
                if get_template(template_id).source_type == family and count > 0
            }
        )
        for family in allowed_families
    }
    expected_template_variants = Counter(get_template(template_id).source_type for template_id in expected_templates)
    low_variant_families = [
        family
        for family, variant_count in family_template_variants.items()
        if family_counts[family] > 0
        and variant_count < min(2, expected_template_variants.get(family, 0))
    ]

    total_generated = len(generated_rows) or 1
    family_share = {family: count / total_generated for family, count in family_counts.items()}
    template_share = {template: count / total_generated for template, count in template_counts.items()}
    skewed_families = [family for family, share in family_share.items() if share > thresholds.max_family_share]
    skewed_templates = [template for template, share in template_share.items() if share > thresholds.max_template_share]

    char_values = [count for _, count in char_counts]
    low_char_docs = [doc_id for doc_id, count in char_counts if count < thresholds.min_char_count]
    high_char_docs = [doc_id for doc_id, count in char_counts if count > thresholds.max_char_count]
    out_of_band_nonwhite = [
        (doc_id, round(value, 4))
        for doc_id, value in nonwhite_ratios
        if value < thresholds.min_nonwhite_ratio or value > thresholds.max_nonwhite_ratio
    ]

    file_level_validity = _check(
        passed=not (
            issues["missing_file"]
            or issues["page_count_not_1"]
            or duplicate_file_contents
            or issues["duplicate_doc_id"]
            or issues["pypdf_open_error"]
            or issues["fitz_open_error"]
        ),
        details={
            "manifest_rows": len(rows),
            "generated_rows": len(generated_rows),
            "opened_with_pypdf": reader_ok_count,
            "opened_with_fitz": fitz_ok_count,
            "duplicate_file_contents": duplicate_file_contents,
            "missing_file_issues": issues["missing_file"],
        },
    )

    metadata_completeness = _check(
        passed=not (issues["missing_required_field"] or issues["null_required_field"]),
        details={
            "missing_required_field": issues["missing_required_field"],
            "null_required_field": issues["null_required_field"],
        },
    )

    one_page_realism = _check(
        passed=not (issues["page_count_not_1"] or offpage_hits or out_of_band_nonwhite),
        details={
            "page_count_not_1": issues["page_count_not_1"],
            "offpage_hits": offpage_hits,
            "out_of_band_nonwhite": out_of_band_nonwhite,
        },
    )

    family_coverage = _check(
        passed=not (missing_families or missing_templates or templates_below_min or low_variant_families),
        details={
            "expectation_mode": expectations.mode,
            "expected_families": sorted(allowed_families),
            "expected_templates": sorted(expected_templates),
            "family_counts": dict(family_counts),
            "template_counts": dict(template_counts),
            "missing_families": missing_families,
            "missing_templates": missing_templates,
            "templates_below_min": templates_below_min,
            "low_variant_families": low_variant_families,
        },
        warnings=list(expectations.warnings),
    )

    layout_diversity = _check(
        passed=all(
            [
                expectations.page_sizes.issubset(set(page_size_counts)),
                expectations.margin_presets.issubset(set(margin_counts)),
                expectations.density_presets.issubset(set(density_counts)),
                expectations.header_values.issubset(set(header_counts)),
                expectations.footer_values.issubset(set(footer_counts)),
                expectations.small_text_values.issubset(set(small_text_counts)),
                expectations.table_values.issubset(set(table_counts)),
                expectations.column_values.issubset(set(column_counts)),
                not issues["invalid_double_column_template"],
            ]
        ),
        details={
            "expectation_mode": expectations.mode,
            "expected_page_sizes": sorted(expectations.page_sizes),
            "expected_margin_presets": sorted(expectations.margin_presets),
            "expected_density_presets": sorted(expectations.density_presets),
            "expected_header_values": sorted(expectations.header_values),
            "expected_footer_values": sorted(expectations.footer_values),
            "expected_small_text_values": sorted(expectations.small_text_values),
            "expected_table_values": sorted(expectations.table_values),
            "expected_column_values": sorted(expectations.column_values),
            "page_size_counts": dict(page_size_counts),
            "margin_counts": dict(margin_counts),
            "density_counts": dict(density_counts),
            "header_counts": dict(header_counts),
            "footer_counts": dict(footer_counts),
            "small_text_counts": dict(small_text_counts),
            "table_counts": dict(table_counts),
            "column_counts": dict(column_counts),
        },
        warnings=list(expectations.warnings),
    )

    typography_diversity = _check(
        passed=(
            allowed_fonts.issubset(set(font_counts))
            and not white_text_hits
            and (min(font_sizes) >= 7.0 if font_sizes else False)
            and (max(font_sizes) <= 18.0 if font_sizes else False)
            and (
                (
                    True not in expectations.small_text_values
                    and not small_text_sizes
                )
                or (
                    small_text_sizes
                    and min(small_text_sizes) >= 7.0
                    and max(small_text_sizes) <= 8.1
                )
            )
        ),
        details={
            "expectation_mode": expectations.mode,
            "expected_fonts": sorted(allowed_fonts),
            "font_counts": dict(font_counts),
            "font_size_min_max": [min(font_sizes) if font_sizes else None, max(font_sizes) if font_sizes else None],
            "small_text_size_min_max": [
                min(small_text_sizes) if small_text_sizes else None,
                max(small_text_sizes) if small_text_sizes else None,
            ],
            "white_text_hits": sorted(set(white_text_hits)),
        },
        warnings=list(expectations.warnings),
    )

    content_realism = _check(
        passed=not keyword_hits
        and not any("lorem ipsum" in text.lower() for text in texts.values())
        and not repeated_lines
        and not near_duplicates,
        details={
            "keyword_hits": keyword_hits,
            "repeated_lines": repeated_lines[:10],
            "near_duplicates": near_duplicates[:10],
        },
    )

    structural_sanity = _check(
        passed=not (annotations or acroform_docs or embedded_file_docs or artifact_hits or tr_hits or white_text_hits or offpage_hits),
        details={
            "annotations": annotations,
            "acroform_docs": acroform_docs,
            "embedded_file_docs": embedded_file_docs,
            "artifact_hits": artifact_hits,
            "text_render_mode_hits": tr_hits,
            "xref_length_min_max": [min(xref_lengths) if xref_lengths else None, max(xref_lengths) if xref_lengths else None],
            "resource_font_count_distribution": dict(Counter(resource_font_counts)),
        },
        warnings=(
            ["uniform_xref_length"] if xref_lengths and len(set(xref_lengths)) == 1 else []
        )
        + (
            ["uniform_font_resource_count"] if resource_font_counts and len(set(resource_font_counts)) == 1 else []
        ),
    )

    extraction_sanity = _check(
        passed=not (
            issues["empty_extraction_pypdf"]
            or issues["empty_extraction_fitz"]
            or extractor_mismatch
            or low_char_docs
            or high_char_docs
        ),
        details={
            "empty_extraction_pypdf": issues["empty_extraction_pypdf"],
            "empty_extraction_fitz": issues["empty_extraction_fitz"],
            "extractor_mismatch": extractor_mismatch,
            "char_count_min_max": [min(char_values) if char_values else None, max(char_values) if char_values else None],
            "low_char_docs": low_char_docs,
            "high_char_docs": high_char_docs,
        },
    )

    distribution_sanity = _check(
        passed=not (skewed_families or skewed_templates),
        details={
            "family_share": {key: round(value, 3) for key, value in sorted(family_share.items())},
            "template_share": {key: round(value, 3) for key, value in sorted(template_share.items())},
            "skewed_families": skewed_families,
            "skewed_templates": skewed_templates,
        },
    )

    generator_fingerprints = _check(
        passed=(
            len(set(first_lines)) >= min(10, max(len(generated_rows) // 4, 1))
            and len(set(footer_lines)) >= min(3, max(1, len([row for row in generated_rows if row.get("has_footer")]) // 4))
            and repeated_lines == []
            and (max(top_y) - min(top_y) >= 10 if top_y else False)
        ),
        details={
            "unique_first_lines": len(set(first_lines)),
            "unique_footer_lines": len(set(footer_lines)),
            "repeated_lines": repeated_lines[:10],
            "top_y_range": round((max(top_y) - min(top_y)), 2) if top_y else None,
        },
        warnings=(
            ["uniform_xref_length"] if xref_lengths and len(set(xref_lengths)) == 1 else []
        ),
    )

    negative_checks = _check(
        passed=not (keyword_hits or offpage_hits or tr_hits or white_text_hits or artifact_hits),
        details={
            "keyword_hits": keyword_hits,
            "offpage_hits": offpage_hits,
            "text_render_mode_hits": tr_hits,
            "white_text_hits": sorted(set(white_text_hits)),
            "artifact_hits": artifact_hits,
        },
    )

    sample_paths_by_family: dict[str, list[str]] = {}
    for family in sorted(allowed_families):
        family_rows = [row for row in generated_rows if row.get("source_type") == family][:sample_per_family]
        sample_paths_by_family[family] = [row["pdf_path"] for row in family_rows]

    visual_audit = _manual(
        {
            "sample_paths_by_family": sample_paths_by_family,
            "recommended_checks": [
                "Open 5-10 PDFs per family in a desktop PDF viewer",
                "Review both page sizes and all margin presets",
                "Confirm no clipping, overlap, or obviously synthetic styling",
            ],
        }
    )

    checks = {
        "file_level_validity": file_level_validity,
        "metadata_completeness": metadata_completeness,
        "one_page_realism": one_page_realism,
        "family_coverage": family_coverage,
        "layout_diversity": layout_diversity,
        "typography_diversity": typography_diversity,
        "content_realism": content_realism,
        "generator_fingerprints": generator_fingerprints,
        "structural_sanity": structural_sanity,
        "extraction_sanity": extraction_sanity,
        "distribution_sanity": distribution_sanity,
        "visual_audit": visual_audit,
        "negative_checks": negative_checks,
    }

    overall_pass = all(check["status"] == "pass" for check in checks.values() if check["status"] != "manual")
    return {
        "overall_pass": overall_pass,
        "manifest_path": str(manifest_path),
        "row_count": len(rows),
        "generated_count": len(generated_rows),
        "expectation_mode": expectations.mode,
        "checks": checks,
    }
