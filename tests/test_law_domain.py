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

    def test_raw_packet_save_uses_live_app_path_and_exact_filename_convention(self):
        with mock.patch.object(dlms, "datetime", _FrozenDateTime):
            saved = dlms.save_law_raw_packet("Law packet café", "hadley_v_baxendale")

        self.assertEqual(
            "law_import_20260906_140507_hadley_v_baxendale.txt", saved
        )
        self.assertEqual(
            "Law packet café", (self.imports / saved).read_text(encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
