.PHONY: setup check verify courseware-check

PYTHON ?= python3

setup:
	$(PYTHON) scripts/course.py setup

verify:
	$(PYTHON) scripts/course.py verify

courseware-check:
	$(PYTHON) scripts/course.py courseware-check

check:
	$(PYTHON) scripts/course.py check
