"""Quiz Library, ordering, folders, and text-export routes."""

from datetime import datetime
from functools import wraps
import os
import re
import sqlite3

from flask import (
    Blueprint,
    Response,
    current_app as app,
    jsonify,
    redirect,
    render_template,
    request,
)

from .dependencies import QuizLibraryDependencies


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


# Modern Quiz Library UI introduced on 2026-08-21. This module owns its
# presentation context plus the existing folder-management forms and APIs.

def toggle_hidden(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    save_registry = dependencies.save_registry

    quiz_id = int(
        request.form.get("id") or request.json.get("id")
    )

    view = request.form.get("view")

    with registry_lock:
        registry = load_registry()

        for q in registry:
            if q.get("id") == quiz_id:
                q["hidden"] = not q.get("hidden", False)
                break

        save_registry(registry)

    if view:
        return redirect(f"/library?view={view}")

    return redirect("/library")

def move_quiz_folder(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    save_registry = dependencies.save_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders

    quiz_id = int(request.form.get("id"))
    folder = str(request.form.get("folder") or "").strip()
    view = request.form.get("view") or "visible"

    if not folder:
        folder = "Uncategorized"

    with registry_lock:
        registry = normalize_quiz_folders(load_registry())

        for q in registry:
            if q.get("id") == quiz_id:
                q["folder"] = folder
                break

        save_registry(registry)

    return redirect(f"/library?view={view}")

def add_quiz_folder(dependencies):
    get_quiz_folders = dependencies.get_quiz_folders
    save_quiz_folders = dependencies.save_quiz_folders

    folder = str(request.form.get("folder") or "").strip()
    view = request.form.get("view") or "visible"

    if not folder:
        return redirect(f"/library?view={view}")

    folders = get_quiz_folders()

    existing = {f.lower() for f in folders}

    if folder.lower() not in existing:
        folders.append(folder)
        save_quiz_folders(folders)

    return redirect(f"/library?view={view}")

def set_quiz_folder_hidden(dependencies):
    load_registry = dependencies.load_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    get_quiz_folders = dependencies.get_quiz_folders
    get_hidden_quiz_folders = dependencies.get_hidden_quiz_folders
    save_quiz_folder_state = dependencies.save_quiz_folder_state

    requested_folder = str(request.form.get("folder") or "").strip()
    requested_state = request.form.get("hidden")
    view = request.form.get("view") or "visible"

    if (
        not requested_folder
        or requested_folder.lower() == "uncategorized"
        or requested_state not in {"0", "1"}
    ):
        return redirect(f"/library?view={view}")
    hide_folder = requested_state == "1"

    folders = get_quiz_folders()
    configured_name = next(
        (folder for folder in folders if folder.lower() == requested_folder.lower()),
        None,
    )

    # A legacy assignment-only folder becomes explicitly persistent only when
    # the user chooses to hide it. Page loads never promote legacy folders.
    if configured_name is None and hide_folder:
        registry = normalize_quiz_folders(load_registry())
        configured_name = next(
            (
                str(quiz.get("folder") or "Uncategorized").strip()
                for quiz in registry
                if str(quiz.get("folder") or "Uncategorized").strip().lower()
                == requested_folder.lower()
            ),
            None,
        )
        if configured_name:
            folders.append(configured_name)

    if configured_name is None:
        return redirect(f"/library?view={view}")

    hidden_folders = get_hidden_quiz_folders(folders)
    hidden_folders = [
        folder
        for folder in hidden_folders
        if folder.lower() != configured_name.lower()
    ]
    if hide_folder:
        hidden_folders.append(configured_name)

    save_quiz_folder_state(folders, hidden_folders)
    return redirect(f"/library?view={view}")

def rename_quiz_folder(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    save_registry = dependencies.save_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    get_quiz_folders = dependencies.get_quiz_folders
    get_hidden_quiz_folders = dependencies.get_hidden_quiz_folders
    save_quiz_folder_state = dependencies.save_quiz_folder_state

    old_folder = str(request.form.get("old_folder") or "").strip()
    new_folder = str(request.form.get("new_folder") or "").strip()
    view = request.form.get("view") or "visible"

    if not old_folder or not new_folder:
        return redirect(f"/library?view={view}")

    # Keep Uncategorized stable for safety
    if old_folder.lower() == "uncategorized":
        return redirect(f"/library?view={view}")

    folders = get_quiz_folders()
    hidden_folders = get_hidden_quiz_folders(folders)

    # Do not rename into an existing folder name
    existing = {f.lower() for f in folders if f.lower() != old_folder.lower()}
    if new_folder.lower() in existing:
        return redirect(f"/library?view={view}")

    renamed_folders = []
    for folder in folders:
        if folder.lower() == old_folder.lower():
            renamed_folders.append(new_folder)
        else:
            renamed_folders.append(folder)

    renamed_hidden_folders = [
        new_folder if folder.lower() == old_folder.lower() else folder
        for folder in hidden_folders
    ]
    save_quiz_folder_state(renamed_folders, renamed_hidden_folders)

    # Update existing quizzes that were assigned to the old folder
    with registry_lock:
        registry = normalize_quiz_folders(load_registry())

        for q in registry:
            current_folder = str(q.get("folder") or "Uncategorized").strip()

            if current_folder.lower() == old_folder.lower():
                q["folder"] = new_folder

        save_registry(registry)

    return redirect(f"/library?view={view}")

def delete_quiz_folder(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    save_registry = dependencies.save_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    get_quiz_folders = dependencies.get_quiz_folders
    get_hidden_quiz_folders = dependencies.get_hidden_quiz_folders
    save_quiz_folder_state = dependencies.save_quiz_folder_state

    folder = str(request.form.get("folder") or "").strip()
    view = request.form.get("view") or "visible"

    if not folder:
        return redirect(f"/library?view={view}")

    # Never delete Uncategorized
    if folder.lower() == "uncategorized":
        return redirect(f"/library?view={view}")

    # Remove folder from saved folder list
    folders = get_quiz_folders()
    hidden_folders = get_hidden_quiz_folders(folders)
    folders = [
        f for f in folders
        if f.lower() != folder.lower()
    ]
    hidden_folders = [
        hidden_folder
        for hidden_folder in hidden_folders
        if hidden_folder.lower() != folder.lower()
    ]
    save_quiz_folder_state(folders, hidden_folders)

    # Move quizzes from deleted folder back to Uncategorized
    with registry_lock:
        registry = normalize_quiz_folders(load_registry())

        for q in registry:
            current_folder = str(q.get("folder") or "Uncategorized").strip()

            if current_folder.lower() == folder.lower():
                q["folder"] = "Uncategorized"

        save_registry(registry)

    return redirect(f"/library?view={view}")

def save_folder_order(dependencies):
    get_quiz_folders = dependencies.get_quiz_folders
    save_quiz_folders = dependencies.save_quiz_folders
    get_hidden_quiz_folders = dependencies.get_hidden_quiz_folders

    data = request.get_json() or {}
    ordered_folders = data.get("folders", [])
    view = str(data.get("view") or "").strip().lower()

    if not isinstance(ordered_folders, list):
        return jsonify(status="error", error="Invalid folder order"), 400

    current_folders = get_quiz_folders()

    # Keep only valid folder names from the request
    cleaned_order = []
    seen = set()

    for folder in ordered_folders:
        name = str(folder or "").strip()

        if not name:
            continue

        key = name.lower()

        if key in seen:
            continue

        cleaned_order.append(name)
        seen.add(key)

    hidden_keys = {
        folder.lower()
        for folder in get_hidden_quiz_folders(current_folders)
    }

    if view == "visible" and hidden_keys:
        # Visible omits hidden folders. Reorder only submitted folder slots so
        # every omitted hidden folder retains its position in the saved order.
        current_keys = {folder.lower() for folder in current_folders}
        submitted = [
            folder
            for folder in cleaned_order
            if folder.lower() in current_keys
            and folder.lower() not in hidden_keys
        ]
        submitted_keys = {folder.lower() for folder in submitted}
        submitted_iter = iter(submitted)
        merged_order = [
            next(submitted_iter) if folder.lower() in submitted_keys else folder
            for folder in current_folders
        ]
        merged_keys = {folder.lower() for folder in merged_order}
        merged_order.extend(
            folder
            for folder in cleaned_order
            if folder.lower() not in merged_keys
        )
        cleaned_order = merged_order
    else:
        # Preserve the established behavior when the page submits its complete
        # normal folder ordering.
        for folder in current_folders:
            if folder.lower() not in seen:
                cleaned_order.append(folder)

    save_quiz_folders(cleaned_order)

    return jsonify(status="ok")

def save_quiz_order_in_folder(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    save_registry = dependencies.save_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders

    data = request.get_json() or {}

    folder = str(data.get("folder") or "").strip()
    ordered_html = data.get("order", [])

    if not folder:
        folder = "Uncategorized"

    if not isinstance(ordered_html, list):
        return jsonify(status="error", error="Invalid quiz order"), 400

    with registry_lock:
        registry = normalize_quiz_folders(load_registry())

        # Quizzes currently in this folder
        folder_quizzes = [
            q for q in registry
            if str(q.get("folder") or "Uncategorized").strip().lower() == folder.lower()
        ]

        # Lookup quizzes in this folder by HTML filename
        folder_lookup = {
            q.get("html"): q
            for q in folder_quizzes
            if q.get("html")
        }

        reordered_folder_quizzes = []
        used_html = set()

        # Add quizzes in the requested order
        for html in ordered_html:
            if html in folder_lookup and html not in used_html:
                reordered_folder_quizzes.append(folder_lookup[html])
                used_html.add(html)

        # Preserve any folder quizzes missing from the request
        for q in folder_quizzes:
            html = q.get("html")
            if html not in used_html:
                reordered_folder_quizzes.append(q)

        # Rebuild full registry
        new_registry = []
        inserted_folder = False

        for q in registry:
            current_folder = str(q.get("folder") or "Uncategorized").strip()

            if current_folder.lower() == folder.lower():
                if not inserted_folder:
                    new_registry.extend(reordered_folder_quizzes)
                    inserted_folder = True
                continue

            new_registry.append(q)

        save_registry(new_registry)

    return jsonify(status="ok")

def save_order(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    save_registry = dependencies.save_registry


    data = request.get_json()
    order = data.get("order", [])

    with registry_lock:
        registry = load_registry()

        lookup = {q["html"]: q for q in registry}
        new_list = []

        for html in order:
            if html in lookup:
                new_list.append(lookup.pop(html))

        new_list.extend(lookup.values())
        save_registry(new_list)

    return {"status": "ok"}

def export_all_quizzes_txt(dependencies):
    APP_VERSION = dependencies.app_version()
    load_registry = dependencies.load_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    get_db = dependencies.get_db

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    registry = normalize_quiz_folders(load_registry())
    registry_by_id = {
        int(q.get("id")): q
        for q in registry
        if q.get("id") is not None
    }

    quizzes = cur.execute(
        """
        SELECT id, title, source_file
        FROM quizzes
        ORDER BY title COLLATE NOCASE, id
        """
    ).fetchall()

    lines = []
    exported_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append("# DLMS Quiz Export")
    lines.append(f"# Exported from DLMS v{APP_VERSION}")
    lines.append(f"# Exported on: {exported_on}")
    lines.append("# Format: DLMS text")
    lines.append("# Import compatible: No - contains multiple quizzes")
    lines.append("# Use Export Quiz for import-friendly single quiz files")
    lines.append(f"# Total quizzes: {len(quizzes)}")
    lines.append("")

    for quiz in quizzes:
        quiz_id = quiz["id"]
        quiz_title = quiz["title"] or "Untitled Quiz"
        folder = registry_by_id.get(quiz_id, {}).get("folder", "Uncategorized")

        lines.append("=" * 60)
        lines.append(f"QUIZ: {quiz_title}")
        lines.append(f"QUIZ ID: {quiz_id}")
        lines.append(f"FOLDER: {folder}")
        lines.append("=" * 60)
        lines.append("")

        questions = cur.execute(
            """
            SELECT id, question_number, question_text
            FROM questions
            WHERE quiz_id = ?
            ORDER BY question_number, id
            """,
            (quiz_id,)
        ).fetchall()

        for question in questions:
            question_id = question["id"]
            question_number = question["question_number"]
            question_text = question["question_text"] or ""

            lines.append(f"{question_number}. {question_text}")
            lines.append("")

            choices = cur.execute(
                """
                SELECT label, text, is_correct
                FROM choices
                WHERE question_id = ?
                ORDER BY label
                """,
                (question_id,)
            ).fetchall()

            correct_labels = []

            for choice in choices:
                label = choice["label"]
                text = choice["text"] or ""
                is_correct = bool(choice["is_correct"])

                lines.append(f"{label}. {text}")

                if is_correct:
                    correct_labels.append(label)

            lines.append("")

            if len(correct_labels) == 1:
                lines.append(f"Correct Answer: {correct_labels[0]}")
            else:
                lines.append(f"Correct Answer: {', '.join(correct_labels)}")

            lines.append("")
            lines.append("")

        lines.append("")

    conn.close()

    export_text = "\n".join(lines)

    return Response(
        export_text,
        mimetype="text/plain",
        headers={
            "Content-Disposition": "attachment; filename=dlms_all_quizzes_export.txt"
        }
    )

def export_single_quiz_txt(dependencies, quiz_id):
    APP_VERSION = dependencies.app_version()
    load_registry = dependencies.load_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    get_db = dependencies.get_db

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    registry = normalize_quiz_folders(load_registry())
    registry_by_id = {
        int(q.get("id")): q
        for q in registry
        if q.get("id") is not None
    }

    quiz = cur.execute(
        """
        SELECT id, title, source_file
        FROM quizzes
        WHERE id = ?
        """,
        (quiz_id,)
    ).fetchone()

    if not quiz:
        conn.close()
        return "Quiz not found", 404

    quiz_title = quiz["title"] or "Untitled Quiz"
    folder = registry_by_id.get(quiz_id, {}).get("folder", "Uncategorized")

    exported_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append("# DLMS Single Quiz Export")
    lines.append(f"# Exported from DLMS v{APP_VERSION}")
    lines.append(f"# Exported on: {exported_on}")
    lines.append("# Format: DLMS text")
    lines.append("# Import compatible: Yes")
    lines.append("")

    lines.append("=" * 60)
    lines.append(f"QUIZ: {quiz_title}")
    lines.append(f"QUIZ ID: {quiz_id}")
    lines.append(f"FOLDER: {folder}")
    lines.append("=" * 60)
    lines.append("")

    questions = cur.execute(
        """
        SELECT id, question_number, question_text
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number, id
        """,
        (quiz_id,)
    ).fetchall()

    for question in questions:
        question_id = question["id"]
        question_number = question["question_number"]
        question_text = question["question_text"] or ""

        lines.append(f"{question_number}. {question_text}")
        lines.append("")

        choices = cur.execute(
            """
            SELECT label, text, is_correct
            FROM choices
            WHERE question_id = ?
            ORDER BY label
            """,
            (question_id,)
        ).fetchall()

        correct_labels = []

        for choice in choices:
            label = choice["label"]
            text = choice["text"] or ""
            is_correct = bool(choice["is_correct"])

            lines.append(f"{label}. {text}")

            if is_correct:
                correct_labels.append(label)

        lines.append("")

        if len(correct_labels) == 1:
            lines.append(f"Correct Answer: {correct_labels[0]}")
        else:
            lines.append(f"Correct Answer: {', '.join(correct_labels)}")

        lines.append("")
        lines.append("")

    conn.close()

    export_text = "\n".join(lines)

    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", quiz_title).strip("_")
    if not safe_title:
        safe_title = f"quiz_{quiz_id}"

    return Response(
        export_text,
        mimetype="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=dlms_quiz_{quiz_id}_{safe_title}.txt"
        }
    )

def quiz_library(dependencies):
    APP_VERSION = dependencies.app_version()
    LOGO_FOLDER = dependencies.logo_folder()
    QUIZ_REGISTRY = dependencies.quiz_registry_path()
    load_registry = dependencies.load_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    get_quiz_folders = dependencies.get_quiz_folders
    get_hidden_quiz_folders = dependencies.get_hidden_quiz_folders
    get_portal_title = dependencies.get_portal_title
    resolve_logo_filename = dependencies.resolve_logo_filename
    dprint = dependencies.debug_print

    registry = normalize_quiz_folders(load_registry())

    dprint("[REGISTRY DEBUG] Using registry file:", QUIZ_REGISTRY)
    dprint("[REGISTRY DEBUG] Registry size:", len(registry))
    dprint("[REGISTRY DEBUG] Registry entries:", [
        {
            "id": q.get("id"),
            "title": q.get("title"),
            "html": q.get("html"),
            "hidden": q.get("hidden", False),
        }
        for q in registry
    ])

    for q in registry:
        logo = q.get("logo")
        if logo:
            path = os.path.join(LOGO_FOLDER, logo)
            dprint("[DEBUG] Logo check:", logo, "exists =", os.path.exists(path), "path =", path)

    portal_title = get_portal_title()

    # =====================================================
    # VIEW MODE RESOLUTION (BACKWARD COMPATIBLE)
    # =====================================================
    # Priority:
    # 1) explicit ?view=
    # 2) legacy ?show_hidden=1
    # 3) default = visible only
    view = request.args.get("view")

    if not view and request.args.get("show_hidden") == "1":
        view = "all"

    folder_names = get_quiz_folders()
    configured_folders = list(folder_names)
    configured_folder_names = set(configured_folders)
    registry_folder_names = sorted({
        str(q.get("folder") or "Uncategorized").strip() or "Uncategorized"
        for q in registry
    })

    for folder in registry_folder_names:
        if folder not in folder_names:
            folder_names.append(folder)

    hidden_folder_names = get_hidden_quiz_folders(configured_folders)
    hidden_folder_keys = {folder.lower() for folder in hidden_folder_names}

    def quiz_folder_name(quiz):
        return str(quiz.get("folder") or "Uncategorized").strip() or "Uncategorized"

    def quiz_folder_is_hidden(quiz):
        return quiz_folder_name(quiz).lower() in hidden_folder_keys

    if view == "hidden":
        filtered = [
            q for q in registry
            if q.get("hidden", False) or quiz_folder_is_hidden(q)
        ]
    elif view == "all":
        filtered = registry
    else:
        view = "visible"
        filtered = [
            q for q in registry
            if not q.get("hidden", False) and not quiz_folder_is_hidden(q)
        ]

    normal_filtered = filtered
    render_filtered = filtered
    if view == "visible":
        # Hidden folders stay absent during normal browsing, but their quizzes
        # are present as search-only markup so client-side search can reveal a
        # matching result without changing quiz-level hidden state.
        render_filtered = [
            q for q in registry
            if not q.get("hidden", False) or quiz_folder_is_hidden(q)
        ]

    quizzes = [
        {**q, "logo": resolve_logo_filename(q.get("logo"))}
        for q in render_filtered
    ]
    normal_grouped_quizzes = {folder: [] for folder in folder_names}
    for q in normal_filtered:
        folder = quiz_folder_name(q)
        if folder not in normal_grouped_quizzes:
            normal_grouped_quizzes[folder] = []
        normal_grouped_quizzes[folder].append(q)

    grouped_quizzes = {folder: [] for folder in folder_names}
    for q in quizzes:
        folder = quiz_folder_name(q)
        if folder not in grouped_quizzes:
            grouped_quizzes[folder] = []
        grouped_quizzes[folder].append(q)

    # Persistent custom folders remain visible when empty in Visible and All.
    # Hidden shows only hidden folders or folders containing filtered hidden
    # quizzes. Assignment-only legacy folders retain their discovery behavior.
    normal_display_folder_names = [
        folder for folder in folder_names
        if not (view == "visible" and folder.lower() in hidden_folder_keys)
        and (
            normal_grouped_quizzes.get(folder)
            or (
                folder in configured_folder_names
                and folder.lower() != "uncategorized"
                and (
                    view != "hidden"
                    or folder.lower() in hidden_folder_keys
                )
            )
        )
    ]
    display_folder_names = [
        folder for folder in folder_names
        if folder in normal_display_folder_names
        or (
            view == "visible"
            and folder.lower() in hidden_folder_keys
            and grouped_quizzes.get(folder)
        )
    ]

    visible_count = sum(
        1 for q in registry
        if not q.get("hidden", False) and not quiz_folder_is_hidden(q)
    )
    hidden_count = len(registry) - visible_count
    view_quiz_count = len(normal_filtered)

    return render_template("quiz/library.html", quizzes=quizzes, grouped_quizzes=grouped_quizzes, folder_names=folder_names,
       display_folder_names=display_folder_names,
       normal_display_folder_names=normal_display_folder_names,
       hidden_folder_keys=hidden_folder_keys, portal_title=portal_title,
       visible_count=visible_count, hidden_count=hidden_count,
       view_quiz_count=view_quiz_count, view=view, app_version=APP_VERSION)

def register_library_routes(
    blueprint: Blueprint, dependencies: QuizLibraryDependencies
) -> None:
    """Register Quiz Library and lifecycle-list routes."""
    routes = (
        ("/toggle_hidden", "toggle_hidden", toggle_hidden, ["POST"]),
        ("/move_quiz_folder", "move_quiz_folder", move_quiz_folder, ["POST"]),
        ("/add_quiz_folder", "add_quiz_folder", add_quiz_folder, ["POST"]),
        ("/set_quiz_folder_hidden", "set_quiz_folder_hidden", set_quiz_folder_hidden, ["POST"]),
        ("/rename_quiz_folder", "rename_quiz_folder", rename_quiz_folder, ["POST"]),
        ("/delete_quiz_folder", "delete_quiz_folder", delete_quiz_folder, ["POST"]),
        ("/save_folder_order", "save_folder_order", save_folder_order, ["POST"]),
        ("/save_quiz_order_in_folder", "save_quiz_order_in_folder", save_quiz_order_in_folder, ["POST"]),
        ("/save_order", "save_order", save_order, ["POST"]),
        ("/export/all_quizzes.txt", "export_all_quizzes_txt", export_all_quizzes_txt, ["GET"]),
        ("/export/quiz/<int:quiz_id>.txt", "export_single_quiz_txt", export_single_quiz_txt, ["GET"]),
        ("/library", "quiz_library", quiz_library, ["GET"]),
    )
    for rule, endpoint, view_func, methods in routes:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
