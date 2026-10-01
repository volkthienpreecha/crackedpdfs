"""Command-line interface: build the payload pool and report statistics."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from crackedpdfs_payloads import __version__
from crackedpdfs_payloads.cluster import cluster_texts, nearest_jaccard
from crackedpdfs_payloads.normalize import (
    MAX_CHARS,
    MESSAGE_TYPES,
    MIN_CHARS,
    UNCLASSIFIED,
    classify_message_type,
    dedupe_key,
    detect_language,
    is_valid_length,
    normalize_text,
    payload_id,
)
from crackedpdfs_payloads.sources import V1_SOURCE, RawRecord, SourceResult, all_loaders

PACKAGE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_V1_FILE = PACKAGE_DIR.parents[1] / "src" / "lib" / "prompt-injection-message-library.ts"
DEFAULT_README = PACKAGE_DIR / "README.md"
SUMMARY_START = "<!-- summary:start -->"
SUMMARY_END = "<!-- summary:end -->"

FIELDS: tuple[str, ...] = (
    "id",
    "text",
    "source",
    "source_record",
    "license",
    "url",
    "retrieved_at",
    "language",
    "message_type",
    "message_type_source",
    "cluster_id",
    "nearest_v1_jaccard",
    "char_length",
)


def normalise_records(records: Sequence[RawRecord]) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Normalise, length-filter, and exactly deduplicate raw records.

    Returns the surviving payload rows (without cluster fields) and a counter of drop reasons per source.
    Records are processed in input order, so the first occurrence of a duplicate text wins; v1 messages
    are loaded first and therefore keep their author-assigned type.
    """
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    drops: Counter[str] = Counter()
    for record in records:
        text = normalize_text(record.text)
        if not is_valid_length(text):
            drops[f"{record.source}|length"] += 1
            continue
        key = dedupe_key(text)
        if key in seen:
            drops[f"{record.source}|duplicate"] += 1
            continue
        seen.add(key)
        if record.message_type:
            message_type, type_source = record.message_type, "author"
        else:
            message_type, type_source = classify_message_type(text), "rule"
        rows.append(
            {
                "id": payload_id(text),
                "text": text,
                "source": record.source,
                "source_record": record.source_record,
                "license": record.license,
                "url": record.url,
                "retrieved_at": record.retrieved_at,
                "language": detect_language(text),
                "message_type": message_type,
                "message_type_source": type_source,
                "char_length": len(text),
            }
        )
    return rows, drops


def attach_clusters(rows: list[dict[str, Any]]) -> None:
    """Add cluster_id and nearest_v1_jaccard to each row in place.

    Rows are sorted by id first so that cluster numbering is deterministic across runs.
    """
    rows.sort(key=lambda row: row["id"])
    texts = [row["text"] for row in rows]
    v1_texts = [row["text"] for row in rows if row["source"] == V1_SOURCE]
    cluster_ids = cluster_texts(texts)
    nearest = nearest_jaccard(texts, v1_texts)
    for row, cluster_id, score in zip(rows, cluster_ids, nearest, strict=True):
        row["cluster_id"] = cluster_id
        row["nearest_v1_jaccard"] = score


def summarise(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compute the summary statistics reported in sources.json, the README, and the stats command."""
    by_source = Counter(row["source"] for row in rows)
    by_type = Counter(row["message_type"] for row in rows)
    by_language = Counter(row["language"] for row in rows)
    clusters = Counter(row["cluster_id"] for row in rows)
    v1_clusters = {row["cluster_id"] for row in rows if row["source"] == V1_SOURCE}
    external_in_v1_cluster = sum(1 for row in rows if row["source"] != V1_SOURCE and row["cluster_id"] in v1_clusters)
    external_high_overlap = sum(1 for row in rows if row["source"] != V1_SOURCE and row["nearest_v1_jaccard"] >= 0.7)
    return {
        "total_messages": len(rows),
        "by_source": dict(sorted(by_source.items())),
        "by_message_type": {t: by_type.get(t, 0) for t in (*MESSAGE_TYPES, UNCLASSIFIED)},
        "by_language": dict(by_language.most_common()),
        "cluster_count": len(clusters),
        "singleton_clusters": sum(1 for n in clusters.values() if n == 1),
        "largest_cluster": max(clusters.values(), default=0),
        "v1_cluster_count": len(v1_clusters),
        "external_in_v1_cluster": external_in_v1_cluster,
        "external_nearest_v1_jaccard_ge_0_7": external_high_overlap,
    }


def render_summary(summary: dict[str, Any], sources: Sequence[dict[str, Any]] | None = None) -> str:
    """Render the summary as Markdown tables."""
    lines = ["| Metric | Value |", "| --- | ---: |"]
    lines.append(f"| Total messages | {summary['total_messages']} |")
    lines.append(f"| Clusters | {summary['cluster_count']} |")
    lines.append(f"| Singleton clusters | {summary['singleton_clusters']} |")
    lines.append(f"| Largest cluster | {summary['largest_cluster']} |")
    lines.append(f"| Clusters containing a v1 message | {summary['v1_cluster_count']} |")
    lines.append(f"| External messages sharing a cluster with a v1 message | {summary['external_in_v1_cluster']} |")
    lines.append(
        f"| External messages with nearest v1 Jaccard >= 0.7 | {summary['external_nearest_v1_jaccard_ge_0_7']} |"
    )
    lines.append("")
    lines.append("| Source | License | Raw rows | Kept |")
    lines.append("| --- | --- | ---: | ---: |")
    source_meta = {s["name"]: s for s in sources or []}
    for name, count in summary["by_source"].items():
        meta = source_meta.get(name, {})
        lines.append(f"| {name} | {meta.get('license', '')} | {meta.get('raw_count', '')} | {count} |")
    for meta in sources or []:
        if meta.get("skipped"):
            lines.append(f"| {meta['name']} (skipped) | {meta.get('license', '')} | | 0 |")
    lines.append("")
    lines.append("| Message type | Count |")
    lines.append("| --- | ---: |")
    for message_type, count in summary["by_message_type"].items():
        lines.append(f"| {message_type} | {count} |")
    lines.append("")
    lines.append("| Language | Count |")
    lines.append("| --- | ---: |")
    for language, count in list(summary["by_language"].items())[:8]:
        lines.append(f"| {language} | {count} |")
    return "\n".join(lines)


def update_readme(readme: Path, table: str) -> bool:
    """Replace the block between the summary markers in README.md. Returns False when markers are missing."""
    if not readme.exists():
        return False
    content = readme.read_text(encoding="utf-8")
    if SUMMARY_START not in content or SUMMARY_END not in content:
        return False
    head, rest = content.split(SUMMARY_START, 1)
    _, tail = rest.split(SUMMARY_END, 1)
    readme.write_text(f"{head}{SUMMARY_START}\n{table}\n{SUMMARY_END}{tail}", encoding="utf-8")
    return True


def write_outputs(
    out_dir: Path, rows: Sequence[dict[str, Any]], results: Sequence[SourceResult], drops: Counter[str]
) -> None:
    """Write payloads.jsonl and sources.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "payloads.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({field: row[field] for field in FIELDS}, ensure_ascii=False) + "\n")
    kept = Counter(row["source"] for row in rows)
    sources_manifest = []
    for result in results:
        block = result.manifest()
        block["kept_count"] = kept.get(result.name, 0)
        block["dropped_length"] = drops.get(f"{result.name}|length", 0)
        block["dropped_duplicate"] = drops.get(f"{result.name}|duplicate", 0)
        sources_manifest.append(block)
    manifest = {
        "package": "crackedpdfs-payloads",
        "version": __version__,
        "processing": {
            "min_chars": MIN_CHARS,
            "max_chars": MAX_CHARS,
            "dedupe": "exact, case-insensitive, after whitespace and quote normalisation",
            "id": "pl- plus first 12 hex of sha256(normalised text)",
            "clustering": (
                "MinHash (128 permutations) over character 5-gram shingles, LSH threshold 0.7, union-find components"
            ),
        },
        "sources": sources_manifest,
        "summary": summarise(rows),
    }
    (out_dir / "sources.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build(out_dir: Path, v1_file: Path, readme: Path | None) -> int:
    """Run the full pipeline and write the outputs. Returns a process exit code."""
    results: list[SourceResult] = []
    records: list[RawRecord] = []
    for loader in all_loaders(v1_file):
        try:
            result = loader()
        except Exception as exc:  # noqa: BLE001 - a failed source must not abort the whole build
            name = getattr(loader, "__name__", "source")
            print(f"[build] {name} failed: {exc}", file=sys.stderr)
            continue
        status = f"skipped ({result.skip_reason})" if result.skipped else f"{len(result.records)} raw records"
        print(f"[build] {result.name}: {status}", file=sys.stderr)
        results.append(result)
        records.extend(result.records)
    rows, drops = normalise_records(records)
    attach_clusters(rows)
    write_outputs(out_dir, rows, results, drops)
    summary = summarise(rows)
    table = render_summary(summary, [r.manifest() | {"raw_count": r.raw_count} for r in results])
    if readme is not None and update_readme(readme, table):
        print(f"[build] summary written to {readme}", file=sys.stderr)
    print(table)
    return 0


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Read a payloads.jsonl file."""
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def stats(path: Path) -> int:
    """Print summary statistics for an existing payloads.jsonl."""
    rows = load_rows(path)
    print(render_summary(summarise(rows)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(prog="crackedpdfs-payloads", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build", help="download all sources and write payloads.jsonl and sources.json")
    build_cmd.add_argument("--out", type=Path, default=Path("data"), help="output directory (default: data/)")
    build_cmd.add_argument("--v1-file", type=Path, default=DEFAULT_V1_FILE, help="path to the v1 TypeScript library")
    build_cmd.add_argument(
        "--readme", type=Path, default=DEFAULT_README, help="README to refresh with the summary table"
    )
    build_cmd.add_argument("--no-readme", action="store_true", help="do not touch the README")
    stats_cmd = sub.add_parser("stats", help="print statistics for an existing payloads.jsonl")
    stats_cmd.add_argument("path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    if args.command == "build":
        return build(args.out, args.v1_file, None if args.no_readme else args.readme)
    return stats(args.path)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
