# Security policy

CrackedPDFs ships two kinds of security-relevant material: code that parses untrusted PDFs, and a generator that deliberately produces PDFs carrying hidden prompt-injection payloads. This policy covers both.

## Supported versions

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Paper v1 release (`paper-v1/`, Hugging Face revision `245bc98`) | Frozen research record. Security fixes land on `main`; the frozen record is corrected by documented errata, never rewritten in place. |

## Reporting a vulnerability

Email **volk_thienpreecha@berkeley.edu** with:

- a description of the issue and its impact;
- reproduction steps, including the affected commit and any input files; and
- whether you plan to disclose publicly, and when.

Please do not open a public issue for vulnerabilities. We aim to acknowledge reports within 5 business days and to agree on a disclosure date within 30 days. We will credit reporters who want to be credited.

## In scope

- Memory-safety, denial-of-service, or code-execution issues triggered by feeding a PDF to repository code (the audit tool, feature extractors, validation harness, or generator).
- Secrets, credentials, or private paths committed to the repository or release artifacts.
- Supply-chain issues in CI workflows, pinned actions, or published packages.
- Integrity issues in release artifacts: a published file whose SHA-256 does not match its manifest.

## Out of scope

- The injected PDFs themselves. They contain prompt-injection payloads by design, and that is the point of the benchmark.
- Label, split, or metadata errors. These are important but not vulnerabilities; please use the **Dataset or label issue** template so the report stays public and citable.
- Detector evasion. A new attack that fools the lightweight detector is a research result; open a proposal or contact the authors.

## Responsible use

The injection generator exists to build and evaluate defenses. Do not use it, or the published corpus, to attack systems, models, or people without authorization. When processing PDFs from untrusted sources, including this corpus, run the tooling in an isolated environment.
