"""DLMS-043B publication-journal and crash-reconciliation regressions."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-publication-recovery-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class SimulatedCrash(BaseException):
    pass


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
    dlms.LOGO_FOLDER = str(root / "static" / "logos")
    dlms.LOGO_TEMP_FOLDER = str(root / "static" / "logos" / "_temp")
    for path in (
        dlms.DATA_FOLDER,
        dlms.QUIZ_FOLDER,
        dlms.CONFIG_FOLDER,
        dlms.QUIZ_ASSET_FOLDER,
        dlms.CONTENT_PACK_FOLDER,
        dlms.LOGO_FOLDER,
        dlms.LOGO_TEMP_FOLDER,
    ):
        os.makedirs(path, exist_ok=True)


class PublicationReconciliationTests(unittest.TestCase):
    def setUp(self):
        self._reset_runtime()

    def _reset_runtime(self):
        for child in Path(_TEMP.name).iterdir():
            if child.name in {dlms.DLMS_DATA_ROOT_MARKER, ".secret_key"}:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        _bind_paths()
        dlms.ensure_db_initialized()

    @staticmethod
    def _questions():
        return [{
            "number": 1,
            "type": "choice",
            "question": "Which boundary is durable?",
            "concepts": ["crash-recovery"],
            "choices": [
                {"label": "A", "text": "Journal", "is_correct": True},
                {"label": "B", "text": "Memory", "is_correct": False},
            ],
        }]

    def _db_quiz_ids(self):
        conn = dlms.get_db()
        try:
            return [row[0] for row in conn.execute("SELECT id FROM quizzes ORDER BY id")]
        finally:
            conn.close()

    def _journal_files(self):
        root = Path(dlms._quiz_publication_staging_root())
        if not root.exists():
            return []
        return sorted(path for path in root.iterdir() if path.name.startswith("publication_"))

    def _crash_at(self, boundary, *, question=None, source_pack_id=None):
        def checkpoint(stage, _journal):
            if stage == boundary:
                raise SimulatedCrash(boundary)

        with mock.patch.object(dlms, "_quiz_publication_checkpoint", side_effect=checkpoint):
            with self.assertRaises(SimulatedCrash):
                dlms._publish_quiz(
                    f"Crash at {boundary}",
                    [question or self._questions()[0]],
                    filename_prefix=f"crash_{boundary}",
                    source_pack_id=source_pack_id,
                )
        self.assertEqual(1, len(self._journal_files()))

    def _assert_rolled_back(self):
        report = dlms.reconcile_quiz_publications()
        self.assertEqual(1, report["rolled_back"])
        self.assertEqual([], self._db_quiz_ids())
        self.assertEqual([], dlms.load_registry())
        self.assertEqual([], list(Path(dlms.DATA_FOLDER).iterdir()))
        self.assertEqual([], list(Path(dlms.QUIZ_FOLDER).iterdir()))
        self.assertEqual([], list(Path(dlms.QUIZ_ASSET_FOLDER).iterdir()))
        self.assertEqual([], self._journal_files())

    def test_pre_registry_crash_boundaries_roll_back_exact_publication(self):
        for boundary in (
            "journal_created",
            "db_committed",
            "json_promoted",
            "html_promoted",
            "artifacts_promoted",
        ):
            with self.subTest(boundary=boundary):
                self._reset_runtime()
                self._crash_at(boundary)
                self._assert_rolled_back()

    def test_crash_after_asset_promotion_rolls_back_asset_bucket(self):
        pack_root = Path(dlms.CONTENT_PACK_FOLDER) / "DLMS_Study_recovery_assets"
        (pack_root / "images").mkdir(parents=True)
        Image.new("RGB", (6, 6), "blue").save(pack_root / "images" / "diagram.png")
        (pack_root / "manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "id": "recovery_assets",
            "name": "Recovery Assets",
            "datasets": [],
            "image_datasets": [],
            "quiz_datasets": [],
        }), encoding="utf-8")
        question = self._questions()[0]
        question["image_url"] = "/content-packs/recovery_assets/assets/images/diagram.png"
        self._crash_at(
            "assets_promoted", question=question, source_pack_id="recovery_assets"
        )
        self.assertTrue(any(Path(dlms.QUIZ_ASSET_FOLDER).iterdir()))
        self._assert_rolled_back()

    def test_registry_published_crash_preserves_valid_quiz_and_is_idempotent(self):
        self._crash_at("registry_published")
        registry = dlms.load_registry()
        self.assertEqual(1, len(registry))
        quiz_id = registry[0]["id"]
        html_name = registry[0]["html"]
        report = dlms.reconcile_quiz_publications()
        self.assertEqual(1, report["preserved"])
        self.assertEqual([quiz_id], self._db_quiz_ids())
        self.assertTrue((Path(dlms.QUIZ_FOLDER) / html_name).is_file())
        self.assertTrue((Path(dlms.DATA_FOLDER) / html_name.replace(".html", ".json")).is_file())
        self.assertEqual(1, len(dlms.load_registry()))
        self.assertEqual([], self._journal_files())

        repeated = dlms.reconcile_quiz_publications()
        self.assertEqual(0, repeated["processed"])
        self.assertEqual(1, len(dlms.load_registry()))
        self.assertEqual([quiz_id], self._db_quiz_ids())

    def test_complete_state_crash_preserves_valid_quiz(self):
        self._crash_at("complete")
        self.assertEqual(1, dlms.reconcile_quiz_publications()["preserved"])
        self.assertEqual(1, len(dlms.load_registry()))
        self.assertEqual(1, len(self._db_quiz_ids()))

    def test_published_but_incomplete_quiz_is_rolled_back_exactly(self):
        self._crash_at("registry_published")
        entry = dlms.load_registry()[0]
        (Path(dlms.DATA_FOLDER) / entry["html"].replace(".html", ".json")).unlink()
        report = dlms.reconcile_quiz_publications()
        self.assertEqual(1, report["rolled_back"])
        self.assertEqual([], dlms.load_registry())
        self.assertEqual([], self._db_quiz_ids())
        self.assertFalse((Path(dlms.QUIZ_FOLDER) / entry["html"]).exists())
        self.assertEqual([], self._journal_files())

    def test_reconciliation_crash_retries_without_duplicates(self):
        self._crash_at("json_promoted")
        with mock.patch.object(
            dlms, "_delete_recorded_quiz_rows", side_effect=RuntimeError("recovery crash")
        ):
            first = dlms.reconcile_quiz_publications()
        self.assertEqual(1, first["failed"])
        self.assertEqual(1, len(self._journal_files()))
        second = dlms.reconcile_quiz_publications()
        self.assertEqual(1, second["rolled_back"])
        self.assertEqual([], self._db_quiz_ids())
        self.assertEqual([], dlms.load_registry())
        self.assertEqual(0, dlms.reconcile_quiz_publications()["processed"])

    def test_handled_rollback_failure_retains_journal_for_startup_retry(self):
        with mock.patch.object(
            dlms, "_promote_quiz_artifact", side_effect=RuntimeError("promotion failure")
        ), mock.patch.object(
            dlms, "_delete_recorded_quiz_rows", side_effect=RuntimeError("cleanup failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "promotion failure"):
                dlms._publish_quiz(
                    "Retry cleanup", self._questions(), filename_prefix="retry_cleanup"
                )
        self.assertEqual(1, len(self._db_quiz_ids()))
        self.assertEqual(1, len(self._journal_files()))
        report = dlms.reconcile_quiz_publications()
        self.assertEqual(1, report["rolled_back"])
        self.assertEqual([], self._db_quiz_ids())
        self.assertEqual([], self._journal_files())

    def test_reconciliation_does_not_touch_unrelated_published_quiz(self):
        existing_id, existing_html = dlms._publish_quiz(
            "Existing", self._questions(), filename_prefix="existing"
        )
        self._crash_at("html_promoted")
        report = dlms.reconcile_quiz_publications()
        self.assertEqual(1, report["rolled_back"])
        self.assertEqual([existing_id], self._db_quiz_ids())
        self.assertEqual([existing_html], [entry["html"] for entry in dlms.load_registry()])
        self.assertTrue((Path(dlms.QUIZ_FOLDER) / existing_html).is_file())
        self.assertTrue(
            (Path(dlms.DATA_FOLDER) / existing_html.replace(".html", ".json")).is_file()
        )

    def _journal_record(self, publication_id=None):
        publication_id = publication_id or ("a" * 32)
        html_name, json_name = dlms._generated_quiz_artifact_names("journal_test")
        stem = Path(html_name).stem
        return {
            "marker": dlms.QUIZ_PUBLICATION_JOURNAL_MARKER,
            "schema_version": dlms.QUIZ_PUBLICATION_JOURNAL_VERSION,
            "publication_id": publication_id,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "state": "staging",
            "stage_dir": f"publish_{publication_id}",
            "quiz": {"id": None, "source_file": html_name},
            "artifacts": {
                "json": {"name": json_name, "attempted": False, "promoted": False},
                "html": {"name": html_name, "attempted": False, "promoted": False},
                "assets": {
                    "name": stem,
                    "required": False,
                    "attempted": False,
                    "promoted": False,
                },
            },
            "registry": {"html": html_name, "attempted": False, "published": False},
            "owned_logo": None,
        }

    def _write_journal(self, record, *, raw=None, temporary=False):
        root = Path(dlms._quiz_publication_staging_root())
        root.mkdir(parents=True, exist_ok=True)
        suffix = ".json.tmp" if temporary else ".json"
        path = root / f"publication_{record['publication_id']}{suffix}"
        if raw is None:
            path.write_text(json.dumps(record), encoding="utf-8")
        else:
            path.write_text(raw, encoding="utf-8")
        return path

    def test_malformed_and_unsafe_journals_are_left_for_inspection(self):
        outside = Path(_TEMP.name).parent / "dlms-publication-protected.txt"
        outside.write_text("protected", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        cases = []

        malformed = self._journal_record("1" * 32)
        cases.append((malformed, "{not-json", None))
        unsupported = self._journal_record("2" * 32)
        unsupported["schema_version"] = 999
        cases.append((unsupported, None, None))
        traversal = self._journal_record("3" * 32)
        traversal["stage_dir"] = "../escape"
        cases.append((traversal, None, None))
        absolute = self._journal_record("4" * 32)
        absolute["artifacts"]["json"]["name"] = str(outside)
        cases.append((absolute, None, None))

        for record, raw, _ in cases:
            with self.subTest(publication_id=record["publication_id"]):
                self._reset_runtime()
                path = self._write_journal(record, raw=raw)
                report = dlms.reconcile_quiz_publications()
                self.assertEqual(1, report["unsafe"])
                self.assertTrue(path.exists())
                self.assertEqual("protected", outside.read_text(encoding="utf-8"))
                self.assertEqual([], self._db_quiz_ids())
                self.assertEqual([], dlms.load_registry())

    def test_symlink_escape_journal_is_never_followed(self):
        record = self._journal_record("5" * 32)
        outside = Path(_TEMP.name).parent / "dlms-publication-symlink-target.txt"
        outside.write_text("protected", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        target = Path(dlms.DATA_FOLDER) / record["artifacts"]["json"]["name"]
        target.symlink_to(outside)
        path = self._write_journal(record)
        report = dlms.reconcile_quiz_publications()
        self.assertEqual(1, report["unsafe"])
        self.assertTrue(path.exists())
        self.assertTrue(target.is_symlink())
        self.assertEqual("protected", outside.read_text(encoding="utf-8"))

    def test_nonexistent_db_and_missing_promoted_artifacts_cleanup_safely(self):
        record = self._journal_record("6" * 32)
        record["state"] = "artifacts_promoted"
        record["quiz"]["id"] = 999999
        record["artifacts"]["json"].update(attempted=True, promoted=True)
        record["artifacts"]["html"].update(attempted=True, promoted=True)
        self._write_journal(record)
        report = dlms.reconcile_quiz_publications()
        self.assertEqual(1, report["rolled_back"])
        self.assertEqual([], self._journal_files())
        self.assertEqual([], self._db_quiz_ids())

    def test_duplicate_temp_journal_is_cleaned_with_canonical_record(self):
        record = self._journal_record("7" * 32)
        canonical = self._write_journal(record)
        temporary = self._write_journal(record, temporary=True)
        self.assertTrue(canonical.exists() and temporary.exists())
        report = dlms.reconcile_quiz_publications()
        self.assertEqual(1, report["processed"])
        self.assertEqual(1, report["rolled_back"])
        self.assertFalse(canonical.exists())
        self.assertFalse(temporary.exists())

    def test_empty_root_and_startup_wrapper_are_safe(self):
        root = Path(dlms._quiz_publication_staging_root())
        root.mkdir(parents=True, exist_ok=True)
        self.assertEqual(0, dlms.reconcile_quiz_publications()["processed"])
        with mock.patch.object(
            dlms, "reconcile_quiz_publications", return_value={"processed": 0}
        ) as reconcile:
            result = dlms._run_quiz_publication_startup_reconciliation()
        reconcile.assert_called_once_with()
        self.assertEqual({"processed": 0}, result)

    def test_unverified_data_root_skips_reconciliation_without_deletion(self):
        record = self._journal_record("8" * 32)
        path = self._write_journal(record)
        with mock.patch.object(dlms, "_read_data_root_marker", return_value=None):
            report = dlms.reconcile_quiz_publications()
        self.assertEqual(0, report["processed"])
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
