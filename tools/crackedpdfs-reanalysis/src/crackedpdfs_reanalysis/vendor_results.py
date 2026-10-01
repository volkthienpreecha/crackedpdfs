"""Import vendor-supplied per-file detector results and compare them with the placement audit.

HiddenContent.ai ran their production engine over the complete paper v1 corpus and shared the
per-file output (one CSV row and one findings record per PDF, two passes). This module reduces
that output to the per-file layout used by ``external_baselines/summarize.py`` so the engine can
be reported next to the open-source detectors, and it checks the vendor's geometry against the
independent ``crackedpdfs-audit`` placement audit of the same files.

Scoring for the per-file tables. ``flagged`` is the vendor's own verdict (``suspicious``).
``score`` is the number of hidden characters the engine reported for the file, so that the paired
ranking statistic measures whether the amount of hidden text separates a pair; the flag alone
cannot, because every injected PDF and every confounder is flagged.

Geometry. The vendor records every hidden line with its bounding box in PDF user space. A line
is counted as below the page when the top of its box lies more than ``BELOW_PAGE_TOLERANCE_PT``
below the page's bottom edge, which is the rule stated in the vendor's README. The audit records
glyph counts, so the two are compared per file as "any text below the page" versus "any added
glyph below the page", and per family as rates.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BELOW_PAGE_TOLERANCE_PT = 2.0

ORACLE_TOKENS = (
    "DATASET_SAMPLE_ID",
    "MESSAGE_TYPE=",
    "SYSTEM_POLICY_DO_NOT_REMOVE",
    "DOCUMENT_LAYOUT_NOTE",
)

PER_FILE_COLUMNS = [
    "pdf_id",
    "label",
    "pdf_role",
    "attack_family",
    "flagged",
    "score",
    "techniques",
    "error",
    "seconds",
]


@dataclass(frozen=True)
class VendorFile:
    """One PDF as reported by the vendor engine."""

    pdf_id: str
    pdf_role: str
    attack_family: str
    rendering_regime: str
    spatial_regime: str
    dataset_split: str
    pair_id: str
    flagged: bool
    verdict: str
    techniques: tuple[str, ...]
    hidden_chars: int
    lines: int
    lines_below_page: int
    oracle_tokens: tuple[str, ...]
    occurrences_truncated: bool


def _hidden_text(record: dict[str, Any]) -> str:
    parts = [str(o.get("text", "")) for o in record.get("occurrences", [])]
    parts.extend(str(f.get("excerpt", "")) for f in record.get("findings", []))
    return "\n".join(parts)


def _line_below_page(bbox: list[float]) -> bool:
    # bbox is [x0, y0, x1, y1] with the origin at the page's bottom-left corner.
    return float(bbox[3]) < -BELOW_PAGE_TOLERANCE_PT


def load_vendor_pass(csv_path: Path, findings_path: Path) -> dict[str, VendorFile]:
    """Join the vendor's per-file CSV with its findings records."""
    findings: dict[str, dict[str, Any]] = {}
    with findings_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                findings[str(record["pdf_id"])] = record
    files: dict[str, VendorFile] = {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            record = findings.get(row["pdf_id"], {})
            occurrences = record.get("occurrences", [])
            text = _hidden_text(record)
            files[row["pdf_id"]] = VendorFile(
                pdf_id=row["pdf_id"],
                pdf_role=row["pdf_role"],
                attack_family=row["attack_family"],
                rendering_regime=row["rendering_regime"],
                spatial_regime=row["spatial_regime"],
                dataset_split=row["dataset_split"],
                pair_id=row["pair_id"],
                flagged=row["flagged"].strip().lower() == "true",
                verdict=row["verdict"],
                techniques=tuple(t for t in row["techniques"].split(";") if t),
                hidden_chars=sum(int(f.get("chars", 0)) for f in record.get("findings", [])),
                lines=len(occurrences),
                lines_below_page=sum(1 for o in occurrences if _line_below_page(o["bbox"])),
                oracle_tokens=tuple(t for t in ORACLE_TOKENS if t in text),
                occurrences_truncated=bool(record.get("occurrencesTruncated", False)),
            )
    return files


def load_split(path: Path) -> list[dict[str, str]]:
    """Read the frozen test split listing."""
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def per_file_rows(files: dict[str, VendorFile], split: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Rows in the shared per-file layout for the split members the vendor pass covers."""
    rows = []
    for item in split:
        vendor = files.get(item["pdf_id"])
        if vendor is None:
            continue
        rows.append(
            {
                "pdf_id": item["pdf_id"],
                "label": int(item["label"]),
                "pdf_role": item["pdf_role"],
                "attack_family": item["attack_family"],
                "flagged": int(vendor.flagged),
                "score": float(vendor.hidden_chars),
                "techniques": "|".join(vendor.techniques),
                "error": "",
                "seconds": "0.000",
            }
        )
    return rows


def write_per_file_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write per-file rows with the shared column layout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PER_FILE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def split_coverage(files: dict[str, VendorFile], split: list[dict[str, str]]) -> dict[str, Any]:
    """How the vendor's ``dataset_split`` column relates to the frozen test split."""
    frozen_ids = {r["pdf_id"] for r in split}
    vendor_test = {pid for pid, f in files.items() if f.dataset_split == "test"}
    triads: dict[str, set[str]] = defaultdict(set)
    for item in split:
        if item["pdf_id"] in vendor_test:
            triads[item["triad_id"]].add(item["pdf_role"])
    return {
        "frozen_test_files": len(frozen_ids),
        "vendor_column_test_files": len(vendor_test),
        "overlap_files": len(frozen_ids & vendor_test),
        "frozen_test_files_by_vendor_column": dict(
            Counter(files[pid].dataset_split for pid in frozen_ids if pid in files)
        ),
        "frozen_test_files_missing_from_vendor": len(frozen_ids - set(files)),
        "overlap_complete_triads": sum(1 for roles in triads.values() if len(roles) == 3),
        "overlap_partial_triads": sum(1 for roles in triads.values() if len(roles) < 3),
    }


def load_audit(path: Path) -> dict[str, dict[str, Any]]:
    """Read ``placement-audit.jsonl`` keyed by ``pdf_id``."""
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[str(record["pdf_id"])] = record
    return records


def _group_key(vendor: VendorFile) -> str:
    return vendor.attack_family if vendor.pdf_role == "injected_attack" else vendor.pdf_role


def geometry_agreement(files: dict[str, VendorFile], audit: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Per-file and per-group agreement between vendor line geometry and audited glyph geometry."""
    groups: dict[str, Counter] = defaultdict(Counter)
    total = Counter()
    for pid, vendor in files.items():
        if vendor.pdf_role == "benign_original":
            continue
        record = audit.get(pid)
        key = _group_key(vendor)
        groups[key]["files"] += 1
        groups[key]["vendor_any_below"] += int(vendor.lines_below_page > 0)
        groups[key]["vendor_offpage_only"] += int(vendor.techniques == ("pdf.offpage-text",))
        groups[key]["vendor_oracle_token"] += int(bool(vendor.oracle_tokens))
        if record is None or record.get("status") != "audited":
            groups[key]["audit_missing"] += 1
            continue
        audit_below = int(record.get("added_below_page", 0)) > 0
        groups[key]["audit_any_below"] += int(audit_below)
        groups[key]["audit_contract_holds"] += int(bool(record.get("contract_satisfied")))
        groups[key]["audit_oracle_token"] += int(bool(record.get("lexical_oracle_tokens")))
        agree = audit_below == (vendor.lines_below_page > 0)
        groups[key]["below_page_agree"] += int(agree)
        total["compared"] += 1
        total["below_page_agree"] += int(agree)
    table = []
    for key in sorted(groups):
        g = groups[key]
        compared = g["files"] - g["audit_missing"]
        table.append(
            {
                "group": key,
                "files": g["files"],
                "vendor_any_below_page": g["vendor_any_below"],
                "audit_any_below_page": g["audit_any_below"],
                "below_page_agreement_rate": round(g["below_page_agree"] / compared, 4) if compared else None,
                "vendor_offpage_only_finding": g["vendor_offpage_only"],
                "audit_label_contract_holds": g["audit_contract_holds"],
                "vendor_hidden_text_carries_oracle_token": g["vendor_oracle_token"],
                "audit_oracle_token": g["audit_oracle_token"],
                "audit_missing": g["audit_missing"],
            }
        )
    return {
        "compared_files": total["compared"],
        "below_page_agreement_rate": round(total["below_page_agree"] / total["compared"], 4)
        if total["compared"]
        else None,
        "by_group": table,
    }


def label_claim_check(files: dict[str, VendorFile], audit: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Check the vendor's statement about injected files whose only finding is off-page text.

    The vendor reported that 1,446 injected files labelled ``normal_visible`` would not be flagged
    on a corpus whose text sits on the page as ordinary visible text. The check lists those files
    by family and label and reports how the audit classifies their placement.
    """
    rows: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for pid, vendor in files.items():
        if vendor.pdf_role != "injected_attack" or vendor.techniques != ("pdf.offpage-text",):
            continue
        key = (vendor.attack_family, vendor.rendering_regime, vendor.spatial_regime)
        rows[key]["files"] += 1
        record = audit.get(pid)
        if record and record.get("status") == "audited":
            rows[key][f"audit_realized_{record.get('added_realized_spatial_class')}"] += 1
            rows[key]["audit_contract_holds"] += int(bool(record.get("contract_satisfied")))
    table = []
    for (family, rendering, spatial), counts in sorted(rows.items()):
        entry = {"attack_family": family, "rendering_regime": rendering, "spatial_regime": spatial}
        entry.update(dict(counts))
        table.append(entry)
    normal_visible = sum(r["files"] for r in table if r["rendering_regime"] == "normal_visible")
    return {
        "injected_offpage_only_files": sum(r["files"] for r in table),
        "normal_visible_files": normal_visible,
        "rows": table,
    }


def pair_outcomes(files: dict[str, VendorFile]) -> dict[str, Any]:
    """Within each pair, compare the vendor's flag and hidden-character count across roles."""
    pairs: dict[str, dict[str, VendorFile]] = defaultdict(dict)
    for vendor in files.values():
        if vendor.pdf_role in ("injected_attack", "benign_confounder"):
            pairs[vendor.pair_id][vendor.pdf_role] = vendor
    counts = Counter()
    by_family: dict[str, Counter] = defaultdict(Counter)
    for members in pairs.values():
        if len(members) != 2:
            continue
        injected, confounder = members["injected_attack"], members["benign_confounder"]
        counts["pairs"] += 1
        counts["both_flagged"] += int(injected.flagged and confounder.flagged)
        fam = by_family[injected.attack_family]
        fam["pairs"] += 1
        if injected.hidden_chars > confounder.hidden_chars:
            counts["injected_more_hidden_chars"] += 1
            fam["injected_longer"] += 1
        elif injected.hidden_chars < confounder.hidden_chars:
            counts["confounder_more_hidden_chars"] += 1
            fam["confounder_longer"] += 1
        else:
            counts["equal_hidden_chars"] += 1
            fam["equal"] += 1
    return {
        **dict(counts),
        "by_family": {
            k: {
                "pairs": v["pairs"],
                "injected_longer": v["injected_longer"],
                "confounder_longer": v["confounder_longer"],
                "equal": v["equal"],
                "rank_by_hidden_chars": round((v["injected_longer"] + 0.5 * v["equal"]) / v["pairs"], 4),
            }
            for k, v in sorted(by_family.items())
        },
    }


def technique_rates(files: dict[str, VendorFile]) -> dict[str, dict[str, int]]:
    """Technique combinations per group."""
    out: dict[str, Counter] = defaultdict(Counter)
    for vendor in files.values():
        if vendor.pdf_role == "benign_original":
            continue
        out[_group_key(vendor)][";".join(vendor.techniques) or "none"] += 1
    return {k: dict(v.most_common()) for k, v in sorted(out.items())}


def render_markdown(report: dict[str, Any]) -> str:
    """Render the comparison report as Markdown."""
    lines = ["# HiddenContent.ai per-file results against the placement audit", ""]
    run = report["vendor_run"]
    lines.append(
        f"Vendor engine `{run.get('engine')}`, rule pack `{run.get('rulepack')}`, run on "
        f"{run.get('date')} over corpus freeze `{run.get('corpusFreezeVersion')}`. The structural pass covers "
        f"all {report['structural_files']:,} files; the rendered pass covers the {report['vision_files']:,} files "
        "whose release metadata column `dataset_split` reads `test`."
    )
    lines.append("")
    lines.append("## Which test split the rendered pass used")
    lines.append("")
    cov = report["split_coverage"]
    lines.append("| Quantity | Files |")
    lines.append("|---|---:|")
    lines.append(f"| Frozen paper test split | {cov['frozen_test_files']:,} |")
    lines.append(f"| Release metadata `dataset_split = test` | {cov['vendor_column_test_files']:,} |")
    lines.append(f"| In both | {cov['overlap_files']:,} |")
    lines.append(
        "| Frozen test files by release column | "
        + ", ".join(f"{k} {v:,}" for k, v in sorted(cov["frozen_test_files_by_vendor_column"].items()))
        + " |"
    )
    lines.append(f"| Complete triads in the overlap | {cov['overlap_complete_triads']:,} |")
    lines.append("")
    lines.append("## Text below the page: vendor lines versus audited glyphs")
    lines.append("")
    geo = report["geometry"]
    lines.append(
        f"Per-file agreement on whether any hidden text lies below the page: "
        f"{geo['below_page_agreement_rate']:.4f} over {geo['compared_files']:,} injected and confounder files."
    )
    lines.append("")
    lines.append(
        "| Group | Files | Vendor: any line below page | Audit: any glyph below page | Agreement | "
        "Vendor: off-page is only finding | Audit: label contract holds | Vendor hidden text carries a role token |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for row in geo["by_group"]:
        agree = row["below_page_agreement_rate"]
        lines.append(
            f"| {row['group']} | {row['files']:,} | {row['vendor_any_below_page']:,} | {row['audit_any_below_page']:,} | "
            f"{agree:.3f} | {row['vendor_offpage_only_finding']:,} | {row['audit_label_contract_holds']:,} | "
            f"{row['vendor_hidden_text_carries_oracle_token']:,} |"
            if agree is not None
            else f"| {row['group']} | {row['files']:,} | {row['vendor_any_below_page']:,} | n/a | n/a | "
            f"{row['vendor_offpage_only_finding']:,} | n/a | {row['vendor_hidden_text_carries_oracle_token']:,} |"
        )
    lines.append("")
    lines.append("## Injected files whose only vendor finding is off-page text")
    lines.append("")
    claim = report["label_claim"]
    lines.append(
        f"{claim['injected_offpage_only_files']:,} injected files, {claim['normal_visible_files']:,} of them labelled "
        "`normal_visible`. The audit's realized placement class for each group is listed."
    )
    lines.append("")
    lines.append(
        "| Attack family | Rendering label | Spatial label | Files | Audit realized class | Audit contract holds |"
    )
    lines.append("|---|---|---|---:|---|---:|")
    for row in claim["rows"]:
        realized = ", ".join(
            f"{k[len('audit_realized_') :]} {v:,}" for k, v in row.items() if k.startswith("audit_realized_")
        )
        lines.append(
            f"| {row['attack_family']} | {row['rendering_regime']} | {row['spatial_regime']} | {row['files']:,} | "
            f"{realized or 'n/a'} | {row.get('audit_contract_holds', 0):,} |"
        )
    lines.append("")
    lines.append("## Pairs")
    lines.append("")
    pairs = report["pairs"]
    lines.append(
        f"{pairs['pairs']:,} pairs; both members flagged in {pairs['both_flagged']:,}. Hidden characters reported by the "
        f"engine: injected longer in {pairs.get('injected_more_hidden_chars', 0):,}, confounder longer in "
        f"{pairs.get('confounder_more_hidden_chars', 0):,}, equal in {pairs.get('equal_hidden_chars', 0):,}."
    )
    lines.append("")
    lines.append(
        "| Attack family | Pairs | Injected longer | Confounder longer | Equal | Rank by hidden characters |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    for fam, v in pairs["by_family"].items():
        lines.append(
            f"| {fam} | {v['pairs']:,} | {v['injected_longer']:,} | {v['confounder_longer']:,} | {v['equal']:,} | "
            f"{v['rank_by_hidden_chars']:.3f} |"
        )
    lines.append("")
    lines.append("## Technique combinations reported per group (structural pass)")
    lines.append("")
    lines.append("| Group | Techniques | Files |")
    lines.append("|---|---|---:|")
    for group, combos in report["techniques"].items():
        for combo, n in combos.items():
            lines.append(f"| {group} | `{combo}` | {n:,} |")
    lines.append("")
    return "\n".join(lines)


def build_report(
    structural: dict[str, VendorFile],
    vision: dict[str, VendorFile],
    split: list[dict[str, str]],
    audit: dict[str, dict[str, Any]],
    vendor_run: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the comparison report."""
    return {
        "vendor_run": vendor_run,
        "structural_files": len(structural),
        "vision_files": len(vision),
        "split_coverage": split_coverage(structural, split),
        "geometry": geometry_agreement(structural, audit),
        "label_claim": label_claim_check(structural, audit),
        "pairs": pair_outcomes(structural),
        "techniques": technique_rates(structural),
    }
