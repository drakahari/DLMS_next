import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class AnkiLawSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cases_dir = Path(self.temp_dir.name, "cases")
        self.cases_dir.mkdir()
        self.registry = {
            "version": "1",
            "folders": ["Contracts"],
            "cases": [
                {
                    "id": "valid-aliases",
                    "title": "Valid aliases",
                    "course": "Contracts",
                    "file": "valid-aliases.json",
                },
                {
                    "id": "incomplete",
                    "title": "Incomplete cards",
                    "course": "Contracts",
                    "file": "incomplete.json",
                },
                {
                    "id": "missing",
                    "title": "Missing case data",
                    "course": "Contracts",
                    "file": "missing.json",
                },
                {
                    "id": "unreadable",
                    "title": "Unreadable case data",
                    "course": "Contracts",
                    "file": "unreadable.json",
                },
            ],
        }
        self._write_case(
            "valid-aliases.json",
            """
Front: Offer
Back: A manifestation of willingness to bargain.

Question: What supports a promise?
Answer: Consideration.

Q: What ends the power of acceptance?
A: Revocation, rejection, or lapse.
""",
        )
        self._write_case(
            "incomplete.json",
            """
Back: Orphaned answer.
Front: Missing answer.
Question: Replacement question that also has no answer.
""",
        )
        Path(self.cases_dir, "unreadable.json").mkdir()

        self.case_folder_patch = mock.patch.object(
            dlms, "LAW_CASES_FOLDER", str(self.cases_dir)
        )
        self.registry_patch = mock.patch.object(
            dlms,
            "load_law_registry",
            side_effect=lambda: copy.deepcopy(self.registry),
        )
        self.case_folder_patch.start()
        self.registry_patch.start()
        self.addCleanup(self.case_folder_patch.stop)
        self.addCleanup(self.registry_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def _write_case(self, filename, rule_flashcards):
        payload = {
            "id": Path(filename).stem,
            "title": Path(filename).stem,
            "course": "Contracts",
            "sections": {"rule_flashcards": rule_flashcards},
        }
        Path(self.cases_dir, filename).write_text(
            json.dumps(payload), encoding="utf-8"
        )

    @staticmethod
    def _summary_count(html):
        match = re.search(
            r"<span(?:\s+[^>]*)?>Law Flashcards</span>\s*<strong>(\d+)</strong>",
            html,
        )
        if not match:
            raise AssertionError("Rendered Law Flashcards summary count was missing")
        return int(match.group(1))

    def test_all_anki_pages_use_the_same_recognized_law_card_population(self):
        law_cases = dlms.get_anki_law_case_choices()
        counts = {case["id"]: case["card_count"] for case in law_cases}

        self.assertEqual(
            counts,
            {
                "valid-aliases": 3,
                "incomplete": 0,
                "missing": 0,
                "unreadable": 0,
            },
        )

        with mock.patch.object(dlms, "get_anki_quiz_choices", return_value=[]), \
             mock.patch.object(
                 dlms,
                 "get_anki_missed_summary",
                 return_value={
                     "total": 0,
                     "currently_weak": 0,
                     "recovered": 0,
                     "repeated": 0,
                     "once": 0,
                 },
             ), \
             mock.patch.object(dlms, "build_anki_rows_for_missed", return_value=[]):
            client = dlms.app.test_client()
            landing_html = client.get("/anki").get_data(as_text=True)
            law_html = client.get("/anki/law").get_data(as_text=True)
            custom_html = client.get("/anki/custom").get_data(as_text=True)

        expected_total = sum(counts.values())
        landing_total = self._summary_count(landing_html)
        direct_law_total = self._summary_count(law_html)
        custom_total = len(
            re.findall(r'<input\s+type="checkbox"\s+name="law_cards"', custom_html)
        )

        self.assertEqual(expected_total, 3)
        self.assertEqual(landing_total, expected_total)
        self.assertEqual(direct_law_total, expected_total)
        self.assertEqual(custom_total, expected_total)


if __name__ == "__main__":
    unittest.main()
