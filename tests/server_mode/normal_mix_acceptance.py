"""Normal final AppImage, captured 6,000-question synthetic Server DOM only.

No frozen test hooks/native bridge. Server-owned test scripts report their own
DOM/filter timing; native reveal timing remains source/instrumented evidence.
"""
import argparse,json,os,subprocess,time,hashlib,uuid
from pathlib import Path
from desktop.isolation import PROJECT
from tests.server_mode.mix_sequence import fixture_fidelity
from tests.package.normal_local_settings_smoke import backend_nonce,descendants,starttime,stop_exact_owned

def main():
    p=argparse.ArgumentParser();p.add_argument('--image',type=Path,required=True);p.add_argument('--normal-evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--server-source',type=Path);a=p.parse_args()
    out=a.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    for leaf in ['server-home','server-config','server-cache','server-xdg-data','server-tmp']: (out/leaf).mkdir(mode=0o700)
    server_env=dict(os.environ,HOME=str(out/'server-home'),XDG_CONFIG_HOME=str(out/'server-config'),XDG_CACHE_HOME=str(out/'server-cache'),XDG_DATA_HOME=str(out/'server-xdg-data'),TMPDIR=str(out/'server-tmp'),QUIZAPP_DATA_DIR=str(out/'server-data'),DLMS_PERF_LOG=str(out/'requests.jsonl'),DLMS_PERF_READY=str(out/'port'),DLMS_PERF_QUIZZES='24',DLMS_PERF_QUESTIONS='250',DLMS_PERF_NORMAL_SEQUENCE='1',DLMS_PERF_MATCHING='1',DLMS_PERF_NORMAL_RESULTS=str(out/'dom.jsonl'))
    if a.server_source:
        source=a.server_source.resolve()
        if not source.is_relative_to(PROJECT/'.gate1'):raise ValueError('Task-local released-source snapshot required')
        server_env['DLMS_PERF_SOURCE']=str(source)
    base=a.normal_evidence.absolute();data=base/'data/dlms-desktop-appimage-test';profile='appimage01';local=data/'profiles'/profile/'backend'
    def hashes():return {str(x.relative_to(local)):hashlib.sha256(x.read_bytes()).hexdigest() for x in local.rglob('*') if x.is_file()}
    before=hashes();assert before
    mode=data/'shell'/profile/'mode.json'
    assert not (mode.parent/'instance-owner.json').exists(),'Normal fixture must be stopped'
    log=(out/'server.log').open('w');server=subprocess.Popen([os.sys.executable,'-m','tests.server_mode.performance_server'],env=server_env,cwd=PROJECT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    (out/'server-owner.json').write_text(json.dumps({'pid':server.pid,'start_ticks':Path(f'/proc/{server.pid}/stat').read_text().rsplit(')',1)[1].split()[19]}))
    proc=None;known={}
    try:
        deadline=time.monotonic()+60
        while not (out/'port').exists():
            assert server.poll() is None
            if time.monotonic()>deadline:raise TimeoutError('Synthetic library startup')
            time.sleep(.05)
        store_before=fixture_fidelity(out/'server-data')
        origin='http://127.0.0.2:'+ (out/'port').read_text();identifier=str(uuid.uuid4())
        mode.parent.mkdir(mode=0o700,parents=True,exist_ok=True);config={'version':1,'profile':profile,'mode':'server','server':{'id':identifier,'label':'Captured Mix fixture','origin':origin,'private_http':True}};mode.write_text(json.dumps(config));mode.chmod(0o600)
        env={'PATH':'/nonexistent','FUSERMOUNT_PROG':'/usr/bin/fusermount3','LANG':'C.UTF-8','QT_QPA_PLATFORM':'wayland'}
        for key in ['DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP']:
            if key in os.environ:env[key]=os.environ[key]
        for key,leaf in [('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp')]:env[key]=str(base/leaf)
        with (out/'normal.log').open('w') as stream:
            proc=subprocess.Popen([str(a.image.absolute()),'--profile',profile],env=env,cwd=out,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True);known={proc.pid:starttime(proc.pid)}
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                assert proc.poll() is None
                known.update({pid:starttime(pid) for pid in descendants(proc.pid)})
                records=[json.loads(line) for line in (out/'dom.jsonl').read_text().splitlines()] if (out/'dom.jsonl').exists() else []
                mixes=[r for r in records if r['path']=='/quiz-composer']
                if len(mixes)==2:break
                time.sleep(.05)
            else:raise TimeoutError('Normal captured Mix DOM/filter checkpoints')
            assert all(r['questions']==6000 and not r['hidden'] for r in mixes)
            assert all(all(f['passed'] for f in r['filters']) for r in mixes)
            assert all(next(f for f in r['filters'] if f['name']=='clear_hidden_50')['ids']==[] for r in mixes)
            for mix in mixes:
                steps={s['name']:s for s in mix['filters']}
                first=steps['pick_first_25']['ids'];fifty=steps['pick_next_25']['ids']
                assert len(first)==25 and len(set(fifty))==50 and fifty[:25]==first
                assert steps['quiz_five']['ids']==first
                for name in ['folder_two','folder_two_all_quizzes','quiz_two']:assert steps[name]['ids']==fifty
                assert len(set(steps['select_visible_250']['ids']))==250
                assert steps['clear_hidden_50']['ids']==steps['clear_visible_250']['ids']==[]
            assert [s['ids'] for s in mixes[0]['filters']]==[s['ids'] for s in mixes[1]['filters']]
            assert backend_nonce(proc.pid) is None and hashes()==before
            assert json.loads(mode.read_text())==config
            requests=[json.loads(line) for line in (out/'requests.jsonl').read_text().splitlines()]
            assert len([r for r in requests if r['phase']=='request' and r['path'].startswith('/quiz-composer?')])==2
            assert not any(r.get('local_token_present',False) for r in requests)
            assert all(r['policy']=='camera=(), geolocation=(), microphone=(), payment=(), usb=()' for r in requests if r['phase']=='headers')
        assert not stop_exact_owned(proc,known);proc=None
        text=(out/'normal.log').read_text()
        assert text.count("js: Error with Permissions-Policy header: Unrecognized feature: 'payment'.")==1
        assert text.count("js: Error with Permissions-Policy header: Unrecognized feature: 'usb'.")==1
        assert hashes()==before
        assert fixture_fidelity(out/'server-data')==store_before
        (out/'result.json').write_text(json.dumps({'source_store_before_after':store_before,'normal_artifact':str(a.image),'sha256':hashlib.sha256(a.image.read_bytes()).hexdigest(),'server_dom':records,'local_files_unchanged':True,'local_backend_absent':True,'remote_headers_unchanged':True,'native_reveal':'not measured in normal binary; source Qt visibility checks only in this batch','server_close':'exact task-owned termination, not owner close-dialog acceptance'},indent=2)+'\n')
    finally:
        if proc is not None:assert not stop_exact_owned(proc,known)
        if server.poll() is None:server.terminate();server.wait(timeout=15)
        log.close()
    return 0
if __name__=='__main__':raise SystemExit(main())
