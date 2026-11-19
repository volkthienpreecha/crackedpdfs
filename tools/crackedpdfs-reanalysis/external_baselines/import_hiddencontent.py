"""Import the HiddenContent.ai per-file results and compare them with the placement audit.

HiddenContent.ai shared ``hiddencontent-crackedpdfs-per-file-2026-09-16.zip``: their production
engine (``0.265.0``, rule pack ``2026.09.10-20``) run over all 29,322 paper v1 PDFs without caller
context or OCR (``structural``), plus a second pass with every page rendered at 300 DPI over the
2,811 files whose release metadata column ``dataset_split`` reads ``test`` (``vision-test-split``).
The archive is the vendor's and is not redistributed here; unpack it and point ``--results-dir``
at the folder holding ``structural.csv``, ``structural.findings.jsonl``, ``structural.run.json``
and the ``vision-test-split.*`` files.

Outputs, written next to the open-source detector tables so ``summarize.py`` picks them up:

* ``hiddencontent_structural_per_file.csv`` and ``_run.json``: the structural pass restricted to
  the frozen paper test split (2,919 files).
* ``hiddencontent_vision_per_file.csv`` and ``_run.json``: the rendered pass restricted to the
  frozen test split. Only the files that fall in both the frozen split and the release metadata
  test column are covered, which is a subsample; the run metadata records it.
* ``hiddencontent/comparison.json`` and ``comparison.md``: split coverage, per-family agreement
  between the vendor's line geometry and the audited glyph geometry, the check of the vendor's
  statement about files whose only finding is off-page text, pair outcomes, and technique mixes.

Scoring. ``flagged`` is the vendor verdict ``suspicious``; ``score`` is the number of hidden
characters the engine reported. See ``crackedpdfs_reanalysis.vendor_results`` for the rules.

Example::

    python import_hiddencontent.py \\
        --results-dir $CRACKEDPDFS_WORK/hiddencontent \\
        --audit $CRACKEDPDFS_WORK/audit-v1/placement-audit.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from baseline_common import ARTIFACT_DIR, DEFAULT_SPLIT, WORK_ROOT, write_run_metadata  # noqa: E402

from crackedpdfs_reanalysis.vendor_results import (  # noqa: E402
    build_report,
    load_audit,
    load_split,
    load_vendor_pass,
    per_file_rows,
    render_markdown,
    write_per_file_csv,
)

SOURCE_NOTE = (
    "Results supplied by HiddenContent.ai (Van Chappell) on 2026-09-16; not run by the authors. "
    "The engine is proprietary; its rules are described in the vendor README that accompanies the results."
)


def _run_metadata(vendor_run: dict, pass_name: str, files: int, subsample: str | None) -> dict:
    meta = {
        "detector": f"hiddencontent_{pass_name}",
        "source": SOURCE_NOTE,
        "command_template": f"vendor engine, pass `{vendor_run.get('pass')}`",
        "commit": "vendor",
        "version": f"engine {vendor_run.get('engine')}, rule pack {vendor_run.get('rulepack')}",
        "python": "n/a",
        "workers": "n/a",
        "wall_clock_seconds": "n/a",
        "renderer": vendor_run.get("renderer"),
        "vendor_run_date": vendor_run.get("date"),
        "corpus_freeze_version": vendor_run.get("corpusFreezeVersion"),
        "files": files,
        "flag_rule": "vendor verdict `suspicious` (at least one finding)",
        "score_rule": "hidden characters reported across the file's findings",
        "errors": 0,
        "timeouts": 0,
    }
    if subsample:
        meta["subsample"] = subsample
    return meta


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--results-dir", type=Path, default=WORK_ROOT / "hiddencontent")
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--audit", type=Path, default=WORK_ROOT / "audit-v1" / "placement-audit.jsonl")
    parser.add_argument("--out-dir", type=Path, default=ARTIFACT_DIR)
    args = parser.parse_args()

    structural = load_vendor_pass(
        args.results_dir / "structural.csv", args.results_dir / "structural.findings.jsonl"
    )
    vision = load_vendor_pass(
        args.results_dir / "vision-test-split.csv", args.results_dir / "vision-test-split.findings.jsonl"
    )
    structural_run = json.loads((args.results_dir / "structural.run.json").read_text(encoding="utf-8"))
    vision_run = json.loads((args.results_dir / "vision-test-split.run.json").read_text(encoding="utf-8"))
    split = load_split(args.split)
    audit = load_audit(args.audit) if args.audit.exists() else {}
    if not audit:
        print(
            f"warning: no placement audit at {args.audit}; geometry comparison will be empty", file=sys.stderr
        )

    structural_rows = per_file_rows(structural, split)
    vision_rows = per_file_rows(vision, split)
    write_per_file_csv(args.out_dir / "hiddencontent_structural_per_file.csv", structural_rows)
    write_per_file_csv(args.out_dir / "hiddencontent_vision_per_file.csv", vision_rows)
    write_run_metadata(
        args.out_dir / "hiddencontent_structural_run.json",
        _run_metadata(structural_run, "structural", len(structural_rows), None),
    )
    triads = len({r["pdf_id"].rsplit(".", 1)[0] for r in vision_rows})
    write_run_metadata(
        args.out_dir / "hiddencontent_vision_run.json",
        _run_metadata(
            vision_run,
            "vision",
            len(vision_rows),
            f"{len(vision_rows)} frozen test files ({triads} triads) that also carry dataset_split=test in the release metadata",
        ),
    )

    report = build_report(structural, vision, split, audit, structural_run)
    report_dir = args.out_dir / "hiddencontent"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (report_dir / "comparison.md").write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(
        f"structural rows {len(structural_rows)}, vision rows {len(vision_rows)}, "
        f"geometry compared {report['geometry']['compared_files']} files "
        f"(agreement {report['geometry']['below_page_agreement_rate']})"
    )


if __name__ == "__main__":
    main()
