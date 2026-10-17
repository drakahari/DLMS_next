"""App-local Qt boundary/focus/error/progress probes; no global input."""
import argparse,hashlib,json,threading,time,tempfile
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QFileDialog,QMessageBox,QProgressDialog,QPushButton
from tests.gate1.qt_checks import QtChecks
from desktop.server_mode import configured_server,write_config
from desktop import file_selection as fs

class Handler(BaseHTTPRequestHandler):
    uploads=[]
    def do_GET(self):
        body=b'<html><body><h1>Synthetic file receiver</h1><input id="upload" type="file"><iframe src="https://outside.invalid/"></iframe></body></html>'
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
    def do_POST(self):
        Handler.uploads.append((dict(self.headers),self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(200);self.end_headers();self.wfile.write(b'accepted')
    def log_message(self,*a):pass


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    if not a.profile.startswith('filepick'):raise ValueError('Dedicated fixture profile required')
    q=QtChecks(a.profile,automated=True);report={'platform':q.app.platformName(),'physical_input':False};server=None
    root=Path(tempfile.mkdtemp(prefix='dlms-file-boundary-',dir='/tmp'));fixture=root/'ordinary α.txt';fixture.write_bytes(b'Explicitly chosen ordinary file\n')
    timer=QTimer();timer.setInterval(40);decisions=[];answer=[QMessageBox.StandardButton.Cancel];progress=[];cancel_progress=[False];change_consent=[False]
    def dialogs():
        for widget in q.app.topLevelWidgets():
            if isinstance(widget,QMessageBox) and widget.isVisible():
                decisions.append({'title':widget.windowTitle(),'text':widget.text(),'format':str(widget.textFormat())})
                if change_consent[0] and 'Allow selected files' in widget.windowTitle():
                    old_stat=fixture.stat();fixture.write_bytes(b'X'*old_stat.st_size)
                    __import__('os').utime(fixture,ns=(old_stat.st_atime_ns,old_stat.st_mtime_ns));change_consent[0]=False
                widget.done(int(answer[0]))
            if isinstance(widget,QProgressDialog) and widget.isVisible():
                progress.append(widget.labelText())
                if cancel_progress[0]:
                    cancel_progress[0]=False;widget.findChildren(QPushButton)[0].click()
    timer.timeout.connect(dialogs);timer.start()
    old=fs.Snapshots.stage
    try:
        q.go('/upload');page=q.window.view.page();mode=page.FileSelectionMode.FileSelectOpen
        # Invalid and inaccessible choices give a visible actionable plain-text refusal.
        for name,data in [('bad.exe',b'X'),('bad.png',b'not PNG')]:
            bad=root/name;bad.write_bytes(data);q.window.file_selection_for_test=bad
            assert page.chooseFiles(mode,[],[])==[]
            assert 'refused' in q.window.statusBar().currentMessage().lower(),(name,q.window.statusBar().currentMessage(),decisions)
        link=root/'linked.txt';link.symlink_to(fixture);q.window.file_selection_for_test=link
        assert page.chooseFiles(mode,[],[])==[]
        report['visible_refusals']=list(decisions);decisions.clear()
        # Slow copy runs off GUI; heartbeat/dialog stays responsive. Navigation
        # invalidates only this new batch, not an earlier handed-over File.
        q.window.file_selection_for_test=fixture;first=page.chooseFiles(mode,[],[]);assert Path(first[0]).read_bytes()==fixture.read_bytes()
        def slow(store,*args,**kwargs):time.sleep(.4);return old(store,*args,**kwargs)
        fs.Snapshots.stage=slow
        q.window.file_selection_for_test=fixture
        result=page.chooseFiles(mode,[],[])
        assert result and progress
        report['responsive_slow_progress']=len(progress)
        cancel_progress[0]=True;q.window.file_selection_for_test=fixture
        assert page.chooseFiles(mode,[],[])==[]
        assert 'canceled' in q.window.statusBar().currentMessage().lower()
        assert Path(first[0]).read_bytes()==fixture.read_bytes()
        report['progress_cancel_keeps_prior_file']=True
        q.window.file_selection_for_test=fixture
        QTimer.singleShot(100,lambda:q.window.view.setUrl(q.window.view.url().resolved(__import__('PySide6.QtCore',fromlist=['QUrl']).QUrl('/library'))))
        assert page.chooseFiles(mode,[],[])==[]
        assert Path(first[0]).read_bytes()==fixture.read_bytes()
        report['navigation_cancels_only_new_batch']=True
        fs.Snapshots.stage=old
        q.go('/library')
        before=hashlib.sha256((q.paths['backend']/'results.db').read_bytes()).hexdigest()
        server=ThreadingHTTPServer(('127.0.0.2',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        origin=f'http://127.0.0.2:{server.server_port}'
        config=dict(q.window.mode_config,server=configured_server(q.window.mode_config,origin,'Selected-file boundary',private_http_opt_in=True))
        write_config(a.profile,config);q.window.mode_config=config;assert q.window.switch_to_server()
        q.wait("!!document.querySelector('#upload') && document.readyState==='complete'")
        page=q.window.view.page()
        q.window.file_selection_for_test=fixture
        q.click_css('#upload')
        assert q.js('document.querySelector("#upload").files.length')==0
        assert not Handler.uploads and any(origin in x['text'] for x in decisions)
        assert all('PlainText' in x['format'] for x in decisions)
        report['server_default_cancel_no_upload']=True
        decisions.clear();answer[0]=QMessageBox.StandardButton.Yes
        q.window.file_selection_for_test=fixture;q.click_css('#upload')
        q.wait('document.querySelector("#upload").files.length===1')
        assert not Handler.uploads,'Handback itself must not automatically submit in this fixture'
        fixture.write_bytes(b'Changed ordinary source after consent')
        q.js("window.uploaded=null;const form=new FormData();form.append('file',document.querySelector('#upload').files[0]);fetch('/upload',{method:'POST',body:form}).then(r=>window.uploaded=r.status);true")
        q.wait('window.uploaded===200');assert len(Handler.uploads)==1
        headers,body=Handler.uploads[0];assert b'Explicitly chosen ordinary file\n' in body
        assert not any(k.lower().startswith('x-dlms-desktop') for k in headers)
        report['server_explicit_consent_exact_bytes_no_local_token']=True
        answer[0]=QMessageBox.StandardButton.Cancel;q.window.file_selection_for_test=fixture;q.click_css('#upload')
        assert 'canceled' in q.window.statusBar().currentMessage().lower() and len(Handler.uploads)==1
        report['server_cancel_after_success_updates_status']=True
        answer[0]=QMessageBox.StandardButton.Yes;change_consent[0]=True;q.window.file_selection_for_test=fixture;q.click_css('#upload')
        assert 'refused' in q.window.statusBar().currentMessage().lower() and len(Handler.uploads)==1
        report['source_changed_during_server_confirmation_refused']=True
        # Remote chooser cannot select any Local profile journal/export root.
        private=q.paths['root']/'private.txt';private.write_text('Local recovery evidence fixture')
        q.window.file_selection_for_test=private;assert page.chooseFiles(mode,[],[])==[]
        assert len(Handler.uploads)==1
        assert q.window.server_interceptor.blocked or q.window.blocked_urls
        assert q.window.switch_to_local();q.wait("location.pathname==='/' && document.readyState==='complete'")
        assert hashlib.sha256((q.paths['backend']/'results.db').read_bytes()).hexdigest()==before
        assert not Path(first[0]).exists(),'Actual page destruction must retire its sealed descriptors/links'
        report['local_unchanged_remote_frames_blocked_snapshots_retired']=True
        report['pass']=True
    finally:
        fs.Snapshots.stage=old;timer.stop()
        if q.window.mode=='server':q.window.switch_to_local()
        q.close()
        if server:server.shutdown();server.server_close()
        (q.paths['root']/'file-boundary.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
