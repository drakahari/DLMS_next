"""Build a new private arm64 .app/DMG offline; never install or alter security."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(arguments, **kwargs):
    return subprocess.run(arguments, check=True, **kwargs)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def runtime_inventory():
    files = []
    for tree in ('desktop', 'dlms', 'package_macos', 'templates', 'static', 'desktop_assets'):
        files.extend(p for p in (ROOT / tree).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc')
    files += [ROOT / p for p in ('app.py', 'init.sql', 'requirements-lock.txt', 'desktop/requirements-lock.txt')]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(files))}


def app_inventory(app):
    files = {}
    for path in sorted(app.rglob('*')):
        relative = str(path.relative_to(app))
        if path.is_symlink():
            if not path.resolve().is_relative_to(app.resolve()):
                raise ValueError('Packaged symlink escapes application: ' + relative)
            files[relative] = {'symlink': os.readlink(path)}
        elif path.is_file():
            files[relative] = {'sha256': digest(path), 'mode': path.stat().st_mode & 0o777}
    return files


def prepare_materials(stage):
    from tools.prepare_ocr_bundle import BundleSources, prepare_bundle
    executable = Path('/opt/homebrew/bin/tesseract').resolve(strict=True)
    tessdata = Path('/opt/homebrew/share/tessdata').resolve(strict=True)
    prefix = Path('/opt/homebrew/Cellar/leptonica')
    libraries = sorted(prefix.glob('*/lib/libleptonica.*.dylib'))
    if len(libraries) != 1:
        raise ValueError('Select an unambiguous installed Leptonica source before packaging')
    lept = libraries[0].parents[1]
    header = (lept / 'include/leptonica/allheaders.h').read_text()
    license_text = header[:header.index('*/') + 2] + '\n'
    license_file = stage / 'leptonica-LICENSE.txt'
    license_file.write_text(license_text)
    tesseract_license = executable.parents[1] / 'LICENSE'
    ocr = prepare_bundle(BundleSources('macos', executable, tessdata,
                         tesseract_license, tesseract_license, license_file),
                         stage / 'ocr', repository_root=ROOT)
    notices = stage / 'notices'
    notices.mkdir()
    shutil.copy2(ROOT / 'LICENSE', notices / 'application-LICENSE')
    wheelhouse = ROOT / '.gate1/macos/wheelhouse'
    download = json.loads((wheelhouse.parent / 'wheelhouse.json').read_text())
    for name, expected in download['wheels'].items():
        wheel = wheelhouse / name
        if digest(wheel) != expected:
            raise ValueError('Downloaded wheel changed: ' + name)
        with zipfile.ZipFile(wheel) as archive:
            for item in archive.namelist():
                if not item.endswith('/') and ('.dist-info/licenses/' in item or '.dist-info/' in item
                        and Path(item).name.casefold().startswith(('license', 'copying', 'notice'))):
                    target = notices / name / item
                    if '..' in Path(item).parts or Path(item).is_absolute():
                        raise ValueError('Unsafe wheel license member')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(item))
    # Record exact local native inputs; their distribution/source obligations
    # remain unresolved. This inventory is not a grant of redistribution rights.
    native = {}
    pending = [executable]
    while pending:
        path = pending.pop().resolve()
        if str(path) in native:
            continue
        run(['/usr/bin/lipo', '-verify_arch', 'arm64', str(path)], stdout=subprocess.DEVNULL)
        linked = subprocess.check_output(['/usr/bin/otool', '-L', str(path)], text=True)
        native[str(path)] = {'sha256': digest(path), 'links': linked.splitlines()[1:]}
        for line in linked.splitlines()[1:]:
            name = line.strip().split(' (', 1)[0]
            if name.startswith('/opt/homebrew/'):
                pending.append(Path(name))
    (notices / 'native-inputs.json').write_text(json.dumps(native, indent=2) + '\n')
    (notices / 'PRIVATE-CANDIDATE.txt').write_text(
        'Synthetic-data private candidate only. No redistribution clearance.\n'
        'No Developer ID signature or notarization. Build uses local ad hoc integrity signatures.\n'
        'Desktop/icon grants and exact Qt/PDFium/Tesseract/native library source, notice and replacement obligations remain unresolved.\n'
        'Leptonica notice is reproduced from the installed matching header; no source-offer sufficiency is claimed.\n'
        'Native immutable upload flags can be deliberately cleared by the same user. Production uploads remain unqualified.\n')
    return ocr, notices, native


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-only', action='store_true', help='defer DMG creation to normal Terminal if device access is blocked')
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64' or sys.version_info[:3] != (3, 14, 7):
        raise SystemExit('Requires native arm64 macOS with the pinned Python 3.14.7 environment')
    # This Mac's Documents provider reattaches FinderInfo to .framework/.app
    # directories, which Apple codesign refuses. Build in a dedicated private
    # cache outside the provider; retain repository evidence separately.
    from desktop.macos_paths import real_home
    work = real_home() / '.cache/dlms-desktop-macos-candidate'
    for part in (work.parent, work):
        if part.is_symlink() or (part.exists() and (not part.is_dir()
                or part.stat().st_uid != os.getuid() or part.stat().st_mode & 0o022)):
            raise ValueError('Unsafe private macOS build cache')
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='build-', dir=work))
    inventory = runtime_inventory()
    snapshot = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    ocr, notices, native = prepare_materials(stage)
    identity = {'application_version': '3.3.0', 'release': 'macos-arm64-private-candidate',
                'source_commit': commit + '+snapshot:' + snapshot,
                'target': 'Apple Silicon macOS 26.6.2 (current host only)',
                'support': 'Synthetic-data private candidate; ad hoc only, not notarized; production uploads/public release unqualified'}
    info = stage / 'build-info.json'
    info.write_text(json.dumps(identity, indent=2) + '\n')
    environment = os.environ.copy()
    environment.update(DLMS_TESSERACT_BUNDLE_ROOT=str(ocr), DLMS_MACOS_BUILD_INFO=str(info),
                       DLMS_MACOS_NOTICES=str(notices), PYINSTALLER_CONFIG_DIR=str(stage / 'pyinstaller-cache'))
    for key in ('QTWEBENGINE_DISABLE_SANDBOX', 'QTWEBENGINE_CHROMIUM_FLAGS'):
        environment.pop(key, None)
    log = stage / 'build.log'
    with log.open('w') as output:
        run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
             '--distpath', str(stage / 'dist'), '--workpath', str(stage / 'work'),
             str(ROOT / 'package_macos/DLMS-Desktop.spec')], cwd=ROOT, env=environment,
            stdout=output, stderr=subprocess.STDOUT)
    app = stage / 'dist/DLMS Desktop Candidate.app'
    # Finder metadata may be attached to freshly generated frameworks by the
    # Documents file provider. Remove only signing-incompatible build metadata;
    # never remove quarantine or alter trust/security settings.
    for attribute in ('com.apple.FinderInfo', 'com.apple.ResourceFork'):
        run(['/usr/bin/xattr', '-dr', attribute, str(app)])
    run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', '--timestamp=none', str(app)])
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])
    macho = {}
    for path in app.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as stream:
            magic = stream.read(4)
        if magic not in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
            continue
        architectures = subprocess.check_output(['/usr/bin/lipo', '-archs', str(path)], text=True).strip()
        if architectures != 'arm64':
            raise ValueError('Unexpected packaged architecture: ' + str(path) + ' ' + architectures)
        links = subprocess.check_output(['/usr/bin/otool', '-L', str(path)], text=True)
        if '/opt/homebrew/' in links or str(ROOT) in links:
            raise ValueError('Packaged binary retains a developer-machine link: ' + str(path))
        macho[str(path.relative_to(app))] = {'sha256': digest(path), 'architecture': architectures}
    manifest = app_inventory(app)
    manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    (stage / 'APP_MANIFEST.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    provenance = {'baseline': 'ab89dfef650168697fed0e948a3b202cb2eb6ddf', 'head': commit,
                  'snapshot_sha256': snapshot, 'runtime_files': inventory, 'macho': macho,
                  'app_manifest_sha256': manifest_hash,
                  'native_inputs': native, 'build_info': identity,
                  'python': platform.python_version(), 'macos': platform.mac_ver()[0],
                  'dependencies': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()},
                  'signing': 'ad hoc integrity only; no Developer ID; not notarized',
                  'app': str(app), 'qualified': False}
    (stage / 'PROVENANCE.json').write_text(json.dumps(provenance, indent=2) + '\n')
    (ROOT / '.gate1/macos/CANDIDATE.json').write_text(json.dumps({
        'stage': str(stage), 'app': str(app), 'snapshot_sha256': snapshot,
        'app_manifest_sha256': manifest_hash}, indent=2) + '\n')
    if not args.app_only:
        create_dmg(stage, app)
    print(json.dumps({'stage': str(stage), 'app': str(app), 'native_binaries': len(macho)}, indent=2))
    return 0


def create_dmg(stage, app):
    image = stage / 'DLMS-Desktop-macos-arm64-private.dmg'
    if image.exists():
        raise FileExistsError('Preserve existing DMG evidence')
    run(['/usr/bin/hdiutil', 'create', '-format', 'UDZO', '-volname', 'DLMS Desktop Candidate',
         '-srcfolder', str(app.parent), str(image)])
    run(['/usr/bin/hdiutil', 'verify', str(image)])
    (stage / 'SHA256SUMS').write_text(digest(image) + '  ' + image.name + '\n')
    return image


if __name__ == '__main__':
    raise SystemExit(main())
