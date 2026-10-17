"""An interrupted Qt transfer is terminal to our UI even when isFinished=false."""
from types import SimpleNamespace as NS
from PySide6.QtCore import QObject,Signal,QUrl
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest as QR
import pytest
from desktop.shell import DesktopWindow
from desktop.operation_feedback import OperationFeedback
PAGE=NS(document_generation=0)

@pytest.fixture(autouse=True)
def final_publication_stub(monkeypatch):
    # This unit isolates Qt transfer terminal signals; actual native publication
    # and no-overwrite outcomes are covered in linux_windows tests.
    def publish(owner,record,**kwargs):
        record["native_export"]=True;record["state"]="completed"
        owner._feedback(record["feedback_ticket"],"Export saved", "success")
    monkeypatch.setattr("desktop.exports.begin",publish)

class Request(QObject):
    isFinishedChanged=Signal()
    stateChanged=Signal(object)
    DownloadState=QR.DownloadState
    def __init__(self):super().__init__();self.current=QR.DownloadState.DownloadRequested;self.accepted=False
    def page(self):return PAGE
    def url(self):return QUrl('http://127.0.0.2:8000/export/quiz/1.txt')
    def downloadFileName(self):return 'synthetic.txt'
    def setDownloadDirectory(self,value):self.directory=value
    def setDownloadFileName(self,value):self.name=value
    def accept(self):self.accepted=True
    def cancel(self):self.current=QR.DownloadState.DownloadCancelled
    def state(self):return self.current
    def isFinished(self):return False
    def interruptReasonString(self):return 'Bounded synthetic network interruption'

@pytest.mark.parametrize('terminal,expected',[(QR.DownloadState.DownloadCompleted,'completed'),(QR.DownloadState.DownloadCancelled,'cancelled'),(QR.DownloadState.DownloadInterrupted,'interrupted')])
def test_server_state_signal_settles_once_without_isfinished(terminal,expected,tmp_path):
    state=OperationFeedback();messages=[];profile=object()
    w=NS(mode='server',mode_config={'server':{'origin':'http://127.0.0.2:8000','id':'fixture'}},
         server_paths={'downloads':tmp_path,'root':tmp_path},profile=profile,_closing=False,_retiring_browser=None,_browser_generation=1,view=NS(page=lambda:PAGE,url=lambda:QUrl('http://127.0.0.2:8000/library')),download_results=[],
         _begin_feedback=lambda action:state.begin(action),_feedback=lambda ticket,message,*args:messages.append(message) if state.update(ticket,message) else None,
         statusBar=lambda:NS(showMessage=messages.append))
    r=Request();DesktopWindow._server_download(w,r);assert r.accepted
    r.current=terminal;r.stateChanged.emit(terminal)
    assert w.download_results[-1]['state']==expected
    before=list(messages);r.isFinishedChanged.emit();r.stateChanged.emit(terminal)
    assert messages==before,'Repeated terminal notifications must not duplicate outcome reporting'


def test_old_server_completion_cannot_replace_newer_feedback(tmp_path):
    state=OperationFeedback();messages=[]
    w=NS(mode='server',mode_config={'server':{'origin':'http://127.0.0.2:8000','id':'fixture'}},server_paths={'downloads':tmp_path,'root':tmp_path},
        profile=object(),_closing=False,_retiring_browser=None,_browser_generation=1,view=NS(page=lambda:PAGE,url=lambda:QUrl('http://127.0.0.2:8000/library')),download_results=[],_begin_feedback=lambda action:state.begin(action),
        _feedback=lambda ticket,message,*args:messages.append(message) if state.update(ticket,message) else None,
        statusBar=lambda:NS(showMessage=messages.append))
    first,second=Request(),Request();DesktopWindow._server_download(w,first);DesktopWindow._server_download(w,second)
    before=list(messages);first.current=QR.DownloadState.DownloadCompleted;first.stateChanged.emit(first.current)
    assert w.download_results[0]['state']=='completed' and messages==before
    second.current=QR.DownloadState.DownloadCancelled;second.stateChanged.emit(second.current)
    assert w.download_results[1]['state']=='cancelled' and len(messages)==len(before)+1


@pytest.mark.parametrize('same_url',[False,True])
def test_inflight_export_navigation_retains_private_bytes_without_prompt(tmp_path,monkeypatch,same_url):
    page=NS(document_generation=0)
    current=[QUrl('http://127.0.0.2:8000/library')]
    w=NS(mode='server',mode_config={'server':{'origin':'http://127.0.0.2:8000','id':'fixture'}},
        server_paths={'downloads':tmp_path,'root':tmp_path},profile=object(),_closing=False,_retiring_browser=None,
        _browser_generation=1,view=NS(page=lambda:page,url=lambda:current[0]),download_results=[],
        _begin_feedback=lambda action:1,_feedback=lambda *a:None,statusBar=lambda:NS(showMessage=lambda *a:None))
    r=Request();r.page=lambda:page
    called=[];monkeypatch.setattr('desktop.exports.begin',lambda *a,**kw:called.append(True))
    DesktopWindow._server_download(w,r)
    page.document_generation+=1
    if not same_url:current[0]=QUrl('http://127.0.0.2:8000/review')
    r.current=QR.DownloadState.DownloadCompleted;r.stateChanged.emit(r.current)
    assert w.download_results[0]['state']=='completed_private' and not called
