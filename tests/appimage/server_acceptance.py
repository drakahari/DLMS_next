"""Final normal AppImage connects only to a synthetic loopback Server.

Mode fixtures are changed while closed. Native selector activation remains
source/instrumented or owner evidence, not claimed from this normal smoke.
"""
import argparse,json,os,subprocess,time,threading,uuid,hashlib
from pathlib import Path
from urllib.parse import quote
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from tests.package.normal_local_settings_smoke import backend_nonce,descendants,starttime,stop_exact_owned

class Handler(BaseHTTPRequestHandler):
    seen=[]
    exercise_navigation=False
    def do_GET(self):
        self.seen.append({'path':self.path,'local_token_present':bool(self.headers.get('X-DLMS-Desktop-Token'))})
        if self.path.startswith('/__perf_page_ready?'):
            self.send_response(204);self.end_headers();return
        body=b'<!doctype html><title>Synthetic AppImage Server</title><h1>Server-only quiz</h1><p>Different synthetic history. No Local privileges.</p>'
        if self.exercise_navigation:
            routes=['/','/library','/history','/certifications','/it','/study-packs']
            next_path=routes[routes.index(self.path)+1] if self.path in routes[:-1] else None
            onward='setTimeout(()=>location.href='+json.dumps(next_path)+',80);' if next_path else ''
            body+=('<div class="dashboard-sidebar" data-theme="ethereal"></div><style>body{background:#060b1e;color:#ffd0a8}</style><script>console.error("DLMS normal navigation sentinel error");console.warn("DLMS normal navigation sentinel warning");fetch("/__perf_page_ready?path="+encodeURIComponent(location.pathname)).then(()=>{'+onward+'});</script>').encode()
            self.send_response(200);self.send_header('Permissions-Policy','camera=(), geolocation=(), microphone=(), payment=(), usb=()');self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass


def main():
    p=argparse.ArgumentParser();p.add_argument('--exercise-navigation',action='store_true');p.add_argument('--image',required=True,type=Path);p.add_argument('--normal-evidence',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();out=a.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    base=a.normal_evidence.absolute();data=base/'data/dlms-desktop-appimage-test';profile='appimage01';local=data/'profiles'/profile/'backend'
    def hashes():return {str(p.relative_to(local)):hashlib.sha256(p.read_bytes()).hexdigest() for p in local.rglob('*') if p.is_file()}
    before=hashes();assert before
    Handler.exercise_navigation=a.exercise_navigation
    env={'PATH':'/nonexistent','FUSERMOUNT_PROG':'/usr/bin/fusermount3','LANG':'C.UTF-8','QT_QPA_PLATFORM':'offscreen'}
    for k,leaf in [('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp'),('XDG_RUNTIME_DIR','runtime')]:env[k]=str(base/leaf)
    server=ThreadingHTTPServer(('127.0.0.2',0),Handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    origin=f'http://127.0.0.2:{server.server_port}';identifier=str(uuid.uuid4());mode=data/'shell'/profile/'mode.json';mode.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    config={'version':1,'profile':profile,'mode':'server','server':{'id':identifier,'label':'Synthetic AppImage Server','origin':origin,'private_http':True}};mode.write_text(json.dumps(config));mode.chmod(0o600)
    results=[]
    try:
        for phase in ['connected','outage-reopen']:
            if phase=='outage-reopen':server.shutdown();server.server_close();t.join(timeout=5)
            count=len(Handler.seen)
            with (out/f'{phase}.log').open('w') as log:
                proc=subprocess.Popen([str(a.image.absolute()),'--profile',profile],env=env,cwd=out,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);known={proc.pid:starttime(proc.pid)}
                try:
                    deadline=time.monotonic()+30;desc=mode.parent/'instance-owner.json'
                    while time.monotonic()<deadline:
                        assert proc.poll() is None
                        known.update({pid:starttime(pid) for pid in descendants(proc.pid)})
                        if desc.exists() and (phase!='connected' or len(Handler.seen)>count):break
                        time.sleep(.1)
                    else:raise TimeoutError(phase)
                    if phase=='connected' and a.exercise_navigation:
                        expected=['/','/library','/history','/certifications','/it','/study-packs']
                        deadline=time.monotonic()+15
                        while time.monotonic()<deadline:
                            if all(any(row['path']=='/__perf_page_ready?path='+quote(path,safe='') for row in Handler.seen[count:]) for path in expected):break
                            assert proc.poll() is None;time.sleep(.04)
                        else:raise TimeoutError('Normal package navigation acknowledgments')
                    else:time.sleep(.8)
                    assert backend_nonce(proc.pid) is None,'Server launched Local writer'
                    assert hashes()==before,'Server altered Local dataset'
                    assert json.loads(mode.read_text())==config
                    assert not any(x['local_token_present'] for x in Handler.seen)
                    assert (data/'server-profiles'/identifier/'web/storage').is_dir()
                    results.append({'phase':phase,'requests':len(Handler.seen)-count,'local_backend_absent':True,'local_files_unchanged':True,'server_mode_retained':True,'local_token_absent':True})
                finally:
                    # Normal server-close warning is retained. No invented remote
                    # save knowledge: exact task-owned termination for this smoke.
                    assert not stop_exact_owned(proc,known)
        if a.exercise_navigation:
            text=(out/'connected.log').read_text()
            assert text.count("js: Error with Permissions-Policy header: Unrecognized feature: 'payment'.")==1
            assert text.count("js: Error with Permissions-Policy header: Unrecognized feature: 'usb'.")==1
            assert text.count('js: DLMS normal navigation sentinel error')==6
            assert text.count('js: DLMS normal navigation sentinel warning')==6
        config['mode']='local';mode.write_text(json.dumps(config));assert hashes()==before
        (out/'result.json').write_text(json.dumps({'normal_final_AppImage':True,'console_navigation_checks':a.exercise_navigation,'remote_headers_unchanged':True,'origin':origin,'checks':results,'server_close':'controlled task-owned termination, not native-confirmation acceptance','switching':'closed configuration fixtures; guarded selector source tests separately','local_backend_hashes':before},indent=2)+'\n')
        print('Normal AppImage synthetic Server connection/outage/reopen, token and Local-data isolation passed')
    finally:
        server.server_close()
        if t.is_alive():server.shutdown();t.join(timeout=5)

if __name__=='__main__':main()
