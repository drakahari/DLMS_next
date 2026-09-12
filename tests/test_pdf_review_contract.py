import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms
from dlms.routes import pdf_import as pdf_routes
from tests.csrf_test_utils import csrf_token


class SmartPDFReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlms-pdf-review-contract-")
        root = Path(self.temp.name)
        self.drafts = root / "drafts"
        self.banks = root / "banks"
        self.patchers = [
            mock.patch.object(dlms, "PDF_IMPORT_DRAFT_FOLDER", str(self.drafts)),
            mock.patch.object(dlms, "PDF_QUESTION_BANK_FOLDER", str(self.banks)),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.client = dlms.app.test_client()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def _draft(self, draft_id, choices, correct="A", **question_fields):
        question = {
            "number": 1,
            "question": "Which choices are correct?",
            "choices": choices,
            "correct": correct,
            "declared_answer_text": "",
            "explanation": "Explanation",
            "choice_feedback": {},
            "pages": [1],
            "status": "complete",
            "issues": [],
        }
        question.update(question_fields)
        draft = {
            "id": draft_id,
            "document_type": "question_bank",
            "source_name": "source.pdf",
            "page_count": 1,
            "quiz_title": "Review Contract",
            "exam_minutes": 30,
            "summary": {"detected": 1, "complete": 1, "review": 0, "incomplete": 0},
            "detection": {"recovery_mode": False},
            "questions": [question],
        }
        dlms._save_pdf_import_draft(draft)
        return draft

    @staticmethod
    def _choices(count):
        return [
            {"label": chr(ord("A") + index), "text": f"Choice {index + 1}"}
            for index in range(count)
        ]

    def _save(self, draft_id, choices, answers, mode="single", **payload_fields):
        payload = {
            "index": 0,
            "delete": False,
            "question": "Which choices are correct?",
            "choices": choices,
            "correct_answers": answers,
            "answer_mode": mode,
            "correctness_confirmed": True,
            "explanation": "Explanation",
            "feedback": {},
        }
        payload.update(payload_fields)
        return self.client.post(
            f"/pdf-import/save/{draft_id}",
            data={
                "quiz_title": "Review Contract",
                "exam_minutes": "30",
                "review_payload": json.dumps([payload]),
                "csrf_token": csrf_token(self.client),
            },
        )

    def _saved_bank(self, response):
        bank_id = response.headers["Location"].rsplit("/", 1)[-1]
        return dlms._load_pdf_question_bank(bank_id)

    def test_legacy_scalar_correct_loads_as_single_answer_without_rewriting_draft(self):
        choices = self._choices(4)
        original = self._draft("legacy_scalar", choices, correct="B")
        before = (self.drafts / "legacy_scalar.json").read_bytes()

        response = self.client.get("/pdf-import/review/legacy_scalar")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('value="single" selected', html)
        self.assertIn('value="B" checked data-pdf-role="single-correct"', html)
        self.assertEqual(before, (self.drafts / "legacy_scalar.json").read_bytes())
        self.assertEqual("B", original["questions"][0]["correct"])

    def test_new_banks_save_list_answers_for_supported_choice_counts(self):
        for count in (2, 6, 8, 26):
            with self.subTest(count=count):
                draft_id = f"choice_count_{count}"
                choices = self._choices(count)
                self._draft(draft_id, choices, correct="A")
                response = self._save(draft_id, choices, ["A"])
                self.assertEqual(response.status_code, 302)
                bank = self._saved_bank(response)
                question = bank["questions"][0]
                self.assertEqual(bank["schema_version"], 2)
                self.assertEqual(len(question["choices"]), count)
                self.assertEqual(question["choices"][-1]["label"], chr(64 + count))
                self.assertEqual(question["correct_answers"], ["A"])
                self.assertNotIn("correct", question)
                runtime = pdf_routes._pdf_bank_question_to_quiz(question, 1, bank)
                self.assertEqual(len(runtime["choices"]), count)
                self.assertEqual(runtime["correct"], ["A"])

    def test_more_than_26_choices_is_rejected_without_truncation_or_bank_save(self):
        draft_choices = self._choices(26)
        self._draft("too_many", draft_choices)
        submitted = draft_choices + [{"label": "AA", "text": "Choice 27"}]
        response = self._save("too_many", submitted, ["A"])
        self.assertTrue(response.headers["Location"].endswith("/pdf-import/review/too_many"))
        self.assertTrue((self.drafts / "too_many.json").exists())
        self.assertEqual([], list(self.banks.glob("*.json")))
        with self.client.session_transaction() as session:
            messages = [message for _category, message in session.get("_flashes", [])]
        self.assertTrue(any("more than 26" in message for message in messages))

    def test_multiple_answer_sets_convert_to_independent_runtime_correctness(self):
        for answers in (["A", "C"], ["A", "C", "F"]):
            with self.subTest(answers=answers):
                question = {
                    "number": 1,
                    "original_number": 1,
                    "question": "Select all.",
                    "choices": self._choices(6),
                    "correct_answers": answers,
                    "answer_mode": "multiple",
                }
                runtime = pdf_routes._pdf_bank_question_to_quiz(
                    question, 1, {"title": "Bank"}
                )
                self.assertEqual(runtime["correct"], answers)
                self.assertEqual(
                    [choice["label"] for choice in runtime["choices"] if choice["is_correct"]],
                    answers,
                )

    def test_legacy_bank_conversion_remains_supported(self):
        question = {
            "number": 1,
            "question": "Legacy?",
            "choices": self._choices(2),
            "correct": "B",
        }
        runtime = pdf_routes._pdf_bank_question_to_quiz(question, 1, {"title": "Legacy"})
        self.assertEqual(runtime["correct"], ["B"])

        self.banks.mkdir(exist_ok=True)
        (self.banks / "legacy.json").write_text(
            json.dumps({"id": "legacy", "questions": [question]}), encoding="utf-8"
        )
        loaded = dlms._load_pdf_question_bank("legacy")
        self.assertEqual(loaded["questions"][0]["correct"], "B")
        self.assertNotIn("correct_answers", loaded["questions"][0])

    def test_reorder_relabels_and_preserves_selected_choice_identity(self):
        choices = [
            {"label": "C", "text": "Third"},
            {"label": "A", "text": "First"},
            {"label": "B", "text": "Second"},
        ]
        self._draft("reordered", self._choices(3), correct="A")
        response = self._save("reordered", choices, ["C"])
        bank = self._saved_bank(response)
        question = bank["questions"][0]
        self.assertEqual(
            question["choices"],
            [
                {"label": "A", "text": "Third"},
                {"label": "B", "text": "First"},
                {"label": "C", "text": "Second"},
            ],
        )
        self.assertEqual(question["correct_answers"], ["A"])

    def test_single_and_multiple_modes_require_a_deliberate_valid_answer_set(self):
        for draft_id, mode, answers, expected in (
            ("single_many", "single", ["A", "B"], "exactly one"),
            ("multiple_one", "multiple", ["A"], "at least two"),
            ("none", "single", [], "at least one"),
        ):
            with self.subTest(mode=mode, answers=answers):
                choices = self._choices(3)
                self._draft(draft_id, choices)
                response = self._save(draft_id, choices, answers, mode=mode)
                self.assertTrue(response.headers["Location"].endswith(f"/pdf-import/review/{draft_id}"))
                with self.client.session_transaction() as session:
                    messages = [message for _category, message in session.get("_flashes", [])]
                self.assertTrue(any(expected in message for message in messages))

    def test_future_confirmation_requirement_is_enforced_but_normal_pdf_is_not_gated(self):
        choices = self._choices(2)
        self._draft(
            "confirmation_required",
            choices,
            correct="A",
            correctness_confirmation_required=True,
            correctness_confirmed=False,
        )
        response = self._save(
            "confirmation_required", choices, ["A"], correctness_confirmed=False
        )
        self.assertTrue(response.headers["Location"].endswith("/pdf-import/review/confirmation_required"))

        self._draft("normal_not_gated", choices, correct="A")
        response = self._save(
            "normal_not_gated", choices, ["A"], correctness_confirmed=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/pdf-import/bank/", response.headers["Location"])

    def test_dynamic_editor_contract_has_add_delete_reorder_and_mode_safeguard(self):
        self._draft("editor_contract", self._choices(2), correct="A")
        html = self.client.get("/pdf-import/review/editor_contract").get_data(as_text=True)
        for token in (
            'data-pdf-action="choice-add"',
            'data-pdf-action="choice-delete"',
            'data-pdf-action="choice-up"',
            'data-pdf-action="choice-down"',
            'data-pdf-role="single-correct"',
            'data-pdf-role="multiple-correct"',
            'id="questionReviewConfirmSelected" disabled',
            'id="questionReviewBulkConfirmationStatus" role="status" aria-live="polite" hidden',
            'id="questionReviewSkippedDetails" hidden',
            'id="questionReviewSkippedList"',
            'data-review-reset-confirmation-on-edit="true"',
            "Choose one correct answer before switching to single-answer mode.",
            'aria-live="polite"',
        ):
            self.assertIn(token, html)

        styles = Path(dlms.resource_path("static/style.css")).read_text(encoding="utf-8")
        editor_styles = styles[
            styles.index(".pdf-choice-editor-row {"):
            styles.index(".pdf-choice-field span")
        ]
        for token in (
            "var(--semantic-section-border)",
            "var(--semantic-section-surface)",
            "var(--theme-page-text",
            "var(--theme-accent",
        ):
            self.assertIn(token, editor_styles)

    def test_correctness_controls_render_only_the_active_mode_enabled(self):
        choices = self._choices(2)
        self._draft("single_controls", choices, correct="A", answer_mode="single")
        single_html = self.client.get(
            "/pdf-import/review/single_controls"
        ).get_data(as_text=True)
        self.assertEqual(0, single_html.count('data-pdf-role="single-correct-control" hidden'))
        self.assertEqual(2, single_html.count('data-pdf-role="multiple-correct-control" hidden'))
        self.assertEqual(2, single_html.count('disabled data-pdf-role="multiple-correct"'))

        self._draft(
            "multiple_controls",
            choices,
            correct=["A", "B"],
            answer_mode="multiple",
        )
        multiple_html = self.client.get(
            "/pdf-import/review/multiple_controls"
        ).get_data(as_text=True)
        self.assertEqual(2, multiple_html.count('data-pdf-role="single-correct-control" hidden'))
        self.assertEqual(0, multiple_html.count('data-pdf-role="multiple-correct-control" hidden'))
        self.assertEqual(2, multiple_html.count('disabled data-pdf-role="single-correct"'))

        styles = Path(dlms.resource_path("static/style.css")).read_text(encoding="utf-8")
        script = Path(dlms.resource_path("static/question-review.js")).read_text(
            encoding="utf-8"
        )
        self.assertIn(".pdf-correctness-controls [hidden] { display:none; }", styles)
        self.assertIn('singleInput.disabled = mode !== "single"', script)
        self.assertIn('multipleInput.disabled = mode !== "multiple"', script)
        self.assertIn("skippedList.replaceChildren()", script)
        self.assertIn("detail.textContent = `Question ${item.number}: ${item.reason}.`", script)


if __name__ == "__main__":
    unittest.main()
