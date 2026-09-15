"""crackedpdfs-audit: check where text in a PDF actually lands."""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from .contracts import contract_satisfied, lexical_oracle_hits
from .geometry import added_glyphs, extract_glyphs, summarize_glyphs


def _cmd_file(args: argparse.Namespace) -> int:
    pages = extract_glyphs(args.pdf)
    reference_pages = extract_glyphs(args.reference) if args.reference else []
    report = []
    for index, page in enumerate(pages):
        reference = reference_pages[index] if index < len(reference_pages) else None
        glyphs = added_glyphs(page, reference)
        entry = {
            "page": page.page_number,
            "page_box": page.page_box,
            "scope": "added_vs_reference" if reference else "all_text",
            **summarize_glyphs(glyphs, page.page_box).as_dict(),
            "lexical_oracle_tokens": lexical_oracle_hits("".join(g.text for g in page.glyphs)),
        }
        if args.label:
            entry["label"] = args.label
            entry["contract_satisfied"] = contract_satisfied(args.label, glyphs, page.page_box)
        report.append(entry)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    for entry in report:
        print(
            f"page {entry['page']}  box={tuple(round(v, 1) for v in entry['page_box'])}  scope={entry['scope']}"
        )
        print(
            f"  glyphs={entry['glyphs']:,}  inside={entry['inside']:,}  clipped={entry['clipped']:,}  "
            f"outside={entry['outside']:,} (below={entry['below_page']:,})"
        )
        print(
            f"  invisible_render_mode={entry['invisible_render_mode']:,}  tiny_font={entry['tiny_font']:,}  "
            f"low_contrast_fill={entry['low_contrast_fill']:,}  likely_visible={entry['likely_visible']:,}"
        )
        print(f"  realized={entry['realized_spatial_class']}  preview={entry['text_preview'][:80]!r}")
        if "contract_satisfied" in entry:
            print(f"  label={entry['label']}  contract_satisfied={entry['contract_satisfied']}")
        if entry["lexical_oracle_tokens"]:
            print(f"  lexical_oracle_tokens={entry['lexical_oracle_tokens']}")
    return 0


def _cmd_corpus(args: argparse.Namespace) -> int:
    from .corpus import build_tasks, coverage, coverage_complete, read_metadata, run_audit, write_outputs

    rows = read_metadata(args.metadata)
    families = set(args.families.split(",")) if args.families else None
    tasks = build_tasks(rows, args.root, render=args.render, families=families, paired=not args.unpaired)
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        print("No audited-role rows found in the metadata.", file=sys.stderr)
        return 1
    started = time.time()
    records = []
    for count, record in enumerate(run_audit(tasks, workers=args.workers), start=1):
        records.append(record)
        if count % 1000 == 0 or count == len(tasks):
            print(f"audited {count:,}/{len(tasks):,} PDFs in {time.time() - started:,.0f}s", file=sys.stderr)
    outputs = write_outputs(records, args.out)
    for name, path in outputs.items():
        print(f"{name}: {path}")

    cov = coverage(records)
    if args.unpaired:
        print("mode: UNPAIRED (no reference; all page text counted as added)", file=sys.stderr)
    print(
        f"coverage: records={cov['records']:,} audited={cov['audited']:,} "
        f"missing={cov['missing']:,} reference_missing={cov['reference_missing']:,} "
        f"no_payload={cov['no_payload_detected']:,} "
        f"errors={cov['errors']:,} multi_page={cov['multi_page']:,}",
        file=sys.stderr,
    )
    if args.strict and not coverage_complete(cov):
        print("strict mode: corpus is incomplete (missing files or errors).", file=sys.stderr)
        return 2
    return 0


def _cmd_reveal(args: argparse.Namespace) -> int:
    from .render import reveal

    page = extract_glyphs(args.pdf)[0]
    reference = extract_glyphs(args.reference)[0] if args.reference else None
    glyphs = added_glyphs(page, reference)
    output = reveal(args.pdf, glyphs, page.page_box, args.output, max_side_px=args.max_side, title=args.title)
    print(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crackedpdfs-audit", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    file_cmd = commands.add_parser("file", help="Measure glyph placement and visibility in one PDF.")
    file_cmd.add_argument("pdf")
    file_cmd.add_argument(
        "--reference", help="Clean original; only glyphs added relative to it are measured."
    )
    file_cmd.add_argument("--label", help="spatial_regime label to check, e.g. inside_page.")
    file_cmd.add_argument("--json", action="store_true")
    file_cmd.set_defaults(handler=_cmd_file)

    corpus_cmd = commands.add_parser(
        "corpus", help="Audit an extracted CrackedPDFs corpus against its labels."
    )
    corpus_cmd.add_argument("--root", required=True, help="Directory holding benign/ and injected/.")
    corpus_cmd.add_argument("--metadata", required=True, help="metadata.parquet or metadata.jsonl.")
    corpus_cmd.add_argument("--out", required=True)
    corpus_cmd.add_argument("--workers", type=int)
    corpus_cmd.add_argument(
        "--render", action="store_true", help="Also count changed pixels versus the original."
    )
    corpus_cmd.add_argument("--families", help="Comma-separated attack families to audit.")
    corpus_cmd.add_argument("--limit", type=int)
    corpus_cmd.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any PDF or reference is missing or fails to parse (release gate).",
    )
    corpus_cmd.add_argument(
        "--unpaired",
        action="store_true",
        help=(
            "Audit candidates without their benign originals. All page text counts as added "
            "text, so results are not comparable with paired audits."
        ),
    )
    corpus_cmd.set_defaults(handler=_cmd_corpus)

    reveal_cmd = commands.add_parser("reveal", help="Render off-page and hidden text on an expanded canvas.")
    reveal_cmd.add_argument("pdf")
    reveal_cmd.add_argument("output")
    reveal_cmd.add_argument("--reference")
    reveal_cmd.add_argument("--title")
    reveal_cmd.add_argument("--max-side", type=int, default=1600)
    reveal_cmd.set_defaults(handler=_cmd_reveal)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
