# CrackedPDFs revision: related-work notes

Compiled 2026-10-08 from web sources only (publisher pages, ACL Anthology, USENIX, Crossref, PMLR, OpenReview, arXiv abstract pages, Hugging Face, GitHub). Every key below exists in `references.bib`. Venue status labels:

- **Published**: final venue confirmed against a publisher record.
- **To appear**: acceptance stated only in the arXiv comment field; no proceedings record yet.
- **Preprint**: no peer-reviewed venue found as of October 2026.

Nothing in this file is uncited or invented. Items I could not confirm are listed at the end under "Unverified or caveated".

Total: 117 scholarly or grey-literature entries plus 6 software-artifact entries (123 BibTeX entries).

---

## 1. Background: prompt injection attacks

| Key | Status | One-line summary | Relation to CrackedPDFs |
|---|---|---|---|
| `perez2022ignore` | Preprint (workshop venue unconfirmed) | PromptInject: handcrafted inputs that hijack the goal of GPT-3 or leak its prompt. | Earliest systematic demonstration of direct injection; motivates the threat. |
| `greshake2023not` | Published, AISec 2023 | Defines indirect prompt injection: instructions planted in retrieved data, including hidden text in web pages. | The threat model CrackedPDFs instantiates for PDF ingestion. |
| `liu2023prompt` | Preprint | HouYi: black-box injection against deployed LLM-integrated apps. | Shows injection against real applications; text-only. |
| `liu2024formalizing` | Published, USENIX Security 2024 | Formal framework for prompt injection; benchmarks 5 attacks against 10 defenses (Open-Prompt-Injection). | Canonical formalization; CrackedPDFs should adopt its target task / injected task terminology. |
| `toyer2024tensor` | Published, ICLR 2024 | Tensor Trust: 563k attacks and 118k defenses from an online game. | Source of human-written injection text; no document carrier. |
| `schulhoff2023ignore` | Published, EMNLP 2023 | HackAPrompt competition, about 600k adversarial prompts and a taxonomy. | Same as above; payload diversity reference. |
| `pasquini2024neural` | Published, AISec 2024 | Neural Exec: optimized execution triggers for injection. | Optimized payloads are a natural adaptive-attack extension for the benchmark. |
| `zverev2025can` | Published, ICLR 2025 | Formal measure of instruction/data separation; SEP dataset; no model separates well. | Explains why hidden data-channel text is dangerous once extracted. |
| `owasp2025llm01` | Grey literature | OWASP ranks prompt injection as the top LLM application risk. | Practitioner framing for the introduction. |
| `wang2026landscape` | Preprint | Taxonomy and analysis of injection attacks and defenses for LLM agents. | Survey-style context. |
| `khodayari2026indirect` | Preprint | Scan of about 1.2 billion URLs found about 15.3k hidden AI-directed instructions. | Web-scale prevalence evidence; HTML rather than PDF. |

## 2. Indirect injection and agent benchmarks

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `yi2025benchmarking` | Published, KDD 2025 | BIPIA: first indirect-injection benchmark (email, web, table, code) plus boundary-marking defenses. | Text-level carriers only; CrackedPDFs supplies the file-format carrier BIPIA abstracts away. |
| `debenedetti2024agentdojo` | Published, NeurIPS 2024 D&B | AgentDojo: 97 tool-use tasks for evaluating injection attacks and defenses. | Measures agent outcome, not detection of the carrier. |
| `zhan2024injecagent` | Published, Findings of ACL 2024 | InjecAgent: 1,054 tool-integrated injection cases. | Same; text-only tool outputs. |
| `evtimov2025wasp` | Published, NeurIPS 2025 D&B | WASP: web-agent injection benchmark. | Web carrier analogue. |
| `liao2025eia` | Published, ICLR 2025 | EIA: hidden web elements that make generalist web agents leak PII. | Closest web analogue of visually hidden payloads. |
| `guo2026hidden` | Published, WWW 2026 | OpenRAG-Soc benchmark for social-web indirect injection in RAG, with sanitization and Unicode-normalization defenses. | HTML/Markdown carrier; no PDF rendering semantics. |

## 3. Defenses: detection classifiers and detectors

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `meta2025promptguard2` | Model card | Llama Prompt Guard 2 (86M) injection and jailbreak classifier. | Already a CrackedPDFs baseline; low recall on extracted text. |
| `chennabasappa2025llamafirewall` | Preprint | LlamaFirewall; describes Prompt Guard 2, AlignmentCheck, CodeShield. | Citable technical description for Prompt Guard 2. |
| `protectai2024debertav2` | Model card | ProtectAI DeBERTa-v3-base injection classifier v2. | Already a baseline. |
| `deepset2023deberta` | Model card | deepset DeBERTa-v3-base injection classifier. | Already a baseline. |
| `li2025piguard` | Published, ACL 2025 | PIGuard (formerly InjecGuard): NotInject over-defense benchmark and MOF training. | Over-defense on trigger words maps directly onto CrackedPDFs' benign confounders. Add PIGuard as a baseline. |
| `jacob2025promptshield` | Published, CODASPY 2025 | PromptShield benchmark and detector, evaluated at low false-positive rates. | Supports reporting TPR at fixed low FPR rather than F1 alone. |
| `hung2025attention` | Published, Findings of NAACL 2025 | Attention Tracker: training-free detection from attention drift. | Model-internal detector; operates after extraction. |
| `liu2025datasentinel` | Published, IEEE S&P 2025 | DataSentinel: minimax-trained detector LLM. | Strongest published text-level detector; code in Open-Prompt-Injection (MIT). |
| `abdelnabi2025get` | Published, SaTML 2025 | TaskTracker: activation-delta probes for task drift. | Same family as Attention Tracker. |
| `ivry2025sentinel` | Preprint | Sentinel: ModernBERT-large injection classifier. | Candidate baseline (gated, custom license). |
| `kholkar2025capture` | Published, LLMSec 2025 | CAPTURE: context-aware guardrail benchmark that measures misses and over-defense. | Over-defense measurement precedent. |

## 4. Defenses: training-time and system-level

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `chen2025struq` | Published, USENIX Security 2025 | StruQ: separate prompt and data channels; fine-tune to ignore data-channel instructions. | Complementary: if hidden text is extracted into the data channel, StruQ-style models may still ignore it. CrackedPDFs is upstream of this. |
| `chen2025secalign` | Published, CCS 2025 | SecAlign: preference optimization against injection. | Same. |
| `hines2024defending` | Published, CAMLIS 2024 (CEUR) | Spotlighting: delimiting, datamarking, encoding of untrusted input. | Prompt-level mitigation that cannot recover lost visibility information. |
| `wallace2024instruction` | Preprint | Instruction hierarchy training. | Same. |
| `piet2024jatmo` | Published, ESORICS 2024 | Jatmo: task-specific fine-tuning of non-instruction-tuned models. | Same. |
| `shi2025promptarmor` | Preprint | PromptArmor: off-the-shelf LLM finds and removes injected text. | LLM-as-detector baseline candidate (needs API or local LLM). |
| `zhu2025melon` | Published, ICML 2025 | MELON: masked re-execution to detect indirect injection in agents. | Agent-level; orthogonal. |
| `debenedetti2026defeating` | Published, SaTML 2026 | CaMeL: control/data-flow separation with capabilities. | System-level design that bounds damage regardless of detection. |
| `jia2026critical` | Published, SACMAT 2026 | Critical evaluation shows defenses are weaker than reported once utility and adaptive attacks are measured. | Supports CrackedPDFs' emphasis on evaluation design. |

## 5. Adaptive attacks, over-defense, and shortcut findings in injection detectors

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `zhan2025adaptive` | Published, Findings of NAACL 2025 | Adaptive attacks bypass all 8 tested indirect-injection defenses. | CrackedPDFs does not evaluate adaptive attackers; must be stated as a limitation. |
| `nasr2026attacker` | Published, USENIX Security 2026 | "The Attacker Moves Second": gradient, RL, search, and human attacks break 12 defenses. | Same; strongest citation for the limitation. |
| `fomin2026when` | Published, ICLR 2026 workshop (AIWILD) | Leave-one-dataset-out evaluation; same-source splits inflate AUC by 8.4 points; 28% of top SAE features are dataset shortcuts. | Directly parallels CrackedPDFs' provenance-held-out splits and shortcut audits. |
| `shire2026pidsbench` | Published, IEEE Access 2026 | PIDS-Bench: detectors with F1 above 0.98 in-distribution misclassify about a third of external security-adjacent benign prompts. | Directly parallels the matched-confounder design; cite for "provenance-sensitive over-defense". |
| `li2026defenses` | Published, ACL 2026 | Fine-tuned defenses learn position, trigger-token, and topic shortcuts. | Mechanistic evidence for the shortcut concern. |
| `biswas2026confidently` | Preprint | Severity-aware calibration of injection detectors under attack shift. | Calibration angle; optional. |
| `jaffal2026ragpibench` | Preprint (6 Oct 2026) | RAG-PIBench: leakage-aware frozen splits; TF-IDF baselines remain competitive. | Independent confirmation that sparse lexical baselines are strong and that leakage control matters. |
| `li2025piguard` | (see section 3) | Over-defense benchmark. | Same. |

## 6. Document and PDF hidden content, parser differentials, and poisoning

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `liu2027what` | To appear, IEEE S&P 2027 | 25 "extraction gaps" in four families across 16 PDF stacks and 7 commercial LLM services; static scanner; proposes dual-view consistency. | **Closest competitor.** See differentiation below. |
| `murray2025phantomlint` | Preprint | PhantomLint: prompt-phrase filter, then crop, render, and OCR each flagged block; flags words extracted but not seen. 0.092% FPR on 3,257 ICML 2025 PDFs. | **Closest detector.** Already a baseline. |
| `jin2025trapdoc` | Published, Findings of EMNLP 2025 | TrapDoc: imperceptible "phantom tokens" (for example, zero-size font) in documents make LLMs produce plausible but wrong output. | Same hiding primitives, different goal (deceiving over-reliant users). Payload is not instruction-shaped, so phrase-based detectors miss it. |
| `castagnaro2025hidden` | Published, AISec 2025 | 19 hiding techniques in DOCX, HTML, and PDF against 5 RAG data loaders; 74.4% attack success over 357 scenarios; validated on NotebookLM and OpenAI Assistants. | Attack-side measurement of the same ingestion gap; no detector benchmark or matched controls. |
| `luo2026exploiting` | Preprint (IACR ePrint) | Font-level glyph remapping makes text-extracting LLM platforms read different text than shown; OCR pipelines robust. Also bypasses arXiv TeX detection. | Font/ToUnicode family that CrackedPDFs should cover or explicitly exclude. |
| `xiong2025invisible` | Published, Findings of EMNLP 2025 | Malicious font injection in web resources: code-to-glyph remapping hides prompts. | Font-remapping precursor. |
| `markwood2017pdf` | Published, USENIX Security 2017 | PDF Mirage: font-based content masking against reviewer assignment, plagiarism detection, and search indexing. | The pre-LLM origin of the rendered-versus-extracted gap. Essential citation. |
| `kuchta2018correctness` | Published, EMSE 2018 | 13.5% of real PDFs render inconsistently across readers; 230k-document differential study. | Shows that "what the human sees" is reader-dependent, which bounds any visibility label. |
| `mainka2021shadow` | Published, NDSS 2021 | Shadow attacks hide or replace content in signed PDFs via viewer differences. | Parser-differential precedent. |
| `carmony2016extract` | Published, NDSS 2016 | Parser differentials hide JavaScript from malware detectors' extractors. | Same principle applied to detectors. |
| `zhang2024imperceptible` | Published, ASE 2024 | Imperceptible content poisoning of LLM-powered apps (about 90% success). | Early systematic hidden-content poisoning study. |
| `sinha2026hiding` | Workshop (FAGEN @ ICML 2026) | Float-array steganographic carriers evade Prompt Guard 2 plus TF-IDF ensembles. | Shows text-view detectors fail on encoded payloads; relevant to the acrostic and steganographic families. |
| `jia2026seeing` | Preprint | SkillCamo: instructions hidden in images bundled with agent skills evade text-only scanners. | Image-carrier analogue. |
| `guo2025too` | Preprint | Hidden instructions in PDFs flip LLM answers on trivial multiple-choice questions. | Small attack demonstration using white text in PDFs. |
| `boucher2022bad`, `boucher2023trojan`, `gao2025imperceptible` | Published (S&P 2022, USENIX Sec 2023) / Preprint | Unicode invisible characters, homoglyphs, bidi controls, variation selectors. | Character-level hiding that survives any extractor; overlaps with CrackedPDFs' microglyph family. |

## 7. Hidden prompts in peer review and hiring

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `nikkei2025positive` | News | First report of 17 arXiv preprints with white or tiny-font reviewer prompts. | Real-world trigger. |
| `gibney2025scientists` | Published, Nature news 2025 | Nature's count of 18 preprints. | Citable incident report. |
| `lin2026hidden` | Published, CACM 2026 | Analysis of 18 manuscripts with hidden reviewer-directed prompts; argues it is misconduct. | Real-world hidden-text taxonomy (white text, tiny font). |
| `icml2025publication` | Policy | ICML statement on hidden LLM prompts. | Policy context. |
| `keuper2025prompt` | Preprint | Simple hidden injections push LLM review scores up; reviews skew to accept. | Attack effectiveness evidence. |
| `collu2026misleading` | Accepted, ACM TAISAP 2026 | Hidden PDF prompts under three threat models plus evasion of automated checks. | Most thorough peer-review attack study. |
| `zhou2026give` | To appear, Findings of EMNLP 2026 | Static and iterative in-paper injections; a detection defense partly bypassed by adaptive attackers. | This is the "Zhou et al. 2026" in the revision plan. |
| `sahoo2025when` | Preprint | 1pt white-font prompts extracted via MinerU flip Reject to Accept. | Confirms extractor-mediated success. |
| `zhu2025when` | Preprint | Hidden PDF instructions steer GPT-5-mini reviews of 1,441 papers. | Effectiveness evidence. |
| `theocharopoulos2025multilingual` | Preprint | Hidden injections in about 500 ICML papers in four languages; Arabic largely ineffective. | Payload language as a factor; CrackedPDFs payloads are English only. |
| `li2026llmreviewer` | Preprint | 12 LLM reviewers; cmap glyph-remapping injection is effective. | Font-remapping in the wild of evaluations. |
| `gharami2025chatgpt` | Preprint | Hidden injections plus an editor-side inject-and-detect check. | Defensive use. |
| `rao2025detecting` | Published, PLOS ONE 2025 | Hidden prompts used deliberately as watermarks to detect LLM-written reviews. | Benign use of hidden text: a natural hard-negative class for detectors. |
| `zhang2026measuring` | To appear, USENIX Security 2026 | About 1% of about 200k real resumes contain hidden injections; over 90% are data injections, not explicit instructions; resume-specific detectors beat general ones. | **Strongest real-world prevalence evidence for PDFs**, and a direct challenge to instruction-phrase-based detection. |
| `mu2025ai` | Preprint | Resume-screening attack benchmark (invisible keywords and experience); FIDS LoRA defense. | Hidden-keyword payloads are not instructions. |
| `baxi2026prompt` | Published, Findings of ACL 2026 | Single and multi-injection resume ranking experiments. | Hiring context; hidden-ness not confirmed. |
| `akdemir2025understanding` | Published, RecSys in HR 2025 (CEUR) | Real resumes hide injections in small white text; 1,200 attack/defense combinations. | Practitioner evidence from Indeed. |
| `barach2026resumeshield` | Preprint | ResumeShield: open benchmark (104 synthetic resumes, nine concealment methods) plus channel-separation defense; detection precision 1.000, recall 0.944. | Small open benchmark with a detector; comparable but much smaller and resume-only. |

## 8. RAG and knowledge-base poisoning

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `zou2025poisonedrag` | Published, USENIX Security 2025 | Few optimized passages force attacker-chosen answers. | Poisoning payloads are visible text; CrackedPDFs is about the carrier. |
| `zhong2023poisoning` | Published, EMNLP 2023 | Adversarial passages fool dense retrievers. | Retrieval-side precursor. |
| `xue2024badrag` | Preprint | Trigger-conditioned poisoned passages. | Same. |
| `chaudhari2024phantom` | Preprint | Single-document trigger backdoor on RAG. | Same. |
| `shafran2025machine` | Published, USENIX Security 2025 | Blocker documents jam RAG. | Same. |
| `chen2024agentpoison` | Published, NeurIPS 2024 | Poisoned agent memory and knowledge bases. | Same. |
| `castagnaro2025hidden` | (see section 6) | Data-loader poisoning with hidden content. | Bridges RAG poisoning and hidden PDF content. |
| `jaffal2026ragpibench` | (see section 5) | Leakage-aware RAG injection-detection benchmark. | Detection-side RAG benchmark; text only. |

## 9. Visual and multimodal injection (OCR and VLM defenses)

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `bagdasaryan2023abusing` | Preprint | Instructions blended into images and audio. | If pipelines move to render-then-VLM, the attack surface moves into pixels. |
| `clusmann2025prompt` | Published, Nature Communications 2025 | Sub-visual prompts in medical images hijack VLMs. | Low-contrast text in pixels: the VLM-side counterpart of CrackedPDFs' low-contrast family. |
| `gong2025figstep` | Published, AAAI 2025 | Typographic jailbreak via rendered text images. | Shows OCR/VLM pipelines are not a complete defense. |
| `qi2024visual` | Published, AAAI 2024 | Visual adversarial examples jailbreak aligned LLMs. | Same. |
| `wang2025manipulating` | Preprint | CrossInject: cross-modal injection against multimodal agents. | Already cited in v1; arXiv only. |
| `chen2026repeat` | Preprint | Black-box adaptive visual prompt injection through screenshots and documents. | Adaptive attacks on render-based pipelines. |
| `murray2025phantomlint`, `luo2026exploiting`, `liu2027what` | | All argue that rendering plus OCR is the robust reading of a PDF. | CrackedPDFs should include a render-plus-OCR differential baseline. |

## 10. PDF structural malware detection

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `laskov2011static` | Published, ACSAC 2011 | PJScan: lexical analysis of embedded JavaScript. | Structural detection lineage. |
| `smutz2012malicious` | Published, ACSAC 2012 | PDFrate: random forest on metadata and structure. | Structural-feature detectors; CrackedPDFs' structural-only models are their descendants. |
| `srndic2013detection` | Published, NDSS 2013 | Structural-path features. | Same. |
| `srndic2014practical` | Published, IEEE S&P 2014 | Mimicus: evasion of PDFrate. | Structural detectors are evadable; warns against structure-only shortcuts. |
| `srndic2016hidost` | Published, EURASIP JIS 2016 | Hidost: format-agnostic structural detector. | Same. |
| `xu2016automatically` | Published, NDSS 2016 | EvadeML: genetic-programming evasion of PDFrate and Hidost. | Same. |
| `maiorca2019towards` | Published, ACM CSUR 2019 | Survey of adversarial PDF malware detection. | Background. |
| `chen2020training` | Published, USENIX Security 2020 | Verifiably robust PDF malware classifiers under subtree insertion/deletion. | Robustness properties as a model for future CrackedPDFs work. |

## 11. Evaluation methodology: shortcuts, leakage, pair-input splits, clustered inference

| Key | Status | One-line summary | Relation |
|---|---|---|---|
| `geirhos2020shortcut` | Published, Nature Machine Intelligence 2020 | Defines shortcut learning. | Frame for the TF-IDF shortcut audit. |
| `gururangan2018annotation` | Published, NAACL 2018 | Hypothesis-only baselines reveal annotation artifacts. | Analogue: text-only or structure-only baselines reveal generator artifacts. |
| `mccoy2019right` | Published, ACL 2019 | HANS: models rely on lexical heuristics. | Same. |
| `lapuschkin2019unmasking` | Published, Nature Communications 2019 | Clever Hans predictors. | Same. |
| `warnecke2020evaluating` | Published, EuroS&P 2020 | Explanations reveal artifact-driven security models. | Security-specific Clever Hans evidence. |
| `arp2022dos` | Published, USENIX Security 2022 | Ten pitfalls of ML in security, including spurious correlations and data snooping. | Checklist reviewers expect. |
| `pendlebury2019tesseract` | Published, USENIX Security 2019 | Spatial and temporal bias in malware classification. | Split design reference. |
| `kapoor2023leakage` | Published, Patterns 2023 | Leakage taxonomy across 294 papers. | Leakage framing. |
| `kaufman2012leakage` | Published, ACM TKDD 2012 | Formal definition of leakage. | Same. |
| `park2012flaws` | Published, Nature Methods 2012 | Pair-input evaluation flaws (C1/C2/C3 classes). | Injected file and confounder share a base document: exactly the pair-input setting. |
| `pahikkala2015toward` | Published, Briefings in Bioinformatics 2015 | Hold out new drugs, new targets, or both. | Same; split by base document and by template. |
| `bernett2024cracking` | Published, Briefings in Bioinformatics 2024 | Deep PPI predictors collapse to near random on leakage-free splits. | Strong recent example of the same failure. |
| `gardner2020evaluating` | Published, Findings of EMNLP 2020 | Contrast sets: minimal edits that flip the label. | CrackedPDFs' matched confounders are contrast sets for documents. |
| `kaushik2020learning` | Published, ICLR 2020 | Counterfactually augmented data. | Same. |
| `field2007bootstrapping` | Published, JRSS-B 2007 | Bootstrap schemes for clustered data. | Justifies resampling base documents, not files. |
| `dean2015evaluating` | Published, JSSAM 2015 | Confidence intervals for proportions in cluster surveys, including design-effect corrections. | Design-effect adjusted CIs for per-file metrics. |
| `kish1965survey` | Book, 1965 | Introduces the design effect. | Same. |
| `davison1997bootstrap` | Book, 1997 | Standard bootstrap reference, including hierarchical resampling. | Same. |

---

## Closest work: differentiation paragraphs

**1. Liu and Ming, "What Users See Is Not What Models Read" (`liu2027what`, to appear at IEEE S&P 2027).** This is the most direct competitor and must be discussed first. Liu and Ming characterize the attack surface: they enumerate 25 extraction gaps in four families (semantic overrides via /ToUnicode or /ActualText, hidden semantic injection via render mode, color, clipping, geometry and optional content, reading-order splits, and Type 3 or CID font-decoding splits), and measure which of 16 PDF processing stacks and 7 commercial LLM services expose each gap. Their unit of analysis is the (gap, pipeline) pair, and their defensive artifact is a rule-based static scanner, checked against benign academic PDFs and seven PDF-Prompt-Injection-Toolkit samples (it flagged five), with dual-view consistency proposed but not evaluated. CrackedPDFs asks a different question: given a pipeline, how well can a detector separate injected documents from benign documents that share the same base content and layout, and does the reported score survive held-out provenance splits and shortcut audits? CrackedPDFs contributes what Liu and Ming do not: a labeled corpus at scale (29,322 PDFs from 4,983 base documents), matched benign confounders, learned and rule baselines compared under the same protocol, and an evaluation methodology for detector claims. Conversely, Liu and Ming cover hiding mechanisms CrackedPDFs does not (reading-order splits, /ActualText overrides, and most font-decoding splits), and they test real commercial services end to end. The revision should present the two as complementary: their taxonomy as the attack-surface map, and CrackedPDFs as the detection benchmark, with a table mapping CrackedPDFs families onto their EG01 to EG25 identifiers.

**2. PhantomLint (`murray2025phantomlint`, arXiv 2025).** PhantomLint is a detector, not a benchmark. It filters text blocks for prompt-like phrases with sentence embeddings, then renders, crops, and OCRs each flagged block and reports words present in the text layer but absent from OCR output. Its evaluation is a 26-document synthetic set covering hiding techniques, a 3,257-document ICML 2025 corpus to estimate false positives (3 flagged, all OCR failures), and 119 web-collected documents of which only 6 are negatives. It therefore has no matched negatives: no benign documents that contain hidden-but-harmless content or visible prompt-like language, which are the cases where a phrase-gated, OCR-diff design would fail. CrackedPDFs supplies exactly those controls and can report PhantomLint's behavior on them. Two further differences matter for a fair comparison. First, PhantomLint's phrase gate means non-instruction payloads (the "data injections" that make up over 90% of real resume injections in `zhang2026measuring`, or TrapDoc-style phantom tokens) can pass unflagged by design. Second, its runtime (about 44 to 68 seconds per document on an M1 laptop) constrains how it can be run on a 2,919-document test split, which should be reported.

**3. Castagnaro et al., "The Hidden Threat in Plain Text" (`castagnaro2025hidden`, AISec 2025).** This paper measures the same ingestion gap from the attacker's side for RAG data loaders: 19 hiding techniques across DOCX, HTML, and PDF, five loaders, a 74.4% success rate over 357 scenarios, and end-to-end confirmation on hosted services. It does not build a detection benchmark, release labeled negatives, or evaluate detectors. CrackedPDFs is the detection-side counterpart for PDF, and the overlap in hiding techniques (zero-width characters, font poisoning, invisible text) should be tabulated. Its multi-format scope (DOCX and HTML) is broader than CrackedPDFs and should be acknowledged as a limitation of ours.

**4. Zhang et al., "Measuring Real-World Prompt Injection Attacks in LLM-based Resume Screening" (`zhang2026measuring`, to appear at USENIX Security 2026).** This is the only large real-world measurement of hidden injections in PDFs: about 1% of about 200k resumes, rising over 2024 to 2025, with more than 90% of payloads being data (inserted keywords or qualifications) rather than explicit instructions. It builds resume-specific detectors and reports that general-purpose detectors underperform. CrackedPDFs is synthetic and controlled, whereas Zhang et al. is observational and domain-specific; the two answer different questions (how detectors behave under controlled confounding, versus how common the attack is). The key implication for the revision is that CrackedPDFs' payloads should be described honestly relative to the real distribution: if CrackedPDFs payloads are predominantly instruction-shaped, a detector tuned on them may miss the dominant real-world class. ResumeShield (`barach2026resumeshield`) is the other resume-side benchmark, but at 104 synthetic documents it is far smaller and does not use matched confounders.

**5. Fomin (`fomin2026when`, ICLR 2026 workshop) and PIDS-Bench (`shire2026pidsbench`, IEEE Access 2026).** These are the closest methodological precedents, though neither involves documents. Fomin shows that same-source splits inflate AUC by 8.4 points and that 28% of top SAE features in injection classifiers are dataset-specific shortcuts, and proposes leave-one-dataset-out evaluation. PIDS-Bench shows that a detector above 0.98 F1 in distribution misclassifies about a third of external security-adjacent benign prompts, and that hard-negative augmentation fixes curated but not externally sourced over-defense. CrackedPDFs' provenance-held-out splits, matched confounders, and TF-IDF shortcut audit are the document-level version of the same argument. The revision should cite both as independent text-level confirmation, and frame CrackedPDFs' contribution as extending that methodology to a setting where the shortcut can live in the file structure or generator template rather than in the text.

Secondary close works worth one sentence each: TrapDoc (`jin2025trapdoc`) uses the same hiding primitives with non-instruction payloads; Luo et al. (`luo2026exploiting`) and Xiong et al. (`xiong2025invisible`) cover font glyph remapping; PDF Mirage (`markwood2017pdf`) is the 2017 origin of the rendered-versus-extracted gap and should be cited as such.

---

## Additional open-source baselines to run

Already run (per the revision plan): PhantomLint, wppoland/hidden-text-detector, Andy8647/pdf-injection-scanner, Llama Prompt Guard 2, ProtectAI deberta-v3 v2, deepset deberta-v3-base-injection, Horizon-Labs prompt-injection-guard.

| Tool | Repo / model | License | What it adds | Offline on macOS? |
|---|---|---|---|---|
| **PDF-Prompt-Injection-Toolkit** (detector and injector) | https://github.com/zhihuiyuze/PDF-Prompt-Injection-Toolkit | MIT | Seven-module PDF detector (invisible text, metadata, off-page, Unicode, hidden OCG, extraction comparison, regex). Its injector also gives an out-of-distribution attack set, and Liu and Ming used its samples as test inputs, so it links CrackedPDFs to their evaluation. | Yes (Python). Recommended first. |
| **OpenDataLoader PDF** | https://github.com/opendataloader-project/opendataloader-pdf | Apache-2.0 (v2.0 and later; earlier MPL-2.0) | A production extractor with default-on hidden-text, off-page, and hidden-layer filtering. Use it as a "sanitizing extractor" baseline: measure how much injected payload survives extraction. Liu and Ming evaluated it. | Yes; needs Java 11+ and Python 3.10+; states it runs fully locally. |
| **PIGuard** | https://huggingface.co/leolee99/PIGuard | MIT | Over-defense-aware DeBERTa-v3 classifier (ACL 2025). Directly tests whether over-defense mitigation helps on matched confounders. | Yes; requires `trust_remote_code=True`, so review the code. |
| **Render-plus-OCR differential (own implementation)** | Poppler `pdftoppm` + Tesseract, diff against pdfminer/PyMuPDF text | Tesseract Apache-2.0; Poppler GPL | Isolates the OCR-consistency principle without PhantomLint's phrase gate. Liu and Ming used Poppler plus Tesseract as their runtime reference (over 20 s per PDF). | Yes (Homebrew). |
| **Open-Prompt-Injection / DataSentinel** | https://github.com/liu00222/Open-Prompt-Injection | MIT | Strongest published text-level detector (IEEE S&P 2025). Checkpoint downloaded from Google Drive; base model appears to be Mistral-7B (unconfirmed). | Possible but heavy: 7B model, Apple-silicon MPS, slow on 2,919 documents. |
| **LLM Guard (PromptInjection scanner)** | https://github.com/protectai/llm-guard | MIT; archived 9 July 2026 | Wrapper used in practice and an optional PhantomLint detector. Likely redundant with ProtectAI v2 (default model not confirmed on the repo page). | Yes after model download. Low priority. |
| **AASA** | https://github.com/xxradar/aasa | MIT | PyMuPDF layer extraction (hidden text, metadata, annotations, forms, JavaScript, embedded files) plus 29+ regex patterns; `--static-only` disables the LLM judge. | Static mode should be offline; local-file input not documented (examples take URLs). Low priority. |
| **Meta Prompt-Guard-86M (v1)** | https://huggingface.co/meta-llama/Prompt-Guard-86M | Llama 3.1 Community License | Version comparison with Prompt Guard 2. | Yes after gated download. Optional. |
| **Qualifire Sentinel** | https://huggingface.co/qualifire/prompt-injection-sentinel | Custom ("other"), gated | ModernBERT-large classifier claiming state-of-the-art results. | Yes after gated download; check license before publishing results. Optional. |

Not runnable or not available: the Liu and Ming static scanner (no repository URL in the paper as of v2), Attention Tracker (code location and license not confirmed), the Zhang et al. resume detectors (artifacts at github.com/UNITES-Lab/resume-injection-measurement per the arXiv comment; not inspected).

---

## Unverified or caveated

- `liu2027what`, `zhou2026give`, `zhang2026measuring`: acceptance is stated only in the arXiv comment; no proceedings page yet.
- `collu2026misleading`: ACM TAISAP acceptance from arXiv comment; DOI 10.1145/3803804 did not resolve at time of check.
- `guo2026hidden`: WWW 2026 venue and DOI from arXiv metadata; DOI not found in Crossref at time of check.
- `perez2022ignore`: NeurIPS 2022 ML Safety Workshop venue commonly cited but not confirmed; second author's first name not confirmed.
- `li2026defenses`: first author listed as "Li Li" (ACL Anthology) and "Shawn Li" (arXiv).
- `deepset2023deberta`: year inferred.
- `murray2025phantomlint`: no peer-reviewed venue found; check again before camera-ready.
- Horizon-Labs prompt-injection-guard: I could not locate this model on Hugging Face by search. Make sure the paper gives the exact model ID and revision hash.
- "Zhou et al. 2026" in the revision plan was resolved to `zhou2026give` (Qin Zhou et al.). If a different Zhou paper was intended, it was not found.
- A Research Square preprint ("Labelled-Metadata Channels and Declarative Payload Phrasing in Hidden Prompt Injection: A Cross-Format Measurement Study") appeared in search, but its authors and date could not be retrieved, so it is not in the .bib.
