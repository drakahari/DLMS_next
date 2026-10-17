"""Run a fresh task-owned full DLMS fixture for one physical Mac walkthrough.

No arguments are needed. --check performs a finite startup smoke check only.
Never launches an app/browser, installs, downloads, reuses data or changes host
security. Ctrl-C or the 15-minute deadline stops only this exact service child.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--check', action='store_true', help='startup smoke check; exit within 10 seconds')
    options = parser.parse_args(argv)
    if sys.platform != 'darwin':
        raise SystemExit('This bounded walkthrough fixture requires the prepared Mac.')
    from tools.macos_qualify_candidate import candidate_interpreter
    candidate_interpreter(Path(__file__).resolve())
    from tests.macos.normal_package import SameOrigin
    from desktop import macos_processes as native
    from desktop.macos_paths import real_home
    cache = real_home() / '.cache/dlms-desktop-macos-candidate'
    base = cache / 'walkthrough-service'
    for path in (cache.parent, cache, base):
        if path.is_symlink() or (path.exists() and (not path.is_dir() or path.stat().st_uid != os.getuid()
                                                  or path.stat().st_mode & 0o022)):
            raise SystemExit('Unsafe walkthrough evidence directory; preserve it for inspection.')
        path.mkdir(mode=0o700, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='service-', dir=base))
    def write_json(path, value):
        temporary = path.with_suffix('.new')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    write_json(root / 'synthetic-service.json', {'kind': 'mac-normal-server-fixture', 'version': 1})
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('DLMS_', 'QUIZAPP_', 'QT_', 'QTWEBENGINE_', 'DYLD_'))
                   and key not in {'PYTHONPATH', 'PYTHONHOME'}}
    for key, relative in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'xdg/config'), ('XDG_CACHE_HOME', 'xdg/cache'),
                          ('XDG_DATA_HOME', 'xdg/data'), ('TMPDIR', 'tmp')):
        directory = root / relative
        directory.mkdir(mode=0o700, parents=True)
        environment[key] = str(directory)
    environment['TMP'] = environment['TEMP'] = environment['TMPDIR']
    service = reserved = log = None
    state = {'kind': 'bounded-physical-walkthrough-fixture', 'status': 'starting',
             'synthetic_only': True, 'root': str(root), 'fixture': 'tests/browser/_server.py',
             'maximum_seconds': 10 if options.check else 900}
    # Reserve five seconds for exact-child TERM/KILL cleanup so the service
    # lifetime remains bounded even when startup or normal termination stalls.
    deadline = time.monotonic() + (5 if options.check else 895)
    result = 1
    try:
        reserved = socket.socket()
        reserved.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        reserved.bind(('127.0.0.1', 0))
        reserved.listen(128)
        port = reserved.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        environment.update(QUIZAPP_DATA_DIR=str(root / 'data'), DLMS_NO_BROWSER='1',
            DLMS_BROWSER_TEST_BIND_HOST='127.0.0.1', DLMS_BROWSER_TEST_PORT=str(port),
            DLMS_MAC_QUALIFY_SERVER_ROOT=str(root), DLMS_MAC_QUALIFY_SERVER_FD=str(reserved.fileno()))
        log = os.fdopen(os.open(root / 'service.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb', buffering=0)
        service = subprocess.Popen([sys.executable, '-m', 'tests.macos.normal_server', '--server-worker'],
            cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            close_fds=True, pass_fds=(reserved.fileno(),), start_new_session=True)
        reserved.close(); reserved = None
        found = native.identity(service.pid)
        state.update(origin=origin, pid=found['pid'], start=found['start'], unique=found['unique'])
        opener = build_opener(ProxyHandler({}), SameOrigin(origin))
        ready = False
        startup_deadline = min(deadline, time.monotonic() + 30)
        while time.monotonic() < startup_deadline:
            if service.poll() is not None:
                raise RuntimeError('Synthetic fixture exited during startup; preserve its service.log')
            try:
                with opener.open(Request(origin + '/library', headers={'User-Agent': 'DLMS-Mac-walkthrough-readiness'}), timeout=.5) as response:
                    page = response.read()
                ready = b'Browser Critical Workflow' in page and b'Browser Companion' in page
                if ready:
                    break
            except (OSError, URLError):
                pass
            time.sleep(.1)
        if not ready:
            raise TimeoutError('Synthetic fixture did not reach verified readiness in time')
        state['status'] = 'ready'
        write_json(root / 'SERVICE.json', state)
        print('Verified synthetic DLMS Server origin: ' + origin, flush=True)
        print('Fresh private fixture evidence: ' + str(root), flush=True)
        if options.check:
            print('Startup smoke check passed; stopping this exact service now.', flush=True)
            result = 0
        else:
            print('Use only that exact origin in the candidate. No application/browser was opened.', flush=True)
            print('Ctrl-C stops this task-owned service; automatic stop after 15 minutes. Data is preserved.', flush=True)
            while time.monotonic() < deadline:
                if service.poll() is not None:
                    raise RuntimeError('Synthetic fixture stopped before the walkthrough deadline')
                time.sleep(min(.5, max(0, deadline - time.monotonic())))
            state['stop_reason'] = '15-minute deadline'
            result = 0
    except KeyboardInterrupt:
        state['stop_reason'] = 'owner Ctrl-C'
        result = 0
    except Exception as exc:
        state['error'] = type(exc).__name__ + ': ' + str(exc)
        print('Walkthrough fixture stopped: ' + state['error'], file=sys.stderr, flush=True)
    finally:
        if reserved is not None:
            reserved.close()
        if service is not None:
            if service.poll() is None:
                # This remains our unreaped direct Popen child. No group-wide
                # signal, process search, unknown-PID kill or security bypass.
                service.terminate()
                try:
                    service.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    service.kill()
                    service.wait(timeout=2)
            state['child_exit_code'] = service.returncode
            state['exact_service_child_stopped'] = service.poll() is not None
        if log is not None:
            log.close()
        state['status'] = 'stopped' if result == 0 else 'error'
        write_json(root / 'SERVICE.json', state)
        print('Service ' + state['status'] + '; fresh synthetic data and evidence retained at ' + str(root), flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
