"""DLMS-122 Segment 3 External AI builder entry and transition coverage."""

import html
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


def _question(*, question="Which neutral option comes first?", valid=True):
    return {
        "question": question,
        "answer_mode": "single",
        "choices": [
            {"text": "First neutral option" if valid else "", "is_correct": True},
            {"text": "Second neutral option", "is_correct": False},
        ],
        "explanation": "The neutral source identifies the first option.",
        "concepts": ["ordering"],
    }


def _response_payload(*, valid=True):
    return {
        "schema_version": 1,
        "content_type": "quiz",
        "title": "Neutral Builder Quiz",
        "source": {
            "organization": "Neutral Learning Group",
            "dataset": "Builder fixtures",
            "version": "1",
            "url": "https://example.org/builder",
            "license": "CC BY 4.0",
        },
        "questions": [_question(valid=valid)],
    }


class ExternalAIBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-external-builder-")
        self.addCleanup(self.temporary.cleanup)
        self.draft_root = Path(self.temporary.name) / "external_ai_drafts"
        self.draft_root.mkdir()
        patcher = mock.patch.object(
            dlms, "EXTERNAL_AI_DRAFT_FOLDER", str(self.draft_root)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = dlms.app.test_client()

    def _form(self, *, ai_response="", **changes):
        form = {
            "topic": "Neutral systems",
            "audience": "General learner",
            "difficulty": "Mixed",
            "question_count": "7",
            "source_expectations": "Use the supplied neutral reference.",
            "source_organization": "Neutral Learning Group",
            "source_dataset": "Builder fixtures",
            "source_version": "1",
            "source_url": "https://example.org/builder",
            "source_license": "CC BY 4.0",
            "ai_response": ai_response,
        }
        form.update(changes)
        return form

    def _post(self, path, form):
        form = dict(form)
        form["csrf_token"] = csrf_token(self.client, "/external-ai/quiz-builder")
        return self.client.post(path, data=form)

    def test_build_quiz_has_one_entry_card_and_no_top_level_navigation_item(self):
        body = self.client.get("/upload").get_data(as_text=True)
        self.assertIn("External AI Quiz Builder", body)
        self.assertIn("AI STRUCTURED TEXT", body)
        self.assertEqual(1, body.count('href="/external-ai/quiz-builder"'))
        navigation = body.split('<nav class="dashboard-nav"', 1)[1].split(
            "</nav>", 1
        )[0]
        self.assertNotIn("External AI Quiz Builder", navigation)

    def test_builder_has_labelled_provider_neutral_copy_and_response_controls(self):
        response = self.client.get("/external-ai/quiz-builder")
        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        for required in (
            'name="topic"', 'name="difficulty"', 'name="question_count"',
            'name="source_organization"', 'for="externalAiPrompt"',
            'id="externalAiCopyPrompt"', 'for="externalAiResponse"',
            'name="ai_response"', 'role="status"', "Validate &amp; Review",
            "ChatGPT, Claude, Gemini, a local AI, or another conversational AI",
        ):
            self.assertIn(required, body)
        self.assertIn("does not send anything to an AI service", body)
        self.assertIn("/static/external-ai-builder.js", body)

    def test_builder_uses_component_level_heading_and_control_containment(self):
        body = self.client.get("/external-ai/quiz-builder").get_data(as_text=True)
        self.assertEqual(3, body.count('class="build-section-heading"'))
        self.assertIn(
            '<span class="build-method-label">1 · CONFIGURE</span>',
            body,
        )
        styles = Path(dlms.STATIC_ROOT, "style.css").read_text(encoding="utf-8")
        for rule in (
            ".external-ai-builder-card .build-section-heading {",
            "grid-template-columns: minmax(0, 1fr);",
            ".external-ai-builder-card .build-section-heading > *,",
            ".external-ai-builder-page :where(input:not([type=\"checkbox\"]):not([type=\"radio\"]), select, textarea) {",
        ):
            self.assertIn(rule, styles)

    def test_prompt_generation_uses_segment_one_builder_and_requested_source(self):
        response = self._post(
            "/external-ai/quiz-builder/prompt", self._form(ai_response="retained")
        )
        body = html.unescape(response.get_data(as_text=True))
        self.assertEqual(200, response.status_code)
        self.assertIn("Return exactly 7 questions", body)
        self.assertIn('"organization": "Neutral Learning Group"', body)
        self.assertIn("retained", body)
        self.assertIn("Refresh Prompt", body)
        self.assertIn("Prompt ready to copy.", body)

    def test_question_count_bounds_are_server_enforced_and_form_is_retained(self):
        for count in ("0", "101", "not-a-number"):
            with self.subTest(count=count):
                response = self._post(
                    "/external-ai/quiz-builder/prompt",
                    self._form(question_count=count, ai_response="keep this response"),
                )
                body = response.get_data(as_text=True)
                self.assertEqual(400, response.status_code)
                self.assertIn("Question count", body)
                self.assertIn("keep this response", body)
                self.assertEqual([], list(self.draft_root.glob("*.json")))

    def test_prompt_source_url_is_bounded_and_credential_urls_are_rejected(self):
        response = self._post(
            "/external-ai/quiz-builder/prompt",
            self._form(source_url="https://user:secret@example.org/source"),
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("without credentials", response.get_data(as_text=True))
        self.assertEqual([], list(self.draft_root.glob("*.json")))

    def test_bare_and_single_fenced_json_transition_to_review(self):
        raw_json = json.dumps(_response_payload())
        for raw_response in (raw_json, f"Before\n```json\n{raw_json}\n```\nAfter"):
            with self.subTest(fenced=raw_response != raw_json):
                response = self._post(
                    "/external-ai/quiz-builder/validate",
                    self._form(ai_response=raw_response),
                )
                self.assertEqual(302, response.status_code)
                location = response.headers["Location"]
                self.assertRegex(location, r"^/external-ai/review/[a-f0-9]{32}$")
                draft_id = location.rsplit("/", 1)[-1]
                stored = dlms._load_external_ai_draft(draft_id)
                self.assertEqual(raw_response, stored["raw_response"])
                dlms._delete_external_ai_draft(draft_id)

    def test_invalid_response_is_escaped_retained_and_never_staged(self):
        raw = '<script id="builder-attack">bad()</script> not JSON'
        response = self._post(
            "/external-ai/quiz-builder/validate", self._form(ai_response=raw)
        )
        body = response.get_data(as_text=True)
        self.assertEqual(400, response.status_code)
        self.assertIn('role="alert"', body)
        self.assertIn("&lt;script id=&#34;builder-attack&#34;&gt;", body)
        self.assertNotIn('<script id="builder-attack">', body)
        self.assertEqual([], list(self.draft_root.glob("*.json")))

    def test_oversized_response_is_rejected_without_echo_or_staging(self):
        raw = "x" * (dlms.EXTERNAL_AI_STRUCTURED_MAX_INPUT_BYTES + 1)
        response = self._post(
            "/external-ai/quiz-builder/validate", self._form(ai_response=raw)
        )
        body = response.get_data(as_text=True)
        self.assertEqual(413, response.status_code)
        self.assertIn("exceeds the 1 MiB paste limit", body)
        self.assertNotIn(raw, body)
        self.assertEqual([], list(self.draft_root.glob("*.json")))

    def test_partially_recoverable_response_enters_review_for_repair(self):
        raw = json.dumps(_response_payload(valid=False))
        response = self._post(
            "/external-ai/quiz-builder/validate", self._form(ai_response=raw)
        )
        self.assertEqual(302, response.status_code)
        draft_id = response.headers["Location"].rsplit("/", 1)[-1]
        stored = dlms._load_external_ai_draft(draft_id)
        self.assertEqual("needs_repair", stored["review_draft"]["validation_state"])
        self.assertFalse(
            stored["review_draft"]["questions"][0]["correctness_confirmed"]
        )

    def test_help_explains_manual_flow_safety_and_archive_distinction(self):
        response = self.client.get("/help/external-ai")
        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        for required in (
            "No API key is required", "does not connect to an AI",
            "AI answers may be wrong", "2–26 choices", "multiple-answer",
            "raw AI response is retained only", "AI Study Pack Builder",
            "downloadable DLMS Study Pack archive", "Neither workflow replaces",
        ):
            self.assertIn(required, body)


if __name__ == "__main__":
    unittest.main()
