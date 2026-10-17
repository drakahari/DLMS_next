"""Native controls in a separate instrumented executable; not physical input.

Qt events target only this process's own QMenu/dialog widgets. No SendInput,
UI Automation, global shortcuts, renderer switches or normal-package hook.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time


def assert_no_mix_diagnostic(window):
    """Normal menus may omit the debug action or retire it completely."""
    action = window.mix_diagnostic_action
    if action is not None:
        assert not action.isVisible()
        assert action not in window.mode_menu.actions()


def until(q, predicate, description, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        q.delay(.05)
    raise TimeoutError(description)


class SyntheticServer(BaseHTTPRequestHandler):
    healthy = True
    requests = []

    def log_message(self, *_): pass

    def do_GET(self):
        type(self).requests.append({'path': self.path,
            'local_token_present': bool(self.headers.get('X-DLMS-Desktop-Token'))})
        body = b'<html><body><h1 id="native-menu-server">Synthetic native menu Server</h1></body></html>'
        self.send_response(200 if type(self).healthy else 503)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    from PySide6.QtCore import Qt, QTimer, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    from desktop.webview2_file_selection import _known_private_roots
    from desktop.webview2_shell import DesktopWindow
    from desktop.webview2_browser import View
    from desktop.webview2_about import information
    from desktop.isolation import profile_paths
    from desktop.server_mode import configured_server, read_config, write_config
    import desktop.shell
    roots = _known_private_roots()  # Before QtChecks scopes HOME/APPDATA.
    lifecycle, original_event = [], View._event
    def event(view, value):
        if value.get('event') in ('browser-exited', 'retired'):
            lifecycle.append({key: value[key] for key in ('event', 'pid', 'browser_exited') if key in value})
        return original_event(view, value)
    View._event = event
    desktop.shell.DesktopWindow = lambda *a, **k: DesktopWindow(*a, selection_private_roots=roots, **k)
    from tests.gate1.qt_checks import QtChecks
    if profile_paths(args.profile, create=False)['root'].exists():
        raise ValueError('The menu check requires a new synthetic profile; existing evidence is not reused')
    q = QtChecks(args.profile, automated=True, normal_identity=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), SyntheticServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    report = {'instrumented': True, 'normal_package': False, 'physical_input': False,
              'frozen': bool(getattr(sys, 'frozen', False)), 'about': [], 'stage': 'initial',
              'build': information(), 'runtime': q.window.webview2_runtime_version}

    def menu_key(key, callback=None, *, selector_space=False):
        errors, observations = [], []
        def modal():
            try:
                if callback: observations.append(callback(QApplication.activeModalWidget()))
            except BaseException as exc:
                errors.append(repr(exc))
            finally:
                dialog = QApplication.activeModalWidget()
                if dialog is not None: QTest.keyClick(dialog, Qt.Key.Key_Escape)
        if callback: QTimer.singleShot(100, modal)
        def choose():
            if not q.window.mode_menu.isVisible():
                errors.append('The native selector did not open its menu')
            QTest.keyClick(q.window.mode_menu, key)
        QTimer.singleShot(20, choose)
        timeout = QTimer()
        timeout.setSingleShot(True)
        def cancel_timeout():
            errors.append('Native menu/dialog check timed out')
            dialog = QApplication.activeModalWidget()
            if dialog is not None: dialog.reject()
            q.window.mode_menu.close()
        timeout.timeout.connect(cancel_timeout); timeout.start(10000)
        if selector_space:
            QTest.keyClick(q.window.mode_identity, Qt.Key.Key_Space)
        else:
            q.window.mode_menu.exec(q.window.mode_identity.mapToGlobal(QPoint(0, 0)))
        timeout.stop()
        if errors: raise AssertionError(errors)
        if callback and len(observations) != 1: raise AssertionError('Native dialog did not open')
        return observations

    try:
        assert_no_mix_diagnostic(q.window)
        assert not q.window.local_mode_action.isEnabled() and not q.window.server_mode_action.isEnabled()
        report['stage'] = 'about-local'
        for width in (680, 1280):
            q.window.resize(width, 850); q.delay(.1)
            before = q.window.view
            def about(dialog):
                assert isinstance(dialog, QMessageBox)
                assert dialog.objectName() == 'desktopAboutDialog' and dialog.isVisible()
                assert dialog.textFormat() == Qt.TextFormat.PlainText
                assert dialog.defaultButton() is dialog.escapeButton()
                text = dialog.text()
                assert 'Bundled Local DLMS backend:' in text
                if report['frozen']: assert 'Bundled Local DLMS backend: 3.3.0' in text
                assert f'Detected WebView2 Runtime: {q.window.webview2_runtime_version}' in text
                assert report['build']['release'] in text and report['build']['source_commit'] in text
                assert 'Qt Widgets:' in text and 'Python:' in text and 'Active mode: Local' in text
                assert args.profile not in text and str(q.paths['root']) not in text
                assert q.window._browser_operation_depth == 1
                dialog.grab().save(str(args.output / f'about-{width}.png'))
                return {'window_width': width, 'dialog_width': dialog.width(), 'dialog_height': dialog.height(),
                        'active_during': dialog.isActiveWindow(), 'default_escape_close': True}
            report['about'].extend(menu_key(Qt.Key.Key_A, about, selector_space=width == 680))
            q.delay(.1)
            assert q.window.view is before and not q.window._browser_operation_depth
            report['about'][-1].update(parent_active=q.window.isActiveWindow(),
                                      selector_focus=q.window.mode_identity.hasFocus())
            if q.window.isActiveWindow(): assert q.window.mode_identity.hasFocus()
        report['stage'] = 'configure-cancel'
        config_before = read_config(args.profile)
        def configure(dialog):
            assert isinstance(dialog, QInputDialog) and dialog.isVisible()
            assert dialog.windowTitle() == 'Configure Server origin'
            assert q.window._browser_operation_depth == 1
            return {'actual_native_dialog': True, 'cancel': True}
        report['configure_cancel'] = menu_key(Qt.Key.Key_C, configure)
        assert read_config(args.profile) == config_before
        # Explicit synthetic fixture configuration; not evidence that a human
        # completed the native endpoint/HTTP-consent dialogs.
        origin = f'http://127.0.0.1:{server.server_port}'
        configured = configured_server(q.window.mode_config, origin, 'Synthetic & native menu', private_http_opt_in=True)
        q.window.mode_config = dict(q.window.mode_config, server=configured)
        write_config(args.profile, q.window.mode_config); q.window._update_mode_toolbar()
        report['stage'] = 'native-server-action'
        local_root = q.paths['root']; local_manifest = dict(q.window.manifest)
        menu_key(Qt.Key.Key_S)
        until(q, lambda: q.window.mode == 'server' and q.window._server_page_exposed
              and not q.window.view.page().isLoading(), 'Native Server action did not show the synthetic Server')
        assert q.window.backend is None
        q.wait("Boolean(document.getElementById('native-menu-server'))")
        report['server_action'] = True
        report['stage'] = 'native-retry-action'
        SyntheticServer.healthy = False
        q.window.view.setUrl(q.window.view.url())
        until(q, lambda: q.window.server_unreachable and not q.window.view.page().isLoading(), 'Expected synthetic HTTP503')
        assert q.window.retry_server_action.isVisible()
        before = len(SyntheticServer.requests)
        menu_key(Qt.Key.Key_R)
        until(q, lambda: len(SyntheticServer.requests) > before and q.window.server_unreachable
              and not q.window.view.page().isLoading(), 'Native Retry did not request the same unavailable origin')
        assert q.window.mode == 'server' and q.window.backend is None
        SyntheticServer.healthy = True
        menu_key(Qt.Key.Key_R)
        until(q, lambda: q.window._server_page_exposed and not q.window.view.page().isLoading()
              and not q.window.server_unreachable, 'Native Retry did not recover the synthetic Server')
        report['retry_action'] = {'unavailable_no_local_fallback': True, 'healthy_retry': True}
        report['stage'] = 'about-server'
        def server_about(dialog):
            assert isinstance(dialog, QMessageBox)
            text = dialog.text()
            assert 'Active mode: Server' in text and 'Its deployed backend version is not established' in text
            assert origin not in text and args.profile not in text
            return {'remote_backend_not_inferred': True, 'origin_not_disclosed': True}
        report['server_about'] = menu_key(Qt.Key.Key_A, server_about)
        report['stage'] = 'native-local-action'
        menu_key(Qt.Key.Key_L)
        until(q, lambda: q.window.mode == 'local' and q.window.backend is not None and q.window.view is not None
              and not q.window.view.page().isLoading(), 'Native Local action did not return')
        q.wait("Boolean(document.querySelector('.dashboard-sidebar'))")
        assert q.paths['root'] == local_root and q.window.manifest == local_manifest
        assert not any(row['local_token_present'] for row in SyntheticServer.requests)
        report.update(local_action_preserves_identity=True, no_local_token_on_server=True, passed=True, stage='complete')
    except BaseException as exc:
        report['error'] = repr(exc)
        raise
    finally:
        report['server_requests'] = SyntheticServer.requests
        report['status'] = q.window.statusBar().currentMessage()
        q.close(); q.delay(.3)
        report['close_complete'] = q.window._close_complete
        report['browser_lifecycle'] = lifecycle
        exits = [row['pid'] for row in lifecycle if row['event'] == 'browser-exited']
        retired = [row['pid'] for row in lifecycle if row['event'] == 'retired' and row.get('browser_exited') is True]
        report['native_retirement_proof'] = len(exits) == 3 and exits == retired
        View._event = original_event
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    assert report.get('passed') and report['close_complete'] and report['native_retirement_proof']
    return 0


if __name__ == '__main__': raise SystemExit(main())
