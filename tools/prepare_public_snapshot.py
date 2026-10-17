"""Prepare a local review snapshot/patch; never pushes or invokes a remote."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ADDITIONS = ('desktop/', 'desktop_assets/', 'windows_webview2/', 'package_fedora/',
             'package_linux/', 'package_appimage/', 'package_windows/',
             'package_windows_webview2/', 'package_macos/', 'fixtures/', 'tests/')
EXCLUDE = ('tests/closure/', 'tests/windows/browser_environment_probe.py',
           'tests/windows/test_browser_environment_probe.py',
           'tests/windows/test_webview2_experiment.py',
           'package_macos/personal_launcher.m')
DOCUMENTS = ('docs/choose-your-dlms.md', 'docs/desktop-hosts.md',
             'docs/desktop-validation.md', 'docs/publication-prerequisites.md',
             'docs/desktop-license.md', 'desktop_assets/ICON_PROVENANCE.md',
             'desktop_assets/dlms-badge.svg',
             'tools/run_consolidation_checks.py', 'tools/prepare_public_snapshot.py',
             'tools/validate_publication_patch.py',
             'tools/macos_download_dependencies.py', 'tools/macos_prepare_environment.py',
             'tools/macos_qualify_candidate.py', 'tools/macos_walkthrough_server.py',
             '.github/workflows/desktop-contracts.yml')
# Only these deliberate new publication inputs may be untracked. Never let a
# new ignored/local file become public merely because it sits under tests/.
NEW_INPUTS = ('docs/desktop-license.md', 'desktop_assets/ICON_PROVENANCE.md',
              'desktop_assets/dlms-badge.svg', 'tests/test_public_source_snapshot.py')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True, help='Verified local tree of pinned public commit')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    baseline, output = args.baseline.resolve(), args.output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('Retain earlier snapshots; use a new output directory')
    if output.is_relative_to(baseline) or baseline.is_relative_to(output):
        raise ValueError('Snapshot and baseline must be separate')
    # The caller supplies the read-only acquisition's exact tree, recorded in
    # baseline.json. Do not trust a manifest path as permission to read secrets.
    base_files = sorted(x for x in baseline.rglob('*') if x.is_file())
    if any(x.is_symlink() for x in baseline.rglob('*')):
        raise ValueError('Pinned review tree must contain regular files/directories')
    existing = {x.relative_to(baseline).as_posix() for x in base_files}
    git = ['git', '--git-dir=.dlms-git', '--work-tree=.'] if (ROOT / '.dlms-git').is_dir() else ['git']
    names = subprocess.check_output(git + ['ls-files', '-z'], cwd=ROOT).decode().split('\0')
    names.extend(name for name in NEW_INPUTS if (ROOT / name).is_file())
    allowed = set(existing)
    for name in names:
        if name and (name.startswith(ADDITIONS) or name in DOCUMENTS) and not name.startswith(EXCLUDE):
            if (ROOT / name).is_file():
                allowed.add(name)
    output.mkdir(mode=0o700, parents=True)
    tree = output / 'tree'
    tree.mkdir()
    rows, findings = [], []
    for name in sorted(allowed):
        current, original = ROOT / name, baseline / name
        # Private accumulated instructions/history are never publication input.
        if name == 'AGENTS.md':
            source = original
        elif name == 'windows_webview2/README.md':
            source = ROOT / 'docs/desktop-hosts.md'
        else:
            source = current if current.is_file() else original
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'Unsafe publication input: {name}')
        boundary = baseline if source.is_relative_to(baseline) else ROOT
        if not source.resolve().is_relative_to(boundary):
            raise ValueError(f'Publication input escapes its selected tree: {name}')
        for component in (source, *source.parents):
            if component == boundary:
                break
            if component.is_symlink():
                raise ValueError(f'Symlink in publication input path: {name}')
        data = source.read_bytes()
        transformation = None
        if name == 'windows_webview2/README.md':
            data = data.replace(b'(desktop-validation.md)', b'(../docs/desktop-validation.md)')
            data = data.replace(b'(publication-prerequisites.md)', b'(../docs/publication-prerequisites.md)')
            transformation = 'sanitized host guide with directory-relative documentation links'
        if name == 'tests/server_mode/test_boundary.py':
            # Synthetic endpoint fixture only. Never copy an owner's actual
            # example address into the new public change.
            updated = re.sub(rb'192\.168\.1\.\d{1,3}', b'192.168.50.10', data)
            if updated != data:
                transformation = 'fictional RFC1918 endpoint replaces private operational example'
                data = updated
        if name not in existing or not original.is_file() or data != original.read_bytes():
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                findings.append({'path': name, 'kind': 'binary/asset-rights-review'})
            else:
                patterns = {
                    'personal-path': r'/(?:home|Users)/(?!Shared(?:/|\b))[A-Za-z][^/\s\"\']*|[Cc]:[/\\]+[Uu]sers[/\\]+[A-Za-z][^/\\\s\"\']*',
                    'private-operational-origin': r'192\.168\.1\.\d{1,3}',
                    'private-key': r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
                    'github-token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b',
                    'private-report-reference': r'reports/(?:session-browser|fedora-|blocka|blockb|gate-a|ordinary-file-selection|macos-desktop|macos-consolidation)',
                }
                for kind, pattern in patterns.items():
                    if re.search(pattern, text):
                        findings.append({'path': name, 'kind': kind})
        destination = tree / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
        rows.append({'path': name, 'sha256': sha(data), 'mode': oct(destination.stat().st_mode & 0o777),
                     'input_sha256': sha(source.read_bytes()), 'transformation': transformation,
                     'source': 'pinned public instructions' if name == 'AGENTS.md' else
                               'sanitized host guide' if name == 'windows_webview2/README.md' else
                               'candidate' if source == current else 'retained public baseline'})
    (output / 'ALLOWLIST.json').write_text(json.dumps(rows, indent=2) + '\n')
    (output / 'REVIEW.json').write_text(json.dumps({'automated_findings': findings,
        'limits': 'Pattern scan is not a secret audit or legal clearance. Manual review and publication approval required.'}, indent=2) + '\n')
    # Compare repository-relative names, not private absolute working paths.
    shutil.copytree(baseline, output / 'public-baseline')
    result = subprocess.run(['git', 'diff', '--no-index', '--binary', '--no-renames',
                             'public-baseline', 'tree'], cwd=output, capture_output=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode())
    lines = []
    for line in result.stdout.splitlines(keepends=True):
        if line.startswith((b'diff --git ', b'--- ', b'+++ ', b'Binary files ')):
            for prefix in (b'a/public-baseline/', b'b/public-baseline/', b'a/tree/', b'b/tree/'):
                line = line.replace(prefix, prefix[:2])
        lines.append(line)
    patch = b''.join(lines)
    (output / 'PROPOSED.patch').write_bytes(patch)
    applied = output / 'apply-verification'
    shutil.copytree(baseline, applied)
    for flags in (['--check'], []):
        subprocess.run(['git', 'apply', *flags, str((output / 'PROPOSED.patch').resolve())],
                       cwd=applied, check=True, capture_output=True)
    if {p.relative_to(applied).as_posix() for p in applied.rglob('*') if p.is_file()} != allowed:
        raise ValueError('Patch changed the allowed file set')
    for row in rows:
        path = applied / row['path']
        if sha(path.read_bytes()) != row['sha256'] or oct(path.stat().st_mode & 0o777) != row['mode']:
            raise ValueError(f'Patch does not reproduce the exact reviewed file: {row["path"]}')
    (output / 'APPLY_VERIFIED.json').write_text(json.dumps({'files_verified': len(rows),
        'patch_sha256': sha(patch), 'apply_check': True, 'exact_applied_bytes_and_modes': True}, indent=2) + '\n')
    print(json.dumps({'files': len(rows), 'findings': len(findings), 'patch_sha256': sha(patch)}))


if __name__ == '__main__':
    main()
