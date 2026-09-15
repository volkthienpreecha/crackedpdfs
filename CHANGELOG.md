# Changelog

All notable changes to this repository are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dataset and paper releases are versioned separately from code; entries say which one they affect.

## [Unreleased]

### Fixed

- **Generator:** injection config resolution is idempotent. Paper v1 re-resolved configs in the ADA bridge, which turned page-relative regime anchors into absolute points and placed payloads at the bottom-left page corner, mostly below the page.
- **Generator:** the injector measures every emitted glyph against the visible page box and refuses to write a file whose geometry contradicts its `spatial_regime` label. In-page payloads are wrapped to fit, `header_footer_like` is labelled `near_margin`, and acrostics fit on one page.
- **Generator:** matched confounders carry the same validation marker and exactly the same payload length as the injected PDF, removing a string oracle and a length oracle present in paper v1.
- **Generator:** strong `in_page_split_text_objects` samples no longer fail validation because the marker was wrapped mid-token. Paper v1 contains none.
- **Tooling:** PyMuPDF is imported by its supported module name, so its deprecation warning no longer corrupts the smoke benchmark's JSON output.

### Added

- `tools/crackedpdfs-audit`: an independent placement and visibility audit (`file`, `reveal`, `corpus`) built on pdfminer.six and pypdfium2.
- Dataset manifests and benchmark records include measured placement (`realized_spatial_class`, glyph counts, contract verdict).
- CI: split jobs with a single required `CI ok` gate, SHA-pinned actions, concurrency cancellation, ruff, actionlint, zizmor, CodeQL, and Dependabot.
- Retrying, backoff-aware artifact downloads in `scripts/reproduce_results.py`.
- Community health files: `SECURITY.md`, `SUPPORT.md`, issue and pull request templates, and `CODEOWNERS`.

## [1.0.0] - 2026-08-01

### Added

- Paper v1 release: 29,322 PDFs, frozen grouped splits, metrics, and reproducibility metadata ([Zenodo DOI 10.5281/zenodo.21735803](https://doi.org/10.5281/zenodo.21735803), [arXiv 2607.19396](https://arxiv.org/abs/2607.19396)).
- `make smoke` and `make reproduce-results` release checks.

[Unreleased]: https://github.com/volkthienpreecha/crackedpdfs/compare/fb63233...HEAD
[1.0.0]: https://github.com/volkthienpreecha/crackedpdfs/commit/fb63233
