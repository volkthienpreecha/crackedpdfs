# Contributing to CrackedPDFs

CrackedPDFs is a security benchmark. Changes must preserve provenance, paired evaluation, and narrow claim boundaries.

## Before opening a change

Open an issue before making a large change to the dataset schema, attack taxonomy, split logic, metric definitions, or paper-facing claims. Small fixes to documentation, tests, and reproducibility metadata can go straight to a pull request.

Do not commit:

- generated PDFs outside a reviewed example bundle;
- local databases, feature tables, model binaries, or logs;
- access tokens, `.env` files, machine credentials, or private paths not already present in a frozen provenance record; or
- results that cannot be traced to a command, configuration, split, and source commit.

## Development setup

The paper release uses Python 3.13 and Node.js 22. On Linux:

```bash
git clone https://github.com/volkthienpreecha/crackedpdfs.git
cd crackedpdfs
make smoke
make reproduce-results
```

The smoke target runs the generator, source-integrity, and TypeScript checks. The reproduction target downloads hash-pinned frozen features and regenerates the compact result table without rebuilding the PDF corpus.

`make help` lists every target. CI runs the same targets as separate jobs:

| Target | What it checks |
| --- | --- |
| `make verify-source` | The May 25 detector snapshot is byte-exact. |
| `make test-python` | Generator, injector placement contract, audit tool, and release scripts. |
| `make test-ts` | Injection config resolver, dataset mode, and the TypeScript/Python config contract. |
| `make typecheck` | `tsc --noEmit` over the TypeScript project. |
| `make lint` | Ruff over maintained Python tooling. Install [pre-commit](https://pre-commit.com) to run it on every commit. |
| `make reproduce-results` | Rebuilds the paper table from hash-pinned artifacts. |

For focused Python generator tests on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\tools\PDFautogenerator
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest .\tools\PDFautogenerator\tests
```

For TypeScript tests on Windows PowerShell:

```powershell
npm install
npx --yes tsx --test `
  src/lib/prompt-injection-message-library.test.ts `
  src/backend/services/dataset-mode/index.test.ts `
  src/backend/services/processing/layers/02-watermarking/injection-config.contract.test.ts
```

## Generator changes

The generator writes labels that detectors are scored against, so a label must describe the file.

- Keep `resolveInjectionConfig` idempotent. The contract tests resolve every regime combination twice.
- Never bypass the injector's placement contract. In regime mode it measures every glyph and raises `PlacementContractError` rather than writing a mislabelled PDF.
- Keep matched confounders matched on everything except the instruction: placement, marker line, and payload length.
- Before publishing a regenerated corpus, run `crackedpdfs-audit corpus` over it and include the summary in the release notes.

## Pull request rules

Keep pull requests small and focused. For a change that builds on another open pull request, open a stacked pull request and say which one it depends on. Merge stacks bottom-up with ordinary merge commits (not squash and not rebase merge): squash and rebase rewrite commit identities, which strands the commits the upper pull requests still reference.

Write commit subjects in the imperative mood ("Add", "Fix", "Record"), under about 72 characters, and use the body to explain why.

A pull request should state:

1. what changed;
2. why the change is needed;
3. which benchmark claims or artifacts it can affect;
4. the exact validation commands run; and
5. whether any generated output changed.

If results change, include the old and new split identifiers, metrics, confusion matrices, paired-control results, shortcut audits, and the source commit used to create them.

Do not describe a balanced paired-set classification score as a ranking score. Keep metric names aligned with the artifact fields that produced them.

## Paper artifact changes

Files under `paper-v1/` are a frozen research record. Change them only to:

- correct a documented error;
- add missing provenance without altering the underlying result; or
- publish a clearly versioned replacement.

Never overwrite a frozen split or metric file in place and keep the same version label. Add a new versioned directory instead.

## Reporting dataset and label errors

If a label, split, or release file does not match what a PDF contains, open a [Dataset or label issue](https://github.com/volkthienpreecha/crackedpdfs/issues/new?template=dataset-issue.yml) with the affected `pdf_id` values and measured evidence. `crackedpdfs-audit file <pdf> --reference <original> --label <label>` produces a report you can paste.

## Reporting security issues

Follow [`SECURITY.md`](SECURITY.md). Do not open a public issue for a vulnerability.

## Conduct

By participating, you agree to follow [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
