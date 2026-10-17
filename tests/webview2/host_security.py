"""Actual standalone host boundary checks; synthetic data, never physical acceptance.

This module opens bounded native windows only when explicitly invoked. Each
Local context uses a new process/storage because a frame/worker policy violation
must disable that process's Local credential authority. Server opaque-context
controls demonstrate that the payloads really issue fetch/form requests.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
from socketserver import BaseRequestHandler, ThreadingTCPServer
import ssl
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / '.gate1/windows-native'


def fresh(path):
    from desktop.windows_files import assert_path, owned
    if not path.is_relative_to(AREA):
        raise ValueError('Task-local evidence only')
    assert_path(path)
    path.mkdir(mode=0o700, exist_ok=False)
    owned(path, private=True)
    return path


class Fixture(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, token, *, policy=True, legacy_referrer=False, original_csp=False):
        self.token, self.policy, self.legacy_referrer = token, policy, legacy_referrer
        self.original_csp = original_csp
        self.rows, self.lock = [], threading.Lock()
        super().__init__(('127.0.0.1', 0), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.worker = threading.Thread(target=self.serve_forever, daemon=True)

    def snapshot(self):
        with self.lock:
            return list(self.rows)

    def start(self):
        self.worker.start()
        return self

    def close(self):
        self.shutdown()
        self.server_close()
        self.worker.join(5)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length > 4096:
            self.respond(413, b'too large')
            return
        self.rfile.read(length)
        self.do_GET()

    def respond(self, status, body, kind='text/plain'):
        from desktop.webview2_runtime import LOCAL_CONTENT_POLICY, local_response_policy
        headers = [('Content-Type', kind), ('Content-Length', str(len(body))),
                   ('Cache-Control', 'no-store')]
        if not self.server.policy:
            # Positive opaque/data-worker controls need to observe their own
            # synthetic marker response. This affects this test HTTP fixture
            # only, never a Desktop backend or configured remote response.
            headers.append(('Access-Control-Allow-Origin', '*'))
        if self.server.original_csp:
            headers.append(('Content-Security-Policy', "img-src 'none'"))
        if self.server.policy:
            # Exercise the actual Local response adapter, including replacement
            # of the captured application's no-referrer policy. The reference
            # negative intentionally retains that previous header.
            headers.append(('Referrer-Policy', 'no-referrer'))
            if self.server.legacy_referrer:
                headers.append(('Content-Security-Policy', LOCAL_CONTENT_POLICY))
            else:
                headers = local_response_policy(lambda _status, protected, _exc=None: protected)(
                    str(status), headers)
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        credential = self.headers.get('X-DLMS-Desktop-Token')
        with self.server.lock:
            if len(self.server.rows) >= 4096:
                self.respond(429, b'fixture bound')
                return
            self.server.rows.append({
                'utc': datetime.now(timezone.utc).isoformat(),
                'method': self.command, 'path': parsed.path,
                'case': query.get('case', [''])[0],
                'has_token': credential is not None,
                'authenticated': credential == self.server.token,
                'origin': self.headers.get('Origin'),
                'fetch_destination': self.headers.get('Sec-Fetch-Dest'),
                'document_kind': query.get('document_kind', [''])[0] if query.get('document_kind', [''])[0] in ('blank', 'srcdoc', 'http', 'worker') else '',
            })
        if parsed.path == '/_desktop/ready':
            valid = (credential == self.server.token and
                     self.headers.get('X-DLMS-Desktop-Nonce') == self.server.token)
            self.respond(200 if valid else 403,
                         b'DLMS Desktop Block A ready' if valid else b'refused')
        elif parsed.path == '/worker.js':
            body = ("fetch('/probe?case=worker-script');"
                    "self.onconnect=e=>fetch('/probe?case=shared-worker');"
                    "self.addEventListener('install',e=>e.waitUntil(fetch('/probe?case=service-worker')));")
            self.respond(200, body.encode(), 'application/javascript')
        elif parsed.path == '/worker-socket.js':
            realm = query.get('realm', ['dedicated'])[0]
            target = query.get('target', [''])[0]
            self.respond(200, socket_worker_source(target, realm, self.server.origin).encode(), 'application/javascript')
        elif parsed.path in ('/registrar-frame', '/registrar-worker.js'):
            target = query.get('target', [''])[0]
            kind = query.get('kind', ['service'])[0]
            operation = registrar_source(target, kind, self.server.origin)
            if parsed.path == '/registrar-frame':
                self.respond(200, ('<!doctype html><script>'+operation+'</script>').encode(), 'text/html; charset=utf-8')
            else:
                self.respond(200, operation.encode(), 'application/javascript')
        elif parsed.path == '/frame':
            case, action = query.get('case', ['frame'])[0], query.get('action', ['fetch'])[0]
            body = '<!doctype html><script>' + child_payload(self.server.origin, case, action) + '</script>'
            self.respond(200, body.encode(), 'text/html; charset=utf-8')
        elif parsed.path in ('/control', '/probe', '/outcome'):
            self.respond(200, b'{"ok":true}', 'application/json')
        else:
            self.respond(200, b'<!doctype html><html><body>Private synthetic host boundary fixture</body></html>',
                         'text/html; charset=utf-8')


def socket_worker_source(target, realm, origin=''):
    operation = ("const run=()=>fetch("+json.dumps(origin+'/control?case=worker-started')+").then(()=>new Promise(resolve=>{"
                 "let s,done=false;const finish=()=>{if(done)return;done=true;clearTimeout(t);"
                 "if(s)try{s.close()}catch(e){};fetch("+json.dumps(origin+'/outcome?case=worker-finished')+").then(resolve,resolve)};"
                 "const t=setTimeout(finish,2500);try{s=new WebSocket("+json.dumps(target)+");"
                 "s.onopen=finish;s.onerror=finish;s.onclose=finish}catch(e){finish()}}));")
    if realm == 'service': return operation+"self.addEventListener('install',e=>e.waitUntil(run()))"
    if realm.startswith('shared'): return operation+'self.onconnect=e=>run()'
    return operation+'run()'


def registrar_source(target, kind, origin=''):
    from urllib.parse import urlencode
    # An initial about:blank has no HTTP base URL. Use the explicit synthetic
    # origin so its registration attempt reaches the policy check rather than
    # failing earlier while resolving a relative script URL.
    url = origin+'/worker-socket.js?'+urlencode({'realm': 'service' if kind == 'service' else 'shared', 'target': target})
    if kind == 'service':
        operation = ("if(typeof navigator.serviceWorker==='undefined')return 'registrar-api-unavailable';"
                     "return navigator.serviceWorker.register("+json.dumps(url)+").then(()=> 'registrar-resolved',e=>{"
                     "const reason=['SecurityError','InvalidStateError','TypeError','NotSupportedError'].includes(e.name)?e.name:'Other';"
                     "__marker('registrar-refusal-'+reason);return 'registrar-refused'})")
    else:
        operation = ("if(typeof SharedWorker==='undefined')return 'registrar-api-unavailable';"
                     "try{self.__syntheticSocketWorker=new SharedWorker("+json.dumps(url)+");"
                     "self.__syntheticSocketWorker.port.start();return 'registrar-resolved'}catch(e){return 'registrar-refused'}")
    prefix = ("const __kind=typeof document==='undefined'?'worker':location.href==='about:blank'?'blank':"
              "location.href==='about:srcdoc'?'srcdoc':'http';const __marker=name=>fetch("+
              json.dumps(origin+'/outcome?case=')+"+name+'&document_kind='+__kind);"
              "self.addEventListener('securitypolicyviolation',e=>{if(e.effectiveDirective==='worker-src'&&"
              "e.disposition==='enforce'&&e.originalPolicy.trim()===\"worker-src 'none'\")__marker('registrar-csp-enforced')});")
    # ServiceWorker registration can reject an initial blank/srcdoc document
    # before reaching CSP. Independently attempt a dedicated Worker in that
    # same document, requiring its actual inherited-policy violation and zero
    # bootstrap/execution. This is not a claim that the ServiceWorker rejection
    # itself came from CSP.
    inherited = ("if(__kind==='blank'||__kind==='srcdoc'){__marker('registrar-inheritance-probe');"
                 "try{self.__syntheticInheritedWorker=new Worker("+json.dumps(url)+")}catch(e){}}")
    return (prefix+"fetch("+json.dumps(origin+'/control?case=registrar-started')+"+'&document_kind='+__kind).then(()=>{"+inherited+
            operation+"}).then(result=>__marker(result))")


CSP_CAPTURE = ("window.__syntheticCsp=[];document.addEventListener('securitypolicyviolation',e=>{"
               "if(window.__syntheticCsp.length<8&&['worker-src','img-src'].includes(e.effectiveDirective))"
               "window.__syntheticCsp.push({directive:e.effectiveDirective,enforce:e.disposition==='enforce',"
               "worker_none:e.originalPolicy.trim()===\"worker-src 'none'\","
               "original_image_none:e.originalPolicy.trim()===\"img-src 'none'\"})});true")


def await_csp(host, directive):
    deadline = time.monotonic()+3
    rows = []
    while time.monotonic() < deadline:
        reply = host.evaluate('window.__syntheticCsp')
        assert reply.get('ok') and isinstance(reply.get('value'), list), reply
        rows = reply['value']
        if any(x.get('directive') == directive and x.get('enforce') is True for x in rows):
            return rows
        time.sleep(.05)
    raise AssertionError('No enforced '+directive+' violation from actual attempted operation: '+str(rows))


def child_payload(origin, case, action):
    destination = json.dumps(origin + '/probe?case=' + case)
    if action == 'fetch':
        # CORS mode makes the opaque sandbox's Origin:null observable at the
        # counter; CORS may deny its response, but must not hide the request.
        return f"fetch({destination},{{mode:'cors'}}).catch(()=>{{}})"
    method, target = ('GET', "f.target='_top';") if action == 'get-top' else ('POST', '')
    return (f"const f=document.createElement('form');f.method='{method}';f.action={destination};{target}"
            f"const n=document.createElement('input');n.name='case';n.value={json.dumps(case)};f.append(n);"
            "document.documentElement.append(f);f.submit()")


class Host:
    def __init__(self, executable, case, fixture, mode, *, reuse_storage=None):
        self.case, self.fixture = case, fixture
        self.events, self.condition = deque(maxlen=4096), threading.Condition()
        self.serial, self.forced, self.read_error = 0, False, None
        storage = fresh(case / 'storage') if reuse_storage is None else Path(reuse_storage)
        if reuse_storage is not None:
            from desktop.windows_files import assert_path, owned
            if not storage.is_relative_to(case.parent):
                raise ValueError('Only this fresh evidence run may reopen its own storage')
            assert_path(storage); owned(storage, private=True)
        self.storage = storage
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('WEBVIEW2_', 'QTWEBENGINE_', 'DLMS_', 'QUIZAPP_', 'PYTHON'))}
        for name in ('home', 'tmp', 'appdata', 'localappdata'):
            fresh(case / name)
        env.update(HOME=str(case/'home'), USERPROFILE=str(case/'home'), TMP=str(case/'tmp'),
                   TEMP=str(case/'tmp'), APPDATA=str(case/'appdata'), LOCALAPPDATA=str(case/'localappdata'))
        self.proc = subprocess.Popen([str(executable)], cwd=executable.parent, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        config = {'mode': mode, 'origin': fixture.origin, 'storage': str(storage),
                  'token': fixture.token if mode == 'local' else ''}
        self.proc.stdin.write((json.dumps(config)+'\n').encode())
        self.proc.stdin.flush()

    def _read(self):
        remaining = 4 * 1024 * 1024
        try:
            with (self.case/'host.jsonl').open('xb', buffering=0) as log:
                while True:
                    line = self.proc.stdout.readline(2*1024*1024+1)
                    if not line:
                        break
                    if remaining:
                        piece = line[:remaining]
                        try:
                            log.write(piece)
                        except OSError:
                            remaining = 0
                        remaining -= min(remaining, len(piece))
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError('Non-object event')
                    except (ValueError, UnicodeError):
                        event = {'event': 'invalid-protocol'}
                    with self.condition:
                        self.events.append(event)
                        self.condition.notify_all()
        except Exception as exc:
            self.read_error = type(exc).__name__

    def wait(self, predicate, timeout=25):
        end = time.monotonic()+timeout
        with self.condition:
            while time.monotonic() < end:
                value = predicate(list(self.events))
                if value:
                    return value
                if self.read_error or self.proc.poll() is not None:
                    raise RuntimeError('Host exited or evidence reader failed before expected event')
                self.condition.wait(min(.1, max(0, end-time.monotonic())))
        raise TimeoutError('Bounded standalone host checkpoint')

    def command(self, op, **values):
        self.serial += 1
        self.proc.stdin.write((json.dumps(dict(id=self.serial, op=op, **values))+'\n').encode())
        self.proc.stdin.flush()
        return self.serial

    def evaluate(self, script, *, gesture=False):
        identifier = self.command('eval', script=script, world=0, gesture=gesture)
        return self.wait(lambda rows: next((x for x in rows if x.get('event') == 'reply'
                                          and x.get('id') == identifier), None))

    def loaded(self):
        self.wait(lambda rows: any(x.get('event') == 'ready' for x in rows))
        self.command('navigate', url=self.fixture.origin+'/')
        self.wait(lambda rows: any(x.get('event') == 'load-finish' and x.get('ok') for x in rows))

    def close(self):
        from tests.windows.normal_processes import identity, alive
        from desktop.windows_processes import arguments
        observed, details = {}, []
        for pid in job_children():
            try:
                value = identity(pid)
                observed[pid] = value['start']
                role = [x for x in arguments(pid) if x.startswith('--type=')]
                details.append({'pid': pid, 'start': value['start'], 'image': value['image'],
                                'role': role[:1]})
            except (OSError, ValueError):
                pass
        (self.case/'observed-before-close.json').write_text(json.dumps(details, indent=2)+'\n')
        if self.proc.poll() is None:
            try:
                self.command('close')
                self.proc.wait(timeout=25)
            except (OSError, subprocess.TimeoutExpired):
                self.forced = True
                self.proc.kill()  # Retained handle; failed test cleanup only.
                self.proc.wait(timeout=5)
        self.reader.join(5)
        if self.proc.stdin:
            self.proc.stdin.close()
        if self.proc.stdout:
            self.proc.stdout.close()
        end = time.monotonic()+8
        while (job_children() or any(alive(pid, born) for pid, born in observed.items())) and time.monotonic() < end:
            time.sleep(.1)
        survivors = [pid for pid, born in observed.items() if alive(pid, born)]
        job_survivors = sorted(job_children())
        result = {'exit_code': self.proc.returncode, 'forced_cleanup': self.forced,
                  'observed_survivors': survivors, 'observed_identities': details,
                  'remaining_owned_job_pids': job_survivors,
                  'settle_bound_seconds': 8, 'reader_error': self.read_error}
        (self.case/'cleanup.json').write_text(json.dumps(result, indent=2)+'\n')
        assert not self.forced and not survivors and not job_survivors and not self.read_error, result


def job_children():
    """The harness's own private job also catches late/reparented descendants."""
    import ctypes as c
    from ctypes import wintypes as w
    from desktop import windows_processes as windows
    query = windows.api(windows.k, 'QueryInformationJobObject', w.BOOL,
                        w.HANDLE, c.c_int, w.LPVOID, w.DWORD, c.POINTER(w.DWORD))
    block = c.create_string_buffer(8+512*c.sizeof(c.c_size_t))
    length = w.DWORD()
    windows.checked(query(windows._outer.handle, 3, block, len(block), c.byref(length)))
    count = c.cast(c.addressof(block)+4, c.POINTER(w.DWORD))[0]
    if count > 512:
        raise ValueError('Owned process inventory exceeds its bound')
    values = c.cast(c.addressof(block)+8, c.POINTER(c.c_size_t))
    return {values[i] for i in range(count)} - {os.getpid()}


def marker(case):
    return "await fetch('/control?case=" + case + "');"


def exercise(executable, root, name, script, *, mode='local', positive=False,
             legacy_referrer=False, after_main=True):
    case = fresh(root/name)
    fixture = Fixture(secrets.token_hex(32), policy=mode == 'local', legacy_referrer=legacy_referrer).start()
    host = None
    try:
        host = Host(executable, case, fixture, mode)
        host.loaded()
        reply = host.evaluate('(async()=>{' + marker(name) + script + ';return true})()')
        time.sleep(1.5)
        after = None
        if mode == 'local' and not positive and after_main:
            after = host.evaluate("(async()=>{const r=await fetch('/control?case=after');return r.status})()")
        rows = fixture.snapshot()
        controls = [x for x in rows if x['path'] == '/control' and x['case'] == name]
        assert controls and controls[0]['authenticated'] == (mode == 'local'), rows
        probes = [x for x in rows if x['path'] == '/probe']
        expected_revocation = mode == 'local' and any(x.get('event') == 'fatal' for x in host.events)
        assert reply.get('ok') or expected_revocation, 'Payload evaluation failed before a verified Local revocation'
        if positive:
            assert probes, 'Positive control did not execute payload; refusal cannot be inferred'
            if mode == 'local':
                assert all(x['authenticated'] for x in probes), 'Main-origin positive control lacked its private credential'
            if name in ('main-form', 'main-fetch-explicit-no-referrer'):
                assert any(x['method'] == 'POST' and x['authenticated'] and x['origin'] == fixture.origin
                           for x in probes), probes
            if name in ('opaque-fetch', 'opaque-form'):
                assert any(x['origin'] == 'null' for x in probes), probes
            if name == 'opaque-get-top':
                assert any(x['method'] == 'GET' and x['origin'] is None for x in probes), probes
        else:
            assert not any(x['authenticated'] for x in probes), probes
            if mode == 'local':
                assert not probes, probes
                assert not [x for x in rows if x['path'] in ('/frame', '/worker.js')], rows
                if after_main:
                    fatal = any(x.get('event') == 'fatal' for x in host.events)
                    after_requests = [x for x in rows if x['path'] == '/control' and x['case'] == 'after']
                    if fatal:
                        assert not after_requests, 'A revoked Local host injected credentials after context violation'
                    else:
                        assert after_requests and after_requests[-1]['authenticated'], 'No positive main control after CSP refusal'
                if legacy_referrer:
                    assert any(x.get('event') == 'policy-blocked' and x.get('reason') == 'origin-null'
                               for x in host.events), 'Expected explicit opaque/null-origin refusal was not observed'
        result = {'name': name, 'mode': mode, 'positive_control': positive,
                  'script_reply_ok': bool(reply.get('ok')), 'requests': rows,
                  'after_control_reply': after,
                  'local_policy': ('legacy no-referrer + strict CSP' if legacy_referrer else
                                   'actual local_response_policy' if mode == 'local' else 'Server unchanged'),
                  'fatal_events': [x for x in host.events if x.get('event') == 'fatal'],
                  'page_authority_events': [x for x in host.events if x.get('event') in ('print', 'close-requested')],
                  'passed': True, 'physical_acceptance': False}
        (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        return result
    finally:
        try:
            if host:
                host.close()
        finally:
            (case/'requests.json').write_text(json.dumps(fixture.snapshot(), indent=2)+'\n')
            fixture.close()


def frame_script(kind, name, action):
    payload = child_payload('ORIGIN', name, action)
    # Resolve the active fixture origin in the main world; no credential enters JS.
    payload_expression = json.dumps(payload) + ".replaceAll('ORIGIN',location.origin)"
    prefix = "const f=document.createElement('iframe');"
    if kind == 'sandbox':
        return prefix + "f.sandbox='allow-scripts allow-forms allow-top-navigation';f.src='/frame?case="+name+'&action='+action+"';document.body.append(f)"
    if kind == 'same':
        return prefix + "f.src='/frame?case="+name+'&action='+action+"';document.body.append(f)"
    html = "'<script>'+" + payload_expression + "+'</scr'+'ipt>'"
    if kind == 'srcdoc':
        return prefix + 'f.srcdoc='+html+';document.body.append(f)'
    if kind == 'data':
        return prefix + "f.src='data:text/html,'+encodeURIComponent("+html+');document.body.append(f)'
    return prefix + "f.src=URL.createObjectURL(new Blob(["+html+"],{type:'text/html'}));document.body.append(f)"


def tls_check(executable, root):
    openssl = shutil.which('openssl')
    if not openssl:
        return {'name': 'tls', 'skipped': 'Existing openssl unavailable; no prerequisite installed'}
    case = fresh(root/'tls')
    cert, key = case/'synthetic-cert.pem', case/'synthetic-key.pem'
    with (case/'openssl.log').open('wb') as log:
        subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=synthetic.invalid', '-out', str(cert), '-keyout', str(key)],
                       check=True, timeout=30, stdout=log, stderr=subprocess.STDOUT)
    fixture = Fixture(secrets.token_hex(32), policy=False)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    fixture.socket = context.wrap_socket(fixture.socket, server_side=True)
    fixture.origin = f'https://127.0.0.1:{fixture.server_port}'
    fixture.start()
    host = None
    try:
        host = Host(executable, case, fixture, 'server')
        host.wait(lambda rows: any(x.get('event') == 'ready' for x in rows))
        host.command('navigate', url=fixture.origin+'/')
        host.wait(lambda rows: any(x.get('event') == 'certificate-refused' for x in rows))
        host.wait(lambda rows: any(x.get('event') == 'load-finish' and not x.get('ok') for x in rows))
        assert not fixture.snapshot(), 'Rejected certificate reached application HTTP handler'
        return {'name': 'tls', 'certificate_refused': True, 'application_requests': 0, 'passed': True}
    finally:
        try:
            if host:
                host.close()
        finally:
            fixture.close()


def file_system_check(executable, root, mode, api):
    """Require native denial before a File System Access handle is granted.

    A private Runtime user gesture is test instrumentation, not OS input. No
    filesystem picker is answered and no file/directory handle is ever used.
    A real intercepted input[type=file] positive control first proves this
    document can exercise the native chooser event path.
    """
    case = fresh(root / (mode + '-' + api))
    fixture = Fixture(secrets.token_hex(32), policy=mode == 'local').start()
    host = None
    try:
        host = Host(executable, case, fixture, mode)
        host.loaded()
        control = host.evaluate("(async()=>{const r=await fetch('/control?case=file-system-main');return r.status})()")
        assert control.get('ok') and control.get('value') == 200, control
        rows = [row for row in fixture.snapshot() if row['case'] == 'file-system-main']
        assert len(rows) == 1 and rows[0]['authenticated'] == (mode == 'local'), rows
        ordinary = host.evaluate("(()=>{const active=navigator.userActivation.isActive,f=document.createElement('input');f.type='file';document.body.append(f);f.click();return active})()", gesture=True)
        assert ordinary.get('ok') and ordinary.get('value') is True, ordinary
        picker = host.wait(lambda events: next((row for row in events if row.get('event') == 'file-picker'), None))
        cancel_id = host.command('files', ticket=picker['ticket'], paths=[])
        cancelled = host.wait(lambda events: next((row for row in events if row.get('event') == 'reply' and row.get('id') == cancel_id), None))
        assert cancelled.get('ok') and cancelled.get('value') == {'files_applied': False, 'files_exposed': False}, cancelled
        assert host.evaluate("document.querySelector('input[type=file]').files.length").get('value') == 0
        baseline = len(host.events)
        options = {'mode': 'read'} if api == 'showDirectoryPicker' else ({'suggestedName': 'synthetic-denied.txt'} if api == 'showSaveFilePicker' else {'multiple': False})
        script = ("(async()=>{const api="+json.dumps(api)+",available=typeof window[api]==='function',"
                  "activated=navigator.userActivation.isActive,secure=isSecureContext;"
                  "if(!available)return {available,activated,secure,granted:false,event:'unavailable'};"
                  "let timer;try{return await Promise.race([window[api]("+json.dumps(options)+").then(()=>({available,activated,secure,granted:true,event:'resolved'}),"
                  "e=>({available,activated,secure,granted:false,event:e.name==='AbortError'?'AbortError':'other-refusal'})),"
                  "new Promise(resolve=>{timer=setTimeout(()=>resolve({available,activated,secure,granted:false,event:'bounded-timeout'}),5000)})])}"
                  "finally{clearTimeout(timer)}})()")
        reply = host.evaluate(script, gesture=True)
        (case/'attempt.json').write_text(json.dumps({'api': api, 'reply': reply}, indent=2)+'\n')
        assert reply.get('ok'), reply
        result = reply.get('value')
        assert result == {'available': True, 'activated': True, 'secure': True, 'granted': False, 'event': 'AbortError'}, result
        host.wait(lambda events: any(row.get('event') == 'file-picker-failed' and row.get('error') == 'input-unavailable' for row in events[baseline:]))
        newer = list(host.events)[baseline:]
        assert not any(row.get('event') == 'file-picker' for row in newer), newer
        assert host.evaluate("document.querySelector('input[type=file]').files.length").get('value') == 0
        return {'name': mode+'-'+api, 'mode': mode, 'api': api, 'passed': True,
                'api_present': True, 'actual_private_user_activation': True,
                'ordinary_input_positive_then_cancelled': True,
                'abort_before_handle_grant': True, 'native_refusal': 'input-unavailable',
                'new_picker_tickets': 0, 'page_file_count': 0,
                'physical_acceptance': False, 'actual_host': True}
    finally:
        try:
            if host:
                host.close()
        finally:
            (case/'requests.json').write_text(json.dumps(fixture.snapshot(), indent=2)+'\n')
            fixture.close()


def preflight_negative(executable, root):
    case = fresh(root/'missing-csp')
    fixture = Fixture(secrets.token_hex(32), policy=False).start()
    host = None
    try:
        host = Host(executable, case, fixture, 'local')
        fatal = host.wait(lambda rows: next((x for x in rows if x.get('event') == 'fatal'), None))
        host.proc.wait(timeout=25)
        assert host.proc.returncode != 0, 'Missing Local policy was reported as normal startup'
        assert not any(x.get('event') == 'ready' for x in host.events)
        rows = fixture.snapshot()
        assert rows and all(x['path'] == '/_desktop/ready' for x in rows), rows
        assert rows[0]['authenticated'], rows
        return {'name': 'missing-csp', 'passed': True, 'fatal': fatal, 'requests': rows,
                'no_browser_ready': True}
    finally:
        try:
            if host:
                host.close()
        finally:
            fixture.close()


class HandshakeCounter(ThreadingTCPServer):
    """Count accepted loopback TCP connections, including WSS TLS attempts.

    This is deliberately not a TLS listener: a WSS ClientHello must already
    cross the network boundary before certificate checks could run. No raw
    request/ClientHello bytes or credential values are persisted.
    """
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, token):
        self.token, self.rows, self.lock = token, [], threading.Lock()
        super().__init__(('127.0.0.1', 0), HandshakeHandler)
        self.worker = threading.Thread(target=self.serve_forever, daemon=True)
        self.worker.start()

    def snapshot(self):
        with self.lock:
            return list(self.rows)

    def positive_control(self):
        # An explicit raw synthetic WebSocket opening request proves that the
        # same listener counts a connection; it does not bypass browser policy.
        with socket.create_connection(self.server_address, timeout=2) as client:
            client.sendall(("GET /synthetic-control HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                            "Connection: Upgrade\r\nUpgrade: websocket\r\n"
                            "Sec-WebSocket-Key: c3ludGhldGljLWNvbnRyb2w=\r\n"
                            "Sec-WebSocket-Version: 13\r\n\r\n").encode('ascii'))
            client.recv(256)
        deadline = time.monotonic()+2
        while not self.snapshot() and time.monotonic() < deadline:
            time.sleep(.02)
        rows = self.snapshot()
        assert len(rows) == 1 and rows[0]['kind'] == 'websocket-upgrade', rows
        return rows

    def close(self):
        self.shutdown(); self.server_close(); self.worker.join(5)


class HandshakeHandler(BaseRequestHandler):
    def handle(self):
        self.request.settimeout(1)
        try:
            data = self.request.recv(8192)
        except (TimeoutError, ConnectionError):
            data = b''
        fields = {}
        if data.startswith(b'GET '):
            for line in data.decode('latin1').split('\r\n')[1:]:
                if ':' in line:
                    name, value = line.split(':', 1)
                    fields[name.lower()] = value.strip()
        credential = fields.get('x-dlms-desktop-token')
        row = {'utc': datetime.now(timezone.utc).isoformat(), 'received_bytes': len(data),
               'kind': 'websocket-upgrade' if fields.get('upgrade', '').lower() == 'websocket'
                       else 'tls-client-hello' if data[:1] == b'\x16' else 'other-or-empty',
               'has_token': credential is not None, 'authenticated': credential == self.server.token}
        with self.server.lock:
            if len(self.server.rows) < 64:
                self.server.rows.append(row)
        try:
            self.request.sendall(b'HTTP/1.1 400 Synthetic Counter\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        except (OSError, ConnectionError):
            pass


def websocket_check(executable, root, mode, scheme, realm='main', *, case_name=None, reuse_storage=None,
                    expect_worker_refusal=False, expect_worker_csp=False):
    name = case_name or mode+'-'+scheme+'-'+realm+'-foreign'
    case = fresh(root/name)
    fixture = Fixture(secrets.token_hex(32), policy=mode == 'local', original_csp=expect_worker_csp).start()
    counter, host = HandshakeCounter(fixture.token), None
    try:
        proof = counter.positive_control()
        host = Host(executable, case, fixture, mode, reuse_storage=reuse_storage)
        host.loaded()
        control = host.evaluate("(async()=>{const r=await fetch('/control?case=websocket-main');return r.status})()")
        assert control.get('ok'), control
        controls = [x for x in fixture.snapshot() if x['path'] == '/control']
        assert controls and controls[-1]['authenticated'] == (mode == 'local'), controls
        csp_evidence = []
        if expect_worker_csp:
            assert host.evaluate(CSP_CAPTURE).get('ok')
            assert host.evaluate("(()=>{const i=new Image();i.src='/original-csp-image';document.body.append(i);return true})()").get('ok')
            csp_evidence = await_csp(host, 'img-src')
            assert any(x.get('original_image_none') is True and x.get('enforce') is True for x in csp_evidence)
            assert not any(x['path'] == '/original-csp-image' for x in fixture.snapshot()), 'Existing Server CSP was replaced or weakened'
        target = f'{scheme}://127.0.0.1:{counter.server_address[1]}/synthetic-websocket'
        script = ("new Promise(resolve=>{let s,done=false;const finish=event=>{if(done)return;done=true;"
                  "clearTimeout(t);if(s)try{s.close()}catch(e){};resolve({event,constructed:!!s})};"
                  "const t=setTimeout(()=>finish('bounded-timeout'),2500);try{s=new WebSocket("+
                  json.dumps(target)+");s.onopen=()=>finish('open');s.onerror=()=>finish('error');"
                  "s.onclose=()=>finish('close')}catch(e){finish('constructor-refused')}})")
        if realm != 'main':
            from urllib.parse import urlencode
            worker_url = '/worker-socket.js?' + urlencode({'realm': realm, 'target': target})
            if realm == 'service':
                script = "(async()=>{try{window.__syntheticSocketWorker=await navigator.serviceWorker.register("+json.dumps(worker_url)+");return {registered:true}}catch(e){return {registered:false,refusal:e.name}}})()"
            elif realm in ('service-frame', 'shared-frame', 'service-dedicated', 'service-aboutblank', 'service-srcdoc'):
                url = ('/registrar-worker.js?' if realm.endswith('dedicated') else '/registrar-frame?')+urlencode(
                    {'kind': 'shared' if realm.startswith('shared') else 'service', 'target': target})
                script = ("(()=>{try{window.__syntheticRegistrar=new Worker("+json.dumps(url)+");return {registrar_created:true}}catch(e){return {registrar_created:false,refusal:e.name}}})()"
                          if realm.endswith('dedicated') else
                          "(()=>{const f=document.createElement('iframe');f.src="+json.dumps(url)+";document.body.append(f);return {registrar_created:true}})()")
                if realm in ('service-aboutblank', 'service-srcdoc'):
                    body = registrar_source(target, 'service', fixture.origin)
                    if realm.endswith('aboutblank'):
                        script = "(()=>{const f=document.createElement('iframe');document.body.append(f);f.contentWindow.eval("+json.dumps(body)+");return {registrar_created:true}})()"
                    else:
                        script = "(()=>{window.__syntheticRegistrarFrame=document.createElement('iframe');window.__syntheticRegistrarFrame.srcdoc="+json.dumps('<script>'+body+'</script>')+";document.body.append(window.__syntheticRegistrarFrame);return {registrar_created:true}})()"
            else:
                constructor = 'SharedWorker' if realm.startswith('shared') else 'Worker'
                expression = json.dumps(worker_url)
                if realm == 'shared-blob':
                    expression = 'URL.createObjectURL(new Blob(['+json.dumps(socket_worker_source(target, 'shared', fixture.origin))+"],{type:'application/javascript'}))"
                elif realm == 'shared-data':
                    expression = "'data:application/javascript,'+encodeURIComponent("+json.dumps(socket_worker_source(target, 'shared', fixture.origin))+')'
                script = "(()=>{const api=typeof "+constructor+";try{window.__syntheticSocketWorker=new "+constructor+'('+expression+');'
                if realm.startswith('shared'): script += 'window.__syntheticSocketWorker.port.start();'
                script += 'return {constructed:true,api}}catch(e){return {constructed:false,api,refusal:e.name}}})()'
        reply = host.evaluate(script)
        assert reply.get('ok'), reply
        worker_controls = []
        registrar_controls = []
        refusal_kind = None
        if realm != 'main':
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                worker_controls = [x for x in fixture.snapshot() if x['case'] in ('worker-started', 'worker-finished')]
                registrar_controls = [x for x in fixture.snapshot() if x['case'].startswith('registrar-')]
                if ((expect_worker_csp and (realm in ('dedicated', 'service-dedicated', 'service')
                                           or (realm.startswith('shared') and realm != 'shared-frame')
                                           or any(x['case'] == 'registrar-csp-enforced' for x in registrar_controls)
                                           or (realm == 'shared-frame' and len(registrar_controls) >= 2
                                               and any(x['case'] == 'registrar-api-unavailable' for x in registrar_controls))))
                        or (expect_worker_refusal and (realm.startswith('shared') or realm.startswith('service'))
                            and (not realm.endswith(('frame', 'dedicated')) or len(registrar_controls) >= 2))
                        or {x['case'] for x in worker_controls} == {'worker-started', 'worker-finished'}):
                    break
                time.sleep(.05)
            if expect_worker_csp:
                assert not worker_controls, 'CSP-prohibited worker executed its payload'
                assert not [x for x in fixture.snapshot() if x['path'] in ('/worker-socket.js', '/registrar-worker.js')], 'CSP-prohibited bootstrap reached HTTP server'
                if realm.startswith('shared') and realm != 'shared-frame' and reply.get('value', {}).get('api') == 'undefined':
                    assert reply['value'].get('constructed') is False and reply['value'].get('refusal') == 'ReferenceError'
                    refusal_kind = 'native SharedWorker binding absent (CSP not exercised for this constructor)'
                elif realm == 'shared-frame' and any(x['case'] == 'registrar-api-unavailable' for x in registrar_controls):
                    assert any(x['case'] == 'registrar-started' for x in registrar_controls), registrar_controls
                    refusal_kind = 'frame SharedWorker binding absent (CSP not exercised)'
                elif realm in ('service-frame', 'service-aboutblank', 'service-srcdoc', 'shared-frame'):
                    if realm == 'service-srcdoc' and not registrar_controls:
                        # The existing exact-origin native frame boundary may
                        # cancel srcdoc. Exercise its surviving initial blank
                        # document explicitly and report that actual context.
                        body = registrar_source(target, 'service', fixture.origin)
                        fallback = host.evaluate('(()=>{const f=window.__syntheticRegistrarFrame;if(!f||f.contentWindow.location.href!==\'about:blank\')return false;f.contentWindow.eval('+json.dumps(body)+');return true})()')
                        assert fallback.get('ok') and fallback.get('value') is True, fallback
                        deadline = time.monotonic()+3
                        while time.monotonic() < deadline:
                            registrar_controls = [x for x in fixture.snapshot() if x['case'].startswith('registrar-')]
                            if len(registrar_controls) >= 3: break
                            time.sleep(.05)
                    kinds = {x['case'] for x in registrar_controls}
                    assert {'registrar-started', 'registrar-csp-enforced'} <= kinds, registrar_controls
                    if any(x['document_kind'] in ('blank', 'srcdoc') for x in registrar_controls):
                        assert 'registrar-inheritance-probe' in kinds, registrar_controls
                    if realm == 'shared-frame':
                        # SharedWorker construction can return an object before
                        # CSP asynchronously refuses its script. The actual
                        # violation and zero bootstrap/execution remain proof.
                        assert kinds & {'registrar-refused', 'registrar-resolved'}, registrar_controls
                    else:
                        assert 'registrar-refused' in kinds and 'registrar-resolved' not in kinds, registrar_controls
                    refusal_kind = 'enforced worker-src in actual frame context: '+','.join(sorted({x['document_kind'] for x in registrar_controls}))
                else:
                    if realm == 'service': assert reply.get('value', {}).get('registered') is False, reply
                    csp_evidence = await_csp(host, 'worker-src')
                    assert any(x.get('worker_none') is True and x.get('enforce') is True for x in csp_evidence), csp_evidence
                    refusal_kind = 'enforced appended worker-src none before execution'
            elif expect_worker_refusal and (realm.startswith('shared') or realm.startswith('service')):
                assert not worker_controls, 'Prohibited worker executed its payload'
                assert not [x for x in fixture.snapshot() if x['path'] == '/worker-socket.js'], 'Prohibited worker bootstrap reached HTTP server'
                if realm.startswith('shared') and realm != 'shared-frame':
                    assert reply['value'].get('api') == 'undefined' and reply['value'].get('constructed') is False
                    assert reply['value'].get('refusal') == 'ReferenceError', reply
                    refusal_kind = 'native SharedWorker binding absent'
                elif realm == 'shared-frame':
                    assert {x['case'] for x in registrar_controls} == {'registrar-started', 'registrar-api-unavailable'}, registrar_controls
                    refusal_kind = 'frame SharedWorker binding absent; executed frame marker'
                else:
                    if realm == 'service':
                        assert reply['value'].get('registered') is False, reply
                    else:
                        assert 'registrar-started' in {x['case'] for x in registrar_controls}, registrar_controls
                        assert 'registrar-resolved' not in {x['case'] for x in registrar_controls}, registrar_controls
                    if realm == 'service-dedicated' and any(x['case'] == 'registrar-api-unavailable' for x in registrar_controls):
                        refusal_kind = 'dedicated WorkerNavigator serviceWorker API absent'
                    else:
                        assert realm == 'service' or any(x['case'] == 'registrar-refused' for x in registrar_controls), registrar_controls
                        assert any(x.get('event') == 'policy-blocked' and x.get('reason') == 'worker-bootstrap'
                                   for x in host.events), 'No native worker-bootstrap refusal proof'
                        refusal_kind = 'native service-worker HTTP bootstrap refusal'
            else:
                assert {x['case'] for x in worker_controls} == {'worker-started', 'worker-finished'}, 'Worker payload did not execute start and terminal HTTP controls'
                assert not any(x['authenticated'] for x in worker_controls), worker_controls
        time.sleep(.3)
        rows = counter.snapshot()[len(proof):]
        result = {'name': name, 'mode': mode, 'scheme': scheme, 'realm': realm, 'reply': reply,
                  'storage': str(host.storage),
                  'socket_policy': [x for x in host.events if x.get('event') == 'socket-policy'],
                  'worker_execution_controls': worker_controls,
                  'registrar_execution_controls': registrar_controls, 'expected_worker_refusal': expect_worker_refusal,
                  'expected_worker_csp': expect_worker_csp, 'csp_evidence': csp_evidence,
                  'refusal_kind': refusal_kind,
                  'raw_positive_control': proof, 'native_connection_attempts': rows,
                  'initial_handshakes': len(rows), 'passed': not rows,
                  'actual_host': True, 'physical_acceptance': False,
                  'scope': 'TCP accept counter, including WSS before any certificate decision; no messages or raw bytes retained'}
        (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        return result
    finally:
        try:
            if host:
                host.close()
        finally:
            (case/'requests.json').write_text(json.dumps(fixture.snapshot(), indent=2)+'\n')
            (case/'handshake-counter.json').write_text(json.dumps(counter.snapshot(), indent=2)+'\n')
            counter.close(); fixture.close()


def policy_reopen_checks(executable, root):
    """Same UDF identity survives close/reopen and a relocated identical host.

    Only storage created in this function is reopened. This is a standalone
    host/policy lifecycle check, not an installer or full application update.
    """
    before = {p.relative_to(executable.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in executable.parent.rglob('*') if p.is_file()}
    relocated = fresh(root/'relocated-host')/'payload'
    shutil.copytree(executable.parent, relocated)
    from package_windows_webview2.build import verify_host
    # Rebind only receipt paths to this explicit identical-byte relocation;
    # record this as a harness relocation, never as a separately compiled build.
    (relocated.parent/'SHA256.json').write_text(json.dumps([
        {'Path': str(relocated/name), 'Hash': digest} for name, digest in before.items()
    ], indent=2)+'\n')
    verify_host(relocated)
    copied = {p.relative_to(relocated).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in relocated.rglob('*') if p.is_file()}
    assert copied == before, 'Relocation must use exactly the selected host bytes'
    results = []
    for mode in ('local', 'server'):
        initial_name = mode+'-policy lifecycle 日本語'
        initial = websocket_check(executable, root, mode, 'ws', case_name=initial_name)
        results.append(initial)
        storage = Path(initial['storage'])
        for phase, host in (('reopen', executable), ('relocated-update', relocated/executable.name)):
            results.append(websocket_check(host, root, mode, 'ws',
                                          case_name=mode+'-'+phase, reuse_storage=storage))
        group = results[-3:]
        identities = [item['socket_policy'][0]['id'] if item['socket_policy'] else None for item in group]
        assert identities[0] and len(set(identities)) == 1, 'Private policy identity changed across stable-storage reopen/update'
        assert all(len(item['socket_policy']) == 1 and item['socket_policy'][0].get('enabled') is True
                   for item in group), 'Known policy was not enabled before readiness'
    after = {p.relative_to(executable.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in executable.parent.rglob('*') if p.is_file()}
    copied_after = {p.relative_to(relocated).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in relocated.rglob('*') if p.is_file()}
    receipt = {'original_payload_unchanged': after == before,
               'relocated_payload_unchanged': copied_after == copied,
               'private_data_only': True, 'full_application_update_acceptance': False,
               'cases': results}
    (root/'policy-reopen.json').write_text(json.dumps(receipt, indent=2)+'\n')
    assert receipt['original_payload_unchanged'] and receipt['relocated_payload_unchanged'], 'Browser policy wrote into application payload'
    return results


def main():
    if os.name != 'nt':
        raise RuntimeError('Actual native Windows host only')
    p = argparse.ArgumentParser()
    p.add_argument('--host', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--websocket-only', action='store_true')
    p.add_argument('--file-system-only', action='store_true', help='Require actual File System Access picker denial without granting/using filesystem handles')
    p.add_argument('--policy-reopen', action='store_true', help='Add standalone fresh/reopen/relocated-host policy identity checks')
    p.add_argument('--expect-worker-refusal', action='store_true', help='Require native SharedWorker absence and ServiceWorker bootstrap refusal; never infer it from missing markers alone')
    p.add_argument('--shared-source-baseline', action='store_true', help='Execute permissive Server SharedWorker blob/data controls on an explicitly selected pre-restriction host; boundary failures remain failures')
    p.add_argument('--expect-worker-csp', action='store_true', help='Require actual enforced worker-src violations and preserved original CSP; all workers unsupported')
    args = p.parse_args()
    from desktop.windows_processes import own_launcher
    from desktop.windows_files import assert_path
    from package_windows_webview2.build import verify_host
    own_launcher()
    executable, output = args.host.absolute(), args.output.absolute()
    assert_path(executable, leaf=True)
    if not executable.is_relative_to(AREA) or executable.name != 'DLMS-WebView2-Host.exe':
        raise ValueError('Explicit task-local candidate host required')
    verify_host(executable.parent)
    fresh(output)
    results = []
    complete = False
    harness_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    response_policy_digest = hashlib.sha256((ROOT/'desktop/webview2_runtime.py').read_bytes()).hexdigest()
    if args.file_system_only:
        if args.websocket_only or args.shared_source_baseline or args.policy_reopen:
            raise ValueError('Filesystem controls use their own explicit fresh-profile mode')
        try:
            for mode in ('local', 'server'):
                for api in ('showOpenFilePicker', 'showSaveFilePicker', 'showDirectoryPicker'):
                    results.append(file_system_check(executable, output, mode, api))
            complete = True
        finally:
            (output/'summary.json').write_text(json.dumps({
                'host': str(executable), 'host_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                'harness_sha256': harness_digest, 'response_policy_module_sha256': response_policy_digest,
                'cases': results, 'actual_host': True, 'physical_acceptance': False,
                'complete': complete, 'passed': complete and all(row['passed'] for row in results),
                'scope': 'Fresh synthetic File System Access refusal; no directory/file handle answered or used',
            }, indent=2)+'\n')
        print('Filesystem controls complete; all test windows closed. Evidence: '+str(output), flush=True)
        return
    if args.shared_source_baseline and args.expect_worker_refusal:
        raise ValueError('An execution baseline must not expect worker refusal')
    if args.websocket_only or args.shared_source_baseline:
        try:
            for mode in (('server',) if args.shared_source_baseline else ('local', 'server')):
                for realm in (('shared-blob', 'shared-data') if args.shared_source_baseline else
                        ('main',) if mode == 'local' else (
                        ('main', 'dedicated', 'shared', 'shared-blob', 'shared-data', 'shared-frame',
                         'service', 'service-frame', 'service-aboutblank', 'service-srcdoc', 'service-dedicated') if (args.expect_worker_refusal or args.expect_worker_csp) else
                        ('main', 'dedicated', 'shared', 'service'))):
                    for scheme in ('ws', 'wss'):
                        results.append(websocket_check(executable, output, mode, scheme, realm,
                                                       expect_worker_refusal=args.expect_worker_refusal,
                                                       expect_worker_csp=args.expect_worker_csp))
            if args.policy_reopen and not args.shared_source_baseline and all(x['passed'] for x in results):
                results.extend(policy_reopen_checks(executable, output))
            complete = True
        finally:
            (output/'summary.json').write_text(json.dumps({
                'host': str(executable), 'host_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                'harness_sha256': harness_digest, 'response_policy_module_sha256': response_policy_digest,
                'cases': results, 'actual_host': True, 'physical_acceptance': False,
                'complete': complete, 'passed': complete and all(x['passed'] for x in results),
            }, indent=2)+'\n')
        print('WebSocket counter checks complete; all test windows closed. Evidence: '+str(output), flush=True)
        if not all(x['passed'] for x in results):
            raise AssertionError('Off-origin WebSocket/WSS initial connection reached a synthetic listener')
        return
    try:
        results.append(exercise(executable, output, 'main', "await fetch('/probe?case=main')", positive=True))
        form = "const f=document.createElement('form');f.method='POST';f.action='/probe?case=main-form';document.body.append(f);f.submit()"
        results.append(exercise(executable, output, 'main-form', form, positive=True))
        results.append(exercise(executable, output, 'old-no-referrer-form', form,
                                legacy_referrer=True, after_main=False))
        # Fetch retains its exact Origin in the tested runtime even when its
        # per-request referrer policy omits Referer. Unlike the preceding form
        # navigation, it is a legitimate main-origin positive control.
        results.append(exercise(executable, output, 'main-fetch-explicit-no-referrer',
                                "await fetch('/probe?case=explicit-no-referrer',{method:'POST',mode:'no-cors',body:'synthetic',referrerPolicy:'no-referrer'})",
                                positive=True))
        for action in ('fetch', 'form', 'get-top'):
            name = 'opaque-'+action
            results.append(exercise(executable, output, name, frame_script('sandbox', name, action),
                                    mode='server', positive=True))
        for kind in ('same', 'sandbox', 'srcdoc', 'data', 'blob'):
            for action in ('fetch', 'form', 'get-top'):
                name = kind+'-'+action
                results.append(exercise(executable, output, name, frame_script(kind, name, action)))
        for kind, operation in (
                ('dedicated', "new Worker('/worker.js')"),
                ('shared', "new SharedWorker('/worker.js')"),
                ('service', "await navigator.serviceWorker.register('/worker.js')")):
            script = "try{"+operation+"}catch(e){await fetch('/outcome?case="+kind+"')}"
            if args.expect_worker_csp:
                results.append(websocket_check(executable, output, 'server', 'ws', kind,
                                               case_name='server-prohibited-'+kind,
                                               expect_worker_csp=True))
            else:
                results.append(exercise(executable, output, 'positive-'+kind, script, mode='server', positive=True))
            results.append(exercise(executable, output, kind, script))
        foreign = Fixture(secrets.token_hex(32), policy=False).start()
        try:
            script = ("await fetch('/probe?case=server',{headers:{'X-DLMS-Desktop-Token':'synthetic-forgery'}});"
                      "if(typeof __dlmsPrintRequest!=='undefined')throw Error('print binding exposed');"
                      "document.dispatchEvent(new Event('__dlms_pdf_request'));"
                      "try{chrome.webview.postMessage({op:'print'})}catch(e){};"
                      "try{await fetch("+json.dumps(foreign.origin+'/probe')+")}catch(e){};"
                      "location.href="+json.dumps(foreign.origin+'/probe')+";")
            result = exercise(executable, output, 'server', script, mode='server', positive=True)
            # A page can forge this public header name, but the Server host
            # must never inject/possess the actual private Local nonce. Real
            # WebView2 retained the forged value despite RemoveHeader; retain
            # that observation, never relabel it as successful header scrubbing.
            assert not any(x['authenticated'] for x in result['requests']), result
            result['forged_header_observed'] = any(x['has_token'] for x in result['requests'])
            result['server_actual_nonce_absent'] = True
            assert result['script_reply_ok'], result
            assert not result['page_authority_events'], result
            assert not foreign.snapshot(), foreign.snapshot()
            results.append(result)
        finally:
            foreign.close()
        results.append(tls_check(executable, output))
        results.append(preflight_negative(executable, output))
        complete = True
    finally:
        (output/'summary.json').write_text(json.dumps({
            'host': str(executable), 'host_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'harness_sha256': harness_digest, 'response_policy_module_sha256': response_policy_digest,
            'cases': results, 'actual_host': True, 'physical_acceptance': False,
            'complete': complete,
            'scope': 'Fresh synthetic endpoints and storage only; no existing profiles/settings/trust changes',
        }, indent=2)+'\n')
    print('Actual host security checks complete; all test windows closed. Evidence: '+str(output), flush=True)


if __name__ == '__main__':
    main()
