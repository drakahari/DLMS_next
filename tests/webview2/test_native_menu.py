"""Application-local Qt events only; no desktop input or physical focus claim."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from desktop import build_info, webview2_about
from desktop.webview2_shell import DesktopWindow, QtDesktopWindow


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def metadata(tmp_path, monkeypatch, **changes):
    value = dict(application_version='0.1.0', release='windows-webview2-candidate-test',
                 source_commit='5d2766f + uncommitted ' + 'b' * 64,
                 target='Windows 11 x86-64 WebView2 candidate',
                 browser_runtime='Installed Microsoft WebView2 Evergreen',
                 support='Private unsigned candidate.', **changes)
    folder = tmp_path / 'desktop_assets'
    folder.mkdir()
    (folder / 'build-info.json').write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setattr(webview2_about.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(webview2_about.sys, '_MEIPASS', str(tmp_path), raising=False)
    return value


def test_frozen_webview2_metadata_reproduces_old_about_schema_error(tmp_path, monkeypatch):
    value = metadata(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='Invalid build information'):
        build_info.information()
    assert webview2_about.information() == value
    assert 'not recorded in this build' in webview2_about.about_text(mode='local', runtime_version='155.0.4283.45')


def test_new_identity_accurate_runtime_and_bundled_backend_without_sensitive_context(tmp_path, monkeypatch):
    metadata(tmp_path, monkeypatch, backend_version='3.3.0')
    text = webview2_about.about_text(mode='server', runtime_version='155.0.4283.45')
    assert 'Bundled Local DLMS backend: 3.3.0' in text
    assert 'Detected WebView2 Runtime: 155.0.4283.45' in text
    assert 'Qt Widgets:' in text and 'Python:' in text and 'native C#' in text
    assert 'Its deployed backend version is not established' in text
    assert 'C:' not in text and 'http' not in text and 'nonce' not in text
    assert webview2_about.about_text(mode='local', runtime_version='<html>secret</html>').count('secret') == 0


@pytest.mark.parametrize('mutation', [lambda x: x.update(extra='unexpected'),
    lambda x: x.update(release='bad\nvalue'), lambda x: x.update(source_commit=1),
    lambda x: x.pop('browser_runtime'), lambda x: x.update(backend_version='x' * 512)])
def test_windows_metadata_stays_strict(tmp_path, monkeypatch, mutation):
    value = metadata(tmp_path, monkeypatch)
    mutation(value)
    (tmp_path / 'desktop_assets/build-info.json').write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError):
        webview2_about.information()


def window(monkeypatch):
    monkeypatch.setattr(DesktopWindow, '_style_mode_control', lambda *args: None)
    w = DesktopWindow.__new__(DesktopWindow)
    QMainWindow.__init__(w)
    for name, value in dict(mode='local', profile_name='synthetic',
        mode_config={'server': None}, server_unreachable=False, _mode_switch_busy=False,
        _closing=False, _retiring_browser=None, _close_active=False, _close_complete=True,
        _browser_dialog_depth=0, _browser_operation_depth=0, _browser_generation=3,
        view=None, webview2_runtime_version='155.0.4283.45').items():
        setattr(w, name, value)
    w._create_mode_toolbar()
    return w


def test_all_visible_native_submenu_actions_are_wired_and_have_mnemonics(monkeypatch):
    calls = []
    for name in ('switch_to_local', 'switch_to_server', '_configure_server_dialog', '_retry_server_from_menu', '_show_about'):
        monkeypatch.setattr(DesktopWindow, name, lambda *args, name=name: calls.append(name))
    w = window(monkeypatch)
    visible = [a for a in w.mode_menu.actions() if not a.isSeparator() and a.isVisible()]
    assert [a.text() for a in visible] == ['&Local', '&Server (not configured)', '&Configure Server…', '&About DLMS Desktop…']
    # The common Qt shell omits the debug action entirely by default; older
    # candidate17 created then hid it. Neither may expose it in normal menus.
    assert w.mix_diagnostic_action is None or (
        w.mix_diagnostic_action not in w.mode_menu.actions() and not w.mix_diagnostic_action.isVisible())
    actions = [w.local_mode_action, w.server_mode_action, w.configure_server_action, w.retry_server_action, w.about_action]
    for action in actions:
        action.setEnabled(True)
        action.setVisible(True)
        assert '&' in action.text()
        action.trigger()
    assert calls == ['switch_to_local', 'switch_to_server', '_configure_server_dialog', '_retry_server_from_menu', '_show_about']
    w.deleteLater()


def test_menu_mode_states_retry_visibility_and_ampersand_label(monkeypatch):
    w = window(monkeypatch)
    assert not w.local_mode_action.isEnabled() and not w.server_mode_action.isEnabled()
    assert w.configure_server_action.isEnabled() and not w.retry_server_action.isVisible()
    w.mode_config['server'] = {'label': 'A & B', 'origin': 'https://synthetic.invalid'}
    w._update_mode_toolbar()
    assert w.server_mode_action.isEnabled() and w.server_mode_action.text() == '&Server: A && B'
    w.mode = 'server'; w.server_unreachable = True; w._update_mode_toolbar()
    assert w.local_mode_action.isEnabled() and not w.configure_server_action.isEnabled()
    assert w.retry_server_action.isVisible() and not w.server_mode_action.isEnabled()
    w.deleteLater()


@pytest.mark.parametrize('key,method', [(Qt.Key.Key_L, 'switch_to_local'),
    (Qt.Key.Key_S, 'switch_to_server'), (Qt.Key.Key_C, '_configure_server_dialog'),
    (Qt.Key.Key_R, '_retry_server_from_menu'), (Qt.Key.Key_A, '_show_about')])
def test_native_menu_keyboard_mnemonics_dispatch_each_action(monkeypatch, key, method):
    calls = []
    for name in ('switch_to_local', 'switch_to_server', '_configure_server_dialog', '_retry_server_from_menu', '_show_about'):
        monkeypatch.setattr(DesktopWindow, name, lambda *args, name=name: calls.append(name))
    w = window(monkeypatch)
    for action in (w.local_mode_action, w.server_mode_action, w.configure_server_action,
                   w.retry_server_action, w.about_action):
        action.setEnabled(True); action.setVisible(True)
    QTimer.singleShot(25, lambda: QTest.keyClick(w.mode_menu, key))
    # App-local Qt delivery, not SendInput/UIA or a claim about foreground
    # keyboard delivery to the actual Windows/WebView2 package.
    QTimer.singleShot(1000, w.mode_menu.close)
    w.mode_menu.exec(QPoint(0, 0))
    assert calls == [method]
    w.deleteLater()


def test_selector_space_opens_menu_then_about_mnemonic_dispatches(monkeypatch):
    calls, visible = [], []
    monkeypatch.setattr(DesktopWindow, '_show_about', lambda *args: calls.append('about'))
    w = window(monkeypatch)
    w.show(); w.mode_identity.setFocus()
    def choose():
        visible.append(w.mode_menu.isVisible())
        QTest.keyClick(w.mode_menu, Qt.Key.Key_A)
    QTimer.singleShot(25, choose)
    QTimer.singleShot(1000, w.mode_menu.close)
    QTest.keyClick(w.mode_identity, Qt.Key.Key_Space)
    QApplication.processEvents()
    assert visible == [True] and calls == ['about']
    w.hide(); w.deleteLater()


@pytest.mark.parametrize('key', [Qt.Key.Key_Escape, Qt.Key.Key_Return])
def test_about_action_opens_actual_modal_plaintext_dialog_and_keyboard_closes(monkeypatch, key):
    w = window(monkeypatch)
    monkeypatch.setattr(w, '_about_text', lambda: 'DLMS Desktop\nSynthetic safe build identity')
    focused, observations = [], []
    monkeypatch.setattr(w, '_native_menu_focus', lambda context: focused.append(context))
    def inspect():
        dialog = QApplication.activeModalWidget()
        observations.append((dialog.objectName(), dialog.text(), dialog.textFormat(), w._browser_operation_depth,
                             dialog.defaultButton() is dialog.escapeButton()))
        QTest.keyClick(dialog, key)
    QTimer.singleShot(25, inspect)
    w.about_action.trigger()
    assert observations == [('desktopAboutDialog', 'DLMS Desktop\nSynthetic safe build identity', Qt.TextFormat.PlainText, 1, True)]
    assert w._browser_operation_depth == 0 and focused == [w._native_menu_context()]
    w.deleteLater()


def test_bad_metadata_shows_actionable_failure_instead_of_silent_action(monkeypatch):
    w = window(monkeypatch)
    def invalid(): raise ValueError('sensitive detail must not be shown')
    monkeypatch.setattr(w, '_about_text', invalid)
    texts = []
    def inspect():
        dialog = QApplication.activeModalWidget()
        texts.append(dialog.text())
        dialog.reject()
    QTimer.singleShot(25, inspect)
    w.about_action.trigger()
    assert 'entire executable folder' in texts[0] and 'sensitive detail' not in texts[0]
    w.deleteLater()


@pytest.mark.parametrize('guard,value', [('_closing', True), ('_retiring_browser', object()),
    ('_close_active', True), ('_mode_switch_busy', True), ('_browser_dialog_depth', 1), ('_browser_operation_depth', 1)])
def test_native_menu_dialogs_and_retry_refuse_busy_or_retiring_context(monkeypatch, guard, value):
    w = window(monkeypatch); setattr(w, guard, value)
    calls = []
    monkeypatch.setattr(w, '_show_webview2_about', lambda: calls.append('about'))
    monkeypatch.setattr(w, '_configure_webview2_server_dialog', lambda: calls.append('configure'))
    monkeypatch.setattr(QtDesktopWindow, '_retry_server', lambda self: calls.append('retry'))
    w._show_about(); w._configure_server_dialog(); w._retry_server_from_menu()
    assert calls == []
    w.deleteLater()


def test_context_focus_does_not_activate_another_app_or_retired_context(monkeypatch):
    w = window(monkeypatch); focused = []
    monkeypatch.setattr(w.mode_identity, 'setFocus', lambda *args: focused.append(args))
    context = w._native_menu_context()
    monkeypatch.setattr(w, 'isActiveWindow', lambda: False)
    w._native_menu_focus(context); assert not focused
    monkeypatch.setattr(w, 'isActiveWindow', lambda: True)
    w._browser_generation += 1; w._native_menu_focus(context); assert not focused
    w._native_menu_focus(w._native_menu_context()); assert len(focused) == 1
    w.deleteLater()


def test_configure_cancel_returns_focus_and_preserves_operation_guard(monkeypatch):
    w = window(monkeypatch); calls = []
    monkeypatch.setattr(QtDesktopWindow, '_configure_server_dialog', lambda self: calls.append(self._browser_operation_depth))
    monkeypatch.setattr(w, '_native_menu_focus', lambda context: calls.append(context))
    w.configure_server_action.trigger()
    assert calls == [1, w._native_menu_context()] and w._browser_operation_depth == 0
    w.deleteLater()


def test_retry_menu_requests_only_configured_origin_and_does_not_fallback(monkeypatch):
    w = window(monkeypatch); urls, focus = [], []
    w.mode = 'server'; w.server_unreachable = True
    w.mode_config['server'] = {'origin': 'https://synthetic.invalid:9443', 'label': 'Synthetic'}
    w.view = SimpleNamespace(setUrl=lambda url: urls.append(url.toString()), setFocus=lambda reason: focus.append(reason))
    w.backend = None; w._update_mode_toolbar()
    monkeypatch.setattr(w, 'isActiveWindow', lambda: True)
    w.retry_server_action.trigger()
    assert urls == ['https://synthetic.invalid:9443/'] and len(focus) == 1
    assert w.mode == 'server' and w.backend is None
    monkeypatch.setattr(w, 'isActiveWindow', lambda: False)
    w.retry_server_action.trigger()
    assert len(urls) == 2 and len(focus) == 1
    w.deleteLater()
