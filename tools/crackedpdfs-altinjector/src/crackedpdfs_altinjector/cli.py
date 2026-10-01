"""Command line interface for crackedpdfs-altinjector.

Two subcommands are provided:

``inject``
    Inject a single payload into one PDF.

``batch``
    Inject many payloads described by a JSONL manifest, in parallel.

Both write a JSON record next to each output PDF (``<output>.json``) describing
the realised placement.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from . import BACKENDS, InjectionError, inject
from .techniques import STRENGTHS, TECHNIQUES

_REQUIRED_JOB_KEYS = ("in", "out", "text", "technique", "strength", "backend")


def _write_record(out_path: str | Path, record: dict[str, Any]) -> Path:
    """Write a placement record next to its output PDF and return the path."""
    record_path = Path(str(out_path) + ".json")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record_path


def _run_inject(args: argparse.Namespace) -> int:
    """Handle the ``inject`` subcommand."""
    try:
        record = inject(
            source_path=args.infile,
            out_path=args.outfile,
            text=args.text,
            technique=args.technique,
            strength=args.strength,
            backend=args.backend,
            seed=args.seed,
        )
    except InjectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    record_path = _write_record(args.outfile, record)
    print(f"wrote {args.outfile}")
    print(f"wrote {record_path}")
    return 0


def _resolve_output(out_field: str, out_dir: Path) -> Path:
    """Resolve a job output path, placing relative paths under the output dir."""
    candidate = Path(out_field)
    if candidate.is_absolute():
        return candidate
    return out_dir / candidate


def _run_single_job(job: dict[str, Any], out_dir: str) -> dict[str, Any]:
    """Execute one manifest job and return a result summary (worker entry point)."""
    missing = [key for key in _REQUIRED_JOB_KEYS if key not in job]
    if missing:
        return {"job": job, "ok": False, "error": f"missing keys: {', '.join(missing)}"}

    out_path = _resolve_output(job["out"], Path(out_dir))
    try:
        record = inject(
            source_path=job["in"],
            out_path=out_path,
            text=job["text"],
            technique=job["technique"],
            strength=job["strength"],
            backend=job["backend"],
            seed=job.get("seed"),
        )
    except (InjectionError, OSError) as exc:
        return {"job": job, "ok": False, "error": str(exc), "out": str(out_path)}

    _write_record(out_path, record)
    return {"job": job, "ok": True, "out": str(out_path)}


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load jobs from a JSONL manifest, ignoring blank lines."""
    jobs: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            jobs.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise InjectionError(f"invalid JSON on manifest line {line_number}: {exc}") from exc
    return jobs


def _run_batch(args: argparse.Namespace) -> int:
    """Handle the ``batch`` subcommand."""
    manifest_path = Path(args.manifest)
    try:
        jobs = _load_manifest(manifest_path)
    except InjectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(_run_single_job, job, str(out_dir)) for job in jobs]
        for future in as_completed(futures):
            results.append(future.result())

    succeeded = sum(1 for result in results if result["ok"])
    failed = len(results) - succeeded
    for result in results:
        status = "ok" if result["ok"] else "fail"
        target = result.get("out", result["job"].get("out", "?"))
        detail = "" if result["ok"] else f" :: {result['error']}"
        print(f"[{status}] {target}{detail}")
    print(f"done: {succeeded} succeeded, {failed} failed")
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="crackedpdfs-altinjector",
        description="Independent hidden-text PDF injector for cross-generator detector evaluation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inject_parser = subparsers.add_parser("inject", help="inject a single payload into one PDF")
    inject_parser.add_argument("--in", dest="infile", required=True, help="source PDF path")
    inject_parser.add_argument("--out", dest="outfile", required=True, help="output PDF path")
    inject_parser.add_argument("--text", required=True, help="payload text to inject")
    inject_parser.add_argument("--technique", required=True, choices=sorted(TECHNIQUES))
    inject_parser.add_argument("--strength", default="medium", choices=sorted(STRENGTHS))
    inject_parser.add_argument("--backend", default="reportlab", choices=sorted(BACKENDS))
    inject_parser.add_argument("--seed", type=int, default=None, help="seed for placement jitter")
    inject_parser.set_defaults(func=_run_inject)

    batch_parser = subparsers.add_parser("batch", help="inject many payloads from a JSONL manifest")
    batch_parser.add_argument("--manifest", required=True, help="JSONL manifest path")
    batch_parser.add_argument("--out-dir", required=True, help="directory for outputs")
    batch_parser.add_argument("--workers", type=int, default=4, help="number of parallel workers")
    batch_parser.set_defaults(func=_run_batch)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Program entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
