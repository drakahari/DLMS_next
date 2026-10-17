"""Instrumented actual WebView2 exports; selection-boundary injection, no OS input.

This checks real backend/renderer download bytes and publication. Native folder
navigation is covered separately by gui_file_locations; neither establishes
physical owner acceptance or normal-package native input acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time


SERVER_BYTES = b'1. Synthetic Server question?\nA. First\nC. Third\nCorrect Answer: C\n'


class SyntheticServer(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *_): pass

    def do_GET(self):
        type(self).requests.append({'path': self.path, 'headers': dict(self.headers)})
        if self.path.startswith('/export/'):
            body, content_type = SERVER_BYTES, 'text/plain; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Disposition', 'attachment; filename=server-reference.txt')
        else:
            body = (b'<html><body><input id="typing"><a id="download" href="/export/library.txt">'
                    b'Download Quiz Library Reference</a><a id="next" href="/next">Next</a></body></html>')
            content_type = 'text/html; charset=utf-8'
            self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)


def until(q, predicate, description, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        q.delay(.05)
    raise TimeoutError(description)


def semantics(backend, quiz_id):
    with sqlite3.connect(backend / 'results.db') as connection:
        questions = connection.execute('SELECT id,question_number,question_text FROM questions WHERE quiz_id=? ORDER BY question_number,id', (quiz_id,)).fetchall()
        return [{'number': number, 'text': text, 'choices': connection.execute(
            'SELECT label,text,is_correct FROM choices WHERE question_id=? ORDER BY choice_order,label,id', (identifier,)).fetchall()}
            for identifier, number, text in questions]


def main():
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--operation', choices=('flows', 'reopen'), default='flows')
    parser.add_argument('--oracle', type=Path)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, exist_ok=False)
    def stage(value):
        with (args.output / 'stages.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'stage': value, 'monotonic': time.monotonic()})+'\n')
        print(value, flush=True)
    watchdog = threading.Timer(150, lambda: (stage('owned-watchdog-timeout'), os._exit(124)))
    watchdog.daemon = True; watchdog.start()
    from desktop.webview2_file_selection import _known_private_roots
    from desktop.webview2_shell import DesktopWindow
    from desktop.webview2_browser import View
    from desktop import windows_backup_chooser as native
    from desktop.webview2_exports import PREFERENCE, initial_directory, forbidden_roots
    from desktop.isolation import profile_paths, PROJECT
    import desktop.shell
    private_roots = _known_private_roots()
    old_factory, old_chooser, old_event = desktop.shell.DesktopWindow, native.choose_export, View._event
    protocol = []
    def event(view, value):
        if value.get('event') in ('download', 'blob-download', 'download-blocked', 'attachment-declined', 'navigation-blocked'):
            protocol.append(dict(value))
        return old_event(view, value)
    View._event = event
    oracle = json.loads(args.oracle.read_text(encoding='utf-8')) if args.operation == 'reopen' else None
    if oracle:
        documents, downloads = Path(oracle['documents']), Path(oracle['downloads'])
    else:
        documents = args.output / 'Redirected Documents 日本語'
        downloads = args.output / 'Real Downloads ü'
        documents.mkdir(mode=0o700); downloads.mkdir(mode=0o700)
        if profile_paths(args.profile, create=False)['root'].exists():
            raise ValueError('A fresh synthetic profile is required; existing evidence is not reused')
    desktop.shell.DesktopWindow = lambda *a, **kw: DesktopWindow(*a, documents_folder=documents,
        backup_chooser_folders=(documents, downloads), selection_private_roots=private_roots, **kw)
    from tests.gate1.qt_checks import QtChecks
    from desktop.server_mode import configured_server, write_config
    server = ThreadingHTTPServer(('127.0.0.2', 0), SyntheticServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    q, calls, pending = None, [], []
    report = {'instrumented': True, 'frozen': bool(getattr(sys, 'frozen', False)),
              'normal_package': False, 'physical_acceptance': False,
              'selection_boundary_injected': True, 'actual_native_navigation': False,
              'operation': args.operation, 'exports': []}
    def chooser(owner, filename, folders, **kw):
        assert pending, 'Unexpected destination chooser'
        item = pending.pop(0)
        calls.append({'filename': filename, 'initial': str(kw.get('initial')), 'title': kw.get('title'),
                      'mode': owner.mode, 'expected_initial': str(item['initial']),
                      'dialog_depth': owner._browser_dialog_depth})
        assert Path(kw['initial']) == item['initial'], calls[-1]
        assert owner._browser_dialog_depth == 1
        assert owner._browser_operation_depth == 1
        return (str(item['path']) if item['path'] else '', '')
    native.choose_export = chooser
    try:
        stage('startup'); q = QtChecks(args.profile, automated=True)
        report['runtime'] = q.window.webview2_runtime_version
        def click(selector):
            q.js('document.querySelector('+json.dumps(selector)+').scrollIntoView({block:"center"});true')
            point = json.loads(q.js('JSON.stringify((()=>{const r=document.querySelector('+json.dumps(selector)+').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())'))
            assert q.js('document.elementFromPoint('+str(point['x'])+','+str(point['y'])+').closest('+json.dumps(selector)+')!==null'), (selector, point)
            q.window.view.command('click', x=point['x'], y=point['y'])
        def export(selector, path, expected_initial, expected_state='completed', expected_bytes=None):
            index = len(q.window.download_results)
            before_document = q.js('performance.timeOrigin')
            pending.append({'path': path, 'initial': expected_initial})
            click(selector)
            until(q, lambda: len(q.window.download_results) > index and
                  q.window.download_results[index]['state'] != 'in_progress', 'Export did not terminate')
            assert not pending, 'Expected destination chooser was skipped'
            record = dict(q.window.download_results[index])
            assert record['state'] == expected_state, record
            until(q, lambda: q.window.view.isEnabled() and not q.window.view.page().isLoading()
                  and (q.window.mode != 'server' or q.window._server_page_exposed),
                  'Attachment did not restore the usable page')
            assert q.js('performance.timeOrigin') == before_document
            assert q.window.view.isEnabled() and not q.window._browser_dialog_depth
            assert not q.window._browser_operation_depth
            if q.window.mode == 'server':
                assert not q.window.server_unreachable and q.window._server_page_exposed and q.window.backend is None
            if expected_state == 'completed':
                data = Path(record['path']).read_bytes()
                assert Path(record['staging_path']).read_bytes() == data
                if expected_bytes is not None: assert data == expected_bytes
                assert hashlib.sha256(data).hexdigest() == record['sha256']
                assert Path(record['path']) == path
            elif expected_state == 'cancelled':
                assert record['path'] == ''
            report['exports'].append(record | {'same_document': True,
                'active_after': q.window.isActiveWindow(), 'view_focus_after': q.window.view.hasFocus(),
                'document_focus_after': q.js('document.hasFocus()')})
            return record
        def upload(content, title, variable):
            q.js("""(()=>{const form=new FormData();form.append('file',new File([CONTENT],'Export roundtrip 日本語.txt',{type:'text/plain'}));form.append('quiz_title',TITLE);
              const token=decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='))?.split('=')[1]||'');form.append('csrf_token',token);
              fetch('/process',{method:'POST',body:form,headers:{'X-CSRFToken':token}}).then(r=>window[VARIABLE]=r.status);return true;})()"""
                 .replace('CONTENT', json.dumps(content)).replace('TITLE', json.dumps(title)).replace('VARIABLE', json.dumps(variable)))
            q.wait('window['+json.dumps(variable)+']===200', 35)
        q.go('/library')
        if oracle:
            stage('reopen-preference')
            assert json.loads((q.paths['root']/PREFERENCE).read_text()) == oracle['local_preference']
            export('a[href="/export/all_quizzes.txt"]', None, Path(oracle['remembered_directory']), 'cancelled')
            assert json.loads((q.paths['root']/PREFERENCE).read_text()) == oracle['local_preference']
            report['separate_process_reopen_remembers_successful_directory'] = True
        else:
            stage('synthetic-import')
            upload((PROJECT/'fixtures'/'gate1-neutral-quiz.txt').read_text(encoding='utf-8'), 'Export location synthetic quiz', '__locationImport')
            q.go('/library'); q.wait("document.body.innerText.includes('Export location synthetic quiz')")
            with sqlite3.connect(q.paths['backend']/'results.db') as connection:
                quiz_id = connection.execute('SELECT id FROM quizzes ORDER BY id').fetchone()[0]
            original_semantics = semantics(q.paths['backend'], quiz_id)
            individual_selector = 'a[href="/export/quiz/'+str(quiz_id)+'.txt"]'
            library_selector = 'a[href="/export/all_quizzes.txt"]'
            custom = args.output/'User chosen exports 日本語'; custom.mkdir(mode=0o700)
            first = custom/'Individual quiz ü.txt'
            stage('local-individual-first')
            export(individual_selector, first, downloads)
            single_data = first.read_text(encoding='utf-8')
            assert 'What is two plus two?' in single_data and 'Correct Answer: B' in single_data
            preference = (q.paths['root']/PREFERENCE).read_bytes()
            stage('local-library-reference')
            reference = custom/'Library reference.txt'
            export(library_selector, reference, custom)
            text = reference.read_text(encoding='utf-8')
            assert '# Import compatible: No' in text and 'Export location synthetic quiz' in text
            assert text.index('What is two plus two?') < text.index('Which shape has three sides?') < text.index('Which word names a color?') < text.index('Which item is a fruit?')
            stage('local-cancel-and-collision')
            before = sorted(str(p) for p in custom.iterdir())
            export(library_selector, None, custom, 'cancelled')
            assert sorted(str(p) for p in custom.iterdir()) == before
            digest = hashlib.sha256(first.read_bytes()).hexdigest()
            export(individual_selector, first, custom, 'failed')
            assert hashlib.sha256(first.read_bytes()).hexdigest() == digest
            assert (q.paths['root']/PREFERENCE).read_bytes() == preference
            export(individual_selector, custom/'Repeated quiz.txt', custom)
            stage('local-byte-and-semantic-roundtrip')
            upload(single_data, 'Export reimport synthetic quiz', '__locationReimport')
            with sqlite3.connect(q.paths['backend']/'results.db') as connection:
                imported_id = connection.execute('SELECT id FROM quizzes ORDER BY id DESC').fetchone()[0]
            assert imported_id != quiz_id and semantics(q.paths['backend'], imported_id) == original_semantics
            q.go('/library')
            stage('unavailable-remembered-directory')
            temporary = args.output/'Temporary chosen folder'; temporary.mkdir(mode=0o700)
            export(individual_selector, temporary/'Before folder move.txt', custom)
            temporary.rename(args.output/'Preserved moved folder')
            saved_unavailable = (q.paths['root']/PREFERENCE).read_bytes()
            export(library_selector, None, downloads, 'cancelled')
            assert (q.paths['root']/PREFERENCE).read_bytes() == saved_unavailable
            export(library_selector, custom/'Final remembered reference.txt', downloads)
            local_preference = json.loads((q.paths['root']/PREFERENCE).read_text())
            local_preference_bytes = (q.paths['root']/PREFERENCE).read_bytes()
            stage('synthetic-local-blob-fresh-document')
            # Host40's unchanged exact-document check can decline a Blob
            # following attachment pseudo-navigation (retained source01/02
            # evidence). Exercise its supported fresh-document path here.
            q.go('/library')
            blob_bytes = b'Actual renderer Blob synthetic export\n'
            q.js("(()=>{const a=document.createElement('a');a.id='location-blob';a.download='blob-export.txt';a.href=URL.createObjectURL(new Blob(["+json.dumps(blob_bytes.decode())+"],{type:'text/plain'}));a.textContent='Synthetic blob export';a.style.cssText='position:fixed;left:300px;top:200px;z-index:999999;padding:20px;background:white;color:black';document.body.append(a);return true;})()")
            export('#location-blob', custom/'Local Blob.txt', custom, expected_bytes=blob_bytes)
            assert (q.paths['root']/PREFERENCE).read_bytes() == local_preference_bytes
            stage('server-isolated-first')
            local_rows = semantics(q.paths['backend'], quiz_id)
            origin = f'http://127.0.0.2:{server.server_port}'
            config = dict(q.window.mode_config, server=configured_server(q.window.mode_config, origin,
                          'Synthetic export Server', private_http_opt_in=True))
            write_config(args.profile, config); q.window.mode_config = config
            assert q.window.switch_to_server()
            until(q, lambda: q.window.mode == 'server' and q.window._server_page_exposed and not q.window.view.page().isLoading(), 'Server did not become ready')
            q.wait("Boolean(document.getElementById('download'))")
            remote = args.output/'Server selected exports'; remote.mkdir(mode=0o700)
            first_remote = remote/'Server export.txt'
            export('#download', first_remote, downloads, expected_bytes=SERVER_BYTES)
            assert origin in calls[-1]['title']
            server_preference = (q.window.server_paths['root']/PREFERENCE).read_bytes()
            export('#download', None, remote, 'cancelled')
            export('#download', first_remote, remote, 'failed')
            assert first_remote.read_bytes() == SERVER_BYTES
            export('#download', remote/'Second Server export.txt', remote, expected_bytes=SERVER_BYTES)
            from PySide6.QtCore import QUrl
            q.window.view.setUrl(QUrl(origin+'/next'))
            until(q, lambda: q.window._server_page_exposed and not q.window.view.page().isLoading()
                  and q.window.view.url().path() == '/next', 'Fresh Server document did not load')
            q.js("(()=>{const a=document.createElement('a');a.id='location-blob';a.download='blob-export.txt';a.href=URL.createObjectURL(new Blob(["+json.dumps(blob_bytes.decode())+"],{type:'text/plain'}));a.textContent='Synthetic blob export';a.style.cssText='position:fixed;left:300px;top:200px;z-index:999999;padding:20px;background:white;color:black';document.body.append(a);return true;})()")
            export('#location-blob', remote/'Server Blob.txt', remote, expected_bytes=blob_bytes)
            assert (q.window.server_paths['root']/PREFERENCE).read_bytes() == server_preference
            assert (q.paths['root']/PREFERENCE).read_bytes() == local_preference_bytes
            assert all('x-dlms-desktop-token' not in {key.lower() for key in row['headers']} for row in SyntheticServer.requests)
            request_data = json.dumps(SyntheticServer.requests)
            assert custom.name not in request_data and remote.name not in request_data
            assert q.window.settings_panel is None and q.window.backend is None
            stage('explicit-return-local')
            assert q.window.switch_to_local()
            until(q, lambda: q.window.mode == 'local' and q.window.backend is not None and q.window.view is not None
                  and not q.window.view.page().isLoading(), 'Local did not return')
            q.wait("document.readyState==='complete' && location.pathname==='/' && Boolean(document.querySelector('.dashboard-sidebar'))", 35)
            assert semantics(q.paths['backend'], quiz_id) == local_rows
            assert (q.paths['root']/PREFERENCE).read_bytes() == local_preference_bytes
            oracle = {'documents': str(documents), 'downloads': str(downloads),
                      'remembered_directory': str(custom), 'local_preference': local_preference,
                      'quiz_id': quiz_id, 'question_semantics': original_semantics}
            (args.output/'oracle.json').write_text(json.dumps(oracle, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            report.update(exact_staged_bytes_published=True, single_export_reimport_semantics_match=True,
                library_reference_order_preserved=True, local_server_preferences_separate=True,
                cancel_no_user_file=True, collision_no_replace=True, unavailable_folder_falls_back=True,
                no_local_token_or_destination_disclosed=True)
        report['passed'] = True; stage('complete')
    except BaseException as exc:
        report['error'] = repr(exc)
        raise
    finally:
        native.choose_export = old_chooser; desktop.shell.DesktopWindow = old_factory; View._event = old_event
        if q is not None:
            report['status'] = q.window.statusBar().currentMessage()
            q.close(); q.delay(.3)
            until(q, lambda: q.window._close_complete, 'Normal close did not finish', 20)
            report['close_complete'] = q.window._close_complete
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        watchdog.cancel()
        report['chooser_calls'] = calls
        report['server_requests'] = SyntheticServer.requests
        report['download_protocol'] = protocol
        (args.output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    assert report.get('passed') and report['close_complete']
    return 0


if __name__ == '__main__': raise SystemExit(main())
