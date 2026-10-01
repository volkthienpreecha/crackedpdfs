# crackedpdfs-reanalysis

Re-analysis of the CrackedPDFs paper v1 detectors under stricter evaluation protocols: documents and payloads held out together, symmetric text sanitization, and leave-one-attack-family-out for every detector. Results and interpretation are in [`paper-v2/V1-REANALYSIS.md`](../../paper-v2/V1-REANALYSIS.md).

`benchmark` `evaluation` `prompt-injection` `pdf` `shortcut-learning` `cluster-bootstrap`

## Why a separate package

The detector under `lightweight-detector/` is byte-pinned to the paper and verified by `scripts/verify_source_snapshot.py`; nothing in it may change. This package imports that frozen code unchanged (see `src/crackedpdfs_reanalysis/detector.py`), feeds it the frozen release tables plus a persisted text cache, and evaluates it under new splits. Every retrained number can be checked against the published one first (section 1 of the results document).

## Layout

| Path | Purpose |
| --- | --- |
| `src/crackedpdfs_reanalysis/protocols.py` | Fold assignment over documents and payloads, the C2 / C2p / C3 cells, family holdout, document-grouped validation carve |
| `src/crackedpdfs_reanalysis/models.py` | Model factories that read the paper's own training YAML files |
| `src/crackedpdfs_reanalysis/metrics.py` | Paired ranking, cluster bootstrap by document or payload, design-effect sample size, vectorized best-F1 threshold |
| `src/crackedpdfs_reanalysis/sanitizer.py` | The frozen sanitizer plus a symmetric variant that keeps both roles' scaffold contents |
| `src/crackedpdfs_reanalysis/run.py` | Experiments: `frozen`, `both_out`, `family` |
| `src/crackedpdfs_reanalysis/text_cache.py` | One-time pypdf extraction for all PDFs |
| `src/crackedpdfs_reanalysis/release_audit.py` | Split consistency, payload overlap, and file identity checks on a public release |
| `src/crackedpdfs_reanalysis/sanitizer_residual.py` | Characters added per pair member before and after sanitization |
| `configs/` | Training configurations for the symmetric-sanitizer variants |
| `external_baselines/` | Drivers for PhantomLint, hidden-text-detector, pdf-injection-scanner, and off-the-shelf text classifiers |
| `real_negatives/` | GovDocs1 sample builder with hidden-text screening |
| `tests/` | Protocol invariants, metric equivalence with the frozen implementation, sanitizer behaviour |

Work files live outside the frozen tree, by default in `.cache/crackedpdfs-reanalysis/` at the repository root (`tables/` for the frozen release tables and text cache, `artifacts/` for results). Override with `CRACKEDPDFS_REANALYSIS_WORK`.

## Setup

```bash
cd tools/crackedpdfs-reanalysis
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

Fetch the frozen tables listed in `paper-v1/reproducibility/download-manifest.json` into `.cache/crackedpdfs-reanalysis/tables/` and extract the v1 PDFs (Hugging Face revision `245bc98`, `pdfs/benign.tar.gz` and `pdfs/injected.tar.gz`) anywhere.

## Run

```bash
crackedpdfs-reanalysis text-cache --pdf-root /path/to/pdfs
crackedpdfs-reanalysis release-audit --extra-file /path/to/metadata.parquet
crackedpdfs-reanalysis sanitizer-residual
crackedpdfs-reanalysis run --experiments frozen,both_out,family --folds 5 --bootstrap 1000
crackedpdfs-reanalysis run --experiments frozen,both_out \
  --models hybrid_symmetric_sanitizer,text_tfidf_symmetric_sanitizer --out .cache/crackedpdfs-reanalysis/artifacts/symmetric
```

Each text model takes about two hours for the full protocol on eight cores. `--models` accepts a subset so experiments can run as parallel processes.

## Protocol summary

Triads (benign original, matched confounder, injected PDF) are the unit of assignment. Documents are dealt into *k* folds; payloads are dealt into *k* folds within each message type. For fold *i*, training uses every triad whose document and payload are both outside fold *i*. Test cells: C2 (document unseen, payload seen), C2p (document seen, payload unseen), C3 (both unseen). Thresholds come from a document-grouped validation slice of the training set. Intervals are percentile intervals from resampling whole base documents (and, separately, whole payloads) with replacement.
