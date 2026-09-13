"""Learning-event, adaptive-review, and learner-intelligence routes."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, flash, jsonify, redirect, request, send_from_directory


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class LearningRouteDependencies:
    """Configured application services required by learner-state routes."""

    static_folder: Dependency
    static_root: Dependency
    get_db: Dependency
    learning_payload_error: Dependency
    persist_attempt: Dependency
    persist_study_learning_event: Dependency
    learning_foundation_summary: Dependency
    smart_review_candidates: Dependency
    smart_review_select_candidates: Dependency
    review_candidates_for_topics: Dependency
    review_select_candidates: Dependency
    question_payload_from_db: Dependency
    publish_quiz: Dependency
    review_schedule_payload: Dependency
    question_diagnostics_payload: Dependency
    learning_profile_payload: Dependency
    learning_intelligence_payload: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def record_attempt(dependencies):
    data = request.get_json(silent=True)

    conn = dependencies.get_db()
    cur = conn.cursor()

    try:
        acknowledgement = dependencies.persist_attempt(conn, cur, data)
        return jsonify(acknowledgement), 200
    except dependencies.learning_payload_error() as exc:
        conn.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        conn.rollback()
        print(f"DB ERROR in /record_attempt: {exc}")
        return jsonify({"error": "The quiz attempt could not be recorded."}), 500
    finally:
        conn.close()


def record_study_learning_event(dependencies):
    data = request.get_json(silent=True)

    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        acknowledgement, status = dependencies.persist_study_learning_event(
            conn, cur, data
        )
        return jsonify(acknowledgement), status
    except dependencies.learning_payload_error() as exc:
        conn.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        conn.rollback()
        print(f"[LEARNING EVENT ERROR] {type(exc).__name__}: {exc}")
        return jsonify({"error": "The learning event could not be recorded."}), 500
    finally:
        conn.close()


def learning_foundation_summary(dependencies):
    """Diagnostics for DLMS-006/007; dashboards build on this data."""
    conn = dependencies.get_db()
    cur = conn.cursor()
    out = dependencies.learning_foundation_summary(cur)
    conn.close()
    return jsonify(out)


def smart_review_preview_api(dependencies):
    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        candidates, weak = dependencies.smart_review_candidates(cur)
        return jsonify(
            {
                "weak_topics": [
                    {
                        "name": topic["name"],
                        "mastery": topic["mastery"],
                        "accuracy": topic["accuracy"],
                        "evidence": topic["evidence"],
                    }
                    for topic in weak
                ],
                "candidate_questions": len(candidates),
                "questions": [
                    {
                        "question_id": candidate["question_id"],
                        "question": candidate["question_text"],
                        "topics": candidate["topic_names"],
                    }
                    for candidate in candidates[:50]
                ],
            }
        )
    finally:
        conn.close()


def smart_review_generate(dependencies):
    try:
        requested = int(request.form.get("question_count", "20"))
    except (TypeError, ValueError):
        requested = 20
    requested = max(3, min(requested, 50))

    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        candidates, weak = dependencies.smart_review_candidates(cur)
        if not weak:
            flash(
                "No weak areas currently meet the evidence threshold. "
                "Keep practicing to build evidence.",
                "info",
            )
            return redirect("/learning-intelligence")
        if not candidates:
            flash(
                "Weak areas were detected, but no tagged source questions "
                "are available for review.",
                "error",
            )
            return redirect("/learning-intelligence")
        selected = dependencies.smart_review_select_candidates(
            candidates, weak, requested
        )
        quiz_data = []
        for number, candidate in enumerate(selected, start=1):
            item = dependencies.question_payload_from_db(
                cur, candidate["question_id"]
            )
            if not item:
                continue
            item["number"] = number
            quiz_data.append(item)
    finally:
        conn.close()

    if not quiz_data:
        flash("No usable source questions were available for Smart Review.", "error")
        return redirect("/learning-intelligence")

    topic_names = [topic["name"] for topic in weak[:3]]
    suffix = ", ".join(topic_names)
    if len(weak) > 3:
        suffix += f" +{len(weak) - 3} more"
    quiz_title = f"Smart Review — {suffix}"
    _quiz_id, html_name = dependencies.publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="smart_review",
        exam_minutes=90,
        snapshot_existing_assets=True,
    )
    return redirect(f"/quizzes/{html_name}")


def concept_review_generate(dependencies):
    """Build focused practice from one canonical concept and its source quizzes."""
    try:
        concept_id = int(request.form.get("concept_id", ""))
    except (TypeError, ValueError):
        concept_id = 0
    try:
        requested = int(request.form.get("question_count", "20"))
    except (TypeError, ValueError):
        requested = 20
    requested = max(1, min(requested, 50))

    if concept_id < 1:
        flash("Choose a valid concept for focused review.", "error")
        return redirect("/learning-intelligence")

    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        payload = dependencies.learning_intelligence_payload(cur)
        topic = next(
            (
                candidate
                for candidate in payload.get("topics") or []
                if candidate.get("concept_id") == concept_id
            ),
            None,
        )
        if topic is None:
            flash("That concept is no longer available.", "error")
            return redirect("/learning-intelligence")

        candidates = dependencies.review_candidates_for_topics(cur, [topic])
        if not candidates:
            flash(
                "No tagged source questions are available for that concept.",
                "info",
            )
            return redirect("/learning-intelligence")

        selected = dependencies.review_select_candidates(
            candidates, [topic], requested
        )
        quiz_data = []
        for number, candidate in enumerate(selected, start=1):
            item = dependencies.question_payload_from_db(
                cur, candidate["question_id"]
            )
            if not item:
                continue
            item["number"] = number
            quiz_data.append(item)
        topic_name = topic["name"]
    finally:
        conn.close()

    if not quiz_data:
        flash("No usable source questions were available for Concept Review.", "error")
        return redirect("/learning-intelligence")

    quiz_title = f"Concept Review — {topic_name}"
    _quiz_id, html_name = dependencies.publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="concept_review",
        exam_minutes=90,
        snapshot_existing_assets=True,
    )
    return redirect(f"/quizzes/{html_name}")


def review_schedule_page(dependencies):
    return send_from_directory(dependencies.static_folder(), "review-schedule.html")


def review_schedule_api(dependencies):
    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        return jsonify(dependencies.review_schedule_payload(cur))
    finally:
        conn.close()


def _topics_for_review_scope(topics, scope):
    if scope == "upcoming":
        return [
            topic
            for topic in topics
            if topic.get("review_state") in ("overdue", "due", "due_soon")
        ]
    if scope == "all":
        return topics
    return [
        topic
        for topic in topics
        if topic.get("review_state") in ("overdue", "due")
    ]


def spaced_review_preview_api(dependencies):
    scope = str(request.args.get("scope") or "due").strip().lower()
    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        schedule = dependencies.review_schedule_payload(cur)
        topics = schedule.get("topics") or []
        chosen = _topics_for_review_scope(topics, scope)
        candidates = dependencies.review_candidates_for_topics(cur, chosen)
        return jsonify(
            {
                "scope": scope,
                "topics": [
                    {
                        "name": topic["name"],
                        "review_state": topic["review_state"],
                        "next_review": topic["next_review"],
                        "retained_mastery": topic["retained_mastery"],
                    }
                    for topic in chosen
                ],
                "candidate_questions": len(candidates),
                "questions": [
                    {
                        "question_id": candidate["question_id"],
                        "question": candidate["question_text"],
                        "topics": candidate["topic_names"],
                    }
                    for candidate in candidates[:50]
                ],
            }
        )
    finally:
        conn.close()


def spaced_review_generate(dependencies):
    try:
        requested = int(request.form.get("question_count", "20"))
    except (TypeError, ValueError):
        requested = 20
    requested = max(1, min(requested, 50))
    scope = str(request.form.get("scope") or "due").strip().lower()

    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        schedule = dependencies.review_schedule_payload(cur)
        topics = schedule.get("topics") or []
        chosen = _topics_for_review_scope(topics, scope)
        if not chosen:
            flash("No topics match the selected spaced-review window yet.", "info")
            return redirect("/review-schedule")
        candidates = dependencies.review_candidates_for_topics(cur, chosen)
        if not candidates:
            flash(
                "Review topics are scheduled, but no tagged source questions "
                "are available.",
                "error",
            )
            return redirect("/review-schedule")
        selected = dependencies.review_select_candidates(
            candidates, chosen, requested
        )
        quiz_data = []
        for number, candidate in enumerate(selected, start=1):
            item = dependencies.question_payload_from_db(
                cur, candidate["question_id"]
            )
            if not item:
                continue
            item["number"] = number
            quiz_data.append(item)
    finally:
        conn.close()

    if not quiz_data:
        flash("No usable source questions were available for Spaced Review.", "error")
        return redirect("/review-schedule")

    topic_names = [topic["name"] for topic in chosen[:3]]
    suffix = ", ".join(topic_names)
    if len(chosen) > 3:
        suffix += f" +{len(chosen) - 3} more"
    quiz_title = f"Spaced Review — {suffix}"
    _quiz_id, html_name = dependencies.publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="spaced_review",
        exam_minutes=90,
        snapshot_existing_assets=True,
    )
    return redirect(f"/quizzes/{html_name}")


def learning_diagnostics_page(dependencies):
    return send_from_directory(
        dependencies.static_root(), "learning-diagnostics.html"
    )


def learning_diagnostics_api(dependencies):
    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        return jsonify(dependencies.question_diagnostics_payload(cur))
    finally:
        conn.close()


def learning_profile_page(dependencies):
    return send_from_directory(dependencies.static_folder(), "learning-profile.html")


def learning_profile_api(dependencies):
    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        return jsonify(dependencies.learning_profile_payload(cur))
    finally:
        conn.close()


def learning_intelligence_page(dependencies):
    return send_from_directory(
        dependencies.static_folder(), "learning-intelligence.html"
    )


def learning_intelligence_topics_api(dependencies):
    conn = dependencies.get_db()
    cur = conn.cursor()
    try:
        return jsonify(dependencies.learning_intelligence_payload(cur))
    finally:
        conn.close()


def create_learning_blueprint(dependencies):
    blueprint = Blueprint("learning", __name__)
    rules = (
        ("/record_attempt", "record_attempt", record_attempt, ["POST"]),
        (
            "/api/learning-events/study-response",
            "record_study_learning_event",
            record_study_learning_event,
            ["POST"],
        ),
        (
            "/api/learning-foundation/summary",
            "learning_foundation_summary",
            learning_foundation_summary,
            ["GET"],
        ),
        (
            "/api/smart-review/preview",
            "smart_review_preview_api",
            smart_review_preview_api,
            ["GET"],
        ),
        (
            "/smart-review/generate",
            "smart_review_generate",
            smart_review_generate,
            ["POST"],
        ),
        (
            "/concept-review/generate",
            "concept_review_generate",
            concept_review_generate,
            ["POST"],
        ),
        (
            "/review-schedule",
            "review_schedule_page",
            review_schedule_page,
            ["GET"],
        ),
        (
            "/api/review-schedule",
            "review_schedule_api",
            review_schedule_api,
            ["GET"],
        ),
        (
            "/api/spaced-review/preview",
            "spaced_review_preview_api",
            spaced_review_preview_api,
            ["GET"],
        ),
        (
            "/spaced-review/generate",
            "spaced_review_generate",
            spaced_review_generate,
            ["POST"],
        ),
        (
            "/learning-diagnostics",
            "learning_diagnostics_page",
            learning_diagnostics_page,
            ["GET"],
        ),
        (
            "/api/learning-diagnostics",
            "learning_diagnostics_api",
            learning_diagnostics_api,
            ["GET"],
        ),
        (
            "/learning-profile",
            "learning_profile_page",
            learning_profile_page,
            ["GET"],
        ),
        (
            "/api/learning-profile",
            "learning_profile_api",
            learning_profile_api,
            ["GET"],
        ),
        (
            "/learning-intelligence",
            "learning_intelligence_page",
            learning_intelligence_page,
            ["GET"],
        ),
        (
            "/api/learning-intelligence/topics",
            "learning_intelligence_topics_api",
            learning_intelligence_topics_api,
            ["GET"],
        ),
    )
    for rule, endpoint, view_func, methods in rules:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
    return blueprint
