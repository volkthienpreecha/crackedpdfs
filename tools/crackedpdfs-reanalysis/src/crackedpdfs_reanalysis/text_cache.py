"""Extract pypdf text once for every PDF in a labels table and persist it.

The training and evaluation code extracts text on every run. Repeated
experiments over the same corpus (grouped resamples, payload-held-out folds,
baseline reruns) pay that cost each time, so this script writes a single
parquet keyed by pdf_id that later steps can load instead.

Usage:
    crackedpdfs-reanalysis text-cache --pdf-root /path/to/pdfs \
        --labels .cache/crackedpdfs-reanalysis/tables/labels.parquet \
        --out .cache/crackedpdfs-reanalysis/tables/text_cache.parquet

``file_path`` values in the labels table are corpus-relative (for example
``benign/sample_0001.benign.pdf``) and are resolved against ``--pdf-root``.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from crackedpdfs_reanalysis import detector  # noqa: F401  (adds the frozen detector to sys.path)
from crackedpdfs_reanalysis.detector import TABLES_DIR

from src.parsers.pdf_text import extract_pypdf_text

_DATASET_CONFIG: dict | None = None


def _init(dataset_config: dict) -> None:
    global _DATASET_CONFIG
    _DATASET_CONFIG = dataset_config


def _extract(item: tuple[str, str]) -> tuple[str, str, str]:
    pdf_id, file_path = item
    assert _DATASET_CONFIG is not None
    return pdf_id, file_path, extract_pypdf_text(file_path, _DATASET_CONFIG)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pdf-root", required=True, help="Directory holding benign/ and injected/.")
    parser.add_argument("--labels", default=str(TABLES_DIR / "labels.parquet"))
    parser.add_argument("--out", default=str(TABLES_DIR / "text_cache.parquet"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--progress-every", type=int, default=2000)
    args = parser.parse_args(argv)

    # The frozen extractor resolves corpus-relative paths against raw_dir.
    dataset_config = {"raw_dir": str(Path(args.pdf_root).resolve())}
    labels = pd.read_parquet(args.labels)
    items = list(zip(labels["pdf_id"].astype(str), labels["file_path"].astype(str), strict=True))
    started = time.time()
    rows: list[tuple[str, str, str]] = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init, initargs=(dataset_config,)) as pool:
        for count, row in enumerate(pool.map(_extract, items, chunksize=64), start=1):
            rows.append(row)
            if count % args.progress_every == 0 or count == len(items):
                print(f"extracted {count:,}/{len(items):,} in {time.time() - started:,.0f}s", file=sys.stderr)
    frame = pd.DataFrame(rows, columns=["pdf_id", "file_path", "raw_text"])
    empty = int((frame["raw_text"].str.len() == 0).sum())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)
    print(f"wrote {out} rows={len(frame):,} empty_text={empty:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
