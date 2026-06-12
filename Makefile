.PHONY: setup check courseware-check lab-00 lab-03 lab-04 lab-06 lab-09 lab-01 lab-16

PYTHON ?= python3

setup:
	$(PYTHON) scripts/course.py setup

lab-00:
	$(PYTHON) scripts/course.py lab-00

lab-03:
	$(PYTHON) scripts/course.py lab-03

lab-04:
	$(PYTHON) scripts/course.py lab-04

lab-06:
	$(PYTHON) scripts/course.py lab-06

lab-09:
	$(PYTHON) scripts/course.py lab-09

lab-01:
	$(PYTHON) scripts/course.py lab-01

lab-16:
	$(PYTHON) scripts/course.py lab-16

courseware-check:
	$(PYTHON) scripts/course.py courseware-check

check:
	$(PYTHON) scripts/course.py check
