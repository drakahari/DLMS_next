"""Actual captured AI forms/controls in Local and isolated captured Server.

Only final external dispatch is intercepted; no provider or owner browser opens.
Qt input stays inside the owned view. No host-wide input or physical claim.
"""
import argparse,json,time,sqlite3,sys
from pathlib import Path
from urllib.parse import urlsplit
from PySide6.QtCore import Qt,QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from tests.gate1.qt_checks import QtChecks
from desktop.server_mode import configured_server,write_config


def main():
 p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--server-origin',required=True);p.add_argument('--reopen',action='store_true');p.add_argument('--session-portal',action='store_true');a=p.parse_args()
 if not a.profile.startswith('parityai'):raise ValueError('Dedicated synthetic profile required')
 q=QtChecks(a.profile,automated=True);report={'kind':'instrumented-frozen' if getattr(sys,'frozen',False) else 'source-Qt','checks':[],'opened':[],'confirmations':[]}
 import desktop.shell as shell
 old=shell.dispatch_external;oldq=QMessageBox.question
 report['portal_outcomes']=[]
 def dispatch(url):
  report['opened'].append(url.toString())
  if not a.session_portal:return True
  request=old(url)
  request.finished.connect(lambda state,message:report['portal_outcomes'].append({'state':state,'message':message}))
  return request
 shell.dispatch_external=dispatch
 QMessageBox.question=lambda *args,**kw:report['confirmations'].append(args[2]) or QMessageBox.StandardButton.No
 def go(path):
  origin=f'http://127.0.0.1:{q.window.port}' if q.window.mode=='local' else a.server_origin
  q.window.view.setUrl(QUrl(origin+path));q.wait('location.pathname==='+json.dumps(urlsplit(path).path)+" && document.readyState==='complete'",30);q.delay(.15)
 def post(path,data,ready):
  q.js("""(()=>{let f=document.createElement('form');f.method='POST';f.action=PATH;let data=DATA;data.csrf_token=decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='))?.split('=')[1]||'');for(let [k,v] of Object.entries(data)){let e=document.createElement('input');e.type='hidden';e.name=k;e.value=v;f.append(e)}document.body.append(f);f.submit();return true})()""".replace('PATH',json.dumps(path)).replace('DATA',json.dumps(data)))
  q.wait(ready,30)
 def activate(selector,key=None):
  if key:
   q.js('document.querySelector('+json.dumps(selector)+').focus();true');q.delay(.05)
   QTest.keyClick(q.window.view.focusProxy(),key)
  else:q.click_css(selector)
  q.delay(.25)
 def check(name,selector,key=None,copy=True):
  before=len(report['opened']);prompts=len(report['confirmations']);q.app.clipboard().setText('before-synthetic-ai')
  activate(selector,key)
  deadline=time.monotonic()+5
  while len(report['opened'])==before and time.monotonic()<deadline:q.delay(.04)
  assert len(report['opened'])==before+1,(name,q.window.mode,report)
  assert report['opened'][-1] in ('https://chatgpt.com/','https://claude.ai/','https://gemini.google.com/')
  assert len(report['confirmations'])==prompts,(name,report)
  if a.session_portal:
   deadline=time.monotonic()+5
   while len(report['portal_outcomes'])<len(report['opened']) and time.monotonic()<deadline:q.delay(.02)
   assert len(report['portal_outcomes'])==len(report['opened']) and report['portal_outcomes'][-1]['state']=='accepted',report
  if copy:assert q.app.clipboard().text()!='before-synthetic-ai',name
  report['checks'].append({'mode':q.window.mode,'action':name,'activation':'pointer' if key is None else str(key),'one_direct_open':True,'copy':copy})
 def negatives():
  before=len(report['opened'])
  q.js("document.getElementById('studyAiBtn').click();setTimeout(()=>window.open('https://chatgpt.com/','_blank','noopener,noreferrer'),100);true");q.delay(.25)
  assert len(report['opened'])==before
  # Genuine Copy Question remains copy-only and cannot authorize timer opening.
  activate('#studyCopyBtn');q.js("window.open('https://chatgpt.com/','_blank','noopener,noreferrer');true");q.delay(.2)
  assert len(report['opened'])==before
  # A generic supported-root anchor is still explicitly confirmed.
  q.js("let a=document.createElement('a');a.id='generic';a.href='https://chatgpt.com/';a.target='_blank';a.textContent='Generic website';document.body.prepend(a);true")
  c=len(report['confirmations']);activate('#generic');assert len(report['confirmations'])==c+1 and len(report['opened'])==before
  # A same-origin frame does not receive the top document's private observer.
  q.js("let f=document.createElement('iframe');f.id='hostile-frame';f.srcdoc=`<button id=studyAiBtn onclick=\"window.open('https://chatgpt.com/','_blank','noopener,noreferrer')\">✨ Review with AI</button>`;f.style.cssText='position:fixed;left:10px;top:10px;width:300px;height:100px;z-index:99999';document.body.append(f);true")
  q.delay(.15)
  from PySide6.QtCore import QPoint,QEvent
  from PySide6.QtGui import QKeyEvent
  target=q.window.view.focusProxy();QTest.mouseClick(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(70,35));q.delay(.2)
  assert len(report['opened'])==before
  q.js("document.getElementById('hostile-frame').remove();document.getElementById('studyAiBtn').focus();true");q.delay(.05)
  q.app.sendEvent(target,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Return,Qt.KeyboardModifier.NoModifier,'',True,1));q.delay(.2)
  QTest.keyRelease(target,Qt.Key.Key_Return)
  assert len(report['opened'])==before,'Held/repeated key cannot repeatedly authorize a provider'
  q.js("for(let i=0;i<10;i++)setTimeout(()=>window.open('https://chatgpt.com/','_blank','noopener,noreferrer'),i*10);true");q.delay(.25)
  assert len(report['opened'])==before
  assert q.js("typeof globalThis.__dlmsAITake")=='undefined'
  report['checks'].append({'mode':q.window.mode,'script_timer_copy_only_generic_frame_repeat_flood_boundary':True})
 try:
  if a.reopen:
   record=json.loads((q.paths['root']/'parity-matrix-state.json').read_text())
   with sqlite3.connect(q.paths['backend']/'results.db') as c:
    assert c.execute('SELECT id,score,total FROM attempts ORDER BY id').fetchall()==[tuple(x) for x in record['attempts']]
   report['separate_process_exam_history_equal']=True
  else:
   for mode in ('local','server'):
    if mode=='server':
     cfg=dict(q.window.mode_config,server=configured_server(q.window.mode_config,a.server_origin,'Synthetic AI controls',private_http_opt_in=True));write_config(a.profile,cfg);q.window.mode_config=cfg
     assert q.window.switch_to_server();q.delay(.3)
    go('/')
    text='1. What is two plus two?\nA. Three\nB. Four\nCorrect Answer: B\n'
    q.js("""(async()=>{let f=new FormData();f.append('quiz_title','Parity AI Fixture');f.append('file',new File([TEXT],'fixture.txt'));window.seedStatus=(await fetch('/process',{method:'POST',body:f})).status})()""".replace('TEXT',json.dumps(text)));q.wait('window.seedStatus===200')
    go('/library');href=q.js("[...document.querySelectorAll('a[href^=\"/quizzes/\"]')].find(e=>e.closest('[data-quiz-id]')?.textContent.includes('Parity AI Fixture'))?.getAttribute('href')")
    assert href, q.js('document.body.innerText.slice(-1500)')
    go(href);q.wait("document.querySelector('.study-mode-btn')?.disabled===false");q.js("document.querySelector('.study-mode-btn').click();true");q.delay(.3)
    for key in (None,Qt.Key.Key_Return,Qt.Key.Key_Space):check('Study Review', '#studyAiBtn',key)
    negatives()
    # Existing answered Exam handler settles before History navigation.
    go(href);q.wait("document.querySelector('.exam-mode-btn')?.disabled===false");q.js("window.confirm=()=>true;document.querySelector('.exam-mode-btn').click();true")
    q.wait("!!document.getElementById('submitBtn')");q.js("document.getElementById('submitBtn').click();true")
    q.wait("pendingExamAttempt===null && examAttemptSaveInProgress===false && document.getElementById('result').textContent.includes('saved successfully')",30)
    go('/history');review=q.js("document.querySelector('a[href^=\"/review?\"]')?.getAttribute('href')");assert review
    go(review);q.wait("!!document.querySelector('.review-question-actions button[onclick^=openAIExplain]')")
    check('Explain individual','.review-question-actions button[onclick^=openAIExplain]')
    q.js("document.querySelector('.ai-select').checked=true;true")
    check('Explain selected','button[onclick="explainSelectedWithAI()"]',Qt.Key.Key_Return)
    for index,domain in enumerate(('IT / Cybersecurity','General','Science','Medical','History','Language','Other')):
     go('/study-packs/ai-builder')
     post('/study-packs/ai-builder',{'topic':'Synthetic neutral topic','domain':domain,'ai_provider':('chatgpt','claude','gemini')[index%3],'include_multiple_choice':'on'},"!!document.getElementById('studyPrompt')")
     check('Study Pack '+domain,'button[onclick^=copyAndOpen]')
    go('/law/create');post('/law/create',{'case_name':'Synthetic case','course':'General','ai_provider':'chatgpt','include_case_brief':'on'},"!!document.getElementById('lawPromptBox')")
    check('Law copy/open','button[onclick^=copyPromptAndOpenAi]',Qt.Key.Key_Space)
    go('/certifications/new')
    q.js("(()=>{let f=document.querySelector('form.cert-form');f.elements.field_name.value='AI Fixture';f.elements.field_issuer.value='Synthetic';f.elements.field_earned.value='2025-01-01';f.elements.field_expiration.value='2027-01-01';f.requestSubmit();return true})()")
    q.wait(r"/^\/certifications\/[a-f0-9]{32}$/.test(location.pathname)");cid=q.js("location.pathname.split('/').pop()")
    go('/certifications/matches');post('/certifications/matches',{'credentials':cid,'question':'Synthetic planning'},"!!document.getElementById('certPrompt')")
    check('Portfolio combined','[data-cert-launch]');check('Portfolio manual','#certProviderLink',Qt.Key.Key_Return,False)
    go('/certifications/'+cid+'/ai');post('/certifications/'+cid+'/ai',{'include_certification':'on','include_cycle':'on','question':'Synthetic planning'},"!!document.getElementById('certPrompt')")
    check('Single certification combined','[data-cert-launch]',Qt.Key.Key_Space);check('Single certification manual','#certProviderLink',None,False)
    report['checks'].append({'mode':mode,'exam_to_history_settled':True})
   assert q.window.switch_to_local();q.wait("location.pathname==='/' && document.readyState==='complete'")
   with sqlite3.connect(q.paths['backend']/'results.db') as c:attempts=c.execute('SELECT id,score,total FROM attempts ORDER BY id').fetchall()
   (q.paths['root']/'parity-matrix-state.json').write_text(json.dumps({'attempts':attempts})+'\n')
  report['pass']=True
 finally:
  if q.window.mode=='server':q.window.switch_to_local()
  shell.dispatch_external=old;QMessageBox.question=oldq
  (q.paths['root']/('parity-ai-reopen.json' if a.reopen else 'parity-ai-matrix.json')).write_text(json.dumps(report,indent=2)+'\n');q.close();print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
