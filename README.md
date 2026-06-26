# Whisper Transcriber

A Mac app for turning audio and video files into text transcripts — in batch.
Runs OpenAI's Whisper models locally via Apple Silicon (`mlx-whisper`). Nothing
is uploaded to the cloud. No subscription.

Queue up multiple files, pick a model, click **Transcribe N Files**, and transcripts
land in your chosen folder automatically.

---

## Two ways to install

### Option A — Standalone DMG (recommended for sharing)

Build a self-contained `.app` that needs no Python, Homebrew, or setup at all.
See **[Building the standalone app](#building-the-standalone-app)** below.
Share the resulting DMG with anyone on an Apple Silicon Mac.

### Option B — Self-installing app (this repo, for development)

`Whisper Transcriber.app` auto-installs on first launch:

1. Double-click `Whisper Transcriber.app`.
2. If it's the first launch and the venv is missing, a dialog appears. Click
   **Set Up & Open** — a Terminal window installs everything and then re-opens the
   app automatically.
3. That's it. Subsequent launches open instantly.

**Only prerequisite:** Homebrew with Python (see below if you need it).

---

## Requirements (Option B only)

- A Mac with Apple Silicon (M1 or newer).
- **Homebrew** — the one thing that can't auto-install. See below.

Everything else (Python, ffmpeg, the Whisper engine) installs itself on first launch.

### Installing Homebrew

Open **Terminal** and run:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After it finishes, run the two `shellenv` lines it prints (Apple Silicon only),
then confirm with `brew --version`. Then open the app — it handles the rest.

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
   - `ALL` — writes TXT, SRT, and VTT together
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

## Maintenance (Option B)

- **Setup / Repair…** — re-runs the installer. Use this to update mlx-whisper
  or fix a broken environment.
- **Clean up…** — frees disk space:
  - *Delete downloaded models* — removes the AI models (re-download on next use).
  - *Uninstall everything* — removes models and Python packages, then quits.
    Run `setup.command` again to reinstall.

---

## Building the standalone app

Run this once on an Apple Silicon Mac that has Homebrew:

```bash
brew install python-tk ffmpeg   # if not already installed
./build.sh
```

`build.sh` will:
1. Install `py2app`, `mlx-whisper`, `fpdf2`, `python-docx`, and `sounddevice` into your Homebrew Python.
2. Bundle the app, Python runtime, all ML dependencies, and ffmpeg into a
   single `dist/Whisper Transcriber.app` (~500 MB).
3. Create `dist/Whisper-Transcriber-2.0.dmg` — drag-to-install, no setup needed.

**Distributing:** share the DMG. Recipients open it, drag the app to
Applications, and launch it. No Homebrew, no Terminal, no setup required.

**First-launch Gatekeeper warning:** macOS will say "unidentified developer."
Right-click the app → **Open** → **Open** (once only). This goes away if you
sign with an Apple Developer ID certificate (`codesign --sign "Developer ID…"`).

### Files in this repo

| File | Purpose |
|---|---|
| `whisper_transcriber.py` | Main GUI application |
| `Whisper Transcriber.app` | Self-installing launcher (Option B) |
| `setup.command` | Manual install / repair script |
| `launch.command` | Fallback launcher (same as the app) |
| `setup_py2app.py` | py2app build config (used by `build.sh`) |
| `build.sh` | Builds the standalone .app and DMG |
| `whisper_icon.icns` / `.png` | App icon |

---

## Troubleshooting

**First launch shows "Set Up & Open" dialog**
Click it — the app sets itself up automatically. Requires Homebrew Python.

**"ffmpeg not found" in the log**
Run **Setup / Repair…** — it installs ffmpeg via Homebrew.

**"Homebrew Python not found" dialog**
Install Homebrew and run `brew install python-tk`, then reopen the app.

**Transcription is slow**
Use *Medium* or *Small*. On M1, Medium transcribes ~1 hour of audio in a few
minutes.

**Window looks broken or labels are missing**
Make sure you're opening `Whisper Transcriber.app`, not running the `.py` file
with the system Python. The app uses the Homebrew Python installed by setup.

**Build fails (`./build.sh`)**
Make sure `brew install python-tk` succeeded and that Python reports a version
≥ 3.12. The `mlx-whisper` package requires Apple Silicon.

---

## How it works

- The GUI is a tkinter Python app (`whisper_transcriber.py`).
- In the **self-installing version**: a bash launcher bootstraps a venv at
  `~/Whisper/venv`, installs `mlx-whisper`, then runs the GUI with that Python.
  The GUI calls the `mlx_whisper` CLI via subprocess for each file.
- In the **standalone version** (py2app): Python, all ML packages, and ffmpeg
  are bundled inside the `.app`. The GUI calls the `mlx_whisper` Python API
  directly (no subprocess needed).
- MLX runs Whisper models accelerated by Apple's GPU via the Metal framework.
- `ffmpeg` decodes audio. Whisper transcribes it. Everything stays on your Mac.
- **PDF output** uses `fpdf2`. **DOCX output** uses `python-docx`.
- **Live transcription** uses `sounddevice` to capture 10-second audio chunks
  from the microphone, then passes each chunk directly to `mlx_whisper.transcribe()`.

---

## License

This project is licensed under the [MIT License](LICENSE).

OpenAI's Whisper models and `mlx-whisper` are licensed separately under the MIT
License by their respective authors.
