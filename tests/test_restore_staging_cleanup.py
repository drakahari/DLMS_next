"""DLMS-090 restore-stage cancellation and stale-cleanup regressions."""

import json
import os
import re
import sqlite3
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


class RestoreStagingCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="dlms-restore-staging-cleanup-"
        )
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
            {"title": "Original Live", "theme": "dark"},
            expected_type=dict,
        )
        dlms.save_registry([])
        self.live_sentinel = Path(dlms.DATA_FOLDER) / "live.json"
        self.live_sentinel.write_text('{"state":"original"}', encoding="utf-8")
        self.client = dlms.app.test_client()
        self.archive_count = 0

    def _archive(self):
        self.archive_count += 1
        payload = self.root / f"payload-{self.archive_count}"
        payload.mkdir()
        (payload / "config").mkdir()
        dlms.bootstrap_database(str(payload / "results.db"), require_owned_root=False)
        connection = sqlite3.connect(payload / "results.db")
        try:
            connection.execute(
                "INSERT INTO quizzes (title, source_file) VALUES (?, ?)",
                ("Restored quiz", "restored.html"),
            )
            connection.commit()
        finally:
            connection.close()
        (payload / "config" / "portal.json").write_text(
            json.dumps({"title": "Restored", "theme": "dark"}),
            encoding="utf-8",
        )
        files = sorted(path for path in payload.rglob("*") if path.is_file())
        manifest = {
            "schema_version": dlms.DLMS_BACKUP_SCHEMA_VERSION,
            "kind": "dlms-portable-backup",
            "created_at": "2026-09-02T12:00:00-05:00",
            "dlms_version": dlms.APP_VERSION,
            "file_count": len(files),
            "included_roots": ["config", "results.db"],
            "summary": {},
        }
        archive_path = self.root / f"backup-{self.archive_count}.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(manifest))
            for path in files:
                archive.write(
                    path,
                    dlms.DLMS_BACKUP_DATA_PREFIX + path.relative_to(payload).as_posix(),
                )
        return archive_path

    def _stage(self):
        archive_path = self._archive()
        with archive_path.open("rb") as upload:
            response = self.client.post(
                "/settings/backup/restore/stage",
                data={"backup_file": (upload, "backup.zip")},
                headers=csrf_headers(self.client, "/settings/backup"),
            )
        self.assertEqual(200, response.status_code)
        match = re.search(
            r"/settings/backup/restore/confirm/([a-f0-9]{32})",
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        token = match.group(1)
        self.last_stage_response = response
        return token, Path(dlms.BACKUP_RESTORE_STAGING_FOLDER) / token

    def test_successful_validation_creates_owned_stage_until_user_acts(self):
        token, stage_dir = self._stage()

        self.assertTrue(stage_dir.is_dir())
        self.assertTrue((stage_dir / "restore.zip").is_file())
        self.assertTrue((stage_dir / "report.json").is_file())
        state = json.loads(
            (stage_dir / dlms.RESTORE_STAGING_STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(dlms.RESTORE_STAGING_MARKER, state["marker"])
        self.assertEqual(token, state["token"])
        self.assertIn(
            f'/settings/backup/restore/cancel/{token}',
            self.last_stage_response.get_data(as_text=True),
        )
        self.assertEqual('{"state":"original"}', self.live_sentinel.read_text(encoding="utf-8"))

    def test_explicit_cancel_removes_only_its_stage_without_live_mutation(self):
        token, stage_dir = self._stage()
        other_token, other_stage = self._stage()

        response = self.client.post(
            f"/settings/backup/restore/cancel/{token}",
            headers=csrf_headers(self.client, "/settings/backup"),
            follow_redirects=False,
        )

        self.assertEqual(302, response.status_code)
        self.assertEqual("/settings/backup?restore_cancelled=1", response.headers["Location"])
        self.assertFalse(stage_dir.exists())
        self.assertTrue(other_stage.is_dir())
        self.assertNotEqual(token, other_token)
        self.assertEqual('{"state":"original"}', self.live_sentinel.read_text(encoding="utf-8"))

    def test_cancel_rejects_forged_tokens_and_is_idempotent_for_missing_stage(self):
        forged_token = "f" * 32
        forged_stage = Path(dlms.BACKUP_RESTORE_STAGING_FOLDER) / forged_token
        forged_stage.mkdir()
        sentinel = forged_stage / "not-dlms-stage.txt"
        sentinel.write_text("preserve", encoding="utf-8")

        forged = self.client.post(
            f"/settings/backup/restore/cancel/{forged_token}",
            headers=csrf_headers(self.client, "/settings/backup"),
        )
        malformed = self.client.post(
            "/settings/backup/restore/cancel/not-a-token",
            headers=csrf_headers(self.client, "/settings/backup"),
        )
        traversal = self.client.post(
            "/settings/backup/restore/cancel/%2e%2e",
            headers=csrf_headers(self.client, "/settings/backup"),
        )
        missing_token = "e" * 32
        first_missing = self.client.post(
            f"/settings/backup/restore/cancel/{missing_token}",
            headers=csrf_headers(self.client, "/settings/backup"),
            follow_redirects=False,
        )
        second_missing = self.client.post(
            f"/settings/backup/restore/cancel/{missing_token}",
            headers=csrf_headers(self.client, "/settings/backup"),
            follow_redirects=False,
        )

        self.assertEqual(404, forged.status_code)
        self.assertEqual(400, malformed.status_code)
        self.assertIn(traversal.status_code, {400, 404})
        self.assertTrue(sentinel.is_file())
        self.assertEqual(302, first_missing.status_code)
        self.assertEqual(302, second_missing.status_code)
        self.assertEqual('{"state":"original"}', self.live_sentinel.read_text(encoding="utf-8"))

    def test_cancel_route_is_csrf_protected(self):
        token, stage_dir = self._stage()

        rejected = self.client.post(f"/settings/backup/restore/cancel/{token}")

        self.assertEqual(400, rejected.status_code)
        self.assertTrue(stage_dir.is_dir())

    def test_stale_cleanup_removes_only_old_validated_stages(self):
        old_token, old_stage = self._stage()
        recent_token, recent_stage = self._stage()
        unrelated_directory = Path(dlms.BACKUP_RESTORE_STAGING_FOLDER) / "manual-note"
        unrelated_directory.mkdir()
        unrelated_file = unrelated_directory / "keep.txt"
        unrelated_file.write_text("keep", encoding="utf-8")
        forged_stage = Path(dlms.BACKUP_RESTORE_STAGING_FOLDER) / ("d" * 32)
        forged_stage.mkdir()
        forged_file = forged_stage / "keep.txt"
        forged_file.write_text("keep", encoding="utf-8")
        old_time = time.time() - dlms.RESTORE_STAGING_STALE_SECONDS - 1
        os.utime(old_stage, (old_time, old_time))

        report = dlms._cleanup_stale_restore_staging()

        self.assertEqual(1, report["removed"])
        self.assertFalse(old_stage.exists())
        self.assertTrue(recent_stage.is_dir())
        self.assertTrue(unrelated_file.is_file())
        self.assertTrue(forged_file.is_file())
        self.assertNotEqual(old_token, recent_token)

    def test_stale_cleanup_preserves_stage_while_restore_recovery_state_exists(self):
        _token, stage_dir = self._stage()
        old_time = time.time() - dlms.RESTORE_STAGING_STALE_SECONDS - 1
        os.utime(stage_dir, (old_time, old_time))
        recovery_root = Path(dlms._restore_operation_root())
        recovery_root.mkdir()
        (recovery_root / ("restore_" + "a" * 32 + ".json")).write_text(
            "{}", encoding="utf-8"
        )

        report = dlms._cleanup_stale_restore_staging()

        self.assertEqual(1, report["recovery"])
        self.assertTrue(stage_dir.is_dir())

    def test_successful_restore_still_cleans_its_staging_directory(self):
        token, stage_dir = self._stage()

        response = self.client.post(
            f"/settings/backup/restore/confirm/{token}",
            headers=csrf_headers(self.client, "/settings/backup"),
        )

        self.assertEqual(200, response.status_code)
        self.assertFalse(stage_dir.exists())
        self.assertEqual('{"state":"original"}', self.live_sentinel.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
