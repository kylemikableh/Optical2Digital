#!/usr/bin/env python3

# This file is part of Optical2Digital.
#
# Copyright (C) 2026 Kyle Mikolajczyk
#
# Optical2Digital is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Optical2Digital is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Optical2Digital; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

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
