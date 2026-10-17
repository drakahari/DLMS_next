"""Cross-store snapshots, pre-mutation rejection and process exclusion."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import zipfile

import pytest
from tests import test_study_sessions as sessions
from tests import test_portable_quiz_bundles as portable_tests
from tests.csrf_test_utils import csrf_headers
from dlms.persistence import profile_snapshot as gate
from dlms.services import backups

dlms = sessions.dlms


@pytest.fixture
def profile():
    case = sessions.StudySessionTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def extract(path, root):
    report = dlms._validate_dlms_backup(str(path))
    dlms._extract_validated_backup(str(path), str(root), report)
    return report


def live_records():
    with dlms.get_db() as conn:
        rows = list(conn.iterdump())
    files = {str(p.relative_to(dlms.APP_DATA_DIR)): hashlib.sha256(p.read_bytes()).hexdigest()
             for folder in (dlms.CONFIG_FOLDER, dlms.DATA_FOLDER, dlms.QUIZ_FOLDER)
             for p in Path(folder).rglob('*') if p.is_file()}
    return rows, files


def test_backup_cannot_mix_database_and_later_registry(profile, monkeypatch, tmp_path):
    """Before R1 fix the controlled writer finishes in the DB/file-copy gap."""
    scheduled = threading.Event()
    attempted = threading.Event()
    result = {}
    original_lock = gate._try_lock
    def observed_lock(fd, exclusive):
        try:
            return original_lock(fd, exclusive)
        except BlockingIOError:
            if threading.current_thread().name == 'snapshot-publisher':
                attempted.set()
            raise
    monkeypatch.setattr(gate, '_try_lock', observed_lock)
    def publish():
        assert scheduled.wait(5)
        try:
            result['quiz_id'], result['html'] = profile.publish(title='Concurrent synthetic quiz', kind=None)
        except BaseException as exc:
            result['error'] = exc
        finally:
            # On affected code publication finishes before the snapshot proceeds.
            attempted.set()
    worker = threading.Thread(target=publish, name='snapshot-publisher')
    class Clock:
        count = 0
        @classmethod
        def now(cls):
            cls.count += 1
            if cls.count == 2:
                scheduled.set()
                assert attempted.wait(5)
            return datetime.now()
    worker.start()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(dlms, 'datetime', Clock)
            path, _ = dlms._create_dlms_backup()
    finally:
        scheduled.set()
        worker.join(8)
    assert not worker.is_alive()
    assert 'error' not in result, result
    stage = tmp_path / 'restored'
    report = extract(path, stage)
    registry = json.loads((stage / 'config/quizzes.json').read_text())
    with sqlite3.connect(stage / 'results.db') as conn:
        db_ids = {r[0] for r in conn.execute('SELECT id FROM quizzes')}
    assert all(q['id'] in db_ids for q in registry)
    assert all((stage / 'data' / dlms._quiz_artifact_names(q)[1]).is_file() for q in registry)
    assert result['quiz_id'] not in db_ids  # Snapshot precedes the waiting writer.
    assert any(q['id'] == result['quiz_id'] for q in dlms.load_registry())
    dlms._validate_staged_backup_semantics(str(stage), report['manifest'])


def inconsistent_archive(profile, tmp_path):
    path, _ = dlms._create_dlms_backup()
    output = tmp_path / 'inconsistent.zip'
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == 'DLMS_DATA/config/quizzes.json':
                registry = json.loads(data)
                registry.append(dict(id=9999, title='Synthetic dangling entry', html='missing.html'))
                data = json.dumps(registry).encode()
            dst.writestr(info, data)
    return output


def test_inconsistent_restore_rejected_before_destination_mutation(profile, tmp_path, monkeypatch):
    archive = inconsistent_archive(profile, tmp_path)
    assert zipfile.ZipFile(archive).testzip() is None
    before = live_records()
    staging = Path(dlms.BACKUP_FOLDER) / 'restore_staging'
    monkeypatch.setattr(dlms, 'BACKUP_RESTORE_STAGING_FOLDER', str(staging))
    response = profile.client.post('/settings/backup/restore/stage',
        data={'backup_file': (io.BytesIO(archive.read_bytes()), 'inconsistent.zip')},
        headers=csrf_headers(profile.client))
    assert response.status_code == 400
    assert b'quiz ID 9999' in response.data
    assert b'no database record' in response.data
    assert live_records() == before
    assert not list(staging.glob('*/restore.zip'))


@pytest.mark.parametrize('change', ['missing-data', 'count-mismatch'])
def test_invalid_cross_store_reference_rejected(profile, tmp_path, change):
    path, _ = dlms._create_dlms_backup()
    root = tmp_path / 'stage'
    report = extract(path, root)
    data = root / 'data' / dlms._quiz_artifact_names(dlms.load_registry()[0])[1]
    if change == 'missing-data':
        data.unlink()
        report['manifest'].pop('included_roots', None)
    else:
        data.write_text('[]')
    with pytest.raises(ValueError, match='incomplete quiz data'):
        dlms._validate_staged_backup_semantics(str(root), report['manifest'])


def test_legacy_history_optional_html_and_hotspot_surrogate_preserved(profile, tmp_path):
    runtime = [{'number': 1, 'type': 'hotspot', 'question': 'Find point', 'image_url': '/example.png', 'target_label': 'Point', 'target': {'type': 'circle', 'x': 0.5, 'y': 0.5, 'radius': 0.1}}]
    qid, _ = dlms._publish_quiz('Synthetic hotspot', runtime, [dict(number=1, question='Find point [Image hotspot]', choices=[dict(label='A', text='Point', is_correct=True)])])
    path, _ = dlms._create_dlms_backup()
    root = tmp_path / 'legacy'
    report = extract(path, root)
    registry_path = root / 'config/quizzes.json'
    registry = json.loads(registry_path.read_text())
    # DB-only old/history rows are legitimate; HTML is regenerated by restore.
    registry.pop(0)
    registry_path.write_text(json.dumps(registry))
    for p in (root / 'quizzes').glob('*.html'):
        p.unlink()
    report['manifest'].pop('included_roots', None)
    assert dlms._validate_staged_backup_semantics(str(root), report['manifest'])['status'] == 'valid'
    actual = json.loads((root / 'data' / dlms._quiz_artifact_names(registry[0])[1]).read_text())
    assert actual[0]['type'] == 'hotspot'
    assert actual[0]['question'] == 'Find point'
    with sqlite3.connect(root / 'results.db') as conn:
        assert conn.execute('SELECT question_type FROM questions WHERE quiz_id=?', (qid,)).fetchone()[0] == 'choice'


@pytest.mark.parametrize('checkpoint', ['db_committed', 'artifacts_promoted', 'registry_published'])
def test_snapshot_waits_for_complete_publication(profile, monkeypatch, tmp_path, checkpoint):
    entered, release, blocked = threading.Event(), threading.Event(), threading.Event()
    original = dlms._quiz_publication_checkpoint
    real_lock = gate._try_lock
    def pause(stage, journal):
        if stage == checkpoint:
            entered.set()
            assert release.wait(5)
        return original(stage, journal)
    def observed(fd, exclusive):
        try:
            return real_lock(fd, exclusive)
        except BlockingIOError:
            if exclusive: blocked.set()
            raise
    monkeypatch.setattr(dlms, '_quiz_publication_checkpoint', pause)
    monkeypatch.setattr(gate, '_try_lock', observed)
    with ThreadPoolExecutor(2) as pool:
        publication = pool.submit(profile.publish, title='Boundary fixture', kind=None)
        assert entered.wait(5), re.sub('<[^>]+>', ' ', mutation.result(1).get_data(as_text=True))[-10000:]
        backup = pool.submit(dlms._create_dlms_backup)
        try:
            assert blocked.wait(5)
        finally:
            release.set()
        qid, _ = publication.result(5)
        path, _ = backup.result(5)
    root = tmp_path / 'restored'
    report = extract(path, root)
    assert dlms._validate_staged_backup_semantics(str(root), report['manifest'])['status'] == 'valid'
    assert any(q['id'] == qid for q in json.loads((root / 'config/quizzes.json').read_text()))


def test_private_snapshot_ignores_later_live_changes(profile, monkeypatch, tmp_path):
    real_zip = backups.zipfile.ZipFile
    started = False
    def begin_archive(*args, **kwargs):
        nonlocal started
        if not started:
            started = True
            profile.publish(title='After capture', kind=None)
        return real_zip(*args, **kwargs)
    before = live_records()
    monkeypatch.setattr(backups.zipfile, 'ZipFile', begin_archive)
    path, _ = dlms._create_dlms_backup()
    stage = tmp_path / 'stage'
    report = extract(path, stage)
    assert dlms._validate_staged_backup_semantics(str(stage), report['manifest'])['status'] == 'valid'
    assert len(json.loads((stage / 'config/quizzes.json').read_text())) == 1
    assert len(dlms.load_registry()) == 2
    assert before != live_records()


def test_nested_safety_backup_and_exception_release(profile):
    def broken_reset():
        raise OSError('Synthetic write failure')
    with pytest.raises(OSError, match='Synthetic write failure'):
        dlms._run_reset_with_backup('failure-test', broken_reset)
    assert len(list(Path(dlms.BACKUP_FOLDER).glob('*.zip'))) == 1
    assert profile.client.get('/study-history').status_code == 200
    path, _ = dlms._create_dlms_backup()
    assert Path(path).is_file()


def test_history_deletion_safety_backup_reentrant(profile):
    assert profile.save(profile.payload(1, correct=False)).status_code == 200
    response = profile.client.post('/api/delete_study_history', json={'confirmation': 'DELETE STUDY HISTORY'}, headers=csrf_headers(profile.client))
    assert response.status_code == 200, response.json
    assert list(Path(dlms.BACKUP_FOLDER).glob('*.zip'))


def test_gate_reentrancy_upgrade_timeout_and_other_profile(tmp_path):
    root = tmp_path / 'one'
    root.mkdir()
    with gate.access(root, exclusive=True):
        with gate.access(root):
            with gate.access(root, exclusive=True):
                pass
        def contend():
            with pytest.raises(gate.ProfileBusyError):
                with gate.access(root, timeout=0):
                    pass
            with gate.access(tmp_path / 'other', exclusive=True):
                pass
        with ThreadPoolExecutor(1) as pool: pool.submit(contend).result(2)
    with gate.access(root):
        with pytest.raises(gate.ProfileBusyError):
            with gate.access(root, exclusive=True):
                pass
    with gate.access(root, exclusive=True, timeout=0): pass


def test_separate_process_exclusion_and_exit_release(tmp_path):
    root = tmp_path / 'profile'
    root.mkdir()
    script = '''import sys
from dlms.persistence.profile_snapshot import access
with access(sys.argv[1]):
 print('held', flush=True)
 sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, '-u', '-c', script, str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'held'
        with pytest.raises(gate.ProfileBusyError):
            with gate.access(root, exclusive=True, timeout=0): pass
        with gate.access(root, timeout=0): pass  # Normal concurrent access stays possible.
        child.stdin.write('\n'); child.stdin.flush()
        assert child.wait(timeout=5) == 0
        with gate.access(root, exclusive=True, timeout=0): pass
    finally:
        if child.poll() is None: child.kill(); child.wait(timeout=5)
        child.stdin.close(); child.stdout.close()


def test_gate_rejects_symlink_and_lock_survives_profile_replacement(tmp_path):
    root = tmp_path / 'profile'
    root.mkdir()
    lock = gate.lock_path(root)
    outside = tmp_path / 'outside'
    outside.write_text('unchanged')
    try:
        lock.symlink_to(outside)
    except OSError as exc:
        if os.name == 'nt' and exc.winerror == 1314:
            pytest.skip('Windows symlink privilege unavailable; native handle/lock/parent substitution checks are in tests/windows/test_native.py')
        raise
    with pytest.raises(OSError):
        with gate.access(root): pass
    assert outside.read_text() == 'unchanged'
    lock.unlink()
    with gate.access(root, exclusive=True):
        original_inode = lock.stat().st_ino
        root.rmdir(); root.mkdir()
        assert gate.lock_path(root) == lock
        assert lock.stat().st_ino == original_inode

@pytest.mark.parametrize('field', ['question', 'choices', 'correct'])
def test_same_count_answer_or_text_divergence_is_not_a_valid_backup(profile, tmp_path, field):
    path, _ = dlms._create_dlms_backup()
    root = tmp_path / 'stage'
    report = extract(path, root)
    data = root / 'data' / dlms._quiz_artifact_names(dlms.load_registry()[0])[1]
    items = json.loads(data.read_text())
    if field == 'question': items[0]['question'] = 'Different text'
    elif field == 'choices': items[0]['choices'][0]['text'] = 'Different answer'
    else: items[0]['correct'] = ['Not a stored answer']
    data.write_text(json.dumps(items))
    with pytest.raises(backups.SnapshotConsistencyError, match='disagree'):
        dlms._validate_staged_backup_semantics(str(root), report['manifest'])


def test_snapshot_copy_failure_cleans_only_owned_artifacts(profile, monkeypatch):
    previous, _ = dlms._create_dlms_backup()
    previous_bytes = Path(previous).read_bytes()
    before = live_records()
    real_copy = backups.shutil.copyfile
    def fail(src, dst, *args, **kwargs):
        if 'dlms-backup-snapshot-' in str(dst): raise OSError('Synthetic storage failure')
        return real_copy(src, dst, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(backups.shutil, 'copyfile', fail)
        with pytest.raises(OSError, match='Synthetic storage failure'): dlms._create_dlms_backup()
    assert live_records() == before
    assert Path(previous).read_bytes() == previous_bytes
    assert list(Path(dlms.BACKUP_FOLDER).glob('*.zip')) == [Path(previous)]
    assert not list(Path(dlms.BACKUP_FOLDER).glob('.*.tmp'))
    with gate.access(dlms.APP_DATA_DIR, exclusive=True, timeout=0): pass
    assert Path(dlms._create_dlms_backup()[0]).is_file()


def test_pending_publication_temporary_journal_blocks_backup(profile):
    root = Path(dlms.APP_DATA_DIR, '.quiz_publications')
    root.mkdir(exist_ok=True)
    pending = root / 'publication_synthetic.json.tmp'
    pending.write_text('{"phase":"db_committed"}')
    with pytest.raises(backups.SnapshotConsistencyError, match='recovery is pending'):
        dlms._create_dlms_backup()
    assert pending.exists()
    assert not list(Path(dlms.BACKUP_FOLDER).glob('*.zip'))


def run_during_snapshot(action, pause, monkeypatch):
    """Pause a real request in its mutation; observe backup at the OS gate."""
    entered, release, blocked = threading.Event(), threading.Event(), threading.Event()
    real_lock = gate._try_lock
    def waiting(fd, exclusive):
        try: return real_lock(fd, exclusive)
        except BlockingIOError:
            if exclusive: blocked.set()
            raise
    monkeypatch.setattr(gate, '_try_lock', waiting)
    pause(entered, release)
    with ThreadPoolExecutor(2) as pool:
        mutation = pool.submit(action)
        assert entered.wait(5), re.sub('<[^>]+>', ' ', mutation.result(1).get_data(as_text=True))[-10000:]
        backup = pool.submit(dlms._create_dlms_backup)
        try: assert blocked.wait(5)
        finally: release.set()
        response = mutation.result(5)
        path, _ = backup.result(5)
    assert response.status_code in (200, 302, 303), response.data[:500]
    return path


@pytest.mark.parametrize('operation', ['edit', 'delete'])
def test_http_edit_and_delete_settle_before_snapshot(monkeypatch, tmp_path, operation):
    from tests.test_quiz_mutation_atomicity import QuizMutationAtomicityTests
    case = QuizMutationAtomicityTests(); case.setUp()
    try:
        real_save = dlms.save_registry
        def pause(entered, release):
            def saved(registry):
                result = real_save(registry)
                entered.set(); assert release.wait(5)
                return result
            monkeypatch.setattr(dlms, 'save_registry', saved)
        headers = csrf_headers(case.client)
        def action():
            return case.client.post(f'/{"edit_quiz" if operation == "edit" else "delete_quiz"}/{case.quiz_id}',
                data=case._edit_form() if operation == 'edit' else {}, headers=headers)
        path = run_during_snapshot(action, pause, monkeypatch)
        root = tmp_path / 'stage'; report = extract(path, root)
        dlms._validate_staged_backup_semantics(str(root), report['manifest'])
        registry = json.loads((root/'config/quizzes.json').read_text())
        assert bool(registry) == (operation == 'edit')
        with sqlite3.connect(root/'results.db') as conn:
            row = conn.execute('SELECT title FROM quizzes WHERE id=?', (case.quiz_id,)).fetchone()
            assert row == (('Changed quiz',) if operation == 'edit' else None)
    finally: case.doCleanups()


def test_http_certification_and_attachment_transaction_settles_before_snapshot(monkeypatch, tmp_path):
    from tests.test_certifications import CertificationTests, cert
    case = CertificationTests(); case.setUp()
    try:
        request = case.request('certification', dict(name='Atomic synthetic credential'))
        real_apply = cert.apply
        def pause(entered, release):
            def applied(*args, **kwargs):
                result = real_apply(*args, **kwargs)
                entered.set(); assert release.wait(5)
                return result
            monkeypatch.setattr(cert, 'apply', applied)
        headers = csrf_headers(case.client)
        def action():
            return case.client.post('/certifications/save', data={
                'kind':'certification', 'request_id':request['request_id'],
                'generation':request['generation'], 'revision':str(request['revision']),
                'field_name':'Atomic synthetic credential', 'field_issuer':'Example issuer', 'badge':(io.BytesIO(case.png()),'badge.png'),
                'certificate':(io.BytesIO(case.pdf()),'certificate.pdf')}, headers=headers)
        path = run_during_snapshot(action, pause, monkeypatch)
        root = tmp_path/'stage'; report = extract(path, root)
        dlms._validate_staged_backup_semantics(str(root), report['manifest'])
        with sqlite3.connect(root/'results.db') as conn:
            assert conn.execute('SELECT COUNT(*) FROM certifications').fetchone()[0] == 1
            assert conn.execute('SELECT COUNT(*) FROM certification_attachments').fetchone()[0] == 2
        with dlms.get_db() as live, sqlite3.connect(root/'results.db') as saved:
            for table in ('certifications','certification_cycles','certification_attachments'):
                assert [tuple(r) for r in live.execute('SELECT * FROM '+table)] == saved.execute('SELECT * FROM '+table).fetchall()
    finally: case.doCleanups()


@pytest.mark.parametrize('legacy_order', [False, True])
def test_partial_legacy_flags_do_not_hide_explicit_contradiction(profile, tmp_path, legacy_order):
    path, _ = dlms._create_dlms_backup()
    root = tmp_path/'stage'; report = extract(path, root)
    data = root/'data'/dlms._quiz_artifact_names(dlms.load_registry()[0])[1]
    items = json.loads(data.read_text())
    items[0].pop('correct', None)
    items[0]['choices'][0]['is_correct'] = not items[0]['choices'][0]['is_correct']
    items[0]['choices'][1].pop('is_correct', None)
    data.write_text(json.dumps(items))
    if legacy_order:
        with sqlite3.connect(root/'results.db') as conn:
            conn.execute('UPDATE choices SET choice_order=NULL')
    with pytest.raises(backups.SnapshotConsistencyError, match='correctness'):
        dlms._validate_staged_backup_semantics(str(root), report['manifest'])


def test_database_lock_failure_is_bounded_and_does_not_publish(profile, monkeypatch):
    from types import SimpleNamespace
    previous, _ = dlms._create_dlms_backup()
    before = Path(previous).read_bytes()
    lock = sqlite3.connect(dlms.DB_PATH)
    lock.execute('BEGIN EXCLUSIVE')
    clock = iter([0, 31, 32, 33])
    try:
        # Advance only the snapshot deadline; real SQLite reports SQLITE_BUSY.
        with monkeypatch.context() as patch:
            patch.setattr(backups, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
            with pytest.raises(backups.SnapshotConsistencyError, match='Database snapshot could not finish'):
                dlms._create_dlms_backup()
    finally:
        lock.rollback(); lock.close()
    assert Path(previous).read_bytes() == before
    assert list(Path(dlms.BACKUP_FOLDER).glob('*.zip')) == [Path(previous)]
    assert Path(dlms._create_dlms_backup()[0]).is_file()


def test_portable_import_publishes_before_backup(monkeypatch, tmp_path):
    case = portable_tests.PortableQuizBundleTests(); case.setUp()
    try:
        archive = case._write_bundle(case._minimal_manifest())
        client = dlms.app.test_client()
        staged = client.post('/quiz-bundles/import', data={'bundle_zip':(io.BytesIO(archive.read_bytes()),'synthetic.zip')}, headers=csrf_headers(client))
        assert staged.status_code == 302
        url = staged.headers['Location']
        headers = csrf_headers(client, url)
        original = dlms._quiz_publication_checkpoint
        def pause(entered, release):
            def checkpoint(phase, journal):
                if phase == 'registry_published': entered.set(); assert release.wait(5)
                return original(phase, journal)
            monkeypatch.setattr(dlms, '_quiz_publication_checkpoint', checkpoint)
        path = run_during_snapshot(lambda: client.post(url+'/confirm', data={'confirm_import':'yes'}, headers=headers), pause, monkeypatch)
        root=tmp_path/'stage'; report=extract(path, root)
        assert dlms._validate_staged_backup_semantics(str(root), report['manifest'])['status']=='valid'
        with sqlite3.connect(root/'results.db') as conn:
            assert conn.execute('SELECT COUNT(*) FROM quizzes').fetchone()[0] == 1
            assert conn.execute('SELECT SUM(is_correct) FROM choices').fetchone()[0] == 1
    finally: case.doCleanups()


def test_snapshot_database_open_failure_closes_source(profile, monkeypatch):
    real_connect = dlms.sqlite3.connect
    opened = []
    def connect(path, *args, **kwargs):
        if 'dlms-backup-snapshot-' in str(path):
            raise sqlite3.OperationalError('Synthetic destination open failure')
        result = real_connect(path, *args, **kwargs)
        opened.append(result)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(dlms.sqlite3, 'connect', connect)
        with pytest.raises(sqlite3.OperationalError, match='destination open failure'):
            dlms._create_dlms_backup()
    assert opened
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
            conn.execute('SELECT 1')
    with gate.access(dlms.APP_DATA_DIR, exclusive=True, timeout=0): pass
    assert not list(Path(dlms.BACKUP_FOLDER).glob('*.zip'))
