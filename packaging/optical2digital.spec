# Build with (from repo root): pyinstaller packaging/optical2digital.spec
# Full pipeline: packaging/build-macos.sh (macOS) or packaging/build-windows.ps1 (Windows)
#
# Shared across platforms: this spec branches on sys.platform rather than
# forking into a separate per-platform file. sys.platform here reflects the
# machine PyInstaller itself is running on (the build host) — there is no
# cross-compilation happening anywhere in this pipeline, so that's exactly
# the platform being targeted.

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

FFMPEG_BIN_NAME = "ffmpeg" if IS_MACOS else "ffmpeg.exe"
ICON_PATH = str(ROOT_DIR / "packaging" / ("icon.icns" if IS_MACOS else "icon.ico"))

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
if IS_MACOS:
    datas.append((str(FFMPEG_BUNDLE_DIR / 'libs'), 'libs'))

a = Analysis(
    # Relative script paths in Analysis() are resolved by PyInstaller relative
    # to the .spec file's own directory (packaging/), not the invocation cwd —
    # see PyInstaller/building/build_main.py: "If path is relative, it is
    # relative to the location of .spec file." Hence 'launcher.py', not
    # 'packaging/launcher.py'.
    ['launcher.py'],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=['KylesOpticalDecoder'],
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
# platforms — on Windows (and Linux, if that's added later), the onedir
# folder at packaging/dist/Optical2Digital/ from COLLECT above *is* the
# final build output, wrapped by build-windows.ps1 into a zip + installer.
if IS_MACOS:
    app = BUNDLE(
        coll,
        name='Optical2Digital.app',
        icon=ICON_PATH,
        bundle_identifier='com.mikolasolutions.optical2digital',
    )
