.PHONY: setup check courseware-check lab-00 lab-04 lab-09 lab-01 lab-16

PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	@echo "✓ setup complete"

lab-00:
	$(BIN)/python labs/00-assistant-brief/verify.py

lab-04:
	$(BIN)/python labs/04-research/verify.py

lab-09:
	$(BIN)/python skills/weekly-brief/scripts/verify_report.py \
		labs/09-weekly-brief-skill/sample-report.md

lab-01:
	@bash labs/01-first-ticket/verify.sh

lab-16:
	$(BIN)/python skills/repo-readiness/scripts/verify_report.py \
		labs/16-repo-readiness-skill/sample-report.md

courseware-check:
	$(BIN)/python scripts/verify_courseware.py

check: lab-00 lab-04 lab-09 lab-01 lab-16 courseware-check
	@echo "All courseware checks passed."
