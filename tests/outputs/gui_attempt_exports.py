"""App-local source Qt checks; chooser answers are simulated, not native UAT."""
import argparse,hashlib,json,os,socket,sqlite3,subprocess,sys,time,zipfile
from pathlib import Path
from PySide6.QtCore import QUrl,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog,QMessageBox
import desktop.shell as shell
shell.instance_socket_name=lambda root:'/tmp/dlms-f5-'+hashlib.sha256(str(root).encode()).hexdigest()[:18]+'.sock'
from tests.gate1.qt_checks import QtChecks
from desktop.server_mode import configured_server,write_config


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    q=QtChecks(a.profile,automated=True);answers=[];prompts=[];results=[];server=None
    old=QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName=lambda *args,**kwargs:(prompts.append('Save As') or (str(answers.pop(0)) if answers else '', ''))
    from PySide6.QtCore import QTimer
    timer=QTimer();timer.setInterval(30)
    def dismiss():
        for w in q.app.topLevelWidgets():
            if isinstance(w,QMessageBox) and w.isVisible():prompts.append(w.text());w.reject()
    timer.timeout.connect(dismiss);timer.start()
    def wait(f):
        end=time.monotonic()+20
        while time.monotonic()<end and not f():q.delay(.05)
        assert f(),q.window.statusBar().currentMessage()
    def go(path):
        origin=f'http://127.0.0.1:{q.window.port}' if q.window.mode=='local' else q.window.mode_config['server']['origin']
        q.window.view.setUrl(QUrl(origin+path));q.wait('location.pathname==='+json.dumps(path.split('?')[0])+"&&document.readyState==='complete'");q.delay(.2)
    def package(path):
        with zipfile.ZipFile(path) as z:assert z.testzip() is None;raw=z.read('collection.anki2')
        c=sqlite3.connect(':memory:');c.deserialize(raw);fields=[r[0] for r in c.execute('select flds from notes')];c.close()
        assert len(fields)==1 and 'question two?' in fields[0].lower() and 'question one?' not in fields[0].lower(),fields
        return hashlib.sha256(path.read_bytes()).hexdigest()
    def export(selector,name,state,script=False):
        before=len(q.window.download_results);count=len(prompts)
        answers.append(str(a.output/name) if name else '')
        if script:q.js('document.querySelector('+json.dumps(selector)+').click();true')
        else:q.click_css(selector)
        wait(lambda:len(q.window.download_results)>before and q.window.download_results[-1]['state']!='in_progress')
        record=q.window.download_results[-1];assert record['state']==state,(state,record)
        if state=='refused':assert len(prompts)==count;answers.pop()
        else:
            text={'completed':'saved to the selected folder','cancelled':'Save As canceled','failed':'not saved'}[state]
            q.wait('document.getElementById("attemptExportStatus").textContent.includes('+json.dumps(text)+')')
        digest=package(Path(record['published_path'])) if state=='completed' else None
        results.append({'mode':q.window.mode,'state':state,'sha256':digest,'status':q.window.statusBar().currentMessage()})
    def run_attempt(attempt):
        go('/review?attempt='+attempt);q.wait("document.querySelectorAll('.anki-select').length===2")
        q.click_css('.anki-select[data-qnum="2"]')
        prefix=q.window.mode
        export('#exportAttemptMissed',prefix+'-initial.apkg','completed')
        export('#attemptExportResult a',prefix+'-fallback.apkg','completed')
        export('#exportAttemptMissed',prefix+'-repeated.apkg','completed')
        export('#attemptExportResult a',None,'cancelled')
        path=a.output/(prefix+'-initial.apkg');digest=hashlib.sha256(path.read_bytes()).hexdigest()
        export('#attemptExportResult a',path.name,'failed');assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
        export('#attemptExportResult a',None,'refused',script=True)
        export('#exportAttemptMissed',None,'refused',script=True)
        href=q.js('document.querySelector("#attemptExportResult a").href');name=q.js('document.querySelector("#attemptExportResult a").download')
        content='<a style="display:block;width:100%;height:120px" download="'+name+'" href="'+href+'">Frame export</a>'
        q.js('(()=>{let f=document.createElement("iframe");f.id="untrustedExportFrame";f.style="width:600px;height:120px";f.srcdoc='+json.dumps(content)+';document.body.append(f);return true;})()');q.delay(.3)
        export('#untrustedExportFrame',None,'refused');q.screenshot(str(a.output/(prefix+'-attempt.png')))
    def bundle():
        go('/quiz-bundles');q.window.resize(711,850);q.delay(.3);q.wait("document.querySelector('input[name=quiz_ids]')!==null")
        q.click_css('input[name=quiz_ids]');selected=q.js("JSON.stringify([...document.querySelectorAll('input[name=quiz_ids]:checked')].map(e=>e.value))")
        assert json.loads(selected), 'Fixture must have an actual selected quiz ID'
        q.click_css('#menuButton');q.wait("document.getElementById('menuButton').getAttribute('aria-expanded')==='true'")
        target=q.window.view.focusProxy() or q.window.view;QTest.keyClick(target,Qt.Key.Key_Escape);q.delay(.2)
        q.wait("document.getElementById('menuButton').getAttribute('aria-expanded')==='false'")
        q.js("document.getElementById('menuButton').focus();true")
        target=q.window.view.focusProxy() or q.window.view;QTest.keyClick(target,Qt.Key.Key_Space);q.delay(.2)
        q.wait("document.getElementById('menuButton').getAttribute('aria-expanded')==='true'")
        QTest.keyClick(target,Qt.Key.Key_Escape);q.delay(.2)
        q.wait("document.getElementById('menuButton').getAttribute('aria-expanded')==='false'")
        assert q.js('document.activeElement.id')=='menuButton'
        assert q.js("JSON.stringify([...document.querySelectorAll('input[name=quiz_ids]:checked')].map(e=>e.value))")==selected
        q.screenshot(str(a.output/(q.window.mode+'-bundles.png')),width=711);q.window.resize(1280,850)
    try:
        q.js("""(async()=>{let f=new FormData();f.append('quiz_title','Synthetic attempt output');f.append('file',new File(['1. Question one?\\nA. Correct\\nB. Other\\nCorrect Answer: A\\n2. Question two?\\nA. Correct\\nB. Other\\nCorrect Answer: A\\n'],'synthetic.txt'));window.seed=(await fetch('/process',{method:'POST',body:f})).status;})()""");q.wait('window.seed===200')
        db=sqlite3.connect(q.paths['backend']/'results.db');db.row_factory=sqlite3.Row
        questions=db.execute('select id,quiz_id,question_text from questions order by id').fetchall()
        for attempt in ('f5-selected-attempt','f5-unrelated-attempt'):
            db.execute("insert into attempts(id,quiz_id,score,total,percent,mode) values(?,?,0,2,0,'Exam')",(attempt,questions[0]['quiz_id']))
            for n,row in enumerate(questions,1):db.execute('insert into missed_questions(attempt_id,question_id,attempt_question_number,question_text,choices_text,correct_text,correct_letters) values(?,?,?,?,?,?,?)',(attempt,row['id'],n,row['question_text'],'A. Correct\nB. Other','A. Correct','A'))
        db.commit();before='\n'.join(db.iterdump());db.close()
        run_attempt('f5-selected-attempt');bundle()
        db=sqlite3.connect(q.paths['backend']/'results.db');assert '\n'.join(db.iterdump())==before;db.close()
        serverroot=a.output/'server';serverroot.mkdir()
        with socket.socket() as sock:sock.bind(('127.0.0.2',0));port=sock.getsockname()[1]
        env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_'))};env.update(QUIZAPP_DATA_DIR=str(serverroot/'data'),DLMS_NO_BROWSER='1',DLMS_BROWSER_TEST_BIND_HOST='127.0.0.2',DLMS_BROWSER_TEST_PORT=str(port),PYTHONDONTWRITEBYTECODE='1')
        log=(serverroot/'server.log').open('w');server=subprocess.Popen([sys.executable,'tests/browser/_server.py'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        wait(lambda:(serverroot/'data/browser_fixture.json').exists())
        cfg=dict(q.window.mode_config,server=configured_server(q.window.mode_config,f'http://127.0.0.2:{port}','Synthetic F5 server',private_http_opt_in=True));write_config(a.profile,cfg);q.window.mode_config=cfg;assert q.window.switch_to_server();q.delay(.3)
        db=sqlite3.connect(serverroot/'data/results.db');server_before='\n'.join(db.iterdump());db.close()
        run_attempt('browser-anki-missed-attempt');bundle()
        db=sqlite3.connect(serverroot/'data/results.db');assert '\n'.join(db.iterdump())==server_before;db.close()
        assert q.window.switch_to_local()
        (a.output/'RESULT.json').write_text(json.dumps({'kind':'source Qt app-local input, simulated native chooser answers','downloads':results,'unchanged_local_database':True,'bundle_local_server':True},indent=2)+'\n')
    finally:
        timer.stop();QFileDialog.getSaveFileName=old
        if q.window.mode=='server':q.window.switch_to_local();q.delay(.2)
        q.close()
        if server is not None:server.terminate();server.wait(timeout=15)
if __name__=='__main__':main()
