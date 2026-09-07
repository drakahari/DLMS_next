"""Quiz asset serving, editor, mutation, deletion, and rebuild routes."""

from functools import wraps
import os
import sqlite3
import time

from flask import (
    Blueprint,
    current_app as app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from .dependencies import QuizEditorDependencies


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view

def serve_data(dependencies, filename):
    DATA_FOLDER = dependencies.data_folder()
    BROWSER_SERVED_DATA_EXTENSIONS = dependencies.browser_served_data_extensions()

    extension = os.path.splitext(str(filename or ""))[1].lower()
    if extension not in BROWSER_SERVED_DATA_EXTENSIONS:
        return "Unsupported data file", 415
    return send_from_directory(DATA_FOLDER, filename)

def serve_quiz(dependencies, filename):
    QUIZ_FOLDER = dependencies.quiz_folder()

    if os.path.splitext(str(filename or ""))[1].lower() != ".html":
        return "Unsupported quiz file", 415
    return send_from_directory(QUIZ_FOLDER, filename)

def edit_quiz(dependencies, quiz_id):
    APP_VERSION = dependencies.app_version()
    get_db = dependencies.get_db
    load_registry = dependencies.load_registry
    normalize_exam_minutes = dependencies.normalize_exam_minutes
    _question_concepts = dependencies.question_concepts

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    quiz = cur.execute(
        "SELECT id, title, source_file FROM quizzes WHERE id = ?",
        (quiz_id,)
    ).fetchone()

    if not quiz:
        conn.close()
        return "Quiz not found", 404

    questions = cur.execute(
        """
        SELECT id, question_number, question_text, COALESCE(question_type, 'choice') AS question_type, matching_round_size, COALESCE(matching_direction, 'term_to_definition') AS matching_direction, source_organization, source_dataset, source_version, source_url, source_license, explanation, media_json
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number, id
        """,
        (quiz_id,)
    ).fetchall()

    question_list = []

    for q in questions:
        choices = cur.execute(
            """
            SELECT id, label, text, is_correct
            FROM choices
            WHERE question_id = ?
            ORDER BY label
            """,
            (q["id"],)
        ).fetchall()

        pairs = cur.execute(
            """
            SELECT id, pair_order, left_text, right_text, category, explanation, verification_json
            FROM matching_pairs
            WHERE question_id = ?
            ORDER BY pair_order, id
            """,
            (q["id"],)
        ).fetchall() if q["question_type"] == "matching" else []

        question_list.append({
            "id": q["id"],
            "number": q["question_number"],
            "text": q["question_text"],
            "type": q["question_type"],
            "choices": choices,
            "pairs": pairs,
            "round_size": q["matching_round_size"],
            "direction": q["matching_direction"],
            "explanation": q["explanation"] or "",
            "concepts": _question_concepts(cur, q["id"]),
            "source": {
                "organization": q["source_organization"], "dataset": q["source_dataset"],
                "version": q["source_version"], "url": q["source_url"], "license": q["source_license"]
            }
        })

    conn.close()

    registry = load_registry()
    quiz_entry = next((q for q in registry if str(q.get("id")) == str(quiz_id)), {})
    exam_minutes = normalize_exam_minutes(quiz_entry.get("exam_minutes", 90))

    return render_template("quiz/edit.html", quiz=quiz, questions=question_list, exam_minutes=exam_minutes, app_version=APP_VERSION)

def rebuild_all_quiz_html(dependencies):
    load_registry = dependencies.load_registry
    rebuild_quiz_html_from_registry = dependencies.rebuild_quiz_html_from_registry

    registry = load_registry()

    rebuilt = 0
    failed = []

    for entry in registry:
        quiz_id = entry.get("id")

        if quiz_id is None:
            continue

        try:
            quiz_id = int(quiz_id)

            if rebuild_quiz_html_from_registry(quiz_id):
                rebuilt += 1
            else:
                failed.append(quiz_id)

        except Exception as e:
            print(
                f"[REBUILD ALL] Failed quiz_id={quiz_id}: {e}"
            )
            failed.append(quiz_id)

    return jsonify({
        "status": "complete",
        "rebuilt": rebuilt,
        "failed": failed
    })

def save_edited_quiz(dependencies, quiz_id):
    get_db = dependencies.get_db
    normalize_exam_minutes = dependencies.normalize_exam_minutes
    _set_question_concepts = dependencies.set_question_concepts
    _quiz_owns_question = dependencies.quiz_owns_question
    _quiz_edit_validation = dependencies.quiz_edit_validation
    _publish_quiz_edit_request = dependencies.publish_quiz_edit_request

    conn = get_db()
    cur = conn.cursor()

    action = request.form.get("action", "")

    action_question_id = None
    if action.startswith("add_match_pair_") or action.startswith("add_choices_"):
        try:
            action_question_id = int(action.rsplit("_", 1)[1])
        except ValueError:
            conn.close()
            flash("Invalid question selected for editing.", "error")
            return redirect(f"/edit_quiz/{quiz_id}")
        if not _quiz_owns_question(cur, quiz_id, action_question_id):
            conn.close()
            flash("The selected question does not belong to this quiz.", "error")
            return redirect(f"/edit_quiz/{quiz_id}")

    ts = int(time.time())
    quiz_logo = request.files.get("quiz_logo")

    # =========================
    # SAVE CURRENT FORM VALUES FIRST
    # =========================
    new_title = request.form.get("quiz_title", "").strip()
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))

    if new_title:
        cur.execute(
            "UPDATE quizzes SET title = ? WHERE id = ?",
            (new_title, quiz_id)
        )

    questions = cur.execute(
        "SELECT id, COALESCE(question_type, 'choice') FROM questions WHERE quiz_id = ?",
        (quiz_id,)
    ).fetchall()

    for q in questions:
        question_id = q[0]
        question_type = q[1]
        new_question_text = request.form.get(f"question_{question_id}", "").strip()
        new_explanation = request.form.get(f"explanation_{question_id}", "").strip()
        new_concepts = request.form.get(f"concepts_{question_id}", "")
        _set_question_concepts(cur, question_id, new_concepts)
        if question_type == "matching":
            raw_round_size = request.form.get(f"matching_round_size_{question_id}", "").strip()
            try:
                round_size = int(raw_round_size) if raw_round_size else None
            except ValueError:
                round_size = None
            if round_size is not None:
                round_size = max(2, min(round_size, 100))
            direction = request.form.get(f"matching_direction_{question_id}", "term_to_definition").strip()
            if direction not in {"term_to_definition", "definition_to_term", "random"}:
                direction = "term_to_definition"
            cur.execute(
                "UPDATE questions SET question_text = ?, matching_round_size = ?, matching_direction = ?, explanation = ? WHERE id = ?",
                (new_question_text, round_size, direction, new_explanation, question_id)
            )
        else:
            cur.execute(
                "UPDATE questions SET question_text = ?, explanation = ? WHERE id = ?",
                (new_question_text, new_explanation, question_id)
            )

    choices = cur.execute(
        """
        SELECT c.id
        FROM choices c
        JOIN questions q ON q.id = c.question_id
        WHERE q.quiz_id = ?
        """,
        (quiz_id,)
    ).fetchall()

    for c in choices:
        choice_id = c[0]
        new_choice_text = request.form.get(f"choice_{choice_id}", "").strip()
        is_correct = 1 if request.form.get(f"correct_{choice_id}") else 0

        cur.execute(
            """
            UPDATE choices
            SET text = ?, is_correct = ?
            WHERE id = ?
            """,
            (new_choice_text, is_correct, choice_id)
        )

    matching_pairs = cur.execute(
        """
        SELECT mp.id
        FROM matching_pairs mp
        JOIN questions q ON q.id = mp.question_id
        WHERE q.quiz_id = ?
        """,
        (quiz_id,)
    ).fetchall()

    for pair in matching_pairs:
        pair_id = pair[0]
        left_text = request.form.get(f"match_left_{pair_id}", "").strip()
        right_text = request.form.get(f"match_right_{pair_id}", "").strip()
        cur.execute(
            "UPDATE matching_pairs SET left_text = ?, right_text = ? WHERE id = ?",
            (left_text, right_text, pair_id)
        )

    # =========================
    # ADD NEW QUESTION
    # =========================
    if action == "add_question":
        row = cur.execute(
            "SELECT MAX(question_number) FROM questions WHERE quiz_id = ?",
            (quiz_id,)
        ).fetchone()

        next_qnum = (row[0] or 0) + 1

        cur.execute(
            """
            INSERT INTO questions (quiz_id, question_number, question_text)
            VALUES (?, ?, ?)
            """,
            (quiz_id, next_qnum, "New question")
        )

        question_id = cur.lastrowid

        for label in ["A", "B", "C", "D"]:
            cur.execute(
                """
                INSERT INTO choices (question_id, label, text, is_correct)
                VALUES (?, ?, ?, ?)
                """,
                (question_id, label, f"Option {label}", 0)
            )

        try:
            _publish_quiz_edit_request(
                conn, quiz_id, title=new_title, exam_minutes=exam_minutes,
                logo_file=quiz_logo, timestamp=ts,
            )
        except Exception as exc:
            print(f"[EDIT ERROR] Could not add question atomically: {exc}")
            flash("Quiz changes could not be saved. The original quiz was preserved.", "error")
        finally:
            conn.close()

        return redirect(f"/edit_quiz/{quiz_id}")

    # =========================
    # ADD PAIR TO MATCHING QUESTION
    # =========================
    if action.startswith("add_match_pair_"):
        question_id = action_question_id

        row = cur.execute("SELECT MAX(pair_order) FROM matching_pairs WHERE question_id = ?", (question_id,)).fetchone()
        next_order = (row[0] or 0) + 1
        cur.execute(
            "INSERT INTO matching_pairs(question_id, pair_order, left_text, right_text) VALUES (?, ?, ?, ?)",
            (question_id, next_order, "New term", "New match")
        )
        try:
            _publish_quiz_edit_request(
                conn, quiz_id, title=new_title, exam_minutes=exam_minutes,
                logo_file=quiz_logo, timestamp=ts,
            )
        except Exception as exc:
            print(f"[EDIT ERROR] Could not add matching pair atomically: {exc}")
            flash("Quiz changes could not be saved. The original quiz was preserved.", "error")
        finally:
            conn.close()
        return redirect(f"/edit_quiz/{quiz_id}")

    # =========================
    # ADD CHOICES TO EXISTING QUESTION
    # =========================
    if action.startswith("add_choices_"):
        question_id = action_question_id

        try:
            count = int(request.form.get(f"choice_count_{question_id}", 1))
        except ValueError:
            count = 1

        if count < 1:
            count = 1
        if count > 10:
            count = 10

        existing = cur.execute(
            """
            SELECT label
            FROM choices
            WHERE question_id = ?
            ORDER BY label
            """,
            (question_id,)
        ).fetchall()

        used_labels = {row[0] for row in existing}

        added = 0
        label_index = 0

        while added < count and label_index < 26:
            label = chr(ord("A") + label_index)

            if label not in used_labels:
                cur.execute(
                    """
                    INSERT INTO choices (question_id, label, text, is_correct)
                    VALUES (?, ?, ?, ?)
                    """,
                    (question_id, label, f"Option {label}", 0)
                )

                used_labels.add(label)
                added += 1

            label_index += 1

        try:
            _publish_quiz_edit_request(
                conn, quiz_id, title=new_title, exam_minutes=exam_minutes,
                logo_file=quiz_logo, timestamp=ts,
            )
        except Exception as exc:
            print(f"[EDIT ERROR] Could not add choices atomically: {exc}")
            flash("Quiz changes could not be saved. The original quiz was preserved.", "error")
        finally:
            conn.close()

        return redirect(f"/edit_quiz/{quiz_id}")

    # =========================
    # VALIDATION: each question must have at least one correct answer
    # =========================
    validation_errors, validation_warnings = _quiz_edit_validation(cur, quiz_id)
    if validation_errors:
        conn.rollback()
        conn.close()
        flash("; ".join(validation_errors), "error")
        return redirect(url_for("quiz.edit_quiz", quiz_id=quiz_id))
    for warning in validation_warnings:
        flash(warning, "warning")

    try:
        _publish_quiz_edit_request(
            conn, quiz_id, title=new_title, exam_minutes=exam_minutes,
            logo_file=quiz_logo, timestamp=ts,
        )
    except Exception as exc:
        print(f"[EDIT ERROR] Could not save quiz atomically: {exc}")
        flash("Quiz changes could not be saved. The original quiz was preserved.", "error")
    finally:
        conn.close()

    return redirect(f"/edit_quiz/{quiz_id}")

def delete_question_from_quiz(dependencies, quiz_id, question_id):
    get_db = dependencies.get_db
    _finish_quiz_mutation = dependencies.finish_quiz_mutation

    conn = get_db()
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    # Delete the question
    cur.execute(
        "DELETE FROM questions WHERE id = ? AND quiz_id = ?",
        (question_id, quiz_id)
    )

    # 🔑 Resequence question numbers
    questions = cur.execute(
        "SELECT id FROM questions WHERE quiz_id = ? ORDER BY question_number, id",
        (quiz_id,)
    ).fetchall()

    for idx, q in enumerate(questions, start=1):
        cur.execute(
            "UPDATE questions SET question_number = ? WHERE id = ?",
            (idx, q["id"])
        )

    try:
        _finish_quiz_mutation(conn, quiz_id)
    except Exception as exc:
        print(f"[EDIT ERROR] Could not delete question atomically: {exc}")
        flash("The question could not be deleted. The original quiz was preserved.", "error")
    finally:
        conn.close()

    return redirect(f"/edit_quiz/{quiz_id}")

def add_choices_to_question(dependencies, quiz_id, question_id):
    get_db = dependencies.get_db
    _finish_quiz_mutation = dependencies.finish_quiz_mutation
    _quiz_owns_question = dependencies.quiz_owns_question

    conn = get_db()
    cur = conn.cursor()

    if not _quiz_owns_question(cur, quiz_id, question_id):
        conn.close()
        flash("The selected question does not belong to this quiz.", "error")
        return redirect(f"/edit_quiz/{quiz_id}")

    try:
        count = int(request.form.get("choice_count", 1))
    except ValueError:
        count = 1

    # Safety limits
    if count < 1:
        count = 1
    if count > 10:
        count = 10

    existing = cur.execute(
        """
        SELECT label
        FROM choices
        WHERE question_id = ?
        ORDER BY label
        """,
        (question_id,)
    ).fetchall()

    used_labels = {row[0] for row in existing}

    added = 0
    label_index = 0

    while added < count:
        label = chr(ord("A") + label_index)

        if label not in used_labels:
            cur.execute(
                """
                INSERT INTO choices (question_id, label, text, is_correct)
                VALUES (?, ?, ?, ?)
                """,
                (question_id, label, f"Option {label}", 0)
            )

            used_labels.add(label)
            added += 1

        label_index += 1

    try:
        _finish_quiz_mutation(conn, quiz_id)
    except Exception as exc:
        print(f"[EDIT ERROR] Could not add choices atomically: {exc}")
        flash("The choices could not be added. The original quiz was preserved.", "error")
    finally:
        conn.close()

    return redirect(f"/edit_quiz/{quiz_id}")

def delete_choice_from_question(dependencies, quiz_id, choice_id):
    get_db = dependencies.get_db
    _finish_quiz_mutation = dependencies.finish_quiz_mutation
    _quiz_owns_choice = dependencies.quiz_owns_choice

    conn = get_db()
    cur = conn.cursor()

    if not _quiz_owns_choice(cur, quiz_id, choice_id):
        conn.close()
        flash("The selected answer choice does not belong to this quiz.", "error")
        return redirect(f"/edit_quiz/{quiz_id}")

    # Find the question this choice belongs to
    row = cur.execute(
        """
        SELECT question_id
        FROM choices
        WHERE id = ?
        """,
        (choice_id,)
    ).fetchone()

    if not row:
        conn.close()
        return redirect(f"/edit_quiz/{quiz_id}")

    question_id = row[0]

    # Do not allow deleting the last remaining choice
    choice_count = cur.execute(
        """
        SELECT COUNT(*)
        FROM choices
        WHERE question_id = ?
        """,
        (question_id,)
    ).fetchone()[0]

    if choice_count <= 1:
        conn.close()
        flash("A question must have at least one answer choice.", "error")
        return redirect(f"/edit_quiz/{quiz_id}")

    # Delete the selected choice
    cur.execute(
        """
        DELETE FROM choices
        WHERE id = ?
        """,
        (choice_id,)
    )

    try:
        _finish_quiz_mutation(conn, quiz_id)
    except Exception as exc:
        print(f"[EDIT ERROR] Could not delete choice atomically: {exc}")
        flash("The choice could not be deleted. The original quiz was preserved.", "error")
    finally:
        conn.close()

    return redirect(f"/edit_quiz/{quiz_id}")

def delete_match_pair_from_question(dependencies, quiz_id, pair_id):
    get_db = dependencies.get_db
    _finish_quiz_mutation = dependencies.finish_quiz_mutation
    _quiz_owns_matching_pair = dependencies.quiz_owns_matching_pair

    conn = get_db()
    cur = conn.cursor()
    if not _quiz_owns_matching_pair(cur, quiz_id, pair_id):
        conn.close()
        flash("The selected matching pair does not belong to this quiz.", "error")
        return redirect(f"/edit_quiz/{quiz_id}")
    row = cur.execute("SELECT question_id FROM matching_pairs WHERE id = ?", (pair_id,)).fetchone()
    if not row:
        conn.close()
        return redirect(f"/edit_quiz/{quiz_id}")
    question_id = row[0]
    pair_count = cur.execute("SELECT COUNT(*) FROM matching_pairs WHERE question_id = ?", (question_id,)).fetchone()[0]
    if pair_count <= 2:
        conn.close()
        flash("A matching question must retain at least two pairs.", "error")
        return redirect(f"/edit_quiz/{quiz_id}")
    cur.execute("DELETE FROM matching_pairs WHERE id = ?", (pair_id,))
    remaining = cur.execute("SELECT id FROM matching_pairs WHERE question_id = ? ORDER BY pair_order, id", (question_id,)).fetchall()
    for idx, item in enumerate(remaining, start=1):
        cur.execute("UPDATE matching_pairs SET pair_order = ? WHERE id = ?", (idx, item[0]))
    try:
        _finish_quiz_mutation(conn, quiz_id)
    except Exception as exc:
        print(f"[EDIT ERROR] Could not delete matching pair atomically: {exc}")
        flash("The matching pair could not be deleted. The original quiz was preserved.", "error")
    finally:
        conn.close()
    return redirect(f"/edit_quiz/{quiz_id}")

def delete_quiz(dependencies, quiz_id):
    _delete_quiz_transaction = dependencies.delete_quiz_transaction
    _cleanup_deleted_quiz_artifacts = dependencies.cleanup_deleted_quiz_artifacts

    print("[DELETE] Requested quiz_id:", quiz_id)
    try:
        deleted_entry, kept = _delete_quiz_transaction(quiz_id)
    except Exception as exc:
        print(f"[DELETE ERROR] Quiz deletion was rolled back: {exc}")
        flash("The quiz could not be deleted. The existing quiz was preserved.", "error")
        return redirect("/library")

    _cleanup_deleted_quiz_artifacts(deleted_entry, kept)

    print("[DELETE] Completed quiz_id:", quiz_id)
    return redirect("/library")

def register_editor_routes(
    blueprint: Blueprint, dependencies: QuizEditorDependencies
) -> None:
    """Register Quiz editor, asset, mutation, deletion, and rebuild routes."""
    routes = (
        ("/data/<path:filename>", "serve_data", serve_data, ["GET"]),
        ("/quizzes/<path:filename>", "serve_quiz", serve_quiz, ["GET"]),
        ("/edit_quiz/<int:quiz_id>", "edit_quiz", edit_quiz, ["GET"]),
        ("/admin/rebuild_all_quiz_html", "rebuild_all_quiz_html", rebuild_all_quiz_html, ["POST"]),
        ("/edit_quiz/<int:quiz_id>", "save_edited_quiz", save_edited_quiz, ["POST"]),
        ("/delete_question/<int:quiz_id>/<int:question_id>", "delete_question_from_quiz", delete_question_from_quiz, ["POST"]),
        ("/add_choices/<int:quiz_id>/<int:question_id>", "add_choices_to_question", add_choices_to_question, ["POST"]),
        ("/delete_choice/<int:quiz_id>/<int:choice_id>", "delete_choice_from_question", delete_choice_from_question, ["POST"]),
        ("/delete_match_pair/<int:quiz_id>/<int:pair_id>", "delete_match_pair_from_question", delete_match_pair_from_question, ["POST"]),
        ("/delete_quiz/<int:quiz_id>", "delete_quiz", delete_quiz, ["POST"]),
    )
    for rule, endpoint, view_func, methods in routes:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
