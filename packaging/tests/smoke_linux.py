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

"""CI-only smoke test for the packaged Linux build: launch the PyInstaller
binary, confirm its embedded server answers, then shut it down cleanly.

Must run under a display — in CI:
    xvfb-run -a python3 packaging/tests/smoke_linux.py

Expects the build to have already run (packaging/build-linux.sh), i.e.
packaging/dist/Optical2Digital/Optical2Digital exists.
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BINARY = os.path.join(ROOT_DIR, "packaging", "dist", "Optical2Digital", "Optical2Digital")
URL = "http://127.0.0.1:8000/"
STARTUP_TIMEOUT = 45.0   # QtWebEngine's first run on a cold CI box is slow
SHUTDOWN_TIMEOUT = 10.0


def _wait_for_server(deadline):
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=2) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code  # server is up, just not a 2xx on /
        except Exception:
            time.sleep(0.5)
    return None


def main():
    if not os.path.isfile(BINARY) or not os.access(BINARY, os.X_OK):
        print(f"FAIL: packaged binary not found/executable at {BINARY}")
        return 1

    env = dict(os.environ)
    env["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    env.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-gpu --disable-software-rasterizer --no-sandbox",
    )
    env.setdefault("QT_QPA_PLATFORM", "xcb")

    proc = subprocess.Popen(
        [BINARY], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        status = _wait_for_server(time.time() + STARTUP_TIMEOUT)
        if status is None:
            proc.terminate()
            out, _ = proc.communicate(timeout=SHUTDOWN_TIMEOUT)
            print(f"FAIL: server did not respond at {URL} within {STARTUP_TIMEOUT}s")
            print("---- child output ----")
            print(out)
            return 1
        print(f"OK: server responded ({status}) at {URL}")
    finally:
        if proc.poll() is None:
            proc.terminate()

    try:
        proc.wait(timeout=SHUTDOWN_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        print(f"FAIL: process did not exit within {SHUTDOWN_TIMEOUT}s of SIGTERM")
        return 1

    print("OK: packaged Linux build smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
