# Benchmark v2 stress tests (2026-10-11)

These tests ran the v2 content pools and the injector's new keys on real data before the corpus builder is written. Every number below comes from `tools/crackedpdfs-v2/scripts/stress_v2.py`.

The inputs were:
- the full payload pool (4,653 typed English payloads in 4,180 clusters);
- the 2,000-file GovDocs1 sample in `real-negatives/govdocs1`;
- resolved configs for the 13 families kept in the v2 core.

The GovDocs1 files serve here only as a test bed. The real build must take benign prose and base documents from GovDocs1 threads that are disjoint from the real negatives.

## 1. Content folds

Payload clusters were dealt to folds round-robin within each message type, and that left one type badly skewed. `summarization_steering` came out at 43/22/24/65/20 rows across five folds, because a few large paraphrase clusters landed together. Clusters are now dealt largest first to the fold with the fewest rows of that type.

| Type | Before (rows per fold) | After |
| --- | --- | --- |
| summarization_steering | 43 / 22 / 24 / 65 / 20 | 39 / 36 / 33 / 33 / 33 |
| task_hijack | 171 / 161 / 189 / 177 / 169 | 173 / 173 / 173 / 173 / 175 |
| instruction_override | 300 / 292 / 311 / 311 / 300 | 304 / 303 / 303 / 303 / 301 |

No cluster spans two folds.

## 2. Surface shortcuts between instruction and benign text

Length matching was already exact. But payloads talk to the reader and in the first person far more often than government prose does, so single surface features still separated the two roles. The table gives the AUC of each single feature for telling payload text from its matched benign text, where 0.5 means no signal. All rows use 434 source documents.

| Feature | Length only | + style matching | + reuse cap 8 (shipped) |
| --- | --- | --- | --- |
| first person ("I", "my") | 0.871 | 0.556 | 0.538 |
| second person ("you") | 0.826 | 0.483 | 0.486 |
| ends with a period | 0.191 | 0.454 | 0.484 |
| length | 0.500 | 0.500 | 0.500 |
| upper-case ratio | 0.272 | 0.208 | 0.174 |
| digit ratio | 0.251 | 0.304 | 0.268 |

How the matcher now removes those signals:
- **Matched opening:** the benign text opens with a sentence that addresses the reader or speaks in the first person whenever the payload does.
- **Matched ending:** it copies a closing "?" or "!", and it drops the closing mark when the payload has none.
- **Length first:** exact length always takes priority. A styled draw that misses the length gives way to an unstyled draw that hits it. Exact length now holds for all 4,653 payloads, with no failed draws.

### Sentence reuse

The first styled version reused one short "you" sentence in 164 items, which gave a text model a benign marker it could memorise. Openers now have a hard cap on reuse, and closing sentences prefer the least-used candidate. Sweeping the cap gave these results. The shipped default, run on 500 files, gives exact length on every draw, 85% of draws matching the payload's full style, and a maximum reuse of 20.


| Opener cap | First-person AUC | Max reuse of any sentence |
| --- | --- | --- |
| 4 | 0.613 | 18 |
| 8 (default) | 0.538 | 20 |
| 12 | 0.510 | 25 |
| 20 | 0.502 | 30 |

### What remains

- **Upper-case and digit ratios:** these still separate the roles somewhat (AUC 0.17 and 0.27). GovDocs prose carries more acronyms and numbers than the payloads do. These ratios should be reported in the shortcut audit, not hidden.
- **Word n-grams:** they separate the roles almost perfectly (cross-fold AUC 0.999). That is expected, because the content really differs. The main label is unaffected: the hidden-instruction label is defined within each item, where the text is held fixed across visibility.

### Pool size

The safeguards depend on the size of the benign pool. With 34 source documents instead of 434:
- 5% of draws fail;
- exact length drops to 86%;
- the "you" and first-person AUCs return to 0.83 and 0.86.

The build therefore needs at least 500 source documents.

## 3. Page targeting on real multi-page documents

The test injected one hidden member and its visible twin into one random page (among the first ten) of each of 150 multi-page GovDocs1 PDFs, cycling through the 13 core families.

| Check | Hidden | Visible |
| --- | --- | --- |
| injected and re-read | 149 / 150 | 149 / 150 |
| payload extracted from the target page | 149 / 149 | 149 / 149 |
| payload found on any other page | 0 | 0 |
| page count kept | 149 / 149 | 149 / 149 |
| an untouched page renders pixel-identical | 149 / 149 | 149 / 149 |

- **The one failure:** the source PDF is itself unreadable by pypdf, so the builder must screen base documents first.
- **Injection time:** median 52 ms, p95 1.1 s. The slowest file took 5.9 s; slow cases are large scanned files.

## 4. Render traces of hidden members on real pages

On synthetic bases, hidden members leave almost no render trace. On real pages they can. White text, low-contrast text and layout mimicry are drawn wherever the family's default anchor falls, and on a real page that is often body text, a figure or a shaded box.

The ratio below compares pixels changed by the hidden member with pixels changed by its visible twin, at 100 dpi; a member is flagged when the ratio exceeds 0.1. Each row uses 20 documents.

| Family | Default anchor: median | Default anchor: flagged | Blank-area anchor: median | Blank-area anchor: flagged |
| --- | --- | --- | --- | --- |
| in_page_white_text | 0.099 | 50% | 0.000 | 5% |
| in_page_low_contrast_text | 0.132 | 60% | 0.000 | 10% |
| layout_mimicry | 0.125 | 55% | 0.000 | 5% |
| in_page_tiny_text | 0.080 | 0% | 0.080 | 0% |

The blank-area anchor comes from `crackedpdfs_v2.placement.blank_anchors` and is passed to the injector's new `anchor` key.

- **Tiny text:** this family leaves the same small trace wherever it lands, so anchoring cannot help it. That trace is a property of the family.
- **Builder rule:** place every in-page hidden member at a blank anchor, and give its visible twin the same anchor. Keep the render-diff gate as well. Members still above 0.1 are reported as a separate "partially visible" stratum, not labelled hidden.

## Reproduce

```
npx tsx scripts/v2/resolve_injection_configs.ts < combos.json > resolved.json
python tools/crackedpdfs-v2/scripts/stress_v2.py content --pdfs real-negatives/govdocs1/pdfs -n 500
python tools/crackedpdfs-v2/scripts/stress_v2.py inject  --pdfs real-negatives/govdocs1/pdfs --configs resolved.json -n 150
python tools/crackedpdfs-v2/scripts/stress_v2.py anchor  --pdfs real-negatives/govdocs1/pdfs --configs resolved.json -n 80
```

`combos.json` holds one `{"attack_family": ..., "attack_strength": "medium"}` object per family. The first two columns of the section 2 table were measured with an earlier version of the same script. The shipped script reproduces the final column.
