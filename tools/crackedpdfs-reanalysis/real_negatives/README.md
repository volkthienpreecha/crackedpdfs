# Real-world negatives from GovDocs1

This directory holds the driver that assembles a sample of real-world, benign PDFs for
false-positive testing of the CrackedPDFs detectors and screens each file for pre-existing
hidden text with `crackedpdfs-audit`. The synthetic benchmark pairs every injected PDF with its
clean original, so a detector can look good on it while still firing on ordinary government
documents that happen to contain clipped headers, white-on-white form text, or text parked past
the page edge. This sample makes that failure mode measurable.

## Source and license

The files come from GovDocs1, a corpus of about one million documents collected from United
States government web servers and distributed by Digital Corpora for research use:
https://digitalcorpora.org/corpora/file-corpora/files/. GovDocs1 files are US government public
documents and are freely redistributable. The corpus is organised in 1,000 threads of 1,000 files
each and is mirrored in the AWS Open Data bucket
`s3://digitalcorpora/corpora/files/govdocs1/zipfiles/` as one archive per thread (`000.zip` to
`999.zip`, roughly 330 MB each). Cite Digital Corpora when publishing results derived from the
sample.

## What the driver does

`build_govdocs1_sample.py` runs four resumable stages inside a work directory:

| Stage | Output | Behaviour |
| --- | --- | --- |
| `download` | `pdfs/`, `download_state.json` | Shuffles thread ids 000 to 999 with `random.Random(seed)`, downloads one thread archive at a time with `aws s3 cp --no-sign-request` (or anonymous HTTPS when the CLI is absent), keeps `.pdf` members at or below `--max-file-bytes`, deduplicates by SHA-256 while extracting, deletes the archive, and stops once `--target` unique PDFs are on disk. |
| `inspect` | `inspect.json` | Opens each PDF with pikepdf and records page count, PDF version, and the `/Producer` string from the Info dictionary. Files that fail to open stay on disk and are recorded as unreadable. |
| `audit` | `audit.json` | Runs `crackedpdfs-audit file <pdf> --json` on every readable file in a process pool and sums the per-page counters `glyphs`, `outside`, `clipped`, `invisible_render_mode`, `tiny_font`, `low_contrast_fill`, and `likely_visible`. |
| `manifest` | `manifest.parquet`, `manifest.csv`, `summary.md` | Joins the three records per file. `screened_clean` is true only when all five hidden-text indicators are zero and neither pikepdf nor the audit reported an error. |

Every stage caches its results, so an interrupted run resumes where it stopped and `--stage`
re-runs only the later parts.

## Setup

```bash
mkdir -p ~/crackedpdfs-work/real-negatives/govdocs1
cd ~/crackedpdfs-work/real-negatives/govdocs1
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e "<repo>/tools/crackedpdfs-audit[parquet]" pandas
```

The AWS CLI is optional. With it installed the driver uses `aws s3 cp --no-sign-request`;
otherwise it streams the same archives from `https://digitalcorpora.s3.amazonaws.com/`.

## Commands

```bash
.venv/bin/python <repo>/tools/crackedpdfs-reanalysis/real_negatives/build_govdocs1_sample.py \
    --work-dir ~/crackedpdfs-work/real-negatives/govdocs1 \
    --target 2000 --seed 42 --max-file-bytes 5000000 --workers 7
```

Useful options:

- `--stage download|inspect|audit|manifest` stops after the named stage.
- `--method aws|https` forces the download method.
- `--audit-timeout` bounds the time spent on a single pathological file (default 600 s).
- `--audit-bin` points at a `crackedpdfs-audit` executable outside the active environment.

## Manifest columns

`file_name`, `sha256`, `source_thread`, `bytes`, `pages`, `pdf_version`, `producer`,
`audit_glyphs`, `audit_outside`, `audit_clipped`, `audit_invisible_render_mode`,
`audit_tiny_font`, `audit_low_contrast_fill`, `audit_likely_visible`, `audit_error`,
`screened_clean`.

Only the manifest and summary are meant to be checked in or shared. The PDFs themselves are
re-creatable from the recorded thread ids and the seed, and the manifest records a SHA-256 per
file so a rebuilt sample can be verified byte for byte.
