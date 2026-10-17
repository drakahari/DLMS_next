# Apple Silicon private Desktop host. Browser-edition DLMS.spec is independent.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPEC).resolve().parents[1]
import sys
sys.path.insert(0, str(root))
from tools.pyinstaller_ocr import collect_tesseract_bundle

binaries, data = collect_tesseract_bundle(required=True)
data += [(str(root / p), p) for p in ('templates', 'static', 'desktop_assets')]
data += [(str(root / 'init.sql'), '.'),
         (str(root / 'dlms/theme_sources'), 'dlms/theme_sources'),
         (os.environ['DLMS_MACOS_BUILD_INFO'], 'desktop_assets'),
         (os.environ['DLMS_MACOS_NOTICES'], 'notices'),
         *copy_metadata('pypdfium2'), *copy_metadata('tzdata'), *collect_data_files('tzdata')]
analysis = Analysis([str(root / 'package_macos/entry.py')], pathex=[str(root)],
    binaries=binaries, datas=data,
    hiddenimports=['app', 'compression.zstd', '_zstd', 'pypdfium2', 'pypdfium2_raw',
                   'genanki', 'tzdata', *collect_submodules('dlms'),
                   *collect_submodules('desktop'), *collect_submodules('package_macos')],
    hookspath=[], runtime_hooks=[], excludes=['readline'], noarchive=False, optimize=0)
# Qt ships developer static archives alongside QML plugins. They cannot be
# loaded by WebEngine or dyld and are not part of the executable arm64 payload.
analysis.datas = [row for row in analysis.datas if not row[0].endswith('.a')]
analysis.binaries = [row for row in analysis.binaries if not row[0].endswith('.a')]
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True,
    name='DLMS-Desktop', console=False, debug=False, strip=False, upx=False,
    argv_emulation=False, target_arch='arm64', codesign_identity=None,
    entitlements_file=None)
bundle = BUNDLE(executable, analysis.binaries, analysis.datas,
    name='DLMS Desktop Candidate.app',
    icon=str(root / 'desktop_assets/icons/macos/DLMSDesktop.icns'),
    bundle_identifier='io.github.drakahari.DLMSDesktop.MacCandidate', version='0.1.0',
    info_plist={'CFBundleDisplayName': 'DLMS Desktop Candidate',
                'CFBundleShortVersionString': '0.1.0', 'CFBundleVersion': '1',
                'LSMinimumSystemVersion': '26.6.2', 'NSHighResolutionCapable': True,
                'NSDocumentsFolderUsageDescription': 'Choose synthetic quiz inputs and save candidate exports and backups.',
                'NSDownloadsFolderUsageDescription': 'Choose synthetic inputs and save candidate exports and backups.'})
