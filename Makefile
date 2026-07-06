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
