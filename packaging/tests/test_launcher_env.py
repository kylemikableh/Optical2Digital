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

"""Standalone check that launcher.py configures pywebview's Linux GUI
backend before importing webview. No-op (SKIP) off Linux.

Run directly with python3:
    python3 packaging/tests/test_launcher_env.py
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "packaging"))


def test_linux_gui_env_is_set_on_import():
    if not sys.platform.startswith("linux"):
        print("SKIP: test_linux_gui_env_is_set_on_import (not Linux)")
        return

    # Clear anything a prior run / the ambient shell set so we're actually
    # observing launcher.py's own effect.
    os.environ.pop("PYWEBVIEW_GUI", None)
    os.environ.pop("QTWEBENGINE_DISABLE_SANDBOX", None)

    import launcher  # noqa: F401  — bare import; NOT "from packaging import
                     # launcher" (the `packaging` name collides with the real
                     # PyPI package — see test_launcher_server.py).

    assert os.environ.get("PYWEBVIEW_GUI") == "qt", \
        "launcher should default PYWEBVIEW_GUI=qt on Linux"
    assert os.environ.get("QTWEBENGINE_DISABLE_SANDBOX") == "1", \
        "launcher should set QTWEBENGINE_DISABLE_SANDBOX=1 on Linux"


def test_pywebview_gui_is_only_a_default():
    if not sys.platform.startswith("linux"):
        print("SKIP: test_pywebview_gui_is_only_a_default (not Linux)")
        return

    # A user override must win — launcher uses setdefault for PYWEBVIEW_GUI.
    os.environ["PYWEBVIEW_GUI"] = "gtk"
    for mod in ("launcher",):
        sys.modules.pop(mod, None)
    import launcher  # noqa: F401

    assert os.environ.get("PYWEBVIEW_GUI") == "gtk", \
        "launcher must not clobber an explicit PYWEBVIEW_GUI"
    os.environ.pop("PYWEBVIEW_GUI", None)


if __name__ == "__main__":
    test_linux_gui_env_is_set_on_import()
    test_pywebview_gui_is_only_a_default()
    print("OK: launcher Linux GUI-env checks passed")
