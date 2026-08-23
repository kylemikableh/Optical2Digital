# Build with (from repo root): pyinstaller packaging/optical2digital.spec
# Full pipeline: packaging/build-macos.sh

import pathlib

# NOTE: PyInstaller execs spec files without defining `__file__` in the
# namespace (only its own SPECPATH/SPEC/etc. globals are injected — see
# PyInstaller/building/build_main.py `spec_namespace`). SPECPATH is the
# absolute path to the directory containing this spec file, i.e. the
# `packaging/` directory — equivalent to what `Path(__file__).resolve().parent`
# would give if `__file__` were defined.
ROOT_DIR = pathlib.Path(SPECPATH).resolve().parent
FFMPEG_BUNDLE_DIR = ROOT_DIR / "packaging" / "build" / "ffmpeg-bundle"

a = Analysis(
    # Relative script paths in Analysis() are resolved by PyInstaller relative
    # to the .spec file's own directory (packaging/), not the invocation cwd —
    # see PyInstaller/building/build_main.py: "If path is relative, it is
    # relative to the location of .spec file." Hence 'launcher.py', not
    # 'packaging/launcher.py'.
    ['launcher.py'],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    # The ffmpeg binary + libs/ (Task 2's dylibbundler output) are passed via
    # `datas`, not `binaries`. This does NOT shield them from PyInstaller's
    # own handling: on macOS, the BUNDLE step re-processes and re-signs
    # bundled binaries/dylibs regardless of which list they came from —
    # it rewrites their load-command paths from dylibbundler's
    # `@executable_path/libs/...` to `@rpath/...` (adding
    # `LC_RPATH @loader_path`), flattens the dylibs into the Frameworks
    # root, and ad-hoc re-signs everything. ffmpeg still resolves fine
    # afterward since `@loader_path` correctly points at those
    # Frameworks-root copies. `datas` is used here simply because it's the
    # simpler, more predictable API for "just copy these files in" — not
    # because it avoids PyInstaller's reprocessing.
    datas=[
        (str(ROOT_DIR / 'frontend' / 'dist'), 'frontend/dist'),
        (str(FFMPEG_BUNDLE_DIR / 'ffmpeg'), '.'),
        (str(FFMPEG_BUNDLE_DIR / 'libs'), 'libs'),
    ],
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
    icon=str(ROOT_DIR / 'packaging' / 'icon.icns'),
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

app = BUNDLE(
    coll,
    name='Optical2Digital.app',
    icon=str(ROOT_DIR / 'packaging' / 'icon.icns'),
    bundle_identifier='com.mikolasolutions.optical2digital',
)
