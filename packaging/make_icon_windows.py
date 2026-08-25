#!/usr/bin/env python3
"""Generates packaging/icon.ico from cover.png (repo root).

Windows analog of build-macos.sh's sips/iconutil icon-generation step —
those tools don't exist on Windows, so this uses Pillow instead. Requires
Pillow, a build-time-only dependency installed ad hoc in CI (like
pyinstaller/pywebview), not part of requirements.txt.

Run from repo root: python packaging/make_icon_windows.py
"""
import pathlib

from PIL import Image

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT_DIR / "packaging" / "O2DLogo.png"
DEST = ROOT_DIR / "packaging" / "icon.ico"

img = Image.open(SRC).convert("RGBA")
img.save(DEST, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
print(f"Wrote {DEST}")
