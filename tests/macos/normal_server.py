"""Bounded normal-package Server checks with the exact synthetic browser fixture.

No renderer instrumentation, AX, host input, production service or stored login
is used. Server warning controls remain physical acceptance. Forced test teardown
is explicitly recorded and is never called successful normal Server shutdown.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
import traceback
import uuid
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from desktop import macos_processes as native
from desktop.macos_paths import MARKER, prepare_root, real_home
from tests.macos.normal_package import Client, children, database_snapshot, fixtures_checked, live, native_quit_request, require

PROFILE = 'macserver'


def worker():
    """Wrap only the exact tracked full fixture and the acquired task socket."""
    root = Path(os.environ['DLMS_MAC_QUALIFY_SERVER_ROOT'])
    cache = real_home() / '.cache/dlms-desktop-macos-candidate'
    allowed = ((ROOT / '.gate1/macos').resolve(), (cache / 'qualification-data').resolve(),
               (cache / 'walkthrough-service').resolve())
    require(root.is_absolute() and any(root.resolve().is_relative_to(parent) and root.resolve() != parent for parent in allowed)
            and not any(part.is_symlink() for part in (root, *root.parents)), 'Unsafe synthetic service root')
    marker = json.loads((root / 'synthetic-service.json').read_text())
    require(marker == {'kind': 'mac-normal-server-fixture', 'version': 1}, 'Synthetic service marker differs')
    socket_fd = int(os.environ['DLMS_MAC_QUALIFY_SERVER_FD'])
    os.set_inheritable(socket_fd, False)
    inherited = socket.socket(fileno=socket_fd)
    port = int(os.environ['DLMS_BROWSER_TEST_PORT'])
    require(inherited.getsockname() == ('127.0.0.1', port), 'Service socket is not the acquired task endpoint')
    from tests.browser import _server as fixture
    original_app = fixture.dlms.app.wsgi_app
    events = root / 'requests.jsonl'
    fd = os.open(events, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
    os.close(fd)

    def observed(environ, start_response):
        agent = environ.get('HTTP_USER_AGENT', '')
        cookie = environ.get('HTTP_COOKIE', '')
        record = {'path': environ.get('PATH_INFO'), 'method': environ.get('REQUEST_METHOD'),
                  'renderer': 'Chrome/' in agent or 'QtWebEngine/' in agent,
                  'document': environ.get('HTTP_SEC_FETCH_DEST') == 'document',
                  'local_desktop_credentials': any(key.startswith('HTTP_X_DLMS_DESKTOP') for key in environ),
                  'synthetic_cookie_present': 'dlms_mac_qualify=synthetic-server-cookie' in cookie}
        output = os.open(events, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            os.write(output, (json.dumps(record, separators=(',', ':')) + '\n').encode())
        finally:
            os.close(output)

        def response(status, headers, exc_info=None):
            # Ordinary server-side persistent synthetic cookie; DLMS page bytes
            # remain unchanged, and no native bridge or renderer JS is added.
            headers = list(headers)
            if environ.get('PATH_INFO') == '/' and status.startswith('200'):
                headers.append(('Set-Cookie', 'dlms_mac_qualify=synthetic-server-cookie; Max-Age=3600; Path=/; SameSite=Lax'))
            return start_response(status, headers, exc_info)
        return original_app(environ, response)

    fixture.dlms.app.wsgi_app = observed
    factory = fixture.make_server
    def inherited_server(host, selected_port, application, **kwargs):
        require(host == '127.0.0.1' and selected_port == port, 'Fixture changed its task-owned bind endpoint')
        return factory(host, selected_port, application, fd=socket_fd, **kwargs)
    fixture.make_server = inherited_server
    fixture.main()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--server-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.server_worker:
        return worker()
    require(all((args.app, args.data_root, args.fixtures, args.output)), 'Supply --app --data-root --fixtures --output')
    report = {'kind': 'normal-macos-app-full-synthetic-server', 'status': 'error', 'checks': {},
              'unqualified': ['physical native mode-menu configuration/switching', 'Server warning appearance/default/buttons',
                              'physical Cmd-Q', 'Server Study/Exam workflows', 'native Settings backup/restore/reset'],
              'fixture': 'tests/browser/_server.py'}
    process = service = None
    app_log = service_log = None
    launcher_identity = None
    nonce = None
    backend = None
    tracked = []
    deadline = time.monotonic() + 170
    code = 1
    try:
        require(sys.platform == 'darwin', 'Requires native macOS')
        require(args.output.is_absolute() and args.output.resolve().is_relative_to((ROOT / '.gate1/macos').resolve()), 'Evidence must be under .gate1/macos')
        require(not args.output.exists() and not args.output.is_symlink(), 'Refusing existing evidence')
        args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fixtures_checked(args.fixtures)
        root = prepare_root(args.data_root, create=False)
        require({path.name for path in root.iterdir()} == {MARKER}, 'Only a fresh marked synthetic root is accepted')
        executable = args.app / 'Contents/MacOS/DLMS-Desktop'
        require(args.app.is_absolute() and args.app.suffix == '.app' and not args.app.is_symlink()
                and executable.is_file() and not executable.is_symlink(), 'Supply the real normal app bundle')
        profile = root / 'profiles' / PROFILE
        service_root = root / 'full-synthetic-server'
        service_root.mkdir(mode=0o700)
        (service_root / 'synthetic-service.json').write_text(json.dumps({'kind': 'mac-normal-server-fixture', 'version': 1}))
        report.update(app=str(args.app), data_root=str(root), profile=PROFILE)
        app_log = os.fdopen(os.open(args.output.with_suffix('.launcher.log'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb', buffering=0)
        service_log = os.fdopen(os.open(args.output.with_suffix('.service.log'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb', buffering=0)
        environment = {key: value for key, value in os.environ.items() if not key.startswith(('DLMS_', 'QUIZAPP_', 'QT_', 'QTWEBENGINE_', 'DYLD_'))
                       and key not in {'PYTHONPATH', 'PYTHONHOME'}}
        command = [str(executable), '--profile', PROFILE, '--data-root', str(root)]
        def wait(operation, seconds=30):
            end = min(time.monotonic() + seconds, deadline)
            while time.monotonic() < end:
                try:
                    result = operation()
                    if result:
                        return result
                except (OSError, ValueError, KeyError, URLError):
                    pass
                time.sleep(.1)
            raise TimeoutError('Normal Server check exceeded its bounded wait')

        def launch():
            nonlocal process, launcher_identity, backend, nonce, tracked
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=app_log, stderr=subprocess.STDOUT, start_new_session=True)
            launcher_identity = native.identity(process.pid)
            backend = nonce = None
            tracked = []

        def descendants():
            found, pending = [], [process.pid]
            while pending:
                for pid in children(pending.pop()):
                    try:
                        child = native.identity(pid)
                    except ProcessLookupError:
                        continue
                    if not any(item['pid'] == pid for item in found):
                        found.append(child)
                        pending.append(pid)
            return found

        def capture_helpers():
            nonlocal tracked, nonce
            found = descendants()
            for child in found:
                if not any(native._same_birth(child, prior) for prior in tracked):
                    tracked.append(child)
                try:
                    _arguments, values = native.arguments_environment(child['pid'])
                    env = dict(value.split(b'=', 1) for value in values if b'=' in value)
                    candidate = env.get(b'DLMS_DESKTOP_NONCE', b'').decode('ascii')
                    if env.get(b'DLMS_MACOS_DATA_ROOT') == str(root).encode() and re.fullmatch('[0-9a-f]{64}', candidate):
                        nonce = candidate
                except (OSError, ValueError):
                    continue
            return found

        def no_local_backend():
            require(process.poll() is None, 'Normal Server app exited')
            for child in capture_helpers():
                try:
                    arguments, _environment = native.arguments_environment(child['pid'])
                except ProcessLookupError:
                    continue
                require(not ('--desktop-worker' in arguments and 'backend' in arguments), 'Server started a Local backend')
            return True

        def local_ready():
            nonlocal backend, nonce
            require(process.poll() is None, 'Normal Local app exited before readiness')
            for pid in children(process.pid):
                arguments, values = native.arguments_environment(pid)
                if '--desktop-worker' not in arguments or 'backend' not in arguments:
                    continue
                env = dict(value.split(b'=', 1) for value in values if b'=' in value)
                require(env.get(b'DLMS_DESKTOP_PARENT_PID') == str(process.pid).encode(), 'Wrong Local backend parent')
                found = native.identity(pid)
                require(Path(found['image']).resolve() == executable.resolve(), 'Wrong Local backend executable')
                nonce = env[b'DLMS_DESKTOP_NONCE'].decode('ascii')
                manifest = json.loads((profile / 'desktop-profile.json').read_text())
                client = Client(manifest['port'], nonce)
                require(client.request('/_desktop/ready', raw=True)['status'] == 200, 'Wrong Local readiness')
                backend = found
                return client, manifest
            return None

        def cleanup(*, normal=False):
            nonlocal process
            require(process is not None, 'No task-owned launcher')
            capture_helpers()
            request = native_quit_request(launcher_identity, executable)
            forced = False
            try:
                result = process.wait(timeout=min(20 if normal else 5, max(1, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                require(not normal, 'Native Local Quit did not complete normally')
                forced = True
                native.signal_identity(launcher_identity, signal.SIGTERM)
                try:
                    result = process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()  # exact unreaped direct child only
                    result = process.wait(timeout=3)
            if nonce:
                native.reap(launcher_identity['pid'], nonce)
                if backend is not None:
                    native.reap(backend['group'], nonce)
            for child in tracked:
                if live(child):
                    native.signal_identity(child, signal.SIGTERM)
            wait(lambda: not any(live(child) for child in tracked), 4)
            require(not normal or result == 0, 'Local native Quit returned failure')
            return {'native_quit': request, 'exit_code': result, 'forced_test_teardown': forced,
                    'normal_server_shutdown_qualified': False, 'tracked_helpers_remaining': 0}

        launch()
        client, manifest = wait(local_ready, 40)
        client.request('/')
        client.multipart('/process', {'quiz_title': 'Mac Local isolation sentinel'},
                         [('file', args.fixtures / 'neutral-quiz.txt', 'text/plain')])
        database = profile / 'backend/results.db'
        original = database_snapshot(database)
        require(len(original['quizzes']) == 1, 'Synthetic Local seed differs')
        report['checks']['local_seed_native_quit'] = cleanup(normal=True)
        original_manifest = (profile / 'desktop-profile.json').read_bytes()
        def local_unchanged():
            require(database_snapshot(database) == original, 'Server changed exact Local rows')
            require((profile / 'desktop-profile.json').read_bytes() == original_manifest, 'Server changed Local identity/origin')
            fd = os.open(profile / 'backend-writer.lock', os.O_RDONLY | os.O_NOFOLLOW)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
            return True
        shell = root / 'shell' / PROFILE
        configuration = shell / 'mode.json'
        identifier = str(uuid.uuid4())
        def save_mode(mode, origin):
            value = {'version': 1, 'profile': PROFILE, 'mode': mode,
                     'server': {'id': identifier, 'label': 'Mac task-owned full DLMS Server', 'origin': origin, 'private_http': True}}
            # Validate the tracked pure schema without importing app/controller.
            from desktop.server_mode import _validate_config
            _validate_config(PROFILE, value)
            temporary = configuration.with_name('qualification-mode.tmp')
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as output:
                json.dump(value, output)
                output.flush(); os.fsync(output.fileno())
            os.replace(temporary, configuration)

        reserved = socket.socket()
        reserved.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        reserved.bind(('127.0.0.1', 0))
        reserved.listen(128)
        port = reserved.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        server_environment = environment.copy()
        for key, relative in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'xdg/config'), ('XDG_CACHE_HOME', 'xdg/cache'),
                              ('XDG_DATA_HOME', 'xdg/data'), ('TMPDIR', 'tmp')):
            directory = service_root / relative
            directory.mkdir(mode=0o700, parents=True)
            server_environment[key] = str(directory)
        server_environment.update(QUIZAPP_DATA_DIR=str(service_root / 'data'), DLMS_NO_BROWSER='1',
            DLMS_BROWSER_TEST_BIND_HOST='127.0.0.1', DLMS_BROWSER_TEST_PORT=str(port),
            DLMS_MAC_QUALIFY_SERVER_ROOT=str(service_root), DLMS_MAC_QUALIFY_SERVER_FD=str(reserved.fileno()))
        service = subprocess.Popen([sys.executable, '-m', 'tests.macos.normal_server', '--server-worker'],
            cwd=ROOT, env=server_environment, pass_fds=(reserved.fileno(),), close_fds=True,
            stdin=subprocess.DEVNULL, stdout=service_log, stderr=subprocess.STDOUT, start_new_session=True)
        reserved.close()
        opener = build_opener(ProxyHandler({}))
        def service_ready():
            require(service.poll() is None, 'Full synthetic fixture service exited')
            with opener.open(Request(origin + '/library', headers={'User-Agent': 'DLMS-Mac-server-fixture-probe'}), timeout=1) as response:
                body = response.read()
            return b'Browser Critical Workflow' in body and b'Browser Companion' in body
        wait(service_ready, 35)
        save_mode('server', origin)
        events = service_root / 'requests.jsonl'
        def requests():
            return [json.loads(line) for line in events.read_text().splitlines() if line]
        def rendered(since):
            no_local_backend()
            recent = requests()[since:]
            documents = [item for item in recent if item['renderer'] and item['document'] and item['path'] == '/']
            assets = [item for item in recent if item['renderer'] and item['path'].startswith('/static/')]
            return documents and assets
        first = len(requests())
        launch()
        wait(lambda: rendered(first), 35)
        time.sleep(1)
        no_local_backend()
        storage = root / 'server-profiles' / identifier / 'web/storage'
        require(storage.is_dir() and storage != profile / 'web/storage', 'Server storage is not separated')
        local_unchanged()
        all_requests = requests()[first:]
        require(not any(item['local_desktop_credentials'] for item in all_requests), 'Local Desktop token/nonce reached Server')
        duplicate = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=app_log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            require(duplicate.wait(timeout=12) == 0, 'Duplicate Server launch did not authenticated-focus/exit')
        finally:
            if duplicate.poll() is None:
                duplicate.terminate(); duplicate.wait(timeout=4)
        require(process.poll() is None, 'Duplicate disturbed original Server')
        report['checks']['normal_server_startup_isolation'] = {'passed': True, 'actual_renderer_document_and_assets': True,
             'local_backend_absent': True, 'local_rows_origin_unchanged': True, 'separate_server_storage': True,
             'no_local_desktop_credentials_on_server': True, 'duplicate_authenticated_focus_exit': True,
             'normal_package_uninstrumented': True}
        report['checks']['server_first_quit_teardown'] = cleanup()
        reopen_index = len(requests())
        launch()
        wait(lambda: rendered(reopen_index), 30)
        local_unchanged()
        reopened_documents = [item for item in requests()[reopen_index:]
                              if item['renderer'] and item['document'] and item['path'] == '/']
        cookie_observed = any(item['synthetic_cookie_present'] for item in reopened_documents)
        previous_forced = report['checks']['server_first_quit_teardown']['forced_test_teardown']
        if not previous_forced:
            require(cookie_observed, 'Persistent cookie absent after an orderly Server close')
        else:
            report['unqualified'].append('Server cookie persistence after an orderly native close; prior test teardown was forced')
        report['checks']['server_reopen'] = {
            'passed': True, 'scope': 'normal renderer document/assets and unchanged Local data',
            'same_server_identity_storage': True,
            'actual_renderer_document_and_assets': True,
            'cookie_persistence_observation': {
                'present_on_reopened_document': cookie_observed,
                'previous_teardown_forced': previous_forced,
                'orderly_profile_flush_confirmed': not previous_forced,
                'qualified': cookie_observed and not previous_forced,
                'result': ('unresolved_after_forced_teardown' if previous_forced
                           else 'passed_after_orderly_close')}}
        report['checks']['server_reopen_quit_teardown'] = cleanup()
        # End the exact service before testing a cold Server outage. No request
        # is sent to any other endpoint and an occupied port is never killed.
        service.terminate(); service.wait(timeout=5)
        launch()
        def owns_current_shell():
            descriptor = json.loads((root / 'shell' / PROFILE / 'instance-owner.json').read_text())
            return (descriptor.get('pid') == process.pid
                    and descriptor.get('start_ticks') == launcher_identity['start'])
        wait(owns_current_shell, 10)
        time.sleep(2)
        no_local_backend()
        require(json.loads(configuration.read_text())['mode'] == 'server', 'Unavailable Server selected Local fallback')
        local_unchanged()
        report['checks']['cold_outage_no_local_fallback'] = {'passed': True, 'local_backend_absent': True,
                                                            'saved_server_mode_retained': True, 'local_rows_unchanged': True,
                                                            'visual_outage_feedback_unqualified': True}
        report['checks']['outage_quit_teardown'] = cleanup()
        save_mode('local', origin)
        launch()
        local, reopened_manifest = wait(local_ready, 35)
        require(reopened_manifest == manifest and database_snapshot(database) == original,
                'Explicit stopped-config Local reopen lost exact rows/origin')
        report['checks']['local_reopen_after_server'] = {'passed': True, 'exact_local_rows_origin_preserved': True,
                                                        'mode_menu_switch_unqualified': True}
        report['checks']['final_local_native_quit'] = cleanup(normal=True)
        require(not any(item['local_desktop_credentials'] for item in requests()), 'Local Desktop credentials reached Server')
        report['status'] = 'pass'
        code = 0
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        traceback.print_exc()
    finally:
        if process is not None:
            try:
                # A failed startup may never have registered with AppKit.
                if launcher_identity is not None and live(launcher_identity):
                    native.signal_identity(launcher_identity, signal.SIGTERM)
                try: process.wait(timeout=4)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
                if nonce:
                    native.reap(launcher_identity['pid'], nonce)
                    if backend is not None: native.reap(backend['group'], nonce)
                for child in tracked:
                    if live(child): native.signal_identity(child, signal.SIGKILL)
            except Exception as exc:
                report['cleanup_error'] = type(exc).__name__ + ': ' + str(exc)
        if service is not None and service.poll() is None:
            service.terminate()
            try: service.wait(timeout=4)
            except subprocess.TimeoutExpired: service.kill(); service.wait(timeout=3)
        if app_log: app_log.close()
        if service_log: service_log.close()
        if (args.output.is_absolute() and args.output.resolve().is_relative_to((ROOT / '.gate1/macos').resolve())
                and args.output.parent.is_dir() and not args.output.exists() and not args.output.is_symlink()):
            with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
                json.dump(report, output, indent=2); output.write('\n')
    print(json.dumps({'status': report['status'], 'output': str(args.output), 'error': report.get('error')}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
