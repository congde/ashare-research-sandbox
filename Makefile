.PHONY: setup check courseware-check lab-01 lab-16

PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	@echo "✓ setup complete"

lab-01:
	@bash labs/01-first-ticket/verify.sh

lab-16:
	$(BIN)/python skills/repo-readiness/scripts/verify_report.py \
		labs/16-repo-readiness-skill/sample-report.md

courseware-check:
	$(BIN)/python scripts/verify_courseware.py

check: lab-01 lab-16 courseware-check
	@echo "All courseware checks passed."
