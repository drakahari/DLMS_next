"""Task-owned synthetic WebEngine navigation; no desktop-wide input."""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlsplit
from desktop.isolation import isolated_environment, profile_paths
from desktop.server_mode import configured_server, default_config, write_config
from desktop.settings_surface import THEME_REGISTRY


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    entered, release = threading.Event(), threading.Event()
    second_entered, second_release = threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == '/slow':
                entered.set()
                release.wait(15)
            if parsed.path == '/slow-second':
                second_entered.set(); second_release.wait(15)
            if parsed.path in ['/redirect', '/escape']:
                self.send_response(302)
                self.send_header('Location', '/certifications' if parsed.path == '/redirect'
                                 else f'http://127.0.0.1:{self.server.server_port}/wrong')
                self.end_headers(); return
            if parsed.path == '/slow-image':
                entered.set(); release.wait(15)
                body=b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
                self.send_response(200);self.send_header('Content-Type','image/svg+xml');self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError):pass
                return
            if parsed.path == '/failure':
                self.connection.shutdown(2); self.connection.close(); return
            theme = parse_qs(parsed.query).get('theme', ['ethereal'])[0]
            theme = theme if theme in THEME_REGISTRY else 'light'
            p = THEME_REGISTRY[theme]['colors']
            body = f'''<!doctype html><html><style>body{{background:{p['body_base']};color:{p['page']};font:18px sans-serif;margin:40px}}a{{color:{p['accent_text']}}}</style>
            <div class="dashboard-sidebar" data-theme="{theme}"></div><h1>Synthetic Server: {theme}</h1><p>{parsed.path}</p>
            <a href="/history">Exam History</a> · <a href="/certifications">My Certifications</a> · <a href="/it">IT Study</a> · <a href="/study-packs">Study Packs</a></html>'''.encode()
            if parsed.path == '/tail':body=body.replace(b'</html>',b'<img src="/slow-image"></html>')
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError): pass
    server = ThreadingHTTPServer(('127.0.0.2', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    paths = profile_paths(args.profile)
    config = default_config(args.profile)
    config['server'] = configured_server(config, f'http://127.0.0.2:{server.server_port}', 'Synthetic navigation', private_http_opt_in=True)
    config['mode'] = 'server'; write_config(args.profile, config)
    env = isolated_environment(paths); os.environ.clear(); os.environ.update(env)
    os.environ['DLMS_DESKTOP_AUTOMATED'] = '1'
    from PySide6.QtCore import QUrl, Qt
    from PySide6.QtWidgets import QApplication
    from desktop.identity import configure_application_identity
    from desktop.shell import DesktopWindow
    app = QApplication([]); configure_application_identity(app)
    window = DesktopWindow(paths, args.profile); window.resize(1000, 720); window.show()
    def wait(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate(): return
            time.sleep(.02)
        raise AssertionError('Timed out awaiting synthetic navigation checkpoint')
    def go(path):
        window.view.setUrl(QUrl(config['server']['origin'] + path))
        wait(lambda: not window.view.page().isLoading() and window.view.isVisible()
             and window.view.url().path() == urlsplit(path).path)
        wait(lambda: window._mode_theme == parse_qs(urlsplit(path).query).get('theme', ['ethereal'])[0])
    report = {}
    try:
        window.start()
        if hasattr(window,'_server_page_exposed'):
            assert not window._server_page_exposed and not window.view.isEnabled()
            assert window.view.focusPolicy()==Qt.FocusPolicy.NoFocus
        if not args.baseline:
            assert window.view.page().backgroundColor().name() == '#20252c'
        wait(lambda: window.view is not None and window.view.isVisible() and not window.view.page().isLoading())
        wait(lambda: window._mode_theme == 'ethereal')
        for theme in ['ethereal', 'light', 'dark']:
            go('/history?theme=' + theme)
            window.grab().save(str(args.output / (theme + '-document.png')))
            entered.clear(); release.clear()
            window.view.setUrl(QUrl(config['server']['origin'] + '/slow?theme=' + theme))
            wait(lambda: entered.is_set() and window.server_status.isVisible())
            window.grab().save(str(args.output / (theme + '-loading.png')))
            text = window.server_status.text()
            if hasattr(window,'_server_page_exposed'):
                assert window.server_status.geometry()==window.server_shell.rect()
                assert window._server_surface_stack.currentWidget() is window.server_status
                assert not window.view.isEnabled() and not window._server_page_exposed
                assert not window.view.hasFocus()
                for x,y in [(1,1),(window.server_shell.width()-2,1),(window.server_shell.width()//2,window.server_shell.height()//2)]:
                    assert window.server_shell.childAt(x,y) is window.server_status
            report[theme] = {'loading': text, 'page_background': window.view.page().backgroundColor().name(), 'surface_style': window.centralWidget().styleSheet()}
            if not args.baseline:
                assert text == 'Loading Server page…', text
                assert window.view.page().backgroundColor().name() == THEME_REGISTRY[theme]['colors']['body_base'].lower()
                assert not window._server_page_exposed and window.view.isVisible() and not window.view.isEnabled() and 'Server:' in window.windowTitle()
            release.set()
            wait(lambda: window.view.isVisible() and not window.view.page().isLoading())
        if not args.baseline:
            # A superseding navigation must not turn a canceled old request into a final failure.
            entered.clear(); release.clear()
            window.view.setUrl(QUrl(config['server']['origin'] + '/slow'))
            wait(lambda: entered.is_set() and window.server_status.isVisible())
            window.view.setUrl(QUrl(config['server']['origin'] + '/slow-second'))
            wait(lambda: second_entered.is_set())
            assert window.view.page().isLoading()
            assert not window.server_unreachable, 'Superseded completion must not fail the newer in-flight navigation'
            assert not window._server_page_exposed and not window.view.isEnabled()
            assert window.server_status.text() == 'Loading Server page…'
            window.grab().save(str(args.output / 'superseding-slow-load.png'))
            second_release.set(); release.set()
            wait(lambda: window.view.isVisible() and window.view.url().path() == '/slow-second')
            go('/it')
            go('/study-packs')
            window.view.setUrl(QUrl(config['server']['origin'] + '/redirect'))
            wait(lambda: window.view.isVisible() and window.view.url().path() == '/certifications')
            window.view.setUrl(QUrl(config['server']['origin'] + '/escape'))
            wait(lambda: window.server_unreachable)
            assert not window.view.isVisible() and window.backend is None
            report['wrong_origin'] = window.server_status.text()
            window.grab().save(str(args.output / 'blocked-redirect.png'))
            window._retry_server()
            wait(lambda: 'Server data stays separate' in window.server_status.text())
            wait(lambda: window.view.isVisible() and not window.view.page().isLoading())
            window.view.setUrl(QUrl(config['server']['origin'] + '/failure'))
            wait(lambda: window.server_unreachable)
            report['failure'] = window.server_status.text()
            assert 'no Local fallback' in window.statusBar().currentMessage()
            window.grab().save(str(args.output / 'failure.png'))
            report['rapid_slow_redirect_failure'] = True
            if hasattr(window,'server_readiness_timer'):
                window._retry_server()
                wait(lambda: window.view.isVisible() and not window.view.page().isLoading())
                wait(lambda:window._server_document_identity is not None)
                entered.clear();release.clear()
                window.view.setUrl(QUrl(config['server']['origin']+'/tail'))
                wait(lambda:entered.is_set() and window._server_early_revealed)
                assert window.view.isVisible() and window.view.page().isLoading()
                assert window.statusBar().currentMessage()=='Server page visible; still loading resources…'
                window.view.stop()
                wait(lambda:window.server_unreachable)
                assert not window.view.isVisible() and window.server_status.isVisible()
                assert not window.server_readiness_timer.isActive()
                release.set()
                report['failure_after_provisional_reveal']=True
        (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
    finally:
        release.set(); second_release.set(); window.close()
        wait(lambda: window.view is None, 15)
        app.processEvents(); server.shutdown(); server.server_close(); thread.join(5)
    return 0

if __name__ == '__main__': raise SystemExit(main())
