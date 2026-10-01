"""Audit a released CrackedPDFs label table against its frozen split file.

Checks that anyone can run on the public release without the PDFs:

1. split consistency: the ``dataset_split`` column of the label table must
   agree with the ``train_ids``, ``val_ids``, and ``test_ids`` lists in the
   frozen split file;
2. payload overlap: how many distinct injected messages exist, how often each
   is reused, and whether any test payload also appears in training;
3. file identity: whether two release files are byte-identical.

Usage:
    crackedpdfs-reanalysis release-audit --extra-file metadata.parquet
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from crackedpdfs_reanalysis.detector import ARTIFACTS_DIR, TABLES_DIR

PAYLOAD_COLUMN = "message_variant_id"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_consistency(labels: pd.DataFrame, splits: dict[str, Any]) -> dict[str, Any]:
    frozen = {}
    for name, key in (("train", "train_ids"), ("validation", "val_ids"), ("test", "test_ids")):
        for pdf_id in splits[key]:
            frozen[pdf_id] = name
    column = labels.set_index("pdf_id")["dataset_split"].astype(str)
    missing = sorted(set(frozen) - set(column.index))
    compared = column.loc[[i for i in column.index if i in frozen]]
    frozen_series = pd.Series({i: frozen[i] for i in compared.index})
    agree = compared == frozen_series
    cross = pd.crosstab(frozen_series.rename("frozen_split"), compared.rename("column_split"))
    return {
        "rows_in_split_file": len(frozen),
        "rows_missing_from_table": len(missing),
        "rows_compared": int(len(compared)),
        "rows_agree": int(agree.sum()),
        "agreement_rate": float(agree.mean()) if len(agree) else None,
        "crosstab_frozen_rows_by_column": {
            str(k): {str(c): int(v) for c, v in row.items()} for k, row in cross.iterrows()
        },
    }


def payload_overlap(labels: pd.DataFrame, splits: dict[str, Any]) -> dict[str, Any]:
    injected = labels[labels["label"].astype(int) == 1].set_index("pdf_id")
    by_split = {
        name: injected.loc[[i for i in splits[key] if i in injected.index]]
        for name, key in (("train", "train_ids"), ("validation", "val_ids"), ("test", "test_ids"))
    }
    variants = {name: set(frame[PAYLOAD_COLUMN].astype(str)) for name, frame in by_split.items()}
    uses = injected[PAYLOAD_COLUMN].value_counts()
    test = by_split["test"]
    seen_in_train = test[PAYLOAD_COLUMN].astype(str).isin(variants["train"])
    per_type = injected.groupby("message_type")[PAYLOAD_COLUMN].nunique()
    return {
        "injected_rows": int(len(injected)),
        "distinct_payloads": int(injected[PAYLOAD_COLUMN].nunique()),
        "payloads_per_message_type": {str(k): int(v) for k, v in per_type.items()},
        "uses_per_payload": {"min": int(uses.min()), "median": float(uses.median()), "max": int(uses.max())},
        "distinct_payloads_by_split": {name: len(values) for name, values in variants.items()},
        "payloads_in_all_three_splits": len(variants["train"] & variants["validation"] & variants["test"]),
        "test_injected_rows": int(len(test)),
        "test_injected_rows_with_payload_seen_in_train": int(seen_in_train.sum()),
        "test_payloads_unseen_in_train": sorted(variants["test"] - variants["train"]),
        "documents_per_payload": {
            "median": float(injected.groupby(PAYLOAD_COLUMN)["base_pdf_id"].nunique().median()),
            "max": int(injected.groupby(PAYLOAD_COLUMN)["base_pdf_id"].nunique().max()),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    consistency = report["split_consistency"]
    overlap = report["payload_overlap"]
    lines = [
        "# Release table audit",
        "",
        "## Split consistency",
        "",
        f"Rows compared: {consistency['rows_compared']:,}. Rows whose `dataset_split` column agrees with the frozen split file: "
        f"{consistency['rows_agree']:,} ({100 * (consistency['agreement_rate'] or 0):.1f}%).",
        "",
        "| frozen split | "
        + " | ".join(
            sorted({c for row in consistency["crosstab_frozen_rows_by_column"].values() for c in row})
        )
        + " |",
    ]
    columns = sorted({c for row in consistency["crosstab_frozen_rows_by_column"].values() for c in row})
    lines.append("| --- |" + " ---: |" * len(columns))
    for frozen, row in consistency["crosstab_frozen_rows_by_column"].items():
        lines.append(f"| {frozen} | " + " | ".join(f"{row.get(c, 0):,}" for c in columns) + " |")
    lines += [
        "",
        "## Payload overlap",
        "",
        "| Quantity | Value |",
        "| --- | ---: |",
        f"| Injected PDFs | {overlap['injected_rows']:,} |",
        f"| Distinct payloads | {overlap['distinct_payloads']} |",
        f"| Payloads present in train, validation, and test | {overlap['payloads_in_all_three_splits']} |",
        f"| Uses per payload (min / median / max) | {overlap['uses_per_payload']['min']} / {overlap['uses_per_payload']['median']:.0f} / {overlap['uses_per_payload']['max']} |",
        f"| Test injected PDFs | {overlap['test_injected_rows']:,} |",
        f"| Test injected PDFs whose payload appears in training | {overlap['test_injected_rows_with_payload_seen_in_train']:,} |",
        f"| Test payloads never seen in training | {len(overlap['test_payloads_unseen_in_train'])} |",
        "",
        "## File identity",
        "",
    ]
    for name, digest in report["file_sha256"].items():
        lines.append(f"- `{name}`: `{digest}`")
    if report.get("identical_files"):
        lines.append("")
        lines.append(
            "Byte-identical pairs: " + ", ".join(" = ".join(pair) for pair in report["identical_files"])
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--labels", default=str(TABLES_DIR / "labels.parquet"))
    parser.add_argument("--splits", default=str(TABLES_DIR / "splits.json"))
    parser.add_argument(
        "--extra-file", action="append", default=[], help="Other release files to hash and compare."
    )
    parser.add_argument("--out", default=str(ARTIFACTS_DIR / "release_audit"))
    args = parser.parse_args(argv)

    labels = pd.read_parquet(args.labels)
    with open(args.splits, encoding="utf-8") as handle:
        splits = json.load(handle)
    files = {Path(p).name: Path(p) for p in [args.labels, args.splits, *args.extra_file]}
    digests = {name: sha256(path) for name, path in files.items()}
    identical = []
    names = list(digests)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            if digests[left] == digests[right]:
                identical.append((left, right))
    report = {
        "split_consistency": split_consistency(labels, splits),
        "payload_overlap": payload_overlap(labels, splits),
        "file_sha256": digests,
        "identical_files": identical,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "release_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "release_audit.md").write_text(render_markdown(report), encoding="utf-8")
    print((out / "release_audit.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
