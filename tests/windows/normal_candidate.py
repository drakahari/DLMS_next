"""Normal Windows executable HTTP workflows; separate from Qt instrumentation."""
from pathlib import Path
import argparse
import hashlib
import http.client
import http.cookies
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
import zipfile
import io

from tests.windows.normal_processes import descendants, identity, alive, backend_nonce
from tests.package.normal_pdf_ocr_smoke import multipart
from tests.settings.gui_native_roundtrip import facts

ROOT=Path(__file__).resolve().parents[2]

def request(port,nonce,method,path,body=None,headers=None):
    connection=http.client.HTTPConnection("127.0.0.1",port,timeout=45)
    try:
        connection.request(method,path,body=body,headers={"Host":f"127.0.0.1:{port}","X-DLMS-Desktop-Token":nonce,**(headers or {})})
        response=connection.getresponse()
        fields=response.getheaders()
        return response.status,response.read(),dict(fields)|{"_set_cookies":[v for k,v in fields if k.lower()=="set-cookie"]}
    finally:connection.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--exe",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True);parser.add_argument("--ocr",action="store_true")
    args=parser.parse_args();exe=args.exe.resolve(strict=True);out=args.output.absolute()
    if not out.is_relative_to(ROOT/".gate1/windows-native") or out.exists():raise ValueError("Use a fresh task-local output")
    out.mkdir(mode=0o700);data=out/"Synthetic data 日本語 with spaces";data.mkdir(mode=0o700)
    (data/".dlms-desktop-windows-candidate.json").write_text(json.dumps({"kind":"dlms-desktop-windows-candidate","version":1}))
    profile="normal01";state=data/"profiles"/profile
    records=[];oracle=None;saved={};portable=None
    for run in range(2):
        # Keep SystemRoot for Windows/Qt. No Python, Tesseract or external tools
        # on PATH; every application/runtime dependency comes from the payload.
        env={key:value for key,value in os.environ.items() if not key.startswith(("DLMS_","QUIZAPP_","QTWEBENGINE_","PYTHON"))}
        env["PATH"]=str(out/"no-host-tools")
        with (out/f"launcher-{run}.log").open("w") as log:
            proc=subprocess.Popen([str(exe),"--profile",profile,"--data-root",str(data)],env=env,cwd=out,stdout=log,stderr=subprocess.STDOUT)
            observed={proc.pid:identity(proc.pid)["start"]}
            try:
                deadline=time.monotonic()+45;start=time.monotonic();owner=None;diagnostics={}
                while time.monotonic()<deadline:
                    assert proc.poll() is None,f"normal launcher exited {proc.returncode}"
                    for pid in descendants(proc.pid):
                        try:observed[pid]=identity(pid)["start"]
                        except OSError:pass
                    manifest_path=state/"desktop-profile.json"
                    owner=backend_nonce(proc.pid,exe,diagnostics)
                    if owner and manifest_path.is_file():
                        manifest=json.loads(manifest_path.read_text());port=manifest["port"];nonce=owner[1]
                        try:
                            if request(port,nonce,"GET","/_desktop/ready",headers={"X-DLMS-Desktop-Nonce":nonce})[0]==200:break
                        except OSError:pass
                    time.sleep(.1)
                else:
                    (out/"harness-inspection-failure.json").write_text(json.dumps(diagnostics,indent=2)+"\n")
                    raise TimeoutError("Normal Windows package did not become ready in external harness")
                ready_seconds=round(time.monotonic()-start,3)
                headers={"Origin":f"http://127.0.0.1:{port}","Sec-Fetch-Site":"same-origin"}
                assert request(port,"wrong-token","GET","/")[0]==403
                assert request(port,nonce,"GET","/",headers={"Origin":"https://example.invalid"})[0]==403
                status,html,response=request(port,nonce,"GET","/");assert status==200
                status,body,response=request(port,nonce,"GET","/api/csrf-token",headers=headers|{"X-DLMS-CSRF-Refresh":"1"})
                assert status==200,(status,body[:100])
                headers["Cookie"]="; ".join(x.split(";",1)[0] for x in response["_set_cookies"])
                csrf=json.loads(body)["csrf_token"]
                headers["X-CSRFToken"]=csrf
                def post(path,payload,media="application/json"):
                    if isinstance(payload,dict):payload=json.dumps(payload).encode()
                    return request(port,nonce,"POST",path,payload,headers|{"Content-Type":media})
                if run==0:
                    status,body,_=post('/api/theme',{"theme":"dark"})
                    assert status==200 and json.loads(body)["theme"]=="dark"
                    duplicate=subprocess.run([str(exe),"--profile",profile,"--data-root",str(data)],cwd=out,env=env,timeout=15)
                    assert duplicate.returncode==0
                    fixture=ROOT/"fixtures/gate1-neutral-quiz.txt"
                    form,media=multipart("file",fixture.name,"text/plain",fixture.read_bytes(),{"quiz_title":"Windows Neutral Quiz","csrf_token":csrf})
                    status,body,_=post("/process",form,media);assert status in (200,302),(status,body[:200])
                    registry=json.loads((state/"backend/config/quizzes.json").read_text())
                    entry=next(x for x in registry if x.get("title")=="Windows Neutral Quiz");qid=entry["id"]
                    rawfile=next(p for p in (state/"backend/data").glob("*.json") if str(qid) in p.name)
                    raw=rawfile.read_bytes().decode("utf-8");fp="sha256:"+hashlib.sha256("\0".join(["quiz-recovery-v1","1",str(qid),"/data/"+rawfile.name,str(entry.get("exam_minutes") or 90),raw]).encode()).hexdigest()
                    status,body,_=request(port,nonce,"GET",f"/api/study/quiz/{qid}");assert status==200
                    generation=json.loads(body)["generation"];sid,event,tab=(uuid.uuid4().hex for _ in range(3))
                    claim={"quizId":qid,"sessionId":sid,"owner":tab,"fingerprint":fp,"generation":generation,"answerEncoding":"choice-labels-v1","variants":{}}
                    status,body,_=post("/api/study/session",claim);assert status==200,(status,body[:200]);session=json.loads(body)["session"]
                    action={"contract":2,"quizId":qid,"sessionId":sid,"owner":tab,"generation":generation,"answerEncoding":"choice-labels-v1","assessmentRevision":session["assessment_revision"],"eventId":event,"sequence":1,"questionOrdinal":1,"questionType":"choice","wasCorrect":True,"selected":["B"],"kind":"response"}
                    status,body,_=request(port,nonce,"POST","/_desktop/recovery/action",json.dumps({"kind":"study","payload":action,"fingerprint":fp}).encode(),headers|{"Content-Type":"application/json","X-DLMS-Recovery-Client":"1"})
                    assert status==200,(status,body[:300]);saved={"quiz":qid,"event":event}
                    attempt=uuid.uuid4().hex
                    exam={"quizId":qid,"attemptId":attempt,"mode":"Exam","answerEncoding":"choice-labels-v1",
                          "score":4,"total":4,"percent":100,"startedAt":"2026-10-15T12:00:00Z",
                          "completedAt":"2026-10-15T12:01:00Z","timeRemaining":300,"sessionId":uuid.uuid4().hex,
                          "responseDetails":[{"attemptQuestionNumber":i,"questionType":"choice","wasCorrect":True,
                                              "selected":[label]} for i,label in enumerate(['B','C','A','B'],1)]}
                    envelope=json.dumps({"kind":"exam","payload":exam,"fingerprint":fp}).encode()
                    status,body,_=request(port,nonce,"POST","/_desktop/recovery/action",envelope,
                        headers|{"Content-Type":"application/json","X-DLMS-Recovery-Client":"1"})
                    assert status==200,(status,body[:300]);saved["attempt"]=attempt
                    if args.ocr:
                        for kind in ("pdf","png"):
                            file=ROOT/"tests/fixtures/ocr"/("dlms-question.png" if kind=="png" else "pdf/fully-scanned.pdf")
                            if not file.is_file():raise FileNotFoundError(file)
                            field="pdf_file" if kind=="pdf" else "screenshots"
                            form,media=multipart(field,file.name,"application/pdf" if kind=="pdf" else "image/png",file.read_bytes(),{"rights_ok":"on","quiz_title":"Windows OCR","pdf_content_type":"question_bank"})
                            status,body,response=post("/pdf-import/analyze" if kind=="pdf" else "/pdf-import/screenshots",form,media)
                            assert status==302,(status,body[:200]);draft=response["Location"].rsplit("/",1)[-1]
                            if kind=="pdf":
                                assert post(f"/pdf-import/ocr/{draft}/start",b"ocr_pages=1","application/x-www-form-urlencoded")[0]==302
                            status,body,_=post(f"/pdf-import/ocr/{draft}/process/next" if kind=="pdf" else f"/pdf-import/screenshots/process/{draft}/next",b"","application/x-www-form-urlencoded")
                            assert status==200 and json.loads(body)["status"]=="complete" and json.loads(body)["has_results"],(status,body[:300])
                            result=json.loads((state/'backend/pdf_import_drafts'/f'{draft}.json').read_text())
                            expected='Which port is HTTPS?' if kind=='pdf' else 'Which protocol secures web traffic?'
                            assert result['questions'] and expected in json.dumps(result['questions'])
                    status,body,_=post("/settings/backup/create",b"","application/x-www-form-urlencoded")
                    assert status==200 and body.startswith(b"PK"),(status,body[:200])
                    with zipfile.ZipFile(io.BytesIO(body)) as archive:assert archive.testzip() is None
                    portable=out/"normal-export.zip";portable.write_bytes(body)
                    for path,name in (("/export/all_quizzes.txt","library-reference.txt"),
                                      (f"/export/quiz/{qid}.txt","individual-quiz.txt")):
                        status,text,response=request(port,nonce,'GET',path)
                        assert status==200 and response.get('Content-Disposition','').startswith('attachment;')
                        assert 'Correct Answer:' in text.decode('utf-8-sig')
                        (out/name).write_bytes(text)
                current=facts(state/"backend")
                assert json.loads((state/"backend/config/portal.json").read_text())["theme"]=="dark"
                if oracle is None:oracle=current
                else:assert current==oracle,"Portable rows/assets changed across normal reopen"
                with sqlite3.connect(state/"backend/results.db") as database:
                    assert database.execute("SELECT COUNT(*) FROM study_responses WHERE event_id=?",(saved["event"],)).fetchone()[0]==1
                    columns={row[1] for row in database.execute('PRAGMA table_info(attempts)')}
                    identity_column='attempt_id' if 'attempt_id' in columns else 'id'
                    assert database.execute(f"SELECT COUNT(*) FROM attempts WHERE {identity_column}=?",(saved["attempt"],)).fetchone()[0]==1
                for pid in descendants(proc.pid):
                    try:observed[pid]=identity(pid)["start"]
                    except OSError:pass
                assert request(port,nonce,"POST","/api/shutdown")[0]==200
                assert proc.wait(timeout=35)==0
                deadline=time.monotonic()+5
                while any(alive(pid,born) for pid,born in observed.items()) and time.monotonic()<deadline:time.sleep(.1)
                assert not [pid for pid,born in observed.items() if alive(pid,born)],"Owned process survived normal exit"
                records.append({"run":run,"port":port,"uuid":manifest["uuid"],"ready_seconds":ready_seconds,"exact_cleanup":True})
            finally:
                if proc.poll() is None:proc.kill();proc.wait(timeout=10)
    assert records[0]["port"]==records[1]["port"] and records[0]["uuid"]==records[1]["uuid"]
    (out/"portable-facts.json").write_text(json.dumps(oracle,indent=2)+"\n")
    (out/"result.json").write_text(json.dumps({"normal_executable":str(exe),"runs":records,"saved":saved,
        "backup":str(portable),"physical_acceptance":False,"instrumented":False,"ocr":args.ocr},indent=2)+"\n")
    print("Normal Windows executable launch/duplicate/theme/Study/Exam/export/reopen/cleanup passed")

if __name__=="__main__":main()
