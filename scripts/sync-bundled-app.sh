#!/bin/bash
#
# sync-bundled-app.sh — keep the app bundle's copy of the GUI in sync.
#
# The .app launcher copies Contents/Resources/whisper_transcriber.py over
# ~/Whisper on every launch, so that bundled copy must match the canonical
# top-level whisper_transcriber.py. Run this after editing the top-level file.
#
# Usage:  ./scripts/sync-bundled-app.sh           # copy top-level → bundle
#         ./scripts/sync-bundled-app.sh --check    # exit 1 if they differ
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/whisper_transcriber.py"
DST="$ROOT/Whisper Transcriber.app/Contents/Resources/whisper_transcriber.py"

if [ ! -f "$SRC" ]; then
    echo "✗ Missing $SRC" >&2
    exit 2
fi
if [ ! -f "$DST" ]; then
    echo "✗ Missing $DST" >&2
    exit 2
fi

if [ "${1:-}" = "--check" ]; then
    if diff -q "$SRC" "$DST" >/dev/null; then
        echo "✓ Bundled app copy is in sync."
        exit 0
    fi
    echo "✗ Bundled app copy is OUT OF SYNC with whisper_transcriber.py." >&2
    echo "  Fix it with:  ./scripts/sync-bundled-app.sh" >&2
    exit 1
fi

cp "$SRC" "$DST"
echo "✓ Synced bundled app copy ← whisper_transcriber.py"
