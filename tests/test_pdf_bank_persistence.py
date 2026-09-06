"""Characterization coverage for Smart PDF draft and bank persistence."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_TEMP = tempfile.TemporaryDirectory(prefix="dlms-pdf-persistence-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms


class PDFPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlms-pdf-repository-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.drafts = self.root / "drafts"
        self.questions = self.root / "questions"
        self.terms = self.root / "terms"
        self.path_patches = [
            mock.patch.object(dlms, "PDF_IMPORT_DRAFT_FOLDER", str(self.drafts)),
            mock.patch.object(dlms, "PDF_QUESTION_BANK_FOLDER", str(self.questions)),
            mock.patch.object(dlms, "PDF_TERMINOLOGY_BANK_FOLDER", str(self.terms)),
        ]
        for patcher in self.path_patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_safe_ids_preserve_legacy_sanitizing_and_length_behavior(self):
        long_id = "x" * 100
        for helper in (
            dlms._pdf_import_safe_id,
            dlms._pdf_bank_safe_id,
            dlms._pdf_term_bank_safe_id,
        ):
            with self.subTest(helper=helper.__name__):
                self.assertEqual("BankNamejson", helper("../../Bank Name!.json"))
                self.assertEqual("x" * 80, helper(long_id))
                self.assertEqual("", helper(None))

    def test_paths_use_live_folders_and_keep_sanitized_ids_inside_them(self):
        cases = (
            (dlms._pdf_import_draft_path, self.drafts, "Invalid PDF import draft id"),
            (dlms._pdf_bank_path, self.questions, "Invalid PDF question-bank id"),
            (dlms._pdf_term_bank_path, self.terms, "Invalid PDF terminology-bank id"),
        )
        for helper, folder, message in cases:
            with self.subTest(helper=helper.__name__):
                self.assertEqual(str(folder / "escape.json"), helper("../../escape"))
                with self.assertRaisesRegex(ValueError, message):
                    helper("../../")

    def test_draft_save_load_round_trip_preserves_format_and_unknown_fields(self):
        draft = {
            "id": "legacy_draft",
            "document_type": "question_bank",
            "questions": [],
            "unknown": {"café": "東京"},
        }

        dlms._save_pdf_import_draft(draft)

        path = self.drafts / "legacy_draft.json"
        self.assertEqual(draft, dlms._load_pdf_import_draft("legacy_draft"))
        text = path.read_text(encoding="utf-8")
        self.assertIn('  "document_type": "question_bank"', text)
        self.assertIn('"café": "東京"', text)
        self.assertFalse(text.endswith("\n"))

    def test_draft_legacy_roots_and_failures_keep_existing_semantics(self):
        self.drafts.mkdir()
        (self.drafts / "null.json").write_text("null", encoding="utf-8")
        (self.drafts / "list.json").write_text('[{"legacy": true}]', encoding="utf-8")
        (self.drafts / "broken.json").write_text("{broken", encoding="utf-8")

        self.assertEqual({}, dlms._load_pdf_import_draft("null"))
        self.assertEqual([{"legacy": True}], dlms._load_pdf_import_draft("list"))
        with self.assertRaises(json.JSONDecodeError):
            dlms._load_pdf_import_draft("broken")
        with self.assertRaisesRegex(FileNotFoundError, "PDF import draft not found"):
            dlms._load_pdf_import_draft("missing")
        self.assertFalse((self.drafts / "broken.json.corrupt").exists())

    def test_draft_save_remains_non_atomic_and_requires_an_id(self):
        with mock.patch.object(dlms, "_atomic_write_json") as atomic_write:
            dlms._save_pdf_import_draft({"id": "plain", "questions": []})
        atomic_write.assert_not_called()

        with self.assertRaisesRegex(ValueError, "PDF import draft is missing an id"):
            dlms._save_pdf_import_draft({"id": "../../", "questions": []})

    def test_question_bank_atomic_interception_and_timestamp_mutation(self):
        bank = {"id": "questions", "questions": [], "unknown": "preserved"}
        expected_path = str(self.questions / "questions.json")

        with mock.patch.object(dlms, "datetime") as clock, mock.patch.object(
            dlms, "_atomic_write_json"
        ) as atomic_write:
            clock.now.return_value.isoformat.return_value = "2026-09-06T14:00:00"
            result = dlms._save_pdf_question_bank(bank)

        self.assertIsNone(result)
        self.assertEqual("2026-09-06T14:00:00", bank["updated_at"])
        atomic_write.assert_called_once_with(
            expected_path,
            bank,
            ensure_ascii=False,
            expected_type=dict,
        )

    def test_terminology_bank_atomic_interception_and_timestamp_mutation(self):
        bank = {"id": "terms", "terms": [], "unknown": "preserved"}
        expected_path = str(self.terms / "terms.json")

        with mock.patch.object(dlms, "datetime") as clock, mock.patch.object(
            dlms, "_atomic_write_json"
        ) as atomic_write:
            clock.now.return_value.isoformat.return_value = "2026-09-06T14:01:00"
            result = dlms._save_pdf_terminology_bank(bank)

        self.assertIsNone(result)
        self.assertEqual("2026-09-06T14:01:00", bank["updated_at"])
        atomic_write.assert_called_once_with(
            expected_path,
            bank,
            ensure_ascii=False,
            expected_type=dict,
        )

    def test_bank_round_trips_preserve_unknown_and_selection_metadata(self):
        question_bank = {
            "id": "questions",
            "title": "Café Questions",
            "questions": [{"number": 2, "active": False}, {"number": 1}],
            "used_question_numbers": [2, 2, 7],
            "generated_quizzes": ["one.html"],
            "unknown": {"source": "東京"},
        }
        term_bank = {
            "id": "terms",
            "title": "Café Terms",
            "terms": [{"number": 2, "active": False}, {"number": 1}],
            "used_term_numbers": [1, 1, 4],
            "generated_quizzes": ["terms.html"],
            "unknown": {"source": "Zürich"},
        }

        dlms._save_pdf_question_bank(question_bank)
        dlms._save_pdf_terminology_bank(term_bank)

        self.assertEqual(question_bank, dlms._load_pdf_question_bank("questions"))
        self.assertEqual(term_bank, dlms._load_pdf_terminology_bank("terms"))
        self.assertIn("Café Questions", (self.questions / "questions.json").read_text(encoding="utf-8"))
        self.assertFalse((self.questions / "questions.json").read_text(encoding="utf-8").endswith("\n"))

    def test_bank_load_validation_and_legacy_forms_are_unchanged(self):
        self.questions.mkdir()
        self.terms.mkdir()
        (self.questions / "legacy.json").write_text('{"questions": [], "legacy": 1}', encoding="utf-8")
        (self.terms / "legacy.json").write_text('{"terms": [], "legacy": 1}', encoding="utf-8")
        (self.questions / "missing.json").write_text("{}", encoding="utf-8")
        (self.terms / "missing.json").write_text("{}", encoding="utf-8")
        (self.questions / "broken.json").write_text("{broken", encoding="utf-8")
        (self.terms / "broken.json").write_text("{broken", encoding="utf-8")

        self.assertEqual({"questions": [], "legacy": 1}, dlms._load_pdf_question_bank("legacy"))
        self.assertEqual({"terms": [], "legacy": 1}, dlms._load_pdf_terminology_bank("legacy"))
        with self.assertRaisesRegex(ValueError, "PDF question bank is malformed"):
            dlms._load_pdf_question_bank("missing")
        with self.assertRaisesRegex(ValueError, "PDF terminology bank is malformed"):
            dlms._load_pdf_terminology_bank("missing")
        with self.assertRaises(json.JSONDecodeError):
            dlms._load_pdf_question_bank("broken")
        with self.assertRaises(json.JSONDecodeError):
            dlms._load_pdf_terminology_bank("broken")
        with self.assertRaisesRegex(FileNotFoundError, "PDF question bank not found"):
            dlms._load_pdf_question_bank("absent")
        with self.assertRaisesRegex(FileNotFoundError, "PDF terminology bank not found"):
            dlms._load_pdf_terminology_bank("absent")

    def test_question_bank_listing_preserves_filename_order_defaults_and_counts(self):
        self.questions.mkdir()
        (self.questions / "b.json").write_text(json.dumps({
            "id": "bank-b", "title": "Second", "questions": [{"active": False}, {}],
            "used_question_numbers": [1, 1, 2], "generated_quizzes": [1], "unknown": True,
        }), encoding="utf-8")
        (self.questions / "a.json").write_text('{"questions": []}', encoding="utf-8")
        (self.questions / "broken.json").write_text("{broken", encoding="utf-8")
        (self.questions / "ignored.txt").write_text("ignored", encoding="utf-8")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            banks = dlms._list_pdf_question_banks()

        self.assertEqual(["a", "bank-b"], [bank["id"] for bank in banks])
        self.assertEqual({
            "id": "a", "title": "PDF Question Bank", "source_name": "",
            "question_count": 0, "active_count": 0, "used_count": 0,
            "generated_count": 0, "created_at": "", "updated_at": "",
        }, banks[0])
        self.assertEqual(2, banks[1]["question_count"])
        self.assertEqual(1, banks[1]["active_count"])
        self.assertEqual(2, banks[1]["used_count"])
        self.assertIn("[PDF BANKS] Skipping invalid bank 'broken.json'", output.getvalue())

    def test_terminology_bank_listing_preserves_filename_order_defaults_and_counts(self):
        self.terms.mkdir()
        (self.terms / "b.json").write_text(json.dumps({
            "id": "term-b", "title": "Second", "terms": [{"active": False}, {}],
            "used_term_numbers": [1, 1, 2], "generated_quizzes": [1],
        }), encoding="utf-8")
        (self.terms / "a.json").write_text('{"terms": []}', encoding="utf-8")
        (self.terms / "broken.json").write_text("{broken", encoding="utf-8")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            banks = dlms._list_pdf_terminology_banks()

        self.assertEqual(["a", "term-b"], [bank["id"] for bank in banks])
        self.assertEqual("terminology", banks[0]["kind"])
        self.assertEqual("PDF Terminology Bank", banks[0]["title"])
        self.assertEqual(2, banks[1]["term_count"])
        self.assertEqual(1, banks[1]["active_count"])
        self.assertEqual(2, banks[1]["used_count"])
        self.assertIn("[PDF TERMS] Skipping invalid bank 'broken.json'", output.getvalue())

    def test_bank_deletion_returns_stripped_title_and_removes_exact_file(self):
        self.questions.mkdir()
        self.terms.mkdir()
        question_path = self.questions / "questions.json"
        term_path = self.terms / "terms.json"
        question_path.write_text('{"title": " Questions ", "questions": []}', encoding="utf-8")
        term_path.write_text('{"title": " Terms ", "terms": []}', encoding="utf-8")

        self.assertEqual("Questions", dlms._delete_pdf_question_bank("questions"))
        self.assertEqual("Terms", dlms._delete_pdf_terminology_bank("terms"))
        self.assertFalse(question_path.exists())
        self.assertFalse(term_path.exists())

    def test_invalid_bank_save_does_not_call_atomic_writer(self):
        with mock.patch.object(dlms, "_atomic_write_json") as atomic_write:
            with self.assertRaisesRegex(ValueError, "Question bank is missing an id"):
                dlms._save_pdf_question_bank({"id": "../../", "questions": []})
            with self.assertRaisesRegex(ValueError, "Terminology bank is missing an id"):
                dlms._save_pdf_terminology_bank({"id": "../../", "terms": []})
        atomic_write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
