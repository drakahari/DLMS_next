"""Prepare, but never publish/install, the byte-bound Mac preview delivery.

Run only after reviewing the final docs and opening evidence. No build, tests,
network, Git mutation or installed/profile access occurs. New source/notice
archives have normalized owner/time metadata; the two shared archives and the
qualified DMG remain byte-identical. Existing Downloads folders are preserved.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from package_macos.build import app_inventory, runtime_inventory
from package_macos.preview_materials import BASE, SHARED, deliver_companions, digest

FOLDER = 'DLMS-Desktop-macOS-Preview-20261017'
DMG = 'DLMS-Desktop-3.3.0-macos-arm64-preview1.dmg'
NEW_ARCHIVES = {
    'DLMS-Desktop-3.3.0-macos-preview1-source-native.tar.zst': 'native-sources',
    'DLMS-Desktop-3.3.0-macos-preview1-source-wheel-native.tar.zst': 'wheel-native-sources',
    'DLMS-Desktop-3.3.0-macos-preview1-notices.tar.zst': 'notices',
    'DLMS-Desktop-3.3.0-macos-preview1-source-application.tar.zst': 'DLMS-source',
}
DOCS = ('REDISTRIBUTION.md', 'BUILD_AND_REPLACEMENT.md', 'RELEASE_PROPOSAL.md',
        'OPENING_AND_VALIDATION.md')
FORBIDDEN_PARTS = {'.git', '.gate1', '.venv', '__pycache__', '.pytest_cache',
                   'profiles', 'backups', 'dist', 'build', '.cache'}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT)


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
    Path(path).chmod(0o644)


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def safe_directory(path):
    path = Path(path)
    require(path.is_absolute() and path == Path(os.path.normpath(path)), 'Noncanonical directory')
    for component in (path, *path.parents):
        require(not component.is_symlink(), 'Directory alias refused: ' + str(component))
    st = path.stat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o022,
            'Unsafe task directory: ' + str(path))
    return path


def safe_member(name, prefix):
    path = PurePosixPath(name)
    require(name and not path.is_absolute() and '..' not in path.parts and '\\' not in name
            and name == path.as_posix() and path.parts[0] == prefix,
            'Unsafe or unexpected archive member: ' + name)
    return path


class HashReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, count=-1):
        block = self.stream.read(count)
        self.digest.update(block)
        self.count += len(block)
        return block


def normalize_archive(path, prefix):
    """Preserve every regular member byte/mode; emit no owner/time/PAX data."""
    from compression import zstd

    normalized = path.with_name(path.name + '.normalized')
    members = {}
    with zstd.open(path, 'rb') as decoded:
        with tarfile.open(fileobj=decoded, mode='r|') as original:
            with normalized.open('xb') as target:
                with zstd.open(target, 'wb', level=9) as encoded:
                    # GNU long-name records avoid reintroducing PAX headers for
                    # long upstream filenames after explicitly clearing them.
                    with tarfile.open(fileobj=encoded, mode='w|', format=tarfile.GNU_FORMAT) as archive:
                        for member in original:
                            safe_member(member.name, prefix)
                            require(member.isfile() and member.name not in members,
                                    'Nonregular or duplicate generated archive member: ' + member.name)
                            clean = tarfile.TarInfo(member.name)
                            clean.size = member.size
                            clean.mode = member.mode
                            clean.uid = clean.gid = 0
                            clean.uname = clean.gname = ''
                            clean.mtime = 0
                            clean.pax_headers = {}
                            with original.extractfile(member) as source:
                                reader = HashReader(source)
                                archive.addfile(clean, reader)
                                require(reader.count == member.size, 'Short archive member: ' + member.name)
                                members[member.name] = {'sha256': reader.digest.hexdigest(),
                                                        'bytes': reader.count, 'mode': member.mode}
                target.flush()
                os.fsync(target.fileno())
    require(members, 'Empty generated companion archive')
    # Read the new compressed archive independently: do not infer success from
    # the original-member hashing or trust write-side metadata normalization.
    verified = {}
    with zstd.open(normalized, 'rb') as decoded:
        with tarfile.open(fileobj=decoded, mode='r|') as archive:
            for member in archive:
                safe_member(member.name, prefix)
                require(member.isfile() and member.name not in verified,
                        'Nonregular or duplicate normalized member: ' + member.name)
                require(member.uid == member.gid == member.mtime == 0
                        and member.uname == member.gname == '' and member.pax_headers == {},
                        'Normalized archive retained owner/time/PAX metadata: ' + member.name)
                with archive.extractfile(member) as source:
                    actual = hashlib.file_digest(source, 'sha256').hexdigest()
                verified[member.name] = {'sha256': actual, 'bytes': member.size, 'mode': member.mode}
    require(verified == members, 'Normalized archive member bytes/modes differ: ' + path.name)
    # Only this newly generated task-stage file is replaced; shared archives and
    # the original source directories are never modified.
    os.replace(normalized, path)
    return members


def audit_source_selection():
    names = set(filter(None, (git('ls-files', '-z') +
                git('ls-files', '--others', '--exclude-standard', '-z')).decode().split('\0')))
    require(names, 'No source selected')
    for name in names:
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in name,
                'Unsafe source path')
        require(not FORBIDDEN_PARTS.intersection(path.parts)
                and not path.name.startswith('.env') and path.name != '.DS_Store'
                and path.suffix.lower() not in {'.dmg', '.exe', '.dll', '.dylib', '.so', '.key', '.pem', '.p12', '.pfx'},
                'Unexpected private/build source input: ' + name)
        source = ROOT / name
        require(source.is_file() and not source.is_symlink(), 'Nonregular source input: ' + name)
    return sorted(names)


def public_value(value, home):
    """Remove host identity and task-temp paths from allowlisted public data."""
    if isinstance(value, dict):
        return {str(key): public_value(item, home) for key, item in value.items()}
    if isinstance(value, list):
        return [public_value(item, home) for item in value]
    if isinstance(value, str):
        value = value.replace(str(home), '$HOME')
        value = re.sub(r'/(?:private/)?var/folders/[^\s"\n]*?/AppTranslocation/[^/\s]+/d/',
                       '<task-AppTranslocation>/', value)
        return value
    return value


def validation_record(stage, home, image_sha):
    package = json.loads((stage / 'PACKAGE_CHECK.json').read_text())
    require(package.get('status') == 'pass', 'Focused package check must have passed')
    opening_path = next((stage / name for name in
                         ('OPENING_ACCEPTANCE.json', 'OPENING_FINAL.json', 'OPENING_CHECK.json')
                         if (stage / name).is_file()), stage / 'OPENING_ACCEPTANCE.json')
    require(opening_path.is_file(), 'Opening evidence is missing')
    opening = json.loads(opening_path.read_text())
    require(opening.get('status') == 'pass', 'Final normal downloaded opening acceptance must pass before delivery')
    require(opening.get('dmg_sha256') == image_sha, 'Opening acceptance refers to a different DMG')
    fields = ('status', 'scope', 'dmg_sha256', 'helper_sha256', 'global_security_changes',
              'manual_quarantine_removal', 'installed_apps_changed', 'production_access',
              'existing_profiles_changed', 'normal_finder_launch', 'app_left_closed',
              'downloaded_payload_verified', 'quarantined_normal_opening', 'error',
              'normal_cmd_q', 'normal_reopen', 'reopen_passed', 'cmd_q_passed', 'assessment_before',
              'actual_cmd_q_and_finder_reopen', 'default_profile_identity_reused',
              'task_app_and_helpers_stopped', 'writer_and_instance_locks_released',
              'quarantine_retained', 'signature_and_payload_verified',
              'owner_authenticated_per_app_exception', 'local_dashboard_ready',
              'app_translocation', 'final_metadata_api_fix', 'broad_tests_repeated')
    selected = {key: opening[key] for key in fields if key in opening}
    selected['steps'] = [{key: step[key] for key in
                          ('action', 'status', 'input', 'button', 'reason', 'bundle_id', 'app_translocation')
                          if key in step} for step in opening.get('steps', [])]
    record = {
        'format': 1,
        'package_check': {key: value for key, value in package.items() if key != 'fixtures'},
        'opening_evidence_file': opening_path.name,
        'opening_check': selected,
        'source_of_historical_acceptance': 'Accepted private Mac Local, synthetic Server and installed-owner evidence reused with original scope; no repeated owner walkthrough.',
        'fixtures': 'Synthetic handoff fixtures in ordinary Documents; no profile or owner data exported.',
        'release_status': 'Prepared proposal; no installation replacement, merge or publication authorized/performed.',
        'opening_qualification_complete': opening.get('status') == 'pass',
    }
    return public_value(record, home)


def exclusive_copy(source, target):
    require(source.is_file() and not source.is_symlink(), 'Nonregular delivery input')
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    target.chmod(0o644)
    require(digest(source) == digest(target), 'Delivery copy changed: ' + source.name)


def main():
    require(len(sys.argv) == 1, 'No arguments accepted; fixed task delivery only')
    require(sys.platform == 'darwin' and os.getuid() == os.geteuid() != 0, 'Native normal user only')
    home = Path.home()
    cache = safe_directory(home / '.cache/dlms-desktop-macos-preview')
    inputs = json.loads((cache / 'BUILD_INPUTS.json').read_text())
    require(Path(sys.executable).absolute() == Path(inputs['interpreter']).absolute(),
            'Use the accepted pinned build interpreter')
    require(git('rev-parse', 'HEAD').decode().strip() == BASE, 'Unexpected source HEAD; no commit is created here')
    require(git('branch', '--show-current').decode().strip() == 'feature/macos-desktop-public-preview',
            'Unexpected public preview branch')
    pointer = json.loads((ROOT / '.gate1/macos/CANDIDATE.json').read_text())
    stage = safe_directory(Path(pointer['stage']))
    require(stage.parent == cache and stage.name.startswith('build-'), 'Unexpected build stage')
    app = stage / 'dist/DLMS Desktop.app'
    require(pointer['app'] == str(app) and not app.is_symlink(), 'Unexpected built app')
    provenance = json.loads((stage / 'PROVENANCE.json').read_text())
    require(provenance['baseline'] == BASE and provenance['head'] == BASE, 'Wrong public baseline')
    require(runtime_inventory() == provenance['runtime_files'], 'Runtime source changed since build; no implicit rebuild')
    require(canonical_hash(provenance['runtime_files']) == pointer['snapshot_sha256'] == provenance['snapshot_sha256'],
            'Runtime source snapshot mismatch')
    require(canonical_hash(app_inventory(app)) == pointer['app_manifest_sha256'] == provenance['app_manifest_sha256'],
            'Built app payload changed')
    image = stage / DMG
    require(image.is_file() and not image.is_symlink(), 'Prepared DMG missing')
    image_sha = digest(image)
    expected, name = (stage / 'SHA256SUMS').read_text().strip().split(maxsplit=1)
    require(expected == image_sha and name.removeprefix('*') == DMG, 'Prepared DMG checksum changed')
    validation = validation_record(stage, home, image_sha)
    for name in DOCS:
        require((ROOT / 'docs/macos-preview' / name).is_file(), 'Final release document missing: ' + name)
    selected = audit_source_selection()
    destination = home / 'Downloads' / FOLDER
    require(not destination.exists() and not destination.is_symlink(), 'Preserve existing Downloads delivery folder')
    safe_directory(destination.parent)
    work = Path(tempfile.mkdtemp(prefix='delivery-', dir=cache))
    delivery = work / 'recipient'
    deliver_companions(stage, cache, delivery)
    normalized = {name: normalize_archive(delivery / name, prefix) for name, prefix in NEW_ARCHIVES.items()}
    source_manifest = json.loads((delivery / 'APPLICATION_SOURCE_MANIFEST.json').read_text())
    require(set(source_manifest) == set(selected), 'Source selection changed during export')
    application = normalized['DLMS-Desktop-3.3.0-macos-preview1-source-application.tar.zst']
    require({str(PurePosixPath(name).relative_to('DLMS-source')): info['sha256']
             for name, info in application.items()} == source_manifest, 'Application source archive mismatch')
    require({name: source_manifest[name] for name in provenance['runtime_files']} == provenance['runtime_files'],
            'Delivered source does not match built runtime')
    for name, expected in SHARED.items():
        require(digest(delivery / name) == expected, 'Unmodified shared companion changed')
    exclusive_copy(image, delivery / DMG)
    exclusive_copy(stage / 'APP_MANIFEST.json', delivery / 'APP_MANIFEST.json')
    exclusive_copy(stage / 'EXCLUSIONS.json', delivery / 'QT_EXCLUSIONS.json')
    for name in DOCS:
        exclusive_copy(ROOT / 'docs/macos-preview' / name, delivery / name)
    build_fields = ('baseline', 'head', 'snapshot_sha256', 'runtime_files', 'macho',
                    'app_manifest_sha256', 'build_info', 'python', 'macos', 'dependencies', 'signing')
    build = {key: provenance[key] for key in build_fields}
    build.update(format=1, source_state='Uncommitted public preview snapshot; no new source commit created.',
                 dmg_file=DMG, dmg_sha256=image_sha,
                 native_source_index_sha256=digest(stage / 'notices/native/NATIVE_SOURCES.json'),
                 wheel_native_source_index_sha256=digest(stage / 'notices/wheel-native/WHEEL_NATIVE_SOURCES.json'))
    save(delivery / 'BUILD_PROVENANCE.json', public_value(build, home))
    save(delivery / 'VALIDATION.json', validation)
    save(delivery / 'RUNTIME_SOURCE_MATCH.json', {
        'format': 1, 'application_base': BASE,
        'source_state': 'Exact uncommitted public preview snapshot; not an invented release commit.',
        'runtime_snapshot_sha256': provenance['snapshot_sha256'],
        'app_manifest_sha256': provenance['app_manifest_sha256'],
        'application_source_manifest_sha256': digest(delivery / 'APPLICATION_SOURCE_MANIFEST.json'),
        'runtime_files': provenance['runtime_files'], 'match': True,
    })
    companions = {path.name: {'sha256': digest(path), 'bytes': path.stat().st_size}
                  for path in sorted(delivery.iterdir()) if path.name.endswith(('.tar', '.tar.zst'))}
    save(delivery / 'SOURCE_INDEX.json', {
        'format': 1, 'application_base': BASE, 'branch': 'feature/macos-desktop-public-preview',
        'source_state': 'Uncommitted exact source snapshot. Owner approval precedes any future commit/merge/publication.',
        'application_source_snapshot_sha256': canonical_hash(source_manifest),
        'runtime_snapshot_sha256': provenance['snapshot_sha256'],
        'application_source_manifest': 'APPLICATION_SOURCE_MANIFEST.json',
        'runtime_match': 'RUNTIME_SOURCE_MATCH.json', 'archives': companions,
        'normalized_new_archive_metadata': {'uid': 0, 'gid': 0, 'uname': '', 'gname': '', 'mtime': 0, 'pax_headers': {}},
        'shared_archives': 'Two verified upstream companions are copied byte for byte; their original metadata is preserved.',
    })
    all_files = sorted(delivery.iterdir())
    require(all(path.is_file() and not path.is_symlink() for path in all_files), 'Unexpected delivery directory or alias')
    (delivery / 'SHA256SUMS').write_text(''.join(digest(path) + '  ' + path.name + '\n' for path in all_files))
    (delivery / 'SHA256SUMS').chmod(0o644)
    destination.mkdir(mode=0o700, exist_ok=False)
    for path in sorted(delivery.iterdir()):
        exclusive_copy(path, destination / path.name)
    require(digest(destination / DMG) == image_sha, 'Final DMG changed')
    save(work / 'DELIVERY_RECEIPT.json', {'status': 'prepared-not-published', 'destination': str(destination),
                                       'dmg_sha256': image_sha, 'source_base': BASE,
                                       'source_snapshot_sha256': canonical_hash(source_manifest),
                                       'runtime_snapshot_sha256': provenance['snapshot_sha256']})
    print(json.dumps({'status': 'prepared-not-published', 'directory': str(destination),
                      'dmg_sha256': image_sha, 'source_base': BASE,
                      'source_snapshot_sha256': canonical_hash(source_manifest),
                      'receipt': str(work / 'DELIVERY_RECEIPT.json')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
