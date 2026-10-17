"""Real Qt attachment cancellation/interruption and unchanged-page error paths."""
import argparse, hashlib, json, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PySide6.QtCore import QUrl
from desktop.server_mode import configured_server, write_config
from tests.gate1.qt_checks import QtChecks


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    q=QtChecks(a.profile,automated=True);report={};release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            if self.path=='/cancel':
                self.send_response(200);self.send_header('Content-Type','text/plain');self.send_header('Content-Disposition','attachment; filename=bounded.txt');self.send_header('Content-Length','100000');self.end_headers()
                try:self.wfile.write(b'synthetic'*1000);self.wfile.flush();release.wait(12)
                except (BrokenPipeError,ConnectionResetError):pass
                self.close_connection=True;return
            if self.path=='/broken':
                self.send_response(200);self.send_header('Content-Type','text/plain');self.send_header('Content-Disposition','attachment; filename=broken.txt');self.send_header('Content-Length','100000');self.end_headers();self.wfile.write(b'partial synthetic');self.wfile.flush();self.close_connection=True;return
            status=400 if self.path=='/refusal' else 200
            body=b'<html><body><h1>Synthetic transfer</h1><a href="/cancel">cancel transfer</a><a href="/broken">broken transfer</a><a href="/refusal">refused request</a><p id="reason">Review the synthetic input.</p></body></html>'
            self.send_response(status);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.2',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    def wait(pred,timeout=20):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            q.delay(.04)
            if pred():return
        raise AssertionError('Transfer checkpoint did not complete: '+repr(q.window.download_results))
    try:
        q.go('/library')
        # A bounded, task-owned destination failure; keep all previous files.
        folder=q.paths['downloads'];preserved=folder.with_name('downloads-preserved');folder.rename(preserved);folder.write_text('synthetic obstruction')
        before=len(q.window.download_results)
        try:
            q.js("document.querySelector('a[href=\"/export/all_quizzes.txt\"]').click();true")
            wait(lambda:'unsafe or unavailable' in q.window.statusBar().currentMessage())
            assert q.window.view.isVisible() and not q.window.settings_fallback.isVisible()
            assert len(q.window.download_results)==before
            report['local_destination_failure']={'page_usable':True,'message':q.window.statusBar().currentMessage()}
        finally:
            folder.rename(folder.with_name('downloads-failure-evidence'));preserved.rename(folder)
        config=dict(q.window.mode_config,server=configured_server(q.window.mode_config,f'http://127.0.0.2:{server.server_port}','Bounded failure fixture',private_http_opt_in=True))
        write_config(a.profile,config);q.window.mode_config=config;assert q.window.switch_to_server()
        q.wait("document.querySelector('#reason') && document.readyState==='complete'")
        db=q.paths['backend']/'results.db';local_before=hashlib.sha256(db.read_bytes()).hexdigest()
        requests=[]
        def observe(r):
            requests.append(r)
            r.stateChanged.connect(lambda state:print('Native download state',r.url().path(),str(state),'finished',r.isFinished(),'reason',r.interruptReasonString(),flush=True))
        q.window.profile.downloadRequested.connect(observe)
        q.js("document.querySelector('a[href=\"/cancel\"]').click();true")
        wait(lambda:requests and q.window._active_outputs() and requests[-1].receivedBytes()>0)
        assert not q.window.switch_to_local(),'An active download must prevent leaving its profile'
        report['pending_switch_refusal']=q.window.statusBar().currentMessage()
        requests[-1].cancel();release.set()
        wait(lambda:q.window.download_results[-1]['state']=='cancelled')
        assert q.window.view.isVisible() and q.window.view.isEnabled() and not q.window.server_unreachable
        report['server_cancel']=dict(q.window.download_results[-1]);assert 'cancelled' in q.window.statusBar().currentMessage()
        q.js("document.querySelector('a[href=\"/broken\"]').click();true")
        wait(lambda:q.window.download_results[-1]['state']=='interrupted')
        assert q.window.view.isVisible() and not q.window.server_unreachable
        report['server_interrupted']=dict(q.window.download_results[-1]);assert 'failed' in q.window.statusBar().currentMessage()
        q.js("document.querySelector('a[href=\"/refusal\"]').click();true")
        q.wait("location.pathname==='/refusal' && document.readyState==='complete'")
        wait(lambda:'HTTP 400' in q.window.statusBar().currentMessage())
        assert q.window._server_page_exposed and q.window.view.isEnabled() and not q.window.server_unreachable
        report['server_http400_visible']=q.window.statusBar().currentMessage()
        server.shutdown();server.server_close();q.window.view.setUrl(QUrl(config['server']['origin']+'/outage'))
        wait(lambda:q.window.server_unreachable)
        assert not q.window._server_page_exposed and q.window.backend is None and q.window.mode=='server'
        assert hashlib.sha256(db.read_bytes()).hexdigest()==local_before
        report['outage_no_fallback_local_unchanged']=True
        (q.paths['root']/'download-faults.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:
        release.set();q.close();server.shutdown();server.server_close()
if __name__=='__main__':main()
