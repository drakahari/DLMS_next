"""DLMS-056 existing-quiz mutation atomicity regressions."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-quiz-mutation-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


def _bind_paths():
    root = Path(_TEMP.name)
    dlms._initialize_data_root_ownership(str(root))
    dlms.APP_DATA_DIR = str(root)
    dlms.DATA_FOLDER = str(root / "data")
    dlms.QUIZ_FOLDER = str(root / "quizzes")
    dlms.CONFIG_FOLDER = str(root / "config")
    dlms.QUIZ_REGISTRY = str(root / "config" / "quizzes.json")
    dlms.REGISTRY_FILE = dlms.QUIZ_REGISTRY
    dlms.DB_PATH = str(root / "results.db")
    dlms.QUIZ_ASSET_FOLDER = str(root / "quiz_assets")
    dlms.LOGO_FOLDER = str(root / "static" / "logos")
    dlms.LOGO_TEMP_FOLDER = str(root / "static" / "logos" / "_temp")
    for path in (
        dlms.DATA_FOLDER,
        dlms.QUIZ_FOLDER,
        dlms.CONFIG_FOLDER,
        dlms.QUIZ_ASSET_FOLDER,
        dlms.LOGO_FOLDER,
        dlms.LOGO_TEMP_FOLDER,
    ):
        os.makedirs(path, exist_ok=True)


class QuizMutationAtomicityTests(unittest.TestCase):
    def setUp(self):
        for child in Path(_TEMP.name).iterdir():
            if child.name in {dlms.DLMS_DATA_ROOT_MARKER, ".secret_key"}:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        _bind_paths()
        dlms.ensure_db_initialized()
        self.quiz_id, self.html_name = dlms._publish_quiz(
            "Original quiz",
            [{
                "number": 1,
                "type": "choice",
                "question": "Original question",
                "explanation": "Original explanation",
                "concepts": ["original-concept"],
                "choices": [
                    {"label": "A", "text": "Correct", "is_correct": True},
                    {"label": "B", "text": "Incorrect", "is_correct": False},
                ],
            }],
            filename_prefix="mutation_test",
            exam_minutes=30,
        )
        conn = dlms.get_db()
        try:
            question = conn.execute(
                "SELECT id FROM questions WHERE quiz_id = ?", (self.quiz_id,)
            ).fetchone()
            self.question_id = question["id"]
            self.choices = conn.execute(
                "SELECT id, label FROM choices WHERE question_id = ? ORDER BY label",
                (self.question_id,),
            ).fetchall()
        finally:
            conn.close()
        self.client = dlms.app.test_client()

    def _edit_form(self, *, valid=True):
        data = {
            "quiz_title": "Changed quiz",
            "exam_minutes": "45",
            f"question_{self.question_id}": "Changed question",
            f"explanation_{self.question_id}": "Changed explanation",
            f"concepts_{self.question_id}": "changed-concept",
        }
        for choice in self.choices:
            data[f"choice_{choice['id']}"] = f"Changed {choice['label']}"
        if valid:
            data[f"correct_{self.choices[0]['id']}"] = "on"
        return data

    def _snapshot(self):
        conn = dlms.get_db()
        try:
            db = {
                "quiz": tuple(conn.execute(
                    "SELECT id, title FROM quizzes WHERE id = ?", (self.quiz_id,)
                ).fetchone()),
                "question": tuple(conn.execute(
                    "SELECT question_text, explanation FROM questions WHERE id = ?",
                    (self.question_id,),
                ).fetchone()),
                "choices": [tuple(row) for row in conn.execute(
                    "SELECT label, text, is_correct FROM choices WHERE question_id = ? ORDER BY label",
                    (self.question_id,),
                ).fetchall()],
                "concepts": dlms._question_concepts(conn.cursor(), self.question_id),
            }
        finally:
            conn.close()
        registry_path = Path(dlms.QUIZ_REGISTRY)
        json_path = Path(dlms.DATA_FOLDER) / self.html_name.replace(".html", ".json")
        html_path = Path(dlms.QUIZ_FOLDER) / self.html_name
        return {
            "db": db,
            "registry": registry_path.read_bytes(),
            "json": json_path.read_bytes(),
            "html": html_path.read_bytes(),
        }

    def _assert_no_mutation_staging(self):
        root = Path(dlms._quiz_publication_staging_root())
        leftovers = list(root.glob("mutation_*")) if root.exists() else []
        self.assertEqual([], leftovers)

    def test_rejected_edit_leaves_db_registry_and_artifacts_unchanged(self):
        before = self._snapshot()
        response = self.client.post(
            f"/edit_quiz/{self.quiz_id}",
            data=self._edit_form(valid=False),
            headers=csrf_headers(self.client),
        )
        self.assertEqual(302, response.status_code)
        self.assertEqual(before, self._snapshot())
        self._assert_no_mutation_staging()

    def test_html_generation_failure_rolls_back_complete_edit(self):
        before = self._snapshot()
        with mock.patch.object(dlms, "build_quiz_html", side_effect=RuntimeError("render failed")):
            response = self.client.post(
                f"/edit_quiz/{self.quiz_id}",
                data=self._edit_form(),
                headers=csrf_headers(self.client),
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual(before, self._snapshot())
        self._assert_no_mutation_staging()

    def test_json_write_failure_rolls_back_complete_edit(self):
        before = self._snapshot()
        with mock.patch.object(
            dlms, "_write_staged_quiz_json", side_effect=RuntimeError("write failed")
        ):
            response = self.client.post(
                f"/edit_quiz/{self.quiz_id}",
                data=self._edit_form(),
                headers=csrf_headers(self.client),
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual(before, self._snapshot())
        self._assert_no_mutation_staging()

    def test_second_artifact_promotion_failure_restores_first_artifact(self):
        before = self._snapshot()
        original_replace = dlms.os.replace

        def fail_html_promotion(source, target):
            if "mutation_" in source and target.endswith(".html"):
                raise RuntimeError("HTML promotion failed")
            return original_replace(source, target)

        with mock.patch.object(dlms.os, "replace", side_effect=fail_html_promotion):
            response = self.client.post(
                f"/edit_quiz/{self.quiz_id}",
                data=self._edit_form(),
                headers=csrf_headers(self.client),
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual(before, self._snapshot())
        self._assert_no_mutation_staging()

    def test_json_artifact_promotion_failure_restores_complete_edit(self):
        before = self._snapshot()
        original_replace = dlms.os.replace

        def fail_json_promotion(source, target):
            if "mutation_" in source and target.endswith(".json"):
                raise RuntimeError("JSON promotion failed")
            return original_replace(source, target)

        with mock.patch.object(dlms.os, "replace", side_effect=fail_json_promotion):
            response = self.client.post(
                f"/edit_quiz/{self.quiz_id}",
                data=self._edit_form(),
                headers=csrf_headers(self.client),
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual(before, self._snapshot())
        self._assert_no_mutation_staging()

    def test_registry_write_failure_rolls_back_db_and_promoted_artifacts(self):
        before = self._snapshot()
        original_save = dlms.save_registry
        calls = 0

        def fail_candidate_once(registry):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("registry failed")
            return original_save(registry)

        with mock.patch.object(dlms, "save_registry", side_effect=fail_candidate_once):
            response = self.client.post(
                f"/edit_quiz/{self.quiz_id}",
                data=self._edit_form(),
                headers=csrf_headers(self.client),
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual(before, self._snapshot())
        self._assert_no_mutation_staging()

    def test_edit_commit_failure_restores_registry_database_and_artifacts(self):
        before = self._snapshot()
        with mock.patch.object(
            dlms, "_commit_quiz_mutation", side_effect=RuntimeError("commit failed")
        ):
            response = self.client.post(
                f"/edit_quiz/{self.quiz_id}",
                data=self._edit_form(),
                headers=csrf_headers(self.client),
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual(before, self._snapshot())
        self._assert_no_mutation_staging()

    def test_deletion_commit_failure_restores_registry_and_database(self):
        before = self._snapshot()
        with mock.patch.object(
            dlms, "_commit_quiz_deletion", side_effect=RuntimeError("commit failed")
        ):
            response = self.client.post(
                f"/delete_quiz/{self.quiz_id}", headers=csrf_headers(self.client)
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual(before, self._snapshot())

    def test_deletion_registry_failure_never_deletes_database_or_artifacts(self):
        before = self._snapshot()
        with mock.patch.object(
            dlms, "save_registry", side_effect=RuntimeError("registry failed")
        ):
            response = self.client.post(
                f"/delete_quiz/{self.quiz_id}", headers=csrf_headers(self.client)
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual(before, self._snapshot())

    def test_successful_deletion_removes_only_the_quiz_owned_artifact_bucket(self):
        owned_bucket = Path(dlms.QUIZ_ASSET_FOLDER) / Path(self.html_name).stem
        owned_bucket.mkdir(parents=True)
        (owned_bucket / "owned.png").write_bytes(b"owned")
        unrelated_bucket = Path(dlms.QUIZ_ASSET_FOLDER) / "unrelated"
        unrelated_bucket.mkdir()
        (unrelated_bucket / "keep.png").write_bytes(b"keep")

        response = self.client.post(
            f"/delete_quiz/{self.quiz_id}", headers=csrf_headers(self.client)
        )

        self.assertEqual(302, response.status_code)
        self.assertFalse(owned_bucket.exists())
        self.assertEqual(b"keep", (unrelated_bucket / "keep.png").read_bytes())
        self.assertEqual([], dlms.load_registry())
        conn = dlms.get_db()
        try:
            self.assertIsNone(
                conn.execute(
                    "SELECT id FROM quizzes WHERE id = ?", (self.quiz_id,)
                ).fetchone()
            )
        finally:
            conn.close()

    def test_deleting_one_quiz_preserves_a_logo_shared_by_another_quiz(self):
        logo = Path(dlms.LOGO_FOLDER) / "shared.png"
        logo.write_bytes(b"shared-logo")
        registry = dlms.load_registry()
        registry[0]["logo"] = logo.name
        dlms.save_registry(registry)
        other_id, _ = dlms._publish_quiz(
            "Other quiz",
            [{
                "number": 1,
                "type": "choice",
                "question": "Other question",
                "choices": [
                    {"label": "A", "text": "Correct", "is_correct": True},
                    {"label": "B", "text": "Incorrect", "is_correct": False},
                ],
            }],
            filename_prefix="shared_logo_other",
            logo_filename=logo.name,
        )

        response = self.client.post(
            f"/delete_quiz/{self.quiz_id}", headers=csrf_headers(self.client)
        )

        self.assertEqual(302, response.status_code)
        self.assertEqual(b"shared-logo", logo.read_bytes())
        self.assertEqual([other_id], [entry["id"] for entry in dlms.load_registry()])

    def test_deleting_the_only_logo_owner_removes_the_owned_logo(self):
        logo = Path(dlms.LOGO_FOLDER) / "owned.png"
        logo.write_bytes(b"owned-logo")
        registry = dlms.load_registry()
        registry[0]["logo"] = logo.name
        dlms.save_registry(registry)

        response = self.client.post(
            f"/delete_quiz/{self.quiz_id}", headers=csrf_headers(self.client)
        )

        self.assertEqual(302, response.status_code)
        self.assertFalse(logo.exists())
        self.assertEqual([], dlms.load_registry())

    def test_artifact_cleanup_failure_does_not_reverse_committed_deletion(self):
        html_path = Path(dlms.QUIZ_FOLDER) / self.html_name
        original_remove = dlms.os.remove

        def fail_html_cleanup(path):
            if os.path.abspath(path) == os.path.abspath(html_path):
                raise OSError("simulated cleanup failure")
            return original_remove(path)

        with mock.patch.object(dlms.os, "remove", side_effect=fail_html_cleanup):
            response = self.client.post(
                f"/delete_quiz/{self.quiz_id}", headers=csrf_headers(self.client)
            )

        self.assertEqual(302, response.status_code)
        self.assertTrue(html_path.exists())
        self.assertEqual([], dlms.load_registry())
        conn = dlms.get_db()
        try:
            self.assertIsNone(
                conn.execute(
                    "SELECT id FROM quizzes WHERE id = ?", (self.quiz_id,)
                ).fetchone()
            )
        finally:
            conn.close()

    def test_successful_edit_updates_all_stores_and_keeps_valid_json(self):
        response = self.client.post(
            f"/edit_quiz/{self.quiz_id}",
            data=self._edit_form(),
            headers=csrf_headers(self.client),
        )
        self.assertEqual(302, response.status_code)
        snapshot = self._snapshot()
        self.assertEqual((self.quiz_id, "Changed quiz"), snapshot["db"]["quiz"])
        registry = json.loads(snapshot["registry"])
        self.assertEqual("Changed quiz", registry[0]["title"])
        self.assertEqual(45, registry[0]["exam_minutes"])
        payload = json.loads(snapshot["json"])
        self.assertEqual("Changed question", payload[0]["question"])
        self.assertIn(b"Changed quiz", snapshot["html"])
        self._assert_no_mutation_staging()


if __name__ == "__main__":
    unittest.main()
