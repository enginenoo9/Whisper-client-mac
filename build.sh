#!/bin/bash
#
# build.sh — Build a fully standalone Whisper Transcriber.app and DMG.
#
# Requirements (run once):
#   brew install python-tk ffmpeg
#
# Usage:
#   chmod +x build.sh
#   ./build.sh
#
# Output:
#   dist/Whisper Transcriber.app   — standalone .app (drag to /Applications)
#   dist/Whisper-Transcriber-2.0.dmg  — installer DMG ready to share
#
set -euo pipefail

VERSION="2.0"
APP_NAME="Whisper Transcriber"
DMG_NAME="Whisper-Transcriber-${VERSION}"

echo "==================================================="
echo "  ${APP_NAME} — Standalone Build v${VERSION}"
echo "==================================================="
echo ""

# ── 1. Locate Homebrew Python (must have tkinter) ────────────────────────────
PYTHON=""
for c in \
    /opt/homebrew/bin/python3.14 \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3.12 \
    /usr/local/bin/python3.14 \
    /usr/local/bin/python3.13 \
    /usr/local/bin/python3.12; do
    if [ -x "$c" ]; then
        # Confirm tkinter works with this Python
        if "$c" -c "import tkinter" 2>/dev/null; then
            PYTHON="$c"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "✗ No Homebrew Python with tkinter found."
    echo "  Fix: brew install python-tk"
    exit 1
fi
echo "→ Python: $PYTHON ($("$PYTHON" --version))"

# ── 2. Install / update build + runtime deps ─────────────────────────────────
echo "→ Installing Python dependencies…"
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet --upgrade py2app
"$PYTHON" -m pip install --quiet --upgrade mlx-whisper huggingface_hub
echo "  Done."
echo ""

# ── 3. Stage ffmpeg binary ────────────────────────────────────────────────────
echo "→ Staging ffmpeg for bundling…"
mkdir -p bin

FFMPEG_SRC=""
for cand in \
    "$(brew --prefix 2>/dev/null)/bin/ffmpeg" \
    /opt/homebrew/bin/ffmpeg \
    /usr/local/bin/ffmpeg; do
    if [ -x "$cand" ]; then
        FFMPEG_SRC="$cand"
        break
    fi
done

if [ -z "$FFMPEG_SRC" ]; then
    echo "  ffmpeg not found — installing via Homebrew…"
    brew install ffmpeg
    FFMPEG_SRC="$(brew --prefix)/bin/ffmpeg"
fi

cp "$FFMPEG_SRC" bin/ffmpeg
echo "  Staged: $FFMPEG_SRC → bin/ffmpeg"
echo ""

# ── 4. Clean previous build ───────────────────────────────────────────────────
echo "→ Cleaning previous build artifacts…"
rm -rf build dist
echo ""

# ── 5. Build the .app with py2app ─────────────────────────────────────────────
echo "→ Building .app (this takes several minutes)…"
"$PYTHON" setup_py2app.py py2app 2>&1
echo ""

# ── 6. Verify the app was created ────────────────────────────────────────────
if [ ! -d "dist/${APP_NAME}.app" ]; then
    echo "✗ Build failed — dist/${APP_NAME}.app not found."
    exit 1
fi

# ── 7. Ad-hoc code sign ───────────────────────────────────────────────────────
# An ad-hoc signature satisfies Gatekeeper on the build machine and lets the
# app run on the same machine. Recipients on other Macs will need to
# right-click → Open on first launch (or you can pay for an Apple Developer ID).
echo "→ Signing .app (ad-hoc)…"
if codesign --force --deep --sign - "dist/${APP_NAME}.app" 2>/dev/null; then
    echo "  Signed."
else
    echo "  (codesign not available — skipping; app will require right-click → Open)"
fi
echo ""

# ── 8. Create the DMG ────────────────────────────────────────────────────────
echo "→ Creating DMG…"

STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

cp -r "dist/${APP_NAME}.app" "$STAGING/"
# /Applications symlink lets users drag-to-install in Finder
ln -s /Applications "$STAGING/Applications"

hdiutil create \
    -volname "${APP_NAME}" \
    -srcfolder "$STAGING" \
    -ov \
    -format UDZO \
    "dist/${DMG_NAME}.dmg"

echo ""
echo "==================================================="
echo "  ✓ Build complete!"
echo ""
echo "  App : dist/${APP_NAME}.app"
echo "  DMG : dist/${DMG_NAME}.dmg"
echo ""
echo "  To distribute:"
echo "    Share the DMG. Recipients open it and drag"
echo "    '${APP_NAME}' to the Applications folder."
echo "    No Python, Homebrew, or setup required."
echo ""
echo "  First-launch note:"
echo "    macOS may show 'unidentified developer'."
echo "    Right-click the app → Open → Open to bypass"
echo "    (needed only once, unless you sign with an"
echo "    Apple Developer ID certificate)."
echo "==================================================="

# Clean up staged ffmpeg — don't commit the binary
rm -f bin/ffmpeg
rmdir bin 2>/dev/null || true
