#!/usr/bin/env bash

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

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Building frontend =="
(cd frontend && npm install && npm run build)

echo "== Bundling ffmpeg =="
./packaging/bundle_ffmpeg_macos.sh

echo "== Generating icon =="
mkdir -p packaging/icon.iconset
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" packaging/O2DLogo.png --out "packaging/icon.iconset/icon_${size}x${size}.png" >/dev/null
  sips -z $((size*2)) $((size*2)) packaging/O2DLogo.png --out "packaging/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns packaging/icon.iconset -o packaging/icon.icns
rm -rf packaging/icon.iconset

echo "== Running PyInstaller =="
source .venv/bin/activate
pyinstaller --noconfirm --distpath packaging/dist --workpath packaging/build/pyinstaller \
  packaging/optical2digital.spec

echo "== Creating .dmg =="
hdiutil create -volname "Optical2Digital" -srcfolder "packaging/dist/Optical2Digital.app" \
  -ov -format UDZO "packaging/dist/Optical2Digital.dmg"

echo "Done: packaging/dist/Optical2Digital.dmg"
