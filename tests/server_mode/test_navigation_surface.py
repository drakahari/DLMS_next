"""Presentational theme input must not outlive its document or gain capabilities."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QUrl
from desktop.shell import DesktopWindow
from desktop.server_surface import connection_text, NEUTRAL_SERVER_PALETTE
from desktop.settings_surface import THEME_REGISTRY


class Page:
    def __init__(self):
        self.loading = False
        self.location = QUrl('http://127.0.0.2:8123/history')
    def isLoading(self): return self.loading
    def url(self): return self.location
    def runJavaScript(self, expression, callback):
        assert expression == "document.querySelector('.dashboard-sidebar')?.dataset.theme || ''"
        self.callback = callback


def fixture():
    page = Page()
    view = SimpleNamespace(page=lambda: page, isVisible=lambda: True)
    calls = []
    window = SimpleNamespace(_closing=False, _retiring_browser=None, view=view,
        mode='server', _server_page_exposed=True, _browser_generation=1, _server_navigation_serial=2,
        mode_config={'server': {'origin': 'http://127.0.0.2:8123'}}, server_unreachable=False,
        _server_theme='ethereal', _style_server_surface=lambda: calls.append(window._server_theme),
        _style_mode_control=lambda value: calls.append(value))
    DesktopWindow._poll_mode_theme(window)
    return window, page, calls


@pytest.mark.parametrize('theme', list(THEME_REGISTRY))
def test_allowlisted_top_document_selects_palette_only(theme):
    window, page, calls = fixture()
    page.callback(theme)
    assert calls == [theme] and window._server_theme == theme


@pytest.mark.parametrize('value', ['', None, {}, 3, '<script>localReset()</script>', 'unknown'])
def test_untrusted_value_cannot_select_style(value):
    window, page, calls = fixture(); page.callback(value); assert calls == []
    assert window._server_theme == 'ethereal', 'An unknown value retains the verified same-server palette'


@pytest.mark.parametrize('change', ['closing', 'retiring', 'mode', 'generation', 'serial', 'page', 'url', 'loading', 'hidden', 'covered', 'outage', 'origin'])
def test_late_callback_cannot_style_new_context(change):
    window, page, calls = fixture()
    if change == 'closing': window._closing = True
    elif change == 'retiring': window._retiring_browser = object()
    elif change == 'mode': window.mode = 'local'
    elif change == 'generation': window._browser_generation += 1
    elif change == 'serial': window._server_navigation_serial += 1
    elif change == 'page': window.view = SimpleNamespace(page=lambda: Page())
    elif change == 'url': page.location = QUrl('http://127.0.0.2:8123/it')
    elif change == 'loading': page.loading = True
    elif change == 'hidden': window.view.isVisible = lambda: False
    elif change == 'covered': window._server_page_exposed = False
    elif change == 'outage': window.server_unreachable = True
    elif change == 'origin': window.mode_config['server']['origin'] = 'http://127.0.0.2:9001'
    page.callback('ethereal'); assert calls == []


def test_loading_copy_and_neutral_are_not_local_theme():
    assert connection_text('https://example.invalid', 'synthetic01', initial=False) == 'Loading Server page…'
    assert 'synthetic01' in connection_text('https://example.invalid', 'synthetic01', initial=True)
    assert NEUTRAL_SERVER_PALETTE['body_base'] == '#20252c'


@pytest.mark.parametrize('ok', [True, False])
def test_superseded_finish_cannot_publish_current_load(ok):
    window, page, calls = fixture()
    page.loading = True
    DesktopWindow._server_load_finished(window, ok)
    assert calls == [] and not window.server_unreachable
