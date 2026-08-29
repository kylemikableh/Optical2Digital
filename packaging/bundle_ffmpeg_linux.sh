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

# Produces a self-contained ffmpeg for the packaged Linux app by downloading
# a static build from BtbN/FFmpeg-Builds' latest GitHub release (queried via
# the API rather than a pinned version, so this doesn't go stale) and staging
# it where packaging/optical2digital.spec expects it.
#
# This is a build-time-only step — nothing here is shipped as-is; only the
# resulting packaging/build/ffmpeg-bundle/ffmpeg is (via the spec's `datas`).
# Linux analog of bundle_ffmpeg_windows.ps1 — like that script (and unlike
# bundle_ffmpeg_macos.sh), there's no dylibbundler-equivalent step: BtbN's
# linux*-gpl builds are fully static with no external .so dependencies to
# carry alongside the binary, so no libs/ subdirectory is produced (verified
# by running the extracted ffmpeg standalone at the end).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/packaging/build/ffmpeg-bundle"
ARCH="${1:-amd64}"   # dpkg arch name: amd64 | arm64

# BtbN's asset names embed "linux64" / "linuxarm64" rather than our "amd64" /
# "arm64".
case "$ARCH" in
  amd64) BTBN_TAG="linux64" ;;
  arm64) BTBN_TAG="linuxarm64" ;;
  *) echo "Error: unknown arch '$ARCH' (expected amd64 or arm64)" >&2; exit 1 ;;
esac

for tool in curl jq tar xz; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Error: '$tool' is not installed." >&2
    exit 1
  fi
done

echo "Looking up latest BtbN/FFmpeg-Builds release for $BTBN_TAG..."
release_json="$(curl -fsSL -H 'User-Agent: Optical2Digital-build' \
  https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest)"

# BtbN publishes multiple flavors per arch (gpl/lgpl x shared/static); prefer
# the static gpl build. The filter is intentionally loose about the version
# segment (asset names churn, e.g. "ffmpeg-master-latest-linux64-gpl.tar.xz"
# vs a dated variant) but should be reconfirmed against the actual release
# listing if it ever stops matching.
asset_url="$(printf '%s' "$release_json" | jq -r --arg tag "$BTBN_TAG" '
  [ .assets[]
    | select(.name | test($tag))
    | select(.name | test("gpl"))
    | select(.name | test("shared") | not)
    | select(.name | endswith(".tar.xz"))
    | .browser_download_url ] | .[0] // ""')"

if [[ -z "$asset_url" || "$asset_url" == "null" ]]; then
  echo "Error: no matching BtbN ffmpeg asset for arch tag '$BTBN_TAG'." >&2
  echo "Available assets:" >&2
  printf '%s' "$release_json" | jq -r '.assets[].name' >&2
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading ${asset_url##*/}..."
curl -fsSL -o "$tmp/ffmpeg.tar.xz" "$asset_url"
tar -xJf "$tmp/ffmpeg.tar.xz" -C "$tmp"

src_ffmpeg="$(find "$tmp" -type f -name ffmpeg -path '*/bin/*' -print -quit)"
if [[ -z "$src_ffmpeg" ]]; then
  echo "Error: ffmpeg not found inside downloaded archive ${asset_url##*/}" >&2
  exit 1
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
cp "$src_ffmpeg" "$OUT_DIR/ffmpeg"
chmod +x "$OUT_DIR/ffmpeg"

# Confirm it's actually self-contained (runs off PATH, no missing .so).
# Capture first, then slice with a here-string — piping straight into `head`
# would hand ffmpeg a SIGPIPE that `set -o pipefail` turns into a failure.
if ! ffmpeg_version="$("$OUT_DIR/ffmpeg" -version 2>&1)"; then
  echo "Error: bundled ffmpeg failed to run:" >&2
  printf '%s\n' "$ffmpeg_version" >&2
  exit 1
fi
head -n1 <<< "$ffmpeg_version"

tag_name="$(printf '%s' "$release_json" | jq -r '.tag_name')"
echo "Bundled ffmpeg ($ARCH, from $tag_name) at $OUT_DIR"
