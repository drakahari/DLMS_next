"""Read-only attempt history, overview, and analytics services."""

import json


ATTEMPT_HISTORY_ORIGINS = {"all", "quiz", "it", "medical", "study-pack", "law"}
ATTEMPT_HISTORY_DEFAULT_PAGE_SIZE = 50
ATTEMPT_HISTORY_MAX_PAGE_SIZE = 100


def _quiz_history_origin(
    registry_entry,
    packs=None,
    *,
    discover_content_packs,
    is_medical_pack_manifest,
    is_it_pack_manifest,
):
    """Return the established user-facing origin label for History."""
    entry = registry_entry if isinstance(registry_entry, dict) else {}
    explicit = str(entry.get("source_type") or "").strip().lower()
    explicit_labels = {
        "law": {"key": "law", "label": "Law"},
        "medical": {"key": "medical", "label": "Medical"},
        "it": {"key": "it", "label": "IT"},
        "study-pack": {"key": "study-pack", "label": "Study Pack"},
    }
    if explicit in explicit_labels:
        return explicit_labels[explicit]

    source_pack_id = str(entry.get("source_pack_id") or "").strip().lower()
    if source_pack_id:
        packs = packs if isinstance(packs, dict) else discover_content_packs()
        pack = packs.get(source_pack_id) or {}
        if is_medical_pack_manifest(source_pack_id, pack):
            return {"key": "medical", "label": "Medical"}
        if is_it_pack_manifest(source_pack_id, pack):
            return {"key": "it", "label": "IT"}
        return {"key": "study-pack", "label": "Study Pack"}
    return {"key": "quiz", "label": "Quiz"}


def _attempt_history_context(
    registry,
    installed_packs,
    *,
    quiz_history_origin,
):
    """Build registry-derived title and origin data without changing storage."""
    registry_map = {}
    origin_by_quiz_id = {}
    for entry in registry:
        if not isinstance(entry, dict):
            continue
        raw_quiz_id = entry.get("id", entry.get("quiz_id", entry.get("timestamp")))
        try:
            quiz_id = int(raw_quiz_id)
        except (TypeError, ValueError):
            continue
        registry_map[quiz_id] = entry
        origin_by_quiz_id[quiz_id] = quiz_history_origin(
            entry, installed_packs
        )["key"]
    return registry_map, installed_packs, origin_by_quiz_id


def _parse_attempt_pagination(
    args,
    *,
    origins=ATTEMPT_HISTORY_ORIGINS,
    default_page_size=ATTEMPT_HISTORY_DEFAULT_PAGE_SIZE,
    max_page_size=ATTEMPT_HISTORY_MAX_PAGE_SIZE,
):
    def parse_positive(name, default, maximum=None):
        raw = args.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a positive integer")
        if value < 1:
            raise ValueError(f"{name} must be a positive integer")
        if maximum is not None and value > maximum:
            return maximum
        return value

    page = parse_positive("page", 1)
    page_size = parse_positive("page_size", default_page_size, max_page_size)
    origin = str(args.get("origin", "all") or "all").strip().lower()
    if origin not in origins:
        raise ValueError(
            "origin must be one of: " + ", ".join(sorted(origins))
        )
    return page, page_size, origin


def _attempt_columns(cur):
    cur.execute("PRAGMA table_info(attempts)")
    return {row[1] for row in cur.fetchall()}


def _attempt_origin_where(origin, origin_by_quiz_id):
    """Build the parameterized filter matching legacy registry-origin rules."""
    if origin == "all":
        return "", []

    matching_ids = sorted(
        quiz_id
        for quiz_id, origin_key in origin_by_quiz_id.items()
        if origin_key == origin
    )
    if origin == "quiz":
        non_quiz_ids = sorted(
            quiz_id
            for quiz_id, origin_key in origin_by_quiz_id.items()
            if origin_key != "quiz"
        )
        if not non_quiz_ids:
            return "", []
        placeholders = ", ".join("?" for _ in non_quiz_ids)
        return (
            f" WHERE (a.quiz_id IS NULL OR a.quiz_id NOT IN ({placeholders}))",
            non_quiz_ids,
        )

    if not matching_ids:
        return " WHERE 1 = 0", []
    placeholders = ", ".join("?" for _ in matching_ids)
    return f" WHERE a.quiz_id IN ({placeholders})", matching_ids


def _attempt_select_sql(has_attempt_id_col):
    attempt_id_select = (
        "a.attempt_id AS attempt_id"
        if has_attempt_id_col
        else "NULL AS attempt_id"
    )
    return f"""
        SELECT
            a.id AS attempt_pk,
            {attempt_id_select},
            a.quiz_id,
            q.title AS db_quiz_title,
            a.score,
            a.total,
            a.percent,
            a.started_at,
            a.completed_at,
            a.time_remaining,
            a.mode
        FROM attempts a
        LEFT JOIN quizzes q ON q.id = a.quiz_id
    """


def _attempt_summary_from_row(
    row,
    registry_map,
    installed_packs,
    *,
    quiz_history_origin,
):
    try:
        quiz_id = int(row["quiz_id"])
    except (TypeError, ValueError):
        quiz_id = row["quiz_id"]
    registry_entry = (
        registry_map.get(quiz_id, {}) if isinstance(quiz_id, int) else {}
    )
    origin = quiz_history_origin(registry_entry, installed_packs)
    quiz_title = (
        registry_entry.get("title") or row["db_quiz_title"] or "Unknown Quiz"
    )
    return {
        "id": row["attempt_id"] or row["attempt_pk"],
        "attempt_pk": row["attempt_pk"],
        "attempt_id": row["attempt_id"],
        "quiz_id": quiz_id,
        "quiz_title": quiz_title,
        "score": row["score"],
        "total": row["total"],
        "percent": row["percent"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "time_remaining": row["time_remaining"],
        "mode": row["mode"],
        "origin_key": origin["key"],
        "origin": origin["label"],
        "source_pack_id": (
            registry_entry.get("source_pack_id") if registry_entry else None
        ),
        "source_dataset_id": (
            registry_entry.get("source_dataset_id") if registry_entry else None
        ),
    }


def _resolve_attempt_row(
    cur,
    attempt_reference,
    has_attempt_id_col=None,
    *,
    attempt_columns=_attempt_columns,
    attempt_select_sql=_attempt_select_sql,
):
    """Resolve a public attempt_id first, then the legacy/internal primary key."""
    reference = str(attempt_reference or "").strip()
    if not reference:
        return None
    if has_attempt_id_col is None:
        has_attempt_id_col = "attempt_id" in attempt_columns(cur)
    select_sql = attempt_select_sql(has_attempt_id_col)
    if has_attempt_id_col:
        return cur.execute(
            select_sql
            + """
                WHERE CAST(a.attempt_id AS TEXT) = ? OR CAST(a.id AS TEXT) = ?
                ORDER BY CASE WHEN CAST(a.attempt_id AS TEXT) = ? THEN 0 ELSE 1 END
                LIMIT 1
            """,
            (reference, reference, reference),
        ).fetchone()
    return cur.execute(
        select_sql + " WHERE CAST(a.id AS TEXT) = ? LIMIT 1", (reference,)
    ).fetchone()


def _missed_rows_for_attempt(cur, attempt_row):
    """Read snapshots with the established PK/public-ID fallback."""
    sql = """
        SELECT
            attempt_question_number,
            question_text,
            correct_text,
            correct_letters,
            selected_text,
            selected_letters,
            COALESCE(question_type, 'choice') AS question_type,
            response_json
        FROM missed_questions
        WHERE attempt_id = ?
        ORDER BY attempt_question_number, id
    """
    rows = cur.execute(sql, (attempt_row["attempt_pk"],)).fetchall()
    if not rows and attempt_row["attempt_id"]:
        rows = cur.execute(sql, (attempt_row["attempt_id"],)).fetchall()
    return rows


def attempt_page(
    cur,
    page,
    page_size,
    origin,
    *,
    attempt_columns,
    attempt_history_context,
    attempt_origin_where,
    attempt_select_sql,
    attempt_summary_from_row,
):
    """Return one filtered page of attempt summaries and its metadata."""
    has_attempt_id_col = "attempt_id" in attempt_columns(cur)
    registry_map, installed_packs, origin_by_quiz_id = attempt_history_context()
    where_sql, where_params = attempt_origin_where(origin, origin_by_quiz_id)
    total = cur.execute(
        "SELECT COUNT(*) FROM attempts a" + where_sql, where_params
    ).fetchone()[0]
    aggregate = cur.execute(
        "SELECT AVG(a.percent) AS average_percent, "
        "MAX(a.percent) AS best_percent FROM attempts a" + where_sql,
        where_params,
    ).fetchone()
    offset = (page - 1) * page_size
    rows = cur.execute(
        attempt_select_sql(has_attempt_id_col)
        + where_sql
        + " ORDER BY a.completed_at DESC, a.id DESC LIMIT ? OFFSET ?",
        [*where_params, page_size, offset],
    ).fetchall()
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "attempts": [
            attempt_summary_from_row(row, registry_map, installed_packs)
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1 and total_pages > 0,
        "summary": {
            "total_attempts": total,
            "average_percent": aggregate["average_percent"],
            "best_percent": aggregate["best_percent"],
        },
    }


def attempt_overview(
    cur,
    *,
    attempt_columns,
    attempt_history_context,
    attempt_select_sql,
    attempt_summary_from_row,
):
    """Return the dashboard overview and five most recent attempts."""
    has_attempt_id_col = "attempt_id" in attempt_columns(cur)
    registry_map, installed_packs, _ = attempt_history_context()
    aggregate = cur.execute(
        """
        SELECT COUNT(*) AS total_attempts, AVG(percent) AS average_percent,
               MAX(percent) AS best_percent
        FROM attempts
        """
    ).fetchone()
    rows = cur.execute(
        attempt_select_sql(has_attempt_id_col)
        + " ORDER BY a.completed_at DESC, a.id DESC LIMIT 5"
    ).fetchall()
    recent_attempts = [
        attempt_summary_from_row(row, registry_map, installed_packs) for row in rows
    ]
    return {
        "total_attempts": aggregate["total_attempts"],
        "average_percent": aggregate["average_percent"],
        "best_percent": aggregate["best_percent"],
        "latest_attempt": recent_attempts[0] if recent_attempts else None,
        "recent_attempts": recent_attempts,
    }


def attempt_analytics(
    cur,
    *,
    attempt_columns,
    attempt_history_context,
    attempt_summary_from_row,
):
    """Return the existing aggregate and per-quiz analytics payload."""
    has_attempt_id_col = "attempt_id" in attempt_columns(cur)
    registry_map, installed_packs, _ = attempt_history_context()
    aggregate = cur.execute(
        """
        SELECT COUNT(*) AS total_attempts, AVG(percent) AS average_percent,
               MAX(percent) AS best_percent,
               COALESCE(SUM(CASE WHEN percent >= 75 THEN 1 ELSE 0 END), 0) AS pass_count
        FROM attempts
        """
    ).fetchone()
    attempt_id_select = (
        "a.attempt_id AS attempt_id"
        if has_attempt_id_col
        else "NULL AS attempt_id"
    )
    rows = cur.execute(
        f"""
        WITH ranked AS (
            SELECT a.id AS attempt_pk, {attempt_id_select}, a.quiz_id,
                   a.score, a.total, a.percent, a.started_at, a.completed_at,
                   a.time_remaining, a.mode,
                   ROW_NUMBER() OVER (
                       PARTITION BY a.quiz_id
                       ORDER BY a.completed_at DESC, a.id DESC
                   ) AS position
            FROM attempts a
        )
        SELECT r.quiz_id, q.title AS db_quiz_title,
               COUNT(*) AS attempt_count, AVG(r.percent) AS average_percent,
               MAX(r.percent) AS best_percent,
               SUM(CASE WHEN r.percent >= 75 THEN 1 ELSE 0 END) AS pass_count,
               MAX(CASE WHEN r.position = 1 THEN r.attempt_pk END) AS latest_attempt_pk,
               MAX(CASE WHEN r.position = 1 THEN r.attempt_id END) AS latest_attempt_id,
               MAX(CASE WHEN r.position = 1 THEN r.score END) AS latest_score,
               MAX(CASE WHEN r.position = 1 THEN r.total END) AS latest_total,
               MAX(CASE WHEN r.position = 1 THEN r.percent END) AS latest_percent,
               MAX(CASE WHEN r.position = 1 THEN r.started_at END) AS latest_started_at,
               MAX(CASE WHEN r.position = 1 THEN r.completed_at END) AS latest_completed_at,
               MAX(CASE WHEN r.position = 1 THEN r.time_remaining END) AS latest_time_remaining,
               MAX(CASE WHEN r.position = 1 THEN r.mode END) AS latest_mode,
               MAX(CASE WHEN r.position = 2 THEN r.attempt_pk END) AS previous_attempt_pk,
               MAX(CASE WHEN r.position = 2 THEN r.attempt_id END) AS previous_attempt_id,
               MAX(CASE WHEN r.position = 2 THEN r.percent END) AS previous_percent,
               MAX(CASE WHEN r.position = 2 THEN r.completed_at END) AS previous_completed_at
        FROM ranked r
        LEFT JOIN quizzes q ON q.id = r.quiz_id
        GROUP BY r.quiz_id, q.title
        ORDER BY attempt_count DESC, db_quiz_title COLLATE NOCASE, r.quiz_id
        """
    ).fetchall()
    quizzes = []
    for row in rows:
        latest_row = {
            "attempt_pk": row["latest_attempt_pk"],
            "attempt_id": row["latest_attempt_id"],
            "quiz_id": row["quiz_id"],
            "db_quiz_title": row["db_quiz_title"],
            "score": row["latest_score"],
            "total": row["latest_total"],
            "percent": row["latest_percent"],
            "started_at": row["latest_started_at"],
            "completed_at": row["latest_completed_at"],
            "time_remaining": row["latest_time_remaining"],
            "mode": row["latest_mode"],
        }
        latest = attempt_summary_from_row(
            latest_row, registry_map, installed_packs
        )
        previous = None
        if row["previous_attempt_pk"] is not None:
            previous = {
                "id": row["previous_attempt_id"] or row["previous_attempt_pk"],
                "attempt_pk": row["previous_attempt_pk"],
                "attempt_id": row["previous_attempt_id"],
                "percent": row["previous_percent"],
                "completed_at": row["previous_completed_at"],
            }
        quizzes.append(
            {
                "quiz_id": row["quiz_id"],
                "quiz_title": latest["quiz_title"],
                "attempts": row["attempt_count"],
                "average_percent": row["average_percent"],
                "best_percent": row["best_percent"],
                "pass_count": row["pass_count"],
                "pass_rate": (
                    row["pass_count"] * 100.0 / row["attempt_count"]
                    if row["attempt_count"]
                    else 0
                ),
                "latest_attempt": latest,
                "previous_attempt": previous,
            }
        )
    total_attempts = aggregate["total_attempts"]
    return {
        "summary": {
            "total_attempts": total_attempts,
            "average_percent": aggregate["average_percent"],
            "best_percent": aggregate["best_percent"],
            "pass_count": aggregate["pass_count"],
            "pass_rate": (
                aggregate["pass_count"] * 100.0 / total_attempts
                if total_attempts
                else 0
            ),
            "quiz_count": len(quizzes),
        },
        "quizzes": quizzes,
    }


def attempt_summary(
    cur,
    attempt_reference,
    *,
    attempt_columns,
    resolve_attempt_row,
    attempt_history_context,
    attempt_summary_from_row,
):
    """Return one attempt summary, or ``None`` when it cannot be resolved."""
    has_attempt_id_col = "attempt_id" in attempt_columns(cur)
    row = resolve_attempt_row(cur, attempt_reference, has_attempt_id_col)
    if row is None:
        return None
    registry_map, installed_packs, _ = attempt_history_context()
    return attempt_summary_from_row(row, registry_map, installed_packs)


def missed_questions(
    cur,
    attempt_reference,
    *,
    resolve_attempt_row,
    missed_rows_for_attempt,
    json_module=json,
):
    """Return one attempt's missed-question payload, or ``None`` if absent."""
    attempt_row = resolve_attempt_row(cur, attempt_reference)
    if attempt_row is None:
        return None
    rows = missed_rows_for_attempt(cur, attempt_row)
    return [
        {
            "attempt_question_number": row["attempt_question_number"],
            "question_text": row["question_text"],
            "correct_text": row["correct_text"],
            "correct_letters": row["correct_letters"],
            "selected_text": row["selected_text"],
            "selected_letters": row["selected_letters"],
            "question_type": row["question_type"],
            "response_data": (
                json_module.loads(row["response_json"])
                if row["response_json"]
                else None
            ),
        }
        for row in rows
    ]
