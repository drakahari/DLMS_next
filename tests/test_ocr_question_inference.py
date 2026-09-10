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


def result_marker_image(
    *,
    size=(900, 690),
    row_tops=(210, 285, 360, 435),
    marker_x=816,
    marker_y_offset=29,
    marker_radius=18,
    checks=(),
    wrongs=(),
    selected=(),
):
    """Render neutral result-row controls and dedicated markers in memory."""

    image = Image.new("RGB", size, "#f4f7fb")
    draw = ImageDraw.Draw(image)
    for index, top in enumerate(row_tops):
        row_fill = "#eef4ff" if index in selected else "white"
        draw.rounded_rectangle(
            (23, top, size[0] - 25, top + 58),
            radius=8,
            fill=row_fill,
            outline="#b8b8b8",
            width=2,
        )
        draw.ellipse((36, top + 18, 56, top + 38), fill="white", outline="#53657c", width=2)
        if index in selected:
            draw.ellipse((41, top + 23, 51, top + 33), fill="#315fa8")
        kind = "check" if index in checks else "x" if index in wrongs else None
        if not kind:
            continue
        center_y = top + marker_y_offset
        fill = "#16864b" if kind == "check" else "#c53030"
        draw.ellipse(
            (
                marker_x - marker_radius,
                center_y - marker_radius,
                marker_x + marker_radius,
                center_y + marker_radius,
            ),
            fill=fill,
        )
        stroke = max(4, marker_radius // 4)
        if kind == "check":
            draw.line(
                (
                    marker_x - marker_radius // 2,
                    center_y,
                    marker_x - marker_radius // 6,
                    center_y + marker_radius // 2,
                    marker_x + marker_radius * 2 // 3,
                    center_y - marker_radius // 2,
                ),
                fill="white",
                width=stroke,
                joint="curve",
            )
        else:
            offset = marker_radius // 2
            draw.line(
                (marker_x - offset, center_y - offset, marker_x + offset, center_y + offset),
                fill="white",
                width=stroke,
            )
            draw.line(
                (marker_x + offset, center_y - offset, marker_x - offset, center_y + offset),
                fill="white",
                width=stroke,
            )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def result_layout_observations(banner, question, choices, explanation):
    lines = [(banner, 68, 44), (question, 55, 125)]
    noise = ("@", "O", "©", "O")
    lines.extend(
        (f"{noise[index]} {chr(65 + index)}. {choice}", 72, 224 + 75 * index)
        for index, choice in enumerate(choices)
    )
    lines.extend((("O Explanation", 55, 520), (explanation, 55, 558)))
    return positioned_observations(lines)


def scaled_result_observations(banner, question, answer_lines, explanation):
    lines = [(banner, 72, 47), (question, 58, 132)]
    lines.extend(
        (answer_line, 73, top)
        for answer_line, top in zip(answer_lines, (245, 327, 409, 491))
    )
    lines.extend((("O Explanation", 58, 590), (explanation, 58, 632)))
    return positioned_observations(lines, width=1120, height=840)


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
            ["Course resources", "Quartz", "Cobalt", "Amber", "Violet"]
        )["questions"][0]
        self.assertEqual(question["status"], "incomplete")
        self.assertEqual(question["choices"], [])
        self.assertIn("Quartz", question["ocr_metadata"]["unassigned_text"])

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

    def test_dynamic_result_layouts_detect_source_labels_explanation_and_correct_row(self):
        cases = (
            (
                "paired-result-markers",
                "Incorrect",
                "Which neutral sample matches the rule?",
                ("Quartz pulse", "Cobalt depth", "Amber precision", "Violet scope"),
                "The dedicated marker identifies Cobalt depth.",
                ["B"],
                [{"label": "A", "kind": "x"}, {"label": "B", "kind": "check"}],
                {1},
                {0},
                {0},
            ),
            (
                "final-row-check",
                "Correct",
                "Which option best represents the synthetic group?",
                ("Alpha unit", "Beta unit", "Gamma unit", "Delta collective"),
                "Delta collective is explicitly marked correct by the row result icon.",
                ["D"],
                [{"label": "D", "kind": "check"}],
                {3},
                set(),
                {3},
            ),
        )
        for (
            case_name,
            banner,
            question_text,
            choices,
            explanation,
            answers,
            marker_evidence,
            checks,
            wrongs,
            selected,
        ) in cases:
            with self.subTest(case=case_name):
                observations_for_source = result_layout_observations(
                    banner, question_text, choices, explanation
                )
                image_bytes = result_marker_image(
                    checks=checks, wrongs=wrongs, selected=selected
                )
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

    def test_sequence_recovers_noisy_early_labels_and_dedicated_d_marker(self):
        source = scaled_result_observations(
            "Correct",
            "Which synthetic group best demonstrates civic advocacy?",
            (
                "O A Alpha service",
                "O B Beta office",
                "C. Gamma circle",
                "D. Delta advocates (/)",
            ),
            "The dedicated result marker identifies Delta advocates.",
        )
        fixture = RESULT_FIXTURE_ROOT / "screenshot-result-sequence-recovery-d-correct.png"
        markers = ocr_questions.detect_visual_result_markers(fixture.read_bytes(), source)
        question = ocr_questions.infer_screenshot_questions(
            {"observations": source, "visual_markers": markers},
            source_id="source",
            source_index=1,
        )["questions"][0]

        self.assertEqual(
            question["question"],
            "Which synthetic group best demonstrates civic advocacy?",
        )
        self.assertEqual(
            [choice["text"] for choice in question["choices"]],
            ["Alpha service", "Beta office", "Gamma circle", "Delta advocates"],
        )
        self.assertEqual(
            [choice["label_origin"] for choice in question["choices"]],
            ["source"] * 4,
        )
        self.assertEqual(question["correct_answers"], ["D"])
        self.assertEqual(question["correctness_evidence"], "visual_result_marker")
        self.assertEqual(question["explanation"], "The dedicated result marker identifies Delta advocates.")
        self.assertTrue(question["correctness_confirmation_required"])

    def test_result_row_artifacts_are_removed_and_x_never_becomes_correct(self):
        source = scaled_result_observations(
            "Incorrect",
            "Which neutral signal matches the rule?",
            (
                "| O A Quartz pulse (/)",
                "O B.Cobalt pattern |",
                "© C.Amber cycle (x)",
                "O D. IOCs",
            ),
            "The first neutral row has the dedicated result marker.",
        )
        image_bytes = result_marker_image(
            size=(1120, 840),
            row_tops=(235, 317, 399, 481),
            marker_x=1028,
            marker_y_offset=48,
            marker_radius=25,
            checks={0},
            wrongs={2},
            selected={2},
        )
        markers = ocr_questions.detect_visual_result_markers(image_bytes, source)
        question = ocr_questions.infer_screenshot_questions(
            {"observations": source, "visual_markers": markers},
            source_id="source",
            source_index=1,
        )["questions"][0]

        self.assertEqual(
            [choice["text"] for choice in question["choices"]],
            ["Quartz pulse", "Cobalt pattern", "Amber cycle", "IOCs"],
        )
        self.assertEqual(question["ocr_metadata"]["label_origin"], "source")
        self.assertEqual(question["correct_answers"], ["A"])
        self.assertEqual(question["correctness_evidence"], "visual_result_marker")
        self.assertEqual(
            question["ocr_metadata"]["visual_result_markers"],
            [{"label": "A", "kind": "check"}, {"label": "C", "kind": "x"}],
        )
        self.assertEqual(
            question["explanation"],
            "The first neutral row has the dedicated result marker.",
        )
        self.assertNotIn("Explanation", [choice["text"] for choice in question["choices"]])
        self.assertTrue(question["correctness_confirmation_required"])

    def test_measured_banner_omission_and_control_confusions_are_recovered(self):
        cases = (
            (
                "omitted-banner-with-paired-markers",
                "Which synthetic measure is least useful?",
                (
                    "@ A Alpha timing x)",
                    "O B. Beta detail ()",
                    "| O ©.Gamma accuracy |",
                    "| © D. Delta relevance |",
                ),
                ("Alpha timing", "Beta detail", "Gamma accuracy", "Delta relevance"),
                ["B"],
                [{"label": "A", "kind": "x"}, {"label": "B", "kind": "check"}],
            ),
            (
                "copyright-glyph-as-c-label",
                "Which synthetic group is the example?",
                (
                    "O A Alpha unit",
                    "O B.US. sample unit",
                    "©. Gamma group",
                    "© D. Delta collective ()",
                ),
                ("Alpha unit", "U.S. sample unit", "Gamma group", "Delta collective"),
                ["D"],
                [{"label": "D", "kind": "check"}],
            ),
            (
                "trailing-controls-and-narrow-iocs",
                "Which synthetic assessment is useful?",
                (
                    "O A Alpha behavior (7)",
                    "| O B.Beta instinct |",
                    "© C Gamma habit x)",
                    "| O D.10¢s |",
                ),
                ("Alpha behavior", "Beta instinct", "Gamma habit", "IOCs"),
                ["A"],
                [{"label": "A", "kind": "check"}, {"label": "C", "kind": "x"}],
            ),
        )
        for filename, question_text, answer_lines, choices, answers, evidence in cases:
            with self.subTest(case=filename):
                source = positioned_observations(
                    [(question_text, 24, 114)]
                    + [
                        (answer_line, 24, top)
                        for answer_line, top in zip(answer_lines, (186, 254, 324, 394))
                    ]
                    + [
                        ("Q Explanation", 41, 472),
                        ("Synthetic explanation remains separate.", 44, 514),
                    ],
                    width=815,
                    height=642,
                )
                checks = {
                    index
                    for index, label in enumerate("ABCD")
                    if {"label": label, "kind": "check"} in evidence
                }
                wrongs = {
                    index
                    for index, label in enumerate("ABCD")
                    if {"label": label, "kind": "x"} in evidence
                }
                image_bytes = result_marker_image(
                    size=(815, 642),
                    row_tops=(166, 234, 304, 374),
                    marker_x=762,
                    marker_y_offset=38,
                    checks=checks,
                    wrongs=wrongs,
                    selected=wrongs or checks,
                )
                markers = ocr_questions.detect_visual_result_markers(
                    image_bytes, source
                )
                question = ocr_questions.infer_screenshot_questions(
                    {"observations": source, "visual_markers": markers},
                    source_id="source",
                    source_index=1,
                )["questions"][0]

                self.assertEqual(question["question"], question_text)
                self.assertEqual(
                    [choice["text"] for choice in question["choices"]], list(choices)
                )
                self.assertEqual(
                    [choice["label_origin"] for choice in question["choices"]],
                    ["source"] * 4,
                )
                self.assertEqual(question["correct_answers"], answers)
                self.assertEqual(question["correctness_evidence"], "visual_result_marker")
                self.assertEqual(question["ocr_metadata"]["visual_result_markers"], evidence)
                self.assertEqual(
                    question["explanation"], "Synthetic explanation remains separate."
                )
                self.assertTrue(question["correctness_confirmation_required"])
                self.assertFalse(question["correctness_confirmed"])

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

    def test_incomplete_source_label_sequence_cannot_translate_a_marker_by_position(self):
        source = positioned_observations(
            [
                ("Which neutral option applies?", 55, 125),
                ("O C. Third sample", 72, 374),
                ("O D. Fourth sample", 72, 449),
                ("Q Explanation", 55, 520),
                ("Review the recovered sequence.", 55, 558),
            ]
        )
        question = ocr_questions.infer_screenshot_questions(
            {
                "observations": source,
                "visual_markers": (
                    {"kind": "check", "row_left": 72, "row_top": 449},
                ),
            },
            source_id="source",
            source_index=1,
        )["questions"][0]

        self.assertEqual(question["correct_answers"], [])
        self.assertEqual(question["correctness_evidence"], "unknown")
        self.assertEqual(question["ocr_metadata"]["visual_result_markers"], [])
        self.assertTrue(any("source-label sequence" in issue for issue in question["issues"]))

    def test_geometrically_inconsistent_source_rows_cannot_translate_a_marker(self):
        source = positioned_observations(
            [
                ("Which neutral option applies?", 55, 125),
                ("A. First sample", 72, 224),
                ("B. Second sample", 280, 299),
                ("C. Third sample", 72, 374),
                ("D. Fourth sample", 72, 449),
                ("Explanation", 55, 520),
                ("Review the recovered geometry.", 55, 558),
            ]
        )
        question = ocr_questions.infer_screenshot_questions(
            {
                "observations": source,
                "visual_markers": (
                    {"kind": "check", "row_left": 280, "row_top": 299},
                ),
            },
            source_id="source",
            source_index=1,
        )["questions"][0]

        self.assertEqual(question["correct_answers"], [])
        self.assertEqual(question["correctness_evidence"], "unknown")
        self.assertEqual(question["ocr_metadata"]["visual_result_markers"], [])
        self.assertTrue(any("source-label sequence" in issue for issue in question["issues"]))

    def test_bordered_row_geometry_recovers_early_rows_without_trusting_geometry(self):
        image_bytes = result_marker_image(checks={3}, selected={3})
        incomplete = positioned_observations(
            [
                ("Correct", 68, 44),
                ("Which neutral option applies?", 55, 125),
                ("O B. Cobalt sample", 72, 299),
                ("© C. Amber sample", 72, 374),
                ("O D. Violet sample", 72, 449),
                ("Q Explanation", 55, 520),
                ("A bounded retry supplies the missing row.", 55, 558),
            ]
        )
        regions = ocr_questions.detect_answer_row_regions(image_bytes, incomplete)
        self.assertEqual(len(regions), 4)

        recovered = positioned_observations(
            [
                ("O A. Quartz sample", 72, 224),
                ("O B. Cobalt sample", 72, 299),
                ("© C. Amber sample", 72, 374),
                ("O D. Violet sample", 72, 449),
            ]
        )
        for item in recovered:
            item["block_id"] = 10_000 + item["line_id"]
        merged = ocr_questions.merge_answer_row_observations(
            incomplete, recovered, regions
        )
        markers = ocr_questions.detect_visual_result_markers(
            image_bytes, merged, answer_regions=regions
        )
        question = ocr_questions.infer_screenshot_questions(
            {
                "observations": merged,
                "visual_markers": markers,
                "answer_regions": regions,
            },
            source_id="source",
            source_index=1,
        )["questions"][0]

        self.assertEqual(
            [choice["text"] for choice in question["choices"]],
            ["Quartz sample", "Cobalt sample", "Amber sample", "Violet sample"],
        )
        self.assertEqual(question["ocr_metadata"]["label_origin"], "source")
        self.assertEqual(question["correct_answers"], ["D"])
        self.assertTrue(question["correctness_confirmation_required"])
        self.assertFalse(question["correctness_confirmed"])

    def test_repeated_unlabelled_cards_preserve_feedback_and_explicit_correct_row(self):
        source = positioned_observations(
            [
                ("© Question 8 Incorrect + Explain this further", 30, 24),
                ("Which neutral material matches the sample?", 55, 70),
                ("Your answer is incorrect", 55, 150),
                ("@ Quartz tile", 55, 190),
                ("Explanation", 55, 250),
                ("Quartz is not the requested material.", 55, 285),
                ("Correct answer", 55, 350),
                ("O Cobalt tile", 55, 390),
                ("Explanation", 55, 450),
                ("Cobalt matches the requested material.", 55, 485),
                ("O Amber tile", 55, 550),
                ("Explanation", 55, 610),
                ("Amber is a distractor.", 55, 645),
                ("O Violet tile", 55, 710),
                ("Explanation", 55, 770),
                ("Violet is a distractor.", 55, 805),
                ("Domain", 55, 900),
                ("Neutral Studies", 55, 940),
            ],
            width=900,
            height=1000,
        )
        question = ocr_questions.infer_screenshot_questions(
            source, source_id="source", source_index=1
        )["questions"][0]

        self.assertEqual(question["question"], "Which neutral material matches the sample?")
        self.assertEqual(
            [choice["text"] for choice in question["choices"]],
            ["Quartz tile", "Cobalt tile", "Amber tile", "Violet tile"],
        )
        self.assertEqual(question["ocr_metadata"]["label_origin"], "inferred")
        self.assertEqual(question["correct_answers"], ["B"])
        self.assertEqual(question["correctness_evidence"], "explicit_feedback")
        self.assertEqual(set(question["choice_feedback"]), set("ABCD"))
        self.assertNotIn("Domain", question["question"])
        self.assertNotIn("Domain", question["explanation"])
        self.assertIn("Domain", question["ocr_metadata"]["unassigned_text"])

    def test_overall_explanation_maps_complete_multi_answer_set_but_boxes_alone_do_not(self):
        base = [
            ("@ Question 4 Correct + Explain this further", 30, 24),
            ("Which neutral samples apply? Choose two.", 55, 70),
            ("(C1 Quartz arc", 55, 150),
            ("(C_ Cobalt arc", 55, 230),
            ("(1 Amber arc", 55, 310),
            ("( Violet arc", 55, 390),
            ("Overall explanation", 55, 500),
        ]
        explicit = positioned_observations(
            base
            + [
                ("Correct answers:", 55, 540),
                ("Quartz arc and Cobalt arc are correct.", 55, 580),
                ("Domain", 55, 680),
                ("Neutral Studies", 55, 720),
            ],
            width=900,
            height=800,
        )
        question = ocr_questions.infer_screenshot_questions(
            explicit, source_id="source", source_index=1
        )["questions"][0]
        self.assertEqual(question["answer_mode"], "multiple")
        self.assertEqual(question["correct_answers"], ["A", "B"])
        self.assertEqual(question["correctness_evidence"], "explicit_feedback")
        self.assertIn("Correct answers", question["explanation"])

        controls_only = positioned_observations(
            base
            + [
                ("Review all choices manually.", 55, 540),
                ("Domain", 55, 680),
                ("Neutral Studies", 55, 720),
            ],
            width=900,
            height=800,
        )
        unknown = ocr_questions.infer_screenshot_questions(
            controls_only, source_id="source", source_index=1
        )["questions"][0]
        self.assertEqual(unknown["answer_mode"], "multiple")
        self.assertEqual(unknown["correct_answers"], [])
        self.assertEqual(unknown["correctness_evidence"], "unknown")

    def test_relaxed_label_sequence_is_limited_to_reviewed_result_context(self):
        question = self.infer(
            [
                "Which option?",
                "O A First",
                "O B Second",
                "O C Third",
                "O D Fourth",
            ]
        )["questions"][0]
        self.assertEqual(question["ocr_metadata"]["label_origin"], "inferred")
        self.assertEqual(question["choices"][0]["text"], "O A First")

    def test_visual_selection_or_row_color_without_a_dedicated_marker_stays_unknown(self):
        image = Image.new("RGB", (900, 690), "#f4f7fb")
        draw = ImageDraw.Draw(image)
        draw.rectangle((52, 210, 848, 268), fill="#d9f6df")
        draw.ellipse((72, 228, 92, 248), fill="white", outline="#53657c", width=2)
        draw.ellipse((77, 233, 87, 243), fill="#315fa8")
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

    def test_bannerless_selected_radio_and_checked_checkbox_stay_unknown(self):
        image = Image.new("RGB", (900, 690), "#f4f7fb")
        draw = ImageDraw.Draw(image)
        draw.rectangle((52, 285, 848, 343), fill="#d9f6df")
        draw.ellipse((72, 303, 92, 323), fill="white", outline="#53657c", width=2)
        draw.ellipse((77, 308, 87, 318), fill="#315fa8")
        draw.rectangle((800, 300, 828, 328), fill="white", outline="#16864b", width=3)
        draw.line((806, 314, 813, 321, 824, 306), fill="#16864b", width=4)
        output = BytesIO()
        image.save(output, format="PNG")
        source = positioned_observations(
            [
                ("Which option?", 55, 125),
                ("O A First", 72, 224),
                ("O B Selected", 72, 299),
                ("O C Third", 72, 374),
                ("O D Fourth", 72, 449),
                ("Q Explanation", 55, 520),
                ("Review the source.", 55, 558),
            ]
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
