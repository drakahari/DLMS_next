import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_TEMP = tempfile.TemporaryDirectory(prefix="dlms-bootstrap-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms


class DatabaseBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-schema-fixture-")
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "results.db"

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _tables(conn):
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }

    @staticmethod
    def _columns(conn, table):
        return {row[1]: row for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}

    def _legacy_database(self, *, nullable_question_id=False, include_schema_meta=True):
        question_id_definition = "INTEGER" if nullable_question_id else "INTEGER NOT NULL"
        conn = sqlite3.connect(self.db_path)
        conn.executescript(f"""
            PRAGMA foreign_keys = OFF;
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
                question_id {question_id_definition},
                correct_letters TEXT NOT NULL
            );
            INSERT INTO quizzes (id, title, source_file) VALUES (1, 'Legacy Quiz', 'legacy.html');
            INSERT INTO questions (id, quiz_id, question_number, question_text)
                VALUES (10, 1, 1, 'Legacy question?');
            INSERT INTO attempts (id, quiz_id, score, total, percent, mode)
                VALUES ('legacy-attempt', 1, 0, 1, 0, 'Exam');
            INSERT INTO missed_questions (id, attempt_id, question_id, correct_letters)
                VALUES (20, 'legacy-attempt', 10, 'A');
        """)
        if include_schema_meta:
            conn.executescript("""
                CREATE TABLE schema_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO schema_meta (id, version) VALUES (1, 1);
            """)
        conn.commit()
        conn.close()

    def test_fresh_database_is_complete_current_and_get_db_is_connection_only(self):
        result = dlms.bootstrap_database(str(self.db_path), require_owned_root=False)
        self.assertEqual(result, {"status": "created", "version": dlms.DLMS_SCHEMA_VERSION})

        conn = sqlite3.connect(self.db_path)
        try:
            self.assertTrue(set(dlms.DLMS_SCHEMA_COLUMNS).issubset(self._tables(conn)))
            for table, expected in dlms.DLMS_SCHEMA_COLUMNS.items():
                self.assertTrue(expected.issubset(self._columns(conn, table)), table)
            indexes = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            }
            self.assertTrue(dlms.DLMS_SCHEMA_INDEXES.issubset(indexes))
            self.assertEqual(
                conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0],
                dlms.DLMS_SCHEMA_VERSION,
            )
            self.assertEqual(self._columns(conn, "missed_questions")["question_id"][3], 0)
        finally:
            conn.close()

        traced = []
        connections = [sqlite3.connect(self.db_path), sqlite3.connect(self.db_path)]
        for connection in connections:
            connection.row_factory = sqlite3.Row
            connection.set_trace_callback(traced.append)
        with mock.patch.object(dlms, "DB_PATH", str(self.db_path)), mock.patch.object(
            dlms.sqlite3, "connect", side_effect=connections
        ):
            first = dlms.get_db()
            first.close()
            second = dlms.get_db()
            second.close()
        statements = [statement.strip().upper() for statement in traced]
        self.assertTrue(statements)
        self.assertTrue(all(statement == "PRAGMA FOREIGN_KEYS = ON" for statement in statements))

    def test_current_bootstrap_is_idempotent_and_preserves_data(self):
        dlms.bootstrap_database(str(self.db_path), require_owned_root=False)
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO quizzes (title, source_file) VALUES ('Keep Me', 'keep.html')")
        conn.commit()
        conn.close()

        first = dlms.bootstrap_database(str(self.db_path), require_owned_root=False)
        second = dlms.bootstrap_database(str(self.db_path), require_owned_root=False)
        self.assertEqual(first["status"], "current")
        self.assertEqual(second["status"], "current")
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT title FROM quizzes").fetchone()[0], "Keep Me")
        finally:
            conn.close()

    def test_version_one_migration_repairs_all_legacy_shapes_and_preserves_data(self):
        self._legacy_database()
        calls = []
        original = dlms.DLMS_SCHEMA_MIGRATIONS[2]

        def recorded(conn):
            calls.append(2)
            original(conn)

        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS, {2: recorded}):
            result = dlms.bootstrap_database(str(self.db_path), require_owned_root=False)
        self.assertEqual(result, {"status": "migrated", "version": 2, "from_version": 1})
        self.assertEqual(calls, [2])

        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0], 2)
            self.assertEqual(conn.execute(
                "SELECT id, attempt_id, question_id, correct_letters FROM missed_questions"
            ).fetchone(), (20, "legacy-attempt", 10, "A"))
            self.assertEqual(self._columns(conn, "missed_questions")["question_id"][3], 0)
            self.assertTrue(dlms.DLMS_SCHEMA_COLUMNS["missed_questions"].issubset(
                self._columns(conn, "missed_questions")
            ))
            self.assertIn("registry_id", self._columns(conn, "quizzes"))
            self.assertTrue(dlms.DLMS_SCHEMA_COLUMNS["questions"].issubset(
                self._columns(conn, "questions")
            ))
            self.assertTrue(dlms.DLMS_SCHEMA_COLUMNS["matching_pairs"].issubset(
                self._columns(conn, "matching_pairs")
            ))
            self.assertTrue({"concepts", "question_concepts", "learning_events"}.issubset(
                self._tables(conn)
            ))
            indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertTrue(dlms.DLMS_SCHEMA_INDEXES.issubset(indexes))
        finally:
            conn.close()

    def test_nullable_legacy_snapshot_fields_and_unversioned_database_migrate(self):
        self._legacy_database(nullable_question_id=True, include_schema_meta=False)
        result = dlms.bootstrap_database(str(self.db_path), require_owned_root=False)
        self.assertEqual(result["from_version"], 1)
        conn = sqlite3.connect(self.db_path)
        try:
            columns = self._columns(conn, "missed_questions")
            self.assertEqual(columns["question_id"][3], 0)
            self.assertIn("response_json", columns)
            self.assertEqual(conn.execute("SELECT correct_letters FROM missed_questions").fetchone()[0], "A")
            self.assertEqual(conn.execute("SELECT version FROM schema_meta").fetchone()[0], 2)
        finally:
            conn.close()

    def test_migration_failure_rolls_back_schema_data_and_version(self):
        self._legacy_database()

        def fail_after_ddl(conn):
            conn.execute("ALTER TABLE quizzes ADD COLUMN should_rollback TEXT")
            conn.execute("UPDATE quizzes SET title='Changed'")
            raise RuntimeError("simulated migration failure")

        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS, {2: fail_after_ddl}):
            with self.assertRaisesRegex(RuntimeError, "simulated migration failure"):
                dlms.bootstrap_database(str(self.db_path), require_owned_root=False)

        conn = sqlite3.connect(self.db_path)
        try:
            self.assertNotIn("should_rollback", self._columns(conn, "quizzes"))
            self.assertEqual(conn.execute("SELECT title FROM quizzes").fetchone()[0], "Legacy Quiz")
            self.assertEqual(conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0], 1)
        finally:
            conn.close()

    def test_future_version_is_rejected_without_mutation(self):
        dlms.bootstrap_database(str(self.db_path), require_owned_root=False)
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE schema_meta SET version=999 WHERE id=1")
        conn.execute("INSERT INTO quizzes (title, source_file) VALUES ('Future', 'future.html')")
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(RuntimeError, "newer than this DLMS build"):
            dlms.bootstrap_database(str(self.db_path), require_owned_root=False)
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT version FROM schema_meta").fetchone()[0], 999)
            self.assertEqual(conn.execute("SELECT title FROM quizzes").fetchone()[0], "Future")
        finally:
            conn.close()

    def test_bootstrap_requires_owned_root_and_startup_order_is_explicit(self):
        unowned = self.root / "unowned"
        unowned.mkdir()
        with mock.patch.object(dlms, "APP_DATA_DIR", str(unowned)):
            with self.assertRaisesRegex(RuntimeError, "verified application-data root"):
                dlms.bootstrap_database(str(unowned / "results.db"))
        self.assertFalse((unowned / "results.db").exists())

        source = Path(dlms.__file__).read_text(encoding="utf-8")
        restore_reconciliation_call = source.index("\n_run_restore_startup_reconciliation()")
        bootstrap_call = source.index("\nensure_db_initialized()", restore_reconciliation_call)
        reconciliation_call = source.index("\n_run_quiz_publication_startup_reconciliation()")
        self.assertLess(restore_reconciliation_call, bootstrap_call)
        self.assertLess(bootstrap_call, reconciliation_call)


if __name__ == "__main__":
    unittest.main()
