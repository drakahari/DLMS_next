"""Actual captured Review -> Anki blob -> private publication; synthetic source."""
import argparse
import hashlib
import json
import sqlite3
import time
import zipfile
import re


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--profile', required=True)
    parser.add_argument('--host-build', default='webview2-host-candidate-40')
    args = parser.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    from desktop.isolation import PROJECT
    from desktop import webview2_browser as browser
    if re.fullmatch(r'webview2-host-candidate-[0-9]{2}', args.host_build) is None: raise ValueError('Task-local host build required')
    executable = PROJECT / '.gate1/windows-native' / args.host_build / 'payload/DLMS-WebView2-Host.exe'
    from package_windows_webview2.build import verify_host
    verify_host(executable.parent)
    browser.host_executable = lambda: executable
    from desktop.webview2_file_selection import _known_private_roots
    private_roots = _known_private_roots()
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow = lambda *a, **k: DesktopWindow(*a, selection_private_roots=private_roots, **k)
    from tests.gate1.qt_checks import QtChecks
    from tests.windows.normal_candidate import request, multipart
    q = QtChecks(args.profile, automated=True)
    report = {'source_instrumented': True, 'normal_package': False, 'physical_acceptance': False}
    report.update(host_build=args.host_build, host_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
    def until(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(): return
            q.delay(.06)
        raise TimeoutError('Synthetic Anki export did not reach its checkpoint')
    events = []
    original = q.window.view._event
    def record(event):
        if event.get('event') != 'reply': events.append(dict(event))
        return original(event)
    q.window.view._event = record
    try:
        port, nonce = q.window.port, q.window.nonce
        headers = {'Origin': f'http://127.0.0.1:{port}', 'Sec-Fetch-Site': 'same-origin', 'X-DLMS-CSRF-Refresh': '1'}
        status, body, response = request(port, nonce, 'GET', '/api/csrf-token', headers=headers)
        assert status == 200
        csrf = json.loads(body)['csrf_token']
        headers.update(Cookie='; '.join(x.split(';', 1)[0] for x in response['_set_cookies']), **{'X-CSRFToken': csrf})
        payload, media = multipart('file', 'neutral.txt', 'text/plain', (PROJECT / 'fixtures/gate1-neutral-quiz.txt').read_bytes(),
                                   {'quiz_title': 'Synthetic blob fidelity', 'csrf_token': csrf})
        assert request(port, nonce, 'POST', '/process', payload, headers | {'Content-Type': media})[0] in (200, 302)
        q.go('/library'); q.wait("Boolean(document.querySelector('a[href^=\"/quizzes/\"]'))")
        q.go(q.js("document.querySelector('a[href^=\"/quizzes/\"]').getAttribute('href')"))
        q.wait('quizRecoveryReady===true')
        q.js("window.confirm=()=>true;document.querySelector('.exam-mode-btn').click();true")
        q.wait("Boolean(document.getElementById('submitBtn'))")
        q.js("document.getElementById('submitBtn').click();true")
        def saved():
            with sqlite3.connect(q.paths['backend'] / 'results.db') as db:
                return db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1
        until(saved)
        q.go('/history'); q.wait("Boolean(document.querySelector('a[href^=\"/review?\"]'))")
        q.go(q.js("document.querySelector('a[href^=\"/review?\"]').getAttribute('href')"))
        q.wait("document.querySelectorAll('.anki-select').length===4")
        q.js("document.getElementById('ankiSelectAll').click();true")
        expected = q.js("[...document.querySelectorAll('.anki-select:checked')].map(e=>Number(e.dataset.qnum))")
        assert len(expected) == 4
        stamp = q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
        index = len(events)
        # The separate embedded coordinate-route diagnostic currently drops
        # events before DOM delivery. This explicit CDP user-activation probe
        # exercises the real control/receiver, never physical input acceptance.
        q.window.view.command('eval', world=0, gesture=True,
                              script="document.querySelector('[onclick*=exportMissedAnkiApkg]').click();true")
        until(lambda: any(item['state'] == 'completed' for item in q.window.download_results))
        result = next(item for item in q.window.download_results if item['state'] == 'completed')
        from pathlib import Path
        exported = Path(result['path'])
        assert exported.suffix == '.apkg' and exported.is_file()
        with zipfile.ZipFile(exported) as archive:
            assert archive.testzip() is None
            collection = q.paths['tmp'] / 'synthetic-export-collection.anki2'
            with collection.open('xb') as stream: stream.write(archive.read('collection.anki2'))
        with sqlite3.connect(collection) as db:
            fields = [row[0] for row in db.execute('SELECT flds FROM notes ORDER BY id')]
        with sqlite3.connect(q.paths['backend'] / 'results.db') as db:
            questions = [row[0] for row in db.execute('SELECT question_text FROM questions ORDER BY question_number')]
            answers = list(db.execute('SELECT q.question_text,c.text FROM questions q JOIN choices c ON c.question_id=q.id WHERE c.is_correct=1 ORDER BY q.question_number,c.choice_order'))
        assert len(fields) == len(questions) == 4
        assert all(any(question in item for item in fields) for question in questions)
        assert all(any(question in item.split('\x1f')[0] and answer in item.split('\x1f')[1]
                       for item in fields) for question, answer in answers)
        assert stamp == q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
        assert not [e for e in events[index:] if e.get('event') in ('load-start', 'navigation-blocked', 'download-blocked')]
        assert any(e.get('event') == 'download' and e.get('blob') is True for e in events[index:])
        report.update(passed=True, exact_captured_anki_control=True, notes=4, all_question_texts_present=True,
                      correct_answers_present_on_matching_backs=True,
                      activation='owned CDP eval gesture; DOM click is untrusted',
                      page_preserved=True, sha256=hashlib.sha256(exported.read_bytes()).hexdigest(), output=str(exported))
        report['runtime'] = q.window.view.runtime_info
    finally:
        q.close(); q.delay(.3); report['close_complete'] = q.window._close_complete
        report['events'] = events
        (q.paths['root'] / 'wv-blob-export.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'events'}, indent=2), flush=True)
    assert report.get('passed') and report['close_complete']


if __name__ == '__main__': main()
