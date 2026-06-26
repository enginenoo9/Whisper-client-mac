#!/bin/bash
#
# Whisper Transcriber — launcher.
# Opens the app using the virtual environment created by setup.command.
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
