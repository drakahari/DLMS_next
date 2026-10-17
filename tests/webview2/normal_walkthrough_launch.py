"""Exact PowerShell walkthrough line, normal package, existing synthetic root.

No profile preparation here: missing/unmarked roots remain errors. No quiz/theme
or Exam writes, renderer hooks, OS input or physical pixel acceptance. Shutdown
uses the owned authenticated backend. All output/profiles/evidence are preserved.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'.gate1/windows-native'

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True)
    p.add_argument('--data-root',type=Path,required=True);p.add_argument('--profile',required=True)
    p.add_argument('--inventory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--expected-workflow',type=Path,help='Read-only checks for an earlier synthetic normal_candidate receipt')
    a=p.parse_args();exe=a.exe.resolve(strict=True);root=a.data_root.resolve(strict=True);out=a.output.absolute()
    if any(not path.is_relative_to(WORK) for path in (exe,root,out)) or out.exists():
        raise ValueError('Existing task-local candidate/root and fresh evidence scope required')
    if not __import__('re').fullmatch('[a-z][a-z0-9_-]{0,31}',a.profile):raise ValueError('Invalid profile')
    from package_windows.entry import root_path
    from package_windows_webview2.acceptance import payload_binding
    from desktop.windows_processes import Job,arguments
    from tests.windows.normal_processes import descendants,identity,alive,backend_nonce
    from tests.windows.normal_candidate import request
    from tests.webview2.normal_server_performance import windows
    root_path(root);out.mkdir(mode=0o700)
    before=payload_binding(exe,a.inventory)
    saved=None
    if a.expected_workflow:
        expected=a.expected_workflow.resolve(strict=True)
        if not expected.is_relative_to(WORK):raise ValueError('Task-local synthetic workflow receipt required')
        saved=json.loads(expected.read_text())['saved']
        if type(saved['quiz']) is not int or saved['quiz']<=0:raise ValueError('Synthetic quiz identity required')
    # Literal owner command, executed as a PowerShell script. PowerShell can
    # return before a GUI command; retain its parent by waiting for its own exact
    # child afterward. This adds no app launch flags or environment hooks.
    command=f"& '{exe.as_posix()}' --data-root '{root.as_posix()}' --profile {a.profile}"
    if "'" in str(exe) or "'" in str(root):raise ValueError('This exact-line harness accepts no quoting ambiguity')
    wait_script=("\n$launched = @(Get-CimInstance Win32_Process -Filter \"ParentProcessId = $PID\" | "
        "Where-Object { $_.ExecutablePath -eq '"+str(exe)+"' })\n"
        "if ($launched.Count -ne 1) { throw 'Expected one exact launched child' }\n"
        "Wait-Process -Id $launched[0].ProcessId\n")
    script=out/'owner-command.ps1';script.write_text(command+wait_script,encoding='utf-8-sig')
    state=root/'profiles'/a.profile;receipt={'normal_package':True,'app_test_hooks':False,
        'physical_acceptance':False,'exam_history_acceptance_started':False,'command':command,
        'data_root':str(root),'profile':a.profile,'profile_existed_before':state.exists(),
        'wrapper_waits_only_exact_direct_child':True,'runs':[],**before}
    (out/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    quiz_path=None
    if saved:
        registry=json.loads((state/'backend/config/quizzes.json').read_text())
        filename=next(row['html'] for row in registry if row['id']==saved['quiz'])
        if not __import__('re').fullmatch(r'[A-Za-z0-9_.-]+\.html',filename):raise ValueError('Unexpected synthetic quiz filename')
        quiz_path='/quizzes/'+filename
    for run in range(2):
        observed={};job=Job();proc=None
        with (out/f'launcher-{run}.log').open('w') as log:
            try:
                proc=subprocess.Popen([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
                    '-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                job.assign(int(proc._handle));started=time.monotonic();launcher=None;nonce=None;native=[]
                end=started+45
                while time.monotonic()<end:
                    assert proc.poll() is None,'PowerShell exact launch exited before owned ready window'
                    pids=descendants(proc.pid)
                    for pid in pids:
                        try:
                            value=identity(pid);observed[pid]=value['start']
                            if value['image']==os.path.normcase(str(exe)):
                                argv=arguments(pid)
                                if argv[1:]==['--data-root',root.as_posix(),'--profile',a.profile]:launcher=pid
                        except OSError:pass
                    if launcher:
                        owner=backend_nonce(launcher,exe)
                        manifest_path=state/'desktop-profile.json'
                        if owner and manifest_path.is_file():
                            manifest=json.loads(manifest_path.read_text());port=manifest['port'];nonce=owner[1]
                            try:
                                ready=request(port,nonce,'GET','/_desktop/ready',headers={'X-DLMS-Desktop-Nonce':nonce})[0]==200
                            except OSError:ready=False
                            native=windows(pids)
                            if ready and any(w['class']=='Chrome_RenderWidgetHostHWND' and w['visible'] for w in native):break
                    time.sleep(.05)
                else:raise TimeoutError('Exact normal PowerShell launch did not become ready with a visible owned renderer')
                ready_seconds=round(time.monotonic()-started,3)
                status,html,_=request(port,nonce,'GET','/');assert status==200 and b'Dashboard' in html
                if saved:
                    for path in ('/library',quiz_path):
                        code,body,_=request(port,nonce,'GET',path)
                        assert code==200 and b'Windows Neutral Quiz' in body,(path,code)
                    code,body,_=request(port,nonce,'GET','/history')
                    assert code==200 and b'/api/attempts' in body
                    code,body,_=request(port,nonce,'GET','/api/attempts/'+saved['attempt'])
                    assert code==200 and 'Windows Neutral Quiz' in json.dumps(json.loads(body))
                    receipt['existing_quiz_library_history_readable']=True
                time.sleep(3)
                assert proc.poll() is None
                assert request(port,nonce,'POST','/api/shutdown')[0]==200
                assert proc.wait(timeout=35)==0
                end=time.monotonic()+5
                while any(alive(pid,born) for pid,born in observed.items()) and time.monotonic()<end:time.sleep(.05)
                survivors=[pid for pid,born in observed.items() if alive(pid,born)]
                assert not survivors
                receipt['runs'].append({'run':run,'normal_launcher_pid':launcher,'ready_seconds':ready_seconds,
                    'uuid':manifest['uuid'],'dashboard_http':status,'visible_native_renderer':True,'normal_shutdown_exit':proc.returncode,'owned_survivors':survivors})
                (out/f'native-windows-{run}.json').write_text(json.dumps(native,indent=2)+'\n')
            finally:
                # Failure cleanup is scoped to this test Job, never an owner PID.
                job.stop()
                if proc:proc.wait(timeout=15)
                (out/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    after=payload_binding(exe,a.inventory);assert before==after
    assert receipt['runs'][0]['uuid']==receipt['runs'][1]['uuid']
    receipt.update(passed=True,payload_verified_before_and_after=True)
    (out/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
