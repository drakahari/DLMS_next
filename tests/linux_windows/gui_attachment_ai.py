"""Source Qt attachment preserves its quiz page and rearms deliberate AI input."""
import argparse,json,tempfile,time
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QFileDialog
from tests.gate1.qt_checks import QtChecks
from desktop.server_mode import configured_server,write_config

def main():
 p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--server-origin',required=True);a=p.parse_args()
 if not a.profile.startswith('parityai'):raise ValueError('Dedicated synthetic profile required')
 q=QtChecks(a.profile,automated=True);report={'kind':'source-Qt','modes':[]};opened=[]
 import desktop.shell as shell
 old,oldpicker=shell.dispatch_external,QFileDialog.getSaveFileName
 shell.dispatch_external=lambda u:opened.append(u.toString()) or True
 out=Path(tempfile.mkdtemp(prefix='dlms-attachment-ai-',dir='/tmp'))
 def go(origin,path):
  view=q.window.view;finished=[]
  def loaded(ok):
   if view.url().path()==path:finished.append(ok)
  view.loadFinished.connect(loaded)
  try:
   view.setUrl(QUrl(origin+path));deadline=time.monotonic()+30
   while not finished and time.monotonic()<deadline:q.delay(.05)
   assert finished and finished[-1] is True,path
   q.wait('location.pathname==='+json.dumps(path)+" && document.readyState==='complete'")
  finally:view.loadFinished.disconnect(loaded)
 try:
  for mode in ('local','server'):
   if mode=='server':
    cfg=dict(q.window.mode_config,server=configured_server(q.window.mode_config,a.server_origin,'Synthetic attachment',private_http_opt_in=True));write_config(a.profile,cfg);q.window.mode_config=cfg;assert q.window.switch_to_server()
   origin=f'http://127.0.0.1:{q.window.port}' if mode=='local' else a.server_origin
   go(origin,'/')
   text='1. Select marker.\nA. Marker\nB. Other\nCorrect Answer: A\n'
   q.js("(async()=>{let f=new FormData();f.append('quiz_title','Attachment AI Fixture');f.append('file',new File([TEXT],'fixture.txt'));window.seed=(await fetch('/process',{method:'POST',body:f})).status})()".replace('TEXT',json.dumps(text)));q.wait('window.seed===200')
   go(origin,'/library')
   href=q.js("[...document.querySelectorAll('a[href^=\"/quizzes/\"]')].find(e=>e.closest('[data-quiz-id]')?.textContent.includes('Attachment AI Fixture')).getAttribute('href')")
   go(origin,href);q.wait("document.querySelector('.study-mode-btn')?.disabled===false");q.js("document.querySelector('.study-mode-btn').click();let a=document.createElement('a');a.id='reference-download';a.href='/export/all_quizzes.txt';a.textContent='Download fixture reference';document.body.prepend(a);true");q.delay(.2)
   destination=out/(mode+' reference.txt');QFileDialog.getSaveFileName=lambda *a,**kw:(str(destination),'')
   start=len(q.window.download_results);q.click_css('#reference-download')
   deadline=time.monotonic()+15
   while time.monotonic()<deadline:
    if len(q.window.download_results)>start and q.window.download_results[-1]['state']=='completed':break
    q.delay(.05)
   record=q.window.download_results[-1];assert record['state']=='completed' and 'Attachment AI Fixture' in destination.read_text()
   assert q.js('location.pathname')==href and q.js("document.getElementById('studyAiBtn')!==null")
   # Retain genuine clipboard operation but delay its resolution, not its data.
   q.js("let write=navigator.clipboard.writeText.bind(navigator.clipboard);navigator.clipboard.writeText=t=>write(t).then(()=>new Promise(r=>setTimeout(r,250)));true")
   count=len(opened);q.click_css('#studyAiBtn');q.delay(.6);assert len(opened)==count+1 and opened[-1]=='https://chatgpt.com/'
   assert 'Select marker' in q.app.clipboard().text()
   report['modes'].append({'mode':mode,'attachment_preserved_page':True,'delayed_clipboard_direct_ai':True,'output_bytes':destination.stat().st_size})
  assert q.window.switch_to_local();report['pass']=True
 finally:
  if q.window.mode=='server':q.window.switch_to_local()
  shell.dispatch_external=old;QFileDialog.getSaveFileName=oldpicker
  (q.paths['root']/'attachment-ai.json').write_text(json.dumps(report,indent=2)+'\n');q.close();print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
