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
    return select_installer_guards(section, test_scope)


def select_installer_guards(section, test_scope):
    """Select named, reviewed build guards; unknown guards need review."""
    active = [True]
    selected = []
    values = {'TestScope': test_scope, 'PublicPreview': True}
    for line in section.splitlines():
        directive = line.strip()
        if directive.startswith('#ifdef '):
            name = directive.split()[1]
            assert name in values, 'Review new installer integration guard'
            active.append(active[-1] and values[name])
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


def icon_entries(section):
    """Read the concrete Name/Filename/Parameters/Tasks of each icon entry."""
    icons = section.split('[Icons]', 1)[1].split('[Run]', 1)[0]
    entries = {}
    for line in icons.splitlines():
        if not line.startswith('Name:'):
            continue
        fields = {}
        for item in line.split(';'):
            key, value = item.strip().split(':', 1)
            value = value.strip()
            if value.startswith('"'):
                assert value.endswith('"')
                value = value[1:-1]
            assert key not in fields
            fields[key] = value
        name = fields.pop('Name')
        assert name not in entries
        entries[name] = fields
    return entries


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

    # Four intended purposes, not just an entry count: always-available guarded
    # app launcher, optional menu launcher/uninstaller, and optional desktop.
    # Assert exact targets/profile callbacks and task ownership for both builds.
    application = {
        'Filename': '{app}\\versions\\{#Release}\\DLMS-Desktop-WebView2.exe',
        'Parameters': '{code:MenuProfileParameters}',
        'WorkingDir': '{app}\\versions\\{#Release}',
        'AppUserModelID': 'io.github.drakahari.DLMSDesktop.WebView2Candidate',
    }
    assert icon_entries(ordinary) == {
        '{app}\\Launch DLMS Desktop': application,
        '{group}\\DLMS Desktop': application | {'Tasks': 'not nostartmenu'},
        '{group}\\Uninstall DLMS Desktop': {
            'Filename': '{uninstallexe}', 'Tasks': 'not nostartmenu'},
        '{userdesktop}\\DLMS Desktop WebView2 Candidate': application | {
            'Parameters': '{code:DesktopProfileParameters}', 'Tasks': 'desktopicon'},
    }

    # TestScope must never create real user menu/desktop/registry integration.
    # Its menu macro defaults inside {app}; its explicit override is confined to
    # a TestScope build for the separately accepted unsafe-parent fixture.
    isolated = installer_integration(script, True)
    assert '{group}' not in isolated and '{userdesktop}' not in isolated
    assert '[Run]' not in isolated
    assert icon_entries(isolated) == {
        '{app}\\Launch DLMS Desktop': application,
        '{#TestMenuRoot}\\DLMS Desktop': application | {'Tasks': 'not nostartmenu'},
        '{#TestMenuRoot}\\Uninstall DLMS Desktop': {
            'Filename': '{uninstallexe}', 'Tasks': 'not nostartmenu'},
        '{app}\\synthetic-desktop\\DLMS Desktop': application | {
            'Parameters': '{code:DesktopProfileParameters}', 'Tasks': 'desktopicon'},
    }
    assert '#ifdef TestScope\n  #ifndef TestMenuRoot\n    #define TestMenuRoot "{app}\\synthetic-menu"\n  #endif\n#endif' in script
    setup = script.split('[Setup]', 1)[1].split('[Files]', 1)[0]
    for scope, expected in ((True, 'no'), (False, 'yes')):
        selected = select_installer_guards(setup, scope)
        assert [line for line in selected.splitlines() if line.startswith('CreateUninstallRegKey=')] == [
            'CreateUninstallRegKey=' + expected]
    # The exact profile is selected/validated once, then shared by app and menu
    # launchers; an existing optional desktop can preserve its own valid profile.
    assert 'begin Result := SavedMenuParameters; end;' in script
    assert 'begin Result := SavedDesktopParameters; end;' in script
    assert "SavedMenuParameters := '--profile ' + Profile;" in script
    assert 'if not CaptureShortcutProfile(AppLaunchPath, PreviousParameters) then Exit;' in script
    assert "not CaptureShortcutProfile(MenuPath, PreviousParameters) then begin" in script
    assert 'if FileExists(DesktopPath) then SavedDesktopParameters := PreviousParameters;' in script
