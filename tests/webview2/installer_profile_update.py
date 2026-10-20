"""Focused real-shortcut update qualification, compile-time TestScope only.

No normal Start menu, registry or default data is used. Shortcut launches are
inspected, then the normal executable is invoked with those profile arguments
and an explicit disposable data root; never ShellExecute a default-data link.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from package_windows_webview2.qualify_installer import (
    WORK, ROOT, candidate_inventory, digest, fresh_scope, invoke, tree, variant,
)


def copy_durable_fixture(workflow, data):
    """Copy durable synthetic state, never follow browser/Windows cache links."""
    source = workflow/'Synthetic data 日本語 with spaces'
    data.mkdir(mode=0o700)
    shutil.copy2(source/'.dlms-desktop-windows-candidate.json', data)
    profile = data/'profiles/normal01'
    profile.mkdir(mode=0o700, parents=True)
    shutil.copy2(source/'profiles/normal01/desktop-profile.json', profile)
    backend = source/'profiles/normal01/backend'
    # The trusted fixture is still required to contain ordinary backend files;
    # an unexpected alias is an evidence failure, not something to dereference.
    import stat
    for item in (backend, *backend.rglob('*')):
        value = item.lstat()
        if getattr(value, 'st_file_attributes', 0) & 0x400 or not (
                stat.S_ISREG(value.st_mode) or stat.S_ISDIR(value.st_mode)):
            raise ValueError('Synthetic durable fixture contains an alias/special file')
    shutil.copytree(backend, profile/'backend')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--candidate', required=True)
    p.add_argument('--initial', type=Path, required=True)
    p.add_argument('--update', type=Path, required=True)
    p.add_argument('--initial-release', required=True)
    p.add_argument('--update-release', required=True)
    p.add_argument('--synthetic-workflow', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    inventory, expected = candidate_inventory(a.candidate)
    first = variant(a.initial, a.initial_release, inventory)
    second = variant(a.update, a.update_release, inventory)
    if a.initial_release == a.update_release:
        raise ValueError('Distinct installation releases required')
    workflow = a.synthetic_workflow.resolve(strict=True)
    if not workflow.is_relative_to(WORK.resolve()):
        raise ValueError('Only existing task-local synthetic workflow evidence')
    out = fresh_scope(a.output)
    out.mkdir(mode=0o700)
    app = out/'app'
    script = out/'shortcut.ps1'
    script.write_text('''param([string]$Request)
$a = Get-Content -LiteralPath $Request -Raw | ConvertFrom-Json
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($a.path)
if ($a.write) {
  $link.TargetPath = $a.target
  $link.WorkingDirectory = $a.directory
  $link.Arguments = $a.arguments
  $link.Save()
}
@{target=$link.TargetPath; directory=$link.WorkingDirectory;
  arguments=$link.Arguments} | ConvertTo-Json | Set-Content -LiteralPath $a.result -Encoding UTF8
''', encoding='utf-8-sig')
    counter = 0

    def link(path, *, target=None, arguments='', directory=None):
        nonlocal counter
        counter += 1
        if not path.absolute().is_relative_to(out):
            raise ValueError('No real user shortcuts')
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        request = out/f'link-request-{counter}.json'
        response = out/f'link-response-{counter}.json'
        request.write_text(json.dumps({'path':str(path), 'write':target is not None,
            'target':str(target or ''), 'directory':str(directory or ''),
            'arguments':arguments, 'result':str(response)}))
        subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
            '-NoLogo','-NoProfile','-NonInteractive','-File',str(script),'-Request',str(request)],
            check=True, capture_output=True, text=True, timeout=20)
        return json.loads(response.read_text(encoding='utf-8-sig'))

    def setup(exe, name):
        return subprocess.run([str(exe), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            '/DIR='+str(app), '/TASKS=desktopicon', '/DLMSPROFILE=normal01', '/LOG='+str(out/(name+'.log'))], timeout=120).returncode

    menu = app/'synthetic-menu/DLMS Desktop.lnk'
    desktop = app/'synthetic-desktop/DLMS Desktop.lnk'
    assert setup(first, 'initial') == 0
    old = app/'versions'/a.initial_release
    new = app/'versions'/a.update_release
    assert tree(old) == expected
    initial = link(menu)
    assert initial == {'target':str(old/'DLMS-Desktop-WebView2.exe'),
        'directory':str(old), 'arguments':'--profile normal01'}, initial
    records = [{'case':'fresh-install-explicit-named-profile', 'passed':True}]
    old_exe = old/'DLMS-Desktop-WebView2.exe'
    good = {'target':old_exe, 'directory':old, 'arguments':'--profile normal01'}
    link(menu, **good)
    link(desktop, target=old_exe, directory=old, arguments='--profile other-synthetic01')
    preserved = (menu.read_bytes(), desktop.read_bytes())
    # All negative updates must stop before creating new payload files and must
    # leave the exact old shortcut bytes/payload unchanged.
    cases = [
        ('extra-data-root', {'arguments':'--profile normal01 --data-root C:\\other'}),
        ('duplicate-profile', {'arguments':'--profile normal01 --profile other'}),
        ('invalid-profile', {'arguments':'--profile ../other'}),
        ('foreign-target', {'target':Path(os.environ['SystemRoot'])/'System32/notepad.exe'}),
        ('wrong-directory', {'directory':out}),
        ('stale-version', {'target':app/'versions/missing/DLMS-Desktop-WebView2.exe',
                           'directory':app/'versions/missing'}),
    ]
    for name, changes in cases:
        link(menu, **(good | changes))
        before = menu.read_bytes()
        assert setup(second, name) != 0, name
        assert menu.read_bytes() == before and desktop.read_bytes() == preserved[1]
        assert tree(old) == expected and not list(new.rglob('*.exe')), name
        assert 'Existing DLMS Start menu launch shortcut is invalid or unsafe' in (out/(name+'.log')).read_text(encoding='utf-8-sig')
        records.append({'case':name, 'refused':True, 'payload_and_shortcuts_unchanged':True})
    # A missing link underneath a junction must be refused before shortcut
    # creation, even though the actual link pathname does not exist yet.
    menu.unlink()
    menu.parent.rmdir()
    outside = out/'outside-menu-sentinel'
    outside.mkdir(mode=0o700)
    (outside/'sentinel.txt').write_bytes(b'unchanged')
    outside_before = tree(outside)
    from package_windows_webview2.qualify_installer import junction
    junction(menu.parent, outside)
    try:
        assert setup(second, 'missing-link-junction-parent') != 0
        assert tree(outside) == outside_before and not menu.exists()
        assert tree(old) == expected and not list(new.rglob('*.exe'))
        records.append({'case':'missing-link-junction-parent', 'refused':True,
            'outside_bytes_unchanged':True})
    finally:
        menu.parent.rmdir()
    link(menu, **good)
    assert setup(second, 'named-update') == 0
    updated = link(menu)
    updated_desktop = link(desktop)
    assert updated == {'target':str(new/'DLMS-Desktop-WebView2.exe'),
        'directory':str(new), 'arguments':'--profile normal01'}, updated
    assert updated_desktop == {'target':str(new/'DLMS-Desktop-WebView2.exe'),
        'directory':str(new), 'arguments':'--profile other-synthetic01'}, updated_desktop
    assert tree(old) == expected and tree(new) == expected
    assert setup(second, 'repeated-update') == 0
    assert link(menu) == updated and link(desktop) == updated_desktop
    # Copy only disposable prior workflow data. Keep original evidence untouched.
    data = out/'synthetic-data'
    copy_durable_fixture(workflow, data)
    before_data = tree(data)
    assert (data/'profiles/normal01').is_dir() and not (data/'profiles/default').exists()
    subprocess.run([sys.executable, '-m','tests.webview2.normal_walkthrough_launch',
        '--exe', updated['target'], '--inventory',str(inventory), '--data-root',str(data),
        '--profile', updated['arguments'].split(' ',1)[1],
        '--expected-workflow',str(workflow/'result.json'), '--output',str(out/'named-reopen')],
        cwd=ROOT, check=True, timeout=130)
    assert not (data/'profiles/default').exists()
    assert json.loads((data/'profiles/normal01/backend/config/portal.json').read_text())['theme'] == 'dark'
    records.append({'case':'named-profile-update-reopen', 'passed':True,
        'real_shortcut_target_and_arguments_verified':True, 'normal_reopens':2,
        'explicit_synthetic_root_added_for_test_safety':True,
        'desktop_profile_preserved_separately':True})
    data_before_uninstall = tree(data)
    assert invoke(app/'uninstall/unins000.exe', app, out/'uninstall.log', uninstall=True) == 0
    deadline = time.monotonic()+20
    while app.exists() and time.monotonic()<deadline:time.sleep(.1)
    assert not app.exists() and tree(data) == data_before_uninstall
    # Exercise final reviewed setup's no-existing-link path too, independently
    # from the earlier initial fixture installer.
    assert setup(second, 'final-fresh-explicit-named-profile') == 0
    assert link(menu)['arguments'] == '--profile normal01' and link(desktop)['arguments'] == '--profile normal01'
    assert invoke(app/'uninstall/unins000.exe', app, out/'fresh-uninstall.log', uninstall=True) == 0
    deadline = time.monotonic()+20
    while app.exists() and time.monotonic()<deadline:time.sleep(.1)
    assert not app.exists() and tree(data) == data_before_uninstall
    records.append({'case':'final-reviewed-fresh-install-explicit-named-profile', 'passed':True})
    result = {'passed':True, 'isolated_variant_only':True, 'real_user_integration_tested':False,
        'payload_inventory_sha256':digest(inventory), 'cases':records,
        'synthetic_data_before_reopen_files':len(before_data),
        'external_data_preserved_on_uninstall':True}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':main()
