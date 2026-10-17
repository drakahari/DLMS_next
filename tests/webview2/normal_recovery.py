"""External seeded-journal recovery in an unchanged normal frozen executable.

The journal is explicitly seeded while this disposable application's processes
are closed. This does not claim a UI-accepted interruption/browser checkpoint,
and enables no test hooks in the packaged application.
"""
from pathlib import Path
from contextlib import closing
import argparse
import hashlib
import importlib.metadata
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid

from desktop.profile_state import atomic_json
from desktop.recovery import DurableActions, digest
from tests.windows.normal_candidate import request
from tests.windows.normal_processes import descendants, identity, alive, backend_nonce
from tests.package.normal_pdf_ocr_smoke import multipart

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.gate1/windows-native'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def study_rows(database, event):
    with closing(sqlite3.connect('file:' + database.as_posix() + '?mode=ro', uri=True)) as connection:
        rows = connection.execute('SELECT payload_json FROM study_responses WHERE event_id=?', (event,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from package_windows_webview2.acceptance import payload_binding
    from desktop.windows_files import assert_path, owned, pinned_parents
    exe = args.exe.resolve(strict=True); out = args.output.absolute()
    if not exe.is_relative_to(WORK.resolve(strict=True)) or not out.resolve(strict=False).is_relative_to(WORK.resolve(strict=True)):
        raise ValueError('Only project-local packaged executable and disposable output are allowed')
    if out.exists(): raise FileExistsError('Preserve the previous recovery evidence; use a fresh output')
    with pinned_parents(out):
        assert_path(out); out.mkdir(mode=0o700); owned(out, private=True)
    binding = payload_binding(exe, args.inventory)
    data = out / 'Synthetic seeded recovery 日本語 with spaces'; data.mkdir(mode=0o700)
    (data / '.dlms-desktop-windows-candidate.json').write_text(json.dumps({'kind': 'dlms-desktop-windows-candidate', 'version': 1}))
    profile = 'seeded-normal01'; state = data / 'profiles' / profile
    event = 'normal-seeded-study-' + uuid.uuid4().hex
    report = {'normal_package': True, 'app_test_hooks': False, 'external_journal_seed': True,
              'normal_executable': str(exe), 'journal_seed_kind': 'study',
              'ui_accepted_interruption': False, 'browser_checkpoint_acceptance': False, 'physical_acceptance': False,
              'python_version': sys.version, 'python_executable': sys.executable,
              'harness_sha256': sha(Path(__file__)), 'journal_helper_sha256': sha(ROOT / 'desktop/recovery.py'),
              'source_dependencies': {name: importlib.metadata.version(name) for name in ('PySide6', 'Flask', 'pytest')},
              'event_id': event, 'runs': [], 'passed': False, **binding}
    record, journal, initial_manifest = None, None, None
    # No host Python/OCR executable discovery is available to the application.
    env = {key: value for key, value in os.environ.items() if not key.startswith(('DLMS_', 'QUIZAPP_', 'QTWEBENGINE_', 'PYTHON'))}
    env['PATH'] = str(out / 'no-host-tools')
    try:
        for run in range(3):
            if run:
                # Seed only after the previous normal process tree is proven
                # gone. Exact UUID/epoch, source, session and payload remain
                # subject to the real package's startup reconciliation checks.
                assert record is not None and journal is not None
                assert not journal.exists()
                atomic_json(journal, record)
                reader = DurableActions.__new__(DurableActions)
                reader.root = journal.parent
                assert reader._read(journal) == record  # Strict existing format/hash/identity validation.
                report.setdefault('seeds', []).append({'before_run': run,
                    'phase': 'before_commit' if run == 1 else 'after_commit_before_cleanup',
                    'record_sha256': sha(journal), 'strict_existing_reader_passed': True,
                    'durable_event_rows_before': len(study_rows(state / 'backend/results.db', event))})
            observed, port, nonce, forced = {}, None, None, False
            with (out / f'launcher-{run}.log').open('w') as log:
                proc = subprocess.Popen([str(exe), '--profile', profile, '--data-root', str(data)],
                    cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT)
                observed[proc.pid] = identity(proc.pid)['start']
                try:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        if proc.poll() is not None: raise RuntimeError(f'Normal executable exited during startup: {proc.returncode}')
                        for pid in descendants(proc.pid):
                            try: observed[pid] = identity(pid)['start']
                            except OSError: pass
                        owner = backend_nonce(proc.pid, exe, {})
                        manifest_path = state / 'desktop-profile.json'
                        if owner and manifest_path.is_file():
                            manifest = json.loads(manifest_path.read_text()); port, nonce = manifest['port'], owner[1]
                            try:
                                if request(port, nonce, 'GET', '/_desktop/ready', headers={'X-DLMS-Desktop-Nonce': nonce})[0] == 200: break
                            except OSError: pass
                        time.sleep(.1)
                    else: raise TimeoutError('Normal executable did not become ready')
                    if initial_manifest is None: initial_manifest = dict(manifest)
                    assert manifest == initial_manifest, 'Normal restart changed the profile identity/origin'
                    renderer_names = set()
                    deadline = time.monotonic() + 25
                    while time.monotonic() < deadline:
                        for pid in descendants(proc.pid):
                            try:
                                child = identity(pid); observed[pid] = child['start']
                                name = Path(child['image']).name.lower()
                                if name in ('dlms-webview2-host.exe', 'msedgewebview2.exe'): renderer_names.add(name)
                            except OSError: pass
                        if renderer_names == {'dlms-webview2-host.exe', 'msedgewebview2.exe'}: break
                        assert proc.poll() is None
                        time.sleep(.1)
                    assert renderer_names == {'dlms-webview2-host.exe', 'msedgewebview2.exe'}, 'Normal packaged renderer was not observed'
                    if run == 0:
                        headers = {'Origin': f'http://127.0.0.1:{port}', 'Sec-Fetch-Site': 'same-origin'}
                        status, body, response = request(port, nonce, 'GET', '/api/csrf-token', headers=headers | {'X-DLMS-CSRF-Refresh': '1'})
                        assert status == 200
                        csrf = json.loads(body)['csrf_token']
                        headers.update({'Cookie': '; '.join(x.split(';', 1)[0] for x in response['_set_cookies']), 'X-CSRFToken': csrf})
                        def post(path, body, media='application/json'):
                            if isinstance(body, dict): body = json.dumps(body).encode()
                            return request(port, nonce, 'POST', path, body, headers | {'Content-Type': media})
                        fixture = ROOT / 'fixtures/gate1-neutral-quiz.txt'
                        body, media = multipart('file', fixture.name, 'text/plain', fixture.read_bytes(), {'quiz_title': 'Seeded journal synthetic quiz', 'csrf_token': csrf})
                        assert post('/process', body, media)[0] in (200, 302)
                        registry = json.loads((state / 'backend/config/quizzes.json').read_text())
                        entry = next(item for item in registry if item.get('title') == 'Seeded journal synthetic quiz')
                        qid = entry['id']; files = list((state / 'backend/data').glob('*.json'))
                        assert len(files) == 1
                        rawfile = files[0]; raw = rawfile.read_bytes().decode('utf-8')
                        fingerprint = 'sha256:' + hashlib.sha256('\0'.join(['quiz-recovery-v1', '1', str(qid),
                            '/data/' + rawfile.name, str(entry.get('exam_minutes') or 90), raw]).encode()).hexdigest()
                        status, body, _ = request(port, nonce, 'GET', f'/api/study/quiz/{qid}')
                        assert status == 200
                        generation = json.loads(body)['generation']; session_id, tab = uuid.uuid4().hex, uuid.uuid4().hex
                        status, body, _ = post('/api/study/session', {'quizId': qid, 'sessionId': session_id, 'owner': tab,
                            'fingerprint': fingerprint, 'generation': generation, 'answerEncoding': 'choice-labels-v1', 'variants': {}})
                        assert status == 200
                        revision = json.loads(body)['session']['assessment_revision']
                        payload = {'contract': 2, 'quizId': qid, 'sessionId': session_id, 'owner': tab, 'generation': generation,
                            'answerEncoding': 'choice-labels-v1', 'assessmentRevision': revision, 'eventId': event, 'sequence': 1,
                            'questionOrdinal': 1, 'questionType': 'choice', 'wasCorrect': True, 'selected': ['B'], 'kind': 'response'}
                        record = {'version': 1, 'kind': 'study', 'id': event, 'profile_uuid': manifest['uuid'], 'epoch': manifest['epoch'],
                            'fingerprint': fingerprint, 'assessment_revision': revision, 'payload': payload,
                            'validated_exam': None, 'payload_hash': digest(payload)}
                        record['record_hash'] = digest(record)
                        reader = DurableActions.__new__(DurableActions); reader.root = state / 'durable-actions'
                        journal = reader._path('study', event)
                        assert study_rows(state / 'backend/results.db', event) == []
                        assert not journal.exists()
                    else:
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            rows = study_rows(state / 'backend/results.db', event)
                            if len(rows) == 1 and not journal.exists(): break
                            time.sleep(.1)
                        assert len(rows) == 1 and not journal.exists(), 'Startup did not reconcile the exact seeded journal'
                        assert rows[0]['eventId'] == event and rows[0]['selected'] == ['B'] and rows[0]['assessmentRevision'] == record['assessment_revision']
                        assert not list((state / 'durable-actions-quarantine').glob('*.json'))
                        assert json.loads((state / 'desktop-profile.json').read_text()) == manifest
                    for pid in descendants(proc.pid):
                        try: observed[pid] = identity(pid)['start']
                        except OSError: pass
                    assert request(port, nonce, 'POST', '/api/shutdown')[0] == 200
                    assert proc.wait(timeout=40) == 0
                    deadline = time.monotonic() + 8
                    while any(alive(pid, birth) for pid, birth in observed.items()) and time.monotonic() < deadline: time.sleep(.1)
                    assert not any(alive(pid, birth) for pid, birth in observed.items()), 'Owned process survived normal exit'
                    report['runs'].append({'run': run, 'normal_close': True, 'exact_owned_cleanup': True,
                        'event_rows': len(study_rows(state / 'backend/results.db', event)), 'journal_present': journal.exists(),
                        'owned_renderer_images_observed': sorted(renderer_names),
                        'owned_process_identities': [{'pid': pid, 'start': born} for pid, born in sorted(observed.items())]})
                finally:
                    if proc.poll() is None:
                        if port and nonce:
                            try: request(port, nonce, 'POST', '/api/shutdown'); proc.wait(timeout=12)
                            except (OSError, subprocess.TimeoutExpired): pass
                        if proc.poll() is None:
                            # Only this Popen's retained owned process handle;
                            # never terminate a PID found by a name/substring.
                            forced = True; proc.kill(); proc.wait(timeout=10)
                    if forced: report['forced_test_cleanup'] = True
        assert [run['event_rows'] for run in report['runs']] == [0, 1, 1]
        assert payload_binding(exe, args.inventory) == binding
        report.update(passed=True, payload_verified_before_and_after=True, real_startup_replay=True,
                      committed_replay_deduplicated=True, final_event_count=1)
    finally:
        (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Normal frozen startup recovered the externally seeded Study journal once; repeated committed journal was deduplicated. No UI interruption was simulated.')


if __name__ == '__main__': main()
