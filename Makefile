PYTHON ?= python3.13
VENV ?= .venv-paper
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV_PYTHON) -m pip
ARTIFACT_DIR ?= .cache/crackedpdfs-paper-v1
RESULTS_DIR ?= reproduced-results
DOWNLOAD_MANIFEST ?= paper-v1/reproducibility/download-manifest.json
INJECTOR_DIR := src/backend/services/processing/layers/02-watermarking/volks-pdf-blocker-ada-layer-1

.PHONY: check-python smoke reproduce-results clean-reproduction

check-python:
	@$(PYTHON) -c "import sys; assert sys.version_info[:2] == (3, 13), 'CrackedPDFs requires Python 3.13, got ' + sys.version.split()[0]"

$(VENV)/.smoke-deps: tools/PDFautogenerator/pyproject.toml tools/crackedpdfs-audit/pyproject.toml Makefile
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -e tools/PDFautogenerator -e tools/crackedpdfs-audit pytest pikepdf pdfminer.six
	@touch $@

node_modules/.paper-smoke-deps: package-lock.json
	npm ci
	@touch $@

smoke: check-python $(VENV)/.smoke-deps node_modules/.paper-smoke-deps
	$(VENV_PYTHON) scripts/verify_source_snapshot.py
	$(VENV_PYTHON) -m pytest tests/test_release_workflow.py tools/PDFautogenerator/tests -q
	$(VENV_PYTHON) -m pytest tools/crackedpdfs-audit/tests -q
	$(VENV_PYTHON) -m pytest -q $(INJECTOR_DIR)/test_placement_contract.py \
		$(INJECTOR_DIR)/test_structural_placement.py $(INJECTOR_DIR)/test_validation_harness.py
	PYTHON_BIN=$(VENV_PYTHON) npx --yes tsx --test \
		src/lib/prompt-injection-message-library.test.ts \
		src/backend/services/dataset-mode/index.test.ts \
		src/backend/services/processing/layers/02-watermarking/injection-config.contract.test.ts

reproduce-results: check-python
	$(PYTHON) scripts/verify_source_snapshot.py
	$(PYTHON) scripts/reproduce_results.py \
		--artifact-dir $(ARTIFACT_DIR) \
		--manifest $(DOWNLOAD_MANIFEST) \
		--output-dir $(RESULTS_DIR)

clean-reproduction:
	$(PYTHON) -c "import shutil; [shutil.rmtree(path, ignore_errors=True) for path in ('$(ARTIFACT_DIR)', '$(RESULTS_DIR)')]"
