"""Golden contracts for Law parsing, filenames, lookup, and text export."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services import law as law_service


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 6, 14, 5, 7, tzinfo=tz)


class LawDomainCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-law-domain-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cases = self.root / "cases"
        self.imports = self.root / "imports"
        self.registry = self.root / "law.json"
        self.cases.mkdir()
        self.imports.mkdir()
        patcher = mock.patch.multiple(
            dlms,
            LAW_CASES_FOLDER=str(self.cases),
            LAW_IMPORTS_FOLDER=str(self.imports),
            LAW_REGISTRY=str(self.registry),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_packet_and_socratic_parsers_preserve_exact_golden_shapes(self):
        packet = """Sources Used
Reporter café.

1. Case Brief
Full case name and citation: Café v. Thé
Wrapped fact line.

2. Socratic Review
1. **What happened?**
continued
2) What rule controls?

2A. Socratic Answer Key
1. First answer.

3. IRAC Drill
Issue text.

4. Rule Flashcards
Q: Rule?
A: Rule.
"""

        self.assertEqual(
            [
                {
                    "key": "sources_used",
                    "title": "Sources Used",
                    "content": "Reporter café.",
                    "char_count": 14,
                    "line_count": 1,
                },
                {
                    "key": "case_brief",
                    "title": "1. Case Brief",
                    "content": "Full case name and citation: Café v. Thé\nWrapped fact line.",
                    "char_count": 59,
                    "line_count": 2,
                },
                {
                    "key": "socratic_review",
                    "title": "2. Socratic Review",
                    "content": "1. **What happened?**\ncontinued\n2) What rule controls?",
                    "char_count": 54,
                    "line_count": 3,
                },
                {
                    "key": "socratic_answer_key",
                    "title": "2A. Socratic Answer Key",
                    "content": "1. First answer.",
                    "char_count": 16,
                    "line_count": 1,
                },
                {
                    "key": "irac_drill",
                    "title": "3. IRAC Drill",
                    "content": "Issue text.",
                    "char_count": 11,
                    "line_count": 1,
                },
                {
                    "key": "rule_flashcards",
                    "title": "4. Rule Flashcards",
                    "content": "Q: Rule?\nA: Rule.",
                    "char_count": 17,
                    "line_count": 2,
                },
            ],
            dlms.parse_law_packet_sections(packet),
        )
        self.assertEqual(
            [
                {
                    "id": "q1",
                    "number": "1",
                    "text": "What happened?**\ncontinued",
                },
                {"id": "q2", "number": "2", "text": "What rule controls?"},
            ],
            dlms.parse_socratic_questions(
                "1. **What happened?**\ncontinued\n2) What rule controls?"
            ),
        )
        self.assertEqual(
            [
                {"id": "q1", "number": "1", "text": "First bullet?"},
                {"id": "q2", "number": "2", "text": "Second bullet?"},
            ],
            dlms.parse_socratic_questions("- First bullet?\n* Second bullet?"),
        )

    def test_slug_title_and_import_filename_legacy_rules_are_unchanged(self):
        self.assertEqual("hadley_v_baxendale", dlms.make_law_case_slug("Hadley v. Baxendale"))
        self.assertEqual("a_b_v_c", dlms.make_law_case_slug("A/B vs. C"))
        self.assertEqual("r_sum_case", dlms.make_law_case_slug("résumé — Case"))
        self.assertEqual("untitled_case", dlms.make_law_case_slug(""))

        import_name = "law_import_20260906_120000_Hadley_v._Baxendale.txt"
        self.assertEqual(
            "Hadley_v._Baxendale",
            dlms.extract_law_slug_from_import_filename(import_name),
        )
        self.assertEqual("", dlms.extract_law_slug_from_import_filename("case.txt"))
        self.assertEqual("law_import_resume.TXT", dlms.safe_law_import_filename("../law import résumé.TXT"))
        self.assertEqual("nested_name.txt", dlms.safe_law_import_filename("nested/name.txt"))
        self.assertEqual("", dlms.safe_law_import_filename("../../case.json"))

        self.assertEqual(
            "Café v. Thé",
            dlms.extract_law_case_title(
                "Case Name: Café v. Thé\n1. Case Brief\nFacts", "fallback.txt"
            ),
        )
        self.assertEqual(
            "Case Review 20260906 120000 fallback",
            dlms.extract_law_case_title(
                "No recognized title", "law_import_20260906_120000_fallback.txt"
            ),
        )

    def test_canonical_import_and_case_id_contracts_are_exact_and_addressable(self):
        canonical_imports = (
            "law_import_20260906_140507_hadley_v_baxendale.txt",
            "saved-packet.txt",
        )
        for filename in canonical_imports:
            with self.subTest(canonical_import=filename):
                self.assertEqual(filename, dlms.canonical_law_import_filename(filename))

        for filename in (
            "nested/name.txt",
            "nested\\name.txt",
            "nested name.txt",
            "nested?name.txt",
            "nested#name.txt",
            "nested%name.txt",
            'nested"name.txt',
            "../nested_name.txt",
            "résumé.txt",
            " saved.txt",
            "saved.txt ",
            "saved.json",
            "UPPER.TXT",
            "",
        ):
            with self.subTest(noncanonical_import=filename):
                self.assertEqual("", dlms.canonical_law_import_filename(filename))

        self.assertEqual("Cafe_packet.txt", dlms.safe_law_import_filename("Café packet.txt"))
        self.assertEqual(
            "Cafe_packet.txt", dlms.canonical_law_import_filename("Cafe_packet.txt")
        )

        for case_id in (
            "law_case_20260906_140507_hadley_v_baxendale",
            "law-case-1",
            "case_1",
        ):
            with self.subTest(canonical_case_id=case_id):
                self.assertEqual(case_id, dlms.canonical_law_case_id(case_id))

        for case_id in (
            "nested/case",
            "nested\\case",
            "Case-1",
            "case 1",
            "case.1",
            "case%2f1",
            "résumé",
            "-case",
            "_case",
            "",
            None,
        ):
            with self.subTest(noncanonical_case_id=case_id):
                self.assertEqual("", dlms.canonical_law_case_id(case_id))

    def test_raw_packet_save_uses_live_app_path_and_exact_filename_convention(self):
        with mock.patch.object(dlms, "datetime", _FrozenDateTime):
            saved = dlms.save_law_raw_packet("Law packet café", "hadley_v_baxendale")

        self.assertEqual(
            "law_import_20260906_140507_hadley_v_baxendale.txt", saved
        )
        self.assertEqual(
            "Law packet café", (self.imports / saved).read_text(encoding="utf-8")
        )

    def test_raw_import_path_resolution_requires_exact_stored_spelling(self):
        stored = self.imports / "Exact_Name.txt"
        stored.write_text("packet", encoding="utf-8")

        self.assertEqual(
            str(stored),
            law_service.resolve_law_raw_import_path(
                str(self.imports), "Exact_Name.txt"
            ),
        )
        self.assertIsNone(
            law_service.resolve_law_raw_import_path(
                str(self.imports), "exact_name.txt"
            )
        )
        self.assertIsNone(
            law_service.resolve_law_raw_import_path(
                str(self.imports), "missing.txt"
            )
        )

    def test_case_lookup_resolves_live_app_registry_loader(self):
        expected = {"id": "target", "title": "Live patched case"}
        with mock.patch.object(
            dlms,
            "load_law_registry",
            return_value={"cases": [{"id": "other"}, expected]},
        ) as loader:
            self.assertIs(expected, dlms.get_law_case_by_id("target"))
        loader.assert_called_once_with()

        for invalid in ("nested/case", "Case-1", "case 1"):
            with self.subTest(invalid=invalid), mock.patch.object(
                dlms, "load_law_registry"
            ) as invalid_loader:
                self.assertIsNone(dlms.get_law_case_by_id(invalid))
                invalid_loader.assert_not_called()

    def test_law_text_export_preserves_exact_content_and_filename(self):
        case_id = "law-case-1"
        case_file = f"{case_id}.json"
        case_data = {
            "id": case_id,
            "title": "Café / Palsgraf",
            "course": "Torts",
            "source_import": "source.txt",
            "created_at": "2026-09-01T10:00:00",
            "updated_at": "2026-09-02T11:00:00",
            "sections": {
                "case_brief": "  Brief text.  ",
                "socratic_review": "",
                "socratic_answer_key": "Answer key.",
                "irac_drill": "IRAC text.",
                "rule_flashcards": "",
            },
            "student_notes": "  My notes.  ",
        }
        self.registry.write_text(
            json.dumps(
                {
                    "version": "1",
                    "folders": ["Torts"],
                    "cases": [
                        {
                            "id": case_id,
                            "title": case_data["title"],
                            "course": "Torts",
                            "file": case_file,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.cases / case_file).write_text(json.dumps(case_data), encoding="utf-8")

        with mock.patch.object(dlms, "datetime", _FrozenDateTime):
            response = dlms.app.test_client().get(f"/law/cases/{case_id}/export.txt")

        self.assertEqual(200, response.status_code)
        self.assertEqual("text/plain; charset=utf-8", response.content_type)
        self.assertEqual(
            "attachment; filename=dlms_law_case_Caf_Palsgraf.txt",
            response.headers["Content-Disposition"],
        )
        self.assertEqual(
            "\n".join(
                [
                    "# DLMS Law Case Review Export",
                    f"# Exported from DLMS v{dlms.APP_VERSION}",
                    "# Exported on: 2026-09-06 14:05:07",
                    "# Format: DLMS Law Study text",
                    "",
                    "=" * 60,
                    "CASE REVIEW: Café / Palsgraf",
                    "COURSE: Torts",
                    "SOURCE IMPORT: source.txt",
                    "CREATED: 2026-09-01T10:00:00",
                    "UPDATED: 2026-09-02T11:00:00",
                    "=" * 60,
                    "",
                    "1. Case Brief",
                    "-------------",
                    "Brief text.",
                    "",
                    "",
                    "2A. Socratic Answer Key",
                    "-----------------------",
                    "Answer key.",
                    "",
                    "",
                    "3. IRAC Drill",
                    "-------------",
                    "IRAC text.",
                    "",
                    "",
                    "Student Notes",
                    "-------------",
                    "My notes.",
                    "",
                    "",
                    "Verification Reminder",
                    "---------------------",
                    "Verify citations, holdings, quotations, and procedural history against the original opinion or an approved legal research source.",
                    "",
                ]
            ),
            response.get_data(as_text=True),
        )

    def test_law_text_export_includes_complete_authored_review_in_stable_order(self):
        case_data = {
            "title": "Unicode Review",
            "course": "Torts",
            "source_import": "source.txt",
            "created_at": "2026-09-01T10:00:00",
            "updated_at": "2026-09-02T11:00:00",
            "sources_used": " Reporter Ω\nTreatise & notes ",
            "sections": {
                "case_brief": "Brief text.",
                "socratic_review": (
                    "2. **Second question?**\n"
                    "1. First question?"
                ),
                "socratic_answer_key": "Answer key.",
                "irac_drill": "IRAC drill.",
                "rule_flashcards": "Flashcards.",
            },
            "socratic_student_answers": {
                "z-orphan": " Last preserved response. ",
                "q1": "First answer.",
                "q2": "Réponse café.\nSecond line.",
                "a-orphan": "First preserved response.",
                "empty": "   ",
            },
            "irac_student_response": {
                "conclusion": "Conclusion text.",
                "analysis": "Analyse café.\nApplication line.",
                "rule": "Rule text.",
                "issue": "Issue text.",
            },
            "student_notes": "Student notes stay near the end.",
        }

        export_text, filename = law_service.build_law_case_export(
            case_data,
            "law-case-unicode",
            app_version="test",
            exported_on="2026-09-08 12:00:00",
            parse_socratic_questions=dlms.parse_socratic_questions,
        )

        self.assertEqual("dlms_law_case_Unicode_Review.txt", filename)
        sources_at = export_text.index("Sources Used\n------------")
        imported_at = export_text.index("1. Case Brief\n-------------")
        responses_at = export_text.index(
            "Student Socratic Responses\n--------------------------"
        )
        irac_at = export_text.index(
            "Student IRAC Response\n---------------------"
        )
        notes_at = export_text.index("Student Notes\n-------------")
        reminder_at = export_text.index(
            "Verification Reminder\n---------------------"
        )
        self.assertLess(sources_at, imported_at)
        self.assertLess(imported_at, responses_at)
        self.assertLess(responses_at, irac_at)
        self.assertLess(irac_at, notes_at)
        self.assertLess(notes_at, reminder_at)
        self.assertIn("Reporter Ω\nTreatise & notes", export_text)

        response_block = export_text[responses_at:irac_at]
        expected_response_fragments = (
            "Question 2: Second question?",
            "Réponse café.\nSecond line.",
            "Question 1: First question?",
            "First answer.",
            "Saved Response (a-orphan)",
            "First preserved response.",
            "Saved Response (z-orphan)",
            "Last preserved response.",
        )
        response_positions = [
            response_block.index(fragment) for fragment in expected_response_fragments
        ]
        self.assertEqual(sorted(response_positions), response_positions)
        self.assertNotIn("Saved Response (empty)", response_block)

        irac_block = export_text[irac_at:notes_at]
        expected_irac_fragments = (
            "Issue:\nIssue text.",
            "Rule:\nRule text.",
            "Analysis/Application:\nAnalyse café.\nApplication line.",
            "Conclusion:\nConclusion text.",
        )
        irac_positions = [
            irac_block.index(fragment) for fragment in expected_irac_fragments
        ]
        self.assertEqual(sorted(irac_positions), irac_positions)
        self.assertTrue(
            export_text.endswith(
                "Verify citations, holdings, quotations, and procedural history "
                "against the original opinion or an approved legal research source.\n"
            )
        )

    def test_law_text_export_omits_empty_additional_sections(self):
        case_data = {
            "title": "Empty Review",
            "sections": {},
            "sources_used": "  \n ",
            "socratic_student_answers": {"q1": "  "},
            "irac_student_response": {
                "issue": " ",
                "rule": "",
                "analysis": "\n",
                "conclusion": "  ",
            },
        }

        export_text, _filename = law_service.build_law_case_export(
            case_data,
            "empty-review",
            app_version="test",
            exported_on="2026-09-08 12:00:00",
            parse_socratic_questions=dlms.parse_socratic_questions,
        )
        legacy_text, _legacy_filename = law_service.build_law_case_export(
            {"title": "Empty Review", "sections": {}},
            "empty-review",
            app_version="test",
            exported_on="2026-09-08 12:00:00",
            parse_socratic_questions=dlms.parse_socratic_questions,
        )

        self.assertEqual(legacy_text, export_text)
        self.assertNotIn("Sources Used\n------------", export_text)
        self.assertNotIn("Student Socratic Responses", export_text)
        self.assertNotIn("Student IRAC Response", export_text)


if __name__ == "__main__":
    unittest.main()
