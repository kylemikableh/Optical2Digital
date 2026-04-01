#!/usr/bin/env bash

# This file is part of Kyle's Optical Decoder.
#
# Copyright (C) 2026 Kyle Mikolajczyk
#
# Kyle's Optical Decoder is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Kyle's Optical Decoder is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Kyle's Optical Decoder; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "Error: frontend directory not found at $FRONTEND_DIR"
  exit 1
fi

if [[ ! -f "$ROOT_DIR/start-dev.sh" ]]; then
  echo "Error: start-dev.sh not found at $ROOT_DIR"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm is not installed or not in PATH."
  exit 1
fi

echo "Installing frontend dependencies..."
(
  cd "$FRONTEND_DIR"
  npm install
)

echo "Starting backend + frontend dev servers..."
exec "$ROOT_DIR/start-dev.sh"
