"""Actual WebView2 synthetic Server lifecycle; instrumented, not physical acceptance.

Only the owning anonymous-pipe CDP evaluator supplies synthetic user activation.
No OS input, browser permission relaxation, production endpoint or owner profile.
"""
import argparse
import ctypes
from ctypes import wintypes
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

from tests.server_mode.gui_text_download import Handler, PAYLOAD


class ServerFixture(Handler):
    requests = []
    slow_arrived, slow_release, broken_release = threading.Event(), threading.Event(), threading.Event()

    def record(self):
        self.requests.append({'method': self.command, 'path': self.path,
                              'desktop_token_present': bool(self.headers.get('X-DLMS-Desktop-Token'))})

    def html(self, body, status=200):
        encoded = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Referrer-Policy', 'same-origin')
        self.end_headers(); self.wfile.write(encoded)

    def do_GET(self):
        self.record()
        if self.path == '/slow':
            self.slow_arrived.set(); self.slow_release.wait(12)
            self.html('<html><body id="slow-complete">Synthetic slow response</body></html>'); return
        if self.path == '/certifications':
            self.html('<html><body><form method="post" action="/certifications/validate"><input name="title" value=""><button>Submit synthetic invalid form</button></form></body></html>'); return
        if self.path == '/export/held-broken.txt':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Disposition', 'attachment; filename=interrupted-reference.txt')
            self.send_header('Content-Length', str(len(PAYLOAD) + 1000))
            self.end_headers(); self.wfile.write(PAYLOAD); self.wfile.flush()
            self.broken_release.wait(12); self.close_connection = True; return
        return super().do_GET()

    def do_POST(self):
        self.record()
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        if self.path == '/certifications/validate':
            self.html('<html><body><h1 id="validation-error">Synthetic certification title is required</h1><form method="post" action="/certifications/validate"><input name="title"><button>Try again</button></form></body></html>', 400)
        else: self.send_error(404)


def until(q, predicate, description, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result: return result
        q.delay(.06)
    raise TimeoutError(description)


def native_cover_hit(window):
    """Hit-test actual Windows child HWND z-order, including disabled children."""
    from PySide6.QtCore import QPoint
    user = ctypes.windll.user32
    child_at = user.ChildWindowFromPointEx
    child_at.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
    child_at.restype = wintypes.HWND
    user.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user.ScreenToClient.restype = wintypes.BOOL
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.restype = ctypes.c_int
    point = window.server_status.mapToGlobal(QPoint(window.server_status.width()//2, window.server_status.height()//2))
    native_state = getattr(window.view, 'server_cover_state', {})
    parent = int(window.winId())
    cover = int(native_state.get('hwnd') or window.server_status.winId())
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindowVisible.restype = wintypes.BOOL
    chain = []
    for _ in range(12):
        text = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(wintypes.HWND(parent), text, len(text))
        chain.append({'hwnd': parent, 'class': text.value})
        local = wintypes.POINT(point.x(), point.y())
        if not user.ScreenToClient(wintypes.HWND(parent), ctypes.byref(local)): break
        child = child_at(wintypes.HWND(parent), local, 1)  # skip invisible; retain disabled
        if not child or int(child) == parent: break
        parent = int(child)
    return {'cover_hwnd': cover, 'hit_chain': chain, 'cover_hit': any(x['hwnd'] == cover for x in chain),
            'view_visible': window.view.isVisible(), 'cover_visible': bool(user.IsWindowVisible(wintypes.HWND(cover))),
            'host_cover_state': native_state,
            'point_screen': [point.x(), point.y()]}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--profile', required=True)
    parser.add_argument('--case', choices=('full', 'repeat', 'cancel', 'interrupted', 'pages'), default='full')
    args = parser.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    from desktop.isolation import profile_paths
    if profile_paths(args.profile, create=False)['root'].exists():
        raise ValueError('Choose a new disposable profile; prior evidence is never reused')
    from desktop.webview2_shell import DesktopWindow
    from desktop.webview2_browser import View
    import desktop.shell
    desktop.shell.DesktopWindow = DesktopWindow
    protocol = []
    original_event = View._event
    def traced(view, event):
        if event.get('event') != 'reply' and len(protocol) < 8192: protocol.append(dict(event))
        return original_event(view, event)
    View._event = traced
    from desktop.server_mode import configured_server, write_config, read_config
    from tests.gate1.qt_checks import QtChecks
    from PySide6.QtCore import QUrl
    server = ThreadingHTTPServer(('127.0.0.2', 0), ServerFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    q, stopped = None, False
    report = {'profile': args.profile, 'case': args.case, 'source_instrumented': True, 'normal_package': False,
              'physical_acceptance': False, 'passed': False, 'stage': 'startup'}
    cover_failures = []
    try:
        q = QtChecks(args.profile, automated=True)
        local_storage = q.window.view.runtime_info['storage']
        local_sentinel = q.paths['backend'] / 'webview2-synthetic-sentinel.txt'
        local_sentinel.write_bytes(b'synthetic Local state; must survive Server tests\r\n')
        q.js("localStorage.setItem('wv-server-local-sentinel','synthetic-local');true")
        local_downloads_before = sorted(str(p) for p in q.paths['downloads'].rglob('*'))
        origin = f'http://127.0.0.2:{server.server_port}'
        config = dict(q.window.mode_config, server=configured_server(q.window.mode_config, origin, 'Synthetic WebView2 Server', private_http_opt_in=True))
        write_config(args.profile, config); q.window.mode_config = config
        assert q.window.switch_to_server()

        def ready(path=None):
            return (q.window.view is not None and not q.window.view.page().isLoading()
                    and q.window._server_page_exposed and not q.window.server_unreachable
                    and (path is None or q.window.view.url().path() == path))
        until(q, lambda: ready('/'), 'Initial Server page did not become usable')
        q.wait("document.readyState==='complete' && Boolean(document.querySelector('#download'))")
        assert q.window.backend is None
        assert q.window.mode == read_config(args.profile)['mode'] == 'server'
        assert q.window.view.runtime_info['storage'] != local_storage
        assert q.js("localStorage.getItem('wv-server-local-sentinel')") is None
        q.js("localStorage.setItem('wv-server-remote-sentinel','synthetic-server');true")
        before_document = q.js('performance.timeOrigin')
        report['storage_isolation'] = True

        def click(selector, setup=None):
            if setup: q.js(setup)
            encoded = json.dumps(selector)
            q.js('document.querySelector(' + encoded + ").scrollIntoView({block:'center'});true")
            point = json.loads(q.js('JSON.stringify((()=>{const r=document.querySelector(' + encoded + ').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())'))
            # Actual renderer-local CDP Input mouse events, routed only through
            # the owned pipe. No OS input or browser permission grant.
            q.window.view.command('click', x=point['x'], y=point['y'])

        report['stage'] = 'repeated-attachment'
        paths, declined = [], []
        for route in (('/export/all_quizzes.txt', '/export/all_quizzes.txt', '/redirect/attachment')
                      if args.case in ('full', 'repeat') else ()):
            index = len(q.window.download_results)
            event_start = len(protocol)
            click('#download', "document.querySelector('#download').href=" + json.dumps(route) + ';true')
            until(q, lambda: (len(q.window.download_results) > index and q.window.download_results[index]['state'] != 'in_progress')
                  or any(e.get('event') == 'attachment-declined' for e in protocol[event_start:]), 'Attachment did not reach a terminal state')
            until(q, lambda: ready(), 'Attachment did not restore the same Server document')
            refused = [e for e in protocol[event_start:] if e.get('event') == 'attachment-declined']
            if refused:
                assert len(q.window.download_results) == index
                assert before_document == q.js('performance.timeOrigin')
                assert 'declined' in q.window.statusBar().currentMessage()
                declined.append({'route': route, 'reason': refused[-1]['reason'], 'page_preserved': True,
                                 'new_file_published': False})
                continue
            record = q.window.download_results[index]
            assert record['state'] == 'completed', record
            target = Path(record['path']); assert target.read_bytes() == PAYLOAD
            assert before_document == q.js('performance.timeOrigin')
            paths.append(target)
        if args.case in ('full', 'repeat'):
            assert len(set(paths)) == len(paths) and all(p.read_bytes() == PAYLOAD for p in paths)
            report['repeated_and_redirected_attachments_preserve_document'] = len(paths) == 3
            report['completed_attachment_count'], report['declined_attachments'] = len(paths), declined

        report['stage'] = 'cancel'
        cancel_next = [True]
        def cancelled(request):
            if cancel_next[0]: cancel_next[0] = False; request.cancel()
        if args.case in ('full', 'cancel'):
            q.window.profile.downloadRequested.connect(cancelled)
            index = len(q.window.download_results)
            click('#download', "document.querySelector('#download').href='/export/all_quizzes.txt';true")
            until(q, lambda: len(q.window.download_results) > index and q.window.download_results[index]['state'] == 'cancelled', 'Cancelled attachment did not reach terminal state')
            q.window.profile.downloadRequested.disconnect(cancelled)
            until(q, lambda: ready(), 'Cancelled attachment lost Server page')
            assert not Path(q.window.download_results[index]['path']).exists()
            report['cancel_no_publication'] = True

        report['stage'] = 'interrupted-feedback'
        accelerated = []
        def shorten_watchdog(request):
            if request.url().path() == '/export/held-broken.txt':
                request.timer.setInterval(2500)
                accelerated.append(request)
        if args.case in ('full', 'interrupted'):
            q.window.profile.downloadRequested.connect(shorten_watchdog)
            index = len(q.window.download_results)
            click('#download', "document.querySelector('#download').href='/export/held-broken.txt';true")
            until(q, lambda: len(q.window.download_results) > index, 'Interrupted transfer was not requested')
            q.window.view.setUrl(QUrl(origin + '/next'))
            until(q, lambda: ready('/next'), 'New Server navigation did not finish before old transfer timeout')
            newer = q.window.statusBar().currentMessage()
            until(q, lambda: q.window.download_results[index]['state'] != 'in_progress', 'Interrupted transfer remained in progress', 12)
            assert q.window.download_results[index]['state'] == 'failed'
            assert not Path(q.window.download_results[index]['path']).exists()
            assert q.window.statusBar().currentMessage() == newer
            q.window.profile.downloadRequested.disconnect(shorten_watchdog)
            ServerFixture.broken_release.set()
            report['interrupted_terminal_preserves_newer_feedback'] = {'passed': True, 'instrumented_watchdog_ms': 2500,
                                                                     'default_120_second_timeout_not_measured': True}

        report['stage'] = 'validation-400'
        q.window.view.setUrl(QUrl(origin + '/certifications'))
        until(q, lambda: ready('/certifications'), 'Synthetic certification form did not load')
        click('form button')
        until(q, lambda: ready('/certifications/validate') and q.window.view.page().last_http_status == 400, 'Validation response was hidden as outage')
        q.wait("Boolean(document.querySelector('#validation-error'))")
        assert q.window.settings_panel is None and not q.window._settings_ready()
        assert q.window.backend is None and not q.window.server_unreachable
        report['real_http400_visible_without_native_settings'] = True

        report['stage'] = 'native-cover'
        q.window.view.setUrl(QUrl(origin + '/slow'))
        until(q, lambda: ServerFixture.slow_arrived.is_set() and q.window.view.page().isLoading(), 'Slow route did not begin')
        q.delay(.2)
        cover = native_cover_hit(q.window); report['loading_native_cover'] = cover
        if not (cover['cover_hit'] and cover['cover_visible'] and cover['view_visible']):
            cover_failures.append('loading')
        ServerFixture.slow_release.set()
        until(q, lambda: ready('/slow'), 'Slow route did not reveal after release')

        report['stage'] = '503'
        q.window.view.setUrl(QUrl(origin + '/unavailable'))
        until(q, lambda: q.window.server_unreachable and not q.window._server_page_exposed, 'Real HTTP503 did not show unavailable')
        assert q.window.backend is None and q.window.mode == 'server'
        cover = native_cover_hit(q.window); report['outage_native_cover'] = cover
        if not (cover['cover_hit'] and cover['cover_visible']): cover_failures.append('outage')
        report['http503_no_local_fallback'] = True

        report['stage'] = 'unreachable'
        server.shutdown(); server.server_close(); thread.join(timeout=5); stopped = True
        q.window._retry_server()
        until(q, lambda: not q.window.view.page().isLoading() and q.window.server_unreachable, 'Unreachable endpoint did not terminate with unavailable')
        assert q.window.mode == read_config(args.profile)['mode'] == 'server' and q.window.backend is None
        assert sorted(str(p) for p in q.paths['downloads'].rglob('*')) == local_downloads_before
        report['unreachable_no_local_fallback'] = True

        report['stage'] = 'explicit-return-local'
        assert q.window.switch_to_local()
        q.wait("document.readyState==='complete' && Boolean(document.querySelector('.dashboard-sidebar'))", 35)
        until(q, lambda: not q.window.view.page().isLoading(), 'Local return did not finish')
        assert q.window.mode == read_config(args.profile)['mode'] == 'local'
        assert q.js("localStorage.getItem('wv-server-local-sentinel')") == 'synthetic-local'
        assert q.js("localStorage.getItem('wv-server-remote-sentinel')") is None
        assert local_sentinel.read_bytes() == b'synthetic Local state; must survive Server tests\r\n'
        assert q.window.view.runtime_info['storage'] == local_storage
        assert not any(r['desktop_token_present'] for r in ServerFixture.requests)
        report['explicit_local_return_preserves_data_and_separate_storage'] = True
        report['native_cover_failures'] = cover_failures
        report['passed'], report['stage'] = not bool(declined or cover_failures), 'complete'
    except BaseException as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        ServerFixture.slow_release.set(); ServerFixture.broken_release.set()
        report['requests'], report['events'] = ServerFixture.requests, protocol
        if q is not None:
            report['status_message'] = q.window.statusBar().currentMessage()
            report['downloads'] = q.window.download_results
            q.close(); q.delay(.4)
            report['close_complete'] = q.window._close_complete
            (q.paths['root'] / 'webview2-server-lifecycle.json').write_text(json.dumps(report, indent=2) + '\n')
        if not stopped:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
        print(json.dumps({k:v for k,v in report.items() if k not in ('events', 'requests')}, indent=2), flush=True)
    assert report['passed'] and report['close_complete']


if __name__ == '__main__': main()
