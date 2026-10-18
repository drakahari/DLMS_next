"""Normal frozen Local/Server startup with stale component metadata.

Only task-owned synthetic storage is edited while closed. No machine Runtime
is hidden/removed, no app hooks or injected browser commands are used. The
removed case models the persisted tuple after Evergreen cleanup. Server cleanup
uses the retained launcher handle; no normal/physical Server close is claimed.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from package_windows_webview2.acceptance import payload_binding
from tests.windows.normal_candidate import request
from tests.windows.normal_processes import alive, backend_nonce, descendants, identity, arguments
from tests.webview2.normal_server_performance import windows
from tests.settings.gui_native_roundtrip import facts

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'.gate1/windows-native'
FAMILY=Path('C:/Program Files (x86)/Microsoft/EdgeWebView/Application')
COMPONENTS={'dgiklkfkllikcanfonkcabmbdfmgleag':'edge_clipboard',
            'mhjfbmdgcfjbbpaeojofohoefgiehjai':'edge_pdf'}


def seed(storage,version,out):
    rows=[]
    for path in storage.rglob('Secure Preferences'):
        original=path.read_bytes();data=json.loads(original)
        settings=data.get('extensions',{}).get('settings',{})
        for key,resource in COMPONENTS.items():
            if key in settings:
                assert settings[key]['location']==5
                settings[key]['path']=str(FAMILY/version/'resources'/resource)
                rows.append({'id':key,'version':version,'resource':resource})
        (out/('before-seed-'+str(len(rows))+'.json')).write_bytes(original)
        path.write_text(json.dumps(data),encoding='utf-8')
    assert len(rows)==2,rows
    return rows


def launch(exe,data,profile,mode,output,observed_page):
    env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','QTWEBENGINE_','WEBVIEW2_','PYTHON'))}
    result={'mode':mode,'normal_executable':True,'app_test_hooks':False,'physical_acceptance':False}
    observed={};proc=None;nonce=None;port=None
    with (output/'launcher.log').open('w') as log:
        try:
            proc=subprocess.Popen([str(exe),'--data-root',str(data),'--profile',profile],cwd=output,env=env,stdout=log,stderr=subprocess.STDOUT)
            end=time.monotonic()+45
            while time.monotonic()<end:
                assert proc.poll() is None,'Normal launcher exited before ready'
                pids=descendants(proc.pid)
                for pid in pids:
                    try:observed[pid]=identity(pid)['start']
                    except OSError:pass
                ready=False
                if mode=='local':
                    owner=backend_nonce(proc.pid,exe)
                    manifest=data/'profiles'/profile/'desktop-profile.json'
                    if owner and manifest.exists():
                        nonce=owner[1];port=json.loads(manifest.read_text())['port']
                        try:ready=request(port,nonce,'GET','/_desktop/ready',headers={'X-DLMS-Desktop-Nonce':nonce})[0]==200
                        except OSError:pass
                else:ready=observed_page.is_set()
                native=windows(pids)
                if ready and any(row['class']=='Chrome_RenderWidgetHostHWND' and row['visible'] for row in native):break
                time.sleep(.05)
            else:raise TimeoutError('Normal packaged runtime-transition readiness')
            time.sleep(2)
            assert proc.poll() is None
            if mode=='server':
                assert not (data/'profiles'/profile).exists()
                for pid in descendants(proc.pid):
                    try:
                        if identity(pid)['image']==os.path.normcase(str(exe)):
                            assert arguments(pid)[1:3]!=['--desktop-worker','backend']
                    except OSError:pass
            result['visible_owned_renderer']=True
            if mode=='local':
                assert request(port,nonce,'POST','/api/shutdown')[0]==200
                assert proc.wait(timeout=35)==0
                result['normal_authenticated_shutdown']=True
            else:
                # Let Chromium publish its initial preferences before retained-
                # handle cleanup. The normal Server close confirmation is never
                # bypassed or counted as physical acceptance by this harness.
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    try:
                        files=list((data/'server-profiles').rglob('Secure Preferences'))
                        settings=json.loads(files[0].read_text(encoding='utf-8')).get('extensions',{}).get('settings',{}) if len(files)==1 else {}
                        if all(key in settings for key in COMPONENTS):break
                    except (OSError,ValueError):pass
                    time.sleep(.1)
                else:raise TimeoutError('Synthetic Server initial component metadata not published')
                result['component_metadata_published_before_cleanup']=True
                proc.kill();proc.wait(timeout=15)
                result['retained_handle_forced_server_cleanup']=True
            result['passed']=True
        finally:
            if proc and proc.poll() is None:proc.kill();proc.wait(timeout=15)
            end=time.monotonic()+10
            while any(alive(p,b) for p,b in observed.items()) and time.monotonic()<end:time.sleep(.05)
            result['survivors']=[p for p,b in observed.items() if alive(p,b)]
            (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
            assert not result['survivors']
    return result


def main():
    p=argparse.ArgumentParser()
    for name in ('exe','inventory','local-data-root','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();exe=args.exe.resolve(strict=True);data=args.local_data_root.resolve(strict=True);out=args.output.absolute()
    if any(not path.is_relative_to(WORK) for path in (exe,data,out)) or out.exists():raise ValueError('Fresh task-local synthetic evidence required')
    out.mkdir(mode=0o700);binding=payload_binding(exe,args.inventory);results=[]
    original=facts(data/'profiles/normal01/backend')
    for version in ('155.0.4283.45','155.0.4283.46'):
        if version.endswith('.46'):assert not (FAMILY/version).exists()
        case=out/('local-'+version);case.mkdir(mode=0o700)
        seed(data/'profiles/normal01/web/storage/webview2',version,case)
        results.append(launch(exe,data,'normal01','local',case,None))
        assert facts(data/'profiles/normal01/backend')==original
    observed_page=threading.Event();requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            requests.append({'local_token_present':bool(self.headers.get('X-DLMS-Desktop-Token') or self.headers.get('X-DLMS-Desktop-Nonce'))})
            body=b"<!doctype html><title>Synthetic runtime transition</title><h1>Synthetic Server</h1><script>addEventListener('load',()=>fetch('/ready',{method:'POST'}));</script>"
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_POST(self):
            assert self.path=='/ready';observed_page.set();self.send_response(204);self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.2',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        # A separate short, fresh task-local root avoids the pre-existing native
        # COM failure at deeply nested browser-storage paths. Retain that failed
        # long-path control separately; never weaken the application's guards.
        root=WORK/('sr-'+uuid.uuid4().hex[:8]);root.mkdir(mode=0o700)
        (root/'.dlms-desktop-windows-candidate.json').write_text(json.dumps({'kind':'dlms-desktop-windows-candidate','version':1}))
        profile='runtime-server';shell=root/'shell'/profile;shell.mkdir(parents=True,mode=0o700)
        config={'version':1,'profile':profile,'mode':'server','server':{'id':str(uuid.uuid4()),'label':'Synthetic runtime fixture','origin':f'http://127.0.0.2:{server.server_port}','private_http':True}}
        (shell/'mode.json').write_text(json.dumps(config))
        config_before=(shell/'mode.json').read_bytes()
        for version in (None,'155.0.4283.45','155.0.4283.46'):
            case=out/('server-'+str(version));case.mkdir(mode=0o700);observed_page.clear()
            if version:seed(root/'server-profiles',version,case)
            results.append(launch(exe,root,profile,'server',case,observed_page))
            assert (shell/'mode.json').read_bytes()==config_before
        assert not any(row['local_token_present'] for row in requests)
    finally:server.shutdown();server.server_close();thread.join(5)
    assert binding==payload_binding(exe,args.inventory)
    (out/'result.json').write_text(json.dumps({'passed':True,'normal_package':True,'results':results,'binding':binding,
        'server_data_root':str(root),
        'local_portable_facts_preserved':True,'server_no_local_fallback_or_credential':True,
        'removed_case':'Synthetic persisted metadata names actually absent version; no machine Runtime removed'},indent=2)+'\n')
    print('Normal packaged Local/Server retained/absent historical metadata startup passed; no physical graphics/focus or Server normal-close acceptance claimed.')


if __name__=='__main__':main()
