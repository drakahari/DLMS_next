# Native Windows one-folder Desktop, independent of source/DLMS.spec.
import os
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

if sys.platform != "win32":
    raise RuntimeError("Build this candidate natively on Windows")
root = Path(SPEC).resolve().parents[1]
source = root
sys.path[:0] = [str(root), str(source)]
from tools.pyinstaller_ocr import collect_tesseract_bundle

ocr_binaries, ocr_data = collect_tesseract_bundle(required=True)
identity = Path(os.environ["DLMS_WINDOWS_BUILD_INFO"])
notices = Path(os.environ["DLMS_WINDOWS_NOTICES"])
if not identity.is_file() or not (notices / "INVENTORY.json").is_file():
    raise ValueError("Build identity and notices are required")
datas = [(str(root / "desktop_assets"), "desktop_assets"),
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
analysis = Analysis([str(root / "package_windows/entry.py")], pathex=[str(root), str(source)],
                    binaries=ocr_binaries, datas=datas, hiddenimports=hidden,
                    excludes=["pytest", "tests", "package_fedora.manage", "package_fedora.manage_gui",
                              "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
                              "PySide6.QtQuick3D", "PySide6.QtVirtualKeyboard"],
                    noarchive=False, optimize=0)
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [('X utf8', None, 'OPTION')], exclude_binaries=True, name="DLMS-Desktop",
                 debug=False, strip=False, upx=False, console=False,
                 icon=str(root / "desktop_assets/icons/windows/DLMSDesktop.ico"),
                 version=str(root / "package_windows/version.txt"))
bundle = COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False, name="DLMS-Desktop")
