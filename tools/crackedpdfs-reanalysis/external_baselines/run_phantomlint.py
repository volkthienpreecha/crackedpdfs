"""Run tobycmurray/phantom-lint over the frozen test split.

Setup (see README.md in this directory). PhantomLint declares ``python_requires >=3.9,<3.13`` and
its pinned ``llm-guard`` dependency has no Python 3.13 wheels, so this detector uses a 3.12
environment and the project's ``requirements-frozen.txt``::

    git clone https://github.com/tobycmurray/phantom-lint $CRACKEDPDFS_WORK/baselines/phantom-lint
    cd $CRACKEDPDFS_WORK/baselines/phantom-lint
    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -r requirements-frozen.txt
    .venv/bin/python -m spacy download en_core_web_sm
    uv pip install --python .venv/bin/python --no-deps -e .

Equivalent per-file command (default options: 300 dpi, ``--split noop``, ``--diff word_exact``,
``--analyze nlp`` with threshold 0.75 and the built-in bad-phrase list)::

    .venv/bin/phantomlint <pdf> --output <dir>

PhantomLint's import graph takes over a minute to load, so this driver keeps a pool of persistent
worker processes (``phantomlint_worker.py``) that each load the pipeline once and then process
PDFs sent over standard input with the same component defaults as the console script. A worker
that exceeds the per-file timeout is killed and replaced, and the file is recorded as a timeout.
A worker that exits on its own (for example when the operating system reclaims memory) is
replaced and the file is retried once before being recorded as ``worker_exited``.

Two analyzer modes are supported through ``--analyze``. ``nlp`` (default) reproduces the console
script: a sentence-transformer similarity filter against PhantomLint's ten built-in bad phrases
decides which text blocks are suspicious, and only those blocks are rendered and OCR-diffed.
``passthrough`` corresponds to ``phantomlint --analyze passthrough`` and sends every text block
through the OCR diff, which isolates PhantomLint's hidden-text mechanism from its prompt-content
filter. The passthrough run writes ``phantomlint_passthrough_per_file.csv``.

Progress is appended to ``<name>_progress.jsonl`` in the output directory after every file, and a
rerun skips files already present there, so an interrupted run can be resumed with the same
command. Pass ``--fresh`` to discard previous progress and ``--retry-timeouts`` to re-queue files
whose stored result is a timeout. ``--timeout`` sets the per-file budget (default 120 seconds); the
value used is recorded in the run metadata. ``--triads N`` restricts the run to a
random sample of N triads, stratified by attack family (seeded), for configurations that are too
slow to run over the whole split; the run metadata records the subsample.

Scoring. ``flagged`` is 1 when PhantomLint reports at least one hidden suspicious phrase, which is
exactly the condition under which the console script exits with status 1. ``score`` is the number
of characters highlighted as hidden in ``hidden_suspicious_phrases.txt`` (each highlighted
character carries a U+0332 combining mark). ``techniques`` is ``hidden_suspicious_text`` when
flagged, ``suspicious_visible_only`` when suspicious phrases were found but all were visible in the
OCR rendering, and empty otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline_common import (  # noqa: E402
    ARTIFACT_DIR,
    DEFAULT_BASELINES_ROOT,
    DEFAULT_PDF_ROOT,
    DEFAULT_SPLIT,
    FileResult,
    SplitRow,
    git_commit,
    load_split,
    python_version,
    write_per_file_csv,
    write_run_metadata,
)

DETECTOR_NAME = "phantomlint"
REPO_DIR = DEFAULT_BASELINES_ROOT / "phantom-lint"
PYTHON = REPO_DIR / ".venv" / "bin" / "python"
WORKER_SCRIPT = Path(__file__).resolve().parent / "phantomlint_worker.py"
PDF_ROOT = DEFAULT_PDF_ROOT
REPORT_ROOT = DEFAULT_BASELINES_ROOT / "phantomlint_reports"
DEFAULT_TIMEOUT_SECONDS = 120.0
STARTUP_TIMEOUT_SECONDS = 1200.0
STARTUP_ATTEMPTS = 4
MAX_FILE_ATTEMPTS = 2


class Worker:
    """One persistent PhantomLint worker process with a line reader thread."""

    def __init__(self, log_path: Path, mode: str) -> None:
        self.log = log_path.open("a", encoding="utf-8")
        # Each worker runs with a small thread budget so that several workers share the cores evenly.
        env = dict(
            os.environ,
            PYTHONWARNINGS="ignore",
            TOKENIZERS_PARALLELISM="false",
            OMP_NUM_THREADS="2",
            OMP_THREAD_LIMIT="2",
            HF_HUB_OFFLINE=os.environ.get("HF_HUB_OFFLINE", "0"),
        )
        self.proc = subprocess.Popen(
            [str(PYTHON), "-W", "ignore", str(WORKER_SCRIPT), mode],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            cwd=REPO_DIR,
            env=env,
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        try:
            first = self.lines.get(timeout=STARTUP_TIMEOUT_SECONDS)
        except queue.Empty:
            self.close()
            raise RuntimeError("PhantomLint worker did not report ready in time") from None
        if first is None or not json.loads(first).get("ready"):
            self.close()
            raise RuntimeError("PhantomLint worker exited during startup; see worker log")

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def request(self, pdf: Path, out_dir: Path, timeout: float) -> dict | None | str:
        """Send one request; returns the reply, ``"timeout"`` on overrun, or ``None`` if the worker exited."""
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(json.dumps({"pdf": str(pdf), "out": str(out_dir)}) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            return None
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            return "timeout"
        return None if line is None else json.loads(line)

    def close(self) -> None:
        """Terminate the worker process."""
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.log.close()


def start_worker(log_path: Path, mode: str) -> Worker:
    """Start a worker, retrying a few times with a pause if the host is short of memory."""
    for attempt in range(1, STARTUP_ATTEMPTS + 1):
        try:
            return Worker(log_path, mode)
        except RuntimeError as exc:
            print(
                f"worker start failed (attempt {attempt}/{STARTUP_ATTEMPTS}): {exc}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(30 * attempt)
    raise RuntimeError("could not start a PhantomLint worker")


def to_result(row: SplitRow, reply: dict | str | None, seconds: float) -> FileResult:
    """Convert a worker reply, a timeout marker, or a worker exit into the shared result layout."""
    base = dict(
        pdf_id=row.pdf_id,
        label=row.label,
        pdf_role=row.pdf_role,
        attack_family=row.attack_family,
        seconds=seconds,
    )
    if reply == "timeout":
        return FileResult(flagged=0, score=0.0, techniques="", error="timeout", **base)
    if reply is None:
        return FileResult(flagged=0, score=0.0, techniques="", error="worker_exited", **base)
    if reply.get("error"):
        return FileResult(flagged=0, score=0.0, techniques="", error=reply["error"], **base)
    flagged = int(reply.get("exit_code") == 1)
    technique = (
        "hidden_suspicious_text"
        if flagged
        else ("suspicious_visible_only" if reply.get("suspicious_phrases", 0) else "")
    )
    return FileResult(
        flagged=flagged,
        score=float(reply.get("hidden_chars", 0)),
        techniques=technique,
        error="",
        extra={
            "hidden_phrases": reply.get("hidden_phrases", 0),
            "suspicious_phrases": reply.get("suspicious_phrases", 0),
        },
        **base,
    )


class Progress:
    """Append-only JSONL progress store shared by the worker threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.results: dict[str, FileResult] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    data = json.loads(line)
                    extra = data.pop("extra", {})
                    self.results[data["pdf_id"]] = FileResult(extra=extra, **data)
        self.handle = path.open("a", encoding="utf-8")

    def record(self, result: FileResult) -> int:
        """Persist one result and return the number of completed files."""
        with self.lock:
            self.results[result.pdf_id] = result
            payload = {**result.to_row(), "seconds": result.seconds, "extra": result.extra}
            self.handle.write(json.dumps(payload) + "\n")
            self.handle.flush()
            return len(self.results)

    def close(self) -> None:
        """Close the progress file."""
        self.handle.close()


def worker_loop(
    worker_id: int,
    jobs: queue.Queue,
    progress: Progress,
    log_dir: Path,
    mode: str,
    report_root: Path,
    timeout: float,
) -> None:
    """Thread body: own one worker process, pull rows from the job queue, respawn on timeout or exit."""
    worker = start_worker(log_dir / f"worker_{worker_id}.log", mode)
    try:
        while True:
            try:
                row, attempt = jobs.get_nowait()
            except queue.Empty:
                return
            out_dir = report_root / row.pdf_id
            out_dir.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            reply = worker.request(PDF_ROOT / row.file_path, out_dir, timeout)
            seconds = time.perf_counter() - started
            if reply is None or reply == "timeout":
                worker.close()
                worker = start_worker(log_dir / f"worker_{worker_id}.log", mode)
            if reply is None and attempt < MAX_FILE_ATTEMPTS:
                jobs.put((row, attempt + 1))
                continue
            done = progress.record(to_result(row, reply, seconds))
            if done % 25 == 0:
                print(f"[{done}] completed", file=sys.stderr, flush=True)
    finally:
        worker.close()


def sample_triads(rows: list[SplitRow], n_triads: int, seed: int) -> list[SplitRow]:
    """Return the rows of ``n_triads`` triads sampled at random, stratified by attack family."""
    triads: dict[str, list[SplitRow]] = defaultdict(list)
    family_of: dict[str, str] = {}
    for row in rows:
        triads[row.triad_id].append(row)
        if row.pdf_role == "injected_attack":
            family_of[row.triad_id] = row.attack_family
    by_family: dict[str, list[str]] = defaultdict(list)
    for triad_id in sorted(triads):
        by_family[family_of.get(triad_id, "none")].append(triad_id)
    rng = random.Random(seed)
    total = len(triads)
    chosen: list[str] = []
    for family in sorted(by_family):
        ids = by_family[family]
        take = max(1, round(n_triads * len(ids) / total))
        rng.shuffle(ids)
        chosen.extend(ids[:take])
    chosen_set = set(chosen[:n_triads]) if len(chosen) > n_triads else set(chosen)
    return [row for row in rows if row.triad_id in chosen_set]


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="only process the first N rows (smoke test)")
    parser.add_argument("--triads", type=int, default=None, help="random stratified sample of N triads")
    parser.add_argument("--seed", type=int, default=0, help="seed for --triads sampling")
    parser.add_argument("--out-dir", type=Path, default=ARTIFACT_DIR)
    parser.add_argument(
        "--analyze", choices=["nlp", "passthrough"], default="nlp", help="PhantomLint analyzer (default: nlp)"
    )
    parser.add_argument("--fresh", action="store_true", help="discard previous progress instead of resuming")
    parser.add_argument(
        "--retry-timeouts", action="store_true", help="re-run files whose stored result is a timeout"
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="per-file budget in seconds"
    )
    args = parser.parse_args()

    rows = load_split(args.split)
    if args.triads:
        rows = sample_triads(rows, args.triads, args.seed)
    if args.limit:
        rows = rows[: args.limit]
    name = DETECTOR_NAME if args.analyze == "nlp" else f"{DETECTOR_NAME}_{args.analyze}"
    report_root = REPORT_ROOT / args.analyze
    report_root.mkdir(parents=True, exist_ok=True)
    log_dir = report_root / "_logs"
    log_dir.mkdir(exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    progress_path = args.out_dir / f"{name}_progress.jsonl"
    state_path = args.out_dir / f"{name}_state.json"
    if args.fresh:
        progress_path.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
    progress = Progress(progress_path)
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {"wall_clock_seconds": 0.0, "invocations": 0}
    )

    def is_pending(row: SplitRow) -> bool:
        previous = progress.results.get(row.pdf_id)
        if previous is None:
            return True
        return args.retry_timeouts and previous.error in ("timeout", "worker_exited")

    pending = [row for row in rows if is_pending(row)]
    print(
        f"{len(rows)} rows selected, {len(rows) - len(pending)} already done, {len(pending)} pending",
        file=sys.stderr,
        flush=True,
    )

    jobs: queue.Queue = queue.Queue()
    for row in pending:
        jobs.put((row, 1))
    started = time.perf_counter()
    if pending:
        threads = [
            threading.Thread(
                target=worker_loop, args=(i, jobs, progress, log_dir, args.analyze, report_root, args.timeout)
            )
            for i in range(min(args.workers, len(pending)))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    wall = time.perf_counter() - started
    progress.close()
    state["wall_clock_seconds"] = round(state["wall_clock_seconds"] + wall, 1)
    state["invocations"] += 1
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    ordered = [progress.results[row.pdf_id] for row in rows if row.pdf_id in progress.results]
    out_csv = args.out_dir / f"{name}_per_file.csv"
    write_per_file_csv(out_csv, ordered)
    write_run_metadata(
        args.out_dir / f"{name}_run.json",
        {
            "detector": name,
            "repository": "https://github.com/tobycmurray/phantom-lint",
            "license": "BSD-3-Clause",
            "commit": git_commit(REPO_DIR),
            "version": "0.1 (setup.py)",
            "python": python_version(PYTHON),
            "command_template": (
                f"{REPO_DIR / '.venv' / 'bin' / 'phantomlint'} <pdf> --output <dir> --analyze {args.analyze}"
                "  (executed in-process by phantomlint_worker.py with identical component defaults)"
            ),
            "options": {
                "dpi": 300,
                "split": "noop",
                "diff": "word_exact",
                "analyze": args.analyze,
                "threshold": 0.75,
                "bad_list": "built-in DEFAULT_BADLIST",
            },
            "flag_rule": "at least one hidden suspicious phrase reported (console script exit status 1)",
            "score_rule": "number of characters highlighted as hidden in hidden_suspicious_phrases.txt",
            "timeout_seconds": args.timeout,
            "workers": args.workers,
            "files": len(ordered),
            "subsample": (
                f"{args.triads} triads sampled with seed {args.seed}, stratified by attack family"
                if args.triads
                else "full test split"
            ),
            "wall_clock_seconds": state["wall_clock_seconds"],
            "invocations": state["invocations"],
            "errors": sum(1 for r in ordered if r.error and r.error != "timeout"),
            "timeouts": sum(1 for r in ordered if r.error == "timeout"),
            "reports_dir": str(report_root),
        },
    )
    print(f"wrote {out_csv} ({len(ordered)} rows); this invocation took {wall:,.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
