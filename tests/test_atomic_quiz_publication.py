"""DLMS-043A atomic quiz-publication regression tests."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-atomic-publication-")
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
    dlms.QUIZ_REGISTRY = str(root / "config" / "quizzes.json")
    dlms.REGISTRY_FILE = dlms.QUIZ_REGISTRY
    dlms.DB_PATH = str(root / "results.db")
    dlms.QUIZ_ASSET_FOLDER = str(root / "quiz_assets")
    dlms.CONTENT_PACK_FOLDER = str(root / "content_packs")
    dlms.IMAGE_BUILDER_DRAFT_FOLDER = str(root / "image_builder_drafts")
    dlms.LOGO_FOLDER = str(root / "static" / "logos")
    dlms.LOGO_TEMP_FOLDER = str(root / "static" / "logos" / "_temp")
    for path in (
        dlms.DATA_FOLDER, dlms.QUIZ_FOLDER, dlms.CONFIG_FOLDER,
        dlms.QUIZ_ASSET_FOLDER, dlms.CONTENT_PACK_FOLDER,
        dlms.IMAGE_BUILDER_DRAFT_FOLDER, dlms.LOGO_FOLDER,
        dlms.LOGO_TEMP_FOLDER,
    ):
        os.makedirs(path, exist_ok=True)


class AtomicQuizPublicationTests(unittest.TestCase):
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

    @staticmethod
    def _questions():
        return [
            {
                "number": 1,
                "type": "choice",
                "question": "Which mode is correct?",
                "concepts": ["publication-choice"],
                "choices": [
                    {"label": "A", "text": "Atomic", "is_correct": True},
                    {"label": "B", "text": "Partial", "is_correct": False},
                ],
            },
            {
                "number": 2,
                "type": "matching",
                "question": "Match publication stages.",
                "concepts": ["publication-matching"],
                "pairs": [
                    {"left": "JSON", "right": "Staged artifact"},
                    {"left": "Registry", "right": "Final boundary"},
                ],
            },
        ]

    def _counts(self):
        conn = dlms.get_db()
        try:
            return {
                table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in ("quizzes", "questions", "choices", "matching_pairs", "question_concepts")
            }
        finally:
            conn.close()

    def _assert_clean_failure(self):
        self.assertEqual(
            {"quizzes": 0, "questions": 0, "choices": 0, "matching_pairs": 0, "question_concepts": 0},
            self._counts(),
        )
        self.assertEqual([], dlms.load_registry())
        self.assertEqual([], list(Path(dlms.DATA_FOLDER).iterdir()))
        self.assertEqual([], list(Path(dlms.QUIZ_FOLDER).iterdir()))
        self.assertEqual([], list(Path(dlms.QUIZ_ASSET_FOLDER).iterdir()))
        staging = Path(dlms._quiz_publication_staging_root())
        self.assertFalse(staging.exists() and any(staging.iterdir()))

    def _publish_with_failure(self, target, side_effect):
        with mock.patch.object(dlms, target, side_effect=side_effect):
            with self.assertRaises(RuntimeError):
                dlms._publish_quiz("Failure", self._questions(), filename_prefix="failure")
        self._assert_clean_failure()

    def test_json_staging_failure_leaves_nothing_published(self):
        self._publish_with_failure("_write_staged_quiz_json", RuntimeError("json failure"))

    def test_html_render_failure_rolls_back_uncommitted_db(self):
        self._publish_with_failure("build_quiz_html", RuntimeError("html failure"))

    def test_db_insert_failure_rolls_back_and_cleans_staging(self):
        self._publish_with_failure("_insert_quiz_rows", RuntimeError("insert failure"))

    def test_db_commit_failure_rolls_back_and_cleans_staging(self):
        self._publish_with_failure("_commit_quiz_publication", RuntimeError("commit failure"))

    def test_db_commit_that_persists_then_raises_is_compensated(self):
        def commit_then_raise(connection):
            connection.commit()
            raise RuntimeError("post-commit failure")

        self._publish_with_failure("_commit_quiz_publication", commit_then_raise)

    def test_promotion_failure_removes_prior_promotions_and_committed_db(self):
        original = dlms._promote_quiz_artifact
        calls = 0

        def fail_second(staged, final):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("promotion failure")
            return original(staged, final)

        self._publish_with_failure("_promote_quiz_artifact", fail_second)

    def test_registry_failure_removes_promoted_artifacts_and_committed_db(self):
        self._publish_with_failure("add_quiz_to_registry", RuntimeError("registry failure"))

    def test_success_preserves_artifacts_registry_and_relational_links(self):
        quiz_id, html_name = dlms._publish_quiz(
            "Published", self._questions(), filename_prefix="published", exam_minutes=35
        )
        json_name = html_name.replace(".html", ".json")
        self.assertTrue((Path(dlms.DATA_FOLDER) / json_name).is_file())
        self.assertTrue((Path(dlms.QUIZ_FOLDER) / html_name).is_file())
        runtime = json.loads(
            (Path(dlms.DATA_FOLDER) / json_name).read_text(encoding="utf-8")
        )
        self.assertEqual([1, 2], [item["number"] for item in runtime])
        self.assertTrue(all("source_number" not in item for item in runtime))
        self.assertEqual(quiz_id, dlms.load_registry()[0]["id"])
        self.assertEqual(35, dlms.load_registry()[0]["exam_minutes"])
        self.assertEqual(
            {"quizzes": 1, "questions": 2, "choices": 2, "matching_pairs": 2, "question_concepts": 2},
            self._counts(),
        )
        conn = dlms.get_db()
        try:
            concepts = {
                row[0] for row in conn.execute(
                    "SELECT name FROM concepts ORDER BY name"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertEqual({"publication-choice", "publication-matching"}, concepts)
        staging = Path(dlms._quiz_publication_staging_root())
        self.assertFalse(staging.exists() and any(staging.iterdir()))

    def test_nonsequential_source_numbers_publish_with_canonical_ordinals(self):
        questions = [
            {
                "number": source_number,
                "type": "choice",
                "question": f"Source question {source_number}",
                "choices": [
                    {"label": "A", "text": "Correct", "is_correct": True},
                    {"label": "B", "text": "Incorrect", "is_correct": False},
                ],
            }
            for source_number in (10, 20, 30)
        ]
        original = json.loads(json.dumps(questions))

        quiz_id, html_name = dlms._publish_quiz(
            "Nonsequential", questions, filename_prefix="nonsequential"
        )
        runtime = json.loads(
            (Path(dlms.DATA_FOLDER) / html_name.replace(".html", ".json")).read_text(
                encoding="utf-8"
            )
        )
        conn = dlms.get_db()
        try:
            rows = conn.execute(
                """
                SELECT question_number, media_json FROM questions
                WHERE quiz_id = ? ORDER BY question_number, id
                """,
                (quiz_id,),
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(original, questions)
        self.assertEqual([1, 2, 3], [item["number"] for item in runtime])
        self.assertEqual([10, 20, 30], [item["source_number"] for item in runtime])
        self.assertEqual([1, 2, 3], [row["question_number"] for row in rows])
        self.assertEqual(
            [10, 20, 30],
            [json.loads(row["media_json"])["source_number"] for row in rows],
        )

    def test_ambiguous_or_invalid_source_numbers_do_not_discard_questions(self):
        source_numbers = [1, 1, 0, None, -2]
        questions = []
        for index, source_number in enumerate(source_numbers, start=1):
            question = {
                "type": "choice",
                "question": f"Question payload {index}",
                "choices": [
                    {"label": "A", "text": "Correct", "is_correct": True},
                    {"label": "B", "text": "Incorrect", "is_correct": False},
                ],
            }
            if source_number is not None:
                question["number"] = source_number
            questions.append(question)

        quiz_id, html_name = dlms._publish_quiz(
            "Ambiguous source numbers", questions, filename_prefix="ambiguous_numbers"
        )
        runtime = json.loads(
            (Path(dlms.DATA_FOLDER) / html_name.replace(".html", ".json")).read_text(
                encoding="utf-8"
            )
        )
        conn = dlms.get_db()
        try:
            db_numbers = [
                row[0]
                for row in conn.execute(
                    """
                    SELECT question_number FROM questions
                    WHERE quiz_id = ? ORDER BY question_number, id
                    """,
                    (quiz_id,),
                ).fetchall()
            ]
        finally:
            conn.close()

        self.assertEqual(5, len(runtime))
        self.assertEqual([1, 2, 3, 4, 5], [item["number"] for item in runtime])
        self.assertEqual([1, 2, 3, 4, 5], db_numbers)
        self.assertNotIn("source_number", runtime[0])
        self.assertEqual(1, runtime[1]["source_number"])
        for item in runtime[2:]:
            self.assertNotIn("source_number", item)

    def _make_asset_pack(self):
        root = Path(dlms.CONTENT_PACK_FOLDER) / "DLMS_Study_atomic_assets"
        (root / "images").mkdir(parents=True)
        Image.new("RGB", (8, 8), (20, 80, 140)).save(root / "images" / "diagram.png")
        (root / "manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "id": "atomic_assets",
            "name": "Atomic Assets",
            "datasets": [], "image_datasets": [], "quiz_datasets": [],
        }), encoding="utf-8")
        return root

    def test_asset_copy_failure_never_exposes_final_bucket(self):
        self._make_asset_pack()
        question = self._questions()[0]
        question["image_url"] = "/content-packs/atomic_assets/assets/images/diagram.png"
        with mock.patch.object(dlms.shutil, "copy2", side_effect=RuntimeError("asset copy failure")):
            with self.assertRaisesRegex(RuntimeError, "asset copy failure"):
                dlms._publish_quiz(
                    "Asset failure", [question], filename_prefix="asset_failure",
                    source_pack_id="atomic_assets",
                )
        self._assert_clean_failure()

    def test_pack_assets_and_review_assets_are_staged_then_promoted(self):
        self._make_asset_pack()
        pack_question = self._questions()[0]
        pack_question["image_url"] = "/content-packs/atomic_assets/assets/images/diagram.png"
        _, pack_html = dlms._publish_quiz(
            "Pack asset", [pack_question], filename_prefix="pack_asset",
            source_pack_id="atomic_assets",
        )
        pack_bucket = Path(pack_html).stem
        self.assertTrue((Path(dlms.QUIZ_ASSET_FOLDER) / pack_bucket / "images" / "diagram.png").is_file())

        review_source = Path(dlms.QUIZ_ASSET_FOLDER) / "source_bucket" / "images"
        review_source.mkdir(parents=True)
        shutil.copy2(
            Path(dlms.CONTENT_PACK_FOLDER) / "DLMS_Study_atomic_assets" / "images" / "diagram.png",
            review_source / "diagram.png",
        )
        for prefix in ("smart_review", "spaced_review"):
            question = self._questions()[0]
            question["image_url"] = "/quiz-assets/source_bucket/images/diagram.png"
            _, html_name = dlms._publish_quiz(
                prefix, [question], filename_prefix=prefix, snapshot_existing_assets=True
            )
            bucket = Path(html_name).stem
            self.assertTrue((Path(dlms.QUIZ_ASSET_FOLDER) / bucket / "images" / "diagram.png").is_file())

    def test_shared_logo_is_never_removed_during_rollback(self):
        logo = Path(dlms.LOGO_FOLDER) / "shared.png"
        logo.write_bytes(b"shared-logo")
        with mock.patch.object(dlms, "_write_staged_quiz_json", side_effect=RuntimeError("fail")):
            with self.assertRaises(RuntimeError):
                dlms._publish_quiz("Logo", self._questions(), logo_filename=logo.name)
        self.assertEqual(b"shared-logo", logo.read_bytes())
        self._assert_clean_failure()

    def test_explicitly_publication_owned_logo_is_removed_during_rollback(self):
        logo = Path(dlms.LOGO_FOLDER) / "logo_owned.png"
        logo.write_bytes(b"owned-logo")
        with mock.patch.object(dlms, "_write_staged_quiz_json", side_effect=RuntimeError("fail")):
            with self.assertRaises(RuntimeError):
                dlms._publish_quiz(
                    "Logo", self._questions(), logo_filename=logo.name,
                    rollback_logo_filename=logo.name,
                )
        self.assertFalse(logo.exists())
        self._assert_clean_failure()

    def test_rapid_successive_publications_keep_unique_dlms_042_names(self):
        names = {
            dlms._publish_quiz("Rapid", self._questions(), filename_prefix="rapid")[1]
            for _ in range(8)
        }
        self.assertEqual(8, len(names))
        self.assertEqual(names, {item["html"] for item in dlms.load_registry()})

    def test_pdf_accounting_failure_does_not_delete_published_quiz(self):
        bank = {
            "id": "atomic_pdf",
            "title": "Atomic PDF",
            "source_name": "atomic.pdf",
            "used_question_numbers": [],
            "generated_quizzes": [],
            "questions": [{
                "original_number": 1,
                "question": "Which publication boundary is last?",
                "choices": [
                    {"label": "A", "text": "Database"},
                    {"label": "B", "text": "Registry"},
                ],
                "correct": "B",
                "active": True,
            }],
        }
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_load_pdf_question_bank", return_value=bank), \
             mock.patch.object(
                 dlms, "_save_pdf_question_bank", side_effect=RuntimeError("accounting failure")
             ):
            response = client.post("/pdf-import/bank/atomic_pdf/generate", data={
                "csrf_token": csrf_token(client, "/pdf-import/bank/atomic_pdf"),
                "quiz_title": "Atomic PDF Practice",
                "question_count": "1",
                "selection_mode": "all",
                "exam_minutes": "25",
            })
        self.assertEqual(302, response.status_code)
        self.assertIn("/edit_quiz/", response.headers["Location"])
        self.assertEqual(1, self._counts()["quizzes"])
        self.assertEqual(1, len(dlms.load_registry()))

    def test_build_from_images_removes_new_pack_when_publication_fails(self):
        draft_id = "draft_atomic_123"
        draft = Path(dlms.IMAGE_BUILDER_DRAFT_FOLDER) / draft_id
        draft.mkdir(parents=True)
        Image.new("RGB", (8, 8), (30, 90, 150)).save(draft / "diagram.png")
        payload = {
            "images": [{"id": "image_1", "filename": "diagram.png", "original_name": "diagram.png"}],
            "questions": [{
                "type": "choice", "question": "Which?", "image_id": "image_1",
                "choices": [{"text": "One", "is_correct": True}, {"text": "Two", "is_correct": False}],
            }],
        }
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_publish_quiz", side_effect=RuntimeError("publication failure")):
            response = client.post("/study-packs/image-builder/save", data={
                "csrf_token": csrf_token(client, "/study-packs/image-builder"),
                "draft_id": draft_id,
                "pack_title": "Atomic Images",
                "subject": "General",
                "rights_ok": "on",
                "builder_payload": json.dumps(payload),
            })
        self.assertEqual(400, response.status_code)
        self.assertEqual([], list(Path(dlms.CONTENT_PACK_FOLDER).iterdir()))
        self._assert_clean_failure()


if __name__ == "__main__":
    unittest.main()
