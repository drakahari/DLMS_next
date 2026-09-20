"""Canonical question identity and generated-copy lineage helpers.

Contract v2 gives newly-created questions an installation-local durable UID and
records explicit source/canonical relationships for generated copies.  Rows
created before schema v3 deliberately retain the historical normalized
type/text identity as a conservative fallback; this module never guesses a
lineage from matching text alone.
"""

import re
import uuid


QUESTION_UID_RE = re.compile(r"^[0-9a-f]{32}$")
SOURCE_QUIZ_KIND = "source"
GENERATED_QUIZ_KINDS = frozenset({
    "adaptive_study",
    "concept_review",
    "mixed_quiz",
    "native_spaced_review",
    "smart_review",
    "spaced_review",
})
TRANSIENT_REVIEW_KINDS = GENERATED_QUIZ_KINDS - {"mixed_quiz"}
LEGACY_GENERATED_SOURCE_KINDS = (
    ("spaced_review_native_", "native_spaced_review"),
    ("smart_review_", "smart_review"),
    ("spaced_review_", "spaced_review"),
    ("concept_review_", "concept_review"),
    ("adaptive_study_", "adaptive_study"),
    ("mixed_quiz_", "mixed_quiz"),
)
LEGACY_GENERATED_TITLE_KINDS = (
    ("native due review —", "native_spaced_review"),
    ("adaptive study —", "adaptive_study"),
    ("concept review —", "concept_review"),
    ("smart review —", "smart_review"),
    ("spaced review —", "spaced_review"),
    ("mixed quiz —", "mixed_quiz"),
)


def new_question_uid(*, uuid_factory=uuid.uuid4):
    """Return one opaque installation-local question identifier."""
    return uuid_factory().hex


def valid_question_uid(value):
    return isinstance(value, str) and QUESTION_UID_RE.fullmatch(value) is not None


def validate_generation_kind(value):
    if value is None:
        return None
    if value != SOURCE_QUIZ_KIND and value not in GENERATED_QUIZ_KINDS:
        raise ValueError(f"Unsupported generated quiz kind: {value}")
    return value


def normalize_question_text(value):
    return " ".join(str(value or "").split()).casefold()


def legacy_question_identity(question_type, question_text, *, question_id=None):
    """Historical content-derived identity retained only for legacy fallback."""
    normalized_type = str(question_type or "choice").strip().casefold() or "choice"
    normalized_text = normalize_question_text(question_text)
    if not normalized_text:
        normalized_text = f"question-id:{question_id}" if question_id is not None else ""
    return ("legacy", normalized_type, normalized_text)


def duplicate_content_identity(question_type, question_text, *, question_id=None):
    """Content identity for duplicate discovery, intentionally not lineage."""
    return legacy_question_identity(
        question_type, question_text, question_id=question_id
    )


def _row_value(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        keys = row.keys()
    except AttributeError:
        return default
    return row[key] if key in keys else default


def canonical_learning_identity(row):
    """Resolve a question row to durable lineage or the legacy safe fallback."""
    canonical_uid = _row_value(row, "canonical_question_uid")
    if valid_question_uid(canonical_uid):
        return ("lineage", canonical_uid)
    return legacy_question_identity(
        _row_value(row, "question_type", "choice"),
        _row_value(row, "question_text", ""),
        question_id=_row_value(row, "id"),
    )


def quiz_generation_kind(*, generation_kind=None, source_file=None, title=None):
    """Return an explicit generated kind or a conservative legacy inference.

    ``source`` is the authoritative marker for ordinary quizzes created after
    the metadata contract converged.  A null value remains intentionally
    ambiguous because schema-v3 migration did not guess at historical quiz
    origins; only those legacy rows use the filename/title compatibility map.
    """
    if generation_kind in GENERATED_QUIZ_KINDS:
        return generation_kind
    if generation_kind == SOURCE_QUIZ_KIND:
        return None
    source = str(source_file or "").strip().casefold()
    label = str(title or "").strip().casefold()
    for prefix, kind in LEGACY_GENERATED_SOURCE_KINDS:
        if source.startswith(prefix):
            return kind
    for prefix, kind in LEGACY_GENERATED_TITLE_KINDS:
        if label.startswith(prefix):
            return kind
    return None


def is_generated_quiz(*, generation_kind=None, source_file=None, title=None):
    """Prefer explicit metadata, with the historical naming convention fallback."""
    return quiz_generation_kind(
        generation_kind=generation_kind,
        source_file=source_file,
        title=title,
    ) is not None


def is_generated_question(row):
    if bool(_row_value(row, "is_generated_copy", 0)):
        return True
    return is_generated_quiz(
        generation_kind=_row_value(row, "generation_kind"),
        source_file=_row_value(row, "source_file"),
        title=_row_value(row, "quiz_title", _row_value(row, "title")),
    )


def source_question_lineage():
    """Create identity fields for a newly-authored/imported source question."""
    question_uid = new_question_uid()
    return {
        "question_uid": question_uid,
        "canonical_question_uid": question_uid,
        "source_question_uid": None,
        "is_generated_copy": 0,
    }


def lineage_for_insert(cur, question, *, generation_kind=None):
    """Create fields for an inserted question and safely adopt a direct source.

    A legacy source is assigned an explicit identity only when its database row
    was directly selected to create this generated copy.  Text equality is
    never used to backfill lineage.
    """
    if generation_kind not in GENERATED_QUIZ_KINDS:
        return source_question_lineage()

    child_uid = new_question_uid()
    lineage = question.get("_lineage") if isinstance(question, dict) else None
    source_id = lineage.get("source_question_id") if isinstance(lineage, dict) else None
    source_row = None
    if isinstance(source_id, int) and not isinstance(source_id, bool) and source_id > 0:
        source_row = cur.execute(
            """
            SELECT id, question_uid, canonical_question_uid
            FROM questions WHERE id = ?
            """,
            (source_id,),
        ).fetchone()

    if source_row is None:
        return {
            "question_uid": child_uid,
            "canonical_question_uid": None,
            "source_question_uid": None,
            "is_generated_copy": 1,
        }

    original_source_uid = source_row["question_uid"]
    original_canonical_uid = source_row["canonical_question_uid"]
    source_uid = original_source_uid
    canonical_uid = original_canonical_uid
    if not valid_question_uid(source_uid):
        source_uid = new_question_uid()
    if not valid_question_uid(canonical_uid):
        canonical_uid = source_uid
    if source_uid != original_source_uid or canonical_uid != original_canonical_uid:
        cur.execute(
            """
            UPDATE questions
            SET question_uid = ?, canonical_question_uid = ?
            WHERE id = ?
            """,
            (source_uid, canonical_uid, source_row["id"]),
        )
    return {
        "question_uid": child_uid,
        "canonical_question_uid": canonical_uid,
        "source_question_uid": source_uid,
        "is_generated_copy": 1,
    }
