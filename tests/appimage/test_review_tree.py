"""Uncommitted build provenance must remain readable by the strict runtime."""
import json
import sys
from pathlib import Path

import pytest

from desktop import build_info
from package_appimage import build_payload


def arguments(tmp_path, monkeypatch, digest):
    args = ['build_payload', '--output', str(tmp_path/'build'), '--release', 'review-fixture',
            '--source-commit', '8fadfa5d0fb6a7f494c3e80f719641479e1dc442',
            '--source-tree-sha256', digest]
    for name in ('ocr-bundle', 'notices', 'distribution-kit'):
        folder = tmp_path/name
        folder.mkdir()
        args.extend(['--'+name, str(folder)])
    monkeypatch.setattr(sys, 'argv', args)


def test_review_build_preserves_runtime_identity_and_displays_digest(tmp_path, monkeypatch):
    arguments(tmp_path, monkeypatch, 'b'*64)
    monkeypatch.setattr(build_payload.subprocess, 'run', lambda *args, **kwargs: None)
    build_payload.main()
    assets = tmp_path/'desktop_assets'
    assets.mkdir()
    (assets/'build-info.json').write_bytes((tmp_path/'build/build-info.json').read_bytes())
    monkeypatch.setattr(build_info, '__file__', str(tmp_path/'desktop/build_info.py'))
    value = build_info.information()
    assert set(value) == {'application_version', 'release', 'source_commit', 'target', 'support'}
    assert 'Uncommitted review tree SHA-256: '+'b'*64 in build_info.about_text(
        mode='local', profile='synthetic', local_origin=None)
    assert json.loads((tmp_path/'build/review-tree.json').read_text()) == {
        'baseline_commit': value['source_commit'], 'source_dirty': True, 'source_tree_sha256': 'b'*64}


def test_invalid_review_tree_refused_before_freeze(tmp_path, monkeypatch):
    arguments(tmp_path, monkeypatch, '../not-a-digest')
    with pytest.raises(ValueError, match='SHA-256'):
        build_payload.main()
    assert not (tmp_path/'build').exists()
