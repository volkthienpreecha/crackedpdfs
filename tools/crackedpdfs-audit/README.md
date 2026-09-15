# crackedpdfs-audit

**Labels are claims. This tool checks them against the file.**

`crackedpdfs-audit` measures where every glyph in a PDF actually lands and why a reader would or would not see it: off the page, clipped by the page edge, drawn with an invisible render mode, set too small to read, or filled too close to white. It reads the content stream itself with [pdfminer.six](https://github.com/pdfminer/pdfminer.six) and renders pages with [pypdfium2](https://github.com/pypdfium2-team/pypdfium2). It never consults generator metadata, so its answers are independent of the code that wrote the corpus.

It exists because paper v1 of CrackedPDFs shipped spatial labels that did not describe the files. See [`paper-v1/ERRATA.md`](../../paper-v1/ERRATA.md).

`pdf` `prompt-injection` `hidden-text` `benchmark-hygiene` `MIT`

## Install

```bash
pip install -e "tools/crackedpdfs-audit[parquet,test]"
```

Python 3.11 or newer. Every dependency is permissively licensed: pdfminer.six (MIT), pypdfium2 (Apache-2.0 or BSD-3-Clause), pikepdf (MPL-2.0), Pillow (MIT-CMU), and numpy (BSD-3-Clause).

## Three commands

### `file`: one PDF

```bash
crackedpdfs-audit file injected/sample_0009.injected.pdf \
  --reference benign/sample_0009.benign.pdf --label inside_page
```

```text
page 1  box=(0.0, 0.0, 595.3, 841.9)  scope=added_vs_reference
  glyphs=6,949  inside=0  clipped=63  outside=6,886 (below=6,886)
  invisible_render_mode=0  tiny_font=0  low_contrast_fill=0  likely_visible=0
  realized=straddles_page_edge  preview='[DATASET_SAMPLE_ID=sample_0009][MESSAGE_TYPE=system_extraction]Review note: the '
  label=inside_page  contract_satisfied=False
  lexical_oracle_tokens=['DATASET_SAMPLE_ID', 'MESSAGE_TYPE=']
```

With `--reference`, only glyphs added relative to the clean original are measured (a multiset difference on text, position, and font). Without it, all text on the page is measured.

### `reveal`: see what is hidden

```bash
crackedpdfs-audit reveal injected/sample_0009.injected.pdf reveal.png \
  --reference benign/sample_0009.benign.pdf
```

The page is re-rendered on an expanded canvas, so text parked beyond the page edge becomes visible. The real page boundary is drawn in ink, the area outside it is hatched, and each added glyph is outlined in the color of its strongest hiding mechanism.

### `corpus`: a whole benchmark

```bash
crackedpdfs-audit corpus --root crackedpdfs/pdfs \
  --metadata crackedpdfs/data/metadata.parquet --out audit-v1 --render
```

This expects the Hugging Face layout (`benign/` and `injected/` extracted from the release tarballs). Each injected PDF and each matched confounder is compared with its benign original. The command writes:

| Output | Contents |
| --- | --- |
| `placement-audit.jsonl` | One record per PDF: added-glyph placement counts, visibility reasons, label contract verdict, changed pixels at 72 dpi, and any lexical oracle tokens. |
| `placement-audit-summary.csv` | Rates grouped by role, attack family, and spatial label. |
| `placement-audit-summary.md` | The same table, ready to paste into a report. |

On an 8-core laptop the full 19,548-PDF audit with pixel diffs takes about fifteen minutes.

## Contracts

| Label | Contract |
| --- | --- |
| `inside_page` | Every added glyph lies fully inside the visible page box. |
| `extreme_off_page`, `negative_off_page` | Every added glyph lies fully outside the visible page box. |
| `near_margin` | No added glyph touches the page inset by 72pt on each side. |

The visible page box is the MediaBox intersected with the CropBox. Glyph boxes come from pdfminer's font metrics, and a 0.05pt tolerance absorbs rounding.

## Visibility reasons

| Reason | Rule |
| --- | --- |
| `off_page` | Glyph box does not intersect the visible page box. |
| `clipped_by_page_edge` | Glyph box crosses the page edge. |
| `invisible_render_mode` | Text render mode 3 (neither fill nor stroke) or 7 (clip only). |
| `tiny_font` | Rendered size below 2pt. |
| `low_contrast_fill` | WCAG contrast ratio against white below 1.5 for a filled render mode. |

Contrast is measured against a white page, not against whatever is painted underneath. Use `--render` pixel diffs as ground truth for what a reader sees.

## Lexical oracle tokens

The audit also reports bookkeeping strings that identify the generator role rather than the attack (`DATASET_SAMPLE_ID`, `MESSAGE_TYPE=`, `SYSTEM_POLICY_DO_NOT_REMOVE`, `DOCUMENT_LAYOUT_NOTE`). A detector that keys on them is reading the label, not the document.

## Tests

```bash
python -m pytest tools/crackedpdfs-audit/tests -q
```

The fixtures are built from raw content streams with pikepdf, so the tests never go through the CrackedPDFs generator.
