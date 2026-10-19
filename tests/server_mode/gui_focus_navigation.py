"""Focused source-Qt keyboard/readiness acceptance with task-owned WSGI only.

App-local QTest input, unchanged real ServerPage/AIHandoff, final browser adapter
intercepted. Does not qualify physical Finder focus or another platform.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import traceback
from PySide6.QtCore import Qt, qVersion
from PySide6.QtTest import QTest
import desktop.shell as shell
from desktop.server_mode import configured_server, write_config
from tests.gate1.qt_checks import QtChecks
from tests.six_item.gui_clipboard import QUIZ_TEXT, QUESTION_DATA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not args.profile.startswith('sixfocus'): raise ValueError('Fresh synthetic sixfocus profile required')
    from desktop.isolation import profile_paths
    if profile_paths(args.profile, create=False)['root'].exists(): raise FileExistsError('Preserve existing profiles')
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    report = {'kind':'source Qt / app-local QTest, not physical owner input', 'qt':qVersion(),
              'checks':{}, 'pass':False, 'external_provider_contact':False}
    original_dispatch, original_socket = shell.dispatch_external, shell.instance_socket_name
    dispatches = []
    shell.dispatch_external = lambda url: dispatches.append(url.toString()) or True
    shell.instance_socket_name = lambda p: '/tmp/dlms-focus-' + hashlib.sha256(str(p).encode()).hexdigest()[:18] + '.sock'
    q = process = log = None
    server_root = args.output/'server-data'; port_file = args.output/'server-port'

    def start_server(port=0):
        nonlocal process, log
        env = {k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_'))}
        env.update(QUIZAPP_DATA_DIR=str(server_root), DLMS_NO_BROWSER='1', PYTHONDONTWRITEBYTECODE='1')
        log = (args.output/('server-'+str(time.time_ns())+'.log')).open('x')
        code = ('from pathlib import Path; import app; from werkzeug.serving import make_server; '
                f"s=make_server('127.0.0.1',{port},app.app,threaded=True); "
                f'Path({str(port_file)!r}).write_text(str(s.server_port));s.serve_forever()')
        process = subprocess.Popen([sys.executable,'-B','-c',code], cwd=root,env=env,
                                   stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if process.poll() is not None: raise RuntimeError('Task WSGI exited')
            if port_file.exists():
                import socket
                try:
                    with socket.create_connection(('127.0.0.1',int(port_file.read_text())),timeout=.2): return
                except OSError: pass
            if q is None: time.sleep(.05)
            else: q.delay(.05)
        raise TimeoutError('Task WSGI startup')

    def stop_server():
        nonlocal process,log
        if process is not None:
            process.terminate();process.wait(timeout=10);process=None
        if log is not None:log.close();log=None

    def key(key):
        target=q.app.focusWidget() or q.window.view.focusProxy() or q.window.view
        QTest.keyClick(target,key);q.delay(.09)

    def tab_to(expression, limit=45):
        for _ in range(limit):
            if q.js(expression): return
            key(Qt.Key.Key_Tab)
        raise AssertionError('Native Tab did not reach intended page control')

    def ready():
        deadline=time.monotonic()+20
        while not q.window._server_page_exposed and time.monotonic()<deadline:q.delay(.05)
        assert q.window._server_page_exposed and q.window.view.isEnabled()
        assert q.window.view.focusPolicy()==Qt.FocusPolicy.StrongFocus
        assert q.window.view.focusProxy().focusPolicy()==Qt.FocusPolicy.StrongFocus

    try:
        start_server();origin='http://127.0.0.1:'+port_file.read_text();report['origin']=origin
        q=QtChecks(args.profile,automated=True)
        local_pid=q.window.backend.pid
        config=dict(q.window.mode_config)
        config['server']=configured_server(config,origin,'Focus synthetic ONLY',private_http_opt_in=True)
        write_config(args.profile,config);q.window.mode_config=config
        assert q.window.switch_to_server()
        q.wait('location.origin==='+json.dumps(origin)+" && document.readyState==='complete'");ready()
        report['checks']['local_to_server_ready']={'status':'passed','interactive_proxy':True,'old_local_backend_stopped':q.window.backend is None or q.window.backend.poll() is not None}
        q.js('''(async()=>{const f=new FormData();f.append('quiz_title','Focus selected synthetic');f.append('file',new File([TEXT],'focus.txt'));window.seed=(await fetch('/process',{method:'POST',body:f})).status;})()'''.replace('TEXT',json.dumps(QUIZ_TEXT)))
        q.wait('window.seed===200')
        db=server_root/'results.db'
        with sqlite3.connect(db) as cn:
            rows=cn.execute('SELECT id,quiz_id FROM questions ORDER BY question_number').fetchall();assert len(rows)==4
            cn.execute("INSERT INTO attempts(id,quiz_id,user_name,score,total,percent,mode) VALUES('focus-attempt',?,'Synthetic Focus',0,4,0,'Exam')",(rows[0][1],))
            for n,(row,item) in enumerate(zip(rows,QUESTION_DATA),1):
                cn.execute('''INSERT INTO missed_questions(attempt_id,question_id,attempt_question_number,question_text,choices_text,correct_letters,correct_text,selected_letters,selected_text,question_type) VALUES('focus-attempt',?,?,?,?,?,?,?,?,'choice')''',(row[0],n,item[0],'A. Wrong\nB. Option\nC. Option\nD. Option',item[1],item[2],'A',item[3]))
            cn.commit();before='\n'.join(cn.iterdump())
        # Reach the real shared sidebar link via actual Tab, then native Enter.
        q.window.view.setUrl(shell.QUrl(origin+'/library'))
        q.wait("location.pathname==='/library' && document.readyState==='complete'");ready()
        q.click_css('.dashboard-brand-title')
        tab_to("document.activeElement?.getAttribute('href')==='/marked-questions'")
        assert q.js('document.activeElement.matches(":focus-visible")')
        key(Qt.Key.Key_Return);q.wait("location.pathname==='/marked-questions' && document.readyState==='complete'");ready()
        assert q.js("document.querySelector('#dashboardSidebar a[href=\"/marked-questions\"]').getAttribute('aria-current')")=='page'
        report['checks']['marked_link_native_tab_enter']={'status':'passed','focus_visible':True,'current_navigation':True}
        q.window.view.setUrl(shell.QUrl(origin+'/review?attempt=focus-attempt'))
        q.wait("typeof missedCache!=='undefined' && missedCache.length===4 && aiConfig!==null");ready()
        q.js("aiConfig={...aiConfig,ai_helper_enabled:true,ai_auto_copy_prompt:true,ai_provider:'chatgpt',ai_prompt_template:getDefaultAIPromptTemplate().replace(/\\n/g,'\\r\\n')};true")
        q.click_css('.ai-select[data-index="1"]');q.click_css('.ai-select[data-index="3"]')
        expected=q.js('applyPromptTemplate(buildQuestionBlock([missedCache[1],missedCache[3]]))')
        assert all(QUESTION_DATA[i][0] in expected for i in (1,3)) and all(QUESTION_DATA[i][0] not in expected for i in (0,2))
        tab_to("document.activeElement?.getAttribute('onclick')==='explainSelectedWithAI()'",20)
        clipboard=q.app.clipboard();clipboard.setText('synthetic-focus-sentinel')
        key(Qt.Key.Key_Return)
        deadline=time.monotonic()+5
        while not dispatches and time.monotonic()<deadline:q.delay(.05)
        assert dispatches==['https://chatgpt.com/'],dispatches
        assert clipboard.text()==expected
        assert json.loads(q.js('JSON.stringify([...document.querySelectorAll(".ai-select:checked")].map(e=>Number(e.dataset.index)))'))==[1,3]
        report['checks']['selected_ai_native_tab_enter']={'status':'passed','exact_clipboard_bytes':len(expected.encode()),'sha256':hashlib.sha256(expected.encode()).hexdigest(),'selected':[2,4],'dispatches':1,'final_adapter_intercepted':True}
        q.js('explainSelectedWithAI();true');q.delay(.4);assert len(dispatches)==1
        report['checks']['scripted_ai_dispatch_refused']={'status':'passed'}
        with sqlite3.connect(db) as cn:assert '\n'.join(cn.iterdump())==before
        # Real outage/retry: do not expose or restore keyboard on failed origin.
        port=int(port_file.read_text());stop_server();q.window._retry_server()
        deadline=time.monotonic()+15
        while not q.window.server_unreachable and time.monotonic()<deadline:q.delay(.05)
        assert q.window.server_unreachable and not q.window._server_page_exposed
        assert not q.window.view.isEnabled() and q.window.view.focusPolicy()==Qt.FocusPolicy.NoFocus
        report['checks']['outage_keeps_keyboard_blocked']={'status':'passed'}
        start_server(port);q.window._retry_server()
        q.wait('location.origin==='+json.dumps(origin)+" && document.readyState==='complete'");ready()
        q.click_css('.dashboard-brand-title');key(Qt.Key.Key_Tab)
        assert q.js('document.activeElement.tagName')=='A'
        report['checks']['retry_restores_page_tab']={'status':'passed'}
        assert q.window.switch_to_local();q.wait("location.pathname==='/' && document.readyState==='complete'")
        assert q.window.backend.pid!=local_pid
        q.click_css('.dashboard-brand-title');key(Qt.Key.Key_Tab);assert q.js('document.activeElement.tagName')=='A'
        report['checks']['return_local_tab']={'status':'passed'}
        assert q.window.switch_to_server();q.wait('location.origin==='+json.dumps(origin)+" && document.readyState==='complete'");ready()
        report['checks']['second_server_transition']={'status':'passed'}
        report['pass']=True
    except Exception as error:
        report['error']=str(error);report['traceback']=traceback.format_exc();raise
    finally:
        if q is not None:q.close()
        stop_server();shell.dispatch_external=original_dispatch;shell.instance_socket_name=original_socket
        (args.output/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__': main()
