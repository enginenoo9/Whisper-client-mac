#!/bin/bash
#
# build-dmg.sh — Build a standalone, drag-to-install Whisper Transcriber.dmg.
#
# Bundles a real Python.framework (from python.org) and a static ffmpeg
# binary directly into the .app, so the *build machine* needs Homebrew and
# internet access, but the *end user* needs neither — no Homebrew, no
# separate Python install, no Terminal popup on first launch.
#
# mlx-whisper itself still can't be statically bundled: it's a namespace
# package with runtime Metal shader compilation that breaks every static
# bundler (this project tried py2app previously — see git history for
# "Remove standalone DMG / py2app build path"). So mlx-whisper is still
# installed into a private venv the first time the app runs, just seeded
# from the bundled Python instead of a Homebrew one.
#
# Requirements to BUILD this DMG (not to run the resulting app):
#   - macOS with Xcode Command Line Tools (for codesign)
#   - Homebrew, with ffmpeg installed (`brew install ffmpeg`)
#   - Internet access, to download the official python.org installer
#
# Usage:
#   chmod +x build-dmg.sh
#   ./build-dmg.sh
#
# Output:
#   dist/Whisper Transcriber.app
#   dist/Whisper-Transcriber-<version>.dmg
#
set -euo pipefail

VERSION="3.0"
APP_NAME="Whisper Transcriber"
DMG_NAME="Whisper-Transcriber-${VERSION}"

# Bump this to pick up a newer Python. Must be a released "macOS 64-bit
# universal2 installer" build — check https://www.python.org/downloads/macos/
PYTHON_VERSION="3.12.8"
PYTHON_PKG_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-macos11.pkg"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$ROOT_DIR/.build-dmg"
DIST_DIR="$ROOT_DIR/dist"

echo "==================================================="
echo "  ${APP_NAME} — DMG Build v${VERSION}"
echo "==================================================="
echo ""

# ── 0. Preflight ──────────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
    echo "✗ This script must run on macOS (needs pkgutil, hdiutil, codesign)."
    exit 1
fi
if ! command -v brew >/dev/null 2>&1; then
    echo "✗ Homebrew is required at build time (for ffmpeg). Install from https://brew.sh"
    exit 1
fi
if ! command -v codesign >/dev/null 2>&1; then
    echo "✗ codesign not found — install Xcode Command Line Tools:"
    echo "    xcode-select --install"
    exit 1
fi

rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR"
trap 'rm -rf "$BUILD_DIR"' EXIT

# ── 1. Stage a fresh copy of the committed .app bundle ───────────────────────
echo "→ Staging app bundle…"
APP_SRC="$ROOT_DIR/${APP_NAME}.app"
APP_DST="$DIST_DIR/${APP_NAME}.app"
if [ ! -d "$APP_SRC" ]; then
    echo "✗ '${APP_SRC}' not found."
    exit 1
fi
cp -R "$APP_SRC" "$APP_DST"
# Make sure the bundled script matches the canonical top-level source.
cp "$ROOT_DIR/whisper_transcriber.py" "$APP_DST/Contents/Resources/whisper_transcriber.py"

FRAMEWORKS_DIR="$APP_DST/Contents/Frameworks"
RESOURCES_DIR="$APP_DST/Contents/Resources"
mkdir -p "$FRAMEWORKS_DIR" "$RESOURCES_DIR/bin"

# ── 2. Download + verify the official python.org installer ──────────────────
PKG_PATH="$BUILD_DIR/python.pkg"
echo "→ Downloading Python ${PYTHON_VERSION} from python.org…"
curl -fL --progress-bar -o "$PKG_PATH" "$PYTHON_PKG_URL"

echo "→ Verifying Apple code signature on the installer…"
if ! pkgutil --check-signature "$PKG_PATH" | grep -q "Status: signed"; then
    echo "✗ python.org installer signature could not be verified — aborting."
    echo "  Do not proceed with an unsigned/tampered installer."
    exit 1
fi
echo "  Signature OK."

# ── 3. Extract Python.framework from the pkg (no system install) ────────────
# The installer is a "distribution" package wrapping several component
# sub-packages (framework, docs, IDLE, ...). `pkgutil --expand-full` is
# supposed to recurse into those and decompress their payloads, but that
# behavior is inconsistent across macOS versions. Do it manually instead:
# expand just the outer shell, find the framework sub-package, and
# decompress its Payload (a gzip'd cpio archive) directly — this is the
# same technique long-standing tools like relocatable-python use.
echo "→ Extracting Python.framework…"
EXPAND_DIR="$BUILD_DIR/pkg-expanded"
pkgutil --expand "$PKG_PATH" "$EXPAND_DIR"

FRAMEWORK_SUBPKG="$EXPAND_DIR/Python_Framework.pkg"
if [ ! -d "$FRAMEWORK_SUBPKG" ]; then
    # Sub-package name has varied across releases — fall back to a search
    # by identifier instead of assuming an exact directory name.
    for d in "$EXPAND_DIR"/*.pkg; do
        if [ -f "$d/PackageInfo" ] && grep -qi "pythonframework" "$d/PackageInfo"; then
            FRAMEWORK_SUBPKG="$d"
            break
        fi
    done
fi

if [ ! -d "$FRAMEWORK_SUBPKG" ] || [ ! -f "$FRAMEWORK_SUBPKG/Payload" ]; then
    echo "✗ Could not locate the PythonFramework component package inside the installer."
    echo "  Contents of $EXPAND_DIR:"
    ls "$EXPAND_DIR"
    exit 1
fi
echo "  Found: $(basename "$FRAMEWORK_SUBPKG")"

PAYLOAD_DIR="$BUILD_DIR/payload-extracted"
mkdir -p "$PAYLOAD_DIR"
( cd "$PAYLOAD_DIR" && gzip -dc < "$FRAMEWORK_SUBPKG/Payload" | cpio -idm )

FRAMEWORK_PAYLOAD=""
if [ -x "$PAYLOAD_DIR/Versions/Current/bin/python3" ]; then
    # The payload's cpio archive roots directly inside the framework (no
    # "Python.framework/" wrapper folder) — this is the layout used by
    # current python.org installers.
    FRAMEWORK_PAYLOAD="$PAYLOAD_DIR"
else
    # Fall back to searching for a nested Python.framework directory, in
    # case an older/alternate installer layout wraps it differently.
    while IFS= read -r cand; do
        if [ -x "$cand/Versions/Current/bin/python3" ]; then
            FRAMEWORK_PAYLOAD="$cand"
            break
        fi
    done < <(find "$PAYLOAD_DIR" -type d -name "Python.framework")
fi

if [ -z "$FRAMEWORK_PAYLOAD" ]; then
    echo "✗ Payload decompressed but no usable Python.framework was found inside it."
    echo "  Contents of $PAYLOAD_DIR:"
    find "$PAYLOAD_DIR" -maxdepth 3
    exit 1
fi
cp -R "$FRAMEWORK_PAYLOAD" "$FRAMEWORKS_DIR/Python.framework"

# Trim bulk we don't need at runtime (test suites, docs, Tk demos).
FW_VERSION_DIR="$FRAMEWORKS_DIR/Python.framework/Versions/Current"
rm -rf "$FW_VERSION_DIR"/lib/python*/test \
       "$FW_VERSION_DIR"/lib/python*/idlelib \
       "$FW_VERSION_DIR"/lib/python*/turtledemo \
       "$FW_VERSION_DIR"/share/doc \
       2>/dev/null || true

FW_PYTHON="$FW_VERSION_DIR/bin/python3"
if [ ! -x "$FW_PYTHON" ]; then
    echo "✗ Bundled Python binary missing after extraction: $FW_PYTHON"
    exit 1
fi
echo "  Bundled: $("$FW_PYTHON" --version)"

# ── 4. Stage ffmpeg (from Homebrew, build machine only) ──────────────────────
echo "→ Staging ffmpeg…"
FFMPEG_SRC=""
for cand in "$(brew --prefix 2>/dev/null)/bin/ffmpeg" /opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg; do
    if [ -x "$cand" ]; then FFMPEG_SRC="$cand"; break; fi
done
if [ -z "$FFMPEG_SRC" ]; then
    echo "  ffmpeg not found — installing via Homebrew…"
    brew install ffmpeg
    FFMPEG_SRC="$(brew --prefix)/bin/ffmpeg"
fi
cp "$FFMPEG_SRC" "$RESOURCES_DIR/bin/ffmpeg"
chmod +x "$RESOURCES_DIR/bin/ffmpeg"
echo "  Staged: $FFMPEG_SRC → Contents/Resources/bin/ffmpeg"

# ── 5. Ad-hoc code sign ───────────────────────────────────────────────────────
# No Apple Developer ID cert is configured for this project, so this is an
# ad-hoc signature only. It satisfies Gatekeeper on the build machine; on any
# other Mac, recipients need to right-click → Open the first time (see
# README). A paid Apple Developer Program membership would allow full
# notarization and remove that step.
echo "→ Signing .app (ad-hoc)…"
codesign --force --deep --sign - "$APP_DST"
echo "  Signed (ad-hoc)."

# ── 6. Create the DMG ────────────────────────────────────────────────────────
echo "→ Creating DMG…"
STAGING=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR" "$STAGING"' EXIT
cp -R "$APP_DST" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

hdiutil create \
    -volname "${APP_NAME}" \
    -srcfolder "$STAGING" \
    -ov \
    -format UDZO \
    "$DIST_DIR/${DMG_NAME}.dmg"

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
echo "    No Homebrew, no Python install, no setup"
echo "    required — mlx-whisper installs itself into a"
echo "    private venv on first launch."
echo ""
echo "  First-launch note (no Apple Developer cert):"
echo "    macOS will show 'unidentified developer'."
echo "    Right-click the app → Open → Open to bypass"
echo "    (needed only once per Mac)."
echo "==================================================="
