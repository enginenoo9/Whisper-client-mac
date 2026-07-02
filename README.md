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

1. Open the app from Applications.
2. macOS will say it's from an "unidentified developer" (this project isn't
   signed with a paid Apple Developer certificate) — **right-click the app →
   Open → Open**. You only need to do this once.
3. First launch shows a short **Setting up…** progress window (installs
   mlx-whisper into a private folder, ~1–2 minutes). Every launch after that
   is instant.

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

Requires macOS, Homebrew (`brew install ffmpeg`), Xcode Command Line Tools, and
internet access (to download Python from python.org):

```
./build-dmg.sh
```

This downloads the official python.org macOS installer and, via the vendored
`relocatable-python` tool (see `vendor/relocatable-python/README.md`),
extracts `Python.framework` and rewrites its binaries so they work from
inside an app bundle instead of only from `/Library/Frameworks/` — the
official installer's framework is hard-coded to that one absolute path, so
copying it as-is crashes at launch. No system-wide Python install happens.
The script then stages a copy of Homebrew's `ffmpeg`, bundles both into
`Whisper Transcriber.app`, ad-hoc code-signs it, and produces
`dist/Whisper-Transcriber-<version>.dmg`.

mlx-whisper itself is *not* bundled — it's a namespace package with runtime
Metal shader compilation that breaks every static bundler (this project tried
py2app previously; see git history). It still installs into a private venv
the first time the built app runs, just seeded from the bundled Python
instead of a Homebrew one.

A GitHub Actions workflow (`.github/workflows/build-dmg.yml`) runs this same
script on a macOS runner and uploads the DMG as a build artifact — trigger it
manually from the Actions tab, or push a `v*` tag.

**No Apple Developer certificate is configured**, so the build is only
ad-hoc signed. Recipients see "unidentified developer" and need to
right-click → Open once. A $99/year Apple Developer Program membership would
allow full notarization and remove that step.

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
| `whisper_icon.icns` / `.png` | App icon |

> **Editing the GUI:** the `.app` ships its own copy of `whisper_transcriber.py`
> at `Contents/Resources/` and reinstalls it into `~/Whisper/` on every launch.
> After editing the top-level `whisper_transcriber.py`, run
> `./scripts/sync-bundled-app.sh` to update the bundled copy. CI fails if the two
> drift apart.

---

## Troubleshooting

**"Whisper Transcriber can't be opened because it is from an unidentified developer"**
Right-click the app → **Open** → **Open**. Only needed once per Mac (no paid
Apple Developer certificate is configured for this project).

**First launch shows a "Setting up…" window that doesn't finish**
Needs internet access to install mlx-whisper the first time. Check your
connection and reopen the app to retry.

**"ffmpeg not found" in the log**
DMG installs bundle their own ffmpeg — reinstall from a fresh DMG if this
happens. Source installs: run **Setup / Repair…**, which installs it via
Homebrew.

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

- The GUI is a tkinter Python app (`whisper_transcriber.py`).
- `Contents/MacOS/launcher` (bash) picks a Python interpreter — the bundled
  `Python.framework` if this was built with `build-dmg.sh`, otherwise a
  Homebrew Python for source installs — and hands off to `bootstrap.py`.
- `bootstrap.py` creates a private venv at `~/Whisper/venv`, installs
  `mlx-whisper` and friends into it (skipped on subsequent launches once
  everything's already there), then execs into that venv to run the GUI.
  The GUI calls the `mlx_whisper` CLI via subprocess for each file.
- MLX runs Whisper models accelerated by Apple's GPU via the Metal framework.
- `ffmpeg` decodes audio (bundled in the DMG, or via Homebrew for source
  installs). Whisper transcribes it. Everything stays on your Mac.
- **PDF output** uses `fpdf2`. **DOCX output** uses `python-docx`.
- **Live transcription** uses `sounddevice` to capture 10-second audio chunks
  from the microphone, then passes each chunk directly to `mlx_whisper.transcribe()`.

---

## License

This project is licensed under the [MIT License](LICENSE).

It relies on third-party components that remain under their own licenses —
some installed at runtime via pip, some (Python.framework, ffmpeg) bundled
directly into the DMG by `build-dmg.sh`. Most are MIT or otherwise permissive
(OpenAI Whisper, `mlx`, `mlx-whisper`, `python-docx`, `sounddevice`, CPython,
Tcl/Tk); **ffmpeg** (LGPL-2.1+/GPL) and `fpdf2` (LGPL-3.0) are copyleft. The
full component list is in **[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)**.
