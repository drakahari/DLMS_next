"""Normal frozen guard/worker lock flags and lifecycle, fixture homes only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from package_fedora import manual_replace as replacement
from tests.package.normal_local_settings_smoke import backend_nonce,descendants,request,starttime,stop_exact_owned


def lock_descriptors(pid,lock):
    expected=lock.stat();found=[]
    for child in descendants(pid):
        proc=Path('/proc')/str(child);born=starttime(child)
        try:
            exe=os.readlink(proc/'exe')
            for entry in (proc/'fd').iterdir():
                try:
                    st=entry.stat()
                    if (st.st_dev,st.st_ino)!=(expected.st_dev,expected.st_ino):continue
                    info=(proc/'fdinfo'/entry.name).read_text()
                    flags=int(next(x.split()[1] for x in info.splitlines() if x.startswith('flags:')),8)
                    assert flags&os.O_CLOEXEC,(child,entry.name,exe,info)
                    found.append({'pid':child,'start_ticks':born,'exe':exe,'fd':int(entry.name),'close_on_exec':True})
                except FileNotFoundError:pass
            assert starttime(child)==born
        except FileNotFoundError:pass
    return found


def launch(home,out,index,stage,*,crash=False):
    p=replacement.paths(home)
    env={'PATH':'/nonexistent','LANG':'C.UTF-8','QT_QPA_PLATFORM':'offscreen'}
    for key,rel in (('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp'),('XDG_RUNTIME_DIR','runtime')):
        leaf=out/'environment'/rel;leaf.mkdir(parents=True,exist_ok=True,mode=0o700);env[key]=str(leaf)
    with (out/f'normal-{index}.log').open('w') as log:
        process=subprocess.Popen([str(p['launcher'])],cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        observed={process.pid:starttime(process.pid)}
        try:
            manifest_path=p['data']/'profiles/pilot01/desktop-profile.json'
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError(f'Frozen launcher exited {process.returncode}')
                observed.update({x:starttime(x) for x in descendants(process.pid)})
                owner=backend_nonce(process.pid)
                if owner and manifest_path.exists():
                    manifest=json.loads(manifest_path.read_text())
                    try:
                        if request(manifest['port'],owner[1],'GET','/_desktop/ready')[0]==200:break
                    except OSError:pass
                time.sleep(.08)
            else:raise TimeoutError('Frozen authenticated readiness')
            held=lock_descriptors(process.pid,p['opt']/replacement.LOCK)
            assert any(x['pid']==process.pid for x in held) and any(x['pid']==owner[0] for x in held),held
            observed.update({x['pid']:x['start_ticks'] for x in held})
            before=p['manifest'].read_bytes()
            try:replacement.transition(home,stage_operation=stage);raise AssertionError('Running DLMS failed to exclude replacement')
            except ValueError as exc:assert 'lock is held' in str(exc),str(exc)
            assert p['manifest'].read_bytes()==before and not (p['opt']/replacement.ACTIVE).exists()
            for page in ('/library','/history','/settings/backup','/settings/reset-remove'):
                assert request(manifest['port'],owner[1],'GET',page)[0]==200
            assert request(manifest['port'],'unauthorized','GET','/library')[0]==403
            duplicate=subprocess.run([str(p['launcher'])],cwd=out,env=env,capture_output=True,text=True,timeout=15)
            assert duplicate.returncode==0,duplicate.stderr
            assert json.loads((p['data']/'profiles/pilot01/instance-owner.json').read_text())['pid']==process.pid
            assert backend_nonce(process.pid)[0]==owner[0]
            if crash:
                observed.update({pid:starttime(pid) for pid in descendants(process.pid)})
                (out/'crash-observed.json').write_text(json.dumps(observed,indent=2)+'\n')
                process.kill()  # exact Popen launcher only; no broad process/group kill
                assert process.wait(timeout=10)<0
                deadline=time.monotonic()+12
                while time.monotonic()<deadline:
                    live=[]
                    for pid,born in observed.items():
                        if born and starttime(pid)==born:
                            try:
                                state=(Path('/proc')/str(pid)/'stat').read_text().rsplit(') ',1)[1].split()[0]
                                if state!='Z':live.append(pid)
                            except FileNotFoundError:pass
                    if not live:break
                    time.sleep(.05)
                else:raise AssertionError(f'Parent-pipe crash cleanup failed: {live}')
            else:
                assert request(manifest['port'],owner[1],'POST','/api/shutdown')[0]==200
                assert process.wait(timeout=25)==0
            with replacement.gate(home):pass
            return {'normal_package':True,'profile_uuid':manifest['uuid'],'port':manifest['port'],'lock_descriptors':held,
                    'running_replacement_refused':True,'duplicate_single_writer':True,'unauthorized_rejected':True,'shutdown_exit':process.returncode,'controlled_launcher_crash':crash}
        finally:
            residual=stop_exact_owned(process,observed)
            assert not residual,residual


def main():
    p=argparse.ArgumentParser();p.add_argument('--home',type=Path,required=True);p.add_argument('--stage-operation',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--crash-check',action='store_true');a=p.parse_args()
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    home=a.home.resolve()
    if not home.is_relative_to(Path(__file__).resolve().parents[2]/'.gate1'):raise ValueError('Fixture home required')
    runs=[launch(home,a.output,n,a.stage_operation,crash=a.crash_check and n==1) for n in (1,2)]
    assert runs[0]['profile_uuid']==runs[1]['profile_uuid'] and runs[0]['port']==runs[1]['port']
    before=replacement.old._data_fingerprint(home)
    result=replacement.transition(home,stage_operation=a.stage_operation)
    assert replacement.old._data_fingerprint(home)==before
    record={'runs':runs,'stable_origin_profile':True,'no_owned_helpers_left':True,
            'post_close_fixture_replacement':result['active_release'],'replacement_preserved_data':True,
            'input':'no mouse/keyboard; authenticated local HTTP shutdown only','default_file_manager_tested':False}
    (a.output/'result.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))

if __name__=='__main__':main()
