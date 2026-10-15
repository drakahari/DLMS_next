"""Untrusted database programs must be rejected before staged writes."""
import hashlib
import io
import sqlite3
from pathlib import Path
from unittest import mock

import pytest
from dlms.persistence.certification_schema import DATE_TRIGGERS

from tests import test_study_sessions as sessions
from tests.csrf_test_utils import csrf_headers

dlms = sessions.dlms


@pytest.fixture
def study_profile():
    case = sessions.StudySessionTests()
    case.setUp()
    try:
        assert case.save(case.payload(1, correct=False)).status_code == 200
        yield case
    finally:
        case.doCleanups()


def staged_copy(tmp_path):
    stage = Path(dlms.APP_DATA_DIR) / ('restore-' + tmp_path.name)
    stage.mkdir()
    with sqlite3.connect(dlms.DB_PATH) as source, sqlite3.connect(stage / 'results.db') as target:
        source.backup(target)
    return stage, stage / 'results.db'


def test_unexpected_trigger_rejected_before_any_staged_write(study_profile, tmp_path):
    stage, database = staged_copy(tmp_path)
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TRIGGER unexpected AFTER UPDATE ON study_state BEGIN DELETE FROM study_responses; END')
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        dlms._prepare_staged_restore_database(str(stage))
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT count(*) FROM study_responses').fetchone()[0] == 1
    assert len(study_profile.facts()['answers']) == 1


def test_malicious_backup_stage_rejected_preserving_active_facts_and_recovery(study_profile, tmp_path):
    stage, database = staged_copy(tmp_path)
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TRIGGER unexpected AFTER INSERT ON study_responses BEGIN DELETE FROM study_responses; END')
    inventory = dlms._backup_file_inventory()
    with mock.patch.object(dlms, 'DB_PATH', str(database)), mock.patch.object(
        dlms, '_backup_file_inventory', return_value=[(path, rel) for path, rel in inventory if rel != 'results.db']
    ):
        archive, _ = dlms._create_dlms_backup('untrusted-fixture')
    root = Path(dlms.APP_DATA_DIR)
    recovery = root / 'unrelated-recovery.txt'
    recovery.write_text('Keep this recovery record')
    original = Path(archive).read_bytes()
    response = study_profile.client.post('/settings/backup/restore/stage',
        data={'backup_file': (io.BytesIO(original), 'untrusted.zip')},
        headers=csrf_headers(study_profile.client))
    assert response.status_code == 400
    assert recovery.read_text() == 'Keep this recovery record'
    assert Path(archive).read_bytes() == original
    assert study_profile.save(study_profile.payload(2)).status_code == 200
    with dlms.get_db() as conn:
        rows = conn.execute('SELECT sequence,was_correct FROM study_responses ORDER BY sequence').fetchall()
        assert [tuple(row) for row in rows] == [(1, 0), (2, 1)]


@pytest.mark.parametrize('statement', [
    'CREATE VIEW unexpected AS SELECT * FROM study_responses',
    'CREATE VIRTUAL TABLE unexpected USING fts5(content)',
    'CREATE INDEX unexpected ON questions(length(question_text))',
    'CREATE INDEX unexpected ON questions(id) WHERE length(question_text)>0',
    'ALTER TABLE questions ADD COLUMN unexpected INTEGER GENERATED ALWAYS AS (length(question_text)) VIRTUAL',
    'ALTER TABLE questions ADD COLUMN unexpected INTEGER CHECK(length(question_text)>0)',
])
def test_other_unexpected_schema_programs_rejected(study_profile, tmp_path, statement):
    _, database = staged_copy(tmp_path)
    with sqlite3.connect(database) as conn:
        conn.execute(statement)
    with pytest.raises(ValueError):
        dlms._validate_restored_sqlite(database)


def test_legitimate_staged_database_retains_facts_and_accepts_new_responses(study_profile, tmp_path):
    stage, database = staged_copy(tmp_path)
    dlms._prepare_staged_restore_database(str(stage))
    with mock.patch.object(dlms, 'DB_PATH', str(database)):
        generation = study_profile.client.get(f'/api/study/quiz/{study_profile.quiz_id}').json['generation']
        claim = {**study_profile.claim_data, 'generation': generation}
        response = study_profile.client.post('/api/study/session', json=claim, headers=study_profile.headers)
        assert response.status_code == 200
        payload = {**study_profile.payload(2), 'generation': generation}
        assert study_profile.save(payload).status_code == 200
        with dlms.get_db() as conn:
            assert [tuple(row) for row in conn.execute('SELECT sequence,was_correct FROM study_responses ORDER BY sequence')] == [(1, 0), (2, 1)]


def test_guard_with_changed_string_literal_is_not_trusted(study_profile, tmp_path):
    _, database = staged_copy(tmp_path)
    name = 'certification_dates_update'
    with sqlite3.connect(database) as conn:
        conn.execute('DROP TRIGGER ' + name)
        conn.execute(DATE_TRIGGERS[name].replace('$.planning_deadline', '$.Planning_Deadline'))
    with pytest.raises(ValueError, match='unexpected SQLite trigger'):
        dlms._validate_restored_sqlite(database)


def test_startup_rejects_unexpected_program_without_modifying_database(study_profile, tmp_path):
    _, database = staged_copy(tmp_path)
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TRIGGER unexpected AFTER UPDATE ON study_state BEGIN DELETE FROM study_responses; END')
        conn.execute('UPDATE schema_meta SET version=9')
    original = database.read_bytes()
    with pytest.raises(ValueError, match='unexpected SQLite trigger'):
        dlms.bootstrap_database(str(database))
    assert database.read_bytes() == original
