#!/usr/bin/env python3
"""Standalone checks on the committed Linux packaging templates under
packaging/linux/. Pure filesystem inspection — runs on any OS, needs no
build. (The .deb itself is exercised by build-linux.sh + smoke_linux.py.)

Run directly with python3:
    python3 packaging/tests/test_linux_packaging.py
"""
import os
import shutil
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINUX_DIR = os.path.join(ROOT_DIR, "packaging", "linux")


def _read(name):
    with open(os.path.join(LINUX_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def test_desktop_file_fields():
    text = _read("optical2digital.desktop")
    assert "[Desktop Entry]" in text
    assert "Type=Application" in text
    assert "Exec=optical2digital" in text
    assert "Icon=optical2digital" in text

    cats_line = next(
        (l for l in text.splitlines() if l.startswith("Categories=")), None
    )
    assert cats_line is not None, "Categories= missing"
    assert cats_line.rstrip().endswith(";"), \
        "Categories= must be a semicolon-terminated list"


def test_desktop_file_validate_if_available():
    tool = shutil.which("desktop-file-validate")
    if not tool:
        print("SKIP: test_desktop_file_validate_if_available (tool not installed)")
        return
    path = os.path.join(LINUX_DIR, "optical2digital.desktop")
    result = subprocess.run([tool, path], capture_output=True, text=True)
    assert result.returncode == 0, \
        f"desktop-file-validate failed:\n{result.stdout}{result.stderr}"


def test_control_template_fields_and_placeholders():
    text = _read("control.in")
    for field in ("Package:", "Version:", "Architecture:", "Maintainer:",
                  "Depends:", "Description:"):
        assert field in text, f"control.in missing {field}"
    for placeholder in ("@VERSION@", "@ARCH@", "@INSTALLED_SIZE@"):
        assert placeholder in text, f"control.in missing {placeholder}"


def test_control_depends_covers_qtwebengine_essentials():
    # libqt6webenginecore6 pulls the whole Chromium/QtWebEngine leaf-library
    # closure that PySide6's wheel doesn't bundle. libxcb-cursor0 (Qt 6.5+
    # xcb platform plugin) is only a Recommends of it, so it's listed
    # explicitly; libnss3 likewise as belt-and-suspenders.
    text = _read("control.in")
    depends = text.split("Depends:", 1)[1].split("Description:", 1)[0]
    for pkg in ("libqt6webenginecore6", "libxcb-cursor0", "libnss3"):
        assert pkg in depends, f"control.in Depends is missing {pkg}"


def test_wrapper_script():
    text = _read("optical2digital.wrapper")
    assert text.startswith("#!/bin/sh"), "wrapper must be a /bin/sh script"
    assert "/opt/Optical2Digital/Optical2Digital" in text
    assert "QTWEBENGINE_DISABLE_SANDBOX" in text


def test_maintainer_scripts_shape():
    for name in ("postinst", "postrm"):
        text = _read(name)
        assert text.startswith("#!/bin/sh"), f"{name} must be a /bin/sh script"
        assert "set -e" in text, f"{name} should 'set -e'"


if __name__ == "__main__":
    test_desktop_file_fields()
    test_desktop_file_validate_if_available()
    test_control_template_fields_and_placeholders()
    test_control_depends_covers_qtwebengine_essentials()
    test_wrapper_script()
    test_maintainer_scripts_shape()
    print("OK: Linux packaging template checks passed")
