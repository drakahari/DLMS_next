"""App-local native menu input tests; never launch a real browser."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt, QEvent
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from desktop import webview2_native_ai as native
from desktop import webview2_external as external


@pytest.fixture(scope='module', autouse=True)
def application():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def menu(monkeypatch):
    parent = QWidget()
    parent.show()
    assert QTest.qWaitForWindowExposed(parent, 1000)
    parent.activateWindow()
    QApplication.processEvents()
    context = SimpleNamespace(valid=lambda: True)
    owner = SimpleNamespace(_external_handoff_pending=False)
    calls = []
    monkeypatch.setattr(native, 'capture', lambda owner: context)
    monkeypatch.setattr(external, 'open_native_ai', lambda w, c, u: calls.append(u))
    menu = native.AIWebsiteMenu(owner, parent)
    menu.popup(QPoint(120, 120))
    QApplication.processEvents()
    QTest.qWait(30)  # Let the native popup activate before app-local input.
    yield menu, context, calls
    menu.close()
    parent.close()


@pytest.mark.parametrize('provider,label,url,mnemonic', native.DESTINATIONS)
@pytest.mark.parametrize('input', ['mouse', 'enter', 'space', 'mnemonic'])
def test_one_native_menu_activation_no_replay(menu, provider, label, url, mnemonic, input):
    widget, context, calls = menu
    action = next(a for a in widget.actions() if a.objectName() == 'desktopAI_' + provider)
    if input == 'mouse':
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=widget.actionGeometry(action).center())
    else:
        widget.setActiveAction(action)
        QTest.keyClick(widget, {'enter': Qt.Key.Key_Return, 'space': Qt.Key.Key_Space,
                              'mnemonic': ord(mnemonic.upper())}[input])
    assert calls == [url]
    action.trigger()  # Replaying the signal has no input lease.
    assert calls == [url]


@pytest.mark.parametrize('kind', ['trigger', 'synthetic-key', 'repeat', 'hidden', 'disabled', 'stale', 'replaced'])
def test_no_signal_synthetic_repeat_hidden_or_stale_authority(menu, monkeypatch, kind):
    widget, context, calls = menu
    action = widget.actions()[0]
    widget.setActiveAction(action)
    if kind == 'trigger': action.trigger()
    elif kind in ('synthetic-key', 'repeat'):
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier,
                          '\r', kind == 'repeat', 2 if kind == 'repeat' else 1)
        QApplication.sendEvent(widget, event)
    elif kind == 'hidden':
        widget.close(); QTest.keyClick(widget, Qt.Key.Key_Return)
    elif kind == 'disabled':
        action.setEnabled(False); QTest.keyClick(widget, Qt.Key.Key_Return)
    elif kind == 'stale':
        context.valid = lambda: False; QTest.keyClick(widget, Qt.Key.Key_Return)
    else:
        monkeypatch.setattr(native, 'capture', lambda owner: object())
        QTest.keyClick(widget, Qt.Key.Key_Return)
    assert not calls


def test_release_without_matching_press_and_later_independent_click(menu):
    widget, _, calls = menu
    action = widget.actions()[0]
    point = widget.actionGeometry(action).center()
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=point)
    assert not calls
    widget.popup(QPoint(120, 120)); QApplication.processEvents()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=point)
    assert calls == [native.DESTINATIONS[0][2]]
    widget.popup(QPoint(120, 120)); QApplication.processEvents()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=point)
    assert calls == [native.DESTINATIONS[0][2]] * 2


def test_genuine_marked_repeat_and_press_release_on_different_actions(menu):
    widget, _, calls = menu
    first, second = widget.actions()[:2]
    class Repeat(QKeyEvent):
        def spontaneous(self): return True  # Test only; no runtime bypass/seam.
    widget.setActiveAction(first)
    widget.keyPressEvent(Repeat(QEvent.Type.KeyPress, Qt.Key.Key_Return,
        Qt.KeyboardModifier.NoModifier, '\r', True, 2))
    assert not calls
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=widget.actionGeometry(first).center())
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=widget.actionGeometry(second).center())
    assert not calls


@pytest.mark.parametrize('change', ['busy', 'dialog', 'operation', 'covered'])
def test_capture_refuses_unavailable_context(change):
    owner = SimpleNamespace(mode='server', _external_handoff_pending=change == 'busy',
        _browser_dialog_depth=int(change == 'dialog'), _browser_operation_depth=int(change == 'operation'),
        _server_page_exposed=change != 'covered')
    assert native.capture(owner) is None


@pytest.mark.parametrize('target', ['file:///C:/bad.exe', 'https://unexpected.invalid/',
    'https://chatgpt.com/?prompt=secret', 'https://chatgpt.com.evil.invalid/'])
def test_handoff_revalidates_closed_destination_map(monkeypatch, target):
    context = SimpleNamespace(valid=lambda: True)
    owner = SimpleNamespace(_external_handoff_pending=False)
    monkeypatch.setattr(native, 'capture', lambda owner: context)
    monkeypatch.setattr(external.QTimer, 'singleShot', lambda *a: pytest.fail('Unexpected launch'))
    external.open_native_ai(owner, context, target)
    assert not owner._external_handoff_pending


def test_native_launch_is_queued_once_and_revalidates_document(monkeypatch):
    context = SimpleNamespace(mode='local', valid=lambda: True)
    owner = SimpleNamespace(_external_handoff_pending=False)
    queue = []
    monkeypatch.setattr(native, 'capture', lambda owner: None if owner._external_handoff_pending else context)
    monkeypatch.setattr(external.QTimer, 'singleShot', lambda delay, callback: queue.append(callback))
    external.open_native_ai(owner, context, native.DESTINATIONS[0][2])
    external.open_native_ai(owner, context, native.DESTINATIONS[0][2])
    assert len(queue) == 1
    context.valid = lambda: False
    queue.pop()()
    assert not owner._external_handoff_pending


@pytest.mark.parametrize('change', ['dialog', 'operation', 'covered', 'pending', 'replaced'])
def test_queued_native_handoff_refuses_new_modal_cover_or_replaced_ticket(monkeypatch, change):
    context = SimpleNamespace(mode='server', valid=lambda: True)
    owner = SimpleNamespace(_external_handoff_pending=False, _server_page_exposed=True)
    queue = []
    monkeypatch.setattr(native, 'capture', lambda owner: context)
    monkeypatch.setattr(external.QTimer, 'singleShot', lambda delay, callback: queue.append(callback))
    monkeypatch.setattr(external, '_open', lambda *a, **kw: pytest.fail('Retired activation launched'))
    external.open_native_ai(owner, context, native.DESTINATIONS[0][2])
    if change == 'dialog': owner._browser_dialog_depth = 1
    elif change == 'operation': owner._browser_operation_depth = 1
    elif change == 'covered': owner._server_page_exposed = False
    elif change == 'pending': owner._external_handoff_pending = False
    else: owner._native_ai_pending_ticket = object()
    replacement = owner._native_ai_pending_ticket
    queue.pop()()
    if change == 'replaced':
        assert owner._native_ai_pending_ticket is replacement and owner._external_handoff_pending
    else:
        assert owner._native_ai_pending_ticket is None and not owner._external_handoff_pending


@pytest.mark.parametrize('change', ['url', 'origin', 'navigation', 'mode', 'profile', 'epoch'])
def test_real_selection_context_retires_native_menu_lease(tmp_path, monkeypatch, change):
    from tests.webview2.test_file_selection_adapter import owner
    w = owner(tmp_path)
    w._server_page_exposed = True
    w._external_handoff_pending = False
    menu = native.AIWebsiteMenu(w, w)
    monkeypatch.setattr(external, 'open_native_ai', lambda *a: pytest.fail('Stale session launched'))
    menu.popup(QPoint(120, 120)); QApplication.processEvents()
    assert menu.actions()[0].isEnabled()
    if change == 'url': w.view.page().href += '?new=1'
    elif change == 'origin': w.mode_config['server']['origin'] = 'https://other.invalid'
    elif change == 'navigation': w.view._active_navigation += 1
    elif change == 'mode': w.mode = 'local'
    elif change == 'profile': w.profile_name = 'other'
    else: w.manifest = {'uuid':'replacement', 'epoch':2}
    menu.setActiveAction(menu.actions()[0])
    QTest.keyClick(menu, Qt.Key.Key_Return)
    menu.close(); w.close()
