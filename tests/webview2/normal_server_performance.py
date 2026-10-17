"""Matched normal frozen WebView2 / headed Chrome, synthetic Server 10k only.

Server-owned scripts measure their own page; no packaged test hooks or OS input.
Native child HWND visibility samples do not prove correct displayed pixels.
"""
import argparse,ctypes,hashlib,json,os,subprocess,sys,time,uuid
from ctypes import wintypes as w
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
def rows(path):
 try:
  raw=path.read_text(encoding='utf-8');lines=raw.splitlines()
  if raw and not raw.endswith('\n'):lines=lines[:-1]  # active writer's unfinished last line only
  return [json.loads(line) for line in lines]
 except FileNotFoundError:return []
def wait(predicate,timeout=90):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  value=predicate()
  if value:return value
  time.sleep(.025)
 raise TimeoutError('Bounded synthetic performance checkpoint')

def native_uncovered(items):
 """Own WinForms cover identity, independent of mutable connection label text."""
 by_handle={item['hwnd']:item for item in items}
 renderers=[item for item in items if item['class']=='Chrome_RenderWidgetHostHWND' and item['visible']]
 for label in items:
  if not label['class'].startswith('WindowsForms10.STATIC.'):continue
  cover=by_handle.get(label['parent'])
  host=by_handle.get(cover['parent']) if cover else None
  if (cover and host and host['text']=='DLMS Desktop' and label['pid']==cover['pid']==host['pid']
      and not cover['visible'] and not label['visible']
      and any(renderer['rect']==cover['rect'] for renderer in renderers)):
   return True
 return False

def windows(pids):
 user=ctypes.windll.user32;result=[]
 user.GetForegroundWindow.argtypes=[];user.GetForegroundWindow.restype=w.HWND
 foreground=int(user.GetForegroundWindow() or 0)
 user.GetParent.argtypes=[w.HWND];user.GetParent.restype=w.HWND
 user.IsWindowVisible.argtypes=[w.HWND];user.IsWindowVisible.restype=w.BOOL
 callback=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
 def one(hwnd,unused):
  pid=w.DWORD();user.GetWindowThreadProcessId(w.HWND(hwnd),ctypes.byref(pid))
  if pid.value not in pids:return True
  title=ctypes.create_unicode_buffer(512);cls=ctypes.create_unicode_buffer(256);rect=w.RECT()
  user.GetWindowTextW(w.HWND(hwnd),title,512);user.GetClassNameW(w.HWND(hwnd),cls,256)
  user.GetWindowRect(w.HWND(hwnd),ctypes.byref(rect))
  result.append({'hwnd':int(hwnd),'pid':pid.value,'parent':int(user.GetParent(w.HWND(hwnd)) or 0),
   'class':cls.value,'text':title.value,'visible':bool(user.IsWindowVisible(w.HWND(hwnd))),'foreground':int(hwnd)==foreground,
   'rect':[rect.left,rect.top,rect.right,rect.bottom]})
  return True
 cb=callback(one)
 def top(hwnd,unused):
  one(hwnd,unused);user.EnumChildWindows(w.HWND(hwnd),cb,0);return True
 user.EnumWindows(callback(top),0)
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--baseline-exe',type=Path,help='Compare two unchanged normal WebView2 packages instead of Chrome')
 p.add_argument('--baseline-first',action='store_true',help='Reverse initial package order on a fresh synthetic fixture')
 p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
 out=a.output.absolute();assert out.is_relative_to(ROOT/'.gate1/windows-native') and not out.exists()
 assert a.repeats==3,'Exactly three independent cold/warm sessions'
 if a.baseline_first and not a.baseline_exe:raise ValueError('Reversed initial order requires a normal-package baseline')
 out.mkdir(mode=0o700);exe=a.exe.resolve(strict=True)
 from desktop.windows_files import owned
 owned(out,private=True)
 from desktop.windows_processes import Job
 from tests.windows.normal_processes import descendants,identity,alive
 from tests.windows.responsiveness import CDP,json_http
 server_env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','PYTHON'))}
 for key,leaf in [('USERPROFILE','server-home'),('HOME','server-home'),('APPDATA','server-config'),('LOCALAPPDATA','server-local'),('TEMP','server-tmp'),('TMP','server-tmp')]:
  path=out/leaf;path.mkdir(mode=0o700,exist_ok=True);server_env[key]=str(path)
 server_env.update(QUIZAPP_DATA_DIR=str(out/'server-data'),DLMS_WVPERF_OUTPUT=str(out),DLMS_NO_BROWSER='1')
 (out/'current-run.json').write_text(json.dumps({'run':'initial'}))
 log=(out/'server.log').open('w');server=subprocess.Popen([sys.executable,'-m','tests.webview2.server_performance_fixture'],env=server_env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 server_job=Job();server_job.assign(int(server._handle));results=[];viewport=None
 try:
  wait(lambda:(out/'port').exists() or (server.poll() is not None and (_ for _ in ()).throw(RuntimeError('Fixture startup failed'))),120)
  origin='http://127.0.0.2:'+(out/'port').read_text().strip()
  for repetition in range(3):
   control='baseline' if a.baseline_exe else 'chrome'
   for engine in (['webview2',control] if (repetition%2==0)!=a.baseline_first else [control,'webview2']):
    run=f'{engine}-{repetition}';folder=out/run;folder.mkdir(mode=0o700)
    (out/'current-run.json').write_text(json.dumps({'run':run}))
    proc=None;browser=None;page=None;job=Job();observed={};snapshots=[];ready=[]
    stream=(folder/'launcher.log').open('w');start=time.monotonic()
    try:
     if engine!='chrome':
      data=folder/'data'
      from package_windows.entry import root_path
      root_path(data,create=True)
      shell=data/'shell'/'perf01';shell.mkdir(mode=0o700,parents=True)
      config={'version':1,'profile':'perf01','mode':'server','server':{'id':str(uuid.uuid4()),'label':'Synthetic ten thousand benchmark','origin':origin,'private_http':True}}
      (shell/'mode.json').write_text(json.dumps(config),encoding='utf-8')
      env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','PYTHON','QTWEBENGINE_'))};env['PATH']=str(folder/'no-host-tools')
      selected_exe=a.baseline_exe.resolve(strict=True) if engine=='baseline' else exe
      proc=subprocess.Popen([str(selected_exe),'--data-root',str(data),'--profile','perf01'],env=env,cwd=folder,stdout=stream,stderr=subprocess.STDOUT)
     else:
      chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe');profile=folder/'browser-storage'
      proc=subprocess.Popen([str(chrome),'--user-data-dir='+str(profile),'--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
        '--no-first-run','--no-default-browser-check','--disable-background-networking','--window-size=1280,850','about:blank'],cwd=folder,stdout=stream,stderr=subprocess.STDOUT)
     job.assign(int(proc._handle));observed[proc.pid]=identity(proc.pid)['start']
     if engine=='chrome':
      def port_value():
       try:return int((profile/'DevToolsActivePort').read_text().splitlines()[0])
       except (OSError,ValueError,IndexError):return None
      port=wait(port_value,30);version=json_http(port,'/json/version');browser=CDP.connect_url(version['webSocketDebuggerUrl'])
      target=json_http(port,'/json/new?about:blank','PUT');page=CDP.connect_url(target['webSocketDebuggerUrl'])
      assert viewport,'First normal package establishes actual matched viewport'
      browser.command('Target.activateTarget',{'targetId':target['id']})
      geometry=page.evaluate('({width:innerWidth,height:innerHeight,outerWidth,outerHeight,dpr:devicePixelRatio})')
      assert geometry['dpr']==viewport['dpr'],'Actual display scale must match without emulation'
      native_window=browser.command('Browser.getWindowForTarget',{'targetId':target['id']})
      browser.command('Browser.setWindowBounds',{'windowId':native_window['windowId'],'bounds':{'left':0,'top':0,
        'width':viewport['width']+geometry['outerWidth']-geometry['width'],
        'height':viewport['height']+geometry['outerHeight']-geometry['height'],'windowState':'normal'}})
      wait(lambda:page.evaluate('innerWidth')==viewport['width'] and page.evaluate('innerHeight')==viewport['height'],10)
      (folder/'native-viewport.json').write_text(json.dumps(page.evaluate('({width:innerWidth,height:innerHeight,outerWidth,outerHeight,dpr:devicePixelRatio,screenX,screenY})'),indent=2))
      page.command('Page.navigate',{'url':origin+'/'})
      (folder/'runtime.json').write_text(json.dumps({'version':version,'graphics':browser.command('SystemInfo.getInfo',{})},indent=2))
     last_inspect=0
     def completed():
      nonlocal last_inspect
      assert proc.poll() is None,'Owned test window exited early'
      now=time.monotonic()
      if now-last_inspect>.05:
       pids=descendants(proc.pid)
       for pid in pids:
        if pid not in observed:
         try:observed[pid]=identity(pid)['start']
         except OSError:pass
       snapshots.append({'at':now,'utc_ms':time.time()*1000,'windows':windows(pids)});last_inspect=now
      selected=[x for x in rows(out/'samples.jsonl') if x['run']==run]
      page_ready=[x for x in rows(out/'page-ready.jsonl') if x['run']==run]
      if page_ready:
       current=page_ready[-1];gate=out/f"gate-{run}-{current['cycle']}-{current['stage']}"
       state=snapshots[-1]
       # Advance only after actual native uncovery; browser has no Desktop cover.
       uncovered=native_uncovered(state['windows'])
       if not gate.exists() and (engine=='chrome' or uncovered):
        acknowledged=time.monotonic()
        gate.write_text('native ready' if engine!='chrome' else 'browser two frames')
        ready.append({'cycle':current['cycle'],'stage':current['stage'],'at':acknowledged,'server_report_at':current['received_monotonic'],
          'native_ready_after_report_ms':(acknowledged-current['received_monotonic'])*1000,'uncovered':uncovered})
      return selected if len(selected)==8 and len(ready)==8 else None
     samples=wait(completed,120)
     if viewport is None:viewport=samples[0]['viewport']
     assert all(x['viewport']==viewport and not x['hidden'] for x in samples)
     for sample in samples:
      if sample['path']=='/quiz-composer':
       assert sample['content']['questionCount']==10000
       assert all(f['shown']==(2500 if f['folder'] else 10000) and f['selected']==0 for f in sample['filters'])
     (folder/'native-windows.json').write_text(json.dumps(snapshots,indent=2))
     (folder/'native-ready.json').write_text(json.dumps(ready,indent=2))
     from experiments.windows_webview2.compare import modules
     from tests.webview2.normal_candidate import file_version,argument_metadata
     from desktop.windows_processes import arguments
     inspected=modules(proc.pid)
     for item in inspected:
      if 'identity' in item:
       try:
        argv=arguments(item['pid']);item.update(argument_metadata(argv))
        item['scheduler_flag_names']=[arg.partition('=')[0] for arg in argv if arg.startswith('--')
          and any(word in arg.partition('=')[0].lower() for word in ('occlu','background','visibility','throttl'))]
       except (OSError,ValueError) as exc:item['arguments_error']=type(exc).__name__
       try:item['file_version']=file_version(item['identity']['image'])
       except (OSError,ValueError) as exc:item['file_version_error']=type(exc).__name__
     (folder/'process-runtime-modules.json').write_text(json.dumps(inspected,indent=2))
     assert not any(item.get('security_bypass_flags') for item in inspected)
     results.append({'engine':engine,'repetition':repetition,'samples':samples,'elapsed_seconds':time.monotonic()-start})
     (out/'progress.json').write_text(json.dumps(results,indent=2))
     print(run,'complete',round(time.monotonic()-start,2),flush=True)
    finally:
     if snapshots and not (folder/'native-windows.json').exists():(folder/'native-windows-failure.json').write_text(json.dumps(snapshots,indent=2))
     if page:page.close()
     if browser:browser.close()
     job.stop()
     if proc:proc.wait(timeout=15)
     stream.close();time.sleep(.2)
     (folder/'cleanup.json').write_text(json.dumps({'own_test_job_terminated':True,'survivors':[pid for pid,born in observed.items() if alive(pid,born)],'normal_close_acceptance':False}))
  requests=rows(out/'requests.jsonl');assert not any(x.get('local_token_present') for x in requests)
  (out/'result.json').write_text(json.dumps({'normal_executable':str(exe),'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
    'normal_package':True,'app_test_hooks':False,'physical_input':False,'correct_pixels_established':False,'question_count':10000,
    'origin':origin,'viewport':viewport,'samples':results,'server_local_token_absent':True,
    'baseline_first':a.baseline_first,'baseline_executable':str(a.baseline_exe.resolve(strict=True)) if a.baseline_exe else None,
    'baseline_sha256':hashlib.sha256(a.baseline_exe.read_bytes()).hexdigest() if a.baseline_exe else None},indent=2))
 finally:
  server_job.stop();server.wait(timeout=15);log.close()

if __name__=='__main__':main()
