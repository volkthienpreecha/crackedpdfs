"""Audit a CrackedPDFs-layout corpus: measured placement versus labels."""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from collections.abc import Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import median

from .contracts import CONTRACTS, contract_satisfied, lexical_oracle_hits
from .geometry import PageGlyphs, added_glyphs, extract_glyphs, summarize_glyphs

AUDITED_ROLES = ("injected_attack", "benign_confounder")


@dataclass(frozen=True)
class AuditTask:
    pdf_id: str
    sample_id: str
    role: str
    family: str
    strength: str
    spatial_label: str
    rendering_label: str
    path: str
    reference_path: str | None
    reference_expected: bool
    render: bool
    require_reference: bool = True


def read_metadata(path: str | Path) -> list[dict[str, object]]:
    path = Path(path)
    if path.suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SystemExit(
                "Reading parquet needs pyarrow: pip install 'crackedpdfs-audit[parquet]'"
            ) from exc
        return pq.read_table(path).to_pylist()
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_tasks(
    rows: Iterable[dict[str, object]],
    root: str | Path,
    render: bool = False,
    families: set[str] | None = None,
    paired: bool = True,
) -> list[AuditTask]:
    root = Path(root)
    rows = list(rows)
    originals = {
        str(row["sample_id"]): str(row["file_path"])
        for row in rows
        if row.get("pdf_role") == "benign_original"
    }
    tasks: list[AuditTask] = []
    for row in rows:
        role = str(row.get("pdf_role"))
        if role not in AUDITED_ROLES:
            continue
        family = str(row.get("target_attack_family") or row.get("attack_family"))
        if families and family not in families:
            continue
        prefix = "target" if role == "injected_attack" else "confounder"
        # Missing PDFs are never silently dropped: a task is still built so the
        # output has one record per audited metadata row, marked missing.
        path = root / str(row["file_path"])
        reference = originals.get(str(row["sample_id"]))
        reference_path = root / reference if reference else None
        tasks.append(
            AuditTask(
                pdf_id=str(row["pdf_id"]),
                sample_id=str(row["sample_id"]),
                role=role,
                family=family,
                strength=str(row.get(f"{prefix}_physical_attack_strength") or row.get("attack_strength")),
                spatial_label=str(row.get(f"{prefix}_physical_spatial_regime") or row.get("spatial_regime")),
                rendering_label=str(
                    row.get(f"{prefix}_physical_rendering_regime") or row.get("rendering_regime")
                ),
                path=str(path),
                reference_path=str(reference_path) if reference_path and reference_path.exists() else None,
                # In paired mode every injected or confounder sample must have a
                # benign_original row. Without one, document text would be
                # counted as added text, so a missing row is an error, not an
                # unpaired audit.
                reference_expected=reference is not None,
                render=render,
                require_reference=paired,
            )
        )
    return tasks


@lru_cache(maxsize=256)
def _cached_pages(path: str) -> tuple[PageGlyphs, ...]:
    return tuple(extract_glyphs(path))


def _merge_page_summaries(summaries: list) -> dict[str, object]:
    fields = [
        "glyphs",
        "inside",
        "clipped",
        "outside",
        "below_page",
        "above_page",
        "left_of_page",
        "right_of_page",
        "invisible_render_mode",
        "tiny_font",
        "low_contrast_fill",
        "likely_visible",
    ]
    merged = {field: sum(getattr(s, field) for s in summaries) for field in fields}
    classes = {s.realized_spatial_class for s in summaries}
    merged["realized_spatial_class"] = classes.pop() if len(classes) == 1 else "mixed"
    preview = "".join(s.text_preview for s in summaries)[:120]
    merged["text_preview"] = preview
    return merged


def audit_task(task: AuditTask) -> dict[str, object]:
    record: dict[str, object] = {
        "pdf_id": task.pdf_id,
        "sample_id": task.sample_id,
        "role": task.role,
        "family": task.family,
        "strength": task.strength,
        "spatial_label": task.spatial_label,
        "rendering_label": task.rendering_label,
        "reference_expected": task.reference_expected,
        "has_reference": task.reference_path is not None,
        "paired": task.require_reference,
        "status": "audited",
        "error": None,
    }
    if not Path(task.path).exists():
        record["status"] = "missing"
        record["error"] = f"file not found: {task.path}"
        return record
    if task.require_reference and task.reference_path is None:
        # A pair audit without its clean original would count the whole document
        # as injected text, so it is reported as an error rather than guessed.
        record["status"] = "reference_missing"
        record["error"] = (
            "no benign_original metadata row for this sample; pair not audited"
            if not task.reference_expected
            else "benign original file is missing; pair not audited"
        )
        return record
    try:
        pages = list(_cached_pages(task.path))
        references = list(_cached_pages(task.reference_path)) if task.reference_path else []
        page_summaries = []
        contract_flags = []
        payload_pages = []
        oracle_tokens: set[str] = set()
        for index, page in enumerate(pages):
            reference = references[index] if index < len(references) else None
            extra = added_glyphs(page, reference)
            summary = summarize_glyphs(extra, page.page_box)
            page_summaries.append(summary)
            oracle_tokens.update(lexical_oracle_hits("".join(g.text for g in page.glyphs)))
            # Only pages that actually carry added text can satisfy or violate a
            # placement contract. An untouched page is not a placement failure.
            if summary.glyphs:
                payload_pages.append(index + 1)
                contract_flags.append(contract_satisfied(task.spatial_label, extra, page.page_box))
        scored = [page_summaries[page - 1] for page in payload_pages]
        merged = _merge_page_summaries(scored) if scored else _merge_page_summaries(page_summaries)
        record.update({f"added_{key}": value for key, value in merged.items()})
        record["pages"] = len(pages)
        record["payload_pages"] = payload_pages
        record["page_box"] = list(pages[0].page_box) if pages else None
        record["lexical_oracle_tokens"] = sorted(oracle_tokens)
        if not payload_pages:
            # No added text anywhere is not a pass: the payload is unaccounted for.
            record["status"] = "no_payload_detected"
            record["contract_satisfied"] = None
            record["error"] = "no added glyphs found relative to the reference"
        else:
            verdicts = [flag for flag in contract_flags if flag is not None]
            record["contract_satisfied"] = all(verdicts) if verdicts else None
        if task.render and task.reference_path:
            from .render import pixel_diff

            diff = pixel_diff(task.path, task.reference_path)
            record["changed_pixels_72dpi"] = diff.changed_pixels if diff else None
            if diff:
                record["changed_pixels_by_page"] = diff.changed_pixels_by_page
                record["render_compared_pages"] = diff.compared_pages
                record["render_page_count_mismatch"] = diff.page_count_mismatch
                record["render_dimension_mismatch_pages"] = diff.dimension_mismatch_pages
    except Exception as exc:  # keep auditing the corpus; report the failure per file
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def run_audit(tasks: list[AuditTask], workers: int | None = None) -> Iterator[dict[str, object]]:
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1:
        yield from map(audit_task, tasks)
        return
    # Sort by sample so each worker's reference cache stays warm.
    ordered = sorted(tasks, key=lambda task: task.sample_id)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        yield from pool.map(audit_task, ordered, chunksize=16)


def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        if record.get("error"):
            continue
        groups[(str(record["role"]), str(record["family"]), str(record["spatial_label"]))].append(record)

    rows: list[dict[str, object]] = []
    for (role, family, label), items in sorted(groups.items()):
        glyphs = sum(int(item["added_glyphs"]) for item in items)
        realized: dict[str, int] = defaultdict(int)
        for item in items:
            realized[str(item["added_realized_spatial_class"])] += 1
        pixels = [
            int(item["changed_pixels_72dpi"])
            for item in items
            if item.get("changed_pixels_72dpi") is not None
        ]
        contract = [
            bool(item["contract_satisfied"]) for item in items if item.get("contract_satisfied") is not None
        ]
        rows.append(
            {
                "role": role,
                "family": family,
                "spatial_label": label,
                "pdfs": len(items),
                "mean_added_glyphs": round(glyphs / len(items), 1),
                "frac_glyphs_inside": round(sum(int(i["added_inside"]) for i in items) / glyphs, 4)
                if glyphs
                else None,
                "frac_glyphs_clipped": round(sum(int(i["added_clipped"]) for i in items) / glyphs, 4)
                if glyphs
                else None,
                "frac_glyphs_outside": round(sum(int(i["added_outside"]) for i in items) / glyphs, 4)
                if glyphs
                else None,
                "frac_glyphs_below_page": round(sum(int(i["added_below_page"]) for i in items) / glyphs, 4)
                if glyphs
                else None,
                "realized_classes": ";".join(f"{key}={value}" for key, value in sorted(realized.items())),
                "label_contract_rate": _rate(contract),
                "median_changed_pixels_72dpi": median(pixels) if pixels else None,
                "oracle_token_rate": _rate([bool(item["lexical_oracle_tokens"]) for item in items]),
            }
        )
    return rows


def coverage(records: list[dict[str, object]], expected: int | None = None) -> dict[str, int]:
    """Counts of what was expected, found, audited, and what went wrong."""
    by_status: dict[str, int] = defaultdict(int)
    for record in records:
        by_status[str(record.get("status", "audited"))] += 1
    audited = by_status.get("audited", 0)
    return {
        "expected": expected if expected is not None else len(records),
        "records": len(records),
        "audited": audited,
        "missing": by_status.get("missing", 0),
        "reference_missing": by_status.get("reference_missing", 0),
        "no_payload_detected": by_status.get("no_payload_detected", 0),
        "errors": by_status.get("error", 0),
        "multi_page": sum(1 for r in records if isinstance(r.get("pages"), int) and r["pages"] > 1),
    }


def coverage_complete(cov: dict[str, int]) -> bool:
    """True only when every audited row produced a usable placement verdict."""
    return (
        cov["missing"] == 0
        and cov["reference_missing"] == 0
        and cov["no_payload_detected"] == 0
        and cov["errors"] == 0
    )


def write_outputs(records: list[dict[str, object]], out_dir: str | Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / "placement-audit.jsonl"
    with records_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    cov = coverage(records)
    coverage_path = out_dir / "placement-audit-coverage.json"
    coverage_path.write_text(json.dumps(cov, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = summarize_records(records)
    summary_path = out_dir / "placement-audit-summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        if summary:
            writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()))
            writer.writeheader()
            writer.writerows(summary)

    markdown_path = out_dir / "placement-audit-summary.md"
    lines = [
        "# Placement audit",
        "",
        f"Records: {cov['records']:,}. Audited: {cov['audited']:,}. "
        f"Missing PDFs: {cov['missing']:,}. Missing references: {cov['reference_missing']:,}. "
        f"No payload detected: {cov['no_payload_detected']:,}. "
        f"Extraction errors: {cov['errors']:,}. Multi-page PDFs: {cov['multi_page']:,}.",
        "",
        "Label contracts:",
        "",
        *[f"- `{label}`: {text}." for label, text in CONTRACTS.items()],
        "",
        "| Role | Family | Label | PDFs | Mean added glyphs | Inside | Clipped | Outside | Below page | Label contract | Oracle tokens |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def fmt(value: object) -> str:
        return "n/a" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))

    for row in summary:
        lines.append(
            f"| {row['role']} | {row['family']} | {row['spatial_label']} | {row['pdfs']:,} | "
            f"{row['mean_added_glyphs']:,} | {fmt(row['frac_glyphs_inside'])} | {fmt(row['frac_glyphs_clipped'])} | "
            f"{fmt(row['frac_glyphs_outside'])} | {fmt(row['frac_glyphs_below_page'])} | "
            f"{fmt(row['label_contract_rate'])} | {fmt(row['oracle_token_rate'])} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "records": records_path,
        "coverage": coverage_path,
        "summary_csv": summary_path,
        "summary_markdown": markdown_path,
    }
