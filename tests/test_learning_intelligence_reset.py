import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-learning-reset-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


class LearningIntelligenceResetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-learning-reset-")
        self.addCleanup(self.temporary.cleanup)
        self.data_root = Path(self.temporary.name)
        self.db_path = str(self.data_root / "results.db")
        self.app_data_patch = mock.patch.object(dlms, "APP_DATA_DIR", str(self.data_root))
        self.db_patch = mock.patch.object(dlms, "DB_PATH", self.db_path)
        self.app_data_patch.start()
        self.db_patch.start()
        self.addCleanup(self.app_data_patch.stop)
        self.addCleanup(self.db_patch.stop)
        self.assertTrue(dlms._initialize_data_root_ownership(str(self.data_root)))
        dlms.ensure_db_initialized()

    def _seed_preserved_data(self):
        conn = dlms.get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO quizzes (title, source_file) VALUES (?, ?)", ("Retained Quiz", "retained.json"))
        quiz_id = cur.lastrowid
        cur.execute(
            "INSERT INTO questions (quiz_id, question_number, question_text) VALUES (?, ?, ?)",
            (quiz_id, 1, "Retained question"),
        )
        question_id = cur.lastrowid
        cur.execute("INSERT INTO concepts (name) VALUES (?)", ("Retained concept",))
        concept_id = cur.lastrowid
        cur.execute(
            "INSERT INTO question_concepts (question_id, concept_id) VALUES (?, ?)",
            (question_id, concept_id),
        )
        cur.execute(
            "INSERT INTO attempts (id, quiz_id, score, total, percent, mode) VALUES (?, ?, ?, ?, ?, ?)",
            ("retained-attempt", quiz_id, 0, 1, 0, "Exam"),
        )
        cur.execute(
            "INSERT INTO attempt_answers (attempt_id, question_id, selected_labels, was_correct) VALUES (?, ?, ?, ?)",
            ("retained-attempt", question_id, "B", 0),
        )
        cur.execute(
            "INSERT INTO missed_questions (attempt_id, question_id, question_text) VALUES (?, ?, ?)",
            ("retained-attempt", question_id, "Retained question"),
        )
        dlms._record_learning_event(
            cur,
            event_type="exam_answer",
            quiz_id=quiz_id,
            question_id=question_id,
            attempt_id="retained-attempt",
            mode="Exam",
            was_correct=False,
        )
        conn.commit()
        conn.close()

    def _table_counts(self):
        conn = dlms.get_db()
        try:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "quizzes", "questions", "concepts", "question_concepts", "attempts",
                    "attempt_answers", "missed_questions", "learning_events",
                )
            }
        finally:
            conn.close()

    def test_reset_clears_only_learning_events(self):
        self._seed_preserved_data()
        before = self._table_counts()

        dlms._reset_learning_intelligence_core()

        after = self._table_counts()
        self.assertEqual(after["learning_events"], 0)
        for table, count in before.items():
            if table != "learning_events":
                self.assertEqual(after[table], count, table)

        conn = dlms.get_db()
        try:
            payload = dlms._learning_intelligence_payload(conn.cursor())
        finally:
            conn.close()
        self.assertEqual(payload["summary"]["concepts_with_evidence"], 0)
        self.assertEqual(payload["summary"]["concepts"], 1)
        self.assertEqual(payload["topics"][0]["name"], "Retained concept")
        self.assertEqual(payload["topics"][0]["evidence"], 0)

    def test_reset_rolls_back_when_learning_event_delete_fails(self):
        self._seed_preserved_data()
        conn = dlms.get_db()
        event = conn.execute(
            "SELECT quiz_id, question_id FROM learning_events LIMIT 1"
        ).fetchone()
        dlms._record_learning_event(
            conn.cursor(),
            event_type="study_answer",
            quiz_id=event["quiz_id"],
            question_id=event["question_id"],
            session_id="retained-study-session",
            mode="Study",
            was_correct=True,
        )
        conn.execute("""
            CREATE TRIGGER fail_learning_intelligence_reset
            AFTER DELETE ON learning_events
            BEGIN
                SELECT RAISE(ABORT, 'simulated reset failure');
            END
        """)
        conn.commit()
        conn.close()

        with self.assertRaises(sqlite3.IntegrityError):
            dlms._reset_learning_intelligence_core()

        self.assertEqual(self._table_counts()["learning_events"], 2)

    def test_reset_route_uses_safety_backup_wrapper(self):
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_run_reset_with_backup", return_value="safety.zip") as reset:
            response = client.post("/api/reset_learning_intelligence", headers=csrf_headers(client))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok", "backup": "safety.zip"})
        reset.assert_called_once_with("learning-intelligence", dlms._reset_learning_intelligence_core)

    def test_reset_page_explains_scope_and_preserved_data(self):
        client = dlms.app.test_client()
        response = client.get("/settings/reset-remove")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Reset Learning Intelligence", page)
        self.assertIn("/api/reset_learning_intelligence", page)
        self.assertIn("saved attempts, missed-question history", page)


if __name__ == "__main__":
    unittest.main()
