import os, tempfile, unittest
from pathlib import Path

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-pdf-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms

class PDFImportParserTests(unittest.TestCase):
    def test_question_answer_explanation_and_cross_page_feedback(self):
        pages = [
            {"page": 1, "lines": [
                "Question #1",
                "Which tool crafts packets?",
                "A. tcpdump",
                "B. Scapy",
                "C. dig",
                "D. grep",
                "Correct Answer: B — Scapy",
                "Scapy can craft packets.",
                "Why The Other Options Are Incorrect",
                "A. tcpdump captures packets.",
            ]},
            {"page": 2, "lines": [
                "C. dig queries DNS.",
                "D. grep searches text.",
                "Question #2",
                "Which value is two?",
                "A. one",
                "B. two",
                "Correct Answer: B — two",
                "Two is the requested value.",
            ]},
        ]
        result = dlms._pdf_parse_question_bank(pages)
        self.assertEqual(result["summary"]["detected"], 2)
        q1 = result["questions"][0]
        self.assertEqual(q1["correct"], "B")
        self.assertEqual(q1["choices"][1]["text"], "Scapy")
        self.assertIn("craft packets", q1["explanation"])
        self.assertIn("captures packets", q1["choice_feedback"]["A"])
        self.assertIn(2, q1["pages"])

    def test_embedded_content_cue_is_flagged_for_review(self):
        pages = [{"page": 1, "lines": [
            "Question #4",
            "Given the following payload:",
            "Which mitigation is best?",
            "A. Option one",
            "B. Option two",
            "Correct Answer: B — Option two",
        ]}]
        q = dlms._pdf_parse_question_bank(pages)["questions"][0]
        self.assertEqual(q["status"], "review")
        self.assertTrue(any("embedded" in issue.lower() for issue in q["issues"]))


    def test_plain_questions_do_not_get_embedded_content_warning(self):
        pages = [{"page": 1, "lines": [
            "Question #1",
            "Which of the following should the tester use?",
            "A. tcprelay",
            "B. Bluecrack",
            "C. Scapy",
            "D. tcpdump",
            "Correct Answer: C — Scapy",
            "Scapy can craft packets.",
        ]}]
        q = dlms._pdf_parse_question_bank(pages)["questions"][0]
        self.assertEqual(q["status"], "complete")
        self.assertFalse(any("embedded" in issue.lower() for issue in q["issues"]))

    def test_repeated_short_watermark_text_is_suppressed(self):
        pages = [
            {"page": 1, "lines": ["Question #1", "Daily Debrief", "A. one", "B. two"]},
            {"page": 2, "lines": ["Question #2", "Daily Debrief", "A. three", "B. four"]},
        ]
        cleaned, removed = dlms._pdf_suppress_repeated_margins(pages)
        self.assertIn("Daily Debrief", removed)
        self.assertNotIn("Daily Debrief", cleaned[0]["lines"])
        self.assertNotIn("Daily Debrief", cleaned[1]["lines"])


if __name__ == "__main__":
    unittest.main()
