"""Installer-only source boundaries; native qualification is a separate driver."""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'package_windows_webview2/installer.iss'
BASE = '2107e5cffc787705dfbbb495995655ebd504dedd'
BASE_BLOB = 'a8b85543827e9428b6745d24f712619271f4ff1b'
BASE_GUARD_FIXTURE_SHA256 = '158b04aa248b2b5860c2eab9b7b60bb2eacaba8c619a4c1cab7dc094fe1ee473'
BASE_GUARDS = Path(__file__).parent / 'fixtures/installer_guards_2107e5c.iss.txt'


def test_security_and_path_guards_unchanged():
    current = SOURCE.read_text()
    # Exact guard-region and following boundary from BASE/BASE_BLOB. LF text keeps
    # the comparison exact across Windows checkouts without fetching Git history.
    original = BASE_GUARDS.read_text(encoding='utf-8')
    assert hashlib.sha256(original.encode('utf-8')).hexdigest() == BASE_GUARD_FIXTURE_SHA256
    start = 'function NativeAttributes('
    end = 'function MenuProfileParameters('
    boundary = 'function MenuProfileParameters(Unused: String): String;\n'
    assert original.startswith(start) and original.count(end) == 1
    assert original.endswith(boundary)
    assert current[current.index(start):current.index(end)] == original[:-len(boundary)]
    assert 'S-1-15-3-' not in current  # no capability whitelist


def test_no_menu_is_explicit_and_gates_both_real_and_isolated_icons():
    source = SOURCE.read_text()
    assert 'UsePreviousTasks=no' in source
    assert 'Name: "nostartmenu";' in source
    line = next(x for x in source.splitlines() if x.startswith('Name: "nostartmenu";'))
    assert 'Flags: unchecked' in line
    menu = [x for x in source.splitlines() if x.startswith('Name: "{group}') or x.startswith('Name: "{#TestMenuRoot}')]
    assert len(menu) == 4
    assert all('Tasks: not nostartmenu' in x for x in menu)
    capture = source.split('function CaptureLaunchProfiles: Boolean;', 1)[1].split('function PrepareToInstall', 1)[0]
    assert "if not WizardIsTaskSelected('nostartmenu') and" in capture
    assert 'CaptureShortcutProfile(MenuPath, PreviousParameters)' in capture
    assert 'SetNamedSecurityInfo' not in source and 'SetFileSecurity' not in source


def test_explicit_profile_and_safe_app_launcher():
    source = SOURCE.read_text()
    assert 'Name: "{app}\\Launch DLMS Desktop";' in source
    assert 'CaptureShortcutProfile(AppLaunchPath, PreviousParameters)' in source
    assert "ProfilePage.Values[0] := ExpandConstant('{param:DLMSPROFILE|}')" in source
    assert 'ProfileConfirmation.Checked := False' in source
    assert 'not WizardSilent and not ProfileConfirmation.Checked' in source
    assert "SavedMenuParameters := '--profile ' + Profile" in source
    prepare = source.split('function PrepareToInstall', 1)[1]
    assert prepare.index('ProfileSelectionError') < prepare.index('GuardApplication(True)')
    assert 'Start menu integration cannot safely use this destination.' in source
    assert 'Existing DLMS Start menu launch shortcut is invalid or unsafe.' in source
    assert 'Existing DLMS launch shortcut could not be safely preserved.' not in source
    capture = source.split('function CaptureShortcutProfile(', 1)[1].split('function StartMenuLaunchPath', 1)[0]
    assert capture.index('ShortcutParentUnsafe := False') < capture.index('Attributes := NativeAttributes')
    assert capture.index(' + Parent;') < capture.index('if not SafeCreationParent(Parent)')
    next_click = source.split('function NextButtonClick(', 1)[1].split('function UpdateReadyMemo', 1)[0]
    assert next_click.index('if WizardSilent then Exit') < next_click.index('MsgBox(')


def test_test_menu_override_cannot_escape_into_shipping_build():
    source = SOURCE.read_text()
    definition = source.split('[Setup]', 1)[0]
    assert '#ifdef TestScope\n  #ifndef TestMenuRoot' in definition
    paths = source.split('function StartMenuLaunchPath: String;', 1)[1].split('function AppLaunchPath', 1)[0]
    assert "#else\n  Result := ExpandConstant('{group}\\DLMS Desktop.lnk');" in paths
