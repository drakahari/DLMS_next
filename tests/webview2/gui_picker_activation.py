"""One bounded coordinate-vs-gesture activation measurement; no OS input."""
import argparse
import json
from pathlib import Path
import time
import uuid
import sys


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from PySide6.QtCore import QStandardPaths
    from desktop import webview2_file_selection as fs
    from desktop.webview2_shell import DesktopWindow
    from desktop.isolation import PROJECT
    import desktop.shell
    roots=fs._known_private_roots();documents=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
    desktop.shell.DesktopWindow=lambda *a,**k:DesktopWindow(*a,selection_private_roots=roots,documents_folder=documents,**k)
    from tests.gate1.qt_checks import QtChecks
    fixture=PROJECT/'fixtures/webview2-ordinary'/uuid.uuid4().hex;fixture.mkdir(mode=0o700,parents=True)
    source=fixture/'activation 日本語.txt';source.write_bytes((PROJECT/'fixtures/gate1-neutral-quiz.txt').read_bytes())
    q=QtChecks(a.profile,automated=True);events=[];warnings=[];oldwarning=fs._warning
    import PySide6
    report={'source_instrumented':True,'normal_package':False,'physical_input':False,'python_version':sys.version,
            'python_executable':sys.executable,'pyside_version':PySide6.__version__}
    def call(op,**kw):
        replies=[];errors=[];q.window.view.command(op,callback=replies.append,on_error=errors.append,**kw)
        deadline=time.monotonic()+10
        while not replies and not errors and time.monotonic()<deadline:q.delay(.03)
        return {'reply':replies,'errors':errors}
    fs._warning=lambda context,ticket,message:warnings.append(str(message))
    try:
        q.go('/upload');view=q.window.view;original=view._event
        def event(e):
            if e.get('event') in ('file-picker','file-picker-failed','console-warning','scale-state'):events.append(dict(e))
            return original(e)
        view._event=event
        q.js("""window.probeEvents=[];for(const type of ['pointerdown','pointerup','mousedown','mouseup','click'])document.addEventListener(type,e=>window.probeEvents.push({type,target:e.target.tagName,name:e.target.name,trusted:e.isTrusted,x:e.clientX,y:e.clientY,active:navigator.userActivation.isActive,ever:navigator.userActivation.hasBeenActive,defaultPrevented:e.defaultPrevented}),true);document.querySelector('input[name=file]').scrollIntoView({block:'center',behavior:'instant'});true""")
        call('focus');q.delay(.2)
        probe="""(()=>{const e=document.querySelector('input[name=file]'),r=e.getBoundingClientRect(),x=r.x+20,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);return {x,y,rect:{x:r.x,y:r.y,width:r.width,height:r.height},hit:{tag:hit?.tagName,name:hit?.name},ready:document.readyState,focused:document.hasFocus(),active:navigator.userActivation.isActive,dpr:devicePixelRatio,viewport:{width:innerWidth,height:innerHeight},activeElement:{tag:document.activeElement?.tagName,name:document.activeElement?.name}}})()"""
        before=q.js(probe);report['before']=before;report['scale_state']=view.scale_state
        q.window.file_selection_for_test=str(source)
        report['coordinate_reply']=call('click',x=before['x'],y=before['y']);q.delay(2)
        report['after_coordinate']=q.js("({count:document.querySelector('input[name=file]').files.length,events:window.probeEvents,active:navigator.userActivation.isActive,focused:document.hasFocus()})")
        report['coordinate_native_events']=list(events)
        q.window.file_selection_for_test=str(source)
        report['gesture_reply']=call('eval',script="document.querySelector('input[name=file]').click();true",world=0,gesture=True);q.delay(2)
        report['after_direct_gesture']=q.js("({count:document.querySelector('input[name=file]').files.length,events:window.probeEvents,active:navigator.userActivation.isActive,focused:document.hasFocus()})")
        report['native_events']=events;report['warnings']=warnings;report['measurement_complete']=True
    finally:
        fs._warning=oldwarning;q.close();q.delay(.2);report['close_complete']=q.window._close_complete
        (q.paths['root']/'wv-picker-activation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    assert report.get('measurement_complete') and report['close_complete']


if __name__=='__main__':main()
