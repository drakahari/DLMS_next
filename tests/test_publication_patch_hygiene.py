"""Outer source hygiene and strict inner publication validation are independent."""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tools.validate_publication_patch import git, validate


def commit(repository, message):
    git(repository, 'add', '--force', '--all')
    git(repository, '-c', 'user.name=Synthetic Test', '-c', 'user.email=test@example.invalid',
        'commit', '--quiet', '-m', message)
    return git(repository, 'rev-parse', 'HEAD').decode().strip()


def proposal(tmp_path, *, bad_whitespace=False):
    repository = tmp_path / 'baseline'
    repository.mkdir()
    git(repository, 'init', '--quiet')
    source = repository / 'example.py'
    source.write_text('first = 1\n\nvalue = 1\n\nlast = 1\n')
    base = commit(repository, 'synthetic baseline')
    source.write_text('first = 1\n\nvalue = 2' + (' ' if bad_whitespace else '') + '\n\nlast = 1\n')
    report = tmp_path / 'report'
    report.mkdir()
    patch = git(repository, 'diff', '--binary', base)
    (report / 'PROPOSED.patch').write_bytes(patch)
    (report / 'BASELINES.json').write_text(json.dumps({'public_main': base}))
    (report / 'APPLY_VERIFIED.json').write_text(json.dumps({
        'files_verified': 1, 'patch_sha256': hashlib.sha256(patch).hexdigest()}))
    manifest = [{'path': 'example.py', 'mode': '0o644',
                 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]
    (report / 'ALLOWLIST.json').write_text(json.dumps(manifest))
    return repository, report, base


def test_context_space_is_valid_patch_and_inherited_git_settings_are_ignored(tmp_path, monkeypatch):
    repository, report, base = proposal(tmp_path)
    assert b' \n' in (report / 'PROPOSED.patch').read_bytes()
    before = (repository / 'example.py').read_bytes()
    unrelated = tmp_path / 'unrelated'
    unrelated.mkdir()
    monkeypatch.setenv('GIT_DIR', str(unrelated))
    monkeypatch.setenv('GIT_WORK_TREE', str(unrelated))
    result = validate(repository, report, tmp_path / 'verification', expected_commit=base)
    assert result['files_verified'] == 1 and result['exact_bytes_and_modes']
    assert result['strict_added_source_whitespace']
    assert not list(unrelated.iterdir())
    assert (repository / 'example.py').read_bytes() == before


def test_actual_added_source_whitespace_refused_even_with_matching_checksums(tmp_path):
    repository, report, base = proposal(tmp_path, bad_whitespace=True)
    with pytest.raises(ValueError, match='whitespace'):
        validate(repository, report, tmp_path / 'verification', expected_commit=base)


def test_binary_encoded_text_cannot_hide_actual_source_whitespace(tmp_path):
    repository, report, base = proposal(tmp_path, bad_whitespace=True)
    (repository / '.git/info/attributes').write_text('example.py -diff\n')
    patch = git(repository, 'diff', '--binary', base)
    assert b'GIT binary patch' in patch
    (report / 'PROPOSED.patch').write_bytes(patch)
    evidence = json.loads((report / 'APPLY_VERIFIED.json').read_text())
    evidence['patch_sha256'] = hashlib.sha256(patch).hexdigest()
    (report / 'APPLY_VERIFIED.json').write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match='trailing whitespace'):
        validate(repository, report, tmp_path / 'verification', expected_commit=base)


@pytest.mark.parametrize('case', ['digest', 'duplicate', 'traversal', 'git-path',
                                  'mode', 'mode-mismatch', 'content', 'count', 'extra', 'baseline', 'missing-patch'])
def test_proposal_tampering_and_incomplete_manifest_refused(tmp_path, case):
    repository, report, base = proposal(tmp_path)
    manifest = json.loads((report / 'ALLOWLIST.json').read_text())
    evidence = json.loads((report / 'APPLY_VERIFIED.json').read_text())
    if case == 'digest':
        evidence['patch_sha256'] = '0' * 64
    elif case == 'duplicate':
        manifest += manifest
    elif case == 'traversal':
        manifest[0]['path'] = '../escape.py'
    elif case == 'git-path':
        manifest[0]['path'] = '.git/config'
    elif case == 'mode':
        manifest[0]['mode'] = '0o777'
    elif case == 'mode-mismatch':
        manifest[0]['mode'] = '0o755'
    elif case == 'content':
        manifest[0]['sha256'] = '0' * 64
    elif case == 'count':
        evidence['files_verified'] = 2
    elif case == 'extra':
        manifest[0]['path'] = 'omitted.py'
    elif case == 'missing-patch':
        (report / 'PROPOSED.patch').unlink()
    else:
        (report / 'BASELINES.json').write_text(json.dumps({'public_main': '0' * 40}))
    (report / 'ALLOWLIST.json').write_text(json.dumps(manifest))
    (report / 'APPLY_VERIFIED.json').write_text(json.dumps(evidence))
    with pytest.raises(ValueError):
        validate(repository, report, tmp_path / 'verification', expected_commit=base)
    assert not (tmp_path / 'escape.py').exists()


def test_exact_artifact_exception_does_not_disable_source_or_other_patch_hygiene(tmp_path):
    git(tmp_path, 'init', '--quiet')
    project = Path(__file__).resolve().parents[1]
    (tmp_path / '.gitattributes').write_bytes((project / '.gitattributes').read_bytes())
    commit(tmp_path, 'attributes baseline')
    patch = tmp_path / 'reports/private-consolidation/PROPOSED.patch'
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b'valid unified diff context representation\n \n')
    commit(tmp_path, 'patch syntax')
    git(tmp_path, 'diff', '--check', 'HEAD^', 'HEAD')
    for name in ('example.py', 'another.patch'):
        (tmp_path / name).write_bytes(b'actual trailing whitespace \n')
        commit(tmp_path, 'negative source control')
        with pytest.raises(ValueError):
            git(tmp_path, 'diff', '--check', 'HEAD^', 'HEAD')


def test_ci_requires_separate_patch_validation_without_a_blanket_exclusion():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.load((root / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    steps = workflow['jobs']['non-browser-tests']['steps']
    whitespace = next(s for s in steps if s.get('name') == 'Check changed-line whitespace')
    assert 'git diff --check HEAD^ HEAD' in whitespace['run']
    assert 'exclude' not in whitespace['run'] and '|| true' not in whitespace['run']
    validator = next(s for s in steps if s.get('name') == 'Verify frozen publication patch')
    assert 'validate_publication_patch.py' in validator['run']
    assert '2630ea8ebbf3aebe9e82142da905678dda96050a' in validator['run']
    assert 'continue-on-error' not in validator
    for name in ('BASELINES.json', 'ALLOWLIST.json', 'APPLY_VERIFIED.json', 'PROPOSED.patch'):
        assert f'reports/private-consolidation/{name}' in validator['if']
    assert (root / '.gitattributes').read_text().count('-whitespace') == 1
