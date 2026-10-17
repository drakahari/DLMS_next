"""Source-only phase trace of Server cover/readiness and owned native host IPC."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--host',type=Path,required=True);p.add_argument('--coalesce-theme',action='store_true',help='Source-only controlled cosmetic-query diagnostic');p.add_argument('--renderer-cadence',action='store_true',help='Opt-in owned-fixture buffered duration counts only');a=p.parse_args()
 from desktop.isolation import PROJECT,AREA,profile_paths,isolated_environment
 from desktop.windows_processes import Job
 out=a.output.absolute();assert out.is_relative_to(PROJECT/'.gate1/windows-native') and not out.exists();out.mkdir(mode=0o700)
 paths=profile_paths(a.profile,create=False);assert not paths['root'].exists()
 shell=AREA/'shell'/a.profile;assert not shell.exists() and not shell.is_symlink(),'Fresh Server-only profile required'
 env=os.environ.copy()
 for key,leaf in [('USERPROFILE','home'),('HOME','home'),('APPDATA','config'),('LOCALAPPDATA','local'),('TEMP','tmp'),('TMP','tmp')]:
  path=out/leaf;path.mkdir(mode=0o700,exist_ok=True);env[key]=str(path)
 env.update(DLMS_WVPERF_OUTPUT=str(out),QUIZAPP_DATA_DIR=str(out/'server-data'),DLMS_NO_BROWSER='1')
 if a.renderer_cadence:env['DLMS_WVPERF_CADENCE']='1'
 else:env.pop('DLMS_WVPERF_CADENCE',None)
 (out/'current-run.json').write_text(json.dumps({'run':'source'}));log=(out/'server.log').open('w')
 server=subprocess.Popen([sys.executable,'-m','tests.webview2.server_performance_fixture'],env=env,cwd=PROJECT,stdout=log,stderr=subprocess.STDOUT);job=Job();job.assign(int(server._handle))
 window=None;trace=[];pulses=[]
 def record(kind,**values):trace.append({'at':time.monotonic(),'receipt_perf_counter_ns':time.perf_counter_ns(),'utc_ms':time.time()*1000,'kind':kind,**values})
 try:
  end=time.monotonic()+120
  while not (out/'port').exists():
   assert server.poll() is None
   if time.monotonic()>end:raise TimeoutError('Synthetic source fixture startup')
   time.sleep(.03)
  origin='http://127.0.0.2:'+(out/'port').read_text().strip()
  from desktop.server_mode import default_config,configured_server,write_config
  config=default_config(a.profile);config['mode']='server';config['server']=configured_server(config,origin,'Source performance trace',private_http_opt_in=True);write_config(a.profile,config)
  paths=profile_paths(a.profile);environment=isolated_environment(paths);os.environ.clear();os.environ.update(environment);os.environ['DLMS_DESKTOP_AUTOMATED']='1'
  import package_windows_webview2;package_windows_webview2.ACTIVE=True
  import desktop.webview2_browser as browser
  host=a.host.resolve(strict=True);browser.host_executable=lambda:host
  original_event=browser.View._event;original_command=browser.View.command;issued={}
  theme_script="document.querySelector('.dashboard-sidebar')?.dataset.theme || ''"
  def event(view,value):
   if value.get('event')=='reply' and value.get('id') in issued:
    op,began=issued.pop(value['id']);record('command-reply',op=op,id=value['id'],elapsed_ms=(time.monotonic()-began)*1000,ok=value.get('ok'))
   if value.get('event') in ('diagnostic-phase','diagnostic-native-state','diagnostic-native-state-error'):
    record('diagnostic-host',metadata=value)
   record('native-event',event=value.get('event'),generation=value.get('generation'),nav_id=value.get('nav_id'),id=value.get('id'),shown=value.get('shown'),browser_visible=value.get('browser_visible'),ok=value.get('ok'))
   return original_event(view,value)
  def command(view,op,callback=None,on_error=None,**values):
   began=time.monotonic();serial=view._serial+1
   issued[serial]=(op,began)
   record('command',op=op,id=serial,generation=view._active_generation,nav_id=view._active_navigation,
     script_kind=('theme' if values.get('script')==theme_script else 'readiness' if 'responseStatus' in str(values.get('script','')) else 'other') if op=='eval' else None)
   return original_command(view,op,callback=callback,on_error=on_error,**values)
  browser.View._event=event;browser.View.command=command
  if a.coalesce_theme:
   original_run=browser.Page.runJavaScript
   def run(page,script,*args):
    # Controlled source-only variable: identical cosmetic theme queries only.
    # Keep all readiness, identity, save/recovery and other scripts untouched.
    view=page.parent()
    if script!=theme_script or not args or not callable(args[-1]) or not isinstance(view,browser.View):
     return original_run(page,script,*args)
    key=(view._active_generation,view._active_navigation)
    pending=getattr(page,'_perf_theme_pending',None)
    if pending is None:pending=set();page._perf_theme_pending=pending
    if key in pending:
     record('theme-coalesced',generation=key[0],nav_id=key[1]);return
    pending.add(key);callback=args[-1]
    def completed(value):
     pending.discard(key);callback(value)
    return original_run(page,script,*args[:-1],completed)
   browser.Page.runJavaScript=run
  from desktop.webview2_shell import DesktopWindow
  from PySide6.QtWidgets import QApplication
  from PySide6.QtCore import QTimer
  app=QApplication([])
  class TracedWindow(DesktopWindow):
   def _set_server_page_exposed(self,value,**kwargs):
    record('expose',value=value,loading=kwargs.get('loading'),serial=getattr(self,'_server_navigation_serial',None));return super()._set_server_page_exposed(value,**kwargs)
   def _server_load_started(self):record('load-start-slot');return super()._server_load_started()
   def _server_load_finished(self,ok):record('load-finish-slot',ok=ok);return super()._server_load_finished(ok)
   def _probe_server_readiness(self,completed=False):
    record('probe',completed=completed,pending=getattr(self,'_server_probe_pending',None),loading=self.view.page().isLoading() if self.view else None)
    return super()._probe_server_readiness(completed=completed)
  window=TracedWindow(paths,a.profile);window.show();window.start()
  timer=QTimer();timer.setInterval(20);timer.timeout.connect(lambda:pulses.append(time.monotonic()));timer.start()
  from tests.webview2.normal_server_performance import rows
  from tests.webview2.gui_server import native_cover_hit
  end=time.monotonic()+120;native=[];last=0;ready=[]
  while time.monotonic()<end:
   app.processEvents();now=time.monotonic()
   if window.failed_reason:raise RuntimeError(window.failed_reason)
   if now-last>.05 and window.view and getattr(window.view,'server_cover_state',{}):
    native.append({'at':now,**native_cover_hit(window)});last=now
   samples=[x for x in rows(out/'samples.jsonl') if x['run']=='source']
   page_ready=[x for x in rows(out/'page-ready.jsonl') if x['run']=='source']
   if page_ready:
    current=page_ready[-1];gate=out/f"gate-source-{current['cycle']}-{current['stage']}"
    if not gate.exists() and window._server_page_exposed and native and not native[-1]['cover_visible']:
     gate.write_text('source actual native uncovery');ready.append({'cycle':current['cycle'],'stage':current['stage'],'at':now,'after_report_ms':(now-current['received_monotonic'])*1000})
   if len(samples)==8 and len(ready)==8:break
   time.sleep(.002)
  else:raise TimeoutError('Source native cover/readiness comparison')
  if a.renderer_cadence:assert all(s.get('rendererCadence') is not None for s in samples),'Owned-fixture cadence opt-in was not applied to every page'
  host_metadata=[x['metadata'] for x in trace if x['kind']=='diagnostic-host']
  caps={'phase_limit_possible':any(x.get('event')=='diagnostic-phase' and x.get('sequence',0)>=4096 for x in host_metadata),
    'native_heartbeat_limit_possible':any(x.get('event')=='diagnostic-native-state' and x.get('sequence',0)>=1800 for x in host_metadata),
    'renderer_observer_capped':any(value.get('capped') for s in samples for value in (s.get('rendererCadence') or {}).values())}
  (out/'result.json').write_text(json.dumps({'source_instrumented':True,'normal_package':False,'physical_acceptance':False,'coalesce_theme':a.coalesce_theme,'renderer_cadence':a.renderer_cadence,
   'diagnostic_caps':caps,'instrumentation_overhead':'Private-pipe metadata serialization, read-only native getters/100ms heartbeat, buffered renderer duration observers; not normal-package timing.',
   'host':str(host),'samples':samples,'native_ready':ready,'native_cover':native,'trace':trace,
   'qt_heartbeat_max_ms':max((b-a)*1000 for a,b in zip(pulses,pulses[1:]))},indent=2))
 finally:
  from tests.windows.normal_processes import descendants,identity,alive
  observed={}
  if window is not None and window.view is not None and window.view.process is not None:
   host_pid=int(window.view.process.processId())
   if host_pid:
    for pid in descendants(host_pid):
     try:observed[pid]=identity(pid)['start']
     except OSError:pass
  if window is not None:
   window.close();end=time.monotonic()+15
   while not window._close_complete and time.monotonic()<end:app.processEvents();time.sleep(.01)
  job.stop();server.wait(timeout=15);log.close()
  (out/'trace-preserved.json').write_text(json.dumps(trace,indent=2))
  end=time.monotonic()+5
  while any(alive(pid,born) for pid,born in observed.items()) and time.monotonic()<end:
   app.processEvents();time.sleep(.02)
  survivors=[pid for pid,born in observed.items() if alive(pid,born)]
  cleanup={'source_close_complete':window._close_complete if window is not None else None,'owned_host_browser_survivors':survivors,'fixture_exit':server.returncode}
  (out/'cleanup.json').write_text(json.dumps(cleanup,indent=2))
  if window is not None:assert window._close_complete and not survivors,'Source native cleanup did not complete'
 print('Source trace complete',out,flush=True)

if __name__=='__main__':main()
