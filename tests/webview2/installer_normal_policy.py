"""Native installer-policy checks. New private fixtures and inert payload only.

No user menu, registry integration, actual profile, application launch or existing
machine ACL is modified. These are not clean-account/default-click acceptance.
"""
from pathlib import Path
import argparse
import json
import subprocess
import time

from tests.webview2.installer_menu_policy import create_acl_directory, CAPABILITY, sha
from tests.webview2.installer_parent_probe import directory_sddl, fresh_scope

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    args = parser.parse_args()
    out = fresh_scope(args.output)
    out.mkdir(mode=0o700)
    source = ROOT / 'package_windows_webview2/installer.iss'
    payload = out / 'inert'
    payload.mkdir(mode=0o700)
    (payload / 'DLMS-Desktop-WebView2.exe').write_bytes(b'INERT NEVER EXECUTED\n')
    script = out / 'links.ps1'
    script.write_text('''param([string]$Request)
$a=Get-Content -LiteralPath $Request -Raw | ConvertFrom-Json
$s=New-Object -ComObject WScript.Shell
$l=$s.CreateShortcut($a.path)
if($a.write){$l.TargetPath=$a.target;$l.WorkingDirectory=$a.directory;$l.Arguments=$a.arguments;$l.Save()}
@{target=$l.TargetPath;directory=$l.WorkingDirectory;arguments=$l.Arguments}|ConvertTo-Json|Set-Content -LiteralPath $a.result -Encoding UTF8
''', encoding='utf-8-sig')
    serial = 0
    records = []

    def link(path, *, target=None, directory=None, arguments=None):
        nonlocal serial
        assert path.absolute().is_relative_to(out)
        serial += 1
        request = out / f'link-{serial}.json'
        response = out / f'link-result-{serial}.json'
        request.write_text(json.dumps(dict(path=str(path), target=str(target or ''),
            directory=str(directory or ''), arguments=arguments, write=target is not None,
            result=str(response))))
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                        str(script), '-Request', str(request)],
                       check=True, capture_output=True, timeout=20)
        return json.loads(response.read_text(encoding='utf-8-sig'))

    def record(name, condition):
        records.append(dict(case=name, passed=bool(condition)))
        (out / 'progress.json').write_text(json.dumps(records, indent=2))
        assert condition, name
        print('PASS ' + name, flush=True)

    def compile_variant(name, release, menu, data, adapter=None):
        dest = out / name
        dest.mkdir(mode=0o700)
        compiled_source = source
        if adapter:
            # Explicitly instrumented fixture; never shipping source/payload.
            text = adapter(source.read_text())
            text = text.replace(r'SetupIconFile=..\desktop_assets\icons\windows\DLMSDesktop.ico',
                                'SetupIconFile=' + str(ROOT / 'desktop_assets/icons/windows/DLMSDesktop.ico'))
            compiled_source = dest / 'instrumented.iss'
            compiled_source.write_text(text)
        command = [str(args.compiler), '--no-ide-signtools', '/DTestScope=1',
            '/DTestMenuRoot=' + str(menu), '/DTestDataRoot=' + str(data),
            '/DPayload=' + str(payload), '/DRelease=' + release,
            '/DOutputRoot=' + str(dest), str(compiled_source)]
        with (dest / 'compile.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
        exe, = dest.glob('*.exe')
        return exe

    def invoke(exe, app, name, profile=None):
        log = out / (name + '.log')
        command = [str(exe), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                   '/DIR=' + str(app), '/LOG=' + str(log)]
        if profile is not None:
            command.append('/DLMSPROFILE=' + profile)
        code = subprocess.run(command, timeout=60).returncode
        return code, log.read_text(encoding='utf-8-sig')

    base = 'D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
    parent = out / 'capability Programs'
    create_acl_directory(parent, base + '(A;;FA;;;' + CAPABILITY + ')(A;OICIIO;GA;;;' + CAPABILITY + ')')
    before_acl = directory_sddl(parent)
    menu = parent / 'DLMS'
    data = out / 'data'
    old = compile_variant('old', 'normal-policy-old', menu, data)
    new = compile_variant('new', 'normal-policy-new', menu, data)
    app = out / 'application'
    launcher = app / 'Launch DLMS Desktop.lnk'
    menu_link = menu / 'DLMS Desktop.lnk'
    state = app / 'launch-profile.txt'
    code, log = invoke(old, app, 'fresh-capability')
    record('fresh default menu installation accepts modeled capability parent', code == 0)
    expected = dict(target=str(app / 'versions/normal-policy-old/DLMS-Desktop-WebView2.exe'),
                    directory=str(app / 'versions/normal-policy-old'), arguments='--profile default')
    record('fresh default launch and menu targets/profile', link(launcher) == expected and link(menu_link) == expected)
    record('data initialization deferred to normal first launch', not data.exists())
    record('persistent automatic default selection', state.read_bytes() == b'DLMS-LAUNCH-PROFILE-1\r\ndefault')
    record('uninstall menu has only uninstall purpose', link(menu / 'Uninstall DLMS Desktop.lnk')['target'] == str(app / 'uninstall/unins000.exe'))
    record('desktop shortcut remains optional', not (app / 'synthetic-desktop/DLMS Desktop.lnk').exists())

    # Model trusted existing configuration and opaque existing data, not a
    # command-line override of the installer under test.
    for path in (data, data / 'profiles', data / 'profiles/fresh-20261017'):
        path.mkdir(mode=0o700)
    sentinel = data / 'profiles/fresh-20261017/synthetic-data.txt'
    sentinel.write_bytes(b'synthetic quiz/history/theme sentinel\r\n')
    sentinel_sha = sha(sentinel)
    expected['arguments'] = '--profile fresh-20261017'
    for path in (launcher, menu_link):
        link(path, **expected)
    state.write_bytes(b'DLMS-LAUNCH-PROFILE-1\r\nfresh-20261017')
    state.write_bytes(b'DLMS-LAUNCH-PROFILE-1\r\nmissing-profile')
    code, log = invoke(new, app, 'missing-selected')
    record('missing saved profile cannot replace existing data with empty profile',
           code != 0 and 'missing, but other DLMS profiles exist' in log)
    state.write_bytes(b'DLMS-LAUNCH-PROFILE-1\r\nfresh-20261017')
    code, log = invoke(new, app, 'upgrade-capability')
    expected.update(target=str(app / 'versions/normal-policy-new/DLMS-Desktop-WebView2.exe'),
                    directory=str(app / 'versions/normal-policy-new'))
    record('upgrade automatically preserves named selection/data/previous payload',
           code == 0 and link(launcher) == expected and link(menu_link) == expected
           and sha(sentinel) == sentinel_sha and (app / 'versions/normal-policy-old/DLMS-Desktop-WebView2.exe').exists())
    uninstall = app / 'uninstall/unins000.exe'
    code = subprocess.run([str(uninstall), '/VERYSILENT', '/SUPPRESSMSGBOXES',
        '/NORESTART', '/LOG=' + str(out / 'uninstall.log')], timeout=60).returncode
    time.sleep(1)
    record('uninstall preserves selection record and data, removes menu launch',
           code == 0 and state.exists() and sha(sentinel) == sentinel_sha and not menu_link.exists())
    if menu.exists():
        menu.rmdir()  # only this known empty synthetic directory; never recursive
    code, log = invoke(new, app, 'reinstall-capability')
    record('reinstall recreates menu with intended profile without manual entry',
           code == 0 and link(menu_link) == expected and sha(sentinel) == sentinel_sha)
    record('reported Programs ACL unchanged', directory_sddl(parent) == before_acl)

    state.write_bytes(b'bad selection')
    code, log = invoke(new, app, 'bad-state')
    record('invalid saved state is not treated as fresh', code != 0 and 'saved DLMS launch selection is invalid' in log)
    (data / 'profiles/another').mkdir(mode=0o700)
    state.write_bytes(b'DLMS-LAUNCH-PROFILE-1\r\nanother')
    code, log = invoke(new, app, 'conflicting-state')
    record('conflicting trusted selections require explicit recovery', code != 0 and 'Several existing DLMS profiles' in log)
    state.write_bytes(b'DLMS-LAUNCH-PROFILE-1\r\nfresh-20261017')
    bad_expected = dict(expected, target=str(app / 'versions/missing/DLMS-Desktop-WebView2.exe'),
                        directory=str(app / 'versions/missing'))
    link(menu_link, **bad_expected)
    code, log = invoke(new, app, 'invalid-shortcut')
    record('invalid existing target is refused separately from capability parent',
           code != 0 and 'existing shortcut must be a trusted regular file' in log)
    link(menu_link, **expected)
    removed = data / 'removed'
    removed.write_bytes(b'not a directory')
    code, log = invoke(new, app, 'removed-file')
    record('regular-file removal history refused', code != 0 and 'removal history is unsafe' in log)
    removed.unlink()  # known synthetic file just created by this driver
    removed.mkdir(mode=0o700)
    tombstone = removed / 'fresh-20261017.json'
    tombstone.write_text('{}')
    code, log = invoke(new, app, 'removed-tombstone')
    record('intentional removal prevents automatic profile recreation',
           code != 0 and 'intentional-removal record' in log)
    tombstone.unlink()
    removed.rmdir()
    junction_target = out / 'junction-target'
    junction_target.mkdir(mode=0o700)
    subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(removed), str(junction_target)],
                   check=True, capture_output=True, timeout=15)
    code, log = invoke(new, app, 'removed-reparse')
    record('reparse removal history refused', code != 0 and 'removal history is unsafe' in log)
    removed.rmdir()  # removes only the task-created junction, not its target

    def stale_adapter(text):
        point = 'Expected := ResolutionEvidence; Choice := SelectedProfile;'
        assert text.count(point) == 1
        return text.replace(point, point + """
  if not SaveStringToFile(ProfileRecordPath, 'DLMS-LAUNCH-PROFILE-1'#13#10 + 'another', False) then
    RaiseException('Fixture could not change its synthetic selection');
""")
    stale = compile_variant('stale', 'normal-policy-new', menu, data, stale_adapter)
    code, log = invoke(stale, app, 'stale-selection')
    record('changed selection between wizard resolution and install refused',
           code != 0 and 'launch configuration changed while Setup was open' in log)
    state.write_bytes(b'DLMS-LAUNCH-PROFILE-1\r\nfresh-20261017')

    def move_fault(text):
        declaration = 'function NativeMoveFile(Source, Destination: String; Flags: LongWord): Boolean;'
        assert text.count(declaration) == 1
        text = text.replace(declaration, declaration.replace('NativeMoveFile', 'RealNativeMoveFile'))
        return text.replace('function SidString(Sid: NativeUInt): String;', '''
function NativeMoveFile(Source, Destination: String; Flags: LongWord): Boolean;
begin Result := False; end;

function SidString(Sid: NativeUInt): String;''', 1)
    fault = compile_variant('move-fault', 'normal-policy-new', menu, data, move_fault)
    state.write_bytes(b'DLMS-LAUNCH-PROFILE-1\r\nanother')
    before = state.read_bytes()
    code, log = invoke(fault, app, 'publication-failure', profile='fresh-20261017')
    record('atomic publication failure preserves prior record and reports incomplete install',
           code != 0 and state.read_bytes() == before and 'Could not publish the DLMS launch selection' in log
           and sha(sentinel) == sentinel_sha)
    # The failed setup changed only synthetic shortcut arguments. Restore them
    # to the fixture's intended pre-fault selection for subsequent checks.
    for path in (launcher, menu_link):
        link(path, **expected)

    safe_parent = out / 'safe Programs'
    safe_parent.mkdir(mode=0o700)
    safe_menu = safe_parent / 'DLMS'
    safe_data = out / 'legacy-data'
    for path in (safe_data, safe_data / 'shell', safe_data / 'shell/fresh-20261017'):
        path.mkdir(mode=0o700)
    safe_exe = compile_variant('safe', 'normal-policy-new', safe_menu, safe_data)
    safe_app = out / 'safe-app'
    code, log = invoke(safe_exe, safe_app, 'safe-singleton')
    record('ordinary safe menu and legacy Server-only singleton discovery',
           code == 0 and link(safe_menu / 'DLMS Desktop.lnk')['arguments'] == '--profile fresh-20261017')
    # A genuinely new app root, no authoritative shortcut or record.
    other_menu = safe_parent / 'Other'
    (safe_data / 'shell/second').mkdir(mode=0o700)
    ambiguous = compile_variant('ambiguous', 'normal-policy-new', other_menu, safe_data)
    code, log = invoke(ambiguous, out / 'ambiguous-app', 'ambiguous-data')
    record('multiple legacy profiles do not silently create default', code != 0 and 'Several existing DLMS profiles' in log)

    unsafe_parent = out / 'ordinary-untrusted Programs'
    create_acl_directory(unsafe_parent, base + '(A;OICI;FA;;;WD)(A;OICI;FA;;;' + CAPABILITY + ')')
    unsafe = compile_variant('untrusted', 'normal-policy-new', unsafe_parent / 'DLMS', out / 'absent-data')
    code, log = invoke(unsafe, out / 'untrusted-app', 'untrusted-write')
    record('capability does not mask ordinary untrusted write grant', code != 0 and
           'shortcut creation parent has unsafe' in log and not (unsafe_parent / 'DLMS').exists())
    strict_app = out / 'capability-app'
    create_acl_directory(strict_app, base + '(A;OICI;FA;;;' + CAPABILITY + ')')
    code, log = invoke(new, strict_app, 'strict-payload')
    record('capability allowance cannot reach application tree', code != 0 and
           ('shortcut creation parent has unsafe' in log or 'installation directory is unsafe' in log))
    result = dict(source_sha256=sha(source), compiler_sha256=sha(args.compiler), cases=records,
                  synthetic_only=True, inert_payload_never_executed=True,
                  no_actual_user_menu_registry_profiles_or_existing_acls_changed=True,
                  clean_account_or_physical_default_click_acceptance=False)
    (out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(passed=len(records), result=str(out / 'RESULT.json'))))


if __name__ == '__main__':
    main()
