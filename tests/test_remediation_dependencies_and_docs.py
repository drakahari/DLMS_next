"""Focused prevention for the audited Windows device path and stale guidance."""
import ntpath
from pathlib import Path
from types import SimpleNamespace

import pytest
from werkzeug import security

from dlms.themes import THEME_IDS, theme_groups
from tools.check_release_dependencies import locked_requirements

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path', ['NUL:', 'NUL::$DATA', 'nested/CON:', 'nested/com1::$DATA'])
def test_werkzeug_rejects_windows_devices_with_empty_streams(monkeypatch, path):
    # Exercise upstream's Windows path branch without opening a device. This
    # does not constitute native Windows/NTFS acceptance.
    monkeypatch.setattr(security, 'os', SimpleNamespace(name='nt', path=ntpath))
    assert security.safe_join('uploads', path) is None
    assert security.safe_join('uploads', 'course.pdf') == 'uploads/course.pdf'


def test_werkzeug_build_test_and_runtime_pins_agree():
    for filename in ('requirements-build.txt', 'requirements-test.txt'):
        assert locked_requirements(ROOT / filename)['werkzeug'] == '3.1.9'
    assert 'Werkzeug>=3.1.9,<3.2' in (ROOT / 'requirements.txt').read_text()
    assert 'Werkzeug==3.1.9' in (ROOT / 'docs/screenshots/requirements.txt').read_text()


def test_canonical_theme_guidance_matches_registry():
    assert len(THEME_IDS) == 26
    assert sum(len(group['options']) for group in theme_groups()) == 26
    for name in ('16-settings-and-runtime.md', 'appendix-keyboard-and-accessibility.md'):
        text = (ROOT / 'docs/user-manual' / name).read_text()
        assert '26 manually selectable themes' in text
        assert 'provides five themes' not in text
    assert (ROOT / 'static/help_assets/settings-appearance-theme.webp').is_file()


def test_browser_capture_setup_creates_nested_directories(monkeypatch, tmp_path):
    from tests.browser.test_critical_workflows import _CAPTURE_ENVIRONMENTS, _prepare_capture_directories
    for number, name in enumerate(_CAPTURE_ENVIRONMENTS):
        monkeypatch.setenv(name, str(tmp_path / str(number) / 'nested'))
    _prepare_capture_directories()
    _prepare_capture_directories()
    assert all((tmp_path / str(number) / 'nested').is_dir() for number in range(len(_CAPTURE_ENVIRONMENTS)))
