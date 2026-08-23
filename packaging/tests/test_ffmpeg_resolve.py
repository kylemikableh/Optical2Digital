#!/usr/bin/env python3
"""Standalone check for server._resolve_ffmpeg_path.

Run directly with python3 (this project has no pytest setup):
    python3 packaging/tests/test_ffmpeg_resolve.py
"""
import os
import shutil
import sys
import tempfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)
import server


def test_falls_back_to_path_when_not_frozen():
    assert not getattr(sys, "frozen", False)
    expected = shutil.which("ffmpeg")
    assert server._resolve_ffmpeg_path() == expected, \
        "expected PATH fallback when sys.frozen is not set"


def test_uses_bundled_binary_when_frozen_and_present():
    with tempfile.TemporaryDirectory() as tmp:
        bundled = os.path.join(tmp, "ffmpeg")
        with open(bundled, "w") as f:
            f.write("#!/bin/sh\necho fake\n")
        os.chmod(bundled, 0o755)

        sys.frozen = True
        sys._MEIPASS = tmp
        try:
            result = server._resolve_ffmpeg_path()
            assert result == bundled, f"expected bundled path {bundled!r}, got {result!r}"
        finally:
            del sys.frozen
            del sys._MEIPASS


def test_frozen_but_missing_bundled_binary_falls_back_to_path():
    with tempfile.TemporaryDirectory() as tmp:
        # no ffmpeg file created in tmp — simulates a broken/incomplete bundle
        sys.frozen = True
        sys._MEIPASS = tmp
        try:
            result = server._resolve_ffmpeg_path()
            assert result == shutil.which("ffmpeg"), \
                "expected PATH fallback when the bundled binary is missing"
        finally:
            del sys.frozen
            del sys._MEIPASS


def test_frozen_and_present_but_not_executable_falls_back_to_path():
    with tempfile.TemporaryDirectory() as tmp:
        bundled = os.path.join(tmp, "ffmpeg")
        with open(bundled, "w") as f:
            f.write("#!/bin/sh\necho fake\n")
        os.chmod(bundled, 0o644)  # present, but not executable

        sys.frozen = True
        sys._MEIPASS = tmp
        try:
            result = server._resolve_ffmpeg_path()
            assert result == shutil.which("ffmpeg"), \
                "expected PATH fallback when the bundled binary is not executable"
        finally:
            del sys.frozen
            del sys._MEIPASS


if __name__ == "__main__":
    test_falls_back_to_path_when_not_frozen()
    test_uses_bundled_binary_when_frozen_and_present()
    test_frozen_but_missing_bundled_binary_falls_back_to_path()
    test_frozen_and_present_but_not_executable_falls_back_to_path()
    print("OK: all _resolve_ffmpeg_path checks passed")
