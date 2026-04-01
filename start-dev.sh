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

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_CMD=("$ROOT_DIR/.venv/bin/python")
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD=(python3)
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD=(python)
else
  echo "Error: Python not found. Create .venv or install python3."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm is not installed or not in PATH."
  exit 1
fi

backend_pid=""
frontend_pid=""

cleanup() {
  local exit_code=$?

  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi

  if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
  fi

  wait "$backend_pid" 2>/dev/null || true
  wait "$frontend_pid" 2>/dev/null || true

  exit "$exit_code"
}

trap cleanup INT TERM EXIT

echo "Starting backend: ${PYTHON_CMD[*]} server.py"
(
  cd "$ROOT_DIR"
  "${PYTHON_CMD[@]}" server.py
) &
backend_pid=$!

echo "Starting frontend: npm run dev"
(
  cd "$FRONTEND_DIR"
  npm run dev
) &
frontend_pid=$!

echo "Both services started. Press Ctrl+C to stop."

while true; do
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait "$backend_pid" || true
    echo "Backend process exited. Stopping frontend..."
    break
  fi

  if ! kill -0 "$frontend_pid" 2>/dev/null; then
    wait "$frontend_pid" || true
    echo "Frontend process exited. Stopping backend..."
    break
  fi

  sleep 1
done

# Trigger cleanup through EXIT trap.
exit 0
