"""Normal frozen Server outage evidence; no app hooks, native commands or OS input.

The synthetic exact-origin page navigates itself. Native child hit testing and
bounded trace observations are metadata, not a claim about displayed pixels.
Server cleanup uses this harness's retained Popen handle, not normal UI close.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from package_windows_webview2.acceptance import payload_binding
from tests.windows.normal_processes import alive, arguments, descendants, identity

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.gate1/windows-native'


class Fixture:
    def __init__(self):
        self.requests, self.observations = [], []
        self.library = threading.Event()
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def record(self, status):
                fixture.requests.append({'method': self.command, 'path': self.path, 'status': status,
                    'local_credential_header': bool(self.headers.get('X-DLMS-Desktop-Token') or self.headers.get('X-DLMS-Desktop-Nonce'))})
            def do_GET(self):
                if self.path not in ('/', '/library', '/unavailable'):
                    self.record(404); self.send_error(404); return
                status = 503 if self.path == '/unavailable' else 200
                self.record(status)
                page = 'dashboard' if self.path == '/' else 'library'
                script = ''
                if status == 200:
                    target = '/library' if page == 'dashboard' else '/unavailable'
                    delay = 400 if page == 'dashboard' else 2500
                    script = """<script>addEventListener('load',()=>{
                    fetch('/__observe',{method:'POST',headers:{'Content-Type':'application/json'},
                      body:JSON.stringify({page:PAGE,ready:document.readyState,visible:!document.hidden})})
                      .then(()=>setTimeout(()=>location.assign(TARGET),DELAY));});</script>"""
                    script = script.replace('PAGE', json.dumps(page)).replace('TARGET', json.dumps(target)).replace('DELAY', str(delay))
                body = ('<!doctype html><title>Synthetic Server outage</title><body><h1>' +
                        ('Synthetic HTTP503' if status == 503 else page) + '</h1>' + script + '</body>').encode()
                self.send_response(status); self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                if self.path != '/__observe': self.record(404); self.send_error(404); return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024: self.record(400); self.send_error(400); return
                value = json.loads(self.rfile.read(length))
                if (set(value) != {'page', 'ready', 'visible'} or value['page'] not in ('dashboard', 'library')
                        or value['ready'] != 'complete' or not isinstance(value['visible'], bool)):
                    self.record(400); self.send_error(400); return
                fixture.observations.append(value); self.record(204)
                self.send_response(204); self.send_header('Content-Length', '0'); self.end_headers()
                if value['page'] == 'library': fixture.library.set()
        self.server = ThreadingHTTPServer(('127.0.0.2', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.origin = f'http://127.0.0.2:{self.server.server_port}'
        self.thread.start(); self.stopped = False

    def stop(self):
        if self.stopped: return
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        self.stopped = True


def trace_rows(shell, excluded=()):
    paths = [path for path in (shell / 'window-events').glob('*.jsonl') if path not in excluded]
    rows = []
    for path in paths:
        data = path.read_bytes()
        if len(data) > 8 * 1024 * 1024: raise ValueError('Trace bound exceeded')
        for line in data.splitlines(keepends=True):
            if line.endswith(b'\n'): rows.append(json.loads(line))
    return paths, rows


def owned_windows(owned, host_pids):
    """Read only this process tree's HWNDs and center-child z-order."""
    user = c.WinDLL('user32', use_last_error=True)
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    enum_top = user.EnumWindows; enum_child = user.EnumChildWindows
    for method in (enum_top, enum_child): method.restype = w.BOOL
    enum_top.argtypes = [callback_type, w.LPARAM]
    enum_child.argtypes = [w.HWND, callback_type, w.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
    user.GetWindowThreadProcessId.restype = w.DWORD
    user.GetParent.argtypes = [w.HWND]; user.GetParent.restype = w.HWND
    user.IsWindowVisible.argtypes = [w.HWND]; user.IsWindowVisible.restype = w.BOOL
    user.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]; user.GetClassNameW.restype = c.c_int
    user.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]; user.GetClientRect.restype = w.BOOL
    user.ClientToScreen.argtypes = [w.HWND, c.POINTER(w.POINT)]; user.ClientToScreen.restype = w.BOOL
    user.ScreenToClient.argtypes = [w.HWND, c.POINTER(w.POINT)]; user.ScreenToClient.restype = w.BOOL
    user.ChildWindowFromPointEx.argtypes = [w.HWND, w.POINT, w.UINT]; user.ChildWindowFromPointEx.restype = w.HWND
    def pid(hwnd):
        result = w.DWORD(); user.GetWindowThreadProcessId(hwnd, c.byref(result)); return result.value
    def facts(hwnd):
        handle = int(hwnd.value or 0) if hasattr(hwnd, 'value') else int(hwnd)
        hwnd = w.HWND(handle)
        name = c.create_unicode_buffer(256); user.GetClassNameW(hwnd, name, len(name))
        return {'hwnd': handle, 'pid': pid(hwnd), 'class': name.value, 'visible': bool(user.IsWindowVisible(hwnd))}
    tops, children = [], {}
    @callback_type
    def top(hwnd, _):
        if pid(hwnd) in owned: tops.append(int(hwnd))
        return True
    enum_top(top, 0)
    for hwnd in tops:
        @callback_type
        def child(value, _):
            if pid(value) in host_pids: children[int(value)] = facts(value)
            return True
        enum_child(hwnd, child, 0)
    roots = [row for row in children.values() if pid(user.GetParent(w.HWND(row['hwnd']))) not in host_pids]
    chains = []
    for root in roots:
        rect = w.RECT()
        if not user.GetClientRect(w.HWND(root['hwnd']), c.byref(rect)): continue
        point = w.POINT((rect.right - rect.left) // 2, (rect.bottom - rect.top) // 2)
        user.ClientToScreen(w.HWND(root['hwnd']), c.byref(point))
        hwnd, chain, seen = root['hwnd'], [], set()
        for _ in range(12):
            if not hwnd or hwnd in seen or pid(w.HWND(hwnd)) not in host_pids: break
            seen.add(hwnd); chain.append(facts(w.HWND(hwnd)))
            local = w.POINT(point.x, point.y); user.ScreenToClient(w.HWND(hwnd), c.byref(local))
            hwnd = int(user.ChildWindowFromPointEx(w.HWND(hwnd), local, 1) or 0)  # Skip invisible, retain disabled.
        chains.append(chain)
    return {'host_children': list(children.values()), 'center_hit_chains': chains,
            'visible_native_status_label_hit': any(chain and chain[-1]['visible'] and chain[-1]['class'].startswith('WindowsForms10.STATIC.') for chain in chains),
            'pixel_acceptance': False}


def launch_case(exe, out, data, config, fixture, case):
    profile = config['profile']; shell = data / 'shell' / profile
    env = {key: value for key, value in os.environ.items() if not key.startswith(('DLMS_', 'QUIZAPP_', 'PYTHON', 'QTWEBENGINE_'))}
    env['PATH'] = str(out / 'no-host-tools')
    owned, hosts = {}, set()
    result = {'case': case, 'normal_binary_optin_trace': True, 'app_test_hooks': False,
              'physical_acceptance': False, 'normal_close_acceptance': False,
              'forced_owned_server_cleanup': True, 'passed': False}
    def inspect(proc):
        if not alive(proc.pid, owned[proc.pid]):
            raise RuntimeError('The retained normal Server launcher exited before inspection')
        backend_count = 0
        for pid in descendants(proc.pid):
            try:
                value = identity(pid); owned[pid] = value['start']
                if Path(value['image']).name.lower() == 'dlms-webview2-host.exe': hosts.add(pid)
                if value['image'] == os.path.normcase(str(exe)):
                    argv = arguments(pid)
                    backend_count += argv[1:3] == ['--desktop-worker', 'backend']
            except OSError: pass
        assert not backend_count, 'Server spawned a Local backend'
        assert not (data / 'profiles' / profile).exists(), 'Server created a Local dataset'
        assert json.loads((shell / 'mode.json').read_text()) == config, 'Server configuration changed/fell back'
        return backend_count
    previous_traces = set((shell / 'window-events').glob('*.jsonl'))
    with (out / (case + '-launcher.log')).open('w') as log:
        proc = subprocess.Popen([str(exe), '--data-root', str(data), '--profile', profile, '--capture-window-events'],
                                cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT)
        owned[proc.pid] = identity(proc.pid)['start']
        try:
            deadline = time.monotonic() + 50
            listener_stopped = case == 'offline-reopen'
            while time.monotonic() < deadline:
                assert proc.poll() is None, f'Normal Server process exited: {proc.returncode}'
                inspect(proc)
                if case == 'connection-refused' and fixture.library.is_set() and not listener_stopped:
                    fixture.stop(); listener_stopped = True
                    result['listener_closed_after_library'] = True
                paths, rows = trace_rows(shell, previous_traces)
                failures = [row for row in rows if row['event'] == 'load-finish' and row.get('ok') is False]
                expected_response = (any(row['path'] == '/unavailable' and row['status'] == 503 for row in fixture.requests)
                                     if case == 'http503' else listener_stopped)
                if failures and expected_response and hosts and any(row['event'] == 'sample' for row in rows):
                    windows = owned_windows(owned, hosts)
                    if windows['visible_native_status_label_hit']:
                        result.update(native_outage_cover=windows, failed_load_count=len(failures),
                                      trace_paths=[str(path) for path in paths], samples=[row for row in rows if row['event'] == 'sample'][-3:])
                        break
                time.sleep(.1)
            else: raise TimeoutError('Normal Server outage/native-cover metadata checkpoint did not complete')
            if case != 'offline-reopen':
                assert [row['page'] for row in fixture.observations] == ['dashboard', 'library']
                assert all(row['ready'] == 'complete' for row in fixture.observations)
            if case == 'connection-refused':
                assert not any(row['path'] == '/unavailable' for row in fixture.requests), 'Listener was not closed before navigation'
            assert not any(row['local_credential_header'] for row in fixture.requests)
            inspect(proc)
            result.update(passed=True, local_dataset_absent=True, local_backend_count=0,
                          mode_config_unchanged=True, no_local_credential_headers=True,
                          synthetic_requests=list(fixture.requests), page_observations=list(fixture.observations))
        finally:
            inspection_error = None
            try:
                if proc.poll() is None: inspect(proc)
            except (AssertionError, RuntimeError, OSError) as exc:
                inspection_error = exc
                result.update(passed=False, final_inspection_error={'type': type(exc).__name__, 'reason': str(exc)})
            finally:
                # Server content gets no native shutdown bridge. Always clean
                # up our retained handle, even when an isolation check failed.
                if proc.poll() is None: proc.kill(); proc.wait(timeout=15)
                deadline = time.monotonic() + 10
                while any(alive(pid, born) for pid, born in owned.items()) and time.monotonic() < deadline: time.sleep(.1)
                survivors = [pid for pid, born in owned.items() if alive(pid, born)]
                result.update(owned_process_identities=[{'pid': pid, 'start': born} for pid, born in sorted(owned.items())],
                              survivors=survivors, exact_owned_cleanup=not survivors)
                (out / (case + '-result.json')).write_text(json.dumps(result, indent=2) + '\n')
                assert not survivors, 'Owned Server process survived retained-handle cleanup'
            if inspection_error is not None: raise inspection_error
    return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); exe = args.exe.resolve(strict=True); out = args.output.absolute()
    if (out.exists() or not out.resolve(strict=False).is_relative_to(WORK.resolve(strict=True))
            or not exe.is_relative_to(WORK.resolve(strict=True))): raise ValueError('Use a fresh project-local normal-package test root')
    binding = payload_binding(exe, args.inventory)
    out.mkdir(mode=0o700)
    results = []
    for case in ('http503', 'connection-refused'):
        fixture = Fixture()
        try:
            data = out / (case + ' data 日本語'); data.mkdir(mode=0o700)
            (data / '.dlms-desktop-windows-candidate.json').write_text(json.dumps({'kind': 'dlms-desktop-windows-candidate', 'version': 1}))
            profile = 'server-outage01'; shell = data / 'shell' / profile; shell.mkdir(mode=0o700, parents=True)
            config = {'version': 1, 'profile': profile, 'mode': 'server', 'server': {'id': str(uuid.uuid4()),
                'label': 'Synthetic outage fixture', 'origin': fixture.origin, 'private_http': True}}
            (shell / 'mode.json').write_text(json.dumps(config))
            results.append(launch_case(exe, out, data, config, fixture, case))
            fixture.stop()
            if case == 'connection-refused':
                results.append(launch_case(exe, out, data, config, fixture, 'offline-reopen'))
        finally: fixture.stop()
    assert payload_binding(exe, args.inventory) == binding
    result = {'normal_executable': str(exe), 'python_version': sys.version, 'normal_binary_optin_trace': True,
              'physical_acceptance': False, 'app_test_hooks': False, 'normal_close_acceptance': False,
              'payload_verified_before_and_after': True, 'runs': results, 'passed': True, **binding}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Normal packaged Server HTTP503, connection-refused navigation and offline reopen passed metadata/isolation checks; no pixels or normal close claimed.')


if __name__ == '__main__': main()
