"""App-local source-Qt output matrix, separate from normal frozen evidence."""
import argparse,ast,hashlib,json,os,socket,sqlite3,subprocess,sys,time,zipfile
from pathlib import Path
from PySide6.QtCore import QUrl,QTimer
from PySide6.QtWidgets import QFileDialog,QMessageBox
import desktop.shell as shell
# Source worktrees exceed Unix socket path length; test-only short IPC name.
shell.instance_socket_name=lambda root:'/tmp/dlms-output-'+hashlib.sha256(str(root).encode()).hexdigest()[:18]+'.sock'
from desktop.server_browser import ServerOnlyInterceptor
from tests.gate1.qt_checks import QtChecks
from desktop.server_mode import configured_server,write_config


def main():
 p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--output',required=True,type=Path);p.add_argument('--baseline-print',action='store_true');a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False)
 events=[]
 for cls in (shell.LocalOnlyInterceptor,ServerOnlyInterceptor):
  original=cls.interceptRequest
  def trace(self,info,original=original):
   if info.requestUrl().path()=='/anki/printable':events.append({'method':bytes(info.requestMethod()).decode(),'url':info.requestUrl().toString()})
   original(self,info)
  cls.interceptRequest=trace
 if a.baseline_print:
  old=subprocess.check_output(['git','show','5784e7bbe372ffe6cf6a241d934081815f7edd8c:desktop/shell.py'],text=True)
  method=next(n for n in next(n for n in ast.parse(old).body if isinstance(n,ast.ClassDef) and n.name=='LocalPage').body if isinstance(n,ast.FunctionDef) and n.name=='_new_window')
  exec(compile(ast.unparse(method),'<exact-base-new-window>','exec'),shell.__dict__)
  shell.LocalPage._new_window=shell.__dict__['_new_window']
 q=QtChecks(a.profile,automated=True);answers=[];prompts=[];report={'kind':'source Qt, app-local QTest; native chooser answers simulated','events':events,'downloads':[]};server=None
 timer=QTimer();timer.setInterval(30)
 def dismiss():
  for w in q.app.topLevelWidgets():
   if isinstance(w,QMessageBox) and w.isVisible():prompts.append(w.text());w.reject()
 timer.timeout.connect(dismiss);timer.start()
 def picker(*args,**kwargs):
  prompts.append('Save As');return (str(answers.pop(0)) if answers else '', '')
 original_picker=QFileDialog.getSaveFileName;QFileDialog.getSaveFileName=picker
 def wait_python(f,timeout=20):
  end=time.monotonic()+timeout
  while not f() and time.monotonic()<end:q.delay(.06)
  assert f(),q.window.statusBar().currentMessage()
 def apkg(path):
  with zipfile.ZipFile(path) as z:
   data=z.read('collection.anki2')
  conn=sqlite3.connect(':memory:');conn.deserialize(data)
  fields=[x[0] for x in conn.execute('SELECT flds FROM notes')];conn.close()
  assert any('synthetic marker' in x.lower() or 'Browser question' in x for x in fields),fields
  return {'notes':len(fields),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
 def marked():
  q.go('/library') if q.window.mode=='local' else go('/library')
  selector=q.js("document.querySelector('a[href^=\"/quizzes/\"]').getAttribute('href')")
  go(selector);q.js("document.querySelector('.study-mode-btn').click();true");q.wait('durableStudySession!==null&&reviewMarkContext!==null')
  q.click_css('#studyAnkiBtn');q.wait('reviewMarkContext.indexes.includes(0)&&reviewMarkPending===null')
  go('/marked-questions');q.click_css('#selectPageMarks');q.wait("!document.getElementById('exportMarks').disabled")
 def go(path):
  origin=f'http://127.0.0.1:{q.window.port}' if q.window.mode=='local' else q.window.mode_config['server']['origin']
  q.window.view.setUrl(QUrl(origin+path));q.wait('location.pathname==='+json.dumps(path.split('?')[0])+"&&document.readyState==='complete'");q.delay(.2)
 def export(selector,destination,expected,script=False):
  before=len(q.window.download_results);answers.append(str(destination) if destination else '')
  if script:q.js('document.querySelector('+json.dumps(selector)+').click();true')
  else:q.click_css(selector)
  wait_python(lambda:len(q.window.download_results)>before and q.window.download_results[-1]['state'] not in ('in_progress',))
  record=q.window.download_results[-1]
  assert record['state']==expected,(expected,record,q.window.statusBar().currentMessage())
  if expected=='completed':
   content=apkg(record['published_path']);assert Path(record['published_path']).read_bytes()==Path(record['path']).read_bytes()
  else:content={}
  assert q.js('location.pathname')=='/marked-questions'
  wait_python(lambda: {'completed':'saved to the selected folder','cancelled':'Save As canceled','failed':'not saved','refused':'not saved'}[expected] in q.js("document.getElementById('markActionStatus').textContent"))
  assert 'exported' not in q.js("document.getElementById('markActionStatus').textContent").lower()
  report['downloads'].append({'mode':q.window.mode,'expected':expected,'record':record,'content':content,'status':q.window.statusBar().currentMessage()})
  if expected=='refused':answers.pop()
 def printable(mode):
  go('/anki/custom');q.js("document.querySelector('input[name=quiz_cards]').checked=true;document.querySelector('[name=deck_name]').value='Synthetic preserved POST';document.querySelector('[name=duplex_flip]').value='short';true")
  q.click_css('button[formaction="/anki/printable"]');q.wait("location.pathname==='/anki/printable'&&document.readyState==='complete'");q.delay(.2)
  text=q.js('document.body.innerText')
  if a.baseline_print:
   assert 'Method Not Allowed' in text and events[-1]['method']=='GET',events
  else:
   assert events[-1]['method']=='POST' and 'Synthetic preserved POST' in text and 'short-edge flip' in text and 'Avery 5388' in text,(events,text)
   assert q.js("document.querySelectorAll('.avery-sheet.front-sheet .avery-card').length")>0
  report[mode+'_printable']={'events':list(events),'text':text[:400]}
  q.screenshot(str(a.output/(mode+'-printable.png')))
  if not a.baseline_print:
   q.click_css('#returnCustomDeck');q.wait("location.pathname==='/anki/custom'&&document.readyState==='complete'")
   assert q.js("document.querySelectorAll('input[name=quiz_cards]:checked').length")==1
   assert q.js("document.querySelector('[name=deck_name]').value")=='Synthetic preserved POST'
   report[mode+'_return_preserves_selection']=True
 try:
  q.js("""(async()=>{let f=new FormData();f.append('quiz_title','Output Synthetic');f.append('file',new File(['1. Choose the synthetic marker.\\nA. Marker\\nB. Other\\nCorrect Answer: A\\n'],'synthetic.txt'));window.seed=(await fetch('/process',{method:'POST',body:f})).status;})()""");q.wait('window.seed===200')
  if a.baseline_print:printable('baseline');return
  marked();export('#exportMarks',a.output/'marked-local.apkg','completed')
  export('#markExportResult a',a.output/'marked-repeat.apkg','completed')
  export('#exportMarks',a.output/'marked-new-action.apkg','completed')
  export('#markExportResult a',None,'cancelled')
  old=hashlib.sha256((a.output/'marked-local.apkg').read_bytes()).hexdigest()
  export('#markExportResult a',a.output/'marked-local.apkg','failed');assert hashlib.sha256((a.output/'marked-local.apkg').read_bytes()).hexdigest()==old
  before_prompts=len(prompts);export('#markExportResult a',None,'refused',script=True);assert len(prompts)==before_prompts
  href=q.js("document.querySelector('#markExportResult a').href")
  q.js('(()=>{const f=document.createElement("iframe");f.id="untrustedExportFrame";f.style="width:600px;height:120px;border:0";f.srcdoc='+json.dumps('<a style="display:block;height:120px;width:600px" download="dlms_marked_questions.apkg" href="')+'+'+json.dumps(href)+'+'+json.dumps('">Frame export</a>')+';document.body.append(f);return true;})()')
  q.delay(.3);before_prompts=len(prompts)
  export('#untrustedExportFrame',None,'refused');assert len(prompts)==before_prompts
  printable('local')
  # A real separately owned browser-application server; never production.
  serverroot=a.output/'server';serverroot.mkdir()
  with socket.socket() as sock:sock.bind(('127.0.0.2',0));port=sock.getsockname()[1]
  env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_'))}
  env.update(QUIZAPP_DATA_DIR=str(serverroot/'data'),DLMS_NO_BROWSER='1',DLMS_BROWSER_TEST_BIND_HOST='127.0.0.2',DLMS_BROWSER_TEST_PORT=str(port),PYTHONDONTWRITEBYTECODE='1')
  log=(serverroot/'server.log').open('w');server=subprocess.Popen([sys.executable,'tests/browser/_server.py'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  wait_python(lambda:(serverroot/'data/browser_fixture.json').exists())
  cfg=dict(q.window.mode_config,server=configured_server(q.window.mode_config,f'http://127.0.0.2:{port}','Synthetic output server',private_http_opt_in=True));write_config(a.profile,cfg);q.window.mode_config=cfg;assert q.window.switch_to_server();q.delay(.5)
  marked();export('#exportMarks',a.output/'marked-server.apkg','completed');export('#markExportResult a',None,'cancelled');printable('server')
  assert q.window.switch_to_local();q.wait("location.pathname==='/'&&document.readyState==='complete'")
  report['pass']=True
 finally:
  timer.stop();QFileDialog.getSaveFileName=original_picker
  if q.window.mode=='server':q.window.switch_to_local();q.delay(.2)
  q.close()
  if server is not None:server.terminate();server.wait(timeout=15)
  (a.output/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
