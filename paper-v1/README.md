# CrackedPDFs paper-v1

This directory is the compact research record for:

> Pukaphol (Volk) Thienpreecha and Karthik Subramanian. “CrackedPDFs: A Controlled Benchmark for Hidden Prompt Injection in PDFs.” arXiv:2607.19396v1, 2026.

- Paper: https://arxiv.org/abs/2607.19396
- Dataset archive: https://doi.org/10.5281/zenodo.21735803
- Version: arXiv v1, submitted 2026-07-03
- Corpus: 29,322 PDFs from 4,983 base documents
- Held-out test set: 2,919 PDFs
- Primary result: 0.960 F1
- Paper-reported paired result: 95.9%

## Contents

| Path | Contents |
| --- | --- |
| [`ERRATA.md`](ERRATA.md) | Documented corrections to how this corpus is described. Read first. |
| [`errata/`](errata/) | Measured evidence tables and figures behind each erratum. |
| [`RESULTS.md`](RESULTS.md) | Paper-facing tables, exact artifact values, and metric provenance. |
| [`DATASET.md`](DATASET.md) | Corpus composition, schema, split design, and availability. |
| [`ENVIRONMENT.md`](ENVIRONMENT.md) | Captured Python and dependency versions. |
| [`claim-scope-report.md`](claim-scope-report.md) | Original publication claim boundary. |
| [`metrics/metrics.json`](metrics/metrics.json) | Full frozen evaluation output. |
| [`metrics/hard-setting-summary.csv`](metrics/hard-setting-summary.csv) | Compact primary metrics and label-shuffle checks. |
| [`metrics/shortcut-feature-audit.csv`](metrics/shortcut-feature-audit.csv) | Shortcut audit table. |
| [`metrics/holdout-*.csv`](metrics/) | Held-out attack-family stress-test tables. |
| [`reproducibility/frozen-splits.json`](reproducibility/frozen-splits.json) | Exact base-document group assignments used by the paper run. |
| [`reproducibility/run-manifest.json`](reproducibility/run-manifest.json) | Commands, source paths, and file hashes captured by the run. |
| [`reproducibility/frozen-artifact-manifest.json`](reproducibility/frozen-artifact-manifest.json) | Full publication artifact inventory. |
| [`reproducibility/source-file-hashes.json`](reproducibility/source-file-hashes.json) | Source snapshot hashes. |
| [`reproducibility/configs/`](reproducibility/configs/) | Dataset, feature, evaluation, and model configurations. |
| [`reproducibility/pip-freeze.txt`](reproducibility/pip-freeze.txt) | Complete Python package capture. |
| [`examples/triplets.jsonl`](examples/triplets.jsonl) | Fifteen exact metadata triplets from the paper corpus. |

## Integrity

| File | SHA-256 |
| --- | --- |
| `reproducibility/frozen-splits.json` | `5ab6a6236cd13613fb194896e38eb6f85c131746df799485e800eab6cff338c3` |
| `metrics/metrics.json` | `19b0b62f12fdbe6eaf909cf376dcc523abfa422ac163fff296ec0c187bff64a9` |
| `reproducibility/run-manifest.json` | `8ca762dda50e34d5b0045491e24fa4adea7f27ed6f871e553de83c6c93f08b5b` |
| `reproducibility/frozen-artifact-manifest.json` | `070b963278275da9b812f4c7a16a4a175084eed868e9f3330bf60b6d4c244516` |

The frozen split hash matches the hash recorded inside the original run manifest.

## Provenance notes

1. The original run records source Git commit `1de100c7460a7409b1cf85ac09c9c150f13b53a9` plus a dirty May 25 working tree. The 146 non-cache source files from that exact working tree are frozen in public commit `86148d92341f26cac04e06ad1492929f68b5da02`; `scripts/verify_source_snapshot.py` checks them against the captured SHA-256 manifest. The 38 recorded `.pyc` cache files are deliberately excluded.
2. The paper calls 95.9% a paired ranking result. The frozen artifact records 0.958890 as paired-set classification accuracy and 1.000 as explicit pairwise rank accuracy. See [`RESULTS.md`](RESULTS.md#paired-result-provenance).
3. The complete PDFs, metadata, frozen features, labels, and split file are published at immutable [Hugging Face dataset revision `245bc98`](https://huggingface.co/datasets/volkthienpreecha/crackedpdfs/tree/245bc98ec7e838346ee6fd5bdf5fed1b16d2a3e5) and archived under [Zenodo DOI `10.5281/zenodo.21735803`](https://doi.org/10.5281/zenodo.21735803).
4. The paper PDF lists two authors. The arXiv abstract page displayed only Pukaphol Thienpreecha when this package was prepared.

## What this package can support

This directory is enough to inspect the reported tables, exact metric outputs, split membership, evaluation configuration, environment capture, and claim boundary.

From the repository root, `make reproduce-results` downloads and hash-verifies the frozen feature, label, split, and metric artifacts, then regenerates the compact hard-setting result table without rebuilding 29,322 PDFs.
