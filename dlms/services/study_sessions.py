"""Ordered factual Study sessions and their resettable learning projection."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .attempts import LearningPayloadError, _learning_identifier, _learning_integer, _validate_question_response
from .generated_practice_lifecycle import _verify_artifact, quiz_is_transient


class StudyConflict(LearningPayloadError):
    """A page, queue, or tab no longer owns the current assessment."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def assessment_revision(cur, quiz_id):
    """Exclude presentation/context fields; never infer identity from text."""
    questions = cur.execute("SELECT * FROM questions WHERE quiz_id = ? ORDER BY question_number, id", (quiz_id,)).fetchall()
    identity_metadata = {"question_uid", "canonical_question_uid", "source_question_uid", "is_generated_copy"}
    content = [{**{key: row[key] for key in row.keys() if key not in identity_metadata}, "choices": [], "pairs": []} for row in questions]
    by_id = {row["id"]: row for row in content}
    for row in cur.execute("SELECT c.question_id, c.label, c.text, c.is_correct FROM choices c JOIN questions q ON q.id=c.question_id WHERE q.quiz_id=? ORDER BY c.question_id, c.label", (quiz_id,)):
        by_id[row[0]]["choices"].append(tuple(row)[1:])
    for row in cur.execute("SELECT p.question_id, p.pair_order, p.left_text, p.right_text FROM matching_pairs p JOIN questions q ON q.id=p.question_id WHERE q.quiz_id=? ORDER BY p.question_id, p.pair_order, p.id", (quiz_id,)):
        by_id[row[0]]["pairs"].append(tuple(row)[1:])
    return hashlib.sha256(encode(content).encode()).hexdigest()


def generation(cur):
    return cur.execute("SELECT generation FROM study_state WHERE id = 1").fetchone()[0]


def question_revision(cur, question_id):
    row = cur.execute("SELECT question_text, question_type, matching_round_size, matching_direction, explanation, media_json, correct_letters, correct_text FROM questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        return None
    content = {"question": tuple(row), "choices": [tuple(r) for r in cur.execute("SELECT label, text, is_correct FROM choices WHERE question_id = ? ORDER BY label", (question_id,))],
               "pairs": [tuple(r) for r in cur.execute("SELECT pair_order, left_text, right_text FROM matching_pairs WHERE question_id = ? ORDER BY pair_order, id", (question_id,))]}
    return hashlib.sha256(encode(content).encode()).hexdigest()


def hotspot_result(selected, target):
    x, y = selected["x"], selected["y"]
    if target.get("type") == "circle":
        return (x - target["x"]) ** 2 + (y - target["y"]) ** 2 <= target["radius"] ** 2
    points = target.get("points", [])
    inside = False
    for index, (xi, yi) in enumerate(points):
        xj, yj = points[index - 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
    return inside


def artifact(cur, quiz_id, fingerprint, *, registry, data_folder, artifact_names):
    entry = next((entry for entry in registry if entry.get("id") == quiz_id), None)
    if not entry:
        raise StudyConflict("This quiz is unavailable. Return to Quiz Library.")
    try:
        _verify_artifact(entry, quiz_id, fingerprint, data_folder=data_folder, quiz_artifact_names=artifact_names)
        _, name = artifact_names(entry)
        return json.loads((Path(data_folder) / name).read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise StudyConflict("This quiz page changed or is unavailable. Reload and start a new review; saved history is retained.") from exc


def manifest(cur, quiz_id, questions, variants):
    rows = cur.execute("SELECT id, source_question_uid, is_generated_copy FROM questions WHERE quiz_id = ? ORDER BY question_number, id", (quiz_id,)).fetchall()
    if len(rows) != len(questions) or not rows:
        raise StudyConflict("The quiz question set changed. Reload before studying.")
    if not isinstance(variants, dict):
        raise LearningPayloadError("Matching variants must be an object")
    result = []
    for index, row in enumerate(rows):
        item = {"id": row["id"], "variant": None, "source_id": None, "source_revision": None}
        if row["is_generated_copy"]:
            source = cur.execute("SELECT id FROM questions WHERE question_uid = ? AND is_generated_copy = 0", (row["source_question_uid"],)).fetchone()
            if source:
                item["source_id"] = source["id"]
                item["source_revision"] = question_revision(cur, row["id"])
        question = questions[index]
        if question.get("type") == "matching":
            variant = variants.get(str(index))
            if not isinstance(variant, dict):
                raise LearningPayloadError("A matching variant is required")
            indexes = variant.get("sourcePairIndexes")
            count = len(question.get("pairs", []))
            configured = question.get("round_size")
            expected = min(configured, count) if type(configured) is int and configured >= 2 else count
            if (not isinstance(indexes, list) or len(indexes) != expected
                    or any(type(i) is not int or not 0 <= i < count for i in indexes)
                    or len(set(indexes)) != len(indexes)
                    or variant.get("direction") not in {"term_to_definition", "definition_to_term"}):
                raise LearningPayloadError("Invalid matching variant")
            order = variant.get("optionOrder")
            if order is not None and (not isinstance(order, list) or sorted(order) != list(range(len(indexes)))):
                raise LearningPayloadError("Invalid matching option order")
            item["variant"] = variant
        result.append(item)
    return result


def public_session(cur, row):
    if row is None:
        return None
    result = dict(row)
    result.pop("owner", None)
    result["manifest"] = json.loads(result.pop("manifest_json"))
    responses = cur.execute("SELECT * FROM study_responses WHERE session_id = ? ORDER BY sequence", (row["id"],)).fetchall()
    result["sequence"] = max((r["sequence"] for r in responses), default=0)
    result["sequence_complete"] = len(responses) == result["sequence"]
    result["answers"] = {}
    result["observations"] = {}
    for response in responses:
        payload = json.loads(response["payload_json"])
        key = str(response["ordinal"] - 1)
        observation = result["observations"].setdefault(key, {"first": None, "latest": None, "actions": []})
        if response["kind"] == "response":
            result["answers"][key] = {"selected": payload["selected"], "type": payload["questionType"], "was_correct": response["was_correct"]}
            if response["was_correct"] is not None:
                if observation["first"] is None:
                    observation["first"] = {"correct": bool(response["was_correct"]), "prior_feedback_or_action": bool(observation["actions"])}
                observation["latest"] = bool(response["was_correct"])
            if payload.get("selected"):
                observation["actions"].append("answer_feedback")
        else:
            observation["actions"].append(response["kind"])
    if not result["sequence_complete"]:
        for observation in result["observations"].values():
            observation["first"] = None
    result["reviewed"] = len(result["manifest"]) if row["completed_at"] else sum(answer["was_correct"] is not None for answer in result["answers"].values())
    result["total"] = len(result["manifest"])
    return result


def claim(conn, data, *, registry, data_folder, artifact_names):
    if not isinstance(data, dict):
        raise LearningPayloadError("A session request is required")
    quiz_id = _learning_integer(data.get("quizId"), "quizId", minimum=1)
    session_id = _learning_identifier(data.get("sessionId"), "sessionId")
    owner = _learning_identifier(data.get("owner"), "owner")
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.cursor()
    if data.get("generation") != generation(cur):
        raise StudyConflict("Data was reset or restored. Reload before resuming; old queued saves are invalid.")
    questions = artifact(cur, quiz_id, data.get("fingerprint"), registry=registry, data_folder=data_folder, artifact_names=artifact_names)
    revision = assessment_revision(cur, quiz_id)
    row = cur.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,)).fetchone()
    if row:
        if row["quiz_id"] != quiz_id or row["assessment_revision"] != revision or row["fingerprint"] != data.get("fingerprint"):
            raise StudyConflict("This session uses an older assessment. Start a new review; its history is retained.")
        if row["owner"] != owner and data.get("takeover") is not True:
            raise StudyConflict("Another tab owns this session. Select Resume and take over to continue here.")
        conn.execute("UPDATE study_sessions SET owner = ?, generation = ? WHERE id = ?", (owner, generation(cur), session_id))
    else:
        if data.get("takeover") is True:
            raise StudyConflict("This saved session no longer exists. Start a new review.")
        quiz_row = cur.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
        if not quiz_row:
            raise StudyConflict("Quiz unavailable")
        selected_manifest = manifest(cur, quiz_id, questions, data.get("variants", {}))
        conn.execute("""INSERT INTO study_sessions(id, quiz_id, purpose, fingerprint, assessment_revision, manifest_json, owner, generation, started_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (session_id, quiz_id, "focused" if quiz_is_transient(quiz_row) else "regular", data["fingerprint"], revision, encode(selected_manifest), owner, generation(cur), utc_now()))
    result = public_session(cur, cur.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,)).fetchone())
    conn.commit()
    return result


def owned(cur, data):
    row = cur.execute("SELECT * FROM study_sessions WHERE id = ?", (data.get("sessionId"),)).fetchone()
    if not row or row["quiz_id"] != data.get("quizId"):
        raise StudyConflict("Study session unavailable. Reload and start a new review.")
    if data.get("generation") != generation(cur) or row["generation"] != data.get("generation"):
        raise StudyConflict("Data was reset or restored. Reload; this queued save is no longer valid.")
    if row["owner"] != data.get("owner"):
        raise StudyConflict("This session was taken over by another tab. Reload and explicitly resume to take it back.")
    if row["assessment_revision"] != data.get("assessmentRevision") or row["assessment_revision"] != assessment_revision(cur, row["quiz_id"]):
        raise StudyConflict("The questions changed. Reload and start a new review; saved history is retained.")
    return row


def save_response(conn, data, *, registry, data_folder, artifact_names, record_learning_event):
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.cursor()
    session = owned(cur, data)
    # Check artifact as well as DB assessment, including media/hotspot geometry.
    questions = artifact(cur, session["quiz_id"], session["fingerprint"], registry=registry, data_folder=data_folder, artifact_names=artifact_names)
    event_id = _learning_identifier(data.get("eventId"), "eventId")
    sequence = _learning_integer(data.get("sequence"), "sequence", minimum=1, maximum=1000000)
    ordinal = _learning_integer(data.get("questionOrdinal"), "questionOrdinal", minimum=1, maximum=len(questions))
    kind = data.get("kind", "response")
    if kind not in {"response", "ai_open", "prompt_copy"}:
        raise LearningPayloadError("Unknown observable action")
    if kind != "response" and (data.get("selected") is not None or data.get("wasCorrect") is not None or data.get("questionType") != "choice"):
        raise LearningPayloadError("Tool actions must not assert an answer or correctness")
    # Owner/generation are transport credentials; retry identity is the immutable event.
    payload = {key: data.get(key) for key in ("quizId", "sessionId", "eventId", "sequence", "questionOrdinal", "questionType", "wasCorrect", "selected", "assessmentRevision")}
    payload["kind"] = kind
    encoded = encode(payload)
    existing = cur.execute("SELECT payload_json FROM study_responses WHERE event_id = ?", (event_id,)).fetchone()
    if existing:
        if existing[0] != encoded:
            raise LearningPayloadError("eventId identifies a different response")
        conn.commit()
        return {"ok": True, "event_id": event_id, "already_recorded": True}, 200
    if session["completed_at"]:
        raise StudyConflict("This review is finished. Start a new review to answer again.")
    if cur.execute("SELECT 1 FROM study_responses WHERE session_id = ? AND sequence = ?", (session["id"], sequence)).fetchone():
        raise StudyConflict("This response sequence is already used. Reload to resume saved progress.")
    item = json.loads(session["manifest_json"])[ordinal - 1]
    question = cur.execute("SELECT * FROM questions WHERE id = ?", (item["id"],)).fetchone()
    correct = None
    if kind == "response":
        runtime_type = questions[ordinal - 1].get("type", "choice")
        if data.get("questionType") != runtime_type:
            raise LearningPayloadError("Question type does not match this assessment")
        if data.get("questionType") == "matching":
            variant = item["variant"]
            selected = data.get("selected")
            count = len(variant["sourcePairIndexes"]) if variant else 0
            if not isinstance(selected, dict) or any(not str(k).isdigit() or not 0 <= int(k) < count or type(v) is not int or not 0 <= v < count for k, v in selected.items()) or len(set(selected.values())) != len(selected):
                raise LearningPayloadError("Invalid matching response")
            correct = all(int(k) == v for k, v in selected.items()) if len(selected) == count else None
            if data.get("wasCorrect") is not correct:
                raise LearningPayloadError("Matching correctness disagrees with selections")
        else:
            detail = _validate_question_response(cur, question, data, study=True, field="Study response", attempt_question_number=ordinal)
            correct = detail["wasCorrect"]
            if runtime_type == "hotspot":
                correct = hotspot_result(detail["selected"], questions[ordinal - 1]["target"])
                if data.get("wasCorrect") is not correct:
                    raise LearningPayloadError("Hotspot correctness disagrees with the submitted position")
    saved_at = utc_now()
    cur.execute("""INSERT INTO study_responses(event_id, session_id, sequence, question_id, ordinal, kind, was_correct, payload_json, saved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (event_id, session["id"], sequence, item["id"], ordinal, kind, correct, encoded, saved_at))
    if kind == "response":
        record_learning_event(cur, event_type="study_answer", quiz_id=session["quiz_id"], question_id=item["id"], attempt_id=event_id, session_id=session["id"], mode="Study", was_correct=correct, response={
            "contract": 2, "sequence": sequence, "assessment_revision": session["assessment_revision"],
            "question_number": ordinal, "question_type": data["questionType"], "selected": data["selected"],
            "source_id": item.get("source_id"), "source_revision": item.get("source_revision"),
        })
    # Assistance is ordered factual evidence, and part of the same resettable stream.
    else:
        record_learning_event(cur, event_type="study_action", quiz_id=session["quiz_id"], question_id=item["id"], attempt_id=event_id, session_id=session["id"], mode="Study", response={"contract": 2, "sequence": sequence, "kind": kind})
    if kind == "response":
        # Navigation is saved separately. A delayed answer must not undo an
        # acknowledged Next/Previous request.
        cur.execute("UPDATE study_sessions SET last_activity_at = ? WHERE id = ?", (saved_at, session["id"]))
    conn.commit()
    return {"ok": True, "event_id": event_id, "already_recorded": False}, 200


def finish(conn, data, **artifact_options):
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.cursor()
    row = owned(cur, data)
    artifact(cur, row["quiz_id"], row["fingerprint"], **artifact_options)
    session = public_session(cur, row)
    count = cur.execute("SELECT COUNT(*) FROM study_responses WHERE session_id = ?", (row["id"],)).fetchone()[0]
    if data.get("sequence") != session["sequence"] or count != session["sequence"]:
        raise StudyConflict("Some response saves are missing. Retry them before finishing.")
    if session["reviewed"] != session["total"]:
        raise LearningPayloadError("Every question needs a complete saved answer before Finish Review.")
    if not row["completed_at"]:
        cur.execute("UPDATE study_sessions SET completed_at = ? WHERE id = ?", (utc_now(), row["id"]))
    result = public_session(cur, cur.execute("SELECT * FROM study_sessions WHERE id = ?", (row["id"],)).fetchone())
    conn.commit()
    return {"ok": True, "session": result}


def regular_continuity(cur, registry, *, data_folder, quiz_folder, artifact_names):
    """One current regular reference, independent of targeted generated practice."""
    row = cur.execute("""SELECT s.*, q.title FROM study_sessions s JOIN quizzes q ON q.id = s.quiz_id
                         WHERE purpose = 'regular' AND last_activity_at IS NOT NULL
                         ORDER BY last_activity_at DESC, s.rowid DESC LIMIT 1""").fetchone()
    if not row:
        return None
    session = public_session(cur, row)
    entry = next((e for e in registry if e.get("id") == row["quiz_id"]), None)
    url = None
    available = False
    if entry:
        try:
            html, filename = artifact_names(entry)
            available = all((Path(root) / name).resolve().is_relative_to(Path(root).resolve()) and (Path(root) / name).is_file() for root, name in ((data_folder, filename), (quiz_folder, html)))
            if available:
                url = "/quizzes/" + quote(html, safe="")
        except (OSError, ValueError):
            pass
    unchanged = row["assessment_revision"] == assessment_revision(cur, row["quiz_id"])
    if available and unchanged:
        try:
            artifact(cur, row["quiz_id"], row["fingerprint"], registry=registry, data_folder=data_folder, artifact_names=artifact_names)
        except StudyConflict:
            unchanged = False
    return {"quiz_id": row["quiz_id"], "title": (entry or {}).get("title") or row["title"],
            "reviewed": session["reviewed"], "total": session["total"], "completed_at": row["completed_at"],
            "saved_at": row["last_activity_at"], "url": url, "unchanged": unchanged}
