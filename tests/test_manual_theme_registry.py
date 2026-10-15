"""Persistence, compatibility, and opaque semantic contracts for manual themes."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers
from dlms.themes import (DEFAULT_THEME, LEGACY_PALETTES, SOURCE_MANIFEST,
                         THEME_IDS, THEME_REGISTRY, contrast, normalize_theme)
from dlms.persistence.portal import dashboard_card_defaults


ROOT = Path(__file__).resolve().parents[1]


def test_registry_inventory_and_pinned_manifest():
    assert len(THEME_IDS) == 26
    assert len(SOURCE_MANIFEST['themes']) == 22
    assert SOURCE_MANIFEST['commit'] == 'c668141e9c42b13c80c9ca4ea108e11708c5e8a5'
    assert {item['dlms_id'] for item in SOURCE_MANIFEST['themes']} == THEME_IDS - {
        'light', 'dark', 'purple-gold', 'maroon-gold'}
    assert 'omarchy-ethereal' not in THEME_IDS
    assert sum(item['palette']['mode'] == 'light' for item in SOURCE_MANIFEST['themes']) == 5
    for item in SOURCE_MANIFEST['themes']:
        assert SOURCE_MANIFEST['commit'] in item['source_url']
        assert item['source_url'].endswith('/colors.toml')


def test_existing_theme_output_matches_captured_baseline():
    baseline = json.loads((ROOT / 'tests/fixtures/theme_baseline.json').read_text())
    for theme, expected in baseline['tokens'].items():
        with mock.patch.object(dlms, 'load_portal_config', return_value={'theme': theme}):
            response = dlms.app.test_client().get('/dynamic.css')
        assert response.headers['Cache-Control'] == 'no-store'
        assert dict(re.findall(r'(--[\w-]+):\s*([^;]+);', response.get_data(as_text=True))) == expected


@pytest.mark.parametrize('theme', sorted(THEME_IDS))
def test_every_theme_saves_reloads_and_survives_app_restart(theme, tmp_path):
    # Establish DLMS ownership while the dedicated temporary root is empty.
    dlms._initialize_data_root_ownership(str(tmp_path), is_default=False)
    portal = tmp_path / 'config/portal.json'
    portal.parent.mkdir()
    unrelated = {'title': 'Keep me', 'custom_setting': {'nested': [1, 2]},
                 'dashboard_card_visibility': {**dashboard_card_defaults(), 'it': False},
                 'study_area_visibility': {'it': True, 'law': False, 'medical': True, 'other': False}}
    portal.write_text(json.dumps({**unrelated, 'theme': 'light'}))
    client = dlms.app.test_client()
    with mock.patch.object(dlms, 'PORTAL_CONFIG', str(portal)):
        headers = csrf_headers(client)
        saved = client.post('/settings/appearance/save', data={'theme': theme}, headers=headers)
        assert saved.status_code == 302
        assert dlms.load_portal_config()['theme'] == theme
        page = client.get('/settings/appearance').get_data(as_text=True)
        assert f'<option value="{theme}" selected>' in page
        assert client.post('/api/theme', json={'theme': theme}, headers=headers).get_json()['theme'] == theme
    persisted = json.loads(portal.read_text())
    assert all(persisted[key] == value for key, value in unrelated.items())
    # A fresh interpreter imports the app against only this test's data root.
    env = {**os.environ, 'QUIZAPP_DATA_DIR': str(tmp_path), 'DLMS_NO_BROWSER': '1',
           'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, '-c',
        'import app; print("SAVED_THEME=" + app.load_portal_config()["theme"])'],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'SAVED_THEME=' + theme in result.stdout
    assert json.loads(portal.read_text()) == persisted


@pytest.mark.parametrize('value', [None, '', 'unknown', 7, False, [], {}, ['light'], {'theme': 'light'}])
def test_invalid_stored_values_fall_back_without_rewrite(value, tmp_path):
    portal = tmp_path / 'portal.json'
    original = json.dumps({'theme': value, 'keep': 123})
    portal.write_text(original)
    with mock.patch.object(dlms, 'PORTAL_CONFIG', str(portal)):
        assert dlms.load_portal_config()['theme'] == DEFAULT_THEME
    assert portal.read_text() == original
    assert normalize_theme(' LIGHT ') == 'light'


@pytest.mark.parametrize('payload', [{'theme': 'unknown'}, {'theme': 4}, {'theme': []},
                                     {'theme': {}}, [], ['light'], None, 'light', {}])
def test_invalid_api_payload_does_not_mutate(payload, tmp_path):
    portal = tmp_path / 'portal.json'
    original = '{"theme":"ethereal","keep":123}'
    portal.write_text(original)
    client = dlms.app.test_client()
    with mock.patch.object(dlms, 'PORTAL_CONFIG', str(portal)):
        response = client.post('/api/theme', data=json.dumps(payload), content_type='application/json',
                               headers=csrf_headers(client))
    assert response.status_code == 400
    assert portal.read_text() == original


def test_failed_atomic_write_preserves_saved_choice_and_allows_retry(tmp_path):
    portal = tmp_path / 'portal.json'
    original = '{"theme":"ethereal","keep":123}'
    portal.write_text(original)
    client = dlms.app.test_client()
    with mock.patch.object(dlms, 'PORTAL_CONFIG', str(portal)):
        headers = csrf_headers(client)
        with mock.patch('dlms.persistence.json_files.os.replace', side_effect=OSError('test full disk')):
            for route, body in (('/api/theme', {'json': {'theme': 'omarchy-white'}}),
                                ('/settings/appearance/save', {'data': {'theme': 'omarchy-white'}})):
                response = client.post(route, headers=headers, **body)
                assert response.status_code == 503
                assert portal.read_text() == original
                assert not list(tmp_path.glob('.*.tmp'))
        assert client.post('/api/theme', json={'theme': 'omarchy-white'}, headers=headers).status_code == 200
        assert dlms.load_portal_config()['theme'] == 'omarchy-white'
        assert json.loads(portal.read_text())['keep'] == 123


def test_theme_writes_still_require_csrf(tmp_path):
    portal = tmp_path / 'portal.json'
    portal.write_text('{"theme":"light"}')
    with mock.patch.object(dlms, 'PORTAL_CONFIG', str(portal)):
        for route in ('/api/theme', '/settings/appearance/save'):
            assert dlms.app.test_client().post(route, json={'theme': 'omarchy-white'}).status_code == 400
    assert portal.read_text() == '{"theme":"light"}'


def test_theme_saves_hold_the_existing_registry_lock(tmp_path):
    portal = tmp_path / 'portal.json'
    portal.write_text('{"theme":"light"}')
    original_lock, original_write = dlms.registry_lock, dlms._write_settings_portal_config
    depth = 0

    class ObservedLock:
        def __enter__(self):
            nonlocal depth
            original_lock.acquire()
            depth += 1

        def __exit__(self, *_):
            nonlocal depth
            depth -= 1
            original_lock.release()

    def checked_write(config):
        assert depth > 0
        return original_write(config)

    client = dlms.app.test_client()
    with mock.patch.object(dlms, 'PORTAL_CONFIG', str(portal)), \
         mock.patch.object(dlms, 'registry_lock', ObservedLock()), \
         mock.patch.object(dlms, '_write_settings_portal_config', checked_write):
        headers = csrf_headers(client)
        assert client.post('/api/theme', json={'theme': 'omarchy-white'}, headers=headers).status_code == 200
        assert client.post('/settings/appearance/save', data={'theme': 'omarchy-nord'}, headers=headers).status_code == 302


def test_invalid_appearance_choice_preserves_settings(tmp_path):
    portal = tmp_path / 'portal.json'
    original = '{"theme":"ethereal","title":"Keep me"}'
    portal.write_text(original)
    client = dlms.app.test_client()
    with mock.patch.object(dlms, 'PORTAL_CONFIG', str(portal)):
        response = client.post('/settings/appearance/save', data={'theme': 'unsupported'}, headers=csrf_headers(client))
    assert response.status_code == 400
    assert b'Settings were not saved' in response.data
    assert portal.read_text() == original


@pytest.mark.parametrize('original', [None, '{broken json'])
def test_invalid_api_does_not_initialize_or_recover_settings(original, tmp_path):
    portal = tmp_path / 'portal.json'
    if original is not None:
        portal.write_text(original)
    client = dlms.app.test_client()
    headers = csrf_headers(client)
    with mock.patch.object(dlms, 'PORTAL_CONFIG', str(portal)):
        assert client.post('/api/theme', json={'theme': 'unknown'}, headers=headers).status_code == 400
    if original is None:
        assert not portal.exists()
    else:
        assert portal.read_text() == original


@pytest.mark.parametrize('theme', sorted(THEME_IDS - LEGACY_PALETTES.keys()))
def test_new_theme_semantic_pairs(theme):
    entry = THEME_REGISTRY[theme]
    colors, extra = entry['colors'], entry['extra_tokens']
    for surface in ('body_base', 'panel1', 'surface', 'surface2', 'input_bg', 'sidebar1'):
        for text in ('page', 'heading', 'muted', 'link', 'nav_muted'):
            assert contrast(colors[text], colors[surface]) >= 4.5, (theme, text, surface)
        assert contrast(extra['--theme-control-border'], colors[surface]) >= 3
        assert contrast(extra['--theme-focus-ring'], colors[surface]) >= 3
        for index in range(10):
            assert contrast(extra[f'--theme-chart-{index}'], colors[surface]) >= 3
    assert contrast(colors['on_accent'], colors['accent']) >= 4.5
    assert contrast(extra['--theme-selection-text'], extra['--theme-selection-bg']) >= 7
    for role in ('success', 'warning', 'error'):
        assert contrast(extra[f'--theme-semantic-{role}-text'], extra[f'--theme-semantic-{role}-surface']) >= 4.5
