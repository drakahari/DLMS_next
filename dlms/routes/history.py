"""Attempt-history, analytics, missed-question, and history-page routes."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, jsonify, redirect, request, send_from_directory


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class HistoryRouteDependencies:
    """Configured application services required by attempt-history routes."""

    static_folder: Dependency
    get_db: Dependency
    parse_attempt_pagination: Dependency
    attempt_page: Dependency
    attempt_overview: Dependency
    attempt_analytics: Dependency
    attempt_summary: Dependency
    missed_questions: Dependency
    clear_persistent_history: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def history(dependencies):
    return send_from_directory(dependencies.static_folder(), "history.html")


def history_html_redirect(_dependencies):
    attempt = request.args.get("attempt")
    if attempt:
        return redirect(f"/history?attempt={attempt}", code=301)
    return redirect("/history", code=301)


def review(dependencies):
    return send_from_directory(dependencies.static_folder(), "review.html")


def dashboard(dependencies):
    return send_from_directory(dependencies.static_folder(), "dashboard.html")


def api_attempts(dependencies):
    try:
        page, page_size, origin = dependencies.parse_attempt_pagination()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    conn = dependencies.get_db()
    try:
        return jsonify(
            dependencies.attempt_page(conn.cursor(), page, page_size, origin)
        )
    finally:
        conn.close()


def api_attempts_overview(dependencies):
    conn = dependencies.get_db()
    try:
        return jsonify(dependencies.attempt_overview(conn.cursor()))
    finally:
        conn.close()


def api_attempts_analytics(dependencies):
    conn = dependencies.get_db()
    try:
        return jsonify(dependencies.attempt_analytics(conn.cursor()))
    finally:
        conn.close()


def api_attempt_summary(dependencies, attempt_reference):
    conn = dependencies.get_db()
    try:
        summary = dependencies.attempt_summary(conn.cursor(), attempt_reference)
        if summary is None:
            return jsonify({"error": "Attempt not found"}), 404
        return jsonify(summary)
    finally:
        conn.close()


def api_missed_questions(dependencies):
    attempt_id = request.args.get("attempt")

    if not attempt_id:
        return {"error": "Missing attempt id"}, 400

    conn = dependencies.get_db()
    try:
        missed = dependencies.missed_questions(conn.cursor(), attempt_id)
        if missed is None:
            return jsonify({"error": "Attempt not found"}), 404
        return jsonify(missed)
    finally:
        conn.close()


def clear_db_history(dependencies):
    try:
        dependencies.clear_persistent_history()
        print("[DB] Persistent exam history fully cleared")
        return {"status": "ok", "message": "Persistent history cleared"}
    except Exception as exc:
        print("DB CLEAR ERROR:", exc)
        return {
            "status": "error",
            "error": (
                "Saved history could not be cleared. "
                "Check the local DLMS log for details."
            ),
        }, 500


def history_db(_dependencies):
    return jsonify(
        {
            "error": (
                "Deprecated endpoint. Use /api/attempts for paged summaries and "
                "/api/missed_questions for selected-attempt detail."
            )
        }
    ), 410


def create_history_blueprint(dependencies):
    blueprint = Blueprint("history", __name__)
    rules = (
        ("/history", "history", history, ["GET"]),
        ("/history.html", "history_html_redirect", history_html_redirect, ["GET"]),
        ("/review", "review", review, ["GET"]),
        ("/review.html", "review", review, ["GET"]),
        ("/dashboard", "dashboard", dashboard, ["GET"]),
        ("/dashboard.html", "dashboard", dashboard, ["GET"]),
        ("/api/attempts", "api_attempts", api_attempts, ["GET"]),
        (
            "/api/attempts/overview",
            "api_attempts_overview",
            api_attempts_overview,
            ["GET"],
        ),
        (
            "/api/attempts/analytics",
            "api_attempts_analytics",
            api_attempts_analytics,
            ["GET"],
        ),
        (
            "/api/attempts/<attempt_reference>",
            "api_attempt_summary",
            api_attempt_summary,
            ["GET"],
        ),
        (
            "/api/missed_questions",
            "api_missed_questions",
            api_missed_questions,
            ["GET"],
        ),
        (
            "/api/clear_db_history",
            "clear_db_history",
            clear_db_history,
            ["POST"],
        ),
        ("/history_db", "history_db", history_db, ["GET"]),
    )
    bound_views = {}
    for rule, endpoint, view_func, methods in rules:
        bound_view = bound_views.setdefault(
            endpoint, _bind_dependencies(view_func, dependencies)
        )
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=bound_view,
            methods=methods,
        )
    return blueprint
