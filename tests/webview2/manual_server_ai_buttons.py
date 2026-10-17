"""Manual normal-package walkthrough using captured synthetic DLMS Server pages.

No injected input, renderer hooks or browser override. Existing Study/AI/copy
controls run as served. This limited fixture is not a full DLMS server.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.gate1/windows-native'


def main():
    sys.path.insert(0, str(ROOT))
    p=argparse.ArgumentParser()
    p.add_argument('--exe',type=Path,required=True)
    p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    exe,source,out=a.exe.absolute(),a.fixture.absolute(),a.output.absolute()
    if any(not path.is_relative_to(WORK) for path in (exe,source,out)) or out.exists():
        raise ValueError('Existing project-local candidate/fixture and fresh output required')
    from desktop.windows_files import assert_path
    for path in (exe,source,out):assert_path(path)
    from package_windows_webview2.acceptance import payload_binding
    binding=payload_binding(exe,exe.parents[2]/'payload-inventory.json')
    if source.stat().st_size>10*1024*1024:raise ValueError('Fixture is too large')
    fixture=json.loads(source.read_text())
    if fixture.get('kind')!='dlms-synthetic-ai-pages' or fixture.get('version')!=1:
        raise ValueError('Synthetic captured-page fixture required')
    quiz=fixture['quiz_path']
    if not re.fullmatch(r'/quizzes/[A-Za-z0-9_.-]+\.html',quiz):raise ValueError('Invalid fixture quiz')
    pages={path:base64.b64decode(value,validate=True) for path,value in fixture['pages'].items()}
    if not 1<=len(pages)<=128 or quiz not in pages:raise ValueError('Missing synthetic page')
    static=exe.parent/'_internal/static'
    if not static.is_dir():raise ValueError('Packaged static assets are missing')
    out.mkdir(mode=0o700)
    from package_windows.entry import root_path
    data=root_path(out/'data',create=True)
    records=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def record(self):
            records.append({'local_token_header':bool(self.headers.get('X-DLMS-Desktop-Token') or
                                                       self.headers.get('X-DLMS-Desktop-Nonce'))})
        def respond(self,body,media='application/json'):
            self.send_response(200);self.send_header('Content-Type',media)
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            self.record()
            if self.path=='/':
                self.send_response(302);self.send_header('Location',quiz);self.send_header('Content-Length','0');self.end_headers();return
            body=pages.get(self.path)
            media='application/json' if self.path.startswith(('/api/','/config/','/data/')) else 'text/html; charset=utf-8'
            if self.path.startswith('/static/'):
                path=static/unquote(urlsplit(self.path).path).removeprefix('/static/')
                if path.resolve().is_relative_to(static.resolve()) and path.is_file():
                    assert_path(path);body=path.read_bytes();media=mimetypes.guess_type(path)[0] or 'application/octet-stream'
            if body is None:self.send_error(404);return
            self.respond(body,media)
        def do_POST(self):
            self.record()
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=65536:self.send_error(413);return
            value=json.loads(self.rfile.read(size) or b'{}')
            if self.path=='/api/study/session':
                result={'ok':True,'session':{'sequence':0,'answers':{},'position':0,'assessment_revision':'synthetic-revision'}}
            elif self.path=='/api/learning-events/study-response':result={'ok':True,'event_id':value.get('eventId')}
            else:self.send_error(404);return
            self.respond(json.dumps(result).encode())
    server=ThreadingHTTPServer(('127.0.0.2',0),Handler)
    from desktop.server_mode import default_config,configured_server
    config=default_config('walkserver')
    config.update(mode='server',server=configured_server(config,'http://127.0.0.2:'+str(server.server_port),
        'Synthetic existing AI controls',private_http_opt_in=True))
    shell=data/'shell/walkserver';shell.mkdir(mode=0o700,parents=True)
    (shell/'mode.json').write_text(json.dumps(config))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    process=None;started=time.monotonic()
    print('Normal candidate / synthetic Server only. Enter Study, then Review with AI.\n'
          'Use the existing page button, not a native menu. No automatic paste/submission.\n'
          'Close DLMS normally; fixture expires after15min and never terminates DLMS.',flush=True)
    try:
        with (out/'launcher.log').open('w') as log:
            process=subprocess.Popen([str(exe),'--data-root',str(data),'--profile','walkserver'],
                cwd=out,stdout=log,stderr=subprocess.STDOUT)
            while process.poll() is None and time.monotonic()-started<900:time.sleep(.25)
            if process.poll() is None:print('Fixture expired. Close DLMS normally.',flush=True)
    finally:
        server.shutdown();server.server_close()
        (out/'result.json').write_text(json.dumps({'normal_package':True,'app_test_hooks':False,
            'owner_results':'pending separate report','bounded_partial_server_fixture':True,
            'observed_requests':len(records),'local_token_headers_absent':bool(records) and not any(r['local_token_header'] for r in records),
            'data_root':str(data),'exit':process.poll() if process else None,'app_terminated_by_fixture':False,
            **binding},indent=2)+'\n')


if __name__=='__main__':main()
