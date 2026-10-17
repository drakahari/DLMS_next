import os
from types import SimpleNamespace as NS
import pytest
from PySide6.QtCore import QUrl,QCoreApplication
from PySide6.QtDBus import QDBusMessage,QDBusObjectPath
from PySide6.QtWidgets import QApplication
from desktop import external_browser as browser

@pytest.fixture(scope='session')
def app():
 return QCoreApplication.instance() or QApplication([])

class Bar:
 def __init__(self):self.message=''
 def showMessage(self,message):self.message=message
 def currentMessage(self):return self.message
 def setToolTip(self,*a):pass
 def setAccessibleDescription(self,*a):pass

def owner():
 bar=Bar()
 return NS(mode='local',_browser_generation=1,view=object(),_closing=False,statusBar=lambda:bar,_browser_dialog_depth=0,_close_after_dialog=False),bar

@pytest.mark.parametrize('target',['file:///tmp/private','javascript:alert(1)','http://localhost/','http://127.0.0.1:9001/','https://name:pass@host.invalid/'])
def test_bad_urls_never_create_request(target,monkeypatch):
 monkeypatch.setattr(browser,'PortalRequest',lambda *a:pytest.fail('request created'))
 with pytest.raises(ValueError):browser.dispatch(QUrl(target))


def test_request_stays_pending_until_exact_sender_path_and_verified_handle(app):
 r=browser.PortalRequest('https://example.invalid/');out=[];r.finished.connect(lambda *x:out.append(x))
 r.portal_owner=':1.42';r.expected=browser.PATH+'/request/1_99/dlms_fixture'
 def signal(sender,path,code):
  r.response(NS(service=lambda:sender,path=lambda:path,arguments=lambda:[code,{}]))
 signal(':1.99',r.expected,0);signal(':1.42',r.expected+'/wrong',0)
 assert not out
 signal(':1.42',r.expected,0);assert not out # Even early success waits for exact method reply.
 m=NS(type=lambda:QDBusMessage.MessageType.ReplyMessage,arguments=lambda:[QDBusObjectPath(r.expected)])
 r._opened(m);assert out[0][0]=='accepted'
 r._response_code(1);assert len(out)==1

@pytest.mark.parametrize('change',['mode','view','generation','new-status','new-request','closing','retiring'])
def test_async_ui_cannot_overwrite_new_context(app,monkeypatch,change):
 from desktop.shell import handoff_external
 o,b=owner();r=browser.PortalRequest('https://chatgpt.com/')
 monkeypatch.setattr('desktop.shell.dispatch_external',lambda url:r)
 handoff_external(o,QUrl('https://chatgpt.com/'),ai=True);assert 'Requesting' in b.message
 if change=='mode':o.mode='server'
 elif change=='view':o.view=object()
 elif change=='generation':o._browser_generation+=1
 elif change=='new-status':b.message='A later operation'
 elif change=='new-request':o._external_handoff_serial+=1
 elif change=='retiring':o._retiring_browser=object()
 else:o._closing=True
 before=b.message;r._finish('accepted','session accepted');assert b.message==before

@pytest.mark.parametrize('outcome',['accepted','cancelled','unconfirmed','unavailable'])
def test_truthful_async_ui(app,monkeypatch,outcome):
 from desktop.shell import handoff_external
 from PySide6.QtWidgets import QMessageBox
 o,b=owner();r=browser.PortalRequest('https://chatgpt.com/');warnings=[]
 monkeypatch.setattr('desktop.shell.dispatch_external',lambda url:r)
 monkeypatch.setattr(QMessageBox,'warning',lambda *args:warnings.append(args[2]))
 handoff_external(o,QUrl('https://chatgpt.com/'),ai=True)
 assert 'Requesting' in b.message and 'accepted' not in b.message
 r._finish(outcome,'result '+outcome)
 assert b.message.startswith('result '+outcome)
 assert ('Paste manually' in b.message)==(outcome=='accepted')
 assert bool(warnings)==(outcome in {'unconfirmed','unavailable'})


def test_other_platform_does_not_import_qtdbus(app,monkeypatch):
 import builtins
 from desktop.shell import handoff_external
 o,b=owner();original=builtins.__import__
 def guarded(name,*args,**kwargs):
  if name in {'external_browser','PySide6.QtDBus'}:raise AssertionError('Linux-only import reached other platform')
  return original(name,*args,**kwargs)
 monkeypatch.setattr('desktop.shell.sys.platform','win32')
 monkeypatch.setattr('desktop.shell.dispatch_external',lambda url:True)
 monkeypatch.setattr(builtins,'__import__',guarded)
 handoff_external(o,QUrl('https://example.invalid/'))
 assert b.message=='Browser handoff requested.'


def test_request_cap_and_no_environment_handoff(app,monkeypatch,tmp_path):
 monkeypatch.setattr(browser,'_active',set(range(8)))
 with pytest.raises(OSError,match='still pending'):browser.dispatch(QUrl('https://example.invalid/'))
 monkeypatch.setattr(browser,'_active',set())
 for key in ('HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
  monkeypatch.setenv(key,str(tmp_path/'already-scoped-before-DLMS'))
 monkeypatch.setenv('BROWSER','/invalid/do-not-run')
 before=dict(os.environ);addresses=[]
 monkeypatch.setattr(browser,'PortalRequest',lambda address:addresses.append(address) or object())
 browser.dispatch(QUrl('https://example.invalid/path?q=bounded'))
 assert addresses==['https://example.invalid/path?q=bounded'] and dict(os.environ)==before
