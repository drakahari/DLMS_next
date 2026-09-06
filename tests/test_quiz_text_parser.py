"""Golden characterization coverage for the legacy text quiz parser."""

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_TEMP = tempfile.TemporaryDirectory(prefix="dlms-quiz-text-parser-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms


class LegacyQuizTextParserTests(unittest.TestCase):
    def test_single_and_multiple_answers_preserve_exact_output_shape(self):
        source = """Question 4 Which letters are correct?
A. Alpha
B. Beta
C. Gamma
Correct Answers: AC

5) Pick one
A) First
B) Second
Suggested Answer - b
"""

        self.assertEqual(
            [
                {
                    "number": 4,
                    "question": "Which letters are correct?",
                    "choices": [
                        {"label": "A", "text": "Alpha", "is_correct": True},
                        {"label": "B", "text": "Beta", "is_correct": False},
                        {"label": "C", "text": "Gamma", "is_correct": True},
                    ],
                    "correct": ["A", "C"],
                },
                {
                    "number": 5,
                    "question": "Pick one",
                    "choices": [
                        {"label": "A", "text": "First", "is_correct": False},
                        {"label": "B", "text": "Second", "is_correct": True},
                    ],
                    "correct": ["B"],
                },
            ],
            dlms.parse_questions(source),
        )

    def test_later_and_ambiguous_answer_markers_keep_legacy_semantics(self):
        source = """Question 1 Marker behavior
A. One
B. Two
C. Three
Correct Answer: AC
Suggested Answer: b

Question 2 Punctuation behavior
A. One
B. Two
Correct Answers: A, B
"""

        questions = dlms.parse_questions(source)

        self.assertEqual(["B"], questions[0]["correct"])
        self.assertEqual([False, True, False], [c["is_correct"] for c in questions[0]["choices"]])
        self.assertEqual(["A"], questions[1]["correct"])

    def test_unrecognized_custom_marker_and_incomplete_blocks_are_skipped(self):
        source = """Question 1 Custom marker
A. One
B. Two
Answer Key: A

Question 2 Too few choices
A. Only
Correct Answer: A
"""

        self.assertEqual([], dlms.parse_questions(source))
        self.assertIn("!! Skipped: NO correct answer found", dlms.PARSE_LOG)
        self.assertIn(
            "!! Skipped: Not enough choices: [{'label': 'A', 'text': 'Only'}]",
            dlms.PARSE_LOG,
        )
        self.assertEqual("Total questions parsed: 0", dlms.PARSE_LOG[-1])

    def test_unicode_wrapped_text_bom_and_file_input_are_preserved(self):
        source_path = Path(_TEMP.name) / "legacy-unicode-quiz.txt"
        source_path.write_text(
            "\ufeffQuestion #7 Café question\r\n"
            "wrapped naïve line\r\n"
            "A) Jalapeño\r\n"
            "B) 東京\r\n"
            "CORRECT ANSWER- b\r\n",
            encoding="utf-8",
        )

        self.assertEqual(
            [
                {
                    "number": 7,
                    "question": "Café question wrapped naïve line",
                    "choices": [
                        {"label": "A", "text": "Jalapeño", "is_correct": False},
                        {"label": "B", "text": "東京", "is_correct": True},
                    ],
                    "correct": ["B"],
                }
            ],
            dlms.parse_questions(str(source_path)),
        )
        self.assertEqual("Input detected as FILE path → reading file", dlms.PARSE_LOG[1])

    def test_matching_looking_input_remains_a_legacy_choice_question(self):
        questions = dlms.parse_questions(
            """Question 1 Match each item
A. Apple → Red
B. Sky → Blue
Correct Answer: AB
"""
        )

        self.assertEqual(["number", "question", "choices", "correct"], list(questions[0]))
        self.assertNotIn("type", questions[0])
        self.assertNotIn("pairs", questions[0])
        self.assertEqual(["A", "B"], questions[0]["correct"])

    def test_effective_confidence_analyzer_preserves_exact_result_and_messages(self):
        source = """Question 1 Café question
A. Oui
B. Non
Correct Answer: A

Question 2 Incomplete
No choices here
"""

        self.assertEqual(
            (
                {"high": 1, "medium": 0, "low": 1, "total": 2},
                [
                    {
                        "index": 1,
                        "title": "Question 1 Café question",
                        "confidence": "high",
                        "reason": (
                            "Found A–Z answer choices; Found 'Correct/Suggested Answer' line; "
                            "2 choices detected"
                        ),
                    },
                    {
                        "index": 2,
                        "title": "Question 2 Incomplete",
                        "confidence": "low",
                        "reason": (
                            "No A–Z answer choices found; No explicit correct-answer line found; "
                            "0 choices detected (unusual count)"
                        ),
                    },
                ],
            ),
            dlms.analyze_confidence(source),
        )

    def test_app_keeps_two_confidence_definitions_and_later_one_is_effective(self):
        tree = ast.parse(Path(dlms.__file__).read_text(encoding="utf-8"))
        definitions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "analyze_confidence"
        ]

        self.assertEqual(2, len(definitions))
        summary, details = dlms.analyze_confidence(
            "Question 1 Test\nA. Yes\nB. No\nCorrect Answer: A"
        )
        self.assertEqual("high", details[0]["confidence"])
        self.assertNotIn("score", details[0])
        self.assertEqual(1, summary["total"])

    def test_app_level_debug_helper_is_resolved_at_call_time(self):
        source = "Question 1 Test\nA. Yes\nB. No\nCorrect Answer: A"

        with mock.patch.object(dlms, "dbg") as debug_log:
            questions = dlms.parse_questions(source)

        self.assertEqual(1, len(questions))
        debug_log.assert_any_call("=== NEW PARSE SESSION STARTED ===")
        debug_log.assert_any_call("Total questions parsed:", 1)


if __name__ == "__main__":
    unittest.main()
