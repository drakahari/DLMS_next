# -*- mode: python ; coding: utf-8 -*-
"""Canonical platform-aware PyInstaller build for DLMS.

Only the application entry point and the two required local data inputs are
declared here. Runtime data always belongs in the per-user DLMS data root and
must never be added to this manifest. Windows and Linux remain one-file builds;
macOS is packaged as a native application bundle.
"""

import re
import sys
from pathlib import Path


project_root = Path(SPEC).resolve().parent
app_source = (project_root / "app.py").read_text(encoding="utf-8")
app_version_match = re.search(r'^APP_VERSION = "([^"]+)"$', app_source, re.MULTILINE)
if app_version_match is None:
    raise ValueError("DLMS.spec could not determine APP_VERSION from app.py")
app_release_version = app_version_match.group(1)
app_bundle_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?: RC(\d+))?", app_release_version)
if app_bundle_match is None:
    raise ValueError("APP_VERSION is not compatible with the macOS bundle version format")
major, minor, patch = (int(value) for value in app_bundle_match.groups()[:3])
if not (1 <= major <= 9999 and 0 <= minor <= 99 and 0 <= patch <= 99):
    raise ValueError("APP_VERSION exceeds the macOS bundle version component limits")
app_bundle_version = f"{major}.{minor}.{patch}"
rc_build = app_bundle_match.group(4)
if rc_build is None:
    app_bundle_build_version = app_bundle_version
else:
    rc_build = int(rc_build)
    if not 1 <= rc_build <= 255:
        raise ValueError("The macOS final-candidate build number must be between 1 and 255")
    app_bundle_build_version = f"{app_bundle_version}fc{rc_build}"

bundle_data = [
    (str(project_root / "static"), "static"),
    (str(project_root / "init.sql"), "."),
]

analysis = Analysis(
    [str(project_root / "app.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=bundle_data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
python_archive = PYZ(analysis.pure)

if sys.platform == "darwin":
    executable = EXE(
        python_archive,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name="DLMS",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    app_bundle = BUNDLE(
        executable,
        analysis.binaries,
        analysis.datas,
        name="DLMS.app",
        icon=str(project_root / "static" / "favicon.ico"),
        bundle_identifier="io.github.drakahari.DLMS",
        version=app_bundle_version,
        info_plist={
            "CFBundleGetInfoString": f"DLMS {app_release_version}",
            "CFBundleVersion": app_bundle_build_version,
        },
    )
else:
    executable = EXE(
        python_archive,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name="DLMS",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
