"""Run wppoland/hidden-text-detector over the frozen test split.

Setup (see README.md in this directory)::

    cd $CRACKEDPDFS_WORK/baselines
    git clone https://github.com/wppoland/hidden-text-detector
    cd hidden-text-detector
    uv venv --python 3.13 .venv
    uv pip install --python .venv/bin/python -r requirements.txt

Per-file command::

    .venv/bin/python scripts/scan.py --json <pdf>

Scoring. ``flagged`` is 1 when at least one finding has severity ``CRITICAL``, which mirrors the
tool's own exit-code rule (exit 1 only on a critical finding). ``score`` is
``critical_count + 0.1 * warning_count`` so that documents with only warnings rank above clean
documents and below any document with a critical finding. ``techniques`` lists the distinct
finding types with severity CRITICAL or WARNING, joined with ``|``. INFO findings (for example a
full-page OCR text layer) are ignored for both flagging and scoring, matching the tool's verdict.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline_common import (  # noqa: E402
    ARTIFACT_DIR,
    DEFAULT_BASELINES_ROOT,
    DEFAULT_PDF_ROOT,
    DEFAULT_SPLIT,
    FileResult,
    SplitRow,
    extract_json_payload,
    git_commit,
    load_split,
    python_version,
    run_command,
    run_pool,
    write_per_file_csv,
    write_run_metadata,
)

DETECTOR_NAME = "hidden_text_detector"
REPO_DIR = DEFAULT_BASELINES_ROOT / "hidden-text-detector"
PYTHON = REPO_DIR / ".venv" / "bin" / "python"
SCRIPT = REPO_DIR / "scripts" / "scan.py"
PDF_ROOT = DEFAULT_PDF_ROOT
TIMEOUT_SECONDS = 120.0


def scan_one(row: SplitRow) -> FileResult:
    """Scan a single PDF and reduce the JSON findings to the shared result layout."""
    pdf_path = PDF_ROOT / row.file_path
    cmd = [str(PYTHON), str(SCRIPT), "--json", str(pdf_path)]
    env = dict(os.environ, PYTHONWARNINGS="ignore")
    code, out, err, seconds, timed_out = run_command(cmd, TIMEOUT_SECONDS, env=env, cwd=REPO_DIR)
    base = dict(
        pdf_id=row.pdf_id,
        label=row.label,
        pdf_role=row.pdf_role,
        attack_family=row.attack_family,
        seconds=seconds,
    )
    if timed_out:
        return FileResult(flagged=0, score=0.0, techniques="", error="timeout", **base)
    try:
        payload = extract_json_payload(out)
    except ValueError:
        detail = (err.strip().splitlines() or ["no output"])[-1]
        return FileResult(flagged=0, score=0.0, techniques="", error=f"exit={code}: {detail}"[:500], **base)
    findings = []
    if isinstance(payload, dict):
        for value in payload.values():
            findings.extend(value)
    critical = [f for f in findings if f.get("severity") == "CRITICAL"]
    warnings = [f for f in findings if f.get("severity") == "WARNING"]
    techniques = sorted({f.get("type", "") for f in critical + warnings})
    error = ""
    if "ERROR scanning" in err:
        error = "scan_error: " + err.strip().splitlines()[-1][:400]
    return FileResult(
        flagged=int(bool(critical)),
        score=len(critical) + 0.1 * len(warnings),
        techniques="|".join(techniques),
        error=error,
        **base,
    )


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=None, help="only process the first N rows (smoke test)")
    parser.add_argument("--out-dir", type=Path, default=ARTIFACT_DIR)
    args = parser.parse_args()

    rows = load_split(args.split)
    if args.limit:
        rows = rows[: args.limit]
    started = time.perf_counter()
    results = run_pool(rows, scan_one, args.workers)
    wall = time.perf_counter() - started

    out_csv = args.out_dir / f"{DETECTOR_NAME}_per_file.csv"
    write_per_file_csv(out_csv, results)
    write_run_metadata(
        args.out_dir / f"{DETECTOR_NAME}_run.json",
        {
            "detector": DETECTOR_NAME,
            "repository": "https://github.com/wppoland/hidden-text-detector",
            "license": "MIT",
            "commit": git_commit(REPO_DIR),
            "version": "unversioned (no release tags); commit SHA identifies the build",
            "python": python_version(PYTHON),
            "command_template": f"{PYTHON} {SCRIPT} --json <pdf>",
            "flag_rule": "any finding with severity CRITICAL",
            "score_rule": "critical_count + 0.1 * warning_count",
            "timeout_seconds": TIMEOUT_SECONDS,
            "workers": args.workers,
            "files": len(results),
            "wall_clock_seconds": round(wall, 1),
            "errors": sum(1 for r in results if r.error and r.error != "timeout"),
            "timeouts": sum(1 for r in results if r.error == "timeout"),
        },
    )
    print(f"wrote {out_csv} ({len(results)} rows) in {wall:,.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
