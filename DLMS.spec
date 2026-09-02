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
app_bundle_version = app_release_version.split(" ", 1)[0]

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
        info_plist={"CFBundleGetInfoString": f"DLMS {app_release_version}"},
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
