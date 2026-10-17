"""Bounded native qualification of this private synthetic-data candidate.

No downloads, installs, production contacts, desktop-wide input or security
changes. Uses new task roots, app-local Qt tests and the normal packaged app.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def candidate_interpreter(entry_script=None):
    """Use only this checkout's offline-created task environment.

    No virtualenv symlink inside Documents: its FileProvider can rename the
    link and mark dependencies hidden, making Qt plugin enumeration fail.
    """
    if entry_script is not None and Path(entry_script).resolve() != ROOT / 'tools/macos_walkthrough_server.py':
        raise SystemExit('Explicit entry is restricted to the bounded walkthrough service helper.')
    import pwd
    cache = Path(pwd.getpwuid(os.getuid()).pw_dir) / '.cache/dlms-desktop-macos-candidate'
    pointer = cache / 'ENVIRONMENT.json'
    if pointer.is_symlink() or not pointer.is_file() or pointer.stat().st_size > 16384:
        raise SystemExit('Verified private cache environment pointer is unavailable.')
    record = json.loads(pointer.read_text())
    environment = Path(record['environment'])
    if (record.get('repository') != str(ROOT) or environment.parent != cache / 'environments'
            or environment.is_symlink() or not environment.is_dir()
            or environment.stat().st_uid != os.getuid() or environment.stat().st_mode & 0o077):
        raise SystemExit('Private cache environment identity differs; preserve it for inspection.')
    actual = hashlib.sha256((ROOT / '.gate1/macos/wheelhouse.json').read_bytes()).hexdigest()
    if actual != record.get('download_inventory_sha256'):
        raise SystemExit('Candidate environment download inventory changed.')
    python = environment / 'bin/python'
    if not python.is_file():
        raise SystemExit('Candidate cache interpreter is missing.')
    if Path(sys.prefix).resolve() != environment.resolve():
        selected_entry = Path(entry_script).resolve() if entry_script is not None else Path(__file__).resolve()
        os.execv(str(python), [str(python), str(selected_entry), *sys.argv[1:]])
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('all', 'normal-app', 'normal-server', 'source-import', 'source-chooser', 'source-server', 'management', 'source'), default='all',
                        help='Bounded fresh-root diagnostic scopes do not create a DMG.')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('Run this bounded qualification helper on the Mac.')
    candidate_interpreter()
    from package_macos.build import app_inventory, create_dmg
    from desktop.macos_paths import prepare_root, real_home
    pointer = json.loads((ROOT / '.gate1/macos/CANDIDATE.json').read_text())
    app = Path(pointer['app'])
    stage = Path(pointer['stage'])
    cache = real_home() / '.cache/dlms-desktop-macos-candidate'
    if not stage.resolve().is_relative_to(cache.resolve()) or app != stage / 'dist/DLMS Desktop Candidate.app':
        raise SystemExit('Candidate path does not match the dedicated build cache.')
    manifest = app_inventory(app)
    actual = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    if actual != pointer['app_manifest_sha256']:
        raise SystemExit('Packaged app changed; preserve it for inspection, do not run.')
    # Establish this session's local socket access once; never retry a denied
    # permission or contact a remote service to diagnose a local policy denial.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
    with tempfile.TemporaryDirectory(prefix='dlms-native-probe-', dir='/private/tmp') as directory:
        with socket.socket(socket.AF_UNIX) as probe:
            probe.bind(str(Path(directory) / 'socket'))
    fixtures = real_home() / 'Documents/DLMS-Mac-walkthrough-20261017'
    for line in (fixtures / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split(maxsplit=1)
        path = fixtures / name.removeprefix('*')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit('Visible synthetic fixture changed: ' + str(path))
    base = ROOT / '.gate1/macos/qualify'
    for part in (ROOT / '.gate1', ROOT / '.gate1/macos', base):
        if part.is_symlink() or (part.exists() and (not part.is_dir()
                or part.stat().st_uid != os.getuid() or part.stat().st_mode & 0o022)):
            raise SystemExit('Unsafe qualification evidence directory; preserve it for inspection.')
    base.mkdir(mode=0o700, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix='run-', dir=base))
    profile = 'macqual' + secrets.token_hex(4)
    # Documents metadata services can change even newly written private file
    # ctimes/visibility. Exercise native storage outside that provider, as the
    # normal app does; keep old Documents evidence and profiles untouched.
    data_base = cache / 'qualification-data'
    if data_base.is_symlink() or (data_base.exists() and (not data_base.is_dir()
            or data_base.stat().st_uid != os.getuid() or data_base.stat().st_mode & 0o077)):
        raise SystemExit('Unsafe qualification data cache; preserve it for inspection.')
    data_base.mkdir(mode=0o700, exist_ok=True)
    data_root = data_base / run_root.name
    data_root.mkdir(mode=0o700)
    (run_root / 'DATA-LOCATION.json').write_text(json.dumps({'data_root': str(data_root)}) + '\n')
    source = prepare_root(data_root / 'source-data')
    normal = prepare_root(data_root / 'normal-data')
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(('DLMS_', 'QUIZAPP_', 'QTWEBENGINE_', 'QT_', 'DYLD_')) or key in {'PYTHONPATH', 'PYTHONHOME'}:
            environment.pop(key, None)
    environment.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR='/private/tmp')
    records = []

    def execute(label, arguments, timeout=300, *, offscreen=False):
        log = run_root / (label + '.log')
        print('RUN', label, flush=True)
        env = environment.copy()
        if offscreen:
            env['QT_QPA_PLATFORM'] = 'offscreen'
        started = time.monotonic()
        with log.open('x') as output:
            process = subprocess.Popen(arguments, cwd=ROOT, env=env, stdout=output,
                                       stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Interrupt the exact unreaped task child first so its finally
                # block can close the owned window/backend and retain evidence.
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                code = 124
        records.append({'check': label, 'returncode': code,
                        'seconds': round(time.monotonic() - started, 2), 'log': str(log)})
        (run_root / 'RESULTS.json').write_text(json.dumps(records, indent=2) + '\n')
        if code:
            print(log.read_text()[-6000:], flush=True)
            raise SystemExit('Stopped at ' + label + '; evidence preserved at ' + str(run_root))

    if args.scope == 'all':
        for name in ('test_processes', 'test_paths_filesystem', 'test_file_selection', 'test_publication', 'test_application_browser'):
            execute(name, [sys.executable, '-m', 'unittest', 'tests.macos.' + name, '-q'], offscreen=name == 'test_application_browser')
    if args.scope in {'all', 'normal-app'}:
        execute('normal-app', [sys.executable, '-m', 'tests.macos.normal_package', '--app', str(app),
                          '--data-root', str(normal), '--fixtures', str(fixtures),
                          '--output', str(run_root / 'normal-app.json')], timeout=600)
    if args.scope == 'normal-app':
        print('Normal-package HTTP/native-Quit checks complete. Evidence:', run_root, flush=True)
        print('This partial run does not qualify native UI workflows or create a DMG.', flush=True)
        return 0
    if args.scope in {'all', 'normal-server'}:
        server = prepare_root(data_root / 'server-data')
        execute('normal-server', [sys.executable, '-m', 'tests.macos.normal_server', '--app', str(app),
                '--data-root', str(server), '--fixtures', str(fixtures),
                '--output', str(run_root / 'normal-server.json')], timeout=180)
    if args.scope == 'normal-server':
        print('Normal-package synthetic Server checks complete. Evidence:', run_root, flush=True)
        print('This partial run does not qualify native UI workflows or create a DMG.', flush=True)
        return 0
    common = ['--data-root', str(source), '--profile', profile, '--fixtures', str(fixtures)]
    phases = {'source-import': ('import',), 'source-chooser': ('chooser',),
              'source-server': ('import',), 'management': ('import',)}.get(
        args.scope, ('import', 'reopen', 'chooser', 'ocr'))
    for phase in phases:
        execute('source-' + phase, [sys.executable, '-m', 'tests.macos.gui_candidate', *common,
                '--phase', phase, '--output', str(run_root / ('source-' + phase + '.json'))])
    management = (('server',) if args.scope == 'source-server' else
                  ('backup', 'restore', 'restore', 'reset', 'reset', 'server')
                  if args.scope in {'all', 'source', 'management'} else ())
    for index, phase in enumerate(management):
        execute(f'management-{index}-{phase}', [sys.executable, '-m', 'tests.macos.gui_management', *common,
                '--phase', phase, '--output', str(run_root / f'management-{index}-{phase}.json')])
    if args.scope != 'all':
        print('Diagnostic scope complete:', args.scope, 'Evidence:', run_root, flush=True)
        print('This partial run does not qualify the complete candidate or create a DMG.', flush=True)
        return 0
    image = stage / 'DLMS-Desktop-macos-arm64-private.dmg'
    if not image.exists():
        create_dmg(stage, app)
    else:
        sums = stage / 'SHA256SUMS'
        if not sums.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() + '  ' + image.name + '\n' != sums.read_text():
            raise SystemExit('Existing DMG is unverified; preserve it for inspection.')
        subprocess.run(['/usr/bin/hdiutil', 'verify', str(image)], check=True)
    print('Automated native checks complete. Evidence:', run_root, flush=True)
    print('Private candidate:', app, '\nDMG:', image, flush=True)
    print('Physical native-sheet/focus/Cmd-Q/default-browser walkthrough remains separate.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
