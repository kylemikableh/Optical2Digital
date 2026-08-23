#!/usr/bin/env bash
# Produces a self-contained ffmpeg (no Homebrew paths baked in) by copying
# the build machine's Homebrew ffmpeg and running dylibbundler over it.
#
# This is a build-time-only step — the tool and the source ffmpeg installation
# it reads from are NOT shipped to end users, only the resulting
# packaging/build/ffmpeg-bundle/ directory is (via optical2digital.spec).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/packaging/build/ffmpeg-bundle"

if ! command -v dylibbundler >/dev/null 2>&1; then
  echo "Error: dylibbundler is not installed. Run: brew install dylibbundler" >&2
  exit 1
fi

SRC_FFMPEG="$(command -v ffmpeg || true)"
if [[ -z "$SRC_FFMPEG" ]]; then
  echo "Error: ffmpeg is not installed. Run: brew install ffmpeg" >&2
  exit 1
fi

echo "Bundling ffmpeg from: $SRC_FFMPEG"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/libs"
cp "$SRC_FFMPEG" "$OUT_DIR/ffmpeg"
chmod +w "$OUT_DIR/ffmpeg"

dylibbundler -od -b \
  -x "$OUT_DIR/ffmpeg" \
  -d "$OUT_DIR/libs" \
  -p "@executable_path/libs/"

dylib_count="$(find "$OUT_DIR/libs" -name '*.dylib' | wc -l | tr -d ' ')"
echo "Bundled ffmpeg + $dylib_count dylibs at $OUT_DIR"
