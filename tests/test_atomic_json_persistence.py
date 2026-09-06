"""DLMS-084 regression coverage for durable user-owned JSON persistence."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


class AtomicJsonPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-atomic-json-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_successful_atomic_replacement(self):
        path = self.root / "settings.json"
        original = {"title": "Before"}
        replacement = {"title": "After", "enabled": True}
        path.write_text(json.dumps(original), encoding="utf-8")
        real_replace = os.replace

        with mock.patch.object(dlms.os, "replace", wraps=real_replace) as replace_mock:
            dlms._atomic_write_json(str(path), replacement, expected_type=dict)

        self.assertEqual(replacement, json.loads(path.read_text(encoding="utf-8")))
        replace_mock.assert_called_once()
        temporary_path, destination = replace_mock.call_args.args
        self.assertEqual(str(path), destination)
        self.assertEqual(path.parent, Path(temporary_path).parent)
        self.assertFalse(Path(temporary_path).exists())

    def test_failed_atomic_replacement_keeps_live_file_and_cleans_temporary_file(self):
        path = self.root / "settings.json"
        original_text = json.dumps({"title": "Recoverable"}, indent=2)
        path.write_text(original_text, encoding="utf-8")

        with mock.patch.object(dlms.os, "replace", side_effect=OSError("simulated replacement failure")):
            with self.assertRaisesRegex(OSError, "simulated replacement failure"):
                dlms._atomic_write_json(str(path), {"title": "Lost"}, expected_type=dict)

        self.assertEqual(original_text, path.read_text(encoding="utf-8"))
        self.assertEqual([], list(self.root.glob(".settings.json.*.tmp")))

    def test_write_and_flush_failures_keep_live_file_and_clean_temporary_file(self):
        real_fdopen = os.fdopen

        class FaultingTemporaryFile:
            def __init__(self, wrapped, operation):
                self.wrapped = wrapped
                self.operation = operation

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                self.wrapped.close()

            def write(self, value):
                if self.operation == "write":
                    raise OSError("simulated write failure")
                return self.wrapped.write(value)

            def flush(self):
                if self.operation == "flush":
                    raise OSError("simulated flush failure")
                return self.wrapped.flush()

            def fileno(self):
                return self.wrapped.fileno()

        for operation in ("write", "flush"):
            with self.subTest(operation=operation):
                path = self.root / f"{operation}.json"
                original_text = json.dumps({"title": "Recoverable"}, indent=2)
                path.write_text(original_text, encoding="utf-8")

                def faulting_fdopen(*args, **kwargs):
                    return FaultingTemporaryFile(
                        real_fdopen(*args, **kwargs), operation
                    )

                with mock.patch.object(dlms.os, "fdopen", side_effect=faulting_fdopen):
                    with self.assertRaisesRegex(OSError, f"simulated {operation} failure"):
                        dlms._atomic_write_json(
                            str(path), {"title": "Lost"}, expected_type=dict
                        )

                self.assertEqual(original_text, path.read_text(encoding="utf-8"))
                self.assertEqual([], list(self.root.glob(f".{operation}.json.*.tmp")))

    def test_file_fsync_failure_keeps_live_file_and_cleans_temporary_file(self):
        path = self.root / "fsync.json"
        original_text = json.dumps({"title": "Recoverable"}, indent=2)
        path.write_text(original_text, encoding="utf-8")

        with mock.patch.object(
            dlms.os, "fsync", side_effect=OSError("simulated file fsync failure")
        ):
            with self.assertRaisesRegex(OSError, "simulated file fsync failure"):
                dlms._atomic_write_json(
                    str(path), {"title": "Lost"}, expected_type=dict
                )

        self.assertEqual(original_text, path.read_text(encoding="utf-8"))
        self.assertEqual([], list(self.root.glob(".fsync.json.*.tmp")))

    def test_directory_fsync_failure_is_best_effort_after_successful_replace(self):
        path = self.root / "directory-fsync.json"
        replacement = {"title": "Durable enough"}
        real_fsync = os.fsync

        def fail_only_for_directory(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("simulated directory fsync failure")
            return real_fsync(descriptor)

        with mock.patch.object(dlms.os, "fsync", side_effect=fail_only_for_directory):
            dlms._atomic_write_json(str(path), replacement, expected_type=dict)

        self.assertEqual(replacement, json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual([], list(self.root.glob(".directory-fsync.json.*.tmp")))

    def test_expected_root_type_failure_does_not_replace_live_file(self):
        path = self.root / "root-type.json"
        original_text = json.dumps({"title": "Recoverable"}, indent=2)
        path.write_text(original_text, encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "JSON payload must contain dict"):
            dlms._atomic_write_json(str(path), ["wrong root"], expected_type=dict)

        self.assertEqual(original_text, path.read_text(encoding="utf-8"))
        self.assertEqual([], list(self.root.glob(".root-type.json.*.tmp")))

    def test_non_ascii_output_and_requested_formatting_are_preserved(self):
        path = self.root / "unicode.json"
        payload = {"title": "Café 医学", "enabled": True}

        dlms._atomic_write_json(
            str(path), payload, indent=4, ensure_ascii=False, expected_type=dict
        )

        serialized = path.read_text(encoding="utf-8")
        self.assertIn('    "title": "Café 医学"', serialized)
        self.assertNotIn("\\u00e9", serialized)
        self.assertEqual(payload, json.loads(serialized))
        self.assertFalse(serialized.endswith("\n"))

    def test_failed_corruption_copy_replace_preserves_original_and_cleans_temp(self):
        path = self.root / "malformed.json"
        malformed = b'{"title": "unterminated"'
        path.write_bytes(malformed)

        with mock.patch.object(
            dlms.os, "replace", side_effect=OSError("simulated corruption-copy failure")
        ):
            with self.assertRaisesRegex(OSError, "simulated corruption-copy failure"):
                dlms._atomic_write_json(
                    str(path), {"title": "Replacement"}, expected_type=dict
                )

        self.assertEqual(malformed, path.read_bytes())
        self.assertFalse(Path(str(path) + ".corrupt").exists())
        self.assertEqual([], list(self.root.glob(".malformed.json.corrupt-*.tmp")))

    def test_malformed_portal_and_law_json_are_preserved_before_defaults_can_be_saved(self):
        config = self.root / "config"
        config.mkdir()
        portal_path = config / "portal.json"
        law_path = config / "law.json"
        first_portal_corruption = b'{"title": "unterminated"'
        latest_portal_corruption = b"{new malformed portal"
        law_corruption = (
            b'{"version":"1","cases":{"recoverable_case":"legacy value"},"folders":[]}'
        )
        portal_path.write_bytes(first_portal_corruption)
        law_path.write_bytes(law_corruption)

        with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal_path)), mock.patch.object(
            dlms, "LAW_REGISTRY", str(law_path)
        ):
            self.assertEqual("Training & Practice Center", dlms.load_portal_config()["title"])
            self.assertEqual([], dlms.load_law_registry()["cases"])
            self.assertEqual(first_portal_corruption, Path(str(portal_path) + ".corrupt").read_bytes())
            self.assertEqual(law_corruption, Path(str(law_path) + ".corrupt").read_bytes())

            # A later malformed live value rotates the single recovery copy;
            # saving defaults plus the requested change cannot destroy it.
            portal_path.write_bytes(latest_portal_corruption)
            dlms.save_portal_config("Recovered settings")

        self.assertEqual(latest_portal_corruption, Path(str(portal_path) + ".corrupt").read_bytes())
        self.assertEqual(
            [Path(str(portal_path) + ".corrupt")],
            list(config.glob("portal.json.corrupt*")),
        )
        self.assertEqual("Recovered settings", json.loads(portal_path.read_text(encoding="utf-8"))["title"])

    def test_existing_portal_law_and_pdf_formats_round_trip_unchanged(self):
        config = self.root / "config"
        portal_path = config / "portal.json"
        law_path = config / "law.json"
        question_folder = self.root / "pdf_question_banks"
        term_folder = self.root / "pdf_terminology_banks"

        with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal_path)), mock.patch.object(
            dlms, "LAW_REGISTRY", str(law_path)
        ), mock.patch.object(dlms, "PDF_QUESTION_BANK_FOLDER", str(question_folder)), mock.patch.object(
            dlms, "PDF_TERMINOLOGY_BANK_FOLDER", str(term_folder)
        ):
            dlms.save_portal_config("Compatible title", show_confidence=False)
            registry = dlms.load_law_registry()
            registry["folders"].append("Evidence")
            dlms.save_law_registry(registry)
            question_bank = {"id": "questions", "questions": [], "title": "Questions"}
            term_bank = {"id": "terms", "terms": [], "title": "Terms"}
            dlms._save_pdf_question_bank(question_bank)
            dlms._save_pdf_terminology_bank(term_bank)

            self.assertEqual("Compatible title", dlms.load_portal_config()["title"])
            self.assertIn("Evidence", dlms.load_law_registry()["folders"])
            self.assertEqual("Questions", dlms._load_pdf_question_bank("questions")["title"])
            self.assertEqual("Terms", dlms._load_pdf_terminology_bank("terms")["title"])


if __name__ == "__main__":
    unittest.main()
