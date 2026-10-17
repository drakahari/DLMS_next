"""Actual source WebView2 chooser/consent transport; synthetic and instrumented.

No OS input is used. The owned host's renderer-local eval user gesture opens
native picker events (DOM click is untrusted); the harness supplies paths and native
dialog button responses. Physical chooser/focus acceptance remains separate.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import uuid
import sys


class Handler(BaseHTTPRequestHandler):
    requests = []
    uploads = []
    def log_message(self, *args): pass
    def do_GET(self):
        self.requests.append({'path': self.path, 'local_token': bool(self.headers.get('X-DLMS-Desktop-Token') or self.headers.get('X-DLMS-Desktop-Nonce'))})
        body = b'''<html><body><h1>Synthetic ordinary file selection</h1>
        <input id="files" type="file" multiple><input id="other" type="file" multiple>
        <a id="next" href="/next">Next</a><iframe src="/embedded" id="embedded"></iframe>
        <script>document.querySelector('#files').onchange=async e=>{
        const files=await Promise.all([...e.target.files].map(async f=>({name:f.name,bytes:[...new Uint8Array(await f.arrayBuffer())]})));
        const r=await fetch('/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(files)});
        window.uploadComplete=r.ok};</script>
        </body></html>''' if self.path != '/embedded' else b'<html><body><input id="frame-files" type="file"></body></html>'
        self.send_response(200); self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        self.requests.append({'path': self.path, 'local_token': bool(self.headers.get('X-DLMS-Desktop-Token') or self.headers.get('X-DLMS-Desktop-Nonce'))})
        length = int(self.headers.get('Content-Length', '0'))
        assert 0 < length < 65536
        files = json.loads(self.rfile.read(length))
        self.uploads.append([{'name': f['name'], 'size': len(f['bytes']), 'sha256': hashlib.sha256(bytes(f['bytes'])).hexdigest()} for f in files])
        self.send_response(200); self.send_header('Content-Length', '0'); self.end_headers()


def until(q, predicate, text, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        q.delay(.04)
    raise TimeoutError(text)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--profile', required=True); args = parser.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    from PySide6.QtCore import QTimer, QUrl, Qt
    from PySide6.QtWidgets import QMessageBox
    from desktop import webview2_file_selection as fs
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    private_roots = fs._known_private_roots()
    from PySide6.QtCore import QStandardPaths
    documents = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
    desktop.shell.DesktopWindow = lambda *a, **k: DesktopWindow(*a, selection_private_roots=private_roots, documents_folder=documents, **k)
    from desktop.isolation import PROJECT
    from desktop.server_mode import configured_server, write_config
    from tests.gate1.qt_checks import QtChecks

    fixture = PROJECT / 'fixtures/webview2-ordinary' / uuid.uuid4().hex
    fixture.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = fixture / 'Z quiz 日本語.txt'; source.write_bytes((PROJECT / 'fixtures/gate1-neutral-quiz.txt').read_bytes())
    second = fixture / 'a choices é.csv'; second.write_bytes(b'left,right\nfirst,one\n')
    inputs = [source, second]
    expected = [{'name': p.name, 'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in inputs]
    server = ThreadingHTTPServer(('127.0.0.2', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    q, report, dialogs, warnings, stores = None, {'source_instrumented': True, 'normal_package': False, 'physical_acceptance': False,
                                                 'fixture': str(fixture), 'passed': False, 'python_version': sys.version,
                                                 'python_executable': sys.executable}, [], [], []
    import PySide6
    report['pyside_version'] = PySide6.__version__
    original_exec, original_warning, original_stage = QMessageBox.exec, fs._warning, fs._stage
    accept = [False]; during_consent = [None]
    def dialog_exec(box):
        if box.windowTitle() != fs.CONSENT_TITLE: return original_exec(box)
        assert box.textFormat() == Qt.TextFormat.PlainText
        assert box.defaultButton() == box.button(QMessageBox.StandardButton.Cancel)
        assert box.escapeButton() == box.button(QMessageBox.StandardButton.Cancel)
        dialogs.append({'text': box.text(), 'default_cancel': True, 'accepted_by_synthetic_harness': accept[0]})
        if during_consent[0]: during_consent[0]()
        QTimer.singleShot(0, lambda: box.done(QMessageBox.StandardButton.Yes if accept[0] else QMessageBox.StandardButton.Cancel))
        return original_exec(box)
    QMessageBox.exec = dialog_exec
    fs._warning = lambda context, ticket, message: warnings.append(str(message)) or fs._feedback(context, ticket, message, 'error')
    try:
        q = QtChecks(args.profile, automated=True)
        local_manifest = (q.paths['root'] / 'desktop-profile.json').read_bytes()
        q.go('/upload')
        report['local_context_valid'] = fs.SelectionContext.capture(q.window.view.page()).valid()
        protocol = []
        original_event = q.window.view._event
        def observed(event):
            if event.get('event') in ('file-picker', 'file-picker-failed', 'reply', 'console-warning'):
                protocol.append(dict(event))
            return original_event(event)
        q.window.view._event = observed
        report['local_protocol'] = protocol
        q.window.file_selection_for_test = str(source)
        def click(selector):
            q.window.view.command('focus')
            q.js('document.querySelector(' + json.dumps(selector) + ').scrollIntoView({block:"center",behavior:"instant"});true')
            q.delay(.15)
            point = q.js('(()=>{const e=document.querySelector(' + json.dumps(selector) + ');const r=e.getBoundingClientRect();const x=r.x+Math.min(20,r.width/2),y=r.y+r.height/2;const hit=document.elementFromPoint(x,y);return {x,y,hit:hit?.tagName,hitName:hit?.name}})()')
            report['last_click'] = point
            q.window.view.command('eval', script='document.querySelector(' + json.dumps(selector) + ').click();true', world=0, gesture=True)
        click('input[name=file]')
        q.wait("document.querySelector('input[name=file]').files.length===1")
        assert not dialogs
        local_store = q.window.view._selection_store; stores.append(local_store)
        report['local_ordinary_selection'] = True
        origin = f'http://127.0.0.2:{server.server_port}'
        config = dict(q.window.mode_config, server=configured_server(q.window.mode_config, origin, 'Synthetic selection Server', private_http_opt_in=True))
        write_config(args.profile, config); q.window.mode_config = config
        assert q.window.switch_to_server()
        until(q, lambda: q.window.mode == 'server' and q.window.view and not q.window.view.page().isLoading()
              and q.window._server_page_exposed, 'Server not exposed')
        q.wait("Boolean(document.querySelector('#files'))")
        assert local_store.closed and not local_store.path.exists()
        assert q.window.backend is None and (q.paths['root'] / 'desktop-profile.json').read_bytes() == local_manifest
        # First native Server consent uses its actual default Cancel.
        q.window.file_selection_for_test = [str(p) for p in inputs]; click('#files')
        until(q, lambda: len(dialogs) == 1 and q.window._browser_dialog_depth == 0, 'Default consent cancel not completed')
        assert q.js("document.querySelector('#files').files.length") == 0
        assert Handler.uploads == []
        assert q.window.statusBar().currentMessage() == fs.SERVER_CANCELED
        assert q.window.view._selection_store is None
        report['server_default_cancel_no_file_exposure'] = True
        # Explicit source-harness Yes; real browser must read ordered sealed bytes.
        accept[0] = True
        def modal_mode_guard():
            assert q.window._browser_dialog_depth > 0
            assert not q.window.switch_to_local()
            assert q.window.mode == 'server' and q.window.backend is None
        during_consent[0] = modal_mode_guard
        q.window.file_selection_for_test = [str(p) for p in inputs]; click('#files')
        q.wait("document.querySelector('#files').files.length===2")
        until(q, lambda: not q.window.view._pending_file_selections, 'Explicit native applied receipt missing')
        # The refused mode-switch notice was newer than this selection ticket;
        # its successful handback must not overwrite that newer feedback.
        assert 'Finish or cancel' in q.window.statusBar().currentMessage()
        report['newer_mode_switch_notice_preserved'] = True
        during_consent[0] = None
        actual = q.js("""(async()=>{const files=[...document.querySelector('#files').files];window.keptFiles=files;return await Promise.all(files.map(async f=>({name:f.name,size:f.size,sha256:[...new Uint8Array(await crypto.subtle.digest('SHA-256',await f.arrayBuffer()))].map(v=>v.toString(16).padStart(2,'0')).join('')})))})()""")
        assert actual == expected, actual
        q.wait('window.uploadComplete===true')
        assert Handler.uploads == [expected]
        store = q.window.view._selection_store; stores.append(store)
        assert dialogs[-1]['text'] == fs.consent_body(origin, [p.name for p in inputs])
        report.update(server_ordered_browser_files=actual, immediate_server_uploads=Handler.uploads, modal_mode_switch_refused=True)
        source.write_bytes(b'Original changed after immutable snapshot.\n')
        again = q.js("(async()=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',await window.keptFiles[0].arrayBuffer()))].map(v=>v.toString(16).padStart(2,'0')).join(''))()")
        assert again == expected[0]['sha256']
        accept[0] = False
        dialogs_before = len(dialogs)
        q.window.file_selection_for_test = [str(second)]; click('#files')
        until(q, lambda: len(dialogs) > dialogs_before and q.window._browser_dialog_depth == 0, 'Second native consent cancel did not finish')
        assert q.js("document.querySelector('#files').files.length") == 2
        assert Handler.uploads == [expected]
        report['canceled_new_selection_preserves_earlier_files_without_upload'] = True
        accept[0] = True
        # Whole-batch invalid input must not invalidate earlier exposed Files.
        bad = fixture / 'unsupported.exe'; bad.write_bytes(b'synthetic unsupported')
        q.window.file_selection_for_test = [str(source), str(bad)]; click('#other')
        until(q, lambda: bool(warnings), 'Invalid batch feedback missing')
        assert q.js("document.querySelector('#other').files.length") == 0
        assert q.js("document.querySelector('#files').files.length") == 2
        report['invalid_new_batch_preserves_earlier_files'] = True
        # Changing the document during native consent invalidates the captured
        # context; no files are exposed to the new document.
        def stale(): q.window.view._active_generation += 1
        during_consent[0] = stale
        generation = q.window.view._active_generation
        q.window.file_selection_for_test = [str(second)]; click('#other')
        until(q, lambda: q.window.view._active_generation != generation and q.window._browser_dialog_depth == 0,
              'Stale consent did not finish')
        assert q.js("document.querySelector('#other').files.length") == 0
        # Restore only the source-harness generation perturbation, so the
        # actual native navigation generation remains authoritative afterward.
        q.window.view._active_generation = generation
        during_consent[0] = None
        report['stale_consent_no_exposure'] = True
        before = store.path
        q.window.view.setUrl(QUrl(origin + '/next'))
        q.wait("location.pathname==='/next' && document.readyState==='complete'")
        assert before.exists() and not store.closed
        assert q.window.backend is None and not any(r['local_token'] for r in Handler.requests)
        assert (q.paths['root'] / 'desktop-profile.json').read_bytes() == local_manifest
        report.update(retained_across_navigation=True, no_local_token=True, local_identity_unchanged=True, passed=True)
    finally:
        QMessageBox.exec, fs._warning, fs._stage = original_exec, original_warning, original_stage
        if q is not None:
            q.close(); q.delay(.3)
            report['close_complete'] = q.window._close_complete
            report['cleanup_errors'] = [str(error) for store in stores for error in store.cleanup_errors]
            report['all_snapshot_roots_removed'] = all(store.closed and not store.path.exists() for store in stores)
            report['dialogs'] = dialogs; report['warnings'] = warnings
            (q.paths['root'] / 'wv-ordinary-selection.json').write_text(json.dumps(report, indent=2) + '\n')
        server.shutdown(); server.server_close(); thread.join(timeout=3)
    print(json.dumps(report, indent=2), flush=True)
    assert report['passed'] and report['close_complete'] and report['all_snapshot_roots_removed'] and not report['cleanup_errors']


if __name__ == '__main__': main()
