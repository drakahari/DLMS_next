"""Atomic edit and deletion coordination for existing quizzes."""

from copy import deepcopy
import os
import shutil
import tempfile


class FolderMetadataCoordinationError(RuntimeError):
    """Base error for an incomplete coordinated folder metadata mutation."""


class FolderMetadataStateConflictError(FolderMetadataCoordinationError):
    """The durable registry is neither the expected old nor target state."""


class FolderMetadataStateUnknownError(FolderMetadataCoordinationError):
    """The durable registry could not be inspected after a failed write."""


class FolderMetadataRollbackIncompleteError(FolderMetadataCoordinationError):
    """Portal compensation failed or could not be validated."""


def _normalized_quiz_folder_registry(registry):
    """Return a detached registry snapshot with legacy folder defaults applied."""
    normalized = deepcopy(registry)
    for quiz in normalized:
        if not str(quiz.get("folder") or "").strip():
            quiz["folder"] = "Uncategorized"
    return normalized


def _restore_quiz_folder_metadata(
    folders,
    hidden_folders,
    *,
    save_quiz_folder_state,
    get_quiz_folders,
    get_hidden_quiz_folders,
):
    """Restore and validate only portal fields owned by the Quiz Library."""
    save_quiz_folder_state(folders, hidden_folders)
    restored_folders = get_quiz_folders()
    restored_hidden = get_hidden_quiz_folders(restored_folders)
    if restored_folders != folders or restored_hidden != hidden_folders:
        raise RuntimeError("Restored Quiz Library folder metadata did not validate")


def _persist_quiz_folder_metadata(
    *,
    original_folders,
    original_hidden_folders,
    target_folders,
    target_hidden_folders,
    original_registry,
    target_registry,
    load_registry,
    save_registry,
    get_quiz_folders,
    get_hidden_quiz_folders,
    save_quiz_folder_state,
    print_message=print,
):
    """Publish portal then registry state, compensating only a known-safe failure."""
    save_quiz_folder_state(target_folders, target_hidden_folders)
    try:
        save_registry(target_registry)
    except Exception as registry_error:
        try:
            durable_registry = _normalized_quiz_folder_registry(load_registry())
        except Exception as state_error:
            print_message(
                "[FOLDER METADATA ERROR] Registry write failed and durable "
                f"state could not be determined: {state_error}"
            )
            raise FolderMetadataStateUnknownError(
                "Quiz folder metadata update failed; durable registry state "
                "could not be determined and portal metadata was not rolled back"
            ) from registry_error

        # When a folder operation does not change any quiz assignment, the old
        # and target registries are equal. A reported registry failure therefore
        # cannot prove publication, so restore the portal snapshot.
        registry_is_original = durable_registry == original_registry
        registry_is_target = durable_registry == target_registry
        if registry_is_original:
            try:
                _restore_quiz_folder_metadata(
                    original_folders,
                    original_hidden_folders,
                    save_quiz_folder_state=save_quiz_folder_state,
                    get_quiz_folders=get_quiz_folders,
                    get_hidden_quiz_folders=get_hidden_quiz_folders,
                )
            except Exception as rollback_error:
                print_message(
                    "[FOLDER METADATA ERROR] Registry write failed and portal "
                    f"compensation was incomplete: {rollback_error}"
                )
                raise FolderMetadataRollbackIncompleteError(
                    "Quiz folder metadata update failed and portal rollback "
                    "could not be completed"
                ) from rollback_error
            raise

        if registry_is_target:
            # os.replace may have completed before a persistence adapter reports
            # failure. Keeping the target portal state avoids undoing a durable
            # target registry and preserves cross-file consistency.
            raise

        print_message(
            "[FOLDER METADATA ERROR] Registry write failed and durable state "
            "does not match the original or intended registry; portal metadata "
            "was not overwritten"
        )
        raise FolderMetadataStateConflictError(
            "Quiz folder metadata update failed with an unexpected durable "
            "registry state; portal metadata was not rolled back"
        ) from registry_error


def rename_quiz_folder_metadata(
    old_folder,
    new_folder,
    *,
    registry_lock,
    load_registry,
    save_registry,
    get_quiz_folders,
    get_hidden_quiz_folders,
    save_quiz_folder_state,
    print_message=print,
):
    """Coordinate a case-insensitive folder rename across both JSON stores."""
    with registry_lock:
        original_registry = _normalized_quiz_folder_registry(load_registry())
        original_folders = list(get_quiz_folders())
        original_hidden_folders = list(
            get_hidden_quiz_folders(original_folders)
        )

        existing = {
            folder.lower()
            for folder in original_folders
            if folder.lower() != old_folder.lower()
        }
        if new_folder.lower() in existing:
            return False

        target_folders = [
            new_folder if folder.lower() == old_folder.lower() else folder
            for folder in original_folders
        ]
        target_hidden_folders = [
            new_folder if folder.lower() == old_folder.lower() else folder
            for folder in original_hidden_folders
        ]
        target_registry = deepcopy(original_registry)
        for quiz in target_registry:
            current_folder = str(
                quiz.get("folder") or "Uncategorized"
            ).strip()
            if current_folder.lower() == old_folder.lower():
                quiz["folder"] = new_folder

        _persist_quiz_folder_metadata(
            original_folders=original_folders,
            original_hidden_folders=original_hidden_folders,
            target_folders=target_folders,
            target_hidden_folders=target_hidden_folders,
            original_registry=original_registry,
            target_registry=target_registry,
            load_registry=load_registry,
            save_registry=save_registry,
            get_quiz_folders=get_quiz_folders,
            get_hidden_quiz_folders=get_hidden_quiz_folders,
            save_quiz_folder_state=save_quiz_folder_state,
            print_message=print_message,
        )
        return True


def delete_quiz_folder_metadata(
    folder,
    *,
    registry_lock,
    load_registry,
    save_registry,
    get_quiz_folders,
    get_hidden_quiz_folders,
    save_quiz_folder_state,
    print_message=print,
):
    """Coordinate a folder deletion and quiz reassignment across both stores."""
    with registry_lock:
        original_registry = _normalized_quiz_folder_registry(load_registry())
        original_folders = list(get_quiz_folders())
        original_hidden_folders = list(
            get_hidden_quiz_folders(original_folders)
        )

        target_folders = [
            configured_folder
            for configured_folder in original_folders
            if configured_folder.lower() != folder.lower()
        ]
        target_hidden_folders = [
            hidden_folder
            for hidden_folder in original_hidden_folders
            if hidden_folder.lower() != folder.lower()
        ]
        target_registry = deepcopy(original_registry)
        for quiz in target_registry:
            current_folder = str(
                quiz.get("folder") or "Uncategorized"
            ).strip()
            if current_folder.lower() == folder.lower():
                quiz["folder"] = "Uncategorized"

        _persist_quiz_folder_metadata(
            original_folders=original_folders,
            original_hidden_folders=original_hidden_folders,
            target_folders=target_folders,
            target_hidden_folders=target_hidden_folders,
            original_registry=original_registry,
            target_registry=target_registry,
            load_registry=load_registry,
            save_registry=save_registry,
            get_quiz_folders=get_quiz_folders,
            get_hidden_quiz_folders=get_hidden_quiz_folders,
            save_quiz_folder_state=save_quiz_folder_state,
            print_message=print_message,
        )


def commit_quiz_mutation(conn):
    """Commit boundary kept separate for deterministic mutation fault tests."""
    conn.commit()


def stage_quiz_mutation_artifacts(
    conn,
    quiz_id,
    quiz_entry,
    *,
    staging_root,
    quiz_artifact_names,
    rebuild_quiz_json,
    rebuild_quiz_html,
    data_folder,
    quiz_folder,
    makedirs=os.makedirs,
    make_temp_dir=tempfile.mkdtemp,
    join_path=os.path.join,
    remove_tree=shutil.rmtree,
):
    root = staging_root()
    makedirs(root, exist_ok=True)
    staging_dir = make_temp_dir(prefix="mutation_", dir=root)
    html_name, json_name = quiz_artifact_names(quiz_entry)
    staged_json = join_path(staging_dir, json_name)
    staged_html = join_path(staging_dir, html_name)
    try:
        if not rebuild_quiz_json(
            quiz_id, conn=conn, quiz_entry=quiz_entry, output_path=staged_json
        ):
            raise RuntimeError("Quiz JSON staging failed")
        if not rebuild_quiz_html(
            quiz_id, quiz_entry=quiz_entry, output_path=staged_html
        ):
            raise RuntimeError("Quiz HTML staging failed")
        return {
            "staging_dir": staging_dir,
            "files": [
                (staged_json, join_path(data_folder, json_name)),
                (staged_html, join_path(quiz_folder, html_name)),
            ],
        }
    except Exception:
        remove_tree(staging_dir, ignore_errors=True)
        raise


def promote_quiz_mutation_artifacts(
    staged,
    *,
    restore_artifacts,
    makedirs=os.makedirs,
    dirname=os.path.dirname,
    join_path=os.path.join,
    basename=os.path.basename,
    isfile=os.path.isfile,
    copy_file=shutil.copy2,
    replace_file=os.replace,
):
    """Replace live edit artifacts atomically while retaining exact rollback copies."""
    promoted = []
    try:
        for index, (staged_path, final_path) in enumerate(staged["files"]):
            makedirs(dirname(final_path), exist_ok=True)
            backup_path = join_path(
                staged["staging_dir"], f"previous_{index}_{basename(final_path)}"
            )
            existed = isfile(final_path)
            if existed:
                copy_file(final_path, backup_path)
            replace_file(staged_path, final_path)
            promoted.append((final_path, backup_path, existed))
        return promoted
    except Exception:
        restore_artifacts(promoted)
        raise


def restore_quiz_mutation_artifacts(
    promoted,
    *,
    isfile=os.path.isfile,
    replace_file=os.replace,
    lexists=os.path.lexists,
    islink=os.path.islink,
    remove_file=os.remove,
):
    errors = []
    for final_path, backup_path, existed in reversed(promoted):
        try:
            if existed and isfile(backup_path):
                replace_file(backup_path, final_path)
            elif not existed and lexists(final_path) and not islink(final_path):
                remove_file(final_path)
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise RuntimeError("Quiz artifact rollback could not be completed") from errors[0]


def remove_new_quiz_logo(
    filename,
    original_registry,
    *,
    logo_folder,
    join_path=os.path.join,
    basename=os.path.basename,
    isfile=os.path.isfile,
    islink=os.path.islink,
    remove_file=os.remove,
):
    if not filename or any(entry.get("logo") == filename for entry in original_registry):
        return
    path = join_path(logo_folder, filename)
    if basename(path) == filename and isfile(path) and not islink(path):
        remove_file(path)


def finish_quiz_mutation(
    conn,
    quiz_id,
    registry_updates=None,
    new_logo_filename=None,
    *,
    registry_lock,
    load_registry,
    save_registry,
    quiz_registry_entry,
    stage_artifacts,
    promote_artifacts,
    commit_mutation,
    restore_artifacts,
    remove_new_logo,
    remove_tree=shutil.rmtree,
):
    """Publish one existing-quiz mutation or compensate every handled failure."""
    staged = None
    promoted = []
    original_registry = None
    registry_attempted = False
    try:
        with registry_lock:
            original_registry = load_registry()
            updated_registry = [dict(entry) for entry in original_registry]
            quiz_entry = quiz_registry_entry(updated_registry, quiz_id)
            if not quiz_entry:
                raise RuntimeError("Quiz registry entry is missing")
            if registry_updates:
                quiz_entry.update(registry_updates)

            staged = stage_artifacts(conn, quiz_id, quiz_entry)
            promoted = promote_artifacts(staged)
            registry_attempted = True
            save_registry(updated_registry)
            commit_mutation(conn)
    except Exception:
        conn.rollback()
        rollback_errors = []
        if original_registry is not None and registry_attempted:
            try:
                save_registry(original_registry)
            except Exception as exc:
                rollback_errors.append(exc)
        try:
            restore_artifacts(promoted)
        except Exception as exc:
            rollback_errors.append(exc)
        try:
            remove_new_logo(new_logo_filename, original_registry or [])
        except Exception as exc:
            rollback_errors.append(exc)
        if rollback_errors:
            raise RuntimeError("Quiz edit failed and rollback was incomplete") from rollback_errors[0]
        raise
    finally:
        if staged:
            remove_tree(staged["staging_dir"], ignore_errors=True)


def quiz_owns_question(cur, quiz_id, question_id):
    return cur.execute(
        "SELECT 1 FROM questions WHERE id = ? AND quiz_id = ?",
        (question_id, quiz_id),
    ).fetchone() is not None


def quiz_owns_choice(cur, quiz_id, choice_id):
    return cur.execute(
        """
        SELECT 1 FROM choices c
        JOIN questions q ON q.id = c.question_id
        WHERE c.id = ? AND q.quiz_id = ?
        """,
        (choice_id, quiz_id),
    ).fetchone() is not None


def quiz_owns_matching_pair(cur, quiz_id, pair_id):
    return cur.execute(
        """
        SELECT 1 FROM matching_pairs mp
        JOIN questions q ON q.id = mp.question_id
        WHERE mp.id = ? AND q.quiz_id = ?
        """,
        (pair_id, quiz_id),
    ).fetchone() is not None


def quiz_edit_validation(
    cur,
    quiz_id,
    *,
    matching_record_validation_errors,
    matching_case_only_term_warnings,
):
    errors = []
    warnings = []
    questions = cur.execute(
        """
        SELECT id, question_number, COALESCE(question_type, 'choice') AS question_type
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number
        """,
        (quiz_id,),
    ).fetchall()
    for question in questions:
        if question["question_type"] == "matching":
            pair_rows = cur.execute(
                "SELECT id, left_text, right_text FROM matching_pairs WHERE question_id = ?",
                (question["id"],),
            ).fetchall()
            records = [
                {"id": row["id"], "left": row["left_text"], "right": row["right_text"]}
                for row in pair_rows
            ]
            errors.extend(
                matching_record_validation_errors(
                    records,
                    context=(
                        f"quiz {quiz_id}, matching question "
                        f"{question['question_number']}"
                    ),
                    left_key="left",
                    right_key="right",
                    record_name="pair",
                )
            )
            warnings.extend(
                matching_case_only_term_warnings(
                    records,
                    context=(
                        f"quiz {quiz_id}, matching question "
                        f"{question['question_number']}"
                    ),
                    left_key="left",
                    record_name="pair",
                )
            )
            continue

        correct_count = cur.execute(
            "SELECT COUNT(*) FROM choices WHERE question_id = ? AND is_correct = 1",
            (question["id"],),
        ).fetchone()[0]
        if correct_count == 0:
            errors.append(
                f"Question {question['question_number']} must have at least one correct answer."
            )
    return errors, warnings


def publish_quiz_edit_request(
    conn,
    quiz_id,
    *,
    title,
    exam_minutes,
    logo_file,
    timestamp,
    flask_app,
    finalize_logo,
    finish_mutation,
    remove_new_logo,
    load_registry,
):
    logo_filename = finalize_logo(flask_app, timestamp, logo_file=logo_file)
    updates = {"exam_minutes": exam_minutes}
    if title:
        updates["title"] = title
        if logo_filename:
            updates["logo"] = logo_filename
    try:
        finish_mutation(
            conn,
            quiz_id,
            registry_updates=updates,
            new_logo_filename=logo_filename,
        )
    except Exception:
        # A logo can be finalized before staging begins; remove only this new,
        # request-owned file if the shared mutation helper did not reach cleanup.
        try:
            remove_new_logo(logo_filename, load_registry())
        except Exception:
            pass
        raise


def commit_quiz_deletion(conn):
    """Commit boundary kept separate for deterministic deletion fault tests."""
    conn.commit()


def cleanup_deleted_quiz_artifacts(
    quiz_entry,
    remaining_registry,
    *,
    quiz_artifact_names,
    quiz_folder,
    data_folder,
    quiz_asset_folder,
    logo_folder,
    join_path=os.path.join,
    splitext=os.path.splitext,
    basename=os.path.basename,
    isfile=os.path.isfile,
    isdir=os.path.isdir,
    islink=os.path.islink,
    remove_file=os.remove,
    remove_tree=shutil.rmtree,
    print_message=print,
):
    """Best-effort cleanup after the DB and registry no longer expose a quiz."""
    if not quiz_entry:
        return
    try:
        html_name, json_name = quiz_artifact_names(quiz_entry)
        targets = [
            join_path(quiz_folder, html_name),
            join_path(data_folder, json_name),
        ]
        for target in targets:
            if isfile(target) and not islink(target):
                try:
                    remove_file(target)
                except Exception as exc:
                    print_message(
                        f"[DELETE CLEANUP ERROR] Could not remove {target}: {exc}"
                    )

        asset_dir = join_path(quiz_asset_folder, splitext(html_name)[0])
        if isdir(asset_dir) and not islink(asset_dir):
            try:
                remove_tree(asset_dir)
            except Exception as exc:
                print_message(
                    f"[DELETE CLEANUP ERROR] Could not remove {asset_dir}: {exc}"
                )
    except Exception as exc:
        print_message(f"[DELETE CLEANUP ERROR] Invalid recorded quiz artifacts: {exc}")

    logo_name = str(quiz_entry.get("logo") or "")
    logo_is_shared = any(entry.get("logo") == logo_name for entry in remaining_registry)
    if logo_name and not logo_is_shared and logo_name == basename(logo_name):
        logo_path = join_path(logo_folder, logo_name)
        if isfile(logo_path) and not islink(logo_path):
            try:
                remove_file(logo_path)
            except Exception as exc:
                print_message(
                    f"[DELETE CLEANUP ERROR] Could not remove {logo_path}: {exc}"
                )


def delete_quiz_transaction(
    quiz_id,
    *,
    get_db,
    registry_lock,
    load_registry,
    save_registry,
    commit_deletion,
    print_message=print,
):
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = ON")
    deleted_entry = None
    kept = []
    try:
        with registry_lock:
            original_registry = load_registry()
            for entry in original_registry:
                if str(entry.get("id")) == str(quiz_id):
                    deleted_entry = entry
                    print_message("[DELETE] Removing registry entry:", entry)
                else:
                    kept.append(entry)

            conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
            registry_published = False
            try:
                save_registry(kept)
                registry_published = True
                commit_deletion(conn)
            except Exception:
                conn.rollback()
                if registry_published:
                    save_registry(original_registry)
                raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return deleted_entry, kept
