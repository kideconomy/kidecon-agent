.PHONY: help install test lint clean

VENV   = env
PYTHON = $(VENV)/bin/python
PIP    = $(VENV)/bin/pip

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

$(VENV)/bin/python:  ## Create virtual environment if missing
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

install: $(VENV)/bin/python  ## Install the kidecon CLI command
	$(PIP) install -e .

# ------------------------------------------------------------------
# Testing
# ------------------------------------------------------------------

test: install  ## Run tests
	$(PYTHON) -m pytest tests/ -v

# ------------------------------------------------------------------
# Quality
# ------------------------------------------------------------------

lint: install  ## Run linters (ruff)
	$(PYTHON) -m ruff check . --exclude 'env'
	$(PYTHON) -m ruff format --check . --exclude 'env'

format: install  ## Auto-format code with ruff
	$(PYTHON) -m ruff check --fix . --exclude 'env'
	$(PYTHON) -m ruff format . --exclude 'env'

# ------------------------------------------------------------------
# Clean
# ------------------------------------------------------------------

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf *.egg-info dist build

# ------------------------------------------------------------------
# Sync shared LLM clients from kidecon-hub (canonical source)
# ------------------------------------------------------------------

LLM_CLIENTS_CANONICAL = ../kidecon-hub/shared/llm_clients
LLM_CLIENTS_LOCAL = shared/llm_clients

.PHONY: sync-llm check-llm-sync

sync-llm:  ## Pull shared LLM library from kidecon-hub (canonical source)
	@echo "Syncing LLM client library from kidecon-hub..."
	@mkdir -p $(LLM_CLIENTS_LOCAL)
	@cp -r $(LLM_CLIENTS_CANONICAL)/* $(LLM_CLIENTS_LOCAL)/
	@echo "✓ Synced from kidecon-hub/shared/llm_clients/"

check-llm-sync:  ## Verify local copy matches canonical hub source
	@diff -rq $(LLM_CLIENTS_CANONICAL) $(LLM_CLIENTS_LOCAL) || \
		(echo "✗ LLM client library is out of sync. Run 'make sync-llm'" && exit 1)
