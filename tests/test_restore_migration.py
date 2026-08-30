"""DLMS-045B staged restore migration and rollback regressions."""
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="dlms-restore-migration-app-")
os.environ["QUIZAPP_DATA_DIR"] = _IMPORT_DATA.name
import app as dlms
from tests.csrf_test_utils import csrf_headers


class RestoreMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-restore-migration-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.live = self.root / "live"
        self.live.mkdir()
        dlms._initialize_data_root_ownership(str(self.live))
        self.restore_staging = self.live / "backup_restore_staging"
        self.restore_staging.mkdir()
        self.backups = self.live / "backups"
        self.backups.mkdir()
        self.db_path = self.live / "results.db"
        self.patches = [
            mock.patch.object(dlms, "APP_DATA_DIR", str(self.live)),
            mock.patch.object(dlms, "DB_PATH", str(self.db_path)),
            mock.patch.object(dlms, "BACKUP_FOLDER", str(self.backups)),
            mock.patch.object(dlms, "BACKUP_RESTORE_STAGING_FOLDER", str(self.restore_staging)),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        dlms.bootstrap_database(str(self.db_path))
        self._set_quiz_title(self.db_path, "Original Live")
        self.live_sentinel = self.live / "keep-live.txt"
        self.live_sentinel.write_text("original", encoding="utf-8")
        self.client = dlms.app.test_client()

    @staticmethod
    def _set_quiz_title(database, title):
        conn = sqlite3.connect(database)
        try:
            conn.execute("DELETE FROM quizzes")
            conn.execute(
                "INSERT INTO quizzes (title, source_file) VALUES (?, ?)",
                (title, title.lower().replace(" ", "-") + ".html"),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _quiz_title(database):
        conn = sqlite3.connect(database)
        try:
            row = conn.execute("SELECT title FROM quizzes ORDER BY id LIMIT 1").fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    @staticmethod
    def _schema_version(database):
        conn = sqlite3.connect(database)
        try:
            return conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
        finally:
            conn.close()

    def _legacy_database(self, path):
        conn = sqlite3.connect(path)
        try:
            conn.executescript("""
                CREATE TABLE quizzes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source_file TEXT NOT NULL UNIQUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quiz_id INTEGER NOT NULL,
                    question_number INTEGER NOT NULL,
                    question_text TEXT NOT NULL,
                    correct_letters TEXT,
                    correct_text TEXT
                );
                CREATE TABLE choices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    text TEXT NOT NULL,
                    is_correct INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE attempts (
                    id TEXT PRIMARY KEY,
                    quiz_id INTEGER NOT NULL,
                    user_name TEXT,
                    started_at DATETIME,
                    completed_at DATETIME,
                    score INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    percent INTEGER NOT NULL,
                    time_remaining INTEGER,
                    mode TEXT NOT NULL
                );
                CREATE TABLE attempt_answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL,
                    question_id INTEGER NOT NULL,
                    selected_labels TEXT,
                    was_correct INTEGER NOT NULL
                );
                CREATE TABLE missed_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL,
                    question_id INTEGER NOT NULL,
                    correct_letters TEXT NOT NULL
                );
                CREATE TABLE schema_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO schema_meta (id, version) VALUES (1, 1);
                INSERT INTO quizzes (id, title, source_file)
                    VALUES (1, 'Restored Legacy', 'restored-legacy.html');
                INSERT INTO questions (id, quiz_id, question_number, question_text)
                    VALUES (10, 1, 1, 'Legacy question?');
                INSERT INTO attempts (id, quiz_id, score, total, percent, mode)
                    VALUES ('legacy-attempt', 1, 0, 1, 0, 'Exam');
                INSERT INTO missed_questions (id, attempt_id, question_id, correct_letters)
                    VALUES (20, 'legacy-attempt', 10, 'A');
            """)
            conn.commit()
        finally:
            conn.close()

    def _current_database(self, path, title="Restored Current"):
        dlms.bootstrap_database(str(path), require_owned_root=False)
        self._set_quiz_title(path, title)

    def _archive(self, database, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": dlms.DLMS_BACKUP_SCHEMA_VERSION,
            "kind": "dlms-portable-backup",
            "created_at": "2026-08-29T12:00:00-05:00",
            "dlms_version": dlms.APP_VERSION,
            "file_count": 1,
            "included_roots": ["results.db"],
            "summary": {},
        }
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(manifest))
            archive.write(database, dlms.DLMS_BACKUP_DATA_PREFIX + "results.db")
        return destination

    def _stage_archive(self, database, token_char="a"):
        token = token_char * 32
        stage = self.restore_staging / token
        stage.mkdir()
        self._archive(database, stage / "restore.zip")
        return token, stage

    def _safety_archive(self):
        return self._archive(self.db_path, self.live / "backups" / "safety.zip")

    def _confirm(self, token):
        return self.client.post(
            f"/settings/data/restore/confirm/{token}",
            headers=csrf_headers(self.client),
        )

    def test_supported_v1_backup_is_migrated_before_live_apply_and_preserves_data(self):
        legacy = self.root / "legacy.db"
        self._legacy_database(legacy)
        token, _stage = self._stage_archive(legacy)
        safety = self._safety_archive()
        original_apply = dlms._apply_restored_data
        events = []

        def apply_checked(staged_root):
            events.append(("apply", self._schema_version(Path(staged_root) / "results.db")))
            return original_apply(staged_root)

        def reconcile_checked():
            events.append(("reconcile", self._schema_version(self.db_path)))
            return {"processed": 0, "failed": 0}

        with mock.patch.object(dlms, "_create_dlms_backup", return_value=(str(safety), {})), \
             mock.patch.object(dlms, "_ensure_runtime_data_dirs"), \
             mock.patch.object(dlms, "_apply_restored_data", side_effect=apply_checked), \
             mock.patch.object(dlms, "reconcile_quiz_publications", side_effect=reconcile_checked):
            response = self._confirm(token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events, [("apply", 2), ("reconcile", 2)])
        self.assertEqual(list(Path(dlms._restore_operation_root()).glob("restore_*.json")), [])
        self.assertEqual(self._schema_version(self.db_path), 2)
        self.assertEqual(self._quiz_title(self.db_path), "Restored Legacy")
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT attempt_id, question_id, correct_letters FROM missed_questions"
                ).fetchone(),
                ("legacy-attempt", 10, "A"),
            )
        finally:
            conn.close()

    def test_current_staged_database_validates_without_running_migration(self):
        staged = self.restore_staging / "current-check"
        staged.mkdir()
        database = staged / "results.db"
        self._current_database(database)
        before = database.stat().st_mtime_ns
        migration = mock.Mock(side_effect=AssertionError("migration must not run"))

        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS, {2: migration}):
            result = dlms._prepare_staged_restore_database(str(staged))

        self.assertEqual(result["bootstrap"]["status"], "current")
        self.assertEqual(result["validation"]["version"], 2)
        self.assertEqual(database.stat().st_mtime_ns, before)
        migration.assert_not_called()

    def test_current_backup_restores_normally_without_migration(self):
        current = self.root / "current-restore.db"
        self._current_database(current, "Restored Current")
        token, _stage = self._stage_archive(current, "9")
        safety = self._safety_archive()
        migration = mock.Mock(side_effect=AssertionError("migration must not run"))

        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS, {2: migration}), \
             mock.patch.object(dlms, "_create_dlms_backup", return_value=(str(safety), {})), \
             mock.patch.object(dlms, "_ensure_runtime_data_dirs"), \
             mock.patch.object(dlms, "reconcile_quiz_publications", return_value={"processed": 0}):
            response = self._confirm(token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._quiz_title(self.db_path), "Restored Current")
        self.assertEqual(self._schema_version(self.db_path), 2)
        self.assertEqual(list(Path(dlms._restore_operation_root()).glob("restore_*.json")), [])
        migration.assert_not_called()

    def test_future_backup_is_rejected_before_safety_backup_or_live_change(self):
        future = self.root / "future.db"
        self._current_database(future, "Future Restore")
        conn = sqlite3.connect(future)
        conn.execute("UPDATE schema_meta SET version=999 WHERE id=1")
        conn.commit()
        conn.close()
        token, stage = self._stage_archive(future, "b")

        with mock.patch.object(dlms, "_create_dlms_backup") as safety:
            response = self._confirm(token)

        self.assertEqual(response.status_code, 400)
        self.assertIn(dlms.RESTORE_FUTURE_SCHEMA_PUBLIC_ERROR, response.get_data(as_text=True))
        self.assertEqual(self._quiz_title(self.db_path), "Original Live")
        self.assertEqual(self.live_sentinel.read_text(encoding="utf-8"), "original")
        safety.assert_not_called()
        self.assertFalse(stage.exists())

    def test_injected_staged_migration_failure_leaves_live_data_untouched(self):
        legacy = self.root / "migration-failure.db"
        self._legacy_database(legacy)
        token, stage = self._stage_archive(legacy, "c")

        def fail_migration(_conn):
            raise sqlite3.OperationalError("database or disk is full")

        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS, {2: fail_migration}), \
             mock.patch.object(dlms, "_create_dlms_backup") as safety:
            response = self._confirm(token)

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b"disk is full", response.data)
        self.assertEqual(self._quiz_title(self.db_path), "Original Live")
        self.assertEqual(self.live_sentinel.read_text(encoding="utf-8"), "original")
        safety.assert_not_called()
        self.assertFalse(stage.exists())

    def test_staged_post_migration_validation_failure_precedes_live_apply(self):
        current = self.root / "invalid-after-migration.db"
        self._current_database(current)
        token, _stage = self._stage_archive(current, "d")

        with mock.patch.object(
            dlms, "_validate_current_restored_database", side_effect=ValueError("missing index")
        ), mock.patch.object(dlms, "_create_dlms_backup") as safety, mock.patch.object(
            dlms, "_apply_restored_data"
        ) as apply:
            response = self._confirm(token)

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b"missing index", response.data)
        self.assertEqual(self._quiz_title(self.db_path), "Original Live")
        safety.assert_not_called()
        apply.assert_not_called()

    def test_post_apply_reconciliation_failure_restores_safety_backup(self):
        restored = self.root / "post-apply.db"
        self._current_database(restored, "Failed Restore")
        token, _stage = self._stage_archive(restored, "e")
        safety = self._safety_archive()
        seen_titles = []

        def reconcile():
            seen_titles.append(self._quiz_title(self.db_path))
            if len(seen_titles) == 1:
                raise RuntimeError("post-apply failure")
            return {"processed": 0, "failed": 0}

        with mock.patch.object(dlms, "_create_dlms_backup", return_value=(str(safety), {})), \
             mock.patch.object(dlms, "_ensure_runtime_data_dirs"), \
             mock.patch.object(dlms, "reconcile_quiz_publications", side_effect=reconcile):
            response = self._confirm(token)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(seen_titles, ["Failed Restore", "Original Live"])
        self.assertEqual(self._quiz_title(self.db_path), "Original Live")
        self.assertEqual(self._schema_version(self.db_path), 2)
        self.assertNotIn(b"post-apply failure", response.data)

    def test_rollback_failure_is_logged_and_not_reported_as_success(self):
        restored = self.root / "rollback-failure.db"
        self._current_database(restored)
        token, _stage = self._stage_archive(restored, "f")
        safety = self._safety_archive()
        apply = mock.Mock(side_effect=[RuntimeError("apply failed"), RuntimeError("rollback failed")])

        with mock.patch.object(dlms, "_create_dlms_backup", return_value=(str(safety), {})), \
             mock.patch.object(dlms, "_ensure_runtime_data_dirs"), \
             mock.patch.object(dlms, "_apply_restored_data", apply), \
             mock.patch("builtins.print") as logged:
            response = self._confirm(token)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(apply.call_count, 2)
        self.assertTrue(any("automatic rollback also failed" in str(call) for call in logged.call_args_list))
        self.assertIn(b"could not complete the restore", response.data)
        self.assertEqual(len(list(Path(dlms._restore_operation_root()).glob("restore_*.json"))), 1)
        self.assertTrue(safety.exists())

    def test_unowned_live_root_blocks_restore_before_migration_or_backup(self):
        current = self.root / "unowned-source.db"
        self._current_database(current)
        token, _stage = self._stage_archive(current, "1")
        unowned = self.root / "unowned-live"
        unowned.mkdir()

        with mock.patch.object(dlms, "APP_DATA_DIR", str(unowned)), \
             mock.patch.object(dlms, "bootstrap_database") as bootstrap, \
             mock.patch.object(dlms, "_create_dlms_backup") as safety:
            response = self._confirm(token)

        self.assertEqual(response.status_code, 409)
        bootstrap.assert_not_called()
        safety.assert_not_called()
        self.assertIn(b"not verified", response.data)

    def test_corrupt_staged_database_is_rejected_without_live_mutation(self):
        corrupt = self.root / "corrupt.db"
        corrupt.write_bytes(b"not sqlite")
        token, _stage = self._stage_archive(corrupt, "2")

        with mock.patch.object(dlms, "_create_dlms_backup") as safety:
            response = self._confirm(token)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._quiz_title(self.db_path), "Original Live")
        safety.assert_not_called()


if __name__ == "__main__":
    unittest.main()
