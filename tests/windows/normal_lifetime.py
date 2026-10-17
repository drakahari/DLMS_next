"""External normal-package crash cleanup and imported-profile reopen checks."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import time

from tests.windows.normal_candidate import request,ROOT
from tests.windows.normal_processes import descendants,identity,alive,backend_nonce
from tests.settings.gui_native_roundtrip import facts

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--profile',required=True);p.add_argument('--oracle',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();exe=args.exe.resolve(strict=True);data=args.data.absolute();out=args.output.absolute()
    if not data.is_relative_to(ROOT/'.gate1/windows-native') or not out.is_relative_to(ROOT/'.gate1/windows-native') or out.exists():
        raise ValueError('Task-owned synthetic paths and a fresh evidence file required')
    oracle=json.loads(args.oracle.read_text());records=[];state=data/'profiles'/args.profile
    for crash in (True,False):
        env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','QTWEBENGINE_','PYTHON'))}
        env['PATH']=str(out.parent/'no-host-tools')
        proc=subprocess.Popen([str(exe),'--data-root',str(data),'--profile',args.profile],env=env,cwd=exe.parent)
        observed={proc.pid:identity(proc.pid)['start']}
        try:
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                assert proc.poll() is None
                owner=backend_nonce(proc.pid,exe)
                if owner:
                    manifest=json.loads((state/'desktop-profile.json').read_text());port=manifest['port'];nonce=owner[1]
                    if request(port,nonce,'GET','/_desktop/ready',headers={'X-DLMS-Desktop-Nonce':nonce})[0]==200:break
                time.sleep(.1)
            else:raise TimeoutError('Normal package readiness')
            assert facts(state/'backend')==oracle
            for pid in descendants(proc.pid):
                try:observed[pid]=identity(pid)['start']
                except OSError:pass
            if crash:proc.kill();proc.wait(timeout=15)
            else:
                assert request(port,nonce,'POST','/api/shutdown')[0]==200
                assert proc.wait(timeout=35)==0
            deadline=time.monotonic()+8
            while any(alive(pid,born) for pid,born in observed.items()) and time.monotonic()<deadline:time.sleep(.1)
            assert not any(alive(pid,born) for pid,born in observed.items())
            records.append({'forced_owner_exit':crash,'facts_equal':True,'owned_descendants_gone':True})
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=15)
    out.write_text(json.dumps({'normal_executable':str(exe),'instrumented':False,'physical_acceptance':False,'runs':records},indent=2)+'\n')
    print('Normal imported-profile/crash/reopen/owned-job cleanup passed')

if __name__=='__main__':main()
