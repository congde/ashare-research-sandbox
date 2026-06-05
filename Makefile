.PHONY: setup check test challenge-001 challenge-002 challenge-003 \
        challenge-004 challenge-005 challenge-006 challenge-graduation \
        harness-check

PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	@echo "✓ setup complete"

test:
	$(BIN)/pytest app/tests -q

check: test
	@bash scripts/check.sh

harness-check:
	@bash harness-kit/scripts/verify.sh

challenge-001:
	@bash challenges/001-hotfix/check.sh

challenge-002:
	@bash challenges/002-explore/check.sh

challenge-003:
	@bash challenges/003-bugfix/check.sh

challenge-004:
	@bash challenges/004-feature-pr/check.sh

challenge-005:
	@bash challenges/005-review/check.sh

challenge-006:
	@bash challenges/006-ci-autofix/check.sh

challenge-graduation:
	@bash challenges/graduation/check.sh
