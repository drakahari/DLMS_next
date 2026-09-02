"""Regression coverage for the manual Create a Short Quiz workflow."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-short-quiz-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


def _bind_paths():
    root = Path(_TEMP.name)
    dlms._initialize_data_root_ownership(str(root))
    dlms.APP_DATA_DIR = str(root)
    dlms.DATA_FOLDER = str(root / "data")
    dlms.QUIZ_FOLDER = str(root / "quizzes")
    dlms.CONFIG_FOLDER = str(root / "config")
    dlms.PORTAL_CONFIG = str(root / "config" / "portal.json")
    dlms.QUIZ_REGISTRY = str(root / "config" / "quizzes.json")
    dlms.REGISTRY_FILE = dlms.QUIZ_REGISTRY
    dlms.DB_PATH = str(root / "results.db")
    dlms.LOGO_FOLDER = str(root / "static" / "logos")
    dlms.LOGO_TEMP_FOLDER = str(root / "static" / "logos" / "_temp")
    for path in (
        dlms.DATA_FOLDER,
        dlms.QUIZ_FOLDER,
        dlms.CONFIG_FOLDER,
        dlms.LOGO_FOLDER,
        dlms.LOGO_TEMP_FOLDER,
    ):
        os.makedirs(path, exist_ok=True)


class ShortQuizWorkflowTests(unittest.TestCase):
    def setUp(self):
        root = Path(_TEMP.name)
        for child in root.iterdir():
            if child.name in {dlms.DLMS_DATA_ROOT_MARKER, ".secret_key"}:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        _bind_paths()
        dlms.ensure_db_initialized()
        self.client = dlms.app.test_client()

    def test_builder_renumbers_matching_controls_on_each_question(self):
        response = self.client.get("/create_short_quiz?count=1")
        page = response.get_data(as_text=True)

        self.assertEqual(200, response.status_code)
        self.assertIn('id="create-short-quiz-form"', page)
        self.assertIn(
            'const roundSize = question.querySelector(".matching-round-size");',
            page,
        )
        self.assertIn(
            'const direction = question.querySelector(".matching-direction");',
            page,
        )
        self.assertNotIn('block.querySelector(".matching-round-size")', page)
        self.assertNotIn('block.querySelector(".matching-direction")', page)

    def test_choice_quiz_creation_publishes_db_registry_json_and_html(self):
        upload_page = self.client.get("/upload")
        self.assertEqual(200, upload_page.status_code)
        self.assertIn('href="/create_short_quiz"', upload_page.get_data(as_text=True))

        response = self.client.post(
            "/create_short_quiz",
            data={
                "quiz_title": "RC2 Short Quiz",
                "exam_minutes": "30",
                "question_type_1": "choice",
                "question_1": "What is 2 + 2?",
                "choice_1_A": "4",
                "choice_1_B": "5",
                "correct_1_A": "on",
            },
            content_type="multipart/form-data",
            headers={"X-CSRFToken": csrf_token(self.client, "/create_short_quiz?count=1")},
            follow_redirects=False,
        )

        self.assertEqual(302, response.status_code)
        registry = dlms.load_registry()
        self.assertEqual(1, len(registry))
        quiz_id = registry[0]["id"]
        self.assertEqual(f"/edit_quiz/{quiz_id}", response.headers["Location"])

        connection = dlms.get_db()
        try:
            quiz = connection.execute(
                "SELECT title FROM quizzes WHERE id = ?", (quiz_id,)
            ).fetchone()
            question = connection.execute(
                "SELECT id, question_text FROM questions WHERE quiz_id = ?", (quiz_id,)
            ).fetchone()
            choices = connection.execute(
                "SELECT label, text, is_correct FROM choices "
                "WHERE question_id = ? ORDER BY label",
                (question["id"],),
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual("RC2 Short Quiz", quiz["title"])
        self.assertEqual("What is 2 + 2?", question["question_text"])
        self.assertEqual(
            [("A", "4", 1), ("B", "5", 0)],
            [tuple(choice) for choice in choices],
        )
        html_name = registry[0]["html"]
        self.assertTrue((Path(dlms.QUIZ_FOLDER) / html_name).is_file())
        self.assertTrue((Path(dlms.DATA_FOLDER) / html_name.replace(".html", ".json")).is_file())


if __name__ == "__main__":
    unittest.main()
