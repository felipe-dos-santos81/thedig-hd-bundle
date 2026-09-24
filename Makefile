PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin

$(VENV)/bin/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -e ".[dev]"

.PHONY: check oracle verify
check: $(VENV)/bin/python
	$(BIN)/pytest

oracle:
	bash vendor/san-oracle/build.sh

verify: check oracle
	$(BIN)/python tools/diff_oracle.py
