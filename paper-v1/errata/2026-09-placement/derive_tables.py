#!/usr/bin/env python3
"""Regenerate the five derived evidence tables in this directory.

This script produces exactly five CSVs:
  lexical-oracle-tokens.csv, placement-by-spatial-label.csv,
  acrostic-placement-by-strength.csv, pair-matching-by-family.csv,
  length-only-paired-ranker.csv

The sixth file in this directory, placement-audit-summary.csv, is written by
`crackedpdfs-audit corpus` itself and is not produced here. Regenerating the
full evidence set is therefore two steps: run the corpus audit, then run this
script over its output.

Inputs, all from the frozen v1 dataset release (Hugging Face revision
245bc98ec7e838346ee6fd5bdf5fed1b16d2a3e5):

  1. placement-audit.jsonl : output of `crackedpdfs-audit corpus --strict`
     over the extracted v1 corpus (one record per injected and confounder PDF).
  2. data/features.parquet : the frozen structural feature table.
  3. paper-v1/metrics/holdout-matched-counterfactual-metrics.csv : the frozen
     source of the paper hybrid paired-ranking values used for comparison.
     These are read from that file, never hardcoded here.

Pinned SHA-256:
  data/features.parquet  4726c8176c8b9dd7f0a24e6ea9a9d4f7263184562619f30d5f182dc380d32b80
  data/metadata.parquet  41838450b245e22761293db57f05997cd9819a86abe2cc1f362f7cccc9724927

Requirements: Python 3.11+ and pandas (for the parquet feature table). See
README.md in this directory for the pinned environment.

Method notes for every table:
  - pairing key: sample_id (injected and confounder share it).
  - tie handling in paired ranking: ties count as one half.
  - scope: all pairs in each attack family across the whole corpus, not a split.
  - a "length proxy" is a single frozen feature; the larger value is called
     injected.

The audit input must be complete: any record whose status is not "audited"
causes this script to refuse to generate publication tables, unless
--allow-incomplete is passed.

Usage:
  python derive_tables.py --audit placement-audit.jsonl \
    --features features.parquet \
    --paper-metrics ../../metrics/holdout-matched-counterfactual-metrics.csv \
    --out .
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ORACLE_TOKENS = (
    "DATASET_SAMPLE_ID",
    "MESSAGE_TYPE=",
    "SYSTEM_POLICY_DO_NOT_REMOVE",
    "DOCUMENT_LAYOUT_NOTE",
)
def load_paper_hybrid_paired_rank(path: Path) -> dict[str, float]:
    """Read the paper hybrid paired-ranking values from the frozen metrics CSV."""
    values: dict[str, float] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("method") == "hybrid" and row.get("paired_rank_accuracy"):
                values[row["family"]] = float(row["paired_rank_accuracy"])
    if not values:
        raise SystemExit(f"No hybrid paired_rank_accuracy rows found in {path}")
    return values


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_audit(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def lexical_oracle_table(audit: list[dict]) -> list[dict]:
    by_role = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    for rec in audit:
        role = rec["role"]
        totals[role] += 1
        for token in rec.get("lexical_oracle_tokens", []):
            by_role[token][role] += 1
    per_role = min(totals.values()) if totals else 0
    return [
        {
            "token": token,
            "injected_attack_pdfs": by_role[token].get("injected_attack", 0),
            "benign_confounder_pdfs": by_role[token].get("benign_confounder", 0),
            "pdfs_per_role": per_role,
        }
        for token in ORACLE_TOKENS
    ]


def placement_by_label_table(audit: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in audit:
        if rec["role"] == "injected_attack" and not rec.get("error"):
            groups[rec["spatial_label"]].append(rec)
    rows = []
    for label, items in sorted(groups.items()):
        glyphs = sum(int(i["added_glyphs"]) for i in items)
        rows.append(
            {
                "spatial_label": label,
                "injected_pdfs": len(items),
                "label_contract_satisfied": sum(1 for i in items if i.get("contract_satisfied")),
                "added_glyphs": glyphs,
                "frac_glyphs_inside": round(sum(int(i["added_inside"]) for i in items) / glyphs, 4),
                "frac_glyphs_clipped": round(sum(int(i["added_clipped"]) for i in items) / glyphs, 4),
                "frac_glyphs_outside": round(sum(int(i["added_outside"]) for i in items) / glyphs, 4),
                "frac_glyphs_below_page": round(
                    sum(int(i["added_below_page"]) for i in items) / glyphs, 4
                ),
            }
        )
    return rows


def acrostic_by_strength_table(audit: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in audit:
        if rec["role"] == "injected_attack" and rec["family"] == "steganographic_acrostic":
            groups[rec["strength"]].append(rec)
    rows = []
    for strength in ("weak", "medium", "strong"):
        items = groups.get(strength, [])
        if not items:
            continue
        rows.append(
            {
                "strength": strength,
                "injected_pdfs": len(items),
                "mean_added_glyphs": round(sum(int(i["added_glyphs"]) for i in items) / len(items), 1),
                "mean_glyphs_below_page": round(
                    sum(int(i["added_below_page"]) for i in items) / len(items), 1
                ),
                "max_glyphs_inside": max(int(i["added_inside"]) for i in items),
            }
        )
    return rows


def pair_matching_table(audit: list[dict]) -> list[dict]:
    inj = {r["sample_id"]: r for r in audit if r["role"] == "injected_attack" and not r.get("error")}
    con = {r["sample_id"]: r for r in audit if r["role"] == "benign_confounder" and not r.get("error")}
    families: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for sample_id, injected in inj.items():
        confounder = con.get(sample_id)
        if confounder is not None:
            families[injected["family"]].append((injected, confounder))
    rows = []
    for family, pairs in sorted(families.items()):
        same_class = sum(
            1
            for i, c in pairs
            if i["added_realized_spatial_class"] == c["added_realized_spatial_class"]
        )
        rows.append(
            {
                "family": family,
                "pairs": len(pairs),
                "same_realized_class": round(same_class / len(pairs), 4),
                "mean_injected_glyphs": round(sum(int(i["added_glyphs"]) for i, _ in pairs) / len(pairs), 1),
                "mean_confounder_glyphs": round(sum(int(c["added_glyphs"]) for _, c in pairs) / len(pairs), 1),
                "injected_longer": sum(1 for i, c in pairs if int(i["added_glyphs"]) > int(c["added_glyphs"])),
                "confounder_longer": sum(1 for i, c in pairs if int(c["added_glyphs"]) > int(i["added_glyphs"])),
            }
        )
    return rows


def length_ranker_table(features_path: Path, audit: list[dict], paper_values: dict[str, float]) -> list[dict]:
    import pandas as pd

    features = pd.read_parquet(features_path)
    role_by_id = {r["pdf_id"]: r for r in audit}
    fam_by_sample = {r["sample_id"]: r["family"] for r in audit}
    # Map each feature row to (sample_id, role) via pdf_id suffix.
    rows_by_family: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for _, row in features.iterrows():
        pdf_id = str(row["pdf_id"])
        rec = role_by_id.get(pdf_id)
        if rec is None:
            continue
        sample_id, role = rec["sample_id"], rec["role"]
        family = fam_by_sample.get(sample_id)
        if family is None:
            continue
        rows_by_family[family][sample_id][role] = float(row["text_density_per_page"])

    out = []
    for family, samples in sorted(rows_by_family.items()):
        wins = 0.0
        count = 0
        for values in samples.values():
            if "injected_attack" in values and "benign_confounder" in values:
                count += 1
                inj, con = values["injected_attack"], values["benign_confounder"]
                wins += 1.0 if inj > con else 0.5 if inj == con else 0.0
        if count:
            out.append(
                {
                    "family": family,
                    "pairs": count,
                    "text_density_per_page_rank_accuracy": round(wins / count, 4),
                    "paper_hybrid_heldout_paired_rank_accuracy": paper_values.get(family, ""),
                }
            )
    return out


def audit_completeness(audit: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in audit:
        status = str(record.get("status", "audited"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument(
        "--paper-metrics",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "metrics" / "holdout-matched-counterfactual-metrics.csv",
        help="Frozen source of the paper hybrid paired-ranking values.",
    )
    parser.add_argument("--out", type=Path, default=Path("."))
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Generate tables even if the audit input contains non-audited records.",
    )
    args = parser.parse_args()

    audit_sha = sha256(args.audit)
    features_sha = sha256(args.features)
    print(f"audit  {args.audit}  sha256={audit_sha}")
    print(f"features {args.features}  sha256={features_sha}")

    audit = load_audit(args.audit)
    counts = audit_completeness(audit)
    incomplete = {status: n for status, n in counts.items() if status != "audited"}
    if incomplete and not args.allow_incomplete:
        raise SystemExit(
            f"Refusing to build publication tables from incomplete audit input: {incomplete}. "
            "Re-run `crackedpdfs-audit corpus --strict` or pass --allow-incomplete."
        )

    paper_values = load_paper_hybrid_paired_rank(args.paper_metrics)
    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "lexical-oracle-tokens.csv", lexical_oracle_table(audit))
    write_csv(args.out / "placement-by-spatial-label.csv", placement_by_label_table(audit))
    write_csv(args.out / "acrostic-placement-by-strength.csv", acrostic_by_strength_table(audit))
    write_csv(args.out / "pair-matching-by-family.csv", pair_matching_table(audit))
    write_csv(
        args.out / "length-only-paired-ranker.csv",
        length_ranker_table(args.features, audit, paper_values),
    )

    provenance = {
        "generated_tables": 5,
        "audit_jsonl_sha256": audit_sha,
        "audit_record_status_counts": counts,
        "features_parquet_sha256": features_sha,
        "paper_metrics_source": str(args.paper_metrics.name),
        "paper_metrics_sha256": sha256(args.paper_metrics),
    }
    (args.out / "derivation-provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote 5 evidence tables and derivation-provenance.json to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
