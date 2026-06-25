#!/bin/bash
#
# Whisper Transcriber — setup / repair script.
# Double-click to install or update everything. Safe to run more than once.
# The .app launcher also calls this automatically on first launch.
#
set -e

# --relaunch: silently re-open the app after setup (used by auto-setup flow)
RELAUNCH=0
for arg in "$@"; do [ "$arg" = "--relaunch" ] && RELAUNCH=1; done

echo "==================================================="
echo "  Whisper Transcriber — Setup"
echo "==================================================="
echo ""

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
WHISPER_DIR="$HOME/Whisper"
mkdir -p "$WHISPER_DIR"

# --- 1. Homebrew -------------------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
    echo "✗ Homebrew is not installed (it's a required prerequisite)."
    echo "  Install it from https://brew.sh, then double-click this setup again."
    echo ""
    read -n 1 -s -r -p "Press any key to close."
    exit 1
fi

# --- 2. Python (with modern Tk) + ffmpeg ------------------------------------
echo "→ Installing Python (python-tk) and ffmpeg via Homebrew…"
echo "  (this is quick if they're already installed)"
brew install python-tk ffmpeg || true
echo ""

# locate a modern Homebrew Python
PYTHON=""
for c in /opt/homebrew/bin/python3.14 \
         /opt/homebrew/bin/python3.13 \
         /opt/homebrew/bin/python3.12 ; do
    if [ -x "$c" ]; then PYTHON="$c"; break; fi
done
if [ -z "$PYTHON" ]; then
    echo "✗ Could not find a Homebrew Python after install."
    read -n 1 -s -r -p "Press any key to close."
    exit 1
fi
echo "→ Using Python: $PYTHON"
echo ""

# --- 3. Virtual environment + mlx-whisper -----------------------------------
if [ ! -d "$WHISPER_DIR/venv" ]; then
    echo "→ Creating virtual environment…"
    "$PYTHON" -m venv "$WHISPER_DIR/venv"
else
    echo "→ Virtual environment already exists — skipping."
fi
echo "→ Installing / updating mlx-whisper…"
"$WHISPER_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$WHISPER_DIR/venv/bin/pip" install --upgrade mlx-whisper
echo ""

# --- 4. Place app files in ~/Whisper (predictable launcher paths) -----------
if [ "$SRC_DIR" != "$WHISPER_DIR" ]; then
    echo "→ Installing app files into $WHISPER_DIR…"
    for f in whisper_transcriber.py setup.command launch.command ; do
        if [ -f "$SRC_DIR/$f" ]; then
            cp "$SRC_DIR/$f" "$WHISPER_DIR/"
        fi
    done
fi
chmod +x "$WHISPER_DIR/setup.command" "$WHISPER_DIR/launch.command" 2>/dev/null || true

echo ""
echo "==================================================="
echo "  ✓ Setup complete!"
echo ""
echo "  Open the Whisper Transcriber app, or double-click"
echo "  launch.command, to start transcribing."
echo "==================================================="
echo ""

if [ "$RELAUNCH" = "1" ]; then
    echo "→ Launching Whisper Transcriber…"
    sleep 1
    open -a "Whisper Transcriber"
else
    read -n 1 -s -r -p "Press any key to close."
fi
