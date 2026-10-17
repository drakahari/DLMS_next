"""Normal frozen response/download probe; no app hooks or host input.

The Server fixture page drives its own DOM. This is not physical acceptance.
Local exports use authenticated HTTP, explicitly separate from native clicking.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import time
import uuid

from tests.windows.normal_candidate import ROOT, request, multipart
from tests.windows.normal_processes import backend_nonce, descendants, identity, alive


def wait_for(predicate, seconds=45):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.1)
    raise TimeoutError('Normal export probe checkpoint')


def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--expect-server-visible',action='store_true');a=p.parse_args()
    exe=a.exe.resolve(strict=True);out=a.output.absolute()
    if out.exists() or not out.is_relative_to(ROOT/'.gate1/windows-native'):
        raise ValueError('Fresh project-local evidence required')
    out.mkdir(mode=0o700)
    result={'exe':str(exe),'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
            'normal_package':True,'physical_input':False,'settings_changed':False}
    env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','PYTHON','QTWEBENGINE_'))}
    env.update(QT_LOGGING_RULES='qt.webenginecontext.debug=true',QT_FORCE_STDERR_LOGGING='1')
    processes=[];logs=[];owned={}
    def launch(command,environment,name):
        log=(out/name).open('w');logs.append(log)
        proc=subprocess.Popen(command,env=environment,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        processes.append(proc);owned[proc.pid]=identity(proc.pid)['start'];return proc
    try:
        for mode in ('local','server'):
            data=out/f'{mode} Synthetic data 日本語';data.mkdir(mode=0o700)
            (data/'.dlms-desktop-windows-candidate.json').write_text(json.dumps({'kind':'dlms-desktop-windows-candidate','version':1}))
            profile='export01';state=data/'profiles'/profile
            if mode=='server':
                server_env=env|{'QUIZAPP_DATA_DIR':str(out/'server-data'),'DLMS_NO_BROWSER':'1',
                    'DLMS_EXPORT_EVIDENCE':str(out),'HOME':str(out/'server-home'),
                    'TMP':str(out/'server-tmp'),'TEMP':str(out/'server-tmp')}
                for folder in ('server-home','server-tmp'):(out/folder).mkdir(mode=0o700)
                server=launch([str(Path(os.sys.executable)),'-m','tests.windows.text_export_server'],server_env,'server.log')
                wait_for(lambda:(out/'port').exists())
                origin='http://127.0.0.2:'+(out/'port').read_text()
                shell=data/'shell'/profile;shell.mkdir(mode=0o700,parents=True)
                config={'version':1,'profile':profile,'mode':'server','server':{
                    'id':str(uuid.uuid4()),'label':'Synthetic export fixture','origin':origin,'private_http':True}}
                (shell/'mode.json').write_text(json.dumps(config))
            proc=launch([str(exe),'--data-root',str(data),'--profile',profile,'--capture-window-events'],env,f'{mode}-launcher.log')
            if mode=='local':
                def ready():
                    if proc.poll() is not None:raise RuntimeError('Normal launcher exited')
                    owner=backend_nonce(proc.pid,exe)
                    manifest=state/'desktop-profile.json'
                    return (owner,json.loads(manifest.read_text())['port']) if owner and manifest.exists() else None
                owner,port=wait_for(ready);nonce=owner[1]
                wait_for(lambda:request(port,nonce,'GET','/_desktop/ready',headers={'X-DLMS-Desktop-Nonce':nonce})[0]==200)
                headers={'Origin':f'http://127.0.0.1:{port}','Sec-Fetch-Site':'same-origin','X-DLMS-CSRF-Refresh':'1'}
                status,body,response=request(port,nonce,'GET','/api/csrf-token',headers=headers)
                csrf=json.loads(body)['csrf_token'];headers['Cookie']='; '.join(x.split(';',1)[0] for x in response['_set_cookies']);headers['X-CSRFToken']=csrf
                form,media=multipart('file','neutral.txt','text/plain',(ROOT/'fixtures/gate1-neutral-quiz.txt').read_bytes(),{'quiz_title':'Normal synthetic text export','csrf_token':csrf})
                assert request(port,nonce,'POST','/process',form,headers|{'Content-Type':media})[0] in (200,302)
                qid=json.loads((state/'backend/config/quizzes.json').read_text())[0]['id']
                exported=[]
                for path in ('/export/all_quizzes.txt',f'/export/quiz/{qid}.txt'):
                    status,body,response=request(port,nonce,'GET',path)
                    assert status==200 and 'attachment;' in response['Content-Disposition']
                    name='library-reference.txt' if 'all_quizzes' in path else 'single-quiz.txt'
                    (out/name).write_bytes(body)
                    exported.append({'path':path,'status':status,'bytes':len(body),'disposition':response['Content-Disposition']})
                form,media=multipart('file','single-quiz.txt','text/plain',(out/'single-quiz.txt').read_bytes(),{'quiz_title':'Reimported synthetic text','csrf_token':csrf})
                assert request(port,nonce,'POST','/process',form,headers|{'Content-Type':media})[0] in (200,302)
                registry=json.loads((state/'backend/config/quizzes.json').read_text())
                reimported=next(x['id'] for x in registry if x['title']=='Reimported synthetic text')
                with sqlite3.connect(state/'backend/results.db') as db:
                    def facts(quiz):
                        rows=db.execute('SELECT id,question_number,question_text FROM questions WHERE quiz_id=? ORDER BY question_number,id',(quiz,)).fetchall()
                        return [[number,text,db.execute('SELECT label,text,is_correct FROM choices WHERE question_id=? ORDER BY choice_order,label,id',(question,)).fetchall()] for question,number,text in rows]
                    original=facts(qid);restored=facts(reimported)
                assert original and original==restored,(original,restored)
                result['local']={'http_exports':exported,'single_text_reimport_response':True,
                    'questions_choices_correctness_and_order_match':True,'questions':len(original),'native_click_tested':False}
                for pid in descendants(proc.pid):
                    try:owned[pid]=identity(pid)['start']
                    except OSError:pass
                assert request(port,nonce,'POST','/api/shutdown')[0]==200
                assert proc.wait(timeout=35)==0
            else:
                wait_for(lambda:(out/'page-observation.json').exists(),35)
                files=list((data/'server-profiles').glob('*/downloads/download-*/*.txt'))
                assert len(files)==1,files
                content=files[0].read_text(encoding='utf-8')
                assert content.index('QUIZ: Alpha synthetic')<content.index('QUIZ: Zulu synthetic')
                result['server']={'page_observation':json.loads((out/'page-observation.json').read_text()),
                    'download':str(files[0]),'bytes':files[0].stat().st_size,'response':json.loads((out/'responses.jsonl').read_text().splitlines()[-1]),
                    'local_backend_created':state.exists(),'cleanup':'owned synthetic launcher terminated after observation, not a close-path acceptance test'}
                for pid in descendants(proc.pid):
                    try:owned[pid]=identity(pid)['start']
                    except OSError:pass
                proc.kill();proc.wait(timeout=15)
                traces=list((data/'shell'/profile/'window-events').glob('*.jsonl'))
                rows=[json.loads(line) for line in traces[0].read_text().splitlines()]
                samples=[r for r in rows if r['event']=='sample']
                result['server']['final_samples']=samples[-3:]
                if a.expect_server_visible:
                    assert result['server']['page_observation']['visible']=='true'
                    assert samples and all(r['view_visible'] for r in samples[-3:])
            (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:proc.kill();proc.wait(timeout=15)
        for log in logs:log.close()
        time.sleep(1)
        survivors=[pid for pid,born in owned.items() if alive(pid,born)]
        (out/'cleanup.json').write_text(json.dumps({'survivors':survivors})+'\n')
        assert not survivors,survivors

if __name__=='__main__':main()
