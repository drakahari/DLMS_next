"""Windows identity extraction and explicit optional installer integration."""
from pathlib import Path

import pytest

from package_windows_webview2.build import ROOT, source_backend_version


def test_captured_backend_identity_is_literal_without_import():
    assert source_backend_version() == '3.3.0'


@pytest.mark.parametrize('body', [
    'APP_VERSION = discover_version()',
    "APP_VERSION = '3.3.0'\nAPP_VERSION = discover_version()",
    "APP_VERSION = '3.3.0'\nAPP_VERSION = '9.9.9'",
    "APP_VERSION = '3.3.0\\nsecret'",
    'APP_VERSION = 3',
])
def test_ambiguous_or_nonliteral_backend_identity_refused(tmp_path, body):
    path = tmp_path / 'captured.py'
    path.write_text(body, encoding='utf-8')
    with pytest.raises(ValueError, match='bounded literal'):
        source_backend_version(path)


def test_shortcut_is_optional_unchecked_and_absent_from_test_scope():
    script = (ROOT / 'package_windows_webview2/installer.iss').read_text()
    ordinary = script.split('#ifndef TestScope\n[Tasks]', 1)[1].split('#endif', 1)[0]
    assert 'Name: "desktopicon"' in ordinary and 'Flags: unchecked' in ordinary
    assert '{userdesktop}\\DLMS Desktop WebView2 Candidate' in ordinary
    assert 'Tasks: desktopicon' in ordinary
