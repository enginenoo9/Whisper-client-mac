#!/usr/bin/env python3
"""
Whisper Transcriber — macOS GUI for mlx-whisper.
Batch transcription: queue multiple files and process them sequentially.
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# py2app sets sys.frozen; use Python API for all ML calls when bundled.
FROZEN = getattr(sys, "frozen", False)

# ── Palette ───────────────────────────────────────────────────────────────────
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

CONFIG_PATH = os.path.expanduser("~/Whisper/whisper_transcriber_config.json")
DEFAULT_MODEL_INDEX = 1


class WhisperApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Whisper Transcriber")
        self.root.geometry("680x710")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        self._setup_theme()

        self._file_queue: list[str] = []
        self.outdir       = tk.StringVar(value=os.path.expanduser("~/Desktop"))
        self.out_format   = tk.StringVar(value="txt")
        self.cleanup      = tk.BooleanVar(value=True)
        self.mlx_installed = FROZEN   # already bundled when frozen
        self.is_running   = False
        self._downloading = False

        self._cfg = self._load_config()
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

        if FROZEN:
            self._status("Ready.")
            self._refresh()
        else:
            self._check_install()

    # ── HF model cache ────────────────────────────────────────────────────────

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

    # ── Cleanup dialog ────────────────────────────────────────────────────────

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
        return [os.path.join(cache, nm) for nm in os.listdir(cache)
                if nm.startswith("models--mlx-community--whisper")]

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

        if not FROZEN:
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
        for d in self._model_dirs():
            shutil.rmtree(d, ignore_errors=True)
        try:
            os.remove(CONFIG_PATH)
        except OSError:
            pass
        venv = os.path.join(os.path.expanduser("~/Whisper"), "venv")
        try:
            subprocess.Popen(["/bin/bash", "-c", f"sleep 1; rm -rf '{venv}'"],
                             start_new_session=True)
        except Exception:
            pass
        self.root.destroy()

    # ── Setup / repair (non-bundled only) ─────────────────────────────────────

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
            subprocess.run(["open", path])
            self._log(f"→ Launched setup: {path}")
            self._status("Setup opened in Terminal — follow the prompts there.")
        except Exception as e:
            self._log(f"✗ Could not launch setup: {e}")

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_config(self):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self, *_):
        data = {
            "model":   self.model_combo.current(),
            "format":  self.out_format.get(),
            "outdir":  self.outdir.get(),
            "cleanup": self.cleanup.get(),
        }
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

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

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _setup_theme(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT,
                        fieldbackground="white", font=("Helvetica", 12))
        style.configure("TFrame",       background=BG)
        style.configure("TLabel",       background=BG, foreground=TEXT)
        style.configure("Title.TLabel", font=("Helvetica", 18, "bold"))
        style.configure("Sub.TLabel",   font=("Helvetica", 10), foreground=MUTED)
        style.configure("Muted.TLabel", font=("Helvetica", 11), foreground=MUTED)
        style.configure("Warn.TLabel",  font=("Helvetica", 11), foreground="#9a6700")
        style.configure("TButton",      font=("Helvetica", 12), padding=4)
        style.configure("Go.TButton",   font=("Helvetica", 13, "bold"), padding=6)
        style.configure("TRadiobutton", background=BG, foreground=TEXT,
                        font=("Helvetica", 11))
        style.map("TRadiobutton", background=[("active", BG)])
        style.configure("TCombobox",    padding=3)

    # ── Build UI ──────────────────────────────────────────────────────────────

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

        def add_label(text, row):
            ttk.Label(grid, text=text).grid(
                row=row, column=0, sticky="nw", pady=9)

        # Row 0 — Model
        add_label("Model", 0)
        self.model_combo = ttk.Combobox(grid, values=[m[0] for m in MODELS],
                                        state="readonly", width=34)
        self.model_combo.current(0)
        self.model_combo.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.download_btn = ttk.Button(grid, text="Download",
                                       command=self._download_model)
        self.download_btn.grid(row=0, column=2, padx=(8, 0))

        # Row 1 — File queue
        add_label("Files", 1)

        queue_cell = ttk.Frame(grid)
        queue_cell.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=6)

        self.file_listbox = tk.Listbox(
            queue_cell, height=4, font=("Monaco", 10),
            selectmode=tk.EXTENDED, activestyle="none",
            bg="white", fg=TEXT,
            selectbackground=ACCENT, selectforeground="white",
            relief="flat", borderwidth=0,
            highlightthickness=1,
            highlightcolor="#b0b0b0", highlightbackground="#d0d0d0",
        )
        sb = ttk.Scrollbar(queue_cell, orient="vertical",
                           command=self.file_listbox.yview)
        self.file_listbox.configure(yscrollcommand=sb.set)
        self.file_listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.file_listbox.bind("<Delete>",    lambda _: self._remove_selected())
        self.file_listbox.bind("<BackSpace>", lambda _: self._remove_selected())

        queue_btns = ttk.Frame(grid)
        queue_btns.grid(row=1, column=2, sticky="n", padx=(8, 0), pady=6)
        ttk.Button(queue_btns, text="Add Files…",
                   command=self._add_files).pack(fill="x", pady=(0, 4))
        ttk.Button(queue_btns, text="Remove",
                   command=self._remove_selected).pack(fill="x", pady=(0, 4))
        ttk.Button(queue_btns, text="Clear All",
                   command=self._clear_files).pack(fill="x")

        # Row 2 — Output directory
        add_label("Save to", 2)
        ttk.Label(grid, textvariable=self.outdir, style="Muted.TLabel"
                  ).grid(row=2, column=1, sticky="w", padx=(12, 0))
        ttk.Button(grid, text="Choose…", command=self._pick_outdir
                   ).grid(row=2, column=2, padx=(8, 0))

        # Row 3 — Output format
        add_label("Format", 3)
        fmt_row = ttk.Frame(grid)
        fmt_row.grid(row=3, column=1, columnspan=2, sticky="w",
                     padx=(12, 0), pady=6)
        for fmt in OUTPUT_FORMATS:
            ttk.Radiobutton(fmt_row, text=fmt.upper(), variable=self.out_format,
                            value=fmt).pack(side="left", padx=6)

        # Row 4 — Text cleanup
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
        self.log = tk.Text(main, height=7, font=("Monaco", 10),
                           bg=LOG_BG, fg=LOG_FG, relief="flat",
                           state="disabled", highlightthickness=0)
        self.log.pack(fill="x", pady=(2, 8))

        bottom = ttk.Frame(main)
        bottom.pack(fill="x", pady=(2, 0))
        self.status_var = tk.StringVar(
            value="Ready." if FROZEN else "Checking for mlx-whisper…")
        ttk.Label(bottom, textvariable=self.status_var,
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(bottom, text="Clean up…",
                   command=self._open_cleanup_dialog).pack(side="right")
        if not FROZEN:
            ttk.Button(bottom, text="Setup / Repair…",
                       command=self._run_setup).pack(side="right", padx=(0, 8))

    # ── Helpers ───────────────────────────────────────────────────────────────

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
        n = len(self._file_queue)
        ready = self.mlx_installed and n > 0 and not self.is_running
        if self.is_running:
            label = "Transcribing…"
        elif n == 1:
            label = "Transcribe 1 File"
        elif n > 1:
            label = f"Transcribe {n} Files"
        else:
            label = "Transcribe"
        self.root.after(0, lambda: self.transcribe_btn.config(
            state="normal" if ready else "disabled", text=label))

    def _current_model(self):
        return MODELS[self.model_combo.current()]

    def _highlight_queue_row(self, idx: int):
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(idx)
        self.file_listbox.see(idx)

    # ── Text cleanup ──────────────────────────────────────────────────────────

    @staticmethod
    def _reflow_text(text):
        lines = [ln.strip() for ln in text.splitlines()]
        joined = " ".join(ln for ln in lines if ln)
        joined = re.sub(r"\s+", " ", joined).strip()
        if not joined:
            return text
        sentences = re.split(r"(?<=[.!?])\s+", joined)
        paras, cur = [], []
        for s in sentences:
            cur.append(s)
            if len(cur) >= 4:
                paras.append(" ".join(cur))
                cur = []
        if cur:
            paras.append(" ".join(cur))
        return "\n\n".join(paras) + "\n"

    # ── Subtitle time formatters (API path) ───────────────────────────────────

    @staticmethod
    def _srt_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec % 1) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _vtt_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec % 1) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    # ── File queue ────────────────────────────────────────────────────────────

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select audio or video files",
            filetypes=[("Audio / Video",
                        "*.mp3 *.mp4 *.m4a *.wav *.flac *.aac *.ogg *.mkv *.webm"),
                       ("All files", "*.*")])
        for p in paths:
            if p not in self._file_queue:
                self._file_queue.append(p)
                self.file_listbox.insert(tk.END, os.path.basename(p))
        self._refresh()

    def _remove_selected(self):
        for i in reversed(self.file_listbox.curselection()):
            self.file_listbox.delete(i)
            del self._file_queue[i]
        self._refresh()

    def _clear_files(self):
        self._file_queue.clear()
        self.file_listbox.delete(0, tk.END)
        self._refresh()

    def _pick_outdir(self):
        path = filedialog.askdirectory(title="Choose where to save transcripts")
        if path:
            self.outdir.set(path)

    # ── ffmpeg / environment ──────────────────────────────────────────────────

    def _build_env(self):
        """Return an env dict with PATH that includes Homebrew and bundled ffmpeg."""
        env = os.environ.copy()
        extra = ["/opt/homebrew/bin", "/usr/local/bin"]
        if FROZEN:
            resource_path = os.environ.get("RESOURCEPATH", "")
            extra.insert(0, os.path.join(resource_path, "bin"))
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
        return env

    # ── Install check (non-bundled only) ──────────────────────────────────────

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

    # ── Model download ────────────────────────────────────────────────────────

    def _download_model(self):
        if not self.mlx_installed:
            self._log("✗ Install mlx-whisper first (click Install Now).")
            return

        label, repo = self._current_model()
        self._downloading = True
        self.root.after(0, lambda: self.download_btn.config(
            state="disabled", text="Downloading…"))
        self._status(f"Downloading {label.split('—')[0].strip()} model…")
        self._log(f"\n→ Downloading model: {repo}")
        self._log("  (cached after first download; large models take a while)")

        def _do():
            if FROZEN:
                # sys.executable is the app wrapper — call the library directly.
                try:
                    from huggingface_hub import snapshot_download  # noqa: PLC0415
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        snapshot_download(repo_id=repo)
                    for line in buf.getvalue().splitlines():
                        if line.strip():
                            self._log(line)
                    ok = True
                except Exception as exc:
                    self._log(f"✗ {exc}")
                    ok = False
            else:
                code = ("from huggingface_hub import snapshot_download;"
                        f"snapshot_download(repo_id='{repo}')")
                proc = subprocess.Popen([sys.executable, "-c", code],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True)
                for line in proc.stdout:
                    if line.strip():
                        self._log(line.rstrip())
                proc.wait()
                ok = proc.returncode == 0

            self._downloading = False
            if ok:
                self._log("✓ Model ready.")
                self._status("Model downloaded and ready.")
            else:
                self._log("✗ Model download failed — see log above.")
                self._status("Model download failed.")
            self.root.after(0, self._refresh_download_btn)

        threading.Thread(target=_do, daemon=True).start()

    # ── Transcription — API path (py2app bundle) ──────────────────────────────

    def _transcribe_via_api(self, file_path: str, model: str,
                            outdir: str, fmt: str) -> bool:
        """Use mlx_whisper Python API directly (required in py2app bundle)."""
        try:
            import mlx_whisper  # noqa: PLC0415
        except ImportError as exc:
            self._log(f"✗ mlx_whisper import failed: {exc}")
            return False

        self._log("  Transcribing… (streaming progress not available in bundled mode)")
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = mlx_whisper.transcribe(
                    file_path, path_or_hf_repo=model, verbose=True)
            for line in buf.getvalue().splitlines():
                if line.strip():
                    self._log(line)
        except Exception as exc:
            self._log(f"✗ {exc}")
            return False

        base     = os.path.splitext(os.path.basename(file_path))[0]
        text     = (result.get("text") or "").strip()
        segments = result.get("segments") or []

        if fmt in ("txt", "all"):
            content = self._reflow_text(text) if self.cleanup.get() else text + "\n"
            with open(os.path.join(outdir, base + ".txt"), "w", encoding="utf-8") as f:
                f.write(content)
            if self.cleanup.get():
                self._log("✓ Cleaned up line breaks in transcript.")

        if fmt in ("srt", "all"):
            with open(os.path.join(outdir, base + ".srt"), "w", encoding="utf-8") as f:
                for i, seg in enumerate(segments, 1):
                    f.write(f"{i}\n"
                            f"{self._srt_time(seg['start'])} --> "
                            f"{self._srt_time(seg['end'])}\n"
                            f"{seg['text'].strip()}\n\n")

        if fmt in ("vtt", "all"):
            with open(os.path.join(outdir, base + ".vtt"), "w", encoding="utf-8") as f:
                f.write("WEBVTT\n\n")
                for seg in segments:
                    f.write(f"{self._vtt_time(seg['start'])} --> "
                            f"{self._vtt_time(seg['end'])}\n"
                            f"{seg['text'].strip()}\n\n")
        return True

    # ── Transcription — CLI path (venv / dev) ─────────────────────────────────

    def _find_mlx_exe(self) -> str | None:
        venv_bin = os.path.dirname(sys.executable)
        for cand in (os.path.join(venv_bin, "mlx_whisper"),
                     shutil.which("mlx_whisper"),
                     shutil.which("mlx-whisper")):
            if cand and os.path.exists(cand):
                return cand
        return None

    def _cleanup_txt_output(self, file_path: str, outdir: str):
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

    def _transcribe_via_cli(self, file_path: str, model: str,
                            outdir: str, fmt: str,
                            mlx_exe: str, env: dict) -> bool:
        """Use the mlx_whisper CLI via subprocess (venv / dev mode)."""
        cmd = [mlx_exe, file_path, "--model", model,
               "--output-dir", outdir, "--output-format", fmt]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=env)
        for line in proc.stdout:
            self._log(line.rstrip())
        proc.wait()
        if proc.returncode == 0:
            if self.cleanup.get() and fmt in ("txt", "all"):
                self._cleanup_txt_output(file_path, outdir)
            return True
        return False

    # ── Batch transcription entry point ───────────────────────────────────────

    def _transcribe(self):
        if not self._file_queue:
            return

        _, model = self._current_model()
        outdir   = self.outdir.get()
        fmt      = self.out_format.get()
        files    = list(self._file_queue)
        n        = len(files)

        self.is_running = True
        self._refresh()
        self._status(f"Transcribing {n} file{'s' if n > 1 else ''}… please wait.")

        env     = self._build_env()
        mlx_exe = None if FROZEN else self._find_mlx_exe()

        def _do():
            if not shutil.which("ffmpeg", path=env["PATH"]):
                self.is_running = False
                self._log("✗ ffmpeg not found.")
                self._log("  Bundled ffmpeg is missing — reinstall the app."
                          if FROZEN else
                          "  Install it with:  brew install ffmpeg")
                self._status("ffmpeg required — see log.")
                self._refresh()
                return

            if not FROZEN and mlx_exe is None:
                self.is_running = False
                self._log("✗ mlx_whisper binary not found.")
                self._log("  Run Setup / Repair… to fix the installation.")
                self._status("mlx_whisper not found — run Setup / Repair.")
                self._refresh()
                return

            failed = []
            for i, file_path in enumerate(files, 1):
                name = os.path.basename(file_path)
                self._log(f"\n[{i}/{n}] {name}")
                self._log(f"  Model : {model}")
                self._log(f"  Format: {fmt}  →  {outdir}")
                self._status(f"[{i}/{n}] Transcribing {name}…")
                self.root.after(0, lambda idx=i - 1: self._highlight_queue_row(idx))

                if FROZEN:
                    ok = self._transcribe_via_api(file_path, model, outdir, fmt)
                else:
                    ok = self._transcribe_via_cli(
                        file_path, model, outdir, fmt, mlx_exe, env)

                if ok:
                    self._log(f"✓ Saved to: {outdir}")
                else:
                    self._log("✗ Failed.")
                    failed.append(name)

            self.is_running = False
            done = n - len(failed)

            if not failed:
                self._log(f"\n✓ All {n} file{'s' if n > 1 else ''} "
                          f"transcribed successfully.")
                self._status(
                    f"Done — {n} transcript{'s' if n > 1 else ''} saved to {outdir}")
                subprocess.run(["open", outdir])
            else:
                self._log(f"\n⚠  {done}/{n} succeeded. "
                          f"Failed: {', '.join(failed)}")
                self._status(f"{done}/{n} transcribed. {len(failed)} failed — see log.")

            self.root.after(0, self._refresh_download_btn)
            self._refresh()

        threading.Thread(target=_do, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    WhisperApp(root)
    root.mainloop()
