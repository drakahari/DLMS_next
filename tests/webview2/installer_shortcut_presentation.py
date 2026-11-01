"""Three compiled checkbox mappings; inert TestScope, no user integration."""
from pathlib import Path
import argparse
import json
import subprocess
from tests.webview2.installer_menu_policy import sha
from tests.webview2.installer_parent_probe import fresh_scope

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    args = parser.parse_args()
    out = fresh_scope(args.output)
    out.mkdir(mode=0o700)
    payload = out / 'inert'
    payload.mkdir(mode=0o700)
    (payload / 'DLMS-Desktop-WebView2.exe').write_bytes(b'INERT NEVER EXECUTED\n')
    source = ROOT / 'package_windows_webview2/installer.iss'
    with (out / 'compile.log').open('w') as log:
        subprocess.run([str(args.compiler), '--no-ide-signtools', '/DTestScope=1',
                        '/DTestDataRoot=' + str(out / 'absent-data'),
                        '/DPayload=' + str(payload), '/DRelease=presentation-check',
                        '/DOutputRoot=' + str(out), str(source)],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
    exe, = out.glob('*.exe')
    reader = out / 'read-link.ps1'
    reader.write_text('''param([string]$Path)
$s=New-Object -ComObject WScript.Shell
$l=$s.CreateShortcut($Path)
@{target=$l.TargetPath;directory=$l.WorkingDirectory;arguments=$l.Arguments}|ConvertTo-Json -Compress
''', encoding='utf-8-sig')

    def link(path):
        assert path.is_relative_to(out) and path.is_file()
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                                 '-File', str(reader), '-Path', str(path)],
                                capture_output=True, text=True, check=True, timeout=20)
        return json.loads(result.stdout)

    rows = []
    for name, tasks, menu, desktop in (
            ('default', None, True, False),
            ('unchecked', '', False, False),
            ('desktop-selected', 'startmenu,desktopicon', True, True)):
        app = out / name
        app.mkdir(mode=0o700)
        command = [str(exe), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                   '/DIR=' + str(app), '/LOG=' + str(out / (name + '.log'))]
        if tasks is not None:
            command.append('/TASKS=' + tasks)
        assert subprocess.run(command, timeout=60).returncode == 0
        paths = {
            'folder': app / 'Launch DLMS Desktop.lnk',
            'menu': app / 'synthetic-menu/DLMS Desktop.lnk',
            'uninstall': app / 'synthetic-menu/Uninstall DLMS Desktop.lnk',
            'desktop': app / 'synthetic-desktop/DLMS Desktop.lnk',
        }
        assert paths['folder'].is_file()
        assert paths['menu'].is_file() == menu
        assert paths['uninstall'].is_file() == menu
        assert paths['desktop'].is_file() == desktop
        version = app / 'versions/presentation-check'
        expected = dict(target=str(version / 'DLMS-Desktop-WebView2.exe'),
                        directory=str(version), arguments='--profile default')
        for purpose in ('folder', 'menu', 'desktop'):
            if paths[purpose].exists():
                assert link(paths[purpose]) == expected
        if menu:
            uninstall = link(paths['uninstall'])
            assert uninstall['target'] == str(app / 'uninstall/unins000.exe')
            assert uninstall['arguments'] == ''
        rows.append(dict(case=name, menu=menu, desktop=desktop, passed=True,
                         exact_targets_and_arguments_verified=True))
    result = dict(installer_source_sha256=sha(source), cases=rows,
                  inert_payload_never_executed=True, isolated_variant_only=True,
                  graphical_checkbox_clicks_tested=False, application_or_data_workflows_retested=False)
    (out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
