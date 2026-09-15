from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher
import hashlib
import json
import re

import pymupdf as fitz
from pypdf import PdfReader

from .audit_config import AuditConfig
from .manifest import read_manifest
from .templates import get_template


WORD_RE = re.compile(r"[a-z0-9]+")
MASK_64 = (1 << 64) - 1


@dataclass(frozen=True)
class PdfAuditRecord:
    doc_id: str
    stage: str
    path: Path
    page_count: int
    text: str
    file_hash: str


def _result(status: str, details: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "details": details,
        "warnings": warnings or [],
    }


def _pass(details: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return _result("pass", details, warnings)


def _fail(details: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return _result("fail", details, warnings)


def _na(details: dict[str, Any]) -> dict[str, Any]:
    return _result("not_applicable", details)


def _sample(items: list[Any], limit: int = 10) -> list[Any]:
    return items[:limit]


def _mix64(value: int) -> int:
    value &= MASK_64
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & MASK_64
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & MASK_64
    value ^= value >> 31
    return value & MASK_64


def _stable_hash64(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


def _normalize_text(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def _shingle_hashes(normalized_text: str, shingle_size: int) -> tuple[int, ...]:
    tokens = normalized_text.split()
    if not tokens:
        return tuple()
    if len(tokens) < shingle_size:
        return (_stable_hash64(normalized_text),)
    hashes = {
        _stable_hash64(" ".join(tokens[index : index + shingle_size]))
        for index in range(len(tokens) - shingle_size + 1)
    }
    return tuple(sorted(hashes))


def _minhash_signature(shingle_hash_values: tuple[int, ...], permutation_count: int) -> tuple[int, ...]:
    if not shingle_hash_values:
        return tuple(0 for _ in range(permutation_count))
    signature: list[int] = []
    for index in range(permutation_count):
        salt = _mix64((index + 1) * 0x9E3779B185EBCA87)
        signature.append(min(_mix64(value ^ salt) for value in shingle_hash_values))
    return tuple(signature)


def find_near_duplicate_pairs(
    texts_by_doc_id: dict[str, str],
    *,
    similarity_threshold: float,
    shingle_size: int,
    band_count: int,
    rows_per_band: int,
    max_bucket_size: int,
    sample_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not texts_by_doc_id:
        return [], {"candidate_pair_count": 0, "bucket_count": 0, "skipped_large_buckets": 0}

    ordered_items = list(texts_by_doc_id.items())
    normalized_texts = {doc_id: _normalize_text(text) for doc_id, text in ordered_items}
    permutation_count = band_count * rows_per_band
    buckets: defaultdict[tuple[int, tuple[int, ...]], list[int]] = defaultdict(list)
    signatures: list[tuple[int, ...]] = []
    for index, (doc_id, _) in enumerate(ordered_items):
        shingles = _shingle_hashes(normalized_texts[doc_id], shingle_size)
        signature = _minhash_signature(shingles, permutation_count)
        signatures.append(signature)
        for band_index in range(band_count):
            start = band_index * rows_per_band
            band_key = signature[start : start + rows_per_band]
            buckets[(band_index, band_key)].append(index)

    candidate_pairs: set[tuple[int, int]] = set()
    skipped_large_buckets = 0
    for indices in buckets.values():
        unique_indices = sorted(set(indices))
        if len(unique_indices) < 2:
            continue
        if len(unique_indices) > max_bucket_size:
            skipped_large_buckets += 1
            continue
        for left, right in combinations(unique_indices, 2):
            candidate_pairs.add((left, right))

    fallback_used = False
    if not candidate_pairs and rows_per_band > 1:
        fallback_used = True
        fallback_buckets: defaultdict[tuple[str, int, int], list[int]] = defaultdict(list)
        for index, signature in enumerate(signatures):
            for signature_index, value in enumerate(signature):
                fallback_buckets[("fallback", signature_index, value)].append(index)
        for indices in fallback_buckets.values():
            unique_indices = sorted(set(indices))
            if len(unique_indices) < 2:
                continue
            if len(unique_indices) > max_bucket_size:
                skipped_large_buckets += 1
                continue
            for left, right in combinations(unique_indices, 2):
                candidate_pairs.add((left, right))

    near_duplicates: list[dict[str, Any]] = []
    for left, right in sorted(candidate_pairs):
        doc_id_a, _ = ordered_items[left]
        doc_id_b, _ = ordered_items[right]
        ratio = SequenceMatcher(None, normalized_texts[doc_id_a], normalized_texts[doc_id_b]).ratio()
        if ratio >= similarity_threshold:
            near_duplicates.append(
                {
                    "doc_id_a": doc_id_a,
                    "doc_id_b": doc_id_b,
                    "similarity": round(ratio, 3),
                }
            )
            if len(near_duplicates) >= sample_limit:
                break

    return near_duplicates, {
        "candidate_pair_count": len(candidate_pairs),
        "bucket_count": len(buckets),
        "skipped_large_buckets": skipped_large_buckets,
        "fallback_used": fallback_used,
    }


def _resolve_stage(row: dict[str, Any], config: AuditConfig, issues: defaultdict[str, list[Any]]) -> str | None:
    raw_stage = row.get(config.stage_field)
    doc_id = row.get("doc_id")
    if raw_stage in {None, ""}:
        if config.allow_missing_stage_for_default:
            return config.default_stage
        issues["missing_stage"].append(doc_id)
        return None
    stage = str(raw_stage)
    if stage not in config.allowed_stages:
        issues["invalid_stage"].append({"doc_id": doc_id, "stage": stage})
        return None
    return stage


def _inspect_pdf(path: Path, row: dict[str, Any]) -> PdfAuditRecord:
    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    if page_count != 1:
        raise ValueError(f"page_count:{page_count}")

    with fitz.open(path) as document:
        page = document[0]
        text = page.get_text("text").strip()
        if not text:
            raise ValueError("empty_text")

    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    stage = str(row.get("stage", "benign"))
    return PdfAuditRecord(
        doc_id=str(row["doc_id"]),
        stage=stage,
        path=path,
        page_count=page_count,
        text=text,
        file_hash=file_hash,
    )


def _status_counts(rows: list[dict[str, Any]], stage_by_doc: dict[str, str]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        doc_id = row.get("doc_id")
        stage = stage_by_doc.get(str(doc_id)) if doc_id is not None else None
        if stage is not None:
            counts[stage] += 1
    return dict(counts)


def audit_dataset(
    manifest_path: Path,
    config: AuditConfig,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    rows = read_manifest(manifest_path)
    issues: defaultdict[str, list[Any]] = defaultdict(list)
    stage_by_doc: dict[str, str] = {}
    pdf_records: list[PdfAuditRecord] = []
    texts_by_doc_id: dict[str, str] = {}
    family_counts: Counter[str] = Counter()
    template_counts: Counter[str] = Counter()
    regime_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()

    benign_keyword_hits: list[dict[str, Any]] = []
    benign_with_injected_metadata: list[str] = []
    injected_missing_metadata: list[dict[str, Any]] = []
    invalid_regimes: list[dict[str, Any]] = []

    seen_doc_ids: set[str] = set()
    exact_hash_counts: Counter[str] = Counter()

    for row_index, row in enumerate(rows):
        doc_id = row.get("doc_id")
        if not doc_id:
            issues["missing_doc_id"].append({"row_index": row_index})
            continue
        doc_id = str(doc_id)
        if doc_id in seen_doc_ids:
            issues["duplicate_doc_id"].append(doc_id)
        seen_doc_ids.add(doc_id)

        stage = _resolve_stage(row, config, issues)
        if stage is not None:
            stage_by_doc[doc_id] = stage
            stage_counts[stage] += 1

        for field in config.required_common_fields:
            if field not in row:
                issues["missing_common_field"].append({"doc_id": doc_id, "field": field})
            elif row[field] is None:
                issues["null_common_field"].append({"doc_id": doc_id, "field": field})

        status = row.get("status")
        if status not in config.allowed_statuses:
            issues["invalid_status"].append({"doc_id": doc_id, "status": status})
            continue

        if stage is None:
            continue

        for field in config.required_stage_fields.get(stage, tuple()):
            if field not in row:
                issues["missing_stage_field"].append({"doc_id": doc_id, "stage": stage, "field": field})
            elif row[field] is None:
                issues["null_stage_field"].append({"doc_id": doc_id, "stage": stage, "field": field})

        source_type = row.get("source_type")
        template_id = row.get("template_id")
        if source_type and source_type not in config.expectations.families:
            issues["unexpected_source_type"].append({"doc_id": doc_id, "source_type": source_type})
        if template_id and template_id not in config.expectations.templates:
            issues["unexpected_template_id"].append({"doc_id": doc_id, "template_id": template_id})
        if row.get("font_family") and row["font_family"] not in config.expectations.fonts:
            issues["unexpected_font_family"].append({"doc_id": doc_id, "font_family": row["font_family"]})
        if row.get("page_size") and row["page_size"] not in config.expectations.page_sizes:
            issues["unexpected_page_size"].append({"doc_id": doc_id, "page_size": row["page_size"]})
        if row.get("margin_preset") and row["margin_preset"] not in config.expectations.margin_presets:
            issues["unexpected_margin_preset"].append({"doc_id": doc_id, "margin_preset": row["margin_preset"]})
        if row.get("density_preset") and row["density_preset"] not in config.expectations.density_presets:
            issues["unexpected_density_preset"].append({"doc_id": doc_id, "density_preset": row["density_preset"]})

        if template_id:
            try:
                template = get_template(str(template_id))
                if source_type and template.source_type != source_type:
                    issues["template_source_mismatch"].append({"doc_id": doc_id, "template_id": template_id, "source_type": source_type})
                if row.get("column_mode") == "double" and not template.allows_two_columns:
                    issues["invalid_double_column_template"].append(doc_id)
            except KeyError:
                issues["unknown_template_definition"].append({"doc_id": doc_id, "template_id": template_id})

        if stage == "benign":
            if row.get(config.regime_field) not in {None, ""} or row.get(config.parent_field) not in {None, ""}:
                benign_with_injected_metadata.append(doc_id)
        if stage == "injected":
            missing_fields: list[str] = []
            if row.get(config.parent_field) in {None, ""}:
                missing_fields.append(config.parent_field)
            regime_value = row.get(config.regime_field)
            if regime_value in {None, ""}:
                missing_fields.append(config.regime_field)
            if missing_fields:
                injected_missing_metadata.append({"doc_id": doc_id, "fields": missing_fields})
            if regime_value not in {None, ""}:
                regime_text = str(regime_value)
                regime_counts[regime_text] += 1
                if config.allowed_regimes and regime_text not in config.allowed_regimes:
                    invalid_regimes.append({"doc_id": doc_id, "regime": regime_text})

        if source_type:
            family_counts[str(source_type)] += 1
        if template_id:
            template_counts[str(template_id)] += 1

        pdf_path_value = row.get("pdf_path")
        if not pdf_path_value:
            issues["missing_file"].append(doc_id)
            continue
        pdf_path = Path(str(pdf_path_value))
        if not pdf_path.exists():
            issues["missing_file"].append(doc_id)
            continue

        try:
            record = _inspect_pdf(pdf_path, {**row, "stage": stage})
        except Exception as exc:
            issues["corrupt_pdf"].append({"doc_id": doc_id, "issue": str(exc)})
            continue

        exact_hash_counts[record.file_hash] += 1
        pdf_records.append(record)
        texts_by_doc_id[doc_id] = record.text

        if int(row.get("page_count", 0)) != record.page_count:
            issues["page_count_mismatch"].append({"doc_id": doc_id, "manifest_page_count": row.get("page_count"), "actual_page_count": record.page_count})

        if stage == "benign":
            lowered = record.text.lower()
            matched = [keyword for keyword in config.suspicious_keywords if keyword in lowered]
            if matched:
                benign_keyword_hits.append({"doc_id": doc_id, "keywords": matched})

    duplicate_hashes = [digest for digest, count in exact_hash_counts.items() if count > 1]
    near_duplicates, near_duplicate_debug = find_near_duplicate_pairs(
        texts_by_doc_id,
        similarity_threshold=config.near_duplicate.similarity_threshold,
        shingle_size=config.near_duplicate.shingle_size,
        band_count=config.near_duplicate.band_count,
        rows_per_band=config.near_duplicate.rows_per_band,
        max_bucket_size=config.near_duplicate.max_bucket_size,
        sample_limit=config.near_duplicate.sample_limit,
    )

    expected_families = set(config.expectations.families)
    expected_templates = set(config.expectations.templates)
    missing_families = sorted(family for family in expected_families if family_counts[family] == 0)
    missing_templates = sorted(template for template in expected_templates if template_counts[template] == 0)
    under_supported_families = sorted(
        family for family in expected_families if family_counts[family] < config.support_thresholds.min_family_count
    )
    under_supported_templates = sorted(
        template for template in expected_templates if template_counts[template] < config.support_thresholds.min_template_count
    )
    under_supported_regimes = sorted(
        regime for regime in config.allowed_regimes if regime_counts[regime] < config.support_thresholds.min_regime_count
    )

    total_rows = len(rows) or 1
    family_share = {family: count / total_rows for family, count in family_counts.items()}
    template_share = {template: count / total_rows for template, count in template_counts.items()}
    regime_share = {regime: count / total_rows for regime, count in regime_counts.items()}
    skewed_families = sorted(
        family for family, share in family_share.items() if share > config.distribution_limits.max_family_share
    )
    skewed_templates = sorted(
        template for template, share in template_share.items() if share > config.distribution_limits.max_template_share
    )
    skewed_regimes = sorted(
        regime for regime, share in regime_share.items() if share > config.distribution_limits.max_regime_share
    )

    schema_failures = (
        issues["missing_doc_id"]
        or issues["missing_common_field"]
        or issues["null_common_field"]
        or issues["missing_stage"]
        or issues["invalid_stage"]
        or issues["invalid_status"]
        or issues["missing_stage_field"]
        or issues["null_stage_field"]
        or issues["unexpected_source_type"]
        or issues["unexpected_template_id"]
        or issues["unexpected_font_family"]
        or issues["unexpected_page_size"]
        or issues["unexpected_margin_preset"]
        or issues["unexpected_density_preset"]
        or issues["template_source_mismatch"]
        or issues["unknown_template_definition"]
        or issues["invalid_double_column_template"]
    )
    schema_validation = (
        _fail(
            {
                "missing_doc_id": _sample(issues["missing_doc_id"]),
                "missing_common_field": _sample(issues["missing_common_field"]),
                "null_common_field": _sample(issues["null_common_field"]),
                "missing_stage": _sample(issues["missing_stage"]),
                "invalid_stage": _sample(issues["invalid_stage"]),
                "invalid_status": _sample(issues["invalid_status"]),
                "missing_stage_field": _sample(issues["missing_stage_field"]),
                "null_stage_field": _sample(issues["null_stage_field"]),
                "unexpected_source_type": _sample(issues["unexpected_source_type"]),
                "unexpected_template_id": _sample(issues["unexpected_template_id"]),
                "unexpected_font_family": _sample(issues["unexpected_font_family"]),
                "unexpected_page_size": _sample(issues["unexpected_page_size"]),
                "unexpected_margin_preset": _sample(issues["unexpected_margin_preset"]),
                "unexpected_density_preset": _sample(issues["unexpected_density_preset"]),
                "template_source_mismatch": _sample(issues["template_source_mismatch"]),
                "unknown_template_definition": _sample(issues["unknown_template_definition"]),
                "invalid_double_column_template": _sample(issues["invalid_double_column_template"]),
            }
        )
        if schema_failures
        else _pass({"row_count": len(rows), "allowed_stages": list(config.allowed_stages), "allowed_statuses": list(config.allowed_statuses)})
    )

    duplicate_pdf_id_check = (
        _fail({"duplicate_doc_ids": _sample(issues["duplicate_doc_id"])})
        if issues["duplicate_doc_id"]
        else _pass({"duplicate_doc_ids": []})
    )

    missing_file_check = (
        _fail({"missing_files": _sample(issues["missing_file"])})
        if issues["missing_file"]
        else _pass({"missing_files": []})
    )

    corrupt_pdf_failures = issues["corrupt_pdf"] or issues["page_count_mismatch"]
    corrupt_pdf_check = (
        _fail(
            {
                "corrupt_pdf": _sample(issues["corrupt_pdf"]),
                "page_count_mismatch": _sample(issues["page_count_mismatch"]),
            }
        )
        if corrupt_pdf_failures
        else _pass({"corrupt_pdf": [], "page_count_mismatch": []})
    )

    benign_leak_failures = benign_keyword_hits or benign_with_injected_metadata
    benign_injection_leak_check = (
        _fail(
            {
                "suspicious_keyword_hits": _sample(benign_keyword_hits),
                "benign_with_injected_metadata": _sample(benign_with_injected_metadata),
            }
        )
        if benign_leak_failures
        else _pass({"suspicious_keyword_hits": [], "benign_with_injected_metadata": []})
    )

    if "injected" not in config.allowed_stages:
        injected_metadata_check = _na({"reason": "injected_stage_not_enabled"})
        regime_field_validation = _na({"reason": "injected_stage_not_enabled"})
        regime_support = _na({"reason": "injected_stage_not_enabled"})
    else:
        injected_metadata_check = (
            _fail({"missing_injected_metadata": _sample(injected_missing_metadata)})
            if injected_missing_metadata
            else _pass({"missing_injected_metadata": []})
        )
        regime_field_validation = (
            _fail({"invalid_regimes": _sample(invalid_regimes), "allowed_regimes": list(config.allowed_regimes)})
            if invalid_regimes
            else _pass({"invalid_regimes": [], "allowed_regimes": list(config.allowed_regimes)})
        )
        regime_support = (
            _fail(
                {
                    "regime_counts": dict(regime_counts),
                    "under_supported_regimes": under_supported_regimes,
                    "threshold": config.support_thresholds.min_regime_count,
                }
            )
            if config.allowed_regimes and under_supported_regimes
            else _pass(
                {
                    "regime_counts": dict(regime_counts),
                    "under_supported_regimes": [],
                    "threshold": config.support_thresholds.min_regime_count,
                }
            )
        )

    distribution_sanity_failures = skewed_families or skewed_templates or skewed_regimes
    distribution_sanity = (
        _fail(
            {
                "family_share": {key: round(value, 4) for key, value in sorted(family_share.items())},
                "template_share": {key: round(value, 4) for key, value in sorted(template_share.items())},
                "regime_share": {key: round(value, 4) for key, value in sorted(regime_share.items())},
                "skewed_families": skewed_families,
                "skewed_templates": skewed_templates,
                "skewed_regimes": skewed_regimes,
            }
        )
        if distribution_sanity_failures
        else _pass(
            {
                "family_share": {key: round(value, 4) for key, value in sorted(family_share.items())},
                "template_share": {key: round(value, 4) for key, value in sorted(template_share.items())},
                "regime_share": {key: round(value, 4) for key, value in sorted(regime_share.items())},
                "skewed_families": [],
                "skewed_templates": [],
                "skewed_regimes": [],
            }
        )
    )

    family_support = (
        _fail(
            {
                "family_counts": dict(family_counts),
                "missing_families": missing_families,
                "under_supported_families": under_supported_families,
                "threshold": config.support_thresholds.min_family_count,
            }
        )
        if missing_families or under_supported_families
        else _pass(
            {
                "family_counts": dict(family_counts),
                "missing_families": [],
                "under_supported_families": [],
                "threshold": config.support_thresholds.min_family_count,
            }
        )
    )

    template_support = (
        _fail(
            {
                "template_counts": dict(template_counts),
                "missing_templates": missing_templates,
                "under_supported_templates": under_supported_templates,
                "threshold": config.support_thresholds.min_template_count,
            }
        )
        if missing_templates or under_supported_templates
        else _pass(
            {
                "template_counts": dict(template_counts),
                "missing_templates": [],
                "under_supported_templates": [],
                "threshold": config.support_thresholds.min_template_count,
            }
        )
    )

    near_duplicate_failures = duplicate_hashes or near_duplicates
    near_duplicate_check = (
        _fail(
            {
                "duplicate_file_hashes": _sample(duplicate_hashes),
                "near_duplicates": _sample(near_duplicates, config.near_duplicate.sample_limit),
                "candidate_pair_count": near_duplicate_debug["candidate_pair_count"],
                "bucket_count": near_duplicate_debug["bucket_count"],
                "skipped_large_buckets": near_duplicate_debug["skipped_large_buckets"],
                "fallback_used": near_duplicate_debug["fallback_used"],
                "similarity_threshold": config.near_duplicate.similarity_threshold,
            }
        )
        if near_duplicate_failures
        else _pass(
            {
                "duplicate_file_hashes": [],
                "near_duplicates": [],
                "candidate_pair_count": near_duplicate_debug["candidate_pair_count"],
                "bucket_count": near_duplicate_debug["bucket_count"],
                "skipped_large_buckets": near_duplicate_debug["skipped_large_buckets"],
                "fallback_used": near_duplicate_debug["fallback_used"],
                "similarity_threshold": config.near_duplicate.similarity_threshold,
            },
            warnings=(
                ["skipped_large_near_duplicate_buckets"]
                if near_duplicate_debug["skipped_large_buckets"] > 0
                else []
            ),
        )
    )

    checks = {
        "schema_validation": schema_validation,
        "duplicate_pdf_id_check": duplicate_pdf_id_check,
        "missing_file_check": missing_file_check,
        "corrupt_pdf_check": corrupt_pdf_check,
        "benign_injection_leak_check": benign_injection_leak_check,
        "injected_metadata_check": injected_metadata_check,
        "regime_field_validation": regime_field_validation,
        "distribution_sanity": distribution_sanity,
        "family_support": family_support,
        "template_support": template_support,
        "regime_support": regime_support,
        "near_duplicate_check": near_duplicate_check,
    }

    overall_pass = all(check["status"] in {"pass", "not_applicable"} for check in checks.values())
    report = {
        "overall_pass": overall_pass,
        "manifest_path": str(manifest_path),
        "config_path": str(config.config_path),
        "row_count": len(rows),
        "generated_count": sum(1 for row in rows if row.get("status") in config.allowed_statuses),
        "stage_counts": _status_counts(rows, stage_by_doc),
        "checks": checks,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
