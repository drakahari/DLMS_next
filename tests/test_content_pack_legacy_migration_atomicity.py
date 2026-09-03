"""DLMS-093 legacy Content Pack asset-migration failure safety."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


class ContentPackLegacyMigrationAtomicityTests(unittest.TestCase):
    PACK_ID = "legacy_pack"
    PACK_FOLDER = "DLMS_Study_legacy_pack"
    LEGACY_URL = "/content-packs/legacy_pack/assets/images/diagram.png"

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="dlms-093-pack-delete-")
        self.root = Path(self._temp.name)
        self._previous = {
            name: getattr(dlms, name)
            for name in (
                "APP_DATA_DIR", "CONTENT_PACK_FOLDER", "QUIZ_ASSET_FOLDER",
                "DATA_FOLDER", "QUIZ_FOLDER", "CONFIG_FOLDER", "REGISTRY_FILE",
                "QUIZ_REGISTRY", "DB_PATH",
            )
        }
        dlms._initialize_data_root_ownership(str(self.root))
        dlms.APP_DATA_DIR = str(self.root)
        dlms.CONTENT_PACK_FOLDER = str(self.root / "content_packs")
        dlms.QUIZ_ASSET_FOLDER = str(self.root / "quiz_assets")
        dlms.DATA_FOLDER = str(self.root / "data")
        dlms.QUIZ_FOLDER = str(self.root / "quizzes")
        dlms.CONFIG_FOLDER = str(self.root / "config")
        dlms.REGISTRY_FILE = str(self.root / "config" / "quizzes.json")
        dlms.QUIZ_REGISTRY = dlms.REGISTRY_FILE
        dlms.DB_PATH = str(self.root / "results.db")
        for path in (
            dlms.CONTENT_PACK_FOLDER, dlms.QUIZ_ASSET_FOLDER, dlms.DATA_FOLDER,
            dlms.QUIZ_FOLDER, dlms.CONFIG_FOLDER,
        ):
            os.makedirs(path, exist_ok=True)
        dlms.ensure_db_initialized()
        self.pack_root = self._make_pack()
        self.quiz_path = Path(dlms.DATA_FOLDER) / "legacy_quiz.json"
        self.original_payload = [{
            "number": 1,
            "question": "Identify the diagram.",
            "image_url": self.LEGACY_URL,
        }]
        self.quiz_path.write_text(
            json.dumps(self.original_payload, indent=2), encoding="utf-8"
        )
        self.original_bytes = self.quiz_path.read_bytes()
        self.client = dlms.app.test_client()

    def tearDown(self):
        for name, value in self._previous.items():
            setattr(dlms, name, value)
        self._temp.cleanup()

    def _make_pack(self):
        pack_root = Path(dlms.CONTENT_PACK_FOLDER) / self.PACK_FOLDER
        (pack_root / "images").mkdir(parents=True)
        (pack_root / "manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "id": self.PACK_ID,
            "name": "Legacy Pack",
            "datasets": [],
            "image_datasets": [],
            "quiz_datasets": [],
        }), encoding="utf-8")
        Image.new("RGB", (8, 8), (30, 80, 130)).save(
            pack_root / "images" / "diagram.png"
        )
        return pack_root

    def _delete_pack(self):
        return self.client.post("/content-packs/delete", data={
            "csrf_token": csrf_token(self.client, "/content-packs"),
            "folder": self.PACK_FOLDER,
            "confirm_delete": "yes",
        })

    def _flash_categories(self):
        with self.client.session_transaction() as session:
            return [category for category, _ in session.get("_flashes", [])]

    def _runtime_asset(self):
        return (
            Path(dlms.QUIZ_ASSET_FOLDER)
            / "legacy_legacy_quiz"
            / "images"
            / "diagram.png"
        )

    def test_atomic_json_write_failure_preserves_quiz_pack_and_existing_assets(self):
        unrelated = Path(dlms.QUIZ_ASSET_FOLDER) / "existing" / "keep.png"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_bytes(b"existing-user-asset")

        with mock.patch.object(
            dlms.json, "dump", side_effect=OSError("simulated runtime JSON write failure")
        ):
            response = self._delete_pack()

        self.assertEqual(302, response.status_code)
        self.assertIn("error", self._flash_categories())
        self.assertNotIn("success", self._flash_categories())
        self.assertEqual(self.original_bytes, self.quiz_path.read_bytes())
        self.assertEqual(self.original_payload, json.loads(self.quiz_path.read_text()))
        self.assertTrue(self.pack_root.is_dir())
        self.assertFalse(self._runtime_asset().exists())
        self.assertEqual(b"existing-user-asset", unrelated.read_bytes())

        with self.client.get("/data/legacy_quiz.json") as served:
            self.assertEqual(200, served.status_code)
            self.assertEqual(self.original_payload, served.get_json())

    def test_asset_copy_failure_leaves_no_partial_destination(self):
        with mock.patch.object(
            dlms.shutil, "copy2", side_effect=OSError("simulated asset copy failure")
        ):
            response = self._delete_pack()

        self.assertEqual(302, response.status_code)
        self.assertIn("error", self._flash_categories())
        self.assertEqual(self.original_bytes, self.quiz_path.read_bytes())
        self.assertTrue(self.pack_root.is_dir())
        self.assertFalse(self._runtime_asset().exists())
        self.assertEqual([], list(Path(dlms.QUIZ_ASSET_FOLDER).rglob("*.png")))

    def test_database_migration_failure_rolls_back_rows_and_new_assets(self):
        self.quiz_path.write_text(
            json.dumps([{"number": 1, "question": "No runtime dependency"}]),
            encoding="utf-8",
        )
        conn = dlms.get_db()
        try:
            conn.execute(
                "INSERT INTO quizzes(title, source_file) VALUES (?, ?)",
                ("Legacy database", "legacy_database.html"),
            )
            quiz_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            original_media = json.dumps({"image_url": self.LEGACY_URL})
            conn.execute(
                """
                INSERT INTO questions(
                    quiz_id, question_number, question_text, question_type, media_json
                ) VALUES (?, 1, 'Legacy database image', 'choice', ?)
                """,
                (quiz_id, original_media),
            )
            conn.commit()
        finally:
            conn.close()

        with mock.patch.object(
            dlms.json, "dumps", side_effect=TypeError("simulated serialization failure")
        ):
            with self.assertRaisesRegex(TypeError, "simulated serialization failure"):
                dlms._snapshot_existing_pack_dependencies(self.PACK_ID)

        conn = dlms.get_db()
        try:
            durable_media = conn.execute(
                "SELECT media_json FROM questions WHERE quiz_id = ?", (quiz_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(original_media, durable_media)
        self.assertTrue(self.pack_root.is_dir())
        self.assertFalse(
            (Path(dlms.QUIZ_ASSET_FOLDER) / f"legacy_quiz_{quiz_id}").exists()
        )

    def test_successful_delete_migrates_runtime_and_database_references(self):
        conn = dlms.get_db()
        try:
            conn.execute(
                "INSERT INTO quizzes(title, source_file) VALUES (?, ?)",
                ("Legacy", "legacy_quiz.html"),
            )
            quiz_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """
                INSERT INTO questions(
                    quiz_id, question_number, question_text, question_type, media_json
                ) VALUES (?, 1, 'Legacy image', 'choice', ?)
                """,
                (quiz_id, json.dumps({"image_url": self.LEGACY_URL})),
            )
            conn.commit()
        finally:
            conn.close()

        response = self._delete_pack()

        self.assertEqual(302, response.status_code)
        self.assertIn("success", self._flash_categories())
        self.assertFalse(self.pack_root.exists())
        runtime = json.loads(self.quiz_path.read_text(encoding="utf-8"))
        self.assertEqual(
            "/quiz-assets/legacy_legacy_quiz/images/diagram.png",
            runtime[0]["image_url"],
        )
        self.assertTrue(self._runtime_asset().is_file())
        with self.client.get(runtime[0]["image_url"]) as served_asset:
            self.assertEqual(200, served_asset.status_code)

        conn = dlms.get_db()
        try:
            media = json.loads(conn.execute(
                "SELECT media_json FROM questions WHERE quiz_id = ?", (quiz_id,)
            ).fetchone()[0])
        finally:
            conn.close()
        self.assertEqual(
            f"/quiz-assets/legacy_quiz_{quiz_id}/images/diagram.png",
            media["image_url"],
        )
        self.assertTrue(
            (Path(dlms.QUIZ_ASSET_FOLDER) / f"legacy_quiz_{quiz_id}" / "images" / "diagram.png").is_file()
        )

    def test_nonlegacy_delete_does_not_rewrite_runtime_quiz(self):
        self.quiz_path.write_text(
            json.dumps([{"number": 1, "question": "No pack dependency"}], indent=2),
            encoding="utf-8",
        )
        before = self.quiz_path.read_bytes()

        response = self._delete_pack()

        self.assertEqual(302, response.status_code)
        self.assertIn("success", self._flash_categories())
        self.assertFalse(self.pack_root.exists())
        self.assertEqual(before, self.quiz_path.read_bytes())
        self.assertEqual([], list(Path(dlms.QUIZ_ASSET_FOLDER).iterdir()))

    def test_removal_failure_keeps_pack_and_retry_reuses_completed_migration(self):
        with mock.patch.object(
            dlms.shutil, "rmtree", side_effect=OSError("simulated pack removal failure")
        ):
            failed = self._delete_pack()

        self.assertEqual(302, failed.status_code)
        self.assertIn("error", self._flash_categories())
        self.assertTrue(self.pack_root.is_dir())
        migrated_bytes = self.quiz_path.read_bytes()
        migrated = json.loads(migrated_bytes)
        self.assertEqual(
            "/quiz-assets/legacy_legacy_quiz/images/diagram.png",
            migrated[0]["image_url"],
        )
        self.assertTrue(self._runtime_asset().is_file())

        with self.client.session_transaction() as session:
            session["_flashes"] = []
        retried = self._delete_pack()
        self.assertEqual(302, retried.status_code)
        self.assertIn("success", self._flash_categories())
        self.assertFalse(self.pack_root.exists())
        self.assertEqual(migrated_bytes, self.quiz_path.read_bytes())
        self.assertTrue(self._runtime_asset().is_file())


if __name__ == "__main__":
    unittest.main()
