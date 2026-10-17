"""Owned Qt input + real captured Study action, final browser process intercepted."""
import argparse,json,time
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from tests.gate1.qt_checks import QtChecks

def main():
 p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
 if not a.profile.startswith('parityai'):raise ValueError('Synthetic profile required')
 q=QtChecks(a.profile,automated=True);result={'calls':[],'confirmations':[]}
 import desktop.shell as shell
 old=shell.dispatch_external;oldq=QMessageBox.question
 shell.dispatch_external=lambda url:result['calls'].append(url.toString()) or True
 QMessageBox.question=lambda *args,**kw:result['confirmations'].append(args[2]) or QMessageBox.StandardButton.No
 try:
  text=(Path(__file__).resolve().parents[2]/'fixtures/gate1-neutral-quiz.txt').read_text()
  q.js("""(async()=>{let f=new FormData();f.append('quiz_title','Parity AI Quiz');f.append('file',new File([TEXT],'ai.txt'));window.imported=(await fetch('/process',{method:'POST',body:f})).status;})()""".replace('TEXT',json.dumps(text)))
  q.wait('window.imported===200');registry=json.loads((q.paths['backend']/'config/quizzes.json').read_text());entry=next(x for x in registry if x['title']=='Parity AI Quiz')
  q.go('/quizzes/'+entry['html']);q.wait("document.querySelector('.study-mode-btn')?.disabled===false");q.js("document.querySelector('.study-mode-btn').click();true");q.delay(.5)
  page=q.window.view.page();result['markup']=q.js("document.getElementById('studyAiBtn').outerHTML")
  result['initial_private']=q.js("typeof globalThis.__dlmsAITake")
  # Keep the original clipboard handler and copy flow. Browser is intercepted.
  q.click_css('#studyAiBtn');q.delay(.5)
  result['native_epoch']=page.ai_handoff.epoch;result['used']=page.ai_handoff.used
  result['private_state']=q.window._evaluate_browser('JSON.stringify({href:location.href})',500)
  assert result['calls']==['https://chatgpt.com/'],result
  assert not result['confirmations'],result
  q.js("document.getElementById('studyAiBtn').click();true");q.delay(.3)
  assert len(result['calls'])==1,result
  button=q.window.view.focusProxy();q.js("document.getElementById('studyAiBtn').focus();true")
  QTest.keyClick(button,Qt.Key.Key_Return);q.delay(.5)
  assert len(result['calls'])==2,result
  q.js("setTimeout(()=>window.open('https://chatgpt.com/','_blank','noopener,noreferrer'),100);true");q.delay(.4)
  assert len(result['calls'])==2,result
  result['pass']=True
 finally:
  shell.dispatch_external=old;QMessageBox.question=oldq
  (q.paths['root']/'ai-result.json').write_text(json.dumps(result,indent=2)+'\n');q.close();print(json.dumps(result,indent=2),flush=True)
if __name__=='__main__':main()
