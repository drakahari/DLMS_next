"""External normal-package idle/process observation, without UI injection."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from tests.windows.normal_candidate import ROOT,request
from tests.windows.normal_processes import descendants,identity,alive,backend_nonce
from desktop.windows_processes import arguments

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=30);p.add_argument('--capture',action='store_true');a=p.parse_args()
    exe=a.exe.resolve(strict=True);out=a.output.absolute()
    if not 5<=a.seconds<=900 or not out.is_relative_to(ROOT/'.gate1/windows-native') or out.exists():raise ValueError('Fresh bounded task-local observation required')
    out.mkdir(mode=0o700);data=out/'Fresh test data 日本語';data.mkdir(mode=0o700)
    (data/'.dlms-desktop-windows-candidate.json').write_text(json.dumps({'kind':'dlms-desktop-windows-candidate','version':1}))
    profile='observe01';root=data/'profiles'/profile
    env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','QTWEBENGINE_','PYTHON'))};env['PATH']=str(out/'no-host-tools')
    command=[str(exe),'--data-root',str(data),'--profile',profile]
    if a.capture:command.append('--capture-window-events')
    with (out/'launcher.log').open('w') as log:
        proc=subprocess.Popen(command,env=env,cwd=exe.parent,stdout=log,stderr=subprocess.STDOUT)
        observed={proc.pid:identity(proc.pid)['start']};changes=[];last=None
        try:
            deadline=time.monotonic()+40;owner=None
            while time.monotonic()<deadline:
                assert proc.poll() is None
                owner=backend_nonce(proc.pid,exe)
                if owner and (root/'desktop-profile.json').exists():
                    port=json.loads((root/'desktop-profile.json').read_text())['port'];nonce=owner[1]
                    if request(port,nonce,'GET','/_desktop/ready',headers={'X-DLMS-Desktop-Nonce':nonce})[0]==200:break
                time.sleep(.1)
            else:raise TimeoutError('Normal observation startup')
            backend=identity(owner[0]);started=time.monotonic();last_ready=started
            duplicate=subprocess.run(command,env=env,cwd=exe.parent,timeout=15)
            assert duplicate.returncode==0
            while time.monotonic()-started<a.seconds:
                assert proc.poll() is None
                assert identity(owner[0])['start']==backend['start']
                if time.monotonic()-last_ready>=5:
                    assert request(port,nonce,'GET','/_desktop/ready',headers={'X-DLMS-Desktop-Nonce':nonce})[0]==200
                    last_ready=time.monotonic()
                roles=[]
                for pid in descendants(proc.pid):
                    try:
                        info=identity(pid);observed[pid]=info['start'];argv=arguments(pid)
                    except OSError:continue
                    role='launcher' if pid==proc.pid else 'backend' if pid==owner[0] else 'helper'
                    role=next((x.removeprefix('--type=') for x in argv if x.startswith('--type=')),role)
                    roles.append({'pid':pid,'start':info['start'],'role':role})
                roles.sort(key=lambda x:x['pid'])
                if roles!=last:changes.append({'seconds':round(time.monotonic()-started,2),'roles':roles});last=roles
                time.sleep(.5)
            assert request(port,nonce,'POST','/api/shutdown')[0]==200 and proc.wait(timeout=35)==0
            deadline=time.monotonic()+8
            while any(alive(pid,born) for pid,born in observed.items()) and time.monotonic()<deadline:time.sleep(.1)
            assert not any(alive(pid,born) for pid,born in observed.items())
            capture={}
            if a.capture:
                logs=list((data/'shell'/profile/'window-events').glob('*.jsonl'));assert len(logs)==1
                records=[json.loads(x) for x in logs[0].read_text().splitlines()]
                assert any(x['event']=='document' for x in records)
                assert any(x['event']=='backend' and x['pid']==owner[0] for x in records)
                assert not any(x['event']=='renderer-terminated' for x in records)
                start=next(x for x in records if x['event']=='capture-start')
                assert logs[0].stat().st_size<=start.get('byte_limit',128*1024) and len(records)<=start.get('record_limit',1000)
                if start['seconds']>=900:
                    assert all(x.get('utc','').endswith('Z') for x in records)
                    assert records[-1]['event']=='capture-stop'
                if start['seconds']>=1800:
                    from desktop.content_layers import valid_layers
                    assert any(x['event']=='document-state' and valid_layers(x.get('layers')) and x['layers']['shell'] is not None for x in records)
                    assert any(x['event']=='sample' and x.get('content_children') for x in records)
                capture={'records':len(records),'documents':sum(x['event']=='document' for x in records),'renderer_terminations':0}
            result={'normal_executable':str(exe),'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
                    'seconds':a.seconds,'backend_stable':True,'process_changes':changes,'exact_cleanup':True,
                    'desktop_exists':(root/'home/Desktop').is_dir(),'capture':capture,'ui_injection':False,
                    'visual_blanking_measured':False,'owner_manual_acceptance':False}
            (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps({k:v for k,v in result.items() if k not in ('process_changes','normal_executable','sha256')},indent=2))
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=15)

if __name__=='__main__':main()
