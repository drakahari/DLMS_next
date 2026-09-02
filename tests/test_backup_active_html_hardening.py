"""DLMS-080 backup restore active-HTML trust-boundary regressions."""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="dlms-backup-html-app-")
os.environ["QUIZAPP_DATA_DIR"] = _IMPORT_DATA.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


class BackupActiveHtmlHardeningTests(unittest.TestCase):
    ATTACK_MARKER = "DLMS080_ATTACKER_CONTROLLED_HTML"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-backup-html-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        dlms._initialize_data_root_ownership(str(self.root))
        app_data_patch = mock.patch.object(dlms, "APP_DATA_DIR", str(self.root))
        app_data_patch.start()
        self.addCleanup(app_data_patch.stop)

    def _create_backup(self):
        payload = self.root / "payload"
        (payload / "config").mkdir(parents=True)
        (payload / "data").mkdir()
        (payload / "quizzes" / "nested").mkdir(parents=True)

        database = payload / "results.db"
        dlms.bootstrap_database(str(database), require_owned_root=False)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "INSERT INTO quizzes (id, title, source_file) VALUES (?, ?, ?)",
                (801, "Canonical Restored Quiz", "restored-source"),
            )
            connection.execute(
                """
                INSERT INTO questions (
                    quiz_id, question_number, question_text, question_type
                ) VALUES (?, ?, ?, ?)
                """,
                (801, 1, "Safe canonical question", "choice"),
            )
            question_id = connection.execute(
                "SELECT id FROM questions WHERE quiz_id = 801"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO choices (question_id, label, text, is_correct)
                VALUES (?, ?, ?, 1)
                """,
                (question_id, "A", "Safe answer"),
            )
            connection.commit()
        finally:
            connection.close()

        registry = [{
            "id": 801,
            "title": "Registry Restored Quiz",
            "html": "restored_quiz.html",
            "exam_minutes": 45,
        }]
        (payload / "config" / "quizzes.json").write_text(
            json.dumps(registry), encoding="utf-8"
        )
        (payload / "config" / "portal.json").write_text(
            json.dumps({"title": "Restored Portal"}), encoding="utf-8"
        )
        (payload / "data" / "restored_quiz.json").write_text(
            json.dumps([{
                "number": 1,
                "question": "Safe canonical question",
                "choices": [{"label": "A", "text": "Safe answer", "is_correct": True}],
                "correct": ["A"],
            }]),
            encoding="utf-8",
        )
        malicious = f"<!doctype html><script>window.{self.ATTACK_MARKER}=true</script>"
        (payload / "quizzes" / "restored_quiz.html").write_text(
            malicious, encoding="utf-8"
        )
        (payload / "quizzes" / "unregistered.html").write_text(
            malicious, encoding="utf-8"
        )
        (payload / "quizzes" / "nested" / "also-active.html").write_text(
            malicious, encoding="utf-8"
        )

        files = sorted(path for path in payload.rglob("*") if path.is_file())
        manifest = {
            "schema_version": dlms.DLMS_BACKUP_SCHEMA_VERSION,
            "kind": "dlms-portable-backup",
            "file_count": len(files),
            "included_roots": sorted({
                path.relative_to(payload).parts[0] for path in files
            }),
        }
        archive_path = self.root / "crafted-valid-backup.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(manifest))
            for path in files:
                archive.write(
                    path,
                    dlms.DLMS_BACKUP_DATA_PREFIX + path.relative_to(payload).as_posix(),
                )
        return archive_path

    def _extract_validated_backup(self, archive_path, name="extracted"):
        report = dlms._validate_dlms_backup(archive_path)
        extracted = self.root / name
        dlms._extract_validated_backup(archive_path, extracted, report)
        semantic = dlms._validate_staged_backup_semantics(
            extracted, report["manifest"]
        )
        self.assertEqual("valid", semantic["status"])
        return extracted, report

    def test_restored_active_html_is_replaced_with_generated_artifacts(self):
        archive_path = self._create_backup()
        extracted, _report = self._extract_validated_backup(archive_path)
        restored_html = extracted / "quizzes" / "restored_quiz.html"

        # Backward-compatible archive validation accepts historical generated
        # HTML, so the trust-boundary preparation step must replace it.
        self.assertIn(self.ATTACK_MARKER, restored_html.read_text(encoding="utf-8"))

        result = dlms._prepare_staged_restore_database(extracted)

        generated = restored_html.read_text(encoding="utf-8")
        self.assertEqual({"generated": 1, "skipped": 0}, result["quiz_html"])
        self.assertNotIn(self.ATTACK_MARKER, generated)
        self.assertIn("Canonical Restored Quiz", generated)
        self.assertIn('const QUIZ_FILE = "/data/restored_quiz.json";', generated)
        self.assertIn('<script src="/static/script.js"></script>', generated)
        self.assertFalse((extracted / "quizzes" / "unregistered.html").exists())
        self.assertFalse((extracted / "quizzes" / "nested").exists())
        self.assertEqual(["restored_quiz.html"], sorted(
            path.name for path in (extracted / "quizzes").iterdir()
        ))

        with mock.patch.object(dlms, "QUIZ_FOLDER", str(extracted / "quizzes")):
            client = dlms.app.test_client()
            served = client.get("/quizzes/restored_quiz.html")
            removed = client.get("/quizzes/unregistered.html")
        self.assertEqual(200, served.status_code)
        self.assertNotIn(self.ATTACK_MARKER.encode(), served.data)
        self.assertEqual(404, removed.status_code)
        served.close()
        removed.close()

    def test_restore_route_never_applies_backup_supplied_quiz_html(self):
        archive_path = self._create_backup()
        stage_dir = self.root / "restore-stage"
        stage_dir.mkdir()
        shutil.copy2(archive_path, stage_dir / "restore.zip")
        safety = self.root / "dlms080-safety.zip"
        safety.write_bytes(b"preserved")
        applied = []
        validate_current = dlms._validate_current_restored_database

        def inspect_apply(staged_root):
            html = Path(staged_root, "quizzes", "restored_quiz.html").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(self.ATTACK_MARKER, html)
            self.assertFalse(Path(staged_root, "quizzes", "unregistered.html").exists())
            applied.append(html)

        def validate_staged_or_mock_live(database_path):
            if os.path.realpath(database_path) == os.path.realpath(dlms.DB_PATH):
                return {}
            return validate_current(database_path)

        fake_journal = {"state": "safety_backup_created"}
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_restore_staging_dir", return_value=str(stage_dir)), \
             mock.patch.object(dlms, "_create_dlms_backup", return_value=(str(safety), {})), \
             mock.patch.object(dlms, "_new_restore_operation", return_value=("journal.json", fake_journal)), \
             mock.patch.object(dlms, "_update_restore_operation_journal"), \
             mock.patch.object(dlms, "_restore_operation_checkpoint"), \
             mock.patch.object(dlms, "_apply_restored_data", side_effect=inspect_apply), \
             mock.patch.object(
                 dlms,
                 "_validate_current_restored_database",
                 side_effect=validate_staged_or_mock_live,
             ), \
             mock.patch.object(dlms, "reconcile_quiz_publications", return_value={}), \
             mock.patch.object(dlms, "_validate_restore_operation_journal", return_value={}), \
             mock.patch.object(dlms, "_finish_restore_operation_cleanup"):
            response = client.post(
                "/settings/backup/restore/confirm/" + "d" * 32,
                headers=csrf_headers(client),
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(applied))

    def test_generation_failure_is_rejected_before_live_mutation(self):
        archive_path = self._create_backup()
        stage_dir = self.root / "failure-stage"
        stage_dir.mkdir()
        shutil.copy2(archive_path, stage_dir / "restore.zip")
        client = dlms.app.test_client()

        with mock.patch.object(dlms, "_restore_staging_dir", return_value=str(stage_dir)), \
             mock.patch.object(dlms, "build_quiz_html", side_effect=OSError("render failed")), \
             mock.patch.object(dlms, "_create_dlms_backup") as safety, \
             mock.patch.object(dlms, "_apply_restored_data") as apply:
            response = client.post(
                "/settings/backup/restore/confirm/" + "e" * 32,
                headers=csrf_headers(client),
            )

        self.assertEqual(400, response.status_code)
        self.assertNotIn(b"render failed", response.data)
        safety.assert_not_called()
        apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
