"""Derived, non-mutating Quiz Library smart views."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dlms.services.question_identity import quiz_generation_kind


RECENTLY_ADDED_DAYS = 30
LOW_SCORE_PERCENT = 75.0
GENERATED_PRACTICE_KINDS = frozenset({
    "adaptive_study",
    "concept_review",
    "native_spaced_review",
    "smart_review",
    "spaced_review",
})
GENERATION_PRESENTATION = {
    "adaptive_study": {
        "label": "Adaptive Study practice",
        "category": "practice",
    },
    "concept_review": {
        "label": "Concept Review practice",
        "category": "practice",
    },
    "native_spaced_review": {
        "label": "Due Questions practice",
        "category": "practice",
    },
    "smart_review": {
        "label": "Smart Review practice",
        "category": "practice",
    },
    "spaced_review": {
        "label": "Topic Retention practice",
        "category": "practice",
    },
    "mixed_quiz": {
        "label": "Mixed Quiz",
        "category": "mixed",
    },
}

SMART_VIEW_DEFINITIONS = (
    {
        "key": "needs-review",
        "label": "Needs Review",
        "description": "Quizzes with source questions due or overdue in native review.",
        "client_derived": False,
    },
    {
        "key": "recently-added",
        "label": "Recently Added",
        "description": f"Quizzes added during the last {RECENTLY_ADDED_DAYS} days.",
        "client_derived": False,
    },
    {
        "key": "low-score",
        "label": "Low Score",
        "description": "Quizzes whose latest completed attempt is below 75%.",
        "client_derived": False,
    },
    {
        "key": "unfinished",
        "label": "Unfinished",
        "description": "Recoverable quiz sessions saved in this browser.",
        "client_derived": True,
    },
    {
        "key": "ocr-imported",
        "label": "OCR Imported",
        "description": "Quizzes published from explicit local OCR workflows.",
        "client_derived": False,
    },
    {
        "key": "generated-practice",
        "label": "Generated Practice",
        "description": (
            "Saved review sessions created from source questions. Revisit, "
            "hide, or ignore them for now without changing source quizzes or "
            "learning history."
        ),
        "client_derived": False,
    },
)
SMART_VIEW_KEYS = frozenset(view["key"] for view in SMART_VIEW_DEFINITIONS)


def normalize_smart_view(value):
    key = str(value or "").strip().casefold()
    return key if key in SMART_VIEW_KEYS else None


def _registry_quiz_ids(registry):
    ordered = []
    seen = set()
    for entry in registry if isinstance(registry, list) else []:
        if not isinstance(entry, dict):
            continue
        value = entry.get("id")
        try:
            quiz_id = int(value)
        except (TypeError, ValueError):
            continue
        if isinstance(value, bool) or quiz_id <= 0 or quiz_id in seen:
            continue
        seen.add(quiz_id)
        ordered.append(quiz_id)
    return ordered


def _parse_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # SQLite CURRENT_TIMESTAMP is UTC and historically stored without an
        # offset. Treating it as UTC preserves the meaning of existing rows.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _quiz_columns(cur):
    return {str(row[1]) for row in cur.execute("PRAGMA table_info(quizzes)").fetchall()}


def _due_quiz_matches(cur, registry_ids, native_schedule, now):
    matches = {}
    if not registry_ids:
        return matches
    schedule = native_schedule(cur, now=now)
    due_questions = [
        item
        for item in schedule.get("questions", [])
        if item.get("schedule_state") in {"due", "overdue"}
    ]
    question_ids = sorted({
        int(question_id)
        for item in due_questions
        for question_id in (
            item.get("source_question_ids") or [item.get("question_id")]
        )
        if isinstance(question_id, int) and not isinstance(question_id, bool)
    })
    if not question_ids:
        return matches
    placeholders = ",".join("?" for _ in question_ids)
    quiz_by_question = {
        int(row["id"]): int(row["quiz_id"])
        for row in cur.execute(
            f"SELECT id, quiz_id FROM questions WHERE id IN ({placeholders})",
            question_ids,
        ).fetchall()
    }
    allowed = set(registry_ids)
    seen_items = set()
    for item_index, item in enumerate(due_questions):
        state = item.get("schedule_state")
        for question_id in (
            item.get("source_question_ids") or [item.get("question_id")]
        ):
            quiz_id = quiz_by_question.get(question_id)
            if quiz_id not in allowed:
                continue
            identity = (quiz_id, item_index)
            if identity in seen_items:
                continue
            seen_items.add(identity)
            match = matches.setdefault(
                quiz_id, {"due": 0, "overdue": 0, "next_review": None}
            )
            match["due"] += 1
            if state == "overdue":
                match["overdue"] += 1
            next_review = item.get("next_review")
            if next_review and (
                match["next_review"] is None or next_review < match["next_review"]
            ):
                match["next_review"] = next_review
    for match in matches.values():
        total = match["due"]
        overdue = match["overdue"]
        match.update({
            "badge": "Overdue" if overdue else "Due now",
            "reason": (
                f"{total} source question{'s' if total != 1 else ''} due"
                + (f" · {overdue} overdue" if overdue else "")
            ),
        })
    return matches


def _recent_quiz_matches(cur, registry_ids, now):
    if not registry_ids or "created_at" not in _quiz_columns(cur):
        return {}
    placeholders = ",".join("?" for _ in registry_ids)
    current = now.astimezone(timezone.utc)
    cutoff = current - timedelta(days=RECENTLY_ADDED_DAYS)
    matches = {}
    for row in cur.execute(
        f"SELECT id, created_at FROM quizzes WHERE id IN ({placeholders})",
        registry_ids,
    ).fetchall():
        created_at = _parse_timestamp(row["created_at"])
        if created_at is None or created_at < cutoff or created_at > current:
            continue
        days = int((current - created_at).total_seconds() // 86400)
        if days == 0:
            when = "Added today"
        elif days == 1:
            when = "Added yesterday"
        else:
            when = f"Added {days} days ago"
        matches[int(row["id"])] = {
            "badge": "New",
            "reason": when,
            "created_at": created_at.isoformat(),
        }
    return matches


def _low_score_matches(cur, registry_ids):
    if not registry_ids:
        return {}
    placeholders = ",".join("?" for _ in registry_ids)
    matches = {}
    rows = cur.execute(
        f"""
        WITH ranked AS (
            SELECT quiz_id, percent, completed_at, id,
                   ROW_NUMBER() OVER (
                       PARTITION BY quiz_id
                       ORDER BY completed_at DESC, id DESC
                   ) AS position
            FROM attempts
            WHERE completed_at IS NOT NULL
              AND quiz_id IN ({placeholders})
        )
        SELECT quiz_id, percent, completed_at
        FROM ranked
        WHERE position = 1 AND percent < ?
        """,
        [*registry_ids, LOW_SCORE_PERCENT],
    ).fetchall()
    for row in rows:
        percent = float(row["percent"])
        rounded = round(percent)
        matches[int(row["quiz_id"])] = {
            "badge": "Below 75%",
            "reason": f"Latest completed score: {rounded}%",
            "percent": percent,
            "completed_at": row["completed_at"],
        }
    return matches


def _ocr_quiz_matches(cur, registry_ids, bank_ocr_quiz_ids):
    if not registry_ids:
        return {}
    placeholders = ",".join("?" for _ in registry_ids)
    direct = {
        int(row["id"])
        for row in cur.execute(
            f"SELECT id, source_file FROM quizzes WHERE id IN ({placeholders})",
            registry_ids,
        ).fetchall()
        if str(row["source_file"] or "").startswith("ocr_matching_")
    }
    bank_ids = {
        int(value)
        for value in bank_ocr_quiz_ids or ()
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }
    return {
        quiz_id: {
            "badge": "Local OCR",
            "reason": "Published from a verified local OCR import workflow",
        }
        for quiz_id in registry_ids
        if quiz_id in direct or quiz_id in bank_ids
    }


def _generated_quiz_presentations(cur, registry_ids, registry):
    """Describe generated quizzes using explicit metadata with legacy fallback."""
    registry_id_set = set(registry_ids)
    rows_by_id = {}
    if registry_ids:
        placeholders = ",".join("?" for _ in registry_ids)
        rows_by_id = {
            int(row["id"]): row
            for row in cur.execute(
                f"""
                SELECT id, title, source_file, generation_kind
                FROM quizzes WHERE id IN ({placeholders})
                """,
                registry_ids,
            ).fetchall()
        }

    presentations = {}
    for entry in registry if isinstance(registry, list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            quiz_id = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        if isinstance(entry.get("id"), bool) or quiz_id not in registry_id_set:
            continue
        row = rows_by_id.get(quiz_id)
        kind = quiz_generation_kind(
            generation_kind=(
                row["generation_kind"] if row is not None
                else entry.get("generation_kind")
            ),
            source_file=(
                row["source_file"] if row is not None else entry.get("html")
            ),
            title=row["title"] if row is not None else entry.get("title"),
        )
        presentation = GENERATION_PRESENTATION.get(kind)
        if presentation is None:
            continue
        presentations[quiz_id] = {
            "kind": kind,
            **presentation,
        }
    return presentations


def build_quiz_smart_views(
    cur,
    registry,
    *,
    native_schedule,
    bank_ocr_quiz_ids=(),
    now=None,
):
    """Return deterministic smart-view definitions and per-quiz evidence."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    registry_ids = _registry_quiz_ids(registry)
    generation = _generated_quiz_presentations(cur, registry_ids, registry)
    matches = {
        "needs-review": _due_quiz_matches(
            cur, registry_ids, native_schedule, now
        ),
        "recently-added": _recent_quiz_matches(cur, registry_ids, now),
        "low-score": _low_score_matches(cur, registry_ids),
        "unfinished": {},
        "ocr-imported": _ocr_quiz_matches(
            cur, registry_ids, bank_ocr_quiz_ids
        ),
        "generated-practice": {
            quiz_id: {
                "reason": (
                    "Saved practice built from source questions · safe to "
                    "revisit or hide"
                ),
            }
            for quiz_id, presentation in generation.items()
            if presentation["kind"] in GENERATED_PRACTICE_KINDS
        },
    }
    views = [
        {**definition, "count": len(matches[definition["key"]])}
        for definition in SMART_VIEW_DEFINITIONS
    ]
    return {"views": views, "matches": matches, "generation": generation}
