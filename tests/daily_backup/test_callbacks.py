from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QUrl
from desktop.shell import DesktopWindow


class Signal:
    def connect(self, callback):self.callback=callback


class Request:
    DownloadState=SimpleNamespace(DownloadCompleted=1,DownloadCancelled=2,DownloadInterrupted=3)
    def __init__(self, page, operation):
        self._page=page;self.operation=operation;self.isFinishedChanged=Signal();self.stateChanged=Signal();self.cancelled=False
    def url(self):return QUrl('http://127.0.0.1:43210/settings/backup/create?desktop_output='+self.operation)
    def page(self):return self._page
    def downloadFileName(self):return 'backup.zip'
    def setDownloadDirectory(self, value):self.directory=value
    def setDownloadFileName(self, value):pass
    def cancel(self):self.cancelled=True
    def accept(self):pass
    def state(self):return 1


def window(tmp_path):
    page=SimpleNamespace(document_generation=0);messages=[];calls=[]
    w=SimpleNamespace(port=43210,mode='local',paths={'downloads':tmp_path,'root':tmp_path},manifest={'uuid':'fixture','epoch':'first'},_closing=False,_retiring_browser=None,_browser_generation=1,
        view=SimpleNamespace(page=lambda:page,url=lambda:QUrl('http://127.0.0.1:43210/settings/backup')),_backup_creating=True,
        backup_output_selection={'operation':'old','path':str(tmp_path/'output.zip')},
        backup_output_operation='old',backup_output_future=None,download_results=[],downloaded_files=[],
        statusBar=lambda:SimpleNamespace(showMessage=messages.append),
        backup_selection_executor=SimpleNamespace(submit=lambda *a: calls.append(a) or Future()),
        backup_output_timer=SimpleNamespace(start=lambda:None),
        _backup_feedback_ticket=1, _feedback=lambda ticket,message,severity='info':messages.append(message))
    return w,page,calls


def test_duplicate_request_cannot_claim_same_selection(tmp_path):
    w,page,calls=window(tmp_path)
    first=Request(page,'old');DesktopWindow._download(w,first)
    duplicate=Request(page,'old');DesktopWindow._download(w,duplicate)
    assert duplicate.cancelled and w.backup_output_selection is None
    first.stateChanged.callback(1)
    first.isFinishedChanged.callback()
    first.stateChanged.callback(1)
    assert len(calls)==1 and calls[0][2]['operation']=='old'


def test_stale_completion_cannot_consume_new_destination(tmp_path):
    w,page,calls=window(tmp_path)
    old=Request(page,'old');DesktopWindow._download(w,old)
    w.backup_output_operation='new'
    w.backup_output_selection={'operation':'new','path':str(tmp_path/'new.zip')}
    old.isFinishedChanged.callback()
    assert not calls and w._backup_creating
    assert w.backup_output_selection['operation']=='new'
    assert w.download_results[0]['state']=='unconfirmed_old_operation'


def test_wrong_page_and_old_operation_refused(tmp_path):
    w,page,calls=window(tmp_path)
    for request in (Request(object(),'old'),Request(page,'unknown')):
        DesktopWindow._download(w,request)
        assert request.cancelled
    assert w.backup_output_selection['operation']=='old' and not calls


def test_open_folder_is_explicit_local_only(tmp_path,monkeypatch):
    from desktop import shell
    calls=[]
    monkeypatch.setattr(shell.QDesktopServices,'openUrl',lambda url:calls.append(url.toLocalFile()) or True)
    w=SimpleNamespace(mode='server',last_backup_output=tmp_path/'saved.zip')
    DesktopWindow._open_backup_folder(w);assert not calls
    w.mode='local';DesktopWindow._open_backup_folder(w)
    assert [Path(path) for path in calls]==[tmp_path]
