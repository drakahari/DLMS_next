"""Bounded fresh synthetic source/unchanged normal-package request-gate controls.

The Server fixture uses ordinary web scripts, no browser debugging/native APIs.
Normal runs use no app test hook or input synthesis. Owned test Jobs are stopped
at completion; that is resource cleanup, not normal-close/save acceptance.
"""
import argparse,hashlib,json,os,subprocess,sys,threading,time,uuid
from pathlib import Path
from .request_lifecycle_fixture import Fixture,CASES

ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser();p.add_argument('--engine',choices=('source','normal'),required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path);p.add_argument('--host',type=Path)
    p.add_argument('--case',choices=CASES,required=True);p.add_argument('--count',type=int,default=16)
    p.add_argument('--body-bytes',type=int,default=1024*1024);p.add_argument('--delay-ms',type=int,default=5)
    p.add_argument('--wait-held',action='store_true',help='Source-only marked diagnostic seam')
    p.add_argument('--profile',required=True);a=p.parse_args()
    if a.wait_held and (a.engine!='source' or not a.host or not (a.host.parent.parent/'AI-RACE-PROBE').is_file()):
        raise ValueError('Held control requires its separately marked source host')
    out=a.output.absolute()
    if not out.is_relative_to(ROOT/'.gate1/windows-native') or out.exists():raise ValueError('Fresh task-local evidence required')
    if not 1<=a.count<=32 or not 0<=a.body_bytes<=1024*1024 or not 0<=a.delay_ms<=500:raise ValueError('Bounded control required')
    out.mkdir(mode=0o700);fixture=Fixture(a.case,a.count,a.body_bytes,a.delay_ms,a.wait_held)
    threading.Thread(target=fixture.serve_forever,daemon=True).start()
    origin='http://127.0.0.2:'+str(fixture.server_port)
    from desktop.windows_processes import Job
    from tests.windows.normal_processes import descendants,identity,alive
    from tests.webview2.normal_server_performance import windows,native_uncovered
    proc=window=app=job=stream=None;observed={};events=[];samples=[];started=time.monotonic()
    report={'engine':a.engine,'normal_package':a.engine=='normal','app_test_hooks':False,
        'physical_acceptance':False,'case':a.case,'count':a.count,'body_bytes':a.body_bytes,'delay_ms':a.delay_ms}
    try:
        if a.engine=='normal':
            if a.exe is None:raise ValueError('Normal executable required')
            exe=a.exe.resolve(strict=True);report['exe_sha256']=hashlib.sha256(exe.read_bytes()).hexdigest()
            data=out/'data';data.mkdir(mode=0o700)
            (data/'.dlms-desktop-windows-candidate.json').write_text(json.dumps({'kind':'dlms-desktop-windows-candidate','version':1}))
            shell=data/'shell'/a.profile;shell.mkdir(mode=0o700,parents=True)
            (shell/'mode.json').write_text(json.dumps({'version':1,'profile':a.profile,'mode':'server','server':{
                'id':str(uuid.uuid4()),'label':'Synthetic request lifecycle','origin':origin,'private_http':True}}))
            env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','PYTHON','QTWEBENGINE_'))}
            stream=(out/'launcher.log').open('w');proc=subprocess.Popen([str(exe),'--data-root',str(data),'--profile',a.profile],
                env=env,cwd=out,stdout=stream,stderr=subprocess.STDOUT)
            job=Job();job.assign(int(proc._handle));launcher=proc.pid
        else:
            import package_windows_webview2;package_windows_webview2.ACTIVE=True
            from desktop.isolation import profile_paths
            from desktop.server_mode import default_config,configured_server,write_config
            if profile_paths(a.profile,create=False)['root'].exists():raise ValueError('Fresh source profile required')
            config=default_config(a.profile);config.update(mode='server',server=configured_server(config,origin,'Synthetic request lifecycle',private_http_opt_in=True));write_config(a.profile,config)
            import desktop.webview2_browser as browser
            browser.host_executable=lambda:a.host.resolve(strict=True)
            report['host_sha256']=hashlib.sha256(a.host.read_bytes()).hexdigest()
            original=browser.View._event
            def event(view,value):
                if value.get('event')!='reply':events.append(dict(value))
                if value.get('event')=='request-probe-held':fixture.held.set()
                return original(view,value)
            browser.View._event=event
            from desktop.webview2_shell import DesktopWindow
            import desktop.shell;desktop.shell.DesktopWindow=DesktopWindow
            from tests.gate1.qt_checks import QtChecks
            q=QtChecks(a.profile,automated=True);window,app=q.window,q.app;launcher=os.getpid()
        ready=False;host_seen=False;terminal=None;finished_at=None;deadline=time.monotonic()+50
        while time.monotonic()<deadline:
            if app:app.processEvents()
            if proc and proc.poll() is not None:terminal='launcher-exited';break
            pids=descendants(launcher)
            for pid in pids:
                if pid not in observed:
                    try:observed[pid]=identity(pid)['start']
                    except OSError:pass
            views=[]
            if a.engine=='normal':
                from desktop.windows_processes import arguments
                for pid in pids:
                    try:
                        # The same EXE also runs a short --runtime-version
                        # prerequisite probe. Only the real stdin renderer,
                        # with no role arguments, establishes this lifetime.
                        found=identity(pid)
                        if (Path(found['image']).name.lower()=='dlms-webview2-host.exe'
                                and len(arguments(pid))==1):views.append(pid)
                    except (OSError,ValueError):pass
            if views:host_seen=True
            if a.engine=='normal' and host_seen and not views:terminal='native-host-retired';break
            own_windows=windows(pids);samples.append({'at':time.monotonic(),'windows':own_windows})
            if not ready:
                ready=bool(window._server_page_exposed) if window else native_uncovered(own_windows)
                if ready:fixture.armed.set()
            if window and window.failed_reason:terminal='native-fatal';break
            if any(r['kind']=='mark' and r['value']=='finished' for r in fixture.snapshot()):
                if finished_at is None:finished_at=time.monotonic()
                # A new page can finish before old paused requests resolve.
                # Observe the trailing lifecycle instead of closing over it.
                if time.monotonic()-finished_at>=2:
                    terminal='fixture-finished';break
            time.sleep(.02)
        report.update(terminal=terminal or 'timeout',armed=ready,post_finish_observation_seconds=2,seconds=round(time.monotonic()-started,3))
    finally:
        fixture.armed.set();fixture.held.set()
        report['fixture_records']=fixture.snapshot();report['events']=events;report['native_windows']=samples[-200:]
        if window:
            host=int(window.view.process.processId()) if window.view and window.view.process else 0
            owned_ids=descendants(host) if host else set()
            for pid in owned_ids:
                try:observed[pid]=identity(pid)['start']
                except OSError:pass
            window.close();end=time.monotonic()+20
            while not window._close_complete and time.monotonic()<end:app.processEvents();time.sleep(.02)
            report['source_close_complete']=window._close_complete
            observed.pop(os.getpid(),None)
        if job:job.stop()
        if proc:proc.wait(timeout=15)
        if stream:stream.close()
        fixture.shutdown();fixture.server_close()
        end=time.monotonic()+5
        while any(alive(pid,born) for pid,born in observed.items()) and time.monotonic()<end:time.sleep(.02)
        report['owned_survivors']=[pid for pid,born in observed.items() if alive(pid,born)]
        report['server_local_token_absent']=not any(r.get('local_token') or r.get('ai_tag') for r in report['fixture_records'])
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report.get(k) for k in ('engine','case','terminal','armed','seconds','owned_survivors','server_local_token_absent')}),flush=True)

if __name__=='__main__':main()
