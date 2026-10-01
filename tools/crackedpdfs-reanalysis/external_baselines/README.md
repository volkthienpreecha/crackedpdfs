# External hidden-text detector baselines

Drivers that run three independently written, open-source hidden-text detectors over the paper v1
frozen test split and reduce their output to a common per-file table so they can be reported as
baselines. The detectors are used unmodified at the commits recorded in the run metadata; only the
orchestration and the reduction to `flagged`, `score` and `techniques` live here.

Outputs are written to `.cache/crackedpdfs-reanalysis/artifacts/external_baselines/` at the repository root (override with `--out-dir`):

| File | Content |
|---|---|
| `<name>_per_file.csv` | One row per test PDF: `pdf_id, label, pdf_role, attack_family, flagged, score, techniques, error, seconds` |
| `<name>_run.json` | Detector commit, version, interpreter, exact command template, flag and score rules, worker count, wall-clock time, error and timeout counts |
| `summary.json`, `summary.md` | Metrics across all detectors (see `summarize.py`) |

## Detectors

| Name | Source | License | Mechanism |
|---|---|---|---|
| `phantomlint` | https://github.com/tobycmurray/phantom-lint | BSD-3-Clause | Renders each text block, OCRs it with Tesseract and reports extracted text that is absent from the OCR. The default `nlp` analyzer first filters blocks by sentence-transformer similarity to ten built-in prompt-injection phrases; only matching blocks are OCR-diffed. |
| `phantomlint_passthrough` | same | same | Same pipeline with `--analyze passthrough`, which sends every text block through the OCR diff and therefore measures the hidden-text mechanism without the prompt-content filter. |
| `hidden_text_detector` | https://github.com/wppoland/hidden-text-detector | MIT | Structural checks with PyMuPDF: rendered-pixel contrast of each span's area, sub-legible font size, off-page placement, invisible render mode, transparency, hidden optional content groups, invisible Unicode. |
| `pdf_injection_scanner` | https://github.com/Andy8647/pdf-injection-scanner | MIT | Character-level checks with pdfplumber: white or near-white fill colour, font size below 2 pt, off-page coordinates, plus regex patterns for prompt-injection phrases. |

## Setup

All paths below match the defaults in `baseline_common.py`; override with the driver flags if the
corpus or clones live elsewhere. Tesseract and Poppler must be on `PATH` (Homebrew:
`brew install tesseract poppler`).

```bash
mkdir -p $CRACKEDPDFS_WORK/baselines
cd $CRACKEDPDFS_WORK/baselines

# PhantomLint. The project declares python_requires >=3.9,<3.13 and its pinned llm-guard
# dependency has no Python 3.13 wheels, so this one detector uses Python 3.12 and the
# project's frozen requirement set.
git clone https://github.com/tobycmurray/phantom-lint
cd phantom-lint
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-frozen.txt
.venv/bin/python -m spacy download en_core_web_sm
uv pip install --python .venv/bin/python --no-deps -e .
cd ..

# hidden-text-detector
git clone https://github.com/wppoland/hidden-text-detector
cd hidden-text-detector
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cd ..

# pdf-injection-scanner
git clone https://github.com/Andy8647/pdf-injection-scanner
cd pdf-injection-scanner
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e .
cd ..
```

## Running

```bash
cd tools/crackedpdfs-reanalysis/external_baselines
python3 run_hidden_text_detector.py --workers 6
python3 run_pdf_injection_scanner.py --workers 6
python3 run_phantomlint.py --workers 3                      # default nlp analyzer
python3 run_phantomlint.py --workers 3 --analyze passthrough
python3 summarize.py
```

Every driver accepts `--limit N` for a smoke test, `--split` to point at a different listing, and
`--out-dir` to redirect the artifacts. Each PDF is given a hard 120 second budget; a file that
exceeds it is recorded with `error=timeout`, `flagged=0` and `score=0`, and the run continues.

PhantomLint's import graph (torch, sentence-transformers, spaCy, llm-guard) takes over a minute to
load, so `run_phantomlint.py` keeps a pool of persistent worker processes
(`phantomlint_worker.py`) that each load the pipeline once with the same component defaults as the
`phantomlint` console script (300 dpi, `noop` splitter, exact word diff, similarity threshold 0.75,
built-in bad-phrase list) and process PDFs sent over standard input. A worker that overruns the
budget is killed and replaced. Raw PhantomLint reports for every file are kept under
`$CRACKEDPDFS_WORK/baselines/phantomlint_reports/<mode>/<pdf_id>/`. Each worker holds a
loaded torch model, so keep the worker count modest on machines with 8 GB of memory.

## Flag and score rules

| Detector | `flagged` = 1 when | `score` | `techniques` |
|---|---|---|---|
| `phantomlint` and `phantomlint_passthrough` | at least one hidden suspicious phrase is reported (console script exit status 1) | number of characters highlighted as hidden in `hidden_suspicious_phrases.txt` | `hidden_suspicious_text`, `suspicious_visible_only`, or empty |
| `hidden_text_detector` | any finding with severity `CRITICAL` (the tool's own exit-code rule) | `critical_count + 0.1 * warning_count` | distinct CRITICAL and WARNING finding types joined with `\|` |
| `pdf_injection_scanner` | any finding (the tool has no severity-based verdict) | `high_count + 0.1 * medium_count` | distinct finding types joined with `\|` |

## Metrics

`summarize.py` computes, for each detector, accuracy, precision, recall and F1 with `flagged` as
the positive prediction and ROC-AUC from `score` (rank-sum formulation, ties count one half), on
the full split and on the paired subset of injected and benign-confounder PDFs. It also reports
paired ranking accuracy (the injected PDF scores strictly above its matched confounder within the
same `triad_id`; ties count one half), flag rates per `pdf_role` and per `attack_family`, technique
frequencies among flagged files, and the error and timeout counts. It uses only the standard
library.

## Off-the-shelf prompt-injection text classifiers (`run_text_classifiers.py`)

Scores the frozen paper v1 test split with publicly available prompt-injection text classifiers so that the
structural detector can be compared against text-only defenses. Text comes from the pypdf text cache
(`data/processed/hard_provenance/text_cache.parquet`) and is scored under two conditions:

* `raw`: the extracted text as cached.
* `sanitized`: the same text after `apply_text_preprocessing` from `src/models/text_preprocessing.py`, configured
  with the `text_tfidf` block of `configs/model_hybrid_hard_provenance.yaml` (benchmark wrapper and synthetic phrase
  marker stripping enabled). The sanitizer is imported, not copied or modified.

Two document scores are recorded for every (model, condition) pair:

* `score_max_chunk`: the text is split into windows of at most 400 model tokens with 50 overlapping tokens and the
  document score is the maximum window score.
* `score_first_512`: the score of the first 512 tokens only, which quantifies what plain truncation loses.

Models (all ungated, loaded from the Hugging Face Hub at the revision recorded in `summary.json`):

| key | repository | positive class |
|---|---|---|
| `protectai_deberta_v3_base_pi_v2` | `protectai/deberta-v3-base-prompt-injection-v2` | `INJECTION` (id 1) |
| `horizon_labs_pi_guard_base` | `Horizon-Labs/prompt-injection-guard-base` | `INJECTION` (id 1) |
| `prompt_guard_2_86m` | `gravitee-io/Llama-Prompt-Guard-2-86M-onnx` (PyTorch weights in the mirror) | `MALICIOUS` (id 1) |
| `deepset_deberta_v3_base_injection` | `deepset/deberta-v3-base-injection` | `INJECTION` (id 1) |

The score is always the softmax probability of the positive class. Identical token sequences are scored once, and
documents are processed in split order so that the per-model time limit (default 60 minutes) leaves a contiguous
prefix of fully scored documents; partially scored models are flagged `timed_out_partial` in the summary.

Environment: a dedicated virtual environment with `torch` (CPU), `transformers`, `huggingface_hub`, `pandas`,
`pyarrow`, `scikit-learn` and `pyyaml`; Python 3.13. Example:

```bash
uv venv --python 3.13 /path/to/text-venv
uv pip install --python /path/to/text-venv/bin/python torch transformers huggingface_hub pandas pyarrow scikit-learn pyyaml
cd lightweight-detector
/path/to/text-venv/bin/python scripts/external_baselines/run_text_classifiers.py \
    --test-split /path/to/test_split.csv \
    --output-dir data/artifacts/text_baselines
```

Useful flags: `--models` (subset of keys), `--limit N` (smoke test), `--batch-size`, `--chunk-tokens`,
`--chunk-overlap`, `--time-limit-minutes`, `--threads`, and `--resume`, which reuses completed per-model outputs
already present in the output directory so that a single model can be re-run and merged with the others.

Outputs in `data/artifacts/text_baselines/`:

* `per_file_scores.parquet` and `.csv`: one row per (pdf, model, condition) with `pdf_id`, `label`, `pdf_role`,
  `attack_family`, `triad_id`, `base_pdf_id`, `model`, `condition`, `score_max_chunk`, `score_first_512`,
  `n_chunks`, `n_tokens`. A per-model copy is also written as `per_file_scores_<model key>.parquet`.
* `summary.json` and `summary.md`: for each model, condition and scoring rule, ROC-AUC, PR-AUC, F1 at 0.5, F1 at
  the best test-set threshold (labelled optimistic), recall at 1% false positive rate, paired ranking accuracy of
  the injected PDF against its matched benign confounder and against its benign original (ties count one half),
  and per-attack-family recall at 0.5. The summary also records model revisions, label mappings, sanitizer
  configuration, library versions, throughput and wall-clock time.
