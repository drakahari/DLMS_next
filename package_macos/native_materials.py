"""Match native Mac inputs to their actual Homebrew producers and source material.

Reads installed inputs only. Acquired files are inert; nothing in this module
installs, imports, builds or executes downloaded code.
"""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import urllib.parse
import urllib.request

CELLAR = Path('/opt/homebrew/Cellar')
CACHE_NAME = '.cache/dlms-desktop-macos-preview/sources/native'
MACHO = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def _output(*args):
    return subprocess.check_output(args, text=True, timeout=30)


def _macho(path):
    with path.open('rb') as stream:
        return stream.read(4) in MACHO


def _links(path):
    return [line.strip().split(' (', 1)[0] for line in
            _output('/usr/bin/otool', '-L', str(path)).splitlines()[1:]]


def _rpaths(path):
    lines = _output('/usr/bin/otool', '-l', str(path)).splitlines()
    return [lines[i + 2].strip().split('path ', 1)[1].split(' (', 1)[0]
            for i, line in enumerate(lines) if line.strip() == 'cmd LC_RPATH']


def _resolve_link(name, owner):
    if name.startswith(('/usr/lib/', '/System/Library/')):
        return None  # supplied by macOS, never bundled by this helper
    if name.startswith('/opt/homebrew/'):
        return Path(name).resolve(strict=True)
    if name.startswith('@loader_path/'):
        return (owner.parent / name.removeprefix('@loader_path/')).resolve(strict=True)
    if name.startswith('@rpath/'):
        suffix = name.removeprefix('@rpath/')
        candidates = [owner.parent / suffix]
        for base in _rpaths(owner):
            if base.startswith('@loader_path'):
                base = str(owner.parent) + base.removeprefix('@loader_path')
            if base.startswith('/'):
                candidates.append(Path(base) / suffix)
        found = {p.resolve() for p in candidates if p.is_file()}
        if len(found) == 1:
            return found.pop()
    raise ValueError('Unresolved non-system native dependency: ' + name)


def installed_roots():
    python = CELLAR / 'python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14'
    roots = [CELLAR / 'tesseract/5.5.3/bin/tesseract', python / 'Python']
    roots.extend(sorted((python / 'lib/python3.14/lib-dynload').glob('*.so')))
    if len(roots) < 3:
        raise ValueError('Pinned native Python extension inputs are missing')
    return roots


def native_closure(roots=None):
    """Follow real load commands including @rpath, not a cross-platform mapping."""
    pending = list(installed_roots() if roots is None else roots)
    result = {}
    while pending:
        path = pending.pop().resolve(strict=True)
        if path in result:
            continue
        if not path.is_relative_to(CELLAR) or not _macho(path):
            raise ValueError('Unexpected native input location or file type')
        links = _links(path)
        resolved = [p for name in links if (p := _resolve_link(name, path)) is not None]
        result[path] = {'sha256': sha256(path), 'links': links,
                        'architecture': _output('/usr/bin/lipo', '-archs', str(path)).strip()}
        if result[path]['architecture'] != 'arm64':
            raise ValueError('Native producer is not arm64: ' + path.name)
        pending.extend(resolved)
    return result


def _stable_source(formula):
    # Only the main stable source, before head/resources/conditional blocks.
    url = re.search(r'^  url "(https://[^"\n]+)"', formula, re.M)
    digest = re.search(r'^  sha256 "([a-f0-9]{64})"', formula, re.M)
    if not url or not digest:
        raise ValueError('Cannot identify exact stable formula source')
    return {'url': url[1], 'sha256': digest[1]}


def _license_expression(formula):
    lines = formula.splitlines()
    start = next(i for i, value in enumerate(lines) if value.startswith('  license '))
    statement = [lines[start].removeprefix('  license ')]
    balance = statement[0].count('[') - statement[0].count(']')
    for line in lines[start + 1:]:
        if balance <= 0:
            break
        statement.append(line.strip())
        balance += line.count('[') - line.count(']')
    return '\n'.join(statement)


def _source_notices(archive, folder):
    """Copy bounded top-level notice text, never extract archive paths or links."""
    result = []
    with tarfile.open(archive) as bundle:
        for member in bundle:
            parts = Path(member.name).parts
            name = parts[-1] if parts else ''
            if (len(parts) != 2 or not member.isfile() or member.size > 2 * 1024 * 1024
                    or not re.match(r'(?i)^(license|copying|copyright|notice|leptonica-license|readme\.ijg)', name)):
                continue
            target = folder / ('source-' + name)
            with bundle.extractfile(member) as stream:
                _write(target, stream.read())
            result.append(str(Path(folder.name) / target.name))
    return result


def _sanitized_receipt(value):
    # Whitelist producer facts. Excludes source.path (personal cache path).
    keys = ('homebrew_version', 'used_options', 'unused_options', 'built_as_bottle',
            'poured_from_bottle', 'compiler', 'arch', 'built_on', 'runtime_dependencies',
            'changed_files', 'binary_relocation_files', 'source_modified_time')
    result = {key: value[key] for key in keys if key in value}
    source = value['source']
    result['source'] = {key: source[key] for key in ('spec', 'versions', 'tap', 'tap_git_head')
                        if key in source}
    return result


def _safe_directory(path):
    for parent in reversed([path, *path.parents]):
        if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
            raise ValueError('Unsafe native material directory')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def _write(path, content):
    raw = content.encode() if isinstance(content, str) else content
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError('Preserve conflicting material: ' + path.name)
        return
    with path.open('xb') as stream:
        stream.write(raw)


def _get(source, target, download):
    if target.exists():
        if target.is_symlink() or sha256(target) != source['sha256']:
            raise ValueError('Source archive checksum mismatch: ' + target.name)
        return True
    if not download:
        return False
    if urllib.parse.urlsplit(source['url']).scheme != 'https':
        raise ValueError('Sources require HTTPS')
    part = target.with_suffix(target.suffix + '.part')
    if part.exists():
        raise FileExistsError('Preserve partial source evidence: ' + part.name)
    # No cookies, credentials, shell, package manager, extraction or execution.
    request = urllib.request.Request(source['url'], headers={'User-Agent': 'DLMS-native-source-materials/1'})
    with urllib.request.urlopen(request, timeout=40) as response, part.open('xb') as output:
        if urllib.parse.urlsplit(response.geturl()).scheme != 'https':
            raise ValueError('Source redirected away from HTTPS')
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > 1024 * 1024 * 1024:
                raise ValueError('Source download exceeds one GiB bound')
            output.write(block)
    if sha256(part) != source['sha256']:
        raise ValueError('Downloaded source checksum mismatch: ' + target.name)
    os.rename(part, target)
    return True


def _producer_bottle(name, version, receipt):
    """Recover the producer revision from its cached, matching arm64 bottle."""
    cache = Path.home() / 'Library/Caches/Homebrew/downloads'
    matches = []
    for path in cache.glob('*--' + name + '-' + version + '*.bottle_manifest.json'):
        value = json.loads(path.read_text())
        for item in value.get('manifests', []):
            annotations = item.get('annotations', {})
            if '.arm64_tahoe' not in annotations.get('org.opencontainers.image.ref.name', ''):
                continue
            tab = json.loads(annotations.get('sh.brew.tab', '{}'))
            if (tab.get('source_modified_time') != receipt['source_modified_time']
                    or tab.get('homebrew_version') != receipt['homebrew_version']):
                continue
            metadata = value.get('annotations', {})
            revision = metadata.get('org.opencontainers.image.revision')
            if revision is not None and not re.fullmatch('[a-f0-9]{40}', revision):
                raise ValueError('Invalid producer core revision')
            matches.append({'manifest_sha256': sha256(path), 'core_revision': revision,
                            'formula_url': metadata.get('org.opencontainers.image.source'),
                            'bottle_sha256': annotations.get('sh.brew.bottle.digest'),
                            'bottle_ref': annotations['org.opencontainers.image.ref.name']})
    if len(matches) > 1:
        raise ValueError('Ambiguous exact producer bottle')
    return matches[0] if matches else None


def _pinned_patch(folder, relative, revision, download):
    # The immutable full core revision comes from the exact producer bottle,
    # rather than today's formula. Save a separate initial-acquisition digest.
    url = 'https://raw.githubusercontent.com/Homebrew/homebrew-core/' + revision + '/' + relative
    target = folder / Path(relative).name
    receipt = target.with_suffix(target.suffix + '.json')
    if target.exists():
        facts = json.loads(receipt.read_text())
        if facts['url'] != url or facts['sha256'] != sha256(target) or target.is_symlink():
            raise ValueError('Pinned producer patch changed')
        return facts
    if not download:
        return None
    request = urllib.request.Request(url, headers={'User-Agent': 'DLMS-native-source-materials/1'})
    with urllib.request.urlopen(request, timeout=40) as response:
        if not response.geturl().startswith('https://'):
            raise ValueError('Producer patch redirected away from HTTPS')
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024 or not raw or b'\x00' in raw:
        raise ValueError('Unexpected producer patch content')
    facts = {'url': url, 'sha256': hashlib.sha256(raw).hexdigest(),
             'producer_core_revision': revision,
             'verification': 'HTTPS file at full immutable producer revision; initial digest recorded, not a formula-supplied digest'}
    _write(target, raw)
    _write(receipt, json.dumps(facts, indent=2, sort_keys=True) + '\n')
    return facts


def prepare(destination=None, *, download=False):
    """Write sanitized local producer evidence and acquire exact source archives.

    JSON index is honest about unresolved exact patch material. It is not a
    declaration that a source-offer/relinking obligation has been satisfied.
    """
    destination = Path.home() / CACHE_NAME if destination is None else Path(destination)
    _safe_directory(destination)
    _write(destination / 'Homebrew-LICENSE.txt', Path('/opt/homebrew/LICENSE.txt').read_bytes())
    closure = native_closure()
    producers = sorted({path.relative_to(CELLAR).parts[:2] for path in closure})
    index = {'format': 1, 'target': 'macos-arm64',
             'scope': 'Homebrew OCR transitive load closure and Python stdlib native-input superset',
             'system_libraries': 'macOS /usr/lib and /System/Library are not redistributed',
             'producers': [], 'unresolved': []}
    for name, version in producers:
        keg = CELLAR / name / version
        folder = destination / (name + '-' + version)
        _safe_directory(folder)
        formula_file = keg / '.brew' / (name + '.rb')
        formula = formula_file.read_text()
        source = _stable_source(formula)
        source['file'] = str(Path(folder.name) / Path(urllib.parse.urlsplit(source['url']).path).name)
        available = _get(source, destination / source['file'], download)
        _write(folder / formula_file.name, formula)
        receipt = _sanitized_receipt(json.loads((keg / 'INSTALL_RECEIPT.json').read_text()))
        _write(folder / 'INSTALL_RECEIPT.json', json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        bottle = _producer_bottle(name, version, receipt)
        if bottle:
            _write(folder / 'BOTTLE_PROVENANCE.json', json.dumps(bottle, indent=2, sort_keys=True) + '\n')
        sbom = keg / 'sbom.spdx.json'
        if sbom.is_file():
            raw = sbom.read_text()
            if '/Users/' in raw or '/home/' in raw:
                raise ValueError('Producer SBOM contains personal paths; review before distribution')
            _write(folder / sbom.name, raw)
        licenses = []
        for item in sorted(keg.iterdir()):
            if item.is_file() and re.match(r'(?i)^(license|copying|notice|copyright)', item.name):
                _write(folder / item.name, item.read_bytes())
                licenses.append(str(Path(folder.name) / item.name))
        if available:
            licenses.extend(_source_notices(destination / source['file'], folder))
        patches, missing_patches = [], []
        for block in re.findall(r'^  patch do\n(.*?)^  end', formula, re.M | re.S):
            url_match = re.search(r'^    url "(https://[^"\n]+)"', block, re.M)
            hash_match = re.search(r'^    sha256 "([a-f0-9]{64})"', block, re.M)
            if url_match:
                if not hash_match:
                    raise ValueError('Producer URL patch is missing its exact digest')
                patch_source = {'url': url_match[1], 'sha256': hash_match[1]}
                patch_file = folder / Path(urllib.parse.urlsplit(url_match[1]).path).name
                if _get(patch_source, patch_file, download):
                    patches.append(dict(patch_source, file=str(Path(folder.name) / patch_file.name),
                                        verification='exact installed formula SHA-256'))
                else:
                    missing_patches.append(patch_file.name)
                    index['unresolved'].append(name + ': exact formula-pinned URL patch not downloaded: ' + patch_file.name)
        for value in re.findall(r'^    file "([^"\n]+)"', formula, re.M):
            if value.startswith('Patches/'):
                facts = _pinned_patch(folder, value, bottle['core_revision'], download) if bottle and bottle['core_revision'] else None
                if facts:
                    patches.append(dict(facts, file=str(Path(folder.name) / Path(value).name)))
                else:
                    missing_patches.append(value)
                    index['unresolved'].append(name + ': exact installed producer patch unavailable: ' + value)
        binaries = {str(p.relative_to(keg)): facts for p, facts in closure.items() if p.is_relative_to(keg)}
        # Public paths stay producer-relative; load names only use public /opt/Homebrew or system paths.
        entry = {'name': name, 'pkg_version': version, 'formula': str(Path(folder.name) / formula_file.name),
                 'formula_sha256': sha256(formula_file), 'receipt': str(Path(folder.name) / 'INSTALL_RECEIPT.json'),
                 'license_expression': _license_expression(formula),
                 'source': dict(source, available=available), 'licenses': licenses,
                 'patches': patches, 'patch_files_missing': missing_patches,
                 'bottle_provenance': bottle, 'native_inputs': binaries}
        index['producers'].append(entry)
        if not available:
            index['unresolved'].append(name + ': matching source archive not downloaded')
    # Installed English traineddata is the exact formula-pinned source, no conversion.
    tess = CELLAR / 'tesseract/5.5.3'
    formula = (tess / '.brew/tesseract.rb').read_text()
    eng = re.search(r'resource "eng" do\s+url "([^"]+)"\s+sha256 "([a-f0-9]{64})"', formula)
    if not eng:
        raise ValueError('Cannot identify pinned English model')
    model = tess / 'share/tessdata/eng.traineddata'
    if sha256(model) != eng[2]:
        raise ValueError('Installed English model differs from its producer source')
    _write(destination / 'eng.traineddata', model.read_bytes())
    index['english_model'] = {'file': 'eng.traineddata', 'url': eng[1], 'sha256': eng[2],
                              'license': 'Apache-2.0; matching Tesseract license included'}
    index['libarchive_features'] = {
        'producer': 'libarchive-3.8.9/libarchive.rb',
        'configure': ['--without-lzo2', '--without-nettle', '--without-xml2', '--without-openssl', '--with-expat'],
        'note': 'Actual macOS producer disables GPL lzo2/nettle; linked closure is recorded. No Windows binary/source mapping reused.'}
    index['binary_license_scope'] = {
        'xz': 'Only liblzma is packaged; source COPYING explicitly licenses liblzma under 0BSD. GPL scripts/tools are not shipped.',
        'zstd': 'libzstd BSD-3-Clause option selected; included MIT code and full source notices retained.',
        'sqlite': 'Public-domain blessing appears in sqlite3.c in the exact included source archive.'}
    index['complete'] = not index['unresolved']
    # Index may advance from planned to downloaded; evidence and archives never overwritten.
    (destination / 'NATIVE_SOURCES.json').write_text(json.dumps(index, indent=2, sort_keys=True) + '\n')
    return destination / 'NATIVE_SOURCES.json'


def _official_initial_source(source, target, download):
    """Keep an honest first-acquisition receipt for an official release URL.

    Unlike Homebrew formula sources, no independently authenticated expected
    SHA-256 is available here. HTTPS plus the exact release URL binds the first
    acquisition; the recorded digest detects later local changes only.
    """
    receipt = target.with_suffix(target.suffix + '.json')
    if target.exists():
        facts = json.loads(receipt.read_text())
        if facts['url'] != source['url'] or facts['sha256'] != sha256(target) or target.is_symlink():
            raise ValueError('Official source changed after acquisition')
        return facts
    if not download:
        return None
    part = target.with_suffix(target.suffix + '.part')
    if part.exists():
        raise FileExistsError('Preserve partial official source evidence')
    request = urllib.request.Request(source['url'], headers={'User-Agent': 'DLMS-native-source-materials/1'})
    with urllib.request.urlopen(request, timeout=40) as response, part.open('xb') as output:
        if not response.geturl().startswith('https://'):
            raise ValueError('Official source redirected away from HTTPS')
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > 1024 * 1024 * 1024:
                raise ValueError('Official source exceeds one GiB bound')
            output.write(block)
    facts = dict(source, sha256=sha256(part),
                 verification='Official HTTPS exact-release URL; initial digest recorded, no independently authenticated expected digest or publisher signature claimed')
    os.rename(part, target)
    _write(receipt, json.dumps(facts, indent=2, sort_keys=True) + '\n')
    return facts


def _ffmpeg_facts(qt_lib):
    result = []
    for component, prefix in [('avutil', 'avutil'), ('avcodec', 'avcodec'),
                              ('avformat', 'avformat'), ('swresample', 'swresample'),
                              ('swscale', 'swscale')]:
        paths = sorted({p.resolve() for p in qt_lib.glob('lib' + component + '.*.dylib')})
        if not paths or len({sha256(p) for p in paths}) != 1:
            raise ValueError('Ambiguous Qt-wheel FFmpeg component: ' + component)
        path = paths[0]
        # These are accepted, locally installed wheel inputs, never a download.
        library = ctypes.CDLL(str(path))
        links = [('@wheel/PySide6/Qt/lib/' + Path(value).name)
                 if value.startswith(str(qt_lib) + '/') else value for value in _links(path)]
        facts = {'file': path.name, 'equivalent_wheel_filenames': [p.name for p in paths],
                 'sha256': sha256(path), 'links': links,
                 'path_normalization': 'Local wheel-prefix load names normalized to @wheel/PySide6/Qt/lib/'}
        for suffix in ('configuration', 'license'):
            function = getattr(library, prefix + '_' + suffix)
            function.argtypes = []
            function.restype = ctypes.c_char_p
            facts[suffix] = function().decode('utf-8')
        function = getattr(library, prefix + '_version')
        function.argtypes = []
        function.restype = ctypes.c_uint
        packed_version = function()
        facts['library_component'] = component
        facts['library_version'] = [packed_version >> 16, (packed_version >> 8) & 255, packed_version & 255]
        flags = shlex.split(facts['configuration'])
        if any(value in flags for value in ('--enable-gpl', '--enable-nonfree')):
            raise ValueError('Unexpected FFmpeg GPL/nonfree producer configuration')
        if 'LGPL version 2.1 or later' not in facts['license']:
            raise ValueError('Unexpected FFmpeg producer library license')
        if component == 'avutil':
            function = library.av_version_info
            function.argtypes = []
            function.restype = ctypes.c_char_p
            facts['release_version'] = function().decode('utf-8')
            if facts['release_version'] != '7.1.5':
                raise ValueError('Unexpected FFmpeg release version')
        result.append(facts)
    return result


def prepare_wheel_native(destination=None, *, download=False):
    """Bind standalone Mac-wheel FFmpeg material and export wheel-native facts.

    Other Qt/PySide/Pillow/PDFium source archives belong to the separately
    validated shared wheel-source companion; this index does not replace it.
    """
    destination = (Path.home() / '.cache/dlms-desktop-macos-preview/sources/wheel-native'
                   if destination is None else Path(destination))
    _safe_directory(destination)
    build_inputs = Path.home() / '.cache/dlms-desktop-macos-preview/BUILD_INPUTS.json'
    interpreter = Path(json.loads(build_inputs.read_text())['interpreter'])
    # Keep the environment directory, not a venv interpreter symlink target.
    environment = interpreter.parent.parent
    site = environment / 'lib/python3.14/site-packages'
    qt_lib = site / 'PySide6/Qt/lib'
    ffmpeg = _ffmpeg_facts(qt_lib)
    source = {'name': 'FFmpeg', 'version': '7.1.5', 'file': 'ffmpeg-7.1.5.tar.xz',
              'url': 'https://ffmpeg.org/releases/ffmpeg-7.1.5.tar.xz',
              'license': 'LGPL-2.1-or-later option; actual library configuration and license strings recorded'}
    acquired = _official_initial_source(source, destination / source['file'], download)
    index = {'format': 1, 'target': 'macos-arm64',
             'scope': 'Standalone Qt-wheel FFmpeg matching source plus wheel-native metadata; remaining wheel sources are in the shared companion',
             'ffmpeg_native_inputs': ffmpeg, 'sources': [acquired or dict(source, available=False)],
             'unresolved': [] if acquired else ['Matching official FFmpeg 7.1.5 source archive not downloaded']}
    if acquired:
        index['source_notices'] = _source_notices(destination / source['file'], destination)
        with tarfile.open(destination / source['file']) as archive:
            member = archive.getmember('ffmpeg-7.1.5/RELEASE')
            with archive.extractfile(member) as stream:
                release = stream.read(128).decode().strip()
            if release != '7.1.5':
                raise ValueError('Official FFmpeg archive release does not match library')
            matches = []
            for facts in ffmpeg:
                component = facts['library_component']
                prefix = 'LIB' + component.upper() + '_VERSION_'
                headers = ''
                for name in ('version.h', 'version_major.h'):
                    with archive.extractfile('ffmpeg-7.1.5/lib' + component + '/' + name) as stream:
                        headers += stream.read().decode() + '\n'
                values = []
                for part in ('MAJOR', 'MINOR', 'MICRO'):
                    value = re.search(r'^#define\s+' + prefix + part + r'\s+(\d+)\b', headers, re.M)
                    if not value:
                        raise ValueError('FFmpeg source component version macro missing')
                    values.append(int(value[1]))
                match = values == facts['library_version']
                matches.append({'component': component, 'source_version': values,
                                'binary_reported_version': facts['library_version'], 'matches': match})
                if not match:
                    index['unresolved'].append('FFmpeg ' + component + ': binary version differs from official source; producer patch correspondence required')
            index['source_header_version_comparison'] = matches
        text = ('FFmpeg standalone libraries in the macOS PySide6 wheel\n'
                '=====================================================\n\n'
                'Actual library supplier release: 7.1.5 (av_version_info).\n'
                'License reported by all five supplied libraries: LGPL version 2.1 or later.\n'
                'The LGPL-2.1-or-later option is selected. Full source licenses accompany this record.\n'
                'No --enable-gpl or --enable-nonfree producer configuration is present.\n\n'
                'The Qt source attribution entry reporting FFmpeg 7.1.3 is stale for these\n'
                'standalone macOS wheel binaries. This record supplies the actual version,\n'
                'configuration, hashes and component/header comparison. The Qt source\n'
                'companion retains its producer build/replacement scripts unchanged.\n'
                'An upstream source version/header match is not a byte-identical rebuild claim.\n\n'
                'Official matching upstream source: ' + source['url'] + '\n'
                'Source archive SHA-256: ' + acquired['sha256'] + '\n\n')
        for facts in ffmpeg:
            text += (facts['library_component'] + ' ' + '.'.join(map(str, facts['library_version']))
                     + '\nConfiguration: ' + facts['configuration'] + '\n\n')
        _write(destination / 'MACOS_FFMPEG_ATTRIBUTION.txt', text)
        index['macos_attribution'] = {'file': 'MACOS_FFMPEG_ATTRIBUTION.txt',
                                     'sha256': sha256(destination / 'MACOS_FFMPEG_ATTRIBUTION.txt')}
    metadata = {
        'pillow_sbom': site / 'pillow-12.3.0.dist-info/sboms/pillow-12.3.0.cdx.json',
        'pdfium_version': site / 'pypdfium2_raw/version.json'}
    index['wheel_metadata'] = {}
    for name, path in metadata.items():
        raw = path.read_text()
        if '/Users/' in raw or '/home/' in raw:
            raise ValueError('Wheel-native metadata contains personal paths')
        filename = name + '.json'
        _write(destination / filename, raw)
        index['wheel_metadata'][name] = {'file': filename, 'sha256': sha256(path)}
    index['wheel_metadata']['pdfium_version']['value'] = json.loads(metadata['pdfium_version'].read_text())
    licenses = site / 'pypdfium2-5.14.0.dist-info/licenses'
    index['pdfium_build_license_bindings'] = [
        {'wheel_path': str(path.relative_to(site)), 'sha256': sha256(path)}
        for path in sorted((licenses / 'data/darwin_arm64/BUILD_LICENSES').glob('*')) if path.is_file()]
    if not index['pdfium_build_license_bindings']:
        raise ValueError('Mac PDFium exact wheel build-license binding is missing')
    pdfium = site / 'pypdfium2_raw/libpdfium.dylib'
    index['pdfium_native_input'] = {'wheel_path': 'pypdfium2_raw/libpdfium.dylib',
                                    'sha256': sha256(pdfium), 'links': _links(pdfium)}
    pillow = site / 'PIL'
    index['pillow_native_inputs'] = {
        str(path.relative_to(site)): {'sha256': sha256(path), 'links': _links(path)}
        for path in sorted([*(pillow / '.dylibs').glob('*.dylib'), *pillow.glob('*.so')])}
    index['complete'] = not index['unresolved']
    path = destination / 'WHEEL_NATIVE_SOURCES.json'
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + '\n')
    return path
