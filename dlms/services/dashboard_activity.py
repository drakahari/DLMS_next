"""Read-only dashboard summaries of durable quiz activity.

No activity or completion is inferred from browser recovery, quiz creation,
answer counts, or Generated Practice's first-completion marker.
"""

import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

from dlms.rendering.quiz_artifacts import _quiz_artifact_names
from dlms.services.history import _attempt_columns, _attempt_select_sql


_AWARE_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)"
)
_SQLITE_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def activity_timestamp(value, sqlite_utc=False):
    """Accept zoned dates and the Study event column's known SQLite UTC format.

    A naive Exam timestamp has no known zone; assigning one would invent its
    position relative to other attempts. Return None without changing storage.
    """
    if not isinstance(value, str):
        return None
    if sqlite_utc and _SQLITE_UTC_TIMESTAMP.fullmatch(value):
        value += "+00:00"
    elif not _AWARE_TIMESTAMP.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, OverflowError):
        return None


def recent_quiz_activity(cur, *, history_context, attempt_summary, quiz_folder, data_folder, quiz_origin, sequence=None):
    """Return two latest summaries and up to three other recent attempts.

    Each mode's dated summary uses one SQL pass over its records. Windows also
    count undated records without fetching full histories into Python. Zoned
    timestamps need normalization before ordering, so the raw text index alone
    cannot answer 'latest' correctly. The existing recent-list query is bounded.
    Registry and content-pack context are loaded once for the whole response.
    """
    registry, packs, _origins = history_context()
    select_attempts = _attempt_select_sql("attempt_id" in _attempt_columns(cur))
    context_cache = {}

    def context(quiz_id, db_title):
        if quiz_id in context_cache:
            return context_cache[quiz_id]
        entry = registry.get(quiz_id, {})
        result = {
            "quiz_id": quiz_id,
            "quiz_title": entry.get("title") or db_title or "Unavailable quiz",
            "folder": entry.get("folder") or None,
            "origin": quiz_origin(entry, packs)["label"] if entry else None,
            "quiz_url": None,
            "availability": "Quiz unavailable",
        }
        if entry and db_title is not None:
            try:
                html, json_name = _quiz_artifact_names(entry)
                available = True
                for folder, filename in ((quiz_folder, html), (data_folder, json_name)):
                    root = os.path.realpath(folder)
                    path = os.path.realpath(os.path.join(root, filename))
                    available = available and os.path.commonpath((root, path)) == root and os.path.isfile(path)
                if available:
                    result.update(quiz_url="/quizzes/" + quote(html, safe=""), availability=None)
                else:
                    result["availability"] = "Quiz page unavailable"
            except (ValueError, OSError):
                result["availability"] = "Quiz page unavailable"
        context_cache[quiz_id] = result
        return result

    def attempt(row):
        result = attempt_summary(row, registry, packs)
        result.update(context(row["quiz_id"], row["db_quiz_title"]))
        result["completed_at"] = activity_timestamp(row["completed_at"])
        return result

    # Register only on this request's connection; these helpers never write.
    cur.connection.create_function("dashboard_time", 2, activity_timestamp, deterministic=True)
    try:
        study = cur.execute("""
            WITH dated AS MATERIALIZED (
                SELECT id, quiz_id, dashboard_time(occurred_at, 1) AS saved_at
                FROM learning_events WHERE event_type = 'study_answer' AND mode = 'Study'
                UNION ALL
                SELECT r.rowid, s.quiz_id, dashboard_time(r.saved_at, 0)
                FROM study_responses r JOIN study_sessions s ON s.id = r.session_id
                WHERE r.kind = 'response' AND NOT EXISTS (
                    SELECT 1 FROM learning_events e WHERE e.attempt_id = r.event_id AND e.event_type = 'study_answer')
                UNION ALL
                SELECT r.id, r.quiz_id, dashboard_time(r.occurred_at, 1)
                FROM study_legacy_responses r WHERE NOT EXISTS (
                    SELECT 1 FROM learning_events e WHERE e.id = r.id AND e.event_type = 'study_answer')
            )
            SELECT *, COUNT(*) OVER () AS record_count,
                   SUM(saved_at IS NULL) OVER () AS undated_count
            FROM dated ORDER BY saved_at DESC, id DESC LIMIT 1
        """).fetchone()
        exam = cur.execute("""
            WITH dated AS MATERIALIZED (
                SELECT id, dashboard_time(completed_at, 0) AS finished_at
                FROM attempts WHERE lower(trim(mode)) = 'exam'
            )
            SELECT *, COUNT(*) OVER () AS record_count,
                   SUM(finished_at IS NULL) OVER () AS undated_count
            FROM dated ORDER BY finished_at DESC, id DESC LIMIT 1
        """).fetchone()
    finally:
        cur.connection.create_function("dashboard_time", 2, None)

    study_entry = None
    if study and study["saved_at"]:
        quiz = cur.execute("SELECT title FROM quizzes WHERE id = ?", (study["quiz_id"],)).fetchone()
        study_entry = dict(context(study["quiz_id"], quiz["title"] if quiz else None))
        study_entry["saved_at"] = study["saved_at"]
    exam_entry = None
    if exam and exam["finished_at"]:
        row = cur.execute(select_attempts + " WHERE a.id = ?", (exam["id"],)).fetchone()
        exam_entry = attempt(row)
    recent = cur.execute(
        select_attempts + " ORDER BY a.completed_at DESC, a.id DESC LIMIT 4"
    ).fetchall()
    # Compare durable row IDs, never titles or timestamps. Keep a lone featured
    # attempt in the list when there is no other history to show.
    alternatives = [row for row in recent if not exam_entry or row["attempt_pk"] != exam["id"]]
    recent = (alternatives or recent)[:3]
    return {
        "study": {"entry": study_entry, "record_count": study["record_count"] if study else 0,
                  "undated_count": study["undated_count"] if study else 0},
        "exam": {"entry": exam_entry, "record_count": exam["record_count"] if exam else 0,
                 "undated_count": exam["undated_count"] if exam else 0},
        "recent_attempts": [attempt(row) for row in recent],
        **({"quiz_sequence": sequence(cur, list(registry.values()), context)} if sequence else {}),
    }
