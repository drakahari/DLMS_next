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


    def test_pdf_bank_selection_preserves_source_and_limits_quiz_size(self):
        bank = {
            "questions": [
                {
                    "number": i,
                    "original_number": i,
                    "question": f"Question {i}",
                    "choices": [{"label": "A", "text": "No"}, {"label": "B", "text": "Yes"}],
                    "correct": "B",
                    "active": True,
                }
                for i in range(1, 101)
            ],
            "used_question_numbers": [],
        }
        selected = dlms._select_pdf_bank_questions(bank, mode="random", count=20)
        self.assertEqual(len(selected), 20)
        self.assertEqual(len(bank["questions"]), 100)

    def test_pdf_bank_unused_and_range_selection(self):
        bank = {
            "questions": [
                {
                    "number": i,
                    "original_number": i,
                    "question": f"Question {i}",
                    "choices": [{"label": "A", "text": "No"}, {"label": "B", "text": "Yes"}],
                    "correct": "B",
                    "active": True,
                }
                for i in range(1, 11)
            ],
            "used_question_numbers": [1, 2, 3, 4],
        }
        unused = dlms._select_pdf_bank_questions(bank, mode="unused", count=3)
        self.assertTrue(all(q["original_number"] not in {1,2,3,4} for q in unused))
        ranged = dlms._select_pdf_bank_questions(bank, mode="range", start_number=4, end_number=7)
        self.assertEqual([q["original_number"] for q in ranged], [4,5,6,7])

    def test_pdf_bank_excluded_questions_are_not_selected(self):
        bank = {
            "questions": [
                {"number": 1, "original_number": 1, "question": "One", "active": True},
                {"number": 2, "original_number": 2, "question": "Two", "active": False},
                {"number": 3, "original_number": 3, "question": "Three", "active": True},
            ]
        }
        selected = dlms._select_pdf_bank_questions(bank, mode="all", count=50)
        self.assertEqual([q["original_number"] for q in selected], [1, 3])


    def test_pdf_auto_detects_question_bank_and_glossary(self):
        q_pages = [{"page": 1, "lines": [
            "Question #1", "Which one?", "A. One", "B. Two",
            "Correct Answer: B — Two", "Question #2", "Which next?",
            "A. Three", "B. Four", "Correct Answer: A — Three",
        ]}]
        q_result = dlms._pdf_parse_question_bank(q_pages)
        g_result = dlms._pdf_parse_glossary(q_pages)
        kind, _ = dlms._pdf_detect_document_type(q_pages, q_result, g_result)
        self.assertEqual(kind, "question_bank")

        g_pages = [{"page": 1, "lines": [
            "Access Control A process used to restrict access to authorized subjects.",
            "Audit Trail A chronological record of system activities and events.",
            "Business Continuity A capability that enables essential operations to continue after disruption.",
            "Data Classification A process for organizing information according to sensitivity and handling requirements.",
            "Encryption A method used to transform readable information into protected ciphertext.",
        ]}]
        q_result = dlms._pdf_parse_question_bank(g_pages)
        g_result = dlms._pdf_parse_glossary(g_pages)
        kind, _ = dlms._pdf_detect_document_type(g_pages, q_result, g_result)
        self.assertEqual(kind, "glossary")

    def test_glossary_parser_handles_inline_and_standalone_terms(self):
        pages = [{"page": 1, "lines": [
            "Access Control A process used to restrict access to authorized subjects.",
            "Audit Trail",
            "A chronological record of system activities and events.",
            "Encryption A method used to transform readable information into protected ciphertext.",
            "Risk Appetite The amount and type of risk an organization is willing to pursue or retain.",
        ]}]
        result = dlms._pdf_parse_glossary(pages)
        found = {x["term"]: x for x in result["terms"]}
        self.assertIn("Access Control", found)
        self.assertIn("Audit Trail", found)
        self.assertIn("chronological record", found["Audit Trail"]["definition"])
        self.assertIn("Encryption", found)

    def test_pdf_terminology_bank_selection_preserves_full_bank(self):
        bank = {
            "terms": [
                {"number": i, "term": f"Term {i}", "definition": f"Definition {i}", "active": True}
                for i in range(1, 41)
            ],
            "used_term_numbers": [1, 2, 3],
        }
        selected = dlms._select_pdf_term_bank_items(bank, mode="random", count=10)
        self.assertEqual(len(selected), 10)
        self.assertEqual(len(bank["terms"]), 40)
        unused = dlms._select_pdf_term_bank_items(bank, mode="unused", count=5)
        self.assertTrue(all(t["number"] not in {1, 2, 3} for t in unused))

    def test_pdf_terminology_generates_matching_and_multiple_choice(self):
        bank = {
            "title": "Terms",
            "source_name": "terms.pdf",
            "terms": [
                {"number": i, "term": f"Term {i}", "definition": f"Definition {i}", "active": True}
                for i in range(1, 7)
            ],
        }
        selected = bank["terms"][:4]
        runtime, dbq = dlms._pdf_terms_matching_questions(bank, selected, "term_to_definition")
        self.assertEqual(runtime[0]["type"], "matching")
        self.assertEqual(len(runtime[0]["pairs"]), 4)

        runtime, dbq = dlms._pdf_terms_mc_questions(bank, selected[:2], "definition_to_term")
        self.assertEqual(len(runtime), 2)
        self.assertTrue(all(q["type"] == "choice" for q in runtime))
        self.assertTrue(all(len(q["choices"]) == 4 for q in runtime))
        self.assertTrue(all(len(q["correct"]) == 1 for q in runtime))


    def test_glossary_standalone_heading_uses_following_definition(self):
        pages = [{"page": 1, "lines": [
            "Audit Trail",
            "A chronological record of system activities and events.",
            "Encryption",
            "A method used to transform readable information into protected ciphertext.",
        ]}]
        result = dlms._pdf_parse_glossary(pages)
        found = {x["term"]: x["definition"] for x in result["terms"]}
        self.assertEqual(
            found["Audit Trail"],
            "A chronological record of system activities and events."
        )
        self.assertEqual(
            found["Encryption"],
            "A method used to transform readable information into protected ciphertext."
        )


    def test_glossary_definition_sentence_is_not_promoted_to_inline_term(self):
        pages = [{"page": 1, "lines": [
            "Audit Trail",
            "A chronological record of system activities and events.",
            "Encryption",
            "A method used to transform readable information into protected ciphertext.",
        ]}]
        result = dlms._pdf_parse_glossary(pages)
        terms = [x["term"] for x in result["terms"]]
        self.assertEqual(terms, ["Audit Trail", "Encryption"])


    def test_glossary_inline_term_with_definition_prose_is_preserved(self):
        pages = [{"page": 1, "lines": [
            "Access Control A process used to restrict access to authorized subjects.",
            "Encryption A method used to transform readable information into protected ciphertext.",
        ]}]
        result = dlms._pdf_parse_glossary(pages)
        found = {x["term"]: x["definition"] for x in result["terms"]}
        self.assertEqual(
            found["Access Control"],
            "A process used to restrict access to authorized subjects."
        )
        self.assertEqual(
            found["Encryption"],
            "A method used to transform readable information into protected ciphertext."
        )


if __name__ == "__main__":
    unittest.main()
