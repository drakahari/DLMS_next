"""Bounded parsing for pasted External AI quiz JSON.

This module intentionally owns syntax extraction and source-neutral
normalization only.  It does not publish quizzes or infer missing content.
"""

from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import urlsplit

from dlms.services.content_packs import _content_pack_choice_question_errors


EXTERNAL_AI_MAX_INPUT_BYTES = 1024 * 1024
EXTERNAL_AI_MAX_NESTING = 14
EXTERNAL_AI_MAX_QUESTIONS = 100
EXTERNAL_AI_MAX_CHOICES = 26
EXTERNAL_AI_MAX_CONCEPTS = 50
EXTERNAL_AI_MAX_OBJECT_MEMBERS = 100
EXTERNAL_AI_MAX_ARRAY_ITEMS = 100
EXTERNAL_AI_MAX_JSON_KEY_CHARS = 240
EXTERNAL_AI_MAX_GENERIC_STRING_CHARS = 100_000
EXTERNAL_AI_MAX_TITLE_CHARS = 240
EXTERNAL_AI_MAX_QUESTION_CHARS = 10_000
EXTERNAL_AI_MAX_CHOICE_CHARS = 4_000
EXTERNAL_AI_MAX_EXPLANATION_CHARS = 20_000
EXTERNAL_AI_MAX_CONCEPT_CHARS = 240
EXTERNAL_AI_MAX_SOURCE_CHARS = 1_000
EXTERNAL_AI_MAX_URL_CHARS = 2_048

_TOP_LEVEL_FIELDS = frozenset({
    "schema_version", "content_type", "title", "source", "questions",
})
_SOURCE_FIELDS = (
    "organization", "dataset", "version", "url", "license",
)
_QUESTION_FIELDS = frozenset({
    "question", "answer_mode", "choices", "explanation", "concepts",
})
_CHOICE_FIELDS = frozenset({"text", "is_correct"})
_FENCED_BLOCK_RE = re.compile(
    r"```(?P<language>[A-Za-z0-9_-]*)[ \t]*\r?\n(?P<body>.*?)```",
    re.DOTALL,
)


class ExternalAIStructuredError(ValueError):
    """Base public parse error with a stable diagnostic code."""

    def __init__(self, message, *, code="invalid_external_ai_response"):
        super().__init__(message)
        self.code = code


class ExternalAIStructuredLimitError(ExternalAIStructuredError):
    """Raised before retaining input that exceeds a resource bound."""


class _DuplicateJSONKey(ValueError):
    pass


class _NonstandardJSONConstant(ValueError):
    pass


def _diagnostic(severity, code, path, message):
    return {
        "severity": severity,
        "code": code,
        "path": path,
        "message": message,
    }


def _normalized_comparison_text(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.split()).casefold()


def _bounded_text(value, *, path, limit):
    if not isinstance(value, str):
        return ""
    if len(value) > limit:
        raise ExternalAIStructuredLimitError(
            f"{path} exceeds the {limit:,}-character limit.",
            code="field_too_long",
        )
    return value.strip()


def _reject_excessive_nesting(text):
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > EXTERNAL_AI_MAX_NESTING:
                raise ExternalAIStructuredLimitError(
                    f"JSON nesting exceeds the {EXTERNAL_AI_MAX_NESTING}-level limit.",
                    code="excessive_nesting",
                )
        elif character in "]}":
            depth = max(0, depth - 1)


def _unique_object(pairs):
    if len(pairs) > EXTERNAL_AI_MAX_OBJECT_MEMBERS:
        raise ExternalAIStructuredLimitError(
            f"A JSON object exceeds the {EXTERNAL_AI_MAX_OBJECT_MEMBERS}-field limit.",
            code="too_many_object_fields",
        )
    result = {}
    for key, value in pairs:
        try:
            key.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ExternalAIStructuredError(
                "A JSON field name contains invalid Unicode.",
                code="invalid_unicode",
            ) from exc
        if len(key) > EXTERNAL_AI_MAX_JSON_KEY_CHARS:
            raise ExternalAIStructuredLimitError(
                f"A JSON field name exceeds the {EXTERNAL_AI_MAX_JSON_KEY_CHARS}-character limit.",
                code="json_key_too_long",
            )
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _reject_loaded_resource_bounds(value):
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ExternalAIStructuredError(
                "A JSON string contains invalid Unicode.",
                code="invalid_unicode",
            ) from exc
        if len(value) > EXTERNAL_AI_MAX_GENERIC_STRING_CHARS:
            raise ExternalAIStructuredLimitError(
                "A JSON string exceeds the general 100,000-character limit.",
                code="json_string_too_long",
            )
        return
    if isinstance(value, list):
        if len(value) > EXTERNAL_AI_MAX_ARRAY_ITEMS:
            raise ExternalAIStructuredLimitError(
                f"A JSON array exceeds the {EXTERNAL_AI_MAX_ARRAY_ITEMS}-item limit.",
                code="too_many_array_items",
            )
        for item in value:
            _reject_loaded_resource_bounds(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            _reject_loaded_resource_bounds(item)


def _extract_json_text(response_text):
    if not isinstance(response_text, str):
        raise ExternalAIStructuredError(
            "The External AI response must be text.", code="response_not_text"
        )
    try:
        byte_count = len(response_text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ExternalAIStructuredError(
            "The External AI response contains invalid Unicode.",
            code="invalid_unicode",
        ) from exc
    if byte_count > EXTERNAL_AI_MAX_INPUT_BYTES:
        raise ExternalAIStructuredLimitError(
            "The External AI response exceeds the 1 MiB paste limit.",
            code="response_too_large",
        )

    stripped = response_text.strip()
    if not stripped:
        raise ExternalAIStructuredError(
            "Paste a JSON response to continue.", code="empty_response"
        )

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    if "```" in stripped:
        matches = list(_FENCED_BLOCK_RE.finditer(stripped))
        if len(matches) != 1 or stripped.count("```") != 2:
            raise ExternalAIStructuredError(
                "Provide exactly one fenced JSON block.",
                code="multiple_or_malformed_fences",
            )
        match = matches[0]
        if match.group("language").casefold() not in {"", "json"}:
            raise ExternalAIStructuredError(
                "The fenced response must be labeled JSON.",
                code="unsupported_fence_language",
            )
        candidate = match.group("body").strip()
        if not candidate:
            raise ExternalAIStructuredError(
                "The fenced JSON block is empty.", code="empty_json_block"
            )
        return candidate

    raise ExternalAIStructuredError(
        "Use bare JSON, or place the JSON in exactly one fenced block. "
        "Unfenced prose mixed with JSON is not accepted.",
        code="mixed_unfenced_content",
    )


def _reject_nonstandard_constant(value):
    raise _NonstandardJSONConstant(value)


def _load_unique_json(json_text):
    _reject_excessive_nesting(json_text)
    try:
        payload = json.loads(
            json_text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonstandard_constant,
        )
    except ExternalAIStructuredError:
        raise
    except _DuplicateJSONKey as exc:
        raise ExternalAIStructuredError(
            f"Duplicate JSON key {str(exc)!r} is not allowed.",
            code="duplicate_json_key",
        ) from exc
    except _NonstandardJSONConstant as exc:
        raise ExternalAIStructuredError(
            f"Nonstandard JSON constant {str(exc)!r} is not allowed.",
            code="nonstandard_json",
        ) from exc
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ExternalAIStructuredError(
            "The External AI response is not valid JSON.", code="malformed_json"
        ) from exc
    if (
        isinstance(payload, dict)
        and isinstance(payload.get("questions"), list)
        and len(payload["questions"]) > EXTERNAL_AI_MAX_QUESTIONS
    ):
        raise ExternalAIStructuredLimitError(
            f"questions exceeds the {EXTERNAL_AI_MAX_QUESTIONS}-question limit.",
            code="too_many_questions",
        )
    _reject_loaded_resource_bounds(payload)
    return payload


def _safe_source_url(value):
    if not value:
        return True
    if len(value) > EXTERNAL_AI_MAX_URL_CHARS:
        raise ExternalAIStructuredLimitError(
            f"source.url exceeds the {EXTERNAL_AI_MAX_URL_CHARS:,}-character limit.",
            code="field_too_long",
        )
    if (
        "\\" in value
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        return False
    try:
        parsed = urlsplit(value)
        # Accessing port also rejects malformed or out-of-range port syntax.
        parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _add_unknown_field_diagnostics(value, allowed, *, path, diagnostics, issues=None):
    if not isinstance(value, dict):
        return
    for name in sorted(set(value) - set(allowed)):
        item = _diagnostic(
            "warning",
            "unknown_field",
            f"{path}.{name}" if path else name,
            f"Unsupported field {name!r} will not be used by DLMS.",
        )
        diagnostics.append(item)
        if issues is not None:
            issues.append(item.copy())


def _normalize_source(source, diagnostics):
    normalized = {name: "" for name in _SOURCE_FIELDS}
    if not isinstance(source, dict):
        diagnostics.append(_diagnostic(
            "error", "invalid_source", "source",
            "source must be an object with provenance fields.",
        ))
        return normalized

    _add_unknown_field_diagnostics(
        source, _SOURCE_FIELDS, path="source", diagnostics=diagnostics
    )
    for name in _SOURCE_FIELDS:
        path = f"source.{name}"
        if name not in source:
            diagnostics.append(_diagnostic(
                "error", "missing_source_field", path,
                f"Required provenance field {name!r} is missing.",
            ))
            continue
        value = source[name]
        if not isinstance(value, str):
            diagnostics.append(_diagnostic(
                "error", "invalid_source_field", path,
                f"{path} must be a string; use an empty string when unknown.",
            ))
            continue
        limit = EXTERNAL_AI_MAX_URL_CHARS if name == "url" else EXTERNAL_AI_MAX_SOURCE_CHARS
        normalized[name] = _bounded_text(value, path=path, limit=limit)
        if name == "url" and not _safe_source_url(normalized[name]):
            diagnostics.append(_diagnostic(
                "error", "unsafe_source_url", path,
                "source.url must be an absolute HTTP or HTTPS URL without credentials.",
            ))
            normalized[name] = ""
    return normalized


def _normalize_question(raw_question, index, diagnostics):
    path = f"questions[{index}]"
    issues = []

    def add_issue(severity, code, suffix, message):
        item = _diagnostic(
            severity, code, f"{path}.{suffix}" if suffix else path, message
        )
        issues.append(item)
        diagnostics.append(item.copy())

    if not isinstance(raw_question, dict):
        add_issue(
            "error", "invalid_question_record", "",
            "Each question must be a JSON object.",
        )
        return {
            "source_index": index,
            "question": "",
            "answer_mode": "",
            "choices": [],
            "proposed_correct_answers": [],
            "explanation": "",
            "concepts": [],
            "validation_issues": issues,
            "correctness_confirmation_required": True,
            "correctness_confirmed": False,
        }

    _add_unknown_field_diagnostics(
        raw_question,
        _QUESTION_FIELDS,
        path=path,
        diagnostics=diagnostics,
        issues=issues,
    )

    question_value = raw_question.get("question")
    if not isinstance(question_value, str) or not question_value.strip():
        add_issue(
            "error", "invalid_question_text", "question",
            "question must be a non-empty string.",
        )
    question_text = _bounded_text(
        question_value,
        path=f"{path}.question",
        limit=EXTERNAL_AI_MAX_QUESTION_CHARS,
    )

    answer_mode = _bounded_text(
        raw_question.get("answer_mode"),
        path=f"{path}.answer_mode",
        limit=16,
    )
    answer_mode = answer_mode.casefold()
    if answer_mode not in {"single", "multiple"}:
        add_issue(
            "error", "invalid_answer_mode", "answer_mode",
            "answer_mode must be exactly 'single' or 'multiple'.",
        )

    raw_choices = raw_question.get("choices")
    if isinstance(raw_choices, list) and len(raw_choices) > EXTERNAL_AI_MAX_CHOICES:
        raise ExternalAIStructuredLimitError(
            f"{path}.choices exceeds the {EXTERNAL_AI_MAX_CHOICES}-choice limit.",
            code="too_many_choices",
        )
    validation_input = {
        "question": question_value,
        "choices": raw_choices,
    }
    for message in _content_pack_choice_question_errors(
        validation_input, context=path
    ):
        add_issue(
            "error", "invalid_choice_question", "choices",
            message.removeprefix(f"{path}: "),
        )

    choices = []
    proposed_correct = []
    if isinstance(raw_choices, list):
        for choice_index, raw_choice in enumerate(raw_choices):
            choice_path = f"{path}.choices[{choice_index}]"
            label = chr(65 + choice_index)
            if not isinstance(raw_choice, dict):
                choices.append({
                    "label": label,
                    "text": "",
                    "proposed_is_correct": None,
                })
                continue
            _add_unknown_field_diagnostics(
                raw_choice,
                _CHOICE_FIELDS,
                path=choice_path,
                diagnostics=diagnostics,
                issues=issues,
            )
            text = _bounded_text(
                raw_choice.get("text"),
                path=f"{choice_path}.text",
                limit=EXTERNAL_AI_MAX_CHOICE_CHARS,
            )
            is_correct = raw_choice.get("is_correct")
            strict_correctness = is_correct if isinstance(is_correct, bool) else None
            choices.append({
                "label": label,
                "text": text,
                "proposed_is_correct": strict_correctness,
            })
            if strict_correctness is True:
                proposed_correct.append(label)

    if answer_mode == "single" and len(proposed_correct) != 1:
        add_issue(
            "error", "single_correct_set_mismatch", "answer_mode",
            "single questions must have exactly one correct choice.",
        )
    elif answer_mode == "multiple" and len(proposed_correct) < 2:
        add_issue(
            "error", "multiple_correct_set_mismatch", "answer_mode",
            "multiple questions must have at least two correct choices.",
        )

    explanation_value = raw_question.get("explanation")
    if not isinstance(explanation_value, str) or not explanation_value.strip():
        add_issue(
            "error", "missing_explanation", "explanation",
            "explanation must be a non-empty string.",
        )
    explanation = _bounded_text(
        explanation_value,
        path=f"{path}.explanation",
        limit=EXTERNAL_AI_MAX_EXPLANATION_CHARS,
    )

    raw_concepts = raw_question.get("concepts")
    concepts = []
    if not isinstance(raw_concepts, list):
        add_issue(
            "error", "invalid_concepts", "concepts",
            "concepts must be an array of non-empty strings.",
        )
    else:
        if len(raw_concepts) > EXTERNAL_AI_MAX_CONCEPTS:
            raise ExternalAIStructuredLimitError(
                f"{path}.concepts exceeds the {EXTERNAL_AI_MAX_CONCEPTS}-item limit.",
                code="too_many_concepts",
            )
        for concept_index, value in enumerate(raw_concepts):
            concept_path = f"{path}.concepts[{concept_index}]"
            if not isinstance(value, str) or not value.strip():
                add_issue(
                    "error", "invalid_concept", f"concepts[{concept_index}]",
                    "Each concept must be a non-empty string.",
                )
                concepts.append("")
                continue
            concepts.append(_bounded_text(
                value,
                path=concept_path,
                limit=EXTERNAL_AI_MAX_CONCEPT_CHARS,
            ))

    return {
        "source_index": index,
        "question": question_text,
        "answer_mode": answer_mode,
        "choices": choices,
        "proposed_correct_answers": proposed_correct,
        "explanation": explanation,
        "concepts": concepts,
        "validation_issues": issues,
        "correctness_confirmation_required": True,
        "correctness_confirmed": False,
    }


def parse_external_ai_quiz_response(response_text):
    """Parse one bounded quiz envelope into a source-neutral review draft.

    Syntax, duplicate-key, and resource-bound failures raise
    :class:`ExternalAIStructuredError`.  Structurally recoverable records are
    retained in order with explicit diagnostics for later Review & Repair.
    """
    payload = _load_unique_json(_extract_json_text(response_text))
    if not isinstance(payload, dict):
        raise ExternalAIStructuredError(
            "The External AI response must contain one JSON object.",
            code="envelope_not_object",
        )

    diagnostics = []
    _add_unknown_field_diagnostics(
        payload, _TOP_LEVEL_FIELDS, path="", diagnostics=diagnostics
    )

    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        diagnostics.append(_diagnostic(
            "error", "unsupported_schema_version", "schema_version",
            "schema_version must be the JSON number 1.",
        ))
    if payload.get("content_type") != "quiz":
        diagnostics.append(_diagnostic(
            "error", "unsupported_content_type", "content_type",
            "content_type must be exactly 'quiz'.",
        ))

    title_value = payload.get("title")
    if not isinstance(title_value, str) or not title_value.strip():
        diagnostics.append(_diagnostic(
            "error", "invalid_title", "title",
            "title must be a non-empty string.",
        ))
    title = _bounded_text(
        title_value, path="title", limit=EXTERNAL_AI_MAX_TITLE_CHARS
    )
    source = _normalize_source(payload.get("source"), diagnostics)

    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        diagnostics.append(_diagnostic(
            "error", "invalid_questions", "questions",
            "questions must be a non-empty array.",
        ))
        raw_questions = []
    if len(raw_questions) > EXTERNAL_AI_MAX_QUESTIONS:
        raise ExternalAIStructuredLimitError(
            f"questions exceeds the {EXTERNAL_AI_MAX_QUESTIONS}-question limit.",
            code="too_many_questions",
        )

    questions = [
        _normalize_question(question, index, diagnostics)
        for index, question in enumerate(raw_questions)
    ]

    seen_questions = {}
    for question_index, question in enumerate(questions):
        normalized = _normalized_comparison_text(question["question"])
        if not normalized:
            continue
        prior_index = seen_questions.get(normalized)
        if prior_index is None:
            seen_questions[normalized] = question_index
            continue
        for duplicate_index, other_index in (
            (question_index, prior_index), (prior_index, question_index),
        ):
            item = _diagnostic(
                "error",
                "duplicate_question",
                f"questions[{duplicate_index}].question",
                f"This duplicates normalized question {other_index + 1}; both records were retained.",
            )
            questions[duplicate_index]["validation_issues"].append(item.copy())
            diagnostics.append(item)

    for question in questions:
        question["validation_state"] = (
            "needs_repair"
            if any(
                item["severity"] == "error"
                for item in question["validation_issues"]
            )
            else "ready_for_review"
        )

    has_errors = any(item["severity"] == "error" for item in diagnostics)
    return {
        "schema_version": 1,
        "content_type": "quiz",
        "title": title,
        "source": source,
        "questions": questions,
        "diagnostics": diagnostics,
        "validation_state": "needs_repair" if has_errors else "ready_for_review",
        "reviewable": bool(questions),
        "correctness_confirmation_required": True,
    }
