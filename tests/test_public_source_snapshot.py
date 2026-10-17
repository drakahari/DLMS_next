"""Source export consent/containment, without a remote or private Git history."""
import json
from pathlib import Path
import subprocess

import pytest

from tools import prepare_public_snapshot as exporter


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    return path


def candidate(tmp_path, monkeypatch):
    root = tmp_path / 'private'
    root.mkdir()
    baseline = tmp_path / 'public'
    baseline.mkdir()
    for name, data in [('LICENSE', 'MIT license fixture\n'),
                       ('AGENTS.md', 'Public instructions\n')]:
        put(baseline, name, data)
        put(root, name, data)
    put(root, 'AGENTS.md', 'PRIVATE historical instructions\n')
    put(root, 'desktop/adapter.py', 'answer = 42\n')
    put(root, 'package_macos/build.py', '"""Generic builder."""\n')
    put(root, 'package_macos/personal_launcher.m', '// private personal path\n')
    put(root, 'reports/private-note.md', 'PRIVATE operational evidence\n')
    subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    # Deliberately untracked under an otherwise eligible source directory.
    put(root, 'desktop/local-secret.txt', 'LOCAL_UNTRACKED_CONTENT\n')
    put(root, 'docs/desktop-license.md', 'New explicitly selected grant\n')
    monkeypatch.setattr(exporter, 'ROOT', root)
    output = tmp_path / 'snapshot'
    monkeypatch.setattr('sys.argv', ['prepare', '--baseline', str(baseline),
                                   '--output', str(output)])
    return root, baseline, output


def test_export_keeps_source_and_explicit_grant_not_private_or_untracked(tmp_path, monkeypatch):
    root, baseline, output = candidate(tmp_path, monkeypatch)
    exporter.main()
    tree = output / 'tree'
    names = {row['path'] for row in json.loads((output / 'ALLOWLIST.json').read_text())}
    assert names == {'LICENSE', 'AGENTS.md', 'desktop/adapter.py',
                     'package_macos/build.py', 'docs/desktop-license.md'}
    assert (tree / 'AGENTS.md').read_bytes() == (baseline / 'AGENTS.md').read_bytes()
    evidence = json.loads((output / 'APPLY_VERIFIED.json').read_text())
    assert evidence['exact_applied_bytes_and_modes'] and evidence['files_verified'] == len(names)
    assert not list(tree.rglob('.git'))
    # Refuse an output collision rather than replacing a reviewed snapshot.
    with pytest.raises(FileExistsError):
        exporter.main()
    assert (root / 'desktop/local-secret.txt').read_text() == 'LOCAL_UNTRACKED_CONTENT\n'


def test_selected_source_link_refused(tmp_path, monkeypatch):
    root, baseline, output = candidate(tmp_path, monkeypatch)
    selected = root / 'desktop/adapter.py'
    selected.unlink()
    selected.symlink_to(baseline / 'LICENSE')
    with pytest.raises(ValueError, match='Unsafe publication input'):
        exporter.main()


def test_report_flags_mac_personal_path_in_new_source(tmp_path, monkeypatch):
    root, baseline, output = candidate(tmp_path, monkeypatch)
    put(root, 'desktop/adapter.py', 'location = "/Users/example-owner/private"\n')
    exporter.main()
    findings = json.loads((output / 'REVIEW.json').read_text())['automated_findings']
    assert {'path': 'desktop/adapter.py', 'kind': 'personal-path'} in findings
