"""
py2app build configuration for Whisper Transcriber.
Run via build.sh — do not invoke directly.
"""

import os
import sys

# py2app's modulegraph walks the full import AST recursively. On large
# dependency trees (mlx, huggingface_hub, …) and newer Pythons this can blow
# past the default recursion limit, raising RecursionError during the build.
# Raise the ceiling well above the default 1000 before py2app runs.
sys.setrecursionlimit(10000)

from setuptools import setup

APP = ["whisper_transcriber.py"]

# build.sh stages ffmpeg into ./bin/ before running this.
DATA_FILES = []
if os.path.exists("bin/ffmpeg"):
    DATA_FILES = [("bin", ["bin/ffmpeg"])]

OPTIONS = {
    "argv_emulation": False,   # must be False for modern macOS / Tk apps
    "iconfile": "whisper_icon.icns",
    "plist": {
        "CFBundleName":             "Whisper Transcriber",
        "CFBundleDisplayName":      "Whisper Transcriber",
        "CFBundleIdentifier":       "com.josephmuller.whispertranscriber",
        "CFBundleVersion":          "2.0",
        "CFBundleShortVersionString": "2.0",
        "NSHighResolutionCapable":  True,
        # Force Aqua appearance — avoids dark-mode rendering bugs in tkinter
        "NSRequiresAquaSystemAppearance": True,
        "LSMinimumSystemVersion":   "12.0",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSMicrophoneUsageDescription": "Whisper Transcriber needs microphone access for live transcription.",
    },
    # All packages that need to be recursively bundled.
    # py2app walks their compiled extensions and dylibs automatically.
    "packages": [
        "mlx",
        "mlx_whisper",
        "huggingface_hub",
        "tokenizers",
        "safetensors",
        "tqdm",
        "filelock",
        "packaging",
        "requests",
        "certifi",
        "charset_normalizer",
        "idna",
        "urllib3",
        "fsspec",
        "regex",
        "tkinter",
        "fpdf",
        "docx",
        "sounddevice",
    ],
    "includes": [
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
    ],
    # Exclude heavy packages that are definitely unused.
    "excludes": [
        "matplotlib", "scipy", "numpy", "pandas",
        "PIL", "Pillow", "PyQt5", "PyQt6", "wx",
        "IPython", "jupyter", "notebook",
        "pytest", "_pytest", "setuptools", "pip",
        "distutils", "email", "html", "http",
        "unittest", "xmlrpc",
    ],
}

setup(
    name="Whisper Transcriber",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
