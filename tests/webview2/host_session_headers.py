"""Synthetic cookie/custom-header fidelity through native request policy.

Cookie and header values exist only in fixture memory/HTTP; receipts retain
presence/equality booleans. No Basic Auth challenge or browser dispatch exists.
"""
from __future__ import annotations

import argparse
import hashlib
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import secrets
import threading
import time

from tests.webview2.host_security import AREA, Fixture, Handler, Host, fresh
from tests.webview2.host_popup_requests import POPUP

COOKIE = 'SyntheticSession'


class SessionHandler(Handler):
    def do_GET(self):
        path = self.path
        if path == '/cookie-gate':
            ready = self.server.release.wait(20)
            return self.respond(200 if ready else 504, b'synthetic gate')
        if path == '/cookie-seed':
            self.send_response(200)
            self.send_header('Set-Cookie', COOKIE+'='+self.server.initial_cookie+'; Path=/; HttpOnly; SameSite=Strict; Max-Age=600')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if path in ('/cookie-check-seed', '/cookie-redirect', '/cookie-hop', '/cookie-check-updated', '/cookie-persist'):
            parsed = SimpleCookie()
            parsed.load(self.headers.get('Cookie', ''))
            value = parsed.get(COOKIE)
            expected = self.server.initial_cookie if path in ('/cookie-check-seed', '/cookie-redirect') else self.server.updated_cookie
            credential = self.headers.get('X-DLMS-Desktop-Token')
            with self.server.lock:
                self.server.rows.append({'path': path, 'method': 'GET',
                    'cookie_present': value is not None,
                    'cookie_matches': value is not None and value.value == expected,
                    'authorization_present': self.headers.get('Authorization') is not None,
                    'authorization_matches': self.headers.get('Authorization') == self.server.authorization,
                    'session_header_present': self.headers.get('X-Session') is not None,
                    'session_header_matches': self.headers.get('X-Session') == self.server.session_header,
                    'has_token': credential is not None,
                    'authenticated': credential == self.server.token})
            if path == '/cookie-redirect':
                self.send_response(307)
                self.send_header('Set-Cookie', COOKIE+'='+self.server.updated_cookie+'; Path=/; HttpOnly; SameSite=Strict; Max-Age=600')
                self.send_header('Location', '/cookie-hop')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            return self.respond(200, b'{"ok":true}', 'application/json')
        return super().do_GET()

    def respond(self, status, body, kind='text/plain'):
        if self.path == '/':
            body, kind = self.server.html, 'text/html; charset=utf-8'
        return super().respond(status, body, kind)


class SessionFixture(Fixture):
    def __init__(self, token, mode, popup):
        super().__init__(token, policy=mode == 'local')
        self.RequestHandlerClass = SessionHandler
        self.initial_cookie, self.updated_cookie = secrets.token_hex(24), secrets.token_hex(24)
        self.authorization = 'Bearer '+secrets.token_hex(24)
        self.session_header = secrets.token_hex(24)
        self.release = threading.Event()
        self.popup = popup
        self.set_html(False)

    def set_html(self, reopen):
        headers = json.dumps({'Authorization': self.authorization, 'X-Session': self.session_header})
        if reopen:
            action = 'fetch("/cookie-persist",{headers}).then(()=>fetch("/cookie-reopen-terminal"));'
        else:
            action = ('const work=Promise.resolve().then(()=>fetch("/cookie-check-seed",{headers}))'
                '.then(()=>fetch("/cookie-redirect",{headers}))'
                '.then(()=>fetch("/cookie-check-updated",{headers}))'
                '.then(()=>fetch("/cookie-terminal"));'+
                ('window.open('+json.dumps(POPUP)+',"_blank","noopener,noreferrer");' if self.popup else ''))
        prefix = '' if reopen else 'fetch("/cookie-seed").then(()=>'
        suffix = '' if reopen else ')'
        script = 'const headers='+headers+';'+prefix+'fetch("/cookie-gate").then(r=>{if(!r.ok)throw Error("gate");'+action+'})'+suffix+';'
        self.html = ('<!doctype html><title>Synthetic session fidelity</title><body>Neutral<script>'+script+'</script>').encode()


def run(executable, output, mode, popup):
    label = mode+('-popup' if popup else '-no-popup')
    case = fresh(output/label)
    fixture = SessionFixture(secrets.token_hex(32), mode, popup).start()
    host, result = None, {'mode': mode, 'popup': popup, 'source_only': True,
        'physical_acceptance': False, 'cookie_or_header_values_logged': False,
        'diagnostic_completed': False, 'passed': False, 'launches': []}
    try:
        host = Host(executable, case, fixture, mode)
        host.loaded()
        storage = host.storage
        time.sleep(2.1)
        fixture.release.set()
        host.wait(lambda _: any(r['path'] == '/cookie-terminal' for r in fixture.snapshot()), 20)
        hidden = host.evaluate('!document.cookie.split(";").some(s=>s.trim().startsWith("SyntheticSession="))')
        result['http_only_invisible_to_page'] = hidden.get('ok') is True and hidden.get('value') is True
        host.close()
        result['launches'].append(json.loads((case/'cleanup.json').read_text()))
        host = None
        fixture.release.clear()
        fixture.set_html(True)
        reopen = fresh(output/(label+'-reopen'))
        host = Host(executable, reopen, fixture, mode, reuse_storage=storage)
        host.loaded()
        time.sleep(2.1)
        fixture.release.set()
        host.wait(lambda _: any(r['path'] == '/cookie-reopen-terminal' for r in fixture.snapshot()), 20)
        rows = [r for r in fixture.snapshot() if 'cookie_matches' in r]
        expected = {'/cookie-check-seed', '/cookie-redirect', '/cookie-hop', '/cookie-check-updated', '/cookie-persist'}
        result['receipt_paths'] = [r['path'] for r in rows]
        result['passed'] = (len(rows) == len(expected) and {r['path'] for r in rows} == expected
            and all(r['cookie_matches'] and r['authorization_matches'] and r['session_header_matches']
                    and (r['authenticated'] if mode == 'local' else not r['has_token']) for r in rows)
            and result['http_only_invisible_to_page'])
        result['diagnostic_completed'] = True
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    finally:
        fixture.release.set()
        try:
            if host is not None:
                host.close()
                result['launches'].append(json.loads((host.case/'cleanup.json').read_text()))
        finally:
            result['requests'] = fixture.snapshot()
            fixture.close()
            (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise ValueError('Native Windows source-only control')
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
        for mode in ('local', 'server'):
            for popup in (False, True):
                result = run(executable, output, mode, popup)
                results.append(result)
                print(json.dumps({k: result.get(k) for k in ('mode', 'popup', 'diagnostic_completed', 'passed', 'error_type')}), flush=True)
    finally:
        (output/'result.json').write_text(json.dumps({'diagnostic_only': True,
            'host_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'cookie_or_header_values_logged': False, 'cases': results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
