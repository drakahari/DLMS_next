import unittest
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


class AnkiCustomDeckScalabilityTests(unittest.TestCase):
    def setUp(self):
        self.sources = {
            "quiz_groups": [
                {
                    "id": 101,
                    "title": "Network Fundamentals",
                    "cards": [
                        {"question_id": 1, "question_number": 1, "front": "First network question"},
                        {"question_id": 2, "question_number": 2, "front": "Second network question"},
                    ],
                },
                {
                    "id": 202,
                    "title": "Medical Terminology",
                    "cards": [
                        {"question_id": 7, "question_number": 1, "front": "Medical question"},
                    ],
                },
            ],
            "missed_cards": [
                {
                    "quiz_id": 101,
                    "question_id": 11,
                    "question_number": 1,
                    "quiz_title": "Network Fundamentals",
                    "front": "Missed network question",
                    "miss_count": 2,
                    "recovery_status": "currently_weak",
                },
                {
                    "quiz_id": 202,
                    "question_id": None,
                    "question_number": 4,
                    "quiz_title": "Medical Terminology",
                    "front": "Recovered medical question",
                    "miss_count": 1,
                    "recovery_status": "recovered",
                },
            ],
            "law_groups": [
                {
                    "id": "case-a",
                    "course": "Torts",
                    "title": "Palsgraf Review",
                    "cards": [
                        {"front": "Duty", "back": "Foreseeability"},
                        {"front": "Proximate cause", "back": "Scope of liability"},
                    ],
                },
                {
                    "id": "case-b",
                    "course": "Contracts",
                    "title": "Hadley Review",
                    "cards": [{"front": "Damages", "back": "Foreseeability"}],
                },
            ],
        }

    def _get_page(self):
        with mock.patch.object(dlms, "get_anki_custom_sources", return_value=self.sources):
            return dlms.app.test_client().get("/anki/custom").get_data(as_text=True)

    def test_quiz_filter_and_accordion_controls_are_accessible(self):
        html = self._get_page()

        self.assertIn('<label class="anki-custom-quiz-filter" for="ankiQuizFilter">', html)
        self.assertIn('type="search"', html)
        self.assertIn('id="ankiQuizFilter"', html)
        self.assertIn('aria-describedby="ankiQuizFilterStatus"', html)
        self.assertIn('id="ankiQuizFilterStatus" aria-live="polite">2 quizzes shown', html)
        self.assertIn('id="ankiExpandAllQuizzes" aria-controls="ankiQuizGroups"', html)
        self.assertIn('id="ankiCollapseAllQuizzes" aria-controls="ankiQuizGroups"', html)
        self.assertEqual(html.count("anki-custom-bulk-group anki-custom-quiz-group"), 2)
        self.assertEqual(html.count("data-anki-quiz-selection-count"), 2)
        self.assertEqual(html.count('data-anki-quiz-select-all aria-controls='), 2)
        self.assertEqual(html.count('data-anki-quiz-clear aria-controls='), 2)

    def test_per_quiz_bulk_actions_are_scoped_and_filter_does_not_expand(self):
        html = self._get_page()

        self.assertIn(
            "selectionGroup.querySelectorAll('input[type=\"checkbox\"]')",
            html,
        )
        self.assertIn("checkbox.name === selectionName", html)
        self.assertIn("groupSelections.forEach(checkbox => { checkbox.checked = true; })", html)
        self.assertIn("groupSelections.forEach(checkbox => { checkbox.checked = false; })", html)
        self.assertIn("updateCustomAnkiSelectionCount(selectionGroup)", html)
        self.assertIn("quizGroup.hidden = !matches", html)
        self.assertNotIn("quizGroup.open = matches", html)
        self.assertIn(
            "visibleCustomAnkiQuizGroups().forEach(quizGroup => { quizGroup.open = true; })",
            html,
        )
        self.assertIn(
            "visibleCustomAnkiQuizGroups().forEach(quizGroup => { quizGroup.open = false; })",
            html,
        )

    def test_non_quiz_bulk_controls_counts_and_law_filter_are_accessible(self):
        html = self._get_page()

        self.assertIn('<details open class="anki-custom-selection-group anki-custom-bulk-group anki-custom-performance-group"', html)
        self.assertIn('id="ankiPerformanceGroup"', html)
        self.assertIn('data-anki-selection-name="missed_cards"', html)
        self.assertIn('id="ankiPerformanceSelectionCount" data-anki-group-selection-count>0 of 2 selected', html)
        self.assertIn('aria-label="Performance History question selection controls"', html)
        self.assertIn('data-anki-group-select-all aria-controls="ankiPerformanceQuestions">Select All Questions', html)
        self.assertIn('data-anki-group-clear aria-controls="ankiPerformanceQuestions" disabled>Clear Performance Selection', html)

        self.assertIn('<label class="anki-custom-quiz-filter" for="ankiLawFilter">', html)
        self.assertIn('id="ankiLawFilter"', html)
        self.assertIn('aria-describedby="ankiLawFilterStatus"', html)
        self.assertIn('id="ankiLawFilterStatus" aria-live="polite">2 cases shown', html)
        self.assertIn('id="ankiExpandAllLawCases" aria-controls="ankiLawGroups"', html)
        self.assertIn('id="ankiCollapseAllLawCases" aria-controls="ankiLawGroups"', html)
        self.assertEqual(html.count("anki-custom-bulk-group anki-custom-law-group"), 2)
        self.assertEqual(html.count('data-anki-selection-name="law_cards"'), 2)
        self.assertIn('id="ankiLawSelectionCount1" data-anki-group-selection-count>0 of 2 selected', html)
        self.assertIn('id="ankiLawSelectionCount2" data-anki-group-selection-count>0 of 1 selected', html)
        self.assertIn("lawGroup.hidden = !matches", html)
        self.assertNotIn("lawGroup.open = matches", html)
        self.assertIn(
            "visibleCustomAnkiLawGroups().forEach(lawGroup => { lawGroup.open = true; })",
            html,
        )
        self.assertIn(
            "visibleCustomAnkiLawGroups().forEach(lawGroup => { lawGroup.open = false; })",
            html,
        )

    def test_performance_history_open_state_uses_guarded_local_storage(self):
        html = self._get_page()

        self.assertIn(
            'const ankiPerformanceOpenStateKey = "dlms.anki.custom.performanceHistory.openState.v1";',
            html,
        )
        self.assertIn(
            'JSON.parse(localStorage.getItem(ankiPerformanceOpenStateKey) || "null")',
            html,
        )
        self.assertIn('typeof savedState === "boolean" ? savedState : null', html)
        self.assertIn(
            "if (savedOpenState !== null) ankiPerformanceGroup.open = savedOpenState;",
            html,
        )
        self.assertIn('ankiPerformanceGroup.addEventListener("toggle"', html)
        self.assertIn("JSON.stringify(ankiPerformanceGroup.open)", html)

    def test_server_render_preserves_checked_questions_and_quiz_count(self):
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "get_anki_custom_sources", return_value=self.sources), \
             mock.patch.object(dlms, "build_custom_anki_rows", return_value=[]):
            response = client.post(
                "/anki/custom",
                data={
                    "csrf_token": csrf_token(client, "/anki/custom"),
                    "deck_name": "Selected Deck",
                    "quiz_cards": ["quiz:101:2"],
                    "missed_cards": ["missed:101:11"],
                    "law_cards": ["law:case-a:2"],
                },
            )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('value="quiz:101:2" checked', html)
        self.assertIn('value="missed:101:11" checked', html)
        self.assertIn('value="law:case-a:2" checked', html)
        self.assertIn('data-anki-quiz-selection-count>1 of 2 selected', html)
        self.assertIn('data-anki-quiz-selection-count>0 of 1 selected', html)
        self.assertIn('id="ankiPerformanceSelectionCount" data-anki-group-selection-count>1 of 2 selected', html)
        self.assertIn('id="ankiLawSelectionCount1" data-anki-group-selection-count>1 of 2 selected', html)
        self.assertIn('id="ankiLawSelectionCount2" data-anki-group-selection-count>0 of 1 selected', html)
        self.assertIn('value="Selected Deck"', html)


if __name__ == "__main__":
    unittest.main()
