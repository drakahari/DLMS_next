"""Native Save As dispatch, data fidelity, refusal/cancel and remembered scopes."""
import argparse,hashlib,json,tempfile,time,sys
from pathlib import Path
from PySide6.QtCore import QTimer,Qt,QUrl
from PySide6.QtWidgets import QFileDialog,QMessageBox
from tests.gate1.qt_checks import QtChecks
from desktop.server_mode import configured_server,write_config

def main():
 p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--server-origin',required=True);p.add_argument('--reopen',action='store_true');a=p.parse_args()
 q=QtChecks(a.profile,automated=True);report={'kind':'instrumented-frozen' if getattr(sys,'frozen',False) else 'source-Qt','steps':[]}
 root=Path(tempfile.mkdtemp(prefix='dlms-export-parity-',dir='/tmp'));folder=root/'Visible Documents é';folder.mkdir()
 original=QFileDialog.getSaveFileName;suggestions=[];answers=[];dialogs=[]
 def picker(*args,**kwargs):suggestions.append(str(args[2]));return (str(answers.pop(0)) if answers else '', '')
 QFileDialog.getSaveFileName=picker
 timer=QTimer();timer.setInterval(50)
 def reject():
  for w in q.app.topLevelWidgets():
   if isinstance(w,QMessageBox) and w.isVisible():dialogs.append(w.text());w.reject()
 timer.timeout.connect(reject);timer.start()
 def go(path):
  origin=f'http://127.0.0.1:{q.window.port}' if q.window.mode=='local' else a.server_origin
  q.window.view.setUrl(QUrl(origin+path));q.wait('location.pathname==='+json.dumps(path)+" && document.readyState==='complete'");q.delay(.15)
 def download(selector,destination,state):
  start=len(q.window.download_results);answers.append(destination if destination else '')
  q.js('document.querySelector('+json.dumps(selector)+').click();true')
  deadline=time.monotonic()+15
  while time.monotonic()<deadline:
   if len(q.window.download_results)>start and q.window.download_results[-1]['state']!='in_progress':break
   q.delay(.05)
  record=q.window.download_results[-1];assert record['state']==state,(record,q.window.statusBar().currentMessage())
  if state=='completed':
   assert Path(record['published_path']).read_bytes()==Path(record['path']).read_bytes()
   assert q.js('location.pathname')=='/library' and q.window.view.isVisible() and (q.window.settings_fallback is None or not q.window.settings_fallback.isVisible())
  report['steps'].append(dict(mode=q.window.mode,state=state,path=record.get('published_path'),status=q.window.statusBar().currentMessage()))
 try:
  if a.reopen:
   from desktop.exports import initial
   data=json.loads((q.paths['root']/'export-parity-state.json').read_text());assert str(initial(q.window)[0])==data['folder']
   for path,digest in data['outputs'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
   report['reopen_remembered_folder_and_bytes']=True
  else:
   q.js("""(async()=>{let f=new FormData();f.append('quiz_title','Export Fixture');f.append('file',new File(['1. Select the marker.\\nA. Marker\\nB. Other\\nCorrect Answer: A\\n'],'fixture.txt'));window.created=(await fetch('/process',{method:'POST',body:f})).status;})()""");q.wait('window.created===200')
   go('/library');reference='a[href="/export/all_quizzes.txt"]';individual='a[href^="/export/quiz/"]'
   first=folder/'Library reference é.txt';download(reference,first,'completed');assert 'Export Fixture' in first.read_text()
   download(individual,folder/'quiz.txt','completed');assert suggestions[-1].startswith(str(folder))
   download(reference,None,'cancelled');before=hashlib.sha256(first.read_bytes()).hexdigest()
   download(reference,first,'failed');assert hashlib.sha256(first.read_bytes()).hexdigest()==before and dialogs
   outputs={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir() if path.is_file()}
   cfg=dict(q.window.mode_config,server=configured_server(q.window.mode_config,a.server_origin,'Synthetic exports',private_http_opt_in=True));write_config(a.profile,cfg);q.window.mode_config=cfg;assert q.window.switch_to_server()
   go('/library');server_out=root/'Server Folder é';server_out.mkdir();download(reference,server_out/'Server.txt','completed')
   assert not suggestions[-1].startswith(str(folder)),'Server must not inherit Local preferred folder'
   assert q.window.switch_to_local();q.wait("location.pathname==='/' && document.readyState==='complete'")
   from desktop.exports import initial
   assert initial(q.window)[0]==folder
   (q.paths['root']/'export-parity-state.json').write_text(json.dumps({'folder':str(folder),'outputs':outputs})+'\n')
  q.window.grab().save(str(q.paths['root']/'export-native.png'))
  report['pass']=True
 finally:
  timer.stop();QFileDialog.getSaveFileName=original
  if q.window.mode=='server':q.window.switch_to_local()
  (q.paths['root']/('export-parity-reopen.json' if a.reopen else 'export-parity.json')).write_text(json.dumps(report,indent=2)+'\n');q.close();print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
