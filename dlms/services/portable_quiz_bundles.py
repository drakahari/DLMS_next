"""Versioned, validated portable archives for ordinary DLMS quizzes."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import os
import re
import secrets
import shutil
import stat
import tempfile
import time
import unicodedata
import zipfile
from datetime import datetime

from dlms.parsing.external_ai_structured import external_ai_source_url_is_safe
from dlms.services.content_packs import (
    _content_pack_choice_question_errors,
    _matching_record_validation_errors,
    _safe_zip_member_name,
)
from dlms.services.learning import _is_generated_review_source
from dlms.services.question_identity import is_generated_quiz


PORTABLE_QUIZ_BUNDLE_FORMAT = "dlms-portable-quiz-bundle"
PORTABLE_QUIZ_BUNDLE_SCHEMA_VERSION = 1
PORTABLE_QUIZ_BUNDLE_MANIFEST = "dlms-quiz-bundle.json"
PORTABLE_QUIZ_BUNDLE_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
PORTABLE_QUIZ_BUNDLE_ASSET_REF_PREFIX = "dlms-bundle-asset:"

PORTABLE_QUIZ_BUNDLE_UPLOAD_MAX_BYTES = 128 * 1024 * 1024
PORTABLE_QUIZ_BUNDLE_MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
PORTABLE_QUIZ_BUNDLE_MAX_SINGLE_FILE_BYTES = 32 * 1024 * 1024
PORTABLE_QUIZ_BUNDLE_MAX_FILES = 512
PORTABLE_QUIZ_BUNDLE_MAX_QUIZZES = 100
PORTABLE_QUIZ_BUNDLE_MAX_QUESTIONS_PER_QUIZ = 2_000
PORTABLE_QUIZ_BUNDLE_MAX_TOTAL_QUESTIONS = 10_000
PORTABLE_QUIZ_BUNDLE_MAX_MATCHING_PAIRS = 1_000
PORTABLE_QUIZ_BUNDLE_MAX_ASSETS_PER_QUIZ = 100
PORTABLE_QUIZ_BUNDLE_MAX_COMPRESSION_RATIO = 200

_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_TITLE_CHARS = 240
_MAX_FOLDER_CHARS = 120
_MAX_QUESTION_CHARS = 10_000
_MAX_CHOICE_CHARS = 4_000
_MAX_EXPLANATION_CHARS = 20_000
_MAX_CONCEPT_CHARS = 240
_MAX_CONCEPTS = 24
_MAX_SOURCE_CHARS = 1_000
_MAX_URL_CHARS = 2_048
_ALLOWED_DIRECTIONS = {"term_to_definition", "definition_to_term", "random"}
_SOURCE_FIELDS = {"organization", "dataset", "version", "url", "license"}
_MEDIA_FIELDS = {
    "image_url", "image_alt", "image_edits", "image_source",
}
_QUIZ_FIELDS = {
    "bundle_id", "title", "folder", "exam_minutes", "logo", "assets",
    "questions",
}
_QUESTION_COMMON_FIELDS = {
    "number", "source_number", "type", "question", "explanation", "concepts",
    "source", "media",
}
_ASSET_FIELDS = {"path", "sha256", "size", "role"}
_CHOICE_FIELDS = {"label", "text", "is_correct"}
_PAIR_FIELDS = {"left", "right", "category", "explanation", "verification"}


class PortableQuizBundleError(ValueError):
    """A portable bundle is malformed, unsupported, or unsafe."""


class PortableQuizBundleImportError(RuntimeError):
    """A validated bundle could not be imported coherently."""


class _DuplicateJSONKey(ValueError):
    pass


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError(f"nonstandard JSON constant {value!r}")


def _strict_json_loads(payload):
    try:
        return json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKey, ValueError) as exc:
        raise PortableQuizBundleError("Bundle manifest is not strict valid JSON.") from exc


def _normalized_text(value):
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.strip().split())


def _required_text(value, *, label, maximum):
    if not isinstance(value, str):
        raise PortableQuizBundleError(f"{label} must be a text string.")
    cleaned = value.strip()
    if not cleaned:
        raise PortableQuizBundleError(f"{label} must not be empty.")
    if len(cleaned) > maximum:
        raise PortableQuizBundleError(
            f"{label} exceeds the {maximum:,}-character limit."
        )
    return cleaned


def _optional_text(value, *, label, maximum):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PortableQuizBundleError(f"{label} must be a text string.")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise PortableQuizBundleError(
            f"{label} exceeds the {maximum:,}-character limit."
        )
    return normalized


def _exact_fields(value, allowed, *, label):
    if not isinstance(value, dict):
        raise PortableQuizBundleError(f"{label} must be an object.")
    unexpected = set(value) - set(allowed)
    if unexpected:
        raise PortableQuizBundleError(
            f"{label} contains unsupported field {sorted(unexpected)[0]!r}."
        )


def _safe_generic_json(value, *, label, depth=0):
    if depth > 10:
        raise PortableQuizBundleError(f"{label} is nested too deeply.")
    if value is None or isinstance(value, (bool, int)):
        return copy.deepcopy(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PortableQuizBundleError(f"{label} contains a non-finite number.")
        return value
    if isinstance(value, str):
        if len(value) > _MAX_EXPLANATION_CHARS:
            raise PortableQuizBundleError(f"{label} contains oversized text.")
        if value.startswith((
            PORTABLE_QUIZ_BUNDLE_ASSET_REF_PREFIX,
            "/quiz-assets/",
            "/content-packs/",
        )):
            raise PortableQuizBundleError(
                f"{label} contains an asset reference in an unsupported field."
            )
        return value
    if isinstance(value, list):
        if len(value) > 200:
            raise PortableQuizBundleError(f"{label} contains too many list items.")
        return [
            _safe_generic_json(item, label=label, depth=depth + 1)
            for item in value
        ]
    if isinstance(value, dict):
        if len(value) > 40:
            raise PortableQuizBundleError(f"{label} contains too many fields.")
        cleaned = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 120:
                raise PortableQuizBundleError(f"{label} contains an invalid field name.")
            cleaned[key] = _safe_generic_json(
                item, label=label, depth=depth + 1
            )
        return cleaned
    raise PortableQuizBundleError(f"{label} contains an unsupported JSON value.")


def _validate_source(value, *, label):
    if value in (None, {}):
        return {}
    _exact_fields(value, _SOURCE_FIELDS, label=label)
    cleaned = {}
    for field in sorted(_SOURCE_FIELDS):
        maximum = _MAX_URL_CHARS if field == "url" else _MAX_SOURCE_CHARS
        cleaned[field] = _optional_text(
            value.get(field), label=f"{label}.{field}", maximum=maximum
        )
    if cleaned.get("url") and not external_ai_source_url_is_safe(cleaned["url"]):
        raise PortableQuizBundleError(f"{label}.url must use http:// or https://.")
    return {key: item for key, item in cleaned.items() if item}


def _validate_concepts(value, *, label):
    if value is None:
        return []
    if not isinstance(value, list):
        raise PortableQuizBundleError(f"{label} must be a list.")
    if len(value) > _MAX_CONCEPTS:
        raise PortableQuizBundleError(
            f"{label} may contain at most {_MAX_CONCEPTS} concepts."
        )
    cleaned = []
    seen = set()
    for index, raw in enumerate(value, 1):
        concept = _required_text(
            raw, label=f"{label} item {index}", maximum=_MAX_CONCEPT_CHARS
        )
        key = concept.casefold()
        if key in seen:
            raise PortableQuizBundleError(f"{label} contains a duplicate concept.")
        seen.add(key)
        cleaned.append(concept)
    return cleaned


def _asset_ref(path):
    return PORTABLE_QUIZ_BUNDLE_ASSET_REF_PREFIX + path


def _asset_path_from_ref(value, *, label):
    if not isinstance(value, str) or not value.startswith(
        PORTABLE_QUIZ_BUNDLE_ASSET_REF_PREFIX
    ):
        raise PortableQuizBundleError(f"{label} must reference a declared bundle asset.")
    path = value[len(PORTABLE_QUIZ_BUNDLE_ASSET_REF_PREFIX):]
    try:
        normalized = _safe_zip_member_name(path)
    except ValueError as exc:
        raise PortableQuizBundleError(f"{label} contains an unsafe asset path.") from exc
    if path != normalized:
        raise PortableQuizBundleError(f"{label} asset path is not canonical.")
    return path


def _validate_media(value, *, label, asset_references):
    if value in (None, {}):
        return {}
    _exact_fields(value, _MEDIA_FIELDS, label=label)
    cleaned = {}
    if "image_url" in value:
        path = _asset_path_from_ref(value["image_url"], label=f"{label}.image_url")
        asset_references.setdefault(path, set()).add("question-media")
        cleaned["image_url"] = _asset_ref(path)
    if "image_alt" in value:
        cleaned["image_alt"] = _optional_text(
            value["image_alt"], label=f"{label}.image_alt", maximum=_MAX_SOURCE_CHARS
        )
    for field in ("image_edits", "image_source"):
        if field in value:
            cleaned[field] = _safe_generic_json(
                value[field], label=f"{label}.{field}"
            )
    return cleaned


def _validate_choice_question(question, *, context):
    _exact_fields(
        question, _QUESTION_COMMON_FIELDS | {"choices"}, label=context
    )
    choices = question.get("choices")
    errors = _content_pack_choice_question_errors(question, context=context)
    if errors:
        raise PortableQuizBundleError("; ".join(errors))
    cleaned = []
    for index, choice in enumerate(choices):
        _exact_fields(choice, _CHOICE_FIELDS, label=f"{context} choice {index + 1}")
        label = choice.get("label")
        expected = chr(ord("A") + index)
        if label != expected:
            raise PortableQuizBundleError(
                f"{context} choice {index + 1} must use label {expected}."
            )
        cleaned.append({
            "label": label,
            "text": _required_text(
                choice.get("text"),
                label=f"{context} choice {index + 1} text",
                maximum=_MAX_CHOICE_CHARS,
            ),
            "is_correct": choice.get("is_correct"),
        })
    return cleaned


def _validate_matching_question(question, *, context):
    _exact_fields(
        question,
        _QUESTION_COMMON_FIELDS | {"pairs", "round_size", "direction"},
        label=context,
    )
    pairs = question.get("pairs")
    if isinstance(pairs, list) and len(pairs) > PORTABLE_QUIZ_BUNDLE_MAX_MATCHING_PAIRS:
        raise PortableQuizBundleError(
            f"{context} exceeds the {PORTABLE_QUIZ_BUNDLE_MAX_MATCHING_PAIRS:,}-pair limit."
        )
    errors = _matching_record_validation_errors(
        pairs,
        context=context,
        left_key="left",
        right_key="right",
        record_name="pair",
    )
    if errors:
        raise PortableQuizBundleError("; ".join(errors))
    cleaned_pairs = []
    for index, pair in enumerate(pairs):
        pair_label = f"{context} pair {index + 1}"
        _exact_fields(pair, _PAIR_FIELDS, label=pair_label)
        cleaned_pairs.append({
            "left": _required_text(
                pair.get("left"), label=f"{pair_label}.left", maximum=_MAX_CHOICE_CHARS
            ),
            "right": _required_text(
                pair.get("right"), label=f"{pair_label}.right", maximum=_MAX_CHOICE_CHARS
            ),
            "category": _optional_text(
                pair.get("category"), label=f"{pair_label}.category", maximum=_MAX_CONCEPT_CHARS
            ),
            "explanation": _optional_text(
                pair.get("explanation"),
                label=f"{pair_label}.explanation",
                maximum=_MAX_EXPLANATION_CHARS,
            ),
            "verification": _safe_generic_json(
                pair.get("verification") or {}, label=f"{pair_label}.verification"
            ),
        })
    direction = question.get("direction") or "term_to_definition"
    if direction not in _ALLOWED_DIRECTIONS:
        raise PortableQuizBundleError(f"{context} has an unsupported matching direction.")
    round_size = question.get("round_size")
    if round_size is None:
        round_size = len(cleaned_pairs)
    if (
        isinstance(round_size, bool)
        or not isinstance(round_size, int)
        or not 2 <= round_size <= len(cleaned_pairs)
    ):
        raise PortableQuizBundleError(
            f"{context} round_size must be between 2 and the pair count."
        )
    return cleaned_pairs, round_size, direction


def _validate_question(question, *, quiz_number, question_number, asset_references):
    context = f"Quiz {quiz_number}, question {question_number}"
    if not isinstance(question, dict):
        raise PortableQuizBundleError(f"{context} must be an object.")
    qtype = question.get("type") or "choice"
    if qtype not in {"choice", "matching"}:
        raise PortableQuizBundleError(f"{context} has unsupported type {qtype!r}.")
    number = question.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise PortableQuizBundleError(f"{context}.number must be a positive integer.")
    if number != question_number:
        raise PortableQuizBundleError(f"{context}.number must be sequential.")
    source_number = question.get("source_number")
    if source_number is not None and (
        isinstance(source_number, bool)
        or not isinstance(source_number, int)
        or source_number < 1
    ):
        raise PortableQuizBundleError(f"{context}.source_number must be positive.")

    cleaned = {
        "number": number,
        "type": qtype,
        "question": _required_text(
            question.get("question"), label=f"{context}.question", maximum=_MAX_QUESTION_CHARS
        ),
        "explanation": _optional_text(
            question.get("explanation"),
            label=f"{context}.explanation",
            maximum=_MAX_EXPLANATION_CHARS,
        ),
        "concepts": _validate_concepts(
            question.get("concepts") or [], label=f"{context}.concepts"
        ),
        "source": _validate_source(question.get("source") or {}, label=f"{context}.source"),
        "media": _validate_media(
            question.get("media") or {},
            label=f"{context}.media",
            asset_references=asset_references,
        ),
    }
    if source_number is not None:
        cleaned["source_number"] = source_number
    if qtype == "choice":
        cleaned["choices"] = _validate_choice_question(question, context=context)
    else:
        pairs, round_size, direction = _validate_matching_question(
            question, context=context
        )
        cleaned.update({
            "pairs": pairs,
            "round_size": round_size,
            "direction": direction,
        })
    return cleaned


def validate_portable_quiz_bundle_manifest(manifest):
    """Return a canonical manifest or reject all unsupported structure."""
    _exact_fields(
        manifest,
        {"format", "schema_version", "created_at", "created_by", "quizzes"},
        label="Bundle manifest",
    )
    if manifest.get("format") != PORTABLE_QUIZ_BUNDLE_FORMAT:
        raise PortableQuizBundleError("Archive is not a DLMS portable quiz bundle.")
    version = manifest.get("schema_version")
    if isinstance(version, bool) or version != PORTABLE_QUIZ_BUNDLE_SCHEMA_VERSION:
        raise PortableQuizBundleError(
            f"Unsupported portable quiz bundle schema version {version!r}."
        )
    created_at = _required_text(
        manifest.get("created_at"), label="Bundle created_at", maximum=80
    )
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PortableQuizBundleError("Bundle created_at must be an ISO 8601 timestamp.") from exc
    if parsed_created_at.tzinfo is None:
        raise PortableQuizBundleError("Bundle created_at must include a timezone.")
    created_by = manifest.get("created_by")
    _exact_fields(created_by, {"application", "version"}, label="Bundle created_by")
    if created_by.get("application") != "DLMS":
        raise PortableQuizBundleError("Bundle creator must identify DLMS.")
    creator_version = _required_text(
        created_by.get("version"), label="Bundle creator version", maximum=40
    )

    quizzes = manifest.get("quizzes")
    if not isinstance(quizzes, list) or not quizzes:
        raise PortableQuizBundleError("Bundle must contain at least one quiz.")
    if len(quizzes) > PORTABLE_QUIZ_BUNDLE_MAX_QUIZZES:
        raise PortableQuizBundleError(
            f"Bundle contains more than {PORTABLE_QUIZ_BUNDLE_MAX_QUIZZES} quizzes."
        )

    cleaned_quizzes = []
    seen_bundle_ids = set()
    all_asset_declarations = {}
    total_questions = 0
    for quiz_number, quiz in enumerate(quizzes, 1):
        context = f"Quiz {quiz_number}"
        _exact_fields(quiz, _QUIZ_FIELDS, label=context)
        bundle_id = quiz.get("bundle_id")
        if not isinstance(bundle_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,63}", bundle_id
        ):
            raise PortableQuizBundleError(f"{context}.bundle_id is invalid.")
        if bundle_id in seen_bundle_ids:
            raise PortableQuizBundleError("Bundle contains duplicate quiz identifiers.")
        seen_bundle_ids.add(bundle_id)
        title = _required_text(
            quiz.get("title"), label=f"{context}.title", maximum=_MAX_TITLE_CHARS
        )
        folder = _required_text(
            quiz.get("folder") or "Uncategorized",
            label=f"{context}.folder",
            maximum=_MAX_FOLDER_CHARS,
        )
        if any(ord(character) < 32 for character in folder):
            raise PortableQuizBundleError(f"{context}.folder contains control characters.")
        exam_minutes = quiz.get("exam_minutes")
        if (
            isinstance(exam_minutes, bool)
            or not isinstance(exam_minutes, int)
            or not 1 <= exam_minutes <= 1_440
        ):
            raise PortableQuizBundleError(
                f"{context}.exam_minutes must be between 1 and 1440."
            )

        assets = quiz.get("assets")
        if not isinstance(assets, list):
            raise PortableQuizBundleError(f"{context}.assets must be a list.")
        if len(assets) > PORTABLE_QUIZ_BUNDLE_MAX_ASSETS_PER_QUIZ:
            raise PortableQuizBundleError(
                f"{context} contains too many assets."
            )
        cleaned_assets = []
        quiz_assets = {}
        for asset_number, asset in enumerate(assets, 1):
            asset_label = f"{context} asset {asset_number}"
            _exact_fields(asset, _ASSET_FIELDS, label=asset_label)
            path = asset.get("path")
            if not isinstance(path, str):
                raise PortableQuizBundleError(f"{asset_label}.path must be text.")
            try:
                normalized_path = _safe_zip_member_name(path)
            except ValueError as exc:
                raise PortableQuizBundleError(f"{asset_label}.path is unsafe.") from exc
            expected_prefix = f"assets/{bundle_id}/"
            if normalized_path != path or not path.startswith(expected_prefix):
                raise PortableQuizBundleError(
                    f"{asset_label}.path must be beneath {expected_prefix}."
                )
            remainder = path[len(expected_prefix):]
            if not remainder or "/" in remainder:
                raise PortableQuizBundleError(f"{asset_label}.path must name one file.")
            digest = asset.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise PortableQuizBundleError(f"{asset_label}.sha256 is invalid.")
            size = asset.get("size")
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or not 0 < size <= PORTABLE_QUIZ_BUNDLE_MAX_SINGLE_FILE_BYTES
            ):
                raise PortableQuizBundleError(f"{asset_label}.size is invalid.")
            role = asset.get("role")
            if role not in {"question-media", "quiz-logo"}:
                raise PortableQuizBundleError(f"{asset_label}.role is unsupported.")
            key = path.casefold()
            if key in all_asset_declarations:
                raise PortableQuizBundleError(f"Bundle declares duplicate asset path {path!r}.")
            cleaned_asset = {
                "path": path, "sha256": digest, "size": size, "role": role,
            }
            all_asset_declarations[key] = cleaned_asset
            quiz_assets[path] = cleaned_asset
            cleaned_assets.append(cleaned_asset)

        asset_references = {}
        logo = quiz.get("logo")
        if logo is not None:
            logo_path = _asset_path_from_ref(logo, label=f"{context}.logo")
            asset_references.setdefault(logo_path, set()).add("quiz-logo")
            logo = _asset_ref(logo_path)

        questions = quiz.get("questions")
        if not isinstance(questions, list) or not questions:
            raise PortableQuizBundleError(f"{context} must contain questions.")
        if len(questions) > PORTABLE_QUIZ_BUNDLE_MAX_QUESTIONS_PER_QUIZ:
            raise PortableQuizBundleError(
                f"{context} exceeds the per-quiz question limit."
            )
        total_questions += len(questions)
        if total_questions > PORTABLE_QUIZ_BUNDLE_MAX_TOTAL_QUESTIONS:
            raise PortableQuizBundleError("Bundle contains too many total questions.")
        cleaned_questions = [
            _validate_question(
                question,
                quiz_number=quiz_number,
                question_number=number,
                asset_references=asset_references,
            )
            for number, question in enumerate(questions, 1)
        ]

        if set(quiz_assets) != set(asset_references):
            raise PortableQuizBundleError(
                f"{context} assets must be declared exactly once and referenced by content."
            )
        for path, roles in asset_references.items():
            if roles != {quiz_assets[path]["role"]}:
                raise PortableQuizBundleError(
                    f"{context} asset {path!r} is used for the wrong role."
                )

        cleaned_quizzes.append({
            "bundle_id": bundle_id,
            "title": title,
            "folder": folder,
            "exam_minutes": exam_minutes,
            "logo": logo,
            "assets": cleaned_assets,
            "questions": cleaned_questions,
        })

    return {
        "format": PORTABLE_QUIZ_BUNDLE_FORMAT,
        "schema_version": PORTABLE_QUIZ_BUNDLE_SCHEMA_VERSION,
        "created_at": created_at,
        "created_by": {"application": "DLMS", "version": creator_version},
        "quizzes": cleaned_quizzes,
    }


def portable_quiz_export_catalog(
    cur, registry, *, is_generated_source=_is_generated_review_source
):
    """List source quizzes independently of Library visibility, with accounting.

    Content/media validation still runs when the selected archive is built.
    Each Library entry receives one candidate or exclusion reason.
    """
    rows = cur.execute("""
        SELECT z.id, z.title, COALESCE(z.source_file, '') AS source_file,
               z.generation_kind,
               COUNT(q.id) AS question_count,
               SUM(CASE WHEN LOWER(COALESCE(NULLIF(TRIM(q.question_type), ''), 'choice')) NOT IN ('choice', 'matching') THEN 1 ELSE 0 END) AS unsupported_count,
               SUM(CASE WHEN LOWER(COALESCE(NULLIF(TRIM(q.question_type), ''), 'choice')) = 'matching' THEN 1 ELSE 0 END) AS matching_count
        FROM quizzes z
        LEFT JOIN questions q ON q.quiz_id = z.id
        GROUP BY z.id, z.title, z.source_file, z.generation_kind
    """).fetchall()
    rows_by_id = {row["id"]: row for row in rows}
    catalog = []
    excluded_generated_count = 0
    counts = dict(unavailable=0, empty=0, unsupported=0, hidden_included=0)
    seen = set()
    for entry in registry or []:
        try:
            quiz_id = int(entry.get("id"))
        except (AttributeError, TypeError, ValueError):
            counts['unavailable'] += 1
            continue
        if quiz_id in seen:
            counts['unavailable'] += 1
            continue
        seen.add(quiz_id)
        row = rows_by_id.get(quiz_id)
        if row is None:
            counts['unavailable'] += 1
            continue
        generated = is_generated_quiz(
            generation_kind=row["generation_kind"],
            source_file=row["source_file"],
            title=row["title"],
        )
        if is_generated_source is not _is_generated_review_source:
            generated = is_generated_source(row["source_file"], row["title"])
        if generated:
            excluded_generated_count += 1
            continue
        if not int(row['question_count'] or 0):
            counts['empty'] += 1
            continue
        if int(row['unsupported_count'] or 0):
            counts['unsupported'] += 1
            continue
        if entry.get('hidden'):
            counts['hidden_included'] += 1
        catalog.append({
            "quiz_id": quiz_id,
            "title": row["title"],
            "folder": str(entry.get("folder") or "Uncategorized"),
            "question_count": int(row["question_count"] or 0),
            "choice_count": int(row["question_count"] or 0) - int(row["matching_count"] or 0),
            "matching_count": int(row["matching_count"] or 0),
        })
    return {
        "quizzes": catalog, "excluded_generated_count": excluded_generated_count,
        "library_count": len(registry or []), "candidate_count": len(catalog),
        "max_quizzes": PORTABLE_QUIZ_BUNDLE_MAX_QUIZZES,
        **counts,
    }


def _export_media(question, *, add_asset):
    media = {}
    # composition_sources contains installation-local quiz/question IDs. Those
    # identities are not portable and must never be attributed on another DLMS
    # installation; human-readable source metadata and source_number are kept.
    for field in ("image_alt", "image_edits", "image_source"):
        if field in question:
            media[field] = copy.deepcopy(question[field])
    image_url = question.get("image_url")
    if image_url:
        media["image_url"] = _asset_ref(add_asset(image_url, "question-media"))
    return media


def _export_question(question, *, number, add_asset):
    qtype = str(question.get("type") or "choice").strip().lower()
    exported = {
        "number": number,
        "type": qtype,
        "question": question.get("question") or question.get("text") or "",
        "explanation": question.get("explanation") or "",
        "concepts": copy.deepcopy(question.get("concepts") or []),
        "source": copy.deepcopy(question.get("source") or {}),
        "media": _export_media(question, add_asset=add_asset),
    }
    source_number = question.get("source_number")
    original_number = question.get("number")
    if isinstance(source_number, int) and not isinstance(source_number, bool):
        exported["source_number"] = source_number
    elif isinstance(original_number, int) and original_number > 0 and original_number != number:
        exported["source_number"] = original_number
    if qtype == "matching":
        exported.update({
            "pairs": copy.deepcopy(question.get("pairs") or []),
            "round_size": question.get("round_size"),
            "direction": question.get("direction") or "term_to_definition",
        })
    else:
        exported["choices"] = copy.deepcopy(question.get("choices") or [])
    return exported


def build_portable_quiz_bundle(
    cur,
    registry,
    selected_quiz_ids,
    *,
    question_payload_from_db,
    resolve_media_source,
    logo_folder,
    validate_raster_image,
    allowed_image_extensions,
    app_version,
    now=datetime.now,
):
    """Build one self-contained ZIP without changing any source quiz."""
    selected = []
    for raw in selected_quiz_ids or []:
        try:
            quiz_id = int(raw)
        except (TypeError, ValueError):
            raise PortableQuizBundleError("Quiz selection contains an invalid ID.")
        if quiz_id not in selected:
            selected.append(quiz_id)
    if not selected:
        raise PortableQuizBundleError("Select at least one quiz to export.")
    if len(selected) > PORTABLE_QUIZ_BUNDLE_MAX_QUIZZES:
        raise PortableQuizBundleError("Too many quizzes were selected.")

    catalog = portable_quiz_export_catalog(cur, registry)
    allowed = {item["quiz_id"]: item for item in catalog["quizzes"]}
    if any(quiz_id not in allowed for quiz_id in selected):
        raise PortableQuizBundleError(
            "One or more selected quizzes are unavailable or not exportable."
        )
    selected_set = set(selected)
    ordered = [item for item in catalog["quizzes"] if item["quiz_id"] in selected_set]
    registry_by_id = {
        int(entry["id"]): entry
        for entry in registry or []
        if isinstance(entry, dict) and str(entry.get("id") or "").isdigit()
    }

    archive_assets = {}
    quizzes = []
    for quiz_number, catalog_item in enumerate(ordered, 1):
        quiz_id = catalog_item["quiz_id"]
        bundle_id = f"quiz-{quiz_number:03d}"
        declarations = []
        source_to_archive = {}

        def add_asset(reference, role):
            source_path = (
                reference if role == "quiz-logo" else resolve_media_source(reference)
            )
            if not source_path:
                raise PortableQuizBundleError(
                    f"Quiz {catalog_item['title']!r} uses unsupported media {reference!r}."
                )
            real_source = os.path.realpath(source_path)
            if role == "quiz-logo" and os.path.dirname(real_source) != os.path.realpath(logo_folder):
                raise PortableQuizBundleError("A selected quiz logo reference is unsafe.")
            key = (real_source, role)
            if key in source_to_archive:
                return source_to_archive[key]
            if (
                not os.path.isfile(real_source)
                or os.path.islink(source_path)
                or os.path.islink(real_source)
            ):
                raise PortableQuizBundleError("A referenced quiz asset is missing or unsafe.")
            extension = os.path.splitext(real_source)[1].lower()
            if extension not in allowed_image_extensions:
                raise PortableQuizBundleError("A referenced quiz asset type is unsupported.")
            validate_raster_image(real_source, allowed_image_extensions)
            size = os.path.getsize(real_source)
            if not 0 < size <= PORTABLE_QUIZ_BUNDLE_MAX_SINGLE_FILE_BYTES:
                raise PortableQuizBundleError("A referenced quiz asset exceeds the size limit.")
            with open(real_source, "rb") as handle:
                payload = handle.read(PORTABLE_QUIZ_BUNDLE_MAX_SINGLE_FILE_BYTES + 1)
            if len(payload) != size:
                raise PortableQuizBundleError("A referenced quiz asset changed during export.")
            path = f"assets/{bundle_id}/asset-{len(declarations) + 1:03d}{extension}"
            declaration = {
                "path": path,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "role": role,
            }
            declarations.append(declaration)
            archive_assets[path] = payload
            source_to_archive[key] = path
            return path

        question_rows = cur.execute("""
            SELECT id FROM questions
            WHERE quiz_id = ? ORDER BY question_number, id
        """, (quiz_id,)).fetchall()
        if len(question_rows) > PORTABLE_QUIZ_BUNDLE_MAX_QUESTIONS_PER_QUIZ:
            raise PortableQuizBundleError(
                f"Quiz {catalog_item['title']!r} exceeds the bundle question limit."
            )
        questions = []
        for number, row in enumerate(question_rows, 1):
            question = question_payload_from_db(cur, row["id"])
            if not question:
                raise PortableQuizBundleError("A selected source question is unavailable.")
            questions.append(_export_question(question, number=number, add_asset=add_asset))

        entry = registry_by_id[quiz_id]
        logo = None
        logo_name = str(entry.get("logo") or "").strip()
        if logo_name:
            if logo_name != os.path.basename(logo_name):
                raise PortableQuizBundleError("A selected quiz has an unsafe logo reference.")
            logo = _asset_ref(add_asset(os.path.join(logo_folder, logo_name), "quiz-logo"))
        try:
            exam_minutes = int(entry.get("exam_minutes") or 90)
        except (TypeError, ValueError):
            exam_minutes = 90
        quizzes.append({
            "bundle_id": bundle_id,
            "title": catalog_item["title"],
            "folder": catalog_item["folder"],
            "exam_minutes": max(1, min(exam_minutes, 1_440)),
            "logo": logo,
            "assets": declarations,
            "questions": questions,
        })

    timestamp = now().astimezone()
    manifest = validate_portable_quiz_bundle_manifest({
        "format": PORTABLE_QUIZ_BUNDLE_FORMAT,
        "schema_version": PORTABLE_QUIZ_BUNDLE_SCHEMA_VERSION,
        "created_at": timestamp.isoformat(timespec="seconds"),
        "created_by": {"application": "DLMS", "version": str(app_version)},
        "quizzes": quizzes,
    })
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            PORTABLE_QUIZ_BUNDLE_MANIFEST,
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        )
        for path in sorted(archive_assets):
            archive.writestr(path, archive_assets[path])
    safe_name = f"DLMS-Quiz-Bundle-{timestamp.strftime('%Y%m%d')}.zip"
    return output.getvalue(), safe_name, manifest


def _validate_image_payload(payload, path, *, validate_raster_image, allowed_extensions):
    extension = os.path.splitext(path)[1].lower()
    if extension not in allowed_extensions:
        raise PortableQuizBundleError(f"Bundle asset {path!r} has an unsupported type.")
    descriptor, temporary_path = tempfile.mkstemp(suffix=extension)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        validate_raster_image(temporary_path, allowed_extensions)
    except ValueError as exc:
        raise PortableQuizBundleError(f"Bundle asset {path!r} is not a safe image: {exc}") from exc
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass


def inspect_portable_quiz_bundle(
    archive_path,
    *,
    validate_raster_image,
    allowed_image_extensions,
):
    """Validate archive structure, manifest semantics, assets, CRCs, and limits."""
    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise PortableQuizBundleError("Uploaded file is not a valid ZIP archive.") from exc
    with archive:
        infos = archive.infolist()
        if not infos:
            raise PortableQuizBundleError("Bundle ZIP is empty.")
        if len(infos) > PORTABLE_QUIZ_BUNDLE_MAX_FILES:
            raise PortableQuizBundleError("Bundle ZIP contains too many members.")
        seen = set()
        file_infos = {}
        directory_names = set()
        total = 0
        for info in infos:
            try:
                name = _safe_zip_member_name(info.filename)
            except ValueError as exc:
                raise PortableQuizBundleError("Bundle ZIP contains an unsafe path.") from exc
            if name != info.filename.rstrip("/"):
                raise PortableQuizBundleError("Bundle ZIP contains a non-canonical path.")
            key = name.casefold()
            if key in seen:
                raise PortableQuizBundleError(f"Bundle ZIP contains duplicate path {name!r}.")
            seen.add(key)
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            kind = stat.S_IFMT(unix_mode)
            if kind == stat.S_IFLNK or (kind and kind not in {stat.S_IFREG, stat.S_IFDIR}):
                raise PortableQuizBundleError("Bundle ZIP contains a link or special file.")
            if info.flag_bits & 0x1:
                raise PortableQuizBundleError("Encrypted bundle members are not supported.")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise PortableQuizBundleError("Bundle uses an unsupported compression method.")
            if info.is_dir():
                if name != "assets" and not re.fullmatch(r"assets/[a-z0-9][a-z0-9-]{0,63}", name):
                    raise PortableQuizBundleError("Bundle ZIP contains an unexpected directory.")
                directory_names.add(name)
                continue
            size = int(info.file_size or 0)
            total += size
            if size > PORTABLE_QUIZ_BUNDLE_MAX_SINGLE_FILE_BYTES:
                raise PortableQuizBundleError(f"Bundle member {name!r} is too large.")
            if total > PORTABLE_QUIZ_BUNDLE_MAX_UNCOMPRESSED_BYTES:
                raise PortableQuizBundleError("Bundle expands beyond the permitted size limit.")
            compressed = int(info.compress_size or 0)
            if (
                size > 1024 * 1024
                and size / max(1, compressed) > PORTABLE_QUIZ_BUNDLE_MAX_COMPRESSION_RATIO
            ):
                raise PortableQuizBundleError("Bundle contains a suspicious compression ratio.")
            file_infos[name] = info

        manifest_info = file_infos.get(PORTABLE_QUIZ_BUNDLE_MANIFEST)
        if manifest_info is None:
            raise PortableQuizBundleError("Bundle manifest is missing.")
        if manifest_info.file_size > _MAX_MANIFEST_BYTES:
            raise PortableQuizBundleError("Bundle manifest is too large.")
        manifest = validate_portable_quiz_bundle_manifest(
            _strict_json_loads(archive.read(manifest_info))
        )
        declarations = {
            asset["path"]: asset
            for quiz in manifest["quizzes"]
            for asset in quiz["assets"]
        }
        expected_files = {PORTABLE_QUIZ_BUNDLE_MANIFEST, *declarations}
        expected_directories = set()
        if declarations:
            expected_directories.add("assets")
            expected_directories.update(
                path.rsplit("/", 1)[0] for path in declarations
            )
        if not directory_names.issubset(expected_directories):
            raise PortableQuizBundleError("Bundle ZIP contains an unexpected directory.")
        if set(file_infos) != expected_files:
            unexpected = set(file_infos) - expected_files
            missing = expected_files - set(file_infos)
            if unexpected:
                raise PortableQuizBundleError(
                    f"Bundle ZIP contains unexpected file {sorted(unexpected)[0]!r}."
                )
            raise PortableQuizBundleError(
                f"Bundle ZIP is missing declared asset {sorted(missing)[0]!r}."
            )
        for path, declaration in declarations.items():
            payload = archive.read(file_infos[path])
            if len(payload) != declaration["size"]:
                raise PortableQuizBundleError(f"Bundle asset {path!r} has the wrong size.")
            if hashlib.sha256(payload).hexdigest() != declaration["sha256"]:
                raise PortableQuizBundleError(f"Bundle asset {path!r} failed integrity validation.")
            _validate_image_payload(
                payload,
                path,
                validate_raster_image=validate_raster_image,
                allowed_extensions=allowed_image_extensions,
            )
        bad_member = archive.testzip()
        if bad_member:
            raise PortableQuizBundleError(f"Bundle member {bad_member!r} failed CRC validation.")

    return {
        "manifest": manifest,
        "file_count": len(file_infos),
        "uncompressed_bytes": total,
        "quiz_count": len(manifest["quizzes"]),
        "question_count": sum(len(quiz["questions"]) for quiz in manifest["quizzes"]),
        "asset_count": len(declarations),
    }


def portable_quiz_bundle_stage_path(token, *, staging_folder):
    if not PORTABLE_QUIZ_BUNDLE_TOKEN_RE.fullmatch(str(token or "")):
        raise PortableQuizBundleError("Invalid portable bundle import token.")
    return os.path.join(staging_folder, token)


def stage_portable_quiz_bundle(
    upload,
    *,
    content_length,
    staging_folder,
    bounded_save_upload,
    inspect_bundle,
    secure_filename,
    token_hex=secrets.token_hex,
    now=datetime.now,
):
    """Save and validate one uploaded archive for an explicit preview step."""
    if not upload or not upload.filename:
        raise PortableQuizBundleError("Choose a portable quiz bundle ZIP.")
    if not str(upload.filename).lower().endswith(".zip"):
        raise PortableQuizBundleError("Portable quiz bundles must be ZIP files.")
    if content_length and content_length > PORTABLE_QUIZ_BUNDLE_UPLOAD_MAX_BYTES + 2 * 1024 * 1024:
        raise PortableQuizBundleError("Portable quiz bundle exceeds the 128 MB upload limit.")
    token = token_hex(16)
    stage_dir = portable_quiz_bundle_stage_path(token, staging_folder=staging_folder)
    os.makedirs(staging_folder, exist_ok=True)
    os.makedirs(stage_dir, exist_ok=False)
    archive_path = os.path.join(stage_dir, "bundle.zip")
    try:
        bounded_save_upload(
            upload,
            archive_path,
            PORTABLE_QUIZ_BUNDLE_UPLOAD_MAX_BYTES,
            "Portable quiz bundle",
        )
        report = inspect_bundle(archive_path)
        uploaded_name = secure_filename(upload.filename) or "quiz-bundle.zip"
        metadata = {
            "token": token,
            "uploaded_name": uploaded_name[:240],
            "created_at": now().astimezone().isoformat(timespec="seconds"),
            "quiz_count": report["quiz_count"],
            "question_count": report["question_count"],
            "asset_count": report["asset_count"],
        }
        with open(os.path.join(stage_dir, "stage.json"), "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        return token
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def load_staged_portable_quiz_bundle(token, *, staging_folder, inspect_bundle):
    stage_dir = portable_quiz_bundle_stage_path(token, staging_folder=staging_folder)
    metadata_path = os.path.join(stage_dir, "stage.json")
    archive_path = os.path.join(stage_dir, "bundle.zip")
    if not os.path.isfile(metadata_path) or not os.path.isfile(archive_path):
        raise FileNotFoundError("Portable bundle import session is unavailable or expired.")
    with open(metadata_path, "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    if not isinstance(metadata, dict) or metadata.get("token") != token:
        raise PortableQuizBundleError("Portable bundle staging metadata is invalid.")
    return stage_dir, archive_path, metadata, inspect_bundle(archive_path)


def remove_portable_quiz_bundle_stage(token, *, staging_folder):
    try:
        stage_dir = portable_quiz_bundle_stage_path(token, staging_folder=staging_folder)
    except PortableQuizBundleError:
        return
    shutil.rmtree(stage_dir, ignore_errors=True)


def _title_key(title):
    return _normalized_text(title).casefold()


def _collision_title(title, used_titles):
    if _title_key(title) not in used_titles:
        return title, False
    suffix_number = 1
    while True:
        suffix = " (Imported)" if suffix_number == 1 else f" (Imported {suffix_number})"
        base = title[:_MAX_TITLE_CHARS - len(suffix)].rstrip()
        candidate = base + suffix
        if _title_key(candidate) not in used_titles:
            return candidate, True
        suffix_number += 1


def plan_portable_quiz_bundle_import(manifest, existing_titles):
    """Return deterministic collision-safe titles without changing the manifest."""
    used = {_title_key(title) for title in existing_titles}
    plans = []
    for quiz in manifest["quizzes"]:
        import_title, renamed = _collision_title(quiz["title"], used)
        used.add(_title_key(import_title))
        plans.append({
            "bundle_id": quiz["bundle_id"],
            "source_title": quiz["title"],
            "import_title": import_title,
            "renamed": renamed,
            "folder": quiz["folder"],
            "exam_minutes": quiz["exam_minutes"],
            "question_count": len(quiz["questions"]),
            "choice_count": sum(q["type"] == "choice" for q in quiz["questions"]),
            "matching_count": sum(q["type"] == "matching" for q in quiz["questions"]),
            "asset_count": len(quiz["assets"]),
            "quiz": quiz,
        })
    return plans


def _replace_asset_references(value, mapping):
    if isinstance(value, dict):
        return {key: _replace_asset_references(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_asset_references(item, mapping) for item in value]
    if isinstance(value, str) and value.startswith(PORTABLE_QUIZ_BUNDLE_ASSET_REF_PREFIX):
        path = _asset_path_from_ref(value, label="Imported content")
        if path not in mapping:
            raise PortableQuizBundleError("Imported content references an undeclared asset.")
        return mapping[path]
    return copy.deepcopy(value)


def _publication_questions(quiz, asset_urls):
    questions = []
    for source in quiz["questions"]:
        item = {
            "number": source["number"],
            "type": source["type"],
            "question": source["question"],
            "explanation": source["explanation"],
            "concepts": copy.deepcopy(source["concepts"]),
        }
        if source.get("source"):
            item["source"] = copy.deepcopy(source["source"])
        if source.get("source_number") is not None:
            item["source_number"] = source["source_number"]
        for key, value in _replace_asset_references(
            source.get("media") or {}, asset_urls
        ).items():
            item[key] = value
        if source["type"] == "matching":
            item.update({
                "pairs": copy.deepcopy(source["pairs"]),
                "round_size": source["round_size"],
                "direction": source["direction"],
            })
        else:
            item["choices"] = copy.deepcopy(source["choices"])
            item["correct"] = [
                choice["label"] for choice in item["choices"] if choice["is_correct"]
            ]
        questions.append(item)
    return questions


def _prepare_import_logo(source_path, *, logo_folder, validate_raster_image, allowed_extensions):
    extension = os.path.splitext(source_path)[1].lower()
    validate_raster_image(source_path, allowed_extensions)
    os.makedirs(logo_folder, exist_ok=True)
    while True:
        name = f"logo_{int(time.time())}_{secrets.token_hex(4)}{extension}"
        destination = os.path.join(logo_folder, name)
        if not os.path.lexists(destination):
            break
    shutil.copy2(source_path, destination)
    validate_raster_image(destination, allowed_extensions)
    return name


def _cleanup_unpublished_logo(name, *, logo_folder):
    if not name or name != os.path.basename(name):
        return
    path = os.path.join(logo_folder, name)
    if os.path.isfile(path) and not os.path.islink(path):
        os.remove(path)


def install_staged_portable_quiz_bundle(
    token,
    *,
    load_staged_bundle,
    existing_titles,
    quiz_asset_folder,
    logo_folder,
    validate_raster_image,
    allowed_image_extensions,
    publish_quiz,
    set_imported_folders,
    rollback_published_quiz,
    remove_stage,
):
    """Publish a validated batch and compensate every completed item on failure."""
    _stage_dir, archive_path, metadata, report = load_staged_bundle(token)
    plans = plan_portable_quiz_bundle_import(
        report["manifest"], existing_titles()
    )
    source_bucket = f"portable_import_{token[:12]}_{secrets.token_hex(4)}"
    source_root = os.path.join(quiz_asset_folder, source_bucket)
    os.makedirs(quiz_asset_folder, exist_ok=True)
    os.makedirs(source_root, exist_ok=False)
    published = []
    prepared_logos = set()
    try:
        asset_paths = {
            asset["path"]
            for quiz in report["manifest"]["quizzes"]
            for asset in quiz["assets"]
        }
        with zipfile.ZipFile(archive_path, "r") as archive:
            for path in sorted(asset_paths):
                relative = path[len("assets/"):]
                target = os.path.realpath(os.path.join(source_root, relative))
                if not target.startswith(os.path.realpath(source_root) + os.sep):
                    raise PortableQuizBundleError("Bundle asset escaped import staging.")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(path, "r") as source, open(target, "wb") as destination:
                    shutil.copyfileobj(source, destination)
                validate_raster_image(target, allowed_image_extensions)

        for plan in plans:
            quiz = plan["quiz"]
            asset_urls = {
                asset["path"]: (
                    f"/quiz-assets/{source_bucket}/{asset['path'][len('assets/'):]}"
                )
                for asset in quiz["assets"]
            }
            logo_name = None
            if quiz.get("logo"):
                logo_path = _asset_path_from_ref(quiz["logo"], label="Quiz logo")
                relative = logo_path[len("assets/"):]
                logo_name = _prepare_import_logo(
                    os.path.join(source_root, relative),
                    logo_folder=logo_folder,
                    validate_raster_image=validate_raster_image,
                    allowed_extensions=allowed_image_extensions,
                )
                prepared_logos.add(logo_name)
            try:
                quiz_id, html_name = publish_quiz(
                    plan["import_title"],
                    _publication_questions(quiz, asset_urls),
                    filename_prefix="portable_quiz",
                    exam_minutes=plan["exam_minutes"],
                    logo_filename=logo_name,
                    snapshot_existing_assets=True,
                    rollback_logo_filename=logo_name,
                )
            except Exception:
                _cleanup_unpublished_logo(logo_name, logo_folder=logo_folder)
                prepared_logos.discard(logo_name)
                raise
            prepared_logos.discard(logo_name)
            published.append({
                "quiz_id": quiz_id,
                "html": html_name,
                "title": plan["import_title"],
                "source_title": plan["source_title"],
                "folder": plan["folder"],
                "renamed": plan["renamed"],
            })

        set_imported_folders(published)
        remove_stage(token)
        return {"published": published, "metadata": metadata}
    except Exception as original:
        rollback_errors = []
        for item in reversed(published):
            try:
                rollback_published_quiz(item["quiz_id"])
            except Exception as exc:
                rollback_errors.append(exc)
        for logo_name in prepared_logos:
            try:
                _cleanup_unpublished_logo(logo_name, logo_folder=logo_folder)
            except Exception as exc:
                rollback_errors.append(exc)
        if rollback_errors:
            raise PortableQuizBundleImportError(
                "Portable bundle import failed and rollback was incomplete."
            ) from rollback_errors[0]
        raise PortableQuizBundleImportError(
            "Portable bundle import failed; no imported quizzes were kept."
        ) from original
    finally:
        shutil.rmtree(source_root, ignore_errors=True)
