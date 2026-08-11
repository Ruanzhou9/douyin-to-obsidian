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

# Quick test
test:
	.venv/bin/python3 -c "
import requests, yt_dlp, zhconv, json
from pathlib import Path
print('All core deps: OK')
try:
	import imageio_ffmpeg
	print(f'ffmpeg: {imageio_ffmpeg.get_ffmpeg_exe()}')
except:
	print('ffmpeg: not found')
import douyin_to_obsidian.extract as e
c = e._load_corrections()
print(f'Corrections: {len(c)} rules')
"

# Clean temp files
clean:
	rm -rf .venv/ douyin_output/ *.egg-info/ __pycache__/
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete

# Extract a douyin link
extract:
	@.venv/bin/python3 scripts/douyin_extract.py $(URL)