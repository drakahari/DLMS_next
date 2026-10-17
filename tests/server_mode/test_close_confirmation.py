"""Native dialog only: no server, backend or host input is used."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from desktop.shell import DesktopWindow


@pytest.mark.parametrize('action,accepted', [('enter', False), ('escape', False), ('keep', False), ('close', True)])
def test_server_close_wording_safe_default_and_explicit_choice(action, accepted):
    app = QApplication.instance() or QApplication([])
    parent = QMainWindow()
    errors = []
    def interact():
        dialog = app.activeModalWidget()
        try:
            assert isinstance(dialog, QMessageBox)
            assert dialog.windowTitle() == 'Close DLMS Desktop?'
            assert 'DLMS Desktop cannot verify its save state.' in dialog.text()
            assert 'does not delete results already saved on the server' in dialog.text()
            assert 'unsaved Study or Exam work' in dialog.text()
            assert 'inspect Server History' in dialog.text()
            buttons = {b.text(): b for b in dialog.buttons()}
            assert set(buttons) == {'Keep open', 'Close DLMS Desktop'}
            assert dialog.defaultButton() is buttons['Keep open']
            assert dialog.escapeButton() is buttons['Keep open']
            if action in ('enter', 'escape'):
                QTest.keyClick(dialog, Qt.Key.Key_Return if action == 'enter' else Qt.Key.Key_Escape)
            else:
                buttons['Keep open' if action == 'keep' else 'Close DLMS Desktop'].click()
        except BaseException as error:
            errors.append(error)
            dialog.reject()
    QTimer.singleShot(0, interact)
    result = DesktopWindow._confirm_server_close(parent)
    parent.close()
    if errors:
        raise errors[0]
    assert result is accepted


def test_loaded_server_keep_open_still_refuses_close(monkeypatch):
    monkeypatch.delenv('DLMS_DESKTOP_AUTOMATED', raising=False)
    calls = []
    stub = SimpleNamespace(backup_output_future=None, mode='server', server_loaded_once=True,
                           _close_complete=False, _close_active=False, _browser_dialog_depth=0,
                           _active_outputs=lambda: [],
                           _confirm_server_close=lambda: calls.append('confirm') or False)
    stub._close_event_impl = lambda event: DesktopWindow._close_event_impl(stub, event)
    event = QCloseEvent()
    DesktopWindow.closeEvent(stub, event)
    assert not event.isAccepted()
    assert calls == ['confirm']
