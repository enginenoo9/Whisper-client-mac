#!/bin/bash
#
# build-dmg.sh — Build a standalone, drag-to-install Whisper Transcriber.dmg.
#
# Bundles a real Python.framework (from python.org) and a static ffmpeg
# binary directly into the .app, so the *build machine* needs internet
# access, but the *end user* doesn't — no Homebrew, no
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
#   - python3 with pip (to fetch the imageio-ffmpeg wheel)
#   - Internet access, to download the official python.org installer
#     and the ffmpeg wheel from PyPI
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

VERSION="3.6.1"
APP_NAME="Whisper Transcriber"
DMG_NAME="Whisper-Transcriber-${VERSION}"

# Bump this to pick up a newer Python. Must be a released "macOS 64-bit
# universal2 installer" build — check https://www.python.org/downloads/macos/
PYTHON_VERSION="3.12.8"

# Source of the bundled standalone ffmpeg binary (see step 3).
IMAGEIO_FFMPEG_VERSION="0.6.0"

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

# ── 2. Build a relocatable Python.framework ──────────────────────────────────
# python.org's official installer produces a Python.framework whose binaries
# have their shared-library path hard-coded to /Library/Frameworks/... —
# copy it into the app bundle as-is and it crashes at launch with a
# "Library not loaded" dyld error the moment it runs from anywhere else.
# vendor/relocatable-python (see that directory's README) downloads the same
# official installer over HTTPS and rewrites those Mach-O load-command paths
# with install_name_tool so the framework works from any location, then
# re-signs the binaries it touched.
echo "→ Building a relocatable Python ${PYTHON_VERSION} framework…"
python3 "$ROOT_DIR/vendor/relocatable-python/make_relocatable_python_framework.py" \
    --destination "$FRAMEWORKS_DIR" \
    --python-version "$PYTHON_VERSION" \
    --os-version "11" \
    --without-pip

FW_VERSION_DIR="$FRAMEWORKS_DIR/Python.framework/Versions/Current"
FW_PYTHON="$FW_VERSION_DIR/bin/python3"
if [ ! -x "$FW_PYTHON" ]; then
    echo "✗ Bundled Python binary missing after build: $FW_PYTHON"
    exit 1
fi

# Trim bulk we don't need at runtime (test suites, docs, Tk demos).
rm -rf "$FW_VERSION_DIR"/lib/python*/test \
       "$FW_VERSION_DIR"/lib/python*/idlelib \
       "$FW_VERSION_DIR"/lib/python*/turtledemo \
       "$FW_VERSION_DIR"/share/doc \
       2>/dev/null || true

# python.org also ships a standalone x86_64-only "-intel64" binary for
# people who need to force Intel compatibility. This app has no use for
# it — nothing here runs on Intel — and unlike the universal binaries
# thinned below, it's genuine Intel-only code the thinning step can't
# touch (it's already single-arch, not fat). Just remove it.
rm -f "$FW_VERSION_DIR"/bin/python3*-intel64

echo "  Bundled: $("$FW_PYTHON" --version)"

# ── 3. Stage a self-contained ffmpeg ─────────────────────────────────────────
# Homebrew's ffmpeg can't be used here: it's dynamically linked against
# libav*.dylib files under /opt/homebrew/Cellar, so a copied binary only runs
# on Macs that happen to have Homebrew's ffmpeg installed too. The
# imageio-ffmpeg wheel on PyPI ships a standalone arm64 build that links only
# against macOS system libraries — pull the binary out of that instead.
echo "→ Staging ffmpeg (imageio-ffmpeg ${IMAGEIO_FFMPEG_VERSION})…"
FFMPEG_DL="$BUILD_DIR/imageio-ffmpeg"
python3 -m pip download "imageio-ffmpeg==${IMAGEIO_FFMPEG_VERSION}" \
    --no-deps --only-binary=:all: --platform macosx_11_0_arm64 \
    --dest "$FFMPEG_DL" --quiet
unzip -q -o "$FFMPEG_DL"/imageio_ffmpeg-*.whl "imageio_ffmpeg/binaries/*" -d "$FFMPEG_DL"
FFMPEG_SRC="$(find "$FFMPEG_DL/imageio_ffmpeg/binaries" -name 'ffmpeg-macos-aarch64-*' -type f | head -1)"
if [ -z "$FFMPEG_SRC" ]; then
    echo "✗ No arm64 ffmpeg binary found in the imageio-ffmpeg wheel."
    exit 1
fi
cp "$FFMPEG_SRC" "$RESOURCES_DIR/bin/ffmpeg"
chmod +x "$RESOURCES_DIR/bin/ffmpeg"
# Guard against ever shipping a binary that depends on non-system libraries.
if otool -L "$RESOURCES_DIR/bin/ffmpeg" | tail -n +2 | grep -vE '^[[:space:]]+/(usr/lib|System/Library)/'; then
    echo "✗ Staged ffmpeg links against non-system libraries (listed above)."
    exit 1
fi
echo "  Staged: $(basename "$FFMPEG_SRC") → Contents/Resources/bin/ffmpeg"

# ── 4. Strip unused x86_64 code ───────────────────────────────────────────────
# This app only ever runs on Apple Silicon — mlx/mlx-whisper have no x86_64
# build at all — but python.org's universal2 installer ships both
# architectures, and some Homebrew formulas do too. Keeping the unused Intel
# slice around is exactly what triggers macOS's "this app uses Rosetta and
# may not be supported in a future version of macOS" notification, even
# though that code path can never actually execute. Thin everything to
# arm64-only.
echo "→ Stripping unused x86_64 code (arm64-only app; Intel code is what"
echo "  triggers macOS's Rosetta deprecation notice)…"
while IFS= read -r -d '' f; do
    info="$(lipo -info "$f" 2>/dev/null || true)"
    if [[ "$info" == *"x86_64"* && "$info" == *"arm64"* ]]; then
        perms="$(stat -f "%Lp" "$f")"
        lipo -thin arm64 -output "${f}.thin" "$f"
        mv "${f}.thin" "$f"
        chmod "$perms" "$f"
    fi
done < <(find "$APP_DST" -type f -perm -u+x -print0)
echo "  Verifying framework still works after thinning…"
"$FW_PYTHON" --version

# ── 5. Ad-hoc code sign ───────────────────────────────────────────────────────
# No Apple Developer ID cert is configured for this project, so this is an
# ad-hoc signature only. It satisfies Gatekeeper on the build machine; on any
# other Mac, recipients need to approve it once via System Settings →
# Privacy & Security → Open Anyway (see README). A paid Apple Developer Program membership would allow full
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
echo "    macOS will block the first launch. Recipients"
echo "    click Done, then System Settings → Privacy &"
echo "    Security → Open Anyway (needed once per Mac)."
echo "==================================================="
