"""Captured app, 10k synthetic questions; HTTP and browser-side phase evidence."""
import hashlib,json,os,sys,time,threading,re,secrets
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));os.environ['DLMS_NO_BROWSER']='1'
import app as dlms
from flask import request,Response
from werkzeug.serving import make_server

out=Path(os.environ['DLMS_WVPERF_OUTPUT']);probe=(ROOT/'tests/webview2/server_performance_probe.js').read_bytes();record_lock=threading.Lock()
cadence=(ROOT/'tests/webview2/server_performance_cadence.js').read_bytes() if os.environ.get('DLMS_WVPERF_CADENCE')=='1' else None
def record(leaf,value):
 with record_lock:
  with (out/leaf).open('a',encoding='utf-8') as stream:stream.write(json.dumps(value)+'\n')

for bank in range(20):
 dlms._publish_quiz(f'Synthetic benchmark bank {bank+1:02d}',[
  {'number':i+1,'type':'choice','question':f'Synthetic bank {bank+1} question {i+1}?',
   'choices':[{'label':'A','text':'First synthetic choice','is_correct':True},{'label':'C','text':'Second synthetic choice','is_correct':False}],
   'correct':['A'],'explanation':'Synthetic benchmark explanation.'} for i in range(500)],
  filename_prefix=f'wvp_{bank}',exam_minutes=5)
registry=dlms.load_registry()
for i,row in enumerate(registry):row['folder']=f'Synthetic Folder {i%4+1}'
dlms.save_registry(registry)
cfg=dlms.load_portal_config();cfg['theme']='ethereal';dlms._write_settings_portal_config(cfg)

@dlms.app.before_request
def started():
 request.wvperf_start=time.monotonic()
 record('requests.jsonl',{'phase':'request','path':request.full_path,'at':request.wvperf_start,
  'local_token_present':bool(request.headers.get('X-DLMS-Desktop-Token'))})
 if request.path=='/' and '__wvperf' not in request.args:
  run=json.loads((out/'current-run.json').read_text())['run']
  return Response(status=302,headers={'Location':'/library?__wvperf='+run+'&cycle=0&stage=0'})

@dlms.app.after_request
def prepared(response):
 if request.path in ('/','/library','/quiz-composer'):
  response.direct_passthrough=False
  extra=b'<script src="/__wvperf/probe.js"></script>'
  if request.path=='/' and '__wvperf' not in request.args:
   run=json.loads((out/'current-run.json').read_text())['run']
   extra+=('<script>location.replace('+json.dumps('/library?__wvperf='+run+'&cycle=0&stage=0')+')</script>').encode()
  body=response.get_data().replace(b'</body>',extra+b'</body>')
  if cadence is not None:body=body.replace(b'<head>',b'<head><script>'+cadence+b'</script>',1)
  response.set_data(body)
 record('requests.jsonl',{'phase':'prepared','path':request.full_path,'at':time.monotonic(),
  'elapsed_ms':(time.monotonic()-request.wvperf_start)*1000,'status':response.status_code,
  'bytes':len(response.get_data()) if not response.direct_passthrough else None})
 return response

@dlms.app.get('/__wvperf/probe.js')
def script():return Response(probe,mimetype='application/javascript',headers={'Cache-Control':'public,max-age=3600'})

@dlms.app.post('/__wvperf/ready')
@dlms.app.post('/__wvperf/record')
def measured():
 value=request.get_json();assert isinstance(value,dict) and len(json.dumps(value))<65536
 if (re.fullmatch(r'(?:webview2-[0-2]|chrome-[0-2]|baseline-[0-2]|source)',str(value.get('run',''))) is None
     or type(value.get('cycle')) is not int or value['cycle'] not in (0,1)
     or type(value.get('stage')) is not int or value['stage'] not in range(4)):
  return Response('Synthetic measurement identity invalid',status=400)
 value['received_monotonic']=time.monotonic();record('page-ready.jsonl' if request.path.endswith('/ready') else 'samples.jsonl',value)
 gate=out/f"gate-{value['run']}-{value['cycle']}-{value['stage']}"
 deadline=time.monotonic()+25
 while not gate.exists():
  if time.monotonic()>deadline:
   record('gate-failures.jsonl',{'run':value['run'],'cycle':value['cycle'],'stage':value['stage'],'at':time.monotonic()})
   return Response('Synthetic native-ready gate timed out',status=504)
  time.sleep(.01)
 return Response(status=204)

original=dlms.app.wsgi_app
def traced(environ,start_response):
 path=environ.get('PATH_INFO','')+'?'+environ.get('QUERY_STRING','')
 def headers(status,values,exc_info=None):
  record('requests.jsonl',{'phase':'headers','path':path,'at':time.monotonic(),'status':status})
  return start_response(status,values,exc_info)
 iterable=original(environ,headers)
 def stream():
  digest=hashlib.sha256();complete=False
  try:
   for block in iterable:digest.update(block);yield block
   complete=True
  finally:
   if hasattr(iterable,'close'):iterable.close()
   record('requests.jsonl',{'phase':'body','path':path,'at':time.monotonic(),'complete':complete,'sha256':digest.hexdigest()})
 return stream()

# Ephemeral assignment can select Chromium-blocked service ports (observed1720).
# Choose an available high test port without overriding browser protections.
for attempt in range(16):
 try:
  server=make_server('127.0.0.2',50000+secrets.randbelow(10000),traced,threaded=True)
  break
 except SystemExit:
  if attempt==15:raise RuntimeError('No available high port for synthetic benchmark')
(out/'port').write_text(str(server.server_port),encoding='ascii')
server.serve_forever()
