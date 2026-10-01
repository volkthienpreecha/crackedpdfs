# GovDocs1 real-negative sample

Source: GovDocs1, Digital Corpora (https://digitalcorpora.org/corpora/file-corpora/files/).
Threads were drawn in a seeded random order (seed 42) and downloaded as whole thread
archives via `aws`; only `.pdf` members at or below 5,000,000 bytes were kept.

## Counts

| Quantity | Value |
| --- | --- |
| Threads downloaded | 9 (776, 507, 895, 922, 033, 483, 085, 750, 354) |
| Zip bytes downloaded | 3,474,980,106 |
| PDF members seen in those threads | 2,029 |
| Skipped for size cap or empty | 28 |
| Skipped as SHA-256 duplicates | 1 |
| Unique PDFs kept on disk | 2,000 |
| Total bytes kept | 1,202,673,472 |
| Unreadable by pikepdf | 0 |
| Readable but audit failed | 24 |
| Screened clean (all hidden indicators zero, no error) | 1,169 (58.5%) |

## Flagged by indicator (readable, audited files)

| Indicator | Files with nonzero count | Share of audited |
| --- | --- | --- |
| outside | 91 | 4.6% |
| clipped | 72 | 3.6% |
| invisible_render_mode | 126 | 6.4% |
| tiny_font | 304 | 15.4% |
| low_contrast_fill | 563 | 28.5% |
| any indicator | 807 | 40.8% |

Audited files with zero extracted glyphs (scanned or image-only): 55.

## Distributions

File size in bytes: min 2,198, p5 17,900, p25 60,435, median 187,488, p75 656,904, p95 2,822,208, max 4,897,152, mean 601,336.7

Pages (readable files): min 1, p5 1, p25 4, median 12, p75 36, p95 154, max 1,627, mean 37.2

PDF versions:

- 1.0: 9
- 1.1: 65
- 1.2: 359
- 1.3: 447
- 1.4: 758
- 1.5: 188
- 1.6: 166
- 1.7: 8

Top producer strings:

- 148: Acrobat Distiller 7.0.5 (Windows)
- 129: Acrobat Distiller 5.0.5 (Windows)
- 123: Acrobat Distiller 4.0 for Windows
- 119: Acrobat Distiller 5.0 (Windows)
- 116: Acrobat Distiller 6.0 (Windows)
- 88: Acrobat Distiller 6.0.1 (Windows)
- 85: Acrobat Distiller 7.0 (Windows)
- 81: Acrobat Distiller 8.1.0 (Windows)
- 68: <none>
- 54: Acrobat Distiller 3.01 for Windows
- 48: Acrobat Distiller 4.05 for Windows
- 41: Acrobat PDFWriter 5.0 for Windows NT
- 36: Acrobat PDFWriter 3.02 for Windows
- 29: Acrobat Distiller 3.01 for Power Macintosh
- 28: Acrobat Distiller 8.0.0 (Windows)

## Audit errors on readable files

- 033558.pdf: IndexError: list index out of range
- 033802.pdf: AssertionError: Invalid octal b'610' (392)
- 354318.pdf: IndexError: list index out of range
- 483733.pdf: pdfminer.pdfparser.PDFSyntaxError: No /Root object! - Is this really a PDF?
- 507259.pdf: timeout after 600s
- 507330.pdf: timeout after 600s
- 507348.pdf: timeout after 600s
- 507366.pdf: timeout after 600s
- 507367.pdf: timeout after 600s
- 507380.pdf: timeout after 600s
- 507381.pdf: timeout after 600s
- 507676.pdf: AssertionError: Invalid octal b'663' (435)
- 507949.pdf: timeout after 600s
- 507951.pdf: timeout after 600s
- 922048.pdf: timeout after 600s
- 922199.pdf: IndexError: list index out of range
- 922328.pdf: timeout after 600s
- 922475.pdf: timeout after 600s
- 922590.pdf: timeout after 600s
- 922591.pdf: timeout after 600s
- 922610.pdf: timeout after 600s
- 922702.pdf: timeout after 600s
- 922718.pdf: timeout after 600s
- 922719.pdf: timeout after 600s

## Commands

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e "<repo>/tools/crackedpdfs-audit[parquet]" pandas
aws s3 cp --no-sign-request s3://digitalcorpora/corpora/files/govdocs1/zipfiles/NNN.zip zips/   # per selected thread, deleted after extraction
.venv/bin/crackedpdfs-audit file pdfs/<file>.pdf --json  # per file, in a process pool
build_govdocs1_sample.py --work-dir /Users/karthik/crackedpdfs-work/real-negatives/govdocs1 --target 2000 --seed 42 --max-file-bytes 5000000 --workers 7
```

Per-file audit counters are summed over pages. The hidden-text indicators are `outside`, `clipped`,
`invisible_render_mode`, `tiny_font`, and `low_contrast_fill`; `screened_clean` is true only when all
five are zero and neither pikepdf nor the audit reported an error.
