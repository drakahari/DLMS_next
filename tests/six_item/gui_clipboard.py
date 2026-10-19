"""Focused source Qt clipboard/AI check using existing QtChecks.

App-local QTest input, synthetic Local data, final browser dispatch intercepted.
This is not a normal-package or physical-input pass. --server adds a task-owned
synthetic shared WSGI deployment; its results are separate from Local.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import os
import subprocess
import sys
import time
import traceback

from PySide6.QtCore import Qt, qVersion
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest

import desktop.shell as shell
from desktop.isolation import profile_paths
from tests.gate1.qt_checks import QtChecks


QUESTION_DATA = (
    ('What is two plus two?', 'B', 'B — Four', 'A — Three'),
    ('Which shape has three sides?', 'C', 'C — Triangle', 'A — Square'),
    ('Which word names a color?', 'D', 'D — Blue', 'A — Spoon'),
    ('Which item is a fruit?', 'B', 'B — Apple', 'A — Pencil'),
)
QUIZ_TEXT = '''1. What is two plus two?
A. Three
B. Four
C. Five
D. Six
Correct Answer: B

2. Which shape has three sides?
A. Square
B. Circle
C. Triangle
D. Rectangle
Correct Answer: C

3. Which word names a color?
A. Spoon
B. Table
C. Chair
D. Blue
Correct Answer: D

4. Which item is a fruit?
A. Pencil
B. Apple
C. Chair
D. Stone
Correct Answer: B
'''

OBSERVE = r'''(() => {
  window.clipboardProbe = {copies:[], exec:[], alerts:[], asyncWrites:[]};
  const snapshot = () => {
    const t=document.activeElement;
    return {tag:t?.tagName, id:t?.id, value:t?.value ?? null,
      start:t?.selectionStart ?? null,end:t?.selectionEnd ?? null,
      selection:getSelection().toString(),focus:document.hasFocus(),
      style:t?{display:getComputedStyle(t).display,
        visibility:getComputedStyle(t).visibility,userSelect:getComputedStyle(t).userSelect}:null};
  };
  document.addEventListener('copy', e => {
    clipboardProbe.copies.push({...snapshot(),defaultPrevented:e.defaultPrevented});
  });
  window.clipboardProbeOriginalExec=document.execCommand;
  document.execCommand=function(...args) {
    const before=snapshot();
    try {const result=clipboardProbeOriginalExec.apply(this,args);
      clipboardProbe.exec.push({command:args[0],before,result});return result;}
    catch(error){clipboardProbe.exec.push({command:args[0],before,error:String(error)});throw error;}
  };
  if(navigator.clipboard?.writeText) {
    const clipboard=navigator.clipboard,original=clipboard.writeText.bind(clipboard);
    clipboard.writeText=async text=>{
      const item={text,focus:document.hasFocus(),state:'pending'};
      clipboardProbe.asyncWrites.push(item);
      try {await original(text);item.state='resolved';}
      catch(error){item.state='rejected';item.error=String(error);throw error;}
    };
  }
  window.alert=message=>clipboardProbe.alerts.push(String(message));
  return true;
})()'''


def text_record(text):
    data = text.encode('utf-8')
    return {'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest(),
            'crlf':text.count('\r\n'), 'lf':text.count('\n')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--server', action='store_true', help='Start a fresh task-owned real shared WSGI server')
    args = parser.parse_args()
    if not args.profile.startswith('sixclip'):
        raise ValueError('Use a new synthetic sixclip-prefixed profile')
    if profile_paths(args.profile,create=False)['root'].exists():
        raise ValueError('Synthetic clipboard profile already exists; choose a fresh name')
    args.output = args.output.absolute()
    args.output.mkdir(parents=True, exist_ok=False)
    # Match existing source Qt drivers for deep worktree Unix socket paths.
    original_socket = shell.instance_socket_name
    shell.instance_socket_name = lambda root: '/tmp/dlms-sixclip-' + hashlib.sha256(str(root).encode()).hexdigest()[:18] + '.sock'
    original_dispatch = shell.dispatch_external
    dispatches = []
    shell.dispatch_external = lambda url: dispatches.append(url.toString()) or True
    report = {'layer':'source Qt, existing QtChecks, app-local QTest input',
              'scope':'synthetic Local only; final external dispatch intercepted',
              'dispatches':dispatches, 'actions':[], 'pass':False}
    source_root=Path(__file__).resolve().parents[2]
    report['inputs']={name:hashlib.sha256((source_root/name).read_bytes()).hexdigest()
        for name in ('static/review.html','desktop/ai_actions.py','desktop/shell.py',
                     'app.py','dlms/rendering/quiz_artifacts.py')}
    report['runtime']={'python':sys.version.split()[0], 'qt':qVersion()}
    q = None
    server = server_log = None
    backend = None
    try:
        q = QtChecks(args.profile, automated=True)
        local_db = q.paths['backend']/'results.db'
        with sqlite3.connect(local_db) as db:
            local_before='\n'.join(db.iterdump())
        backend = q.paths['backend']
        if args.server:
            backend = args.output/'server-data'
            port_file = args.output/'server-port'
            env = {key:value for key,value in os.environ.items() if not key.startswith(('DLMS_', 'QUIZAPP_'))}
            env.update(QUIZAPP_DATA_DIR=str(backend), DLMS_NO_BROWSER='1')
            server_log = (args.output/'server.log').open('w')
            code = ('from pathlib import Path; import app; from werkzeug.serving import make_server; '
                    "s=make_server('127.0.0.2',0,app.app,threaded=True); "
                    f'Path({str(port_file)!r}).write_text(str(s.server_port)); s.serve_forever()')
            server = subprocess.Popen([sys.executable, '-c', code], env=env,
                cwd=Path(__file__).resolve().parents[2], stdout=server_log, stderr=subprocess.STDOUT,
                start_new_session=True)
            deadline=time.monotonic()+20
            while not port_file.exists() and time.monotonic()<deadline:
                if server.poll() is not None:raise RuntimeError('Synthetic WSGI server stopped at startup')
                q.delay(.05)
            if not port_file.exists():raise TimeoutError('Synthetic WSGI server startup')
            origin='http://127.0.0.2:'+port_file.read_text()
            from desktop.server_mode import configured_server, write_config
            config=dict(q.window.mode_config)
            config['server']=configured_server(config,origin,'Six item synthetic',private_http_opt_in=True)
            write_config(args.profile,config);q.window.mode_config=config
            assert q.window.switch_to_server()
            q.wait("location.origin==="+json.dumps(origin)+" && document.readyState==='complete'",30)
            report.update(scope='synthetic Server/source Qt; final external dispatch intercepted',origin=origin)
        q.js('''(async()=>{const f=new FormData();f.append('quiz_title','Six item clipboard synthetic');
          f.append('file',new File([TEXT],'six-clipboard.txt'));
          window.clipboardSeed=(await fetch('/process',{method:'POST',body:f})).status;})()'''.replace('TEXT',json.dumps(QUIZ_TEXT)))
        q.wait('window.clipboardSeed===200')
        with sqlite3.connect(backend/'results.db') as db:
            db.row_factory=sqlite3.Row
            rows=db.execute('SELECT id,quiz_id,question_number,question_text FROM questions ORDER BY question_number').fetchall()
            assert len(rows)==4, [dict(row) for row in rows]
            assert [row['question_text'] for row in rows]==[item[0] for item in QUESTION_DATA]
            db.execute("INSERT INTO attempts(id,quiz_id,user_name,score,total,percent,mode) VALUES(?,?,'Synthetic Clipboard',0,4,0,'Exam')",
                       ('six-clipboard-attempt',rows[0]['quiz_id']))
            for n,(row,item) in enumerate(zip(rows,QUESTION_DATA),1):
                db.execute('''INSERT INTO missed_questions(attempt_id,question_id,attempt_question_number,
                    question_text,choices_text,correct_letters,correct_text,selected_letters,selected_text,question_type)
                    VALUES(?,?,?,?,?,?,?,?,?,'choice')''',
                    ('six-clipboard-attempt',row['id'],n,item[0],'A. Wrong\nB. Option\nC. Option\nD. Option',item[1],item[2],'A',item[3]))
            db.commit()
            before_db='\n'.join(db.iterdump())
        if args.server:
            q.window.view.setUrl(QUrl(origin+'/review?attempt=six-clipboard-attempt'))
        else:
            q.go('/review?attempt=six-clipboard-attempt')
        q.wait("missedCache.length===4 && aiConfig!==null && document.querySelectorAll('.ai-select').length===4")
        if args.server:
            deadline=time.monotonic()+15
            while not q.window._server_page_exposed and time.monotonic()<deadline:q.delay(.05)
            if not q.window._server_page_exposed:raise TimeoutError('Server view was not exposed for input')
        # Deterministic page-fixture settings, not a user config/profile edit.
        # CRLF is intentional: textarea/execCommand normalizes it to LF.
        q.js("aiConfig={...aiConfig,ai_helper_enabled:true,ai_auto_copy_prompt:true,ai_provider:'chatgpt',ai_prompt_template:getDefaultAIPromptTemplate().replace(/\\n/g,'\\r\\n')};true")
        q.click_css('.ai-select[data-index="1"]')
        q.click_css('.ai-select[data-index="3"]')
        q.js(OBSERVE)
        selector='button[onclick="explainSelectedWithAI()"]'
        selected=lambda:json.loads(q.js("JSON.stringify([...document.querySelectorAll('.ai-select:checked')].map(e=>Number(e.dataset.index)))"))
        expected=q.js('applyPromptTemplate(buildQuestionBlock([missedCache[1],missedCache[3]]))')
        single=q.js('buildPrompt(1)')
        assert selected()==[1,3]
        assert all(QUESTION_DATA[i][0] in expected for i in (1,3))
        assert all(QUESTION_DATA[i][0] not in expected for i in (0,2))
        report['expected_combined']=text_record(expected)
        report['expected_single']=text_record(single)
        clipboard=q.app.clipboard()

        def wait_python(condition,timeout=8):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if condition():return
                q.delay(.05)
            raise TimeoutError('Source Qt clipboard/handoff condition timed out')

        def action(kind,button=selector):
            if kind=='pointer':q.click_css(button)
            else:
                q.js('document.querySelector('+json.dumps(button)+').scrollIntoView({block:"center"});document.querySelector('+json.dumps(button)+').focus();true')
                q.delay(.1)
                target=q.window.view.focusProxy() or q.window.view
                QTest.keyClick(target,Qt.Key.Key_Return if kind=='enter' else Qt.Key.Key_Space)

        def record(name,expected_text=None):
            actual=clipboard.text()
            state=json.loads(q.js('JSON.stringify({probe:clipboardProbe,active:document.activeElement?.id,focus:document.hasFocus(),statuses:[...document.querySelectorAll("[role=status]")].map(e=>e.textContent),body:document.body.innerText})'))
            entry={'name':name,'clipboard':text_record(actual),
                   'exact_expected':actual==expected_text if expected_text is not None else None,
                   'dispatch_count':len(dispatches),'selected':selected(),'state':state}
            report['actions'].append(entry)
            return entry

        # No personal clipboard read: each read follows our synthetic sentinel
        # or the deliberate action in this source-only synthetic session.
        clipboard.setText('six-item-single-sentinel')
        action('pointer','button[onclick="copyAIExplainPrompt(1, this)"]')
        wait_python(lambda:clipboard.text()==single)
        record('single-pointer',single)
        assert not dispatches
        for kind in ('pointer','enter','space'):
            before=len(dispatches)
            clipboard.setText('six-item-'+kind+'-sentinel')
            action(kind)
            wait_python(lambda:len(dispatches)>before)
            q.delay(.15)
            entry=record('combined-'+kind,expected)
            assert len(dispatches)==before+1 and dispatches[-1]=='https://chatgpt.com/'
            assert entry['exact_expected'],entry
            assert entry['selected']==[1,3]

        # Same page handler without a new trusted input must not dispatch.
        before=len(dispatches)
        q.js('explainSelectedWithAI();true')
        q.delay(.7)
        record('scripted-dispatch-refused')
        assert len(dispatches)==before

        # Force both document copy APIs to deny; native AI policy stays intact.
        # Observe truthful feedback without assuming a specific UI wording.
        q.js("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('Synthetic clipboard denial')}}});document.execCommand=()=>false;clipboardProbe.alerts=[];true")
        sentinel='six-item-denial-sentinel'
        clipboard.setText(sentinel)
        action('pointer')
        q.delay(.7)
        denied=record('denial')
        assert clipboard.text()==sentinel
        feedback=' '.join(denied['state']['probe']['alerts']+denied['state']['statuses'])
        report['denial_feedback']=feedback
        assert feedback and any(word in feedback.lower() for word in ('could not','failed','unable','not copied','unavailable','manually')),feedback
        with sqlite3.connect(backend/'results.db') as db:
            report['database_unchanged']='\n'.join(db.iterdump())==before_db
        assert report['database_unchanged']
        if args.server:
            assert q.window.switch_to_local()
            q.wait("location.pathname==='/' && document.readyState==='complete'",30)
            with sqlite3.connect(local_db) as db:
                report['local_data_unchanged']='\n'.join(db.iterdump())==local_before
            assert report['local_data_unchanged']
        q.screenshot(str(args.output/'review.png'))
        report['pass']=True
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
        report['traceback']=traceback.format_exc()
        if q is not None and q.window.view is not None:
            report['failure_probe']=q.js('JSON.stringify({probe:window.clipboardProbe,focus:document.hasFocus(),statuses:[...document.querySelectorAll("[role=status]")].map(e=>e.textContent)})')
            report['failure_clipboard']=text_record(q.app.clipboard().text())
            report['view_exposed']=getattr(q.window,'_server_page_exposed',None)
        raise
    finally:
        if q is not None:q.close()
        if server is not None:
            server.terminate();server.wait(timeout=10)
        if server_log is not None:server_log.close()
        shell.dispatch_external=original_dispatch
        shell.instance_socket_name=original_socket
        (args.output/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    main()
