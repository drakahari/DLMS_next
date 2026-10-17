from pathlib import Path
from types import SimpleNamespace, MethodType

from desktop.operation_feedback import OperationFeedback
from desktop.shell import DesktopWindow


def test_attempt_invalidates_previous_callbacks_before_selection():
    state = OperationFeedback()
    old = state.begin('create_backup')
    assert state.update(old, 'Backup saved', 'success')
    new = state.begin('create_backup')
    assert not state.message
    assert state.update(new, 'Backup destination refused', 'error')
    assert not state.update(old, 'Late saved', 'success')
    assert (state.action, state.message, state.severity) == ('create_backup', 'Backup destination refused', 'error')
    cancelled = state.begin('backup')
    assert state.update(cancelled, 'Canceled')
    assert not state.update(new, 'Late refusal', 'error')


def fake():
    state = OperationFeedback()
    messages=[]
    bar=SimpleNamespace(showMessage=messages.append, setToolTip=lambda value:None,
                        setAccessibleDescription=lambda value:None)
    w=SimpleNamespace(operation_feedback=state,failed_reason=None,mode='local',_feedback_mode='local',_settings_transition_refused=False,
        statusBar=lambda:bar,_render_backup_feedback=lambda **kw:None,pdf_results=[],pdf_files=[])
    w._feedback=MethodType(DesktopWindow._feedback,w)
    return w,messages


def test_pdf_completes_once_and_old_callback_cannot_hide_new_refusal(tmp_path):
    w,messages=fake()
    pdf=tmp_path/'synthetic.pdf';pdf.write_bytes(b'%PDF-fixture')
    old=w.operation_feedback.begin('pdf')
    w.pdf_results.append({'path':str(pdf),'state':'in_progress','feedback_ticket':old})
    new=w.operation_feedback.begin('create_backup')
    w._feedback(new,'Backup destination refused','error')
    DesktopWindow._pdf_finished(w,str(pdf),True)
    DesktopWindow._pdf_finished(w,str(pdf),False)
    assert w.pdf_results[0]['state']=='completed' and w.pdf_files==[pdf]
    assert messages==['Backup destination refused']


def test_failed_app_or_server_never_receives_local_completion():
    w,messages=fake();ticket=w.operation_feedback.begin('backup')
    w.failed_reason='Backend stopped'
    assert not w._feedback(ticket,'saved','success') and not messages
    w.failed_reason=None;w.mode='server'
    assert not w._feedback(ticket,'saved','success') and not messages
    assert not w.operation_feedback.message


def test_open_folder_failure_keeps_saved_path(monkeypatch,tmp_path):
    from desktop import shell
    w,messages=fake();w.last_backup_output=tmp_path/'saved.zip'
    w._begin_feedback=w.operation_feedback.begin
    monkeypatch.setattr(shell.QDesktopServices,'openUrl',lambda url:False)
    DesktopWindow._open_backup_folder(w)
    assert str(w.last_backup_output) in messages[-1]
    assert 'remains saved' in messages[-1] and 'could not be opened' in messages[-1]
