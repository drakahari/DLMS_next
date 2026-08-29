"""Focused regressions for DLMS-039 through DLMS-042."""
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-039-042-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms
from tests.csrf_test_utils import csrf_token


def _bind_paths():
    root = Path(_TEMP.name)
    dlms.APP_DATA_DIR = str(root)
    dlms.DATA_FOLDER = str(root / "data")
    dlms.QUIZ_FOLDER = str(root / "quizzes")
    dlms.CONFIG_FOLDER = str(root / "config")
    dlms.QUIZ_REGISTRY = str(root / "config" / "quizzes.json")
    dlms.REGISTRY_FILE = dlms.QUIZ_REGISTRY
    dlms.DB_PATH = str(root / "results.db")
    dlms.LOGO_FOLDER = str(root / "static" / "logos")
    dlms.LOGO_TEMP_FOLDER = str(root / "static" / "logos" / "_temp")
    for path in (dlms.DATA_FOLDER, dlms.QUIZ_FOLDER, dlms.CONFIG_FOLDER, dlms.LOGO_FOLDER, dlms.LOGO_TEMP_FOLDER):
        os.makedirs(path, exist_ok=True)


class Dlms039To042RegressionTests(unittest.TestCase):
    def setUp(self):
        for child in Path(_TEMP.name).iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        _bind_paths()
        dlms.ensure_db_initialized()

    @staticmethod
    def _choice_question(text="Question"):
        return {
            "number": 1, "question": text,
            "choices": [
                {"label": "A", "text": "One", "is_correct": True},
                {"label": "B", "text": "Two", "is_correct": False},
            ],
        }

    @staticmethod
    def _matching_question(text="Match"):
        return {
            "number": 1, "type": "matching", "question": text,
            "pairs": [
                {"left": "Alpha", "right": "First"},
                {"left": "Beta", "right": "Second"},
                {"left": "Gamma", "right": "Third"},
            ],
        }

    def _quiz(self, title, question):
        quiz_id = dlms.save_quiz_to_db(title, f"{title}.html", [question])
        dlms.add_quiz_to_registry(quiz_id, f"{title}.html", title)
        return quiz_id

    def _question_id(self, quiz_id):
        conn = dlms.get_db()
        try:
            return conn.execute("SELECT id FROM questions WHERE quiz_id = ?", (quiz_id,)).fetchone()[0]
        finally:
            conn.close()

    def test_cross_quiz_edit_actions_do_not_mutate_or_rebuild_other_quiz(self):
        quiz_a = self._quiz("quiz-a", self._choice_question("A"))
        quiz_b_choice = self._quiz("quiz-b-choice", self._choice_question("B"))
        quiz_b_match = self._quiz("quiz-b-match", self._matching_question("B match"))
        choice_question = self._question_id(quiz_b_choice)
        match_question = self._question_id(quiz_b_match)
        conn = dlms.get_db()
        try:
            choice_id = conn.execute("SELECT id FROM choices WHERE question_id = ? LIMIT 1", (choice_question,)).fetchone()[0]
            pair_id = conn.execute("SELECT id FROM matching_pairs WHERE question_id = ? LIMIT 1", (match_question,)).fetchone()[0]
            choice_count = conn.execute("SELECT COUNT(*) FROM choices WHERE question_id = ?", (choice_question,)).fetchone()[0]
            pair_count = conn.execute("SELECT COUNT(*) FROM matching_pairs WHERE question_id = ?", (match_question,)).fetchone()[0]
        finally:
            conn.close()

        client = dlms.app.test_client()
        requests = [
            (f"/edit_quiz/{quiz_a}", {"action": f"add_match_pair_{match_question}"}),
            (f"/edit_quiz/{quiz_a}", {"action": f"add_choices_{choice_question}"}),
            (f"/add_choices/{quiz_a}/{choice_question}", {"choice_count": "1"}),
            (f"/delete_choice/{quiz_a}/{choice_id}", {}),
            (f"/delete_match_pair/{quiz_a}/{pair_id}", {}),
        ]
        with mock.patch.object(dlms, "rebuild_quiz_json_from_db") as rebuild_json, \
             mock.patch.object(dlms, "rebuild_quiz_html_from_registry") as rebuild_html:
            for path, data in requests:
                response = client.post(path, data=data, headers={"X-CSRFToken": csrf_token(client)})
                self.assertEqual(302, response.status_code)
        self.assertFalse(rebuild_json.called)
        self.assertFalse(rebuild_html.called)
        conn = dlms.get_db()
        try:
            self.assertEqual(choice_count, conn.execute("SELECT COUNT(*) FROM choices WHERE question_id = ?", (choice_question,)).fetchone()[0])
            self.assertEqual(pair_count, conn.execute("SELECT COUNT(*) FROM matching_pairs WHERE question_id = ?", (match_question,)).fetchone()[0])
        finally:
            conn.close()

    def test_same_quiz_child_actions_remain_available(self):
        quiz_id = self._quiz("same-quiz", self._matching_question("Same quiz"))
        question_id = self._question_id(quiz_id)
        conn = dlms.get_db()
        try:
            pair_id = conn.execute("SELECT id FROM matching_pairs WHERE question_id = ? ORDER BY pair_order LIMIT 1", (question_id,)).fetchone()[0]
        finally:
            conn.close()
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "rebuild_quiz_json_from_db", return_value=True) as rebuild_json, \
             mock.patch.object(dlms, "rebuild_quiz_html_from_registry", return_value=True) as rebuild_html:
            add = client.post(
                f"/edit_quiz/{quiz_id}", data={"action": f"add_match_pair_{question_id}"},
                headers={"X-CSRFToken": csrf_token(client)},
            )
            delete = client.post(
                f"/delete_match_pair/{quiz_id}/{pair_id}", headers={"X-CSRFToken": csrf_token(client)},
            )
        self.assertEqual(302, add.status_code)
        self.assertEqual(302, delete.status_code)
        self.assertTrue(rebuild_json.called)
        self.assertTrue(rebuild_html.called)

    def test_manual_and_csv_matching_workflows_use_shared_validation(self):
        client = dlms.app.test_client()
        duplicate_manual = {
            "quiz_title": "Duplicate manual", "question_1": "Match", "question_type_1": "matching",
            "match_left_1_1": " Alpha ", "match_right_1_1": "First",
            "match_left_1_2": "Alpha", "match_right_1_2": "Second",
        }
        response = client.post("/create_short_quiz", data=duplicate_manual, headers={"X-CSRFToken": csrf_token(client)})
        self.assertEqual(302, response.status_code)
        self.assertEqual([], dlms.load_registry())

        csv_cases = {
            "duplicate-answer": "term,definition\nAlpha,Same\nBeta, same ",
            "unicode": "term,definition\nＡlpha,First\nAlpha,Second",
            "conflict": "term,definition\nAlpha,First\nAlpha,Second",
        }
        for name, text in csv_cases.items():
            with self.subTest(name=name):
                response = client.post(
                    "/matching_bank_import",
                    data={
                        "quiz_title": name, "csv_file": (io.BytesIO(text.encode("utf-8")), f"{name}.csv"),
                    },
                    content_type="multipart/form-data",
                    headers={"X-CSRFToken": csrf_token(client)},
                )
                self.assertEqual(302, response.status_code)
        self.assertEqual([], dlms.load_registry())

    def test_manual_matching_accepts_case_sensitive_terms_and_edit_validation_rolls_back(self):
        client = dlms.app.test_client()
        response = client.post(
            "/create_short_quiz",
            data={
                "quiz_title": "stat directives", "question_1": "Match", "question_type_1": "matching",
                "match_left_1_1": "stat %a", "match_right_1_1": "Octal permissions",
                "match_left_1_2": "stat %A", "match_right_1_2": "Symbolic permissions",
            },
            headers={"X-CSRFToken": csrf_token(client)},
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("case-only left variants", response.get_data(as_text=True))
        quiz_id = dlms.load_registry()[0]["id"]
        question_id = self._question_id(quiz_id)
        conn = dlms.get_db()
        try:
            pairs = conn.execute("SELECT id, left_text, right_text FROM matching_pairs WHERE question_id = ? ORDER BY pair_order", (question_id,)).fetchall()
        finally:
            conn.close()
        response = client.post(
            f"/edit_quiz/{quiz_id}",
            data={
                "quiz_title": "stat directives",
                f"match_left_{pairs[0]['id']}": "Alpha", f"match_right_{pairs[0]['id']}": "First",
                f"match_left_{pairs[1]['id']}": " Alpha ", f"match_right_{pairs[1]['id']}": "Second",
            },
            headers={"X-CSRFToken": csrf_token(client)},
        )
        self.assertEqual(302, response.status_code)
        conn = dlms.get_db()
        try:
            persisted = conn.execute("SELECT left_text, right_text FROM matching_pairs WHERE question_id = ? ORDER BY pair_order", (question_id,)).fetchall()
        finally:
            conn.close()
        self.assertEqual([("stat %a", "Octal permissions"), ("stat %A", "Symbolic permissions")], [tuple(row) for row in persisted])

    def test_generated_artifacts_are_unique_and_registry_entries_survive_rapid_creation(self):
        runtime = [self._choice_question("Rapid")]
        with mock.patch.object(dlms.time, "time_ns", return_value=1_700_000_000_000_000_000):
            first_id, first_html = dlms._create_quiz_from_runtime("First", runtime, runtime, filename_prefix="rapid")
            second_id, second_html = dlms._create_quiz_from_runtime("Second", runtime, runtime, filename_prefix="rapid")
        self.assertNotEqual(first_id, second_id)
        self.assertNotEqual(first_html, second_html)
        self.assertTrue((Path(dlms.QUIZ_FOLDER) / first_html).is_file())
        self.assertTrue((Path(dlms.QUIZ_FOLDER) / second_html).is_file())
        self.assertTrue((Path(dlms.DATA_FOLDER) / first_html.replace(".html", ".json")).is_file())
        self.assertTrue((Path(dlms.DATA_FOLDER) / second_html.replace(".html", ".json")).is_file())
        self.assertEqual({first_html, second_html}, {entry["html"] for entry in dlms.load_registry()})


if __name__ == "__main__":
    unittest.main()
