"""Shared helpers for running external hidden-text detectors over the frozen test split.

Each ``run_<detector>.py`` driver in this directory imports this module. The helpers cover
loading the split listing, running one detector command per PDF across a process pool with a
hard per-file timeout, and writing the per-file CSV in the agreed column layout.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

WORK_ROOT = Path(os.environ.get("CRACKEDPDFS_WORK", Path.home() / "crackedpdfs-work")).resolve()
DEFAULT_SPLIT = WORK_ROOT / "v1" / "test_split.csv"
DEFAULT_PDF_ROOT = WORK_ROOT / "v1" / "pdfs"
DEFAULT_BASELINES_ROOT = WORK_ROOT / "baselines"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACT_DIR = REPO_ROOT / ".cache" / "crackedpdfs-reanalysis" / "artifacts" / "external_baselines"
ARTIFACT_DIR = DEFAULT_ARTIFACT_DIR

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


@dataclass
class SplitRow:
    """One row of the frozen test split listing."""

    pdf_id: str
    file_path: str
    label: int
    pdf_role: str
    attack_family: str
    benign_confounder_family: str
    triad_id: str
    base_pdf_id: str


@dataclass
class FileResult:
    """Detector outcome for one PDF."""

    pdf_id: str
    label: int
    pdf_role: str
    attack_family: str
    flagged: int
    score: float
    techniques: str
    error: str
    seconds: float
    extra: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        """Return the CSV row for this result (the ``extra`` payload is not serialised)."""
        row = asdict(self)
        row.pop("extra")
        row["seconds"] = f"{self.seconds:.3f}"
        return row


def load_split(path: Path = DEFAULT_SPLIT) -> list[SplitRow]:
    """Load the test split listing into typed rows."""
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            SplitRow(
                pdf_id=r["pdf_id"],
                file_path=r["file_path"],
                label=int(r["label"]),
                pdf_role=r["pdf_role"],
                attack_family=r["attack_family"],
                benign_confounder_family=r["benign_confounder_family"],
                triad_id=r["triad_id"],
                base_pdf_id=r["base_pdf_id"],
            )
            for r in csv.DictReader(handle)
        ]


def run_command(
    cmd: list[str], timeout: float, env: dict | None = None, cwd: Path | None = None
) -> tuple[int | None, str, str, float, bool]:
    """Run ``cmd`` with a hard timeout.

    Returns ``(returncode, stdout, stderr, seconds, timed_out)``. On timeout the return code is ``None``.
    """
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd, errors="replace"
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - start
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return None, out, err, elapsed, True
    return proc.returncode, proc.stdout, proc.stderr, time.perf_counter() - start, False


def extract_json_payload(stdout: str) -> object:
    """Return the first JSON document found in ``stdout``.

    Some detectors print progress text before the JSON body, so the parser scans forward from
    each line that starts with ``[`` or ``{`` until ``json.loads`` succeeds.
    """
    lines = stdout.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            candidate = "\n".join(lines[idx:])
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON payload found in detector output")


def run_pool(
    rows: list[SplitRow],
    worker: Callable[[SplitRow], FileResult],
    workers: int,
    progress_every: int = 100,
) -> list[FileResult]:
    """Run ``worker`` over all rows with a process pool and return results in split order."""
    results: dict[str, FileResult] = {}
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(worker, row): row for row in rows}
        for done, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            try:
                results[row.pdf_id] = future.result()
            except Exception as exc:  # pragma: no cover - defensive, worker functions catch their own errors
                results[row.pdf_id] = FileResult(
                    pdf_id=row.pdf_id,
                    label=row.label,
                    pdf_role=row.pdf_role,
                    attack_family=row.attack_family,
                    flagged=0,
                    score=0.0,
                    techniques="",
                    error=f"driver_exception: {type(exc).__name__}: {exc}"[:500],
                    seconds=0.0,
                )
            if done % progress_every == 0 or done == len(rows):
                elapsed = time.perf_counter() - started
                print(f"[{done}/{len(rows)}] elapsed {elapsed:,.0f}s", file=sys.stderr, flush=True)
    return [results[row.pdf_id] for row in rows]


def write_per_file_csv(path: Path, results: list[FileResult]) -> None:
    """Write results to ``path`` using the shared column layout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PER_FILE_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_row())


def write_run_metadata(path: Path, metadata: dict) -> None:
    """Write run metadata (commit, command template, timing) next to the per-file CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_commit(repo: Path) -> str:
    """Return the checked-out commit SHA of ``repo`` or ``unknown`` if git is unavailable."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def python_version(python: Path) -> str:
    """Return the version string of the interpreter at ``python``."""
    try:
        return subprocess.run(
            [str(python), "--version"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
