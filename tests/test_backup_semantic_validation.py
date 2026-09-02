import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="dlms-backup-semantic-app-")
os.environ["QUIZAPP_DATA_DIR"] = _IMPORT_DATA.name

import app as dlms
from tests.csrf_test_utils import csrf_headers


class BackupSemanticValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-backup-semantics-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _manifest(self, root=None, **updates):
        manifest = {
            "schema_version": dlms.DLMS_BACKUP_SCHEMA_VERSION,
            "kind": "dlms-portable-backup",
            "file_count": 0,
        }
        if root is not None:
            manifest["included_roots"] = sorted(path.name for path in root.iterdir())
        manifest.update(updates)
        return manifest

    def _write_core_database(self, path, *, omit_table=None, omit_question_text=False):
        definitions = {
            "quizzes": "id INTEGER, title TEXT, source_file TEXT",
            "questions": "id INTEGER, quiz_id INTEGER, question_number INTEGER" +
                         ("" if omit_question_text else ", question_text TEXT"),
            "choices": "id INTEGER, question_id INTEGER, label TEXT, text TEXT, is_correct INTEGER",
            "attempts": "id TEXT, quiz_id INTEGER, score INTEGER, total INTEGER, percent INTEGER, mode TEXT",
            "attempt_answers": "id INTEGER, attempt_id TEXT, question_id INTEGER, was_correct INTEGER",
            "missed_questions": "id INTEGER, attempt_id TEXT",
        }
        connection = sqlite3.connect(path)
        try:
            for table, columns in definitions.items():
                if table != omit_table:
                    connection.execute(f"CREATE TABLE {table} ({columns})")
            connection.commit()
        finally:
            connection.close()

    def test_valid_current_database_and_legacy_core_schema_pass(self):
        database = self.root / "results.db"
        self._write_core_database(database)
        result = dlms._validate_restored_sqlite(database)
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(result["schema"], "compatible")

    def test_non_sqlite_and_corrupt_sqlite_are_rejected(self):
        fake = self.root / "fake.db"
        fake.write_bytes(b"not sqlite")
        with self.assertRaisesRegex(ValueError, "corrupt|SQLite"):
            dlms._validate_restored_sqlite(fake)

        valid = self.root / "valid.db"
        self._write_core_database(valid)
        damaged = bytearray(valid.read_bytes())
        damaged[100:140] = b"X" * 40
        valid.write_bytes(damaged)
        with self.assertRaisesRegex(ValueError, "integrity|corrupt|SQLite"):
            dlms._validate_restored_sqlite(valid)

    def test_missing_critical_table_or_column_is_rejected(self):
        for name, kwargs, message in [
            ("missing-table.db", {"omit_table": "choices"}, "missing required table choices"),
            ("missing-column.db", {"omit_question_text": True}, "missing required column.*question_text"),
        ]:
            with self.subTest(name=name):
                path = self.root / name
                self._write_core_database(path, **kwargs)
                with self.assertRaisesRegex(ValueError, message):
                    dlms._validate_restored_sqlite(path)

    def test_integrity_check_failure_is_rejected(self):
        connection = mock.MagicMock()
        connection.execute.return_value.fetchall.return_value = [("page 3 is damaged",)]
        with mock.patch.object(dlms.sqlite3, "connect", return_value=connection):
            with self.assertRaisesRegex(ValueError, "failed SQLite integrity_check"):
                dlms._validate_restored_sqlite(self.root / "results.db")
        connection.close.assert_called_once()

    def test_json_syntax_and_critical_shapes_are_validated(self):
        config = self.root / "config"
        config.mkdir()
        portal = config / "portal.json"
        portal.write_text('{"title": "Study", "theme": "dark"}', encoding="utf-8")
        self.assertIsInstance(dlms._validate_restored_json(portal, "config/portal.json"), dict)

        portal.write_text("{bad", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            dlms._validate_restored_json(portal, "config/portal.json")
        portal.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            dlms._validate_restored_json(portal, "config/portal.json")

        # Evolving user-content JSON remains deliberately shape-flexible.
        optional = self.root / "data.json"
        optional.write_text('"legacy-value"', encoding="utf-8")
        self.assertEqual(dlms._validate_restored_json(optional, "data/legacy.json"), "legacy-value")

    def test_valid_raster_passes_and_active_or_malformed_assets_fail(self):
        background = self.root / "static" / "bg"
        background.mkdir(parents=True)
        png = background / "safe.png"
        Image.new("RGB", (2, 2), "green").save(png)
        self.assertEqual(dlms._validate_restored_assets(self.root), ["static/bg/safe.png"])

        png.write_bytes(b"<html><script>alert(1)</script></html>")
        with self.assertRaisesRegex(ValueError, "Unsafe restored image asset"):
            dlms._validate_restored_assets(self.root)

        png.unlink()
        (background / "active.svg").write_text("<svg onload='alert(1)'></svg>", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SVG|unsupported image type"):
            dlms._validate_restored_assets(self.root)

    def test_manifest_version_types_and_declared_roots_are_validated(self):
        (self.root / "config").mkdir()
        dlms._validate_backup_manifest_semantics(self._manifest(self.root), self.root)
        with self.assertRaisesRegex(ValueError, "Unsupported backup schema_version"):
            dlms._validate_backup_manifest_semantics(self._manifest(schema_version=999), self.root)
        with self.assertRaisesRegex(ValueError, "included_roots does not match"):
            dlms._validate_backup_manifest_semantics(
                self._manifest(included_roots=["other"]), self.root
            )

    def test_complete_staged_backup_passes_and_requires_results_database(self):
        config = self.root / "config"
        config.mkdir()
        (config / "portal.json").write_text('{"title":"Study","theme":"dark"}', encoding="utf-8")
        self._write_core_database(self.root / "results.db")
        result = dlms._validate_staged_backup_semantics(self.root, self._manifest(self.root))
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["sqlite"][0]["path"], "results.db")

        (self.root / "results.db").unlink()
        with self.assertRaisesRegex(ValueError, "missing required DLMS database"):
            dlms._validate_staged_backup_semantics(self.root, self._manifest(self.root))

    def test_current_application_backup_passes_structural_and_semantic_validation(self):
        backup_path, _manifest = dlms._create_dlms_backup("semantic-test")
        report = dlms._validate_dlms_backup(backup_path)
        extracted = self.root / "current-backup"
        dlms._extract_validated_backup(backup_path, extracted, report)
        result = dlms._validate_staged_backup_semantics(extracted, report["manifest"])
        self.assertEqual(result["status"], "valid")

    def test_semantic_failure_precedes_backup_and_live_apply(self):
        client = dlms.app.test_client()
        stage_dir = self.root / "stage"
        stage_dir.mkdir()
        archive_path = stage_dir / "restore.zip"
        manifest = self._manifest(file_count=1)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(manifest))
            archive.writestr("DLMS_DATA/config/portal.json", "{}")

        events = []
        with mock.patch.object(dlms, "_restore_staging_dir", return_value=str(stage_dir)), \
             mock.patch.object(dlms, "_validate_staged_backup_semantics", side_effect=ValueError("bad semantics")), \
             mock.patch.object(dlms, "_create_dlms_backup", side_effect=lambda *_: events.append("backup")), \
             mock.patch.object(dlms, "_apply_restored_data", side_effect=lambda *_: events.append("apply")):
            response = client.post(
                "/settings/backup/restore/confirm/" + "a" * 32,
                headers=csrf_headers(client),
            )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b"bad semantics", response.data)
        self.assertIn(b"could not complete the restore", response.data)
        self.assertEqual(events, [])

    def test_valid_restore_orders_semantics_before_backup_and_apply(self):
        client = dlms.app.test_client()
        stage_dir = self.root / "valid-stage"
        stage_dir.mkdir()
        archive_path = stage_dir / "restore.zip"
        manifest = self._manifest(file_count=1)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(manifest))
            archive.writestr("DLMS_DATA/config/portal.json", "{}")
        safety = Path(dlms.BACKUP_FOLDER) / "semantic-safety.zip"
        safety.write_bytes(b"preserved")
        events = []

        def semantic(*_args):
            events.append("semantic")
            return {"status": "valid"}

        fake_journal = {"state": "safety_backup_created"}
        with mock.patch.object(dlms, "_restore_staging_dir", return_value=str(stage_dir)), \
             mock.patch.object(dlms, "_validate_staged_backup_semantics", side_effect=semantic), \
             mock.patch.object(dlms, "_prepare_staged_restore_database", side_effect=lambda *_: events.append("migrate")), \
             mock.patch.object(dlms, "_create_dlms_backup", side_effect=lambda *_: (events.append("backup") or (str(safety), {}))), \
             mock.patch.object(dlms, "_new_restore_operation", return_value=("journal.json", fake_journal)), \
             mock.patch.object(dlms, "_update_restore_operation_journal"), \
             mock.patch.object(dlms, "_validate_restore_operation_journal", return_value={}), \
             mock.patch.object(dlms, "_finish_restore_operation_cleanup"), \
             mock.patch.object(dlms, "_validate_current_restored_database"), \
             mock.patch.object(dlms, "_apply_restored_data", side_effect=lambda *_: events.append("apply")), \
             mock.patch.object(dlms, "reconcile_quiz_publications", side_effect=lambda: events.append("reconcile")):
            response = client.post(
                "/settings/backup/restore/confirm/" + "b" * 32,
                headers=csrf_headers(client),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events, ["semantic", "migrate", "backup", "apply", "reconcile"])

    def test_apply_failure_still_uses_existing_rollback_path(self):
        client = dlms.app.test_client()
        stage_dir = self.root / "rollback-stage"
        stage_dir.mkdir()
        archive_path = stage_dir / "restore.zip"
        manifest = self._manifest(file_count=1)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(manifest))
            archive.writestr("DLMS_DATA/config/portal.json", "{}")
        safety = Path(dlms.BACKUP_FOLDER) / "rollback-safety.zip"
        safety.write_bytes(archive_path.read_bytes())
        apply_calls = []

        def apply_then_rollback(path):
            apply_calls.append(path)
            if len(apply_calls) == 1:
                raise OSError("simulated apply failure")

        fake_journal = {"state": "live_apply_started"}

        def recover(*_args):
            apply_then_rollback("journal-rollback")
            return "rolled_back"

        with mock.patch.object(dlms, "_restore_staging_dir", return_value=str(stage_dir)), \
             mock.patch.object(dlms, "_validate_staged_backup_semantics", return_value={"status": "valid"}), \
             mock.patch.object(dlms, "_prepare_staged_restore_database", return_value={"status": "current"}), \
             mock.patch.object(dlms, "_create_dlms_backup", return_value=(str(safety), {})), \
             mock.patch.object(dlms, "_new_restore_operation", return_value=("journal.json", fake_journal)), \
             mock.patch.object(dlms, "_update_restore_operation_journal"), \
             mock.patch.object(dlms, "_read_restore_operation_journal", return_value=(fake_journal, {})), \
             mock.patch.object(dlms, "_recover_one_restore_operation", side_effect=recover), \
             mock.patch.object(dlms, "_apply_restored_data", side_effect=apply_then_rollback), \
             mock.patch.object(dlms, "reconcile_quiz_publications"):
            response = client.post(
                "/settings/backup/restore/confirm/" + "c" * 32,
                headers=csrf_headers(client),
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b"simulated apply failure", response.data)
        self.assertIn(b"preserved or rolled back", response.data)
        self.assertEqual(len(apply_calls), 2)


if __name__ == "__main__":
    unittest.main()
