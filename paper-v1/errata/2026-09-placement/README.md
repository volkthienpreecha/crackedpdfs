# Placement erratum evidence (2026-09)

Evidence for [`paper-v1/ERRATA.md`](../../ERRATA.md).

Regenerating this directory is **two steps**. The corpus audit writes
`placement-audit-summary.csv` and the per-PDF `placement-audit.jsonl`;
[`derive_tables.py`](derive_tables.py) then turns that JSONL into the five
derived CSVs. No single script produces all six files.

## Provenance of the published tables

| Item | Value |
| --- | --- |
| Auditor | `crackedpdfs-audit` 0.1.0, repository commit `39ba7bc004bc` |
| Audit command | `crackedpdfs-audit corpus --root crackedpdfs-v1/pdfs --metadata crackedpdfs-v1/data/metadata.parquet --out audit-v1 --render --strict` |
| Corpus revision | Hugging Face `volkthienpreecha/crackedpdfs` at `245bc98ec7e838346ee6fd5bdf5fed1b16d2a3e5` |
| Audit records | `19,548` (9,774 injected + 9,774 confounders) |
| Audit coverage | audited 19,548; missing 0; reference_missing 0; no_payload_detected 0; errors 0 (`--strict` passed) |
| `placement-audit.jsonl` SHA-256 | `bb977bcf59af8e43fe0dfdd70d44ad8f27ca32c4897243afdffb17e72828f50c` |
| `data/features.parquet` SHA-256 | `4726c8176c8b9dd7f0a24e6ea9a9d4f7263184562619f30d5f182dc380d32b80` |
| `data/metadata.parquet` SHA-256 | `41838450b245e22761293db57f05997cd9819a86abe2cc1f362f7cccc9724927` |
| Paper comparison values | Read from [`../../metrics/holdout-matched-counterfactual-metrics.csv`](../../metrics/holdout-matched-counterfactual-metrics.csv) (`method = hybrid`, column `paired_rank_accuracy`), never retyped |

`derivation-provenance.json` in this directory records the checksums and record
status counts of the inputs actually used for the committed tables. A checksum
printed by a later run identifies that run, not this evidence.

## Environment

Python 3.11 or newer, plus:

```bash
pip install -e "tools/crackedpdfs-audit[parquet]"   # auditor, pdfminer.six, pypdfium2
pip install "pandas>=2.2"                            # derive_tables.py only
```

## Regenerate

```bash
# 1. Audit the corpus. --strict fails the run if any PDF, benign original, or
#    payload is missing, so the tables are never built from a partial audit.
crackedpdfs-audit corpus --root crackedpdfs-v1/pdfs \
  --metadata crackedpdfs-v1/data/metadata.parquet --out audit-v1 --render --strict

# 2. Derive the five CSVs. This refuses incomplete audit input unless
#    --allow-incomplete is passed.
python derive_tables.py --audit audit-v1/placement-audit.jsonl \
  --features crackedpdfs-v1/data/features.parquet --out .
```

## Method

- Pairing key: `sample_id` (an injected PDF and its confounder share it).
- Scope: all pairs in each attack family across the whole corpus, not a split.
- Paired ranking: the larger value of a length proxy is called injected; ties count as one half.
- Placement classes and glyph counts come from `crackedpdfs-audit`, which reads glyph geometry from the PDF content stream and never from generator metadata.
- Placement verdicts are computed over pages that carry added glyphs. Every v1 PDF is single-page, so this does not change the v1 numbers; it matters for multi-page corpora.

## Files

| File | Produced by | Contents |
| --- | --- | --- |
| `placement-audit-summary.csv` | step 1 (auditor) | Grouped summary (role x family x label). |
| `lexical-oracle-tokens.csv` | step 2 | Per-role frequency of the four bookkeeping tokens. |
| `placement-by-spatial-label.csv` | step 2 | Injected-PDF placement fractions grouped by `spatial_regime` label. |
| `acrostic-placement-by-strength.csv` | step 2 | Acrostic glyph counts and below-page counts by strength. |
| `pair-matching-by-family.csv` | step 2 | Per-family realized-class match rate and injected-vs-confounder length. |
| `length-only-paired-ranker.csv` | step 2 | Paired-ranking accuracy of one frozen length feature versus the paper hybrid. |
| `derivation-provenance.json` | step 2 | Checksums and audit status counts of the inputs used. |
| `v1-acrostic-off-page.png`, `fixed-acrostic-in-page.png` | `crackedpdfs-audit reveal` | Renders before and after the generator fix. |
