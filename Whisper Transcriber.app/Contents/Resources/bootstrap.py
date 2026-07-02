#!/usr/bin/env python3
"""
Whisper Transcriber — bootstrap.

Runs under the Python.framework bundled inside the .app. On a clean Mac
this is the first code that executes: it seeds a private venv (so the
read-only, ad-hoc-signed .app bundle is never written to), installs
mlx-whisper and the other runtime packages into it, then execs into that
venv to run the real app. Subsequent launches skip straight to the exec
once everything is already installed — no Terminal, no Homebrew.
"""

import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

BG, TEXT, MUTED = "#f5f5f7", "#1d1d1f", "#86868b"
LOG_BG, LOG_FG = "#1e1e1e", "#d4d4d4"

REQUIRED_PACKAGES = ["mlx-whisper", "fpdf2", "python-docx", "sounddevice", "pyobjc-framework-Cocoa"]
IMPORT_CHECK = "import mlx_whisper, fpdf, docx, sounddevice, Foundation"

WHISPER_DIR = os.path.expanduser("~/Whisper")
VENV_DIR = os.path.join(WHISPER_DIR, "venv")
VENV_PY = os.path.join(VENV_DIR, "bin", "python3")
APP_PY = os.path.join(WHISPER_DIR, "whisper_transcriber.py")


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
        self.root = tk.Tk()
        self.root.title("Whisper Transcriber — Setup")
        self.root.configure(bg=BG)
        self.root.geometry("480x360")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        self.root.after(200, self._start)

    def _build(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, font=("Helvetica", 12))

        frm = ttk.Frame(self.root, padding=(24, 20))
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Setting up Whisper Transcriber",
                  font=("Helvetica", 16, "bold")).pack(anchor="w")
        ttk.Label(frm, text="One-time setup — this takes a minute or two.",
                  foreground=MUTED).pack(anchor="w", pady=(2, 14))

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
        self._log("→ pip install " + " ".join(REQUIRED_PACKAGES))
        self._run([VENV_PY, "-m", "pip", "install", "--upgrade", "pip"])
        self._run([VENV_PY, "-m", "pip", "install", "--upgrade"] + REQUIRED_PACKAGES)

        self._status("Verifying installation…")
        r = subprocess.run([VENV_PY, "-c", IMPORT_CHECK], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                "Install finished but packages still aren't importable:\n"
                + r.stderr[-800:])

    def _run(self, cmd):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            if line.strip():
                self._log(line.rstrip())
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")

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
