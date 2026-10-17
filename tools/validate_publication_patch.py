"""Validate the frozen publication diff as a patch, not as ordinary source text.

Local-only validation. The caller supplies an isolated repository containing the
pinned public commit. No fetching, source execution or original checkout writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PINNED_PUBLIC = '2630ea8ebbf3aebe9e82142da905678dda96050a'


def git(repository: Path, *args: str) -> bytes:
    # Inherited private-checkout/index/replace settings must never redirect an
    # apply into the Desktop checkout or change what the pinned objects mean.
    environment = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_NO_REPLACE_OBJECTS='1', GIT_OPTIONAL_LOCKS='0',
                       GIT_TERMINAL_PROMPT='0')
    command = ['git', '--no-replace-objects', '-c', 'core.autocrlf=false',
               '-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab',
               '-C', str(repository), *args]
    result = subprocess.run(command, env=environment, capture_output=True)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout).decode('utf-8', errors='replace') or 'Git validation failed')
    return result.stdout


def relative_name(value: str) -> str:
    if (not isinstance(value, str) or not value or '\\' in value or '\x00' in value
            or PurePosixPath(value).is_absolute()
            or any(p in ('', '.', '..', '.git') for p in value.split('/'))
            or any(p.lower() == '.git' for p in value.split('/'))):
        raise ValueError('Unsafe publication path')
    return value


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_object(kind: str, data: bytes) -> str:
    return hashlib.sha1(kind.encode() + b' ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def tree_hash(files: dict[str, tuple[str, str]]) -> str:
    nodes = {}
    for path, value in files.items():
        parts = path.split('/')
        node = nodes
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    def encode(node):
        entries = []
        for name, value in sorted(node.items(), key=lambda pair: pair[0].encode() + (b'/' if isinstance(pair[1], dict) else b'')):
            mode, oid = ('40000', encode(value)) if isinstance(value, dict) else value
            entries.append(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(oid))
        return git_object('tree', b''.join(entries))
    return encode(nodes)


def validate(repository: Path, report: Path, work: Path, *, expected_commit: str = PINNED_PUBLIC) -> dict:
    if work.exists() or work.is_symlink():
        raise ValueError('Use a fresh work directory; preserve earlier evidence')
    metadata = json.loads((report / 'BASELINES.json').read_text())
    if metadata['public_main'] != expected_commit:
        raise ValueError('Publication baseline differs from the pinned commit')
    raw_commit = git(repository, 'cat-file', 'commit', expected_commit)
    if git_object('commit', raw_commit) != expected_commit:
        raise ValueError('Public commit object does not match its pinned identity')
    expected_tree = raw_commit.splitlines()[0].decode().removeprefix('tree ')
    patch = report / 'PROPOSED.patch'
    if patch.is_symlink() or not patch.is_file():
        raise ValueError('Publication patch must be a regular file')
    patch_sha = digest(patch.read_bytes())
    verification = json.loads((report / 'APPLY_VERIFIED.json').read_text())
    if verification['patch_sha256'] != patch_sha:
        raise ValueError('Publication patch checksum differs from reviewed evidence')
    manifest = json.loads((report / 'ALLOWLIST.json').read_text())
    wanted = {}
    for row in manifest:
        name = relative_name(row['path'])
        if name in wanted or row['mode'] not in ('0o644', '0o755'):
            raise ValueError('Duplicate publication path or unsupported file mode')
        if len(row['sha256']) != 64 or any(c not in '0123456789abcdef' for c in row['sha256']):
            raise ValueError('Invalid publication file checksum')
        wanted[name] = row
    if verification['files_verified'] != len(wanted):
        raise ValueError('Publication file count differs from reviewed evidence')
    work.mkdir(mode=0o700, parents=True)
    files = {}
    for record in git(repository, 'ls-tree', '-rz', expected_commit).split(b'\0'):
        if not record:
            continue
        info, raw_name = record.split(b'\t', 1)
        mode, kind, oid = info.decode().split()
        name = relative_name(raw_name.decode())
        if kind != 'blob' or mode not in ('100644', '100755') or name in files:
            raise ValueError('Unsupported public baseline entry')
        data = git(repository, 'cat-file', 'blob', oid)
        if git_object('blob', data) != oid:
            raise ValueError('Public baseline blob identity mismatch')
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if mode == '100755' else 0o644)
        files[name] = (mode, oid)
    if tree_hash(files) != expected_tree:
        raise ValueError('Extracted baseline does not match the pinned Git tree')
    # Initialize only the fresh verification tree; never apply in the source or
    # baseline repository. Git's path checks remain enabled (no unsafe-paths).
    git(work, 'init', '--quiet')
    git(work, 'add', '--force', '--all')
    if git(work, 'write-tree').decode().strip() != expected_tree:
        raise ValueError('Verification index differs from the exact public baseline')
    for flags in (['--check'], []):
        git(work, 'apply', *flags, '--whitespace=error-all', str(patch.resolve()))
    actual = {}
    for path in work.rglob('*'):
        if path.relative_to(work).parts[0] == '.git':
            continue
        if path.is_symlink():
            raise ValueError('Applied publication tree contains a symlink')
        if path.is_file():
            actual[path.relative_to(work).as_posix()] = path
        elif not path.is_dir():
            raise ValueError('Applied publication tree contains a special file')
    if actual.keys() != wanted.keys():
        raise ValueError('Applied publication tree differs from the complete allowlist')
    for name, path in actual.items():
        row = wanted[name]
        if digest(path.read_bytes()) != row['sha256'] or oct(stat.S_IMODE(path.stat().st_mode)) != row['mode']:
            raise ValueError('Publication bytes or file mode differ: ' + name)
    # Check the actual reconstructed source diff too, independently of whether
    # a malicious/broken patch encoded a text file as a binary delta.
    git(work, 'add', '--force', '--all')
    git(work, 'diff', '--cached', '--check', expected_tree)
    return {'baseline_commit': expected_commit, 'baseline_tree': expected_tree,
            'patch_sha256': patch_sha, 'files_verified': len(actual),
            'strict_added_source_whitespace': True, 'exact_bytes_and_modes': True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-repository', type=Path, required=True)
    parser.add_argument('--report', type=Path, default=ROOT / 'reports/private-consolidation')
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.baseline_repository.resolve(), args.report.resolve(), args.work.absolute())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
