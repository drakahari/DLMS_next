"""Native installer-only qualification in fresh task-owned scopes.

Compiles tiny TestScope variants with inert (never executed) payload bytes.
Creates ACLs only at creation of new synthetic directories; no existing machine
permissions, shell folders, registry entries, data or applications are changed.
No desktop input or application workflow is exercised.
"""
from pathlib import Path
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
import subprocess
import time

from tests.webview2.installer_parent_probe import directory_sddl, fresh_scope

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.gate1/windows-native'
CAPABILITY = 'S-1-15-3-2968813833-811790644-2202111208-3784096404-1081847329-2708967783-1438471679'
PROFILE = 'fresh-20261017'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_acl_directory(path, sddl):
    """Set the initial descriptor in CreateDirectory, never edit an existing ACL."""
    assert not path.exists() and path.absolute().is_relative_to(WORK)
    api = c.WinDLL('advapi32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    convert = api.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.c_void_p]
    convert.restype = w.BOOL
    class SecurityAttributes(c.Structure):
        _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]
    create = kernel.CreateDirectoryW
    create.argtypes = [w.LPCWSTR, c.POINTER(SecurityAttributes)]
    create.restype = w.BOOL
    kernel.LocalFree.argtypes = [c.c_void_p]
    descriptor = c.c_void_p()
    if not convert(sddl, 1, c.byref(descriptor), None):
        raise c.WinError(c.get_last_error())
    try:
        attrs = SecurityAttributes(c.sizeof(SecurityAttributes), descriptor, False)
        if not create(str(path), c.byref(attrs)):
            raise c.WinError(c.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = fresh_scope(args.output)
    out.mkdir(mode=0o700)
    source = ROOT / 'package_windows_webview2/installer.iss'
    source_sha = sha(source)
    payload = out / 'inert-payload'
    payload.mkdir(mode=0o700)
    (payload / 'DLMS-Desktop-WebView2.exe').write_bytes(b'SYNTHETIC INERT FILE - NEVER EXECUTE\n')
    compiler = WORK / 'inno-portable/ISCC.exe'
    script = out / 'shortcut.ps1'
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
        request.write_text(json.dumps({'path': str(path), 'target': str(target or ''),
            'directory': str(directory or ''), 'arguments': arguments, 'write': target is not None,
            'result': str(response)}))
        subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
            '-File', str(script), '-Request', str(request)], check=True, capture_output=True, timeout=20)
        return json.loads(response.read_text(encoding='utf-8-sig'))

    def compile_variant(name, release, menu):
        folder = out / name
        folder.mkdir(mode=0o700)
        cmd = [str(compiler), '--no-ide-signtools', '/DTestScope=1',
            '/DTestMenuRoot=' + str(menu), '/DPayload=' + str(payload),
            '/DRelease=' + release, '/DOutputRoot=' + str(folder), str(source)]
        with (folder / 'compile.log').open('w') as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=source.parent, check=True, timeout=60)
        exe, = folder.glob('*.exe')
        return exe

    def invoke(exe, app, name, *, no_menu=False, profile=PROFILE):
        cmd = [str(exe), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            '/DIR=' + str(app), '/TASKS=' + ('nostartmenu' if no_menu else ''),
            '/LOG=' + str(out / (name + '.log'))]
        if profile is not None:
            cmd.append('/DLMSPROFILE=' + profile)
        code = subprocess.run(cmd, timeout=60).returncode
        return code, (out / (name + '.log')).read_text(encoding='utf-8-sig')

    def record(name, condition):
        assert condition, name
        records.append({'case': name, 'passed': True})
        (out / 'progress.json').write_text(json.dumps(records, indent=2))
        print('PASS ' + name, flush=True)

    # Match the rejecting ACEs at a NEW synthetic shell parent only.
    # Creation owner is the current user; OW is the owner-rights principal.
    base_acl = 'D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
    unsafe_parent = out / 'unsafe shell Programs'
    create_acl_directory(unsafe_parent, base_acl + '(A;;FA;;;' + CAPABILITY + ')(A;OICIIO;GA;;;' + CAPABILITY + ')')
    safe_parent = out / 'safe shell Programs'
    safe_parent.mkdir(mode=0o700)
    unsafe_before = directory_sddl(unsafe_parent)
    safe_before = directory_sddl(safe_parent)
    unsafe_menu = unsafe_parent / 'DLMS'
    safe_menu = safe_parent / 'DLMS'
    unsafe_old = compile_variant('unsafe-old', 'menu-policy-old', unsafe_menu)
    unsafe_new = compile_variant('unsafe-new', 'menu-policy-new', unsafe_menu)
    safe_old = compile_variant('safe-old', 'menu-policy-old', safe_menu)
    safe_new = compile_variant('safe-new', 'menu-policy-new', safe_menu)
    app = out / 'unsafe-parent installation'
    data = out / 'external synthetic data'
    data.mkdir(mode=0o700)
    sentinel = data / PROFILE
    sentinel.write_bytes(b'synthetic durable state must survive install, update and uninstall\r\n')
    sentinel_sha = sha(sentinel)

    code, log = invoke(unsafe_old, app, 'unsafe-menu-fresh')
    record('unsafe parent accurately refused before menu or payload writes', code != 0 and
        'Start menu integration cannot safely use this destination.' in log and
        str(unsafe_parent) in log and not unsafe_menu.exists() and not list(app.rglob('*.exe')))
    code, log = invoke(unsafe_old, app, 'no-menu-no-profile', no_menu=True, profile=None)
    record('no-menu does not imply a default profile', code != 0 and 'Explicit profile selection is required' in log)
    code, log = invoke(unsafe_old, app, 'no-menu-invalid-profile', no_menu=True, profile='../bad')
    record('unsafe profile refused', code != 0 and 'Explicit profile selection is required' in log)
    code, log = invoke(unsafe_old, app, 'no-menu-fresh', no_menu=True)
    launcher = app / 'Launch DLMS Desktop.lnk'
    expected = {'target': str(app / 'versions/menu-policy-old/DLMS-Desktop-WebView2.exe'),
                'directory': str(app / 'versions/menu-policy-old'), 'arguments': '--profile ' + PROFILE}
    record('explicit no-menu fresh installation has safe named-profile launcher',
           code == 0 and link(launcher) == expected and not unsafe_menu.exists())
    code, log = invoke(unsafe_new, app, 'no-menu-upgrade', no_menu=True)
    expected.update(target=str(app / 'versions/menu-policy-new/DLMS-Desktop-WebView2.exe'), directory=str(app / 'versions/menu-policy-new'))
    record('no-menu upgrade preserves named profile and old payload', code == 0 and
        link(launcher) == expected and Path(app / 'versions/menu-policy-old/DLMS-Desktop-WebView2.exe').exists() and
        not unsafe_menu.exists() and sha(sentinel) == sentinel_sha)
    # Existing unsafe menu entries are neither read for profile authority nor changed.
    unsafe_menu.mkdir()
    foreign = unsafe_menu / 'DLMS Desktop.lnk'
    foreign.write_bytes(b'untrusted synthetic existing menu bytes')
    foreign_sha = sha(foreign)
    code, log = invoke(unsafe_new, app, 'no-menu-existing-unsafe-entry', no_menu=True)
    record('no-menu leaves unsafe existing menu unchanged', code == 0 and sha(foreign) == foreign_sha)
    uninstall = app / 'uninstall/unins000.exe'
    code = subprocess.run([str(uninstall), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
        '/LOG=' + str(out / 'no-menu-uninstall.log')], timeout=60).returncode
    time.sleep(1)
    record('no-menu uninstall leaves external data and unowned menu unchanged',
           code == 0 and sha(sentinel) == sentinel_sha and sha(foreign) == foreign_sha and not launcher.exists())
    code, log = invoke(unsafe_new, app, 'no-menu-reinstall', no_menu=True)
    record('reinstall after uninstall retains explicit intended profile and external data',
           code == 0 and link(launcher) == expected and sha(sentinel) == sentinel_sha and sha(foreign) == foreign_sha)

    safe_app = out / 'safe-parent installation'
    code, log = invoke(safe_old, safe_app, 'safe-menu-fresh')
    menu_link = safe_menu / 'DLMS Desktop.lnk'
    record('ordinary safe-menu fresh install', code == 0 and menu_link.exists() and
        (safe_menu / 'Uninstall DLMS Desktop.lnk').exists() and
        link(menu_link)['arguments'] == '--profile ' + PROFILE)
    # Actual existing-shortcut rejection must remain separate from parent rejection.
    good = link(menu_link)
    link(menu_link, target=safe_app / 'versions/removed/DLMS-Desktop-WebView2.exe',
         directory=safe_app / 'versions/removed', arguments='--profile ' + PROFILE)
    before = menu_link.read_bytes()
    code, log = invoke(safe_new, safe_app, 'invalid-existing-menu')
    record('missing-target existing shortcut has distinct refusal and no overwrite', code != 0 and
        'Existing DLMS Start menu launch shortcut is invalid or unsafe.' in log and menu_link.read_bytes() == before)
    link(menu_link, target=good['target'], directory=good['directory'], arguments=good['arguments'])
    code, log = invoke(safe_new, safe_app, 'safe-menu-upgrade')
    record('ordinary safe-menu upgrade', code == 0 and link(menu_link)['arguments'] == '--profile ' + PROFILE and
        link(menu_link)['target'] == str(safe_app / 'versions/menu-policy-new/DLMS-Desktop-WebView2.exe'))
    before = menu_link.read_bytes()
    code, log = invoke(safe_new, safe_app, 'safe-menu-opt-out-upgrade', no_menu=True)
    record('opting out on upgrade leaves prior menu unchanged', code == 0 and menu_link.read_bytes() == before)
    code = subprocess.run([str(safe_app / 'uninstall/unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
        '/LOG=' + str(out / 'safe-menu-uninstall.log')], timeout=60).returncode
    time.sleep(1)
    record('uninstall after opt-out preserves original installer menu retirement semantics', code == 0 and not menu_link.exists())
    record('synthetic parent descriptors and external data unchanged',
        directory_sddl(unsafe_parent) == unsafe_before and directory_sddl(safe_parent) == safe_before and sha(sentinel) == sentinel_sha)
    assert sha(source) == source_sha
    result = {'source_base': '2107e5cffc787705dfbbb495995655ebd504dedd', 'installer_script_sha256': source_sha,
        'compiler_sha256': sha(compiler), 'cases': records, 'unsafe_parent_initial_sddl': unsafe_before,
        'test_scope_only': True, 'inert_payload_never_executed': True, 'real_menu_registry_profiles_untouched': True,
        'existing_machine_acls_unchanged': True, 'ui_profile_checkbox_not_physically_exercised': True,
        'old_uninstall_log_behavior': 'Unchanged Inno ownership: opt-out update does not edit prior menu entries; later uninstall removes entries owned by earlier menu-enabled install.'}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': len(records), 'result': str(out / 'result.json')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
