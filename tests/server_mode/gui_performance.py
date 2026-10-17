"""Matched Qt-engine control versus Desktop, repeated cold/warm synthetic loads."""
import argparse,atexit,json,os,subprocess,sys,time,statistics
from pathlib import Path
from types import SimpleNamespace
from desktop.isolation import PROJECT,profile_paths,isolated_environment
from desktop.server_mode import default_config,configured_server,write_config

METRICS="""JSON.stringify({url:location.href,ready:document.readyState,timeOrigin:performance.timeOrigin,
 nav:performance.getEntriesByType('navigation')[0]?.toJSON(),
 paint:performance.getEntriesByType('paint').map(x=>({name:x.name,startTime:x.startTime})),
 viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},cards:document.querySelectorAll('.quiz-card').length,theme:document.querySelector('.dashboard-sidebar')?.dataset.theme,
 features:document.featurePolicy?.allowedFeatures(),paymentType:typeof PaymentRequest,usbType:typeof navigator.usb})"""

FILTER_SCRIPT="""(() => {
 const select=document.getElementById('folderFilter');
 const before=performance.now();const origin=performance.timeOrigin;
 select.value=FOLDER_VALUE;select.dispatchEvent(new Event('input',{bubbles:true}));
 const processed=performance.now();
 const height=document.getElementById('questionList').getBoundingClientRect().height;
 const layout=performance.now();
 window.__filterMeasure={folder:select.value,origin,begin:before,handler_ms:processed-before,
  layout_ms:layout-processed,height,shown:[...document.querySelectorAll('.mixed-builder-question')].filter(n=>!n.hidden).length,done:false};
 requestAnimationFrame(()=>requestAnimationFrame(()=>{window.__filterMeasure.frame_ms=performance.now()-before;window.__filterMeasure.done=true}));return true;
})()"""

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--repeats',type=int,default=4);p.add_argument('--mix',action='store_true');p.add_argument('--probe-mode',choices=['baseline','off','visible','page-visible'],default='baseline');a=p.parse_args()
    out=a.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    for leaf in ['server-home','server-cache','server-tmp','server-config','server-xdg-data']: (out/leaf).mkdir(mode=0o700)
    env=os.environ.copy();
    if a.mix:env.update(DLMS_PERF_QUIZZES='24',DLMS_PERF_QUESTIONS='150')
    env.update(HOME=str(out/'server-home'),XDG_CONFIG_HOME=str(out/'server-config'),XDG_DATA_HOME=str(out/'server-xdg-data'),XDG_CACHE_HOME=str(out/'server-cache'),TMPDIR=str(out/'server-tmp'),QUIZAPP_DATA_DIR=str(out/'server-data'),DLMS_PERF_LOG=str(out/'requests.jsonl'),DLMS_PERF_READY=str(out/'port'))
    slog=(out/'server.log').open('w');proc=subprocess.Popen([sys.executable,'-m','tests.server_mode.performance_server'],env=env,cwd=PROJECT,stdout=slog,stderr=subprocess.STDOUT,start_new_session=True)
    (out/'server-owner.json').write_text(json.dumps({'pid':proc.pid,'start_ticks':Path(f'/proc/{proc.pid}/stat').read_text().rsplit(')',1)[1].split()[19],'argv':[sys.executable,'-m','tests.server_mode.performance_server'],'cwd':str(PROJECT)}))
    def stop_server():
        if proc.poll() is None:proc.terminate();proc.wait(timeout=15)
    atexit.register(stop_server)
    deadline=time.monotonic()+60
    while not (out/'port').exists():
        assert proc.poll() is None
        if time.monotonic()>deadline:raise TimeoutError('Synthetic library startup')
        time.sleep(.05)
    origin='http://127.0.0.2:'+ (out/'port').read_text()
    paths=profile_paths(a.profile);config=default_config(a.profile);config['mode']='server';config['server']=configured_server(config,origin,'Performance fixture',private_http_opt_in=True);write_config(a.profile,config)
    env=isolated_environment(paths);os.environ.clear();os.environ.update(env);os.environ['DLMS_DESKTOP_AUTOMATED']='1'
    from PySide6.QtCore import QEvent,QObject,QUrl
    from PySide6.QtWidgets import QApplication,QMainWindow
    from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from desktop.identity import configure_application_identity
    from desktop.shell import DesktopWindow
    from desktop.server_browser import ServerPage,ServerOnlyInterceptor
    app=QApplication([]);configure_application_identity(app)
    window=DesktopWindow(paths,a.profile);window.resize(1100,780);window.show()
    control=QMainWindow();control.resize(1100,780);cv=QWebEngineView(control)
    profile=QWebEngineProfile('performance-control',control);profile.setPersistentStoragePath(str(out/'control-storage'));profile.setCachePath(str(out/'control-cache'))
    for flag in ['LocalContentCanAccessFileUrls','LocalContentCanAccessRemoteUrls','JavascriptCanAccessClipboard','JavascriptCanPaste']:profile.settings().setAttribute(getattr(QWebEngineSettings.WebAttribute,flag),False)
    interceptor=ServerOnlyInterceptor(origin,profile);profile.setUrlRequestInterceptor(interceptor)
    owner=SimpleNamespace(view=cv,_closing=False,statusBar=control.statusBar,note_blocked=lambda url:None,close_browser_notices=[])
    cp=ServerPage(profile,owner,origin,parent=cv);cv.setPage(cp);control.setCentralWidget(cv)
    calls=[];original_console=ServerPage.javaScriptConsoleMessage
    def console(page,level,message,line,source):
        calls.append({'level':str(level),'message':message,'source':source});original_console(page,level,message,line,source)
    ServerPage.javaScriptConsoleMessage=console
    def wait(predicate,timeout=90):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            app.processEvents()
            if predicate():return
            time.sleep(.005)
        raise TimeoutError('Qt benchmark checkpoint')
    def js(page,expr):
        answer=[];page.runJavaScript(expr,answer.append);wait(lambda:bool(answer));return answer[0]
    samples=[];reveals=[];probe_events=[]
    class Filter(QObject):
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Type.Show and not hasattr(window,'_set_server_page_exposed'):
                reveals.append(time.monotonic())
                if hasattr(window,'_server_early_revealed') and window._server_early_revealed:
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100,lambda:window.grab().save(str(out/'tail-provisional.png')) if window.view is not None and window.view.page().isLoading() else None)
            return False
    filt=Filter(window)
    try:
        window.start();wait(lambda:window.view is not None and window.view.isVisible() and not window.view.page().isLoading())
        window.view.installEventFilter(filt)
        if hasattr(window,'_set_server_page_exposed'):
            expose=window._set_server_page_exposed
            def measured_expose(value,**kwargs):
                changed=value and not window._server_page_exposed
                expose(value,**kwargs)
                if changed:reveals.append(time.monotonic())
            window._set_server_page_exposed=measured_expose
        if a.probe_mode=='off':window.view.loadStarted.connect(window.server_readiness_timer.stop)
        if a.probe_mode=='visible':window.view.hide=lambda:None
        if a.probe_mode=='page-visible':window.view.loadStarted.connect(lambda:window.view.page().setVisible(True))
        counts={'theme':0,'readiness':0}
        run_js=window.view.page().runJavaScript
        def counted_js(*args):
            if args[0]=="document.querySelector('.dashboard-sidebar')?.dataset.theme || ''":counts['theme']+=1
            if 'responseStatus:nav?.responseStatus' in args[0]:
                counts['readiness']+=1
                issued=time.monotonic();callback=args[-1]
                def traced(raw):
                    event={'issued':issued,'received':time.monotonic(),'raw':raw,'native_url':window.view.url().toString() if window.view else None,'previous':window._server_previous_document,'active':window.server_readiness_timer.isActive(),'loading':window.view.page().isLoading() if window.view else None}
                    probe_events.append(event)
                    with (out/'probes.jsonl').open('a') as stream:stream.write(json.dumps(event)+'\n')
                    callback(raw)
                args=(*args[:-1],traced)
            return run_js(*args)
        window.view.page().runJavaScript=counted_js
        control.show();app.processEvents();control.statusBar().setFixedHeight(window.statusBar().height());window.view.setFixedSize(600,550);cv.setFixedSize(600,550);cv.setUrl(QUrl(origin+'/library?perf_case=plain'));wait(lambda:not cp.isLoading() and cp.url().path()=='/library')
        for case in (['mix'] if a.mix else ['plain','tail']):
            for cache in ['cold','warm']:
                # Counterbalance renderer order. Each uses an independent cache,
                # same URL/HTTP bytes, engine, session, size and security boundary.
                for repetition in range(a.repeats):
                    for renderer in (['desktop','control'] if repetition%2==0 else ['control','desktop']):
                        view=window.view if renderer=='desktop' else cv
                        prof=window.profile if renderer=='desktop' else profile
                        if cache=='cold':
                            cleared=[];slot=lambda:cleared.append(True);prof.clearHttpCacheCompleted.connect(slot);prof.clearHttpCache();wait(lambda:bool(cleared));prof.clearHttpCacheCompleted.disconnect(slot)
                        target=origin+('/quiz-composer' if a.mix else '/library?perf_case='+case)
                        finished=[];slot=lambda ok:finished.append(ok);view.loadFinished.connect(slot)
                        reveals.clear();initial_counts=counts.copy();started=time.monotonic();view.setUrl(QUrl(target));wait(lambda:bool(finished));ended=time.monotonic();view.loadFinished.disconnect(slot)
                        assert finished[-1] and view.url().toString()==target
                        value=json.loads(js(view.page(),METRICS));wait(lambda:view.isVisible())
                        # Let paint metrics settle identically; this is excluded
                        # from navigation/reveal timing, not an application wait.
                        until=time.monotonic()+.08;wait(lambda:time.monotonic()>=until)
                        value=json.loads(js(view.page(),METRICS))
                        folder_samples=[]
                        if a.mix and renderer=='desktop':window.grab().save(str(out/(cache+'-mix.png')))
                        if a.mix:
                            assert js(view.page(),"document.querySelectorAll('.mixed-builder-question').length")==3600
                            for folder in ['synthetic folder 1','', 'synthetic folder 1']:
                                request_rows_before=[json.loads(line) for line in (out/'requests.jsonl').read_text().splitlines()]
                                document_before=value['timeOrigin']
                                assert js(view.page(),FILTER_SCRIPT.replace('FOLDER_VALUE',json.dumps(folder))) is True
                                wait(lambda:js(view.page(),"window.__filterMeasure?.done===true"))
                                measure=json.loads(js(view.page(),"JSON.stringify(window.__filterMeasure)"))
                                assert measure['shown']==(900 if folder else 3600)
                                measure['main_requests_during_filter']=len([json.loads(line) for line in (out/'requests.jsonl').read_text().splitlines()[len(request_rows_before):] if json.loads(line)['phase']=='request' and json.loads(line)['path'].startswith('/quiz-composer')])
                                assert measure['main_requests_during_filter']==0
                                assert measure['origin']==document_before and view.url().toString()==target
                                folder_samples.append(measure)
                        sample={'filters':folder_samples,'case':case,'cache':cache,'renderer':renderer,'repetition':repetition,'started_monotonic':started,'finished_ms':(ended-started)*1000,'reveal_ms':(reveals[0]-started)*1000 if reveals else 0,'browser':value,'theme_checks':counts['theme']-initial_counts['theme'] if renderer=='desktop' else None,'readiness_probes':counts['readiness']-initial_counts['readiness'] if renderer=='desktop' else None}
                        samples.append(sample)
                        with (out/'samples.jsonl').open('a') as stream:stream.write(json.dumps(sample)+'\n')
                        print(renderer,cache,round(sample['finished_ms'],1),round(sample['reveal_ms'],1),flush=True)
        assert all(s['browser']['nav']['responseStatus']==200 for s in samples)
        dimensions={tuple(s['browser']['viewport'].values()) for s in samples}
        assert len(dimensions)==1, ('Benchmark requires equal actual viewport/scale',dimensions)
        events=[json.loads(line) for line in (out/'requests.jsonl').read_text().splitlines()]
        for sample in samples:
            end=sample['started_monotonic']+sample['finished_ms']/1000
            sample['main_requests']=[row for row in events if row['phase']=='request' and row['path']==('/quiz-composer?' if a.mix else '/library?perf_case='+sample['case']) and sample['started_monotonic']<=row['at']<=end]
            assert len(sample['main_requests'])==1, 'Every navigation must issue exactly one library request'
        headers=[r['policy'] for r in events if r['phase']=='headers']
        if headers:assert all(value=='camera=(), geolocation=(), microphone=(), payment=(), usb=()' for value in headers)

        (out/'result.json').write_text(json.dumps({'origin':origin,'samples':samples,'console':calls,'engine_control':'Unwrapped Qt WebEngine with same exact-origin boundary, not native Firefox/Omarchy browser benchmark'},indent=2)+'\n')
        for case in (['mix'] if a.mix else ['plain','tail']):
            for cache in ['cold','warm']:
                for renderer in ['desktop','control']:
                    subset=[s for s in samples if (s['case'],s['cache'],s['renderer'])==(case,cache,renderer)]
                    print(case,cache,renderer,'median finish/reveal/DCL:',*[round(statistics.median([s['finished_ms'] if field=='finish' else s['reveal_ms'] if field=='reveal' else s['browser']['nav']['domContentLoadedEventEnd'] for s in subset]),1) for field in ['finish','reveal','DCL']],flush=True)
    finally:
        ServerPage.javaScriptConsoleMessage=original_console
        window.close();wait(lambda:window.view is None)
        from desktop.browser_lifetime import BrowserRetirement
        retirement=BrowserRetirement(cv,profile,control);retirement.start()
        from PySide6.QtCore import QEventLoop,QTimer
        loop=QEventLoop();retirement.finished.connect(loop.quit);QTimer.singleShot(5000,loop.quit);loop.exec()
        assert retirement.done;control.close();app.processEvents()
        proc.terminate();proc.wait(timeout=15);slog.close()
    return 0
if __name__=='__main__':raise SystemExit(main())
