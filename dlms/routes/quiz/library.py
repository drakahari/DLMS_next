"""Quiz Library, ordering, folders, and text-export routes."""

from datetime import datetime
from functools import wraps
import os
import re
import sqlite3
from urllib.parse import urlencode

from flask import (
    Blueprint,
    Response,
    current_app as app,
    jsonify,
    redirect,
    render_template,
    request,
)

from dlms.services.quiz_smart_views import normalize_smart_view

from .dependencies import QuizLibraryDependencies


VIRTUAL_GENERATED_PRACTICE_GROUP = ("dlms-virtual", "generated-practice")


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


# Modern Quiz Library UI introduced on 2026-08-21. This module owns its
# presentation context plus the existing folder-management forms and APIs.


def _library_return_url(view=None, smart=None):
    normalized_view = str(view or "").strip().casefold()
    if normalized_view not in {"visible", "hidden", "all"}:
        normalized_view = "visible"
    query = {"view": normalized_view}
    normalized_smart = normalize_smart_view(smart)
    if normalized_smart:
        query["smart"] = normalized_smart
    return f"/library?{urlencode(query)}"

def toggle_hidden(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    save_registry = dependencies.save_registry

    quiz_id = int(
        request.form.get("id") or request.json.get("id")
    )

    view = request.form.get("view")
    smart = request.form.get("smart")

    with registry_lock:
        registry = load_registry()

        for q in registry:
            if q.get("id") == quiz_id:
                q["hidden"] = not q.get("hidden", False)
                break

        save_registry(registry)

    if view or smart:
        return redirect(_library_return_url(view, smart))

    return redirect("/library")

def move_quiz_folder(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    save_registry = dependencies.save_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    build_folder_identity = dependencies.build_quiz_folder_identity
    get_quiz_folders = dependencies.get_quiz_folders

    quiz_id = int(request.form.get("id"))
    folder = str(request.form.get("folder") or "").strip()
    view = request.form.get("view") or "visible"
    smart = request.form.get("smart")

    with registry_lock:
        loaded_registry = load_registry()
        identity = build_folder_identity(
            get_quiz_folders(), loaded_registry
        )
        target_folder = identity.resolve(folder)
        if target_folder is None:
            return redirect(_library_return_url(view, smart))

        registry = normalize_quiz_folders(loaded_registry)

        for q in registry:
            if q.get("id") == quiz_id:
                q["folder"] = target_folder
                break

        save_registry(registry)

    return redirect(_library_return_url(view, smart))

def add_quiz_folder(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    build_folder_identity = dependencies.build_quiz_folder_identity
    get_quiz_folders = dependencies.get_quiz_folders
    save_quiz_folders = dependencies.save_quiz_folders

    folder = str(request.form.get("folder") or "").strip()
    view = request.form.get("view") or "visible"
    smart = request.form.get("smart")

    if not folder:
        return redirect(_library_return_url(view, smart))

    with registry_lock:
        folders = get_quiz_folders()
        identity = build_folder_identity(folders, load_registry())
        existing_display = identity.resolve(folder)

        if existing_display is None:
            folders.append(folder)
            save_quiz_folders(folders)
        elif not identity.is_configured(existing_display):
            # Choosing New Folder for an assignment-only legacy identity makes
            # it persistent without changing its established display spelling.
            folders.append(existing_display)
            save_quiz_folders(folders)

    return redirect(_library_return_url(view, smart))

def set_quiz_folder_hidden(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    build_folder_identity = dependencies.build_quiz_folder_identity
    get_quiz_folders = dependencies.get_quiz_folders
    get_hidden_quiz_folders = dependencies.get_hidden_quiz_folders
    save_quiz_folder_state = dependencies.save_quiz_folder_state

    requested_folder = str(request.form.get("folder") or "").strip()
    requested_state = request.form.get("hidden")
    view = request.form.get("view") or "visible"
    smart = request.form.get("smart")

    if (
        not requested_folder
        or requested_state not in {"0", "1"}
    ):
        return redirect(_library_return_url(view, smart))
    hide_folder = requested_state == "1"

    with registry_lock:
        folders = get_quiz_folders()
        identity = build_folder_identity(folders, load_registry())
        configured_name = identity.resolve(requested_folder)
        if (
            configured_name is None
            or identity.is_uncategorized(configured_name)
        ):
            return redirect(_library_return_url(view, smart))

        # A legacy assignment-only folder becomes explicitly persistent only
        # when the user chooses to hide it. Page loads never promote legacy
        # folders.
        if not identity.is_configured(configured_name):
            if hide_folder:
                folders.append(configured_name)
            else:
                return redirect(_library_return_url(view, smart))

        hidden_folders = get_hidden_quiz_folders(folders)
        hidden_folders = [
            folder
            for folder in hidden_folders
            if identity.resolve(folder) != configured_name
        ]
        if hide_folder:
            hidden_folders.append(configured_name)

        save_quiz_folder_state(folders, hidden_folders)
    return redirect(_library_return_url(view, smart))

def rename_quiz_folder(dependencies):
    rename_folder_metadata = dependencies.rename_quiz_folder_metadata

    old_folder = str(request.form.get("old_folder") or "").strip()
    new_folder = str(request.form.get("new_folder") or "").strip()
    view = request.form.get("view") or "visible"
    smart = request.form.get("smart")

    if not old_folder or not new_folder:
        return redirect(_library_return_url(view, smart))

    rename_folder_metadata(old_folder, new_folder)

    return redirect(_library_return_url(view, smart))

def delete_quiz_folder(dependencies):
    delete_folder_metadata = dependencies.delete_quiz_folder_metadata

    folder = str(request.form.get("folder") or "").strip()
    view = request.form.get("view") or "visible"
    smart = request.form.get("smart")

    if not folder:
        return redirect(_library_return_url(view, smart))

    delete_folder_metadata(folder)

    return redirect(_library_return_url(view, smart))

def save_folder_order(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    build_folder_identity = dependencies.build_quiz_folder_identity
    get_quiz_folders = dependencies.get_quiz_folders
    save_quiz_folders = dependencies.save_quiz_folders
    get_hidden_quiz_folders = dependencies.get_hidden_quiz_folders

    data = request.get_json() or {}
    ordered_folders = data.get("folders", [])
    view = str(data.get("view") or "").strip().lower()

    if not isinstance(ordered_folders, list):
        return jsonify(status="error", error="Invalid folder order"), 400

    with registry_lock:
        current_folders = get_quiz_folders()
        identity = build_folder_identity(
            current_folders, load_registry()
        )

        # Resolve only known identities and keep their stored display spelling.
        cleaned_order = []
        seen = set()

        for folder in ordered_folders:
            if not str(folder or "").strip():
                continue
            name = identity.resolve(folder)
            if name is None:
                continue

            key = identity.key(name)

            if key in seen:
                continue

            cleaned_order.append(name)
            seen.add(key)

        hidden_keys = {
            identity.key(folder)
            for folder in get_hidden_quiz_folders(current_folders)
        }

        if view == "visible" and hidden_keys:
            # Visible omits hidden folders. Reorder only submitted folder slots
            # so every omitted hidden folder retains its saved position.
            current_keys = {
                identity.key(folder) for folder in current_folders
            }
            submitted = [
                folder
                for folder in cleaned_order
                if identity.key(folder) in current_keys
                and identity.key(folder) not in hidden_keys
            ]
            submitted_keys = {
                identity.key(folder) for folder in submitted
            }
            submitted_iter = iter(submitted)
            merged_order = [
                next(submitted_iter)
                if identity.key(folder) in submitted_keys
                else folder
                for folder in current_folders
            ]
            merged_keys = {
                identity.key(folder) for folder in merged_order
            }
            merged_order.extend(
                folder
                for folder in cleaned_order
                if identity.key(folder) not in merged_keys
            )
            cleaned_order = merged_order
        else:
            # Preserve the established behavior when the page submits its
            # complete normal folder ordering.
            for folder in current_folders:
                if identity.key(folder) not in seen:
                    cleaned_order.append(folder)

        save_quiz_folders(cleaned_order)

    return jsonify(status="ok")

def save_quiz_order_in_folder(dependencies):
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    save_registry = dependencies.save_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    build_folder_identity = dependencies.build_quiz_folder_identity
    get_quiz_folders = dependencies.get_quiz_folders

    data = request.get_json() or {}

    folder = str(data.get("folder") or "").strip()
    ordered_html = data.get("order", [])

    if not folder:
        folder = "Uncategorized"

    if not isinstance(ordered_html, list):
        return jsonify(status="error", error="Invalid quiz order"), 400

    with registry_lock:
        loaded_registry = load_registry()
        identity = build_folder_identity(
            get_quiz_folders(), loaded_registry
        )
        folder_display = identity.resolve(folder)
        if folder_display is None:
            return jsonify(status="error", error="Unknown quiz folder"), 400
        folder_identity = identity.key(folder_display)
        registry = normalize_quiz_folders(loaded_registry)

        # Quizzes currently in this folder
        folder_quizzes = [
            q for q in registry
            if identity.key(q.get("folder")) == folder_identity
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
            if identity.key(q.get("folder")) == folder_identity:
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
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    get_db = dependencies.get_db

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    with registry_lock:
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
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    get_db = dependencies.get_db

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    with registry_lock:
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
    lines.append("# Import compatibility: Classic choice-question text only")
    lines.append("# Use a Portable Quiz Bundle to preserve matching, images, and hotspots")
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
    registry_lock = dependencies.registry_lock()
    load_registry = dependencies.load_registry
    normalize_quiz_folders = dependencies.normalize_quiz_folders
    build_folder_identity = dependencies.build_quiz_folder_identity
    get_quiz_folders = dependencies.get_quiz_folders
    get_hidden_quiz_folders = dependencies.get_hidden_quiz_folders
    get_portal_title = dependencies.get_portal_title
    resolve_logo_filename = dependencies.resolve_logo_filename
    dprint = dependencies.debug_print

    with registry_lock:
        registry = normalize_quiz_folders(load_registry())
        configured_folders = get_quiz_folders()
        identity = build_folder_identity(configured_folders, registry)
        hidden_folder_names = get_hidden_quiz_folders(configured_folders)

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
    smart = normalize_smart_view(request.args.get("smart"))

    if not view and request.args.get("show_hidden") == "1":
        view = "all"

    folder_names = list(identity.folders)
    virtual_generated_practice_client_key = "__dlms_generated_practice__"
    while identity.resolve(virtual_generated_practice_client_key) is not None:
        virtual_generated_practice_client_key = (
            "_" + virtual_generated_practice_client_key
        )
    configured_folder_keys = identity.configured_keys
    hidden_folder_keys = {
        identity.key(folder) for folder in hidden_folder_names
    }

    def quiz_folder_name(quiz):
        return identity.resolve(quiz.get("folder")) or "Uncategorized"

    def quiz_folder_is_hidden(quiz):
        return identity.key(quiz_folder_name(quiz)) in hidden_folder_keys

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

    # Smart views are read-only overlays on the existing Visible/Hidden/All
    # scope. Their evidence comes from canonical services and storage; the
    # Unfinished view is completed in the browser because recoverable quiz
    # state intentionally lives in browser-local storage.
    conn = dependencies.get_db()
    try:
        smart_view_data = dependencies.quiz_smart_views(conn.cursor(), registry)
    finally:
        conn.close()
    smart_matches = smart_view_data["matches"]
    generation_presentations = smart_view_data.get("generation", {})
    source_provenance = smart_view_data.get("provenance", {})
    active_smart_view = next(
        (
            item
            for item in smart_view_data["views"]
            if item["key"] == smart
        ),
        None,
    )
    base_normal_filtered = list(normal_filtered)
    base_normal_ids = {
        int(q["id"])
        for q in base_normal_filtered
        if isinstance(q.get("id"), int) and not isinstance(q.get("id"), bool)
    }
    smart_views = []
    for item in smart_view_data["views"]:
        count = None if item["client_derived"] else len(
            base_normal_ids.intersection(smart_matches[item["key"]])
        )
        smart_views.append({**item, "count": count})
    if active_smart_view and not active_smart_view["client_derived"]:
        allowed_ids = set(smart_matches[smart])
        normal_filtered = [q for q in normal_filtered if q.get("id") in allowed_ids]
        render_filtered = [q for q in render_filtered if q.get("id") in allowed_ids]
    elif active_smart_view:
        # Hidden-folder search-only markup is a normal-library convenience. It
        # must not leak outside the selected base scope in a dynamic view.
        render_filtered = list(normal_filtered)

    def quiz_group_name(quiz):
        folder = quiz_folder_name(quiz)
        presentation = generation_presentations.get(quiz.get("id"))
        if (
            not active_smart_view
            and identity.is_uncategorized(folder)
            and presentation
            and presentation.get("category") == "practice"
        ):
            return VIRTUAL_GENERATED_PRACTICE_GROUP
        return folder

    quizzes = [
        {
            **q,
            "folder": quiz_folder_name(q),
            "logo": resolve_logo_filename(q.get("logo")),
            "smart_match": (
                smart_matches.get(smart, {}).get(q.get("id"))
                if active_smart_view else None
            ),
            "generation": generation_presentations.get(q.get("id")),
            "source_provenance": source_provenance.get(q.get("id")),
        }
        for q in render_filtered
    ]
    normal_grouped_quizzes = {folder: [] for folder in folder_names}
    for q in normal_filtered:
        folder = quiz_group_name(q)
        if folder not in normal_grouped_quizzes:
            normal_grouped_quizzes[folder] = []
        normal_grouped_quizzes[folder].append(q)

    grouped_quizzes = {folder: [] for folder in folder_names}
    for q in quizzes:
        folder = quiz_group_name(q)
        if folder not in grouped_quizzes:
            grouped_quizzes[folder] = []
        grouped_quizzes[folder].append(q)

    group_names = list(folder_names)
    if normal_grouped_quizzes.get(VIRTUAL_GENERATED_PRACTICE_GROUP):
        uncategorized_index = next(
            (
                index
                for index, folder in enumerate(group_names)
                if identity.is_uncategorized(folder)
            ),
            len(group_names),
        )
        group_names.insert(
            uncategorized_index, VIRTUAL_GENERATED_PRACTICE_GROUP
        )

    # Persistent custom folders remain visible when empty in Visible and All.
    # Hidden shows only hidden folders or folders containing filtered hidden
    # quizzes. Assignment-only legacy folders retain their discovery behavior.
    def normal_group_is_displayed(folder):
        if folder == VIRTUAL_GENERATED_PRACTICE_GROUP:
            return bool(normal_grouped_quizzes.get(folder))
        if view == "visible" and identity.key(folder) in hidden_folder_keys:
            return False
        if normal_grouped_quizzes.get(folder):
            return True
        return bool(
            not active_smart_view
            and identity.key(folder) in configured_folder_keys
            and not identity.is_uncategorized(folder)
            and (
                view != "hidden"
                or identity.key(folder) in hidden_folder_keys
            )
        )

    normal_display_folder_names = [
        folder for folder in group_names
        if normal_group_is_displayed(folder)
    ]
    display_folder_names = [
        folder for folder in group_names
        if folder in normal_display_folder_names
        or (
            folder != VIRTUAL_GENERATED_PRACTICE_GROUP
            and
            not active_smart_view
            and view == "visible"
            and identity.key(folder) in hidden_folder_keys
            and grouped_quizzes.get(folder)
        )
    ]
    normal_display_folder_count = sum(
        1
        for folder in normal_display_folder_names
        if folder != VIRTUAL_GENERATED_PRACTICE_GROUP
    )
    collapsible_group_names = [
        virtual_generated_practice_client_key
        if folder == VIRTUAL_GENERATED_PRACTICE_GROUP else folder
        for folder in group_names
    ]

    visible_count = sum(
        1 for q in registry
        if not q.get("hidden", False) and not quiz_folder_is_hidden(q)
    )
    hidden_count = len(registry) - visible_count
    view_quiz_count = (
        None
        if active_smart_view and active_smart_view["client_derived"]
        else len(normal_filtered)
    )
    active_quiz_ids = [
        str(quiz.get("id"))
        for quiz in registry
        if quiz.get("id") is not None
    ]

    return render_template("quiz/library.html", quizzes=quizzes, grouped_quizzes=grouped_quizzes, folder_names=folder_names,
       display_folder_names=display_folder_names,
       normal_display_folder_names=normal_display_folder_names,
       normal_display_folder_count=normal_display_folder_count,
       hidden_folder_keys=hidden_folder_keys, portal_title=portal_title,
       visible_count=visible_count, hidden_count=hidden_count,
       view_quiz_count=view_quiz_count, view=view, app_version=APP_VERSION,
       active_quiz_ids=active_quiz_ids,
       virtual_generated_practice_group=VIRTUAL_GENERATED_PRACTICE_GROUP,
       virtual_generated_practice_client_key=virtual_generated_practice_client_key,
       collapsible_group_names=collapsible_group_names,
       smart=smart, smart_views=smart_views,
       active_smart_view=active_smart_view,
       smart_eligible_quiz_ids=sorted(base_normal_ids))


def _mixed_quiz_page_context(dependencies, *, error=None, selected_ids=(), title=""):
    with dependencies.registry_lock():
        registry = dependencies.normalize_quiz_folders(dependencies.load_registry())
    conn = dependencies.get_db()
    try:
        catalog = dependencies.mixed_quiz_catalog(conn.cursor(), registry)
    finally:
        conn.close()
    return {
        "app_version": dependencies.app_version(),
        "portal_title": dependencies.get_portal_title(),
        "catalog": catalog,
        "filter_options": dependencies.mixed_quiz_filter_options(catalog),
        "selected_ids": {int(value) for value in selected_ids},
        "quiz_title": title,
        "error": error,
    }


def mixed_quiz_builder(dependencies):
    return render_template(
        "quiz/mixed-builder.html", **_mixed_quiz_page_context(dependencies)
    )


def quiz_duplicate_report(dependencies):
    """Render a read-only comparison of ordinary source questions."""
    with dependencies.registry_lock():
        registry = dependencies.normalize_quiz_folders(
            dependencies.load_registry()
        )
    conn = dependencies.get_db()
    try:
        report = dependencies.quiz_duplicate_report(conn.cursor(), registry)
    finally:
        conn.close()
    return render_template(
        "quiz/duplicates.html",
        app_version=dependencies.app_version(),
        portal_title=dependencies.get_portal_title(),
        report=report,
    )


def create_mixed_quiz(dependencies):
    title = re.sub(r"\s+", " ", str(request.form.get("title") or "")).strip()
    selected_ids = []
    invalid_selection = False
    for raw_id in request.form.getlist("question_ids"):
        try:
            question_id = int(raw_id)
        except (TypeError, ValueError):
            question_id = 0
        if question_id <= 0:
            invalid_selection = True
        elif question_id not in selected_ids:
            selected_ids.append(question_id)

    context = _mixed_quiz_page_context(
        dependencies, selected_ids=selected_ids, title=title
    )
    allowed = {item["question_id"]: item for item in context["catalog"]}
    error = None
    if not title:
        error = "Enter a name for the mixed quiz."
    elif len(title) > 200:
        error = "Quiz names must be 200 characters or fewer."
    elif len(selected_ids) < 2:
        error = "Select at least two questions."
    elif invalid_selection or any(
        question_id not in allowed for question_id in selected_ids
    ):
        error = "One or more selected questions are no longer available. Review the selection and try again."
    else:
        source_quiz_ids = {
            quiz_id
            for question_id in selected_ids
            for quiz_id in allowed[question_id]["source_quiz_ids"]
        }
        if len(source_quiz_ids) < 2:
            error = "Select questions from at least two source quizzes."

    if error:
        context["error"] = error
        return render_template("quiz/mixed-builder.html", **context), 400

    conn = dependencies.get_db()
    try:
        cur = conn.cursor()
        questions = []
        for ordinal, question_id in enumerate(selected_ids, start=1):
            payload = dependencies.question_payload_from_db(cur, question_id)
            if payload is None:
                context["error"] = "A selected question is no longer available. Review the selection and try again."
                return render_template("quiz/mixed-builder.html", **context), 400
            payload["number"] = ordinal
            # Exact duplicates can carry concept links from more than one
            # original bank; retain that canonical union in the new quiz.
            payload["concepts"] = list(allowed[question_id]["concepts"])
            payload["composition_sources"] = [
                dict(source) for source in allowed[question_id]["sources"]
            ]
            questions.append(payload)
    finally:
        conn.close()

    _quiz_id, html_name = dependencies.publish_quiz(
        title,
        questions,
        filename_prefix="mixed_quiz",
        generation_kind="mixed_quiz",
        exam_minutes=90,
        snapshot_existing_assets=True,
    )
    return redirect(f"/quizzes/{html_name}")

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
        ("/library/duplicates", "quiz_duplicate_report", quiz_duplicate_report, ["GET"]),
        ("/quiz-composer", "mixed_quiz_builder", mixed_quiz_builder, ["GET"]),
        ("/quiz-composer/create", "create_mixed_quiz", create_mixed_quiz, ["POST"]),
    )
    for rule, endpoint, view_func, methods in routes:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
