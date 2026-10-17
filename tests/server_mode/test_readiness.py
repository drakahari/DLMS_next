import json,time
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineScript
from desktop.server_readiness import document_identity,ready_new_document,READINESS_SCRIPT
from desktop.shell import DesktopWindow

URL='http://127.0.0.2:8123/library'
SNAPSHOT={'href':URL,'timeOrigin':2000,'ready':'interactive','responseStatus':200,'responseEnd':14,'theme':'ethereal'}
PREVIOUS=('http://127.0.0.2:8123/history',1000)

def test_ready_is_not_save_or_load_completion():
    assert ready_new_document(SNAPSHOT,PREVIOUS,URL)
    assert not ready_new_document(SNAPSHOT,None,URL)
    assert not ready_new_document(SNAPSHOT,(URL,2000),URL)
    assert not ready_new_document(SNAPSHOT,('different',2000),URL)

@pytest.mark.parametrize('key,value', [('href','http://127.0.0.1:8123/'),('ready','loading'),('ready',None),('ready',{}),('ready',[]),('responseStatus',500),('responseStatus','200'),('responseStatus',200.0),('responseEnd',0),('responseEnd',True),('responseEnd',float('nan')),('responseEnd',float('inf')),('timeOrigin',None),('timeOrigin',float('nan')),('timeOrigin',True)])
def test_missing_invalid_or_error_evidence_refuses(key,value):
    snapshot=SNAPSHOT|{key:value}
    assert not ready_new_document(snapshot,PREVIOUS,URL)

class Timer:
    def __init__(self):self.active=True
    def isActive(self):return self.active
    def stop(self):self.active=False
class Page:
    def __init__(self):self.loading=True;self.location=QUrl(URL)
    def isLoading(self):return self.loading
    def url(self):return self.location
    def runJavaScript(self,expr,world,callback):
        assert expr==READINESS_SCRIPT and world==QWebEngineScript.ScriptWorldId.ApplicationWorld
        self.callback=callback

def fixture():
    page=Page();calls=[]
    view=SimpleNamespace(page=lambda:page,show=lambda:calls.append('show'),isVisible=lambda:True)
    window=SimpleNamespace(mode='server',_closing=False,_retiring_browser=None,view=view,
        _server_probe_pending=False,_server_probe_deadline=time.monotonic()+5,_server_probe_ticket=0,_server_navigation_serial=1,_browser_generation=1,
        mode_config={'server':{'origin':'http://127.0.0.2:8123'}},server_readiness_timer=Timer(),
        _server_previous_document=PREVIOUS,_server_document_identity=None,_server_early_revealed=False,
        _server_theme='',_server_page_exposed=True,server_unreachable=False,server_loaded_once=True,
        server_status=SimpleNamespace(hide=lambda:calls.append('hide')),
        _style_server_surface=lambda:calls.append('style'),
        _set_server_page_exposed=lambda exposed:calls.extend(["hide","show"] if exposed else []),
        statusBar=lambda:SimpleNamespace(showMessage=lambda message:calls.append(message)))
    DesktopWindow._probe_server_readiness(window)
    return window,page,calls

def test_provisional_reveal_remains_loading_not_a_save_ack():
    window,page,calls=fixture();page.callback(json.dumps(SNAPSHOT))
    assert window._server_early_revealed and not window.server_readiness_timer.active
    assert window._server_document_identity==(URL,2000)
    assert calls==['style','hide','show','Server page visible; still loading resources…']

@pytest.mark.parametrize('change',['closing','retirement','local','page','serial','generation','ticket','origin','wrong_url','no_longer_loading','previous_missing','old_document','failed_status'])
def test_stale_or_unverified_probe_cannot_reveal(change):
    window,page,calls=fixture();snapshot=SNAPSHOT.copy()
    if change=='closing':window._closing=True
    elif change=='retirement':window._retiring_browser=object()
    elif change=='local':window.mode='local'
    elif change=='page':window.view=SimpleNamespace(page=lambda:Page())
    elif change=='serial':window._server_navigation_serial+=1
    elif change=='generation':window._browser_generation+=1
    elif change=='ticket':window._server_probe_ticket+=1
    elif change=='origin':window.mode_config['server']['origin']='https://example.invalid'
    elif change=='wrong_url':page.location=QUrl('http://127.0.0.1:8123/library')
    elif change=='no_longer_loading':page.loading=False
    elif change=='previous_missing':window._server_previous_document=None
    elif change=='old_document':snapshot['timeOrigin']=1000
    elif change=='failed_status':snapshot['responseStatus']=500
    page.callback(json.dumps(snapshot));assert not calls and not window._server_early_revealed

def test_completion_captures_identity_but_never_permits_old_probe():
    window,page,calls=fixture();old=page.callback
    window._server_probe_ticket+=1;window._server_probe_pending=False;page.loading=False
    DesktopWindow._probe_server_readiness(window,completed=True)
    current=page.callback;old(json.dumps(SNAPSHOT));assert window._server_document_identity is None
    current(json.dumps(SNAPSHOT));assert window._server_document_identity==(URL,2000) and not calls


def test_poll_budget_stops_without_claiming_failure_or_success():
    window,page,calls=fixture();window._server_probe_deadline=0
    DesktopWindow._probe_server_readiness(window)
    assert not window.server_readiness_timer.active and not calls
    page.callback(json.dumps(SNAPSHOT))
    assert not calls and not window._server_early_revealed


def test_completion_cannot_record_a_covered_document():
    window,page,calls=fixture()
    window._server_probe_pending=False;page.loading=False;window._server_page_exposed=False
    DesktopWindow._probe_server_readiness(window,completed=True)
    page.callback(json.dumps(SNAPSHOT))
    assert window._server_document_identity is None and not calls
