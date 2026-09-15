# Paper results

This file separates three things that are easy to blur together:

1. values printed in arXiv v1;
2. full-precision values in the recovered frozen metric artifact; and
3. metric-definition discrepancies between the prose and the artifact.

The full source is [`metrics/metrics.json`](metrics/metrics.json). The compact frozen table is [`metrics/hard-setting-summary.csv`](metrics/hard-setting-summary.csv).

## Dataset and split table

| Quantity | Paper value |
| --- | ---: |
| Base documents | 4,983 |
| Total PDFs | 29,322 |
| Injected PDFs | 9,774 |
| Benign originals or matched confounders | 19,548 |
| Train PDFs | 23,766 |
| Validation PDFs | 2,637 |
| Test PDFs | 2,919 |
| Test injected PDFs | 973 |
| Test negatives | 1,946 |
| Balanced paired-subset PDFs | 1,946 |
| Matched injected-confounder pairs | 973 |

## Main held-out results

The following table uses full-precision values from `hard-setting-summary.csv`. The paper rounds these values to three decimal places in prose and two decimal places in Figure 4.

| Method | Accuracy | Precision | Recall | F1 | ROC-AUC | PR-AUC | Paper framing |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Hybrid | 0.9725933539 | 0.9256434700 | 0.9979445015 | **0.9604352127** | **0.9984351382** | **0.9969446988** | Primary result |
| PromptGuard | 0.7368961973 | 0.8596491228 | 0.2517985612 | 0.3895071542 | 0.8576915886 | 0.7345972652 | Extracted-text baseline |
| Rule baseline | 0.6591298390 | 0.4933973589 | 0.8448098664 | 0.6229632437 | 0.7487335341 | 0.4995312211 | PDF rule baseline |
| Structural logistic regression | 0.3788968825 | 0.3423423423 | 0.9373072970 | 0.5015122354 | 0.6143685257 | 0.4520596413 | Structural negative control |
| Structural XGBoost | 0.6591298390 | 0.4941489362 | 0.9547790339 | 0.6512443042 | 0.7983818495 | 0.6431920980 | Structural negative control |
| Text-only TF-IDF | 1.0000000000 | 1.0000000000 | 1.0000000000 | 1.0000000000 | 1.0000000000 | 1.0000000000 | Shortcut-prone comparator; excluded from the primary claim |

Paper-rounded headline values:

- Hybrid: 0.973 accuracy, 0.960 F1, 0.998 ROC-AUC, 0.997 PR-AUC.
- PromptGuard: 0.390 F1 and 0.252 recall.
- Rule baseline: 0.623 F1.
- Structural logistic regression: 0.502 F1.
- Structural XGBoost: 0.651 F1.

## Test confusion matrices

Rows are true labels and columns are predicted labels in the order `[[TN, FP], [FN, TP]]`.

| Method | Confusion matrix |
| --- | --- |
| Hybrid | `[[1868, 78], [2, 971]]` |
| PromptGuard | `[[1906, 40], [728, 245]]` |
| Rule baseline | `[[1102, 844], [151, 822]]` |
| Structural logistic regression | `[[194, 1752], [61, 912]]` |
| Structural XGBoost | `[[995, 951], [44, 929]]` |
| Text-only TF-IDF | `[[1946, 0], [0, 973]]` |

## Paired result provenance

The arXiv v1 abstract and results section say that the hybrid detector “ranks injected files above matched benign confounders in 95.9% of 973 pairs.” Figure 5 labels 95.9% as paired accuracy.

The recovered frozen artifact distinguishes two calculations:

| Artifact field | Value | What it measures |
| --- | ---: | --- |
| `models.hybrid.balanced_evaluation.injected_vs_benign_confounder.accuracy` | **0.9588900308** | Thresholded classification accuracy over 1,946 PDFs: 973 injected and 973 matched confounders. |
| `models.hybrid.paired_contrast.by_negative_type.benign_confounder.pair_accuracy` | **1.0000000000** | Within-pair score ordering across 973 injected-confounder pairs. |

The balanced-set confusion matrix is `[[895, 78], [2, 971]]`, which gives `(895 + 971) / 1946 = 0.9588900308`.

The original [`claim-scope-report.md`](claim-scope-report.md) also calls 0.9588900308 “paired benign-confounder accuracy,” not ranking accuracy.

Therefore:

- 95.9% is preserved here as the **paper-reported paired result**;
- the frozen artifact supports 95.9% as **paired-set classification accuracy**; and
- the explicit frozen **pairwise ranking accuracy is 100%**.

This should be corrected or clarified in an arXiv revision before the metric is marketed as paired ranking.

## Label-shuffle sanity check

| Model | Accuracy | F1 | ROC-AUC | PR-AUC |
| --- | ---: | ---: | ---: | ---: |
| Hybrid | 0.3329907503 | 0.4996144950 | 0.5066993828 | 0.3611015484 |
| Structural logistic regression | 0.3333333333 | 0.4989701339 | 0.4812802819 | 0.3562009617 |
| Structural XGBoost | 0.3333333333 | 0.4968976215 | 0.5124821887 | 0.3430629358 |
| Text-only TF-IDF | 0.3336759164 | 0.4993564994 | 0.5020000444 | 0.3630158782 |

The paper rounds the hybrid result to 0.500 F1 and 0.507 ROC-AUC, logistic regression to 0.499 F1 and 0.481 ROC-AUC, and XGBoost to 0.497 F1 and 0.512 ROC-AUC.

## Held-out attack-family stress tests

These are limitation tests, not the primary success criterion. `Target-family F1` compares target-family positives against all test negatives. `Paired rank accuracy` compares each target-family injected sample with its matched benign confounder.

| Held-out family | Target positives | Target-family F1 | Paired rank pairs | Paired rank accuracy |
| --- | ---: | ---: | ---: | ---: |
| Steganographic acrostic | 792 | 0.6666666667 | 792 | **0.4242424242** |
| Microglyph steganography | 696 | 0.5690923957 | 696 | 1.0000000000 |
| Semantic fragmentation | 639 | 0.7778454047 | 639 | 1.0000000000 |
| Layout mimicry | 669 | 0.7829139848 | 669 | 1.0000000000 |
| In-page low-contrast text | 682 | 0.7848101266 | 682 | 1.0000000000 |
| Margin microtext | 618 | 0.8323232323 | 618 | 1.0000000000 |

> **Erratum:** acrostic payloads in this corpus sit below the page rather than on it, and matched pairs differ in payload length. Placement is identical within every pair, so it does not explain the 0.424 paired rank, but a single frozen length feature ranks the same pairs at 0.351 and the other held-out families at 0.985 or higher. See [`ERRATA.md`](ERRATA.md#finding-2-matched-pairs-differ-in-a-marker-and-in-length).

The exact source tables are:

- [`metrics/holdout-target-family-focus-metrics.csv`](metrics/holdout-target-family-focus-metrics.csv);
- [`metrics/holdout-matched-counterfactual-metrics.csv`](metrics/holdout-matched-counterfactual-metrics.csv); and
- [`metrics/holdout-aggregate-metrics.csv`](metrics/holdout-aggregate-metrics.csv).

## Shortcut audit

Text-only TF-IDF reaches perfect held-out metrics but is not clean positive evidence. The paper reports that wrapper and synthetic tokens appeared among high-weight evidence. The hybrid model passed the wrapper-token audit with zero wrapper-token hits.

The frozen audit table is [`metrics/shortcut-feature-audit.csv`](metrics/shortcut-feature-audit.csv).

## Claim boundary

Supported:

> On this controlled hard-provenance benchmark, the sanitized hybrid text-and-structure detector outperforms PromptGuard and structural-only controls under matched benign-confounder evaluation, shortcut audits, and label-shuffle checks.

Not supported:

- broad robustness to arbitrary real-world PDFs;
- reliable generalization to all unseen attack families;
- robustness to OCR-only ingestion or scanned documents;
- robustness to adaptive attackers or unseen injection generators; or
- treating the perfect TF-IDF result as a valid primary detector result.
