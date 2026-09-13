"""Focused DLMS-130 External AI matching/terminology workflow coverage."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.parsing.external_ai_structured import (
    ExternalAIStructuredError,
    ExternalAIStructuredLimitError,
    parse_external_ai_matching_response,
)
from dlms.services import external_ai_structured, question_review
from tests.csrf_test_utils import csrf_token


def _source():
    return {
        "organization": "Neutral Learning Group",
        "dataset": "Terminology notes",
        "version": "1",
        "url": "https://example.org/terms",
        "license": "CC BY 4.0",
    }


def _matching_question(*, pairs=None, **changes):
    value = {
        "question": "Match each neutral term to its definition.",
        "direction": "term_to_definition",
        "round_size": 2,
        "pairs": pairs or [
            {
                "left": "Alpha tool",
                "right": "The first neutral tool",
                "category": "tools",
                "explanation": "The notes define the alpha tool first.",
            },
            {
                "left": "Beta tool",
                "right": "The second neutral tool",
                "category": "tools",
                "explanation": "The notes define the beta tool second.",
            },
        ],
        "explanation": "Match terms using the supplied notes.",
        "concepts": ["neutral terminology"],
    }
    value.update(changes)
    return value


def _envelope(*questions, **changes):
    value = {
        "schema_version": 1,
        "content_type": "matching",
        "title": "Neutral Matching Quiz",
        "source": _source(),
        "questions": list(questions or (_matching_question(),)),
    }
    value.update(changes)
    return value


def _submitted(review, *, confirmed=True):
    return [
        {
            "index": index,
            "number": index + 1,
            "delete": False,
            "question": question["question"],
            "direction": question["direction"],
            "round_size": question["round_size"],
            "pairs": question["pairs"],
            "review_confirmed": confirmed,
            "explanation": question["explanation"],
            "concepts": question["concepts"],
        }
        for index, question in enumerate(review["questions"])
    ]


class ExternalAIMatchingServiceTests(unittest.TestCase):
    def test_matching_prompt_is_bounded_provider_neutral_and_uses_canonical_fields(self):
        prompt = external_ai_structured.build_external_ai_quiz_prompt(
            "Neutral terminology",
            12,
            content_type="matching",
            requested_source=_source(),
        )
        self.assertIn("Create matching/terminology content", prompt)
        self.assertIn('"pair_count": 12', prompt)
        self.assertIn('"content_type": "matching"', prompt)
        self.assertIn('"left": "term string"', prompt)
        self.assertIn('"right": "definition string"', prompt)
        self.assertIn("exactly 12 distinct pairs", prompt)
        self.assertNotIn("API key", prompt)

    def test_valid_response_parses_to_matching_review_records(self):
        parsed = parse_external_ai_matching_response(json.dumps(_envelope()))
        self.assertEqual("matching", parsed["content_type"])
        self.assertEqual("ready_for_review", parsed["validation_state"])
        question = parsed["questions"][0]
        self.assertEqual("term_to_definition", question["direction"])
        self.assertEqual(2, question["round_size"])
        self.assertEqual("Alpha tool", question["pairs"][0]["left"])
        self.assertFalse(question["review_confirmed"])

    def test_malformed_unsupported_and_unexpected_responses_are_safe(self):
        with self.assertRaises(ExternalAIStructuredError):
            parse_external_ai_matching_response('{"content_type":')

        with self.assertRaises(ExternalAIStructuredError):
            parse_external_ai_matching_response(json.dumps(
                _envelope(content_type="flashcards")
            ))

        unexpected = _envelope()
        unexpected["questions"][0]["execute"] = "unexpected"
        with self.assertRaises(ExternalAIStructuredError):
            parse_external_ai_matching_response(json.dumps(unexpected))

    def test_missing_invalid_and_duplicate_pairs_are_blocking_but_repairable(self):
        bad_pairs = [
            {"left": "Repeated", "right": "Shared", "category": "", "explanation": ""},
            {"left": "Repeated", "right": "Shared", "category": "", "explanation": ""},
            {"left": "", "right": 42, "category": [], "explanation": ""},
        ]
        parsed = parse_external_ai_matching_response(json.dumps(_envelope(
            _matching_question(pairs=bad_pairs, round_size="3")
        )))
        self.assertEqual("needs_repair", parsed["validation_state"])
        codes = {item["code"] for item in parsed["diagnostics"]}
        self.assertIn("invalid_matching_pairs", codes)
        self.assertIn("invalid_matching_pair_field", codes)
        self.assertIn("invalid_matching_round_size", codes)
        self.assertEqual(3, len(parsed["questions"][0]["pairs"]))

    def test_pair_and_prompt_count_limits_are_enforced(self):
        with self.assertRaises(ValueError):
            external_ai_structured.build_external_ai_quiz_prompt(
                "Neutral terms", 1, content_type="matching"
            )
        too_many = [
            {"left": f"Term {index}", "right": f"Definition {index}"}
            for index in range(101)
        ]
        with self.assertRaises(ExternalAIStructuredLimitError):
            parse_external_ai_matching_response(json.dumps(_envelope(
                _matching_question(pairs=too_many, round_size=10)
            )))

    def test_review_requires_confirmation_and_revalidates_repaired_pairs(self):
        draft = external_ai_structured.build_external_ai_review_draft(
            json.dumps(_envelope()), content_type="matching"
        )
        blocked = question_review.validate_matching_review_submission(
            draft, _submitted(draft, confirmed=False),
            title=draft["title"], source=draft["source"],
        )
        self.assertTrue(any("explicit confirmation" in item for item in blocked["errors"]))
        self.assertEqual([], blocked["publish_questions"])

        submitted = _submitted(draft)
        submitted[0]["pairs"][1]["left"] = submitted[0]["pairs"][0]["left"]
        duplicated = question_review.validate_matching_review_submission(
            draft, submitted, title=draft["title"], source=draft["source"],
        )
        self.assertTrue(any("one left maps to multiple answers" in item for item in duplicated["errors"]))


class ExternalAIMatchingRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-external-matching-")
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
        for name, value in paths.items():
            patcher = mock.patch.object(dlms, name, str(value))
            patcher.start()
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

    def _stage(self):
        return dlms._stage_external_ai_quiz_response(
            json.dumps(_envelope()), content_type="matching"
        )

    def test_builder_distinguishes_choice_matching_and_zip_workflows(self):
        body = self.client.get("/external-ai/quiz-builder").get_data(as_text=True)
        self.assertIn('name="content_type"', body)
        self.assertIn("Choice questions", body)
        self.assertIn("Matching / terminology", body)
        self.assertIn("AI Study Pack Builder", body)
        self.assertIn("downloadable DLMS Study Pack archive", body)

        token = csrf_token(self.client, "/external-ai/quiz-builder")
        response = self.client.post(
            "/external-ai/quiz-builder/prompt",
            data={
                "csrf_token": token,
                "content_type": "matching",
                "topic": "Neutral terminology",
                "audience": "General learner",
                "difficulty": "Mixed",
                "question_count": "8",
                "source_expectations": "Use reliable neutral notes.",
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("exactly 8 distinct pairs", response.get_data(as_text=True))

    def test_review_renders_matching_editor_and_publication_is_canonical(self):
        draft_id, review = self._stage()
        body = self.client.get(f"/external-ai/review/{draft_id}").get_data(as_text=True)
        self.assertIn("EXTERNAL AI MATCHING · REVIEW", body)
        self.assertIn('data-matching-role="pair-row"', body)
        self.assertIn("confirm every term/definition pairing", body)
        self.assertIn("/static/external-ai-matching-review.js", body)
        self.assertNotIn('data-pdf-role="answer-mode"', body)

        source = review["source"]
        response = self.client.post(
            f"/external-ai/review/{draft_id}/publish",
            data={
                "csrf_token": csrf_token(
                    self.client, f"/external-ai/review/{draft_id}"
                ),
                "quiz_title": review["title"],
                "exam_minutes": "30",
                **{f"source_{name}": source[name] for name in source},
                "review_payload": json.dumps(_submitted(review)),
            },
        )
        self.assertEqual(302, response.status_code)
        quiz_id = int(response.headers["Location"].rsplit("/", 1)[-1])
        connection = dlms.get_db()
        try:
            question = connection.execute(
                "SELECT id, question_type, matching_round_size, matching_direction, "
                "source_organization FROM questions WHERE quiz_id = ?",
                (quiz_id,),
            ).fetchone()
            pairs = connection.execute(
                "SELECT left_text, right_text, category, explanation "
                "FROM matching_pairs WHERE question_id = ? ORDER BY pair_order",
                (question["id"],),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual("matching", question["question_type"])
        self.assertEqual(2, question["matching_round_size"])
        self.assertEqual("term_to_definition", question["matching_direction"])
        self.assertEqual("Neutral Learning Group", question["source_organization"])
        self.assertEqual("Alpha tool", pairs[0]["left_text"])
        self.assertEqual("tools", pairs[0]["category"])
        self.assertFalse(
            Path(dlms.EXTERNAL_AI_DRAFT_FOLDER, f"{draft_id}.json").exists()
        )

    def test_unsupported_content_type_is_not_staged(self):
        raw = json.dumps(_envelope(content_type="unsupported"))
        token = csrf_token(self.client, "/external-ai/quiz-builder")
        response = self.client.post(
            "/external-ai/quiz-builder/validate",
            data={
                "csrf_token": token,
                "content_type": "matching",
                "topic": "Neutral terminology",
                "audience": "General learner",
                "difficulty": "Mixed",
                "question_count": "2",
                "source_expectations": "Use reliable neutral notes.",
                "ai_response": raw,
            },
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("content_type must be exactly", response.get_data(as_text=True))
        self.assertEqual([], list(Path(dlms.EXTERNAL_AI_DRAFT_FOLDER).glob("*.json")))


if __name__ == "__main__":
    unittest.main()
