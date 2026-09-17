"""Durable, presentation-only completion state for generated review quizzes."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .question_identity import quiz_generation_kind, TRANSIENT_REVIEW_KINDS


COMPLETION_KEY = "generated_practice_completion"


def completion_metadata(entry, kind):
    """Treat absent, malformed, and non-review metadata as active."""
    if kind not in TRANSIENT_REVIEW_KINDS or not isinstance(entry, dict):
        return None
    value = entry.get(COMPLETION_KEY)
    if not isinstance(value, dict) or set(value) != {"completed_at", "mode", "reference"}:
        return None
    if not isinstance(value["mode"], str) or value["mode"] not in {"Study", "Exam"}:
        return None
    reference = value["reference"]
    if not isinstance(reference, str) or not 0 < len(reference) <= 128 or not reference.strip():
        return None
    timestamp = value["completed_at"]
    if not isinstance(timestamp, str) or len(timestamp) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return {
        "completed_at": parsed.astimezone(timezone.utc).isoformat(),
        "mode": value["mode"],
        "reference": reference,
    }


def quiz_is_transient(row):
    return quiz_generation_kind(
        generation_kind=row["generation_kind"],
        source_file=row["source_file"],
        title=row["title"],
    ) in TRANSIENT_REVIEW_KINDS


def generated_practice_status(cur, quiz_id, registry):
    quiz = cur.execute(
        "SELECT id, title, source_file, generation_kind FROM quizzes WHERE id = ?",
        (quiz_id,),
    ).fetchone()
    if quiz is None or not quiz_is_transient(quiz):
        return {"is_transient": False, "completed": False}
    kind = quiz_generation_kind(
        generation_kind=quiz["generation_kind"],
        source_file=quiz["source_file"], title=quiz["title"],
    )
    entry = next((item for item in registry if isinstance(item, dict) and item.get("id") == quiz_id), None)
    return {
        "is_transient": True,
        "completed": completion_metadata(entry, kind) is not None,
    }


def _current_quiz_questions(cur, quiz_id):
    return cur.execute(
        "SELECT id FROM questions WHERE quiz_id = ? ORDER BY question_number, id",
        (quiz_id,),
    ).fetchall()


def _verify_study(cur, quiz_id, reference, questions, answers):
    if not isinstance(answers, list) or len(answers) != len(questions):
        raise ValueError("Every quiz question needs a saved Study response.")
    expected = {row["id"] for row in questions}
    latest = {}
    rows = cur.execute(
        """SELECT id, question_id, was_correct, response_json
           FROM learning_events
           WHERE quiz_id = ? AND session_id = ? AND event_type = 'study_answer'
           ORDER BY id""",
        (quiz_id, reference),
    ).fetchall()
    for row in rows:
        if row["question_id"] in expected:
            latest[row["question_id"]] = row
    if set(latest) != expected:
        raise ValueError("Every quiz question needs a saved Study response.")
    for ordinal, question in enumerate(questions, start=1):
        answer = answers[ordinal - 1]
        if not isinstance(answer, dict) or set(answer) != {"ordinal", "selected"}:
            raise ValueError("Study response details are incomplete.")
        if answer["ordinal"] != ordinal or latest[question["id"]]["was_correct"] is None:
            raise ValueError("A Study response is incomplete or not saved.")
        try:
            saved = json.loads(latest[question["id"]]["response_json"] or "{}")
        except (TypeError, ValueError):
            raise ValueError("A saved Study response is unavailable.") from None
        if saved.get("question_number") != ordinal or saved.get("selected") != answer["selected"]:
            raise ValueError("The current Study answer has not been saved.")


def _verify_exam(cur, quiz_id, reference, questions):
    attempt = cur.execute(
        """SELECT mode, total, completed_at FROM attempts
           WHERE id = ? AND quiz_id = ?""",
        (reference, quiz_id),
    ).fetchone()
    if not attempt or attempt["mode"] != "Exam" or not attempt["completed_at"] or attempt["total"] != len(questions):
        raise ValueError("A completed, saved Exam attempt is required.")
    responses = cur.execute(
        """SELECT question_id, was_correct FROM learning_events
           WHERE quiz_id = ? AND attempt_id = ? AND event_type = 'exam_answer'""",
        (quiz_id, reference),
    ).fetchall()
    if (
        len(responses) != len(questions)
        or {row["question_id"] for row in responses} != {row["id"] for row in questions}
        or any(row["was_correct"] is None for row in responses)
    ):
        raise ValueError("The saved Exam attempt has incomplete question evidence.")


def _verify_artifact(entry, quiz_id, fingerprint, *, data_folder, quiz_artifact_names):
    if not isinstance(fingerprint, str) or len(fingerprint) != 71 or not fingerprint.startswith("sha256:"):
        raise ValueError("The quiz page identity is missing. Reload the quiz and retry.")
    _html_name, json_name = quiz_artifact_names(entry)
    raw = (Path(data_folder) / json_name).read_text(encoding="utf-8")
    identity = "\0".join((
        "quiz-recovery-v1", "1", str(quiz_id), f"/data/{json_name}",
        str(entry.get("exam_minutes") or 90), raw,
    ))
    current = "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    if fingerprint != current:
        raise ValueError("This quiz changed. Reload it before recording completion.")


def complete_generated_practice(
    cur, data, *, registry_lock, load_registry, save_registry,
    data_folder, quiz_artifact_names,
):
    """Verify one saved run before atomically publishing its lifecycle marker.

    Study responses remain committed independently. A registry failure cannot
    erase them and is reported without treating the quiz as completed.
    """
    if not isinstance(data, dict):
        raise ValueError("A completion request is required.")
    quiz_id = data.get("quizId")
    mode = data.get("mode")
    reference = data.get("reference")
    count = data.get("questionCount")
    if isinstance(quiz_id, bool) or not isinstance(quiz_id, int) or quiz_id < 1:
        raise ValueError("A valid quiz is required.")
    if not isinstance(mode, str) or mode not in {"Study", "Exam"} or not isinstance(reference, str) or not 0 < len(reference) <= 128 or not reference.strip():
        raise ValueError("A valid saved session is required.")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("A valid quiz question count is required.")
    quiz = cur.execute(
        "SELECT id, title, source_file, generation_kind FROM quizzes WHERE id = ?",
        (quiz_id,),
    ).fetchone()
    if quiz is None:
        raise ValueError("This quiz is no longer available.")
    if not quiz_is_transient(quiz):
        return {"ok": True, "applicable": False}
    questions = _current_quiz_questions(cur, quiz_id)
    if len(questions) != count:
        raise ValueError("The quiz question set changed. Reload and retry.")
    with registry_lock:
        registry = load_registry()
        entry = next((item for item in registry if isinstance(item, dict) and item.get("id") == quiz_id), None)
        if entry is None:
            raise ValueError("This generated quiz is no longer in the Library.")
        _verify_artifact(
            entry, quiz_id, data.get("fingerprint"),
            data_folder=data_folder, quiz_artifact_names=quiz_artifact_names,
        )
        if mode == "Study":
            _verify_study(cur, quiz_id, reference, questions, data.get("answers"))
        else:
            _verify_exam(cur, quiz_id, reference, questions)
        kind = quiz_generation_kind(
            generation_kind=quiz["generation_kind"], source_file=quiz["source_file"], title=quiz["title"],
        )
        existing = completion_metadata(entry, kind)
        if existing:
            return {"ok": True, "applicable": True, "already_completed": True}
        updated = [dict(item) for item in registry]
        target = next(item for item in updated if item.get("id") == quiz_id)
        target[COMPLETION_KEY] = {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "reference": reference,
        }
        try:
            save_registry(updated)
        except Exception:
            durable = next((item for item in load_registry() if isinstance(item, dict) and item.get("id") == quiz_id), None)
            if completion_metadata(durable, kind) != completion_metadata(target, kind):
                raise
        # Read back through the repository boundary: a reported write must be durable.
        durable = next((item for item in load_registry() if isinstance(item, dict) and item.get("id") == quiz_id), None)
        if completion_metadata(durable, kind) != completion_metadata(target, kind):
            raise OSError("Generated Practice completion could not be confirmed.")
    return {"ok": True, "applicable": True, "already_completed": False}
