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


def installer_integration(script, test_scope):
    """Select only the real Inno integration branch; refuse unknown guards."""
    section = '[Tasks]' + script.split('[Tasks]', 1)[1].split('[Code]', 1)[0]
    active = [True]
    selected = []
    for line in section.splitlines():
        directive = line.strip()
        if directive == '#ifdef TestScope':
            active.append(active[-1] and test_scope)
        elif directive == '#else':
            assert len(active) > 1
            active[-1] = active[-2] and not active[-1]
        elif directive == '#endif':
            assert len(active) > 1
            active.pop()
        else:
            assert not directive.startswith('#'), 'Review new installer integration guard'
            if active[-1]:
                selected.append(line)
    assert active == [True]
    return '\n'.join(selected)


def test_shortcut_is_optional_unchecked_and_test_scope_is_app_private():
    script = (ROOT / 'package_windows_webview2/installer.iss').read_text()
    ordinary = installer_integration(script, False)
    task = next(line for line in ordinary.splitlines() if line.startswith('Name: "desktopicon"'))
    assert 'Flags: unchecked' in task
    assert '{userdesktop}\\DLMS Desktop WebView2 Candidate' in ordinary
    assert 'Tasks: desktopicon' in ordinary
    assert '{group}\\DLMS Desktop' in ordinary
    assert '[Run]' in ordinary and 'postinstall skipifsilent unchecked' in ordinary
    assert 'Parameters: "{code:MenuProfileParameters}"' in ordinary
    assert 'Parameters: "{code:DesktopProfileParameters}"' in ordinary

    # Real .lnk coverage is now intentional, strictly below the isolated app.
    # TestScope must still never create user menu/desktop/registry integration.
    isolated = installer_integration(script, True)
    assert '{group}' not in isolated and '{userdesktop}' not in isolated
    assert '[Run]' not in isolated
    icons = isolated.split('[Icons]', 1)[1]
    entries = [line for line in icons.splitlines() if line.startswith('Name:')]
    assert len(entries) == 2
    assert entries[0].startswith('Name: "{app}\\synthetic-menu\\')
    assert entries[1].startswith('Name: "{app}\\synthetic-desktop\\')
    assert 'Tasks: desktopicon' in entries[1]
    assert 'Parameters: "{code:MenuProfileParameters}"' in entries[0]
    assert 'Parameters: "{code:DesktopProfileParameters}"' in entries[1]
    registry = script.split('#ifdef TestScope', 1)[1].split('#endif', 1)[0]
    isolated_registry, ordinary_registry = registry.split('#else', 1)
    assert 'CreateUninstallRegKey=no' in isolated_registry
    assert 'CreateUninstallRegKey=yes' not in isolated_registry
    assert 'CreateUninstallRegKey=yes' in ordinary_registry
