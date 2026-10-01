# External hidden-text detector baselines

Independently written open-source detectors run unmodified over the paper v1 frozen test split (2919 PDFs, 973 injected, 973 benign confounders, 973 benign originals). `flagged` is the positive prediction; ROC-AUC uses each detector's numeric `score` (ties count one half). Scoring rules are documented in each driver's docstring and in the `run` block of `summary.json`. Rows whose coverage is a triad subsample (see Run details) report metrics on that subsample only; paired metrics remain valid because sampling is by triad.

## Headline metrics

| Detector | Subset | n | Acc | Prec | Rec | F1 | ROC-AUC |
|---|---|---|---|---|---|---|---|
| phantomlint | full test split | 180 | 0.672 | 1.000 | 0.017 | 0.033 | 0.508 |
| phantomlint | injected vs confounder | 120 | 0.508 | 1.000 | 0.017 | 0.033 | 0.508 |
| phantomlint_passthrough | full test split | 180 | 0.644 | 0.482 | 0.900 | 0.628 | 0.863 |
| phantomlint_passthrough | injected vs confounder | 120 | 0.500 | 0.500 | 0.900 | 0.643 | 0.780 |
| hidden_text_detector | full test split | 2919 | 0.667 | 0.500 | 0.729 | 0.593 | 0.682 |
| hidden_text_detector | injected vs confounder | 1946 | 0.500 | 0.500 | 0.729 | 0.593 | 0.500 |
| pdf_injection_scanner | full test split | 2919 | 0.667 | 0.500 | 0.985 | 0.663 | 0.744 |
| pdf_injection_scanner | injected vs confounder | 1946 | 0.500 | 0.500 | 0.985 | 0.663 | 0.495 |

## Paired ranking accuracy

Score of the injected PDF strictly above its matched benign confounder within the same triad; ties count one half.

| Detector | Pairs | Wins | Ties | Accuracy |
|---|---|---|---|---|
| phantomlint | 60 | 1 | 59 | 0.508 |
| phantomlint_passthrough | 60 | 54 | 6 | 0.950 |
| hidden_text_detector | 973 | 0 | 973 | 0.500 |
| pdf_injection_scanner | 973 | 55 | 739 | 0.436 |

## Flag rate by PDF role

| Detector | benign_confounder | benign_original | injected_attack |
|---|---|---|---|
| phantomlint | 0.000 (0/60) | 0.000 (0/60) | 0.017 (1/60) |
| phantomlint_passthrough | 0.900 (54/60) | 0.067 (4/60) | 0.900 (54/60) |
| hidden_text_detector | 0.729 (709/973) | 0.000 (0/973) | 0.729 (709/973) |
| pdf_injection_scanner | 0.985 (958/973) | 0.000 (0/973) | 0.985 (958/973) |

## Flag rate by attack family (injected PDFs only)

| Attack family | n | phantomlint | phantomlint_passthrough | hidden_text_detector | pdf_injection_scanner |
|---|---|---|---|---|---|
| existing_stream_patch | 5 | 0.000 | 1.000 | 1.000 | 1.000 |
| header_footer_like | 4 | 0.000 | 1.000 | 0.838 | 1.000 |
| in_page_invisible_text | 5 | 0.000 | 1.000 | 1.000 | 1.000 |
| in_page_low_contrast_text | 4 | 0.000 | 1.000 | 1.000 | 1.000 |
| in_page_split_text_objects | 3 | 0.000 | 1.000 | 1.000 | 1.000 |
| in_page_tiny_text | 4 | 0.250 | 1.000 | 0.000 | 1.000 |
| in_page_white_text | 3 | 0.000 | 1.000 | 1.000 | 1.000 |
| layout_mimicry | 5 | 0.000 | 1.000 | 1.000 | 1.000 |
| margin_microtext | 4 | 0.000 | 1.000 | 1.000 | 1.000 |
| microglyph_steganography | 4 | 0.000 | 0.000 | 1.000 | 1.000 |
| near_margin_normal_font | 4 | 0.000 | 1.000 | 0.000 | 1.000 |
| plain_single_block | 3 | 0.000 | 1.000 | 0.654 | 1.000 |
| semantic_fragmentation | 4 | 0.000 | 1.000 | 1.000 | 1.000 |
| split_text_objects | 4 | 0.000 | 1.000 | 0.742 | 0.773 |
| steganographic_acrostic | 4 | 0.000 | 0.500 | 0.000 | 1.000 |

## Techniques reported among flagged files

- phantomlint: hidden_suspicious_text (1)
- phantomlint_passthrough: hidden_suspicious_text (112)
- hidden_text_detector: Text in invisible render mode (mode 3) (610), Text not visible in the rendered page (478), Sub-legible font size (254), Text positioned outside the page (76)
- pdf_injection_scanner: Off-Page Text (1916), White/Invisible Text (494), Tiny Text (470), Suspicious Pattern (34)

## Run details

| Detector | Files | Coverage | Commit | Version | Python | Workers | Wall clock (s) | Mean s/file | Max s/file | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|---|---|
| phantomlint | 180 | 60 triads sampled with seed 0, stratified by attack family | `7f6200145abf` | 0.1 (setup.py) | Python 3.12.13 | 2 | 2649.8 | 25.40 | 600.1 | 0 | 2 |
| phantomlint_passthrough | 180 | 60 triads sampled with seed 0, stratified by attack family | `7f6200145abf` | 0.1 (setup.py) | Python 3.12.13 | 2 | 2413.8 | 26.27 | 600.1 | 0 | 4 |
| hidden_text_detector | 2919 | full test split | `ce9e505dc1c1` | unversioned (no release tags); commit SHA identifies the build | Python 3.13.3 | 6 | 1116.8 | 2.28 | 13.9 | 0 | 0 |
| pdf_injection_scanner | 2919 | full test split | `88555839b5af` | 0.2.1 (pyproject.toml) | Python 3.13.3 | 6 | 1627.5 | 3.30 | 16.6 | 0 | 0 |

Command lines:

- phantomlint: `/Users/karthik/crackedpdfs-work/baselines/phantom-lint/.venv/bin/phantomlint <pdf> --output <dir> --analyze nlp  (executed in-process by phantomlint_worker.py with identical component defaults)`
  - flag rule: at least one hidden suspicious phrase reported (console script exit status 1)
  - score rule: number of characters highlighted as hidden in hidden_suspicious_phrases.txt
- phantomlint_passthrough: `/Users/karthik/crackedpdfs-work/baselines/phantom-lint/.venv/bin/phantomlint <pdf> --output <dir> --analyze passthrough  (executed in-process by phantomlint_worker.py with identical component defaults)`
  - flag rule: at least one hidden suspicious phrase reported (console script exit status 1)
  - score rule: number of characters highlighted as hidden in hidden_suspicious_phrases.txt
- hidden_text_detector: `/Users/karthik/crackedpdfs-work/baselines/hidden-text-detector/.venv/bin/python /Users/karthik/crackedpdfs-work/baselines/hidden-text-detector/scripts/scan.py --json <pdf>`
  - flag rule: any finding with severity CRITICAL
  - score rule: critical_count + 0.1 * warning_count
- pdf_injection_scanner: `/Users/karthik/crackedpdfs-work/baselines/pdf-injection-scanner/.venv/bin/pdf-scan --json <pdf>`
  - flag rule: any finding (the tool has no severity-based verdict)
  - score rule: high_count + 0.1 * medium_count
