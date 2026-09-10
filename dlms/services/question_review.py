"""Source-neutral helpers for bounded choice-question Review & Repair."""

from __future__ import annotations

import copy
import json
import unicodedata

from dlms.parsing.external_ai_structured import (
    EXTERNAL_AI_MAX_CHOICE_CHARS,
    EXTERNAL_AI_MAX_EXPLANATION_CHARS,
    EXTERNAL_AI_MAX_QUESTION_CHARS,
    EXTERNAL_AI_MAX_SOURCE_CHARS,
    EXTERNAL_AI_MAX_TITLE_CHARS,
    EXTERNAL_AI_MAX_URL_CHARS,
    external_ai_source_url_is_safe,
)
from dlms.services.content_packs import (
    _content_pack_choice_question_errors,
    _matching_comparison_key,
)


QUESTION_REVIEW_MIN_CHOICES = 2
QUESTION_REVIEW_MAX_CHOICES = 26
QUESTION_REVIEW_MAX_QUESTIONS = 100
QUESTION_REVIEW_MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
QUESTION_REVIEW_MAX_CONCEPTS = 24
QUESTION_REVIEW_MAX_CONCEPT_CHARS = 120
QUESTION_REVIEW_LABELS = tuple(chr(ord("A") + index) for index in range(26))
_SOURCE_FIELDS = ("organization", "dataset", "version", "url", "license")
_UNREPAIRABLE_ENVELOPE_DIAGNOSTIC_CODES = {
    "unsupported_content_type",
    "unsupported_schema_version",
}


class QuestionReviewPayloadError(ValueError):
    """Raised when a submitted editor payload is malformed or unbounded."""


class _DuplicateReviewKey(ValueError):
    pass


def _review_unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateReviewKey(key)
        result[key] = value
    return result


def _review_reject_constant(value):
    raise ValueError(f"Nonstandard JSON constant {value!r}")


def _validate_review_payload_shape(value, *, depth=0):
    if depth > 14:
        raise QuestionReviewPayloadError("Review data is nested too deeply.")
    if isinstance(value, str):
        if len(value) > EXTERNAL_AI_MAX_EXPLANATION_CHARS:
            raise QuestionReviewPayloadError("Review data contains an oversized text field.")
        return
    if isinstance(value, list):
        if len(value) > QUESTION_REVIEW_MAX_QUESTIONS:
            raise QuestionReviewPayloadError("Review data contains too many list items.")
        for item in value:
            _validate_review_payload_shape(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 32:
            raise QuestionReviewPayloadError("Review data contains too many object fields.")
        for key, item in value.items():
            if len(key) > 120:
                raise QuestionReviewPayloadError("Review data contains an oversized field name.")
            _validate_review_payload_shape(item, depth=depth + 1)


def parse_question_review_payload(raw_payload):
    """Parse the hidden editor payload with independent request bounds."""
    if not isinstance(raw_payload, str):
        raise QuestionReviewPayloadError("Review data must be text.")
    try:
        payload_size = len(raw_payload.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise QuestionReviewPayloadError("Review data is not valid UTF-8 text.") from exc
    if payload_size > QUESTION_REVIEW_MAX_PAYLOAD_BYTES:
        raise QuestionReviewPayloadError("Review data exceeds the 2 MiB limit.")
    try:
        payload = json.loads(
            raw_payload,
            object_pairs_hook=_review_unique_object,
            parse_constant=_review_reject_constant,
        )
    except _DuplicateReviewKey as exc:
        raise QuestionReviewPayloadError(
            f"Review data contains duplicate key {str(exc)!r}."
        ) from exc
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise QuestionReviewPayloadError("Review data is not valid JSON.") from exc
    if not isinstance(payload, list):
        raise QuestionReviewPayloadError("Review data must be a list of questions.")
    if len(payload) > QUESTION_REVIEW_MAX_QUESTIONS:
        raise QuestionReviewPayloadError(
            f"Review data may contain at most {QUESTION_REVIEW_MAX_QUESTIONS} questions."
        )
    _validate_review_payload_shape(payload)
    return payload


def choice_question_correct_answers(
    question,
    *,
    answer_keys=("correct_answers", "correct"),
    choice_boolean_keys=(),
):
    """Return ordered A-Z answer labels from one review source record."""
    if not isinstance(question, dict):
        return []
    raw_answers = None
    for key in answer_keys:
        if key not in question:
            continue
        candidate = question.get(key)
        if key.endswith("answers") and not isinstance(candidate, list):
            continue
        raw_answers = candidate
        break
    if raw_answers is None and choice_boolean_keys:
        raw_answers = []
        for index, choice in enumerate(question.get("choices") or []):
            if not isinstance(choice, dict):
                continue
            if any(choice.get(key) is True for key in choice_boolean_keys):
                raw_answers.append(
                    str(choice.get("label") or QUESTION_REVIEW_LABELS[index])
                )
    if not isinstance(raw_answers, list):
        raw_answers = [raw_answers]
    answers = []
    for raw_answer in raw_answers:
        answer = str(raw_answer or "").strip().upper()
        if answer in QUESTION_REVIEW_LABELS and answer not in answers:
            answers.append(answer)
    return answers


def normalize_choice_question_for_review(
    question,
    *,
    answer_keys=("correct_answers", "correct"),
    choice_boolean_keys=(),
):
    """Build the common bounded editor representation without source UI data."""
    normalized = copy.deepcopy(question) if isinstance(question, dict) else {}
    raw_choices = normalized.get("choices") or []
    if not isinstance(raw_choices, list):
        raw_choices = []
    if len(raw_choices) > QUESTION_REVIEW_MAX_CHOICES:
        raise ValueError(
            f"Question {normalized.get('number') or ''} has more than "
            f"{QUESTION_REVIEW_MAX_CHOICES} choices."
        )

    original_answers = set(choice_question_correct_answers(
        normalized,
        answer_keys=answer_keys,
        choice_boolean_keys=choice_boolean_keys,
    ))
    original_feedback = (
        normalized.get("choice_feedback")
        if isinstance(normalized.get("choice_feedback"), dict)
        else {}
    )
    choices = []
    answers = []
    feedback = {}
    for index, raw_choice in enumerate(raw_choices):
        if not isinstance(raw_choice, dict):
            raw_choice = {}
        old_label = str(raw_choice.get("label") or "").strip().upper()
        label = QUESTION_REVIEW_LABELS[index]
        choice = {"label": label, "text": str(raw_choice.get("text") or "")}
        label_origin = str(raw_choice.get("label_origin") or "").strip().lower()
        if label_origin in {"source", "inferred", "manual"}:
            choice["label_origin"] = label_origin
        choices.append(choice)
        if old_label in original_answers:
            answers.append(label)
        note = str(original_feedback.get(old_label) or "")
        if note:
            feedback[label] = note

    while len(choices) < QUESTION_REVIEW_MIN_CHOICES:
        label = QUESTION_REVIEW_LABELS[len(choices)]
        choices.append({"label": label, "text": ""})

    explicit_mode = str(normalized.get("answer_mode") or "").strip().lower()
    answer_mode = (
        explicit_mode
        if explicit_mode in {"single", "multiple"}
        else ("multiple" if len(answers) > 1 else "single")
    )
    confirmation_required = bool(
        normalized.get("correctness_confirmation_required", False)
    )
    normalized.update({
        "choices": choices,
        "correct_answers": answers,
        "answer_mode": answer_mode,
        "choice_feedback": feedback,
        "correctness_confirmation_required": confirmation_required,
        "correctness_confirmed": bool(
            normalized.get("correctness_confirmed", not confirmation_required)
        ),
    })
    return normalized


def submitted_question_at_index(submitted_items, index):
    """Return one uniquely addressed review item, or ``None``."""
    found = []
    for item in submitted_items or []:
        if not isinstance(item, dict):
            continue
        try:
            submitted_index = int(item.get("index", -1))
        except (TypeError, ValueError):
            continue
        if submitted_index == index:
            found.append(item)
    return found[0] if len(found) == 1 else None


def _bounded_review_text(value, *, label, limit, required=False):
    if not isinstance(value, str):
        return "", f"{label} must be text."
    value = value.strip()
    if required and not value:
        return value, f"{label} is required."
    if len(value) > limit:
        return value, f"{label} exceeds the {limit:,}-character limit."
    return value, None


def _review_source(source):
    source = source if isinstance(source, dict) else {}
    normalized = {}
    errors = []
    for name in _SOURCE_FIELDS:
        limit = EXTERNAL_AI_MAX_URL_CHARS if name == "url" else EXTERNAL_AI_MAX_SOURCE_CHARS
        value, error = _bounded_review_text(
            source.get(name), label=f"Source {name}", limit=limit
        )
        normalized[name] = value
        if error:
            errors.append(error)
    if (
        normalized["url"]
        and len(normalized["url"]) <= EXTERNAL_AI_MAX_URL_CHARS
        and not external_ai_source_url_is_safe(normalized["url"])
    ):
        errors.append(
            "Source URL must be an absolute HTTP or HTTPS URL without credentials."
        )
    return normalized, errors


def _review_concepts(value, *, question_number):
    if not isinstance(value, list):
        return [], [f"Question {question_number}: concepts must be a list."]
    if len(value) > QUESTION_REVIEW_MAX_CONCEPTS:
        return list(value), [
            f"Question {question_number}: use no more than "
            f"{QUESTION_REVIEW_MAX_CONCEPTS} concepts."
        ]
    concepts = []
    errors = []
    seen = set()
    for index, raw_concept in enumerate(value, 1):
        concept, error = _bounded_review_text(
            raw_concept,
            label=f"Question {question_number} concept {index}",
            limit=QUESTION_REVIEW_MAX_CONCEPT_CHARS,
            required=True,
        )
        concepts.append(concept)
        if error:
            errors.append(error)
            continue
        key = unicodedata.normalize("NFKC", concept).casefold()
        if key in seen:
            errors.append(
                f"Question {question_number}: duplicate concept {concept!r}."
            )
        seen.add(key)
    return concepts, errors


def validate_quiz_review_submission(draft, submitted_items, *, title, source):
    """Revalidate a complete reviewed quiz and build canonical publish data."""
    original_questions = (
        draft.get("questions") if isinstance(draft, dict) else None
    )
    if not isinstance(original_questions, list) or not original_questions:
        raise QuestionReviewPayloadError("The review draft has no questions.")
    if len(original_questions) > QUESTION_REVIEW_MAX_QUESTIONS:
        raise QuestionReviewPayloadError("The review draft has too many questions.")

    title, title_error = _bounded_review_text(
        title,
        label="Quiz title",
        limit=EXTERNAL_AI_MAX_TITLE_CHARS,
        required=True,
    )
    normalized_source, source_errors = _review_source(source)
    errors = ([title_error] if title_error else []) + source_errors
    for diagnostic in draft.get("diagnostics") or []:
        if (
            isinstance(diagnostic, dict)
            and diagnostic.get("severity") == "error"
            and diagnostic.get("code") in _UNREPAIRABLE_ENVELOPE_DIAGNOSTIC_CODES
        ):
            errors.append(
                "Response envelope: "
                + str(diagnostic.get("message") or "unsupported structured response")
                + " Start Over with a schema_version 1 quiz response."
            )

    if not isinstance(submitted_items, list):
        raise QuestionReviewPayloadError("Review data must be a list.")
    indexes = []
    for item in submitted_items:
        if not isinstance(item, dict) or type(item.get("index")) is not int:
            raise QuestionReviewPayloadError(
                "Every reviewed question must have an integer index."
            )
        indexes.append(item["index"])
    if sorted(indexes) != list(range(len(original_questions))):
        raise QuestionReviewPayloadError(
            "Review data must contain every draft question exactly once."
        )

    reviewed_questions = []
    publish_questions = []
    included_by_text = {}
    included_count = 0
    for index, original in enumerate(original_questions):
        submitted = submitted_question_at_index(submitted_items, index)
        if submitted is None:
            raise QuestionReviewPayloadError(
                "Review data contains an ambiguous question index."
            )
        number = index + 1
        excluded = submitted.get("delete") is True
        question, question_error = _bounded_review_text(
            submitted.get("question"),
            label=f"Question {number} text",
            limit=EXTERNAL_AI_MAX_QUESTION_CHARS,
            required=not excluded,
        )
        explanation, explanation_error = _bounded_review_text(
            submitted.get("explanation"),
            label=f"Question {number} explanation",
            limit=EXTERNAL_AI_MAX_EXPLANATION_CHARS,
            required=not excluded,
        )
        answer_mode = str(submitted.get("answer_mode") or "").strip().lower()
        raw_choices = submitted.get("choices")
        if not isinstance(raw_choices, list):
            raise QuestionReviewPayloadError(
                f"Question {number} choices must be a list."
            )
        if len(raw_choices) > QUESTION_REVIEW_MAX_CHOICES:
            raise QuestionReviewPayloadError(
                f"Question {number} may contain at most "
                f"{QUESTION_REVIEW_MAX_CHOICES} choices."
            )

        choice_errors = []
        choices = []
        for choice_index, raw_choice in enumerate(raw_choices):
            expected_label = QUESTION_REVIEW_LABELS[choice_index]
            if not isinstance(raw_choice, dict):
                choice_errors.append(
                    f"Question {number} choice {expected_label} must be an object."
                )
                raw_choice = {}
            submitted_label = str(raw_choice.get("label") or "").strip().upper()
            if submitted_label != expected_label:
                choice_errors.append(
                    f"Question {number} choices must use positional A-Z labels."
                )
            text, text_error = _bounded_review_text(
                raw_choice.get("text"),
                label=f"Question {number} choice {expected_label}",
                limit=EXTERNAL_AI_MAX_CHOICE_CHARS,
                required=not excluded,
            )
            if text_error:
                choice_errors.append(text_error)
            choices.append({"label": expected_label, "text": text})

        raw_answers = submitted.get("correct_answers")
        if not isinstance(raw_answers, list):
            raise QuestionReviewPayloadError(
                f"Question {number} correct answers must be a list."
            )
        correct_answers = []
        for raw_answer in raw_answers:
            if not isinstance(raw_answer, str):
                choice_errors.append(
                    f"Question {number} correct-answer labels must be text."
                )
                continue
            answer = raw_answer.strip().upper()
            if answer not in {choice["label"] for choice in choices}:
                choice_errors.append(
                    f"Question {number} has an invalid correct-answer label."
                )
            elif answer in correct_answers:
                choice_errors.append(
                    f"Question {number} repeats correct-answer label {answer}."
                )
            else:
                correct_answers.append(answer)

        concepts, concept_errors = _review_concepts(
            submitted.get("concepts", []), question_number=number
        )
        confirmed = submitted.get("correctness_confirmed") is True
        validation_issues = []
        if not excluded:
            included_count += 1
            if question_error:
                validation_issues.append(question_error)
            if explanation_error:
                validation_issues.append(explanation_error)
            validation_issues.extend(choice_errors)
            validation_issues.extend(concept_errors)
            if not QUESTION_REVIEW_MIN_CHOICES <= len(choices) <= QUESTION_REVIEW_MAX_CHOICES:
                validation_issues.append(
                    f"Question {number} needs 2-26 choices."
                )
            if answer_mode not in {"single", "multiple"}:
                validation_issues.append(
                    f"Question {number} answer mode must be single or multiple."
                )
            elif answer_mode == "single" and len(correct_answers) != 1:
                validation_issues.append(
                    f"Question {number} needs exactly one correct answer in single-answer mode."
                )
            elif answer_mode == "multiple" and len(correct_answers) < 2:
                validation_issues.append(
                    f"Question {number} needs at least two correct answers in multiple-answer mode."
                )
            if not confirmed:
                validation_issues.append(
                    f"Question {number} needs explicit confirmation of the complete correct-answer set."
                )

            validation_input = {
                "question": question,
                "choices": [
                    {
                        "text": choice["text"],
                        "is_correct": choice["label"] in correct_answers,
                    }
                    for choice in choices
                ],
            }
            for message in _content_pack_choice_question_errors(
                validation_input,
                context=f"Question {number}",
                matching_comparison_key=_matching_comparison_key,
            ):
                clean = message.removeprefix(f"Question {number}: ")
                full = f"Question {number}: {clean}"
                if full not in validation_issues:
                    validation_issues.append(full)

        reviewed = copy.deepcopy(original) if isinstance(original, dict) else {}
        reviewed.update({
            "source_index": index,
            "number": number,
            "question": question,
            "answer_mode": answer_mode,
            "choices": [
                {
                    **choice,
                    "proposed_is_correct": choice["label"] in correct_answers,
                }
                for choice in choices
            ],
            "proposed_correct_answers": correct_answers,
            "explanation": explanation,
            "concepts": concepts,
            "validation_issues": [
                {
                    "severity": "error",
                    "code": "review_validation",
                    "path": f"questions[{index}]",
                    "message": message,
                }
                for message in validation_issues
            ],
            "correctness_confirmation_required": True,
            "correctness_confirmed": confirmed,
            "excluded": excluded,
            "validation_state": (
                "excluded" if excluded else
                "needs_repair" if validation_issues else
                "ready_for_review"
            ),
        })
        reviewed_questions.append(reviewed)
        errors.extend(validation_issues)

        if not excluded and not validation_issues:
            comparison_key = _matching_comparison_key(question)
            prior = included_by_text.get(comparison_key)
            if prior is not None:
                duplicate_message = (
                    f"Questions {prior + 1} and {number} have duplicate question text; "
                    "edit or exclude one."
                )
                errors.append(duplicate_message)
                for duplicate_index in (prior, index):
                    reviewed_questions[duplicate_index]["validation_issues"].append({
                        "severity": "error",
                        "code": "duplicate_question",
                        "path": f"questions[{duplicate_index}].question",
                        "message": duplicate_message,
                    })
                    reviewed_questions[duplicate_index]["validation_state"] = "needs_repair"
            else:
                included_by_text[comparison_key] = index

            publish_questions.append({
                "number": len(publish_questions) + 1,
                "type": "choice",
                "question": question,
                "answer_mode": answer_mode,
                "choices": [
                    {
                        "label": choice["label"],
                        "text": choice["text"],
                        "is_correct": choice["label"] in correct_answers,
                    }
                    for choice in choices
                ],
                "correct": correct_answers,
                "explanation": explanation,
                "concepts": concepts,
                "source": normalized_source,
            })

    if included_count == 0:
        errors.append("Keep at least one valid question before publishing.")

    updated_draft = copy.deepcopy(draft)
    updated_draft.update({
        "title": title,
        "source": normalized_source,
        "questions": reviewed_questions,
        "validation_state": "needs_repair" if errors else "ready_for_publication",
        "correctness_confirmation_required": True,
    })
    return {
        "review_draft": updated_draft,
        "publish_questions": publish_questions if not errors else [],
        "errors": errors,
        "warnings": [
            diagnostic
            for diagnostic in (draft.get("diagnostics") or [])
            if isinstance(diagnostic, dict)
            and diagnostic.get("severity") == "warning"
        ],
    }
