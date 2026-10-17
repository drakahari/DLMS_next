"""Black-box HTTP-backed qualification of the normal private macOS .app.

Run from normal Terminal. This launches a real renderer but controls only its
exact owned loopback backend. It does not claim physical renderer, chooser,
Cmd-Q, browser opening, Server mode or native Settings acceptance.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))
from desktop import macos_processes as native
from desktop.macos_paths import MARKER, prepare_root, real_home

PROFILE = 'macnormal'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def wait_for(operation, seconds=40):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            result = operation()
            if result:
                return result
        except (OSError, ValueError, KeyError) as exc:
            last = type(exc).__name__
        time.sleep(0.1)
    raise TimeoutError('Bounded package check timed out' + (f' ({last})' if last else ''))


def children(pid):
    library = native._library()
    function = library.proc_listchildpids
    function.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    function.restype = ctypes.c_int
    count = function(pid, None, 0)
    require(count >= 0, 'Cannot enumerate task-owned child processes')
    values = (ctypes.c_int * (count + 64))()
    count = function(pid, values, ctypes.sizeof(values))
    require(0 <= count < len(values), 'Child enumeration is incomplete')
    return [value for value in values[:count] if value > 0]


def live(found):
    try:
        current = native.identity(found['pid'])
        return native._same_birth(found, current) and current['status'] != 5
    except ProcessLookupError:
        return False


def native_quit_request(found, executable):
    """Ask only the exact launched NSRunningApplication to quit normally.

    No event tap, keystroke, accessibility grant, AppleScript, forceTerminate,
    or bundle-name lookup is used. Successful delivery is not proof of exit.
    """
    require(sys.platform == 'darwin' and live(found), 'Native Quit target is not the captured live launcher')
    ctypes.CDLL('/System/Library/Frameworks/AppKit.framework/AppKit')
    objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p

    def send(receiver, selector, restype, argument_types=(), arguments=()):
        # objc_msgSend is variadic at the C boundary; each selector receives
        # its exact ABI signature instead of mutating a shared ctypes callable.
        invoke = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argument_types)(
            ('objc_msgSend', objc))
        return invoke(receiver, objc.sel_registerName(selector), *arguments)

    pool = send(objc.objc_getClass(b'NSAutoreleasePool'), b'new', ctypes.c_void_p)
    require(pool, 'Cannot establish native Quit autorelease lifetime')
    try:
        application = send(objc.objc_getClass(b'NSRunningApplication'),
                           b'runningApplicationWithProcessIdentifier:', ctypes.c_void_p,
                           (ctypes.c_int,), (found['pid'],))
        require(application, 'Exact launched application is not registered with AppKit')
        pid = send(application, b'processIdentifier', ctypes.c_int)
        require(pid == found['pid'], 'Native Quit application PID differs from this launcher')
        url = send(application, b'executableURL', ctypes.c_void_p)
        require(url, 'Native Quit target has no executable identity')
        path = send(url, b'path', ctypes.c_void_p)
        require(path, 'Native Quit target has no executable path')
        value = send(path, b'UTF8String', ctypes.c_char_p)
        require(value and Path(os.fsdecode(value)).resolve() == executable.resolve(),
                'Native Quit target executable differs from the normal app')
        require(live(found), 'Native Quit target exited or changed birth before dispatch')
        # Objective-C BOOL is a C bool on arm64; PID is int32_t and objects/
        # selectors are pointer-sized. terminate is the non-forcing AppKit API.
        sent = send(application, b'terminate', ctypes.c_bool)
        require(sent, 'AppKit refused to deliver the normal native Quit request')
        return {'method': 'NSRunningApplication.terminate', 'exact_pid': found['pid'],
                'request_delivered': True, 'physical_cmd_q_tested': False}
    finally:
        send(pool, b'drain', None)


class SameOrigin(HTTPRedirectHandler):
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, request, response, code, message, headers, url):
        require(urlsplit(url).scheme + '://' + urlsplit(url).netloc == self.origin,
                'Refused redirect outside the task-owned loopback origin')
        return super().redirect_request(request, response, code, message, headers, url)


class Client:
    def __init__(self, port, nonce):
        require(1024 <= port <= 65535, 'Invalid task-owned backend port')
        self.origin = f'http://127.0.0.1:{port}'
        self.nonce = nonce
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies), SameOrigin(self.origin))

    def request(self, path, *, data=None, content_type=None, method=None, recovery=False, raw=False, headers=None):
        require(path.startswith('/') and not path.startswith('//'), 'Only local paths are allowed')
        head = {'X-DLMS-Desktop-Token': self.nonce, 'X-DLMS-Desktop-Nonce': self.nonce,
                'Sec-Fetch-Site': 'same-origin'}
        if data is not None:
            head['Origin'] = self.origin
            token = next((unquote(cookie.value) for cookie in self.cookies if cookie.name == 'dlms_csrf_token'), None)
            if token:
                head['X-CSRFToken'] = token
        if content_type:
            head['Content-Type'] = content_type
        if recovery:
            head['X-DLMS-Recovery-Client'] = '1'
        if headers:
            head.update(headers)
        request = Request(self.origin + path, data=data, headers=head, method=method)
        with self.opener.open(request, timeout=90) as response:
            body = response.read()
            result = {'status': response.status, 'path': urlsplit(response.url).path,
                      'type': response.headers.get('Content-Type', ''), 'body': body}
        if raw:
            return result
        if 'application/json' in result['type']:
            return json.loads(body)
        return result

    def json(self, path, value, *, recovery=False):
        return self.request(path, data=json.dumps(value).encode(), content_type='application/json', recovery=recovery)

    def multipart(self, path, fields, files=()):
        boundary = 'dlmsmac' + secrets.token_hex(16)
        parts = []
        for key, value in fields.items():
            for item in (value if isinstance(value, list) else [value]):
                parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                          str(item).encode(), b'\r\n']
        for key, file, media in files:
            parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{file.name}"\r\nContent-Type: {media}\r\n\r\n'.encode(),
                      file.read_bytes(), b'\r\n']
        parts += [f'--{boundary}--\r\n'.encode()]
        return self.request(path, data=b''.join(parts), content_type='multipart/form-data; boundary=' + boundary)


def database_snapshot(path):
    tables = ('quizzes', 'questions', 'choices', 'study_sessions', 'study_responses', 'learning_events')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
        return {table: connection.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables}


def fixtures_checked(folder):
    require(folder.is_absolute() and folder.is_dir() and not folder.is_symlink(), 'Fixture directory must be a real absolute directory')
    resolved = folder.resolve()
    require(any(resolved.is_relative_to(real_home() / name) for name in ('Documents', 'Downloads')),
            'Owner fixtures must be in normal Documents or Downloads')
    expected = REPOSITORY / 'tests/fixtures/macos_handoff'
    names = ['neutral-quiz.txt', 'ocr-question.png', 'scanned.pdf', 'EXPECTED.json', 'README.md', 'SHA256SUMS']
    for name in names:
        leaf = folder / name
        require(leaf.is_file() and not leaf.is_symlink(), 'Required visible fixture is missing: ' + name)
        require(hashlib.sha256(leaf.read_bytes()).digest() == hashlib.sha256((expected / name).read_bytes()).digest(),
                'Visible fixture differs from the exact handoff: ' + name)
    return str(resolved)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--fixtures', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    evidence = {'kind': 'normal-macos-app-http-backed', 'status': 'error', 'profile': PROFILE,
                'unqualified': ['physical renderer clicks/focus', 'native file chooser/save cancellation', 'Cmd-Q',
                                'normal-browser AI opening/clipboard', 'Server mode/isolation', 'native Settings backup/restore/reset'],
                'checks': {}}
    process = None
    backend = None
    nonce = None
    launcher_identity = None
    log = None
    code = 1
    try:
        require(sys.platform == 'darwin', 'Normal macOS package qualification requires macOS')
        require(args.output.is_absolute() and args.output.resolve().is_relative_to((REPOSITORY / '.gate1/macos').resolve()),
                'Evidence must be inside this repository .gate1/macos')
        require(not args.output.exists() and not args.output.is_symlink(), 'Refusing to overwrite existing qualification evidence')
        args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        evidence['fixtures'] = fixtures_checked(args.fixtures)
        require(args.app.is_absolute() and args.app.suffix == '.app' and not args.app.is_symlink(), 'Supply an absolute normal .app bundle')
        executable = args.app / 'Contents/MacOS/DLMS-Desktop'
        require(executable.is_file() and not executable.is_symlink() and os.access(executable, os.X_OK), 'Normal app executable is missing')
        root = prepare_root(args.data_root, create=False)
        require({path.name for path in root.iterdir()} == {MARKER}, 'Qualification requires a fresh marked root; existing data was left untouched')
        evidence.update(app=str(args.app), data_root=str(root))
        profile = root / 'profiles' / PROFILE
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('DLMS_', 'QUIZAPP_')) and key not in {
                   'PYTHONPATH', 'PYTHONHOME', 'QTWEBENGINE_DISABLE_SANDBOX', 'QTWEBENGINE_CHROMIUM_FLAGS',
                   'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QTWEBENGINE_PROCESS_PATH'}}
        command = [str(executable), '--profile', PROFILE, '--data-root', str(root)]
        log_path = args.output.with_suffix('.launcher.log')
        log = os.fdopen(os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb', buffering=0)

        def launch():
            return subprocess.Popen(command, cwd=REPOSITORY, env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

        def ready():
            nonlocal backend, nonce
            require(process.poll() is None, 'Normal app exited before readiness; inspect its launcher log')
            for pid in children(process.pid):
                try:
                    arguments, values = native.arguments_environment(pid)
                    variables = dict(item.split(b'=', 1) for item in values if b'=' in item)
                    if '--desktop-worker' not in arguments or 'backend' not in arguments:
                        continue
                    require(variables.get(b'DLMS_DESKTOP_PARENT_PID') == str(process.pid).encode(), 'Backend parent is not this launcher')
                    found = native.identity(pid)
                    require(Path(found['image']).resolve() == executable.resolve(), 'Backend executable differs from the normal package')
                    nonce = variables.get(b'DLMS_DESKTOP_NONCE', b'').decode('ascii')
                    require(re.fullmatch('[0-9a-f]{64}', nonce), 'Backend launch nonce is missing')
                    manifest = json.loads((profile / 'desktop-profile.json').read_text())
                    require(manifest['name'] == PROFILE, 'Profile manifest identity differs')
                    client = Client(manifest['port'], nonce)
                    response = client.request('/_desktop/ready', raw=True)
                    require(response['body'] == b'DLMS Desktop Block A ready', 'Wrong readiness payload')
                    backend = found
                    return client, manifest
                except (OSError, ValueError, KeyError, URLError):
                    continue
            return None

        def close_normal(client):
            native_request = native_quit_request(launcher_identity, executable)
            require(process.wait(timeout=20) == 0, 'Normal shutdown returned a failure status')
            remaining = native._owned(process.pid, nonce) + native._owned(backend['group'], nonce)
            require(not remaining, 'An exact owned helper survived normal shutdown')
            require(not live(backend), 'Exact backend survived normal shutdown')
            with socket.socket() as connection:
                connection.settimeout(0.3)
                require(connection.connect_ex(('127.0.0.1', int(urlsplit(client.origin).port))) != 0,
                        'Loopback port remained open after normal shutdown')
            return native_request

        process = launch()
        launcher_identity = native.identity(process.pid)
        client, manifest = wait_for(ready, 60)
        checks = evidence['checks']
        checks['startup'] = {'passed': True, 'port': manifest['port'], 'launcher_pid': process.pid, 'backend_pid': backend['pid']}
        duplicate = launch()
        try:
            require(duplicate.wait(timeout=15) == 0, 'Duplicate normal launch did not focus/exit successfully')
        finally:
            if duplicate.poll() is None:
                duplicate.terminate()
                duplicate.wait(timeout=4)
        require(process.poll() is None and live(backend), 'Duplicate launch disturbed original ownership')
        checks['duplicate'] = {'passed': True, 'original_backend_retained': True}
        client.request('/')
        client.multipart('/process', {'quiz_title': 'Mac Normal Synthetic Quiz'},
                         [('file', args.fixtures / 'neutral-quiz.txt', 'text/plain')])
        database = profile / 'backend/results.db'
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
            quizzes = connection.execute('SELECT id,title FROM quizzes').fetchall()
            require(len(quizzes) == 1 and quizzes[0][1] == 'Mac Normal Synthetic Quiz', 'TXT import did not publish exactly the synthetic quiz')
            quiz_id = quizzes[0][0]
            questions = connection.execute('SELECT id,question_number,question_text FROM questions ORDER BY question_number,id').fetchall()
            labels = [connection.execute('SELECT label FROM choices WHERE question_id=? AND is_correct=1 ORDER BY choice_order,id', (row[0],)).fetchall() for row in questions]
        require([row[1] for row in questions] == [1, 2, 3, 4], 'Question order changed')
        require(labels == [[('B',)], [('C',)], [('A',)], [('B',)]], 'Correct answer IDs/labels changed')
        checks['txt_import'] = {'passed': True, 'quiz_id': quiz_id, 'question_ids': [row[0] for row in questions], 'correct_labels': ['B', 'C', 'A', 'B']}
        registry = json.loads((profile / 'backend/config/quizzes.json').read_text())
        entry = next(item for item in registry if item['id'] == quiz_id)
        filename = entry['html'][:-5] + '.json'
        require(Path(filename).name == filename, 'Unsafe generated artifact name')
        raw = client.request('/data/' + quote(filename), raw=True)['body'].decode('utf-8')
        identity = '\0'.join(('quiz-recovery-v1', '1', str(quiz_id), '/data/' + filename, str(entry.get('exam_minutes') or 90), raw))
        fingerprint = 'sha256:' + hashlib.sha256(identity.encode()).hexdigest()
        status = client.request(f'/api/study/quiz/{quiz_id}')
        credentials = {'quizId': quiz_id, 'sessionId': 'mac-normal-' + secrets.token_hex(12),
                       'owner': 'mac-qualification-' + secrets.token_hex(12), 'generation': status['generation'],
                       'answerEncoding': 'choice-labels-v1'}
        session = client.json('/api/study/session', dict(credentials, fingerprint=fingerprint, variants={}, takeover=False))['session']
        credentials['assessmentRevision'] = session['assessment_revision']
        for index, label in enumerate(('B', 'C', 'A', 'B'), 1):
            payload = dict(credentials, questionOrdinal=index, questionType='choice', eventId=secrets.token_hex(16),
                           wasCorrect=True, selected=[label], contract=2, kind='response', sequence=index)
            answer = client.json('/_desktop/recovery/action', {'kind': 'study', 'payload': payload, 'fingerprint': fingerprint}, recovery=True)
            require(answer.get('ok') is True, 'Study save was not durably acknowledged')
            repeated = client.json('/_desktop/recovery/action', {'kind': 'study', 'payload': payload, 'fingerprint': fingerprint}, recovery=True)
            require(repeated.get('ok') is True and repeated.get('already_recorded') is True, 'Study retry was not idempotent')
        completed = client.json('/api/study/finish', dict(credentials, sequence=4))
        require(completed.get('ok') is True and completed['session']['reviewed'] == 4, 'Study completion was not persisted')
        checks['study_http_durable'] = {'passed': True, 'saved': 4, 'reviewed': 4, 'score': '4/4', 'retry_idempotent': True}
        exported = client.request(f'/export/quiz/{quiz_id}.txt', raw=True)['body']
        require(all(row[2].encode() in exported for row in questions), 'TXT export omitted synthetic question text')
        require(len(re.findall(rb'Correct Answer:\s*[A-Z]', exported)) == 4, 'TXT export answer count changed')
        export_path = args.output.with_suffix('.export.txt')
        with os.fdopen(os.open(export_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(exported)
        checks['export_http'] = {'passed': True, 'sha256': hashlib.sha256(exported).hexdigest(), 'path': str(export_path)}
        client.request('/pdf-import')
        staged = client.multipart('/pdf-import/screenshots', {'rights_ok': 'on', 'quiz_title': 'Mac Normal OCR Review'},
                                  [('screenshots', args.fixtures / 'ocr-question.png', 'image/png')])
        require(staged['path'].startswith('/pdf-import/screenshots/process/'), 'Bundled screenshot OCR was unavailable or staging failed')
        processed = client.multipart(staged['path'] + '/next', {})
        require(processed.get('status') == 'complete' and processed.get('has_results') is True and processed.get('failed') == 0,
                'Bundled screenshot OCR did not produce reviewable results')
        review = client.request(processed['review_url'], raw=True)['body'].decode('utf-8')
        from tests.macos.fixture_expectations import screenshot_review
        fields = screenshot_review(review)
        checks['ocr_screenshot_http'] = {'passed': True, 'review_only': True, 'published': False,
                                         'reviewed_fields': fields}
        pdf = client.multipart('/pdf-import/analyze', {'rights_ok': 'on', 'quiz_title': 'Mac Normal PDF Review', 'pdf_content_type': 'question_bank'},
                               [('pdf_file', args.fixtures / 'scanned.pdf', 'application/pdf')])
        require(pdf['path'].startswith('/pdf-import/ocr/'), 'Scanned PDF did not reach native PDF/OCR offer')
        started = client.multipart(pdf['path'] + '/start', {'ocr_pages': ['1']})
        require(started['path'].endswith('/process'), 'Scanned PDF OCR selection did not start')
        processed_pdf = client.multipart(started['path'] + '/next', {})
        require(processed_pdf.get('status') == 'complete' and processed_pdf.get('has_results') is True and processed_pdf.get('failed') == 0,
                'Bundled PDFium/OCR did not produce reviewable results')
        pdf_review = client.request(processed_pdf['review_url'], raw=True)['body'].decode('utf-8')
        require('443' in pdf_review and 'HTTPS' in pdf_review, 'Scanned PDF OCR review omitted expected content')
        checks['ocr_scanned_pdf_http'] = {'passed': True, 'review_only': True, 'published': False}
        snapshot = database_snapshot(database)
        quit_evidence = close_normal(client)
        checks['normal_shutdown'] = {'passed': True, 'owned_helpers_remaining': 0,
                                     'native_quit_request': quit_evidence}
        process = launch()
        launcher_identity = native.identity(process.pid)
        client, reopened = wait_for(ready, 60)
        require(reopened == manifest, 'Desktop UUID/epoch/origin changed on separate-process reopen')
        require(database_snapshot(database) == snapshot, 'Quiz/answer/Study/history IDs or saved records changed on reopen')
        status = client.request(f'/api/study/quiz/{quiz_id}')
        require(status['session']['completed_at'] and status['session']['sequence'] == 4, 'Study save was absent after reopen')
        reopen_quit = close_normal(client)
        checks['reopen_native_quit'] = {'passed': True, 'native_quit_request': reopen_quit}
        checks['separate_process_reopen'] = {'passed': True, 'same_origin_uuid_epoch': True, 'exact_saved_records': True}
        evidence['status'] = 'pass'
        code = 0
    except Exception as exc:
        evidence['error'] = type(exc).__name__ + ': ' + str(exc)
        traceback.print_exc()
    finally:
        if process is not None and process.poll() is None:
            evidence['failure_cleanup'] = {'attempted': True}
            try:
                if backend is not None and nonce:
                    native.reap(backend['group'], nonce)
                    native.reap(process.pid, nonce, exclude={process.pid})
                if launcher_identity is not None and live(launcher_identity):
                    native.signal_identity(launcher_identity, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()  # exact unreaped Popen child
                    process.wait(timeout=4)
                evidence['failure_cleanup']['launcher_stopped'] = True
            except Exception as exc:
                evidence['failure_cleanup']['error'] = type(exc).__name__ + ': ' + str(exc)
        if log is not None:
            log.close()
        # Never write evidence to an unchecked destination after input failure.
        if (args.output.is_absolute() and args.output.resolve().is_relative_to((REPOSITORY / '.gate1/macos').resolve())
                and args.output.parent.is_dir() and not args.output.exists() and not args.output.is_symlink()):
            with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
                json.dump(evidence, stream, indent=2)
                stream.write('\n')
    print(json.dumps({'status': evidence['status'], 'output': str(args.output), 'error': evidence.get('error')}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
