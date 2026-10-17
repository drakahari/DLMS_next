"""Normal final AppImage runs; no host input or shipped test hooks.

Authenticated requests exercise the real task-owned backend. Native chooser /
button checks are separate instrumented evidence or owner-only, not inferred.
"""
from pathlib import Path
import argparse,json,os,subprocess,time,hashlib,sqlite3,re,shutil,uuid
from tests.package.normal_local_settings_smoke import backend_nonce,descendants,request,starttime,stop_exact_owned
from tests.package.normal_pdf_ocr_smoke import multipart


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();inputs=parser.add_mutually_exclusive_group(required=True);inputs.add_argument('--image',type=Path);inputs.add_argument('--appdir',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--pdf',type=Path,required=True);parser.add_argument('--png',type=Path,required=True);parser.add_argument('--platform',choices=['offscreen','wayland','xcb'],default='offscreen');parser.add_argument('--expect-host-platform',action='store_true');parser.add_argument('--backup-dir',type=Path);a=parser.parse_args()
    a.image=(a.appdir/'AppRun' if a.appdir else a.image).absolute();out=a.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    env={'PATH':'/nonexistent','LANG':'C.UTF-8','QT_QPA_PLATFORM':a.platform,
         'FUSERMOUNT_PROG':'/usr/bin/fusermount3'}
    if a.platform!='offscreen':
        # Preserve display transports only; all writable application state below
        # remains disposable. No host input or desktop integration.
        for key in ['DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP']:
            if key in os.environ:env[key]=os.environ[key]
    for key,leaf in [('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp'),('XDG_RUNTIME_DIR','runtime')]:
        if key=='XDG_RUNTIME_DIR' and a.platform!='offscreen' and key in env:continue
        p=out/leaf;p.mkdir(mode=0o700);env[key]=str(p)
    data=out/'data/dlms-desktop-appimage-test';profile='appimage01';state=data/'profiles'/profile
    cwd=out/'unrelated cwd';cwd.mkdir();runs=[]
    moved=out/'relocated path with spaces/Renamed DLMS.AppImage';moved.parent.mkdir()
    if a.appdir:
        moved=moved.parent/'DLMS directory with spaces/AppRun';shutil.copytree(a.appdir,moved.parent,symlinks=True)
    else:
        shutil.copyfile(a.image,moved);moved.chmod(0o755)
    assert sha(moved)==sha(a.image)
    saved=None;oracle=None
    for index,exe in enumerate([a.image,moved] if a.appdir else [a.image,moved,None]):
        fallback=index==2;fuse=not fallback and not a.appdir
        if fallback:
            extraction=out/'explicit extraction fallback';extraction.mkdir()
            x=subprocess.run([str(a.image),'--appimage-extract'],cwd=extraction,env=env,capture_output=True,text=True,timeout=90)
            (out/'extraction.log').write_text(x.stdout+x.stderr);assert x.returncode==0
            exe=extraction/'squashfs-root/AppRun'
        with (out/f'launch-{index}.log').open('w') as log:
            proc=subprocess.Popen([str(exe),'--profile',profile],env=env,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            known={proc.pid:starttime(proc.pid)}
            try:
                until=time.monotonic()+45;started=time.monotonic()
                while time.monotonic()<until:
                    assert proc.poll() is None,('early-exit',index,proc.returncode)
                    known.update({p:starttime(p) for p in descendants(proc.pid)})
                    owner=backend_nonce(proc.pid)
                    if owner and (state/'desktop-profile.json').is_file():
                        manifest=json.loads((state/'desktop-profile.json').read_text());port=manifest['port'];nonce=owner[1]
                        try:
                            if request(port,nonce,'GET','/_desktop/ready')[0]==200:break
                        except OSError:pass
                    time.sleep(.08)
                else:raise TimeoutError('AppImage authenticated readiness')
                ready_ms=round((time.monotonic()-started)*1000)
                win=json.loads((state/'instance-owner.json').read_text());exe_path=os.readlink(f"/proc/{win['pid']}/exe")
                if fuse:assert '.mount_' in exe_path,('not-normal-FUSE-launch',exe_path)
                assert request(port,'invalid','GET','/library')[0]==403
                for path in ['/library','/study-history','/settings/backup','/settings/reset-remove']:
                    assert request(port,nonce,'GET',path)[0]==200,path
                # Actual final-file duplicate, independent runtime/FUSE mount.
                if index==0:
                    dup=subprocess.run([str(moved),'--profile',profile],env=env,cwd=cwd,capture_output=True,text=True,timeout=20)
                    (out/'duplicate.json').write_text(json.dumps({'exit':dup.returncode,'stdout':dup.stdout,'stderr':dup.stderr},indent=2)+'\n')
                    assert dup.returncode==0,dup.stderr
                    assert json.loads((state/'instance-owner.json').read_text())['pid']==win['pid']
                    assert backend_nonce(proc.pid)[0]==owner[0]
                origin=f'http://127.0.0.1:{port}'
                status,body,headers=request(port,nonce,'GET','/api/csrf-token',extra_headers={'Origin':origin,'X-DLMS-CSRF-Refresh':'1'},include_headers=True);assert status==200
                cookie='; '.join(v.split(';',1)[0] for k,v in headers if k.lower()=='set-cookie');csrf=json.loads(body)['csrf_token']
                common={'Origin':origin,'Referer':origin+'/library','Cookie':cookie,'X-CSRFToken':csrf}
                def post(path,body,media='application/json'):
                    if isinstance(body,dict):body=json.dumps(body).encode()
                    return request(port,nonce,'POST',path,body=body,extra_headers=common|{'Content-Type':media},include_headers=True)
                db=state/'backend/results.db'
                if index==0:
                    fixture=Path(__file__).resolve().parents[2]/'fixtures/gate1-neutral-quiz.txt'
                    form,media=multipart('file','neutral.txt','text/plain',fixture.read_bytes(),{'quiz_title':'AppImage Neutral Quiz','csrf_token':csrf})
                    status,_,headers=post('/process',form,media);assert status in [200,302],status
                    registry=json.loads((state/'backend/config/quizzes.json').read_text());entry=next(x for x in registry if x.get('title')=='AppImage Neutral Quiz');qid=entry['id']
                    artifacts=list((state/'backend/data').glob('*.json'));assert artifacts
                    rawfile=next(p for p in artifacts if str(qid) in p.name) if any(str(qid) in p.name for p in artifacts) else artifacts[0]
                    raw=rawfile.read_text();fp='sha256:'+hashlib.sha256('\0'.join(['quiz-recovery-v1','1',str(qid),'/data/'+rawfile.name,str(entry.get('exam_minutes') or 90),raw]).encode()).hexdigest()
                    status,b=request(port,nonce,'GET',f'/api/study/quiz/{qid}');assert status==200;generation=json.loads(b)['generation']
                    sid=uuid.uuid4().hex;event=uuid.uuid4().hex;tab=uuid.uuid4().hex
                    claim={'quizId':qid,'sessionId':sid,'owner':tab,'fingerprint':fp,'generation':generation,'answerEncoding':'choice-labels-v1','variants':{}}
                    status,b,_=post('/api/study/session',claim);assert status==200,(status,b[:300]);session=json.loads(b)['session']
                    action={'contract':2,'quizId':qid,'sessionId':sid,'owner':tab,'generation':generation,'answerEncoding':'choice-labels-v1','assessmentRevision':session['assessment_revision'],'eventId':event,'sequence':1,'questionOrdinal':1,'questionType':'choice','wasCorrect':True,'selected':['B'],'kind':'response'}
                    status,b,_=request(port,nonce,'POST','/_desktop/recovery/action',body=json.dumps({'kind':'study','payload':action,'fingerprint':fp}).encode(),extra_headers=common|{'Content-Type':'application/json','X-DLMS-Recovery-Client':'1'},include_headers=True)
                    assert status==200,(status,b[:300]);result=json.loads(b);assert result['ok']
                    saved={'quiz':qid,'session':sid,'event':event,'result':result}
                    # Same immutable retry goes through actual durable-action adapter.
                    status,b=request(port,nonce,'POST','/_desktop/recovery/action',body=json.dumps({'kind':'study','payload':action,'fingerprint':fp}).encode(),extra_headers=common|{'Content-Type':'application/json','X-DLMS-Recovery-Client':'1'});assert status==200
                    # Packaged PDFium/Tesseract, with no host programs on PATH.
                    form,media=multipart('pdf_file','scan.pdf','application/pdf',a.pdf.read_bytes(),{'rights_ok':'on','quiz_title':'AppImage Scanned PDF','pdf_content_type':'question_bank'})
                    status,b,h=post('/pdf-import/analyze',form,media);assert status==302,(status,b[:100]);loc=dict(h)['Location'];assert '/ocr/' in loc;draft=loc.rsplit('/',1)[-1]
                    status,_,_=post(f'/pdf-import/ocr/{draft}/start',b'ocr_pages=1','application/x-www-form-urlencoded');assert status==302
                    status,b,_=post(f'/pdf-import/ocr/{draft}/process/next',b'','application/x-www-form-urlencoded');assert status==200 and json.loads(b)['status']=='complete',b[:300]
                    form,media=multipart('screenshots','image.png','image/png',a.png.read_bytes(),{'rights_ok':'on','quiz_title':'AppImage PNG OCR'})
                    status,_,h=post('/pdf-import/screenshots',form,media);assert status==302;draft=dict(h)['Location'].rsplit('/',1)[-1]
                    status,b,_=post(f'/pdf-import/screenshots/process/{draft}/next',b'','application/x-www-form-urlencoded');assert status==200 and json.loads(b)['status']=='complete'
                    assert 'Which shape has three sides?' in (state/f'backend/pdf_import_drafts/{draft}.json').read_text()
                with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as c:
                    facts={t:c.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall() for t in ['quizzes','questions','choices','matching_pairs','study_sessions','study_responses']}
                    assert c.execute('SELECT count(*) FROM study_responses WHERE event_id=?',(saved['event'],)).fetchone()[0]==1
                if oracle is None:oracle=facts
                else:assert facts==oracle,('changed-records',index)
                # No replacement lock is opened in this standalone namespace.
                held=[]
                mount_target=os.readlink(f"/proc/{win['pid']}/fd/1023") if fuse else None
                lifetime_pipe=os.readlink(f"/proc/{win['pid']}/fd/3") if fuse else None
                if fuse:assert lifetime_pipe.startswith('pipe:[')
                for pid in descendants(proc.pid):
                    known[pid]=starttime(pid)
                    for fd in Path(f'/proc/{pid}/fd').glob('*'):
                        try:
                            target=os.readlink(fd)
                            assert 'manual-replacement.lock' not in target,target
                            if pid != win['pid'] and fuse:
                                assert target not in {mount_target,lifetime_pipe},('inherited-mount-handle',pid,fd.name,target)
                            protected = (Path(target).name == 'backend-writer.lock'
                                         or (pid == win['pid'] and fuse and fd.name in {'3','1023'}))
                            if protected:
                                flags=next(s.split()[1] for s in Path(f'/proc/{pid}/fdinfo/{fd.name}').read_text().splitlines() if s.startswith('flags:'))
                                assert int(flags,8)&os.O_CLOEXEC,(pid,fd.name,target)
                                held.append({'pid':pid,'fd':fd.name,'target':target,'close_on_exec':True})
                        except (FileNotFoundError,ProcessLookupError):pass
                mapped=[]
                if a.expect_host_platform:
                    for pid in descendants(proc.pid):
                        try:
                            libraries=sorted(set(line.split()[-1] for line in Path(f'/proc/{pid}/maps').read_text().splitlines()
                                if any(name in line for name in ['libfontconfig.so','libgbm.so','libfreetype.so','libEGL','libGLX','libdrm.so','libxml2.so','libexpat.so'])))
                        except FileNotFoundError:continue
                        mapped.append({'pid':pid,'libraries':libraries})
                    own=next(x['libraries'] for x in mapped if x['pid']==win['pid'])
                    for name in ['libfontconfig.so','libgbm.so']:
                        selected=[Path(x) for x in own if name in Path(x).name]
                        assert selected and all(not x.is_relative_to(Path(exe_path).parent) for x in selected),(name,selected)
                if a.backup_dir and index==0:
                    from tests.settings.gui_native_roundtrip import facts
                    import zipfile,io
                    folder=a.backup_dir.absolute();folder.mkdir(mode=0o700,parents=True,exist_ok=False)
                    before=facts(state/'backend')
                    status,content,h=post('/settings/backup/create',b'','application/x-www-form-urlencoded')
                    assert status==200 and content.startswith(b'PK'),(status,content[:200])
                    with zipfile.ZipFile(io.BytesIO(content)) as archive:assert archive.testzip() is None
                    with (folder/'daily-backup.zip').open('xb') as file:file.write(content)
                    (folder/'portable-facts.json').write_text(json.dumps(before,sort_keys=True,indent=2)+'\n')
                    assert facts(state/'backend')==before
                    (folder/'export.json').write_text(json.dumps({'normal_frozen_backend_route':True,'native_save_chooser':False,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)},indent=2)+'\n')
                assert request(port,nonce,'POST','/api/shutdown')[0]==200
                assert proc.wait(timeout=30)==0
                # Allow only deterministic normal cleanup, not broad process-name kills.
                live=[p for p,born in known.items() if born and starttime(p)==born]
                until=time.monotonic()+5
                while live and time.monotonic()<until:
                    time.sleep(.05);live=[p for p,born in known.items() if born and starttime(p)==born]
                assert not live,('orphan-after-normal-close',live)
                runs.append({'index':index,'kind':'tar-AppDir' if a.appdir else ('explicit-extraction-fallback' if fallback else 'normal-FUSE-AppImage'),'file':str(exe),'profile_uuid':manifest['uuid'],'port':port,'backend_ready_ms':ready_ms,'owner_pid':win['pid'],'owner_executable':exe_path,'same_records':True,'exact_cleanup':True,'sealed_descriptors':held,'host_platform_maps':mapped,'Qt_platform':a.platform})
            finally:
                residual=stop_exact_owned(proc,known);assert not residual,residual
        (out/'progress.json').write_text(json.dumps(runs,indent=2)+'\n')
    assert all(x['profile_uuid']==runs[0]['profile_uuid'] and x['port']==runs[0]['port'] for x in runs)
    (out/'records.json').write_text(json.dumps(oracle,indent=2)+'\n')
    result={'normal_final_AppImage':not bool(a.appdir),'normal_tar_AppDir':bool(a.appdir),'image_sha256':sha(a.image) if not a.appdir else None,'saved':saved,'runs':runs,'pdf_png_ocr':'passed; frozen backend routes, PATH=/nonexistent','duplicate_across_distinct_mounts':'not applicable to AppDir' if a.appdir else 'focused same owner/backend','state_outside_mount':str(data),'native_button_acceptance':'pending owner; no input injection/test hooks','limits':'No physical input/rendered-appearance/power-loss/public-distribution claim'}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('Normal portable create/Study/OCR/duplicate/move/reopen passed; extraction separately when AppImage')

if __name__=='__main__':main()
