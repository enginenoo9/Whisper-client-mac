# Whisper Transcriber

A simple Mac app for turning audio and video files into text transcripts. It
runs OpenAI's Whisper models locally using Apple Silicon (via `mlx-whisper`) —
nothing is uploaded to the cloud, and there's no subscription.

Pick a model, choose a file, click **Transcribe**, and a text transcript lands
on your Desktop.

---

## What's in this folder

| File | Purpose |
|------|---------|
| `Whisper Transcriber.app` | The app you double-click to use it. |
| `whisper_transcriber.py` | The actual program (the app launches this). |
| `setup.command` | One-time installer. Run this first on a new Mac. |
| `launch.command` | Backup launcher (does the same thing as the app). |
| `whisper_icon.png` / `.icns` | The app icon, in case you want to re-apply it. |

---

## Requirements

- A Mac with Apple Silicon (M1 or newer recommended).
- **Homebrew** installed — this is the one thing the setup can't install for
  you. See the next section if you don't already have it.

Everything else (Python, ffmpeg, the Whisper engine) is installed automatically
by `setup.command`.

---

## Step 0 — Install Homebrew (only if you don't have it)

Homebrew is a free tool that lets the setup script install what it needs. You
only do this once per Mac. To check whether it's already installed, open
**Terminal** (Applications → Utilities → Terminal) and type:

```
brew --version
```

If that prints a version number, you already have it — skip to Step 1.

If it says "command not found," install it:

1. Open **Terminal**.
2. Paste this line and press Return:

   ```
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

3. It will ask for your Mac password (the one you log in with) and pause to
   confirm — press **Return** to continue. Installation takes a few minutes,
   and it may install Apple's Command Line Tools along the way.

4. **Important final step (Apple Silicon Macs):** when it finishes, it prints a
   "Next steps" message asking you to run two lines to add Homebrew to your
   PATH. Copy and run them. They look like this (use the exact lines the
   installer shows you):

   ```
   echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
   eval "$(/opt/homebrew/bin/brew shellenv)"
   ```

5. Confirm it worked by running `brew --version` again — you should now see a
   version number.

That's it — Homebrew is installed. Now continue to Step 1.

---

## Step 1 — First-time setup (new Mac)

1. Put this whole folder somewhere convenient.
2. Double-click **`setup.command`**.
   - It installs Python, ffmpeg, and the Whisper engine.
   - It copies the app files into your home folder at `~/Whisper/`.
   - This takes a few minutes the first time. When it says
     "Setup complete," you can close the window.
3. Double-click **`Whisper Transcriber.app`** to open it.

> **First launch note:** macOS may warn that the app is from an
> "unidentified developer." Right-click the app → **Open** → **Open**. You only
> need to do this once.

---

## How to use it

1. Open the app.
2. **Model** — pick the quality/speed you want:
   - *Large V3* — best accuracy, slowest, ~3 GB
   - *Medium* — great balance (default), ~1.5 GB
   - *Small* — fast, ~460 MB
   - *Base* — fastest, ~145 MB
3. **Audio file** — click *Choose…* and pick your podcast, recording, or video.
4. **Save to** — defaults to your Desktop; change it if you like.
5. **Format** — `TXT` for a plain transcript (most common). `SRT`/`VTT` are
   subtitle formats for video. `ALL` makes all three.
6. **Cleanup** — leave checked to merge the choppy per-segment line breaks into
   readable paragraphs.
7. Click **Transcribe**.

The first time you use a given model it downloads automatically (one time, then
cached). When it finishes, the folder with your transcript opens automatically.

Your last choices (model, format, save folder) are remembered next time.

---

## Models

- **Download button** — pre-downloads the selected model so you don't wait
  during transcription. If a model is already downloaded, the button shows
  "Downloaded ✓" and is greyed out.
- Models are cached in `~/.cache/huggingface` and only download once.

---

## Maintenance

Buttons in the bottom-right of the app:

- **Setup / Repair…** — re-runs the installer (useful if something breaks or to
  update the Whisper engine).
- **Clean up…** — opens a dialog to free disk space:
  - *Delete downloaded models* — removes the AI models (they re-download next
    time you need them). Reversible.
  - *Uninstall everything* — removes the models **and** the Python packages,
    then quits. To use the app again, run `setup.command` once more.

---

## Troubleshooting

**"Whisper Transcriber isn't set up yet" dialog**
Run `setup.command` first. It creates everything the app needs.

**App icon looks generic / wrong**
Finder sometimes caches icons. Move the app to a different folder, or log out
and back in, and it'll refresh.

**"ffmpeg not found" in the progress log**
Run **Setup / Repair…** (or `setup.command`) — it installs ffmpeg.

**Setup says "Homebrew is not installed"**
Do Step 0 above to install Homebrew, then run `setup.command` again. On Apple
Silicon, don't skip the PATH step (the two `shellenv` lines) — without it, the
setup won't find `brew`.

**Transcription is slow**
Larger models are slower. Try *Medium* or *Small*. On Apple Silicon, *Medium*
typically transcribes a 1-hour file in a few minutes.

**Window looks broken / black / labels missing**
This happens with Apple's old built-in Python. The app avoids it by using the
Homebrew Python that `setup.command` installs — so make sure you ran setup and
are opening the app (not running the script with the system Python).

---

## How it works (for the curious)

- The app is a small launcher that runs `whisper_transcriber.py` using a Python
  virtual environment at `~/Whisper/venv`.
- That environment has `mlx-whisper`, which runs Whisper models accelerated by
  Apple's MLX framework.
- `ffmpeg` decodes the audio; Whisper transcribes it; the result is written as
  a text (or subtitle) file.
- Everything runs locally on your Mac. No audio leaves the machine.
