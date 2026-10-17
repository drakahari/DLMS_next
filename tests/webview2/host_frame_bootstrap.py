"""Forbidden frame bootstrap around popup; no permitted foreign-frame policy.

Page-owned action follows native completion plus a2.1s HTTP gate. No input/eval
is in flight during action. A later bounded DOM read verifies the parent ran;
Local frame revocation can legitimately refuse its HTTP terminal marker. This
does not establish interception coverage inside an actual OOPIF.
"""
from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import secrets
import threading
import time

from tests.webview2.host_security import AREA, Fixture, Handler, Host, fresh
from tests.webview2.host_popup_requests import POPUP


class FrameHandler(Handler):
    def respond(self, status, body, kind='text/plain'):
        if self.path == '/':
            body, kind = self.server.html, 'text/html; charset=utf-8'
        elif self.path == '/opaque-child':
            body, kind = self.server.child_html, 'text/html; charset=utf-8'
        elif self.path == '/frame-gate':
            if not self.server.release.wait(15):
                status = 504
            body = b'synthetic frame gate'
        return super().respond(status, body, kind)


class FrameFixture(Fixture):
    def __init__(self, token, foreign_origin, mode, kind, popup):
        super().__init__(token, policy=mode == 'local')
        self.RequestHandlerClass = FrameHandler
        self.release = threading.Event()
        target = json.dumps(foreign_origin+'/forbidden-child')
        child = ('<script>fetch('+target+', {mode:"no-cors"}).finally(()=>'
                 'parent.postMessage("synthetic-child-complete","*"));</script>')
        self.child_html = ('<!doctype html>'+child).encode()
        assign = ('f.src='+target+';' if kind == 'foreign' else
                  'f.sandbox="allow-scripts";f.src="/opaque-child";')
        script = ('window.__frameState={started:false,attached:false,complete:false,child:false};'
            'addEventListener("message",e=>{if(e.data==="synthetic-child-complete")__frameState.child=true});'
            'fetch("/frame-gate").then(r=>{if(!r.ok)throw Error("gate");'
            '__frameState.started=true;const f=document.createElement("iframe");'+assign+
            'document.body.append(f);__frameState.attached=f.isConnected;'+
            ('window.open('+json.dumps(POPUP)+',"_blank","noopener,noreferrer");' if popup else '')+
            'setTimeout(()=>{__frameState.complete=true;fetch("/frame-terminal").catch(()=>{});},1000);});')
        self.html = ('<!doctype html><title>Neutral forbidden frame fixture</title><body>Neutral'
                     '<script>'+script+'</script></body>').encode()


def targets(host):
    identifier = host.command('diagnostic-targets')
    reply = host.wait(lambda rows: next((e for e in rows if e.get('event') == 'reply' and e.get('id') == identifier), None))
    return {'available': reply.get('ok') is True, 'value': reply.get('value') if reply.get('ok') else None,
            'error_type': reply.get('value', {}).get('type') if not reply.get('ok') and isinstance(reply.get('value'), dict) else None}


def run(executable, output, mode, kind, popup, inventory=False):
    label = mode+'-'+kind+('-popup' if popup else '-no-popup')
    case = fresh(output/label)
    foreign = Fixture(secrets.token_hex(32)).start()
    cross_site = foreign.origin.replace('127.0.0.1', 'localhost')
    fixture = FrameFixture(secrets.token_hex(32), cross_site, mode, kind, popup).start()
    host = None
    result = {'mode': mode, 'kind': kind, 'popup': popup, 'source_only': True,
              'actual_oopif_coverage': False, 'physical_acceptance': False,
              'input_or_eval_in_flight_during_action': False, 'diagnostic_completed': False, 'passed': False}
    try:
        # Prove the same localhost alias resolves to the owned receiver. The
        # baseline request is excluded from forbidden-frame observations.
        connection = HTTPConnection('localhost', foreign.server_port, timeout=5)
        try:
            connection.request('GET', '/reachable')
            response = connection.getresponse()
            result['cross_site_receiver_reachable'] = response.status == 200
            response.read()
        finally:
            connection.close()
        baseline = len(foreign.snapshot())
        host = Host(executable, case, fixture, mode)
        host.loaded()
        result['targets_before'] = targets(host) if inventory else {'available': False, 'requested': False}
        finished = time.monotonic()
        time.sleep(2.1)
        result['seconds_after_native_finish_before_release'] = time.monotonic()-finished
        fixture.release.set()
        # No evaluation/input command spans the HTML action. Only after its
        # bounded terminal timer has elapsed do we read the parent state.
        time.sleep(3)
        state = host.evaluate('window.__frameState')
        result['parent_terminal'] = state.get('value') if state.get('ok') else None
        result['targets_after'] = targets(host) if inventory else {'available': False, 'requested': False}
        outside = foreign.snapshot()[baseline:]
        result['foreign_requests'] = outside
        children = [r for r in fixture.snapshot() if r['path'] == '/opaque-child']
        result['opaque_child_bootstrap'] = children
        result['http_terminal_observed'] = any(r['path'] == '/frame-terminal' for r in fixture.snapshot())
        parent = result['parent_terminal'] or {}
        result['passed'] = (result['cross_site_receiver_reachable'] and parent.get('started') is True
            and parent.get('attached') is True and parent.get('complete') is True and not outside
            and (not (mode == 'server' and kind == 'opaque') or
                 (parent.get('child') is True and len(children) == 1 and not children[0]['has_token'])))
        result['diagnostic_completed'] = True
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    finally:
        fixture.release.set()
        try:
            if host is not None:
                host.close()
                result['cleanup'] = json.loads((case/'cleanup.json').read_text())
        finally:
            result['requests'] = fixture.snapshot()
            result['host_events'] = list(host.events) if host is not None else []
            fixture.close()
            foreign.close()
            (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('both', 'local', 'server'), default='both')
    parser.add_argument('--kind', choices=('all', 'foreign', 'opaque'), default='all')
    parser.add_argument('--target-inventory', action='store_true', help='Copied diagnostic host only; no normal application API')
    args = parser.parse_args()
    if os.name != 'nt':
        raise ValueError('Native Windows synthetic source-only control')
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
        for mode in ('local', 'server') if args.mode == 'both' else (args.mode,):
            for kind in ('foreign', 'opaque') if args.kind == 'all' else (args.kind,):
                for popup in (False, True):
                    result = run(executable, output, mode, kind, popup, args.target_inventory)
                    results.append(result)
                    print(json.dumps({k: result.get(k) for k in ('mode', 'kind', 'popup', 'diagnostic_completed', 'passed', 'error_type')}), flush=True)
    finally:
        (output/'result.json').write_text(json.dumps({'diagnostic_only': True,
            'host_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'actual_oopif_coverage': False, 'cases': results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
