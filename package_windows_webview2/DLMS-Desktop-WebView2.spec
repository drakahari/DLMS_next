# Native Windows one-folder Desktop, independent of source/DLMS.spec.
import os
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

if sys.platform != "win32":
    raise RuntimeError("Build this candidate natively on Windows")
root = Path(SPEC).resolve().parents[1]
instrumented = os.environ.get('DLMS_WV_BUILD_INSTRUMENTED') == '1'
name = 'DLMS-Desktop-WebView2-Instrumented' if instrumented else 'DLMS-Desktop-WebView2'
entry = root / ('package_windows_webview2/entry_instrumented.py' if instrumented else 'package_windows_webview2/entry.py')
source = root
sys.path[:0] = [str(root), str(source)]
from tools.pyinstaller_ocr import collect_tesseract_bundle

ocr_binaries, ocr_data = collect_tesseract_bundle(required=True)
if os.environ.get('DLMS_WINDOWS_PUBLIC_PREVIEW') == '1':
    import json
    native_root = Path(os.environ['DLMS_WINDOWS_PINNED_NATIVE'])
    native_records = json.loads(Path(os.environ['DLMS_WINDOWS_PINNED_NATIVE_RECORDS']).read_text())
    ocr_binaries += [(str(native_root / record['file']), '.') for record in native_records]
identity = Path(os.environ["DLMS_WINDOWS_BUILD_INFO"])
notices = Path(os.environ["DLMS_WINDOWS_NOTICES"])
if not identity.is_file() or not (notices / "INVENTORY.json").is_file():
    raise ValueError("Build identity and notices are required")
host = Path(os.environ["DLMS_WEBVIEW2_HOST"])
from package_windows_webview2.build import verify_host
verify_host(host)
datas = [(str(host), "windows_webview2"),(str(root / "desktop_assets"), "desktop_assets"),
         (str(root/'fixtures/gate1-neutral-quiz.txt'),'fixtures'),
         (str(source/'tests/fixtures/ocr/pdf/fully-scanned.pdf'),'fixtures'),
         (str(source/'tests/fixtures/ocr/dlms-question.png'),'fixtures'),
         (str(source / "static"), "static"), (str(source / "templates"), "templates"),
         (str(source / "dlms/theme_sources"), "dlms/theme_sources"),
         (str(source / "init.sql"), "."), (str(identity), "desktop_assets"),
         (str(notices), "notices"), *ocr_data,
         *copy_metadata("pypdfium2"), *copy_metadata("tzdata"), *collect_data_files("tzdata")]
hidden = ["app", "pypdfium2", "pypdfium2_raw", "genanki", "tzdata",
          *collect_submodules("dlms"),
          *[x for x in collect_submodules("desktop") if x != "desktop.windows_worker"]]
if instrumented:
    hidden += ['tests.gate1.qt_checks', 'tests.webview2.gui_native_followup',
               'tests.webview2.gui_file_locations', 'tests.webview2.gui_export_locations',
               'tests.webview2.gui_backup_followup', 'tests.webview2.gui_ai_handoff',
               'tests.settings.gui_native_roundtrip']
analysis = Analysis([str(entry)], pathex=[str(root), str(source)],
                    binaries=ocr_binaries, datas=datas, hiddenimports=hidden,
                    excludes=["pytest", *([] if instrumented else ['tests']), "package_fedora.manage", "package_fedora.manage_gui",
                              "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
                              "PySide6.QtQuick3D", "PySide6.QtQuickTimeline", "PySide6.QtWaylandCompositor", "PySide6.QtVirtualKeyboard"],
                    noarchive=False, optimize=0)
if os.environ.get('DLMS_WINDOWS_PUBLIC_PREVIEW') == '1':
    from package_windows_webview2.preview_bundle import prune
    from package_windows_webview2.native_inputs import verify_collected
    verify_collected(analysis.binaries, native_root, native_records)
    import json
    analysis.binaries, analysis.datas, removed = prune(analysis.binaries, analysis.datas)
    (identity.parent / 'preview-exclusions.json').write_text(json.dumps(removed, indent=2) + '\n')
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [('X utf8', None, 'OPTION')], exclude_binaries=True, name=name,
                 debug=False, strip=False, upx=False, console=False,
                 icon=str(root / "desktop_assets/icons/windows/DLMSDesktop.ico"),
                 version=os.environ.get('DLMS_WINDOWS_VERSION_RESOURCE', str(root / "package_windows_webview2/version.txt")))
bundle = COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False, name=name)
