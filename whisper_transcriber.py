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
OUTPUT_FORMATS      = ["txt", "srt", "vtt", "pdf", "docx"]
LIVE_OUTPUT_FORMATS = ["txt", "pdf", "docx"]

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
    --bg: #f5f5f7;
    --card: #ffffff;
    --text: #1d1d1f;
    --muted: #86868b;
    --border: #e3e3e6;
    --accent: #0071e3;
    --accent-press: #0060c4;
    --field: #ffffff;
    --log-bg: #1c1c1e;
    --log-fg: #d6d6d6;
    --shadow: 0 1px 3px rgba(0,0,0,.06), 0 8px 24px rgba(0,0,0,.05);
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

  header { text-align: center; margin-bottom: 22px; }
  header h1 { font-size: 27px; font-weight: 700; letter-spacing: -.02em; margin: 0; }
  header p  { color: var(--muted); font-size: 13px; margin: 4px 0 0; }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    box-shadow: var(--shadow);
    padding: 20px 22px;
    margin-bottom: 16px;
  }

  .row { display: grid; grid-template-columns: 84px 1fr; align-items: center; gap: 12px; }
  .row + .row { margin-top: 16px; }
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

  .btn:hover { background: #f5f5f7; }
  .btn:active { transform: scale(.98); }
  .btn:disabled { color: #b0b0b5; cursor: default; background: var(--field); }
  .btn.primary {
    background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600;
  }
  .btn.primary:hover { background: #0077ed; }
  .btn.primary:active { background: var(--accent-press); }
  .btn.primary:disabled { background: #a9cbf2; border-color: #a9cbf2; color: #fff; }
  .btn.small { padding: 7px 12px; font-size: 13px; }
  .btn.ghost { background: transparent; border-color: transparent; color: var(--accent); }
  .btn.ghost:hover { background: rgba(0,113,227,.08); }
  .btn.block { width: 100%; }

  .filelist {
    flex: 1; height: 116px; overflow-y: auto;
    border: 1px solid var(--border); border-radius: 10px; background: var(--field);
    padding: 6px;
  }
  .filelist .empty { color: var(--muted); font-size: 13px; padding: 34px 10px; text-align: center; }
  .filelist .item {
    display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 7px;
    font-size: 13px; cursor: default;
  }
  .filelist .item.sel { background: var(--accent); color: #fff; }
  .filelist .item .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .filebtns { display: flex; flex-direction: column; gap: 6px; }

  .path { color: var(--muted); font-size: 13px; white-space: nowrap; overflow: hidden;
          text-overflow: ellipsis; flex: 1; }

  .seg { display: inline-flex; background: #ececef; border-radius: 9px; padding: 2px; }
  .seg button {
    border: none; background: transparent; font: inherit; font-size: 13px;
    padding: 6px 14px; border-radius: 7px; cursor: pointer; color: var(--text);
    transition: background .12s;
  }
  .seg button.on { background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.12); font-weight: 600; }

  .toggle { position: relative; width: 40px; height: 24px; flex: none; }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle .slider {
    position: absolute; inset: 0; background: #d1d1d6; border-radius: 999px; transition: background .18s;
  }
  .toggle .slider::before {
    content: ""; position: absolute; width: 20px; height: 20px; left: 2px; top: 2px;
    background: #fff; border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,.25); transition: transform .18s;
  }
  .toggle input:checked + .slider { background: #34c759; }
  .toggle input:checked + .slider::before { transform: translateX(16px); }
  .toggle-row { display: flex; align-items: center; gap: 10px; }
  .toggle-row .lbl { font-size: 13px; }

  .actions { display: flex; justify-content: center; gap: 12px; margin: 4px 0 16px; }
  .actions .btn { padding: 11px 26px; font-size: 15px; }

  .loglabel { color: var(--muted); font-size: 11px; font-weight: 600; letter-spacing: .06em;
              text-transform: uppercase; margin: 0 2px 6px; }
  .log {
    background: var(--log-bg); color: var(--log-fg); border-radius: 12px;
    font-family: "SF Mono", Menlo, Monaco, monospace; font-size: 12px; line-height: 1.5;
    padding: 12px 14px; height: 150px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;
    user-select: text;
  }

  footer { display: flex; align-items: center; justify-content: space-between; margin-top: 14px; }
  footer .status { color: var(--muted); font-size: 13px; }
  footer .fbtns { display: flex; gap: 6px; }

  .banner {
    display: none; align-items: center; gap: 12px; background: #fff7e6; border: 1px solid #ffe2a8;
    color: #7a5c00; border-radius: 12px; padding: 12px 16px; margin-bottom: 16px; font-size: 13px;
  }
  .banner.show { display: flex; }
  .banner .btn { margin-left: auto; }

  /* Overlays (Live + Cleanup) */
  .overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.28);
    backdrop-filter: blur(4px); z-index: 10; align-items: center; justify-content: center;
  }
  .overlay.show { display: flex; }
  .modal {
    background: var(--card); border-radius: 18px; box-shadow: 0 20px 60px rgba(0,0,0,.3);
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
  .modal .foot { display: flex; gap: 8px; margin-top: 16px; }
  .modal .foot .spacer { flex: 1; }
  .rec-dot { width: 9px; height: 9px; border-radius: 50%; background: #ff3b30; display: inline-block;
             margin-right: 6px; animation: pulse 1.1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Whisper Transcriber</h1>
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

    <div class="row">
      <label class="key">Files</label>
      <div class="val" style="align-items: stretch;">
        <div class="filelist" id="filelist"></div>
        <div class="filebtns">
          <button class="btn small" onclick="addFiles()">Add Files…</button>
          <button class="btn small" onclick="removeFiles()">Remove</button>
          <button class="btn small" onclick="clearFiles()">Clear All</button>
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
      <label class="key">Cleanup</label>
      <div class="val toggle-row">
        <label class="toggle"><input type="checkbox" id="cleanup" onchange="onCleanup()"><span class="slider"></span></label>
        <span class="lbl">Merge segment breaks into flowing paragraphs</span>
      </div>
    </div>
  </div>

  <div class="actions">
    <button class="btn primary" id="transcribeBtn" onclick="transcribe()" disabled>Transcribe</button>
    <button class="btn" onclick="openLive()">Live Transcribe…</button>
  </div>

  <div class="loglabel">Progress</div>
  <div class="log" id="log"></div>

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
    </div>
    <p class="sub" id="liveStatus">Ready — click Start Recording to begin</p>
    <div class="live-text empty" id="liveText">Transcript will appear here…</div>
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
                cleanup: true, modelIndex: 1, sel: [], recording: false };

  function api() { return window.pywebview.api; }

  // A rejected api() promise with no .catch() fails completely silently —
  // that's exactly what hid the add-files bug. Route uncaught rejections
  // through here so a future one shows up instead of vanishing.
  function reportErr(e) { console.error(e); setStatus('Error — see log or try again.'); }

  window.addEventListener('pywebviewready', function () {
    api().ready().then(function (s) {
      STATE.models = s.models; STATE.formats = s.formats; STATE.liveFormats = s.liveFormats;
      STATE.format = s.format; STATE.cleanup = s.cleanup; STATE.modelIndex = s.modelIndex;
      renderModels(); renderFormat(); renderLiveFormat();
      document.getElementById('cleanup').checked = s.cleanup;
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
  function renderFiles(names) {
    STATE.files = names; STATE.sel = [];
    var box = document.getElementById('filelist'); box.innerHTML = '';
    if (!names.length) { box.innerHTML = '<div class="empty">No files added yet</div>'; return; }
    names.forEach(function (n, i) {
      var d = document.createElement('div'); d.className = 'item';
      d.innerHTML = '<span class="name">' + escapeHtml(n) + '</span>';
      d.onclick = function () { toggleSel(i, d); };
      box.appendChild(d);
    });
  }
  function toggleSel(i, el) {
    var p = STATE.sel.indexOf(i);
    if (p >= 0) { STATE.sel.splice(p, 1); el.classList.remove('sel'); }
    else { STATE.sel.push(i); el.classList.add('sel'); }
  }
  function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  function onModel()   { STATE.modelIndex = parseInt(document.getElementById('model').value, 10);
                         document.getElementById('liveModel').textContent = 'Model: ' + STATE.models[STATE.modelIndex].split('—')[0].trim();
                         api().set_model(STATE.modelIndex); }
  function onCleanup() { STATE.cleanup = document.getElementById('cleanup').checked; api().set_cleanup(STATE.cleanup); }

  function addFiles()    { api().add_files().then(renderFiles).catch(reportErr); }
  function removeFiles() { api().remove_files(STATE.sel).then(renderFiles).catch(reportErr); }
  function clearFiles()  { api().clear_files().then(renderFiles).catch(reportErr); }
  function chooseOutdir(){ api().choose_outdir().then(function (p) { document.getElementById('outdir').textContent = p; }).catch(reportErr); }
  function downloadModel(){ api().download_model(); }
  function transcribe()  { api().transcribe(); }
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
    else { api().live_start(STATE.liveFmt); }
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
  function pushLog(t)      { var l = document.getElementById('log'); l.textContent += t + "\n"; l.scrollTop = l.scrollHeight; }
  function setStatus(t)    { document.getElementById('status').textContent = t; }
  function setDownloadBtn(o){ var b = document.getElementById('downloadBtn'); b.disabled = !o.enabled; b.textContent = o.text; }
  function setTranscribe(o){ var b = document.getElementById('transcribeBtn'); b.disabled = !o.enabled; b.textContent = o.label; }
  function setInstallDone(){ document.getElementById('banner').classList.remove('show'); }
  function setInstallRetry(){ var b = document.getElementById('installBtn'); b.disabled = false; b.textContent = 'Retry'; }
  function setLiveText(t)  { var e = document.getElementById('liveText');
                             if (t) { e.textContent = t; e.classList.remove('empty'); e.scrollTop = e.scrollHeight; }
                             else { e.textContent = 'Transcript will appear here…'; e.classList.add('empty'); } }
  function liveStatus(t)   { document.getElementById('liveStatus').innerHTML = t; }
  function setRecording(r) { STATE.recording = r;
                             document.getElementById('recBtn').textContent = r ? 'Stop Recording' : 'Start Recording'; }
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
        self._cfg = self._load_config()
        self.outdir = self._cfg.get("outdir") if os.path.isdir(
            self._cfg.get("outdir", "")) else os.path.expanduser("~/Desktop")
        self.out_format = self._cfg.get("format") if self._cfg.get(
            "format") in OUTPUT_FORMATS else "txt"
        self.cleanup = bool(self._cfg.get("cleanup", True))
        self.model_index = self._cfg.get("model", DEFAULT_MODEL_INDEX)
        if not isinstance(self.model_index, int) or not (0 <= self.model_index < len(MODELS)):
            self.model_index = DEFAULT_MODEL_INDEX
        self.mlx_installed = False
        self.is_running = False
        self._downloading = False
        self._repairing = False
        # Live state
        self._live_recording = False
        self._live_stop = threading.Event()
        self._live_transcript = ""

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
                "outdir": self.outdir, "cleanup": self.cleanup}
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def set_model(self, index):
        self.model_index = int(index)
        self._save_config()
        self._js("setDownloadBtn",
                 {"enabled": False, "text": "Downloaded ✓"}
                 if self._model_is_cached(self._current_model()[1])
                 else {"enabled": True, "text": "Download"})

    def set_format(self, fmt):
        if fmt in OUTPUT_FORMATS:
            self.out_format = fmt
            self._save_config()

    def set_cleanup(self, flag):
        self.cleanup = bool(flag)
        self._save_config()

    # ── File queue ────────────────────────────────────────────────────────────

    def add_files(self):
        # pywebview validates each filter description against
        # ^([\w ]+)\(...\)$ — word chars and spaces only. A "/" (as in the
        # previous "Audio / Video Files") fails that regex and raises
        # ValueError before the dialog even opens, which silently killed
        # this button (JS called it with .then() and no .catch()).
        types = ("Media Files (*.mp3;*.mp4;*.m4a;*.wav;*.flac;*.aac;*.ogg;*.mkv;*.webm)",
                 "All files (*.*)")
        try:
            result = self.window.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=True, file_types=types)
        except Exception as exc:
            self._log(f"✗ Couldn't open file picker: {exc}")
            return [os.path.basename(p) for p in self._file_queue]
        if result:
            for p in result:
                if p not in self._file_queue:
                    self._file_queue.append(p)
        self._refresh_transcribe()
        return [os.path.basename(p) for p in self._file_queue]

    def remove_files(self, indices):
        for i in sorted((int(x) for x in indices), reverse=True):
            if 0 <= i < len(self._file_queue):
                del self._file_queue[i]
        self._refresh_transcribe()
        return [os.path.basename(p) for p in self._file_queue]

    def clear_files(self):
        self._file_queue.clear()
        self._refresh_transcribe()
        return []

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
        self._js("setTranscribe", {"enabled": ready, "label": label})

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
                self._status("Installation failed — see log.")
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
                self._status("Repair failed — see log.")
        threading.Thread(target=_do, daemon=True).start()

    # ── Model download ────────────────────────────────────────────────────────

    def download_model(self):
        if not self.mlx_installed:
            self._log("✗ Install mlx-whisper first (click Install Now).")
            return
        label, repo = self._current_model()
        self._downloading = True
        self._js("setDownloadBtn", {"enabled": False, "text": "Downloading…"})
        self._status(f"Downloading {label.split('—')[0].strip()} model…")
        self._log(f"\n→ Downloading model: {repo}")
        self._log("  (cached after first download; large models take a while)")

        def _do():
            code = ("from huggingface_hub import snapshot_download;"
                    f"snapshot_download(repo_id='{repo}')")
            proc = subprocess.Popen([sys.executable, "-c", code],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                if line.strip():
                    self._log(line.rstrip())
            proc.wait()
            self._downloading = False
            if proc.returncode == 0:
                self._log("✓ Model ready.")
                self._status("Model downloaded and ready.")
                self._js("setDownloadBtn", {"enabled": False, "text": "Downloaded ✓"})
            else:
                self._log("✗ Model download failed — see log above.")
                self._status("Model download failed.")
                self._js("setDownloadBtn", {"enabled": True, "text": "Download"})
        threading.Thread(target=_do, daemon=True).start()

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
        return env

    def _find_mlx_exe(self):
        venv_bin = os.path.dirname(sys.executable)
        for cand in (os.path.join(venv_bin, "mlx_whisper"),
                     shutil.which("mlx_whisper"),
                     shutil.which("mlx-whisper")):
            if cand and os.path.exists(cand):
                return cand
        return None

    def _run_mlx_cli(self, mlx_exe, file_path, model, out_dir, cli_fmt, env):
        cmd = [mlx_exe, file_path, "--model", model,
               "--output-dir", out_dir, "--output-format", cli_fmt]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=env)
        for line in proc.stdout:
            self._log(line.rstrip())
        proc.wait()
        return proc.returncode == 0

    def _transcribe_via_cli(self, file_path, model, outdir, fmt, mlx_exe, env):
        base = os.path.splitext(os.path.basename(file_path))[0]

        if fmt in ("pdf", "docx"):
            # mlx_whisper always names its text output "<base>.txt" — if we
            # asked it to write that straight into outdir, it would collide
            # with (silently overwrite, then delete) any real standalone
            # .txt output already sitting there for this file. Generate the
            # intermediate text in an isolated scratch dir instead, so it
            # can never touch a real file in the user's chosen folder.
            with tempfile.TemporaryDirectory() as tmpdir:
                if not self._run_mlx_cli(mlx_exe, file_path, model, tmpdir, "txt", env):
                    return False
                tmp_txt = os.path.join(tmpdir, base + ".txt")
                if not os.path.exists(tmp_txt):
                    return False
                with open(tmp_txt, encoding="utf-8") as f:
                    text = f.read()
            if self.cleanup:
                text = self._reflow_text(text)
                self._log("✓ Cleaned up line breaks in transcript.")
            return (self._write_pdf(text, base, outdir) if fmt == "pdf"
                    else self._write_docx(text, base, outdir))

        # txt / srt / vtt: mlx_whisper writes directly into outdir.
        if not self._run_mlx_cli(mlx_exe, file_path, model, outdir, fmt, env):
            return False
        if self.cleanup and fmt == "txt":
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
                self._status("ffmpeg required — see log.")
                self._refresh_transcribe()
                return
            if mlx_exe is None:
                self.is_running = False
                self._log("✗ mlx_whisper binary not found. Run Setup / Repair…")
                self._status("mlx_whisper not found — run Setup / Repair.")
                self._refresh_transcribe()
                return

            failed = []
            for i, file_path in enumerate(files, 1):
                name = os.path.basename(file_path)
                self._log(f"\n[{i}/{n}] {name}")
                self._log(f"  Model : {model}")
                self._log(f"  Format: {fmt}  →  {outdir}")
                self._status(f"[{i}/{n}] Transcribing {name}…")
                ok = self._transcribe_via_cli(file_path, model, outdir, fmt, mlx_exe, env)
                if ok:
                    self._log(f"✓ Saved to: {outdir}")
                else:
                    self._log("✗ Failed.")
                    failed.append(name)

            self.is_running = False
            done = n - len(failed)
            if not failed:
                self._log(f"\n✓ All {n} file{'s' if n > 1 else ''} transcribed successfully.")
                self._status(f"Done — {n} transcript{'s' if n > 1 else ''} saved to {outdir}")
                subprocess.run(["open", outdir])
            else:
                self._log(f"\n⚠  {done}/{n} succeeded. Failed: {', '.join(failed)}")
                self._status(f"{done}/{n} transcribed. {len(failed)} failed — see log.")
            self.set_model(self.model_index)
            self._refresh_transcribe()
        threading.Thread(target=_do, daemon=True).start()

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
        self._live_transcript = ""

    def _record_loop(self):
        import sounddevice as sd
        import numpy as np
        import time
        buffer, last = [], time.monotonic()
        lock = threading.Lock()

        def cb(indata, frames, tinfo, status):
            with lock:
                buffer.append(indata[:, 0].copy())

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
                audio, path_or_hf_repo=self._current_model()[1], verbose=False)
            text = (result.get("text") or "").strip()
            if text:
                sep = " " if self._live_transcript else ""
                self._live_transcript += sep + text
                self._js("setLiveText", self._live_transcript)
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
            self._js("liveStatus", "Save failed — see the log in the main window.")
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


def _force_light_appearance():
    """Force light appearance so the native window chrome doesn't follow
    system Dark Mode (the page's own CSS is light regardless)."""
    try:
        from AppKit import NSApplication, NSAppearance
        NSApplication.sharedApplication().setAppearance_(
            NSAppearance.appearanceNamed_("NSAppearanceNameAqua"))
    except Exception:
        pass


def main():
    api = Api()
    _fix_macos_menu_bar_name()
    _force_light_appearance()
    window = webview.create_window(
        "Whisper Transcriber", html=HTML, js_api=api,
        width=700, height=880, min_size=(640, 720),
        background_color="#f5f5f7")
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
