#!/usr/bin/env bash
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
  sips -z "$size" "$size" cover.png --out "packaging/icon.iconset/icon_${size}x${size}.png" >/dev/null
  sips -z $((size*2)) $((size*2)) cover.png --out "packaging/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
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
