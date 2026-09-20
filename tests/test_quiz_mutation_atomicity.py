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
                "identity": tuple(conn.execute(
                    """
                    SELECT question_uid, canonical_question_uid,
                           source_question_uid, is_generated_copy
                    FROM questions WHERE id = ?
                    """,
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

    def _canonical_snapshot(self):
        tables = (
            "quizzes", "questions", "choices", "matching_pairs", "concepts",
            "question_concepts", "attempts", "attempt_answers",
            "missed_questions", "learning_events",
        )
        conn = dlms.get_db()
        try:
            database = {
                table: [tuple(row) for row in conn.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'
                ).fetchall()]
                for table in tables
            }
        finally:
            conn.close()
        return {
            "database": database,
            "registry": Path(dlms.QUIZ_REGISTRY).read_bytes(),
        }

    def _post_rebuild_all(self):
        return self.client.post(
            "/admin/rebuild_all_quiz_html",
            json={"confirmation": "rebuild-all-quiz-pages"},
            headers=csrf_headers(self.client, "/admin/maintenance"),
        )

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
        before_identity = self._snapshot()["db"]["identity"]
        response = self.client.post(
            f"/edit_quiz/{self.quiz_id}",
            data=self._edit_form(),
            headers=csrf_headers(self.client),
        )
        self.assertEqual(302, response.status_code)
        snapshot = self._snapshot()
        self.assertEqual((self.quiz_id, "Changed quiz"), snapshot["db"]["quiz"])
        self.assertEqual(before_identity, snapshot["db"]["identity"])
        registry = json.loads(snapshot["registry"])
        self.assertEqual("Changed quiz", registry[0]["title"])
        self.assertEqual(45, registry[0]["exam_minutes"])
        payload = json.loads(snapshot["json"])
        self.assertEqual("Changed question", payload[0]["question"])
        self.assertIn(b"Changed quiz", snapshot["html"])
        self._assert_no_mutation_staging()

    def test_rebuild_all_regenerates_choice_matching_and_generated_quiz_pages_only(self):
        matching_id, matching_html = dlms._publish_quiz(
            "Matching quiz",
            [{
                "number": 1,
                "type": "matching",
                "question": "Match each neutral term.",
                "concepts": ["matching-concept"],
                "source": {
                    "organization": "Neutral Learning Group",
                    "dataset": "Synthetic Terms",
                    "version": "1",
                    "url": "https://example.invalid/terms",
                    "license": "Synthetic test content",
                },
                "pairs": [
                    {"left": "Term one", "right": "Definition one"},
                    {"left": "Term two", "right": "Definition two"},
                ],
                "round_size": 2,
                "direction": "term_to_definition",
            }],
            filename_prefix="rebuild_matching",
        )
        generated_id, generated_html = dlms._publish_quiz(
            "Renamed generated practice",
            [{
                "number": 1,
                "type": "choice",
                "question": "Generated practice question",
                "choices": [
                    {"label": "A", "text": "First", "is_correct": True},
                    {"label": "B", "text": "Second", "is_correct": True},
                    {"label": "C", "text": "Third", "is_correct": False},
                ],
            }],
            filename_prefix="rebuild_generated",
            generation_kind="adaptive_study",
        )

        conn = dlms.get_db()
        try:
            conn.execute(
                """
                INSERT INTO attempts
                    (id, quiz_id, started_at, completed_at, score, total, percent, mode)
                VALUES ('rebuild-attempt', ?, '2026-09-14T10:00:00Z',
                        '2026-09-14T10:01:00Z', 1, 1, 100, 'Study')
                """,
                (self.quiz_id,),
            )
            conn.execute(
                """
                INSERT INTO attempt_answers
                    (attempt_id, question_id, selected_labels, was_correct)
                VALUES ('rebuild-attempt', ?, 'A', 1)
                """,
                (self.question_id,),
            )
            conn.execute(
                """
                INSERT INTO learning_events
                    (event_type, quiz_id, question_id, attempt_id, mode,
                     was_correct, response_json)
                VALUES ('study_answer', ?, ?, 'rebuild-attempt', 'Study', 1,
                        '{"selected":["A"]}')
                """,
                (self.quiz_id, self.question_id),
            )
            conn.commit()
        finally:
            conn.close()

        html_names = [self.html_name, matching_html, generated_html]
        for html_name in html_names:
            (Path(dlms.QUIZ_FOLDER) / html_name).write_text(
                "stale html", encoding="utf-8"
            )
            (Path(dlms.DATA_FOLDER) / html_name.replace(".html", ".json")).write_text(
                '[{"stale": true}]', encoding="utf-8"
            )

        before = self._canonical_snapshot()
        response = self._post_rebuild_all()

        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        self.assertEqual(
            {
                "status": "complete",
                "total": 3,
                "rebuilt": 3,
                "failed": [],
                "failure_details": [],
            },
            response.get_json(),
        )
        self.assertEqual(before, self._canonical_snapshot())

        choice_payload = json.loads(
            (Path(dlms.DATA_FOLDER) / self.html_name.replace(".html", ".json"))
            .read_text(encoding="utf-8")
        )
        matching_payload = json.loads(
            (Path(dlms.DATA_FOLDER) / matching_html.replace(".html", ".json"))
            .read_text(encoding="utf-8")
        )
        generated_payload = json.loads(
            (Path(dlms.DATA_FOLDER) / generated_html.replace(".html", ".json"))
            .read_text(encoding="utf-8")
        )
        self.assertEqual("choice", choice_payload[0]["type"])
        self.assertEqual(["A"], choice_payload[0]["correct"])
        self.assertEqual("matching", matching_payload[0]["type"])
        self.assertEqual(2, len(matching_payload[0]["pairs"]))
        self.assertEqual(
            "Neutral Learning Group",
            matching_payload[0]["source"]["organization"],
        )
        self.assertEqual("Generated practice question", generated_payload[0]["question"])
        self.assertEqual(["A", "B"], generated_payload[0]["correct"])
        for quiz_id, html_name in (
            (self.quiz_id, self.html_name),
            (matching_id, matching_html),
            (generated_id, generated_html),
        ):
            rendered = (Path(dlms.QUIZ_FOLDER) / html_name).read_text(encoding="utf-8")
            self.assertIn(f"window.QUIZ_ID = {quiz_id};", rendered)
        self._assert_no_mutation_staging()

    def test_rebuild_failure_restores_old_pair_and_continues_other_quizzes(self):
        other_id, other_html = dlms._publish_quiz(
            "Other quiz",
            [{
                "number": 1,
                "type": "choice",
                "question": "Other question",
                "choices": [
                    {"label": "A", "text": "Yes", "is_correct": True},
                    {"label": "B", "text": "No", "is_correct": False},
                ],
            }],
            filename_prefix="rebuild_other",
        )
        failed_html = Path(dlms.QUIZ_FOLDER) / self.html_name
        failed_json = Path(dlms.DATA_FOLDER) / self.html_name.replace(".html", ".json")
        failed_html.write_bytes(b"previous html")
        failed_json.write_bytes(b'[{"previous": true}]')
        before = self._canonical_snapshot()
        original_replace = dlms.os.replace

        def fail_first_html_promotion(source, target):
            if (
                "mutation_" in str(source)
                and os.path.abspath(target) == os.path.abspath(failed_html)
            ):
                raise RuntimeError("simulated rebuild promotion failure")
            return original_replace(source, target)

        with mock.patch.object(
            dlms.os, "replace", side_effect=fail_first_html_promotion
        ):
            response = self._post_rebuild_all()

        self.assertEqual(200, response.status_code)
        self.assertEqual("partial", response.get_json()["status"])
        self.assertEqual(1, response.get_json()["rebuilt"])
        self.assertEqual([self.quiz_id], response.get_json()["failed"])
        self.assertEqual(b"previous html", failed_html.read_bytes())
        self.assertEqual(b'[{"previous": true}]', failed_json.read_bytes())
        self.assertIn(
            f"window.QUIZ_ID = {other_id};",
            (Path(dlms.QUIZ_FOLDER) / other_html).read_text(encoding="utf-8"),
        )
        self.assertEqual(before, self._canonical_snapshot())
        self._assert_no_mutation_staging()

    def test_editor_adds_a_new_source_question_with_durable_identity(self):
        form = self._edit_form()
        form["action"] = "add_question"
        response = self.client.post(
            f"/edit_quiz/{self.quiz_id}",
            data=form,
            headers=csrf_headers(self.client),
        )
        self.assertEqual(302, response.status_code)
        conn = dlms.get_db()
        try:
            added = conn.execute(
                """
                SELECT question_uid, canonical_question_uid,
                       source_question_uid, is_generated_copy
                FROM questions
                WHERE quiz_id = ? AND question_number = 2
                """,
                (self.quiz_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(added)
        self.assertRegex(added["question_uid"], r"^[0-9a-f]{32}$")
        self.assertEqual(added["question_uid"], added["canonical_question_uid"])
        self.assertIsNone(added["source_question_uid"])
        self.assertEqual(0, added["is_generated_copy"])


if __name__ == "__main__":
    unittest.main()
