"""Source-specific routes for External AI quiz building, review, and publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, flash, redirect, render_template, request, url_for

from dlms.services import external_ai_structured, question_review


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class ExternalAIRouteDependencies:
    """Application services used by the additive External AI route family."""

    build_prompt: Dependency
    stage_response: Dependency
    load_draft: Dependency
    update_review_draft: Dependency
    delete_draft: Dependency
    publish_quiz: Dependency
    normalize_exam_minutes: Dependency
    print_message: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def _builder_values(form=None):
    values = form if form is not None else {}
    return {
        "topic": str(values.get("topic") or ""),
        "audience": str(values.get("audience") or "General learner"),
        "difficulty": str(values.get("difficulty") or "Mixed"),
        "question_count": str(values.get("question_count") or "10"),
        "source_expectations": str(
            values.get("source_expectations")
            or "Use reliable sources appropriate to the topic."
        ),
        "source": {
            name: str(values.get(f"source_{name}") or "")
            for name in external_ai_structured.EXTERNAL_AI_PROMPT_SOURCE_FIELDS
        },
        "ai_response": str(values.get("ai_response") or ""),
    }


def _build_prompt(dependencies, values):
    try:
        question_count = int(values["question_count"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Question count must be a whole number between 1 and 100."
        ) from exc
    return dependencies.build_prompt(
        values["topic"],
        question_count,
        audience=values["audience"],
        difficulty=values["difficulty"],
        source_expectations=values["source_expectations"],
        requested_source=values["source"],
    )


def _builder_response_bound_error(values):
    try:
        response_bytes = len(values["ai_response"].encode("utf-8"))
    except UnicodeEncodeError:
        values["ai_response"] = ""
        return "The AI response contains invalid Unicode and was not retained."
    if response_bytes > external_ai_structured.EXTERNAL_AI_MAX_INPUT_BYTES:
        values["ai_response"] = ""
        return (
            "The AI response exceeds the 1 MiB paste limit and was not retained."
        )
    return None


def _render_builder(values, *, prompt="", errors=(), status=200):
    return render_template(
        "external_ai/builder.html",
        builder=values,
        generated_prompt=prompt,
        errors=list(errors),
        max_questions=external_ai_structured.EXTERNAL_AI_MAX_QUESTIONS,
        max_response_bytes=external_ai_structured.EXTERNAL_AI_MAX_INPUT_BYTES,
    ), status


def external_ai_builder(_dependencies):
    return _render_builder(_builder_values(), status=200)


def external_ai_builder_prompt(dependencies):
    values = _builder_values(request.form)
    response_error = _builder_response_bound_error(values)
    if response_error:
        return _render_builder(values, errors=[response_error], status=413)
    try:
        prompt = _build_prompt(dependencies, values)
    except ValueError as exc:
        return _render_builder(values, errors=[str(exc)], status=400)
    return _render_builder(values, prompt=prompt, status=200)


def external_ai_builder_validate(dependencies):
    values = _builder_values(request.form)
    response_error = _builder_response_bound_error(values)
    if response_error:
        return _render_builder(values, errors=[response_error], status=413)
    try:
        prompt = _build_prompt(dependencies, values)
    except ValueError as exc:
        return _render_builder(values, errors=[str(exc)], status=400)

    try:
        draft_id, _review = dependencies.stage_response(values["ai_response"])
    except external_ai_structured.ExternalAIStructuredError as exc:
        return _render_builder(values, prompt=prompt, errors=[str(exc)], status=400)
    except Exception as exc:
        dependencies.print_message(
            f"[EXTERNAL AI RESPONSE STAGING ERROR] {type(exc).__name__}"
        )
        return _render_builder(
            values,
            prompt=prompt,
            errors=["The response could not be staged safely. Try again."],
            status=500,
        )
    return redirect(url_for("external_ai.external_ai_review", draft_id=draft_id))


def _load_review_or_redirect(dependencies, draft_id):
    try:
        stored = dependencies.load_draft(draft_id)
        return stored, None
    except Exception as exc:
        dependencies.print_message(
            f"[EXTERNAL AI REVIEW LOAD ERROR] {type(exc).__name__}"
        )
        flash("The External AI review session is unavailable or expired.", "error")
        return None, redirect("/upload")


def external_ai_review(dependencies, draft_id):
    stored, failure = _load_review_or_redirect(dependencies, draft_id)
    if failure is not None:
        return failure
    try:
        draft = external_ai_structured.external_ai_review_presentation(stored)
    except ValueError as exc:
        dependencies.print_message(
            f"[EXTERNAL AI REVIEW DATA ERROR] {type(exc).__name__}"
        )
        flash(str(exc), "error")
        return redirect("/upload")
    return render_template("external_ai/review.html", draft=draft)


def external_ai_publish(dependencies, draft_id):
    stored, failure = _load_review_or_redirect(dependencies, draft_id)
    if failure is not None:
        return failure
    review_draft = stored["review_draft"]
    try:
        submitted = question_review.parse_question_review_payload(
            request.form.get("review_payload") or ""
        )
        result = question_review.validate_quiz_review_submission(
            review_draft,
            submitted,
            title=request.form.get("quiz_title"),
            source={
                name: request.form.get(f"source_{name}")
                for name in ("organization", "dataset", "version", "url", "license")
            },
        )
    except question_review.QuestionReviewPayloadError as exc:
        flash(str(exc), "error")
        return redirect(url_for("external_ai.external_ai_review", draft_id=draft_id))

    try:
        dependencies.update_review_draft(draft_id, result["review_draft"])
    except Exception as exc:
        dependencies.print_message(
            f"[EXTERNAL AI REVIEW UPDATE ERROR] {type(exc).__name__}"
        )
        flash("The repaired draft could not be saved safely.", "error")
        return redirect(url_for("external_ai.external_ai_review", draft_id=draft_id))

    if result["errors"]:
        first = result["errors"][0]
        remainder = len(result["errors"]) - 1
        flash(
            first + (f" Review also found {remainder} more issue(s)." if remainder else ""),
            "error",
        )
        return redirect(url_for("external_ai.external_ai_review", draft_id=draft_id))

    exam_minutes = dependencies.normalize_exam_minutes(
        request.form.get("exam_minutes")
    )
    try:
        quiz_id, _html_name = dependencies.publish_quiz(
            result["review_draft"]["title"],
            result["publish_questions"],
            filename_prefix="external_ai",
            exam_minutes=exam_minutes,
        )
    except Exception as exc:
        dependencies.print_message(
            f"[EXTERNAL AI QUIZ PUBLICATION ERROR] {type(exc).__name__}"
        )
        flash(
            "The quiz could not be published. Your reviewed draft was preserved.",
            "error",
        )
        return redirect(url_for("external_ai.external_ai_review", draft_id=draft_id))

    try:
        dependencies.delete_draft(draft_id)
    except Exception as exc:
        dependencies.print_message(
            f"[EXTERNAL AI DRAFT CLEANUP ERROR] {type(exc).__name__}"
        )
        flash(
            "Quiz published, but its temporary review data could not be removed.",
            "warning",
        )
    flash(
        f"Published '{result['review_draft']['title']}' after Review & Repair.",
        "success",
    )
    return redirect(f"/edit_quiz/{quiz_id}")


def external_ai_cancel(dependencies, draft_id):
    try:
        dependencies.delete_draft(draft_id)
    except FileNotFoundError:
        pass
    except Exception as exc:
        dependencies.print_message(
            f"[EXTERNAL AI DRAFT CANCEL ERROR] {type(exc).__name__}"
        )
        flash("The temporary External AI draft could not be removed.", "error")
        return redirect(url_for("external_ai.external_ai_review", draft_id=draft_id))
    flash("External AI review draft removed.", "success")
    return redirect("/upload")


def create_external_ai_blueprint(
    dependencies: ExternalAIRouteDependencies,
) -> Blueprint:
    blueprint = Blueprint("external_ai", __name__)
    routes = (
        (
            "/external-ai/quiz-builder",
            "external_ai_builder",
            external_ai_builder,
            ["GET"],
        ),
        (
            "/external-ai/quiz-builder/prompt",
            "external_ai_builder_prompt",
            external_ai_builder_prompt,
            ["POST"],
        ),
        (
            "/external-ai/quiz-builder/validate",
            "external_ai_builder_validate",
            external_ai_builder_validate,
            ["POST"],
        ),
        (
            "/external-ai/review/<draft_id>",
            "external_ai_review",
            external_ai_review,
            ["GET"],
        ),
        (
            "/external-ai/review/<draft_id>/publish",
            "external_ai_publish",
            external_ai_publish,
            ["POST"],
        ),
        (
            "/external-ai/review/<draft_id>/cancel",
            "external_ai_cancel",
            external_ai_cancel,
            ["POST"],
        ),
    )
    for rule, endpoint, view_func, methods in routes:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
    return blueprint
