"""Windows controller failures before restore staging; no native windows."""
import pytest
from types import SimpleNamespace
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QMainWindow
from desktop import webview2_shell as shell, windows_backup_chooser as chooser
from desktop.operation_feedback import OperationFeedback


@pytest.fixture
def owner(monkeypatch):
    app=QApplication.instance() or QApplication([])
    w=shell.DesktopWindow.__new__(shell.DesktopWindow)
    QMainWindow.__init__(w)
    for name,value in dict(mode='local',_feedback_mode='local',_feedback_writing=False,
            _browser_generation=2,_server_navigation_serial=4,_wv_status_serial=0,
            _wv_feedback_context={},operation_feedback=OperationFeedback(),settings_panel=None,
            failed_reason=None,_settings_transition_refused=False,_closing=False,_retiring_browser=None,
            view=SimpleNamespace(page=lambda:'current-page')).items():setattr(w,name,value)
    w.statusBar().messageChanged.connect(w._status_message_changed)
    w.import_in_progress=False
    w._import_status_serial=0
    w._settings_generation=4
    w._browser_dialog_depth=0
    w._close_after_dialog=False
    w.backup_chooser_folders=()
    w.backup_selection_future=None
    w.import_worker=None
    w.focused=[]
    w._restore_backup_focus=lambda valid:w.focused.append(valid())
    monkeypatch.setenv('DLMS_DESKTOP_AUTOMATED','1')
    yield w
    w.deleteLater()


@pytest.mark.parametrize('kind',[OSError,ValueError,RuntimeError])
def test_native_setup_failure_is_visible_error_not_cancel_and_never_staged(owner,monkeypatch,kind):
    def fail(*args):
        assert owner._browser_dialog_depth==1
        raise kind('synthetic native setup unavailable')
    monkeypatch.setattr(chooser,'choose_open',fail)
    owner._choose_backup(still_authorized=lambda:True)
    assert owner.operation_feedback.severity=='error'
    assert 'Backup chooser could not open; no import started' in owner.statusBar().currentMessage()
    assert 'canceled' not in owner.statusBar().currentMessage()
    assert owner.focused==[True]
    assert not owner.import_in_progress and owner.backup_selection_future is None and owner.import_worker is None
    assert owner._browser_dialog_depth==0 and owner._browser_operation_depth==0


@pytest.mark.parametrize('stale',['mode','browser','settings','authorization','feedback','closing'])
def test_stale_chooser_failure_cannot_replace_feedback_or_refocus(owner,monkeypatch,stale):
    state={'authorized':True}
    def fail(*args):
        if stale=='mode':owner.mode='server'
        elif stale=='browser':owner._browser_generation+=1
        elif stale=='settings':owner._settings_generation+=1
        elif stale=='authorization':state['authorized']=False
        elif stale=='closing':owner._closing=True
        owner.statusBar().showMessage('Newer navigation or recovery notice')
        raise OSError('old chooser error')
    monkeypatch.setattr(chooser,'choose_open',fail)
    owner._choose_backup(still_authorized=lambda:state['authorized'])
    assert owner.statusBar().currentMessage()=='Newer navigation or recovery notice'
    assert not owner.focused
    assert not owner.import_in_progress and owner.backup_selection_future is None
    assert owner._browser_dialog_depth==0 and owner._browser_operation_depth==0


def test_native_cancel_retains_original_cancellation_semantics(owner,monkeypatch):
    monkeypatch.setattr(chooser,'choose_open',lambda *args:('',''))
    owner._choose_backup(still_authorized=lambda:True)
    assert 'Backup file selection canceled; no import started' in owner.statusBar().currentMessage()
    assert owner.focused==[True]


@pytest.mark.parametrize('newer_during_dialog',[False,True])
def test_failure_warning_is_plain_text_owned_modal_and_focus_is_revalidated(owner,monkeypatch,newer_during_dialog):
    def fail(*args):raise ValueError('<b>synthetic native error</b>')
    monkeypatch.setattr(chooser,'choose_open',fail)
    original=shell.QMessageBox
    seen={}
    class Dialog:
        Icon=original.Icon
        StandardButton=original.StandardButton
        def __init__(self,parent):assert parent is owner
        def setWindowTitle(self,value):seen['title']=value
        def setIcon(self,value):pass
        def setTextFormat(self,value):seen['format']=value
        def setText(self,value):seen['text']=value
        def setStandardButtons(self,value):pass
        def setDefaultButton(self,value):pass
        def setEscapeButton(self,value):pass
        def exec(self):
            assert owner._browser_dialog_depth==1
            if newer_during_dialog:owner.statusBar().showMessage('Newer recovery notice')
        def deleteLater(self):seen['disposed']=True
    monkeypatch.setattr(shell,'QMessageBox',Dialog)
    monkeypatch.delenv('DLMS_DESKTOP_AUTOMATED')
    owner._choose_backup(still_authorized=lambda:True)
    assert seen['format']==Qt.TextFormat.PlainText
    assert '<b>synthetic native error</b>' in seen['text']
    assert seen['disposed'] and owner._browser_dialog_depth==0
    assert owner.focused==([] if newer_during_dialog else [True])
