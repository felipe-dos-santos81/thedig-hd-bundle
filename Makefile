# Makefile for thedig-textures — extract every texture from GOG's The Dig
# Targets:
#   install → check → oracle → verify
SERVICE = thedig-textures

# Variables
VENV   = .venv
BIN    = $(VENV)/bin
PY     ?= python3
PYTHON = $(BIN)/python
PIP    = $(BIN)/pip

.PHONY: help install check oracle verify clean

# ── Environment ──────────────────────────────────────────────────────────────

help: ## Print this help message
	@printf '\033[01;32m${SERVICE} — The Dig texture extraction\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install the package with dev dependencies
	@if [ ! -d "$(VENV)" ]; then \
		$(PY) -m venv $(VENV); \
		$(PIP) install -U pip; \
		$(PIP) install -e ".[dev]"; \
	fi

clean: ## Remove the venv and all caches
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +

# ── Verification ─────────────────────────────────────────────────────────────

check: install ## Run the unit test suite (game-marked tests deselected)
	$(PYTHON) -m pytest

oracle: ## Build the vendored C++ codec-37 reference oracle
	bash vendor/san-oracle/build.sh

verify: check oracle ## check + oracle + byte-exact 55-file SAN differential
	$(PYTHON) tools/diff_oracle.py
