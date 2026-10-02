#!/usr/bin/env python3
"""
Whisper Transcriber — macOS GUI for mlx-whisper.

The UI is HTML/CSS/JS rendered inside a native macOS WebView (pywebview →
WKWebView). Tkinter can't produce a modern-looking Mac app no matter how
it's themed — its widget rendering tops out at a dated look — so the
presentation layer lives in the embedded HTML below, and all the actual
work (transcription, live capture, model download, file I/O) stays in
Python, exposed to the page through pywebview's JS bridge.

Batch transcription of files + chunk-based live microphone transcription.
Output formats: TXT, SRT, VTT, PDF, or DOCX.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from datetime import datetime

import webview

# ── Models & formats ──────────────────────────────────────────────────────────
MODELS = [
    ("Large V3 — Best accuracy (~3 GB)",   "mlx-community/whisper-large-v3-mlx"),
    ("Medium — Great balance (~1.5 GB)",   "mlx-community/whisper-medium-mlx"),
    ("Small — Fast (~460 MB)",             "mlx-community/whisper-small-mlx"),
    ("Base — Fastest (~145 MB)",           "mlx-community/whisper-base-mlx"),
]
MEDIA_EXTENSIONS = ["mp3", "mp4", "m4a", "wav", "flac", "aac", "ogg", "mkv", "webm",
                    "mov", "aiff", "aif", "opus", "wma", "m4v", "avi", "caf"]
OUTPUT_FORMATS      = ["txt", "srt", "vtt", "pdf", "docx"]
LIVE_OUTPUT_FORMATS = ["txt", "pdf", "docx"]

# Spoken-language choices: Whisper's code → name. Whisper knows ~100; this
# is the widely used subset, kept here rather than read from
# mlx_whisper.tokenizer because importing that pulls in MLX (~1.5 s).
LANGUAGES = [
    ("ar", "Arabic"), ("bn", "Bengali"), ("bg", "Bulgarian"), ("yue", "Cantonese"),
    ("ca", "Catalan"), ("zh", "Chinese"), ("hr", "Croatian"), ("cs", "Czech"),
    ("da", "Danish"), ("nl", "Dutch"), ("en", "English"), ("et", "Estonian"),
    ("tl", "Filipino (Tagalog)"), ("fi", "Finnish"), ("fr", "French"), ("de", "German"),
    ("el", "Greek"), ("gu", "Gujarati"), ("he", "Hebrew"), ("hi", "Hindi"),
    ("hu", "Hungarian"), ("is", "Icelandic"), ("id", "Indonesian"), ("it", "Italian"),
    ("ja", "Japanese"), ("ko", "Korean"), ("lv", "Latvian"), ("lt", "Lithuanian"),
    ("ms", "Malay"), ("mr", "Marathi"), ("no", "Norwegian"), ("fa", "Persian"),
    ("pl", "Polish"), ("pt", "Portuguese"), ("pa", "Punjabi"), ("ro", "Romanian"),
    ("ru", "Russian"), ("sr", "Serbian"), ("sk", "Slovak"), ("sl", "Slovenian"),
    ("es", "Spanish"), ("sw", "Swahili"), ("sv", "Swedish"), ("ta", "Tamil"),
    ("te", "Telugu"), ("th", "Thai"), ("tr", "Turkish"), ("uk", "Ukrainian"),
    ("ur", "Urdu"), ("vi", "Vietnamese"), ("cy", "Welsh"),
]
LANGUAGE_CODES = {code for code, _ in LANGUAGES}

# Live transcripts are written here as they're transcribed, so a crash or
# an accidental Close never loses a recording. Outside the venv, so
# "Uninstall everything" leaves them alone.
LIVE_AUTOSAVE_DIR = os.path.expanduser("~/Whisper/Live Transcripts")

# Keep these in sync with bootstrap.py and setup.command.
#
# mlx-whisper declares a dependency on torch, but only its model-conversion
# script uses it — transcription never imports it. torch (plus sympy, which
# it pulls in) is ~500 MB, about half the whole environment. So mlx-whisper
# is installed with --no-deps, pinned so a new release can't quietly start
# needing something that isn't listed, and its real runtime dependencies are
# listed here instead.
MLX_WHISPER_PACKAGE = "mlx-whisper==0.4.3"
REQUIRED_PACKAGES = ["mlx", "numba", "numpy", "scipy", "tiktoken", "tqdm",
                     "more-itertools", "huggingface_hub",
                     "fpdf2", "python-docx", "sounddevice",
                     "pyobjc-framework-Cocoa", "pywebview"]

PDF_UNICODE_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]

CONFIG_PATH =os.path.expanduser("~/Whisper/whisper_transcriber_config.json")
DEFAULT_MODEL_INDEX = 1


# ═══════════════════════════════════════════════════════════════════════════════
#  Front-end (HTML / CSS / JS rendered in the WebView)
# ═══════════════════════════════════════════════════════════════════════════════

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    color-scheme: light dark;  /* native controls & scrollbars follow too */
    --bg: #f5f5f7;
    --card: #ffffff;
    --text: #1d1d1f;
    --muted: #86868b;
    --border: #e3e3e6;
    --accent: #0071e3;
    --accent-hover: #0077ed;
    --accent-press: #0060c4;
    --accent-tint: rgba(0,113,227,.08);
    --on-accent: #ffffff;
    /* Neutral gray rather than a pale blue: white text on light blue read
       as washed-out and looked half-enabled. */
    --primary-disabled: #e8e8ed;
    --primary-disabled-fg: #8e8e93;
    --field: #ffffff;
    --hover: #f2f2f4;
    --control: #e3e3e6;        /* × hover, progress-bar track */
    --icon: #6e6e73;
    --disabled: #b0b0b5;
    --danger: #d70015;
    --green: #34c759;
    --rec: #ff3b30;
    --seg-bg: #ececef;
    --seg-on: #ffffff;
    --toggle-off: #d1d1d6;
    --knob: #ffffff;
    --banner-bg: #fff7e6; --banner-border: #ffe2a8; --banner-fg: #7a5c00;
    --log-bg: #1c1c1e;
    --log-fg: #d6d6d6;
    --scrim: rgba(0,0,0,.28);
    --shadow: 0 1px 3px rgba(0,0,0,.06), 0 8px 24px rgba(0,0,0,.05);
    --modal-shadow: 0 20px 60px rgba(0,0,0,.3);
  }
  /* Dark mode follows the macOS appearance setting. Colors track Apple's
     own dark palette (system blue #0a84ff, red #ff453a, grays). */
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1e1e1e;
      --card: #2a2a2c;
      --text: #f5f5f7;
      --muted: #98989d;
      --border: #3a3a3c;
      --accent: #0a84ff;
      --accent-hover: #2b93ff;
      --accent-press: #0071e3;
      --accent-tint: rgba(10,132,255,.16);
      --primary-disabled: #1f3f63;
      --primary-disabled-fg: rgba(255,255,255,.45);
      --field: #1f1f21;
      --hover: #353538;
      --control: #48484a;
      --icon: #a1a1a6;
      --disabled: #636366;
      --danger: #ff453a;
      --green: #30d158;
      --rec: #ff453a;
      --seg-bg: #1f1f21;
      --seg-on: #48484a;
      --toggle-off: #48484a;
      --knob: #f5f5f7;
      --banner-bg: #3a2e10; --banner-border: #6b5417; --banner-fg: #ffd479;
      --log-bg: #141414;
      --scrim: rgba(0,0,0,.5);
      --shadow: 0 1px 3px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.3);
      --modal-shadow: 0 20px 60px rgba(0,0,0,.6);
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
    background: var(--bg);
    color: var(--text);
    font-size: 14px;
    -webkit-font-smoothing: antialiased;
    user-select: none;
  }
  .wrap { max-width: 640px; margin: 0 auto; padding: 28px 28px 40px; }

  /* No big title: the window's title bar already says "Whisper Transcriber". */
  header { text-align: center; margin: -8px 0 16px; }
  header p  { color: var(--muted); font-size: 13px; margin: 0; }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    box-shadow: var(--shadow);
    padding: 20px 22px;
    margin-bottom: 16px;
  }

  .row { display: grid; grid-template-columns: 84px 1fr; align-items: center; gap: 12px; }
  .row + .row { margin-top: 12px; }
  .row > label.key { color: var(--muted); font-weight: 500; font-size: 13px; }
  .row .val { display: flex; align-items: center; gap: 10px; min-width: 0; }

  select, .btn {
    font-family: inherit; font-size: 14px;
    border-radius: 9px; border: 1px solid var(--border);
    background: var(--field); color: var(--text);
    padding: 9px 12px; cursor: pointer; transition: background .12s, border-color .12s, transform .04s;
  }
  select { flex: 1; min-width: 0; appearance: none;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path d='M3 4.5L6 7.5L9 4.5' stroke='%2386868b' stroke-width='1.4' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>");
    background-repeat: no-repeat; background-position: right 11px center; padding-right: 30px; }
  select:focus { outline: none; border-color: var(--accent); }
  input.text {
    flex: 1; min-width: 0; font-family: inherit; font-size: 14px;
    border-radius: 9px; border: 1px solid var(--border);
    background: var(--field); color: var(--text); padding: 9px 12px;
    user-select: text;
  }
  input.text::placeholder { color: var(--muted); }
  input.text:focus { outline: none; border-color: var(--accent); }

  .btn:hover { background: var(--hover); }
  .btn:active { transform: scale(.98); }
  .btn:disabled { color: var(--disabled); cursor: default; background: var(--field); }
  .btn.primary {
    background: var(--accent); color: var(--on-accent); border-color: var(--accent); font-weight: 600;
  }
  .btn.primary:hover { background: var(--accent-hover); }
  .btn.primary:active { background: var(--accent-press); }
  .btn.primary:disabled { background: var(--primary-disabled); border-color: var(--primary-disabled); color: var(--primary-disabled-fg); }
  .btn.small { padding: 7px 12px; font-size: 13px; }
  .btn.ghost { background: transparent; border-color: transparent; color: var(--accent); }
  .btn.ghost:hover { background: var(--accent-tint); }
  .btn.block { width: 100%; }

  .filecol { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
  /* Grows with its contents (a dropped folder can add dozens of files),
     then scrolls. The caps keep the whole page inside the default window
     height, so the footer never scrolls out of view — lower while the
     Details log is open, since that takes up the room. */
  #filelist { height: auto; min-height: 116px; max-height: 200px; }
  body.log-open #filelist { max-height: 116px; }
  .row.top { align-items: start; }
  .row.top > label.key { padding-top: 9px; }
  .filemeta { display: none; align-items: center; justify-content: space-between;
              color: var(--muted); font-size: 12px; padding: 0 4px; }
  .filemeta.show { display: flex; }
  .linkbtn { border: none; background: none; padding: 0; font: inherit; font-size: 12px;
             color: var(--accent); cursor: pointer; }
  .linkbtn:hover { text-decoration: underline; }
  .filelist {
    flex: 1; height: 116px; overflow-y: auto;
    border: 1px solid var(--border); border-radius: 10px; background: var(--field);
    padding: 6px;
  }
  .filelist .empty { color: var(--muted); font-size: 13px; padding: 34px 10px; text-align: center; }
  #filelist { transition: border-color .12s, background .12s; }
  body.dragging #filelist {
    border: 2px dashed var(--accent); background: var(--accent-tint); padding: 5px;
  }
  body.dragging #filelist .empty { color: var(--accent); }
  .filelist .item {
    display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 7px;
    font-size: 13px; cursor: default;
  }
  .filelist .item .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #filelist .item:hover { background: var(--hover); }
  #filelist .item .name { flex: 0 1 auto; }
  #filelist .item .folder { flex: 1 1 0; min-width: 40px; color: var(--muted); font-size: 12px;
                            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #filelist .item .rm {
    flex: none; width: 20px; height: 20px; border: none; border-radius: 50%; padding: 0;
    background: transparent; color: var(--icon); font-size: 16px; line-height: 20px;
    cursor: pointer; opacity: 0; transition: opacity .1s, background .1s;
  }
  #filelist .item:hover .rm, #filelist .item .rm:focus-visible { opacity: 1; }
  #filelist .item .st { flex: none; display: flex; align-items: center; gap: 6px;
                        font-size: 12px; color: var(--muted); white-space: nowrap; }
  #filelist .item .st.failed { color: var(--danger); }
  #filelist .item .st.cancelled { font-style: italic; }
  #filelist .item .bar { width: 64px; height: 4px; border-radius: 2px; background: var(--control);
                         overflow: hidden; }
  #filelist .item .bar > i { display: block; height: 100%; background: var(--accent);
                             transition: width .3s; }
  #filelist .item .pct { width: 30px; text-align: right; font-variant-numeric: tabular-nums; }
  #filelist .item .rm:hover { background: var(--control); color: var(--text); }
  .filebtns { display: flex; flex-direction: column; gap: 6px; }

  .path { color: var(--muted); font-size: 13px; white-space: nowrap; overflow: hidden;
          text-overflow: ellipsis; flex: 1; }

  .seg { display: inline-flex; background: var(--seg-bg); border-radius: 9px; padding: 2px; }
  .seg button {
    border: none; background: transparent; font: inherit; font-size: 13px;
    padding: 6px 14px; border-radius: 7px; cursor: pointer; color: var(--text);
    transition: background .12s;
  }
  .seg button.on { background: var(--seg-on); box-shadow: 0 1px 2px rgba(0,0,0,.12); font-weight: 600; }

  .toggle { position: relative; width: 40px; height: 24px; flex: none; }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle .slider {
    position: absolute; inset: 0; background: var(--toggle-off); border-radius: 999px; transition: background .18s;
  }
  .toggle .slider::before {
    content: ""; position: absolute; width: 20px; height: 20px; left: 2px; top: 2px;
    background: var(--knob); border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,.25); transition: transform .18s;
  }
  .toggle input:checked + .slider { background: var(--green); }
  .toggle input:checked + .slider::before { transform: translateX(16px); }
  .toggle-row { display: flex; align-items: center; gap: 10px; }
  .toggle-row .lbl, .val > .lbl { font-size: 13px; }
  .val > .lbl { white-space: nowrap; }

  .actions { display: flex; justify-content: center; gap: 12px; margin: 4px 0 16px; }
  .actions .btn { padding: 11px 26px; font-size: 15px; }

  .loglabel { color: var(--muted); font-size: 11px; font-weight: 600; letter-spacing: .06em;
              text-transform: uppercase; margin: 0 2px 6px; padding: 2px 0;
              border: none; background: none; font-family: inherit; cursor: pointer; }
  .loglabel:hover { color: var(--text); }
  .loglabel .chev { display: inline-block; width: 10px; transition: transform .12s; }
  .loglabel[aria-expanded="true"] .chev { transform: rotate(90deg); }
  .log[hidden] { display: none; }
  .log {
    background: var(--log-bg); color: var(--log-fg); border-radius: 12px;
    font-family: "SF Mono", Menlo, Monaco, monospace; font-size: 12px; line-height: 1.5;
    padding: 12px 14px; height: 130px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;
    user-select: text;
  }

  footer { display: flex; align-items: center; justify-content: space-between; margin-top: 14px; }
  footer .status { color: var(--muted); font-size: 13px; }
  footer .fbtns { display: flex; gap: 6px; }

  .banner {
    display: none; align-items: center; gap: 12px; background: var(--banner-bg); border: 1px solid var(--banner-border);
    color: var(--banner-fg); border-radius: 12px; padding: 12px 16px; margin-bottom: 16px; font-size: 13px;
  }
  .banner.show { display: flex; }
  .banner .btn { margin-left: auto; }

  /* Overlays (Live + Cleanup) */
  .overlay {
    display: none; position: fixed; inset: 0; background: var(--scrim);
    backdrop-filter: blur(4px); z-index: 10; align-items: center; justify-content: center;
  }
  .overlay.show { display: flex; }
  .modal {
    background: var(--card); border-radius: 18px; box-shadow: var(--modal-shadow);
    width: 540px; max-width: calc(100vw - 40px); padding: 24px 26px;
  }
  .modal h2 { margin: 0 0 4px; font-size: 20px; letter-spacing: -.01em; }
  .modal .sub { color: var(--muted); font-size: 13px; margin: 0 0 16px; }
  .modal .bar { display: flex; align-items: center; justify-content: space-between; gap: 12px;
                margin-bottom: 14px; flex-wrap: wrap; }
  .live-text {
    background: var(--field); border: 1px solid var(--border); border-radius: 12px;
    height: 220px; overflow-y: auto; padding: 12px 14px; font-size: 14px; line-height: 1.55;
    white-space: pre-wrap; word-break: break-word; user-select: text;
  }
  .live-text.empty { color: var(--muted); }
  .autosave { color: var(--muted); font-size: 12px; margin: 6px 2px 0; visibility: hidden; }
  .autosave.on { visibility: visible; }
  .mic { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px;
         visibility: hidden; }
  .mic.on { visibility: visible; }
  .meter { width: 120px; height: 6px; border-radius: 3px; background: var(--control); overflow: hidden; }
  .meter > i { display: block; height: 100%; width: 0; background: var(--green);
               transition: width .08s linear; }
  .modal .foot { display: flex; gap: 8px; margin-top: 16px; }
  .modal .foot .spacer { flex: 1; }
  .rec-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--rec); display: inline-block;
             margin-right: 6px; animation: pulse 1.1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <p>Local transcription · runs entirely on your Mac</p>
  </header>

  <div class="banner" id="banner">
    <span>⚠ mlx-whisper is not installed.</span>
    <button class="btn small" id="installBtn" onclick="installMlx()">Install Now</button>
  </div>

  <div class="card">
    <div class="row">
      <label class="key">Model</label>
      <div class="val">
        <select id="model" onchange="onModel()"></select>
        <button class="btn small" id="downloadBtn" onclick="downloadModel()">Download</button>
      </div>
    </div>

    <div class="row top">
      <label class="key">Files</label>
      <div class="val" style="align-items: stretch;">
        <div class="filecol">
          <div class="filelist" id="filelist"></div>
          <div class="filemeta" id="filemeta">
            <span id="filecount"></span>
            <button class="linkbtn" onclick="clearFiles()">Clear all</button>
          </div>
        </div>
        <div class="filebtns">
          <button class="btn small" onclick="addFiles()">Add Files…</button>
        </div>
      </div>
    </div>

    <div class="row">
      <label class="key">Save to</label>
      <div class="val">
        <span class="path" id="outdir"></span>
        <button class="btn small" onclick="chooseOutdir()">Choose…</button>
      </div>
    </div>

    <div class="row">
      <label class="key">Format</label>
      <div class="val"><div class="seg" id="format"></div></div>
    </div>

    <div class="row">
      <label class="key" for="language">Language</label>
      <div class="val">
        <select id="language" onchange="onLanguage()"></select>
        <label class="toggle"><input type="checkbox" id="translate" onchange="onTranslate()"
               aria-label="Translate to English"><span class="slider"></span></label>
        <span class="lbl">Translate to English</span>
      </div>
    </div>

    <div class="row">
      <label class="key" for="vocab">Vocabulary</label>
      <div class="val">
        <input type="text" class="text" id="vocab" spellcheck="false" maxlength="600"
               placeholder="Names and terms to spell right, e.g. Kubernetes, Dr. Nguyen"
               onchange="onVocab()"
               title="Whisper will favor these spellings. Separate with commas.">
      </div>
    </div>

    <div class="row">
      <label class="key">Cleanup</label>
      <div class="val toggle-row">
        <label class="toggle"><input type="checkbox" id="cleanup" onchange="onCleanup()"><span class="slider"></span></label>
        <span class="lbl">Merge segment breaks into flowing paragraphs</span>
      </div>
    </div>

    <div class="row">
      <label class="key">Timestamps</label>
      <div class="val toggle-row">
        <label class="toggle"><input type="checkbox" id="timestamps" onchange="onTimestamps()"><span class="slider"></span></label>
        <span class="lbl">Start each paragraph with its time, like [00:12:34]</span>
      </div>
    </div>
  </div>

  <div class="actions">
    <button class="btn primary" id="transcribeBtn" onclick="transcribeOrCancel()" disabled>Transcribe</button>
    <button class="btn" onclick="openLive()">Live Transcribe…</button>
  </div>

  <button class="loglabel" id="logToggle" onclick="toggleLog()" aria-expanded="false"
          aria-controls="log"><span class="chev">▸</span> Details</button>
  <div class="log" id="log" hidden></div>

  <footer>
    <span class="status" id="status">Starting…</span>
    <div class="fbtns">
      <button class="btn ghost small" onclick="runSetup()">Setup / Repair…</button>
      <button class="btn ghost small" onclick="openCleanup()">Clean up…</button>
    </div>
  </footer>
</div>

<!-- Live overlay -->
<div class="overlay" id="liveOverlay">
  <div class="modal">
    <h2>Live Transcription</h2>
    <p class="sub" id="liveModel"></p>
    <div class="bar">
      <div class="seg" id="liveFormat"></div>
      <div class="mic" id="mic" title="Microphone input level">
        Mic <div class="meter" role="meter" aria-label="Microphone level"
                 aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" id="meter"><i id="meterFill"></i></div>
      </div>
    </div>
    <p class="sub" id="liveStatus">Ready — click Start Recording to begin</p>
    <div class="live-text empty" id="liveText">Transcript will appear here…</div>
    <p class="autosave" id="autosave">Auto-saved as you go to ~/Whisper/Live Transcripts ·
      <button class="linkbtn" onclick="api().live_reveal_autosave()">Show in Finder</button></p>
    <div class="foot">
      <button class="btn primary" id="recBtn" onclick="toggleRec()">Start Recording</button>
      <button class="btn" onclick="liveCopy()">Copy</button>
      <button class="btn" onclick="liveClear()">Clear</button>
      <span class="spacer"></span>
      <button class="btn" id="liveSaveBtn" onclick="liveSave()" disabled>Save…</button>
      <button class="btn" onclick="closeLive()">Close</button>
    </div>
  </div>
</div>

<!-- Cleanup overlay -->
<div class="overlay" id="cleanupOverlay">
  <div class="modal">
    <h2>Clean up</h2>
    <p class="sub" id="cleanupInfo">Checking disk usage…</p>
    <div class="filelist" id="modelList" style="height: auto; max-height: 180px; margin-bottom: 14px;"></div>
    <div class="foot" style="flex-direction: column; align-items: stretch; gap: 8px;">
      <button class="btn block" onclick="uninstallAll()">Uninstall everything (models + packages)</button>
      <button class="btn ghost block" onclick="closeCleanup()">Cancel</button>
    </div>
  </div>
</div>

<script>
  var STATE = { models: [], formats: [], liveFormats: [], format: "txt",
                cleanup: true, modelIndex: 1, recording: false };

  function api() { return window.pywebview.api; }

  // A rejected api() promise with no .catch() fails completely silently —
  // that's exactly what hid the add-files bug. Route uncaught rejections
  // through here so a future one shows up instead of vanishing.
  function reportErr(e) { console.error(e); setStatus('Error — see Details or try again.'); }

  window.addEventListener('pywebviewready', function () {
    api().ready().then(function (s) {
      STATE.models = s.models; STATE.formats = s.formats; STATE.liveFormats = s.liveFormats;
      STATE.format = s.format; STATE.cleanup = s.cleanup; STATE.modelIndex = s.modelIndex;
      renderModels(); renderFormat(); renderLiveFormat(); renderLanguages(s.languages, s.language);
      document.getElementById('cleanup').checked = s.cleanup;
      document.getElementById('timestamps').checked = s.timestamps;
      document.getElementById('translate').checked = s.translate;
      document.getElementById('vocab').value = s.vocab;
      document.getElementById('outdir').textContent = s.outdir;
      setStatus(s.mlxInstalled ? "Ready." : "mlx-whisper not installed — click Install Now.");
      if (!s.mlxInstalled) document.getElementById('banner').classList.add('show');
      setDownloadBtn(s.modelCached ? {enabled:false, text:"Downloaded ✓"} : {enabled:true, text:"Download"});
      renderFiles([]);
    }).catch(reportErr);
  });

  function renderModels() {
    var sel = document.getElementById('model'); sel.innerHTML = '';
    STATE.models.forEach(function (m, i) {
      var o = document.createElement('option'); o.value = i; o.textContent = m;
      if (i === STATE.modelIndex) o.selected = true; sel.appendChild(o);
    });
  }
  function renderFormat() {
    var box = document.getElementById('format'); box.innerHTML = '';
    STATE.formats.forEach(function (f) {
      var b = document.createElement('button'); b.textContent = f.toUpperCase();
      if (f === STATE.format) b.className = 'on';
      b.onclick = function () { STATE.format = f; renderFormat(); api().set_format(f); };
      box.appendChild(b);
    });
  }
  function renderLanguages(langs, current) {
    var sel = document.getElementById('language'); sel.innerHTML = '';
    [{code: '', name: 'Detect automatically'}].concat(langs).forEach(function (l) {
      var o = document.createElement('option'); o.value = l.code; o.textContent = l.name;
      if (l.code === current) o.selected = true; sel.appendChild(o);
    });
  }
  function renderLiveFormat() {
    var box = document.getElementById('liveFormat'); box.innerHTML = '';
    STATE.liveFmt = STATE.liveFmt || STATE.liveFormats[0];
    STATE.liveFormats.forEach(function (f) {
      var b = document.createElement('button'); b.textContent = f.toUpperCase();
      if (f === STATE.liveFmt) b.className = 'on';
      b.onclick = function () { STATE.liveFmt = f; renderLiveFormat(); };
      box.appendChild(b);
    });
  }
  // A row's status in the current/last batch: Waiting, a progress bar
  // while it's transcribing, Show in Finder once done, or Failed.
  function fileStatus(r, i) {
    var s = document.createElement('span'); s.className = 'st';
    if (r.state === 'waiting') s.textContent = 'Waiting';
    else if (r.state === 'running') {
      s.innerHTML = '<span class="bar"><i style="width:' + r.pct + '%"></i></span>' +
                    '<span class="pct">' + r.pct + '%</span>';
      s.setAttribute('aria-label', 'Transcribing, ' + r.pct + ' percent');
    } else if (r.state === 'done') {
      var b = document.createElement('button'); b.className = 'linkbtn';
      b.textContent = 'Show in Finder';
      b.onclick = function () { api().reveal_output(i); };
      s.appendChild(b);
    } else if (r.state === 'failed') {
      s.className += ' failed'; s.textContent = 'Failed';
      s.title = 'See Details below for the error';
    } else if (r.state === 'cancelled') {
      s.className += ' cancelled'; s.textContent = 'Cancelled';
    } else return null;
    return s;
  }

  // rows: [{name, folder, path, state, pct}] from Api._file_rows().
  function renderFiles(rows) {
    STATE.files = rows;
    var box = document.getElementById('filelist'); box.innerHTML = '';
    var meta = document.getElementById('filemeta');
    meta.classList.toggle('show', rows.length > 0);
    document.getElementById('filecount').textContent =
      rows.length + (rows.length === 1 ? ' file' : ' files');
    if (!rows.length) { box.innerHTML = '<div class="empty">Drop audio or video files here</div>'; return; }
    rows.forEach(function (r, i) {
      var d = document.createElement('div'); d.className = 'item'; d.title = r.path;
      d.innerHTML = '<span class="name">' + escapeHtml(r.name) + '</span>' +
                    '<span class="folder">' + escapeHtml(r.folder) + '</span>';
      var st = fileStatus(r, i);
      if (st) d.appendChild(st);
      // No × on the file being transcribed: removing it wouldn't stop it.
      // An invisible spacer takes its place so the statuses stay aligned.
      var x = document.createElement('button'); x.className = 'rm'; x.textContent = '×';
      if (r.state === 'running') { x.style.visibility = 'hidden'; x.tabIndex = -1; x.setAttribute('aria-hidden', 'true'); }
      else {
        x.title = 'Remove'; x.setAttribute('aria-label', 'Remove ' + r.name + ' (' + r.folder + ')');
        x.onclick = function () { removeFile(i); };
      }
      d.appendChild(x);
      box.appendChild(d);
    });
  }
  // Drag and drop. The drop itself is handled in Python (Api.bind_drop),
  // which is the only place the files' full paths are available. Here we
  // just highlight the file list while something is dragged over the
  // window, and cancel dragover — without that, WebKit ignores the drop,
  // or navigates to the dropped file and replaces the whole UI with it.
  // dragenter/dragleave fire for every child element crossed, so count them.
  (function () {
    var depth = 0;
    function isFiles(e) { return e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types, 'Files') >= 0; }
    document.addEventListener('dragenter', function (e) {
      if (!isFiles(e)) return;
      depth++; document.body.classList.add('dragging');
    });
    document.addEventListener('dragleave', function (e) {
      if (!isFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) document.body.classList.remove('dragging');
    });
    document.addEventListener('dragover', function (e) {
      if (!isFiles(e)) return;
      e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
    });
    document.addEventListener('drop', function () {
      depth = 0; document.body.classList.remove('dragging');
    });
  })();

  function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  function onModel()   { STATE.modelIndex = parseInt(document.getElementById('model').value, 10);
                         document.getElementById('liveModel').textContent = 'Model: ' + STATE.models[STATE.modelIndex].split('—')[0].trim();
                         api().set_model(STATE.modelIndex); }
  function onCleanup() { STATE.cleanup = document.getElementById('cleanup').checked; api().set_cleanup(STATE.cleanup); }
  function onTimestamps() { api().set_timestamps(document.getElementById('timestamps').checked); }
  function onLanguage()   { api().set_language(document.getElementById('language').value); }
  function onTranslate()  { api().set_translate(document.getElementById('translate').checked); }
  // Bridge calls run concurrently, so a set_vocab fired by the field's
  // change event could land after a transcribe started by the same click.
  // Starting a job saves the vocabulary first and waits for it.
  function onVocab()      { return api().set_vocab(document.getElementById('vocab').value); }

  function addFiles()    { api().add_files().then(renderFiles).catch(reportErr); }
  function removeFile(i) { api().remove_files([i]).then(renderFiles).catch(reportErr); }
  function clearFiles()  { api().clear_files().then(renderFiles).catch(reportErr); }
  function chooseOutdir(){ api().choose_outdir().then(function (p) { document.getElementById('outdir').textContent = p; }).catch(reportErr); }
  function downloadModel(){ api().download_model(); }
  function transcribeOrCancel() {
    if (STATE.canCancel) api().cancel_transcribe();
    else onVocab().then(function () { return api().transcribe(); }).catch(reportErr);
  }
  function runSetup()    { api().run_setup(); }
  function installMlx()  { document.getElementById('installBtn').disabled = true;
                           document.getElementById('installBtn').textContent = 'Installing…'; api().install_mlx(); }

  // Live
  function openLive() {
    document.getElementById('liveModel').textContent = 'Model: ' + STATE.models[STATE.modelIndex].split('—')[0].trim();
    document.getElementById('liveOverlay').classList.add('show');
  }
  function closeLive() { if (STATE.recording) api().live_stop(); document.getElementById('liveOverlay').classList.remove('show'); }
  function toggleRec() {
    if (STATE.recording) { api().live_stop(); }
    else { onVocab().then(function () { return api().live_start(STATE.liveFmt); }).catch(reportErr); }
  }
  function liveCopy()  { var t = document.getElementById('liveText'); navigator.clipboard && navigator.clipboard.writeText(t.textContent); liveStatus('Copied to clipboard.'); }
  function liveClear() { api().live_clear(); setLiveText(''); document.getElementById('liveSaveBtn').disabled = true; }
  function liveSave()  { api().live_save(STATE.liveFmt); }

  // Cleanup
  function openCleanup()  { document.getElementById('cleanupOverlay').classList.add('show'); refreshCleanup(); }
  function refreshCleanup() {
    api().cleanup_info().then(function (s) {
      document.getElementById('cleanupInfo').textContent =
        s.count + ' model(s) downloaded — about ' + s.size + ' on disk.';
      renderModelList(s.models);
    }).catch(reportErr);
  }
  function renderModelList(models) {
    var box = document.getElementById('modelList'); box.innerHTML = '';
    var installed = models.filter(function (m) { return m.installed; });
    if (!installed.length) { box.innerHTML = '<div class="empty">No models downloaded</div>'; return; }
    installed.forEach(function (m) {
      var d = document.createElement('div'); d.className = 'item';
      d.innerHTML = '<span class="name" style="flex:1">' + escapeHtml(m.label) + '</span>';
      var b = document.createElement('button'); b.className = 'btn ghost small';
      b.textContent = 'Delete';
      b.onclick = function () { deleteModel(m.index); };
      d.appendChild(b);
      box.appendChild(d);
    });
  }
  function deleteModel(index) { api().delete_model(index).then(refreshCleanup).catch(reportErr); }
  function closeCleanup() { document.getElementById('cleanupOverlay').classList.remove('show'); }
  function uninstallAll() { if (confirm('Remove ALL models and Python packages, then quit?')) api().uninstall_everything(); }

  // ── Push targets (called from Python) ──
  function pushLog(t)      { var l = document.getElementById('log'); l.textContent += t + "\n";
                             if (/^\s*[✗⚠]/.test(t)) toggleLog(true);  // surface errors
                             l.scrollTop = l.scrollHeight; }
  function toggleLog(open) {
    var l = document.getElementById('log'), b = document.getElementById('logToggle');
    if (open === undefined) open = l.hidden;
    l.hidden = !open; b.setAttribute('aria-expanded', open ? 'true' : 'false');
    document.body.classList.toggle('log-open', open);
    if (open) l.scrollTop = l.scrollHeight;
  }
  function setStatus(t)    { document.getElementById('status').textContent = t; }
  function setDownloadBtn(o){ var b = document.getElementById('downloadBtn'); b.disabled = !o.enabled; b.textContent = o.text; }
  function setTranscribe(o){ var b = document.getElementById('transcribeBtn'); b.disabled = !o.enabled; b.textContent = o.label;
                             STATE.canCancel = o.cancel; b.classList.toggle('primary', !o.cancel); }
  function setAutosave(on) { document.getElementById('autosave').classList.toggle('on', on); }
  function setInstallDone(){ document.getElementById('banner').classList.remove('show'); }
  function setInstallRetry(){ var b = document.getElementById('installBtn'); b.disabled = false; b.textContent = 'Retry'; }
  function setLiveText(t)  { var e = document.getElementById('liveText');
                             if (t) { e.textContent = t; e.classList.remove('empty'); e.scrollTop = e.scrollHeight; }
                             else { e.textContent = 'Transcript will appear here…'; e.classList.add('empty'); } }
  function liveStatus(t)   { document.getElementById('liveStatus').innerHTML = t; }
  function setRecording(r) { STATE.recording = r;
                             document.getElementById('recBtn').textContent = r ? 'Stop Recording' : 'Start Recording';
                             document.getElementById('mic').classList.toggle('on', r);
                             if (!r) setLevel(0); }
  function setLevel(v)     { var p = Math.round(v * 100);
                             document.getElementById('meterFill').style.width = p + '%';
                             document.getElementById('meter').setAttribute('aria-valuenow', p); }
  function setLiveSave(on) { document.getElementById('liveSaveBtn').disabled = !on; }
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
#  Back-end (Python API exposed to the page)
# ═══════════════════════════════════════════════════════════════════════════════

class Api:
    def __init__(self):
        self.window = None
        self._file_queue: list[str] = []
        self._file_state: dict[str, dict] = {}  # path → {state, pct, output}
        self._cfg = self._load_config()
        self.outdir = self._cfg.get("outdir") if os.path.isdir(
            self._cfg.get("outdir", "")) else os.path.expanduser("~/Desktop")
        self.out_format = self._cfg.get("format") if self._cfg.get(
            "format") in OUTPUT_FORMATS else "txt"
        self.cleanup = bool(self._cfg.get("cleanup", True))
        self.timestamps = bool(self._cfg.get("timestamps", False))
        self.language = self._cfg.get("language") if self._cfg.get(
            "language") in LANGUAGE_CODES else ""  # "" = auto-detect
        self.translate = bool(self._cfg.get("translate", False))
        self.vocab = str(self._cfg.get("vocab", ""))
        self.model_index = self._cfg.get("model", DEFAULT_MODEL_INDEX)
        if not isinstance(self.model_index, int) or not (0 <= self.model_index < len(MODELS)):
            self.model_index = DEFAULT_MODEL_INDEX
        self.mlx_installed = False
        self.is_running = False
        self._cancel = threading.Event()
        self._proc = None  # the running mlx_whisper process, for Cancel
        self._downloading = False
        self._repairing = False
        # Live state
        self._live_recording = False
        self._live_stop = threading.Event()
        self._live_transcript = ""
        self._live_autosave = None  # this transcript's file in LIVE_AUTOSAVE_DIR

    # ── JS bridge helpers ─────────────────────────────────────────────────────

    def _js(self, fn, *args):
        if not self.window:
            return
        payload = ",".join(json.dumps(a) for a in args)
        try:
            self.window.evaluate_js(f"window.{fn}({payload})")
        except Exception:
            pass

    def _log(self, msg):     self._js("pushLog", msg)
    def _status(self, msg):  self._js("setStatus", msg)

    def _current_model(self):
        return MODELS[self.model_index]

    # ── Initial state ─────────────────────────────────────────────────────────

    def ready(self):
        # Synchronous: the returned mlxInstalled value must already be
        # correct, since the page only reads it once at startup to decide
        # whether to show the "not installed" banner — a backgrounded check
        # here previously raced ahead of that read, so a correct-but-late
        # result had no way to un-show a banner already shown from stale
        # data. (pywebview runs js_api calls off the main thread, so this
        # brief pip-show subprocess doesn't block the window.)
        self._check_install()
        return {
            "models":      [m[0] for m in MODELS],
            "formats":     OUTPUT_FORMATS,
            "liveFormats": LIVE_OUTPUT_FORMATS,
            "format":      self.out_format,
            "cleanup":     self.cleanup,
            "timestamps":  self.timestamps,
            "languages":   [{"code": c, "name": n} for c, n in LANGUAGES],
            "language":    self.language,
            "translate":   self.translate,
            "vocab":       self.vocab,
            "modelIndex":  self.model_index,
            "outdir":      self.outdir,
            "mlxInstalled": self.mlx_installed,
            "modelCached": self._model_is_cached(self._current_model()[1]),
        }

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self):
        data = {"model": self.model_index, "format": self.out_format,
                "outdir": self.outdir, "cleanup": self.cleanup,
                "timestamps": self.timestamps, "language": self.language,
                "translate": self.translate, "vocab": self.vocab}
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def set_model(self, index):
        self.model_index = int(index)
        self._save_config()
        repo = self._current_model()[1]
        if self._downloading == repo:
            btn = {"enabled": False, "text": "Downloading…"}
        elif self._model_is_cached(repo):
            btn = {"enabled": False, "text": "Downloaded ✓"}
        else:
            # Only one download at a time (download_model ignores clicks
            # while one is running), so don't offer the button until then.
            btn = {"enabled": not self._downloading, "text": "Download"}
        self._js("setDownloadBtn", btn)

    def set_format(self, fmt):
        if fmt in OUTPUT_FORMATS:
            self.out_format = fmt
            self._save_config()

    def set_cleanup(self, flag):
        self.cleanup = bool(flag)
        self._save_config()

    def set_timestamps(self, flag):
        self.timestamps = bool(flag)
        self._save_config()

    def set_language(self, code):
        self.language = code if code in LANGUAGE_CODES else ""
        self._save_config()

    def set_translate(self, flag):
        self.translate = bool(flag)
        self._save_config()

    def set_vocab(self, text):
        self.vocab = " ".join(str(text).split())  # one line, tidy spacing
        self._save_config()

    def _decode_opts(self):
        """Language / translate / vocabulary as mlx_whisper.transcribe()
        keyword arguments. The vocabulary goes in as Whisper's "initial
        prompt": text the model treats as what came just before the audio,
        so names and terms in it get spelled that way."""
        opts = {"task": "translate" if self.translate else "transcribe"}
        if self.language:
            opts["language"] = self.language
        if self.vocab:
            opts["initial_prompt"] = self.vocab
        return opts

    @staticmethod
    def _cli_args(opts):
        """_decode_opts() as mlx_whisper command-line flags. Joined with
        "=" so a vocabulary starting with "-" isn't read as a flag."""
        return [f"--{key.replace('_', '-')}={val}" for key, val in opts.items()]

    # ── File queue ────────────────────────────────────────────────────────────

    def add_files(self):
        # pywebview validates each filter description against
        # ^([\w ]+)\(...\)$ — word chars and spaces only. A "/" (as in the
        # previous "Audio / Video Files") fails that regex and raises
        # ValueError before the dialog even opens, which silently killed
        # this button (JS called it with .then() and no .catch()).
        types = ("Media Files (" + ";".join("*." + e for e in MEDIA_EXTENSIONS) + ")",
                 "All files (*.*)")
        try:
            result = self.window.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=True, file_types=types)
        except Exception as exc:
            self._log(f"✗ Couldn't open file picker: {exc}")
            return self._file_rows()
        self._queue_files(result or [])
        return self._file_rows()

    def _file_rows(self):
        """What the page shows for each queued file: its name, the folder
        it's in (so two "audio.m4a" rows from different folders can be told
        apart), and the full path, with ~ for the home folder, for the
        hover tooltip."""
        home = os.path.expanduser("~")
        rows = []
        for p in self._file_queue:
            parent = os.path.dirname(p)
            short = "~" + p[len(home):] if p.startswith(home + os.sep) else p
            st = self._file_state.get(p, {})
            rows.append({"name": os.path.basename(p),
                         "folder": "Home" if parent == home else os.path.basename(parent),
                         "path": short,
                         # "", "waiting", "running", "done" or "failed" — the
                         # file's progress in the current/last batch.
                         "state": st.get("state", ""),
                         "pct": st.get("pct", 0)})
        return rows

    def _push_files(self):
        self._js("renderFiles", self._file_rows())

    def _set_file_state(self, path, **fields):
        self._file_state.setdefault(path, {}).update(fields)
        self._push_files()

    def reveal_output(self, index):
        """Show in Finder: select the file's transcript in its folder."""
        index = int(index)
        if not (0 <= index < len(self._file_queue)):
            return
        out = self._file_state.get(self._file_queue[index], {}).get("output")
        if out and os.path.exists(out):
            subprocess.run(["open", "-R", out])
        else:
            self._status("That transcript isn't there anymore — it may have been moved.")

    def _queue_files(self, paths):
        added = 0
        for p in paths:
            if p not in self._file_queue:
                self._file_queue.append(p)
                added += 1
        self._refresh_transcribe()
        return added

    # ── Drag and drop ─────────────────────────────────────────────────────────

    def bind_drop(self):
        """Called once the page has loaded. WKWebView only hands over the
        full paths of dropped files when the drop is handled from Python —
        a drop listener in the page's own JS only sees bare file names."""
        try:
            from webview.dom import DOMEventHandler
            self.window.dom.document.events.drop += DOMEventHandler(
                self._on_drop, prevent_default=True, stop_propagation=True)
        except Exception as exc:
            self._log(f"(Drag and drop unavailable: {exc} — use Add Files… instead.)")

    def _on_drop(self, event):
        files = (event.get("dataTransfer") or {}).get("files") or []
        dropped = [f.get("pywebviewFullPath") for f in files]
        media, skipped = [], 0
        for p in filter(None, dropped):
            # Folders are searched for media files, including subfolders.
            if os.path.isdir(p):
                for root, dirs, names in os.walk(p):
                    dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                    for nm in sorted(names):
                        if self._is_media(nm):
                            media.append(os.path.join(root, nm))
            elif self._is_media(p):
                media.append(p)
            else:
                skipped += 1
        added = self._queue_files(media)
        self._js("renderFiles", self._file_rows())
        if skipped:
            self._log(f"(Skipped {skipped} dropped file{'s' if skipped != 1 else ''}"
                      f" that {'aren’t' if skipped != 1 else 'isn’t'} audio or video.)")
        if not added and not skipped:
            self._status("No new audio or video files in what was dropped.")

    @staticmethod
    def _is_media(path):
        return os.path.splitext(path)[1].lower().lstrip(".") in MEDIA_EXTENSIONS

    def remove_files(self, indices):
        for i in sorted((int(x) for x in indices), reverse=True):
            if 0 <= i < len(self._file_queue):
                self._file_state.pop(self._file_queue[i], None)
                del self._file_queue[i]
        self._refresh_transcribe()
        return self._file_rows()

    def clear_files(self):
        self._file_queue.clear()
        self._file_state.clear()
        self._refresh_transcribe()
        return self._file_rows()

    def choose_outdir(self):
        try:
            result = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        except Exception as exc:
            self._log(f"✗ Couldn't open folder picker: {exc}")
            return self.outdir
        if result:
            self.outdir = result[0]
            self._save_config()
        return self.outdir

    def open_output_folder(self):
        subprocess.run(["open", self.outdir])

    def _refresh_transcribe(self):
        # While a batch runs, the button turns into Cancel.
        if self.is_running:
            cancelling = self._cancel.is_set()
            self._js("setTranscribe", {"enabled": not cancelling, "cancel": True,
                                       "label": "Cancelling…" if cancelling else "Cancel"})
            return
        n = len(self._file_queue)
        ready = self.mlx_installed and n > 0
        if n == 1:
            label = "Transcribe 1 File"
        elif n > 1:
            label = f"Transcribe {n} Files"
        else:
            label = "Transcribe"
        self._js("setTranscribe", {"enabled": ready, "cancel": False, "label": label})

    # ── Install check / install ───────────────────────────────────────────────

    def _check_install(self):
        r = subprocess.run([sys.executable, "-m", "pip", "show", "mlx-whisper"],
                           capture_output=True)
        self.mlx_installed = r.returncode == 0
        if self.mlx_installed:
            self._js("setInstallDone")
            self._status("Ready.")
        else:
            self._status("mlx-whisper not installed — click Install Now.")
        self._refresh_transcribe()

    def _pip_install_all(self):
        """Install/upgrade every runtime package, streaming pip's output to
        the log. Returns True on success."""
        pip = [sys.executable, "-m", "pip", "install", "--upgrade"]
        for cmd in (pip + REQUIRED_PACKAGES, pip + ["--no-deps", MLX_WHISPER_PACKAGE]):
            self._log("→ " + " ".join(cmd[2:]))
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                if line.strip():
                    self._log(line.rstrip())
            proc.wait()
            if proc.returncode != 0:
                return False
        return True

    def install_mlx(self):
        self._status("Installing mlx-whisper — this may take a minute…")

        def _do():
            if self._pip_install_all():
                self.mlx_installed = True
                self._js("setInstallDone")
                self._log("✓ Installed successfully.")
                self._status("Ready.")
            else:
                self._log("✗ Install failed — see log above.")
                self._status("Installation failed — see Details.")
                self._js("setInstallRetry")
            self._refresh_transcribe()
        threading.Thread(target=_do, daemon=True).start()

    # ── HF model cache ────────────────────────────────────────────────────────

    def _hf_cache_dir(self):
        for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
            if os.environ.get(var):
                return os.environ[var]
        if os.environ.get("HF_HOME"):
            return os.path.join(os.environ["HF_HOME"], "hub")
        return os.path.expanduser("~/.cache/huggingface/hub")

    def _model_is_cached(self, repo):
        snaps = os.path.join(self._hf_cache_dir(),
                             "models--" + repo.replace("/", "--"), "snapshots")
        if not os.path.isdir(snaps):
            return False
        for snap in os.listdir(snaps):
            sd = os.path.join(snaps, snap)
            if os.path.isdir(sd):
                for _r, _d, files in os.walk(sd):
                    if files:
                        return True
        return False

    # Sizes and deletion go through huggingface_hub's own cache scanner
    # rather than walking models--*/ folders directly: huggingface_hub 2.0
    # moved file contents into a shared hub/blobs/ store that the per-model
    # folders only link to, so deleting a model's folder left its gigabytes
    # behind and measuring it reported a few KB. The scanner understands
    # both layouts.

    def _scan_cache(self):
        try:
            from huggingface_hub import scan_cache_dir
            return scan_cache_dir(self._hf_cache_dir())
        except Exception:
            return None  # no cache yet, or huggingface_hub not installed

    @staticmethod
    def _whisper_repos(info):
        if info is None:
            return []
        return [r for r in info.repos
                if r.repo_type == "model" and r.repo_id.startswith("mlx-community/whisper")]

    def _delete_cached(self, repo_ids):
        info = self._scan_cache()
        hashes = [rev.commit_hash for r in self._whisper_repos(info)
                  if r.repo_id in repo_ids for rev in r.revisions]
        if hashes:
            info.delete_revisions(*hashes).execute()

    @staticmethod
    def _human_size(n):
        n = float(n)
        for unit in ("B", "KB", "MB"):
            if n < 1024:
                return f"{n:.0f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"

    def cleanup_info(self):
        repos = {r.repo_id: r for r in self._whisper_repos(self._scan_cache())}
        models = []
        for i, (label, repo) in enumerate(MODELS):
            r = repos.get(repo)
            models.append({"index": i, "label": label, "installed": r is not None,
                           "size": self._human_size(r.size_on_disk) if r else None})
        return {"count": len(repos),
                "size": self._human_size(sum(r.size_on_disk for r in repos.values())),
                "models": models}

    def delete_model(self, index):
        # Synchronous on purpose: the Clean up list re-reads the cache as
        # soon as this call returns, so deleting in a background thread
        # could refresh the list before the model was actually gone.
        index = int(index)
        if not (0 <= index < len(MODELS)):
            return
        label, repo = MODELS[index]
        try:
            self._delete_cached({repo})
            self._log(f"✓ Deleted {label} from cache.")
            self._status("Model deleted — it'll re-download when next used.")
        except Exception as e:
            self._log(f"(could not remove {label}: {e})")
        if index == self.model_index:
            self.set_model(self.model_index)  # refresh download button

    def uninstall_everything(self):
        try:
            self._delete_cached({r.repo_id for r in self._whisper_repos(self._scan_cache())})
        except Exception:
            pass
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
        os._exit(0)

    # ── Setup / repair ────────────────────────────────────────────────────────

    def run_setup(self):
        # Repairs the venv in place with this same interpreter. This used to
        # open ~/Whisper/setup.command in Terminal, but DMG installs never
        # get that file (it's only copied from next to the .app, which in
        # /Applications has no siblings) and it requires Homebrew anyway —
        # so for most users the button did nothing.
        if self._repairing or self.is_running:
            return
        self._repairing = True
        self._status("Repairing — reinstalling packages…")
        self._log("\n→ Repairing installation…")

        def _do():
            ok = self._pip_install_all()
            self._repairing = False
            if ok:
                self._log("✓ Repair complete. Quit and reopen the app to load the updated packages.")
                self._status("Repair complete — restart the app.")
                self._check_install()
            else:
                self._log("✗ Repair failed — see log above. Check your internet connection.")
                self._status("Repair failed — see Details.")
        threading.Thread(target=_do, daemon=True).start()

    # ── Model download ────────────────────────────────────────────────────────

    def download_model(self):
        if not self.mlx_installed:
            self._log("✗ Install mlx-whisper first (click Install Now).")
            return
        if self._downloading:
            return
        label, repo = self._current_model()
        name = label.split("—")[0].strip()
        self._downloading = repo
        self._js("setDownloadBtn", {"enabled": False, "text": "Downloading…"})
        self._status(f"Downloading {name} model…")
        self._log(f"\n→ Downloading model: {repo}")

        def _do():
            # In-process rather than a pip-style subprocess: huggingface_hub's
            # tqdm bars redraw with \r, which came out as mangled lines in
            # the log, and its "set a HF_TOKEN" warning read like an error
            # (public models don't need a token). Silence both and report
            # progress in the status line instead, measured the same way the
            # setup window does it (see DOWNLOAD_SCRIPT in bootstrap.py).
            try:
                from huggingface_hub import HfApi, snapshot_download
                from huggingface_hub.utils import disable_progress_bars
                from huggingface_hub.utils import logging as hf_logging
                disable_progress_bars()
                hf_logging.set_verbosity_error()
                info = HfApi().model_info(repo, files_metadata=True)
                total = sum(s.size or 0 for s in info.siblings)
                baseline = self._cache_bytes()
                err = []

                def run():
                    try:
                        snapshot_download(repo_id=repo)
                    except Exception as exc:
                        err.append(exc)

                t = threading.Thread(target=run, daemon=True)
                t.start()
                while t.is_alive():
                    done = min(max(self._cache_bytes() - baseline, 0), total)
                    if total and self._current_model()[1] == repo:
                        self._js("setDownloadBtn", {"enabled": False,
                                 "text": f"Downloading {done * 100 // total}%"})
                    self._status(f"Downloading {name} model — "
                                 f"{self._human_size(done)} of {self._human_size(total)}")
                    t.join(0.5)
                if err:
                    raise err[0]
            except Exception as exc:
                self._downloading = False
                self._log(f"✗ Model download failed: {exc}")
                self._status("Model download failed — check your internet connection.")
                self.set_model(self.model_index)  # refresh download button
                return
            self._downloading = False
            self._log("✓ Model ready.")
            self._status(f"{name} model downloaded and ready.")
            self.set_model(self.model_index)  # refresh download button
        threading.Thread(target=_do, daemon=True).start()

    def _cache_bytes(self):
        """Total bytes in the HF cache, each file counted once (symlinks
        skipped, hardlinks deduplicated) so it works for both the old
        per-model layout and huggingface_hub 2.0's shared blob store."""
        n, seen = 0, set()
        for root, _dirs, files in os.walk(self._hf_cache_dir()):
            for f in files:
                try:
                    st = os.lstat(os.path.join(root, f))
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode) and (st.st_dev, st.st_ino) not in seen:
                    seen.add((st.st_dev, st.st_ino))
                    n += st.st_size
        return n

    # ── Text helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _reflow_text(text):
        lines = [ln.strip() for ln in text.splitlines()]
        joined = re.sub(r"\s+", " ", " ".join(ln for ln in lines if ln)).strip()
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

    def _write_pdf(self, text, base, outdir):
        try:
            from fpdf import FPDF
        except ImportError:
            self._log("✗ fpdf2 not installed. Run Setup / Repair… to install it.")
            return False
        try:
            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=20)
            pdf.add_page()
            pdf.set_margins(20, 20, 20)
            # fpdf2's built-in Helvetica is Latin-1 only — a single curly
            # apostrophe or any non-English transcript raises. Embed a
            # Unicode TTF that ships with macOS instead; it has no bold
            # face, so the title is just set larger.
            font = next((p for p in PDF_UNICODE_FONTS if os.path.exists(p)), None)
            if font:
                pdf.add_font("Body", fname=font)
                title_font, body_font = ("Body", ""), ("Body", "")
            else:
                title_font, body_font = ("Helvetica", "B"), ("Helvetica", "")
            pdf.set_font(*title_font, size=14)
            pdf.cell(0, 10, base, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
            pdf.set_font(*body_font, size=11)
            for para in text.split("\n\n"):
                if para.strip():
                    pdf.multi_cell(0, 6, para.strip())
                    pdf.ln(3)
            pdf.output(os.path.join(outdir, base + ".pdf"))
            return True
        except Exception as exc:
            self._log(f"✗ PDF error: {exc}")
            return False

    def _write_docx(self, text, base, outdir):
        try:
            from docx import Document
            from docx.shared import Inches, Pt
        except ImportError:
            self._log("✗ python-docx not installed. Run Setup / Repair… to install it.")
            return False
        try:
            doc = Document()
            for section in doc.sections:
                section.top_margin = Inches(1)
                section.bottom_margin = Inches(1)
                section.left_margin = Inches(1.25)
                section.right_margin = Inches(1.25)
            doc.add_heading(base, level=0)
            for para in text.split("\n\n"):
                if para.strip():
                    p = doc.add_paragraph(para.strip())
                    for run in p.runs:
                        run.font.size = Pt(11)
            doc.save(os.path.join(outdir, base + ".docx"))
            return True
        except Exception as exc:
            self._log(f"✗ DOCX error: {exc}")
            return False

    # ── ffmpeg / mlx CLI env ──────────────────────────────────────────────────

    def _build_env(self):
        env = os.environ.copy()
        extra = ["/opt/homebrew/bin", "/usr/local/bin"]
        bundle_resources = os.environ.get("WHISPER_BUNDLE_RESOURCES")
        if bundle_resources:
            extra.insert(0, os.path.join(bundle_resources, "bin"))
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
        # mlx_whisper fetches the model through huggingface_hub when it isn't
        # cached yet; keep its download bars and "set a HF_TOKEN" warning
        # out of the log (same as the Download button).
        env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        env["HF_HUB_VERBOSITY"] = "error"
        return env

    def _find_mlx_exe(self):
        venv_bin = os.path.dirname(sys.executable)
        for cand in (os.path.join(venv_bin, "mlx_whisper"),
                     shutil.which("mlx_whisper"),
                     shutil.which("mlx-whisper")):
            if cand and os.path.exists(cand):
                return cand
        return None

    # With --verbose False, mlx_whisper draws a tqdm bar counting audio
    # frames ("  42%|████  | 2280/5430 [00:05<00:07, 400.00frames/s]"). tqdm
    # redraws it with \r, which text-mode pipes turn into separate lines, so
    # each redraw arrives as its own line to parse.
    _FRAMES_RE = re.compile(r"(\d+)/(\d+) \[[^\]]*frames/s\]")

    def _run_mlx_cli(self, mlx_exe, file_path, model, out_dir, cli_fmt, env, base,
                     opts, on_progress=None):
        cmd = [mlx_exe, file_path, "--model", model, "--output-name", base,
               "--output-dir", out_dir, "--output-format", cli_fmt, "--verbose", "False"]
        cmd += self._cli_args(opts["decode"])
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=env)
        self._proc = proc
        if self._cancel.is_set():  # Cancel clicked just before _proc was set
            proc.terminate()
        for line in proc.stdout:
            m = self._FRAMES_RE.search(line)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                if on_progress and total:
                    on_progress(min(done * 100 // total, 100))
            elif line.strip():
                self._log(line.rstrip())
        proc.wait()
        self._proc = None
        return proc.returncode == 0

    @staticmethod
    def _timestamp(seconds):
        s = int(seconds)
        return f"[{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}]"

    @classmethod
    def _timestamped_text(cls, segments, cleanup):
        """Transcript text with [hh:mm:ss] start times, from mlx_whisper's
        JSON segments. With Cleanup on, segments are merged into paragraphs
        of about four sentences, like _reflow_text, each stamped with when
        it starts; with Cleanup off, every segment is its own line."""
        lines = [(seg.get("start", 0), " ".join(seg.get("text", "").split()))
                 for seg in segments]
        lines = [(t, s) for t, s in lines if s]
        if not cleanup:
            return "".join(f"{cls._timestamp(t)} {s}\n" for t, s in lines)
        paras, cur, start, sentences = [], [], 0, 0
        for t, s in lines:
            if not cur:
                start = t
            cur.append(s)
            sentences += len(re.findall(r"[.!?](?=\s|$)", s))
            if sentences >= 4:
                paras.append(f"{cls._timestamp(start)} {' '.join(cur)}")
                cur, sentences = [], 0
        if cur:
            paras.append(f"{cls._timestamp(start)} {' '.join(cur)}")
        return "\n\n".join(paras) + "\n"

    @staticmethod
    def _output_names(files):
        """Output base name for each queued file, unique within the batch.
        Transcripts are all written to one folder as "<name>.<format>", so
        two files that share a name — "Meeting 1/audio.m4a" and
        "Meeting 2/audio.m4a", or "talk.mp3" and "talk.mp4" — would
        otherwise overwrite each other; later ones become "audio (2)" etc.
        Compared case-insensitively, like the macOS filesystem."""
        used, names = set(), []
        for path in files:
            stem = os.path.splitext(os.path.basename(path))[0]
            name, k = stem, 1
            while name.lower() in used:
                k += 1
                name = f"{stem} ({k})"
            used.add(name.lower())
            names.append(name)
        return names

    def _transcribe_via_cli(self, file_path, model, outdir, fmt, mlx_exe, env, base,
                            opts, on_progress=None):
        cleanup = opts["cleanup"]
        # Timestamps need the segment times, which only mlx_whisper's JSON
        # output has, so that path builds the .txt itself as well.
        stamped = opts["timestamps"] and fmt in ("txt", "pdf", "docx")
        if fmt in ("pdf", "docx") or stamped:
            # If mlx_whisper wrote its "<base>.txt" straight into outdir, it
            # would collide with (silently overwrite, then delete) any real
            # standalone .txt output already sitting there for this file.
            # Generate the intermediate text in an isolated scratch dir
            # instead, so it can never touch a real file in the user's
            # chosen folder.
            cli_fmt = "json" if stamped else "txt"
            with tempfile.TemporaryDirectory() as tmpdir:
                if not self._run_mlx_cli(mlx_exe, file_path, model, tmpdir, cli_fmt, env,
                                         base, opts, on_progress):
                    return False
                tmp_out = os.path.join(tmpdir, base + "." + cli_fmt)
                if not os.path.exists(tmp_out):
                    return False
                with open(tmp_out, encoding="utf-8") as f:
                    if stamped:
                        text = self._timestamped_text(json.load(f).get("segments", []),
                                                      cleanup)
                    else:
                        text = f.read()
            if cleanup and not stamped:
                text = self._reflow_text(text)
                self._log("✓ Cleaned up line breaks in transcript.")
            if fmt == "txt":
                try:
                    with open(os.path.join(outdir, base + ".txt"), "w", encoding="utf-8") as f:
                        f.write(text)
                    return True
                except OSError as exc:
                    self._log(f"✗ Couldn't save transcript: {exc}")
                    return False
            return (self._write_pdf(text, base, outdir) if fmt == "pdf"
                    else self._write_docx(text, base, outdir))

        # txt / srt / vtt: mlx_whisper writes directly into outdir.
        if not self._run_mlx_cli(mlx_exe, file_path, model, outdir, fmt, env, base,
                                 opts, on_progress):
            return False
        if cleanup and fmt == "txt":
            txt_path = os.path.join(outdir, base + ".txt")
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, encoding="utf-8") as f:
                        original = f.read()
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(self._reflow_text(original))
                    self._log("✓ Cleaned up line breaks in transcript.")
                except Exception as e:
                    self._log(f"(Could not clean up text: {e})")
        return True

    # ── Batch transcription ───────────────────────────────────────────────────

    def transcribe(self):
        if not self._file_queue or self.is_running:
            return
        _, model = self._current_model()
        outdir, fmt = self.outdir, self.out_format
        files = list(self._file_queue)
        n = len(files)
        # Settings are fixed for the whole batch, even if changed meanwhile.
        opts = {"cleanup": self.cleanup, "timestamps": self.timestamps,
                "decode": self._decode_opts()}
        self._cancel.clear()
        self.is_running = True
        self._refresh_transcribe()
        self._status(f"Transcribing {n} file{'s' if n > 1 else ''}… please wait.")
        env = self._build_env()
        mlx_exe = self._find_mlx_exe()

        def _do():
            if not shutil.which("ffmpeg", path=env["PATH"]):
                self.is_running = False
                self._log("✗ ffmpeg not found.")
                self._log("  DMG install: reinstall the app. Source: brew install ffmpeg")
                self._status("ffmpeg required — see Details.")
                self._refresh_transcribe()
                return
            if mlx_exe is None:
                self.is_running = False
                self._log("✗ mlx_whisper binary not found. Run Setup / Repair…")
                self._status("mlx_whisper not found — run Setup / Repair.")
                self._refresh_transcribe()
                return

            # Every file in this batch starts as "waiting"; files added
            # while it runs have no state, so they don't look queued for it.
            self._file_state.clear()
            for p in files:
                self._file_state[p] = {"state": "waiting", "pct": 0}
            self._push_files()

            failed, skipped, done = [], 0, 0
            bases = self._output_names(files)
            for i, (file_path, base) in enumerate(zip(files, bases), 1):
                name = os.path.basename(file_path)
                if self._cancel.is_set():
                    break
                if file_path not in self._file_queue:
                    skipped += 1  # removed from the list before its turn
                    continue
                self._log(f"\n[{i}/{n}] {name}")
                self._log(f"  Model : {model}")
                self._log(f"  Format: {fmt}  →  {outdir}")
                self._status(f"Transcribing {name} ({i} of {n})…")
                self._set_file_state(file_path, state="running", pct=0)

                last = [0]

                def on_progress(pct, path=file_path):
                    if pct != last[0]:  # only redraw the list on a new percent
                        last[0] = pct
                        self._set_file_state(path, pct=pct)

                ok = self._transcribe_via_cli(file_path, model, outdir, fmt, mlx_exe, env,
                                              base, opts, on_progress)
                output = os.path.join(outdir, base + "." + fmt)
                if self._cancel.is_set() and not ok:
                    self._log(f"(Cancelled: {name})")
                    self._set_file_state(file_path, state="cancelled")
                    break
                if ok:
                    done += 1
                    self._log(f"✓ Saved to: {output}")
                    self._set_file_state(file_path, state="done", pct=100, output=output)
                else:
                    self._log(f"✗ Failed: {name}")
                    failed.append(name)
                    self._set_file_state(file_path, state="failed")

            self.is_running = False
            folder = os.path.basename(outdir.rstrip(os.sep)) or outdir
            if self._cancel.is_set():
                # Files that never got their turn go back to having no status.
                for p in files:
                    if self._file_state.get(p, {}).get("state") == "waiting":
                        self._file_state.pop(p)
                self._push_files()
                self._log("\nCancelled.")
                self._status(f"Cancelled — {done} transcript{'s' if done != 1 else ''} "
                             f"saved to {folder}." if done else "Cancelled.")
                self._cancel.clear()
            elif not failed and not done:
                self._status("Nothing transcribed — the files were removed from the list.")
            elif not failed:
                self._log(f"\n✓ {done} file{'s' if done != 1 else ''} transcribed successfully.")
                self._status(f"Done — {done} transcript{'s' if done != 1 else ''} "
                             f"saved to {folder}.")
            else:
                self._log(f"\n⚠  {done} of {done + len(failed)} succeeded. "
                          f"Failed: {', '.join(failed)}")
                self._status(f"{done} transcribed, {len(failed)} failed — see Details.")
            if skipped:
                self._log(f"({skipped} file{'s were' if skipped != 1 else ' was'} removed "
                          "from the list before its turn and skipped.)")
            self.set_model(self.model_index)
            self._refresh_transcribe()
        threading.Thread(target=_do, daemon=True).start()

    def cancel_transcribe(self):
        """Stop the batch: kill the file being transcribed (nothing is
        written for it) and skip the rest. Finished transcripts stay."""
        if not self.is_running or self._cancel.is_set():
            return
        self._cancel.set()
        self._status("Cancelling…")
        self._refresh_transcribe()
        proc = self._proc
        if proc:
            proc.terminate()

    # ── Live transcription ────────────────────────────────────────────────────

    CHUNK_SECS = 10
    SAMPLE_RATE = 16000

    def live_start(self, fmt):
        missing = []
        for mod in ("sounddevice", "mlx_whisper"):
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)
        if missing:
            self._js("liveStatus",
                     "Missing: " + " ".join(missing) + " — run Setup / Repair.")
            return
        self._live_fmt = fmt if fmt in LIVE_OUTPUT_FORMATS else "txt"
        self._live_recording = True
        self._live_stop.clear()
        self._js("setRecording", True)
        self._js("setLiveSave", False)
        self._js("liveStatus",
                 '<span class="rec-dot"></span>Recording… (first transcript in ~10 s)')
        threading.Thread(target=self._record_loop, daemon=True).start()

    def live_stop(self):
        self._live_recording = False
        self._live_stop.set()
        self._js("setRecording", False)
        self._js("liveStatus", "Finishing last chunk…")

    def live_clear(self):
        # The auto-saved file stays; the next words start a new one.
        self._live_transcript = ""
        self._live_autosave = None
        self._js("setAutosave", False)

    def _autosave_live(self):
        """Rewrite this transcript's file in LIVE_AUTOSAVE_DIR. Written to
        a temp file and renamed into place, so a crash mid-write can't
        leave a half-written transcript behind."""
        try:
            if not self._live_autosave:
                os.makedirs(LIVE_AUTOSAVE_DIR, exist_ok=True)
                stamp = datetime.now().strftime("%Y-%m-%d at %H.%M.%S")
                self._live_autosave = os.path.join(LIVE_AUTOSAVE_DIR,
                                                   f"Live Transcript {stamp}.txt")
            tmp = self._live_autosave + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(self._live_transcript + "\n")
            os.replace(tmp, self._live_autosave)
            self._js("setAutosave", True)
        except OSError as exc:
            self._js("liveStatus", f"Couldn't auto-save: {exc}")

    def live_reveal_autosave(self):
        if self._live_autosave and os.path.exists(self._live_autosave):
            subprocess.run(["open", "-R", self._live_autosave])
        else:
            subprocess.run(["open", LIVE_AUTOSAVE_DIR])

    def _record_loop(self):
        import sounddevice as sd
        import numpy as np
        import time
        buffer, last = [], time.monotonic()
        lock = threading.Lock()
        peak = [0.0]  # loudest block RMS since the meter last drew

        def cb(indata, frames, tinfo, status):
            block = indata[:, 0].copy()
            rms = float(np.sqrt(np.mean(block * block))) if len(block) else 0.0
            with lock:
                buffer.append(block)
                peak[0] = max(peak[0], rms)

        def meter():
            # Its own thread: the loop below transcribes each chunk inline,
            # which would freeze the meter for seconds at a time. RMS is
            # drawn on a -50…-10 dBFS scale, so normal speech sits around
            # the middle and room noise near the bottom.
            while not self._live_stop.wait(0.1):
                with lock:
                    rms, peak[0] = peak[0], 0.0
                db = 20 * np.log10(max(rms, 1e-6))
                self._js("setLevel", round(min(max((db + 50) / 40, 0.0), 1.0), 2))
            self._js("setLevel", 0)

        def take():
            # The audio callback runs on PortAudio's own thread. Without the
            # lock, a block appended between concatenating the buffer and
            # clearing it would be silently dropped.
            with lock:
                blocks = buffer[:]
                buffer.clear()
            return np.concatenate(blocks) if blocks else None

        try:
            with sd.InputStream(samplerate=self.SAMPLE_RATE, channels=1,
                                dtype="float32", callback=cb):
                threading.Thread(target=meter, daemon=True).start()
                while not self._live_stop.is_set():
                    now = time.monotonic()
                    if now - last >= self.CHUNK_SECS:
                        chunk = take()
                        last = now
                        if chunk is not None:
                            self._transcribe_chunk(chunk)
                    time.sleep(0.1)
            chunk = take()
            if chunk is not None:
                self._transcribe_chunk(chunk)
        except Exception as exc:
            self._js("liveStatus", f"Audio error: {exc}")

        words = len(self._live_transcript.split()) if self._live_transcript else 0
        self._js("liveStatus", f"Done — {words} word{'s' if words != 1 else ''} transcribed")
        if self._live_transcript:
            self._js("setLiveSave", True)

    def _transcribe_chunk(self, audio):
        import mlx_whisper
        import numpy as np
        if len(audio) < self.SAMPLE_RATE * 0.5:
            return
        # Whisper hallucinates repeated phrases — often literally looping
        # the last thing actually said — when fed near-silent audio. This
        # is a well-documented model failure mode, not a decoding bug.
        # Most likely to hit the short trailing chunk after Stop, which is
        # often mostly silence/pause. Gate on average amplitude before
        # ever handing the chunk to the model.
        if float(np.abs(audio).mean()) < 0.006:
            return
        try:
            result = mlx_whisper.transcribe(
                audio, path_or_hf_repo=self._current_model()[1], verbose=False,
                **self._decode_opts())
            text = (result.get("text") or "").strip()
            if text:
                sep = " " if self._live_transcript else ""
                self._live_transcript += sep + text
                self._js("setLiveText", self._live_transcript)
                self._autosave_live()
        except Exception as exc:
            self._js("liveStatus", f"Transcription error: {exc}")

    def live_save(self, fmt):
        text = self._live_transcript.strip()
        if not text:
            return
        fmt = fmt if fmt in LIVE_OUTPUT_FORMATS else "txt"
        base = "live_transcript_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "txt":
            try:
                with open(os.path.join(self.outdir, base + ".txt"), "w", encoding="utf-8") as f:
                    f.write(text)
                ok = True
            except OSError as exc:
                self._log(f"✗ Couldn't save transcript: {exc}")
                ok = False
        elif fmt == "pdf":
            ok = self._write_pdf(text, base, self.outdir)
        else:
            ok = self._write_docx(text, base, self.outdir)
        if not ok:
            self._js("liveStatus", "Save failed — see Details in the main window.")
            return
        self._js("liveStatus", f"Saved: {base}.{fmt}")
        subprocess.run(["open", self.outdir])


# ═══════════════════════════════════════════════════════════════════════════════
#  macOS integration + entry point
# ═══════════════════════════════════════════════════════════════════════════════

def _fix_macos_menu_bar_name():
    """The app execs into a bare venv Python outside Contents/MacOS/, so macOS
    can't trace the process back to Info.plist for the menu bar app name.
    Override the in-memory bundle dict Cocoa reads when drawing the menu."""
    try:
        from Foundation import NSBundle
        NSBundle.mainBundle().infoDictionary()["CFBundleName"] = "Whisper Transcriber"
    except Exception:
        pass


def _system_is_dark():
    """Whether macOS is currently in Dark Mode (also true while "Auto" is
    in its dark phase). The page itself follows the appearance through
    prefers-color-scheme, live; this only picks the window's background
    color for the moment before the page has drawn, so a dark-mode launch
    doesn't flash light."""
    try:
        from Foundation import NSUserDefaults
        style = NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle")
        return style == "Dark"
    except Exception:
        return False


def main():
    api = Api()
    _fix_macos_menu_bar_name()
    window = webview.create_window(
        "Whisper Transcriber", html=HTML, js_api=api,
        width=700, height=880, min_size=(640, 720),
        background_color="#1e1e1e" if _system_is_dark() else "#f5f5f7")
    api.window = window
    window.events.loaded += api.bind_drop
    webview.start()


if __name__ == "__main__":
    main()
