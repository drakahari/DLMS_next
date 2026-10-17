"""Hosted-runner fixture setup must not change runtime ownership policy."""
import pytest

from tests.windows.ci_adapter_contracts import SELECTION, ordinary_fixture_owner


def test_windows_ci_retains_the_existing_native_selection():
    assert SELECTION == (
        'tests/windows/test_native.py',
        'tests/windows/test_reserved_paths.py',
        'tests/windows/test_restore_connection.py',
        'tests/webview2/test_ai_contract.py',
        'tests/webview2/test_backup_chooser.py',
    )


def test_fixture_setup_requires_explicit_hosted_windows_context(monkeypatch):
    # Even on Windows this must refuse before calling any native API.
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.delenv('RUNNER_OS', raising=False)
    with pytest.raises(RuntimeError, match='only for hosted Windows CI'):
        with ordinary_fixture_owner():
            pytest.fail('Non-CI invocation must not yield')
