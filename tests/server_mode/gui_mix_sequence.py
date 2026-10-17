"""6000-question sequenced Qt/Firefox control; app-local only, fresh synthetic roots."""
import argparse,atexit,hashlib,importlib.util,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace
from desktop.isolation import PROJECT,profile_paths,isolated_environment
from desktop.server_mode import default_config,configured_server,write_config
from tests.server_mode.gui_performance import METRICS
from tests.server_mode.mix_sequence import INSTRUMENT,OPERATIONS,operation_script,FIDELITY,fixture_fidelity

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--profile',required=True);p.add_argument('--variant',choices=['baseline','hidden','checked','conditional','flex','contain','style','old-css'],default='baseline');p.add_argument('--matching',action='store_true');p.add_argument('--checks',action='store_true');p.add_argument('--renderer',choices=['desktop','qt','firefox'],required=True);a=p.parse_args()
 out=a.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False)
 for leaf in ['home','config','cache','data','tmp']:(out/leaf).mkdir(mode=0o700)
 env=dict(os.environ,HOME=str(out/'home'),XDG_CONFIG_HOME=str(out/'config'),XDG_CACHE_HOME=str(out/'cache'),XDG_DATA_HOME=str(out/'data'),TMPDIR=str(out/'tmp'),QUIZAPP_DATA_DIR=str(out/'server-data'),DLMS_PERF_LOG=str(out/'requests.jsonl'),DLMS_PERF_READY=str(out/'port'),DLMS_PERF_QUIZZES='24',DLMS_PERF_QUESTIONS='250')
 env['DLMS_PERF_VARIANT']=a.variant
 if a.matching:env['DLMS_PERF_MATCHING']='1'
 log=(out/'server.log').open('w');server=subprocess.Popen([sys.executable,'-m','tests.server_mode.performance_server'],env=env,cwd=PROJECT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 def stop_server():
  if server.poll() is None:server.terminate();server.wait(timeout=15)
 atexit.register(stop_server)
 (out/'server-owner.json').write_text(json.dumps({'pid':server.pid,'start_ticks':Path(f'/proc/{server.pid}/stat').read_text().rsplit(')',1)[1].split()[19]}))
 app=window=view=profile=browser=firefox=flog=None;js_calls=[];heartbeat=[];native=[];samples=[]
 def wait(predicate,timeout=180):
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   if app:app.processEvents()
   if predicate():return
   time.sleep(.005)
  raise TimeoutError('Sequenced synthetic checkpoint')
 try:
  wait(lambda:(out/'port').exists() or server.poll() is not None);assert server.poll() is None
  store_before=fixture_fidelity(out/'server-data')
  origin='http://127.0.0.2:'+ (out/'port').read_text()
  if a.renderer=='firefox':
   spec=importlib.util.spec_from_file_location('sequence_bidi',PROJECT/'tests/browser/_bidi.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
   with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
   fenv=env.copy()
   for key in ['DISPLAY','WAYLAND_DISPLAY','WAYLAND_SOCKET','XAUTHORITY']:fenv.pop(key,None)
   fenv.update(GDK_BACKEND='x11',MOZ_ENABLE_WAYLAND='0')
   froot=out/'firefox-profile';froot.mkdir(mode=0o700);flog=(out/'firefox.log').open('w');firefox=subprocess.Popen([shutil.which('firefox'),'--headless','--no-remote','--profile',str(froot),'--remote-debugging-port',str(port),'about:blank'],env=fenv,stdout=flog,stderr=subprocess.STDOUT,start_new_session=True)
   deadline=time.monotonic()+30
   while browser is None:
    assert firefox.poll() is None
    if time.monotonic()>deadline:raise TimeoutError('Firefox start')
    try:browser=mod.FirefoxBidi.connect('127.0.0.1',port,timeout=.5)
    except (OSError,mod.BidiError):time.sleep(.05)
   browser.start_session();browser.command('browsingContext.setViewport',{'context':browser.context,'viewport':{'width':1000,'height':700},'devicePixelRatio':1})
   browser.command('script.addPreloadScript',{'functionDeclaration':'() => {'+INSTRUMENT+'}','contexts':[browser.context]})
   def js(expr):return browser.evaluate(expr)
   started=time.monotonic();browser.command('browsingContext.navigate',{'context':browser.context,'url':origin+'/quiz-composer','wait':'complete'},timeout=180);finished=time.monotonic()
  else:
   paths=profile_paths(a.profile);config=default_config(a.profile);config['mode']='server';config['server']=configured_server(config,origin,'6000 sequence',private_http_opt_in=True);write_config(a.profile,config)
   qt_env=isolated_environment(paths);os.environ.clear();os.environ.update(qt_env);os.environ['DLMS_DESKTOP_AUTOMATED']='1'
   from PySide6.QtCore import QTimer,QUrl
   from PySide6.QtWidgets import QApplication,QMainWindow
   from PySide6.QtWebEngineCore import QWebEngineScript,QWebEngineProfile,QWebEngineSettings
   from PySide6.QtWebEngineWidgets import QWebEngineView
   from desktop.shell import DesktopWindow
   from desktop.identity import configure_application_identity
   from desktop.server_browser import ServerPage,ServerOnlyInterceptor
   app=QApplication([]);configure_application_identity(app)
   pulse=QTimer();pulse.setInterval(20);pulse.timeout.connect(lambda:heartbeat.append(time.monotonic()));pulse.start()
   if a.renderer=='desktop':
    window=DesktopWindow(paths,a.profile);window.resize(1100,800);window.show();window.start();wait(lambda:window.view and not window.view.page().isLoading() and window._server_page_exposed);view=window.view;profile=window.profile
    original=view.page().runJavaScript
    def counted(*args):
     native.append({'at':time.monotonic(),'kind':'readiness' if 'responseStatus' in args[0] else 'theme' if args[0].startswith("document.querySelector('.dashboard-sidebar')") else 'other'})
     return original(*args)
    view.page().runJavaScript=counted
    style=window._style_server_surface
    def timed_style():
     start=time.monotonic();style();native.append({'at':start,'kind':'native_style','ms':1000*(time.monotonic()-start)})
    window._style_server_surface=timed_style
   else:
    window=QMainWindow();window.resize(1100,800);view=QWebEngineView(window);profile=QWebEngineProfile('sequence-control',window);profile.setPersistentStoragePath(str(out/'storage'));profile.setCachePath(str(out/'web-cache'))
    interceptor=ServerOnlyInterceptor(origin,profile);profile.setUrlRequestInterceptor(interceptor)
    for flag in ['LocalContentCanAccessFileUrls','LocalContentCanAccessRemoteUrls','JavascriptCanAccessClipboard','JavascriptCanPaste']:profile.settings().setAttribute(getattr(QWebEngineSettings.WebAttribute,flag),False)
    owner=SimpleNamespace(view=view,_closing=False,statusBar=window.statusBar,note_blocked=lambda url:None,close_browser_notices=[]);page=ServerPage(profile,owner,origin,parent=view);view.setPage(page);window.setCentralWidget(view);window.show()
   view.setFixedSize(1000,700)
   script=QWebEngineScript();script.setName('synthetic sequence instrumentation');script.setSourceCode(INSTRUMENT);script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation);script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld);script.setRunsOnSubFrames(False);view.page().scripts().insert(script)
   def js(expr):
    answer=[];start=time.monotonic();view.page().runJavaScript(expr,answer.append);wait(lambda:bool(answer));js_calls.append({'wall_ms':1000*(time.monotonic()-start)});return answer[0]
   done=[];view.loadFinished.connect(lambda ok:done.append(ok));started=time.monotonic();view.setUrl(QUrl(origin+'/quiz-composer'));wait(lambda:bool(done));finished=time.monotonic();assert done[-1]
  assert js("document.querySelectorAll('.mixed-builder-question').length")==6000
  initial_ids=json.loads(js("JSON.stringify({one:[...document.querySelectorAll('[name=question_ids]')].filter(b=>b.dataset.sourceIds.split(',').includes(document.getElementById('sourceFilter').options[1].value)).map(b=>b.value),five:[...document.querySelectorAll('[name=question_ids]')].filter(b=>b.dataset.sourceIds.split(',').includes(document.getElementById('sourceFilter').options[5].value)).map(b=>b.value),four:[...document.querySelectorAll('[name=question_ids]')].filter(b=>b.dataset.sourceIds.split(',').includes(document.getElementById('sourceFilter').options[4].value)).map(b=>b.value)})"))
  assert all(len(v)==250 for v in initial_ids.values())
  expected=[]
  fidelity=hashlib.sha256(js(FIDELITY).encode()).hexdigest();metrics=json.loads(js(METRICS));url=metrics['url'];stamp=metrics['timeOrigin']
  for name,body,shown,selected in OPERATIONS:
   begin=time.monotonic();h_start=max(0,len(heartbeat)-1);n_start=len(native);calls_start=len(js_calls)
   assert js(operation_script(name,body)) is True
   wait(lambda:js('window.__mixMeasure?.done===true'))
   value=json.loads(js('JSON.stringify(window.__mixMeasure)'));value['native_wall_ms']=1000*(time.monotonic()-begin)
   value['native_processing']=native[n_start:];value['js_callback_wall_ms']=[x['wall_ms'] for x in js_calls[calls_start:]]
   if app:
    tick_count=len(heartbeat);wait(lambda:len(heartbeat)>tick_count)
   ticks=heartbeat[h_start:];value['native_heartbeat_max_gap_ms']=max([1000*(b-a) for a,b in zip(ticks,ticks[1:])],default=None)
   assert value['shown']==shown,(name,value['shown'],shown)
   if name=='pick_first_25':expected=initial_ids['one'][:25]
   if name=='pick_next_25':expected=expected+initial_ids['five'][:25]
   if name in ['clear_hidden_50','clear_visible_250']:expected=[]
   if name=='select_visible_250':expected=initial_ids['four']
   assert value['checked']==expected,(name,'immutable initial IDs changed')
   assert len(value['checked'])==selected and value['formIds']==value['checked'] and value['count']==f'{selected} selected',(name,value)
   assert value['origin']==stamp and js('location.href')==url
   if name in ['folder_two','folder_two_all_quizzes','quiz_two']:assert value['hidden_selected']==50
   samples.append(value)
   with (out/'samples.jsonl').open('a') as stream:stream.write(json.dumps(value)+'\n')
   print(name,'handler/layout/frame/wall',*[round(value[k],1) for k in ['handler_ms','style_read_ms','layout_ms','frames_ms','native_wall_ms']],'checked',len(value['checked']),flush=True)
  assert hashlib.sha256(js(FIDELITY).encode()).hexdigest()==fidelity
  assert fixture_fidelity(out/'server-data')==store_before
  # Capture Server form state before optional diagnostics deliberately navigate to Library.
  final_ids=json.loads(js("JSON.stringify(new FormData(document.getElementById('mixedQuizForm')).getAll('question_ids'))"))
  assert final_ids==[], 'The completed sequence must clear all selected question IDs'
  if a.checks:
   assert a.renderer=='desktop'
   from desktop.mix_diagnostics import MixDiagnostics
   collector=MixDiagnostics(window);wait(lambda:collector.ready or collector.stopped);assert collector.ready
   js("document.querySelector('[name=question_ids]').click()")
   wait(lambda:collector.bytes>0);time.sleep(.6);app.processEvents()
   js("document.getElementById('clearSelection').click()")
   wait(lambda:any('clearSelection' in line for line in collector.path.read_text().splitlines()))
   evidence=[json.loads(line) for line in collector.path.read_text().splitlines()]
   assert any(e['counts']['checked']==0 for e in evidence)
   assert 'Neutral synthetic' not in collector.path.read_text() and origin not in collector.path.read_text()
   assert any(row['phase']=='deferred-after-event' and row['control']=='clearSelection' and row['counts']['checked']==0 for e in evidence for row in e['events'])
   checks={'diagnostic':{'counts_only':True,'private_mode':oct(collector.path.stat().st_mode&0o777)}}
   collector.stop('Synthetic acceptance complete')
   from desktop.settings_surface import THEME_REGISTRY
   def set_theme(theme):
    from urllib.request import urlopen
    with urlopen(origin+'/__perf_theme/'+theme) as response:assert response.status==204
    js("(()=>{window.__themeLoaded=false;let link=document.getElementById('__fixtureTheme');if(!link){link=document.createElement('link');link.id='__fixtureTheme';link.rel='stylesheet';document.body.appendChild(link)};link.onload=()=>window.__themeLoaded=true;link.href='/dynamic.css?fixture='+"+json.dumps(theme)+"})()")
    wait(lambda:js('window.__themeLoaded===true'))
    actual=js("getComputedStyle(document.documentElement).getPropertyValue('--theme-page-text').trim()")
    assert actual==THEME_REGISTRY[theme]['colors']['page'],(theme,actual)
    js("document.querySelector('.dashboard-sidebar').dataset.theme="+json.dumps(theme))
    window._poll_mode_theme();wait(lambda:window._mode_theme==theme)
   visual=[]
   js("document.getElementById('sourceFilter').value=document.getElementById('sourceFilter').options[1].value;document.getElementById('sourceFilter').dispatchEvent(new Event('input',{bubbles:true}));document.querySelectorAll('.mixed-builder-question:not([hidden]) .mixed-builder-preview').forEach((p,i)=>{if(i<3)p.open=true})")
   # Test-only source-style comparison, not a runtime remote CSS injection.
   for theme in THEME_REGISTRY:
    set_theme(theme)
    expr="""JSON.stringify([...document.querySelectorAll('.mixed-builder-question:not([hidden])')].slice(0,3).map(c=>{const r=c.getBoundingClientRect(),t=getComputedStyle(c),li=c.querySelector('li');return {width:r.width,height:r.height,color:t.color,font:t.font,border:t.border,list:li?getComputedStyle(li).listStyleType:null,labels:c.querySelector('.mixed-builder-preview')?.textContent}}))"""
    before=js("document.querySelectorAll('.mixed-builder-question').forEach(c=>c.style.contain='none');"+expr)
    after=js("document.querySelectorAll('.mixed-builder-question').forEach(c=>c.style.removeProperty('contain'));"+expr)
    assert before==after,(theme,'style containment changed previews')
    visual.append({'theme':theme,'preview_geometry_fonts_labels_equal':True})
   for width,zoom,name in [(1000,1,'wide'),(600,1,'narrow'),(1000,2,'zoom200')]:
    view.setFixedSize(width,700);view.setZoomFactor(zoom);window.resize(width+20,800)
    for theme in ['light','dark','ethereal']:
     set_theme(theme)
     for state in ['before','after']:
      js("document.querySelectorAll('.mixed-builder-question').forEach(c=>c.style.contain="+json.dumps('none' if state=='before' else 'style')+")")
      js("document.querySelector('.mixed-builder-question:not([hidden])').scrollIntoView({block:'start'})");app.processEvents();time.sleep(.1);app.processEvents();window.grab().save(str(out/(name+'-'+theme+'-'+state+'.png')))
   checks['visual']=visual;checks['rendered_evidence']='Qt grab; inspect files, partial viewport, no physical keyboard claim'
   view.setZoomFactor(1)
   second=MixDiagnostics(window);wait(lambda:second.ready);view.setUrl(QUrl(origin+'/library'));wait(lambda:second.stopped)
   checks['navigation_stops_diagnostic']=True
   (out/'checks.json').write_text(json.dumps(checks,indent=2)+'\n')
  requests=[json.loads(line) for line in (out/'requests.jsonl').read_text().splitlines()];assert len([r for r in requests if r['phase']=='request' and r['path'].startswith('/quiz-composer')])==1
  result={'source_store_before_after':store_before,'variant':a.variant,'renderer':a.renderer,'entry_ms':1000*(finished-started),'navigation':metrics,'samples':samples,'fidelity_sha256_before_after':fidelity,'no_new_filter_requests':True,'final_checked_ids':final_ids,'heartbeat_ticks':len(heartbeat),'response_body':[r for r in requests if r['phase']=='body' and r['path'].startswith('/quiz-composer')],'instrumentation':'test-only listener/observer duration wrappers; forced layout then two animation-frame opportunities, not physical paint guarantee'}
  (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 finally:
  if browser:browser.close()
  if firefox and firefox.poll() is None:firefox.terminate();firefox.wait(timeout=15)
  if flog:flog.close()
  if app and window:
   if a.renderer=='desktop':window.close();wait(lambda:window.view is None)
   else:
    from desktop.browser_lifetime import BrowserRetirement
    retirement=BrowserRetirement(view,profile,window);retirement.start();wait(lambda:retirement.done);window.close()
   app.processEvents()
  stop_server();log.close()
 return 0
if __name__=='__main__':raise SystemExit(main())
