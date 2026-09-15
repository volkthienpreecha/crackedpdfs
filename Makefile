PYTHON ?= python3.13
VENV ?= .venv-paper
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV_PYTHON) -m pip
ARTIFACT_DIR ?= .cache/crackedpdfs-paper-v1
RESULTS_DIR ?= reproduced-results
DOWNLOAD_MANIFEST ?= paper-v1/reproducibility/download-manifest.json
INJECTOR_DIR := src/backend/services/processing/layers/02-watermarking/volks-pdf-blocker-ada-layer-1
RUFF_LINT_PATHS := tools/crackedpdfs-audit scripts/reproduce_results.py scripts/verify_source_snapshot.py \
	scripts/smoke_benchmark.py tests $(INJECTOR_DIR)/test_placement_contract.py
RUFF_FORMAT_PATHS := tools/crackedpdfs-audit $(INJECTOR_DIR)/test_placement_contract.py
TS_TESTS := src/lib/prompt-injection-message-library.test.ts \
	src/backend/services/dataset-mode/index.test.ts \
	src/backend/services/processing/layers/02-watermarking/injection-config.contract.test.ts

.PHONY: help check-python deps verify-source test-python test-ts typecheck lint smoke \
	reproduce-results clean-reproduction

help:
	@echo "make smoke              verify the frozen source, then run every Python and TypeScript test"
	@echo "make verify-source      check the byte-exact May 25 detector snapshot"
	@echo "make test-python        generator, injector placement, audit tool, and release tests"
	@echo "make test-ts            TypeScript resolver, dataset-mode, and contract tests"
	@echo "make typecheck          tsc --noEmit over the TypeScript project"
	@echo "make lint               ruff over the maintained Python tooling"
	@echo "make reproduce-results  download hash-pinned artifacts and rebuild the paper table"

check-python:
	@$(PYTHON) -c "import sys; assert sys.version_info[:2] == (3, 13), 'CrackedPDFs requires Python 3.13, got ' + sys.version.split()[0]"

$(VENV)/.smoke-deps: tools/PDFautogenerator/pyproject.toml tools/crackedpdfs-audit/pyproject.toml Makefile
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -e tools/PDFautogenerator -e tools/crackedpdfs-audit pytest pikepdf pdfminer.six ruff
	@touch $@

node_modules/.paper-smoke-deps: package-lock.json
	npm ci
	@touch $@

deps: check-python $(VENV)/.smoke-deps

verify-source: deps
	$(VENV_PYTHON) scripts/verify_source_snapshot.py

test-python: deps
	$(VENV_PYTHON) -m pytest -q tests/test_release_workflow.py tools/PDFautogenerator/tests
	$(VENV_PYTHON) -m pytest -q tools/crackedpdfs-audit/tests
	$(VENV_PYTHON) -m pytest -q $(INJECTOR_DIR)/test_placement_contract.py \
		$(INJECTOR_DIR)/test_structural_placement.py $(INJECTOR_DIR)/test_validation_harness.py

test-ts: deps node_modules/.paper-smoke-deps
	PYTHON_BIN=$(VENV_PYTHON) npx --yes tsx --test $(TS_TESTS)

typecheck: node_modules/.paper-smoke-deps
	npx tsc --noEmit -p tsconfig.json

lint: deps
	$(VENV_PYTHON) -m ruff check $(RUFF_LINT_PATHS)
	$(VENV_PYTHON) -m ruff format --check $(RUFF_FORMAT_PATHS)

smoke: verify-source test-python test-ts

reproduce-results: check-python
	$(PYTHON) scripts/verify_source_snapshot.py
	$(PYTHON) scripts/reproduce_results.py \
		--artifact-dir $(ARTIFACT_DIR) \
		--manifest $(DOWNLOAD_MANIFEST) \
		--output-dir $(RESULTS_DIR)

clean-reproduction:
	$(PYTHON) -c "import shutil; [shutil.rmtree(path, ignore_errors=True) for path in ('$(ARTIFACT_DIR)', '$(RESULTS_DIR)')]"
