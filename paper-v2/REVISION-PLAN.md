# CrackedPDFs v2: revision plan after the FLMSec reject

Status: plan only. Nothing here is built. Measurements quoted below were taken on 2026-09-30 from the frozen v1 release tables (`labels.parquet`, `splits.json`, `metrics.json`) and the repository at `main` (`aa680a0`).

## 1. What the reviews got right, what they got wrong, and what we measured

| Reviewer concern | Verdict | Evidence |
| --- | --- | --- |
| JNsg: payload strings leak across splits because grouping is by document only | Correct, and worse than they guessed | 104 distinct payloads total (13 per message type). All 104 appear in train, validation, and test. Every one of the 973 frozen test injections uses a payload seen in training, 72 to 114 times each. |
| JNsg: payloads come from public datasets [19, 20] | Wrong premise, same conclusion | The 104 messages are hand-written in `src/lib/prompt-injection-message-library.ts`. No public dataset is read anywhere. The citations say "informed partly by", which reads as sourcing. |
| RDJV, eH9y, JNsg: text-only ties hybrid, so structure adds nothing | Correct, and now explained | With every test payload memorised, extracted text is sufficient. The tie is a symptom of leakage, not evidence about structure. |
| eH9y: TF-IDF "shortcut-prone" is asserted, not shown | Partly wrong | `metrics.json` already has top-weight audits. We never printed them. Hybrid top positive features: ` e `, ` t `, ` n `, ` r `, ` o `, ` s ` (single letters between spaces, the split-text and acrostic chunking artifact), then `instructions`, `hidden`, `answer`, `do not`. TF-IDF top negative features: `benign layout calibration text only` (confounder boilerplate). Both detectors learned the generator. |
| RDJV: unclear whether detectors see hidden content or recognise synthetic attack text | Correct | Same evidence as above. The PromptGuard baseline also receives raw text with every marker and wrapper intact and truncated at 512 tokens, so it is not a fair text baseline either. |
| eH9y: fully synthetic, non-adaptive | Correct | One generator, 14 templates, one injector. No real negatives. |
| JNsg: PromptGuard is domain-mismatched | Correct | Agreed in the paper already. |
| JNsg: 973 pairs from 498 groups, no dependence correction | Correct | Bootstrap is row-level, 200 iterations. |
| RDJV, JNsg: no PhantomLint comparison | Correct, and now feasible | PhantomLint is public (BSD-3, PDF input, offline, OCR-based). |
| All: acrostic failure unexplained | Now explained by the September erratum | Acrostic text is entirely off the page and the confounder is longer than the payload in 514 of 792 pairs, reversing the length signal every other family carries. |

Additional defects found while measuring, not raised by reviewers:

- `labels.parquet` has a `dataset_split` column that disagrees with `splits.json` for 94% of rows. `splits.json` is the frozen truth, but anyone reading the parquet alone gets a different split.
- `data/metadata.parquet` and `data/labels.parquet` in the release are byte-identical files.
- `raw_injected_text` and `message_length_chars` are null for every row, so the release cannot be audited for payload overlap without this repository.
- The hybrid is absent from the standard leave-one-family-out eval configs and only runs in the `model_only` variants; the paper does not say which was used.
- The text mismatch feature group is disabled in every config, so three of the four "mismatch" features are constant zero. The paper lists them as features.
- The spatial-placement bug (erratum, September 2026) means every regime label except `extreme_off_page` is wrong in v1.

## 2. The thesis after revision

Drop "structure beats text" as the claim. The defensible v2 thesis is:

> Hidden-instruction detection in PDFs must be evaluated against three confounds at once: payload memorisation, generator artifacts, and visibility-matched text. CrackedPDFs v2 controls all three and reports what survives.

The headline result then becomes whatever the both-out split shows. JNsg said explicitly that a large drop "is itself the paper's most important finding". Plan for either outcome (section 9).

## 3. Workstreams

Each workstream lists the change, the stress test that would falsify it, and the kill criterion.

### WS1. Payload-grouped evaluation (blocks JNsg's primary objection)

Change:
1. Expand the payload pool from 104 to at least 1,500 messages with stable ids and a recorded source. Sources: the existing 104, deepset/prompt-injections (Apache-2.0), AgentDojo injection tasks (MIT), BIPIA attacker goals (CC BY-SA), Open-Prompt-Injection (MIT), SPML (MIT), plus LLM-paraphrased variants labelled as paraphrases of a parent id. Keep each message's license in the manifest.
2. Near-duplicate clustering with MinHash over character 5-grams at 0.7 Jaccard, plus parent-paraphrase links. The grouping key is the cluster id, not the message id.
3. New split builder: independent K-fold over `base_pdf_id` and over `payload_cluster_id`, evaluated on the block where both are held out (Pahikkala's S4 "both-out" design; Park and Marcotte C3). Report C1 (both seen), C2 (document unseen), C2' (payload unseen), and C3 (both unseen) in one table.
4. Keep the message-type stratification so every type appears in each fold.

Stress tests:
- Audit script asserts zero payload-cluster overlap between train and C3 test, and prints the Jaccard of the nearest train message for every test message. Fails the build if any pair exceeds 0.7.
- Rerun the frozen v1 pipeline on the v1 corpus with payload-grouped folds (this is possible today from `message_variant_id` without regenerating anything). This gives the "v1 under payload holdout" number that JNsg asked for and belongs in the arXiv v2 erratum regardless of the rest of the plan.

Kill criterion: if C3 F1 for sanitized text-only stays above 0.95 with 1,500 payloads, the leak was not the explanation and section 9 branch B applies.

### WS2. Remove generator shortcuts (blocks RDJV, eH9y W1 and W3)

Change:
1. Symmetric scaffolding. Injected and confounder members get identical marker lines and identical wrapper tags (one neutral tag for both roles). Confounder body text is drawn from a prose bank of the same register and exact character length as the payload, not a repeated calibration sentence. PR #6 did length parity; the tag asymmetry and the calibration boilerplate remain.
2. Chunking parity. Whatever chunking the attack family applies to the payload (single characters per text object, acrostic initials, fragments) is applied to the confounder text too. Today the single-letter trigram is the strongest feature in the model.
3. Audit the sanitizer in both directions: `_strip_known_scaffold_blocks` must not delete content from one role only. Replace with a role-blind strip of the single neutral tag.
4. Add a text-token shortcut audit to the existing numeric one: single n-gram classifiers over sanitized text, flag any n-gram whose presence alone exceeds 0.7 accuracy, and gate the release on it.

Stress tests:
- Train TF-IDF on v2 and inspect the top 200 weights: none may be a scaffold token, a single-letter trigram, or a confounder-only phrase.
- Length-only paired ranker (already in the erratum derivation) must sit at 0.5 within its CI on every family.
- Label-shuffle retrain stays at chance (already done, keep).

Kill criterion: any n-gram above the 0.7 single-feature gate blocks the release, the same rule the numeric audit already applies.

### WS3. Visibility-matched quartets (RDJV's concrete suggestion)

Change: extend each triplet to a quartet by adding a `visible_instruction` member: the same payload, same position, same font, rendered visibly (normal render mode, black, normal size, inside the page). Two labels per file:
- `contains_instruction` (visible_instruction = 1, injected = 1, originals and confounders = 0).
- `hidden_instruction` (injected = 1, everything else = 0).

Report detectors under both labels. A detector that scores visible_instruction as high as injected under the hidden-instruction label is reading text, not visibility. This is the experiment that separates the two mechanisms, and it directly answers "does structure matter".

Stress tests:
- The `crackedpdfs-audit` tool must verify every visible_instruction member is `likely_visible` for all glyphs and has nonzero pixel diff against the original.
- Text-only detectors should be near chance on injected versus visible_instruction; structure-aware ones should not. If neither separates them, structure features are not capturing visibility and WS6 feature work is needed.

### WS4. Regenerate the corpus with truthful placement (erratum follow-through)

Change: regenerate with the merged generator (idempotent resolution, placement contract, q/Q isolation, matched confounders), gated by `crackedpdfs-audit corpus --strict` in CI. Release as v2 with a new DOI. Decisions needed first:
- Acrostic family redesign: dedicated visible region with plausible prose, no body overlap, full message recovery, and a decoder test that recovers the instruction from the PDF. Without a decoder test the family cannot claim the instruction is present.
- `in_page_split_text_objects` strong strength: either fix validation so character-per-object samples can pass, or drop the strength and say so.
- Add multi-page base documents (PDFAutoGen supports one page today) so "off page" has a meaning beyond "below page 1".

Stress tests: the audit's realized placement must equal the label for 100% of files per label; the summary table from the erratum is regenerated and must show zero `straddles_page_edge`.

### WS5. Real documents and a second injector (eH9y W1, JNsg synthetic corpus)

Change:
1. Real benign negatives for false-positive measurement: a 5,000-file sample from GovDocs1 (redistributable) and the DocLayNet PDFs (CDLA-Permissive-1.0), deduplicated by SHA-256 and screened with `crackedpdfs-audit` and PhantomLint so pre-existing hidden text is recorded rather than mislabelled.
2. Real-document positives: inject into those same real PDFs with our injector, giving injected and confounder twins on real bases.
3. Independent injector: a second implementation that does not share code with ours. Candidates: the zhihuiyuze PDF-Prompt-Injection-Toolkit generators (MIT), a reportlab-based writer, and a Chromium print-to-PDF path with CSS hiding (white text, zero font size, offscreen absolute positioning, `opacity: 0`). Train on ours, test on theirs.
4. Attack mechanisms the current injector does not produce and which real attackers use: annotations and form fields, metadata and XMP, optional content groups (hidden layers), zero-width and Unicode tag characters, ToUnicode remapping (the font-mapping attack in reference 7), image-only text (OCR-mediated). Each family needs a matched confounder.

Stress tests:
- Report FPR on real negatives with Wilson intervals, separately for clean files and files the screening flagged.
- Cross-injector transfer table: train A test B and train B test A for every detector.

Kill criterion: none. This is where the paper either generalises or honestly reports that it does not.

### WS6. Baselines and fair comparisons (RDJV and JNsg on PhantomLint, eH9y W3)

Change:
1. PhantomLint as a baseline: wrap its phrase output into a document score (fraction of extracted characters flagged hidden) and a binary verdict. Run it on v1 and v2 and on the real-document sets.
2. Open structural detectors: wppoland/hidden-text-detector (MIT) and Andy8647/pdf-injection-scanner (MIT) as rule baselines that we did not write.
3. Text baselines fed the same sanitized text as our models, chunked rather than truncated: Llama Prompt Guard 2 (22M and 86M), ProtectAI deberta-v3-prompt-injection-v2, Horizon-Labs prompt-injection-guard (Apache-2.0, targets document content). Keep the raw-text PromptGuard-86M run only as the "what a naive deployment sees" row.
4. Run every detector in every leave-one-family-out config, including the hybrid, and state which config each figure uses.
5. Feature-group ablations for the hybrid (drop text, drop each structural group) on the C3 split, with the top-weight audits printed in the appendix.

Stress tests: a baseline must be run with its own defaults and with our sanitized text, and both rows reported.

### WS7. Statistics (JNsg's dependence point)

Change:
- Cluster bootstrap over `base_pdf_id` for all document-level metrics, and over `payload_cluster_id` for the C3 numbers, 2,000 resamples, percentile intervals (Field and Welsh 2007).
- Paired-ranking accuracy with Wilson intervals on an effective sample size `n / DEFF` (Dean and Pagano 2015).
- Replace the pre-registered "hybrid ahead on 4 of 5 splits" rule with a paired bootstrap of the per-split F1 difference and report the interval.
- Every table carries intervals. No bare point estimates.

### WS8. Paper rewrite (eH9y W2, W4, W5; JNsg reframing)

- Lead with the problem and the stakes (one paragraph of real incidents: the hidden-prompt peer-review cases from Lin 2025, Zhou et al. 2026, Keuper 2025), then the three confounds, then the benchmark.
- One headline table: C1, C2, C2', C3 for each detector, with intervals. Table 1 versus Table 2 confusion goes away because the resampling is the main protocol.
- A discussion section that ties results together: leakage explains the v1 tie, chunking artifacts explain the TF-IDF perfect score, off-page geometry and reversed length explain the acrostic failure, and the quartet experiment says whether visibility is being detected at all.
- Related work expanded with: PhantomLint, Liu and Ming 2026 (semantic integrity failures in document-to-LLM supply chains, the closest framing), TrapDoc, Fomin 2026 and PIDS-Bench 2026 (shortcut and distribution-shift findings in injection classifiers), InjecGuard (over-defense), BIPIA, Open-Prompt-Injection, the peer-review hidden-prompt studies, and the pair-input leakage literature (Park and Marcotte 2012, Pahikkala 2015, Bernett 2024). Cite published versions where they exist.
- Fix the [19, 20] citation so it no longer implies the payloads were drawn from those datasets.
- An explicit "what v1 got wrong" subsection pointing to the erratum. Reviewers rewarded transparency; keep doing it.

### WS9. Release and reproducibility hygiene

- Fix `dataset_split` in the labels table or remove the column; make `splits.json` the only source.
- Ship a real `metadata.parquet` with `message_variant_id`, `payload_cluster_id`, `payload_source`, `payload_license`, realized placement fields, and the audit verdict per file.
- Ship payload text in the release (it is the attack, there is no reason to hide it) so overlap can be audited without this repo.
- Add a `make audit-release` target that runs the placement audit, the text-token shortcut audit, the payload-overlap audit, and the split consistency check, and have CI run it on the example triplets plus a sampled download.
- Remove Windows absolute paths from frozen metrics.
- Version the detector configs with the corpus version so v1 configs cannot silently run on v2 data.

## 4. Experiments to run on v1 before any regeneration

These need only the frozen artifacts and the existing pipeline, and they should go into an arXiv v2 and a second erratum within two weeks:

1. Payload-grouped folds on v1 (WS1 stress test). The single most important number for the rebuttal story.
2. Print the existing top-weight audits (WS2 evidence). Already computed, never reported.
3. PromptGuard rerun on sanitized, chunked text (WS6).
4. PhantomLint on the v1 test split (WS6).
5. Cluster bootstrap intervals for the existing headline numbers (WS7).
6. Hybrid in all six leave-one-family-out configs with the config named (WS6).

## 5. Sequencing

| Phase | Weeks | Output |
| --- | --- | --- |
| A. v1 re-analysis (section 4) | 1 to 2 | arXiv v2 of the paper with corrected claims; erratum 2 |
| B. Generator: WS2 scaffolding and chunking parity, WS3 quartets, WS4 acrostic and split-text decisions | 3 to 5 | Generator PRs with contract tests and audit gates |
| C. Payload pool and both-out splitter (WS1) | parallel with B | `payloads/` manifest with ids, licenses, clusters; splitter with tests |
| D. Regenerate v2 corpus, audit, release (WS4, WS9) | 6 | v2 DOI |
| E. Real documents and second injector (WS5) | 6 to 9 | Real-negative FPR table, cross-injector table |
| F. Baselines, ablations, statistics (WS6, WS7) | 8 to 10 | Full result tables with intervals |
| G. Paper rewrite (WS8) | 10 to 12 | Submission-ready draft |

Phase A is independent and should ship first regardless of whether the rest proceeds.

## 6. Decisions only the authors can make

1. Venue and deadline: another workshop, or a datasets-and-benchmarks track that rewards the controls and the negative results. This sets how much of WS5 is in scope.
2. Acrostic family: redesign with a decoder test, or drop it and say the family is deferred.
3. Whether v2 keeps the "hybrid detector" as a contribution at all, or positions the paper purely as a benchmark with baselines. The evidence so far favours the latter.
4. How to credit Van Chappell (HiddenContent.ai) for the placement finding.
5. Payload sources: whether CC BY-SA data (BIPIA) is acceptable given the release license.

## 7. Stress-testing the plan itself

Things that could go wrong with the plan, and the answer:

- The both-out split leaves too few C3 cells per family. With 4,983 documents and 1,500 payload clusters in 5 by 5 folds, each C3 block is about 4% of pairs, roughly 400 injected files per fold, about 27 per family. Mitigation: use repeated folds and pool, and report per-family C3 only where support is at least 100.
- Paraphrased payloads leak their parent's phrasing. Mitigation: cluster id, not message id, is the grouping key; paraphrases inherit the parent cluster.
- Real-document negatives contain genuine hidden text. Mitigation: screen with two independent tools, record the result, and report FPR both ways.
- A second injector shares a library (pikepdf) with ours and inherits artifacts. Mitigation: at least one injector path that never touches pikepdf (Chromium print, reportlab).
- The quartet's visible_instruction member changes page layout and so leaks through structure. Mitigation: the audit records pixel diff and glyph counts; the confounder gets the same visible prose block.
- Expanding the pool changes message-type balance. Mitigation: stratify by type in both fold dimensions.
- Regeneration breaks the frozen v1 reproduction. Mitigation: v1 artifacts and `make reproduce-results` stay pinned; v2 gets its own manifest.

## 8. What to say in the rebuttal or cover letter

Three sentences: the reviewers' leakage concern is correct and the measured overlap is complete (104 payloads, all in every split); the near-tie between text and hybrid and the TF-IDF perfect score are explained by payload memorisation and generator chunking artifacts, which we now audit and remove; v2 adds payload-grouped both-out evaluation, visibility-matched quartets, real-document negatives, a second injector, and PhantomLint and modern text baselines, and reports whatever survives.

## 9. Expected outcomes and the two branches

Branch A (likely): C3 F1 for text-only drops well below 0.9 and the hybrid retains an advantage on the quartet hidden-instruction label. The paper's thesis is restored with evidence, and the v1 numbers are reported as the C1 row.

Branch B: C3 F1 stays high for text-only, or the quartet shows no visibility separation. Then the contribution is the benchmark and the controls, the headline is that current detectors read text rather than visibility, and the detector is demoted to a baseline. JNsg said this outcome is publishable. Write the paper so either branch fits the same structure.
