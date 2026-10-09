#!/usr/bin/env python3
"""
Whisper Transcriber — bootstrap.

Runs under the Python.framework bundled inside the .app. On a clean Mac
this is the first code that executes: it seeds a private venv (so the
read-only, ad-hoc-signed .app bundle is never written to), installs
mlx-whisper and the other runtime packages into it, downloads the model
the user picks, then execs into that venv to run the real app. Subsequent launches skip straight to the exec
once everything is already installed — no Terminal, no Homebrew.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

BG, TEXT, MUTED = "#f5f5f7", "#1d1d1f", "#86868b"
LOG_BG, LOG_FG = "#1e1e1e", "#d4d4d4"

# Keep in sync with whisper_transcriber.py (see the comment there for why
# mlx-whisper is installed with --no-deps).
MLX_WHISPER_PACKAGE = "mlx-whisper==0.4.3"
REQUIRED_PACKAGES = ["mlx", "numba", "numpy", "scipy", "tiktoken", "tqdm",
                     "more-itertools", "huggingface_hub",
                     "fpdf2", "python-docx", "sounddevice",
                     "pyobjc-framework-Cocoa", "pywebview"]
IMPORT_CHECK = "import mlx_whisper, fpdf, docx, sounddevice, Foundation, webview"

# The multilingual subset of MODELS in whisper_transcriber.py (labels and
# repos must match it); the English-only models are offered in the app.
MODELS = [
    ("Large V3 Turbo — Fast & near-best accuracy (~1.6 GB)", "mlx-community/whisper-large-v3-turbo"),
    ("Large V3 — Best accuracy (~3 GB)",                     "mlx-community/whisper-large-v3-mlx"),
    ("Medium — Great balance (~1.5 GB)",                     "mlx-community/whisper-medium-mlx"),
    ("Small — Fast (~480 MB)",                               "mlx-community/whisper-small-mlx"),
    ("Base — Faster (~145 MB)",                              "mlx-community/whisper-base-mlx"),
    ("Tiny — Fastest, lowest accuracy (~75 MB)",             "mlx-community/whisper-tiny-mlx"),
]
DEFAULT_MODEL_INDEX = 0

WHISPER_DIR = os.path.expanduser("~/Whisper")
VENV_DIR = os.path.join(WHISPER_DIR, "venv")
VENV_PY = os.path.join(VENV_DIR, "bin", "python3")
APP_PY = os.path.join(WHISPER_DIR, "whisper_transcriber.py")
CONFIG_PATH = os.path.join(WHISPER_DIR, "whisper_transcriber_config.json")

# Runs inside the venv: downloads a model while printing "PROGRESS <done>
# <total>" lines for the setup window's progress bar. huggingface_hub's own
# tqdm bars redraw with \r, which doesn't survive being piped line-by-line,
# so progress is measured from how much the cache has grown instead. The
# whole cache is measured (not just the model's folder) because
# huggingface_hub 2.0 writes file contents to a shared hub/blobs/ store; each
# inode is counted once and symlinks are skipped, so links between the two
# layouts aren't double-counted.
DOWNLOAD_SCRIPT = r"""
import os, stat, sys, threading
from huggingface_hub import HfApi, snapshot_download
from huggingface_hub.constants import HF_HUB_CACHE

repo = sys.argv[1]
info = HfApi().model_info(repo, files_metadata=True)
total = sum(s.size or 0 for s in info.siblings)

def cache_size():
    n, seen = 0, set()
    for root, _dirs, files in os.walk(HF_HUB_CACHE):
        for f in files:
            try:
                st = os.lstat(os.path.join(root, f))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and (st.st_dev, st.st_ino) not in seen:
                seen.add((st.st_dev, st.st_ino))
                n += st.st_size
    return n

baseline = cache_size()
def size():
    return max(cache_size() - baseline, 0)

err = []
def run():
    try:
        snapshot_download(repo_id=repo)
    except Exception as exc:
        err.append(exc)

t = threading.Thread(target=run)
t.start()
while t.is_alive():
    print("PROGRESS", min(size(), total), total, flush=True)
    t.join(0.5)
if err:
    print(f"{type(err[0]).__name__}: {err[0]}", flush=True)
    sys.exit(1)
print("PROGRESS", total, total, flush=True)
"""


def hf_cache_dir():
    for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(var):
            return os.environ[var]
    if os.environ.get("HF_HOME"):
        return os.path.join(os.environ["HF_HOME"], "hub")
    return os.path.expanduser("~/.cache/huggingface/hub")


def any_model_cached():
    """True if any Whisper model has at least one downloaded file — in that
    case setup is a repair, not a first run, and shouldn't offer a model."""
    cache = hf_cache_dir()
    if not os.path.isdir(cache):
        return False
    for nm in os.listdir(cache):
        if not nm.startswith("models--mlx-community--whisper"):
            continue
        snaps = os.path.join(cache, nm, "snapshots")
        for _root, _dirs, files in os.walk(snaps):
            if files:
                return True
    return False


def save_model_choice(repo):
    """Pre-select the downloaded model in the app's config."""
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg["model"] = repo
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f)
    except OSError:
        pass


def human_size(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def bundle_dir():
    if len(sys.argv) > 1:
        return sys.argv[1]
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, ".."))  # Contents/Resources -> Contents


def seed_python(bundle):
    """Python used to create the private venv.

    Normally the Python.framework bundled by build-dmg.sh. If that's not
    present (e.g. running this .app straight from a git checkout, where
    Frameworks/ is a build artifact and isn't committed), fall back to
    whichever interpreter is currently running this script — the launcher
    already found a working Homebrew Python with tkinter in that case.
    """
    bundled = os.path.join(bundle, "Contents", "Frameworks", "Python.framework",
                            "Versions", "Current", "bin", "python3")
    if os.path.exists(bundled):
        return bundled
    return sys.executable


def sync_app_files(bundle):
    """Mirror the bundled script + helper scripts into ~/Whisper, like the old launcher did."""
    os.makedirs(WHISPER_DIR, exist_ok=True)
    bundled_py = os.path.join(bundle, "Contents", "Resources", "whisper_transcriber.py")
    if os.path.exists(bundled_py):
        shutil.copy(bundled_py, APP_PY)

    parent = os.path.dirname(bundle)
    for helper in ("setup.command", "launch.command"):
        src = os.path.join(parent, helper)
        dst = os.path.join(WHISPER_DIR, helper)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy(src, dst)
            os.chmod(dst, 0o755)


def deps_ready():
    if not os.path.exists(VENV_PY):
        return False
    r = subprocess.run([VENV_PY, "-c", IMPORT_CHECK], capture_output=True)
    return r.returncode == 0


def launch(bundle):
    env = os.environ.copy()
    env["WHISPER_BUNDLE_RESOURCES"] = os.path.join(bundle, "Contents", "Resources")
    os.execve(VENV_PY, [VENV_PY, APP_PY], env)


class SetupWindow:
    def __init__(self, bundle):
        self.bundle = bundle
        # Only a true first run offers a model; a repair (deps broken, a
        # model already downloaded) goes straight to reinstalling packages.
        self.offer_model = not any_model_cached()
        self.root = tk.Tk()
        self.root.title("Whisper Transcriber — Setup")
        self.root.configure(bg=BG)
        self.root.geometry("520x590" if self.offer_model else "480x360")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._force_light_appearance()
        self._build()
        self.root.after(200, self._start)

    def _force_light_appearance(self):
        # The labels below use fixed light-theme colors, and the main app
        # forces light appearance too, so in system Dark Mode this window
        # otherwise drew dark text on a dark background. pyobjc isn't
        # available under the bundled framework Python this runs on, but
        # Tk 8.6.10+ can set the window's appearance itself.
        try:
            self.root.tk.call("::tk::unsupported::MacWindowStyle",
                              "appearance", self.root, "aqua")
        except tk.TclError:
            pass

    def _build(self):
        # Native aqua theme for this window only — it's plain tkinter,
        # running under the bundled framework Python before pywebview (what
        # the real app UI uses) is even installed into the venv.
        style = ttk.Style(self.root)
        try:
            style.theme_use("aqua")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, font=("Helvetica", 12))

        frm = ttk.Frame(self.root, padding=(24, 20))
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Setting up Whisper Transcriber",
                  font=("Helvetica", 16, "bold")).pack(anchor="w")
        ttk.Label(frm, text="One-time setup — this takes a few minutes.",
                  foreground=MUTED).pack(anchor="w", pady=(2, 14))

        # Mirrored into a plain attribute on the Tk thread, so the setup
        # worker thread never has to touch a Tk variable itself.
        self.model_index = DEFAULT_MODEL_INDEX
        self.model_var = tk.IntVar(value=DEFAULT_MODEL_INDEX)
        self.model_var.trace_add(
            "write", lambda *_: setattr(self, "model_index", self.model_var.get()))
        self.model_radios = []
        if self.offer_model:
            box = ttk.LabelFrame(frm, text="Transcription model", padding=(12, 8))
            box.pack(fill="x", pady=(0, 14))
            for i, (label, _repo) in enumerate(MODELS):
                rb = ttk.Radiobutton(box, text=label, value=i, variable=self.model_var)
                rb.pack(anchor="w", pady=1)
                self.model_radios.append(rb)
            ttk.Label(box, text="You can download the others from the app later.",
                      foreground=MUTED).pack(anchor="w", pady=(4, 0))

        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 10))

        self.status_var = tk.StringVar(value="Starting…")
        ttk.Label(frm, textvariable=self.status_var, foreground=MUTED
                  ).pack(anchor="w", pady=(0, 8))

        self.log = tk.Text(frm, height=10, font=("Monaco", 10),
                            bg=LOG_BG, fg=LOG_FG, relief="flat",
                            state="disabled", highlightthickness=0)
        self.log.pack(fill="both", expand=True)

        self.quit_btn = ttk.Button(frm, text="Quit", command=self._on_close)
        self.quit_btn.pack(anchor="e", pady=(10, 0))

    def _log(self, msg):
        def _do():
            self.log.config(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.config(state="disabled")
        self.root.after(0, _do)

    def _status(self, msg):
        self.root.after(0, self.status_var.set, msg)

    def _start(self):
        self.progress.start(12)
        threading.Thread(target=self._run_setup, daemon=True).start()

    def _run_setup(self):
        try:
            self._do_setup()
        except Exception as exc:
            self._fail(str(exc))
            return
        self.root.after(0, self._finish)

    def _do_setup(self):
        seed = seed_python(self.bundle)
        if not os.path.exists(seed):
            raise RuntimeError(f"Seed Python not found at {seed}")

        if not os.path.exists(VENV_PY):
            self._status("Creating environment…")
            self._log(f"→ {seed} -m venv {VENV_DIR}")
            self._run([seed, "-m", "venv", VENV_DIR])

        self._status("Installing transcription engine (this is the slow part)…")
        pip = [VENV_PY, "-m", "pip", "install", "--upgrade"]
        self._log("→ pip install " + " ".join(REQUIRED_PACKAGES))
        self._run(pip + ["pip"])
        self._run(pip + REQUIRED_PACKAGES)
        self._log(f"→ pip install --no-deps {MLX_WHISPER_PACKAGE}")
        self._run(pip + ["--no-deps", MLX_WHISPER_PACKAGE])

        self._status("Verifying installation…")
        r = subprocess.run([VENV_PY, "-c", IMPORT_CHECK], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                "Install finished but packages still aren't importable:\n"
                + r.stderr[-800:])

        if self.offer_model:
            self._download_model()

    def _download_model(self):
        index = self.model_index
        label, repo = MODELS[index]
        name = label.split("—")[0].strip()
        self.root.after(0, self._begin_download)
        self._status(f"Downloading the {name} model…")
        self._log(f"→ Downloading {repo}")

        def on_line(line):
            parts = line.split()
            if len(parts) == 3 and parts[0] == "PROGRESS":
                done, total = int(parts[1]), int(parts[2])
                self.root.after(0, self._set_progress, done, total, name)
                return True
            return False

        env = os.environ.copy()
        env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        # Hides the "unauthenticated requests… set a HF_TOKEN" warning:
        # public models don't need a token, and it reads like an error.
        env["HF_HUB_VERBOSITY"] = "error"
        try:
            self._run([VENV_PY, "-c", DOWNLOAD_SCRIPT, repo], on_line=on_line, env=env)
        except RuntimeError:
            # Not fatal: everything needed to run the app is installed, and
            # the model can be downloaded from the main window instead.
            self._log("⚠ Model download failed — you can download it from the app.")
            return
        save_model_choice(repo)
        self._log("✓ Model ready.")

    def _begin_download(self):
        for rb in self.model_radios:
            rb.state(["disabled"])
        self.progress.stop()
        self.progress.config(mode="determinate", maximum=1, value=0)

    def _set_progress(self, done, total, name):
        self.progress.config(maximum=max(total, 1), value=done)
        self.status_var.set(f"Downloading the {name} model — "
                            f"{human_size(done)} of {human_size(total)}")

    def _run(self, cmd, on_line=None, env=None):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, env=env)
        for line in proc.stdout:
            if on_line and on_line(line):
                continue
            if line.strip():
                self._log(line.rstrip())
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd[:3])}")

    def _finish(self):
        self.progress.stop()
        self._status("Done — launching…")
        self.root.after(400, lambda: (self.root.destroy(), launch(self.bundle)))

    def _fail(self, msg):
        def _do():
            self.progress.stop()
            self._status("Setup failed.")
            self._log(f"✗ {msg}")
            self.quit_btn.config(text="Close")
            messagebox.showerror(
                "Setup failed",
                "Whisper Transcriber couldn't finish setup.\n\n"
                "Check your internet connection and try reopening the app.\n\n"
                f"Details: {msg[:300]}")
        self.root.after(0, _do)

    def _on_close(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    bundle = bundle_dir()
    sync_app_files(bundle)
    if deps_ready():
        launch(bundle)
        return
    SetupWindow(bundle).run()


if __name__ == "__main__":
    main()
