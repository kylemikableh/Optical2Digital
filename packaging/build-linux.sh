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

# Linux analog of build-macos.sh / build-windows.ps1: builds the frontend,
# bundles a static ffmpeg, generates icons, runs PyInstaller, then wraps the
# resulting onedir bundle into a Debian .deb (installs to /opt/Optical2Digital
# with an `optical2digital` command and an application-menu entry).
#
# Usage:  APP_VERSION=1.2.3 ./packaging/build-linux.sh [amd64|arm64]
#
# The .deb links against whatever glibc the build host has, so for release
# artifacts this runs on the oldest supported runner (ubuntu-22.04) — see
# .github/workflows/release.yml. A locally-built .deb is fine for smoke
# testing but inherits this machine's glibc floor.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ARCH="${1:-amd64}"
case "$ARCH" in
  amd64|arm64) ;;
  *) echo "Error: unknown arch '$ARCH' (expected amd64 or arm64)" >&2; exit 1 ;;
esac

VERSION="${APP_VERSION:-0.0.0-dev}"
PKG="optical2digital"
DIST_DIR="packaging/dist"
ONEDIR="$DIST_DIR/Optical2Digital"
ICON_DIR="packaging/build/icons"
STAGE="packaging/build/deb/${PKG}_${VERSION}_${ARCH}"
ICON_SIZES="16 32 48 64 128 256 512"

echo "== Building frontend =="
(cd frontend && npm install && npm run build)

echo "== Bundling ffmpeg =="
./packaging/bundle_ffmpeg_linux.sh "$ARCH"

echo "== Generating icons =="
if ! command -v convert >/dev/null 2>&1; then
  echo "Error: ImageMagick 'convert' is not installed." >&2
  exit 1
fi
rm -rf "$ICON_DIR"
for size in $ICON_SIZES; do
  mkdir -p "$ICON_DIR/${size}x${size}"
  convert "packaging/O2DLogo.png" -resize "${size}x${size}" \
    "$ICON_DIR/${size}x${size}/${PKG}.png"
done

echo "== Running PyInstaller =="
# Use an already-activated venv if there is one (VIRTUAL_ENV is exported by
# `activate`), otherwise fall back to a repo-root .venv like build-macos.sh.
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  echo "Using active virtualenv: $VIRTUAL_ENV"
elif [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "Error: no virtualenv active and no .venv found. Create one first:" >&2
  echo "    python3 -m venv .venv && source .venv/bin/activate" >&2
  echo "    pip install --upgrade pip" >&2
  echo "    pip install wheel cmake scikit-build setuptools packaging numpy scipy natsort fastapi uvicorn pydantic pywebview pyinstaller pyside6 qtpy" >&2
  echo "    CMAKE_ARGS=\"-DBUILD_opencv_dnn=OFF\" pip install --no-build-isolation opencv-python" >&2
  exit 1
fi
# Fail fast if the GUI stack the frozen app needs isn't importable in this
# venv — otherwise PyInstaller happily produces a bundle that dies at startup
# with "No module named 'qtpy'" / "You must have either QT or GTK ...". The
# QtWebEngine check is import-time, not just "is the package installed": its
# .so dlopens system libs (libnss3, libminizip.so.1, ...) that must be
# present on the *build* box too, and PyInstaller's analysis imports the
# module. Print the real error so a missing system lib is obvious.
if ! python - <<'PY'
import importlib, sys
for mod in ("qtpy", "PySide6", "PySide6.QtWebEngineWidgets"):
    try:
        importlib.import_module(mod)
    except Exception as e:
        print(f"  {mod}: {e.__class__.__name__}: {e}", file=sys.stderr)
        sys.exit(1)
PY
then
  echo "Error: the Qt GUI stack is not importable in this venv ($VIRTUAL_ENV)." >&2
  echo "  - missing package?  pip install pyside6 qtpy" >&2
  echo "    (the 'pyside6' metapackage pulls PySide6-Addons, which has QtWebEngine)" >&2
  echo "  - 'cannot open shared object file' above?  install that system lib" >&2
  echo "    (e.g. 'sudo apt install libqt6webenginecore6' drags in the whole" >&2
  echo "     Chromium/QtWebEngine leaf-library closure PySide6 doesn't bundle)." >&2
  exit 1
fi

export APP_VERSION="$VERSION"
pyinstaller --noconfirm --distpath "$DIST_DIR" --workpath packaging/build/pyinstaller \
  packaging/optical2digital.spec

if [[ ! -x "$ONEDIR/Optical2Digital" ]]; then
  echo "Error: expected PyInstaller output at $ONEDIR/Optical2Digital" >&2
  exit 1
fi

# Sanity-check that PyInstaller's PySide6 hooks pulled in the QtWebEngine
# helper process — without it the window opens but the page never renders.
if [[ -z "$(find "$ONEDIR" -name 'QtWebEngineProcess*' -print -quit)" ]]; then
  echo "Warning: QtWebEngineProcess not found in the bundle — the app UI may" >&2
  echo "         not render. Check the PySide6 QtWebEngine hidden imports in" >&2
  echo "         packaging/optical2digital.spec, and that 'pyside6' in the" >&2
  echo "         venv includes QtWebEngine (the standard wheel does)." >&2
fi

echo "== Staging .deb tree =="
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/opt/Optical2Digital" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/doc/$PKG"

cp -a "$ONEDIR/." "$STAGE/opt/Optical2Digital/"
install -m 0755 packaging/linux/optical2digital.wrapper "$STAGE/usr/bin/optical2digital"
install -m 0644 packaging/linux/optical2digital.desktop "$STAGE/usr/share/applications/${PKG}.desktop"
install -m 0644 packaging/linux/copyright "$STAGE/usr/share/doc/$PKG/copyright"

for size in $ICON_SIZES; do
  dest="$STAGE/usr/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "$dest"
  install -m 0644 "$ICON_DIR/${size}x${size}/${PKG}.png" "$dest/${PKG}.png"
done

installed_kb="$(du -s -k "$STAGE" | cut -f1)"
sed -e "s/@VERSION@/${VERSION}/g" \
    -e "s/@ARCH@/${ARCH}/g" \
    -e "s/@INSTALLED_SIZE@/${installed_kb}/g" \
    packaging/linux/control.in > "$STAGE/DEBIAN/control"
install -m 0755 packaging/linux/postinst "$STAGE/DEBIAN/postinst"
install -m 0755 packaging/linux/postrm "$STAGE/DEBIAN/postrm"

echo "== Validating .desktop file =="
if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$STAGE/usr/share/applications/${PKG}.desktop"
else
  echo "(desktop-file-validate not installed — skipping)"
fi

echo "== Building .deb =="
OUT="$DIST_DIR/Optical2Digital-linux-${ARCH}.deb"
rm -f "$OUT"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT"

dpkg-deb --info "$OUT"
# `| sed -n '1,40p'` rather than `| head`: sed reads stdin to EOF, so
# dpkg-deb's internal tar never gets SIGPIPE (which, under `set -o pipefail`,
# would fail this script even though the .deb built fine).
dpkg-deb --contents "$OUT" | sed -n '1,40p'
echo "  ... ($(dpkg-deb --contents "$OUT" | wc -l) entries total)"

echo "Done: $OUT"
