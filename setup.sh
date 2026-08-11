#!/usr/bin/env bash
# =============================================================================
# douyin-to-obsidian — One-click setup
# =============================================================================
# Usage: bash setup.sh
#
# This script:
#   1. Creates a Python virtual environment
#   2. Installs all dependencies
#   3. Downloads Whisper model (small, ~1GB)
#   4. Installs ffmpeg (via imageio-ffmpeg fallback)
#   5. Verifies everything works
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Darwin)  OS_NAME="macOS" ;;
    Linux)   OS_NAME="Linux" ;;
    MINGW*|MSYS*) OS_NAME="Windows" ;;
    *)       OS_NAME="$OS" ;;
esac

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║       douyin-to-obsidian  Setup          ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
info "Detected OS: $OS_NAME"
info "Root: $ROOT_DIR"
echo ""

# -------------------------------------------------------------------------
# Step 1: Check Python
# -------------------------------------------------------------------------
info "Step 1/5: Checking Python..."
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+' | head -1 || echo "0")
        if [ "$(echo "$VER >= 3.9" | bc 2>/dev/null || echo 0)" = "1" ] || [ "$VER" = "0" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    err "Python 3.9+ not found. Install it first: https://python.org"
    exit 1
fi
ok "$($PYTHON --version)"

# -------------------------------------------------------------------------
# Step 2: Create virtual environment
# -------------------------------------------------------------------------
info "Step 2/5: Creating virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created at $VENV_DIR"
else
    ok "Virtual environment already exists"
fi

# Activate
if [ "$OS_NAME" = "Windows" ]; then
    source "$VENV_DIR/Scripts/activate" 2>/dev/null || true
    PIP="$VENV_DIR/Scripts/pip"
    PY="$VENV_DIR/Scripts/python"
else
    source "$VENV_DIR/bin/activate" 2>/dev/null || true
    PIP="$VENV_DIR/bin/pip"
    PY="$VENV_DIR/bin/python"
fi

# -------------------------------------------------------------------------
# Step 3: Install Python dependencies
# -------------------------------------------------------------------------
info "Step 3/5: Installing Python dependencies..."
# Use PyPI mirror in China
if [ -n "${HF_ENDPOINT:-}" ]; then
    "$PIP" install -e "$ROOT_DIR" -i https://mirrors.aliyun.com/pypi/simple/
else
    "$PIP" install -e "$ROOT_DIR"
fi
"$PIP" install imageio-ffmpeg  # ffmpeg fallback
ok "Dependencies installed"

# -------------------------------------------------------------------------
# Step 4: Download Whisper model (small, ~1GB)
# -------------------------------------------------------------------------
info "Step 4/5: Downloading Whisper model (small)..."
if [ -n "${HF_ENDPOINT:-}" ]; then
    export HF_ENDPOINT="$HF_ENDPOINT"
fi
"$PY" -c "
from faster_whisper import WhisperModel
print('Downloading whisper small model (first run)...')
model = WhisperModel('small', device='auto', compute_type='default')
print('Model loaded successfully')
" 2>&1 | tail -5
ok "Whisper model ready"

# -------------------------------------------------------------------------
# Step 5: Verify
# -------------------------------------------------------------------------
info "Step 5/5: Verifying installation..."
"$PY" -c "
import requests, yt_dlp, faster_whisper, zhconv, json
from pathlib import Path
print('✅ Core deps: OK')
try:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    print(f'✅ ffmpeg: {ff}')
except Exception:
    print('⚠️  ffmpeg not found (can be installed later)')
# Test corrections
import douyin_to_obsidian.extract as e
c = e._load_corrections()
print(f'✅ Corrections: {len(c)} rules loaded')
"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║           Setup complete! 🎉             ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  You can now use the CLI:"
echo "    $PY $ROOT_DIR/scripts/douyin_extract.py <douyin_url>"
echo ""
echo "  Or (if installed via pip):"
echo "    douyin-extract <douyin_url>"
echo ""
echo "  For China users, set HF_ENDPOINT before running:"
echo "    export HF_ENDPOINT=https://hf-mirror.com"
echo ""