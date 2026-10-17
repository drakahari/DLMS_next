"""Bounded source integration diagnosis, never normal-package acceptance."""
import argparse,json,os,time
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from desktop.isolation import profile_paths,isolated_environment,PROJECT
    paths=profile_paths(a.profile);environment=isolated_environment(paths)
    os.environ.clear();os.environ.update(environment);os.environ['DLMS_DESKTOP_AUTOMATED']='1'
    from PySide6.QtWidgets import QApplication
    from desktop.webview2_shell import DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    app=QApplication([]);window=DesktopWindow(paths,a.profile)
    q=object.__new__(QtChecks);q.app=app;q.window=window;q.paths=paths
    out=PROJECT/'.gate1/windows-native'/(a.profile+'-startup.jsonl')
    assert not out.exists()
    window.show();window.start();last=None;ready=False
    with out.open('x',encoding='utf-8',buffering=1) as stream:
        for i in range(90):
            view=window.view
            state={'second':i,'failed':window.failed_reason,'backend_ready':window.ready_ms,'view':view is not None}
            if view is not None:
                state.update(stage=getattr(view,'startup_stage',None),ready=view._ready,
                    process_state=str(view.process.state()) if view.process else None,
                    queue=len(view._queue),callbacks=len(view._callbacks),url=view.url().toString(),
                    loading=view.page().isLoading(),events=list(getattr(view,'protocol_events',[])),
                    stderr=bytes(view._stderr).decode('utf-8','replace'))
            stream.write(json.dumps(state)+'\n')
            if state!=last:print(json.dumps({k:v for k,v in state.items() if k!='events'}),flush=True)
            last=state
            if window.failed_reason:break
            if view is not None and view._ready and not view.page().isLoading() and view.url().path()=='/':
                result=q.js("document.readyState==='complete' && Boolean(document.querySelector('.dashboard-sidebar'))",3)
                if result:ready=True;break
            q.delay(1)
        print('Initial WebView2 document verified: '+str(ready),flush=True)
        if ready:
            print(json.dumps({'runtime':window.view.runtime_info,'viewport':q.js('JSON.stringify({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})')}),flush=True)
        window.close();q.delay(1)
        print('Close complete: '+str(window._close_complete),flush=True)
    if not ready or not window._close_complete:raise RuntimeError('Source startup/close not verified; retain evidence')

if __name__=='__main__':main()
