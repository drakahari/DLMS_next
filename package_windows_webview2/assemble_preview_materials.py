"""Assemble Windows recipient materials from verified Linux and Windows inputs.

No downloads, package scripts, private history, profiles, or installed data.
Supply the published Linux companions, reviewed Windows OCR source/recipe kit,
Windows CPython external sources and the pinned Windows wheel cache.
"""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LINUX_ARCHIVES = {
    'DLMS-Desktop-3.3.0-preview1-source-python.tar.zst': '40d78ccaad2cb0aadcca96f7f9cfeff06cba11e2de794ec45146954190b141f1',
    'DLMS-Desktop-3.3.0-preview1-source-qt-pyside.tar': '2d5f30392243200188b7df70563ba9d40e9847d695c979f628e38543d9d6ff73',
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plain_files(root):
    for path in (root, *root.rglob('*')):
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Source/material aliases refused')
        if path.is_file():
            yield path
        elif not path.is_dir():
            raise ValueError('Nonregular source/material input')


def archive_tree(target, root, *, exclude=()):
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in plain_files(root):
            if path.name not in exclude:
                archive.write(path, path.relative_to(root).as_posix())


def main():
    parser = argparse.ArgumentParser()
    for name in ('linux-materials', 'native-sources', 'python-extras', 'installer-sources', 'wheelhouse', 'output', 'delivery'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    args.delivery.mkdir(parents=True, exist_ok=False)
    kit = args.output
    sources = []

    def record(path, role):
        sources.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path), 'role': role})

    for name, expected in LINUX_ARCHIVES.items():
        source = args.linux_materials / name
        if digest(source) != expected:
            raise ValueError('Published Linux source companion changed')
        target = args.delivery / name.replace('preview1-', 'windows-preview1-shared-')
        shutil.copyfile(source, target)
        record(target, 'Unmodified published Linux shared source companion; Windows differences indexed separately')

    native_index = json.loads((args.native_sources / 'SOURCE_INDEX_FINAL.json').read_text())
    for row in native_index:
        for source in row['sources']:
            if 'file' in source:
                relative = Path(source['file'].replace('\\', '/'))
                if relative.is_absolute() or '..' in relative.parts or relative.drive:
                    raise ValueError('Escaping source index')
                if digest(args.native_sources / relative) != source['sha256']:
                    raise ValueError('Exact Windows native source changed')
    archive = args.delivery / 'DLMS-Desktop-3.3.0-windows-preview1-source-native.zip'
    archive_tree(archive, args.native_sources, exclude=('ACQUISITION.json', 'SOURCE_INDEX.json'))
    record(archive, 'Windows conda producer sources, recipes, patches and notices, including static LZO')
    extras_index = json.loads((args.python_extras / 'SOURCE_INDEX.json').read_text())
    for row in extras_index:
        matches = [p for p in args.python_extras.iterdir() if p.is_file() and p.name.startswith(row['name']) and p.suffix != '.json']
        if len(matches) != 1 or digest(matches[0]) != row['sha256']:
            raise ValueError('Windows Python source changed')
    archive = args.delivery / 'DLMS-Desktop-3.3.0-windows-preview1-source-python-extras.zip'
    archive_tree(archive, args.python_extras)
    record(archive, 'Official matching Windows CPython external tags and Windows-specific Python package sources')
    python_source = args.linux_materials / 'source-native/native-build-sources/Python-3.14.7.tar.xz'
    if digest(python_source) != '3b48dac8fb59f62eaa67ac83c1eb12bda1b7a08406dd286e252c11a66be27f81':
        raise ValueError('CPython source differs from pinned release')
    shutil.copyfile(python_source, args.delivery / python_source.name)
    record(args.delivery / python_source.name, 'Exact CPython3.14.7 source including Windows PCbuild instructions')
    installer_index=json.loads((args.installer_sources/'SOURCE_INDEX.json').read_text())
    installer_source=args.installer_sources/'innosetup-7.1.0-source.tar.gz'
    if digest(installer_source)!=installer_index['source_sha256']:
        raise ValueError('Matching installer engine source changed')
    installer_target=args.delivery/'DLMS-Desktop-3.3.0-windows-preview1-source-installer.tar.gz'
    shutil.copyfile(installer_source,installer_target)
    record(installer_target,'Official Inno7.1.0 installer engine source; separate from application runtime')

    wheel_rows = json.loads((ROOT / 'package_windows/wheels-lock.json').read_text())
    for row in wheel_rows:
        if digest(args.wheelhouse / row['file']) != row['sha256']:
            raise ValueError('Pinned Windows wheel differs: ' + row['file'])
    for dist in metadata.distributions():
        name = dist.metadata['Name']
        for item in dist.files or []:
            if any(word in str(item).lower() for word in ('license', 'notice', 'copying')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = kit / 'wheels' / name / str(item)
                    if not target.resolve().is_relative_to(kit.resolve()):
                        raise ValueError('Escaping wheel notice path')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    linux_texts = args.linux_materials / 'notices/distribution-kit/upstream-texts'
    for name in ('Qt-6.11.2', 'PySide-Shiboken-6.11.2', 'Chromium-source-metadata'):
        shutil.copytree(linux_texts / name, kit / 'upstream-texts' / name)
    # Keep only relevant license texts; no Ubuntu/AppImage binary mappings are reused.
    shutil.copytree(args.linux_materials / 'notices/distribution-kit/common-licenses', kit / 'common-licenses')
    for row in native_index:
        source = args.native_sources / row['package'] / 'licenses'
        if source.is_dir():
            shutil.copytree(source, kit / 'native' / row['package'])
    for name in ('LICENSE', 'desktop_assets/ICON_PROVENANCE.md'):
        shutil.copyfile(ROOT / name, kit / Path(name).name)
    vendor=kit/'vendor';vendor.mkdir()
    shutil.copyfile(ROOT/'.gate1/windows-native/inno-portable/license.txt',vendor/'Inno-Setup-7.1.0-LICENSE.txt')
    shutil.copyfile(ROOT/'.gate1/windows-native/webview2-inputs-01/sdk/LICENSE.txt',vendor/'Microsoft-WebView2-SDK-LICENSE.txt')
    shutil.copyfile(ROOT/'package_fedora/notices/CPython-3.14.7-LICENSE',vendor/'CPython-3.14.7-LICENSE.txt')
    # CPython's Windows source tag carries the external OpenSSL license omitted by
    # the NuGet top-level text. Copy actual upstream license files from the archive.
    for source in args.python_extras.glob('*.zip'):
        with zipfile.ZipFile(source) as archive:
            for name in archive.namelist():
                if Path(name).name.lower().startswith(('license', 'copying', 'notice')) and not name.endswith('/'):
                    target = kit / 'python-native' / source.stem / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))

    exact = {'scope': 'Windows x86-64 inputs; technical correspondence, not legal certification',
             'wheels': wheel_rows, 'ocr_native': native_index, 'windows_python': extras_index,
             'shared_sources': sources,
             'excluded_linux_only_materials': ['Ubuntu native mapping', 'AppImage runtime', 'ELF ABI floor'],
             'microsoft_runtime': 'WebView2 Evergreen and .NET Framework are system prerequisites, not bundled; SDK loader/DLLs retain Microsoft SDK license'}
    (kit / 'EXACT_INPUTS.json').write_text(json.dumps(exact, indent=2) + '\n')
    for name in ('REDISTRIBUTION.md', 'BUILD_AND_REPLACEMENT.md'):
        shutil.copyfile(ROOT / 'docs/windows-preview' / name, kit / name)

    # Export only the public index plus the explicit working-tree implementation.
    # No private Git objects/history, .gate1, profiles, logs, backups or build output.
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    extra = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    selected = sorted(set(p for p in files + extra if p and (ROOT / p).is_file()))
    if any(p.split('/')[0] in ('.gate1', '.git', '.venv', 'dist', 'profiles') for p in selected):
        raise ValueError('Private/build data in source export')
    application = args.delivery / 'DLMS-Desktop-3.3.0-windows-preview1-source-application.zip'
    with zipfile.ZipFile(application, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name in selected:
            archive.write(ROOT / name, 'DLMS-source/' + name)
    record(application, 'Public baseline plus reviewed Windows working-tree changes; no private history')
    (kit / 'SOURCE_MATERIALS.json').write_text(json.dumps({'archives': sources, 'unresolved': [],
        'application_base': '58bcd13870b97c44201226ca3cf064772444a5ae',
        'scope': 'Technical source and recipient materials; not legal certification or vendor binary reproducibility'}, indent=2) + '\n')
    manifest = {'format': 1, 'platform': 'windows-x86_64-preview',
                'sha256': {p.relative_to(kit).as_posix(): digest(p) for p in plain_files(kit)}}
    (kit / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    from .preview_materials import verify
    verify(kit)
    archive = args.delivery / 'DLMS-Desktop-3.3.0-windows-preview1-notices.zip'
    archive_tree(archive, kit)
    print(json.dumps({'kit': str(kit), 'delivery': str(args.delivery), 'source_archives': sources}, indent=2))


if __name__ == '__main__':
    main()
