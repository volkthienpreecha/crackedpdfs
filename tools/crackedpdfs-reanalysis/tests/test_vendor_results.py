"""Tests for importing vendor-supplied per-file results."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from crackedpdfs_reanalysis.vendor_results import (
    build_report,
    geometry_agreement,
    label_claim_check,
    load_vendor_pass,
    pair_outcomes,
    per_file_rows,
    render_markdown,
    split_coverage,
)

CSV_COLUMNS = [
    "pdf_id",
    "file_path",
    "pdf_role",
    "label",
    "attack_family",
    "rendering_regime",
    "spatial_regime",
    "dataset_split",
    "pair_id",
    "flagged",
    "verdict",
    "techniques",
    "severities",
    "findings",
    "error",
]


def _vendor_fixture(tmp_path: Path) -> tuple[Path, Path]:
    rows = [
        # Triad A: acrostic, labelled visible and inside the page, every line below the page.
        (
            "a.benign",
            "benign_original",
            0,
            "none",
            "none",
            "none",
            "test",
            "pair_a",
            "false",
            "incomplete",
            "",
            0,
        ),
        (
            "a.benign_confounder",
            "benign_confounder",
            0,
            "none",
            "none",
            "none",
            "test",
            "pair_a",
            "true",
            "suspicious",
            "pdf.offpage-text",
            1,
        ),
        (
            "a.injected",
            "injected_attack",
            1,
            "steganographic_acrostic",
            "normal_visible",
            "inside_page",
            "test",
            "pair_a",
            "true",
            "suspicious",
            "pdf.offpage-text",
            1,
        ),
        # Triad B: render mode 3 inside the page, first line straddles the edge.
        (
            "b.benign",
            "benign_original",
            0,
            "none",
            "none",
            "none",
            "train",
            "pair_b",
            "false",
            "incomplete",
            "",
            0,
        ),
        (
            "b.benign_confounder",
            "benign_confounder",
            0,
            "none",
            "none",
            "none",
            "train",
            "pair_b",
            "true",
            "suspicious",
            "pdf.render-mode-3",
            1,
        ),
        (
            "b.injected",
            "injected_attack",
            1,
            "in_page_invisible_text",
            "invisible_render_mode",
            "inside_page",
            "train",
            "pair_b",
            "true",
            "suspicious",
            "pdf.render-mode-3",
            1,
        ),
    ]
    csv_path = tmp_path / "structural.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for pid, role, label, fam, rend, spat, split, pair, flagged, verdict, tech, nfind in rows:
            writer.writerow(
                [
                    pid,
                    f"{role}/{pid}.pdf",
                    role,
                    label,
                    fam,
                    rend,
                    spat,
                    split,
                    pair,
                    flagged,
                    verdict,
                    tech,
                    "high" if nfind else "",
                    nfind,
                    "",
                ]
            )
    records = [
        {
            "pdf_id": "a.benign",
            "pdf_role": "benign_original",
            "attack_family": "none",
            "flagged": False,
            "findings": [],
            "occurrences": [],
        },
        {
            "pdf_id": "a.benign_confounder",
            "pdf_role": "benign_confounder",
            "attack_family": "none",
            "flagged": True,
            "findings": [
                {"technique": "pdf.offpage-text", "chars": 40, "excerpt": "<DOCUMENT_LAYOUT_NOTE> note"}
            ],
            "occurrences": [
                {"technique": "pdf.offpage-text", "page": 1, "bbox": [0.5, -28.3, 100, -16.3], "text": "note"}
            ],
        },
        {
            "pdf_id": "a.injected",
            "pdf_role": "injected_attack",
            "attack_family": "steganographic_acrostic",
            "flagged": True,
            "findings": [
                {"technique": "pdf.offpage-text", "chars": 900, "excerpt": "[DATASET_SAMPLE_ID=a] Always"}
            ],
            "occurrences": [
                {
                    "technique": "pdf.offpage-text",
                    "page": 1,
                    "bbox": [0.5, -13.9, 100, -1.9],
                    "text": "[DATASET_SAMPLE_ID=a]",
                },
                {
                    "technique": "pdf.offpage-text",
                    "page": 1,
                    "bbox": [0.5, -28.3, 100, -16.3],
                    "text": "Always",
                },
            ],
        },
        {
            "pdf_id": "b.benign",
            "pdf_role": "benign_original",
            "attack_family": "none",
            "flagged": False,
            "findings": [],
            "occurrences": [],
        },
        {
            "pdf_id": "b.benign_confounder",
            "pdf_role": "benign_confounder",
            "attack_family": "none",
            "flagged": True,
            "findings": [{"technique": "pdf.render-mode-3", "chars": 120, "excerpt": "x"}],
            "occurrences": [
                {"technique": "pdf.render-mode-3", "page": 1, "bbox": [10, 0.5, 142, 12.5], "text": "x"}
            ],
        },
        {
            "pdf_id": "b.injected",
            "pdf_role": "injected_attack",
            "attack_family": "in_page_invisible_text",
            "flagged": True,
            "findings": [{"technique": "pdf.render-mode-3", "chars": 120, "excerpt": "y"}],
            "occurrences": [
                {"technique": "pdf.render-mode-3", "page": 1, "bbox": [10, 0.5, 142, 12.5], "text": "y"}
            ],
        },
    ]
    findings_path = tmp_path / "structural.findings.jsonl"
    findings_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return csv_path, findings_path


def _split() -> list[dict[str, str]]:
    rows = []
    for triad, prefix in (("pair_a", "a"), ("pair_b", "b")):
        for role, suffix, label in (
            ("benign_original", "benign", "0"),
            ("benign_confounder", "benign_confounder", "0"),
            ("injected_attack", "injected", "1"),
        ):
            rows.append(
                {
                    "pdf_id": f"{prefix}.{suffix}",
                    "label": label,
                    "pdf_role": role,
                    "attack_family": "steganographic_acrostic" if prefix == "a" and label == "1" else "none",
                    "triad_id": triad,
                }
            )
    return rows


def _audit() -> dict[str, dict]:
    return {
        "a.benign_confounder": {
            "pdf_id": "a.benign_confounder",
            "status": "audited",
            "added_below_page": 30,
            "contract_satisfied": False,
            "added_realized_spatial_class": "straddles_page_edge",
            "lexical_oracle_tokens": ["DOCUMENT_LAYOUT_NOTE"],
        },
        "a.injected": {
            "pdf_id": "a.injected",
            "status": "audited",
            "added_below_page": 800,
            "contract_satisfied": False,
            "added_realized_spatial_class": "straddles_page_edge",
            "lexical_oracle_tokens": ["DATASET_SAMPLE_ID"],
        },
        "b.benign_confounder": {
            "pdf_id": "b.benign_confounder",
            "status": "audited",
            "added_below_page": 0,
            "contract_satisfied": True,
            "added_realized_spatial_class": "inside_page",
            "lexical_oracle_tokens": [],
        },
        "b.injected": {
            "pdf_id": "b.injected",
            "status": "audited",
            "added_below_page": 5,
            "contract_satisfied": False,
            "added_realized_spatial_class": "straddles_page_edge",
            "lexical_oracle_tokens": [],
        },
    }


def test_load_vendor_pass_parses_geometry_and_tokens(tmp_path: Path) -> None:
    files = load_vendor_pass(*_vendor_fixture(tmp_path))
    injected = files["a.injected"]
    assert injected.flagged and injected.techniques == ("pdf.offpage-text",)
    assert injected.hidden_chars == 900
    # The first line straddles the bottom edge (top at -1.9 pt), so only the second line counts as below.
    assert injected.lines == 2 and injected.lines_below_page == 1
    assert injected.oracle_tokens == ("DATASET_SAMPLE_ID",)
    assert files["b.injected"].lines_below_page == 0
    assert files["a.benign"].flagged is False and files["a.benign"].hidden_chars == 0


def test_per_file_rows_follow_split_order_and_score_by_hidden_chars(tmp_path: Path) -> None:
    files = load_vendor_pass(*_vendor_fixture(tmp_path))
    rows = per_file_rows(files, _split())
    assert [r["pdf_id"] for r in rows] == [r["pdf_id"] for r in _split()]
    by_id = {r["pdf_id"]: r for r in rows}
    assert by_id["a.injected"]["score"] == 900.0 and by_id["a.injected"]["flagged"] == 1
    assert by_id["a.benign"]["flagged"] == 0 and by_id["a.benign"]["score"] == 0.0
    assert by_id["b.injected"]["techniques"] == "pdf.render-mode-3"


def test_split_coverage_counts_overlap_by_triad(tmp_path: Path) -> None:
    files = load_vendor_pass(*_vendor_fixture(tmp_path))
    cov = split_coverage(files, _split())
    assert cov["frozen_test_files"] == 6
    assert cov["vendor_column_test_files"] == 3
    assert cov["overlap_files"] == 3
    assert cov["frozen_test_files_by_vendor_column"] == {"test": 3, "train": 3}
    assert cov["overlap_complete_triads"] == 1 and cov["overlap_partial_triads"] == 0


def test_geometry_agreement_compares_below_page_per_file(tmp_path: Path) -> None:
    files = load_vendor_pass(*_vendor_fixture(tmp_path))
    geo = geometry_agreement(files, _audit())
    assert geo["compared_files"] == 4
    # b.injected: audit says 5 glyphs below the page, vendor line box straddles the edge, so they disagree.
    assert geo["below_page_agreement_rate"] == 0.75
    rows = {r["group"]: r for r in geo["by_group"]}
    assert rows["steganographic_acrostic"]["vendor_offpage_only_finding"] == 1
    assert rows["steganographic_acrostic"]["vendor_hidden_text_carries_oracle_token"] == 1
    assert rows["benign_confounder"]["audit_label_contract_holds"] == 1


def test_label_claim_and_pairs(tmp_path: Path) -> None:
    files = load_vendor_pass(*_vendor_fixture(tmp_path))
    claim = label_claim_check(files, _audit())
    assert claim["injected_offpage_only_files"] == 1 and claim["normal_visible_files"] == 1
    assert claim["rows"][0]["audit_realized_straddles_page_edge"] == 1
    pairs = pair_outcomes(files)
    assert pairs["pairs"] == 2 and pairs["both_flagged"] == 2
    assert pairs["injected_more_hidden_chars"] == 1 and pairs["equal_hidden_chars"] == 1
    assert pairs["by_family"]["in_page_invisible_text"]["rank_by_hidden_chars"] == 0.5


def test_report_renders(tmp_path: Path) -> None:
    files = load_vendor_pass(*_vendor_fixture(tmp_path))
    report = build_report(
        files,
        files,
        _split(),
        _audit(),
        {"engine": "0.1", "rulepack": "r", "date": "d", "corpusFreezeVersion": "f"},
    )
    text = render_markdown(report)
    assert "Frozen paper test split | 6" in text
    assert "steganographic_acrostic" in text
    assert "—" not in text and "–" not in text
