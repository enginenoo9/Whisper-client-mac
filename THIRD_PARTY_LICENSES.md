# Third-Party Licenses

Whisper Transcriber is distributed under the [MIT License](LICENSE). It does not
bundle third-party code — its dependencies install at runtime into a local
virtual environment (via `pip`) and via Homebrew (`ffmpeg`). Each remains under
its own license, reproduced or referenced below.

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
| Python & Tkinter (Tcl/Tk) | Runtime & GUI | PSF / BSD-style | https://www.python.org |
| **`fpdf2`** | PDF output | **LGPL-3.0** | https://github.com/py-pdf/fpdf2 |
| **ffmpeg** | Audio/video decoding | **LGPL-2.1+ / GPL** (build-dependent) | https://ffmpeg.org |

## Copyleft components

These two are not MIT-licensed. Because Whisper Transcriber installs them at
runtime rather than redistributing them, the obligations fall on whoever
distributes the binaries (Homebrew for ffmpeg, PyPI for `fpdf2`). If you ever
repackage or redistribute the app together with these components, review their
terms:

- **ffmpeg** — LGPL-2.1-or-later / GPL (Homebrew's build is typically GPL). See
  https://ffmpeg.org/legal.html.
- **`fpdf2`** — LGPL-3.0-only. See https://www.gnu.org/licenses/lgpl-3.0.html.

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
