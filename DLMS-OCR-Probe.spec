# -*- mode: python ; coding: utf-8 -*-
"""Strict frozen OCR runtime probe for native release builders."""

import sys
from pathlib import Path


project_root = Path(SPEC).resolve().parent
sys.path.insert(0, str(project_root))
from tools.pyinstaller_ocr import collect_tesseract_bundle

ocr_binaries, ocr_data = collect_tesseract_bundle(required=True)
probe_data = [
    (str(project_root / "tests" / "fixtures" / "ocr" / "dlms-question.png"), "ocr-probe"),
]
probe_data.extend(ocr_data)

analysis = Analysis(
    [str(project_root / "tools" / "ocr_packaging_probe.py")],
    pathex=[str(project_root)],
    binaries=ocr_binaries,
    datas=probe_data,
    hiddenimports=["dlms.services.ocr"],
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
    name="DLMS-OCR-Probe",
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
