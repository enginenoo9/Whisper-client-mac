# Whisper Transcriber

A Mac app for turning audio and video files into text transcripts — in batch.
Runs OpenAI's Whisper models locally via Apple Silicon (`mlx-whisper`). Nothing
is uploaded to the cloud. No subscription.

Queue up multiple files, pick a model, click **Transcribe N Files**, and transcripts
land in your chosen folder automatically.

---

## Install

**Recommended: the DMG.** Download `Whisper-Transcriber-<version>.dmg`, open it,
and drag **Whisper Transcriber** into your **Applications** folder. No Homebrew,
no Python install, nothing to run in Terminal.

1. Open the app from Applications. macOS will block it the first time with
   **"Whisper Transcriber" Not Opened** (this project isn't signed with a paid
   Apple Developer certificate). Click **Done** — not Move to Trash.
2. Open **System Settings → Privacy & Security**, scroll down to the
   *Security* section, and click **Open Anyway** next to the message about
   Whisper Transcriber. Confirm with **Open Anyway** and your password or
   Touch ID. You only need to do this once per Mac.
   (The old right-click → Open shortcut no longer works as of macOS 15
   Sequoia.)
3. First launch shows a **Setting up…** window. Pick a transcription model
   (Medium is a good default) — setup installs mlx-whisper into a private
   folder and downloads that model, a few minutes in total depending on your
   connection. Every launch after that is instant.

The DMG bundles its own Python and ffmpeg, so there's genuinely nothing else
to install. See [Building the DMG](#building-the-dmg) if you want to build it
yourself instead of using a prebuilt release.

### Alternative: run from source

If you'd rather not use the DMG, the `.app` in this repo still works standalone
against a Homebrew Python (useful for development):

1. Install Homebrew, then `brew install python-tk`.
2. Double-click `Whisper Transcriber.app` (or `launch.command`) — it sets up a
   venv in `~/Whisper/venv` and installs mlx-whisper into it, same as before.

You can also run `setup.command` directly to install, then `launch.command` to start.

---

## Requirements

- A Mac with Apple Silicon (M1 or newer).
- **DMG install:** nothing else — it's fully self-contained.
- **Run-from-source install:** Homebrew with Python (`brew install python-tk`).

### Installing Homebrew (source install only)

Open **Terminal** and run:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After it finishes, run the two `shellenv` lines it prints (Apple Silicon only),
then confirm with `brew --version`. Then open the app — it handles the rest.

---

## Building the DMG

Requires macOS, Xcode Command Line Tools, `python3` with pip, and internet
access (to download Python from python.org and ffmpeg from PyPI):

```
./build-dmg.sh
```

This downloads the official python.org macOS installer and, via the vendored
`relocatable-python` tool (see `vendor/relocatable-python/README.md`),
extracts `Python.framework` and rewrites its binaries so they work from
inside an app bundle instead of only from `/Library/Frameworks/` — the
official installer's framework is hard-coded to that one absolute path, so
copying it as-is crashes at launch. No system-wide Python install happens.
The script then stages a standalone `ffmpeg` from the `imageio-ffmpeg` wheel
(Homebrew's can't be used — it depends on Homebrew's own libraries, so it
only runs on Macs that have them), removes the standalone
x86_64-only `python3.12-intel64` binary python.org ships alongside the
universal one (unneeded — nothing here supports Intel), strips the unused
x86_64 slice from every remaining bundled binary (this app is Apple
Silicon-only — mlx-whisper has no Intel build — and leftover Intel code is
what triggers macOS's "this app uses Rosetta" deprecation notice even
though it can never actually run), bundles everything into
`Whisper Transcriber.app`, ad-hoc
code-signs it, and produces `dist/Whisper-Transcriber-<version>.dmg`.

mlx-whisper itself is *not* bundled — it's a namespace package with runtime
Metal shader compilation that breaks every static bundler (this project tried
py2app previously; see git history). It still installs into a private venv
the first time the built app runs, just seeded from the bundled Python
instead of a Homebrew one.

A GitHub Actions workflow (`.github/workflows/build-dmg.yml`) runs this same
script on a macOS runner and uploads the DMG as a build artifact — trigger it
manually from the Actions tab, or push a `v*` tag.

**No Apple Developer certificate is configured**, so the build is only
ad-hoc signed. Recipients have to approve it once via System Settings →
Privacy & Security → **Open Anyway** (see [Install](#install)). A $99/year
Apple Developer Program membership would allow full notarization and remove
that step.

---

## How to use it

1. Open the app.
2. **Model** — pick quality vs. speed:
   - *Large V3* — best accuracy (~3 GB)
   - *Medium* — great balance, default (~1.5 GB)
   - *Small* — fast (~460 MB)
   - *Base* — fastest (~145 MB)
3. **Files** — click **Add Files…** to queue one or more audio/video files.
   Select multiple at once with Shift- or Command-click. Remove individual
   files with **Remove** or the Delete key. **Clear All** empties the queue.
4. **Save to** — defaults to your Desktop.
5. **Format** — choose your output:
   - `TXT` — plain text transcript
   - `SRT` / `VTT` — subtitle formats (with timestamps)
   - `PDF` — formatted PDF document
   - `DOCX` — Word-compatible document
6. **Cleanup** — merges choppy per-segment line breaks into readable paragraphs.
7. Click **Transcribe 1 File** / **Transcribe N Files**.

Files are processed one at a time in order. The current file is highlighted in
the queue. When the last one finishes, the output folder opens automatically.

Your last choices (model, format, save folder) are remembered next time.

---

## Live Transcription

Click **Live Transcribe…** to transcribe from your microphone in real time.

1. Select an output format (TXT, PDF, or DOCX).
2. Click **Start** — the app begins recording and transcribes in ~10-second chunks.
3. Text appears as each chunk is processed (expect ~12–15 second latency).
4. Click **Stop** to finish. The transcript is saved to your **Save to** folder
   with a timestamped filename.

macOS will prompt for microphone permission on first use.

---

## Models

- **Download** — pre-fetches the selected model so you don't wait during
  transcription. Shows "Downloaded ✓" once cached.
- Models are stored in `~/.cache/huggingface` and only download once per Mac.

---

## Maintenance

- **Setup / Repair…** — re-runs the installer. Use this to update mlx-whisper
  or fix a broken environment.
- **Clean up…** — frees disk space:
  - *Delete downloaded models* — removes the AI models (re-download on next use).
  - *Uninstall everything* — removes models and Python packages, then quits.
    Run `setup.command` again to reinstall.

---

## Files in this repo

| File | Purpose |
|---|---|
| `whisper_transcriber.py` | Main GUI application |
| `Whisper Transcriber.app` | App bundle (launcher + bootstrap + GUI) |
| `build-dmg.sh` | Builds the standalone DMG (bundles Python + ffmpeg) |
| `setup.command` | Manual install / repair script (source-install path) |
| `launch.command` | Fallback launcher (source-install path) |
| `whisper_icon.icns` / `.png` | App icon (generated — don't edit by hand) |
| `scripts/generate-icon.py` | Regenerates the icon (`pip3 install pillow`, then run it) |

> **Editing the GUI:** the `.app` ships its own copy of `whisper_transcriber.py`
> at `Contents/Resources/` and reinstalls it into `~/Whisper/` on every launch.
> After editing the top-level `whisper_transcriber.py`, run
> `./scripts/sync-bundled-app.sh` to update the bundled copy. CI fails if the two
> drift apart.

---

## Troubleshooting

**"Whisper Transcriber" Not Opened / "Apple could not verify…"**
Click **Done**, then go to System Settings → Privacy & Security and click
**Open Anyway** (see [Install](#install)). Only needed once per Mac (no paid
Apple Developer certificate is configured for this project). If the Open
Anyway button doesn't appear, you can instead clear the download quarantine
flag in Terminal:

```bash
xattr -dr com.apple.quarantine "/Applications/Whisper Transcriber.app"
```

**First launch shows a "Setting up…" window that doesn't finish**
Needs internet access to install mlx-whisper the first time. Check your
connection and reopen the app to retry. If only the model download fails,
setup still finishes — download the model from the app's **Download** button.

**"ffmpeg not found" in the log**
DMG installs bundle their own ffmpeg — reinstall from a fresh DMG if this
happens. Source installs: `brew install ffmpeg`.

**"Homebrew Python not found" dialog**
Only relevant to the run-from-source path. Install Homebrew and run
`brew install python-tk`, then reopen the app. (The DMG doesn't need this.)

**Transcription is slow**
Use *Medium* or *Small*. On M1, Medium transcribes ~1 hour of audio in a few
minutes.

**Window looks broken or labels are missing**
Make sure you're opening `Whisper Transcriber.app`, not running the `.py` file
with the system Python.

---

## How it works

- The GUI (`whisper_transcriber.py`) is an HTML/CSS/JS front-end rendered in a
  native macOS WebView via `pywebview`. Tkinter can't produce a modern-looking
  Mac app no matter how it's themed (its widget rendering tops out at a dated
  look), so the presentation layer is web tech and all the real work stays in
  Python, exposed to the page through pywebview's JS bridge.
- `Contents/MacOS/launcher` (bash) picks a Python interpreter — the bundled
  `Python.framework` if this was built with `build-dmg.sh`, otherwise a
  Homebrew Python for source installs — and hands off to `bootstrap.py`.
- `bootstrap.py` creates a private venv at `~/Whisper/venv`, installs
  `mlx-whisper` and friends into it (skipped on subsequent launches once
  everything's already there), then execs into that venv to run the GUI.
  The GUI calls the `mlx_whisper` CLI via subprocess for each file. (The
  one-time setup progress window in `bootstrap.py` is still plain tkinter —
  it runs under the bundled framework Python before pywebview is installed.)
- MLX runs Whisper models accelerated by Apple's GPU via the Metal framework.
- `ffmpeg` decodes audio (bundled in the DMG, or via Homebrew for source
  installs). Whisper transcribes it. Everything stays on your Mac.
- **PDF output** uses `fpdf2`. **DOCX output** uses `python-docx`.
- **Live transcription** uses `sounddevice` to capture 10-second audio chunks
  from the microphone, then passes each chunk directly to `mlx_whisper.transcribe()`.
- The final `execve` into `~/Whisper/venv`'s Python means the running process
  lives outside `Contents/MacOS/`, so macOS can't trace it back to
  `Info.plist` for the menu bar — it shows "Python" instead of the app name
  unless corrected. `pyobjc-framework-Cocoa` overrides that at startup
  (`_fix_macos_menu_bar_name()` in `whisper_transcriber.py`).

---

## License

This project is licensed under the [MIT License](LICENSE).

It relies on third-party components that remain under their own licenses —
some installed at runtime via pip, some (Python.framework, ffmpeg) bundled
directly into the DMG by `build-dmg.sh`. Most are MIT or otherwise permissive
(OpenAI Whisper, `mlx`, `mlx-whisper`, `python-docx`, `sounddevice`, CPython,
Tcl/Tk); **ffmpeg** (LGPL-2.1+/GPL) and `fpdf2` (LGPL-3.0) are copyleft. The
full component list is in **[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)**.
