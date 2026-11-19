"""Run Andy8647/pdf-injection-scanner over the frozen test split.

Setup (see README.md in this directory)::

    cd $CRACKEDPDFS_WORK/baselines
    git clone https://github.com/Andy8647/pdf-injection-scanner
    cd pdf-injection-scanner
    uv venv --python 3.13 .venv
    uv pip install --python .venv/bin/python -e .

Per-file command::

    .venv/bin/pdf-scan --json <pdf>

Scoring. The tool reports every finding as a "potential injection" and has no exit-code verdict,
so ``flagged`` is 1 when the JSON array is non-empty. Structural findings (White/Invisible Text,
Tiny Text, Off-Page Text) carry severity ``high``; the regex-based Suspicious Pattern finding
carries severity ``medium``. ``score`` is ``high_count + 0.1 * medium_count``. ``techniques``
lists the distinct finding types joined with ``|``.
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

DETECTOR_NAME = "pdf_injection_scanner"
REPO_DIR = DEFAULT_BASELINES_ROOT / "pdf-injection-scanner"
PYTHON = REPO_DIR / ".venv" / "bin" / "python"
CLI = REPO_DIR / ".venv" / "bin" / "pdf-scan"
PDF_ROOT = DEFAULT_PDF_ROOT
TIMEOUT_SECONDS = 120.0


def scan_one(row: SplitRow) -> FileResult:
    """Scan a single PDF and reduce the JSON findings to the shared result layout."""
    pdf_path = PDF_ROOT / row.file_path
    cmd = [str(CLI), "--json", str(pdf_path)]
    env = dict(os.environ, PYTHONWARNINGS="ignore", TERM="dumb", NO_COLOR="1", COLUMNS="200")
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
        detail = ((err.strip() or out.strip()).splitlines() or ["no output"])[-1]
        return FileResult(flagged=0, score=0.0, techniques="", error=f"exit={code}: {detail}"[:500], **base)
    findings = payload if isinstance(payload, list) else []
    high = [f for f in findings if f.get("severity") == "high"]
    medium = [f for f in findings if f.get("severity") == "medium"]
    techniques = sorted({f.get("type", "") for f in findings})
    return FileResult(
        flagged=int(bool(findings)),
        score=len(high) + 0.1 * len(medium),
        techniques="|".join(techniques),
        error="",
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
            "repository": "https://github.com/Andy8647/pdf-injection-scanner",
            "license": "MIT",
            "commit": git_commit(REPO_DIR),
            "version": "0.2.1 (pyproject.toml)",
            "python": python_version(PYTHON),
            "command_template": f"{CLI} --json <pdf>",
            "flag_rule": "any finding (the tool has no severity-based verdict)",
            "score_rule": "high_count + 0.1 * medium_count",
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
