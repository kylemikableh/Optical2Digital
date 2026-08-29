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

# Build with (from repo root): pyinstaller packaging/optical2digital.spec
# Full pipeline: packaging/build-macos.sh (macOS), packaging/build-windows.ps1
# (Windows), or packaging/build-linux.sh (Linux)
#
# Shared across platforms: this spec branches on sys.platform rather than
# forking into a separate per-platform file. sys.platform here reflects the
# machine PyInstaller itself is running on (the build host) — there is no
# cross-compilation happening anywhere in this pipeline, so that's exactly
# the platform being targeted.

import os
import pathlib
import sys

# NOTE: PyInstaller execs spec files without defining `__file__` in the
# namespace (only its own SPECPATH/SPEC/etc. globals are injected — see
# PyInstaller/building/build_main.py `spec_namespace`). SPECPATH is the
# absolute path to the directory containing this spec file, i.e. the
# `packaging/` directory — equivalent to what `Path(__file__).resolve().parent`
# would give if `__file__` were defined.
ROOT_DIR = pathlib.Path(SPECPATH).resolve().parent
FFMPEG_BUNDLE_DIR = ROOT_DIR / "packaging" / "build" / "ffmpeg-bundle"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# APP_VERSION is set by packaging/build-macos.sh / build-windows.ps1 (which
# in turn derive it from the release git tag — see
# .github/workflows/release.yml), falling back to a clearly-marked dev
# version for local/manual builds. Written out as a real module here, before
# Analysis() runs below, so PyInstaller's static import analysis picks it up
# automatically because packaging/launcher.py imports it — that's what gets
# the version into the running app's window title, on both platforms.
APP_VERSION = os.environ.get("APP_VERSION", "0.0.0-dev")
(ROOT_DIR / "app_version.py").write_text(f'APP_VERSION = "{APP_VERSION}"\n', encoding="utf-8")

# Only Windows uses the .exe suffix — macOS and Linux both ship a plain
# `ffmpeg`. This must stay in lockstep with server._resolve_ffmpeg_path(),
# which looks for the bundled binary by the same name.
FFMPEG_BIN_NAME = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

# PyInstaller only embeds an icon into PE (Windows) and Mach-O (macOS)
# executables — there's no equivalent for a Linux ELF, and passing a path to
# a file that doesn't exist on the build host (there's no icon.ico/.icns on
# Linux) makes PyInstaller error out. The Linux app icon is instead supplied
# by the .desktop file + hicolor PNGs installed by the .deb (see
# packaging/build-linux.sh).
if IS_MACOS:
    ICON_PATH = str(ROOT_DIR / "packaging" / "icon.icns")
elif IS_LINUX:
    ICON_PATH = None
else:
    ICON_PATH = str(ROOT_DIR / "packaging" / "icon.ico")

# The ffmpeg binary (+ libs/ on macOS, dylibbundler's output — see Task 2)
# is passed via `datas`, not `binaries`. This does NOT shield it from
# PyInstaller's own handling: on macOS, the BUNDLE step re-processes and
# re-signs bundled binaries/dylibs regardless of which list they came from —
# it rewrites their load-command paths from dylibbundler's
# `@executable_path/libs/...` to `@rpath/...` (adding
# `LC_RPATH @loader_path`), flattens the dylibs into the Frameworks root, and
# ad-hoc re-signs everything. ffmpeg still resolves fine afterward since
# `@loader_path` correctly points at those Frameworks-root copies. `datas` is
# used here simply because it's the simpler, more predictable API for "just
# copy these files in" — not because it avoids PyInstaller's reprocessing.
# On Windows there's no BUNDLE/re-signing step at all — packaging/
# bundle_ffmpeg_windows.ps1 stages a self-contained ffmpeg.exe with no
# separate DLLs to carry along, so no libs/ entry is needed there.
datas = [
    (str(ROOT_DIR / 'frontend' / 'dist'), 'frontend/dist'),
    (str(FFMPEG_BUNDLE_DIR / FFMPEG_BIN_NAME), '.'),
]
# pywebview has no default GUI backend on Linux the way it does on macOS
# (Cocoa) and Windows (EdgeWebView2) — packaging/build-linux.sh installs
# PySide6 into the build venv and packaging/launcher.py sets
# PYWEBVIEW_GUI=qt, so the Qt backend has to be pulled in explicitly:
# PyInstaller's static analysis can't follow pywebview's runtime backend
# selection, nor qtpy's dynamic re-export of the PySide6.* modules. Naming
# the concrete PySide6 QtWebEngine modules here is what triggers
# PyInstaller's dedicated hook-PySide6.QtWebEngineWidgets hook, which bundles
# the QtWebEngineProcess helper, *.pak resources, icudtl.dat and
# qtwebengine_locales/ — without them the window opens but never renders.
# (collect_all('PySide6') would also work but drags in every Qt module.)
binaries = []
hiddenimports = ['KylesOpticalDecoder']
if IS_LINUX:
    hiddenimports += [
        'webview.platforms.qt',
        'qtpy',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebChannel',
        'PySide6.QtPrintSupport',
    ]

if IS_MACOS:
    datas.append((str(FFMPEG_BUNDLE_DIR / 'libs'), 'libs'))
    # DATA-typed entries land under Contents/Resources in the final .app
    # (see PyInstaller's BUNDLE._process_bundle_toc) — that's exactly
    # where AppKit's standard About panel looks for a Credits.rtf to show
    # as its scrollable credits pane.
    datas.append((str(ROOT_DIR / 'packaging' / 'Credits.rtf'), '.'))

a = Analysis(
    # Relative script paths in Analysis() are resolved by PyInstaller relative
    # to the .spec file's own directory (packaging/), not the invocation cwd —
    # see PyInstaller/building/build_main.py: "If path is relative, it is
    # relative to the location of .spec file." Hence 'launcher.py', not
    # 'packaging/launcher.py'.
    ['launcher.py'],
    pathex=[str(ROOT_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Optical2Digital',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON_PATH,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='Optical2Digital',
)

# BUNDLE() produces a macOS .app and is unsupported/meaningless on other
# platforms — on Windows and Linux the onedir folder at
# packaging/dist/Optical2Digital/ from COLLECT above *is* the final build
# output, wrapped by build-windows.ps1 into a zip + installer, and by
# build-linux.sh into a .deb.
if IS_MACOS:
    app = BUNDLE(
        coll,
        name='Optical2Digital.app',
        icon=ICON_PATH,
        bundle_identifier='com.mikolasolutions.optical2digital',
        version=APP_VERSION,
        # info_plist keys are merged into (and override) PyInstaller's
        # generated Info.plist — see BUNDLE.assemble() in
        # PyInstaller/building/osx.py. These two feed the "About
        # Optical2Digital" panel: NSHumanReadableCopyright is the line
        # shown directly under the version, and CFBundleVersion is the
        # build number some tooling/notarization steps expect alongside
        # CFBundleShortVersionString (which `version=` above already
        # sets). The Credits.rtf bundled above (see `datas`) supplies the
        # panel's scrollable credits text.
        info_plist={
            'NSHumanReadableCopyright': 'Copyright © 2026 Kyle Mikolajczyk. Released under the GNU General Public License v3.0.',
            'CFBundleVersion': APP_VERSION,
        },
    )
