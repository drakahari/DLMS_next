"""Normal package: 45 observed cover-on/off lifecycles, synthetic Server only."""
import argparse,hashlib,json,os,subprocess,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from tests.webview2.normal_server_performance import windows,native_uncovered

def main():
 p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 root=Path(__file__).resolve().parents[2];out=a.output.absolute();assert out.is_relative_to(root/'.gate1/windows-native') and not out.exists()
 out.mkdir(mode=0o700);exe=a.exe.resolve(strict=True);requested=[];ready=[];records=[];holds=[threading.Event() for _ in range(45)];gates=[threading.Event() for _ in range(45)]
 lock=threading.Lock();failed=[]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*_):pass
  def do_GET(self):
   query=parse_qs(urlsplit(self.path).query);step=int(query.get('step',['0'])[0]);assert 0<=step<45
   path=urlsplit(self.path).path
   if self.headers.get('X-DLMS-Desktop-Token'):failed.append('Local credential disclosed')
   if path=='/hold':
    success=holds[step].wait(15);body=b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>';kind='image/svg+xml'
    if not success:failed.append(f'cover-on gate timeout at {step}')
   elif path=='/ready':
    with lock:ready.append({'step':step,'at':time.monotonic()})
    success=gates[step].wait(15);body=b'ready';kind='text/plain'
    if not success:failed.append(f'cover-off gate timeout at {step}')
   elif path=='/':
    with lock:requested.append({'step':step,'at':time.monotonic()})
    body=(f'<!doctype html><title>Synthetic navigation {step}</title><h1>Page {step}</h1><img src="/hold?step={step}" alt="Held synthetic lifecycle resource"><script>'
     f'addEventListener("load",async()=>{{await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));'
     f'const response=await fetch("/ready?step={step}");if(!response.ok)throw Error("gate");'
     +(f'location.href="/?step={step+1}";' if step<44 else 'document.body.dataset.complete="true";')+'});</script>').encode();kind='text/html; charset=utf-8';success=True
   else:body=b'';kind='text/plain';success=True
   self.send_response(200 if success else 504);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers()
   try:self.wfile.write(body)
   except (BrokenPipeError,ConnectionResetError):pass
 server=ThreadingHTTPServer(('127.0.0.2',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 from package_windows.entry import root_path
 from desktop.windows_processes import Job
 from tests.windows.normal_processes import descendants,identity,alive
 data=out/'data';root_path(data,create=True);shell=data/'shell'/'history01';shell.mkdir(mode=0o700,parents=True)
 config={'version':1,'profile':'history01','mode':'server','server':{'id':str(uuid.uuid4()),'label':'Synthetic navigation history','origin':f'http://127.0.0.2:{server.server_port}','private_http':True}}
 (shell/'mode.json').write_text(json.dumps(config));env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','PYTHON','QTWEBENGINE_'))};env['PATH']=str(out/'no-host-tools')
 proc=None;job=Job();observed={};passed=False;reason=None;stream=(out/'launcher.log').open('w')
 try:
  proc=subprocess.Popen([str(exe),'--data-root',str(data),'--profile','history01'],env=env,cwd=out,stdout=stream,stderr=subprocess.STDOUT);job.assign(int(proc._handle));observed[proc.pid]=identity(proc.pid)['start']
  deadline=time.monotonic()+65;state_deadline=time.monotonic()+15;last_step=-1
  while time.monotonic()<deadline:
   assert proc.poll() is None,'Owned normal package exited early'
   pids=descendants(proc.pid)
   for pid in pids:
    if pid not in observed:
     try:observed[pid]=identity(pid)['start']
     except OSError:pass
   items=windows(pids);by_handle={x['hwnd']:x for x in items}
   with lock:current=requested[-1]['step'] if requested else None;ready_steps={x['step'] for x in ready}
   if current is not None:
    if current!=last_step:last_step=current;state_deadline=time.monotonic()+12
    visible_cover=any(x['class'].startswith('WindowsForms10.STATIC.') and x['visible'] and by_handle.get(x['parent'],{}).get('visible') for x in items)
    if not holds[current].is_set() and visible_cover:
     records.append({'step':current,'phase':'cover-on','at':time.monotonic()});holds[current].set()
    if holds[current].is_set() and current in ready_steps and not gates[current].is_set() and native_uncovered(items):
     records.append({'step':current,'phase':'cover-off','at':time.monotonic()});gates[current].set()
    if current==44 and gates[44].is_set():passed=True;break
    if time.monotonic()>state_deadline:raise TimeoutError(f'Normal native lifecycle stalled at step {current}; cover-on={holds[current].is_set()}, page-ready={current in ready_steps}, cover-off={gates[current].is_set()}')
   time.sleep(.025)
  else:raise TimeoutError('Normal navigation history outer bound')
  assert [r['step'] for r in records if r['phase']=='cover-on']==list(range(45))
  assert [r['step'] for r in records if r['phase']=='cover-off']==list(range(45))
  assert not failed
 except BaseException as exc:
  reason=type(exc).__name__+': '+str(exc);raise
 finally:
  for event in holds+gates:event.set()
  job.stop()
  if proc:proc.wait(timeout=15)
  server.shutdown();server.server_close();stream.close()
  (out/'result.json').write_text(json.dumps({'passed':passed,'reason':reason,'normal_package':True,'app_test_hooks':False,'physical_acceptance':False,
   'executable':str(exe),'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'requested':requested,'ready':ready,'native_events':records,
   'failures':failed,'owned_survivors':[pid for pid,born in observed.items() if alive(pid,born)],'cleanup':'Exact test job, not normal-close acceptance'},indent=2))
 print('Normal package45native lifecycles passed',out,flush=True)

if __name__=='__main__':main()
