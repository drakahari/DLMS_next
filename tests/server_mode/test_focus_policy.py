"""Real WebEngine focus proxy survives the Server loading/failure cover.

No application backend, user data, AI action or external endpoint is used.
The Server constructor and terminal-load/exposure methods are production code;
only its transport/page authorization is replaced by inert in-memory HTML here.
"""
import time
from types import MethodType
import pytest
from PySide6.QtCore import Qt, QEventLoop, QTimer, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor
from desktop.shell import DesktopWindow
from desktop.browser_lifetime import BrowserRetirement

ORIGIN = 'http://127.0.0.1:17999'
HTML = '<input id="first" type="checkbox"><input id="second" type="checkbox"><button id="button">Inert</button>'


class InertTransport(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        pass  # setHtml's data: main document is a test-only transport.


def delay():
    loop = QEventLoop(); QTimer.singleShot(30, loop.quit); loop.exec()


def until(condition):
    end = time.monotonic() + 8
    while time.monotonic() < end:
        if condition(): return
        delay()
    raise AssertionError('Bounded focus-state condition did not complete')


def js(page, expression):
    values = []; page.runJavaScript(expression, values.append)
    until(lambda: bool(values))
    return values[0]


@pytest.fixture
def server(monkeypatch, tmp_path):
    application = QApplication.instance() or QApplication([])
    import desktop.shell as shell
    monkeypatch.setattr(shell, 'server_root', lambda _: {k: tmp_path / k for k in ('storage', 'cache')})
    monkeypatch.setattr(shell, 'ServerPage', lambda profile, owner, origin, parent: QWebEnginePage(profile, parent))
    monkeypatch.setattr(shell, 'ServerOnlyInterceptor', lambda origin, parent: InertTransport(parent))
    window = QMainWindow(); window.resize(900, 500)
    window.profile_name = 'synthetic-focus'
    window.mode_config = {'server': {'id': 'synthetic-focus', 'origin': ORIGIN, 'label': 'Synthetic focus'}}
    window._closing = False; window._retiring_browser = None
    window._browser_generation = 1; window.server_loaded_once = False
    window.server_readiness_timer = QTimer(window)
    window._update_mode_toolbar = lambda: None
    window._style_server_surface = lambda: None
    window._poll_mode_theme = lambda: None
    window._probe_server_readiness = lambda **_: None
    window._page_loading_changed = lambda *_: None
    # Do not contact an endpoint: an explicit setHtml starts each test load.
    window._retry_server = lambda: None
    window._server_download = lambda _: None
    for name in ('_set_server_page_exposed', '_server_load_started', '_server_load_finished'):
        setattr(window, name, MethodType(getattr(DesktopWindow, name), window))
    DesktopWindow._show_server(window)
    window.show(); window.activateWindow(); application.processEvents()
    try:
        yield application, window
    finally:
        window._closing = True
        retirement = BrowserRetirement(window.view, window.profile, window)
        retirement.start(); until(lambda: retirement.done)
        window.view = None
        window.close(); window.deleteLater(); application.processEvents()


def covered(window, *, visible):
    assert not window._server_page_exposed
    assert not window.view.isEnabled()
    assert window.view.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert window.view.isVisible() == visible
    assert window._server_surface_stack.currentWidget() is window.server_status


def load(window):
    window.view.page().setHtml(HTML, QUrl(ORIGIN + '/library'))
    until(lambda: not window.view.page().isLoading() and js(window.view.page(), "!!document.getElementById('first')"))


def interactive(window):
    assert window._server_page_exposed and window.view.isEnabled()
    assert window.view.isVisible() and not window.server_status.isVisible()
    assert window.view.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert window.view.focusProxy().focusPolicy() == Qt.FocusPolicy.StrongFocus
    page = window.view.page()
    js(page, "document.getElementById('first').focus();true")
    window.view.setFocus()
    QTest.keyClick(window.view.focusProxy(), Qt.Key.Key_Tab)
    until(lambda: js(page, 'document.activeElement.id') == 'second')


def test_loading_to_ready_restores_real_focus_proxy(server):
    _, window = server
    assert window._server_view_focus_policy == Qt.FocusPolicy.StrongFocus
    covered(window, visible=True)
    load(window); covered(window, visible=True)
    window._server_load_finished(True)
    interactive(window)


def test_failure_retry_and_second_navigation_keep_cover_protected(server):
    _, window = server
    load(window); window._server_load_finished(False)
    covered(window, visible=False)
    assert window.server_unreachable
    window._server_connection_attempt = True
    load(window); covered(window, visible=True)
    window._server_load_finished(True); interactive(window)
    assert not window.server_unreachable
    load(window); covered(window, visible=True)
    window._server_load_finished(True); interactive(window)


def test_failed_retry_never_restores_keyboard_input(server):
    _, window = server
    for _ in range(2):
        load(window); window._server_load_finished(False)
        covered(window, visible=False)
        assert window.view.focusProxy().focusPolicy() == Qt.FocusPolicy.NoFocus


def test_stale_finish_cannot_uncover_a_loading_or_local_view(server):
    _, window = server
    load(window)
    original = window.view.page().isLoading
    window.view.page().isLoading = lambda: True
    try: window._server_load_finished(True)
    finally: window.view.page().isLoading = original
    covered(window, visible=True)
    window.mode = 'local'; window._server_load_finished(True)
    covered(window, visible=True)
