"""Source-only Fetch mechanism controls; synthetic bytes, not receiver acceptance.

No browser dispatch, owner profiles, production endpoints or body/token logging.
Large requests are streamed into a receiver digest and compared with the exact
browser Request clone, including multipart framing. Response-pending close is
not claimed as a paused-CDP-decision cancellation test.
"""
from __future__ import annotations

import argparse
from email.message import Message
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

from tests.webview2.host_security import (AREA, Fixture, Handler, Host, exercise,
                                        frame_script, fresh, websocket_check)

POPUP = 'https://dlms-popup-probe.invalid/synthetic-no-content'
MAX_BODY = 257 * 1024 * 1024  #256MiB supported File plus bounded multipart framing.


class StreamFixture(Fixture):
    def __init__(self, token):
        super().__init__(token)
        self.RequestHandlerClass = StreamHandler
        self.received = threading.Event()
        self.release = threading.Event()
        self.foreign_origin = None


class StreamHandler(Handler):
    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path != '/large':
            return super().do_POST()
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= MAX_BODY:
            return self.respond(413, b'fixture body bound')
        self.connection.settimeout(15)
        count, digest = 0, hashlib.sha256()
        query = parse_qs(parsed.query)
        direct = query.get('direct', [''])[0]
        payload_digest, payload_count, framing_valid = hashlib.sha256(), 0, True

        def consume(length_to_read):
            nonlocal count
            block = self.rfile.read(length_to_read)
            count += len(block)
            digest.update(block)
            return block

        complete = False
        try:
            if direct == 'multipart':
                payload_length = int(query.get('bytes', ['0'])[0])
                if not 0 < payload_length <= MAX_BODY:
                    raise ValueError('Synthetic payload bound')
                content_type = Message()
                content_type['Content-Type'] = self.headers.get('Content-Type', '')
                boundary = (content_type.get_param('boundary') or '').encode('ascii')
                if not boundary or len(boundary) > 200:
                    raise ValueError('Synthetic multipart boundary')
                header = bytearray()
                while len(header) < 8192 and not header.endswith(b'\r\n\r\n'):
                    block = consume(1)
                    if not block:
                        break
                    header.extend(block)
                framing_valid = (header.startswith(b'--'+boundary+b'\r\n')
                                 and header.endswith(b'\r\n\r\n'))
                while payload_count < payload_length:
                    block = consume(min(65536, payload_length-payload_count))
                    if not block:
                        break
                    payload_count += len(block)
                    payload_digest.update(block)
                tail = bytearray()
                while count < length and len(tail) <= 4096:
                    block = consume(min(4096, length-count))
                    if not block:
                        break
                    tail.extend(block)
                framing_valid = framing_valid and tail in (b'\r\n--'+boundary+b'--', b'\r\n--'+boundary+b'--\r\n')
            else:
                while count < length:
                    block = consume(min(65536, length-count))
                    if not block:
                        break
                    payload_count += len(block)
                    payload_digest.update(block)
            complete = count == length
        except (OSError, TimeoutError, ValueError):
            pass
        credential = self.headers.get('X-DLMS-Desktop-Token')
        with self.server.lock:
            self.server.rows.append({
                'path': '/large', 'method': 'POST', 'bytes': count,
                'declared_bytes': length, 'complete': complete,
                'sha256': digest.hexdigest(),
                'payload_bytes': payload_count, 'payload_sha256': payload_digest.hexdigest(),
                'framing_valid': framing_valid,
                'has_token': credential is not None,
                'authenticated': credential == self.server.token,
                'kind': 'multipart' if self.headers.get('Content-Type', '').startswith('multipart/form-data;') else 'raw',
            })
        self.respond(200 if complete else 400, b'{"ok":true}', 'application/json')

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/redirect':
            kind = parse_qs(parsed.query).get('kind', ['same'])[0]
            credential = self.headers.get('X-DLMS-Desktop-Token')
            with self.server.lock:
                self.server.rows.append({'path': '/redirect', 'method': 'GET',
                    'kind': kind if kind in ('same', 'foreign', 'blocked') else 'invalid',
                    'status': 307, 'has_token': credential is not None,
                    'authenticated': credential == self.server.token})
            destination = (self.server.foreign_origin+'/probe' if kind == 'foreign'
                           else '/probe' if kind == 'blocked' else '/control')
            self.send_response(307)
            self.send_header('Location', destination)
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        if parsed.path == '/held':
            self.server.received.set()
            self.server.release.wait(40)
            try:
                return self.respond(200, b'held synthetic response')
            except ConnectionAbortedError:
                # Expected only when the test closes its own client first.
                with self.server.lock:
                    self.server.rows.append({'path': '/held', 'client_aborted_after_close': True})
                return
        return super().do_GET()


def wait_for(predicate, timeout=20):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise TimeoutError('Bounded synthetic receiver checkpoint')


def large_script(size, multipart):
    # The only retained values are sizes/digests/status. Never serialize the
    # Request, the File bytes, clipboard, credentials or native event payloads.
    body = ("const form=new FormData();form.append('file',new File([bytes],'synthetic résumé data.bin',"
            "{type:'application/octet-stream'}));const body=form;" if multipart else 'const body=bytes;')
    return ("(async()=>{const bytes=new Uint8Array("+str(size)+");bytes.fill(65);"+body+
            "const request=new Request('/large',{method:'POST',body});"
            "const copy=await request.clone().arrayBuffer();"
            "const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',copy)),"
            "v=>v.toString(16).padStart(2,'0')).join('');"
            "const r=await fetch(request);return {bytes:copy.byteLength,sha256:hash,status:r.status}})()")


def run_case(executable, output, mode, name, action):
    case = fresh(output/(mode+'-'+name))
    fixture = StreamFixture(secrets.token_hex(32)).start()
    foreign = Fixture(secrets.token_hex(32)).start()
    fixture.foreign_origin = foreign.origin
    host = None
    result = {'mode': mode, 'case': name, 'source_only': True,
              'application_receiver_acceptance': False, 'physical_acceptance': False,
              'diagnostic_completed': False, 'passed': False}
    try:
        host = Host(executable, case, fixture, mode)
        host.loaded()
        action(host, fixture, foreign, result)
        result['diagnostic_completed'] = True
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    finally:
        try:
            fixture.release.set()
            if host is not None:
                if not result.get('host_closed_by_action'):
                    host.close()
                result['cleanup'] = json.loads((case/'cleanup.json').read_text())
        finally:
            result['requests'] = fixture.snapshot()
            result['foreign_requests'] = foreign.snapshot()
            result['host_events'] = list(host.events) if host is not None else []
            fixture.close()
            foreign.close()
            (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def large_action(size, multipart):
    def action(host, fixture, foreign, result):
        result['payload_bytes'] = size
        result['kind'] = 'multipart-file' if multipart else 'raw-binary'
        reply = host.evaluate(large_script(size, multipart))
        result['reply_ok'] = reply.get('ok') is True
        expected = reply.get('value') if isinstance(reply.get('value'), dict) else {}
        result['expected'] = expected
        rows = [x for x in fixture.snapshot() if x['path'] == '/large']
        result['receiver_count'] = len(rows)
        result['passed'] = (result['reply_ok'] and expected.get('status') == 200 and len(rows) == 1
            and rows[0]['complete'] and rows[0]['bytes'] == expected.get('bytes')
            and rows[0]['sha256'] == expected.get('sha256')
            and (rows[0]['authenticated'] if result['mode'] == 'local' else not rows[0]['has_token']))
    return action


def synthetic_digest(size):
    digest = hashlib.sha256()
    block = b'A'*65536
    remaining = size
    while remaining:
        count = min(remaining, len(block))
        digest.update(block[:count])
        remaining -= count
    return digest.hexdigest()


def direct_action(size, kind):
    def action(host, fixture, foreign, result):
        multipart = kind in ('memory-file', 'disk-file')
        result.update(payload_bytes=size, kind=kind, request_cloned=False,
                      native_chooser_acceptance=False, server_consent_acceptance=False)
        if kind in ('disk-file', 'disk-raw'):
            folder = fresh(host.case/'synthetic inputs')
            path = folder/'résumé synthetic bytes.bin'
            with path.open('xb') as stream:
                remaining = size
                while remaining:
                    count = min(65536, remaining)
                    stream.write(b'A'*count)
                    remaining -= count
            from desktop.windows_files import assert_path, owned
            assert_path(path, leaf=True)
            owned(path, private=True)
            before = len(host.events)
            opened = host.evaluate("(()=>{window.__directInput=document.createElement('input');"
                "__directInput.type='file';document.body.append(__directInput);__directInput.click();return true})()", gesture=True)
            if opened.get('ok') is not True:
                raise AssertionError('Synthetic file input activation failed')
            picker = host.wait(lambda rows: next((e for e in rows[before:] if e.get('event') == 'file-picker'), None))
            identifier = host.command('files', ticket=picker['ticket'], paths=[str(path)])
            applied = host.wait(lambda rows: next((e for e in rows if e.get('event') == 'reply' and e.get('id') == identifier), None))
            result['trusted_host_files_applied'] = (applied.get('ok') is True
                and applied.get('value', {}).get('files_applied') is True)
            if not result['trusted_host_files_applied']:
                raise AssertionError('Synthetic disk File handback failed')
            prefix = 'const file=__directInput.files[0];'
        else:
            prefix = 'const bytes=new Uint8Array('+str(size)+');bytes.fill(65);'
            if kind == 'memory-file':
                prefix += "const file=new File([bytes],'synthetic bytes.bin',{type:'application/octet-stream'});"
        if multipart:
            prefix += "const body=new FormData();body.append('file',file);"
        elif kind == 'text':
            prefix = "const body='A'.repeat("+str(size)+');'
        elif kind == 'disk-raw':
            prefix += 'const body=file;'
        else:
            prefix += 'const body=bytes;'
        target = '/large?direct='+('multipart' if multipart else 'raw')+'&bytes='+str(size)
        actual_file = multipart or kind == 'disk-raw'
        file_metadata = ',file_size:file.size,file_name:file.name,is_file:file instanceof File' if actual_file else ''
        script = '(async()=>{'+prefix+'const r=await fetch('+json.dumps(target)+",{method:'POST',body});return {status:r.status"+file_metadata+'}})()'
        reply = host.evaluate(script)
        result['reply_ok'] = reply.get('ok') is True
        result['status'] = reply.get('value', {}).get('status')
        if actual_file:
            result['renderer_file'] = {key: reply.get('value', {}).get(key) for key in ('file_size', 'file_name', 'is_file')}
        result['expected_payload_sha256'] = synthetic_digest(size)
        rows = [x for x in fixture.snapshot() if x['path'] == '/large']
        result['receiver_count'] = len(rows)
        result['passed'] = (result['reply_ok'] and result['status'] == 200 and len(rows) == 1
            and rows[0]['complete'] and rows[0]['framing_valid']
            and rows[0]['payload_bytes'] == size
            and rows[0]['payload_sha256'] == result['expected_payload_sha256']
            and (not actual_file or (result['renderer_file']['is_file'] is True
                                  and result['renderer_file']['file_size'] == size))
            and (rows[0]['authenticated'] if result['mode'] == 'local' else not rows[0]['has_token']))
    return action


def redirect_action(kind, popup):
    def action(host, fixture, foreign, result):
        if kind == 'blocked':
            identifier = host.command('policy', blocked_paths=['/probe'])
            policy = host.wait(lambda rows: next((e for e in rows if e.get('event') == 'reply' and e.get('id') == identifier), None))
            if policy.get('ok') is not True:
                raise AssertionError('Blocked-path policy was not acknowledged')
        # The request promise and optional popup share one task. No actual
        # dispatcher is installed; the reserved destination is never opened.
        script = ("(async()=>{const p=fetch('/redirect?kind="+kind+"');"+
                  ("window.open("+json.dumps(POPUP)+",'_blank','noopener,noreferrer');" if popup else '')+
                  "try{const r=await p;return {status:r.status,readable:true}}"
                  "catch(e){return {readable:false}}})()")
        result['popup'] = popup
        result['reply'] = host.evaluate(script)
        initial = [x for x in fixture.snapshot() if x['path'] == '/redirect']
        qualified = (len(initial) == 1 and initial[0]['status'] == 307
            and initial[0]['kind'] == kind
            and (initial[0]['authenticated'] if result['mode'] == 'local' else not initial[0]['has_token']))
        result['initial_redirect_qualified'] = qualified
        own = [x for x in fixture.snapshot() if x['path'] in ('/control', '/probe')]
        foreign_rows = foreign.snapshot()
        if kind == 'same':
            result['passed'] = (qualified and len(own) == 1 and own[0]['path'] == '/control' and not foreign_rows
                and (own[0]['authenticated'] if result['mode'] == 'local' else not own[0]['has_token']))
        else:
            result['passed'] = (qualified and not own and not foreign_rows
                and result['reply'].get('ok') is True
                and result['reply'].get('value', {}).get('readable') is False)
    return action


def pending_action(host, fixture, foreign, result):
    # Covers host shutdown with an outstanding network response. It does not
    # simulate a CDP handler stopped before its continue/fail decision.
    reply = host.evaluate("(()=>{window.__held=fetch('/held').then(()=>true,()=>false);return true})()")
    result['started'] = reply.get('ok') is True and reply.get('value') is True
    result['receiver_started'] = fixture.received.wait(5)
    start = time.monotonic()
    host.close()
    result['host_closed_by_action'] = True
    result['close_seconds'] = time.monotonic()-start
    result['response_released_before_close'] = fixture.release.is_set()
    result['passed'] = result['started'] and result['receiver_started'] and not fixture.release.is_set()


def pending_scan_action(size):
    def action(host, fixture, foreign, result):
        # Diagnostic-only event is supplied by copied host50, never by the
        # normal application's public surface. No pause/delay API is added.
        from tests.webview2.host_security import job_children
        from tests.windows.normal_processes import identity, alive
        observed = []
        for pid in job_children():
            try:
                observed.append(dict(pid=pid, **identity(pid)))
            except OSError:
                pass
        time.sleep(2.1)
        baseline = len(host.events)
        script = ("(()=>{const bytes=new Uint8Array("+str(size)+");bytes.fill(65);"
            "const body=new FormData();body.append('file',new File([bytes],'synthetic pending.bin'));"
            "window.__pendingScan=fetch('/large?direct=multipart&bytes="+str(size)+"',{method:'POST',body}).catch(()=>false);return true})()")
        identifier = host.command('eval', script=script, world=0)
        received = host.wait(lambda rows: next((e for e in rows[baseline:]
            if e.get('event') == 'diagnostic-fetch-envelope' and e.get('stage') == 'received'
            and e.get('envelope_chars', 0) > 16*1024*1024), None), 25)
        result['envelope_chars'] = received['envelope_chars']
        result['eval_command_id'] = identifier
        close_id = host.command('close')
        host.proc.wait(timeout=25)
        host.reader.join(5)
        events = list(host.events)[baseline:]
        close_index = next((i for i, e in enumerate(events) if e.get('event') == 'reply'
                            and e.get('id') == close_id and e.get('ok') is True), None)
        parsed = next((i for i, e in enumerate(events) if e.get('event') == 'diagnostic-fetch-envelope'
                       and e.get('stage') == 'parsed' and e.get('envelope_chars') == received['envelope_chars']), None)
        result['close_ack_index'] = close_index
        result['large_parse_index'] = parsed
        result['close_preceded_decision_evidence'] = close_index is not None and (parsed is None or close_index < parsed)
        result['decision_events_after_close'] = ([e for e in events[close_index+1:]
            if e.get('event') == 'diagnostic-fetch'] if close_index is not None else [])
        result['observed_before_close'] = observed
        host.close()
        result['host_closed_by_action'] = True
        result['observed_survivors_after_close'] = [row['pid'] for row in observed if alive(row['pid'], row['start'])]
        result['receiver_count'] = len([r for r in fixture.snapshot() if r['path'] == '/large'])
        result['passed'] = (result['close_preceded_decision_evidence']
            and not result['decision_events_after_close'] and not result['observed_survivors_after_close']
            and result['receiver_count'] == 0)
        result['scope'] = 'Native close during pending metadata/decision; worker parse completion itself may be unobserved after process exit'
    return action


def context_cases(executable, output):
    """Reuse independently established context payloads; no OOPIF claim."""
    definitions = []
    for action in ('fetch', 'form', 'get-top'):
        name = 'opaque-'+action
        definitions.append((name, lambda name=name, action=action: exercise(
            executable, output, name, frame_script('sandbox', name, action), mode='server', positive=True)))
    for kind in ('same', 'sandbox', 'srcdoc', 'data', 'blob'):
        for action in ('fetch', 'form', 'get-top'):
            name = kind+'-'+action
            definitions.append((name, lambda name=name, kind=kind, action=action: exercise(
                executable, output, name, frame_script(kind, name, action))))
    for kind, operation in (
            ('dedicated', "new Worker('/worker.js')"),
            ('shared', "new SharedWorker('/worker.js')"),
            ('service', "await navigator.serviceWorker.register('/worker.js')")):
        script = "try{"+operation+"}catch(e){await fetch('/outcome?case="+kind+"')}"
        definitions.append(('local-'+kind, lambda kind=kind, script=script: exercise(
            executable, output, 'local-'+kind, script)))
        definitions.append(('server-'+kind, lambda kind=kind: websocket_check(
            executable, output, 'server', 'ws', kind, case_name='server-'+kind, expect_worker_csp=True)))
    for name, operation in definitions:
        try:
            result = operation()
            result['diagnostic_completed'] = True
        except Exception as exc:
            result = {'case': name, 'passed': False, 'error_type': type(exc).__name__,
                      'diagnostic_completed': False}
        result['oopif_established'] = False
        yield result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('local', 'server', 'both'), default='both')
    parser.add_argument('--case', choices=('large', 'direct', 'redirect', 'pending-close', 'pending-scan-close', 'contexts', 'all'), default='large')
    parser.add_argument('--size-mib', type=int, default=20)
    parser.add_argument('--direct-kind', choices=('all', 'text', 'binary', 'memory-file', 'disk-file', 'disk-raw'), default='all')
    parser.add_argument('--only-large', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt' or not 1 <= args.size_mib <= 256:
        raise ValueError('Native Windows control; maximum synthetic payload256MiB')
    from desktop.windows_processes import own_launcher
    from desktop.windows_files import assert_path
    from package_windows_webview2.build import verify_host
    executable, output = args.host.absolute(), args.output.absolute()
    assert_path(executable, leaf=True)
    if not executable.is_relative_to(AREA) or executable.name != 'DLMS-WebView2-Host.exe':
        raise ValueError('Explicit inventoried project-local host required')
    verify_host(executable.parent)
    own_launcher()
    fresh(output)
    results = []
    try:
        if args.case in ('contexts', 'all'):
            for result in context_cases(executable, output):
                results.append(result)
                print(json.dumps({key: result.get(key) for key in ('mode', 'name', 'case', 'diagnostic_completed', 'passed', 'error_type')}), flush=True)
        for mode in ('local', 'server') if args.mode == 'both' else (args.mode,):
            definitions = []
            if args.case in ('large', 'all'):
                for size in (1024, 1024*1024, args.size_mib*1024*1024):
                    for multipart in (False, True):
                        definitions.append(('large-'+str(size)+('-file' if multipart else '-raw'), large_action(size, multipart)))
            if args.case == 'direct':
                for size in ((args.size_mib*1024*1024,) if args.only_large else (1024, args.size_mib*1024*1024)):
                    for kind in (('text', 'binary', 'memory-file', 'disk-file', 'disk-raw') if args.direct_kind == 'all' else (args.direct_kind,)):
                        definitions.append(('direct-'+str(size)+'-'+kind, direct_action(size, kind)))
            if args.case in ('redirect', 'all'):
                for kind in ('same', 'foreign', 'blocked'):
                    for popup in (False, True):
                        definitions.append(('redirect-'+kind+('-popup' if popup else ''), redirect_action(kind, popup)))
            if args.case in ('pending-close', 'all'):
                definitions.append(('pending-close', pending_action))
            if args.case == 'pending-scan-close':
                definitions.append(('pending-scan-close', pending_scan_action(args.size_mib*1024*1024)))
            for name, action in definitions:
                result = run_case(executable, output, mode, name, action)
                results.append(result)
                print(json.dumps({key: result.get(key) for key in ('mode', 'case', 'diagnostic_completed', 'passed', 'error_type')}), flush=True)
    finally:
        (output/'result.json').write_text(json.dumps({
            'host_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'normal_package': False, 'diagnostic_only': True,
            'body_or_token_values_logged': False, 'cases': results,
        }, indent=2)+'\n')


if __name__ == '__main__':
    main()
