"""Durable Study APIs. Application-wide CSRF protection applies to every write."""

from dataclasses import dataclass
from collections.abc import Callable

from flask import Blueprint, jsonify, render_template, request

from dlms.services import study_sessions as study


@dataclass(frozen=True)
class StudyRouteDependencies:
    get_db: Callable
    artifact_options: Callable
    run_delete: Callable
    operation_error: Callable


def create_study_blueprint(dependencies):
    get_db = dependencies.get_db
    artifact_options = dependencies.artifact_options
    run_delete = dependencies.run_delete
    operation_error = dependencies.operation_error
    bp = Blueprint("study", __name__)

    def write(operation):
        conn = get_db()
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise study.LearningPayloadError("Request body must be an object")
            return jsonify(operation(conn, data))
        except study.StudyConflict as exc:
            conn.rollback()
            return jsonify(error=str(exc)), 409
        except (study.LearningPayloadError, ValueError) as exc:
            conn.rollback()
            return jsonify(error=str(exc)), 400
        except Exception:
            conn.rollback()
            return jsonify(error="Study progress could not be saved. Retry without closing this page."), 500
        finally:
            conn.close()

    @bp.get("/api/study/quiz/<int:quiz_id>")
    def status(quiz_id):
        conn = get_db()
        try:
            cur = conn.cursor()
            session_id = request.args.get("sessionId")
            if session_id is not None:
                # Exact-session completion lookup; no history scan or answer load.
                row = cur.execute("SELECT id, quiz_id, purpose, completed_at FROM study_sessions WHERE id = ? AND quiz_id = ?", (session_id, quiz_id)).fetchone()
                return jsonify(session=dict(row) if row else None)
            row = cur.execute("SELECT * FROM study_sessions WHERE quiz_id = ? AND last_activity_at IS NOT NULL ORDER BY last_activity_at DESC, rowid DESC LIMIT 1", (quiz_id,)).fetchone()
            return jsonify(generation=study.generation(cur), session=study.public_session(cur, row))
        finally:
            conn.close()

    @bp.post("/api/study/session")
    def claim():
        return write(lambda conn, data: {"ok": True, "session": study.claim(conn, data, **artifact_options())})

    @bp.post("/api/study/finish")
    def finish():
        return write(lambda conn, data: study.finish(conn, data, **artifact_options()))

    @bp.post("/api/study/position")
    def position():
        def save(conn, data):
            conn.execute("BEGIN IMMEDIATE")
            row = study.owned(conn.cursor(), data)
            value = study._learning_integer(data.get("position"), "position", minimum=0, maximum=len(study.json.loads(row["manifest_json"])) - 1)
            if not row["completed_at"]:
                conn.execute("UPDATE study_sessions SET position = ? WHERE id = ?", (value, row["id"]))
            conn.commit()
            return {"ok": True}
        return write(save)

    @bp.get("/study-history")
    def history():
        conn = get_db()
        try:
            page = max(1, request.args.get("page", 1, type=int))
            cur = conn.cursor()
            rows = cur.execute("""SELECT s.*, q.title FROM study_sessions s JOIN quizzes q ON q.id = s.quiz_id
                                  WHERE last_activity_at IS NOT NULL ORDER BY last_activity_at DESC, s.rowid DESC LIMIT 51 OFFSET ?""", ((page - 1) * 50,)).fetchall()
            sessions = [study.public_session(cur, row) for row in rows[:50]]
            reset_at = cur.execute("SELECT learning_reset_at FROM study_state WHERE id = 1").fetchone()[0]
            legacy = cur.execute("SELECT r.*, q.title FROM study_legacy_responses r LEFT JOIN quizzes q ON q.id=r.quiz_id ORDER BY r.id DESC LIMIT 51 OFFSET ?", ((page - 1) * 50,)).fetchall()
            return render_template("study/history.html", sessions=sessions, legacy=legacy[:50], page=page, more=len(rows) > 50 or len(legacy) > 50, reset_at=reset_at)
        finally:
            conn.close()

    @bp.post("/api/delete_study_history")
    def delete_history():
        # Same owned-root and automatic backup safeguards as scoped resets.
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get("confirmation") != "DELETE STUDY HISTORY":
            return jsonify(error="Confirm DELETE STUDY HISTORY to continue."), 400
        try:
            return jsonify(status="ok", backup=run_delete())
        except Exception as exc:
            message, status = operation_error(exc, "Study-history deletion")
            return jsonify(error=message), status

    return bp
