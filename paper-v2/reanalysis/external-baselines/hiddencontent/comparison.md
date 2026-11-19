# HiddenContent.ai per-file results against the placement audit

Vendor engine `0.265.0`, rule pack `2026.09.10-20`, run on 2026-09-16 over corpus freeze `usenix-physical-10k-20260525-1`. The structural pass covers all 29,322 files; the rendered pass covers the 2,811 files whose release metadata column `dataset_split` reads `test`.

## Which test split the rendered pass used

| Quantity | Files |
|---|---:|
| Frozen paper test split | 2,919 |
| Release metadata `dataset_split = test` | 2,811 |
| In both | 165 |
| Frozen test files by release column | test 165, train 2,481, validation 273 |
| Complete triads in the overlap | 55 |

## Text below the page: vendor lines versus audited glyphs

Per-file agreement on whether any hidden text lies below the page: 0.9853 over 19,548 injected and confounder files.

| Group | Files | Vendor: any line below page | Audit: any glyph below page | Agreement | Vendor: off-page is only finding | Audit: label contract holds | Vendor hidden text carries a role token |
|---|---:|---:|---:|---:|---:|---:|---:|
| benign_confounder | 9,774 | 9,081 | 9,225 | 0.985 | 2,001 | 2,238 | 8,286 |
| existing_stream_patch | 635 | 635 | 635 | 1.000 | 0 | 0 | 635 |
| header_footer_like | 651 | 481 | 481 | 1.000 | 125 | 315 | 651 |
| in_page_invisible_text | 637 | 637 | 637 | 1.000 | 0 | 0 | 637 |
| in_page_low_contrast_text | 682 | 682 | 682 | 1.000 | 0 | 0 | 682 |
| in_page_split_text_objects | 462 | 462 | 462 | 1.000 | 0 | 0 | 462 |
| in_page_tiny_text | 660 | 660 | 660 | 1.000 | 0 | 0 | 660 |
| in_page_white_text | 660 | 660 | 660 | 1.000 | 0 | 0 | 660 |
| layout_mimicry | 669 | 669 | 669 | 1.000 | 0 | 0 | 669 |
| margin_microtext | 618 | 618 | 618 | 1.000 | 0 | 618 | 618 |
| microglyph_steganography | 696 | 696 | 696 | 1.000 | 0 | 0 | 0 |
| near_margin_normal_font | 654 | 654 | 654 | 1.000 | 654 | 654 | 654 |
| plain_single_block | 647 | 464 | 464 | 1.000 | 182 | 329 | 647 |
| semantic_fragmentation | 639 | 639 | 639 | 1.000 | 0 | 0 | 639 |
| split_text_objects | 672 | 332 | 476 | 0.786 | 248 | 322 | 672 |
| steganographic_acrostic | 792 | 792 | 792 | 1.000 | 792 | 0 | 0 |

## Injected files whose only vendor finding is off-page text

2,001 injected files, 1,651 of them labelled `normal_visible`. The audit's realized placement class for each group is listed.

| Attack family | Rendering label | Spatial label | Files | Audit realized class | Audit contract holds |
|---|---|---|---:|---|---:|
| header_footer_like | tiny_font | extreme_off_page | 40 | off_page 40 | 40 |
| header_footer_like | white_text | extreme_off_page | 85 | off_page 85 | 85 |
| near_margin_normal_font | normal_visible | near_margin | 654 | straddles_page_edge 654 | 654 |
| plain_single_block | normal_visible | extreme_off_page | 44 | off_page 44 | 44 |
| plain_single_block | normal_visible | negative_off_page | 47 | straddles_page_edge 47 | 0 |
| plain_single_block | tiny_font | extreme_off_page | 49 | off_page 49 | 49 |
| plain_single_block | white_text | extreme_off_page | 42 | off_page 42 | 42 |
| split_text_objects | normal_visible | extreme_off_page | 60 | off_page 60 | 60 |
| split_text_objects | normal_visible | negative_off_page | 54 | straddles_page_edge 54 | 0 |
| split_text_objects | tiny_font | extreme_off_page | 46 | off_page 46 | 46 |
| split_text_objects | white_text | extreme_off_page | 48 | off_page 48 | 48 |
| split_text_objects | white_text | inside_page | 13 | straddles_page_edge 13 | 0 |
| split_text_objects | white_text | near_margin | 13 | straddles_page_edge 13 | 13 |
| split_text_objects | white_text | negative_off_page | 14 | straddles_page_edge 14 | 0 |
| steganographic_acrostic | normal_visible | inside_page | 792 | straddles_page_edge 792 | 0 |

## Pairs

9,774 pairs; both members flagged in 9,774. Hidden characters reported by the engine: injected longer in 8,152, confounder longer in 1,454, equal in 168.

| Attack family | Pairs | Injected longer | Confounder longer | Equal | Rank by hidden characters |
|---|---:|---:|---:|---:|---:|
| existing_stream_patch | 635 | 624 | 0 | 11 | 0.991 |
| header_footer_like | 651 | 647 | 0 | 4 | 0.997 |
| in_page_invisible_text | 637 | 613 | 0 | 24 | 0.981 |
| in_page_low_contrast_text | 682 | 662 | 0 | 20 | 0.985 |
| in_page_split_text_objects | 462 | 462 | 0 | 0 | 1.000 |
| in_page_tiny_text | 660 | 655 | 0 | 5 | 0.996 |
| in_page_white_text | 660 | 637 | 0 | 23 | 0.983 |
| layout_mimicry | 669 | 662 | 0 | 7 | 0.995 |
| margin_microtext | 618 | 610 | 0 | 8 | 0.994 |
| microglyph_steganography | 696 | 482 | 176 | 38 | 0.720 |
| near_margin_normal_font | 654 | 0 | 654 | 0 | 0.000 |
| plain_single_block | 647 | 580 | 47 | 20 | 0.912 |
| semantic_fragmentation | 639 | 639 | 0 | 0 | 1.000 |
| split_text_objects | 672 | 601 | 63 | 8 | 0.900 |
| steganographic_acrostic | 792 | 278 | 514 | 0 | 0.351 |

## Technique combinations reported per group (structural pass)

| Group | Techniques | Files |
|---|---|---:|
| benign_confounder | `pdf.render-mode-3` | 2,920 |
| benign_confounder | `pdf.white-text;pdf.offpage-text` | 2,446 |
| benign_confounder | `pdf.tiny-font;pdf.offpage-text` | 2,407 |
| benign_confounder | `pdf.offpage-text` | 2,001 |
| existing_stream_patch | `pdf.render-mode-3` | 635 |
| header_footer_like | `pdf.white-text;pdf.offpage-text` | 201 |
| header_footer_like | `pdf.render-mode-3` | 183 |
| header_footer_like | `pdf.tiny-font;pdf.offpage-text` | 142 |
| header_footer_like | `pdf.offpage-text` | 125 |
| in_page_invisible_text | `pdf.render-mode-3` | 637 |
| in_page_low_contrast_text | `pdf.white-text;pdf.offpage-text` | 682 |
| in_page_split_text_objects | `pdf.render-mode-3` | 462 |
| in_page_tiny_text | `pdf.tiny-font;pdf.offpage-text` | 660 |
| in_page_white_text | `pdf.white-text;pdf.offpage-text` | 660 |
| layout_mimicry | `pdf.white-text;pdf.offpage-text` | 669 |
| margin_microtext | `pdf.tiny-font;pdf.offpage-text` | 618 |
| microglyph_steganography | `pdf.tiny-font;pdf.offpage-text` | 696 |
| near_margin_normal_font | `pdf.offpage-text` | 654 |
| plain_single_block | `pdf.offpage-text` | 182 |
| plain_single_block | `pdf.render-mode-3` | 176 |
| plain_single_block | `pdf.tiny-font;pdf.offpage-text` | 153 |
| plain_single_block | `pdf.white-text;pdf.offpage-text` | 136 |
| semantic_fragmentation | `pdf.render-mode-3` | 639 |
| split_text_objects | `pdf.offpage-text` | 248 |
| split_text_objects | `pdf.render-mode-3` | 188 |
| split_text_objects | `pdf.tiny-font;pdf.offpage-text` | 138 |
| split_text_objects | `pdf.white-text;pdf.offpage-text` | 98 |
| steganographic_acrostic | `pdf.offpage-text` | 792 |

