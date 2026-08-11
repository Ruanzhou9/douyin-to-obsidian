.PHONY: setup install test clean

# Detect OS
UNAME_S := $(shell uname -s)

# Python
PYTHON := python3

# Setup: one-command install
setup:
	@bash setup.sh

# Install deps only (faster, skip model download)
install:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -e .
	.venv/bin/pip install imageio-ffmpeg
	@echo "Run 'source .venv/bin/activate' to activate"

# Quick sanity test. Uses env var PYTHON if set, else the interpreter that has the deps.
PY ?= python3

test:
	$(PY) -c "import sys; sys.path.insert(0, '.'); \
import douyin_to_obsidian.extract as e; \
import douyin_to_obsidian.browser_fallback as bf; \
print('extract import: OK'); \
print('browser_fallback import: OK'); \
c = e._load_corrections(); \
print(f'corrections: {len(c)} definite + {len(e._AMBIGUOUS)} ambiguous'); \
print('test: PASS')"

# Clean temp files
clean:
	rm -rf .venv/ douyin_output/ *.egg-info/ __pycache__/
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete

# Extract a douyin link
extract:
	@.venv/bin/python3 scripts/douyin_extract.py $(URL)