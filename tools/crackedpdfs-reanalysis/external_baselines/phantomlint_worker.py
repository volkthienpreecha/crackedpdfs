"""Persistent PhantomLint worker process.

PhantomLint's import graph (torch, sentence-transformers, spaCy, llm-guard) takes well over a
minute to load, so invoking the ``phantomlint`` console script once per PDF is impractical for a
2,919-file split. This worker loads the pipeline once with the same defaults as
``phantomlint.cli.main`` and then processes one PDF per line of standard input, replying with one
JSON object per line on standard output. ``run_phantomlint.py`` manages a pool of these workers
and enforces the per-file timeout by killing and respawning a worker that overruns.

Run with the PhantomLint virtual environment interpreter and one positional argument, the analyzer
mode (``nlp`` for the console-script default or ``passthrough`` to send every text block through the
OCR diff). Each request line is a JSON object
``{"pdf": "<path>", "out": "<output directory>"}``; each reply is a JSON object with the keys
``exit_code``, ``hidden_phrases``, ``hidden_chars``, ``suspicious_phrases``, ``seconds`` and
``error``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

from phantomlint.analyzers import LocalSemanticAnalyzer, PassthroughAnalyzer  # noqa: E402
from phantomlint.cli import DEFAULT_BADLIST, DEFAULT_DPI, DEFAULT_THRESHOLD  # noqa: E402
from phantomlint.detector import (  # noqa: E402
    HIDDEN_SUSPICIOUS_PHRASES_FILE,
    SUSPICIOUS_PHRASES_FILE,
    detect_hidden_phrases,
)
from phantomlint.diffing import WordDiffer  # noqa: E402
from phantomlint.ocr import TesseractOCREngine  # noqa: E402
from phantomlint.renderer import renderer_for  # noqa: E402
from phantomlint.splitters import NoopSplitter  # noqa: E402

HIGHLIGHT_MARK = "̲"


def count_report(path: Path, header: str) -> tuple[int, int]:
    """Return ``(phrase_blocks, highlighted_characters)`` for one PhantomLint report file."""
    if not path.exists():
        return 0, 0
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.count(header), text.count(HIGHLIGHT_MARK)


def main() -> None:
    """Load the pipeline once and serve requests from standard input."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "nlp"
    ocr = TesseractOCREngine()
    splitter = NoopSplitter()
    analyzer = (
        PassthroughAnalyzer() if mode == "passthrough" else LocalSemanticAnalyzer(threshold=DEFAULT_THRESHOLD)
    )
    differ = WordDiffer(threshold=1.0)
    print(json.dumps({"ready": True}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        pdf_path = Path(request["pdf"])
        out_dir = Path(request["out"])
        started = time.perf_counter()
        reply = {
            "exit_code": None,
            "hidden_phrases": 0,
            "hidden_chars": 0,
            "suspicious_phrases": 0,
            "error": "",
        }
        real_stdout = sys.stdout
        with open(os.devnull, "w") as devnull:
            try:
                renderer = renderer_for(pdf_path, DEFAULT_DPI)
                if renderer is None:
                    reply["error"] = "unsupported file type"
                else:
                    sys.stdout = devnull
                    try:
                        detect_hidden_phrases(
                            pdf_path, out_dir, ocr, splitter, differ, analyzer, renderer, DEFAULT_BADLIST
                        )
                        reply["exit_code"] = 0
                    except SystemExit as exc:
                        reply["exit_code"] = int(exc.code or 0)
                    finally:
                        sys.stdout = real_stdout
                hidden_blocks, hidden_chars = count_report(
                    out_dir / HIDDEN_SUSPICIOUS_PHRASES_FILE, "Hidden suspicious phrases found on page"
                )
                suspicious_blocks, _ = count_report(
                    out_dir / SUSPICIOUS_PHRASES_FILE, "Suspicious phrases found on page"
                )
                reply.update(
                    hidden_phrases=hidden_blocks,
                    hidden_chars=hidden_chars,
                    suspicious_phrases=suspicious_blocks,
                )
            except Exception as exc:  # noqa: BLE001 - report any failure to the driver and keep serving
                sys.stdout = real_stdout
                reply["error"] = f"{type(exc).__name__}: {exc}"[:500]
        reply["seconds"] = round(time.perf_counter() - started, 3)
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
