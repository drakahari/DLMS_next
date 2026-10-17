"""Normal artifact Server attachment navigation, no native/test hook injection.

Only our synthetic remote document self-navigates; it cannot call native APIs.
Local state is prepopulated by normal_acceptance and must stay byte-identical.
"""
import argparse,hashlib,json,os,subprocess,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from tests.package.normal_local_settings_smoke import descendants,starttime,stop_exact_owned


def hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}

def main():
    p=argparse.ArgumentParser();p.add_argument('--image',type=Path,required=True);p.add_argument('--normal-evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    base=a.normal_evidence.absolute();data=base/'data/dlms-desktop-appimage-test';profile='appimage01';local=data/'profiles'/profile
    assert json.loads((base/'result.json').read_text())['normal_final_AppImage']
    local_before=hashes(local/'backend');assert local_before
    payload=b'Bounded synthetic quiz reference\nA. First\nB. Second\nCorrect Answer: B\n';reports=[]
    script="""let n=0;const fire=()=>{document.querySelector('#export').click();n++;setTimeout(()=>fetch('/report',{method:'POST',body:JSON.stringify({n,visible:document.visibilityState,url:location.pathname,session:localStorage.getItem('syntheticSession')})}).then(()=>{if(n<3)setTimeout(fire,120)}),300)};localStorage.setItem('syntheticSession',localStorage.getItem('syntheticSession')||'server-only');setTimeout(fire,100);"""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            if self.path=='/download':
                self.send_response(200);self.send_header('Content-Disposition','attachment; filename=synthetic-reference.txt');self.send_header('Content-Type','text/plain');body=payload
            else:
                self.send_response(200);self.send_header('Content-Type','text/html');body=('<html><body><div class="dashboard-sidebar" data-theme="ethereal"></div><h1>Synthetic Server only</h1><a id="export" href="/download">Download</a><script>'+script+'</script></body></html>').encode()
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_POST(self):
            assert self.path=='/report';reports.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));self.send_response(204);self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.2',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    sid=str(uuid.uuid4());shell=data/'shell'/profile;mode=shell/'mode.json';original=mode.read_bytes() if mode.exists() else None;config=json.loads(original) if original is not None else dict(version=1,profile=profile,mode='local',server=None)
    config.update(mode='server',server=dict(id=sid,label='Synthetic normal downloads',origin=f'http://127.0.0.2:{server.server_port}',private_http=True))
    mode.write_text(json.dumps(config));mode.chmod(0o600)
    env={'PATH':'/nonexistent','LANG':'C.UTF-8','QT_QPA_PLATFORM':'wayland','FUSERMOUNT_PROG':'/usr/bin/fusermount3'}
    for key in ['DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP']:
        if key in os.environ:env[key]=os.environ[key]
    for k,leaf in [('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp')]:env[k]=str(base/leaf)
    runs=[]
    try:
        for index in range(2):
            before=len(reports)
            with (out/f'launch-{index}.log').open('w') as log:
                proc=subprocess.Popen([str(a.image.absolute()),'--profile',profile],env=env,cwd=out,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);known={proc.pid:starttime(proc.pid)}
                try:
                    end=time.monotonic()+35
                    while time.monotonic()<end:
                        assert proc.poll() is None
                        known.update({pid:starttime(pid) for pid in descendants(proc.pid)})
                        files=list((data/'server-profiles'/sid/'downloads').glob('download-*/*.txt'))
                        if len(reports)>=before+3 and len(files)>=(index+1)*3:break
                        time.sleep(.05)
                    else:raise AssertionError('Normal Server downloads did not complete')
                    assert all(p.read_bytes()==payload for p in files)
                    assert all(r['visible']=='visible' and r['url']=='/' and r['session']=='server-only' for r in reports[before:])
                    assert not any(b'--desktop-worker\0backend' in (Path('/proc')/str(pid)/'cmdline').read_bytes() for pid in descendants(proc.pid) if (Path('/proc')/str(pid)/'cmdline').exists())
                    assert hashes(local/'backend')==local_before
                    runs.append(dict(index=index,downloads=len(files),all_hashes_equal=True,page_visible_after_each=True,server_session_retained=True,local_backend_absent=True,local_hashes_unchanged=True))
                finally:
                    # Normal Server has no shutdown API: exact task-owned process
                    # termination is cleanup, not an orderly Server-close claim.
                    assert not stop_exact_owned(proc,known)
            assert hashes(local/'backend')==local_before
        (out/'result.json').write_text(json.dumps(dict(normal_artifact=str(a.image),runs=runs,remote_dom_reports=reports,scope='Synthetic remote page automation only; no native GUI test hooks. Server launcher exact termination, not window close.'),indent=2)+'\n')
        print('Normal Server repeated TXT/navigation/storage/isolation passed')
    finally:
        mode.write_bytes(original) if original is not None else mode.unlink();server.shutdown();server.server_close()
if __name__=='__main__':main()
