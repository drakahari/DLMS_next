"""Smart PDF import, review, source-bank, and generation routes."""

import json
import os
import random
import re
import secrets
from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, flash, redirect, render_template, request


Dependency = Callable[..., Any]
PDF_QUESTION_MIN_CHOICES = 2
PDF_QUESTION_MAX_CHOICES = 26
PDF_CHOICE_LABELS = tuple(chr(ord("A") + index) for index in range(26))


@dataclass(frozen=True)
class PDFImportRouteDependencies:
    """Configured application services required by the Smart PDF workflow."""

    pdf_import_max_bytes: Dependency
    upload_multipart_overhead_bytes: Dependency
    save_pdf_import_upload: Dependency
    remove_pdf_import_upload: Dependency
    save_pdf_import_draft: Dependency
    load_pdf_import_draft: Dependency
    delete_pdf_import_draft: Dependency
    list_pdf_question_banks: Dependency
    save_pdf_question_bank: Dependency
    load_pdf_question_bank: Dependency
    delete_pdf_question_bank: Dependency
    list_pdf_terminology_banks: Dependency
    save_pdf_terminology_bank: Dependency
    load_pdf_terminology_bank: Dependency
    delete_pdf_terminology_bank: Dependency
    extract_pdf_pages: Dependency
    suppress_repeated_pdf_margins: Dependency
    parse_pdf_question_bank: Dependency
    parse_pdf_glossary: Dependency
    detect_pdf_document_type: Dependency
    recover_pdf_questions: Dependency
    recover_pdf_glossary: Dependency
    add_pdf_question_review_slots: Dependency
    secure_filename: Dependency
    normalize_exam_minutes: Dependency
    timestamp_now: Dependency
    publish_quiz: Dependency
    create_quiz_from_runtime: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def _pdf_bank_active_questions(bank):
    active = [
        question
        for question in (bank.get("questions") or [])
        if isinstance(question, dict) and question.get("active", True)
    ]
    return sorted(
        active,
        key=lambda question: (
            int(question.get("original_number") or question.get("number") or 0),
            int(question.get("number") or 0),
        ),
    )


def _pdf_question_correct_answers(question):
    """Return canonical answer labels from list-capable or legacy scalar data."""

    raw_answers = question.get("correct_answers")
    if not isinstance(raw_answers, list):
        raw_answers = [question.get("correct")]
    answers = []
    for raw_answer in raw_answers:
        answer = str(raw_answer or "").strip().upper()
        if answer in PDF_CHOICE_LABELS and answer not in answers:
            answers.append(answer)
    return answers


def _normalize_pdf_question_for_review(question):
    """Build the bounded, editable Smart PDF review representation."""

    normalized = deepcopy(question) if isinstance(question, dict) else {}
    raw_choices = normalized.get("choices") or []
    if not isinstance(raw_choices, list):
        raw_choices = []
    if len(raw_choices) > PDF_QUESTION_MAX_CHOICES:
        raise ValueError(
            f"Question {normalized.get('number') or ''} has more than "
            f"{PDF_QUESTION_MAX_CHOICES} choices."
        )

    original_answers = set(_pdf_question_correct_answers(normalized))
    original_feedback = (
        normalized.get("choice_feedback")
        if isinstance(normalized.get("choice_feedback"), dict)
        else {}
    )
    choices = []
    answers = []
    feedback = {}
    for index, raw_choice in enumerate(raw_choices):
        if not isinstance(raw_choice, dict):
            raw_choice = {}
        old_label = str(raw_choice.get("label") or "").strip().upper()
        label = PDF_CHOICE_LABELS[index]
        choices.append({"label": label, "text": str(raw_choice.get("text") or "")})
        if old_label in original_answers:
            answers.append(label)
        note = str(original_feedback.get(old_label) or "")
        if note:
            feedback[label] = note

    while len(choices) < PDF_QUESTION_MIN_CHOICES:
        label = PDF_CHOICE_LABELS[len(choices)]
        choices.append({"label": label, "text": ""})

    explicit_mode = str(normalized.get("answer_mode") or "").strip().lower()
    answer_mode = (
        explicit_mode
        if explicit_mode in {"single", "multiple"}
        else ("multiple" if len(answers) > 1 else "single")
    )
    confirmation_required = bool(
        normalized.get("correctness_confirmation_required", False)
    )
    normalized.update(
        {
            "choices": choices,
            "correct_answers": answers,
            "answer_mode": answer_mode,
            "choice_feedback": feedback,
            "correctness_confirmation_required": confirmation_required,
            "correctness_confirmed": bool(
                normalized.get("correctness_confirmed", not confirmation_required)
            ),
        }
    )
    return normalized


def _normalize_pdf_draft_for_review(draft):
    normalized = deepcopy(draft)
    questions = normalized.get("questions") or []
    if not isinstance(questions, list):
        raise ValueError("The PDF question review data is malformed.")
    normalized["questions"] = [
        _normalize_pdf_question_for_review(question) for question in questions
    ]
    return normalized


def _pdf_submitted_question_at_index(submitted_items, index):
    for item in submitted_items or []:
        if not isinstance(item, dict):
            continue
        try:
            submitted_index = int(item.get("index", -1))
        except (TypeError, ValueError):
            continue
        if submitted_index == index:
            return item
    return None


def _select_pdf_bank_questions(
    bank, mode="random", count=50, start_number=1, end_number=None
):
    active = _pdf_bank_active_questions(bank)
    if not active:
        raise ValueError("This question bank has no active questions.")

    mode = str(mode or "random").strip().lower()
    try:
        count = max(1, int(count))
    except Exception:
        count = 50
    count = min(count, len(active))

    if mode == "all":
        return active

    if mode == "range":
        try:
            start_number = int(start_number)
            end_number = int(end_number)
        except Exception:
            raise ValueError("Question range requires valid start and end numbers.")
        if end_number < start_number:
            raise ValueError("Range end must be greater than or equal to range start.")
        selected = [
            question
            for question in active
            if start_number
            <= int(question.get("original_number") or question.get("number") or 0)
            <= end_number
        ]
        if not selected:
            raise ValueError("No active questions fall within that range.")
        return selected

    if mode == "sequential":
        try:
            start_number = int(start_number)
        except Exception:
            start_number = 1
        candidates = [
            question
            for question in active
            if int(question.get("original_number") or question.get("number") or 0)
            >= start_number
        ]
        if not candidates:
            raise ValueError(
                "No active questions exist at or after that starting question number."
            )
        return candidates[:count]

    if mode == "unused":
        used = {
            int(number)
            for number in (bank.get("used_question_numbers") or [])
            if str(number).isdigit()
        }
        candidates = [
            question
            for question in active
            if int(question.get("original_number") or question.get("number") or 0)
            not in used
        ]
        if not candidates:
            raise ValueError(
                "All active questions in this bank have already been used."
            )
        return random.sample(candidates, min(count, len(candidates)))

    return random.sample(active, count)


def _pdf_bank_question_to_quiz(question, number, bank):
    choices = []
    correct_answers = _pdf_question_correct_answers(question)
    correct_set = set(correct_answers)
    for raw in question.get("choices") or []:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip().upper()
        text = str(raw.get("text") or "").strip()
        if label and text:
            choices.append(
                {"label": label, "text": text, "is_correct": label in correct_set}
            )
    labels = {choice["label"] for choice in choices}
    if (
        not PDF_QUESTION_MIN_CHOICES <= len(choices) <= PDF_QUESTION_MAX_CHOICES
        or not correct_answers
        or not correct_set.issubset(labels)
    ):
        raise ValueError(
            f"Bank question {question.get('original_number') or question.get('number')} is incomplete."
        )
    return {
        "number": number,
        "type": "choice",
        "question": str(question.get("question") or "").strip(),
        "choices": choices,
        "correct": correct_answers,
        "explanation": str(question.get("explanation") or "").strip(),
        "source": {
            "organization": "User-provided document",
            "dataset": bank.get("source_name")
            or bank.get("title")
            or "PDF question bank",
            "version": "",
            "url": "",
            "license": "User-provided; redistribution not cleared",
        },
    }


def _pdf_term_bank_active_terms(bank):
    active = [
        term
        for term in (bank.get("terms") or [])
        if isinstance(term, dict) and term.get("active", True)
    ]
    return sorted(active, key=lambda term: int(term.get("number") or 0))


def _select_pdf_term_bank_items(
    bank, mode="random", count=25, start_number=1, end_number=None
):
    active = _pdf_term_bank_active_terms(bank)
    if not active:
        raise ValueError("This terminology bank has no active terms.")

    mode = str(mode or "random").strip().lower()
    try:
        count = max(1, int(count))
    except Exception:
        count = 25
    count = min(count, len(active))

    if mode == "all":
        return active

    if mode == "range":
        try:
            start_number = int(start_number)
            end_number = int(end_number)
        except Exception:
            raise ValueError("Term range requires valid start and end numbers.")
        if end_number < start_number:
            raise ValueError("Range end must be greater than or equal to range start.")
        selected = [
            term
            for term in active
            if start_number <= int(term.get("number") or 0) <= end_number
        ]
        if not selected:
            raise ValueError("No active terms fall within that range.")
        return selected

    if mode == "sequential":
        try:
            start_number = int(start_number)
        except Exception:
            start_number = 1
        candidates = [
            term
            for term in active
            if int(term.get("number") or 0) >= start_number
        ]
        if not candidates:
            raise ValueError("No active terms exist at or after that starting number.")
        return candidates[:count]

    if mode == "unused":
        used = {
            int(number)
            for number in (bank.get("used_term_numbers") or [])
            if str(number).isdigit()
        }
        candidates = [
            term
            for term in active
            if int(term.get("number") or 0) not in used
        ]
        if not candidates:
            raise ValueError("All active terms in this bank have already been used.")
        return random.sample(candidates, min(count, len(candidates)))

    return random.sample(active, count)


def _pdf_term_source(bank):
    return {
        "organization": "User-provided document",
        "dataset": bank.get("source_name")
        or bank.get("title")
        or "PDF terminology bank",
        "version": "",
        "url": "",
        "license": "User-provided; redistribution not cleared",
    }


def _pdf_terms_matching_questions(bank, selected, direction="random"):
    pairs = [
        {
            "left": str(term.get("term") or "").strip(),
            "right": str(term.get("definition") or "").strip(),
        }
        for term in selected
        if str(term.get("term") or "").strip()
        and str(term.get("definition") or "").strip()
    ]
    if len(pairs) < 2:
        raise ValueError("Matching practice requires at least two complete terms.")
    question = {
        "number": 1,
        "type": "matching",
        "question": "Match each term with its correct definition.",
        "pairs": pairs,
        "round_size": len(pairs),
        "direction": direction
        if direction in {"random", "term_to_definition", "definition_to_term"}
        else "random",
        "explanation": "Definitions are taken from the reviewed user-provided terminology bank.",
        "source": _pdf_term_source(bank),
    }
    return [question], [dict(question)]


def _pdf_terms_mc_questions(bank, selected, direction="definition_to_term"):
    pool = _pdf_term_bank_active_terms(bank)
    if len(pool) < 4:
        raise ValueError(
            "Multiple-choice terminology practice requires at least four active terms."
        )

    runtime, db_questions = [], []
    for number, target in enumerate(selected, 1):
        target_term = str(target.get("term") or "").strip()
        target_def = str(target.get("definition") or "").strip()
        if not target_term or not target_def:
            continue

        distractor_pool = [
            term
            for term in pool
            if int(term.get("number") or 0) != int(target.get("number") or 0)
        ]
        distractors = random.sample(distractor_pool, 3)
        option_terms = [target] + distractors
        random.shuffle(option_terms)

        choices = []
        correct = []
        for option in option_terms:
            label = chr(65 + len(choices))
            is_correct = int(option.get("number") or 0) == int(
                target.get("number") or 0
            )
            if direction == "term_to_definition":
                text = str(option.get("definition") or "").strip()
            else:
                text = str(option.get("term") or "").strip()
            choices.append(
                {"label": label, "text": text, "is_correct": is_correct}
            )
            if is_correct:
                correct.append(label)

        if direction == "term_to_definition":
            question_text = (
                f"Which definition best matches the term: {target_term}?"
            )
        else:
            question_text = f"Which term best matches this definition? {target_def}"

        question = {
            "number": number,
            "type": "choice",
            "question": question_text,
            "choices": choices,
            "correct": correct,
            "explanation": f"{target_term}: {target_def}",
            "source": _pdf_term_source(bank),
        }
        runtime.append(question)
        db_questions.append(dict(question))

    if not runtime:
        raise ValueError("No usable multiple-choice questions were generated.")
    return runtime, db_questions


def pdf_import_page(dependencies):
    return render_template(
        "pdf_import/index.html",
        banks=dependencies.list_pdf_question_banks(),
        term_banks=dependencies.list_pdf_terminology_banks(),
    )


def pdf_question_bank_delete(dependencies, bank_id):
    try:
        title = dependencies.delete_pdf_question_bank(bank_id)
        flash(
            f"Deleted source question bank '{title}'. Existing generated quizzes were not deleted.",
            "success",
        )
    except FileNotFoundError:
        flash(
            "PDF question bank was already removed or could not be found.", "error"
        )
    except Exception as exc:
        print(f"[PDF QUESTION BANK DELETE ERROR] {type(exc).__name__}: {exc}")
        flash("Could not delete the PDF question bank.", "error")
    return redirect("/pdf-import")


def pdf_terminology_bank_delete(dependencies, bank_id):
    try:
        title = dependencies.delete_pdf_terminology_bank(bank_id)
        flash(
            f"Deleted source terminology bank '{title}'. Existing generated quizzes were not deleted.",
            "success",
        )
    except FileNotFoundError:
        flash(
            "PDF terminology bank was already removed or could not be found.", "error"
        )
    except Exception as exc:
        print(f"[PDF TERMINOLOGY BANK DELETE ERROR] {type(exc).__name__}: {exc}")
        flash("Could not delete the PDF terminology bank.", "error")
    return redirect("/pdf-import")


def pdf_import_analyze(dependencies):
    pdf_import_max_bytes = dependencies.pdf_import_max_bytes()
    multipart_overhead_bytes = dependencies.upload_multipart_overhead_bytes()
    upload = request.files.get("pdf_file")
    if not upload or not upload.filename:
        flash("Choose a PDF to analyze.", "error")
        return redirect("/pdf-import")
    if not str(upload.filename).lower().endswith(".pdf"):
        flash("Smart PDF Import currently accepts PDF files only.", "error")
        return redirect("/pdf-import")
    if not request.form.get("rights_ok"):
        flash(
            "Confirm that you have permission to use the document for your own study.",
            "error",
        )
        return redirect("/pdf-import")
    if (
        request.content_length
        and request.content_length > pdf_import_max_bytes + multipart_overhead_bytes
    ):
        flash("PDF exceeds the 64 MB Smart PDF Import limit.", "error")
        return redirect("/pdf-import")

    draft_id = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:20]
    source_name = dependencies.secure_filename(upload.filename) or "study.pdf"
    temp_pdf = None
    try:
        temp_pdf = dependencies.save_pdf_import_upload(upload, draft_id)
        pages = dependencies.extract_pdf_pages(temp_pdf)
        pages, removed_margins = dependencies.suppress_repeated_pdf_margins(pages)

        requested_type = (
            request.form.get("pdf_content_type") or "auto"
        ).strip().lower()
        question_result = dependencies.parse_pdf_question_bank(pages)
        glossary_result = dependencies.parse_pdf_glossary(pages)

        if requested_type == "question_bank":
            document_type = "question_bank"
            detection = {"forced": True}
        elif requested_type == "glossary":
            document_type = "glossary"
            detection = {"forced": True}
        else:
            document_type, detection = dependencies.detect_pdf_document_type(
                pages,
                question_result=question_result,
                glossary_result=glossary_result,
            )

        if document_type == "question_bank":
            result = question_result
            if not result.get("questions"):
                result = dependencies.recover_pdf_questions(pages)
                detection = {
                    **(detection or {}),
                    "recovery_mode": True,
                    "reason": "no_structured_question_records",
                }
        elif document_type == "glossary":
            result = glossary_result
            if not result.get("terms"):
                result = dependencies.recover_pdf_glossary(pages)
                detection = {
                    **(detection or {}),
                    "recovery_mode": True,
                    "reason": "no_structured_glossary_records",
                }
        else:
            answer_markers = sum(
                1
                for page in pages
                for line in page.get("lines", [])
                if re.search(r"Correct\s+Answer:", line, re.I)
            )
            choice_lines = sum(
                1
                for page in pages
                for line in page.get("lines", [])
                if re.match(r"^[A-Z]\.\s+", line)
            )
            if answer_markers or choice_lines >= 2:
                document_type = "question_bank"
                result = dependencies.recover_pdf_questions(pages)
                detection = {
                    **(detection or {}),
                    "recovery_mode": True,
                    "reason": "auto_low_confidence_question_like",
                }
            elif glossary_result.get("terms"):
                document_type = "glossary"
                result = glossary_result
            else:
                document_type = "question_bank"
                result = dependencies.recover_pdf_questions(pages)
                detection = {
                    **(detection or {}),
                    "recovery_mode": True,
                    "reason": "auto_unstructured_recovery",
                }

        if document_type == "question_bank":
            result["questions"] = [
                dependencies.add_pdf_question_review_slots(question)
                for question in (result.get("questions") or [])
            ]
            if not result.get("questions"):
                raise ValueError(
                    "No selectable text could be recovered from this PDF. OCR is not enabled."
                )
        elif document_type == "glossary" and not result.get("terms"):
            raise ValueError(
                "No selectable text could be recovered from this PDF. OCR is not enabled."
            )

        draft = {
            "id": draft_id,
            "created_at": dependencies.timestamp_now(),
            "source_name": source_name,
            "source_kind": "user-provided-pdf",
            "redistribution_status": "not-cleared-for-redistribution",
            "document_type": document_type,
            "detection": detection,
            "quiz_title": (request.form.get("quiz_title") or "").strip()
            or os.path.splitext(source_name)[0],
            "exam_minutes": dependencies.normalize_exam_minutes(
                request.form.get("exam_minutes")
            ),
            "page_count": len(pages),
            "removed_margin_text": removed_margins,
            **result,
        }
        dependencies.save_pdf_import_draft(draft)
    except Exception as exc:
        print(f"[PDF ANALYSIS ERROR] {type(exc).__name__}: {exc}")
        flash(
            "PDF analysis failed. The document may be malformed, encrypted, or outside the supported limits.",
            "error",
        )
        return redirect("/pdf-import")
    finally:
        dependencies.remove_pdf_import_upload(temp_pdf)
    return redirect(f"/pdf-import/review/{draft_id}")


def _render_pdf_glossary_review(draft):
    return render_template("pdf_import/review-glossary.html", draft=draft)


def pdf_import_review(dependencies, draft_id):
    try:
        draft = dependencies.load_pdf_import_draft(draft_id)
    except Exception as exc:
        print(f"[PDF REVIEW LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("The PDF review session is unavailable or expired.", "error")
        return redirect("/pdf-import")

    if draft.get("document_type") == "glossary":
        return _render_pdf_glossary_review(draft)
    try:
        review_draft = _normalize_pdf_draft_for_review(draft)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect("/pdf-import")
    return render_template("pdf_import/review-question-bank.html", draft=review_draft)


def _save_pdf_glossary_draft(dependencies, draft, draft_id):
    bank_title = (request.form.get("quiz_title") or "").strip()
    if not bank_title:
        flash("Terminology bank title is required.", "error")
        return redirect(f"/pdf-import/review/{draft_id}")

    raw_payload = (request.form.get("term_review_payload") or "").strip()
    try:
        submitted_items = json.loads(raw_payload) if raw_payload else []
    except Exception:
        submitted_items = []
    if not isinstance(submitted_items, list):
        submitted_items = []

    bank_terms = []
    originals = draft.get("terms") or []
    for index, original in enumerate(originals):
        submitted = next(
            (
                item
                for item in submitted_items
                if isinstance(item, dict) and int(item.get("index", -1)) == index
            ),
            None,
        )
        excluded = bool((submitted or {}).get("exclude"))
        term = str(
            (submitted or {}).get("term")
            if submitted is not None
            else original.get("term") or ""
        ).strip()
        definition = str(
            (submitted or {}).get("definition")
            if submitted is not None
            else original.get("definition") or ""
        ).strip()
        valid = bool(term and definition)
        if not excluded and not valid:
            flash(
                f"Term {original.get('number')} needs both a term and definition. Repair it or exclude it.",
                "error",
            )
            return redirect(f"/pdf-import/review/{draft_id}")
        bank_terms.append(
            {
                "number": index + 1,
                "term": term,
                "definition": definition,
                "pages": original.get("pages") or [],
                "parser_status": original.get("status")
                or ("complete" if valid else "incomplete"),
                "parser_issues": original.get("issues") or [],
                "active": not excluded and valid,
            }
        )

    if not bank_terms:
        flash("No terminology records were available to save.", "error")
        return redirect(f"/pdf-import/review/{draft_id}")

    bank_id = (
        "pdfterms_"
        + secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:14]
    )
    bank = {
        "schema_version": 1,
        "id": bank_id,
        "kind": "terminology",
        "title": bank_title,
        "source_name": draft.get("source_name") or "PDF import",
        "source_kind": "user-provided-pdf",
        "redistribution_status": "not-cleared-for-redistribution",
        "created_at": dependencies.timestamp_now(),
        "default_exam_minutes": dependencies.normalize_exam_minutes(
            request.form.get("exam_minutes")
        ),
        "page_count": draft.get("page_count") or 0,
        "terms": bank_terms,
        "used_term_numbers": [],
        "generated_quizzes": [],
    }
    dependencies.save_pdf_terminology_bank(bank)
    dependencies.delete_pdf_import_draft(draft_id)

    active_count = len(_pdf_term_bank_active_terms(bank))
    excluded_count = len(bank_terms) - active_count
    flash(
        f"Saved terminology bank '{bank_title}' with {active_count} active term(s)"
        + (
            f" and {excluded_count} excluded source record(s)."
            if excluded_count
            else "."
        ),
        "success",
    )
    return redirect(f"/pdf-import/terms/{bank_id}")


def _save_pdf_question_draft(dependencies, draft, draft_id):
    bank_title = (request.form.get("quiz_title") or "").strip()
    exam_minutes = dependencies.normalize_exam_minutes(
        request.form.get("exam_minutes")
    )
    if not bank_title:
        flash("Question bank title is required.", "error")
        return redirect(f"/pdf-import/review/{draft_id}")

    submitted_items = None
    raw_payload = (request.form.get("review_payload") or "").strip()
    if raw_payload:
        try:
            parsed_payload = json.loads(raw_payload)
            if isinstance(parsed_payload, list):
                submitted_items = parsed_payload
        except Exception:
            submitted_items = None

    originals = draft.get("questions") or []
    bank_questions = []
    for index, original in enumerate(originals):
        submitted = None
        if submitted_items is not None:
            submitted = _pdf_submitted_question_at_index(submitted_items, index)

        if submitted is not None:
            excluded = bool(submitted.get("delete"))
            question = str(submitted.get("question") or "").strip()
            raw_choices = submitted.get("choices") or []
            if not isinstance(raw_choices, list):
                raw_choices = []
            if len(raw_choices) > PDF_QUESTION_MAX_CHOICES:
                flash(
                    f"Question {original.get('number')} has more than "
                    f"{PDF_QUESTION_MAX_CHOICES} answer choices. Delete choices before saving.",
                    "error",
                )
                return redirect(f"/pdf-import/review/{draft_id}")
            choices = []
            original_labels = []
            for raw_choice in raw_choices:
                if not isinstance(raw_choice, dict):
                    continue
                original_label = str(raw_choice.get("label") or "").strip().upper()
                text = str(raw_choice.get("text") or "").strip()
                if text:
                    label = PDF_CHOICE_LABELS[len(choices)]
                    choices.append({"label": label, "text": text})
                    original_labels.append(original_label)
            submitted_answers = submitted.get("correct_answers")
            if not isinstance(submitted_answers, list):
                submitted_answers = [submitted.get("correct")]
            submitted_answers = {
                str(answer or "").strip().upper() for answer in submitted_answers
            }
            correct_answers = [
                choice["label"]
                for choice, original_label in zip(choices, original_labels)
                if original_label in submitted_answers
            ]
            answer_mode = str(submitted.get("answer_mode") or "").strip().lower()
            if answer_mode not in {"single", "multiple"}:
                answer_mode = "multiple" if len(correct_answers) > 1 else "single"
            explanation = str(submitted.get("explanation") or "").strip()
            submitted_feedback = (
                submitted.get("feedback")
                if isinstance(submitted.get("feedback"), dict)
                else {}
            )
            feedback = {
                choice["label"]: str(submitted_feedback.get(original_label) or "")
                for choice, original_label in zip(choices, original_labels)
                if str(submitted_feedback.get(original_label) or "").strip()
            }
            confirmation_required = bool(
                original.get("correctness_confirmation_required", False)
            )
            correctness_confirmed = bool(
                submitted.get("correctness_confirmed", not confirmation_required)
            )
        else:
            normalized_original = _normalize_pdf_question_for_review(original)
            excluded = bool(request.form.get(f"delete_{index}"))
            question = (
                request.form.get(f"question_{index}")
                or original.get("question")
                or ""
            ).strip()
            choices = []
            for choice in normalized_original.get("choices") or []:
                label = str(choice.get("label") or "").strip().upper()
                text = (
                    request.form.get(f"choice_{index}_{label}")
                    or choice.get("text")
                    or ""
                ).strip()
                if label and text:
                    choices.append({"label": label, "text": text})
            requested_correct = request.form.get(f"correct_{index}")
            correct_answers = (
                [str(requested_correct).strip().upper()]
                if requested_correct is not None
                else normalized_original.get("correct_answers") or []
            )
            answer_mode = normalized_original.get("answer_mode") or "single"
            explanation = (
                request.form.get(f"explanation_{index}")
                or original.get("explanation")
                or ""
            ).strip()
            feedback = (
                normalized_original.get("choice_feedback")
                if isinstance(normalized_original.get("choice_feedback"), dict)
                else {}
            )
            confirmation_required = bool(
                normalized_original.get("correctness_confirmation_required", False)
            )
            correctness_confirmed = bool(
                normalized_original.get("correctness_confirmed", not confirmation_required)
            )

        labels = {choice["label"] for choice in choices}
        correct_answers = [
            answer
            for answer in correct_answers
            if answer in PDF_CHOICE_LABELS and answer in labels
        ]
        correct_answers = list(dict.fromkeys(correct_answers))
        valid = bool(
            question
            and PDF_QUESTION_MIN_CHOICES <= len(choices) <= PDF_QUESTION_MAX_CHOICES
            and correct_answers
            and (answer_mode != "single" or len(correct_answers) == 1)
            and (answer_mode != "multiple" or len(correct_answers) >= 2)
            and (not confirmation_required or correctness_confirmed)
        )
        if not excluded and not valid:
            missing = []
            if not question:
                missing.append("question text")
            if len(choices) < PDF_QUESTION_MIN_CHOICES:
                missing.append(
                    f"answer choices ({len(choices)} detected/submitted)"
                )
            if len(choices) > PDF_QUESTION_MAX_CHOICES:
                missing.append(f"no more than {PDF_QUESTION_MAX_CHOICES} answer choices")
            if not correct_answers:
                missing.append("at least one correct answer")
            elif answer_mode == "single" and len(correct_answers) != 1:
                missing.append("exactly one correct answer in single-answer mode")
            elif answer_mode == "multiple" and len(correct_answers) < 2:
                missing.append("at least two correct answers in multiple-answer mode")
            if confirmation_required and not correctness_confirmed:
                missing.append("explicit confirmation of the complete correct-answer set")
            flash(
                f"Question {original.get('number')} cannot be active in the bank: "
                f"{', '.join(missing)}. Repair it or mark it for deletion/exclusion.",
                "error",
            )
            return redirect(f"/pdf-import/review/{draft_id}")

        feedback_parts = []
        for choice in choices:
            note = str((feedback or {}).get(choice["label"]) or "").strip()
            if note:
                feedback_parts.append(f"{choice['label']}: {note}")
        stored_explanation = explanation
        if feedback_parts:
            stored_explanation = (
                f"{stored_explanation}\n\nOther option notes: "
                + " | ".join(feedback_parts)
            ).strip()

        bank_questions.append(
            {
                "number": index + 1,
                "original_number": int(original.get("number") or index + 1),
                "question": question,
                "choices": choices,
                "correct_answers": correct_answers,
                "answer_mode": answer_mode,
                "correctness_confirmed": correctness_confirmed,
                "explanation": stored_explanation,
                "choice_feedback": feedback or {},
                "pages": original.get("pages") or [],
                "parser_status": original.get("status")
                or ("complete" if valid else "incomplete"),
                "parser_issues": original.get("issues") or [],
                "active": not excluded and valid,
            }
        )

    if not bank_questions:
        flash("No parsed questions were available to save.", "error")
        return redirect(f"/pdf-import/review/{draft_id}")

    bank_id = (
        "pdfbank_"
        + secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:14]
    )
    bank = {
        "schema_version": 2,
        "id": bank_id,
        "title": bank_title,
        "source_name": draft.get("source_name") or "PDF import",
        "source_kind": "user-provided-pdf",
        "redistribution_status": "not-cleared-for-redistribution",
        "created_at": dependencies.timestamp_now(),
        "default_exam_minutes": exam_minutes,
        "page_count": draft.get("page_count") or 0,
        "questions": bank_questions,
        "used_question_numbers": [],
        "generated_quizzes": [],
    }
    dependencies.save_pdf_question_bank(bank)
    dependencies.delete_pdf_import_draft(draft_id)

    active_count = len(_pdf_bank_active_questions(bank))
    excluded_count = len(bank_questions) - active_count
    flash(
        f"Saved question bank '{bank_title}' with {active_count} active question(s)"
        + (
            f" and {excluded_count} excluded source question(s)."
            if excluded_count
            else "."
        ),
        "success",
    )
    return redirect(f"/pdf-import/bank/{bank_id}")


def pdf_import_save(dependencies, draft_id):
    try:
        draft = dependencies.load_pdf_import_draft(draft_id)
    except Exception as exc:
        print(f"[PDF REVIEW SAVE ERROR] {type(exc).__name__}: {exc}")
        flash("The PDF review session is unavailable or expired.", "error")
        return redirect("/pdf-import")

    if draft.get("document_type") == "glossary":
        return _save_pdf_glossary_draft(dependencies, draft, draft_id)
    return _save_pdf_question_draft(dependencies, draft, draft_id)


def pdf_question_banks_page(_dependencies):
    return redirect("/pdf-import")


def pdf_question_bank_page(dependencies, bank_id):
    try:
        bank = dependencies.load_pdf_question_bank(bank_id)
    except Exception as exc:
        print(f"[PDF QUESTION BANK LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("The selected PDF question bank could not be loaded.", "error")
        return redirect("/pdf-import")

    questions = bank.get("questions") or []
    active = _pdf_bank_active_questions(bank)
    excluded = [
        question
        for question in questions
        if isinstance(question, dict) and not question.get("active", True)
    ]
    used = {
        int(number)
        for number in (bank.get("used_question_numbers") or [])
        if str(number).isdigit()
    }
    max_number = max(
        [
            int(question.get("original_number") or question.get("number") or 0)
            for question in questions
            if isinstance(question, dict)
        ]
        or [1]
    )
    default_count = min(50, len(active)) if active else 1
    return render_template(
        "pdf_import/question-bank.html",
        bank=bank,
        questions=questions,
        active=active,
        excluded=excluded,
        used=used,
        default_count=default_count,
        max_number=max_number,
    )


def pdf_question_bank_generate(dependencies, bank_id):
    try:
        bank = dependencies.load_pdf_question_bank(bank_id)
        quiz_title = (request.form.get("quiz_title") or "").strip()
        if not quiz_title:
            raise ValueError("Quiz title is required.")
        exam_minutes = dependencies.normalize_exam_minutes(
            request.form.get("exam_minutes")
        )
        mode = (request.form.get("selection_mode") or "random").strip().lower()
        selected = _select_pdf_bank_questions(
            bank,
            mode=mode,
            count=request.form.get("question_count") or 50,
            start_number=request.form.get("start_number") or 1,
            end_number=request.form.get("end_number"),
        )
        quiz_data = [
            _pdf_bank_question_to_quiz(question, number, bank)
            for number, question in enumerate(selected, 1)
        ]
        quiz_id, _ = dependencies.publish_quiz(
            quiz_title,
            quiz_data,
            filename_prefix="pdf_bank",
            exam_minutes=exam_minutes,
        )

        try:
            selected_numbers = [
                int(question.get("original_number") or question.get("number") or 0)
                for question in selected
            ]
            used = {
                int(number)
                for number in (bank.get("used_question_numbers") or [])
                if str(number).isdigit()
            }
            used.update(number for number in selected_numbers if number)
            bank["used_question_numbers"] = sorted(used)
            bank.setdefault("generated_quizzes", []).append(
                {
                    "quiz_id": quiz_id,
                    "title": quiz_title,
                    "created_at": dependencies.timestamp_now(),
                    "selection_mode": mode,
                    "question_count": len(selected),
                    "question_numbers": selected_numbers,
                }
            )
            dependencies.save_pdf_question_bank(bank)
        except Exception as exc:
            print(
                f"[PDF QUIZ ACCOUNTING ERROR] Published quiz {quiz_id}: {type(exc).__name__}: {exc}"
            )
            flash(
                "Quiz created, but source-bank usage tracking could not be updated.",
                "warning",
            )

        flash(
            f"Created '{quiz_title}' with {len(selected)} question(s) from '{bank.get('title')}'. "
            f"The source bank remains intact.",
            "success",
        )
        return redirect(f"/edit_quiz/{quiz_id}")
    except Exception as exc:
        print(f"[PDF QUIZ GENERATION ERROR] {type(exc).__name__}: {exc}")
        flash(
            "Could not generate a quiz from the selected PDF question bank.",
            "error",
        )
        return redirect(f"/pdf-import/bank/{bank_id}")


def pdf_terminology_banks_page(_dependencies):
    return redirect("/pdf-import")


def pdf_terminology_bank_page(dependencies, bank_id):
    try:
        bank = dependencies.load_pdf_terminology_bank(bank_id)
    except Exception as exc:
        print(f"[PDF TERMINOLOGY BANK LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("The selected PDF terminology bank could not be loaded.", "error")
        return redirect("/pdf-import")

    terms = bank.get("terms") or []
    active = _pdf_term_bank_active_terms(bank)
    excluded = [
        term
        for term in terms
        if isinstance(term, dict) and not term.get("active", True)
    ]
    used = {
        int(number)
        for number in (bank.get("used_term_numbers") or [])
        if str(number).isdigit()
    }
    max_number = max(
        [int(term.get("number") or 0) for term in terms if isinstance(term, dict)]
        or [1]
    )
    default_count = min(25, len(active)) if active else 1
    return render_template(
        "pdf_import/terminology-bank.html",
        bank=bank,
        terms=terms,
        active=active,
        excluded=excluded,
        used=used,
        max_number=max_number,
        default_count=default_count,
    )


def pdf_terminology_bank_generate(dependencies, bank_id):
    try:
        bank = dependencies.load_pdf_terminology_bank(bank_id)
        quiz_title = (request.form.get("quiz_title") or "").strip()
        if not quiz_title:
            raise ValueError("Quiz title is required.")
        exam_minutes = dependencies.normalize_exam_minutes(
            request.form.get("exam_minutes")
        )
        mode = (request.form.get("selection_mode") or "random").strip().lower()
        practice_type = (
            request.form.get("practice_type") or "matching"
        ).strip().lower()
        direction = (request.form.get("direction") or "random").strip().lower()

        selected = _select_pdf_term_bank_items(
            bank,
            mode=mode,
            count=request.form.get("term_count") or 25,
            start_number=request.form.get("start_number") or 1,
            end_number=request.form.get("end_number"),
        )
        if practice_type == "multiple_choice":
            mc_direction = (
                direction
                if direction in {"term_to_definition", "definition_to_term"}
                else "definition_to_term"
            )
            runtime, db_questions = _pdf_terms_mc_questions(
                bank, selected, mc_direction
            )
        else:
            runtime, db_questions = _pdf_terms_matching_questions(
                bank, selected, direction
            )

        quiz_id, _ = dependencies.create_quiz_from_runtime(
            quiz_title,
            runtime,
            db_questions,
            filename_prefix="pdf_terms",
            exam_minutes=exam_minutes,
        )

        try:
            selected_numbers = [int(term.get("number") or 0) for term in selected]
            used = {
                int(number)
                for number in (bank.get("used_term_numbers") or [])
                if str(number).isdigit()
            }
            used.update(number for number in selected_numbers if number)
            bank["used_term_numbers"] = sorted(used)
            bank.setdefault("generated_quizzes", []).append(
                {
                    "quiz_id": quiz_id,
                    "title": quiz_title,
                    "created_at": dependencies.timestamp_now(),
                    "practice_type": practice_type,
                    "selection_mode": mode,
                    "direction": direction,
                    "term_count": len(selected),
                    "term_numbers": selected_numbers,
                }
            )
            dependencies.save_pdf_terminology_bank(bank)
        except Exception as exc:
            print(
                f"[PDF TERMINOLOGY ACCOUNTING ERROR] Published quiz {quiz_id}: {type(exc).__name__}: {exc}"
            )
            flash(
                "Practice quiz created, but source-bank usage tracking could not be updated.",
                "warning",
            )

        flash(
            f"Created '{quiz_title}' from {len(selected)} terminology item(s). The source bank remains intact.",
            "success",
        )
        return redirect(f"/edit_quiz/{quiz_id}")
    except Exception as exc:
        print(f"[PDF TERMINOLOGY GENERATION ERROR] {type(exc).__name__}: {exc}")
        flash(
            "Could not generate practice from the selected terminology bank.", "error"
        )
        return redirect(f"/pdf-import/terms/{bank_id}")


def create_pdf_import_blueprint(
    dependencies: PDFImportRouteDependencies,
) -> Blueprint:
    """Create the complete Smart PDF workflow Blueprint."""
    blueprint = Blueprint("pdf_import", __name__)
    routes = (
        ("/pdf-import", "pdf_import_page", pdf_import_page, ["GET"]),
        (
            "/pdf-import/bank/<bank_id>/delete",
            "pdf_question_bank_delete",
            pdf_question_bank_delete,
            ["POST"],
        ),
        (
            "/pdf-import/terms/<bank_id>/delete",
            "pdf_terminology_bank_delete",
            pdf_terminology_bank_delete,
            ["POST"],
        ),
        (
            "/pdf-import/analyze",
            "pdf_import_analyze",
            pdf_import_analyze,
            ["POST"],
        ),
        (
            "/pdf-import/review/<draft_id>",
            "pdf_import_review",
            pdf_import_review,
            ["GET"],
        ),
        (
            "/pdf-import/save/<draft_id>",
            "pdf_import_save",
            pdf_import_save,
            ["POST"],
        ),
        (
            "/pdf-import/banks",
            "pdf_question_banks_page",
            pdf_question_banks_page,
            ["GET"],
        ),
        (
            "/pdf-import/bank/<bank_id>",
            "pdf_question_bank_page",
            pdf_question_bank_page,
            ["GET"],
        ),
        (
            "/pdf-import/bank/<bank_id>/generate",
            "pdf_question_bank_generate",
            pdf_question_bank_generate,
            ["POST"],
        ),
        (
            "/pdf-import/terms",
            "pdf_terminology_banks_page",
            pdf_terminology_banks_page,
            ["GET"],
        ),
        (
            "/pdf-import/terms/<bank_id>",
            "pdf_terminology_bank_page",
            pdf_terminology_bank_page,
            ["GET"],
        ),
        (
            "/pdf-import/terms/<bank_id>/generate",
            "pdf_terminology_bank_generate",
            pdf_terminology_bank_generate,
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
