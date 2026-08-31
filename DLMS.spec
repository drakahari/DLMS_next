# -*- mode: python ; coding: utf-8 -*-
"""Canonical one-file PyInstaller build for DLMS.

Only the application entry point and the two required local data inputs are
declared here. Runtime data always belongs in the per-user DLMS data root and
must never be added to this manifest.
"""

from pathlib import Path


project_root = Path(SPEC).resolve().parent
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
