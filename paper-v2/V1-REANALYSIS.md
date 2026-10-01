# Paper v1 re-analysis: what the frozen detectors actually learned

| | |
| --- | --- |
| Date | 2026-10-01 |
| Inputs | Frozen v1 release tables (`features.parquet` sha256 `4726c817…d32b80`, `labels.parquet` `41838450…724927`, `splits.json` `5ab6a623…38c3`) and the 29,322 v1 PDFs at Hugging Face revision `245bc98` |
| Code | [`tools/crackedpdfs-reanalysis/`](../tools/crackedpdfs-reanalysis/) (the frozen detector under `lightweight-detector/` is imported unchanged) |
| Raw results | [`reanalysis/`](reanalysis/) (JSON per experiment, intervals from 1,000 cluster bootstrap resamples) |
| Changes to v1 artifacts | None. Every number below is computed from the frozen tables and PDFs. |

This document answers the three evaluation questions raised in the FLMSec reviews: whether payload strings leak across splits, whether the near-perfect text scores come from memorised payloads, and what the detectors use when they separate an injected PDF from its matched confounder. It also adds the comparisons that were missing: every detector under the same leave-one-family-out protocol, and three independently written hidden-text detectors on the same test split.

## 1. Reproduction check

The four frozen detectors were retrained from the frozen feature table, the frozen split, and a persisted pypdf text cache (`crackedpdfs-reanalysis text-cache`, 29,322 PDFs, 0 empty extractions), using the published training configurations.

| Model | Paper F1 | Retrained F1 | Paper ROC-AUC | Retrained ROC-AUC | Cluster-bootstrap F1 interval (by document) |
| --- | ---: | ---: | ---: | ---: | --- |
| Sanitized hybrid | 0.9604 | 0.9605 | 0.9984 | 0.9980 | [0.953, 0.967] |
| Sanitized text-only TF-IDF | 1.0000 | 1.0000 | 1.0000 | 1.0000 | [1.000, 1.000] |
| Structural logistic regression | 0.5015 | 0.5015 | 0.6144 | 0.6144 | [0.497, 0.506] |
| Structural XGBoost | 0.6512 | 0.6630 | 0.7984 | 0.7958 | [0.652, 0.672] |

The pipeline reproduces the paper to the fourth decimal for three models; XGBoost differs within library version noise. The row-level bootstrap in the paper (200 iterations) gave the hybrid [0.953, 0.968]; resampling whole base documents gives [0.953, 0.967]. Within-pair ranking of the retrained hybrid is 0.986 (14 of 973 pairs reversed) against the frozen artifact's 1.000, so the published 100% figure is at the optimistic edge of what retraining reproduces.

## 2. Release table audit

`crackedpdfs-reanalysis release-audit` on the public release ([`reanalysis/release_audit.md`](reanalysis/release_audit.md)):

- The `dataset_split` column in `labels.parquet` agrees with the frozen `splits.json` for 19,281 of 29,322 rows (65.8%). The column is the generator's own hash split, not the published split. `splits.json` is the only valid source.
- `data/metadata.parquet` and `data/labels.parquet` are byte-identical.
- `raw_injected_text` and `message_length_chars` are null for every row.

## 3. Payload overlap across splits

| Quantity | Value |
| --- | ---: |
| Distinct payloads (`message_variant_id`) | 104, 13 per message type |
| Payloads present in train, validation, and test | 104 of 104 |
| Uses per payload (min / median / max) | 72 / 94 / 114 |
| Frozen test injected PDFs whose payload appears in training | 973 of 973 |

The payloads are the 104 hand-written messages in `src/lib/prompt-injection-message-library.ts`. The paper's references [19, 20] are cited as sources of inspiration; no public dataset is read by the generator.

## 4. What separates a pair after sanitization

The text channel of the hybrid and the text-only model sees pypdf text after `apply_text_preprocessing`. The sanitizer deletes the entire `DOCUMENT_LAYOUT_NOTE` block (the confounder's whole addition) and strips only the tags around the injected `SYSTEM_POLICY_DO_NOT_REMOVE` block. Measured over all 19,548 pair members (`crackedpdfs-reanalysis sanitizer-residual`, [`reanalysis/sanitizer-residual-summary.json`](reanalysis/sanitizer-residual-summary.json)):

| Role | Characters added to the original, raw | Characters added, after sanitization |
| --- | ---: | ---: |
| Confounder, non-acrostic families (per-family means) | 180 to 343 | 2 to 11 |
| Injected, non-acrostic families (per-family means) | 197 to 386 | 75 to 144 |
| Confounder, acrostic | 10,743 | 7,277 |
| Injected, acrostic | 8,929 | 6,028 |

- The rule "more than 20 added characters survive sanitization" classifies pair members with accuracy 0.959. The paper's paired-set classification accuracy is 0.959.
- Residual length orders the injected member above its confounder in 9,170 of 9,774 pairs; the 514 reversed pairs are acrostics, the family where the hybrid's paired rank was 0.424.
- The frozen hybrid's strongest positive weights are the isolated single-letter trigrams ` e `, ` t `, ` n `, ` r `, ` s `, ` o ` followed by `as`, `instructions`, `hidden`; its strongest negative weight is ` . `. Text-only TF-IDF's strongest negative weights are `benign`, `benign layout`, `layout calibration text`, `calibration text only`: the confounder filler phrase. Both detectors learned the generator's scaffolding, not the visibility of the text.

## 5. Holding out payloads as well as documents

Protocol (`crackedpdfs_reanalysis/protocols.py`): documents and payloads are dealt into five folds independently (payloads stratified by message type). For fold *i* the training set is every triad whose document and payload are both outside fold *i*; a 10% document-grouped slice selects the threshold. Test cells follow the pair-input literature (Park and Marcotte 2012; Pahikkala et al. 2015):

| Cell | Document | Payload | Rows pooled over five folds |
| --- | --- | --- | ---: |
| C2 | unseen | seen | 23,310 |
| C2p | seen | unseen | 23,310 |
| C3 | unseen | unseen | 6,012 |

Pooled results. Intervals are 95% percentile intervals from 1,000 resamples of whole base documents; a second interval by payload is in the JSON.

| Model | Cell | F1 | ROC-AUC | PR-AUC | Pair rank vs confounder | Pair rank vs original |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Hybrid | C2 | 0.961 [0.958, 0.964] | 0.998 | 0.996 | 0.973 [0.969, 0.978] | 1.000 |
| Hybrid | C2p | 0.903 [0.899, 0.908] | 0.984 | 0.961 | 0.973 [0.968, 0.977] | 1.000 |
| Hybrid | C3 | 0.904 [0.894, 0.913] | 0.984 | 0.961 | 0.969 [0.961, 0.977] | 1.000 |
| Text-only | C2 | 1.000 [1.000, 1.000] | 1.000 | 1.000 | 1.000 | 1.000 |
| Text-only | C2p | 0.926 [0.921, 0.931] | 1.000 | 1.000 | 1.000 | 1.000 |
| Text-only | C3 | 0.925 [0.915, 0.934] | 1.000 | 0.999 | 1.000 [1.000, 1.000] | 1.000 |
| Structural LR | C3 | 0.499 [0.493, 0.504] | 0.616 | 0.447 | 0.454 [0.441, 0.470] | 0.839 |
| Structural XGBoost | C3 | 0.655 [0.648, 0.662] | 0.804 | 0.655 | 0.595 [0.578, 0.613] | 0.973 |

Reading: holding out the payload costs the text models about six F1 points, all of it through the decision threshold (ROC-AUC stays at 1.000 and every pair is still ranked correctly). Payload memorisation is not what drives the v1 text scores. The structural models are unaffected by the payload dimension, as expected, and do not separate injected PDFs from confounders at all (paired rank below 0.6).

## 6. Treating both roles alike in the sanitizer

A symmetric sanitizer variant (`strip_scaffold_block_contents: false` in `tools/crackedpdfs-reanalysis/configs/`, implemented by removing the `DOCUMENT_LAYOUT_NOTE` tags before the frozen sanitizer runs) strips the tags of both wrappers and keeps the contents of both. The confounder then contributes its family note and the repeated filler sentence instead of nothing.

| Model | Frozen split F1 | Frozen ROC-AUC | C3 F1 | C3 ROC-AUC | C3 pair rank vs confounder |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hybrid, symmetric sanitizer | 0.999 | 1.000 | 0.844 [0.829, 0.857] | 0.998 | 1.000 |
| Text-only, symmetric sanitizer | 1.000 | 1.000 | 0.940 [0.931, 0.948] | 1.000 | 1.000 |

Discrimination does not drop, because the confounder body is a fixed generator phrase: the strongest negative weights become `benign`, `layout`, `nign`, `enign`. The v1 corpus therefore cannot be repaired by sanitization. Any text model can separate "an instruction" from "a calibration sentence repeated to length", and that is a property of the generator, not of hiddenness. This is what the shared scaffold and prose-bank confounder body in the generator (PR #15) remove for v2.

## 7. Every detector under the leave-one-family-out protocol

The paper reported this stress test for the hybrid only, from a configuration that was not the standard one. Here every detector is retrained under one protocol: every base document that carries the held-out family moves to the test set in full. Target-family F1 scores the family's injected PDFs against all test negatives at the validation-selected threshold; pair rank is within-triad.

| Held-out family | Hybrid pair rank (paper) | Hybrid pair rank | Hybrid target F1 | Text-only pair rank | Text-only target F1 | XGBoost pair rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Steganographic acrostic | 0.424 | 0.432 [0.394, 0.471] | 0.664 | 0.721 [0.688, 0.749] | 0.667 | 0.433 |
| Microglyph steganography | 1.000 | 1.000 | 0.555 | 0.240 [0.211, 0.273] | 0.000 | 0.942 |
| Semantic fragmentation | 1.000 | 1.000 | 0.764 | 1.000 | 1.000 | 0.457 |
| Layout mimicry | 1.000 | 1.000 | 0.776 | 1.000 | 1.000 | 0.498 |
| Margin microtext | 1.000 | 1.000 | 0.762 | 1.000 | 1.000 | 0.500 |
| In-page low-contrast text | 1.000 | 1.000 | 0.775 | 1.000 | 1.000 | 0.485 |

Two findings the paper could not show:

- On acrostics the structural channel hurts. Text-only ranks 0.721 of pairs correctly where the hybrid ranks 0.432, below chance. The acrostic confounder is longer than its payload (section 4) and the hybrid's residual size features follow the length.
- Microglyph steganography is the one family where structure carries the decision. Text-only fails completely (pair rank 0.240, target F1 0.000) because the extracted text of the injected member is not instruction-like, while the structural XGBoost alone reaches 0.942 and the hybrid 1.000. This is the only evidence in the v1 corpus that the structural representation adds something the text does not have.

## 8. Independently written detectors on the same test split

Three open-source hidden-text detectors were run unmodified over the frozen test split (`tools/crackedpdfs-reanalysis/external_baselines/`, [`reanalysis/external-baselines/summary.md`](reanalysis/external-baselines/summary.md)). PhantomLint is OCR-based and slow (50 to 300 s per file on this machine), so it ran on a stratified subsample of 60 triads (180 files).

| Detector | Files | Flags injected | Flags confounder | Flags original | Pair rank vs confounder |
| --- | ---: | ---: | ---: | ---: | ---: |
| hidden-text-detector (wppoland, MIT) | 2,919 | 72.9% | 72.9% | 0.0% | 0.500 (973 ties) |
| pdf-injection-scanner (Andy8647, MIT) | 2,919 | 98.5% | 98.5% | 0.0% | 0.436 |
| PhantomLint, default `nlp` analyzer | 180 | 1.7% | 0.0% | 0.0% | 0.508 |
| PhantomLint, `passthrough` analyzer | 180 | 90.0% | 90.0% | 0.0% | 0.950 |

All four confirm what HiddenContent.ai reported from their engine: the confounders carry hidden text by construction, so a hidden-text detector flags both members of a pair. Separating the pair requires reading what the hidden text says. PhantomLint's default analyzer first filters blocks by similarity to ten built-in injection phrases and misses nearly every v1 payload; its passthrough mode finds the hidden text and, because it reports highlighted characters, ranks 95% of pairs correctly on length alone.

## 9. Off-the-shelf prompt-injection text classifiers

Four public classifiers were scored zero-shot on the test split under two text conditions: the raw pypdf text (what a naive deployment sees) and the paper's sanitized text. Documents were chunked into 400-token windows with 50 tokens of overlap and scored by the maximum over windows; a first-512-tokens score records what truncation alone would see ([`reanalysis/text-baselines/summary.md`](reanalysis/text-baselines/summary.md)).

| Model (license) | Text | ROC-AUC | F1 at 0.5 | Recall at 1% FPR | Pair rank vs confounder |
| --- | --- | ---: | ---: | ---: | ---: |
| Horizon-Labs prompt-injection-guard-base (Apache-2.0) | raw | 0.991 | 0.919 | 0.781 | 0.930 |
| Horizon-Labs prompt-injection-guard-base | sanitized | 0.950 | 0.666 | 0.295 | 0.960 |
| Llama Prompt Guard 2 86M (ONNX mirror) | raw | 0.991 | 0.630 | 0.818 | 0.975 |
| Llama Prompt Guard 2 86M | sanitized | 0.894 | 0.253 | 0.301 | 0.952 |
| deepset deberta-v3-base-injection (MIT) | raw | 0.713 | 0.500 | 0.002 | 0.829 |
| deepset deberta-v3-base-injection | sanitized | 0.732 | 0.500 | 0.041 | 0.899 |
| ProtectAI deberta-v3-base-prompt-injection-v2 (Apache-2.0), 1,019 of 2,919 documents before the 60 minute budget | raw | 0.844 | 0.381 | 0.124 | 0.836 |

Three observations. First, a current guard model with no training on this corpus ranks the raw text almost as well as the paper's trained hybrid (ROC-AUC 0.991 against 0.998), so the v1 task is not hard for text classifiers once the instruction is extractable. Second, sanitization costs these models far more than it costs the paper's models (Horizon-Labs 0.991 to 0.950, Prompt Guard 2 0.991 to 0.894): the role-specific wrapper tags are themselves injection-like tokens for a guard model, and removing them exposes how much of the raw-text score they carried. Third, every model misses microglyph steganography (recall 0.000 to 0.015 except Horizon-Labs raw), which agrees with section 7: that family's extracted text is not instruction-like, and only structure finds it. The paper's PromptGuard-86M row (F1 0.390 on raw text truncated to 512 tokens) was therefore a weak baseline for reasons of generation and truncation, not of the model family.

## 10. What this means for the paper's claims

1. The leakage concern is correct as a fact about the corpus (104 payloads in every split) but is not the explanation of the scores. Text-only reaches ROC-AUC 1.000 on documents and payloads it has never seen.
2. The explanation is the generator: role-specific wrappers, a confounder body that is a repeated calibration phrase, and a sanitizer that keeps one role's content and deletes the other's. Residual length alone reproduces the paper's paired-set accuracy.
3. The near-tie between text-only and hybrid in the paper follows from (2): the text channel already carries a generator fingerprint, so structure has nothing left to add, except on microglyphs, where it is decisive.
4. The acrostic failure is explained by the reversed length relation in that family and by off-page placement (September erratum); it is not evidence about steganography.
5. The structural-only models remain negative controls: they do not separate pairs on any protocol.

Corpus v2 must change the generator, not the evaluation alone: a shared scaffold with prose confounder bodies (PR #15), a payload pool large enough to hold out (`tools/crackedpdfs-payloads`, 11,035 messages), truthful placement (September erratum fixes), visibility-matched quartets, and a second injector (`tools/crackedpdfs-altinjector`). The both-out protocol in this document is the evaluation v2 will report by default.

## 11. Reproduce

```bash
cd tools/crackedpdfs-reanalysis
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
# Frozen tables from the Hugging Face release at revision 02d7e0b into .cache/crackedpdfs-reanalysis/tables/
# (see paper-v1/reproducibility/download-manifest.json); PDFs from revision 245bc98 (pdfs/benign.tar.gz, pdfs/injected.tar.gz)
.venv/bin/crackedpdfs-reanalysis text-cache --pdf-root /path/to/pdfs
.venv/bin/crackedpdfs-reanalysis release-audit --extra-file /path/to/metadata.parquet
.venv/bin/crackedpdfs-reanalysis sanitizer-residual
.venv/bin/crackedpdfs-reanalysis run --experiments frozen,both_out,family --folds 5 --bootstrap 1000
.venv/bin/crackedpdfs-reanalysis run --experiments frozen,both_out \
  --models hybrid_symmetric_sanitizer,text_tfidf_symmetric_sanitizer --out .cache/crackedpdfs-reanalysis/artifacts/symmetric
```

The full run takes about two hours per text model on eight cores; `--models` splits it into parallel processes. The JSON files in [`reanalysis/`](reanalysis/) are the outputs of exactly these commands.
