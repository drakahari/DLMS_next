"""Focused regressions for the no-evidence Topic Intelligence presentation."""

import unittest
from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "static" / "learning-intelligence.html"


class LearningIntelligenceEmptyStateTests(unittest.TestCase):
    def test_no_evidence_state_explains_reset_result_and_preserved_concepts(self):
        source = PAGE.read_text(encoding="utf-8")

        self.assertIn("No Learning Intelligence data exists yet.", source)
        self.assertIn("Your tagged concepts are preserved.", source)
        self.assertIn("after you answer tagged questions in Study or Exam Mode", source)

    def test_zero_evidence_topics_are_hidden_until_explicitly_requested(self):
        source = PAGE.read_text(encoding="utf-8")

        self.assertIn('id="liToggleZeroEvidence"', source)
        self.assertIn("const visibleTopics=noEvidence&&!state.showZeroEvidence?[]:state.topics;", source)
        self.assertIn("state.hasEvidence=Number(s.concepts_with_evidence||0)>0;", source)
        self.assertIn("state.showZeroEvidence=!state.showZeroEvidence", source)
        self.assertIn("aria-expanded", source)

    def test_existing_topic_filters_remain_available_for_evidenced_topics(self):
        source = PAGE.read_text(encoding="utf-8")

        for topic_filter in ("all", "weak", "developing", "proficient", "strong", "insufficient"):
            self.assertIn(f'data-li-filter="{topic_filter}"', source)
        self.assertIn(
            "document.getElementById('liToolbar').hidden=noEvidence&&!state.showZeroEvidence;",
            source,
        )


if __name__ == "__main__":
    unittest.main()
