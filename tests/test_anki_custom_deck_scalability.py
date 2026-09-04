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
            "missed_cards": [],
            "law_groups": [],
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
        self.assertEqual(html.count('class="anki-custom-selection-group anki-custom-quiz-group"'), 2)
        self.assertEqual(html.count('class="anki-custom-quiz-selection-count"'), 2)
        self.assertEqual(html.count('data-anki-quiz-select-all aria-controls='), 2)
        self.assertEqual(html.count('data-anki-quiz-clear aria-controls='), 2)

    def test_per_quiz_bulk_actions_are_scoped_and_filter_does_not_expand(self):
        html = self._get_page()

        self.assertIn(
            "quizGroup.querySelectorAll('input[type=\"checkbox\"][name=\"quiz_cards\"]')",
            html,
        )
        self.assertIn("quizSelections.forEach(checkbox => { checkbox.checked = true; })", html)
        self.assertIn("quizSelections.forEach(checkbox => { checkbox.checked = false; })", html)
        self.assertIn("updateCustomAnkiSelectionCount(quizGroup)", html)
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
                },
            )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('value="quiz:101:2" checked', html)
        self.assertIn('data-anki-quiz-selection-count>1 of 2 selected', html)
        self.assertIn('data-anki-quiz-selection-count>0 of 1 selected', html)
        self.assertIn('value="Selected Deck"', html)


if __name__ == "__main__":
    unittest.main()
