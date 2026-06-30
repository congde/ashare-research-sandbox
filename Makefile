.PHONY: setup check verify courseware-check teaching-plots

PYTHON ?= python3

setup:
	$(PYTHON) scripts/course.py setup

verify:
	$(PYTHON) scripts/course.py verify

courseware-check:
	$(PYTHON) scripts/course.py courseware-check

teaching-plots:
	$(PYTHON) scripts/course.py teaching-plots

check:
	$(PYTHON) scripts/course.py check
