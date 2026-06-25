#!/usr/bin/env python3
"""
Whisper Transcriber — macOS GUI for mlx-whisper.
ttk 'clam' theme so colors render correctly regardless of macOS dark/light mode.
Includes a per-model Download button to pre-fetch models on demand.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import sys
import os
import shutil
import json
import re

# ---- fixed palette ----------------------------------------------------------
BG     = "#f0f0f0"
TEXT   = "#1a1a1a"
MUTED  = "#666666"
ACCENT = "#0071e3"
LOG_BG = "#1e1e1e"
LOG_FG = "#d4d4d4"

MODELS = [
    ("Large V3  — Best accuracy  (~3 GB)",  "mlx-community/whisper-large-v3-mlx"),
    ("Medium    — Great balance  (~1.5 GB)", "mlx-community/whisper-medium-mlx"),
    ("Small     — Fast           (~460 MB)", "mlx-community/whisper-small-mlx"),
    ("Base      — Fastest        (~145 MB)", "mlx-community/whisper-base-mlx"),
]
OUTPUT_FORMATS = ["txt", "srt", "vtt", "all"]

# Remembers the user's last model / format / output folder across launches.
CONFIG_PATH = os.path.expanduser("~/Whisper/whisper_transcriber_config.json")
DEFAULT_MODEL_INDEX = 1  # Medium


class WhisperApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Whisper Transcriber")
        self.root.geometry("680x600")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        self._setup_theme()

        self.selected_file = tk.StringVar(value="No file selected")
        self.outdir        = tk.StringVar(value=os.path.expanduser("~/Desktop"))
        self.out_format    = tk.StringVar(value="txt")
        self.cleanup       = tk.BooleanVar(value=True)
        self.mlx_installed = False
        self.is_running    = False
        self._downloading  = False
        self._full_path    = None

        self._cfg = self._load_config()
        # apply saved output dir / format before building widgets
        if self._cfg.get("outdir") and os.path.isdir(self._cfg["outdir"]):
            self.outdir.set(self._cfg["outdir"])
        if self._cfg.get("format") in OUTPUT_FORMATS:
            self.out_format.set(self._cfg["format"])
        if "cleanup" in self._cfg:
            self.cleanup.set(bool(self._cfg["cleanup"]))

        self._build()
        self._apply_saved_model()
        self._wire_persistence()
        self._refresh_download_btn()
        self._check_install()

    # ----------------------------------------------- model cache detection
    def _hf_cache_dir(self):
        for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
            if os.environ.get(var):
                return os.environ[var]
        if os.environ.get("HF_HOME"):
            return os.path.join(os.environ["HF_HOME"], "hub")
        return os.path.expanduser("~/.cache/huggingface/hub")

    def _model_is_cached(self, repo):
        folder = "models--" + repo.replace("/", "--")
        snaps = os.path.join(self._hf_cache_dir(), folder, "snapshots")
        if not os.path.isdir(snaps):
            return False
        for snap in os.listdir(snaps):
            sd = os.path.join(snaps, snap)
            if os.path.isdir(sd):
                for _root, _dirs, files in os.walk(sd):
                    if files:
                        return True
        return False

    def _refresh_download_btn(self, *_):
        if self._downloading:
            return
        repo = self._current_model()[1]
        if self._model_is_cached(repo):
            self.download_btn.config(state="disabled", text="Downloaded ✓")
        else:
            self.download_btn.config(state="normal", text="Download")

    # ------------------------------------------------------------ cleanup
    @staticmethod
    def _human_size(n):
        n = float(n)
        for unit in ("B", "KB", "MB"):
            if n < 1024:
                return f"{n:.0f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"

    def _model_dirs(self):
        cache = self._hf_cache_dir()
        if not os.path.isdir(cache):
            return []
        return [os.path.join(cache, n) for n in os.listdir(cache)
                if n.startswith("models--mlx-community--whisper")]

    def _disk_usage_models(self):
        total = 0
        for d in self._model_dirs():
            for root, _dirs, files in os.walk(d):
                for fn in files:
                    fp = os.path.join(root, fn)
                    try:
                        if not os.path.islink(fp):
                            total += os.path.getsize(fp)
                    except OSError:
                        pass
        return total

    def _open_cleanup_dialog(self):
        size_h = self._human_size(self._disk_usage_models())
        n_models = len(self._model_dirs())

        win = tk.Toplevel(self.root)
        win.title("Clean Up")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=22)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Clean up Whisper Transcriber",
                  style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(frm,
                  text=f"{n_models} model(s) downloaded — about {size_h} on disk.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 14))

        ttk.Button(frm, text=f"Delete downloaded models  ({size_h})",
                   command=lambda: (win.destroy(), self._delete_models())
                   ).pack(fill="x", pady=(0, 2))
        ttk.Label(frm, text="Removes the AI models only. They re-download on next use.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 12))

        ttk.Button(frm, text="Uninstall everything (models + packages)",
                   command=lambda: (win.destroy(), self._full_uninstall())
                   ).pack(fill="x", pady=(0, 2))
        ttk.Label(frm,
                  text="Removes models and all Python packages, then quits.\n"
                       "Double-click setup again to reinstall.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 12))

        ttk.Button(frm, text="Cancel", command=win.destroy).pack()

    def _delete_models(self):
        def _do():
            removed = 0
            for d in self._model_dirs():
                try:
                    shutil.rmtree(d)
                    removed += 1
                except Exception as e:
                    self._log(f"(could not remove {os.path.basename(d)}: {e})")
            self._log(f"✓ Deleted {removed} model(s) from cache.")
            self._status("Models deleted — they'll re-download when next used.")
            self.root.after(0, self._refresh_download_btn)
        threading.Thread(target=_do, daemon=True).start()

    def _full_uninstall(self):
        if not messagebox.askyesno(
                "Uninstall everything",
                "This removes ALL downloaded models and the Python packages, "
                "then quits the app.\n\n"
                "You'll need to run setup again to use it. Continue?"):
            return
        # remove models + saved config immediately
        for d in self._model_dirs():
            shutil.rmtree(d, ignore_errors=True)
        try:
            os.remove(CONFIG_PATH)
        except OSError:
            pass
        # the app is running from venv/bin/python, so schedule the venv
        # deletion to happen a moment after this process exits, then quit.
        venv = os.path.join(os.path.expanduser("~/Whisper"), "venv")
        try:
            subprocess.Popen(["/bin/bash", "-c", f"sleep 1; rm -rf '{venv}'"],
                             start_new_session=True)
        except Exception:
            pass
        self.root.destroy()

    # -------------------------------------------------------- setup / repair
    def _setup_script_path(self):
        try:
            here = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            here = os.path.expanduser("~/Whisper")
        for cand in (os.path.join(here, "setup.command"),
                     os.path.expanduser("~/Whisper/setup.command")):
            if os.path.exists(cand):
                return cand
        return None

    def _run_setup(self):
        path = self._setup_script_path()
        if not path:
            self._log("✗ setup.command not found (expected in ~/Whisper).")
            self._status("setup.command not found.")
            return
        try:
            subprocess.run(["open", path])  # .command opens in Terminal
            self._log(f"→ Launched setup: {path}")
            self._status("Setup opened in Terminal — follow the prompts there.")
        except Exception as e:
            self._log(f"✗ Could not launch setup: {e}")

    # ----------------------------------------------------------- persistence
    def _load_config(self):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self, *_):
        data = {
            "model":  self.model_combo.current(),
            "format": self.out_format.get(),
            "outdir": self.outdir.get(),
            "cleanup": self.cleanup.get(),
        }
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(data, f)
        except Exception:
            pass  # never block the UI on a config write

    def _apply_saved_model(self):
        idx = self._cfg.get("model", DEFAULT_MODEL_INDEX)
        if not isinstance(idx, int) or not (0 <= idx < len(MODELS)):
            idx = DEFAULT_MODEL_INDEX
        self.model_combo.current(idx)

    def _wire_persistence(self):
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_change)
        self.out_format.trace_add("write", self._save_config)
        self.outdir.trace_add("write", self._save_config)
        self.cleanup.trace_add("write", self._save_config)

    def _on_model_change(self, *_):
        self._save_config()
        self._refresh_download_btn()

    # ------------------------------------------------------------- ttk theme
    def _setup_theme(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT,
                        fieldbackground="white", font=("Helvetica", 12))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Title.TLabel", font=("Helvetica", 18, "bold"))
        style.configure("Sub.TLabel", font=("Helvetica", 10), foreground=MUTED)
        style.configure("Muted.TLabel", font=("Helvetica", 11), foreground=MUTED)
        style.configure("Warn.TLabel", font=("Helvetica", 11), foreground="#9a6700")
        style.configure("TButton", font=("Helvetica", 12), padding=4)
        style.configure("Go.TButton", font=("Helvetica", 13, "bold"), padding=6)
        style.configure("TRadiobutton", background=BG, foreground=TEXT,
                        font=("Helvetica", 11))
        style.map("TRadiobutton", background=[("active", BG)])
        style.configure("TCombobox", padding=3)

    # ------------------------------------------------------------------ build
    def _build(self):
        main = ttk.Frame(self.root, padding=(28, 18))
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Whisper Transcriber",
                  style="Title.TLabel").pack(pady=(0, 2))
        ttk.Label(main, text="Local transcription • runs entirely on your Mac",
                  style="Sub.TLabel").pack(pady=(0, 12))

        self.install_frame = ttk.Frame(main)
        ttk.Label(self.install_frame, text="⚠  mlx-whisper is not installed.",
                  style="Warn.TLabel").pack(side="left", padx=(0, 8))
        self.install_btn = ttk.Button(self.install_frame, text="Install Now",
                                      command=self._install)
        self.install_btn.pack(side="left")

        grid = ttk.Frame(main)
        grid.pack(fill="x", pady=(4, 4))
        grid.columnconfigure(1, weight=1)

        def add_label(text, r):
            ttk.Label(grid, text=text).grid(row=r, column=0, sticky="w", pady=9)

        # Model + Download button
        add_label("Model", 0)
        self.model_combo = ttk.Combobox(grid, values=[m[0] for m in MODELS],
                                        state="readonly", width=34)
        self.model_combo.current(0)
        self.model_combo.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.download_btn = ttk.Button(grid, text="Download",
                                       command=self._download_model)
        self.download_btn.grid(row=0, column=2, padx=(8, 0))

        add_label("Audio file", 1)
        ttk.Label(grid, textvariable=self.selected_file, style="Muted.TLabel"
                  ).grid(row=1, column=1, sticky="w", padx=(12, 0))
        ttk.Button(grid, text="Choose…", command=self._pick_file
                   ).grid(row=1, column=2, padx=(8, 0))

        add_label("Save to", 2)
        ttk.Label(grid, textvariable=self.outdir, style="Muted.TLabel"
                  ).grid(row=2, column=1, sticky="w", padx=(12, 0))
        ttk.Button(grid, text="Choose…", command=self._pick_outdir
                   ).grid(row=2, column=2, padx=(8, 0))

        add_label("Format", 3)
        fmt_row = ttk.Frame(grid)
        fmt_row.grid(row=3, column=1, columnspan=2, sticky="w", padx=(12, 0), pady=6)
        for fmt in OUTPUT_FORMATS:
            ttk.Radiobutton(fmt_row, text=fmt.upper(), variable=self.out_format,
                            value=fmt).pack(side="left", padx=6)

        add_label("Cleanup", 4)
        ttk.Checkbutton(grid,
                        text="Merge segment breaks into flowing paragraphs",
                        variable=self.cleanup
                        ).grid(row=4, column=1, columnspan=2, sticky="w",
                               padx=(12, 0), pady=6)

        self.transcribe_btn = ttk.Button(main, text="Transcribe",
                                         command=self._transcribe,
                                         style="Go.TButton", state="disabled")
        self.transcribe_btn.pack(pady=14)

        ttk.Label(main, text="Progress",
                  font=("Helvetica", 10, "bold")).pack(anchor="w")
        self.log = tk.Text(main, height=9, font=("Monaco", 10),
                           bg=LOG_BG, fg=LOG_FG, relief="flat",
                           state="disabled", highlightthickness=0)
        self.log.pack(fill="x", pady=(2, 8))

        bottom = ttk.Frame(main)
        bottom.pack(fill="x", pady=(2, 0))
        self.status_var = tk.StringVar(value="Checking for mlx-whisper…")
        ttk.Label(bottom, textvariable=self.status_var,
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(bottom, text="Clean up…",
                   command=self._open_cleanup_dialog).pack(side="right")
        ttk.Button(bottom, text="Setup / Repair…",
                   command=self._run_setup).pack(side="right", padx=(0, 8))

    # ---------------------------------------------------------------- helpers
    def _log(self, msg):
        def _do():
            self.log.config(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.config(state="disabled")
        self.root.after(0, _do)

    def _status(self, msg):
        self.root.after(0, self.status_var.set, msg)

    def _refresh(self):
        ok = (self.mlx_installed and self._full_path and not self.is_running)
        self.root.after(0, lambda: self.transcribe_btn.config(
            state="normal" if ok else "disabled"))

    def _current_model(self):
        return MODELS[self.model_combo.current()]

    # --------------------------------------------------------- text cleanup
    @staticmethod
    def _reflow_text(text):
        """Merge per-segment line breaks into readable flowing paragraphs."""
        # join all non-empty lines into one stream, normalize whitespace
        lines = [ln.strip() for ln in text.splitlines()]
        joined = " ".join(ln for ln in lines if ln)
        joined = re.sub(r"\s+", " ", joined).strip()
        if not joined:
            return text
        # split into sentences (keep the punctuation), group into paragraphs
        sentences = re.split(r"(?<=[.!?])\s+", joined)
        paras, cur = [], []
        for s in sentences:
            cur.append(s)
            if len(cur) >= 4:                 # ~4 sentences per paragraph
                paras.append(" ".join(cur))
                cur = []
        if cur:
            paras.append(" ".join(cur))
        return "\n\n".join(paras) + "\n"

    def _cleanup_txt_output(self, file_path, outdir):
        """Reflow the .txt mlx-whisper wrote for this input, in place."""
        base = os.path.splitext(os.path.basename(file_path))[0]
        txt_path = os.path.join(outdir, base + ".txt")
        if not os.path.exists(txt_path):
            return
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                original = f.read()
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(self._reflow_text(original))
            self._log("✓ Cleaned up line breaks in transcript.")
        except Exception as e:
            self._log(f"(Could not clean up text: {e})")

    # ------------------------------------------------------------ file pickers
    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Select audio or video file",
            filetypes=[("Audio / Video",
                        "*.mp3 *.mp4 *.m4a *.wav *.flac *.aac *.ogg *.mkv *.webm"),
                       ("All files", "*.*")])
        if path:
            self._full_path = path
            self.selected_file.set(os.path.basename(path))
            self._refresh()

    def _pick_outdir(self):
        path = filedialog.askdirectory(title="Choose where to save the transcript")
        if path:
            self.outdir.set(path)

    # ----------------------------------------------------------- install check
    def _check_install(self):
        def _check():
            r = subprocess.run([sys.executable, "-m", "pip", "show", "mlx-whisper"],
                               capture_output=True)
            self.mlx_installed = r.returncode == 0
            if self.mlx_installed:
                self._status("Ready.")
            else:
                self.root.after(0, lambda: self.install_frame.pack(pady=(0, 8)))
                self._status("mlx-whisper not installed — click Install Now.")
            self._refresh()
        threading.Thread(target=_check, daemon=True).start()

    def _install(self):
        self.root.after(0, lambda: self.install_btn.config(
            state="disabled", text="Installing…"))
        self._status("Installing mlx-whisper — this may take a minute…")

        def _do():
            self._log("→ pip install mlx-whisper")
            r = subprocess.run([sys.executable, "-m", "pip", "install", "mlx-whisper"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                self.mlx_installed = True
                self.root.after(0, self.install_frame.pack_forget)
                self._log("✓ Installed successfully.")
                self._status("Ready.")
            else:
                self._log("✗ Failed:\n" + r.stderr[:500])
                self._status("Installation failed — see log.")
                self.root.after(0, lambda: self.install_btn.config(
                    state="normal", text="Retry"))
            self._refresh()
        threading.Thread(target=_do, daemon=True).start()

    # -------------------------------------------------------- model download
    def _download_model(self):
        if not self.mlx_installed:
            self._log("✗ Install mlx-whisper first (click Install Now).")
            self._status("Install mlx-whisper before downloading a model.")
            return

        label, repo = self._current_model()
        self._downloading = True
        self.root.after(0, lambda: self.download_btn.config(
            state="disabled", text="Downloading…"))
        self._status(f"Downloading {label.split('—')[0].strip()} model…")
        self._log(f"\n→ Downloading model: {repo}")
        self._log("  (cached after first download; large models take a while)")

        code = ("from huggingface_hub import snapshot_download;"
                f"snapshot_download(repo_id='{repo}')")

        def _do():
            proc = subprocess.Popen([sys.executable, "-c", code],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._log(line)
            proc.wait()
            self._downloading = False
            if proc.returncode == 0:
                self._log("✓ Model ready.")
                self._status("Model downloaded and ready.")
            else:
                self._log("✗ Model download failed — see log above.")
                self._status("Model download failed.")
            self.root.after(0, self._refresh_download_btn)
        threading.Thread(target=_do, daemon=True).start()

    # --------------------------------------------------------------- transcribe
    def _transcribe(self):
        file_path = self._full_path
        if not file_path:
            return
        label, model = self._current_model()
        outdir = self.outdir.get()
        fmt    = self.out_format.get()

        self.is_running = True
        self._refresh()
        self.root.after(0, lambda: self.transcribe_btn.config(text="Transcribing…"))
        self._status(f"Transcribing {os.path.basename(file_path)} — please wait…")

        self._log(f"\n→ File  : {os.path.basename(file_path)}")
        self._log(f"  Model : {model}")
        self._log(f"  Format: {fmt}  →  {outdir}\n")

        # mlx_whisper installs a CLI script next to the running python
        # (e.g. ~/Whisper/venv/bin/mlx_whisper). Prefer that; fall back to PATH.
        venv_bin = os.path.dirname(sys.executable)
        mlx_exe = None
        for cand in (os.path.join(venv_bin, "mlx_whisper"),
                     shutil.which("mlx_whisper"),
                     shutil.which("mlx-whisper")):
            if cand and os.path.exists(cand):
                mlx_exe = cand
                break
        cmd = [mlx_exe, file_path, "--model", model,
               "--output-dir", outdir, "--output-format", fmt]

        # Apps launched from Finder/Automator get a minimal PATH that omits
        # Homebrew, so ffmpeg (needed by mlx-whisper to decode audio) isn't
        # found. Ensure the common Homebrew bin dirs are on PATH for the child.
        env = os.environ.copy()
        extra_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
        env["PATH"] = os.pathsep.join(extra_paths + [env.get("PATH", "")])

        # Verify ffmpeg is reachable before launching mlx-whisper.
        if not shutil.which("ffmpeg", path=env["PATH"]):
            self.is_running = False
            self._log("✗ ffmpeg not found. Install it with:  brew install ffmpeg")
            self._status("ffmpeg is required — run 'brew install ffmpeg'.")
            self.root.after(0, lambda: self.transcribe_btn.config(text="Transcribe"))
            self._refresh()
            return

        def _do():
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, env=env)
            for line in proc.stdout:
                self._log(line.rstrip())
            proc.wait()
            self.is_running = False
            if proc.returncode == 0:
                if self.cleanup.get() and fmt in ("txt", "all"):
                    self._cleanup_txt_output(file_path, outdir)
                self._log(f"\n✓ Done!  Saved to: {outdir}")
                self._status(f"Done — transcript saved to {outdir}")
                subprocess.run(["open", outdir])
            else:
                self._log("✗ Failed — check the log above.")
                self._status("Transcription failed.")
            self.root.after(0, lambda: self.transcribe_btn.config(text="Transcribe"))
            self.root.after(0, self._refresh_download_btn)
            self._refresh()
        threading.Thread(target=_do, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    WhisperApp(root)
    root.mainloop()
