"""Law Study landing, import, case-review, mutation, and export routes."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, Response, redirect, render_template, request, url_for


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class LawRouteDependencies:
    """Configured application services required by the Law route family."""

    app_version: Dependency
    default_law_ai_prompt: Dependency
    get_portal_title: Dependency
    load_portal_config: Dependency
    load_law_registry: Dependency
    law_case_path: Dependency
    law_import_path: Dependency
    make_law_case_slug: Dependency
    safe_law_import_filename: Dependency
    save_law_raw_packet: Dependency
    parse_law_packet_sections: Dependency
    get_law_case_by_id: Dependency
    load_law_case_data: Dependency
    parse_socratic_questions: Dependency
    start_pending_case_workflow: Dependency
    cancel_pending_case_workflow: Dependency
    list_law_raw_imports: Dependency
    load_law_raw_packet: Dependency
    delete_law_raw_packet: Dependency
    create_law_case_from_import: Dependency
    update_law_case_details: Dependency
    delete_law_case_and_registry: Dependency
    update_law_case_notes: Dependency
    update_law_case_socratic_answers: Dependency
    update_law_case_irac_response: Dependency
    build_law_case_export: Dependency
    secure_filename: Dependency
    now: Dependency
    from_timestamp: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def law_study_home(dependencies):
    portal_title = dependencies.get_portal_title()
    law_registry = dependencies.load_law_registry()
    saved_cases = len(law_registry.get("cases", []))
    course_count = len(law_registry.get("folders", []))

    return render_template(
        "law/index.html",
        portal_title=portal_title,
        law_registry=law_registry,
        saved_cases=saved_cases,
        course_count=course_count,
    )


def law_create_case_review(dependencies):
    portal_title = dependencies.get_portal_title()
    law_registry = dependencies.load_law_registry()
    law_folders = law_registry.get("folders", [])

    case_name = ""
    course = law_folders[0] if law_folders else "Torts"
    ai_provider = "chatgpt"
    generated_prompt = ""
    ai_provider_url = ""
    case_slug = ""

    include_case_brief = True
    include_socratic = True
    include_irac = True
    include_flashcards = True

    if request.method == "POST":
        case_name = request.form.get("case_name", "").strip()
        course = request.form.get("course", course).strip()
        ai_provider = request.form.get("ai_provider", "chatgpt").strip().lower()

        case_slug = dependencies.make_law_case_slug(case_name)

        if case_name:
            try:
                dependencies.start_pending_case_workflow(
                    law_registry,
                    case_name=case_name,
                    case_slug=case_slug,
                    course=course,
                    created_at=dependencies.now().isoformat(timespec="seconds"),
                )
            except Exception as exc:
                print(f"[LAW WORKFLOW ERROR] Failed starting case workflow: {exc}")
                return "Failed to start Law case workflow", 500

        provider_urls = {
            "chatgpt": "https://chatgpt.com/",
            "claude": "https://claude.ai/",
            "gemini": "https://gemini.google.com/",
            "local": dependencies.load_portal_config().get("ai_custom_url", ""),
        }

        ai_provider_url = provider_urls.get(ai_provider, "")

        include_case_brief = "include_case_brief" in request.form
        include_socratic = "include_socratic" in request.form
        include_irac = "include_irac" in request.form
        include_flashcards = "include_flashcards" in request.form

        requested_sections = []

        if include_case_brief:
            requested_sections.append(
                """
1. Case Brief
   - Full case name and citation
   - Court and year
   - Procedural posture
   - Key facts
   - Issue
   - Rule
   - Holding
   - Reasoning
   - Important concurrence or dissent, if any
""".strip()
            )

        if include_socratic:
            requested_sections.append(
                """
    2. Socratic Review
    - Five cold-call style questions
    - One fact-change question
    - One policy question
    - Do not place the model answers directly under the questions

    2A. Socratic Answer Key
    - Provide short model guidance for each Socratic question
    - Keep each answer concise
    - This section should be treated as hidden-by-default in DLMS
    - Label each answer so it clearly matches the question number
    """.strip()
            )

        if include_irac:
            requested_sections.append(
                """
3. IRAC Drill
   - One short practice fact pattern based on the case
   - Issue
   - Rule
   - Application / Analysis
   - Conclusion
   - Model IRAC answer
""".strip()
            )

        if include_flashcards:
            requested_sections.append(
                """
4. Rule Flashcards
   - Five active-recall flashcards
   - Front: question
   - Back: concise answer
   - Focus on rule, holding, reasoning, and key facts
""".strip()
            )

        if case_name:
            cfg = dependencies.load_portal_config()
            law_prompt_template = str(
                cfg.get("law_ai_prompt_template")
                or dependencies.default_law_ai_prompt()
            ).strip()
            generated_prompt = (
                law_prompt_template.replace("{{case_name}}", case_name)
                .replace("{{course}}", course)
                .replace("{{study_sections}}", chr(10).join(requested_sections))
            )
        else:
            generated_prompt = "Please enter a case name before generating the AI prompt."

    return render_template(
        "law/create.html",
        portal_title=portal_title,
        law_folders=law_folders,
        case_name=case_name,
        case_slug=case_slug,
        course=course,
        ai_provider=ai_provider,
        generated_prompt=generated_prompt,
        ai_provider_url=ai_provider_url,
        include_case_brief=include_case_brief,
        include_socratic=include_socratic,
        include_irac=include_irac,
        include_flashcards=include_flashcards,
    )


def law_cancel_pending_workflow(dependencies):
    registry = dependencies.load_law_registry()

    if "pending_case_workflow" in registry:
        try:
            dependencies.cancel_pending_case_workflow(registry)
        except Exception as exc:
            print(f"[LAW WORKFLOW ERROR] Failed cancelling case workflow: {exc}")
            return "Failed to cancel Law case workflow", 500

    return redirect("/law/import?workflow_cancelled=1")


def law_import_case_packet(dependencies):
    portal_title = dependencies.get_portal_title()

    law_registry = dependencies.load_law_registry()
    pending_workflow = law_registry.get("pending_case_workflow", {}) or {}

    if pending_workflow:
        case_name = str(pending_workflow.get("case_name", "")).strip()
        case_slug = str(pending_workflow.get("case_slug", "")).strip()
    else:
        case_name = request.values.get("case_name", "").strip()
        case_slug = request.values.get("case_slug", "").strip()

    if case_name and not case_slug:
        case_slug = dependencies.make_law_case_slug(case_name)

    raw_packet = ""
    packet_submitted = False
    line_count = 0
    char_count = 0
    saved_file = ""
    save_message = ""
    save_message_category = ""

    if request.method == "POST":
        raw_packet = request.form.get("raw_packet", "").strip()
        action = request.form.get("action", "preview")

        packet_submitted = bool(raw_packet)

        if raw_packet:
            line_count = len(raw_packet.splitlines())
            char_count = len(raw_packet)

            if action in {"save_and_preview", "save_raw"}:
                try:
                    saved_file = dependencies.save_law_raw_packet(
                        raw_packet, case_slug
                    )

                    if action == "save_and_preview":
                        return redirect(
                            url_for(
                                "law.law_view_saved_import", filename=saved_file
                            )
                        )

                    save_message = f"Saved raw case packet as {saved_file}"
                    save_message_category = "success"

                except Exception as exc:
                    print(f"[LAW IMPORT ERROR] Failed saving raw packet: {exc}")
                    save_message = "Error: failed to save raw case packet."
                    save_message_category = "error"

    return render_template(
        "law/import.html",
        portal_title=portal_title,
        case_name=case_name,
        case_slug=case_slug,
        raw_packet=raw_packet,
        packet_submitted=packet_submitted,
        line_count=line_count,
        char_count=char_count,
        saved_file=saved_file,
        save_message=save_message,
        save_message_category=save_message_category,
    )


def law_saved_imports(dependencies):
    portal_title = dependencies.get_portal_title()

    imports = []

    try:
        imports = dependencies.list_law_raw_imports(imports=imports)
    except Exception as exc:
        print(f"[LAW IMPORTS ERROR] Failed loading saved imports: {exc}")

    return render_template(
        "law/imports.html",
        portal_title=portal_title,
        imports=imports,
    )


def law_view_saved_import(dependencies, filename):
    portal_title = dependencies.get_portal_title()

    safe_name = dependencies.safe_law_import_filename(filename)

    if not safe_name:
        return "Invalid import filename", 400

    import_path = dependencies.law_import_path(safe_name)

    if not os.path.exists(import_path) or not os.path.isfile(import_path):
        return "Saved import not found", 404

    try:
        raw_packet = dependencies.load_law_raw_packet(import_path)
    except Exception as exc:
        print(f"[LAW IMPORT ERROR] Failed reading saved import: {exc}")
        return "Failed to read saved import", 500

    line_count = len(raw_packet.splitlines())
    char_count = len(raw_packet)

    modified = dependencies.from_timestamp(os.stat(import_path).st_mtime).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    size = os.stat(import_path).st_size
    parsed_sections = dependencies.parse_law_packet_sections(raw_packet)

    return render_template(
        "law/import-detail.html",
        portal_title=portal_title,
        filename=safe_name,
        raw_packet=raw_packet,
        line_count=line_count,
        char_count=char_count,
        modified=modified,
        size=size,
        parsed_sections=parsed_sections,
    )


def law_delete_saved_import(dependencies, filename):
    safe_name = dependencies.safe_law_import_filename(filename)

    if not safe_name:
        return "Invalid import filename", 400

    import_path = dependencies.law_import_path(safe_name)

    try:
        dependencies.delete_law_raw_packet(import_path)
    except Exception as exc:
        print(f"[LAW IMPORT ERROR] Failed deleting saved import: {exc}")
        return "Failed to delete saved import", 500

    return redirect("/law/imports?deleted=1")


def law_create_case_from_import(dependencies, filename):
    safe_name = dependencies.safe_law_import_filename(filename)

    if not safe_name:
        return "Invalid import filename", 400

    import_path = dependencies.law_import_path(safe_name)

    if not os.path.exists(import_path) or not os.path.isfile(import_path):
        return "Saved import not found", 404

    try:
        raw_packet = dependencies.load_law_raw_packet(import_path)
    except Exception as exc:
        print(f"[LAW CASE ERROR] Failed reading import: {exc}")
        return "Failed to read saved import", 500

    parsed_sections = dependencies.parse_law_packet_sections(raw_packet)

    if not parsed_sections:
        return (
            "No recognized Law Study sections were found. Cannot create case review yet.",
            400,
        )

    try:
        case_id = dependencies.create_law_case_from_import(
            safe_name, raw_packet, parsed_sections
        )
    except Exception as exc:
        print(f"[LAW CASE ERROR] Failed creating case review: {exc}")
        return "Failed to create case review", 500

    return redirect(url_for("law.law_view_case_review", case_id=case_id))


def law_case_reviews(dependencies):
    portal_title = dependencies.get_portal_title()
    registry = dependencies.load_law_registry()

    cases = registry.get("cases", [])
    cases = sorted(
        cases, key=lambda candidate: str(candidate.get("created_at", "")), reverse=True
    )

    return render_template(
        "law/cases.html",
        portal_title=portal_title,
        cases=cases,
    )


def _law_case_context(dependencies, case_id):
    case_entry = dependencies.get_law_case_by_id(case_id)
    if not case_entry:
        return None, None, None, ("Law case review not found", 404)

    case_file = dependencies.secure_filename(case_entry.get("file") or "")
    if not case_file.lower().endswith(".json"):
        return None, None, None, ("Invalid case file", 400)

    case_path = dependencies.law_case_path(case_file)
    if not os.path.exists(case_path) or not os.path.isfile(case_path):
        return None, None, None, ("Law case file not found", 404)

    return case_entry, case_file, case_path, None


def law_view_case_review(dependencies, case_id):
    portal_title = dependencies.get_portal_title()
    law_registry = dependencies.load_law_registry()
    law_folders = law_registry.get("folders", [])

    case_entry, _case_file, case_path, error = _law_case_context(
        dependencies, case_id
    )
    if error:
        return error

    try:
        case_data = dependencies.load_law_case_data(case_path)
    except Exception as exc:
        print(f"[LAW CASE ERROR] Failed reading case review: {exc}")
        return "Failed to read case review", 500

    sections = case_data.get("sections", {}) or {}
    sources_used = case_data.get("sources_used", "")

    section_cards = [
        {
            "key": "case_brief",
            "title": "Case Brief",
            "icon": "📄",
            "content": sections.get("case_brief", ""),
        }
    ]

    irac_drill_content = sections.get("irac_drill", "")
    rule_flashcards_content = sections.get("rule_flashcards", "")
    socratic_answer_key = sections.get("socratic_answer_key", "")
    socratic_questions = dependencies.parse_socratic_questions(
        sections.get("socratic_review", "")
    )
    socratic_student_answers = case_data.get("socratic_student_answers", {}) or {}
    irac_student_response = case_data.get("irac_student_response", {}) or {}
    socratic_total = len(socratic_questions)

    socratic_answered = 0
    for question in socratic_questions:
        qid = question.get("id")
        answer = str(socratic_student_answers.get(qid, "")).strip()
        if answer:
            socratic_answered += 1

    socratic_progress_text = f"{socratic_answered} of {socratic_total} answered"

    return render_template(
        "law/case-detail.html",
        portal_title=portal_title,
        case_entry=case_entry,
        case_data=case_data,
        rule_flashcards_content=rule_flashcards_content,
        section_cards=section_cards,
        socratic_answer_key=socratic_answer_key,
        socratic_questions=socratic_questions,
        socratic_student_answers=socratic_student_answers,
        socratic_total=socratic_total,
        socratic_answered=socratic_answered,
        socratic_progress_text=socratic_progress_text,
        sources_used=sources_used,
        irac_student_response=irac_student_response,
        irac_drill_content=irac_drill_content,
        law_folders=law_folders,
    )


def law_update_case_review_details(dependencies, case_id):
    case_entry, _case_file, case_path, error = _law_case_context(
        dependencies, case_id
    )
    if error:
        return error

    new_title = request.form.get("title", "").strip()
    new_course = request.form.get("course", "").strip()

    try:
        dependencies.update_law_case_details(
            case_path, case_id, case_entry, new_title, new_course
        )
    except Exception as exc:
        print(f"[LAW CASE ERROR] Failed updating case review details: {exc}")
        return "Failed to update case review details", 500

    return redirect(f"/law/cases/{case_id}?updated=1")


def law_delete_case_review(dependencies, case_id):
    case_entry = dependencies.get_law_case_by_id(case_id)

    if not case_entry:
        return "Law case review not found", 404

    case_file = dependencies.secure_filename(case_entry.get("file") or "")

    if not case_file.lower().endswith(".json"):
        return "Invalid case file", 400

    case_path = dependencies.law_case_path(case_file)

    try:
        registry = dependencies.load_law_registry()
        dependencies.delete_law_case_and_registry(case_path, registry, case_id)
    except Exception as exc:
        print(f"[LAW CASE ERROR] Failed deleting case review: {exc}")
        return "Failed to delete case review", 500

    return redirect("/law/cases?deleted=1")


def law_update_case_review_notes(dependencies, case_id):
    case_entry, _case_file, case_path, error = _law_case_context(
        dependencies, case_id
    )
    if error:
        return error

    student_notes = request.form.get("student_notes", "").strip()

    try:
        dependencies.update_law_case_notes(
            case_path, case_id, student_notes
        )
    except Exception as exc:
        print(f"[LAW CASE ERROR] Failed updating case review notes: {exc}")
        return "Failed to update case review notes", 500

    return redirect(f"/law/cases/{case_id}?notes_updated=1")


def law_update_socratic_answers(dependencies, case_id):
    case_entry, _case_file, case_path, error = _law_case_context(
        dependencies, case_id
    )
    if error:
        return error

    try:
        dependencies.update_law_case_socratic_answers(
            case_path, case_id, request.form.to_dict(flat=True)
        )
    except Exception as exc:
        print(f"[LAW CASE ERROR] Failed updating Socratic answers: {exc}")
        return "Failed to update Socratic answers", 500

    return redirect(f"/law/cases/{case_id}?socratic_answers_updated=1")


def law_update_irac_response(dependencies, case_id):
    case_entry, _case_file, case_path, error = _law_case_context(
        dependencies, case_id
    )
    if error:
        return error

    irac_response = {
        "issue": request.form.get("irac_issue", "").strip(),
        "rule": request.form.get("irac_rule", "").strip(),
        "analysis": request.form.get("irac_analysis", "").strip(),
        "conclusion": request.form.get("irac_conclusion", "").strip(),
    }

    try:
        dependencies.update_law_case_irac_response(
            case_path, case_id, irac_response
        )
    except Exception as exc:
        print(f"[LAW CASE ERROR] Failed updating IRAC response: {exc}")
        return "Failed to update IRAC response", 500

    return redirect(f"/law/cases/{case_id}?irac_updated=1")


def law_export_case_review_txt(dependencies, case_id):
    case_entry, _case_file, case_path, error = _law_case_context(
        dependencies, case_id
    )
    if error:
        return error

    try:
        case_data = dependencies.load_law_case_data(case_path)
    except Exception as exc:
        print(f"[LAW CASE ERROR] Failed exporting case review: {exc}")
        return "Failed to export case review", 500

    export_text, filename = dependencies.build_law_case_export(
        case_data,
        case_id,
        app_version=dependencies.app_version(),
        exported_on=dependencies.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    return Response(
        export_text,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def create_law_blueprint(dependencies: LawRouteDependencies) -> Blueprint:
    """Create the Law Blueprint with the configured application adapters."""
    blueprint = Blueprint("law", __name__)
    rules = (
        ("/law", "law_study_home", law_study_home, ["GET"]),
        ("/law/create", "law_create_case_review", law_create_case_review, ["GET", "POST"]),
        ("/law/workflow/cancel", "law_cancel_pending_workflow", law_cancel_pending_workflow, ["POST"]),
        ("/law/import", "law_import_case_packet", law_import_case_packet, ["GET", "POST"]),
        ("/law/imports", "law_saved_imports", law_saved_imports, ["GET"]),
        ("/law/imports/<path:filename>", "law_view_saved_import", law_view_saved_import, ["GET"]),
        ("/law/imports/<path:filename>/delete", "law_delete_saved_import", law_delete_saved_import, ["POST"]),
        ("/law/imports/<path:filename>/create_case", "law_create_case_from_import", law_create_case_from_import, ["POST"]),
        ("/law/cases", "law_case_reviews", law_case_reviews, ["GET"]),
        ("/law/cases/<case_id>", "law_view_case_review", law_view_case_review, ["GET"]),
        ("/law/cases/<case_id>/update_details", "law_update_case_review_details", law_update_case_review_details, ["POST"]),
        ("/law/cases/<case_id>/delete", "law_delete_case_review", law_delete_case_review, ["POST"]),
        ("/law/cases/<case_id>/update_notes", "law_update_case_review_notes", law_update_case_review_notes, ["POST"]),
        ("/law/cases/<case_id>/update_socratic_answers", "law_update_socratic_answers", law_update_socratic_answers, ["POST"]),
        ("/law/cases/<case_id>/update_irac_response", "law_update_irac_response", law_update_irac_response, ["POST"]),
        ("/law/cases/<case_id>/export.txt", "law_export_case_review_txt", law_export_case_review_txt, ["GET"]),
    )
    for rule, endpoint, view_func, methods in rules:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
    return blueprint
