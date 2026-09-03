"""DLMS-088 restored browser-content and custom AI URL regressions."""

import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image


_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="dlms-backup-browser-app-")
os.environ["QUIZAPP_DATA_DIR"] = _IMPORT_DATA.name
from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


class BackupBrowserContentPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-backup-browser-policy-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _staged_root(self, name, *, ai_custom_url=None):
        root = self.root / name
        (root / "data").mkdir(parents=True)
        (root / "config").mkdir()
        dlms.bootstrap_database(str(root / "results.db"), require_owned_root=False)
        (root / "data" / "quiz.json").write_text("[]", encoding="utf-8")
        (root / "data" / "parse_log_1.txt").write_text("parser output", encoding="utf-8")
        if ai_custom_url is not None:
            (root / "config" / "portal.json").write_text(
                json.dumps({"title": "Restored", "ai_custom_url": ai_custom_url}),
                encoding="utf-8",
            )
        return root

    @staticmethod
    def _manifest(root):
        files = [path for path in root.rglob("*") if path.is_file()]
        return {
            "schema_version": dlms.DLMS_BACKUP_SCHEMA_VERSION,
            "kind": "dlms-portable-backup",
            "file_count": len(files),
            "included_roots": sorted(path.name for path in root.iterdir()),
        }

    def test_data_restore_allows_required_json_and_text_only(self):
        root = self._staged_root("valid-data")
        result = dlms._validate_staged_backup_semantics(root, self._manifest(root))
        self.assertEqual(
            ["data/parse_log_1.txt", "data/quiz.json"],
            result["browser_data"],
        )

        for index, extension in enumerate(
            (".html", ".htm", ".svg", ".js", ".mjs", ".css", ".xml", ".xhtml", ".wasm", "")
        ):
            with self.subTest(extension=extension or "extensionless"):
                active = root / "data" / f"active_{index}{extension}"
                active.write_text("<script>window.DLMS088_ACTIVE=true</script>", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Unsafe restored browser-served file"):
                    dlms._validate_staged_backup_semantics(root, self._manifest(root))
                active.unlink()

    def test_restored_custom_ai_urls_keep_absolute_web_targets_and_normalize_unsafe_values(self):
        valid_urls = (
            "https://example.com/assistant?model=study",
            "http://localhost:11434/",
            "https://example.com:9001/data/assistant",
        )
        for index, url in enumerate(valid_urls):
            with self.subTest(valid=url):
                root = self._staged_root(f"valid-url-{index}", ai_custom_url=url)
                result = dlms._validate_staged_backup_semantics(root, self._manifest(root))
                restored = json.loads((root / "config" / "portal.json").read_text(encoding="utf-8"))
                self.assertEqual("valid", result["portal_config"]["status"])
                self.assertEqual(url, restored["ai_custom_url"])

        unsafe_urls = (
            "/data/restored.html",
            "data/restored.html",
            "//example.com/assistant",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///tmp/assistant.html",
            "ftp://example.com/assistant",
            "http://localhost:9001/",
            "http://localhost:9001/data/restored.html",
            "http://127.0.0.1:9001/%64ata/restored.html",
            "http://localhost:9001/quizzes/restored.html",
            "http://localhost:9001/other/../data/restored.html",
            "https://example.com\\@localhost:9001/data/restored.html",
        )
        for index, url in enumerate(unsafe_urls):
            with self.subTest(unsafe=url):
                root = self._staged_root(f"unsafe-url-{index}", ai_custom_url=url)
                result = dlms._validate_staged_backup_semantics(root, self._manifest(root))
                restored = json.loads((root / "config" / "portal.json").read_text(encoding="utf-8"))
                self.assertEqual("normalized", result["portal_config"]["status"])
                self.assertEqual("", restored["ai_custom_url"])

    def test_restored_image_builder_drafts_require_real_passive_rasters(self):
        root = self._staged_root("draft-assets")
        draft = root / "image_builder_drafts" / "draft_123456"
        draft.mkdir(parents=True)
        Image.new("RGB", (2, 2), "green").save(draft / "safe.png")
        result = dlms._validate_staged_backup_semantics(root, self._manifest(root))
        self.assertIn("image_builder_drafts/draft_123456/safe.png", result["assets"])

        active = draft / "active.svg"
        active.write_text("<svg onload='alert(1)'></svg>", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsafe restored image asset"):
            dlms._validate_staged_backup_semantics(root, self._manifest(root))

    def test_ai_settings_enforce_the_same_server_side_url_policy_without_partial_save(self):
        portal = self.root / "portal.json"
        original = {"title": "Keep", "theme": "dark", "ai_custom_url": "https://safe.example/"}
        portal.write_text(json.dumps(original), encoding="utf-8")
        client = dlms.app.test_client()

        with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal)):
            rejected = client.post(
                "/settings/ai/save",
                data={"ai_provider": "local", "ai_custom_url": "javascript:alert(1)"},
                headers=csrf_headers(client, "/settings/ai"),
            )
            self.assertEqual(400, rejected.status_code)
            self.assertIn("absolute HTTP or HTTPS URL", rejected.get_data(as_text=True))
            self.assertEqual(original, json.loads(portal.read_text(encoding="utf-8")))

            for url in ("https://example.com/assistant", "http://localhost:11434/"):
                with self.subTest(url=url):
                    saved = client.post(
                        "/settings/ai/save",
                        data={"ai_provider": "local", "ai_custom_url": url},
                        headers=csrf_headers(client, "/settings/ai"),
                    )
                    self.assertEqual(302, saved.status_code)
                    self.assertEqual(url, json.loads(portal.read_text(encoding="utf-8"))["ai_custom_url"])

    def test_ai_launch_templates_serialize_valid_urls_as_javascript_data(self):
        source = Path(dlms.__file__).read_text(encoding="utf-8")
        self.assertIn("onclick='copyAndOpen({{ ai_url|tojson }})'", source)
        self.assertIn("onclick='copyPromptAndOpenAi({{ ai_provider_url|tojson }})'", source)


class BackupBrowserContentRouteTests(unittest.TestCase):
    ATTACK_MARKER = "DLMS088_ATTACKER_CONTROLLED_CONTENT"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-backup-browser-route-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.live = self.root / "live"
        self.live.mkdir()
        dlms._initialize_data_root_ownership(str(self.live))

        paths = {
            "APP_DATA_DIR": self.live,
            "UPLOAD_FOLDER": self.live / "uploads",
            "DATA_FOLDER": self.live / "data",
            "QUIZ_FOLDER": self.live / "quizzes",
            "CONFIG_FOLDER": self.live / "config",
            "REGISTRY_FILE": self.live / "config" / "quizzes.json",
            "QUIZ_REGISTRY": self.live / "config" / "quizzes.json",
            "PORTAL_CONFIG": self.live / "config" / "portal.json",
            "LAW_FOLDER": self.live / "law",
            "LAW_CASES_FOLDER": self.live / "law" / "cases",
            "LAW_IMPORTS_FOLDER": self.live / "law" / "imports",
            "LAW_EXPORTS_FOLDER": self.live / "law" / "exports",
            "LAW_REGISTRY": self.live / "config" / "law.json",
            "LOGO_FOLDER": self.live / "static" / "logos",
            "LOGO_TEMP_FOLDER": self.live / "static" / "logos" / "_temp",
            "BACKGROUND_FOLDER": self.live / "static" / "bg",
            "CONTENT_PACK_FOLDER": self.live / "content_packs",
            "QUIZ_ASSET_FOLDER": self.live / "quiz_assets",
            "IMAGE_BUILDER_DRAFT_FOLDER": self.live / "image_builder_drafts",
            "PDF_IMPORT_DRAFT_FOLDER": self.live / "pdf_import_drafts",
            "PDF_QUESTION_BANK_FOLDER": self.live / "pdf_question_banks",
            "PDF_TERMINOLOGY_BANK_FOLDER": self.live / "pdf_terminology_banks",
            "CONTENT_PACK_STAGING_FOLDER": self.live / "content_pack_staging",
            "BACKUP_FOLDER": self.live / "backups",
            "BACKUP_RESTORE_STAGING_FOLDER": self.live / "backups" / "restore_staging",
            "DB_PATH": self.live / "results.db",
        }
        self.patchers = []
        for name, value in paths.items():
            patcher = mock.patch.object(dlms, name, str(value))
            patcher.start()
            self.patchers.append(patcher)
            self.addCleanup(patcher.stop)

        dlms._ensure_runtime_data_dirs()
        dlms.bootstrap_database(dlms.DB_PATH)
        dlms._atomic_write_json(
            dlms.PORTAL_CONFIG,
            {"title": "Original Live", "theme": "dark", "ai_custom_url": "https://safe.example/"},
            expected_type=dict,
        )
        dlms.save_registry([])
        self.live_sentinel = Path(dlms.DATA_FOLDER, "live.json")
        self.live_sentinel.write_text('{"state":"original"}', encoding="utf-8")
        self.client = dlms.app.test_client()
        self.archive_number = 0

    def _archive(self, *, ai_custom_url="https://example.com/assistant", active_data=None):
        self.archive_number += 1
        payload = self.root / f"payload-{self.archive_number}"
        (payload / "config").mkdir(parents=True)
        (payload / "data").mkdir()
        (payload / "quizzes").mkdir()

        database = payload / "results.db"
        dlms.bootstrap_database(str(database), require_owned_root=False)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "INSERT INTO quizzes (id, title, source_file) VALUES (881, ?, ?)",
                ("Canonical Restored Quiz", "restored-source"),
            )
            connection.execute(
                "INSERT INTO questions (quiz_id, question_number, question_text, question_type) VALUES (881, 1, ?, 'choice')",
                ("Safe canonical question",),
            )
            question_id = connection.execute(
                "SELECT id FROM questions WHERE quiz_id = 881"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO choices (question_id, label, text, is_correct) VALUES (?, 'A', 'Safe answer', 1)",
                (question_id,),
            )
            connection.commit()
        finally:
            connection.close()

        (payload / "config" / "quizzes.json").write_text(
            json.dumps([{
                "id": 881,
                "title": "Registry Restored Quiz",
                "html": "restored_quiz.html",
                "exam_minutes": 45,
            }]),
            encoding="utf-8",
        )
        (payload / "config" / "portal.json").write_text(
            json.dumps({
                "title": "Restored Portal",
                "theme": "dark",
                "ai_provider": "local",
                "ai_custom_url": ai_custom_url,
            }),
            encoding="utf-8",
        )
        (payload / "data" / "restored_quiz.json").write_text("[]", encoding="utf-8")
        (payload / "data" / "parse_log_1.txt").write_text("safe parser output", encoding="utf-8")
        malicious = f"<!doctype html><script>window.{self.ATTACK_MARKER}=true</script>"
        (payload / "quizzes" / "restored_quiz.html").write_text(malicious, encoding="utf-8")
        (payload / "quizzes" / "unregistered.html").write_text(malicious, encoding="utf-8")
        if active_data:
            (payload / "data" / active_data).write_text(malicious, encoding="utf-8")

        files = sorted(path for path in payload.rglob("*") if path.is_file())
        manifest = {
            "schema_version": dlms.DLMS_BACKUP_SCHEMA_VERSION,
            "kind": "dlms-portable-backup",
            "created_at": "2026-09-02T12:00:00-05:00",
            "dlms_version": dlms.APP_VERSION,
            "file_count": len(files),
            "included_roots": sorted({path.relative_to(payload).parts[0] for path in files}),
            "summary": {},
        }
        archive_path = self.root / f"crafted-{self.archive_number}.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(manifest))
            for path in files:
                archive.write(
                    path,
                    dlms.DLMS_BACKUP_DATA_PREFIX + path.relative_to(payload).as_posix(),
                )
        return archive_path

    def _stage(self, archive_path):
        with archive_path.open("rb") as upload:
            return self.client.post(
                "/settings/backup/restore/stage",
                data={"backup_file": (upload, "crafted.zip")},
                headers=csrf_headers(self.client, "/settings/backup"),
            )

    @staticmethod
    def _restore_token(response):
        match = re.search(
            r"/settings/backup/restore/confirm/([a-f0-9]{32})",
            response.get_data(as_text=True),
        )
        if not match:
            raise AssertionError("Restore confirmation token was not rendered")
        return match.group(1)

    def test_original_active_data_backup_is_rejected_before_stage_or_confirm_can_mutate_live_data(self):
        archive_path = self._archive(
            ai_custom_url="/data/restored-active.html",
            active_data="restored-active.html",
        )

        stage_response = self._stage(archive_path)
        self.assertEqual(400, stage_response.status_code)
        self.assertIn("Backup rejected", stage_response.get_data(as_text=True))
        self.assertEqual([], list(Path(dlms.BACKUP_RESTORE_STAGING_FOLDER).iterdir()))
        self.assertEqual('{"state":"original"}', self.live_sentinel.read_text(encoding="utf-8"))
        self.assertEqual(
            "https://safe.example/",
            json.loads(Path(dlms.PORTAL_CONFIG).read_text(encoding="utf-8"))["ai_custom_url"],
        )

        # Even a caller that already possesses a token cannot cross the same
        # semantic gate during confirmation or trigger a safety backup/apply.
        token = "d" * 32
        stage_dir = Path(dlms.BACKUP_RESTORE_STAGING_FOLDER, token)
        stage_dir.mkdir()
        shutil.copy2(archive_path, stage_dir / "restore.zip")
        with mock.patch.object(dlms, "_create_dlms_backup") as safety, mock.patch.object(
            dlms, "_apply_restored_data"
        ) as apply:
            confirm_response = self.client.post(
                f"/settings/backup/restore/confirm/{token}",
                headers=csrf_headers(self.client, "/settings/backup"),
            )
        self.assertEqual(400, confirm_response.status_code)
        safety.assert_not_called()
        apply.assert_not_called()
        self.assertEqual('{"state":"original"}', self.live_sentinel.read_text(encoding="utf-8"))
        self.assertFalse(Path(dlms.DATA_FOLDER, "restored-active.html").exists())

        served = self.client.get("/data/restored-active.html")
        self.assertEqual(415, served.status_code)
        self.assertNotIn(self.ATTACK_MARKER.encode(), served.data)

    def test_valid_data_restores_and_unsafe_optional_ai_url_is_normalized(self):
        stage_response = self._stage(self._archive(ai_custom_url="/data/restored_quiz.json"))
        self.assertEqual(200, stage_response.status_code)
        self.assertIn("Custom AI URL will be cleared", stage_response.get_data(as_text=True))
        token = self._restore_token(stage_response)

        confirm_response = self.client.post(
            f"/settings/backup/restore/confirm/{token}",
            headers=csrf_headers(self.client, "/settings/backup"),
        )
        self.assertEqual(200, confirm_response.status_code)

        quiz_json = self.client.get("/data/restored_quiz.json")
        parser_log = self.client.get("/data/parse_log_1.txt")
        restored_quiz = self.client.get("/quizzes/restored_quiz.html")
        unregistered_quiz = self.client.get("/quizzes/unregistered.html")
        for response in (quiz_json, parser_log, restored_quiz, unregistered_quiz):
            self.addCleanup(response.close)
        self.assertEqual(200, quiz_json.status_code)
        self.assertEqual("application/json", quiz_json.mimetype)
        self.assertEqual(200, parser_log.status_code)
        self.assertEqual("text/plain", parser_log.mimetype)
        self.assertEqual(200, restored_quiz.status_code)
        self.assertNotIn(self.ATTACK_MARKER.encode(), restored_quiz.data)
        self.assertEqual(404, unregistered_quiz.status_code)
        self.assertEqual("", self.client.get("/config/portal.json").get_json()["ai_custom_url"])

    def test_valid_absolute_http_and_https_urls_survive_complete_restore(self):
        for url in ("https://example.com/assistant", "http://localhost:11434/"):
            with self.subTest(url=url):
                stage_response = self._stage(self._archive(ai_custom_url=url))
                self.assertEqual(200, stage_response.status_code)
                self.assertNotIn("Custom AI URL will be cleared", stage_response.get_data(as_text=True))
                confirm_response = self.client.post(
                    f"/settings/backup/restore/confirm/{self._restore_token(stage_response)}",
                    headers=csrf_headers(self.client, "/settings/backup"),
                )
                self.assertEqual(200, confirm_response.status_code)
                self.assertEqual(
                    url,
                    self.client.get("/config/portal.json").get_json()["ai_custom_url"],
                )

    def test_every_restored_browser_file_route_blocks_active_non_raster_types(self):
        active = f"<svg onload='window.{self.ATTACK_MARKER}=true'></svg>"
        Path(dlms.DATA_FOLDER, "active.html").write_text(active, encoding="utf-8")
        Path(dlms.QUIZ_FOLDER, "active.svg").write_text(active, encoding="utf-8")
        Path(dlms.LOGO_FOLDER, "active.svg").write_text(active, encoding="utf-8")
        Path(dlms.BACKGROUND_FOLDER, "active.svg").write_text(active, encoding="utf-8")

        quiz_bucket = Path(dlms.QUIZ_ASSET_FOLDER, "bucket")
        quiz_bucket.mkdir()
        (quiz_bucket / "active.svg").write_text(active, encoding="utf-8")
        draft = Path(dlms.IMAGE_BUILDER_DRAFT_FOLDER, "draft_123456")
        draft.mkdir()
        (draft / "active.svg").write_text(active, encoding="utf-8")

        pack = Path(dlms.CONTENT_PACK_FOLDER, "active-pack")
        pack.mkdir()
        (pack / "manifest.json").write_text(
            json.dumps({
                "schema_version": 1,
                "id": "active-pack",
                "datasets": [],
                "image_datasets": [],
                "quiz_datasets": [],
            }),
            encoding="utf-8",
        )
        (pack / "active.svg").write_text(active, encoding="utf-8")

        routes = (
            "/data/active.html",
            "/quizzes/active.svg",
            "/user-static/logos/active.svg",
            "/user-bg/active.svg",
            "/quiz-assets/bucket/active.svg",
            "/image-builder/drafts/draft_123456/active.svg",
            "/content-packs/active-pack/assets/active.svg",
        )
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(415, response.status_code)
                self.assertNotIn(self.ATTACK_MARKER.encode(), response.data)


if __name__ == "__main__":
    unittest.main()
