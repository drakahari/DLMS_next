"""DLMS-084 regression coverage for durable user-owned JSON persistence."""

import json
import os
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
