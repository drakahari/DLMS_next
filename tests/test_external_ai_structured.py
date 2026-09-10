"""Focused contract coverage for DLMS-122 Segment 1."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dlms import prompts
from dlms.parsing.external_ai_structured import (
    EXTERNAL_AI_MAX_INPUT_BYTES,
    ExternalAIStructuredError,
    ExternalAIStructuredLimitError,
    parse_external_ai_quiz_response,
)
from dlms.persistence.external_ai_drafts import (
    create_external_ai_draft,
    delete_external_ai_draft,
    load_external_ai_draft,
    prune_external_ai_drafts,
)
from dlms.services import backups, external_ai_structured as external_ai_service
from dlms.services.external_ai_structured import (
    build_external_ai_quiz_prompt,
    build_external_ai_review_draft,
    external_ai_review_presentation,
    stage_external_ai_quiz_response,
)


def _source(**changes):
    value = {
        "organization": "Neutral Learning Group",
        "dataset": "General study notes",
        "version": "1",
        "url": "https://example.org/notes",
        "license": "CC BY 4.0",
    }
    value.update(changes)
    return value


def _question(
    question="Which item belongs in the blue container?",
    *,
    mode="single",
    choice_count=2,
    correct=(0,),
    **changes,
):
    value = {
        "question": question,
        "answer_mode": mode,
        "choices": [
            {
                "text": f"Neutral option {number + 1}",
                "is_correct": number in correct,
            }
            for number in range(choice_count)
        ],
        "explanation": "The source notes identify the matching item.",
        "concepts": ["classification"],
    }
    value.update(changes)
    return value


def _envelope(*questions, **changes):
    value = {
        "schema_version": 1,
        "content_type": "quiz",
        "title": "Neutral Quiz",
        "source": _source(),
        "questions": list(questions or (_question(),)),
    }
    value.update(changes)
    return value


def _json(payload):
    return json.dumps(payload, ensure_ascii=False)


class ExternalAIParserSyntaxTests(unittest.TestCase):
    def test_accepts_bare_fenced_and_one_fenced_block_with_surrounding_prose(self):
        body = _json(_envelope())
        samples = (
            body,
            f"```json\n{body}\n```",
            f"Here is the requested object.\n```json\n{body}\n```\nEnd.",
        )
        for sample in samples:
            with self.subTest(sample=sample[:20]):
                parsed = parse_external_ai_quiz_response(sample)
                self.assertEqual("ready_for_review", parsed["validation_state"])
                self.assertEqual("A", parsed["questions"][0]["choices"][0]["label"])

    def test_rejects_multiple_fenced_blocks_and_unfenced_mixed_prose(self):
        body = _json(_envelope())
        samples = (
            f"```json\n{body}\n```\n```json\n{body}\n```",
            f"Intro {body}",
            f"{body} trailing prose",
        )
        for sample in samples:
            with self.subTest(sample=sample[:20]):
                with self.assertRaises(ExternalAIStructuredError):
                    parse_external_ai_quiz_response(sample)

    def test_rejects_duplicate_keys_and_malformed_json(self):
        with self.assertRaises(ExternalAIStructuredError) as duplicate:
            parse_external_ai_quiz_response(
                '{"schema_version":1,"schema_version":1}'
            )
        self.assertEqual("duplicate_json_key", duplicate.exception.code)

        with self.assertRaises(ExternalAIStructuredError) as malformed:
            parse_external_ai_quiz_response('{"schema_version": 1,}')
        self.assertEqual("malformed_json", malformed.exception.code)

        with self.assertRaises(ExternalAIStructuredError) as nonstandard:
            parse_external_ai_quiz_response('{"schema_version": NaN}')
        self.assertEqual("nonstandard_json", nonstandard.exception.code)

    def test_bare_json_may_contain_literal_markdown_fence_text(self):
        payload = _envelope(_question(question="What does ``` represent here?"))
        parsed = parse_external_ai_quiz_response(_json(payload))
        self.assertIn("```", parsed["questions"][0]["question"])

    def test_rejects_invalid_unicode_after_json_unescaping(self):
        payload = _envelope(_question(question="Invalid surrogate: \ud800"))
        escaped = json.dumps(payload, ensure_ascii=True)
        with self.assertRaises(ExternalAIStructuredError) as invalid:
            parse_external_ai_quiz_response(escaped)
        self.assertEqual("invalid_unicode", invalid.exception.code)

    def test_rejects_oversized_input_and_excessive_nesting(self):
        oversized = '{"value":"' + ("x" * EXTERNAL_AI_MAX_INPUT_BYTES) + '"}'
        with self.assertRaises(ExternalAIStructuredLimitError) as too_large:
            parse_external_ai_quiz_response(oversized)
        self.assertEqual("response_too_large", too_large.exception.code)

        nested = '{"value":' + ("[" * 15) + "0" + ("]" * 15) + "}"
        with self.assertRaises(ExternalAIStructuredLimitError) as too_deep:
            parse_external_ai_quiz_response(nested)
        self.assertEqual("excessive_nesting", too_deep.exception.code)

        unknown_array = _envelope()
        unknown_array["unsupported"] = list(range(101))
        with self.assertRaises(ExternalAIStructuredLimitError) as too_wide:
            parse_external_ai_quiz_response(_json(unknown_array))
        self.assertEqual("too_many_array_items", too_wide.exception.code)


class ExternalAIParserValidationTests(unittest.TestCase):
    def test_question_and_choice_count_bounds(self):
        for choice_count in (2, 6, 26):
            with self.subTest(choice_count=choice_count):
                parsed = parse_external_ai_quiz_response(
                    _json(_envelope(_question(choice_count=choice_count)))
                )
                self.assertEqual(choice_count, len(parsed["questions"][0]["choices"]))
                self.assertEqual(
                    chr(64 + choice_count),
                    parsed["questions"][0]["choices"][-1]["label"],
                )

        with self.assertRaises(ExternalAIStructuredLimitError) as too_many:
            parse_external_ai_quiz_response(
                _json(_envelope(_question(choice_count=27)))
            )
        self.assertEqual("too_many_choices", too_many.exception.code)

        questions = [
            _question(f"Neutral question {number}?") for number in range(101)
        ]
        with self.assertRaises(ExternalAIStructuredLimitError) as too_many_questions:
            parse_external_ai_quiz_response(_json(_envelope(*questions)))
        self.assertEqual("too_many_questions", too_many_questions.exception.code)

    def test_single_and_multiple_correct_sets_are_proposed_but_unconfirmed(self):
        parsed = parse_external_ai_quiz_response(_json(_envelope(
            _question("Single?", correct=(1,)),
            _question(
                "Multiple?", mode="multiple", choice_count=4, correct=(0, 2)
            ),
        )))
        self.assertEqual(["B"], parsed["questions"][0]["proposed_correct_answers"])
        self.assertEqual(["A", "C"], parsed["questions"][1]["proposed_correct_answers"])
        for question in parsed["questions"]:
            self.assertTrue(question["correctness_confirmation_required"])
            self.assertFalse(question["correctness_confirmed"])

    def test_injected_choice_order_is_applied_before_labels_and_diagnostics(self):
        question = _question(choice_count=3, correct=(0,))
        question["choices"][0]["unsupported_note"] = "diagnostic follows choice"
        parsed = parse_external_ai_quiz_response(
            _json(_envelope(question)),
            choice_shuffler=lambda choices: choices.reverse(),
        )
        normalized = parsed["questions"][0]
        self.assertEqual(
            ["Neutral option 3", "Neutral option 2", "Neutral option 1"],
            [choice["text"] for choice in normalized["choices"]],
        )
        self.assertEqual(["C"], normalized["proposed_correct_answers"])
        self.assertTrue(normalized["choices"][2]["proposed_is_correct"])
        self.assertIn(
            "questions[0].choices[2].unsupported_note",
            {item["path"] for item in parsed["diagnostics"]},
        )

    def test_invalid_mode_and_string_boolean_are_diagnostic_not_inferred(self):
        choices = [
            {"text": "Neutral one", "is_correct": "true"},
            {"text": "Neutral two", "is_correct": False},
        ]
        parsed = parse_external_ai_quiz_response(_json(_envelope(
            _question(mode="pick-one", choices=choices)
        )))
        question = parsed["questions"][0]
        self.assertEqual([], question["proposed_correct_answers"])
        self.assertIsNone(question["choices"][0]["proposed_is_correct"])
        self.assertEqual("needs_repair", parsed["validation_state"])
        codes = {issue["code"] for issue in question["validation_issues"]}
        self.assertIn("invalid_answer_mode", codes)
        self.assertIn("invalid_choice_question", codes)

    def test_duplicate_choices_block_record_and_duplicate_questions_remain_visible(self):
        repeated_choices = [
            {"text": " Same choice ", "is_correct": True},
            {"text": "same   choice", "is_correct": False},
        ]
        parsed = parse_external_ai_quiz_response(_json(_envelope(
            _question("Repeated prompt?", choices=repeated_choices),
            _question("  repeated   PROMPT?  "),
        )))
        self.assertEqual(2, len(parsed["questions"]))
        codes = [item["code"] for item in parsed["diagnostics"]]
        self.assertIn("invalid_choice_question", codes)
        self.assertEqual(2, codes.count("duplicate_question"))
        self.assertTrue(all(
            question["validation_state"] == "needs_repair"
            for question in parsed["questions"]
        ))

    def test_unknown_fields_are_reported_and_not_silently_normalized(self):
        question = _question(extra_record_data="notice me")
        question["choices"][0]["correct_answer"] = True
        payload = _envelope(question, unsupported_envelope_value=3)
        parsed = parse_external_ai_quiz_response(_json(payload))
        paths = {
            item["path"] for item in parsed["diagnostics"]
            if item["code"] == "unknown_field"
        }
        self.assertEqual({
            "unsupported_envelope_value",
            "questions[0].extra_record_data",
            "questions[0].choices[0].correct_answer",
        }, paths)

    def test_unicode_and_script_like_educational_text_remain_literal(self):
        literal = '<script>alert("not executable")</script> café 東京'
        parsed = parse_external_ai_quiz_response(_json(_envelope(
            _question(question=literal, explanation=f"Explain {literal}")
        )))
        self.assertEqual(literal, parsed["questions"][0]["question"])
        self.assertIn(literal, parsed["questions"][0]["explanation"])

    def test_source_urls_are_bounded_http_https_without_credentials(self):
        for unsafe in (
            "javascript:alert(1)",
            "file:///tmp/source",
            "https://user:secret@example.org/source",
            "https://example.org/bad path",
            "https://example.org\\redirect",
        ):
            with self.subTest(url=unsafe):
                parsed = parse_external_ai_quiz_response(
                    _json(_envelope(source=_source(url=unsafe)))
                )
                self.assertEqual("", parsed["source"]["url"])
                self.assertIn(
                    "unsafe_source_url",
                    {item["code"] for item in parsed["diagnostics"]},
                )

        for safe in ("https://example.org/source", "http://localhost:8000/notes"):
            with self.subTest(url=safe):
                parsed = parse_external_ai_quiz_response(
                    _json(_envelope(source=_source(url=safe)))
                )
                self.assertEqual(safe, parsed["source"]["url"])

    def test_envelope_explanation_concepts_and_known_field_lengths_are_validated(self):
        payload = _envelope(
            _question(explanation="", concepts="classification"),
            schema_version=1.0,
            source={"organization": "Neutral Learning Group"},
        )
        parsed = parse_external_ai_quiz_response(_json(payload))
        codes = {item["code"] for item in parsed["diagnostics"]}
        self.assertIn("unsupported_schema_version", codes)
        self.assertIn("missing_source_field", codes)
        self.assertIn("missing_explanation", codes)
        self.assertIn("invalid_concepts", codes)

        with self.assertRaises(ExternalAIStructuredLimitError) as too_long:
            parse_external_ai_quiz_response(_json(_envelope(
                _question(answer_mode="s" * 17)
            )))
        self.assertEqual("field_too_long", too_long.exception.code)


class ExternalAIPromptAndDraftTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-external-ai-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / "external_ai_drafts"

    def test_prompt_has_complete_bounded_contract_and_neutral_example(self):
        prompt = build_external_ai_quiz_prompt("Neutral organization", 7)
        self.assertEqual(1, prompt.count("```json"))
        self.assertEqual(2, prompt.count("```"))
        for required in (
            '"schema_version"', '"content_type"', '"source"',
            '"answer_mode"', '"choices"', '"is_correct"',
            '"explanation"', '"concepts"', "exactly 7 questions",
            "2-26", "true or false", "explicitly confirm correctness",
        ):
            with self.subTest(required=required):
                self.assertIn(required, prompt)
        self.assertIn("Do not use aliases such as correct_answer", prompt)
        self.assertIn("DLMS assigns A-Z labels", prompt)

    def test_existing_archive_prompt_catalog_digest_is_unchanged(self):
        value = prompts.DEFAULT_STUDY_CONTENT_PACK_PROMPT
        self.assertEqual(13882, len(value))
        self.assertEqual(
            "ef7e2980a4d6543841420cbf93ae48baa8a24d8520484a53c7244c9de557cebe",
            hashlib.sha256(value.encode("utf-8")).hexdigest(),
        )

    def test_review_draft_is_source_neutral_and_has_no_raw_or_ocr_fields(self):
        draft = build_external_ai_review_draft(_json(_envelope()))
        self.assertEqual("external_ai_quiz", draft["draft_type"])
        self.assertNotIn("raw_response", draft)
        self.assertFalse(any("ocr" in key.casefold() for key in draft))
        self.assertTrue(draft["correctness_confirmation_required"])

    def test_repeated_drafts_do_not_pin_single_or_multiple_correctness_to_leading_positions(self):
        offsets = iter((0, 0, 1, 1, 2, 2))

        def rotate(choices):
            offset = next(offsets)
            choices[:] = choices[offset:] + choices[:offset]

        payload = _json(_envelope(
            _question("Single position?", choice_count=4, correct=(0,)),
            _question(
                "Multiple positions?",
                mode="multiple",
                choice_count=4,
                correct=(0, 1),
            ),
        ))
        observed_single = set()
        observed_multiple = set()
        for _index in range(3):
            draft = build_external_ai_review_draft(
                payload,
                choice_shuffler=rotate,
            )
            single, multiple = draft["questions"]
            observed_single.add(tuple(single["proposed_correct_answers"]))
            observed_multiple.add(tuple(multiple["proposed_correct_answers"]))
            self.assertEqual(
                {"Neutral option 1"},
                {
                    choice["text"]
                    for choice in single["choices"]
                    if choice["proposed_is_correct"] is True
                },
            )
            self.assertEqual(
                {"Neutral option 1", "Neutral option 2"},
                {
                    choice["text"]
                    for choice in multiple["choices"]
                    if choice["proposed_is_correct"] is True
                },
            )
        self.assertGreater(len(observed_single), 1)
        self.assertGreater(len(observed_multiple), 1)
        self.assertNotEqual({("A",)}, observed_single)
        self.assertNotEqual({("A", "B")}, observed_multiple)

    def test_default_draft_path_invokes_the_secure_choice_shuffler(self):
        def reverse(choices):
            choices.reverse()

        with mock.patch.object(
            external_ai_service,
            "_shuffle_external_ai_choices",
            side_effect=reverse,
        ) as shuffle:
            draft = build_external_ai_review_draft(
                _json(_envelope(_question(choice_count=4, correct=(0,))))
            )
        shuffle.assert_called_once()
        self.assertEqual(["D"], draft["questions"][0]["proposed_correct_answers"])

    def test_review_presentation_preserves_the_one_randomized_order(self):
        raw = _json(_envelope(_question(choice_count=4, correct=(0,))))
        review = build_external_ai_review_draft(
            raw,
            choice_shuffler=lambda choices: choices.reverse(),
        )
        stored = {
            "id": "a" * 32,
            "review_draft": review,
            "raw_response": raw,
        }
        first = external_ai_review_presentation(stored)
        second = external_ai_review_presentation(stored)
        self.assertEqual(first["questions"][0]["choices"], second["questions"][0]["choices"])
        self.assertEqual(["D"], first["questions"][0]["correct_answers"])
        self.assertFalse(first["questions"][0]["correctness_confirmed"])

    def test_transient_save_load_delete_and_strict_ids(self):
        raw = _json(_envelope())
        review = build_external_ai_review_draft(raw)
        draft_id = create_external_ai_draft(
            self.folder,
            review,
            raw,
            token_hex=lambda _bytes: "a" * 32,
            timestamp_now=lambda: "2026-09-10T12:00:00+00:00",
        )
        self.assertEqual("a" * 32, draft_id)
        stored = load_external_ai_draft(self.folder, draft_id)
        self.assertEqual(raw, stored["raw_response"])
        self.assertEqual(review, stored["review_draft"])
        with self.assertRaises(ValueError):
            load_external_ai_draft(self.folder, "../../escape")
        self.assertTrue(delete_external_ai_draft(self.folder, draft_id))
        self.assertFalse(delete_external_ai_draft(self.folder, draft_id))

    def test_stage_retains_partially_recoverable_semantics_but_not_invalid_syntax(self):
        partial = _envelope(_question(explanation=""))
        draft_id, review = stage_external_ai_quiz_response(
            self.folder, _json(partial)
        )
        self.assertEqual("needs_repair", review["validation_state"])
        self.assertTrue((self.folder / f"{draft_id}.json").is_file())

        count_before = len(list(self.folder.iterdir()))
        with self.assertRaises(ExternalAIStructuredError):
            stage_external_ai_quiz_response(self.folder, "not json")
        self.assertEqual(count_before, len(list(self.folder.iterdir())))

    def test_prune_removes_only_abandoned_opaque_drafts(self):
        raw = _json(_envelope())
        review = build_external_ai_review_draft(raw)
        old_id = create_external_ai_draft(
            self.folder, review, raw, token_hex=lambda _bytes: "b" * 32
        )
        current_id = create_external_ai_draft(
            self.folder, review, raw, token_hex=lambda _bytes: "c" * 32
        )
        old_path = self.folder / f"{old_id}.json"
        current_path = self.folder / f"{current_id}.json"
        os.utime(old_path, (1_000, 1_000))
        os.utime(current_path, (100_000, 100_000))
        unrelated = self.folder / "notes.txt"
        unrelated.write_text("keep", encoding="utf-8")

        removed = prune_external_ai_drafts(
            self.folder, stale_seconds=86_400, now=lambda: 100_001
        )
        self.assertEqual(1, removed)
        self.assertFalse(old_path.exists())
        self.assertTrue(current_path.exists())
        self.assertTrue(unrelated.exists())

    def test_transient_root_is_excluded_from_portable_backups(self):
        excluded = {
            ".restore_operations", "backups", "uploads",
            "content_pack_staging", "external_ai_drafts",
        }
        self.assertTrue(backups.backup_rel_is_excluded(
            "external_ai_drafts/private.json",
            data_root_marker=".dlms-data-root",
            excluded_top_level=excluded,
        ))


if __name__ == "__main__":
    unittest.main()
