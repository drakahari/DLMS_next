import re
import unittest
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class AnkiMissedSummaryLabelTests(unittest.TestCase):
    def _render_summary(self, summary):
        with mock.patch.object(dlms, "get_anki_quiz_choices", return_value=[]), \
             mock.patch.object(dlms, "get_anki_missed_summary", return_value=summary):
            response = dlms.app.test_client().get("/anki")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_summary_uses_clear_dynamic_labels_and_explains_overlap(self):
        html = self._render_summary({
            "total": 30,
            "currently_weak": 28,
            "recovered": 2,
            "repeated": 3,
            "once": 27,
        })

        self.assertRegex(html, r"Questions Ever Missed:</span>\s*<strong>30</strong>")
        self.assertRegex(html, r"<strong>28</strong>\s*<span>not yet revisited</span>")
        self.assertRegex(html, r"<strong>2</strong>\s*<span>revisited later</span>")
        self.assertRegex(html, r"<strong>3</strong>\s*<span>missed more than once</span>")
        self.assertIn("Repeat count overlaps revisit status.", html)
        self.assertNotRegex(html, r">\s*(?:weak|recovered)\s*<")

    def test_summary_metrics_are_semantically_grouped_and_theme_aware(self):
        html = self._render_summary({
            "total": 7,
            "currently_weak": 4,
            "recovered": 3,
            "repeated": 2,
            "once": 5,
        })
        self.assertIn('role="group" aria-labelledby="ankiMissedSummaryTitle" aria-describedby="ankiMissedOverlapNote"', html)
        self.assertIn('<ul class="anki-missed-summary-metrics" aria-label="Missed-question details">', html)
        self.assertIn('id="ankiMissedOverlapNote"', html)

        with open(dlms.resource_path("static/style.css"), "r", encoding="utf-8") as handle:
            css = handle.read()
        for selector, tokens in {
            ".anki-tools-summary .anki-missed-summary-total": ("--theme-muted-text",),
            ".anki-tools-summary .anki-missed-summary-total strong": ("--theme-heading",),
            ".anki-tools-summary .anki-missed-summary-metrics li": ("--theme-muted-text",),
            ".anki-tools-summary .anki-missed-summary-metrics strong": ("--theme-heading",),
            ".anki-tools-summary .anki-missed-summary-note": ("--theme-muted-text",),
        }.items():
            rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
            self.assertIsNotNone(rule, f"Missing style rule for {selector}")
            self.assertTrue(all(token in rule.group(1) for token in tokens))

        metrics = re.search(
            re.escape(".anki-tools-summary .anki-missed-summary-metrics") + r"\s*\{([^}]*)\}",
            css,
        )
        self.assertIn("display: grid", metrics.group(1))
        metric_row = re.search(
            re.escape(".anki-tools-summary .anki-missed-summary-metrics li") + r"\s*\{([^}]*)\}",
            css,
        )
        self.assertIn("grid-template-columns", metric_row.group(1))


if __name__ == "__main__":
    unittest.main()
