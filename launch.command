#!/bin/bash
#
# Whisper Transcriber — direct launcher (source-install path).
# Runs the GUI straight from the venv, skipping the .app bundle entirely.
# Requires a prior setup (setup.command, or any first launch of the .app).
#
VENV_PY="$HOME/Whisper/venv/bin/python"
APP="$HOME/Whisper/whisper_transcriber.py"

if [ ! -x "$VENV_PY" ] || [ ! -f "$APP" ]; then
    echo "Whisper Transcriber isn't set up yet."
    echo "Please double-click  setup.command  first."
    echo ""
    read -n 1 -s -r -p "Press any key to close."
    exit 1
fi

exec "$VENV_PY" "$APP"
