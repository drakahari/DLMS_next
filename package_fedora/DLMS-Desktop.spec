# -*- mode: python ; coding: utf-8 -*-
"""Fedora one-folder development package; no installer or release metadata."""
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPEC).resolve().parent.parent
source = root
sys.path[:0] = [str(source), str(root)]
from tools.pyinstaller_ocr import collect_tesseract_bundle

instrumented = os.environ.get("DLMS_DESKTOP_BUILD_INSTRUMENTED") == "1"
minimal = os.environ.get('DLMS_DESKTOP_MINIMAL_BUNDLE') == '1'
host_platform = os.environ.get('DLMS_DESKTOP_HOST_PLATFORM_LIBS') == '1'
if host_platform and not sys.platform.startswith('linux'):
    raise ValueError('Host platform exclusions are qualified for Linux only')
name = "DLMS-Desktop-Instrumented" if instrumented else "DLMS-Desktop"
entry = root / "package_fedora" / ("entry_instrumented.py" if instrumented else "entry_normal.py")
ocr_binaries, ocr_data = collect_tesseract_bundle(required=True)
build_info = Path(os.environ['DLMS_DESKTOP_BUILD_INFO']).resolve()
notices = Path(os.environ['DLMS_DESKTOP_NOTICE_ROOT']).resolve()
if not build_info.is_file() or not (notices/'INVENTORY.json').is_file():
    raise ValueError('Verified build identity and available notice inputs are required')
datas = [
    (str(root / "desktop_assets"), "desktop_assets"),
    (str(source / "static"), "static"),
    (str(source / "templates"), "templates"),
    (str(source / "dlms" / "theme_sources"), "dlms/theme_sources"),
    (str(source / "init.sql"), "."),
    (str(source / "LICENSE"), "notices/source"),
    *ocr_data,
    (str(build_info), "desktop_assets"),
    (str(notices), "notices/available-build-texts"),
    *copy_metadata("pypdfium2"),
    *copy_metadata("tzdata"),
    *collect_data_files("tzdata"),
]
# Optional verified distribution texts; old build invocations remain valid.
distribution_root = os.environ.get('DLMS_DESKTOP_DISTRIBUTION_ROOT')
if distribution_root:
    from package_fedora.assemble_distribution import verify_materials
    verified_distribution = Path(distribution_root).resolve()
    verify_materials(verified_distribution)
    datas.append((str(verified_distribution), 'notices/distribution'))
hidden = ["compression.zstd", "_zstd", "package_fedora", "package_fedora.manage", "package_fedora.manage_gui",
          "package_fedora.installation", "package_fedora.manual_replace", "package_fedora.replace_pilot",
          "package_fedora.install_pilot", "app", "pypdfium2", "pypdfium2_raw", "genanki", "tzdata",
          *collect_submodules("dlms"), *collect_submodules("desktop")]
if instrumented:
    datas.append((str(root / "fixtures" / "gate1-neutral-quiz.txt"), "fixtures"))
    hidden.extend([
        "tests.linux_windows.gui_matrix", "tests.linux_windows.gui_exports",
        "tests.file_selection.gui_workflows", "tests.file_selection.gui_boundary", "tests.file_selection.gui_focus",
        "tests.daily_use.gui_downloads", "tests.daily_use.journeys_certifications",
        "tests.daily_use.journeys_validation",
        "tests.server_mode.gui_navigation_surface",
        "tests.shutdown.gui_lifecycle",
        "tests.gate1.qt_checks", "tests.gate1.lifecycle_integration",
        "tests.gate1.gui_foundation", "tests.gate1.gui_compatibility",
        "tests.gate1.gui_ocr_pdf", "tests.gate1.gui_clipboard_focus",
        "tests.gate1.gui_study_pending", "tests.gate1.gui_exam_recovery",
        "tests.data_safety.gui_managed_retry", "tests.data_safety.managed_import_smoke",
        "tests.data_safety.audit_managed_import",
        "tests.package.gui_completed_import",
        "tests.parity.gui_matching_mixed",
        "tests.blocka.gui_durable_crash",
        "tests.blockb.gui_menu_adoption", "tests.blockb.gui_adoption",
        "tests.completion.gui_maintenance_scope", "tests.data_safety.gui_pending_import_gate",
        "tests.package.gui_mixed_packaged",
        "tests.daily_backup.gui_workflow", "tests.settings.gui_native_roundtrip",
    ])
analysis = Analysis(
    [str(entry)], pathex=[str(root), str(source)], binaries=ocr_binaries,
    datas=datas, hiddenimports=hidden, hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=['readline'] if minimal else [], noarchive=False, optimize=0,
)
if minimal:
    from package_fedora.minimal_bundle import prune
    import json
    analysis.binaries, analysis.datas, removed = prune(analysis.binaries, analysis.datas)
    report = Path(os.environ['DLMS_DESKTOP_MINIMAL_REPORT']).resolve()
    if report.exists():
        raise FileExistsError('Minimal bundle evidence destination exists; preserve it')
    report.write_text(json.dumps({'scope':'Unused Qt families/optional Readline only',
                                  'removed':removed}, indent=2) + '\n')
if host_platform:
    from package_linux.host_platform import prune as prune_platform, write_manifest
    analysis.binaries, analysis.datas, removed_platform = prune_platform(analysis.binaries, analysis.datas)
    platform_report = Path(os.environ['DLMS_DESKTOP_HOST_PLATFORM_REPORT']).resolve()
    write_manifest(platform_report, removed_platform)
    analysis.datas.append(('desktop_assets/host-platform.json', str(platform_report), 'DATA'))
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True, name=name,
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True,
)
bundle = COLLECT(executable, analysis.binaries, analysis.datas,
                 strip=False, upx=False, name=name)
if minimal:
    from package_fedora.minimal_bundle import verify_payload
    verify_payload(Path(bundle.name))
if host_platform:
    from package_linux.host_platform import verify_payload as verify_platform_payload
    verify_platform_payload(Path(bundle.name))
