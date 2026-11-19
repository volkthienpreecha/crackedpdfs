# Off-the-shelf prompt-injection text classifiers on the paper v1 test split

Generated 2026-10-01T09:36:57Z. 2919 documents, conditions: raw, sanitized. Scores are the positive-class softmax probability.

Chunking: windows of at most 400 tokens with 50 overlapping tokens, document score = max over windows (`max_chunk`). `first_512` scores only the first 512 tokens.

Runtime: CPU, batch size 16, torch 2.14.1 with 4 threads, transformers 5.18.0, Python 3.13.3. Total wall clock 294.2 min.

## Models

| key | repository | revision | license | labels (id: name) | positive | status | docs | seq/s | wall clock |
|---|---|---|---|---|---|---|---|---|---|
| protectai_deberta_v3_base_pi_v2 | protectai/deberta-v3-base-prompt-injection-v2 | 90c9989b1a342275dd0d1a95aad283c04e075671 | Apache-2.0 | 0: SAFE, 1: INJECTION | INJECTION | timed_out_partial | 1019/2919 | 0.1 | 190.0 min |
| horizon_labs_pi_guard_base | Horizon-Labs/prompt-injection-guard-base | af3c52e6a9d8bccc8e8c3ed4ba9d7fa084a47e33 | Apache-2.0 | 0: SAFE, 1: INJECTION | INJECTION | completed | 2919/2919 | 2.3 | 35.1 min |
| prompt_guard_2_86m | gravitee-io/Llama-Prompt-Guard-2-86M-onnx | 45a05fbd5337a864edc608f994911f009c37ca57 | Llama 4 Community License (ungated mirror of meta-llama/Llama-Prompt-Guard-2-86M) | 0: BENIGN, 1: MALICIOUS | MALICIOUS | completed | 2919/2919 | 2.3 | 34.2 min |
| deepset_deberta_v3_base_injection | deepset/deberta-v3-base-injection | 80dda00d0b0d9a03917a7685e2ddbcd28e04dbb1 | MIT | 0: LEGIT, 1: INJECTION | INJECTION | completed | 2919/2919 | 2.1 | 34.3 min |

## Headline metrics

| model | condition | scoring | ROC-AUC | PR-AUC | F1@0.5 | recall@0.5 | FPR@0.5 | F1@best (optimistic) | best thr | recall@1% FPR | pair acc vs confounder | pair acc vs benign original |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| protectai_deberta_v3_base_pi_v2 | raw | max_chunk | 0.844 | 0.596 | 0.381 | 0.259 | 0.020 | 0.602 | 0.0006 | 0.124 | 0.836 (n=165) | 1.000 (n=166) |
| protectai_deberta_v3_base_pi_v2 | raw | first_512 | 0.814 | 0.588 | 0.306 | 0.181 | 0.000 | 0.562 | 0.0006 | 0.260 | 0.815 (n=173) | 0.982 (n=169) |
| protectai_deberta_v3_base_pi_v2 | sanitized | max_chunk | metrics undefined: a single class is present | | | | | | | | | |
| protectai_deberta_v3_base_pi_v2 | sanitized | first_512 | metrics undefined: a single class is present | | | | | | | | | |
| horizon_labs_pi_guard_base | raw | max_chunk | 0.991 | 0.983 | 0.919 | 0.913 | 0.037 | 0.928 | 0.2434 | 0.781 | 0.930 (n=973) | 1.000 (n=973) |
| horizon_labs_pi_guard_base | raw | first_512 | 0.993 | 0.987 | 0.911 | 0.845 | 0.005 | 0.926 | 0.0331 | 0.879 | 0.965 (n=973) | 1.000 (n=973) |
| horizon_labs_pi_guard_base | sanitized | max_chunk | 0.950 | 0.891 | 0.666 | 0.541 | 0.041 | 0.875 | 0.0001 | 0.295 | 0.960 (n=973) | 0.995 (n=973) |
| horizon_labs_pi_guard_base | sanitized | first_512 | 0.957 | 0.921 | 0.644 | 0.496 | 0.023 | 0.875 | 0.0001 | 0.445 | 0.934 (n=973) | 0.995 (n=973) |
| prompt_guard_2_86m | raw | max_chunk | 0.991 | 0.982 | 0.630 | 0.459 | 0.000 | 0.928 | 0.0052 | 0.818 | 0.975 (n=973) | 1.000 (n=973) |
| prompt_guard_2_86m | raw | first_512 | 0.990 | 0.981 | 0.628 | 0.457 | 0.000 | 0.930 | 0.0065 | 0.754 | 0.996 (n=973) | 1.000 (n=973) |
| prompt_guard_2_86m | sanitized | max_chunk | 0.894 | 0.834 | 0.253 | 0.145 | 0.000 | 0.760 | 0.0014 | 0.301 | 0.952 (n=973) | 0.994 (n=973) |
| prompt_guard_2_86m | sanitized | first_512 | 0.889 | 0.810 | 0.253 | 0.145 | 0.000 | 0.760 | 0.0014 | 0.238 | 0.950 (n=973) | 0.994 (n=973) |
| deepset_deberta_v3_base_injection | raw | max_chunk | 0.713 | 0.452 | 0.500 | 1.000 | 1.000 | 0.628 | 0.9988 | 0.002 | 0.829 (n=973) | 0.874 (n=973) |
| deepset_deberta_v3_base_injection | raw | first_512 | 0.702 | 0.451 | 0.500 | 1.000 | 1.000 | 0.626 | 0.9988 | 0.001 | 0.855 (n=973) | 0.852 (n=973) |
| deepset_deberta_v3_base_injection | sanitized | max_chunk | 0.732 | 0.543 | 0.500 | 1.000 | 1.000 | 0.617 | 0.9987 | 0.041 | 0.899 (n=973) | 0.896 (n=973) |
| deepset_deberta_v3_base_injection | sanitized | first_512 | 0.721 | 0.538 | 0.500 | 1.000 | 1.000 | 0.614 | 0.9987 | 0.041 | 0.899 (n=973) | 0.883 (n=973) |

The optimistic F1 selects the threshold on the test set itself and is an upper bound, not a deployable number.

## Per-attack-family recall at threshold 0.5 (max_chunk scoring)

| attack family | n | protectai_deberta_v3_base_pi_v2 / raw | protectai_deberta_v3_base_pi_v2 / sanitized | horizon_labs_pi_guard_base / raw | horizon_labs_pi_guard_base / sanitized | prompt_guard_2_86m / raw | prompt_guard_2_86m / sanitized | deepset_deberta_v3_base_injection / raw | deepset_deberta_v3_base_injection / sanitized |
|---|---|---|---|---|---|---|---|---|---|
| existing_stream_patch | 73 | 0.214 | n/a | 1.000 | 0.603 | 0.466 | 0.205 | 1.000 | 1.000 |
| header_footer_like | 68 | 0.200 | n/a | 0.971 | 0.588 | 0.559 | 0.162 | 1.000 | 1.000 |
| in_page_invisible_text | 74 | 0.273 | n/a | 0.959 | 0.527 | 0.500 | 0.176 | 1.000 | 1.000 |
| in_page_low_contrast_text | 62 | 0.071 | n/a | 0.968 | 0.500 | 0.532 | 0.226 | 1.000 | 1.000 |
| in_page_split_text_objects | 46 | 0.333 | n/a | 0.978 | 0.413 | 0.543 | 0.196 | 1.000 | 1.000 |
| in_page_tiny_text | 68 | 0.100 | n/a | 0.941 | 0.588 | 0.500 | 0.088 | 1.000 | 1.000 |
| in_page_white_text | 51 | 0.167 | n/a | 0.980 | 0.529 | 0.510 | 0.176 | 1.000 | 1.000 |
| layout_mimicry | 79 | 0.222 | n/a | 0.962 | 0.519 | 0.532 | 0.114 | 1.000 | 1.000 |
| margin_microtext | 61 | 0.333 | n/a | 0.951 | 0.639 | 0.607 | 0.197 | 1.000 | 1.000 |
| microglyph_steganography | 66 | 0.000 | n/a | 0.894 | 0.015 | 0.000 | 0.000 | 1.000 | 1.000 |
| near_margin_normal_font | 70 | 0.200 | n/a | 0.943 | 0.429 | 0.471 | 0.129 | 1.000 | 1.000 |
| plain_single_block | 52 | 0.167 | n/a | 0.981 | 0.538 | 0.500 | 0.192 | 1.000 | 1.000 |
| semantic_fragmentation | 57 | 0.231 | n/a | 0.982 | 0.439 | 0.561 | 0.140 | 1.000 | 1.000 |
| split_text_objects | 66 | 0.417 | n/a | 0.985 | 0.636 | 0.758 | 0.242 | 1.000 | 1.000 |
| steganographic_acrostic | 80 | 1.000 | n/a | 0.350 | 1.000 | 0.000 | 0.000 | 1.000 | 1.000 |

## Sanitizer

`apply_text_preprocessing` from `src/models/text_preprocessing.py` with the `text_tfidf` block of `model_hybrid_hard_provenance.yaml`: strip_known_benchmark_wrappers=True, strip_synthetic_phrase_markers=True.
