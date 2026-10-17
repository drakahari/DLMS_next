"""Qt attachment classification must never turn real failures into success."""
from types import SimpleNamespace as NS
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineLoadingInfo as LI
from desktop.shell import DesktopWindow


def fixture(mode='server', loading=False):
    url=QUrl('http://127.0.0.1:8123/library');calls=[]
    view=NS(url=lambda:url,page=lambda:NS(isLoading=lambda:loading))
    window=NS(failed_reason=None,_settings_transition_refused=False,maintenance_transition=False,
        import_in_progress=False,backend=NS(poll=lambda:None),view=view,mode=mode,_closing=False,_retiring_browser=None,port=8123,
        mode_config={'server':{'origin':'http://127.0.0.1:8123'}},_local_loaded_url=bytes(url.toEncoded()),
        _server_loaded_url=bytes(url.toEncoded()),_server_previous_document=('doc',123),
        server_readiness_timer=NS(stop=lambda:calls.append('stop')),_server_probe_ticket=2,
        _server_probe_pending=True,server_unreachable=False,_server_document_identity=None,
        _set_server_page_exposed=lambda v:calls.append(('expose',v)),_update_mode_toolbar=lambda:None,
        statusBar=lambda:NS(showMessage=lambda s:calls.append(s)),
        server_status=NS(setText=lambda s:calls.append(s)),
        _settings_page_loaded=lambda *a:calls.append(('local',a)),
        _server_load_finished=lambda ok:calls.append(('server',ok)))
    return window,view,calls


def info(status=LI.LoadStatus.LoadStoppedStatus,download=True,url='http://127.0.0.1:8123/export/all_quizzes.txt'):
    return NS(status=lambda:status,isDownload=lambda:download,url=lambda:QUrl(url),errorDomain=lambda:LI.ErrorDomain.ConnectionErrorDomain,errorCode=lambda:-105,isErrorPage=lambda:True)


@pytest.mark.parametrize('mode',['local','server'])
def test_attachments_keep_only_previously_loaded_same_origin_document(mode):
    window,view,calls=fixture(mode)
    DesktopWindow._page_loading_changed(window,info(),view,mode)
    if mode=='local':assert calls==[('local',(True,view))]
    else:assert ('expose',True) in calls and window._server_document_identity==('doc',123)


@pytest.mark.parametrize('mode',['local','server'])
@pytest.mark.parametrize('status',[LI.LoadStatus.LoadFailedStatus,LI.LoadStatus.LoadStoppedStatus,LI.LoadStatus.LoadSucceededStatus])
def test_non_download_failures_remain_failures(mode,status):
    window,view,calls=fixture(mode)
    DesktopWindow._page_loading_changed(window,info(status,False),view,mode)
    ok=status==LI.LoadStatus.LoadSucceededStatus
    assert calls==([(mode,(ok,view))] if mode=='local' else [(mode,ok)])


@pytest.mark.parametrize('mode',['local','server'])
@pytest.mark.parametrize('change',['retired','closing','newmode','superseded','foreign','initial'])
def test_attachment_cannot_expose_wrong_context(mode,change):
    w,v,calls=fixture(mode,loading=change=='superseded')
    if change=='retired':w._retiring_browser=object()
    if change=='closing':w._closing=True
    if change=='newmode':w.mode='other'
    if change=='initial':w._local_loaded_url=w._server_loaded_url=None
    event=info(url='https://foreign.invalid/download') if change=='foreign' else info()
    DesktopWindow._page_loading_changed(w,event,v,mode)
    assert ('expose',True) not in calls and not any(isinstance(c,tuple) and c[0]=='local' for c in calls)

@pytest.mark.parametrize('enabled',[False,True])
def test_mix_timing_not_in_normal_menus(enabled,monkeypatch):
    from PySide6.QtWidgets import QApplication,QMainWindow
    app=QApplication.instance() or QApplication([])
    window=QMainWindow()
    for name in ('switch_to_local','switch_to_server','_configure_server_dialog','_retry_server',
                 '_capture_mix_diagnostics','_show_about','_style_mode_control','_update_mode_toolbar'):
        setattr(window,name,lambda *_:None)
    if enabled:monkeypatch.setenv('DLMS_DESKTOP_DEBUG_MIX_TIMING','1')
    else:monkeypatch.delenv('DLMS_DESKTOP_DEBUG_MIX_TIMING',raising=False)
    DesktopWindow._create_mode_toolbar(window)
    assert any('Capture Mix timing' in a.text() for a in window.mode_menu.actions())==enabled
    assert (window.mix_diagnostic_action is not None)==enabled
    window.close()

@pytest.mark.parametrize('mode',['local','server'])
@pytest.mark.parametrize('code',[400,403,404,409,500,503])
def test_same_origin_http_error_document_keeps_actionable_feedback_without_native_privileges(mode,code):
    w,v,calls=fixture(mode);v.show=lambda:calls.append('show');w.settings_fallback=NS(hide=lambda:calls.append('hide-fallback'))
    w._settings_navigation_started=lambda:calls.append('reset-privileges')
    w._poll_mode_theme=lambda:calls.append('palette-only')
    event=info(LI.LoadStatus.LoadFailedStatus,False,'http://127.0.0.1:8123/library')
    event.errorDomain=lambda:LI.ErrorDomain.HttpStatusCodeDomain
    event.errorCode=lambda:code;event.isErrorPage=lambda:False
    DesktopWindow._page_loading_changed(w,event,v,mode)
    assert any(isinstance(c,str) and f'HTTP {code}' in c and 'no successful save' in c for c in calls)
    if mode=='local':assert 'reset-privileges' in calls and 'show' in calls
    else:assert ('expose',True) in calls and w.server_unreachable is False


@pytest.mark.parametrize('change',['native-error','foreign','different-url','network'])
def test_http_error_visibility_exception_cannot_hide_real_connection_failure(change):
    w,v,calls=fixture()
    e=info(LI.LoadStatus.LoadFailedStatus,False,'http://127.0.0.1:8123/library')
    e.errorDomain=lambda:LI.ErrorDomain.HttpStatusCodeDomain;e.errorCode=lambda:400;e.isErrorPage=lambda:False
    if change=='native-error':e.isErrorPage=lambda:True
    if change=='foreign':v.url=lambda:QUrl('https://foreign.invalid/library');e.url=v.url
    if change=='different-url':e.url=lambda:QUrl('http://127.0.0.1:8123/other')
    if change=='network':e.errorDomain=lambda:LI.ErrorDomain.ConnectionErrorDomain
    DesktopWindow._page_loading_changed(w,e,v,'server')
    assert calls==[('server',False)]

@pytest.mark.parametrize('state',['failed_reason','_settings_transition_refused','maintenance_transition','import_in_progress','dead-backend'])
@pytest.mark.parametrize('download',[True,False])
def test_terminal_response_cannot_uncover_local_recovery_guidance(state,download):
    w,v,calls=fixture('local')
    if state=='dead-backend':w.backend.poll=lambda:1
    else:setattr(w,state,True)
    event=info(LI.LoadStatus.LoadFailedStatus,download,'http://127.0.0.1:8123/library')
    event.errorDomain=lambda:LI.ErrorDomain.HttpStatusCodeDomain;event.errorCode=lambda:400;event.isErrorPage=lambda:False
    DesktopWindow._page_loading_changed(w,event,v,'local')
    assert calls==[]
