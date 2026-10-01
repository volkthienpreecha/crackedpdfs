# Dataset Benchmark Protocol

This document defines the reproducible benchmark protocol for dataset-mode generation.

## 1) Regime space

The benchmark enumerates combinations across:

- Spatial: `extreme_off_page`, `negative_off_page`, `near_margin`, `inside_page`
- Rendering: `invisible_render_mode`, `tiny_font`, `white_text`, `normal_visible`
- Structural: `append_new_stream`, `prepend_stream`, `inject_into_existing_stream`
- Artifact wrapper: `true`, `false`
- Message archetype: `instruction_override`, `task_hijack`, `policy_framing`

Compatibility filter:

- Exclude `inside_page + normal_visible`.

## 2) Archetype definitions

Archetypes are controlled text policies:

- `instruction_override`:
  - long
  - compliance/policy-style
- `task_hijack`:
  - short
  - direct output lock
- `policy_framing`:
  - medium
  - contextual reframing without overt system-override phrasing

Envelope requirement for each archetype file:

- Must start with `<SYSTEM_POLICY_DO_NOT_REMOVE>`
- Must end with `</SYSTEM_POLICY_DO_NOT_REMOVE>`

The envelope above is the storage format of the message library. What is
written into a PDF depends on `scaffoldMode`:

- `shared` (default): the injected payload and its matched confounder both use
  the marker line followed by `<DOCUMENT_NOTE>` and `</DOCUMENT_NOTE>`. The
  confounder body is neutral document prose drawn deterministically from a
  fixed sentence bank and cut to exactly the payload's character length. No
  token distinguishes the two roles; only the message content does.
- `role_specific`: the paper v1 scheme. Injected payloads keep the
  `SYSTEM_POLICY_DO_NOT_REMOVE` tags and confounders use
  `DOCUMENT_LAYOUT_NOTE` with repeated calibration filler. The wrapper tags
  identify the role on their own; this mode exists only to rebuild that corpus.

The run manifest records `scaffold_mode`.

Length band constraints (word count):

- short: `8-45`
- medium: `46-120`
- long: `121-500`

## 3) Balancing policy

Target sample count: `targetSamples`.

Balancing steps:

1. Build finite compatible regime combinations.
2. Allocate quota per combination:
   - base quota: `floor(targetSamples / numCombos)`
   - distribute remainder across first combinations in shuffled combo order.
3. Shuffle expanded combo list with seeded RNG.
4. Select sources via benign-registry strata round-robin (seeded order).
5. Generate per-sample benign/injected pair records with unique `pair_id`.

Expected distribution property:

- Combination counts differ by at most 1 sample.

## 4) Pairing strategy

Per sample:

- Keep benign copy.
- Create injected counterpart.
- Track:
  - `pair_id`
  - `base_pair_group_id`
  - `source_occurrence_index`

This allows repeated reuse of the same base PDF while keeping pairing explicit.

## 5) Seed and split controls

Reproducibility controls:

- `seed`: assignment/balancing seed.
- `split_seed`: train/validation/test split seed.
- `freeze_version`: dataset freeze identifier.
- `specification_hash`: hash over protocol-relevant inputs.

Split config:

- train ratio
- validation ratio
- test ratio

Ratios are normalized to sum to 1.0.

## 6) Manifest requirements

Each sample manifest entry must include:

- full resolved injection config
- source/base identifiers
- regime + archetype labels
- pairing metadata
- validation payload with evidence
- benign and injected file artifacts (or failure state)

Run-level manifest includes:

- regime distributions
- benign registry distributions
- validation summary
- stability controls (`freeze`, seeds, splits, spec hash)

## 7) Phase 5 acceptance criteria

A sample passes Phase 5 only if all are true:

1. Benign raw absence check passes.
2. Benign extractor matrix check passes.
3. Injected raw presence check passes.
4. Injected extractor matrix check passes.
5. Injected render-hidden check passes.

Extractor matrix minimum:

- At least 2 extractors must run.

Current extractors:

- `raw_stream`
- `pypdf_text` (`pypdf` or `PyPDF2`)
- `pdfplumber_text`

Renderer visibility path:

- Render pages with PyMuPDF.
- OCR via Tesseract.
- Fail if marker/tokens are visible in rendered evidence.

Any failing criterion marks the sample as validation-failed.
