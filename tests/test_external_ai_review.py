"""DLMS-122 Segment 2 review and canonical-publication coverage."""

import html
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services import external_ai_structured, question_review
from tests.csrf_test_utils import csrf_token


def _source(**changes):
    source = {
        "organization": "Neutral Learning Group",
        "dataset": "General study notes",
        "version": "1",
        "url": "https://example.org/notes",
        "license": "CC BY 4.0",
    }
    source.update(changes)
    return source


def _question(
    text="Which container is labeled for paper?",
    *,
    mode="single",
    count=2,
    correct=(0,),
    explanation="The neutral guide identifies the paper container.",
    concepts=None,
):
    return {
        "question": text,
        "answer_mode": mode,
        "choices": [
            {
                "text": f"Neutral choice {number + 1}",
                "is_correct": number in correct,
            }
            for number in range(count)
        ],
        "explanation": explanation,
        "concepts": concepts or ["sorting"],
    }


def _envelope(*questions, **changes):
    envelope = {
        "schema_version": 1,
        "content_type": "quiz",
        "title": "Neutral External Quiz",
        "source": _source(),
        "questions": list(questions or (_question(),)),
    }
    envelope.update(changes)
    return envelope


def _submitted_questions(review_draft, *, confirmed=True):
    submitted = []
    for index, question in enumerate(review_draft["questions"]):
        submitted.append({
            "index": index,
            "number": index + 1,
            "delete": False,
            "question": question.get("question") or "",
            "choices": [
                {"label": choice["label"], "text": choice.get("text") or ""}
                for choice in question.get("choices") or []
            ],
            "answer_mode": question.get("answer_mode") or "single",
            "correct_answers": question.get("proposed_correct_answers") or [],
            "correctness_confirmed": confirmed,
            "explanation": question.get("explanation") or "",
            "concepts": question.get("concepts") or [],
            "feedback": {},
        })
    return submitted


class QuestionReviewServiceTests(unittest.TestCase):
    def _draft(self, *questions):
        return external_ai_structured.build_external_ai_review_draft(
            json.dumps(_envelope(*questions))
        )

    def _validate(self, draft, submitted):
        return question_review.validate_quiz_review_submission(
            draft,
            submitted,
            title=draft["title"],
            source=draft["source"],
        )

    def test_submitted_review_payload_has_independent_bounds_and_duplicate_keys(self):
        with self.assertRaises(question_review.QuestionReviewPayloadError):
            question_review.parse_question_review_payload(
                '[{"index": 0, "index": 1}]'
            )
        deeply_nested = "value"
        for _index in range(16):
            deeply_nested = [deeply_nested]
        with self.assertRaises(question_review.QuestionReviewPayloadError):
            question_review.parse_question_review_payload(
                json.dumps(deeply_nested)
            )
        with self.assertRaises(question_review.QuestionReviewPayloadError):
            question_review.parse_question_review_payload(
                "x" * (question_review.QUESTION_REVIEW_MAX_PAYLOAD_BYTES + 1)
            )

    def test_supports_2_more_than_5_and_26_choices_with_a_z_labels(self):
        for count in (2, 6, 26):
            with self.subTest(count=count):
                draft = self._draft(_question(count=count))
                submitted = _submitted_questions(draft)
                result = self._validate(draft, submitted)
                self.assertEqual([], result["errors"])
                choices = result["publish_questions"][0]["choices"]
                self.assertEqual(count, len(choices))
                self.assertEqual(chr(64 + count), choices[-1]["label"])

    def test_add_delete_reorder_and_positional_reassignment(self):
        draft = self._draft(_question(count=3, correct=(0,)))
        submitted = _submitted_questions(draft)
        submitted[0]["choices"] = [
            {"label": "A", "text": "Moved third"},
            {"label": "B", "text": "Moved first"},
            {"label": "C", "text": "Added replacement"},
            {"label": "D", "text": "New fourth"},
        ]
        submitted[0]["correct_answers"] = ["B"]
        result = self._validate(draft, submitted)
        self.assertEqual([], result["errors"])
        published = result["publish_questions"][0]
        self.assertEqual(["A", "B", "C", "D"], [c["label"] for c in published["choices"]])
        self.assertEqual("Moved first", published["choices"][1]["text"])
        self.assertTrue(published["choices"][1]["is_correct"])

        submitted[0]["choices"] = submitted[0]["choices"][:2]
        result = self._validate(draft, submitted)
        self.assertEqual([], result["errors"])
        self.assertEqual(2, len(result["publish_questions"][0]["choices"]))

    def test_single_multiple_mode_changes_are_revalidated(self):
        draft = self._draft(_question())
        submitted = _submitted_questions(draft)
        submitted[0]["answer_mode"] = "multiple"
        submitted[0]["correct_answers"] = ["A", "B"]
        multiple = self._validate(draft, submitted)
        self.assertEqual([], multiple["errors"])
        self.assertEqual(["A", "B"], multiple["publish_questions"][0]["correct"])

        submitted[0]["answer_mode"] = "single"
        guarded = self._validate(draft, submitted)
        self.assertTrue(any("exactly one" in error for error in guarded["errors"]))
        self.assertEqual([], guarded["publish_questions"])

        submitted[0]["correct_answers"] = ["B"]
        single = self._validate(draft, submitted)
        self.assertEqual([], single["errors"])
        self.assertEqual(["B"], single["publish_questions"][0]["correct"])

    def test_confirmation_explanation_concepts_and_distinct_choices_are_blocking(self):
        draft = self._draft(_question())
        submitted = _submitted_questions(draft, confirmed=False)
        result = self._validate(draft, submitted)
        self.assertTrue(any("explicit confirmation" in error for error in result["errors"]))

        submitted[0]["correctness_confirmed"] = True
        submitted[0]["explanation"] = ""
        submitted[0]["concepts"] = ["Repeated", "repeated"]
        submitted[0]["choices"][1]["text"] = submitted[0]["choices"][0]["text"]
        result = self._validate(draft, submitted)
        self.assertTrue(any("explanation is required" in error for error in result["errors"]))
        self.assertTrue(any("duplicate concept" in error for error in result["errors"]))
        self.assertTrue(any("duplicate choice text" in error for error in result["errors"]))

    def test_mixed_confirmation_states_are_revalidated_for_every_included_question(self):
        draft = self._draft(
            _question("First independently reviewed question?"),
            _question("Second question still needs repair?"),
            _question("Excluded question?"),
            _question("Unselected question remains unconfirmed?"),
        )
        submitted = _submitted_questions(draft, confirmed=False)
        submitted[0]["correctness_confirmed"] = True
        submitted[1]["choices"][0]["text"] = ""
        submitted[2]["delete"] = True
        submitted[2]["correctness_confirmed"] = True

        blocked = self._validate(draft, submitted)

        self.assertEqual([], blocked["publish_questions"])
        self.assertTrue(any("Question 2 choice A is required" in error for error in blocked["errors"]))
        self.assertTrue(any("Question 4 needs explicit confirmation" in error for error in blocked["errors"]))
        reviewed = blocked["review_draft"]["questions"]
        self.assertTrue(reviewed[0]["correctness_confirmed"])
        self.assertFalse(reviewed[1]["correctness_confirmed"])
        self.assertTrue(reviewed[2]["excluded"])
        self.assertFalse(reviewed[2]["correctness_confirmed"])
        self.assertFalse(reviewed[3]["correctness_confirmed"])

        submitted[1]["choices"][0]["text"] = "Repaired neutral choice"
        submitted[1]["correctness_confirmed"] = True
        submitted[3]["correctness_confirmed"] = True
        publishable = self._validate(draft, submitted)
        self.assertEqual([], publishable["errors"])
        self.assertEqual(3, len(publishable["publish_questions"]))

    def test_source_url_is_revalidated_without_fetching(self):
        draft = self._draft(_question())
        result = question_review.validate_quiz_review_submission(
            draft,
            _submitted_questions(draft),
            title=draft["title"],
            source={**draft["source"], "url": "https://user:secret@example.org/"},
        )
        self.assertTrue(any("without credentials" in error for error in result["errors"]))
        self.assertEqual([], result["publish_questions"])

    def test_duplicate_question_can_be_explicitly_excluded(self):
        draft = self._draft(
            _question("Repeated neutral question?"),
            _question(" repeated  NEUTRAL question? "),
        )
        submitted = _submitted_questions(draft)
        blocked = self._validate(draft, submitted)
        self.assertTrue(any("duplicate question text" in error for error in blocked["errors"]))

        submitted[1]["delete"] = True
        repaired = self._validate(draft, submitted)
        self.assertEqual([], repaired["errors"])
        self.assertEqual(1, len(repaired["publish_questions"]))
        self.assertTrue(repaired["review_draft"]["questions"][1]["excluded"])

    def test_malformed_recoverable_question_can_be_repaired_without_invention(self):
        malformed = _question(text="", count=2, explanation="")
        malformed["choices"][0]["text"] = ""
        draft = self._draft(malformed)
        submitted = _submitted_questions(draft)
        submitted[0].update({
            "question": "Which neutral item is first?",
            "choices": [
                {"label": "A", "text": "First item"},
                {"label": "B", "text": "Second item"},
            ],
            "correct_answers": ["A"],
            "explanation": "The provided ordering identifies the first item.",
            "concepts": ["ordering"],
            "correctness_confirmed": True,
        })
        result = self._validate(draft, submitted)
        self.assertEqual([], result["errors"])
        self.assertEqual("Which neutral item is first?", result["publish_questions"][0]["question"])

    def test_unrepairable_envelope_diagnostic_remains_blocking(self):
        payload = _envelope(_question())
        payload["schema_version"] = 2
        draft = external_ai_structured.build_external_ai_review_draft(
            json.dumps(payload)
        )
        result = self._validate(draft, _submitted_questions(draft))
        self.assertTrue(
            any("Response envelope" in error for error in result["errors"])
        )
        self.assertEqual([], result["publish_questions"])


class ExternalAIReviewRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-external-review-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {
            "APP_DATA_DIR": self.root,
            "EXTERNAL_AI_DRAFT_FOLDER": self.root / "external_ai_drafts",
            "DATA_FOLDER": self.root / "data",
            "QUIZ_FOLDER": self.root / "quizzes",
            "CONFIG_FOLDER": self.root / "config",
            "QUIZ_REGISTRY": self.root / "config" / "quizzes.json",
            "PORTAL_CONFIG": self.root / "config" / "portal.json",
            "DB_PATH": self.root / "results.db",
            "QUIZ_ASSET_FOLDER": self.root / "quiz_assets",
            "LOGO_FOLDER": self.root / "static" / "logos",
            "LOGO_TEMP_FOLDER": self.root / "static" / "logos" / "_temp",
        }
        self.patchers = []
        for name, value in paths.items():
            patcher = mock.patch.object(dlms, name, str(value))
            patcher.start()
            self.patchers.append(patcher)
            self.addCleanup(patcher.stop)
        dlms._initialize_data_root_ownership(str(self.root))
        for name in (
            "EXTERNAL_AI_DRAFT_FOLDER", "DATA_FOLDER", "QUIZ_FOLDER",
            "CONFIG_FOLDER", "QUIZ_ASSET_FOLDER", "LOGO_FOLDER",
            "LOGO_TEMP_FOLDER",
        ):
            Path(getattr(dlms, name)).mkdir(parents=True, exist_ok=True)
        dlms.ensure_db_initialized()
        dlms.save_registry([])
        self.client = dlms.app.test_client()

    def _stage(self, *questions, **envelope_changes):
        raw = json.dumps(
            _envelope(*questions, **envelope_changes), ensure_ascii=False
        )
        draft_id, review = dlms._stage_external_ai_quiz_response(raw)
        return draft_id, review, raw

    def _post(self, draft_id, review, *, submitted=None, **form_changes):
        submitted = submitted or _submitted_questions(review)
        source = review["source"]
        form = {
            "quiz_title": review["title"],
            "exam_minutes": "45",
            "source_organization": source["organization"],
            "source_dataset": source["dataset"],
            "source_version": source["version"],
            "source_url": source["url"],
            "source_license": source["license"],
            "review_payload": json.dumps(submitted, ensure_ascii=False),
            "csrf_token": csrf_token(
                self.client, f"/external-ai/review/{draft_id}"
            ),
        }
        form.update(form_changes)
        return self.client.post(
            f"/external-ai/review/{draft_id}/publish", data=form
        )

    def test_review_is_source_neutral_escaped_and_reference_only(self):
        literal = '<script>window.external_ai_attack = true</script>'
        draft_id, _review, raw = self._stage(
            _question(text=literal), unsupported_field="reported"
        )
        response = self.client.get(f"/external-ai/review/{draft_id}")
        self.assertEqual(200, response.status_code)
        body = response.get_data(as_text=True)
        self.assertIn("EXTERNAL AI QUIZ · REVIEW", body)
        self.assertIn("Raw AI response (reference only)", body)
        self.assertIn("unsupported_field", raw)
        self.assertIn("Unsupported field", body)
        self.assertIn(html.escape(literal), body)
        self.assertNotIn(literal, body)
        for absent in (
            "OCR confidence", "visual result marker", "Unassigned OCR text",
            "Source screenshot", "PDF page preview", "inferred label",
        ):
            self.assertNotIn(absent, body)
        self.assertIn('data-pdf-action="choice-add"', body)
        self.assertIn('data-pdf-action="choice-up"', body)
        self.assertIn('data-pdf-role="concepts"', body)
        self.assertIn("/static/question-review.js", body)
        self.assertIn('id="questionReviewConfirmSelected" disabled', body)
        self.assertIn('id="questionReviewBulkConfirmationStatus" role="status" aria-live="polite"', body)
        self.assertIn('id="questionReviewSkippedDetails" hidden', body)
        self.assertIn('id="questionReviewSkippedSummary"', body)
        self.assertIn('id="questionReviewSkippedList"', body)
        self.assertIn(
            'class="build-secondary-link" id="pdfDeleteSelected">Exclude Selected</button>',
            body,
        )
        self.assertNotIn(
            'class="build-secondary-link pdf-review-danger-action" id="pdfDeleteSelected">Exclude Selected</button>',
            body,
        )
        self.assertNotIn("Confirm All", body)

    def test_review_containment_uses_shared_responsive_choice_geometry(self):
        draft_id, _review, _raw = self._stage(
            _question(
                text="Long neutral question " + ("q" * 600),
                explanation="Long neutral explanation " + ("e" * 800),
            ),
            source={**_source(), "organization": "o" * 800},
        )
        response = self.client.get(f"/external-ai/review/{draft_id}")
        self.assertEqual(200, response.status_code)
        styles = Path(dlms.STATIC_ROOT, "style.css").read_text(encoding="utf-8")
        for selector in (
            ".pdf-choice-editor,",
            ".pdf-import-choice-grid,",
            ".pdf-choice-editor-row > *,",
            ".external-ai-review-page #pdfReviewForm,",
            ".external-ai-review-page .external-ai-source-grid > *,",
        ):
            self.assertIn(selector, styles)
        self.assertIn(
            "grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));",
            styles,
        )
        self.assertIn(
            ".pdf-import-page #pdfDeleteSelected { color:var(--semantic-secondary-control-text)!important;",
            styles,
        )
        self.assertIn(
            ".pdf-import-page .pdf-review-bulk-bar button:not(:disabled):hover,",
            styles,
        )

    def test_review_renders_only_the_active_correctness_control_type(self):
        draft_id, _review, _raw = self._stage(
            _question("Choose one neutral option?", mode="single", correct=(0,)),
            _question("Choose both neutral options?", mode="multiple", correct=(0, 1)),
        )
        body = self.client.get(f"/external-ai/review/{draft_id}").get_data(
            as_text=True
        )

        self.assertEqual(2, body.count('data-pdf-role="single-correct-control" hidden'))
        self.assertEqual(2, body.count('data-pdf-role="multiple-correct-control" hidden'))
        self.assertEqual(2, body.count('disabled data-pdf-role="single-correct"'))
        self.assertEqual(2, body.count('disabled data-pdf-role="multiple-correct"'))

    def test_canonical_publication_creates_single_and_multiple_answer_quiz(self):
        draft_id, review, raw = self._stage(
            _question("Single neutral question?", correct=(1,), concepts=["single concept"]),
            _question(
                "Multiple neutral question?",
                mode="multiple",
                count=4,
                correct=(0, 2),
                concepts=["multiple concept"],
            ),
        )
        expected_correct = [
            question["proposed_correct_answers"]
            for question in review["questions"]
        ]
        response = self._post(draft_id, review)
        self.assertEqual(302, response.status_code)
        quiz_id = int(response.headers["Location"].rsplit("/", 1)[-1])
        self.assertFalse(Path(dlms.EXTERNAL_AI_DRAFT_FOLDER, f"{draft_id}.json").exists())

        connection = dlms.get_db()
        try:
            quiz = connection.execute(
                "SELECT title FROM quizzes WHERE id = ?", (quiz_id,)
            ).fetchone()
            questions = connection.execute(
                "SELECT id, question_number, source_organization, explanation "
                "FROM questions WHERE quiz_id = ? ORDER BY question_number",
                (quiz_id,),
            ).fetchall()
            correct = [
                [row[0] for row in connection.execute(
                    "SELECT label FROM choices WHERE question_id = ? AND is_correct = 1 ORDER BY label",
                    (question["id"],),
                ).fetchall()]
                for question in questions
            ]
            concepts = [row[0] for row in connection.execute(
                "SELECT name FROM concepts ORDER BY name"
            ).fetchall()]
        finally:
            connection.close()
        self.assertEqual("Neutral External Quiz", quiz["title"])
        self.assertEqual(expected_correct, correct)
        self.assertEqual("Neutral Learning Group", questions[0]["source_organization"])
        self.assertEqual(["multiple concept", "single concept"], concepts)

        registry = dlms.load_registry()
        entry = next(item for item in registry if int(item["id"]) == quiz_id)
        self.assertTrue(Path(dlms.QUIZ_FOLDER, entry["html"]).is_file())
        json_files = list(Path(dlms.DATA_FOLDER).glob("external_ai_*.json"))
        self.assertEqual(1, len(json_files))
        durable_text = json_files[0].read_text(encoding="utf-8")
        self.assertNotIn(raw, durable_text)
        self.assertNotIn("raw_response", durable_text)

    def test_validation_failure_preserves_repaired_draft_and_publishes_nothing(self):
        draft_id, review, _raw = self._stage(_question())
        submitted = _submitted_questions(review, confirmed=False)
        submitted[0]["explanation"] = "Edited but not confirmed."
        response = self._post(draft_id, review, submitted=submitted)
        self.assertEqual(302, response.status_code)
        stored = dlms._load_external_ai_draft(draft_id)
        self.assertEqual(
            "Edited but not confirmed.",
            stored["review_draft"]["questions"][0]["explanation"],
        )
        self.assertEqual("needs_repair", stored["review_draft"]["validation_state"])
        connection = dlms.get_db()
        try:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0])
        finally:
            connection.close()

    def test_publication_failure_preserves_latest_reviewed_draft(self):
        draft_id, review, _raw = self._stage(_question())
        submitted = _submitted_questions(review)
        submitted[0]["explanation"] = "Reviewed explanation retained after failure."
        with mock.patch.object(
            dlms, "_publish_quiz", side_effect=RuntimeError("simulated publication failure")
        ):
            response = self._post(draft_id, review, submitted=submitted)
        self.assertEqual(302, response.status_code)
        stored = dlms._load_external_ai_draft(draft_id)
        self.assertEqual(
            "Reviewed explanation retained after failure.",
            stored["review_draft"]["questions"][0]["explanation"],
        )

    def test_start_over_cancel_removes_only_the_transient_draft(self):
        draft_id, _review, _raw = self._stage(_question())
        token = csrf_token(self.client, f"/external-ai/review/{draft_id}")
        response = self.client.post(
            f"/external-ai/review/{draft_id}/cancel",
            data={"csrf_token": token},
        )
        self.assertEqual(302, response.status_code)
        self.assertEqual("/upload", response.headers["Location"])
        self.assertFalse(Path(dlms.EXTERNAL_AI_DRAFT_FOLDER, f"{draft_id}.json").exists())


if __name__ == "__main__":
    unittest.main()
