"""Anki row construction, naming, and export helpers."""

import html
import os
import random
import re
import tempfile
import unicodedata


def export_quiz_to_apkg(
    deck_name,
    deck_rows,
    *,
    genanki_module,
    random_module=random,
    tempfile_module=tempfile,
    os_module=os,
    html_module=html,
):
    """
    Build an Anki package and return the temporary package path.

    ``genanki_module`` is supplied by the application so its existing import
    and compatibility boundary remains authoritative.
    """
    model = genanki_module.Model(
        1607392319,
        "AutoQuiz Model",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "<hr id='answer'>{{Back}}",
            },
        ],
    )

    deck = genanki_module.Deck(
        random_module.randrange(1 << 30, 1 << 31),
        deck_name,
    )

    for row in deck_rows:
        front = html_module.escape(row.get("front") or "")
        back = html_module.escape(row.get("back") or "")

        front = front.replace("\n", "<br>")
        back = back.replace("\n", "<br>")

        note = genanki_module.Note(
            model=model,
            fields=[front, back],
        )

        deck.add_note(note)

    fd, path = tempfile_module.mkstemp(suffix=".apkg")
    os_module.close(fd)

    try:
        genanki_module.Package(deck).write_to_file(path)
    except Exception:
        try:
            os_module.remove(path)
        except FileNotFoundError:
            pass
        raise

    return path


def _remove_temp_anki_package(path, *, os_module=os, print_message=print):
    """Best-effort cleanup for a generated temporary Anki package."""
    try:
        os_module.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        print_message(f"[ANKI] Unable to remove temporary export {path}: {exc}")


def build_anki_rows_for_quiz(quiz_id, *, get_db):
    """Build standard front/back rows for every question in one DLMS quiz."""
    try:
        quiz_id = int(quiz_id)
    except (TypeError, ValueError):
        return None, []

    conn = get_db()
    cur = conn.cursor()

    quiz = cur.execute(
        """
        SELECT id, title
        FROM quizzes
        WHERE id = ?
        """,
        (quiz_id,)
    ).fetchone()

    if not quiz:
        conn.close()
        return None, []

    questions = cur.execute(
        """
        SELECT id, question_number, question_text
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number, id
        """,
        (quiz_id,)
    ).fetchall()

    deck_rows = []

    for question in questions:
        choices = cur.execute(
            """
            SELECT label, text, is_correct
            FROM choices
            WHERE question_id = ?
            ORDER BY label
            """,
            (question["id"],)
        ).fetchall()

        front_parts = [(question["question_text"] or "").strip()]

        if choices:
            front_parts.append("")
            for choice in choices:
                front_parts.append(
                    f"{choice['label']}. {(choice['text'] or '').strip()}"
                )

        correct_parts = [
            f"{choice['label']}. {(choice['text'] or '').strip()}"
            for choice in choices
            if choice["is_correct"]
        ]

        back = "Correct Answer"
        if correct_parts:
            back += "\n" + "\n".join(correct_parts)

        deck_rows.append({
            "front": "\n".join(front_parts).strip(),
            "back": back.strip(),
            "question_number": question["question_number"],
            "question_id": question["id"],
            "quiz_id": quiz_id,
        })

    conn.close()
    return quiz["title"] or "DLMS Quiz", deck_rows


def build_anki_rows_for_missed(
    quiz_id=None,
    min_misses=1,
    status_filter="all",
    *,
    get_db,
):
    """Build aggregate missed-question cards from DLMS snapshot data."""
    try:
        min_misses = max(1, min(int(min_misses or 1), 100))
    except (TypeError, ValueError):
        min_misses = 1

    status_filter = str(status_filter or "all").strip().lower()
    valid_filters = {"all", "currently_weak", "repeated", "recovered", "once"}
    if status_filter not in valid_filters:
        status_filter = "all"

    selected_quiz_id = None
    if quiz_id not in (None, "", "all"):
        try:
            selected_quiz_id = int(quiz_id)
        except (TypeError, ValueError):
            selected_quiz_id = None

    conn = get_db()
    cur = conn.cursor()

    attempt_sql = """
        SELECT id, quiz_id, completed_at
        FROM attempts
        WHERE completed_at IS NOT NULL
    """
    attempt_params = []

    if selected_quiz_id is not None:
        attempt_sql += " AND quiz_id = ? "
        attempt_params.append(selected_quiz_id)

    attempt_sql += """
        ORDER BY
            completed_at ASC,
            id ASC
    """

    attempt_rows = cur.execute(attempt_sql, attempt_params).fetchall()

    attempts_by_quiz = {}
    attempt_order = {}

    for position, row in enumerate(attempt_rows):
        qid = row["quiz_id"]
        attempts_by_quiz.setdefault(qid, []).append(row["id"])
        attempt_order[row["id"]] = position

    sql = """
        SELECT
            mq.id AS missed_id,
            mq.attempt_id,
            mq.question_id,
            mq.attempt_question_number,
            mq.question_text,
            mq.choices_text,
            mq.correct_text,
            mq.correct_letters,
            a.quiz_id,
            a.completed_at,
            qu.title AS quiz_title
        FROM missed_questions mq
        JOIN attempts a ON a.id = mq.attempt_id
        LEFT JOIN quizzes qu ON qu.id = a.quiz_id
        WHERE a.completed_at IS NOT NULL
    """
    params = []

    if selected_quiz_id is not None:
        sql += " AND a.quiz_id = ? "
        params.append(selected_quiz_id)

    sql += """
        ORDER BY
            a.completed_at DESC,
            a.id DESC,
            mq.id DESC
    """

    rows = cur.execute(sql, params).fetchall()
    conn.close()

    aggregated = {}

    for row in rows:
        question_text = (row["question_text"] or "").strip()
        if not question_text:
            continue

        question_id = row["question_id"]
        if question_id is not None:
            key = ("id", row["quiz_id"], question_id)
        else:
            key = ("text", row["quiz_id"], question_text.casefold())

        if key not in aggregated:
            aggregated[key] = {
                "question_text": question_text,
                "choices_text": (row["choices_text"] or "").strip(),
                "correct_text": (row["correct_text"] or "").strip(),
                "correct_letters": (row["correct_letters"] or "").strip(),
                "quiz_title": row["quiz_title"] or "Unknown Quiz",
                "quiz_id": row["quiz_id"],
                "question_number": row["attempt_question_number"],
                "question_id": row["question_id"],
                "miss_count": 0,
                "latest_miss_attempt_id": row["attempt_id"],
            }

        aggregated[key]["miss_count"] += 1

    cards = []

    for item in aggregated.values():
        if item["miss_count"] < min_misses:
            continue

        latest_miss_attempt_id = item["latest_miss_attempt_id"]
        quiz_attempt_ids = attempts_by_quiz.get(item["quiz_id"], [])
        latest_miss_position = attempt_order.get(latest_miss_attempt_id, -1)

        has_later_attempt = any(
            attempt_order.get(attempt_id, -1) > latest_miss_position
            for attempt_id in quiz_attempt_ids
        )

        recovery_status = "recovered" if has_later_attempt else "currently_weak"

        if status_filter == "currently_weak" and recovery_status != "currently_weak":
            continue
        if status_filter == "recovered" and recovery_status != "recovered":
            continue
        if status_filter == "repeated" and item["miss_count"] < 2:
            continue
        if status_filter == "once" and item["miss_count"] != 1:
            continue

        front_parts = [item["question_text"]]
        if item["choices_text"]:
            front_parts.extend(["", item["choices_text"]])

        correct = item["correct_text"] or item["correct_letters"]
        back_parts = ["Correct Answer"]
        if correct:
            back_parts.append(correct)

        back_parts.extend([
            "",
            f"Missed in DLMS: {item['miss_count']} "
            + ("times" if item["miss_count"] != 1 else "time"),
            "DLMS status: "
            + ("Currently Weak" if recovery_status == "currently_weak" else "Recovered Later"),
        ])

        cards.append({
            "front": "\n".join(front_parts).strip(),
            "back": "\n".join(back_parts).strip(),
            "quiz_title": item["quiz_title"],
            "quiz_id": item["quiz_id"],
            "question_number": item["question_number"],
            "question_id": item["question_id"],
            "miss_count": item["miss_count"],
            "recovery_status": recovery_status,
        })

    cards.sort(
        key=lambda item: (
            0 if item["recovery_status"] == "currently_weak" else 1,
            -item["miss_count"],
            str(item["quiz_title"]).casefold(),
            item["question_number"] if isinstance(item["question_number"], int) else 999999,
        )
    )

    return cards


def get_anki_missed_summary(quiz_id=None, *, build_rows_for_missed):
    """Return non-destructive performance counts for the Anki Tools UI."""
    all_cards = build_rows_for_missed(quiz_id, 1, "all")

    return {
        "total": len(all_cards),
        "currently_weak": sum(
            1 for card in all_cards
            if card.get("recovery_status") == "currently_weak"
        ),
        "recovered": sum(
            1 for card in all_cards
            if card.get("recovery_status") == "recovered"
        ),
        "repeated": sum(
            1 for card in all_cards
            if int(card.get("miss_count") or 0) >= 2
        ),
        "once": sum(
            1 for card in all_cards
            if int(card.get("miss_count") or 0) == 1
        ),
    }


def parse_law_flashcards_text(raw_text):
    """Convert a Law Study Rule Flashcards section into front/back pairs."""
    text = str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    flashcard_heading_pattern = re.compile(
        r"(?im)^\s*(?:[-*+]\s*)?(?:\*\*|__)?"
        r"flashcard\s*#?\s*\d+"
        r"(?:\*\*|__)?\s*:?\s*$"
    )
    text = flashcard_heading_pattern.sub("", text)

    label_pattern = re.compile(
        r"(?im)^\s*(?:[-*+]\s*)?(?:\*\*|__)?"
        r"(front|back|question|answer|q|a)"
        r"(?:\*\*|__)?\s*:\s*(.*)$"
    )

    matches = list(label_pattern.finditer(text))
    if not matches:
        return []

    pieces = []

    for idx, match in enumerate(matches):
        label = match.group(1).lower()
        inline_value = (match.group(2) or "").strip()
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        continuation = text[match.end():block_end].strip()

        value_parts = []
        if inline_value:
            value_parts.append(inline_value)
        if continuation:
            value_parts.append(continuation)

        value = "\n".join(value_parts).strip()
        normalized = "front" if label in ("front", "question", "q") else "back"
        pieces.append((normalized, value))

    cards = []
    pending_front = None

    for label, value in pieces:
        if label == "front":
            pending_front = value
        elif label == "back" and pending_front:
            if pending_front.strip() and value.strip():
                cards.append({
                    "front": pending_front.strip(),
                    "back": value.strip()
                })
            pending_front = None

    return cards


def get_anki_quiz_choices(*, get_db):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT
            qu.id,
            qu.title,
            COUNT(q.id) AS question_count
        FROM quizzes qu
        LEFT JOIN questions q ON q.quiz_id = qu.id
        GROUP BY qu.id, qu.title
        ORDER BY LOWER(qu.title), qu.id
        """
    ).fetchall()
    conn.close()

    return [
        {
            "id": row["id"],
            "title": row["title"] or f"Quiz {row['id']}",
            "question_count": row["question_count"] or 0,
        }
        for row in rows
    ]


def get_anki_law_case_choices(*, load_law_registry, load_law_flashcards_for_case):
    registry = load_law_registry()
    cases = registry.get("cases", []) or []
    results = []

    for case in cases:
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            continue

        meta, cards = load_law_flashcards_for_case(case_id)

        results.append({
            "id": case_id,
            "title": (meta or {}).get("title") or case.get("title") or "Untitled Case",
            "course": (meta or {}).get("course") or case.get("course") or "Uncategorized",
            "card_count": len(cards),
        })

    results.sort(
        key=lambda item: (
            str(item["course"]).casefold(),
            str(item["title"]).casefold()
        )
    )

    return results


def get_anki_law_courses(law_cases=None, *, get_law_case_choices):
    law_cases = law_cases if law_cases is not None else get_law_case_choices()
    course_map = {}

    for case in law_cases:
        course = str(case.get("course") or "Uncategorized").strip() or "Uncategorized"
        info = course_map.setdefault(
            course,
            {"course": course, "case_count": 0, "card_count": 0},
        )
        info["case_count"] += 1
        info["card_count"] += int(case.get("card_count") or 0)

    return sorted(
        course_map.values(),
        key=lambda item: item["course"].casefold()
    )


def load_law_flashcards_for_selection(
    case_ids=None,
    course=None,
    *,
    get_law_case_choices,
    load_law_flashcards_for_case,
):
    """Combine Rule Flashcards from selected cases or an entire course."""
    law_cases = get_law_case_choices()

    selected_ids = {
        str(case_id).strip()
        for case_id in (case_ids or [])
        if str(case_id).strip()
    }

    selected_course = str(course or "").strip()

    if selected_course:
        selected_cases = [
            case for case in law_cases
            if str(case.get("course") or "").strip().casefold() == selected_course.casefold()
        ]
    else:
        selected_cases = [
            case for case in law_cases
            if str(case.get("id") or "").strip() in selected_ids
        ]

    deck_rows = []
    loaded_cases = []

    for case in selected_cases:
        meta, cards = load_law_flashcards_for_case(case["id"])
        if not meta:
            continue

        loaded_cases.append(meta)

        for card in cards:
            row = dict(card)
            row["front"] = f"{meta['title']}\n\n{row.get('front', '')}".strip()
            deck_rows.append(row)

    selection_meta = {
        "course": selected_course or None,
        "case_count": len(loaded_cases),
        "case_titles": [case["title"] for case in loaded_cases],
    }

    return selection_meta, deck_rows


def get_anki_custom_sources(
    *,
    get_quiz_choices,
    build_rows_for_quiz,
    build_rows_for_missed,
    get_law_case_choices,
    load_law_flashcards_for_case,
):
    """Return selectable DLMS content for the Custom Anki Deck workspace."""
    quiz_groups = []
    for quiz in get_quiz_choices():
        quiz_title, cards = build_rows_for_quiz(quiz["id"])
        quiz_groups.append({
            "id": quiz["id"],
            "title": quiz_title or quiz["title"],
            "cards": cards,
        })

    missed_cards = build_rows_for_missed(None, 1, "all")

    law_groups = []
    for case in get_law_case_choices():
        meta, cards = load_law_flashcards_for_case(case["id"])
        law_groups.append({
            "id": case["id"],
            "title": (meta or {}).get("title") or case["title"],
            "course": (meta or {}).get("course") or case["course"],
            "cards": cards,
        })

    return {
        "quiz_groups": quiz_groups,
        "missed_cards": missed_cards,
        "law_groups": law_groups,
    }


def build_custom_anki_rows(
    quiz_tokens=None,
    missed_tokens=None,
    law_tokens=None,
    *,
    get_quiz_choices,
    build_rows_for_quiz,
    build_rows_for_missed,
    get_law_case_choices,
    load_law_flashcards_for_case,
):
    """Assemble selected DLMS content into one deduplicated card list."""
    quiz_tokens = set(quiz_tokens or [])
    missed_tokens = set(missed_tokens or [])
    law_tokens = set(law_tokens or [])

    rows = []

    for quiz in get_quiz_choices():
        quiz_title, cards = build_rows_for_quiz(quiz["id"])
        for card in cards:
            token = f"quiz:{quiz['id']}:{card.get('question_id')}"
            if token not in quiz_tokens:
                continue

            row = dict(card)
            row["front"] = (
                f"{quiz_title}\n\n{row.get('front', '')}"
            ).strip()
            rows.append(row)

    for card in build_rows_for_missed(None, 1, "all"):
        stable_id = card.get("question_id")
        if stable_id is None:
            stable_id = card.get("question_number")

        token = f"missed:{card.get('quiz_id')}:{stable_id}"
        if token not in missed_tokens:
            continue

        row = dict(card)
        row["front"] = (
            f"{card.get('quiz_title', 'DLMS Quiz')}\n\n"
            f"{row.get('front', '')}"
        ).strip()
        rows.append(row)

    for case in get_law_case_choices():
        meta, cards = load_law_flashcards_for_case(case["id"])
        if not meta:
            continue

        for index, card in enumerate(cards, start=1):
            token = f"law:{case['id']}:{index}"
            if token not in law_tokens:
                continue

            row = dict(card)
            row["front"] = (
                f"{meta['course']} · {meta['title']}\n\n"
                f"{row.get('front', '')}"
            ).strip()
            rows.append(row)

    unique_rows = []
    seen = set()

    for row in rows:
        key = (
            str(row.get("front") or "").strip().casefold(),
            str(row.get("back") or "").strip().casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)

    return unique_rows


def make_safe_anki_download_name(
    name,
    fallback="dlms_anki_deck",
    *,
    secure_filename,
    os_module=os,
):
    cleaned = secure_filename(str(name or "").strip())
    cleaned = os_module.path.splitext(cleaned)[0]
    if not cleaned:
        cleaned = secure_filename(str(fallback or "").strip())
        cleaned = os_module.path.splitext(cleaned)[0]
    if not cleaned:
        cleaned = "dlms_anki_deck"
    return f"{cleaned}.apkg"


def make_safe_anki_deck_name(name, fallback="DLMS Anki Deck"):
    normalized = unicodedata.normalize("NFKC", str(name or ""))
    cleaned = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in normalized
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("::", " - ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    return (cleaned[:120].rstrip() or fallback)


def export_anki_tsv_for_quiz(quiz_id, *, get_db):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            q.number AS question_number,
            q.text   AS question_text,
            qu.title AS quiz_title,
            GROUP_CONCAT(
                c.label || '. ' || c.text,
                CHAR(10)
            ) AS choices,
            GROUP_CONCAT(
                CASE WHEN c.is_correct = 1 THEN c.label END,
                ', '
            ) AS correct_letters,
            GROUP_CONCAT(
                CASE WHEN c.is_correct = 1 THEN c.label || '. ' || c.text END,
                CHAR(10)
            ) AS correct_text
        FROM questions q
        JOIN quizzes qu ON qu.id = q.quiz_id
        JOIN choices c ON c.question_id = q.id
        WHERE q.quiz_id = ?
        GROUP BY q.id
        ORDER BY q.number
    """, (quiz_id,))

    rows = cur.fetchall()
    conn.close()

    lines = ["Front\tBack\tTags"]

    for row in rows:
        front = (
            f"<b>{row['question_text']}</b><br><br>"
            + "<br>".join((row["choices"] or "").split("\n"))
        ).replace("\t", " ")

        back = (
            f"<b>Correct answer:</b> {row['correct_letters']}<br><br>"
            + "<br>".join((row["correct_text"] or "").split("\n"))
        ).replace("\t", " ")

        quiz_tag = (row["quiz_title"] or "autoquiz").replace(" ", "_")
        tags = quiz_tag

        lines.append(f"{front}\t{back}\t{tags}")

    return "\n".join(lines)


def format_anki_missed_tsv(rows, *, logger):
    lines = ["Front\tBack\tTags"]

    for idx, row in enumerate(rows, start=1):
        if not row["question_text"]:
            logger.warning("[ANKI-TSV] Empty question_text | row=%s", idx)

        front_parts = [row["question_text"] or ""]
        if row["choices_text"]:
            front_parts.extend(["", row["choices_text"]])

        front = "\n".join(front_parts).replace("\t", " ")

        back_parts = []
        if row["correct_letters"]:
            back_parts.append(f"Correct: {row['correct_letters']}")
        if row["correct_text"]:
            back_parts.append(row["correct_text"])

        back = "\n".join(back_parts).replace("\t", " ")

        quiz_tag = (row["quiz_title"] or "autoquiz").replace(" ", "_")
        tags = f"{quiz_tag} missed"

        lines.append(f"{front}\t{back}\t{tags}")

        if idx == 1:
            logger.debug(
                "[ANKI-TSV] First card preview:\nFRONT:\n%s\nBACK:\n%s",
                front[:500],
                back[:500],
            )

    tsv = "\n".join(lines)

    logger.info(
        "[ANKI-TSV] TSV generated | lines=%s | bytes=%s",
        len(lines),
        len(tsv.encode("utf-8")),
    )

    return tsv
