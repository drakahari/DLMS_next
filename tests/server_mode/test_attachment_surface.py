"""Attachment recovery must never reveal a different/failed Server document."""
import json
import os
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineLoadingInfo, QWebEngineScript, QWebEngineDownloadRequest
from desktop.shell import DesktopWindow
from desktop.server_readiness import READINESS_SCRIPT

URL='http://127.0.0.2:8123/library'
SNAPSHOT={'href':URL,'timeOrigin':1000,'ready':'complete'}


class Page:
    loading=False
    location=QUrl(URL)
    def isLoading(self):return self.loading
    def url(self):return self.location
    def runJavaScript(self,script,world,callback):
        assert script==READINESS_SCRIPT and world==QWebEngineScript.ScriptWorldId.ApplicationWorld
        self.callback=callback


def fixture():
    calls=[];page=Page()
    view=SimpleNamespace(page=lambda:page)
    window=SimpleNamespace(mode='server',_closing=False,_retiring_browser=None,view=view,
        _browser_generation=1,_server_navigation_serial=2,_server_probe_ticket=3,
        _server_probe_pending=True,_server_previous_document=(URL,1000),
        _server_document_identity=None,_server_has_document=True,_server_connection_attempt=False,
        server_unreachable=False,mode_config={'server':{'origin':'http://127.0.0.2:8123'}},
        server_readiness_timer=SimpleNamespace(stop=lambda:calls.append('stop')),
        _server_load_finished=lambda ok:calls.append(('finish',ok)),
        _update_mode_toolbar=lambda:calls.append('toolbar'),
        _set_server_page_exposed=lambda exposed:calls.append(('expose',exposed)))
    return window,page,calls


def test_only_exact_retained_document_restores_presentation():
    window,page,calls=fixture()
    DesktopWindow._restore_server_attachment_document(window,page,1)
    page.callback(json.dumps(SNAPSHOT))
    assert calls==['stop','toolbar',('expose',True)]
    assert window._server_document_identity==(URL,1000) and not window.server_unreachable


@pytest.mark.parametrize('change',['closing','retired','local','page','generation','serial','ticket','origin','loading'])
def test_late_identity_callback_cannot_change_current_surface(change):
    window,page,calls=fixture()
    DesktopWindow._restore_server_attachment_document(window,page,1)
    if change=='closing':window._closing=True
    elif change=='retired':window._retiring_browser=object()
    elif change=='local':window.mode='local'
    elif change=='page':window.view=SimpleNamespace(page=lambda:Page())
    elif change=='generation':window._browser_generation+=1
    elif change=='serial':window._server_navigation_serial+=1
    elif change=='ticket':window._server_probe_ticket+=1
    elif change=='origin':window.mode_config['server']['origin']='http://127.0.0.2:9001'
    elif change=='loading':page.loading=True
    page.callback(json.dumps(SNAPSHOT));assert calls==['stop']


@pytest.mark.parametrize('value',[None,'bad json','null','{}','[]',json.dumps(SNAPSHOT|{'timeOrigin':2000}),json.dumps(SNAPSHOT|{'href':'http://127.0.0.1:8123/library'}),json.dumps(SNAPSHOT|{'ready':'loading'})])
def test_missing_wrong_or_incomplete_identity_fails_closed(value):
    window,page,calls=fixture()
    DesktopWindow._restore_server_attachment_document(window,page,1)
    page.callback(value);assert calls==['stop',('finish',False)]


@pytest.mark.parametrize('change',['missing','initial','connecting'])
def test_no_prior_verified_page_cannot_be_revealed(change):
    window,page,calls=fixture()
    if change=='missing':window._server_previous_document=None
    elif change=='initial':window._server_has_document=False
    else:window._server_connection_attempt=True
    DesktopWindow._restore_server_attachment_document(window,page,1)
    assert calls==['stop',('finish',False)] and not hasattr(page,'callback')


@pytest.mark.parametrize('download,status,error_page,origin,restores',[
    (True,'LoadStoppedStatus',False,'http://127.0.0.2:8123',True),
    (False,'LoadStoppedStatus',False,'http://127.0.0.2:8123',False),
    (True,'LoadFailedStatus',False,'http://127.0.0.2:8123',False),
    (True,'LoadStoppedStatus',True,'http://127.0.0.2:8123',False),
    (True,'LoadStoppedStatus',False,'http://127.0.0.1:8123',False),
])
def test_qt_confirmation_not_url_suffix_or_error_code_authorizes_recovery(download,status,error_page,origin,restores):
    window,page,calls=fixture()
    window._restore_server_attachment_document=lambda p,g:calls.append('restore')
    info=SimpleNamespace(status=lambda:getattr(QWebEngineLoadingInfo.LoadStatus,status),
        isDownload=lambda:download,isErrorPage=lambda:error_page,
        url=lambda:QUrl(origin+'/export/all_quizzes.txt'))
    DesktopWindow._server_load_information(window,info,page,1)
    assert calls==(['restore'] if restores else [('finish',False)])


class Signal:
    def __init__(self):self.slots=[]
    def connect(self,slot):self.slots.append(slot)
    def emit(self):
        for slot in self.slots:slot()


class Download:
    DownloadState=QWebEngineDownloadRequest.DownloadState
    def __init__(self,page):
        self._page=page;self.current=self.DownloadState.DownloadRequested
        self.isFinishedChanged=Signal();self.stateChanged=Signal();self.cancelled=False
    def page(self):return self._page
    def url(self):return QUrl('http://127.0.0.2:8123/export/all_quizzes.txt')
    def downloadFileName(self):return 'synthetic.txt'
    def cancel(self):self.cancelled=True
    def accept(self):self.current=self.DownloadState.DownloadInProgress
    def setDownloadDirectory(self,path):self.directory=path
    def setDownloadFileName(self,name):self.name=name
    def state(self):return self.current
    def interruptReasonString(self):return 'Synthetic interrupted connection'


def qt_download_fixture(tmp_path):
    """Linux Qt uses private reception followed by a separate native Save As.

    Candidate17's WebView2 download controller has its own native tests in
    tests/webview2/test_export_destinations.py. A received attachment is not
    equivalent to a successfully published visible destination on either host.
    """
    window,page,calls=fixture()
    page.document_generation=1
    window.view.url=page.url
    window.profile=object()
    window.mode_config['server']['id']='synthetic-server'
    window.server_paths={'downloads':tmp_path,'root':tmp_path}
    window.download_results=[]
    window._begin_feedback=lambda action:('synthetic',action)
    window._feedback=lambda ticket,message,severity='info':calls.append(message)
    window.statusBar=lambda:SimpleNamespace(showMessage=lambda message:calls.append(message))
    return window,page,calls


@pytest.mark.parametrize('terminal,state,message',[('DownloadCompleted','in_progress',None),
    ('DownloadCancelled','cancelled','cancelled'),('DownloadInterrupted','interrupted','failed')])
def test_download_outcome_feedback_is_independent_of_page_recovery(tmp_path,monkeypatch,terminal,state,message):
    from desktop import exports
    window,page,calls=qt_download_fixture(tmp_path)
    offered=[]
    def native_offer(owner,record,*,captured):
        assert owner is window and captured==exports.context(window)
        record['native_export']=True
        offered.append(record)
    monkeypatch.setattr(exports,'begin',native_offer)
    request=Download(page)
    DesktopWindow._server_download(window,request)
    assert not request.cancelled and window.download_results[0]['state']=='in_progress'
    request.current=getattr(request.DownloadState,terminal);request.stateChanged.emit()
    record=window.download_results[0]
    assert record['state']==state
    if terminal=='DownloadCompleted':
        # Bytes received permits Save As; it must not claim final publication.
        assert offered==[record] and record['native_export'] is True
        assert 'published_path' not in record and 'sha256' not in record
    else:
        assert not offered and message in calls[-1]
    # Duplicate terminal signal must not offer a second chooser/publication.
    prior=list(calls);request.isFinishedChanged.emit()
    assert calls==prior and len(offered)==(terminal=='DownloadCompleted')


@pytest.mark.parametrize('change',['page','origin','retired','local'])
def test_foreign_or_retired_request_cannot_claim_private_server_destination(tmp_path,change):
    window,page,calls=fixture();window.server_paths={'downloads':tmp_path};window.download_results=[]
    request=Download(page)
    if change=='page':request._page=Page()
    elif change=='origin':request.url=lambda:QUrl('http://127.0.0.1:8123/export/all_quizzes.txt')
    elif change=='retired':window._retiring_browser=object()
    else:window.mode='local'
    DesktopWindow._server_download(window,request)
    assert request.cancelled and not window.download_results and not list(tmp_path.iterdir())


@pytest.mark.parametrize('name',['../outside.txt','C:/elsewhere/other.txt','texte_日本語.txt'])
def test_download_uses_safe_basename_in_fresh_server_staging(tmp_path,name):
    window,page,calls=qt_download_fixture(tmp_path)
    request=Download(page);request.downloadFileName=lambda:name
    DesktopWindow._server_download(window,request)
    assert not request.cancelled
    from pathlib import Path
    destination=Path(window.download_results[0]['path'])
    assert destination.is_relative_to(tmp_path) and destination.name==Path(name).name


@pytest.mark.skipif(os.name!='nt',reason='Windows path ambiguity rules')
@pytest.mark.parametrize('name',['CON.txt','file.txt:stream','trailing.','trailing '])
def test_windows_ambiguous_attachment_name_is_refused(tmp_path,name):
    window,page,calls=qt_download_fixture(tmp_path)
    request=Download(page);request.downloadFileName=lambda:name
    DesktopWindow._server_download(window,request)
    assert request.cancelled and not window.download_results and 'no existing file was replaced' in calls[-1]


def local_fixture():
    window,page,calls=fixture();page.location=QUrl('http://127.0.0.1:8123/library')
    window.mode='local';window.port=8123;window._settings_generation=1
    window._local_previous_document=(page.location.toString(),1000)
    window._local_document_identity=None;window._settings_transition_refused=False
    window.maintenance_transition=False;window.import_in_progress=False;window.failed_reason=None
    window.backend=SimpleNamespace(poll=lambda:None)
    window._settings_page_loaded=lambda ok,view:calls.append(('settings-loaded',ok))
    info=SimpleNamespace(status=lambda:QWebEngineLoadingInfo.LoadStatus.LoadStoppedStatus,
        isDownload=lambda:True,isErrorPage=lambda:False,
        url=lambda:QUrl('http://127.0.0.1:8123/export/all_quizzes.txt'))
    return window,page,info,calls


def test_local_attachment_requires_exact_prior_document_and_existing_settings_validation():
    window,page,info,calls=local_fixture()
    DesktopWindow._local_load_information(window,info,page,1)
    page.callback(json.dumps(SNAPSHOT|{'href':page.url().toString()}))
    assert calls==[('settings-loaded',True)]
    assert window._local_document_identity==window._local_previous_document


@pytest.mark.parametrize('change',['mode','closing','page','generation','settings-generation','retired',
    'maintenance','import','refusal','backend-dead','failed'])
def test_local_attachment_late_callback_cannot_revive_transition_or_other_page(change):
    window,page,info,calls=local_fixture()
    DesktopWindow._local_load_information(window,info,page,1)
    if change=='mode':window.mode='server'
    elif change=='closing':window._closing=True
    elif change=='page':window.view=SimpleNamespace(page=lambda:Page())
    elif change=='generation':window._browser_generation+=1
    elif change=='settings-generation':window._settings_generation+=1
    elif change=='retired':window._retiring_browser=object()
    elif change=='maintenance':window.maintenance_transition=True
    elif change=='import':window.import_in_progress=True
    elif change=='refusal':window._settings_transition_refused=True
    elif change=='backend-dead':window.backend=SimpleNamespace(poll=lambda:1)
    elif change=='failed':window.failed_reason='Synthetic failed backend'
    page.callback(json.dumps(SNAPSHOT|{'href':'http://127.0.0.1:8123/library'}))
    assert calls==[] and window._local_document_identity is None


@pytest.mark.parametrize('change',['missing-previous','new-document','server-origin','incomplete'])
def test_unverified_local_retained_document_stays_failed(change):
    window,page,info,calls=local_fixture();value=SNAPSHOT|{'href':page.url().toString()}
    if change=='missing-previous':window._local_previous_document=None
    DesktopWindow._local_load_information(window,info,page,1)
    if change=='new-document':value['timeOrigin']=2000
    elif change=='server-origin':value['href']=URL
    elif change=='incomplete':value['ready']='loading'
    if hasattr(page,'callback'):page.callback(json.dumps(value))
    assert calls==[('settings-loaded',False)] and window._local_document_identity is None


def test_non_attachment_backup_conflict_preserves_existing_failure_handling():
    window,page,info,calls=local_fixture()
    page.location=QUrl('http://127.0.0.1:8123/settings/backup/create?desktop_output=fixture')
    window._settings_page_loaded=lambda ok,view:DesktopWindow._settings_page_loaded(window,ok,view)
    window.settings_panel=object();window._import_reopen_status=None
    window._backup_creating=True;window.backup_output_operation='fixture';window.backup_output_selection={'operation':'fixture'}
    window._active_outputs=lambda:False
    window._backup_feedback_ticket=1
    window._feedback=lambda *args:calls.append(('feedback',args))
    window._settings_navigation_started=lambda:calls.append('navigation-started')
    window.view.url=lambda:page.location;window.view.show=lambda:calls.append('show')
    DesktopWindow._settings_page_loaded(window,False,window.view)
    assert not window._backup_creating and window.backup_output_selection is None
    assert calls[:2]==['navigation-started','show'] and 'no selected file was published' in calls[-1][1][1]
