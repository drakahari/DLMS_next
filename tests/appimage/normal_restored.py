"""Final normal standalone binary reopens an instrumented-imported synthetic dataset.
No native input or normal-binary hooks; all filesystem state is explicitly task-local.
"""
import argparse,hashlib,json,os,re,subprocess,time
from pathlib import Path
from desktop.isolation import PROJECT
from tests.package.normal_local_settings_smoke import backend_nonce,descendants,request,starttime,stop_exact_owned
from tests.settings.gui_native_roundtrip import facts

def main():
    p=argparse.ArgumentParser();p.add_argument('--image',type=Path,required=True);p.add_argument('--normal-evidence',type=Path,required=True);p.add_argument('--facts',type=Path,required=True);p.add_argument('--profile',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    base=a.normal_evidence.absolute();out=a.output.absolute()
    assert base.is_relative_to(PROJECT/'.gate1') and out.is_relative_to(PROJECT/'.gate1')
    assert re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',a.profile)
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    state=base/'data/dlms-desktop-appimage-test/profiles'/a.profile
    expected=json.loads(a.facts.read_text());manifest=json.loads((state/'desktop-profile.json').read_text())
    assert facts(state/'backend')==expected
    env={'PATH':'/nonexistent','LANG':'C.UTF-8','QT_QPA_PLATFORM':'wayland','FUSERMOUNT_PROG':'/usr/bin/fusermount3'}
    for key in ['DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP']:
        if key in os.environ:env[key]=os.environ[key]
    for key,leaf in [('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp')]:env[key]=str(base/leaf)
    rows=[]
    for index in range(2):
        with (out/f'launch-{index}.log').open('w') as stream:
            proc=subprocess.Popen([str(a.image.absolute()),'--profile',a.profile],env=env,cwd=out,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True);known={proc.pid:starttime(proc.pid)}
            try:
                until=time.monotonic()+45
                while time.monotonic()<until:
                    assert proc.poll() is None
                    known.update({pid:starttime(pid) for pid in descendants(proc.pid)})
                    owner=backend_nonce(proc.pid)
                    if owner:
                        try:
                            if request(manifest['port'],owner[1],'GET','/_desktop/ready')[0]==200:break
                        except OSError:pass
                    time.sleep(.1)
                else:raise TimeoutError('Restored normal profile readiness')
                now=json.loads((state/'desktop-profile.json').read_text());assert (now['uuid'],now['port'],now['epoch'])==(manifest['uuid'],manifest['port'],manifest['epoch'])
                for page in ['/library','/history','/study-history']:assert request(now['port'],owner[1],'GET',page)[0]==200
                assert request(now['port'],'unauthorized','GET','/library')[0]==403
                assert facts(state/'backend')==expected
                assert request(now['port'],owner[1],'POST','/api/shutdown')[0]==200
                assert proc.wait(timeout=30)==0
                rows.append({'normal_package':True,'profile_uuid':now['uuid'],'port':now['port'],'epoch':now['epoch'],'records_assets_equal':True,'shutdown':0})
            finally:assert not stop_exact_owned(proc,known)
    (out/'result.json').write_text(json.dumps({'normal_artifact':str(a.image),'sha256':hashlib.sha256(a.image.read_bytes()).hexdigest(),'native_import':'separate instrumented Qt evidence, not normal-button automation','runs':rows,'owned_cleanup':True},indent=2)+'\n')
    print('Normal restored profile records/assets and separate-process reopen passed')
if __name__=='__main__':main()
