"""Application-local attachment lifecycle regression, separate from physical input."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

from desktop.server_mode import configured_server, write_config
from tests.gate1.qt_checks import QtChecks

PAYLOAD=b'1. Synthetic question?\nA. First\nC. Third\nCorrect Answer: A\n'


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path.startswith('/redirect/'):
            targets={'/redirect/page':'/next','/redirect/attachment':'/export/all_quizzes.txt','/redirect/failure':'/unavailable'}
            self.send_response(302);self.send_header('Location',targets[self.path]);self.send_header('Content-Length','0');self.end_headers();return
        if self.path=='/unavailable':
            self.send_error(503);return
        if self.path.startswith('/export/'):
            self.send_response(200)
            self.send_header('Content-Type','text/plain')
            self.send_header('Content-Disposition','attachment; filename=synthetic-reference.txt')
            self.send_header('Content-Length',str(len(PAYLOAD)+(100 if 'broken' in self.path else 0)))
            self.end_headers();self.wfile.write(PAYLOAD)
            if 'broken' in self.path:self.close_connection=True
            return
        body=b'<html><body><a href="/export/all_quizzes.txt" id="download">Download Quiz Library Reference</a><a href="/next" id="next">Next</a></body></html>'
        self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--expect-bug',action='store_true')
    p.add_argument('--case',choices=('success','cancel','interrupted','destination-error'),default='success');a=p.parse_args()
    server=ThreadingHTTPServer(('127.0.0.2',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    q=QtChecks(a.profile,automated=True);events=[];report={}
    try:
        origin=f'http://127.0.0.2:{server.server_port}'
        config=dict(q.window.mode_config,server=configured_server(q.window.mode_config,origin,'Attachment fixture',private_http_opt_in=True))
        write_config(a.profile,config);q.window.mode_config=config
        assert q.window.switch_to_server()
        q.wait("document.readyState==='complete' && Boolean(document.querySelector('#download'))")
        q.delay(.5);page=q.window.view.page()
        page.loadStarted.connect(lambda:events.append({'event':'start','url':page.url().toString(),'requested':page.requestedUrl().toString()}))
        page.loadFinished.connect(lambda ok:events.append({'event':'finish','ok':ok,'url':page.url().toString(),'requested':page.requestedUrl().toString()}))
        page.loadingChanged.connect(lambda info:events.append({'event':'information','status':info.status().name,'download':info.isDownload(),'error':info.errorCode(),'url':info.url().toString(),'requested':page.requestedUrl().toString()}))
        q.window.profile.downloadRequested.connect(lambda req:events.append({'event':'download','url':req.url().toString(),'same_page':req.page() is page}))
        if a.case=='cancel':q.window.profile.downloadRequested.connect(lambda req:req.cancel())
        original_check=None
        if a.case=='destination-error':
            import desktop.shell as shell
            original_check=shell.assert_safe_leaf
            def refuse_destination(path):
                if path.is_relative_to(q.window.server_paths['downloads']):raise OSError('Synthetic destination unavailable')
                return original_check(path)
            shell.assert_safe_leaf=refuse_destination
        if a.case=='interrupted':q.js("document.querySelector('#download').href='/export/broken.txt';true")
        before=q.js('performance.timeOrigin')
        q.js("document.querySelector('#download').click();true")
        deadline=time.monotonic()+45
        while (not any(r['state']!='in_progress' for r in q.window.download_results)
                and not (a.case=='destination-error' and 'destination is unavailable' in q.window.statusBar().currentMessage())
                and time.monotonic()<deadline):q.delay(.05)
        q.delay(.7)
        report={'source_instrumented':True,'physical_acceptance':False,'events':events,
            'same_document':before==q.js('performance.timeOrigin'),
            'server_unreachable':q.window.server_unreachable,'page_exposed':q.window._server_page_exposed,
            'view_visible':q.window.view.isVisible(),'view_enabled':q.window.view.isEnabled(),
            'message':q.window.statusBar().currentMessage(),'downloads':q.window.download_results}
        expected={'success':'completed','cancel':'cancelled','interrupted':'failed','destination-error':'unavailable'}[a.case]
        if a.case=='destination-error':assert not q.window.download_results and 'unavailable' in report['message']
        else:assert any(r['state']==expected for r in q.window.download_results),report
        if a.case=='success':assert Path(q.window.download_results[-1]['path']).read_bytes()==PAYLOAD
        if a.expect_bug:assert report['server_unreachable'] and not report['page_exposed']
        else:
            assert not report['server_unreachable'] and report['page_exposed'] and report['view_enabled']
            assert expected in report['message'],report['message']
            assert report['same_document']
            assert not list(q.paths['downloads'].iterdir())
            if a.case=='success':
                first=Path(q.window.download_results[-1]['path']);first_bytes=first.read_bytes()
                q.js("location.href='/redirect/attachment';true");q.delay(1)
                assert len(q.window.download_results)==2
                second=Path(q.window.download_results[-1]['path'])
                assert first!=second and first.read_bytes()==first_bytes==second.read_bytes()
                assert not q.window.server_unreachable and q.window._server_page_exposed
                report['redirect_attachment_repeated_no_overwrite']=True
            q.js("location.href='/redirect/page';true");q.wait("location.pathname==='/next' && document.readyState==='complete'")
            q.delay(.2);assert not q.window.server_unreachable
            q.js("location.href='/redirect/failure';true");q.delay(.7)
            assert q.window.server_unreachable and not q.window._server_page_exposed
            report['later_navigation_works']=True;report['real_503_still_unavailable']=True
    finally:
        if locals().get('original_check') is not None:shell.assert_safe_leaf=original_check
        (q.paths['root']/'attachment-lifecycle.json').write_text(json.dumps(report,indent=2)+'\n')
        q.close();server.shutdown();server.server_close();thread.join(timeout=5)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
