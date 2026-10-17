import json,time
from types import SimpleNamespace as NS
from PySide6.QtCore import QUrl
import pytest
from desktop.ai_actions import AIHandoff


def fixture(monkeypatch):
 pending=[];opened=[];generic=[];blocked=[]
 page=NS(url=lambda:QUrl('http://127.0.0.1:8456/quizzes/fixture.html'),runJavaScript=lambda script,world,callback:pending.append((script,callback)))
 view=NS(page=lambda:page)
 owner=NS(view=view,mode='local',port=8456,_browser_generation=1,_closing=False,_retiring_browser=None,
          manifest={'uuid':'fixture','epoch':'first'},mode_config={},note_blocked=lambda url:blocked.append(url.toString()),
          statusBar=lambda:bar)
 from tests.session_browser.test_contract import Bar
 bar=Bar()
 a=NS(owner=owner,page=page,epoch=2,used=0,started=time.monotonic())
 monkeypatch.setattr('desktop.shell.dispatch_external',lambda url:opened.append(url.toString()) or True)
 value=json.dumps({'state':'ai','id':1,'epoch':2,'href':page.url().toString(),'timeOrigin':1000})
 def request(user=True):AIHandoff.handle(a,QUrl('https://chatgpt.com/'),user,generic=lambda:generic.append(True))
 return a,owner,pending,opened,generic,blocked,value,request


def test_consumes_before_any_async_work_and_only_once(monkeypatch):
 a,o,p,opened,g,b,v,request=fixture(monkeypatch);request();assert a.used==2
 request();assert len(p)==1
 p.pop(0)[1](v);assert len(p)==1
 p.pop(0)[1](True);assert opened==['https://chatgpt.com/']
 request();assert len(opened)==1

@pytest.mark.parametrize('boundary',['take','validate'])
@pytest.mark.parametrize('change',['epoch','mode','profile','retirement','closing','view','origin','generation'])
def test_stale_callback_cannot_open(monkeypatch,boundary,change):
 a,o,p,opened,g,b,v,request=fixture(monkeypatch);request()
 if boundary=='validate':p.pop(0)[1](v)
 if change=='epoch':a.epoch+=1
 elif change=='mode':o.mode='server'
 elif change=='profile':o.manifest['epoch']='new'
 elif change=='retirement':o._retiring_browser=object()
 elif change=='closing':o._closing=True
 elif change=='view':o.view=None
 elif change=='origin':a.page.url=lambda:QUrl('https://hostile.invalid/')
 elif change=='generation':o._browser_generation+=1
 p.pop(0)[1](v if boundary=='take' else True)
 assert not opened and not g

@pytest.mark.parametrize('native,fresh',[(False,True),(True,False)])
def test_native_and_fresh_input_required(monkeypatch,native,fresh):
 a,o,p,opened,g,b,v,request=fixture(monkeypatch)
 if not fresh:a.started-=6
 request(native);assert not p and not opened and not g

@pytest.mark.parametrize('raw',['null','{}','{"state":"ai"}','{"state":"refused"}','forged','{"state":"generic"}'])
def test_invalid_or_generic_private_reply_never_auto_opens(monkeypatch,raw):
 a,o,p,opened,g,b,v,request=fixture(monkeypatch);request();p.pop(0)[1](raw)
 assert not opened
 assert len(g)==int(raw=='{"state":"generic"}')
