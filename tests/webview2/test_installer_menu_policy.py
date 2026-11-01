"""Installer-only source boundaries; native qualification is a separate driver."""
from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'package_windows_webview2/installer.iss'
BASE = '2107e5cffc787705dfbbb495995655ebd504dedd'
BASE_BLOB = 'a8b85543827e9428b6745d24f712619271f4ff1b'
BASE_GUARD_FIXTURE_SHA256 = '158b04aa248b2b5860c2eab9b7b60bb2eacaba8c619a4c1cab7dc094fe1ee473'
BASE_GUARDS = Path(__file__).parent / 'fixtures/installer_guards_2107e5c.iss.txt'


def function(text, name):
    pattern = rf'(?m)^(?:function|procedure) {name}\b'
    start = re.search(pattern, text).start()
    following = re.search(r'(?m)^(?:function|procedure) ', text[start + 1:])
    return text[start:start + 1 + following.start()] if following else text[start:]


def test_payload_path_and_effective_access_guards_remain_exact():
    current = SOURCE.read_text()
    original = BASE_GUARDS.read_text(encoding='utf-8')
    assert hashlib.sha256(original.encode('utf-8')).hexdigest() == BASE_GUARD_FIXTURE_SHA256
    # Only the reviewed shell-principal classification is changed. These
    # payload/data/path-substitution checks still match the pinned fixture.
    for name in ('SidString', 'InitializeGuard', 'EffectiveCreateAccess',
                 'OwnedDirectory', 'ReservedDosStem', 'NativeLocalPath',
                 'PinDirectory', 'ReleasePins', 'SafeDirectoryChain', 'SafeTree',
                 'SafeCreationParent', 'EnsurePrivateDirectory', 'GuardApplication',
                 'SupportedWebView2Version', 'HasWebView2Runtime'):
        assert function(current, name).strip() == function(original, name).strip(), name
    strict = function(current, 'DirectorySecurityAllowed')
    assert 'CreationParent, False' in strict
    assert 'DirectorySecurityCore(Handle, CreationParent, False)' in function(current, 'DirectorySecurity')
    assert 'ShellObject and CapabilityPrincipal(Ace + 8)' in function(current, 'DirectorySecurityAllowedCore')
    assert "'S-1-15-3-'" in function(current, 'CapabilityPrincipal')
    assert 'NativeValidSid(Sid)' in function(current, 'CapabilityPrincipal')
    assert '2968813833' not in current  # no individual capability whitelist
    assert 'SetNamedSecurityInfo' not in current and 'SetFileSecurity' not in current


def test_normal_launch_and_profile_ui_defaults():
    source = SOURCE.read_text()
    launch = next(x for x in source.splitlines() if 'Description: "Open DLMS Desktop"' in x)
    assert 'postinstall skipifsilent' in launch and 'unchecked' not in launch
    assert 'CreateInputQueryPage' not in source and 'ProfileConfirmation' not in source
    assert 'CreateInputOptionPage' in source
    assert "if ProfileChoices.Count = 0 then AddProfile('default')" in source
    assert 'TokenElevation(Token, 20' in source and '(Elevated <> 0)' in source
    resolve = function(source, 'ResolveProfile')
    assert resolve.index('TokenElevation') < resolve.index('CaptureProfileChoice')
    assert "DiscoverProfiles(DataRoot + '\\profiles')" in resolve
    assert "DiscoverProfiles(DataRoot + '\\shell')" in resolve
    assert 'Existing.IndexOf(Authority[I]) < 0' in resolve
    prepare = function(source, 'PrepareToInstall')
    assert prepare.index('ResolutionEvidence <> Expected') < prepare.index('GuardApplication(True)')


def test_profile_state_is_not_an_inplace_overwrite_or_uninstall_target():
    source = SOURCE.read_text()
    write = function(source, 'SaveProfileRecord')
    assert "if Text = Buffer then begin CloseNative(Previous); Exit; end" in write
    assert write.index('NativeFlush(Handle)') < write.index('NativeMoveFile(')
    assert 'Flags := 8' in write and 'if RecordExisted then Flags := Flags or 1' in write
    assert 'launch-profile.txt' not in source.split('[Code]')[0]
    assert 'Step = ssPostInstall' in function(source, 'CurStepChanged')
    capture = function(source, 'CaptureShortcutProfile')
    assert 'DirectorySecurityCore(Handle, False, ShellObject)' in capture
    assert 'not PinDirectory(Directory, True)' in capture
    assert 'OwnedDirectory(TargetHandle)' in capture


def test_positive_checked_menu_and_distinct_errors_remain():
    source = SOURCE.read_text()
    task = next(x for x in source.splitlines() if x.startswith('Name: "startmenu";'))
    assert 'Description: "Create a Start menu shortcut"' in task
    assert 'unchecked' not in task
    desktop = next(x for x in source.splitlines() if x.startswith('Name: "desktopicon";'))
    assert 'Flags: unchecked' in desktop
    menu = [x for x in source.splitlines() if x.startswith('Name: "{group}') or x.startswith('Name: "{#TestMenuRoot}')]
    assert len(menu) == 4 and all('Tasks: startmenu' in x for x in menu)
    assert source.count("if WizardIsTaskSelected('startmenu') and") == 2
    assert 'nostartmenu' not in source
    memo = function(source, 'UpdateReadyMemo')
    assert 'SelectedProfile' not in memo and 'DLMS profile:' not in memo
    assert 'Install without Start menu entries' not in source
    assert 'Start menu integration cannot safely use this destination.' in source
    assert 'Existing DLMS Start menu launch shortcut is invalid or unsafe.' in source
    assert 'Existing DLMS launch shortcut could not be safely preserved.' not in source


def test_test_menu_override_cannot_escape_into_shipping_build():
    source = SOURCE.read_text()
    definition = source.split('[Setup]', 1)[0]
    assert '#ifdef TestScope\n  #ifndef TestMenuRoot' in definition
    paths = source.split('function StartMenuLaunchPath: String;', 1)[1].split('function AppLaunchPath', 1)[0]
    assert "#else\n  Result := ExpandConstant('{group}\\DLMS Desktop.lnk');" in paths
