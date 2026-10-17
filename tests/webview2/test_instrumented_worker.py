"""Separate check artifact preserves bootstrap gates; normal entry is unchanged."""
import os
import sys
import types

import pytest

if os.name != 'nt':
    pytest.skip('Windows worker bootstrap', allow_module_level=True)

from desktop import windows_processes
from package_windows_webview2 import entry_instrumented as entry


@pytest.mark.parametrize('role', ['backend', 'adopt', 'maintenance', 'removal'])
def test_worker_authenticates_root_and_profile_before_dispatch(monkeypatch, role):
    events = []
    arguments = [] if role == 'backend' else ['--profile', 'wvfollowupcheck']
    monkeypatch.setattr(sys, 'argv', ['check.exe', '--desktop-worker', role, *arguments])
    monkeypatch.setenv('DLMS_DESKTOP_DATA_ROOT', 'marked-test-root')
    monkeypatch.setenv('DLMS_DESKTOP_PROFILE_NAME', 'wvfollowupcheck')
    monkeypatch.setenv('DLMS_DESKTOP_AUTOMATED', 'untrusted')
    monkeypatch.setenv('DLMS_DESKTOP_TEST_FAIL_MANIFEST', '1')
    def authenticate():
        assert 'DLMS_DESKTOP_AUTOMATED' not in os.environ
        assert not any(key.startswith('DLMS_DESKTOP_TEST_') for key in os.environ)
        events.append('authenticated')
    monkeypatch.setattr(windows_processes, 'bootstrap', authenticate)
    monkeypatch.setattr(entry, '_check_data_root', lambda value: events.append('root') or value)
    original_profile = entry._check_profile
    def profile(value):
        original_profile(value)
        events.append('profile')
    monkeypatch.setattr(entry, '_check_profile', profile)
    def run():
        assert events == ['authenticated', 'root', 'profile']
        assert sys.argv == ['check.exe', *arguments]
        assert os.environ.get('DLMS_DESKTOP_AUTOMATED') == ('1' if role == 'adopt' else None)
        assert not any(key.startswith('DLMS_DESKTOP_TEST_') for key in os.environ)
        return 7
    monkeypatch.setitem(sys.modules, 'desktop.' + role, types.SimpleNamespace(main=run))
    assert entry._worker() == 7


@pytest.mark.parametrize('arguments', [[], ['--profile'], ['--profile', 'default'],
    ['--profile=wvfollowupcheck'], ['--profile', 'wvfollowupcheck', '--profile', 'wvfollowupother']])
def test_worker_refuses_non_test_or_ambiguous_profile(monkeypatch, arguments):
    monkeypatch.setattr(sys, 'argv', ['check.exe', '--desktop-worker', 'adopt', *arguments])
    monkeypatch.setenv('DLMS_DESKTOP_DATA_ROOT', 'marked-test-root')
    monkeypatch.delenv('DLMS_DESKTOP_AUTOMATED', raising=False)
    monkeypatch.setattr(windows_processes, 'bootstrap', lambda: None)
    monkeypatch.setattr(entry, '_check_data_root', lambda value: value)
    with pytest.raises(ValueError, match='profile'):
        entry._worker()
    assert 'DLMS_DESKTOP_AUTOMATED' not in os.environ


def test_worker_authentication_failure_prevents_root_or_application_import(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check.exe', '--desktop-worker', 'adopt', '--profile', 'wvfollowupcheck'])
    monkeypatch.delenv('DLMS_DESKTOP_AUTOMATED', raising=False)
    def failed():
        raise RuntimeError('parent identity changed')
    monkeypatch.setattr(windows_processes, 'bootstrap', failed)
    monkeypatch.setattr(entry, '_check_data_root', lambda value: pytest.fail('Root before authentication'))
    with pytest.raises(RuntimeError, match='identity changed'):
        entry._worker()
    assert 'DLMS_DESKTOP_AUTOMATED' not in os.environ


def test_unknown_role_refused_before_bootstrap(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check.exe', '--desktop-worker', 'unknown'])
    monkeypatch.setattr(windows_processes, 'bootstrap', lambda: pytest.fail('Unknown role reached bootstrap'))
    with pytest.raises(ValueError, match='Unknown'):
        entry._worker()
