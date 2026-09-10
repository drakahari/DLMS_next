"""Focused layout-inference coverage for DLMS-119 screenshot OCR drafts."""

from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

from dlms.parsing import ocr_questions


def observations(lines, *, width=1200, confidence=93.0):
    output = []
    top = 30
    for line_number, item in enumerate(lines, 1):
        if isinstance(item, tuple):
            text, left = item
        else:
            text, left = item, 80
        cursor = left
        for word_number, word in enumerate(text.split(), 1):
            word_width = max(16, len(word) * 10)
            output.append(
                {
                    "source_id": "source",
                    "page_index": 0,
                    "source_width": width,
                    "source_height": 1600,
                    "text": word,
                    "bounding_box": {
                        "left": cursor,
                        "top": top,
                        "width": word_width,
                        "height": 26,
                    },
                    "confidence": confidence,
                    "block_id": 1,
                    "paragraph_id": 1,
                    "line_id": line_number,
                }
            )
            cursor += word_width + 9
        top += 54
    return output


def positioned_observations(lines, *, width=900, height=690):
    output = []
    for line_number, (text, left, top) in enumerate(lines, 1):
        cursor = left
        for word in text.split():
            word_width = max(16, len(word) * 12)
            output.append(
                {
                    "source_id": "source",
                    "page_index": 0,
                    "source_width": width,
                    "source_height": height,
                    "text": word,
                    "bounding_box": {
                        "left": cursor,
                        "top": top,
                        "width": word_width,
                        "height": 28,
                    },
                    "confidence": 94.0,
                    "block_id": 1,
                    "paragraph_id": 1,
                    "line_id": line_number,
                }
            )
            cursor += word_width + 8
    return output


RESULT_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "ocr"


def result_layout_observations(banner, question, choices, explanation):
    lines = [(banner, 68, 44), (question, 55, 125)]
    noise = ("@", "O", "©", "O")
    lines.extend(
        (f"{noise[index]} {chr(65 + index)}. {choice}", 72, 224 + 75 * index)
        for index, choice in enumerate(choices)
    )
    lines.extend((("O Explanation", 55, 520), (explanation, 55, 558)))
    return positioned_observations(lines)


class OCRQuestionInferenceTests(unittest.TestCase):
    def infer(self, lines, **kwargs):
        return ocr_questions.infer_screenshot_questions(
            observations(lines, **kwargs), source_id="source", source_index=1
        )

    def test_explicit_labels_and_one_answer_key_are_preserved_as_review_evidence(self):
        result = self.infer(
            [
                "Which protocol securely transfers files?",
                "A. FTP",
                "B. SFTP",
                "C. HTTP",
                "D. SNMP",
                "Correct answer: B",
                "Explanation: SFTP encrypts file transfers.",
            ]
        )
        question = result["questions"][0]
        self.assertEqual([choice["text"] for choice in question["choices"]], ["FTP", "SFTP", "HTTP", "SNMP"])
        self.assertEqual(question["correct_answers"], ["B"])
        self.assertEqual(question["correctness_evidence"], "explicit_source")
        self.assertEqual(question["ocr_metadata"]["label_origin"], "source")
        self.assertTrue(question["correctness_confirmation_required"])
        self.assertFalse(question["correctness_confirmed"])
        self.assertEqual(question["explanation"], "SFTP encrypts file transfers.")

    def test_unlabelled_six_and_eight_choice_blocks_receive_all_positional_labels(self):
        for count in (6, 8):
            with self.subTest(count=count):
                result = self.infer(
                    ["Which properties apply?"]
                    + [(f"Choice {index}", 170) for index in range(1, count + 1)]
                )
                question = result["questions"][0]
                self.assertEqual(len(question["choices"]), count)
                self.assertEqual(question["choices"][-1]["label"], chr(64 + count))
                self.assertEqual(question["ocr_metadata"]["label_origin"], "inferred")
                self.assertEqual(question["ocr_metadata"]["structure_confidence"], "medium")

    def test_maximum_26_is_supported_and_more_is_never_truncated_into_a_valid_question(self):
        labels = [f"{chr(65 + index)}. Choice {index + 1}" for index in range(26)]
        question = self.infer(["Which choices apply?"] + labels)["questions"][0]
        self.assertEqual(len(question["choices"]), 26)
        self.assertEqual(question["choices"][-1]["label"], "Z")

        too_many = [f"{chr(65 + (index % 26))}. Choice {index + 1}" for index in range(27)]
        question = self.infer(["Which choices apply?"] + too_many)["questions"][0]
        self.assertEqual(question["choices"], [])
        self.assertEqual(question["status"], "incomplete")
        self.assertIn("Choice 27", question["ocr_metadata"]["unassigned_text"])
        self.assertTrue(any("More than 26" in issue for issue in question["issues"]))

    def test_multiple_answer_instruction_and_complete_explicit_set(self):
        question = self.infer(
            [
                "Which controls apply? Select all that apply",
                "A. First",
                "B. Second",
                "C. Third",
                "D. Fourth",
                "Correct answers: B and D",
            ]
        )["questions"][0]
        self.assertEqual(question["answer_mode"], "multiple")
        self.assertEqual(question["answer_mode_evidence"], "explicit_instruction")
        self.assertEqual(question["correct_answers"], ["B", "D"])

    def test_feedback_can_supply_answer_evidence_but_visual_selection_never_does(self):
        feedback = self.infer(
            [
                "Which answers apply?",
                "A. First",
                "B. Second",
                "C. Third",
                "Explanation: The correct answers are A and C.",
            ]
        )["questions"][0]
        self.assertEqual(feedback["correct_answers"], ["A", "C"])
        self.assertEqual(feedback["correctness_evidence"], "explicit_feedback")

        selected_words = self.infer(
            [
                "Which answer is correct?",
                "A. First selected",
                "B. Second highlighted green",
                "C. Third checked",
            ]
        )["questions"][0]
        self.assertEqual(selected_words["correct_answers"], [])
        self.assertEqual(selected_words["correctness_evidence"], "unknown")

    def test_label_anomalies_are_normalized_by_position_and_flagged(self):
        question = self.infer(
            ["Which option?", "A. One", "8. Two", "B. Three", "D. Four"]
        )["questions"][0]
        self.assertEqual([choice["label"] for choice in question["choices"]], list("ABCD"))
        self.assertTrue(any("read source label B as 8" in issue for issue in question["issues"]))
        self.assertTrue(any("normalized" in issue for issue in question["issues"]))

    def test_non_question_vertical_list_is_retained_as_unassigned_in_incomplete_draft(self):
        question = self.infer(
            ["Course resources", "Timeliness", "Detail", "Completeness", "Accuracy"]
        )["questions"][0]
        self.assertEqual(question["status"], "incomplete")
        self.assertEqual(question["choices"], [])
        self.assertIn("Timeliness", question["ocr_metadata"]["unassigned_text"])

    def test_clear_multiple_question_markers_split_but_chrome_remains_visible(self):
        result = self.infer(
            [
                "Question 1 Which protocol?",
                "A. FTP",
                "B. SFTP",
                "Next",
                "Question 2 Which port?",
                "A. 22",
                "B. 80",
                "Submit",
            ]
        )
        self.assertEqual(len(result["questions"]), 2)
        self.assertIn("Next", result["questions"][0]["ocr_metadata"]["unassigned_text"])
        self.assertIn("Submit", result["questions"][1]["ocr_metadata"]["unassigned_text"])

    def test_more_than_fifty_clear_questions_preserves_overflow_text_for_review(self):
        lines = []
        for number in range(1, 52):
            lines.extend([f"Question {number} Which option?", "A. First", "B. Second"])
        result = self.infer(lines)
        self.assertEqual(len(result["questions"]), 50)
        self.assertTrue(result["warnings"])
        self.assertIn(
            "Question 51 Which option?",
            result["questions"][-1]["ocr_metadata"]["unassigned_text"],
        )

    def test_choice_feedback_and_distinct_confidence_dimensions_are_preserved(self):
        result = ocr_questions.infer_screenshot_questions(
            observations(
                [
                    "Which option?",
                    "A. One",
                    "B. Two",
                    "A feedback: This is a distractor.",
                ],
                confidence=50,
            ),
            source_id="source",
            source_index=1,
        )
        question = result["questions"][0]
        self.assertEqual(question["choice_feedback"]["A"], "This is a distractor.")
        self.assertEqual(question["ocr_metadata"]["text_confidence"], "low")
        self.assertIn(question["ocr_metadata"]["structure_confidence"], {"high", "medium"})
        self.assertEqual(question["ocr_metadata"]["correctness_evidence"], "unknown")

    def test_reviewed_result_fixtures_detect_source_labels_explanation_and_correct_row(self):
        cases = (
            (
                "screenshot-result-a-wrong-b-correct.png",
                "Incorrect",
                "Which quality is most useful for this synthetic example?",
                ("Timeliness", "Detail", "Accuracy", "Relevance"),
                "Detail is the answer identified by the result feedback.",
                ["B"],
                [{"label": "A", "kind": "x"}, {"label": "B", "kind": "check"}],
            ),
            (
                "screenshot-result-d-correct.png",
                "Correct",
                "Which option best represents the synthetic group?",
                ("Alpha unit", "Beta unit", "Gamma unit", "Delta collective"),
                "Delta collective is explicitly marked correct by the row result icon.",
                ["D"],
                [{"label": "D", "kind": "check"}],
            ),
            (
                "screenshot-result-a-correct-c-wrong.png",
                "Incorrect",
                "Which assessment best identifies the synthetic condition?",
                ("Behavioral", "Instinctual", "Habitual", "Indicators"),
                "Behavioral is marked correct; the selected Habitual row is marked wrong.",
                ["A"],
                [{"label": "A", "kind": "check"}, {"label": "C", "kind": "x"}],
            ),
        )
        for filename, banner, question_text, choices, explanation, answers, marker_evidence in cases:
            with self.subTest(filename=filename):
                observations_for_source = result_layout_observations(
                    banner, question_text, choices, explanation
                )
                image_bytes = (RESULT_FIXTURE_ROOT / filename).read_bytes()
                markers = ocr_questions.detect_visual_result_markers(
                    image_bytes, observations_for_source
                )
                result = ocr_questions.infer_screenshot_questions(
                    {"observations": observations_for_source, "visual_markers": markers},
                    source_id="source",
                    source_index=1,
                )
                inferred = result["questions"][0]
                self.assertEqual(len(inferred["choices"]), 4)
                self.assertEqual(
                    [choice["label_origin"] for choice in inferred["choices"]],
                    ["source"] * 4,
                )
                self.assertEqual([choice["text"] for choice in inferred["choices"]], list(choices))
                self.assertEqual(inferred["correct_answers"], answers)
                self.assertEqual(inferred["correctness_evidence"], "visual_result_marker")
                self.assertEqual(inferred["ocr_metadata"]["visual_result_markers"], marker_evidence)
                self.assertEqual(inferred["explanation"], explanation)
                self.assertNotIn("Explanation", [choice["text"] for choice in inferred["choices"]])
                self.assertTrue(inferred["correctness_confirmation_required"])
                self.assertFalse(inferred["correctness_confirmed"])

    def test_control_glyph_noise_is_bounded_to_a_real_following_source_label(self):
        question = self.infer(
            [
                "Which option?",
                "@ A. First",
                "O B. Second",
                "© C. Third",
                "O D. Fourth",
                "@ ordinary prose is not a labelled choice",
            ]
        )["questions"][0]
        self.assertEqual([choice["text"] for choice in question["choices"]], ["First", "Second", "Third", "Fourth"])
        self.assertEqual(question["ocr_metadata"]["label_origin"], "source")
        self.assertIn("ordinary prose", question["ocr_metadata"]["unassigned_text"])

    def test_visual_selection_or_row_color_without_a_dedicated_marker_stays_unknown(self):
        image = Image.new("RGB", (900, 690), "#f4f7fb")
        draw = ImageDraw.Draw(image)
        draw.rectangle((52, 210, 848, 268), fill="#d9f6df")
        output = BytesIO()
        image.save(output, format="PNG")
        source = result_layout_observations(
            "Incorrect",
            "Which option?",
            ("Selected green row", "Second", "Third", "Fourth"),
            "Review the source.",
        )
        markers = ocr_questions.detect_visual_result_markers(output.getvalue(), source)
        question = ocr_questions.infer_screenshot_questions(
            {"observations": source, "visual_markers": markers},
            source_id="source",
            source_index=1,
        )["questions"][0]
        self.assertEqual(markers, ())
        self.assertEqual(question["correct_answers"], [])
        self.assertEqual(question["correctness_evidence"], "unknown")

    def test_outlined_circle_and_disconnected_check_glyph_are_one_dedicated_marker(self):
        image = Image.new("RGB", (900, 690), "#f4f7fb")
        draw = ImageDraw.Draw(image)
        draw.ellipse((798, 296, 834, 332), outline="#16864b", width=4)
        draw.line((806, 314, 813, 322, 828, 304), fill="#16864b", width=4)
        output = BytesIO()
        image.save(output, format="PNG")
        source = result_layout_observations(
            "Incorrect",
            "Which option?",
            ("Wrong selected row", "Correct row", "Third", "Fourth"),
            "Review the source.",
        )
        markers = ocr_questions.detect_visual_result_markers(output.getvalue(), source)
        question = ocr_questions.infer_screenshot_questions(
            {"observations": source, "visual_markers": markers},
            source_id="source",
            source_index=1,
        )["questions"][0]
        self.assertEqual([marker["kind"] for marker in markers], ["check"])
        self.assertEqual(question["correct_answers"], ["B"])
        self.assertEqual(question["correctness_evidence"], "visual_result_marker")

    def test_multiple_dedicated_checks_preserve_multi_answer_support(self):
        image = Image.new("RGB", (900, 690), "#f4f7fb")
        draw = ImageDraw.Draw(image)
        for center_y in (314, 464):
            draw.ellipse((798, center_y - 18, 834, center_y + 18), fill="#16864b")
            draw.line(
                (806, center_y, 813, center_y + 8, 828, center_y - 10),
                fill="white",
                width=5,
            )
        output = BytesIO()
        image.save(output, format="PNG")
        source = result_layout_observations(
            "Correct",
            "Which options apply? Select all that apply",
            ("First", "Second", "Third", "Fourth"),
            "Two rows are explicitly marked.",
        )
        markers = ocr_questions.detect_visual_result_markers(output.getvalue(), source)
        question = ocr_questions.infer_screenshot_questions(
            {"observations": source, "visual_markers": markers},
            source_id="source",
            source_index=1,
        )["questions"][0]
        self.assertEqual(question["correct_answers"], ["B", "D"])
        self.assertEqual(question["answer_mode"], "multiple")
        self.assertTrue(question["correctness_confirmation_required"])

    def test_unassociated_or_ambiguous_checkmark_does_not_establish_correctness(self):
        fixture = Image.open(RESULT_FIXTURE_ROOT / "screenshot-result-d-correct.png").convert("RGB")
        draw = ImageDraw.Draw(fixture)
        draw.ellipse((732, 446, 768, 482), fill="#16864b")
        draw.line((740, 464, 747, 472, 762, 454), fill="white", width=5)
        output = BytesIO()
        fixture.save(output, format="PNG")
        source = result_layout_observations(
            "Correct",
            "Which option best represents the synthetic group?",
            ("Alpha unit", "Beta unit", "Gamma unit", "Delta collective"),
            "Delta collective is explicitly marked correct by the row result icon.",
        )
        markers = ocr_questions.detect_visual_result_markers(output.getvalue(), source)
        question = ocr_questions.infer_screenshot_questions(
            {"observations": source, "visual_markers": markers},
            source_id="source",
            source_index=1,
        )["questions"][0]
        self.assertFalse(any(marker["row_top"] == 449 for marker in markers))
        self.assertEqual(question["correct_answers"], [])
        self.assertEqual(question["correctness_evidence"], "unknown")

        outside = Image.new("RGB", (900, 690), "#f4f7fb")
        outside_draw = ImageDraw.Draw(outside)
        outside_draw.ellipse((798, 592, 834, 628), fill="#16864b")
        outside_draw.line((806, 610, 813, 618, 828, 600), fill="white", width=5)
        outside_bytes = BytesIO()
        outside.save(outside_bytes, format="PNG")
        self.assertEqual(
            ocr_questions.detect_visual_result_markers(outside_bytes.getvalue(), source),
            (),
        )


if __name__ == "__main__":
    unittest.main()
