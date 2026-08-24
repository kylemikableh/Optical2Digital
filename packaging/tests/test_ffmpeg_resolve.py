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
    # sys.platform is pinned to a non-Windows value so this test is
    # deterministic regardless of which OS actually runs it — the bundled
    # filename _resolve_ffmpeg_path looks for depends on sys.platform (see
    # test_uses_ffmpeg_exe_when_frozen_on_windows for the win32 case), so
    # without pinning this, running on real Windows would create a file
    # named "ffmpeg" that the function (correctly) wouldn't find, since it
    # would be looking for "ffmpeg.exe" instead.
    with tempfile.TemporaryDirectory() as tmp:
        bundled = os.path.join(tmp, "ffmpeg")
        with open(bundled, "w") as f:
            f.write("#!/bin/sh\necho fake\n")
        os.chmod(bundled, 0o755)

        sys.frozen = True
        sys._MEIPASS = tmp
        real_platform = sys.platform
        sys.platform = "darwin"
        try:
            result = server._resolve_ffmpeg_path()
            assert result == bundled, f"expected bundled path {bundled!r}, got {result!r}"
        finally:
            sys.platform = real_platform
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
    # This test's premise (chmod off the execute bit, then confirm
    # os.access(X_OK) reports it as not executable) doesn't hold on a real
    # Windows host: os.access(..., os.X_OK) has no execute-bit concept on
    # Windows and just reports whether the file exists, regardless of
    # chmod — that's a real OS-level fact, not something the sys.platform
    # patch below can fake, so this scenario is untestable there and is
    # skipped rather than asserting something Windows can't actually do.
    if os.name == "nt":
        print("SKIP: test_frozen_and_present_but_not_executable_falls_back_to_path (no execute-bit concept on Windows)")
        return

    # sys.platform pinned to non-Windows for the same reason as
    # test_uses_bundled_binary_when_frozen_and_present above.
    with tempfile.TemporaryDirectory() as tmp:
        bundled = os.path.join(tmp, "ffmpeg")
        with open(bundled, "w") as f:
            f.write("#!/bin/sh\necho fake\n")
        os.chmod(bundled, 0o644)  # present, but not executable

        sys.frozen = True
        sys._MEIPASS = tmp
        real_platform = sys.platform
        sys.platform = "darwin"
        try:
            result = server._resolve_ffmpeg_path()
            assert result == shutil.which("ffmpeg"), \
                "expected PATH fallback when the bundled binary is not executable"
        finally:
            sys.platform = real_platform
            del sys.frozen
            del sys._MEIPASS


def test_uses_ffmpeg_exe_when_frozen_on_windows():
    # sys.platform is monkeypatched here (rather than relying on the OS this
    # test actually runs on) so the win32 branch of _resolve_ffmpeg_path is
    # exercised on any platform, matching how the other tests fake sys.frozen.
    with tempfile.TemporaryDirectory() as tmp:
        bundled = os.path.join(tmp, "ffmpeg.exe")
        with open(bundled, "w") as f:
            f.write("fake\n")
        os.chmod(bundled, 0o755)

        sys.frozen = True
        sys._MEIPASS = tmp
        real_platform = sys.platform
        sys.platform = "win32"
        try:
            result = server._resolve_ffmpeg_path()
            assert result == bundled, f"expected {bundled!r}, got {result!r}"
        finally:
            sys.platform = real_platform
            del sys.frozen
            del sys._MEIPASS


if __name__ == "__main__":
    test_falls_back_to_path_when_not_frozen()
    test_uses_bundled_binary_when_frozen_and_present()
    test_frozen_but_missing_bundled_binary_falls_back_to_path()
    test_frozen_and_present_but_not_executable_falls_back_to_path()
    test_uses_ffmpeg_exe_when_frozen_on_windows()
    print("OK: all _resolve_ffmpeg_path checks passed")
