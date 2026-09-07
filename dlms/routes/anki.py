"""Anki catalog, custom deck, printable-card, and export routes."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, Response, render_template, request


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class AnkiRouteDependencies:
    """Configured application services required by the Anki route family."""

    app_version: Dependency
    get_anki_quiz_choices: Dependency
    get_anki_law_case_choices: Dependency
    get_anki_law_courses: Dependency
    get_anki_missed_summary: Dependency
    get_anki_custom_sources: Dependency
    build_anki_rows_for_quiz: Dependency
    build_anki_rows_for_missed: Dependency
    build_custom_anki_rows: Dependency
    load_law_flashcards_for_selection: Dependency
    load_law_flashcards_for_case: Dependency
    export_quiz_to_apkg: Dependency
    send_temp_anki_package: Dependency
    make_safe_anki_download_name: Dependency
    make_safe_anki_deck_name: Dependency
    export_anki_tsv_for_quiz: Dependency
    load_study_export_selection: Dependency
    load_attempt_missed_rows: Dependency
    load_missed_tsv_rows: Dependency
    attempt_history_context: Dependency
    format_anki_missed_tsv: Dependency
    log_info: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def anki_tools(dependencies):
    quizzes = dependencies.get_anki_quiz_choices()
    law_cases = dependencies.get_anki_law_case_choices()

    anki_source = (request.args.get("source") or "").strip().lower()
    preview_rows = []
    preview_title = ""
    preview_message = ""

    selected_quiz_id = request.args.get("quiz_id", "")
    selected_missed_quiz = request.args.get("missed_quiz_id", "all")
    selected_min_misses = request.args.get("min_misses", "1")
    selected_missed_status = request.args.get("missed_status", "all")

    if anki_source == "quiz" and selected_quiz_id:
        quiz_title, preview_rows = dependencies.build_anki_rows_for_quiz(
            selected_quiz_id
        )
        if quiz_title:
            preview_title = f"{quiz_title} - Quiz Deck"
        else:
            preview_message = "That quiz could not be found."

    elif anki_source == "missed":
        preview_rows = dependencies.build_anki_rows_for_missed(
            selected_missed_quiz,
            selected_min_misses,
            selected_missed_status,
        )
        status_titles = {
            "all": "All Missed Questions",
            "currently_weak": "Currently Weak Questions",
            "repeated": "Repeatedly Missed Questions",
            "recovered": "Recovered Questions",
            "once": "Questions Missed Once",
        }
        preview_title = status_titles.get(
            selected_missed_status,
            "Missed Questions",
        )
        if not preview_rows:
            preview_message = "No missed questions match those filters."

    missed_summary = dependencies.get_anki_missed_summary()
    total_missed_cards = missed_summary["total"]
    total_law_cards = sum(case["card_count"] for case in law_cases)

    return render_template(
        "anki/index.html",
        app_version=dependencies.app_version(),
        quizzes=quizzes,
        anki_source=anki_source,
        preview_rows=preview_rows,
        preview_title=preview_title,
        preview_message=preview_message,
        selected_quiz_id=selected_quiz_id,
        selected_missed_quiz=selected_missed_quiz,
        selected_min_misses=selected_min_misses,
        selected_missed_status=selected_missed_status,
        missed_summary=missed_summary,
        total_missed_cards=total_missed_cards,
        total_law_cards=total_law_cards,
    )


def anki_custom_deck(dependencies):
    sources = dependencies.get_anki_custom_sources()

    deck_name = (request.form.get("deck_name") or "DLMS Custom Deck").strip()
    selected_quiz = request.form.getlist("quiz_cards")
    selected_missed = request.form.getlist("missed_cards")
    selected_law = request.form.getlist("law_cards")
    selected_quiz_tokens = set(selected_quiz)
    selected_missed_tokens = set(selected_missed)
    selected_law_tokens = set(selected_law)
    quiz_groups = []
    for quiz in sources["quiz_groups"]:
        quiz_view = dict(quiz)
        quiz_view["selected_count"] = sum(
            f"quiz:{quiz.get('id')}:{card.get('question_id')}"
            in selected_quiz_tokens
            for card in quiz.get("cards", [])
        )
        quiz_groups.append(quiz_view)

    missed_cards = sources["missed_cards"]
    selected_missed_count = sum(
        (
            f"missed:{card.get('quiz_id')}:"
            f"{card.get('question_id') if card.get('question_id') is not None else card.get('question_number')}"
        )
        in selected_missed_tokens
        for card in missed_cards
    )

    law_groups = []
    for case in sources["law_groups"]:
        case_view = dict(case)
        case_view["selected_count"] = sum(
            f"law:{case.get('id')}:{index}" in selected_law_tokens
            for index, _card in enumerate(case.get("cards", []), start=1)
        )
        law_groups.append(case_view)

    preview_requested = request.method == "POST"
    preview_rows = []

    if preview_requested:
        preview_rows = dependencies.build_custom_anki_rows(
            selected_quiz,
            selected_missed,
            selected_law,
        )

    return render_template(
        "anki/custom.html",
        app_version=dependencies.app_version(),
        deck_name=deck_name,
        preview_requested=preview_requested,
        preview_rows=preview_rows,
        quiz_groups=quiz_groups,
        missed_cards=missed_cards,
        selected_missed_count=selected_missed_count,
        law_groups=law_groups,
        selected_quiz=selected_quiz,
        selected_missed=selected_missed,
        selected_law=selected_law,
    )


def anki_export_custom(dependencies):
    deck_name = (request.form.get("deck_name") or "DLMS Custom Deck").strip()

    deck_rows = dependencies.build_custom_anki_rows(
        request.form.getlist("quiz_cards"),
        request.form.getlist("missed_cards"),
        request.form.getlist("law_cards"),
    )

    if not deck_rows:
        return "Select at least one DLMS item before exporting a custom deck.", 400

    apkg_path = dependencies.export_quiz_to_apkg(deck_name, deck_rows)

    return dependencies.send_temp_anki_package(
        apkg_path,
        dependencies.make_safe_anki_download_name(
            deck_name,
            "DLMS_Custom_Deck",
        ),
    )


def _chunk_printable_cards(rows, size=3):
    rows = list(rows or [])
    return [rows[index:index + size] for index in range(0, len(rows), size)]


def _printable_back_sheet(cards, duplex_flip="long"):
    cards = list(cards or [])
    if duplex_flip == "short":
        return list(reversed(cards))
    return cards


def anki_printable_flashcards(dependencies):
    deck_name = (
        request.form.get("deck_name") or "DLMS Printable Flashcards"
    ).strip()
    duplex_flip = (request.form.get("duplex_flip") or "long").strip().lower()
    if duplex_flip not in {"long", "short"}:
        duplex_flip = "long"

    rows = dependencies.build_custom_anki_rows(
        request.form.getlist("quiz_cards"),
        request.form.getlist("missed_cards"),
        request.form.getlist("law_cards"),
    )
    if not rows:
        return (
            "Select at least one DLMS item before creating printable flashcards.",
            400,
        )

    sheets = []
    for sheet_number, cards in enumerate(
        _chunk_printable_cards(rows, 3), start=1
    ):
        sheets.append(
            {
                "number": sheet_number,
                "fronts": cards,
                "backs": _printable_back_sheet(cards, duplex_flip),
            }
        )

    return render_template(
        "anki/printable.html",
        deck_name=deck_name,
        rows=rows,
        sheets=sheets,
        duplex_flip=duplex_flip,
    )


def anki_law_tools(dependencies):
    law_cases = dependencies.get_anki_law_case_choices()
    law_courses = dependencies.get_anki_law_courses(law_cases)

    preview_rows = []
    preview_title = ""
    preview_message = ""

    selected_case_ids = request.args.getlist("case_ids")
    selected_law_scope = (request.args.get("law_scope") or "cases").strip().lower()
    selected_law_course = (request.args.get("law_course") or "").strip()
    preview_requested = (request.args.get("preview") or "").strip() == "1"

    if preview_requested:
        if selected_law_scope == "course":
            if selected_law_course:
                _selection_meta, preview_rows = (
                    dependencies.load_law_flashcards_for_selection(
                        course=selected_law_course
                    )
                )
                preview_title = f"{selected_law_course} - Rule Flashcards"
                if not preview_rows:
                    preview_message = (
                        "No recognized Rule Flashcards were found for that course."
                    )
            else:
                preview_message = "Choose a course before previewing."

        else:
            if selected_case_ids:
                selection_meta, preview_rows = (
                    dependencies.load_law_flashcards_for_selection(
                        case_ids=selected_case_ids
                    )
                )
                case_count = selection_meta.get("case_count", 0)
                preview_title = (
                    f"{case_count} Saved Cases - Rule Flashcards"
                    if case_count != 1
                    else "Saved Case - Rule Flashcards"
                )
                if not preview_rows:
                    preview_message = (
                        "No recognized Rule Flashcards were found in the selected cases."
                    )
            else:
                preview_message = (
                    "Choose at least one saved case before previewing."
                )

    total_law_cards = sum(case["card_count"] for case in law_cases)

    return render_template(
        "anki/law.html",
        app_version=dependencies.app_version(),
        law_cases=law_cases,
        law_courses=law_courses,
        preview_requested=preview_requested,
        preview_rows=preview_rows,
        preview_title=preview_title,
        preview_message=preview_message,
        selected_case_ids=selected_case_ids,
        selected_law_scope=selected_law_scope,
        selected_law_course=selected_law_course,
        total_law_cards=total_law_cards,
    )


def anki_export_quiz(dependencies):
    quiz_id = request.form.get("quiz_id")
    quiz_title, deck_rows = dependencies.build_anki_rows_for_quiz(quiz_id)

    if not quiz_title or not deck_rows:
        return "No quiz cards were available to export.", 404

    deck_name = f"{quiz_title} - DLMS"
    apkg_path = dependencies.export_quiz_to_apkg(deck_name, deck_rows)

    return dependencies.send_temp_anki_package(
        apkg_path,
        dependencies.make_safe_anki_download_name(
            f"{quiz_title}_DLMS",
            "dlms_quiz",
        ),
    )


def anki_export_missed(dependencies):
    quiz_id = request.form.get("quiz_id", "all")
    min_misses = request.form.get("min_misses", "1")
    missed_status = request.form.get("missed_status", "all")

    deck_rows = dependencies.build_anki_rows_for_missed(
        quiz_id,
        min_misses,
        missed_status,
    )

    if not deck_rows:
        return "No missed questions matched those filters.", 404

    if quiz_id not in ("", "all", None):
        quiz_title, _unused = dependencies.build_anki_rows_for_quiz(quiz_id)
        deck_name = f"{quiz_title or 'DLMS'} - Missed Questions"
        file_base = f"{quiz_title or 'DLMS'}_missed_questions"
    else:
        deck_name = "DLMS - Missed Questions"
        file_base = "DLMS_missed_questions"

    try:
        threshold = max(1, int(min_misses or 1))
    except (TypeError, ValueError):
        threshold = 1

    status_names = {
        "currently_weak": "Currently Weak",
        "repeated": "Repeatedly Missed",
        "recovered": "Recovered",
        "once": "Missed Once",
    }

    if missed_status in status_names:
        deck_name += f" - {status_names[missed_status]}"
        file_base += f"_{missed_status}"

    if threshold > 1:
        deck_name += f" - {threshold}+ Misses"
        file_base += f"_{threshold}_plus"

    apkg_path = dependencies.export_quiz_to_apkg(deck_name, deck_rows)

    return dependencies.send_temp_anki_package(
        apkg_path,
        dependencies.make_safe_anki_download_name(
            file_base,
            "dlms_missed_questions",
        ),
    )


def anki_export_law(dependencies):
    law_scope = (request.form.get("law_scope") or "cases").strip().lower()
    case_ids = request.form.getlist("case_ids")
    law_course = (request.form.get("law_course") or "").strip()

    legacy_case_id = request.form.get("case_id")
    if legacy_case_id and not case_ids:
        case_ids = [legacy_case_id]

    if law_scope == "course":
        if not law_course:
            return "Choose a Law Study course to export.", 400

        _selection_meta, deck_rows = (
            dependencies.load_law_flashcards_for_selection(course=law_course)
        )

        if not deck_rows:
            return "No recognized Rule Flashcards were found for that course.", 404

        deck_name = f"DLMS - Law - {law_course}"
        file_base = f"{law_course}_rule_flashcards"

    else:
        if not case_ids:
            return "Choose at least one saved Law Study case to export.", 400

        selection_meta, deck_rows = (
            dependencies.load_law_flashcards_for_selection(case_ids=case_ids)
        )

        if not deck_rows:
            return (
                "No recognized Rule Flashcards were found in the selected cases.",
                404,
            )

        if selection_meta["case_count"] == 1:
            title = selection_meta["case_titles"][0]
            case_meta, _cards = dependencies.load_law_flashcards_for_case(
                case_ids[0]
            )
            course = (case_meta or {}).get("course") or "Law Study"
            deck_name = f"DLMS - Law - {course} - {title}"
            file_base = f"{course}_{title}_flashcards"
        else:
            deck_name = (
                "DLMS - Law - Selected Cases "
                f"({selection_meta['case_count']})"
            )
            file_base = (
                f"DLMS_Law_{selection_meta['case_count']}_selected_cases"
            )

    apkg_path = dependencies.export_quiz_to_apkg(deck_name, deck_rows)

    return dependencies.send_temp_anki_package(
        apkg_path,
        dependencies.make_safe_anki_download_name(
            file_base,
            "dlms_law_flashcards",
        ),
    )


def export_anki_quiz_tsv(dependencies, quiz_id):
    tsv = dependencies.export_anki_tsv_for_quiz(quiz_id)

    dependencies.log_info(
        "[ANKI-TSV] Export quiz TSV | quiz_id=%s | bytes=%s",
        quiz_id,
        len(tsv.encode("utf-8")),
    )

    return Response(
        tsv,
        mimetype="text/tab-separated-values; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=quiz_{quiz_id}_anki.tsv"
        },
    )


def export_anki_study(dependencies):
    data = request.get_json(force=True) or {}

    quiz_id = data.get("quiz_id")
    question_numbers = data.get("question_numbers") or []

    try:
        quiz_id = int(quiz_id)
        question_numbers = sorted(
            {
                int(number)
                for number in question_numbers
                if str(number).isdigit() and int(number) > 0
            }
        )
    except (TypeError, ValueError):
        return {"error": "Invalid quiz or question selection"}, 400

    if not question_numbers:
        return {"error": "No study questions selected"}, 400

    quiz_found, quiz_title, deck_rows = dependencies.load_study_export_selection(
        quiz_id, question_numbers
    )

    if not quiz_found:
        return {"error": "Quiz not found"}, 404

    if not deck_rows:
        return {"error": "No valid questions were selected"}, 400

    deck_name = f"{quiz_title or 'DLMS Study Questions'} - Study Review"

    apkg_path = dependencies.export_quiz_to_apkg(deck_name, deck_rows)

    return dependencies.send_temp_anki_package(
        apkg_path,
        "dlms_study_selected.apkg",
    )


def export_anki_genanki(dependencies):
    data = request.get_json(force=True) or {}

    attempt_id = data.get("attempt_id")

    if not attempt_id:
        return {"error": "Missing attempt_id"}, 400

    rows = dependencies.load_attempt_missed_rows(attempt_id)

    if not rows:
        return {"error": "No missed questions found for this attempt"}, 404

    print(f"[ANKI] exporting {len(rows)} missed questions")

    deck_rows = []
    for row in rows:
        question = (row["question_text"] or "").strip()
        choices_text = (row["choices_text"] or "").strip()
        correct_text = (row["correct_text"] or "").strip()

        front_parts = [question]
        if choices_text:
            front_parts.append("")
            front_parts.append(choices_text)

        front = "\n".join(front_parts)
        back = "Correct Answer\n" + correct_text
        deck_rows.append({"front": front, "back": back})

    quiz_id = rows[0]["quiz_id"]
    registry_map, _installed_packs, _origin_by_quiz_id = (
        dependencies.attempt_history_context()
    )
    registry_entry = (
        registry_map.get(int(quiz_id), {}) if quiz_id is not None else {}
    )
    source_title = (
        registry_entry.get("title") or rows[0]["quiz_title"] or "DLMS Quiz"
    )
    safe_title = dependencies.make_safe_anki_deck_name(source_title, "DLMS Quiz")
    deck_name = f"{safe_title} - Missed Questions"
    download_name = dependencies.make_safe_anki_download_name(
        f"{safe_title}_Missed_Questions",
        "DLMS_Missed_Questions",
    )

    apkg_path = dependencies.export_quiz_to_apkg(deck_name, deck_rows)

    return dependencies.send_temp_anki_package(apkg_path, download_name)


def export_anki_missed_tsv(dependencies):
    data = request.get_json(force=True) or {}

    attempt_id = data.get("attempt_id")
    attempt_qnums = (
        data.get("attempt_question_numbers") or data.get("question_numbers") or []
    )

    if not attempt_id or not attempt_qnums:
        print("[ANKI DEBUG] raw payload:", data)
        return {"error": "Missing attempt_id or attempt_question_numbers"}, 400

    attempt_qnums = [
        int(value)
        for value in attempt_qnums
        if value is not None and str(value).isdigit()
    ]

    if not attempt_qnums:
        return {"error": "No valid question numbers after filtering"}, 400

    rows = dependencies.load_missed_tsv_rows(attempt_id, attempt_qnums)

    dependencies.log_info(
        "[ANKI-TSV] Missed TSV rows fetched: %s | attempt_id=%s",
        len(rows),
        attempt_id,
    )

    tsv = dependencies.format_anki_missed_tsv(rows)

    return Response(
        tsv,
        mimetype="text/tab-separated-values; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=missed_questions_anki.tsv"
        },
    )


def create_anki_blueprint(dependencies):
    blueprint = Blueprint("anki", __name__)
    rules = (
        ("/anki", "anki_tools", anki_tools, ["GET"]),
        ("/anki/custom", "anki_custom_deck", anki_custom_deck, ["GET", "POST"]),
        (
            "/anki/export/custom",
            "anki_export_custom",
            anki_export_custom,
            ["POST"],
        ),
        (
            "/anki/printable",
            "anki_printable_flashcards",
            anki_printable_flashcards,
            ["POST"],
        ),
        ("/anki/law", "anki_law_tools", anki_law_tools, ["GET"]),
        (
            "/anki/export/quiz",
            "anki_export_quiz",
            anki_export_quiz,
            ["POST"],
        ),
        (
            "/anki/export/missed",
            "anki_export_missed",
            anki_export_missed,
            ["POST"],
        ),
        (
            "/anki/export/law",
            "anki_export_law",
            anki_export_law,
            ["POST"],
        ),
        (
            "/export/anki/quiz/<int:quiz_id>",
            "export_anki_quiz_tsv",
            export_anki_quiz_tsv,
            ["GET"],
        ),
        (
            "/export/anki/study",
            "export_anki_study",
            export_anki_study,
            ["POST"],
        ),
        (
            "/export/anki",
            "export_anki_genanki",
            export_anki_genanki,
            ["POST"],
        ),
        (
            "/export/anki/missed",
            "export_anki_missed_tsv",
            export_anki_missed_tsv,
            ["POST"],
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
