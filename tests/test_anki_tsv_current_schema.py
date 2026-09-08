"""Regression coverage for Anki TSV exports on the current database schema."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.current_schema import seed_current_quiz
from tests.csrf_test_utils import csrf_token


class AnkiTsvCurrentSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-anki-tsv-schema-")
        self.addCleanup(self.temporary.cleanup)
        self.db_path = Path(self.temporary.name) / "results.db"
        dlms.bootstrap_database(str(self.db_path), require_owned_root=False)

        db_path_patch = mock.patch.object(dlms, "DB_PATH", str(self.db_path))
        db_path_patch.start()
        self.addCleanup(db_path_patch.stop)
        self.client = dlms.app.test_client()

        conn = sqlite3.connect(self.db_path)
        try:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(questions)")
            }
        finally:
            conn.close()
        self.assertIn("question_number", columns)
        self.assertIn("question_text", columns)
        self.assertNotIn("number", columns)
        self.assertNotIn("text", columns)

    def _insert_quiz_question(self):
        seed_current_quiz(
            dlms.get_db,
            "Quiz One",
            "quiz-one.html",
            [{
                "id": 31,
                "number": 9,
                "question": "What\tis <x>?",
                "choices": [
                    {"label": "A", "text": "Alpha\tvalue", "is_correct": False},
                    {"label": "B", "text": "Beta", "is_correct": True},
                ],
            }],
            quiz_id=3,
        )

    def _insert_missed_attempt(self):
        self._insert_quiz_question()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO attempts (
                    id, quiz_id, score, total, percent, mode
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("attempt-current", 3, 0, 1, 0, "Exam"),
            )
            conn.execute(
                """
                INSERT INTO missed_questions (
                    attempt_id, question_id, attempt_question_number
                ) VALUES (?, ?, ?)
                """,
                ("attempt-current", 31, 1),
            )
            conn.commit()
        finally:
            conn.close()

    def _post_missed(self, question_numbers):
        return self.client.post(
            "/export/anki/missed",
            json={
                "attempt_id": "attempt-current",
                "attempt_question_numbers": question_numbers,
            },
            headers={"X-CSRFToken": csrf_token(self.client)},
        )

    def test_quiz_tsv_succeeds_and_preserves_content_on_current_schema(self):
        self._insert_quiz_question()

        response = self.client.get("/export/anki/quiz/3")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "Front\tBack\tTags\n"
            "<b>What is <x>?</b><br><br>A. Alpha value<br>B. Beta\t"
            "<b>Correct answer:</b> B<br><br>B. Beta\tQuiz_One",
            response.get_data(as_text=True),
        )
        self.assertEqual(
            "attachment; filename=quiz_3_anki.tsv",
            response.headers["Content-Disposition"],
        )

    def test_quiz_tsv_empty_database_preserves_header_only_response(self):
        response = self.client.get("/export/anki/quiz/99")

        self.assertEqual(200, response.status_code)
        self.assertEqual("Front\tBack\tTags", response.get_data(as_text=True))
        self.assertEqual(
            "attachment; filename=quiz_99_anki.tsv",
            response.headers["Content-Disposition"],
        )

    def test_missed_tsv_succeeds_and_preserves_content_on_current_schema(self):
        self._insert_missed_attempt()

        response = self._post_missed([1])

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "Front\tBack\tTags\n"
            "What is <x>?\n\nA. Alpha value\nB. Beta\t"
            "Correct: B\nB. Beta\tQuiz_One missed",
            response.get_data(as_text=True),
        )
        self.assertEqual(
            "attachment; filename=missed_questions_anki.tsv",
            response.headers["Content-Disposition"],
        )

    def test_missed_tsv_no_matching_rows_preserves_header_only_response(self):
        self._insert_missed_attempt()

        response = self._post_missed([99])

        self.assertEqual(200, response.status_code)
        self.assertEqual("Front\tBack\tTags", response.get_data(as_text=True))
        self.assertEqual(
            "attachment; filename=missed_questions_anki.tsv",
            response.headers["Content-Disposition"],
        )


if __name__ == "__main__":
    unittest.main()
