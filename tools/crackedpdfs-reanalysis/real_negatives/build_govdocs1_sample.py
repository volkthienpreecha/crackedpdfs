"""Build a screened sample of real-world benign PDFs from GovDocs1 for false-positive testing.

GovDocs1 (Digital Corpora, https://digitalcorpora.org/corpora/file-corpora/files/) is a corpus of
roughly one million files collected from United States government web servers, packaged in 1,000
threads of 1,000 files each. The threads are mirrored as one zip archive per thread in the AWS Open
Data bucket ``s3://digitalcorpora/corpora/files/govdocs1/zipfiles/``.

The driver runs four stages, each resumable from the files written by the previous one:

1. ``download``: draw threads in a seeded random order, fetch one thread zip at a time, keep only PDF
   members under a size cap, deduplicate by SHA-256 while extracting, delete the zip, and stop once the
   target number of unique PDFs is reached.
2. ``inspect``: open every PDF with pikepdf and record page count, PDF version, and the producer string.
   Files pikepdf cannot open are kept on disk but recorded as unreadable.
3. ``audit``: run ``crackedpdfs-audit file <pdf> --json`` on every readable PDF in a process pool and sum
   the per-page placement and visibility counters.
4. ``manifest``: write ``manifest.parquet``, ``manifest.csv``, and ``summary.md``.

Example::

    python build_govdocs1_sample.py --work-dir ~/crackedpdfs-work/real-negatives/govdocs1 \
        --target 2000 --seed 42 --max-file-bytes 5000000 --workers 8
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.request import urlopen

S3_PREFIX = "s3://digitalcorpora/corpora/files/govdocs1/zipfiles/"
HTTPS_PREFIX = "https://digitalcorpora.s3.amazonaws.com/corpora/files/govdocs1/zipfiles/"
THREAD_COUNT = 1000
HIDDEN_INDICATORS = ("outside", "clipped", "invisible_render_mode", "tiny_font", "low_contrast_fill")
AUDIT_FIELDS = ("glyphs", *HIDDEN_INDICATORS, "likely_visible")
MANIFEST_COLUMNS = (
    "file_name",
    "sha256",
    "source_thread",
    "bytes",
    "pages",
    "pdf_version",
    "producer",
    "audit_glyphs",
    "audit_outside",
    "audit_clipped",
    "audit_invisible_render_mode",
    "audit_tiny_font",
    "audit_low_contrast_fill",
    "audit_likely_visible",
    "audit_error",
    "screened_clean",
)


@dataclass
class DownloadState:
    """Progress of the download stage, persisted as ``download_state.json``."""

    seed: int
    target: int
    max_file_bytes: int
    method: str
    thread_order: list[int]
    threads_done: list[int] = field(default_factory=list)
    kept: dict[str, dict[str, object]] = field(default_factory=dict)
    skipped_duplicates: int = 0
    skipped_oversize: int = 0
    pdf_members_seen: int = 0
    zip_bytes_downloaded: int = 0
    complete: bool = False


def _log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def _load_json(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def _dump_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def choose_method(requested: str) -> str:
    """Pick ``aws`` when the CLI is on PATH, otherwise fall back to anonymous HTTPS."""
    if requested != "auto":
        return requested
    return "aws" if shutil.which("aws") else "https"


def fetch_thread_zip(thread: int, dest: Path, method: str) -> Path:
    """Download one thread archive to ``dest`` and return its path."""
    name = f"{thread:03d}.zip"
    target = dest / name
    if target.exists():
        return target
    partial = dest / (name + ".part")
    if method == "aws":
        cmd = ["aws", "s3", "cp", "--no-sign-request", "--only-show-errors", S3_PREFIX + name, str(partial)]
        subprocess.run(cmd, check=True)
    else:
        with urlopen(HTTPS_PREFIX + name) as response, partial.open("wb") as handle:  # noqa: S310
            shutil.copyfileobj(response, handle, length=1 << 20)
    partial.replace(target)
    return target


def extract_pdfs(
    archive: Path, thread: int, pdf_dir: Path, state: DownloadState
) -> Iterable[tuple[str, str]]:
    """Extract PDF members under the size cap, deduplicating by SHA-256 as they are written."""
    known_hashes = {entry["sha256"] for entry in state.kept.values()}
    with zipfile.ZipFile(archive) as zf:
        for info in sorted(zf.infolist(), key=lambda item: item.filename):
            if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                continue
            state.pdf_members_seen += 1
            if info.file_size > state.max_file_bytes or info.file_size == 0:
                state.skipped_oversize += 1
                continue
            data = zf.read(info)
            digest = hashlib.sha256(data).hexdigest()
            if digest in known_hashes:
                state.skipped_duplicates += 1
                continue
            file_name = Path(info.filename).name
            (pdf_dir / file_name).write_bytes(data)
            known_hashes.add(digest)
            state.kept[file_name] = {
                "sha256": digest,
                "source_thread": f"{thread:03d}",
                "bytes": len(data),
                "zip_member": info.filename,
            }
            yield file_name, digest
            if len(state.kept) >= state.target:
                return


def stage_download(work_dir: Path, target: int, seed: int, max_file_bytes: int, method: str) -> DownloadState:
    """Download thread zips in seeded random order until ``target`` unique PDFs are on disk."""
    pdf_dir = work_dir / "pdfs"
    zip_dir = work_dir / "zips"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    zip_dir.mkdir(parents=True, exist_ok=True)
    state_path = work_dir / "download_state.json"
    saved = _load_json(state_path)
    if saved and saved.get("seed") == seed and saved.get("target") == target:
        state = DownloadState(**saved)
        if state.complete:
            _log(f"download stage already complete: {len(state.kept)} PDFs")
            return state
    else:
        order = list(range(THREAD_COUNT))
        random.Random(seed).shuffle(order)
        state = DownloadState(
            seed=seed, target=target, max_file_bytes=max_file_bytes, method=method, thread_order=order
        )

    for thread in state.thread_order:
        if len(state.kept) >= target:
            break
        if thread in state.threads_done:
            continue
        _log(f"thread {thread:03d}: downloading via {method}")
        archive = fetch_thread_zip(thread, zip_dir, method)
        state.zip_bytes_downloaded += archive.stat().st_size
        before = len(state.kept)
        for _ in extract_pdfs(archive, thread, pdf_dir, state):
            pass
        archive.unlink()
        state.threads_done.append(thread)
        _dump_json(state_path, asdict(state))
        _log(f"thread {thread:03d}: kept {len(state.kept) - before} PDFs, total {len(state.kept)}/{target}")

    state.complete = len(state.kept) >= target
    _dump_json(state_path, asdict(state))
    return state


def inspect_pdf(path: Path) -> dict[str, object]:
    """Open a PDF with pikepdf and return pages, version, producer, or an error string."""
    import pikepdf

    record: dict[str, object] = {"pages": None, "pdf_version": None, "producer": None, "open_error": None}
    try:
        with pikepdf.open(path) as pdf:
            record["pages"] = len(pdf.pages)
            record["pdf_version"] = str(pdf.pdf_version)
            producer = None
            try:
                docinfo = pdf.docinfo
                if "/Producer" in docinfo:
                    producer = str(docinfo["/Producer"])
            except Exception as exc:  # noqa: BLE001
                producer = f"<unreadable Info: {type(exc).__name__}>"
            record["producer"] = producer
    except Exception as exc:  # noqa: BLE001
        record["open_error"] = f"{type(exc).__name__}: {exc}"[:300]
    return record


def stage_inspect(work_dir: Path, names: list[str], workers: int) -> dict[str, dict[str, object]]:
    """Run ``inspect_pdf`` over every file, caching results in ``inspect.json``."""
    cache_path = work_dir / "inspect.json"
    results: dict[str, dict[str, object]] = _load_json(cache_path) or {}
    todo = [name for name in names if name not in results]
    _log(f"inspect stage: {len(todo)} files to open ({len(results)} cached)")
    pdf_dir = work_dir / "pdfs"
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(inspect_pdf, pdf_dir / name): name for name in todo}
        for count, future in enumerate(as_completed(futures), start=1):
            results[futures[future]] = future.result()
            if count % 200 == 0:
                _dump_json(cache_path, results)
                _log(f"inspect stage: {count}/{len(todo)}")
    _dump_json(cache_path, results)
    return results


def audit_pdf(path: Path, audit_bin: str, timeout: int) -> dict[str, object]:
    """Run ``crackedpdfs-audit file --json`` and sum the per-page counters."""
    totals: dict[str, object] = {f"audit_{name}": 0 for name in AUDIT_FIELDS}
    totals["audit_pages"] = 0
    totals["audit_error"] = None
    try:
        proc = subprocess.run(
            [audit_bin, "file", str(path), "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        totals["audit_error"] = f"timeout after {timeout}s"
        return totals
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit {proc.returncode}"
        totals["audit_error"] = tail[:300]
        return totals
    try:
        pages = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        totals["audit_error"] = f"bad json: {exc}"[:300]
        return totals
    for page in pages:
        totals["audit_pages"] += 1
        for name in AUDIT_FIELDS:
            totals[f"audit_{name}"] += int(page.get(name, 0))
    return totals


def stage_audit(
    work_dir: Path, names: list[str], workers: int, audit_bin: str, timeout: int
) -> dict[str, dict[str, object]]:
    """Audit every readable PDF in a process pool, caching results in ``audit.json``."""
    cache_path = work_dir / "audit.json"
    results: dict[str, dict[str, object]] = _load_json(cache_path) or {}
    todo = [name for name in names if name not in results]
    _log(f"audit stage: {len(todo)} files to audit ({len(results)} cached) with {workers} workers")
    pdf_dir = work_dir / "pdfs"
    started = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(audit_pdf, pdf_dir / name, audit_bin, timeout): name for name in todo}
        for count, future in enumerate(as_completed(futures), start=1):
            results[futures[future]] = future.result()
            if count % 100 == 0 or count == len(todo):
                _dump_json(cache_path, results)
                _log(f"audit stage: {count}/{len(todo)} in {time.time() - started:,.0f}s")
    _dump_json(cache_path, results)
    return results


def build_rows(
    state: DownloadState, inspected: dict[str, dict[str, object]], audited: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    """Join download, inspection, and audit records into manifest rows."""
    rows = []
    for name in sorted(state.kept):
        meta = state.kept[name]
        info = inspected.get(name, {})
        audit = audited.get(name, {})
        error = info.get("open_error") or audit.get("audit_error")
        row: dict[str, object] = {
            "file_name": name,
            "sha256": meta["sha256"],
            "source_thread": meta["source_thread"],
            "bytes": meta["bytes"],
            "pages": info.get("pages"),
            "pdf_version": info.get("pdf_version"),
            "producer": info.get("producer"),
        }
        for field_name in AUDIT_FIELDS:
            row[f"audit_{field_name}"] = audit.get(f"audit_{field_name}")
        row["audit_error"] = error
        row["screened_clean"] = bool(
            error is None and all(int(row[f"audit_{name_}"] or 0) == 0 for name_ in HIDDEN_INDICATORS)
        )
        rows.append(row)
    return rows


def _quantiles(values: list[float]) -> str:
    if not values:
        return "n/a"
    qs = statistics.quantiles(values, n=20, method="inclusive") if len(values) > 1 else [values[0]] * 19
    return (
        f"min {min(values):,.0f}, p5 {qs[0]:,.0f}, p25 {qs[4]:,.0f}, median {qs[9]:,.0f}, "
        f"p75 {qs[14]:,.0f}, p95 {qs[18]:,.0f}, max {max(values):,.0f}, mean {statistics.fmean(values):,.1f}"
    )


def write_summary(
    work_dir: Path, state: DownloadState, rows: list[dict[str, object]], argv: list[str]
) -> Path:
    """Write ``summary.md`` with counts, distributions, and the exact commands used."""
    total = len(rows)
    unreadable = [r for r in rows if r["audit_error"] and r["pages"] is None]
    audit_errors = [r for r in rows if r["audit_error"] and r["pages"] is not None]
    clean = sum(1 for r in rows if r["screened_clean"])
    readable = [r for r in rows if r["pages"] is not None]
    lines = [
        "# GovDocs1 real-negative sample",
        "",
        "Source: GovDocs1, Digital Corpora (https://digitalcorpora.org/corpora/file-corpora/files/).",
        f"Threads were drawn in a seeded random order (seed {state.seed}) and downloaded as whole thread",
        f"archives via `{state.method}`; only `.pdf` members at or below {state.max_file_bytes:,} bytes were kept.",
        "",
        "## Counts",
        "",
        "| Quantity | Value |",
        "| --- | --- |",
        f"| Threads downloaded | {len(state.threads_done)} ({', '.join(f'{t:03d}' for t in state.threads_done)}) |",
        f"| Zip bytes downloaded | {state.zip_bytes_downloaded:,} |",
        f"| PDF members seen in those threads | {state.pdf_members_seen:,} |",
        f"| Skipped for size cap or empty | {state.skipped_oversize:,} |",
        f"| Skipped as SHA-256 duplicates | {state.skipped_duplicates:,} |",
        f"| Unique PDFs kept on disk | {total:,} |",
        f"| Total bytes kept | {sum(int(r['bytes']) for r in rows):,} |",
        f"| Unreadable by pikepdf | {len(unreadable):,} |",
        f"| Readable but audit failed | {len(audit_errors):,} |",
        f"| Screened clean (all hidden indicators zero, no error) | {clean:,} ({clean / max(total, 1):.1%}) |",
        "",
        "## Flagged by indicator (readable, audited files)",
        "",
        "| Indicator | Files with nonzero count | Share of audited |",
        "| --- | --- | --- |",
    ]
    audited = [r for r in readable if not r["audit_error"]]
    for name in HIDDEN_INDICATORS:
        flagged = sum(1 for r in audited if int(r[f"audit_{name}"] or 0) > 0)
        lines.append(f"| {name} | {flagged:,} | {flagged / max(len(audited), 1):.1%} |")
    any_flag = sum(1 for r in audited if any(int(r[f"audit_{name}"] or 0) > 0 for name in HIDDEN_INDICATORS))
    lines.append(f"| any indicator | {any_flag:,} | {any_flag / max(len(audited), 1):.1%} |")
    no_text = sum(1 for r in audited if int(r["audit_glyphs"] or 0) == 0)
    lines += [
        "",
        f"Audited files with zero extracted glyphs (scanned or image-only): {no_text:,}.",
        "",
        "## Distributions",
        "",
        f"File size in bytes: {_quantiles([float(r['bytes']) for r in rows])}",
        "",
        f"Pages (readable files): {_quantiles([float(r['pages']) for r in readable])}",
        "",
        "PDF versions:",
        "",
    ]
    versions: dict[str, int] = {}
    for r in readable:
        versions[str(r["pdf_version"])] = versions.get(str(r["pdf_version"]), 0) + 1
    lines += [f"- {version}: {count:,}" for version, count in sorted(versions.items())]
    producers: dict[str, int] = {}
    for r in readable:
        key = str(r["producer"] or "<none>")
        producers[key] = producers.get(key, 0) + 1
    lines += ["", "Top producer strings:", ""]
    lines += [f"- {count:,}: {name}" for name, count in sorted(producers.items(), key=lambda kv: -kv[1])[:15]]
    if unreadable:
        lines += ["", "## Unreadable files", ""]
        lines += [f"- {r['file_name']}: {r['audit_error']}" for r in unreadable]
    if audit_errors:
        lines += ["", "## Audit errors on readable files", ""]
        lines += [f"- {r['file_name']}: {r['audit_error']}" for r in audit_errors]
    lines += [
        "",
        "## Commands",
        "",
        "```bash",
        "uv venv --python 3.13 .venv",
        'uv pip install --python .venv/bin/python -e "<repo>/tools/crackedpdfs-audit[parquet]" pandas',
        f"aws s3 cp --no-sign-request {S3_PREFIX}NNN.zip zips/   # per selected thread, deleted after extraction",
        ".venv/bin/crackedpdfs-audit file pdfs/<file>.pdf --json  # per file, in a process pool",
        " ".join(argv),
        "```",
        "",
        "Per-file audit counters are summed over pages. The hidden-text indicators are `outside`, `clipped`,",
        "`invisible_render_mode`, `tiny_font`, and `low_contrast_fill`; `screened_clean` is true only when all",
        "five are zero and neither pikepdf nor the audit reported an error.",
    ]
    out = work_dir / "summary.md"
    out.write_text("\n".join(lines) + "\n")
    return out


def stage_manifest(work_dir: Path, state: DownloadState, rows: list[dict[str, object]]) -> None:
    """Write the manifest as parquet and CSV."""
    import pandas as pd

    frame = pd.DataFrame(rows, columns=list(MANIFEST_COLUMNS))
    frame["pages"] = frame["pages"].astype("Int64")
    for name in AUDIT_FIELDS:
        frame[f"audit_{name}"] = frame[f"audit_{name}"].astype("Int64")
    frame["screened_clean"] = frame["screened_clean"].astype(bool)
    frame.to_parquet(work_dir / "manifest.parquet", index=False)
    frame.to_csv(work_dir / "manifest.csv", index=False)
    _log(f"wrote manifest with {len(frame)} rows to {work_dir}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--target", type=int, default=2000, help="Unique PDFs to collect.")
    parser.add_argument("--seed", type=int, default=42, help="Seed for the thread draw.")
    parser.add_argument("--max-file-bytes", type=int, default=5_000_000)
    parser.add_argument("--method", choices=("auto", "aws", "https"), default="auto")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument(
        "--audit-bin", default=None, help="Path to crackedpdfs-audit; defaults to the venv copy."
    )
    parser.add_argument("--audit-timeout", type=int, default=600, help="Seconds per file before giving up.")
    parser.add_argument("--stage", choices=("all", "download", "inspect", "audit", "manifest"), default="all")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    work_dir: Path = args.work_dir.expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    audit_bin = args.audit_bin or str(Path(sys.executable).parent / "crackedpdfs-audit")
    method = choose_method(args.method)

    state = stage_download(work_dir, args.target, args.seed, args.max_file_bytes, method)
    if args.stage == "download":
        return 0
    names = sorted(state.kept)
    inspected = stage_inspect(work_dir, names, args.workers)
    if args.stage == "inspect":
        return 0
    readable = [name for name in names if inspected[name].get("open_error") is None]
    audited = stage_audit(work_dir, readable, args.workers, audit_bin, args.audit_timeout)
    if args.stage == "audit":
        return 0
    rows = build_rows(state, inspected, audited)
    stage_manifest(work_dir, state, rows)
    summary = write_summary(work_dir, state, rows, [Path(sys.argv[0]).name, *sys.argv[1:]])
    _log(f"wrote {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
