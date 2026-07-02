# Third-Party Licenses

Whisper Transcriber is distributed under the [MIT License](LICENSE).

Distribution depends on how you got the app:

- **DMG builds** (via `build-dmg.sh`) bundle two third-party components
  directly: **CPython + Tcl/Tk** (as `Python.framework`, downloaded from the
  official python.org installer) and **ffmpeg** (a compiled binary, staged
  from Homebrew at build time). Both ship as unmodified, separate executables
  invoked via subprocess — not linked into this project's own code — and each
  remains under its own license below.
- All other dependencies (`mlx-whisper`, `fpdf2`, `python-docx`,
  `sounddevice`, etc.) install at runtime into a private virtual environment
  via `pip`, on first launch. Each remains under its own license, reproduced
  or referenced below.

| Component | Used for | License | Project |
|---|---|---|---|
| OpenAI Whisper (models & reference code) | Speech-to-text models | MIT | https://github.com/openai/whisper |
| MLX (`mlx`) | Apple-silicon ML runtime | MIT | https://github.com/ml-explore/mlx |
| `mlx-whisper` | Whisper inference on MLX | MIT | https://github.com/ml-explore/mlx-examples |
| Whisper MLX weights (`mlx-community/*`) | Converted model weights | MIT (per original Whisper) | https://huggingface.co/mlx-community |
| `huggingface_hub` | Model downloads | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| `python-docx` | DOCX output | MIT | https://github.com/python-openxml/python-docx |
| `sounddevice` | Microphone capture | MIT | https://github.com/spatialaudio/python-sounddevice |
| PortAudio (via `sounddevice`) | Audio I/O backend | MIT-style | https://www.portaudio.com |
| `pyobjc-framework-Cocoa` | Corrects the macOS menu bar app name | MIT | https://github.com/ronaldoussoren/pyobjc |
| Python & Tkinter (Tcl/Tk) | Runtime & GUI | PSF / BSD-style | https://www.python.org |
| **`fpdf2`** | PDF output | **LGPL-3.0** | https://github.com/py-pdf/fpdf2 |
| **ffmpeg** | Audio/video decoding | **LGPL-2.1+ / GPL** (build-dependent) | https://ffmpeg.org |
| `relocatable-python` (build-time only, vendored in `vendor/`) | Makes the bundled Python.framework work outside `/Library/Frameworks/` | Apache-2.0 | https://github.com/gregneagle/relocatable-python |

## Copyleft components

These two are not MIT-licensed.

- **ffmpeg** — LGPL-2.1-or-later / GPL (Homebrew's build is typically GPL,
  depending on which encoders are enabled — check the `configuration:` line
  in `ffmpeg -version` for the exact build). In DMG builds it ships as an
  unmodified binary invoked as a separate subprocess (mere aggregation, not
  a derivative work), the same way Homebrew already distributes it. In
  source installs it's installed via Homebrew directly, so the redistribution
  obligations fall on Homebrew. See https://ffmpeg.org/legal.html. If you plan
  to distribute this app commercially, verify your ffmpeg build's exact
  license terms.
- **`fpdf2`** — LGPL-3.0-only, installed at runtime via `pip`, not bundled.
  See https://www.gnu.org/licenses/lgpl-3.0.html.

## Build-time-only tool

`vendor/relocatable-python/` (Apache-2.0, by Greg Neagle) is vendored source
used by `build-dmg.sh` to patch the bundled Python.framework's binaries so
they work outside `/Library/Frameworks/`. It runs only on the build machine —
its own source files aren't copied into the app or the DMG, only their
effect (patched Mach-O binaries) is. See `vendor/relocatable-python/README.md`
and `LICENSE` for the full attribution.

## MIT license text (covers the MIT-licensed components above)

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> Each MIT-licensed component is copyright its respective authors. Refer to the
> linked projects for the exact copyright lines.
