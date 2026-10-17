"""Matched headed Chrome/source-Qt measurements with isolated synthetic content.

No OS input, no graphics overrides, no normal-package acceptance claim.
"""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time
from urllib.parse import urlsplit
from tests.windows.normal_processes import descendants,identity,alive
from desktop.isolation import PROJECT

SCRIPT=(PROJECT/'tests/windows/responsiveness.js').read_text()


def wait(predicate,timeout=45):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        result=predicate()
        if result:return result
        time.sleep(.03)
    raise TimeoutError('Responsiveness checkpoint')


def json_http(port,path,method='GET'):
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
    try:
        c.request(method,path);r=c.getresponse();assert r.status==200,r.status;return json.loads(r.read())
    finally:c.close()


spec=importlib.util.spec_from_file_location('dlms_fixture_websocket',PROJECT/'tests/browser/_bidi.py')
bidi=importlib.util.module_from_spec(spec);spec.loader.exec_module(bidi)
FirefoxBidi=bidi.FirefoxBidi
class CDP(FirefoxBidi):
    @classmethod
    def connect_url(cls,url):
        u=urlsplit(url)
        assert u.scheme=='ws' and u.hostname=='127.0.0.1'
        sock=socket.create_connection((u.hostname,u.port),timeout=15)
        key=base64.b64encode(os.urandom(16)).decode()
        try:
            sock.sendall((f'GET {u.path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            data=b''
            while b'\r\n\r\n' not in data:
                data+=sock.recv(4096)
                if len(data)>65536:raise ValueError('Oversized CDP handshake')
            header,remainder=data.split(b'\r\n\r\n',1)
            assert header.startswith(b'HTTP/1.1 101 '),header[:100]
            ack=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            assert ack.lower() in header.lower()
            return cls(sock,remainder)
        except BaseException:sock.close();raise
    def evaluate(self,expression):
        value=self.command('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True},timeout=30)
        if 'exceptionDetails' in value:raise RuntimeError(value['exceptionDetails'])
        return value['result'].get('value')
    def close(self):self._socket.close()


def summarize(value):
    frames=sorted(value.pop('frames'));work=sorted(value.pop('work'))
    def pct(a,p):return a[min(len(a)-1,int((len(a)-1)*p))]
    value.update(frame_count=len(frames),frame_interval_p50_ms=pct(frames,.5),
        frame_interval_p95_ms=pct(frames,.95),frame_interval_max_ms=max(frames),
        intervals_over_25ms=sum(x>25 for x in frames),scroll_work_p95_ms=pct(work,.95))
    return value


def run_browser(out,origin,repeats):
    chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    profile=out/'chrome-profile';profile.mkdir(mode=0o700)
    log=(out/'chrome.log').open('w');proc=None;browser=None;page=None;owned={};samples=[]
    try:
        proc=subprocess.Popen([str(chrome),'--user-data-dir='+str(profile),'--remote-debugging-address=127.0.0.1',
            '--remote-debugging-port=0','--no-first-run','--no-default-browser-check','--disable-background-networking',
            '--window-size=1300,950','about:blank'],stdout=log,stderr=subprocess.STDOUT)
        owned[proc.pid]=identity(proc.pid)['start']
        def debug_port():
            try:return int((profile/'DevToolsActivePort').read_text().splitlines()[0])
            except (OSError,ValueError,IndexError):return None
        port=wait(debug_port)
        version=json_http(port,'/json/version');browser=CDP.connect_url(version['webSocketDebuggerUrl'])
        target=json_http(port,'/json/new?about:blank','PUT');page=CDP.connect_url(target['webSocketDebuggerUrl'])
        page.command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':816,'deviceScaleFactor':1,'mobile':False})
        browser.command('Target.activateTarget',{'targetId':target['id']})
        native_window=browser.command('Browser.getWindowForTarget',{'targetId':target['id']})
        browser.command('Browser.setWindowBounds',{'windowId':native_window['windowId'],
            'bounds':{'left':40,'top':40,'width':1300,'height':950,'windowState':'normal'}})
        (out/'chrome-window.json').write_text(json.dumps(browser.command('Browser.getWindowForTarget',{'targetId':target['id']}),indent=2)+'\n')
        gpu=browser.command('SystemInfo.getInfo',{})['gpu']
        (out/'chrome-graphics.json').write_text(json.dumps({'version':version,'gpu':gpu},indent=2)+'\n')
        for theme in ('purple-gold','ethereal'):
            for run in range(repeats):
                for path in ('/','/library','/settings/layout'):
                    page.command('Page.navigate',{'url':origin+'/__perf_theme/'+theme})
                    time.sleep(.15)
                    target_url=origin+path+'?response_round='+str(run)
                    page.command('Page.navigate',{'url':target_url})
                    wait(lambda:page.evaluate('location.href==='+json.dumps(target_url)+" && document.readyState==='complete'"))
                    time.sleep(.2);page.evaluate(SCRIPT)
                    wait(lambda:page.evaluate('window.__responseProbe?.done'),15)
                    sample=summarize(page.evaluate('window.__responseProbe'))
                    sample.update(engine='chrome',run=run,path=path,requested_theme=theme)
                    # Real CSS hover, delivered only to this synthetic browser target.
                    point=page.evaluate("(()=>{const n=document.querySelector('.dashboard-sidebar [data-nav-key=library]');if(!n)return null;const r=n.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
                    hover=[]
                    if point:
                        for _ in range(8):
                            page.command('Input.dispatchMouseEvent',{'type':'mouseMoved','x':1270,'y':700})
                            page.evaluate("window.__hoverAt=null;document.querySelector('.dashboard-sidebar [data-nav-key=library]').addEventListener('pointerenter',()=>{const start=performance.now();requestAnimationFrame(()=>window.__hoverAt={nextFrameMs:performance.now()-start,actualHover:document.querySelector('.dashboard-sidebar [data-nav-key=library]').matches(':hover')})},{once:true});true")
                            page.command('Input.dispatchMouseEvent',{'type':'mouseMoved',**point})
                            hover.append(wait(lambda:page.evaluate('window.__hoverAt'),4))
                    sample['hover']=hover;samples.append(sample)
                    (out/'chrome-results.json').write_text(json.dumps(samples,indent=2)+'\n')
        for pid in descendants(proc.pid):
            try:owned[pid]=identity(pid)['start']
            except OSError:pass
        browser.command('Browser.close',{});proc.wait(timeout=15)
    finally:
        if page:page.close()
        if browser:browser.close()
        if proc and proc.poll() is None:proc.kill();proc.wait(timeout=15)
        log.close()
        (out/'chrome-cleanup.json').write_text(json.dumps({'survivors':[p for p,b in owned.items() if alive(p,b)]})+'\n')


def graphics_modules():
    """Query known graphics module handles in this test process; never load them."""
    import ctypes as c
    from ctypes import wintypes as w
    from desktop.windows_processes import api,k
    get=api(k,'GetModuleHandleW',w.HMODULE,w.LPCWSTR)
    filename=api(k,'GetModuleFileNameW',w.DWORD,w.HMODULE,w.LPWSTR,w.DWORD)
    modules={}
    for name in ('nvspcap64.dll','d3d11.dll','dxgi.dll','nvldumdx.dll','nvwgf2umx.dll'):
        handle=get(name);entry={'loaded':bool(handle)}
        if handle:
            value=c.create_unicode_buffer(32768)
            length=filename(handle,value,len(value))
            if not length or length>=len(value):raise c.WinError(c.get_last_error())
            entry['path']=value.value
        modules[name]=entry
    return {'utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),'modules':modules}


def run_qt(out,origin,profile_name,repeats,unwrapped=False):
    from desktop.isolation import profile_paths,isolated_environment
    from desktop.server_mode import default_config,configured_server,write_config,server_root
    paths=profile_paths(profile_name);config=default_config(profile_name);config['mode']='server'
    config['server']=configured_server(config,origin,'Responsiveness fixture',private_http_opt_in=True);write_config(profile_name,config)
    env=isolated_environment(paths);os.environ.clear();os.environ.update(env);os.environ['DLMS_DESKTOP_AUTOMATED']='1'
    from PySide6.QtCore import QEvent,QPoint,QPointF,QUrl,Qt
    from PySide6.QtGui import QEnterEvent,QMouseEvent
    from PySide6.QtWidgets import QApplication,QMainWindow
    from desktop.shell import DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    app=QApplication([])
    if unwrapped:
        from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from desktop.server_browser import ServerPage,ServerOnlyInterceptor
        window=QMainWindow();window.resize(1280,850);window.view=QWebEngineView(window)
        store=server_root(config['server']['id'])
        profile=QWebEngineProfile('plain-qt-control',window)
        profile.setPersistentStoragePath(str(store['storage']));profile.setCachePath(str(store['cache']))
        for flag in ('LocalContentCanAccessFileUrls','LocalContentCanAccessRemoteUrls','JavascriptCanAccessClipboard','JavascriptCanPaste'):
            profile.settings().setAttribute(getattr(QWebEngineSettings.WebAttribute,flag),False)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        interceptor=ServerOnlyInterceptor(origin,profile);profile.setUrlRequestInterceptor(interceptor)
        window._closing=False;window._retiring_browser=None;window._browser_dialog_depth=0
        window._close_after_dialog=False;window.close_browser_notices=[];window.note_blocked=lambda url:None
        page=ServerPage(profile,window,origin,parent=window.view);window.view.setPage(page)
        window.setCentralWidget(window.view);window.show();window.view.setUrl(QUrl(origin+'/'))
    else:
        window=DesktopWindow(paths,profile_name);window.show();window.start()
    q=object.__new__(QtChecks);q.app=app;q.window=window;q.paths=paths
    if unwrapped:
        def evaluate(expression,timeout=10):
            answer=[];window.view.page().runJavaScript(expression,answer.append)
            end=time.monotonic()+timeout
            while not answer and time.monotonic()<end:q.delay(.005)
            if not answer:raise TimeoutError('Plain Qt JavaScript callback')
            return answer[0]
        q.js=evaluate
    samples=[]
    try:
        q.wait("document.readyState==='complete' && Boolean(document.querySelector('.dashboard-sidebar'))")
        window.resize(window.width()+1280-window.view.width(),window.height()+816-window.view.height())
        window.move(40,40)
        window.activateWindow();q.delay(.3)
        screen=window.screen();rect=window.frameGeometry()
        (out/'qt-window.json').write_text(json.dumps({'bounds':[rect.x(),rect.y(),rect.width(),rect.height()],
            'screen':screen.name(),'refresh_hz':screen.refreshRate(),'primary':screen is app.primaryScreen(),
            'screen_geometry':[screen.geometry().x(),screen.geometry().y(),screen.geometry().width(),screen.geometry().height()]},indent=2)+'\n')
        (out/'graphics-modules-before.json').write_text(json.dumps(graphics_modules(),indent=2)+'\n')
        for theme in ('purple-gold','ethereal'):
            for run in range(repeats):
                for path in ('/','/library','/settings/layout'):
                    q.js("fetch('/__perf_theme/"+theme+"');true");q.delay(.15)
                    target_url=origin+path+'?response_round='+str(run)
                    window.view.setUrl(QUrl(target_url))
                    q.wait('location.href==='+json.dumps(target_url)+" && document.readyState==='complete'")
                    q.delay(.2);q.js(SCRIPT);q.wait('window.__responseProbe?.done',15)
                    sample=summarize(json.loads(q.js('JSON.stringify(window.__responseProbe)')))
                    sample.update(engine='plain-qt-webengine' if unwrapped else 'source-qt-desktop',run=run,path=path,requested_theme=theme,window_active=window.isActiveWindow())
                    points=json.loads(q.js("JSON.stringify((()=>{const n=document.querySelector('.dashboard-sidebar [data-nav-key=library]');if(!n)return null;const r=n.getBoundingClientRect();return [{x:r.x+r.width/2,y:r.y+r.height/2},{x:1270,y:700}]})())"))
                    hover=[]
                    if points:
                        def move(point):
                            pos=QPoint(round(point['x']),round(point['y']));view=window.view;target=view.childAt(pos) or view
                            local=target.mapFrom(view,pos);global_pos=target.mapToGlobal(local)
                            QApplication.sendEvent(target,QEnterEvent(QPointF(local),QPointF(target.mapTo(window,local)),QPointF(global_pos)))
                            QApplication.sendEvent(target,QMouseEvent(QEvent.Type.MouseMove,QPointF(local),QPointF(global_pos),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
                        for _ in range(8):
                            move(points[1]);q.delay(.04)
                            q.js("window.__hoverAt=null;document.querySelector('.dashboard-sidebar [data-nav-key=library]').addEventListener('pointerenter',()=>{const start=performance.now();requestAnimationFrame(()=>window.__hoverAt={nextFrameMs:performance.now()-start,actualHover:document.querySelector('.dashboard-sidebar [data-nav-key=library]').matches(':hover')})},{once:true});true")
                            move(points[0]);q.wait('Boolean(window.__hoverAt)',4)
                            hover.append(json.loads(q.js('JSON.stringify(window.__hoverAt)')))
                    sample['hover']=hover;samples.append(sample)
                    (out/'qt-results.json').write_text(json.dumps(samples,indent=2)+'\n')
        (out/'graphics-modules-after.json').write_text(json.dumps(graphics_modules(),indent=2)+'\n')
    finally:
        if unwrapped:
            from desktop.browser_lifetime import BrowserRetirement
            window._closing=True
            retirement=BrowserRetirement(window.view,profile,window);retirement.start()
            end=time.monotonic()+5
            while not retirement.done and time.monotonic()<end:q.delay(.01)
            assert retirement.done,'Plain Qt browser retirement did not finish'
            (out/'retirement.json').write_text(json.dumps({'events':retirement.events,'done':retirement.done})+'\n')
            window.close();app.processEvents()
        else:q.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--engine',choices=('controller','qt','plain-qt'),default='controller');p.add_argument('--origin');p.add_argument('--profile',default='responseqt01')
    p.add_argument('--qt-control',action='store_true',help='Sequential wrapped/plain Qt ABBA control; no Chrome or graphics overrides')
    p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
    if not 1<=a.repeats<=3:raise ValueError('One to three bounded repeats required')
    out=a.output.resolve()
    if not out.is_relative_to(PROJECT/'.gate1/windows-native'):raise ValueError('Project-local evidence only')
    if a.engine in ('qt','plain-qt'):return run_qt(out,a.origin,a.profile,a.repeats,unwrapped=a.engine=='plain-qt')
    out.mkdir(mode=0o700,exist_ok=False)
    for name in ('home','cache','tmp','config','xdg'):(out/name).mkdir(mode=0o700)
    env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','QTWEBENGINE_'))}
    env.update(HOME=str(out/'home'),TMP=str(out/'tmp'),TEMP=str(out/'tmp'),XDG_CONFIG_HOME=str(out/'config'),
        XDG_DATA_HOME=str(out/'xdg'),XDG_CACHE_HOME=str(out/'cache'),QUIZAPP_DATA_DIR=str(out/'server-data'),
        DLMS_PERF_LOG=str(out/'requests.jsonl'),DLMS_PERF_READY=str(out/'port'),DLMS_PERF_QUIZZES='40')
    with (out/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-m','tests.server_mode.performance_server'],env=env,cwd=PROJECT,stdout=log,stderr=subprocess.STDOUT)
        try:
            wait(lambda:(out/'port').exists());origin='http://127.0.0.2:'+(out/'port').read_text()
            if not a.qt_control:run_browser(out,origin,a.repeats)
            qenv=env|{'QT_LOGGING_RULES':'qt.webenginecontext.debug=true','QT_FORCE_STDERR_LOGGING':'1'}
            sequence=('qt','plain-qt','plain-qt','qt') if a.qt_control else ('qt',)
            for index,engine in enumerate(sequence):
                case=out/f'{index+1:02}-{engine}' if a.qt_control else out
                if a.qt_control:case.mkdir(mode=0o700)
                name=f'{a.profile}{index+1}' if a.qt_control else a.profile
                with (case/'qt.log').open('w') as qlog:
                    completed=subprocess.run([sys.executable,'-m','tests.windows.responsiveness','--engine',engine,'--origin',origin,'--output',str(case),'--profile',name,'--repeats',str(a.repeats)],cwd=PROJECT,env=qenv,stdout=qlog,stderr=subprocess.STDOUT,timeout=300)
                    assert completed.returncode==0,(engine,completed.returncode)
        finally:
            server.terminate();server.wait(timeout=15)
    print(out)

if __name__=='__main__':main()
