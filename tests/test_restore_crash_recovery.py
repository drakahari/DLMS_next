"""DLMS-047 restore journal and startup crash-recovery regressions."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="dlms-restore-recovery-app-")
os.environ["QUIZAPP_DATA_DIR"] = _IMPORT_DATA.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class SimulatedCrash(BaseException):
    pass


class RestoreCrashRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-restore-recovery-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "live"
        self.root.mkdir()
        dlms._initialize_data_root_ownership(str(self.root))
        self.db_path = self.root / "results.db"
        self.backups = self.root / "backups"
        self.staging = self.backups / "restore_staging"
        self.backups.mkdir()
        self.staging.mkdir()
        self.patches = [
            mock.patch.object(dlms, "APP_DATA_DIR", str(self.root)),
            mock.patch.object(dlms, "DB_PATH", str(self.db_path)),
            mock.patch.object(dlms, "BACKUP_FOLDER", str(self.backups)),
            mock.patch.object(dlms, "BACKUP_RESTORE_STAGING_FOLDER", str(self.staging)),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        dlms.bootstrap_database(str(self.db_path))
        self._set_title("Original Live")
        self.sentinel = self.root / "live-state.txt"
        self.sentinel.write_text("original", encoding="utf-8")
        self.safety_path, self.safety_manifest = dlms._create_dlms_backup(
            "pre-restore-test"
        )
        self.token = "a" * 32
        (self.staging / self.token).mkdir()

    def _set_title(self, title):
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DELETE FROM quizzes")
            connection.execute(
                "INSERT INTO quizzes (title, source_file) VALUES (?, ?)",
                (title, title.lower().replace(" ", "-") + ".html"),
            )
            connection.commit()
        finally:
            connection.close()

    def _title(self):
        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute("SELECT title FROM quizzes ORDER BY id LIMIT 1").fetchone()
            return row[0] if row else None
        finally:
            connection.close()

    def _journal(self, state="safety_backup_created", restore_roots=None):
        journal_path, journal = dlms._new_restore_operation(
            self.token,
            self.safety_path,
            {"created_at": "2026-08-29T12:00:00-05:00", "dlms_version": "3.0.2"},
            safety_manifest=self.safety_manifest,
            restore_roots=restore_roots or ["results.db", "live-state.txt"],
        )
        if state != "safety_backup_created":
            dlms._update_restore_operation_journal(journal_path, journal, state)
        return Path(journal_path), journal

    def _journal_files(self):
        root = Path(dlms._restore_operation_root())
        return sorted(root.glob("restore_*.json")) if root.exists() else []

    def _partially_mutate_live(self):
        self.sentinel.write_text("partially-restored", encoding="utf-8")
        self._set_title("Partial Restore")
        (self.root / "unrelated-after-safety.txt").write_text(
            "leave me", encoding="utf-8"
        )

    def test_pre_mutation_abandonment_cleans_only_helper_state(self):
        journal_path, _journal = self._journal()
        report = dlms.reconcile_restore_operations()

        self.assertEqual(report["abandoned"], 1)
        self.assertEqual(self._title(), "Original Live")
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "original")
        self.assertFalse(journal_path.exists())
        self.assertFalse((self.staging / self.token).exists())
        self.assertTrue(Path(self.safety_path).exists())

    def test_journal_is_durable_before_pre_mutation_checkpoint(self):
        def checkpoint(stage, _journal):
            if stage == "safety_backup_created":
                raise SimulatedCrash(stage)

        with mock.patch.object(dlms, "_restore_operation_checkpoint", side_effect=checkpoint):
            with self.assertRaises(SimulatedCrash):
                dlms._new_restore_operation(self.token, self.safety_path, {})

        self.assertEqual(len(self._journal_files()), 1)
        self.assertEqual(self._title(), "Original Live")
        self.assertEqual(dlms.reconcile_restore_operations()["abandoned"], 1)

    def test_live_apply_crash_rolls_back_exact_snapshot_before_publication_recovery(self):
        self._journal("live_apply_started")
        self._partially_mutate_live()
        observed = []

        def reconcile_publications():
            observed.append((self._title(), self.sentinel.read_text(encoding="utf-8")))
            return {"processed": 0}

        with mock.patch.object(
            dlms, "reconcile_quiz_publications", side_effect=reconcile_publications
        ):
            report = dlms.reconcile_restore_operations()

        self.assertEqual(report["rolled_back"], 1)
        self.assertEqual(observed, [("Original Live", "original")])
        self.assertEqual(self._title(), "Original Live")
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "original")
        self.assertFalse((self.root / "unrelated-after-safety.txt").exists())
        self.assertEqual(self._journal_files(), [])

    def test_rollback_removes_all_roots_absent_from_safety_snapshot(self):
        self._journal(
            "live_apply_started",
            restore_roots=["results.db", "live-state.txt", "restored-only"],
        )
        restored_only = self.root / "restored-only"
        restored_only.mkdir()
        (restored_only / "new-data.txt").write_text("partial", encoding="utf-8")
        unrelated = self.root / "unrelated-root"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_text("keep", encoding="utf-8")

        with mock.patch.object(
            dlms, "reconcile_quiz_publications", return_value={"processed": 0}
        ):
            report = dlms.reconcile_restore_operations()

        self.assertEqual(report["rolled_back"], 1)
        self.assertFalse(restored_only.exists())
        self.assertFalse(unrelated.exists())

    def test_all_pre_reconciliation_crash_states_conservatively_roll_back(self):
        for state in (
            "live_apply_completed",
            "post_apply_validated",
            "rollback_pending",
            "rollback_started",
        ):
            with self.subTest(state=state):
                if self._journal_files():
                    self.fail("prior recovery left a journal")
                if not (self.staging / self.token).exists():
                    (self.staging / self.token).mkdir(parents=True)
                self._set_title("Original Live")
                self.sentinel.write_text("original", encoding="utf-8")
                self._journal(state)
                self._partially_mutate_live()
                with mock.patch.object(
                    dlms, "reconcile_quiz_publications", return_value={"processed": 0}
                ):
                    report = dlms.reconcile_restore_operations()
                self.assertEqual(report["rolled_back"], 1)
                self.assertEqual(self._title(), "Original Live")
                self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "original")

    def test_reconciled_or_complete_restore_with_stale_journal_is_preserved(self):
        for state in ("reconciliation_completed", "complete"):
            with self.subTest(state=state):
                if not (self.staging / self.token).exists():
                    (self.staging / self.token).mkdir(parents=True)
                journal_path, _journal = self._journal(state)
                self._set_title("Validated Restored")
                self.sentinel.write_text("restored", encoding="utf-8")

                first = dlms.reconcile_restore_operations()
                second = dlms.reconcile_restore_operations()

                self.assertEqual(first["preserved"], 1)
                self.assertEqual(second["processed"], 0)
                self.assertEqual(self._title(), "Validated Restored")
                self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "restored")
                self.assertFalse(journal_path.exists())

    def test_crash_during_rollback_retries_idempotently(self):
        self._journal("live_apply_started")
        self._partially_mutate_live()

        def checkpoint(stage, _journal):
            if stage == "rollback_started":
                raise SimulatedCrash(stage)

        with mock.patch.object(dlms, "_restore_operation_checkpoint", side_effect=checkpoint):
            with self.assertRaises(SimulatedCrash):
                dlms.reconcile_restore_operations()
        self.assertEqual(len(self._journal_files()), 1)

        with mock.patch.object(
            dlms, "reconcile_quiz_publications", return_value={"processed": 0}
        ):
            report = dlms.reconcile_restore_operations()
        self.assertEqual(report["rolled_back"], 1)
        self.assertEqual(self._title(), "Original Live")
        self.assertEqual(self._journal_files(), [])

    def test_rollback_failure_retains_journal_and_safety_backup(self):
        self._journal("live_apply_started")
        self._partially_mutate_live()
        Path(self.safety_path).write_bytes(b"not a backup")

        with self.assertRaisesRegex(RuntimeError, "could not complete safely"):
            dlms.reconcile_restore_operations()

        self.assertEqual(len(self._journal_files()), 1)
        self.assertTrue(Path(self.safety_path).exists())
        self.assertEqual(self._title(), "Partial Restore")

    def test_malformed_future_and_unsafe_journals_never_mutate_live_data(self):
        cases = []
        journal_path, journal = self._journal()
        cases.append(("malformed", "{bad json"))
        future = dict(journal)
        future["schema_version"] = dlms.RESTORE_OPERATION_JOURNAL_VERSION + 1
        cases.append(("future", json.dumps(future)))
        traversal = dict(journal)
        traversal["safety_backup"] = {"name": "../outside.zip"}
        cases.append(("traversal", json.dumps(traversal)))
        absolute = dict(journal)
        absolute["safety_backup"] = {"name": str(Path(self.safety_path).resolve())}
        cases.append(("absolute", json.dumps(absolute)))
        invalid_state = dict(journal)
        invalid_state["state"] = "maybe_restored"
        cases.append(("invalid-state", json.dumps(invalid_state)))
        missing_field = dict(journal)
        missing_field.pop("staging")
        cases.append(("missing-field", json.dumps(missing_field)))

        for label, raw in cases:
            with self.subTest(label=label):
                journal_path.write_text(raw, encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "could not complete safely"):
                    dlms.reconcile_restore_operations()
                self.assertEqual(self._title(), "Original Live")
                self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "original")
                self.assertTrue(journal_path.exists())

    def test_symlinked_safety_backup_is_rejected_without_mutation(self):
        external = Path(self.temporary.name) / "external.zip"
        external.write_bytes(Path(self.safety_path).read_bytes())
        safety = Path(self.safety_path)
        safety.unlink()
        try:
            safety.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        journal_path, journal = self._journal_record_for_existing_safety(safety.name)
        self._partially_mutate_live()

        with self.assertRaisesRegex(RuntimeError, "could not complete safely"):
            dlms.reconcile_restore_operations()
        self.assertTrue(journal_path.exists())
        self.assertEqual(self._title(), "Partial Restore")

    def test_unlinked_recovery_directory_is_left_for_inspection(self):
        recovery = Path(dlms._restore_operation_root()) / ("recovery_" + "c" * 32)
        recovery.mkdir(parents=True)

        with self.assertRaisesRegex(RuntimeError, "malformed or unsupported"):
            dlms.reconcile_restore_operations()

        self.assertTrue(recovery.is_dir())
        self.assertEqual(self._title(), "Original Live")

    def _journal_record_for_existing_safety(self, safety_name):
        operation_id = "b" * 32
        now = "2026-08-29T12:00:00-05:00"
        journal = {
            "marker": dlms.RESTORE_OPERATION_JOURNAL_MARKER,
            "schema_version": dlms.RESTORE_OPERATION_JOURNAL_VERSION,
            "operation_id": operation_id,
            "created_at": now,
            "updated_at": now,
            "state": "live_apply_started",
            "safety_backup": {"name": safety_name},
            "staging": {"token": self.token},
            "backup_identity": {},
            "live_roots": {
                "restore": ["results.db", "live-state.txt"],
                "safety": self.safety_manifest["included_roots"],
            },
        }
        root = Path(dlms._restore_operation_root())
        root.mkdir(exist_ok=True)
        path = root / f"restore_{operation_id}.json"
        path.write_text(json.dumps(journal), encoding="utf-8")
        return path, journal

    def test_unowned_root_blocks_reconciliation_without_cleanup(self):
        journal_path, _journal = self._journal()
        (self.root / dlms.DLMS_DATA_ROOT_MARKER).unlink()

        with self.assertRaisesRegex(dlms.DataRootOwnershipError, "not verified"):
            dlms.reconcile_restore_operations()
        self.assertTrue(journal_path.exists())
        self.assertTrue(Path(self.safety_path).exists())


if __name__ == "__main__":
    unittest.main()
