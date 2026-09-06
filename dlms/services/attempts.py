"""Attempt validation, scoring, and learning-event persistence services."""

import json
import re
from datetime import datetime


class LearningPayloadError(ValueError):
    """A client learning/attempt payload failed trust-boundary validation."""


LEARNING_MODES = {"exam": "Exam", "study": "Study"}
LEARNING_QUESTION_TYPES = {"choice", "matching", "hotspot"}


def _learning_integer(
    value, field, *, minimum=None, maximum=None, allow_numeric_string=False
):
    if allow_numeric_string and isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningPayloadError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise LearningPayloadError(f"{field} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise LearningPayloadError(f"{field} must be no greater than {maximum}")
    return value


def _learning_identifier(value, field, *, maximum=128):
    if not isinstance(value, str) or not value.strip():
        raise LearningPayloadError(f"{field} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise LearningPayloadError(f"{field} must be {maximum} characters or fewer")
    return value


def _optional_learning_identifier(
    value, field, *, maximum=128, learning_identifier=_learning_identifier
):
    if value is None:
        return None
    return learning_identifier(value, field, maximum=maximum)


def _attempt_timestamp(value, field):
    if value is None:
        return None, None
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise LearningPayloadError(f"{field} must be an ISO-8601 timestamp")
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LearningPayloadError(f"{field} must be an ISO-8601 timestamp") from exc
    return value, parsed


def _attempt_percent(score, total):
    # Match JavaScript Math.round for the non-negative values accepted here.
    return ((score * 100 * 2) + total) // (total * 2)


def _question_response_context(cur, quiz_id, question_number):
    return cur.execute(
        """
        SELECT id, question_number, question_text,
               COALESCE(question_type, 'choice') AS question_type
        FROM questions
        WHERE quiz_id = ? AND question_number = ?
        ORDER BY id
        LIMIT 1
        """,
        (quiz_id, question_number),
    ).fetchone()


def _question_response_context_by_ordinal(cur, quiz_id, ordinal):
    """Resolve one question by the same stable order used by runtime quizzes."""
    return cur.execute(
        """
        SELECT id, question_number, question_text,
               COALESCE(question_type, 'choice') AS question_type
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number, id
        LIMIT 1 OFFSET ?
        """,
        (quiz_id, ordinal - 1),
    ).fetchone()


def _learning_question_type(
    value, question, field, *, learning_question_types=LEARNING_QUESTION_TYPES
):
    if not isinstance(value, str):
        raise LearningPayloadError(f"{field} must be a supported question type")
    question_type = value.strip().lower()
    if question_type not in learning_question_types:
        raise LearningPayloadError(f"{field} must be choice, matching, or hotspot")
    stored_type = str(question["question_type"] or "choice").strip().lower()
    if question_type == "hotspot":
        # Generated hotspot quizzes deliberately persist a choice surrogate.
        if stored_type != "choice" or not str(
            question["question_text"] or ""
        ).endswith("[Image hotspot]"):
            raise LearningPayloadError(
                f"{field} does not match the stored question type"
            )
    elif question_type != stored_type:
        raise LearningPayloadError(f"{field} does not match the stored question type")
    return question_type


def _strict_correctness(value, field, *, allow_none=False):
    if value is None and allow_none:
        return None
    if not isinstance(value, bool):
        raise LearningPayloadError(f"{field} must be true or false")
    return value


def _choice_response(cur, question_id, selected, *, study):
    if not isinstance(selected, list):
        raise LearningPayloadError("selected must be an array for a choice question")
    labels = []
    for value in selected:
        if not isinstance(value, str) or not value:
            raise LearningPayloadError(
                "selected choice labels must be non-empty strings"
            )
        labels.append(value)
    if len(labels) != len(set(labels)):
        raise LearningPayloadError(
            "selected choice labels must not contain duplicates"
        )

    choices = cur.execute(
        "SELECT label, is_correct FROM choices WHERE question_id = ? ORDER BY label",
        (question_id,),
    ).fetchall()
    allowed = {row["label"] for row in choices}
    correct = {row["label"] for row in choices if row["is_correct"]}
    if not choices or not correct:
        raise LearningPayloadError("the stored choice question is not scoreable")
    if any(label not in allowed for label in labels):
        raise LearningPayloadError("selected contains an unknown choice label")

    if study and len(correct) > 1 and len(labels) != len(correct):
        correctness = None
    else:
        correctness = set(labels) == correct
    return labels, correctness


def _matching_response(
    cur, question_id, selected, *, study, learning_integer=_learning_integer
):
    # Early content-pack clients represented an unanswered match as [].
    if selected == []:
        selected = {}
    if not isinstance(selected, dict):
        raise LearningPayloadError(
            "selected must be an object for a matching question"
        )
    pair_count = cur.execute(
        "SELECT COUNT(*) FROM matching_pairs WHERE question_id = ?", (question_id,)
    ).fetchone()[0]
    if pair_count < 2:
        raise LearningPayloadError("the stored matching question is not scoreable")

    normalized = {}
    for raw_left, raw_right in selected.items():
        left = learning_integer(
            raw_left,
            "selected matching key",
            minimum=0,
            maximum=pair_count - 1,
            allow_numeric_string=True,
        )
        right = learning_integer(
            raw_right,
            "selected matching value",
            minimum=0,
            maximum=pair_count - 1,
            allow_numeric_string=True,
        )
        if left in normalized:
            raise LearningPayloadError("selected matching keys must be unique")
        normalized[left] = right
    if len(set(normalized.values())) != len(normalized):
        raise LearningPayloadError("selected matching answers must not be reused")

    complete = len(normalized) == pair_count and all(
        index in normalized for index in range(pair_count)
    )
    correctness = (
        all(normalized[index] == index for index in range(pair_count))
        if complete
        else (None if study else False)
    )
    return {str(key): value for key, value in sorted(normalized.items())}, correctness


def _hotspot_response(selected, *, study):
    if selected is None and not study:
        return None
    if not isinstance(selected, dict) or set(selected) != {"x", "y"}:
        raise LearningPayloadError(
            "selected must contain only x and y for a hotspot question"
        )
    coordinates = {}
    for key in ("x", "y"):
        value = selected[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise LearningPayloadError(f"selected hotspot {key} must be a number")
        value = float(value)
        if (
            value != value
            or value in (float("inf"), float("-inf"))
            or not 0 <= value <= 1
        ):
            raise LearningPayloadError(
                f"selected hotspot {key} must be between 0 and 1"
            )
        coordinates[key] = value
    return coordinates


def _validate_question_response(
    cur,
    question,
    detail,
    *,
    study,
    field,
    attempt_question_number=None,
    learning_question_type=_learning_question_type,
    strict_correctness=_strict_correctness,
    choice_response=_choice_response,
    matching_response=_matching_response,
    hotspot_response=_hotspot_response,
):
    if not isinstance(detail, dict):
        raise LearningPayloadError(f"{field} must be an object")
    question_type = learning_question_type(
        detail.get("questionType"), question, f"{field}.questionType"
    )
    submitted_correctness = strict_correctness(
        detail.get("wasCorrect"), f"{field}.wasCorrect", allow_none=study
    )
    if question_type == "choice":
        selected, computed_correctness = choice_response(
            cur, question["id"], detail.get("selected"), study=study
        )
    elif question_type == "matching":
        selected, computed_correctness = matching_response(
            cur, question["id"], detail.get("selected"), study=study
        )
    else:
        selected = hotspot_response(detail.get("selected"), study=study)
        # Hotspot geometry is a runtime artifact, while the canonical DB row is
        # intentionally a lightweight choice surrogate. Its strict boolean is
        # therefore validated but cannot yet be independently recomputed here.
        computed_correctness = False if selected is None else submitted_correctness

    if submitted_correctness is not computed_correctness:
        raise LearningPayloadError(
            f"{field}.wasCorrect is inconsistent with selected"
        )
    return {
        "attemptQuestionNumber": (
            question["question_number"]
            if attempt_question_number is None
            else attempt_question_number
        ),
        "questionType": question_type,
        "wasCorrect": computed_correctness,
        "selected": selected,
        "questionId": question["id"],
    }


def _validate_missed_details(
    cur,
    raw_details,
    questions,
    responses,
    *,
    validate_hotspot_shape,
    learning_integer=_learning_integer,
):
    if not isinstance(raw_details, list):
        raise LearningPayloadError("missedDetails must be an array")
    if len(raw_details) > len(questions):
        raise LearningPayloadError("missedDetails contains too many questions")
    normalized = []
    seen = set()
    for index, detail in enumerate(raw_details):
        field = f"missedDetails[{index}]"
        if not isinstance(detail, dict):
            raise LearningPayloadError(f"{field} must be an object")
        number = learning_integer(
            detail.get("attemptQuestionNumber"),
            f"{field}.attemptQuestionNumber",
            minimum=1,
        )
        if number in seen or number not in questions:
            raise LearningPayloadError(
                f"{field} does not identify one unique quiz question"
            )
        seen.add(number)
        response = responses[number]
        if response["wasCorrect"] is not False:
            raise LearningPayloadError(
                f"{field} is inconsistent with the recorded correctness"
            )
        question_type = detail.get("questionType") or response["questionType"]
        if (
            not isinstance(question_type, str)
            or question_type.strip().lower() != response["questionType"]
        ):
            raise LearningPayloadError(
                f"{field}.questionType is inconsistent with responseDetails"
            )
        cleaned = dict(detail)
        cleaned["attemptQuestionNumber"] = number
        cleaned["questionType"] = response["questionType"]
        cleaned["selected"] = response["selected"]
        cleaned["questionId"] = response["questionId"]
        if response["questionType"] == "choice":
            choice_rows = cur.execute(
                "SELECT label, is_correct FROM choices WHERE question_id = ? ORDER BY label",
                (response["questionId"],),
            ).fetchall()
            cleaned["correctLetters"] = [
                row["label"] for row in choice_rows if row["is_correct"]
            ]
            cleaned["selectedLetters"] = list(response["selected"])
        elif response["questionType"] == "matching":
            pair_rows = cur.execute(
                """
                SELECT left_text, right_text FROM matching_pairs
                WHERE question_id = ? ORDER BY pair_order, id
                """,
                (response["questionId"],),
            ).fetchall()
            selections = response["selected"]
            cleaned["correctLetters"] = []
            cleaned["selectedLetters"] = []
            cleaned["correctText"] = [
                f"{row['left_text']} ↔ {row['right_text']}" for row in pair_rows
            ]
            cleaned["selectedText"] = [
                f"{row['left_text']} ↔ "
                + (
                    pair_rows[int(selections[str(pair_index)])]["right_text"]
                    if str(pair_index) in selections
                    else "[No answer]"
                )
                for pair_index, row in enumerate(pair_rows)
            ]
        else:
            hotspot = detail.get("hotspot")
            if not isinstance(hotspot, dict):
                raise LearningPayloadError(f"{field}.hotspot must be an object")
            selected_point = hotspot.get("selected")
            if selected_point != response["selected"]:
                raise LearningPayloadError(
                    f"{field}.hotspot selected point is inconsistent"
                )
            try:
                cleaned_shape = validate_hotspot_shape(hotspot.get("target"))
            except (TypeError, ValueError) as exc:
                raise LearningPayloadError(
                    f"{field}.hotspot target is invalid"
                ) from exc
            cleaned_hotspot = dict(hotspot)
            cleaned_hotspot["selected"] = response["selected"]
            cleaned_hotspot["target"] = cleaned_shape
            target_row = cur.execute(
                """
                SELECT text FROM choices
                WHERE question_id = ? AND is_correct = 1
                ORDER BY label LIMIT 1
                """,
                (response["questionId"],),
            ).fetchone()
            target_label = target_row["text"] if target_row else "Target structure"
            cleaned_hotspot["targetLabel"] = target_label
            cleaned["hotspot"] = cleaned_hotspot
            cleaned["correctLetters"] = ["A"]
            cleaned["selectedLetters"] = []
            cleaned["correctText"] = [target_label]
            cleaned["selectedText"] = [
                "Image location selected"
                if response["selected"] is not None
                else "[No answer]"
            ]
        normalized.append(cleaned)
    return normalized


def _validate_attempt_payload(
    cur,
    data,
    *,
    learning_integer=_learning_integer,
    learning_identifier=_learning_identifier,
    optional_learning_identifier=_optional_learning_identifier,
    validate_question_response=_validate_question_response,
    attempt_percent=_attempt_percent,
    attempt_timestamp=_attempt_timestamp,
    validate_missed_details,
    learning_modes=LEARNING_MODES,
):
    if not isinstance(data, dict):
        raise LearningPayloadError("Request body must be a JSON object")
    quiz_id = learning_integer(
        data.get("quizId"), "quizId", minimum=1, allow_numeric_string=True
    )
    if not cur.execute("SELECT 1 FROM quizzes WHERE id = ?", (quiz_id,)).fetchone():
        raise LearningPayloadError("quizId does not identify an existing quiz")
    attempt_id = learning_identifier(data.get("attemptId"), "attemptId")
    session_id = optional_learning_identifier(data.get("sessionId"), "sessionId")

    mode_value = data.get("mode")
    if mode_value is None:
        mode_value = "Study"
    if (
        not isinstance(mode_value, str)
        or mode_value.strip().lower() not in learning_modes
    ):
        raise LearningPayloadError("mode must be Study or Exam")
    mode = learning_modes[mode_value.strip().lower()]

    score = learning_integer(data.get("score"), "score", minimum=0)
    total = learning_integer(data.get("total"), "total", minimum=1)
    percent = learning_integer(data.get("percent"), "percent", minimum=0, maximum=100)

    rows = cur.execute(
        """
        SELECT id, question_number, question_text,
               COALESCE(question_type, 'choice') AS question_type
        FROM questions WHERE quiz_id = ? ORDER BY question_number, id
        """,
        (quiz_id,),
    ).fetchall()
    if not rows or len(rows) != total:
        raise LearningPayloadError(
            "total does not match the stored quiz question count"
        )
    # attemptQuestionNumber is the 1-based runtime ordinal. Stored/source
    # question numbers remain display metadata and are not required to be
    # unique for older quizzes published before ordinal normalization.
    questions = {ordinal: row for ordinal, row in enumerate(rows, start=1)}

    raw_responses = data.get("responseDetails")
    if not isinstance(raw_responses, list) or len(raw_responses) != len(rows):
        raise LearningPayloadError(
            "responseDetails must contain one response for every quiz question"
        )
    responses = {}
    for index, detail in enumerate(raw_responses):
        field = f"responseDetails[{index}]"
        if not isinstance(detail, dict):
            raise LearningPayloadError(f"{field} must be an object")
        number = learning_integer(
            detail.get("attemptQuestionNumber"),
            f"{field}.attemptQuestionNumber",
            minimum=1,
        )
        if number in responses or number not in questions:
            raise LearningPayloadError(
                f"{field} does not identify one unique quiz question"
            )
        responses[number] = validate_question_response(
            cur,
            questions[number],
            detail,
            study=False,
            field=field,
            attempt_question_number=number,
        )
    if set(responses) != set(questions):
        raise LearningPayloadError("responseDetails must cover every quiz question")

    computed_score = sum(
        1 for detail in responses.values() if detail["wasCorrect"]
    )
    computed_percent = attempt_percent(computed_score, len(rows))
    if score != computed_score or score > total:
        raise LearningPayloadError("score is inconsistent with responseDetails")
    if percent != computed_percent:
        raise LearningPayloadError("percent is inconsistent with score and total")

    started_at, started_value = attempt_timestamp(data.get("startedAt"), "startedAt")
    completed_at, completed_value = attempt_timestamp(
        data.get("completedAt"), "completedAt"
    )
    if started_value is not None and completed_value is not None:
        try:
            if completed_value < started_value:
                raise LearningPayloadError("completedAt must not be before startedAt")
        except TypeError as exc:
            raise LearningPayloadError(
                "startedAt and completedAt must use compatible timezones"
            ) from exc
    time_remaining = data.get("timeRemaining")
    if time_remaining is not None:
        time_remaining = learning_integer(
            time_remaining, "timeRemaining", minimum=0, maximum=1440 * 60
        )

    missed_details = validate_missed_details(
        cur, data.get("missedDetails", []), questions, responses
    )
    return {
        "quiz_id": quiz_id,
        "attempt_id": attempt_id,
        "session_id": session_id,
        "score": computed_score,
        "total": len(rows),
        "percent": computed_percent,
        "started_at": started_at,
        "completed_at": completed_at,
        "time_remaining": time_remaining,
        "mode": mode,
        "response_details": [responses[number] for number in sorted(responses)],
        "missed_details": missed_details,
    }


def _attempt_retry_matches_existing(
    cur, validated, attempt_columns, *, json_module=json
):
    """Return True only when a retry exactly matches one durable attempt."""
    identity_column = "attempt_id" if "attempt_id" in attempt_columns else "id"
    rows = cur.execute(
        f"""
        SELECT id AS attempt_pk, quiz_id, score, total, percent,
               started_at, completed_at, time_remaining, mode
        FROM attempts
        WHERE CAST({identity_column} AS TEXT) = ?
        """,
        (validated["attempt_id"],),
    ).fetchall()
    if not rows:
        return False
    if len(rows) != 1:
        raise LearningPayloadError("attemptId is not unique in saved attempt history")

    row = rows[0]
    expected_summary = (
        validated["quiz_id"],
        validated["score"],
        validated["total"],
        validated["percent"],
        validated["started_at"],
        validated["completed_at"],
        validated["time_remaining"],
        validated["mode"],
    )
    durable_summary = (
        row["quiz_id"],
        row["score"],
        row["total"],
        row["percent"],
        row["started_at"],
        row["completed_at"],
        row["time_remaining"],
        row["mode"],
    )
    if durable_summary != expected_summary:
        raise LearningPayloadError("attemptId already identifies a different attempt")

    event_rows = cur.execute(
        """
        SELECT question_id, was_correct, response_json
        FROM learning_events
        WHERE attempt_id = ? AND event_type = 'exam_answer'
        ORDER BY id
        """,
        (validated["attempt_id"],),
    ).fetchall()
    if len(event_rows) != len(validated["response_details"]):
        raise LearningPayloadError("attemptId already identifies a different attempt")
    for event, response in zip(event_rows, validated["response_details"]):
        try:
            durable_response = json_module.loads(event["response_json"] or "{}")
        except (TypeError, json_module.JSONDecodeError):
            raise LearningPayloadError(
                "attemptId already identifies a different attempt"
            ) from None
        expected_response = {
            "question_number": response["attemptQuestionNumber"],
            "question_type": response["questionType"],
            "selected": response["selected"],
        }
        if (
            event["question_id"] != response["questionId"]
            or event["was_correct"] != (1 if response["wasCorrect"] else 0)
            or durable_response != expected_response
        ):
            raise LearningPayloadError(
                "attemptId already identifies a different attempt"
            )

    references = [str(row["attempt_pk"]), validated["attempt_id"]]
    placeholders = ",".join("?" for _ in references)
    durable_missed = [
        missed[0]
        for missed in cur.execute(
            f"""
            SELECT attempt_question_number
            FROM missed_questions
            WHERE CAST(attempt_id AS TEXT) IN ({placeholders})
            ORDER BY attempt_question_number, id
            """,
            references,
        ).fetchall()
    ]
    expected_missed = sorted(
        detail["attemptQuestionNumber"] for detail in validated["missed_details"]
    )
    if durable_missed != expected_missed:
        raise LearningPayloadError("attemptId already identifies a different attempt")
    return True


def _record_learning_event(
    cur,
    *,
    event_type,
    quiz_id=None,
    question_id=None,
    attempt_id=None,
    session_id=None,
    mode=None,
    was_correct=None,
    response=None,
    json_module=json,
):
    cur.execute(
        """
        INSERT INTO learning_events (
            event_type, quiz_id, question_id, attempt_id, session_id, mode, was_correct, response_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(event_type or "interaction")[:64],
            quiz_id,
            question_id,
            str(attempt_id) if attempt_id else None,
            str(session_id)[:128] if session_id else None,
            str(mode)[:32] if mode else None,
            None if was_correct is None else (1 if bool(was_correct) else 0),
            json_module.dumps(response or {}, ensure_ascii=False),
        ),
    )


def persist_attempt(
    conn,
    cur,
    data,
    *,
    validate_attempt_payload,
    attempt_retry_matches_existing,
    record_learning_event,
    json_module=json,
    print_message=print,
):
    """Validate and atomically persist one completed quiz attempt."""
    validated = validate_attempt_payload(cur, data)
    quiz_id = validated["quiz_id"]
    score = validated["score"]
    total = validated["total"]
    percent = validated["percent"]
    attempt_id = validated["attempt_id"]
    started_at = validated["started_at"]
    completed_at = validated["completed_at"]
    time_remaining = validated["time_remaining"]
    mode = validated["mode"]
    response_details = validated["response_details"]
    missed_details = validated["missed_details"]

    cur.execute("PRAGMA table_info(attempts)")
    attempt_columns = {row[1] for row in cur.fetchall()}

    if attempt_retry_matches_existing(cur, validated, attempt_columns):
        return {
            "ok": True,
            "attempt_id": attempt_id,
            "already_recorded": True,
        }

    if "attempt_id" in attempt_columns:
        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, quiz_id, score, total, percent,
                started_at, completed_at, time_remaining, mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                quiz_id,
                score,
                total,
                percent,
                started_at,
                completed_at,
                time_remaining,
                mode,
            ),
        )
        cur.execute("SELECT id FROM attempts WHERE attempt_id = ?", (attempt_id,))
        row = cur.fetchone()
        attempt_pk = row[0] if row else None
    else:
        cur.execute(
            """
            INSERT INTO attempts (
                id, quiz_id, score, total, percent,
                started_at, completed_at, time_remaining, mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                quiz_id,
                score,
                total,
                percent,
                started_at,
                completed_at,
                time_remaining,
                mode,
            ),
        )
        attempt_pk = attempt_id

    record_learning_event(
        cur,
        event_type="attempt_completed",
        quiz_id=quiz_id,
        attempt_id=attempt_id,
        mode=mode,
        response={"score": score, "total": total, "percent": percent},
    )

    for detail in response_details:
        question_number = detail["attemptQuestionNumber"]
        record_learning_event(
            cur,
            event_type="exam_answer",
            quiz_id=quiz_id,
            question_id=detail["questionId"],
            attempt_id=attempt_id,
            session_id=validated["session_id"],
            mode=mode,
            was_correct=detail.get("wasCorrect"),
            response={
                "question_number": question_number,
                "question_type": detail.get("questionType") or "choice",
                "selected": detail.get("selected"),
            },
        )

    missed_attempt_ref = attempt_pk if attempt_pk is not None else attempt_id

    for missed_detail in missed_details:
        attempt_question_number = missed_detail.get("attemptQuestionNumber")
        if attempt_question_number is None:
            continue

        cur.execute(
            """
            SELECT q.question_text, q.id, COALESCE(q.question_type, 'choice') AS question_type
            FROM questions q
            WHERE q.quiz_id = ? AND q.id = ?
            """,
            (quiz_id, missed_detail["questionId"]),
        )
        question_row = cur.fetchone()

        submitted_question_type = str(
            missed_detail.get("questionType") or ""
        ).strip().lower()
        question_id = question_row["id"] if question_row else None

        if submitted_question_type == "hotspot":
            question_type = "hotspot"
            question_text = question_row["question_text"] if question_row else ""
            suffix = " [Image hotspot]"
            if question_text.endswith(suffix):
                question_text = question_text[: -len(suffix)]
        else:
            question_type = (
                question_row["question_type"]
                if question_row
                else (submitted_question_type or "choice")
            )
            question_text = (
                question_row["question_text"]
                if question_row
                else (missed_detail.get("question") or "")
            )

        if not question_id:
            print_message(
                "[WARN] Missing question snapshot for "
                f"quiz_id={quiz_id}, qnum={attempt_question_number}"
            )

        choices_text = ""
        response_json = ""
        if question_type == "hotspot":
            hotspot_data = (
                missed_detail.get("hotspot")
                if isinstance(missed_detail.get("hotspot"), dict)
                else {}
            )
            response_json = json_module.dumps(hotspot_data, ensure_ascii=False)
        elif question_id and question_type == "matching":
            cur.execute(
                """
                SELECT left_text, right_text
                FROM matching_pairs
                WHERE question_id = ?
                ORDER BY pair_order, id
                """,
                (question_id,),
            )
            choices_text = "\n".join(
                f"{row['left_text']} ↔ {row['right_text']}" for row in cur.fetchall()
            )
        elif question_id:
            cur.execute(
                """
                SELECT label, text
                FROM choices
                WHERE question_id = ?
                ORDER BY label
                """,
                (question_id,),
            )
            choices_text = "\n".join(
                f"{row['label']} — {row['text']}" for row in cur.fetchall()
            )

        correct_letters = missed_detail.get("correctLetters") or []
        selected_letters = missed_detail.get("selectedLetters") or []

        if isinstance(correct_letters, str):
            correct_letters = [correct_letters]
        if isinstance(selected_letters, str):
            selected_letters = [selected_letters]

        correct_letters = [str(value) for value in correct_letters if value]
        selected_letters = [str(value) for value in selected_letters if value]

        correct_text = ""
        selected_text = ""

        if question_type in {"hotspot", "matching"}:
            correct_text = "\n".join(
                str(value) for value in (missed_detail.get("correctText") or [])
            )
            selected_text = "\n".join(
                str(value) for value in (missed_detail.get("selectedText") or [])
            )
        elif question_id:
            cur.execute(
                """
                SELECT label, text
                FROM choices
                WHERE question_id = ? AND is_correct = 1
                """,
                (question_id,),
            )
            correct_text = "\n".join(
                f"{row['label']} — {row['text']}" for row in cur.fetchall()
            )

            if selected_letters:
                cur.execute(
                    f"""
                    SELECT label, text
                    FROM choices
                    WHERE question_id = ?
                    AND label IN ({','.join('?' * len(selected_letters))})
                    """,
                    (question_id, *selected_letters),
                )
                selected_text = "\n".join(
                    f"{row['label']} — {row['text']}" for row in cur.fetchall()
                )

        cur.execute(
            """
            INSERT INTO missed_questions (
                attempt_id,
                attempt_question_number,
                question_text,
                choices_text,
                correct_letters,
                correct_text,
                selected_letters,
                selected_text,
                question_type,
                response_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                missed_attempt_ref,
                attempt_question_number,
                question_text,
                choices_text,
                ",".join(correct_letters),
                correct_text,
                ",".join(selected_letters),
                selected_text,
                question_type,
                response_json,
            ),
        )

    conn.commit()
    return {"ok": True, "attempt_id": attempt_id}


def persist_study_learning_event(
    conn,
    cur,
    data,
    *,
    learning_integer,
    optional_learning_identifier,
    question_response_context_by_ordinal,
    validate_question_response,
    record_learning_event,
    json_module=json,
):
    """Validate and atomically persist one Study Mode learning event."""
    if not isinstance(data, dict):
        raise LearningPayloadError("Request body must be a JSON object")
    quiz_id = learning_integer(
        data.get("quizId"), "quizId", minimum=1, allow_numeric_string=True
    )
    question_ordinal = learning_integer(
        data.get("questionOrdinal", data.get("questionNumber")),
        "questionOrdinal",
        minimum=1,
        allow_numeric_string=True,
    )
    event_id = optional_learning_identifier(data.get("eventId"), "eventId")
    session_id = optional_learning_identifier(data.get("sessionId"), "sessionId")
    row = question_response_context_by_ordinal(cur, quiz_id, question_ordinal)
    if not row:
        return {"error": "Question not found"}, 404
    detail = validate_question_response(
        cur,
        row,
        {
            "questionType": data.get("questionType") or row["question_type"],
            "wasCorrect": data.get("wasCorrect"),
            "selected": data.get("selected"),
        },
        study=True,
        field="study response",
        attempt_question_number=question_ordinal,
    )
    event_response = {
        "question_number": question_ordinal,
        "question_type": detail["questionType"],
        "selected": detail["selected"],
    }
    if event_id:
        # Overlapping Flask requests may use different SQLite connections.
        # Reserve the write before checking this client idempotency key.
        conn.execute("BEGIN IMMEDIATE")
        existing = cur.execute(
            """
            SELECT quiz_id, question_id, session_id, mode,
                   was_correct, response_json
            FROM learning_events
            WHERE event_type = 'study_answer' AND attempt_id = ?
            ORDER BY id
            """,
            (event_id,),
        ).fetchall()
        if existing:
            expected_correctness = (
                None
                if detail["wasCorrect"] is None
                else (1 if detail["wasCorrect"] else 0)
            )
            try:
                durable_response = json_module.loads(
                    existing[0]["response_json"] or "{}"
                )
            except (TypeError, json_module.JSONDecodeError):
                durable_response = None
            exact_retry = (
                len(existing) == 1
                and existing[0]["quiz_id"] == quiz_id
                and existing[0]["question_id"] == row["id"]
                and existing[0]["session_id"] == session_id
                and existing[0]["mode"] == "Study"
                and existing[0]["was_correct"] == expected_correctness
                and durable_response == event_response
            )
            if not exact_retry:
                raise LearningPayloadError(
                    "eventId already identifies a different learning event"
                )
            conn.commit()
            return {
                "ok": True,
                "event_id": event_id,
                "already_recorded": True,
            }, 200
    record_learning_event(
        cur,
        event_type="study_answer",
        quiz_id=quiz_id,
        question_id=row["id"],
        # Study responses have no completed attempt. Reuse this nullable,
        # indexed identity field for the client event key; Study analytics
        # continue to group evidence by session and question.
        attempt_id=event_id,
        session_id=session_id,
        mode="Study",
        was_correct=detail["wasCorrect"],
        response=event_response,
    )
    conn.commit()
    acknowledgement = {"ok": True}
    if event_id:
        acknowledgement.update(
            {"event_id": event_id, "already_recorded": False}
        )
    return acknowledgement, 200
