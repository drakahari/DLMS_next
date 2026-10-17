"""Real QtDBus client + task-owned portal, never the host session portal."""
import json,os,subprocess,sys,time
from pathlib import Path
from PySide6.QtCore import QCoreApplication,QTimer,QUrl
from desktop.external_browser import dispatch,PortalRequest,_active
root=Path(sys.argv[1]);mode=sys.argv[2];root.mkdir(mode=0o700,parents=True,exist_ok=True)
app=QCoreApplication([]);log=(root/'service.log').open('w');service=None
if mode!='unavailable':
 service=subprocess.Popen(['/usr/bin/python3','-m','tests.session_browser.portal_service',str(root/'calls.jsonl'),mode],stdout=log,stderr=subprocess.STDOUT)
 deadline=time.monotonic()+5
 while not (root/'calls.jsonl.ready').exists():
  assert service.poll() is None,(root/'service.log').read_text()
  assert time.monotonic()<deadline;time.sleep(.02)
# Already scoped BEFORE application capture: these must not decide the browser.
for k in ('HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):os.environ[k]=str(root/'scoped')
os.environ['BROWSER']='/must/not/run';os.environ['DLMS_DESKTOP_NONCE']='synthetic-private-do-not-send'
results=[]
request=PortalRequest('https://browser-handoff.invalid/',timeout_ms=250 if mode=='timeout' else 3000)
request.finished.connect(lambda state,message:(results.append({'state':state,'message':message}),app.quit()))
if mode=='client-close':QTimer.singleShot(150,app.quit)
QTimer.singleShot(5000,app.quit)
try:
 app.exec()
 assert len(results)==1,results
 expected={'success':'accepted','early':'accepted','legacy':'accepted','cancel':'cancelled','failure':'unconfirmed','timeout':'unconfirmed','owner-loss':'unconfirmed','error':'unconfirmed','invalid-handle':'unconfirmed','unavailable':'unavailable','client-close':'cancelled'}[mode]
 assert results[0]['state']==expected,results
 assert not _active
 calls=[json.loads(x) for x in (root/'calls.jsonl').read_text().splitlines()] if service else []
 if service:
  opening=[x for x in calls if x['member']=='OpenURI'];assert len(opening)==1
  assert opening[0]['args'][0]=='' and opening[0]['args'][1]=='https://browser-handoff.invalid/'
  assert list(opening[0]['args'][2])==['handle_token']
  encoded=json.dumps(calls);assert 'synthetic-private-do-not-send' not in encoded and '/must/not/run' not in encoded and str(root/'scoped') not in encoded
 if mode in ('timeout','client-close'):
  deadline=time.monotonic()+1
  while not any('Close'==json.loads(x)['member'] for x in (root/'calls.jsonl').read_text().splitlines()) and time.monotonic()<deadline:time.sleep(.01)
  assert 'Close' in (root/'calls.jsonl').read_text()
 (root/'result.json').write_text(json.dumps({'mode':mode,'results':results,'checks':'scoped environment; exact encoded URI; no private fields; no subprocess fallback; single terminal result'},indent=2)+'\n')
 print(json.dumps({'mode':mode,**results[0]}))
finally:
 if service and service.poll() is None:service.terminate();service.wait(timeout=5)
 log.close()
