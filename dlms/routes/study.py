"""Durable Study APIs. Application-wide CSRF protection applies to every write."""

from dataclasses import dataclass
from collections.abc import Callable

from flask import Blueprint, jsonify, render_template, request, abort, url_for

from dlms.services import study_sessions as study
from dlms.services import study_history as history_view


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
            cur = conn.cursor()
            args = {key: history_view.positive(request.args.get(key)) for key in ('sessions_before', 'sessions_after', 'legacy_before', 'legacy_after')}
            old_page = max(1, history_view.positive(request.args.get('page'), 1))
            sessions = history_view.page_rows(cur, before=args['sessions_before'], after=args['sessions_after'], old_page=old_page)
            history_view.session_summaries(cur, sessions['rows'])
            legacy = history_view.page_rows(cur, legacy=True, before=args['legacy_before'], after=args['legacy_after'])
            def page_url(section, direction=None, value=None):
                updated = {key: val for key,val in args.items() if val and not key.startswith(section+'_')}
                if section == 'legacy' and old_page > 1:
                    updated['page'] = old_page
                if direction:
                    updated[section+'_'+direction] = value
                if section == 'legacy':
                    updated['legacy_open'] = 1
                return url_for('study.history', **updated) + ('#legacyHistory' if section=='legacy' else '#studySessions')
            state = cur.execute('SELECT generation,learning_reset_at FROM study_state WHERE id=1').fetchone()
            return render_template('study/history.html', sessions=sessions, legacy=legacy, page_url=page_url,
                                   reset_at=state['learning_reset_at'], history_generation=state['generation'],
                                   legacy_open=request.args.get('legacy_open') == '1')
        finally:
            conn.close()

    @bp.get('/study-history/session/<session_id>')
    def history_session(session_id):
        conn = get_db()
        try:
            result = history_view.session_detail(conn.cursor(), session_id, request.args.get('page', 1))
            if result is None:
                abort(404)
            template = 'study/_session-detail.html' if request.args.get('fragment') == '1' else 'study/session.html'
            return render_template(template, **result)
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
