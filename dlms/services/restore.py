"""Restore, crash recovery, reset, and runtime-data removal services."""

import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path


class RestoreFutureSchemaError(ValueError):
    """Stable restore-facing error for a backup created by newer DLMS code."""


class DataRootOwnershipError(RuntimeError):
    """Raised when a destructive operation does not target owned DLMS data."""


def staged_restore_database_path(staged_data_root, *, is_same_path_or_ancestor):
    """Return the exact staged results.db after enforcing restore-root containment."""
    root = os.path.abspath(staged_data_root)
    real_root = os.path.realpath(root)
    if os.path.islink(root) or not os.path.isdir(real_root):
        raise ValueError("Backup staging data is missing or unsafe")
    database = os.path.join(root, "results.db")
    if os.path.islink(database) or not os.path.isfile(database):
        raise ValueError("Backup is missing a safe staged DLMS database results.db")
    real_database = os.path.realpath(database)
    if not is_same_path_or_ancestor(real_root, real_database):
        raise ValueError("Staged results.db escapes the validated restore root")
    return real_database


def validate_current_restored_database(
    database_path,
    *,
    validate_restored_sqlite,
    database_table_names,
    read_database_schema_version,
    validate_current_database_schema,
    schema_version,
    sqlite_module=sqlite3,
):
    """Read-only post-migration integrity, version, shape, and index validation."""
    sqlite_report = validate_restored_sqlite(database_path)
    try:
        uri = Path(os.path.abspath(database_path)).as_uri() + "?mode=ro"
        conn = sqlite_module.connect(uri, uri=True)
        conn.row_factory = sqlite_module.Row
    except sqlite_module.Error as exc:
        raise ValueError("Migrated results.db is not readable") from exc
    try:
        tables = database_table_names(conn)
        version = read_database_schema_version(conn, tables)
        if version != schema_version:
            raise ValueError(
                f"Migrated results.db schema version {version!r} is not {schema_version}"
            )
        validate_current_database_schema(conn)
    except (RuntimeError, sqlite_module.DatabaseError) as exc:
        raise ValueError("Migrated results.db failed current-schema validation") from exc
    finally:
        conn.close()
    return {"version": schema_version, "sqlite": sqlite_report}


def regenerate_staged_quiz_html(
    staged_data_root,
    database_path,
    *,
    validate_restored_json,
    quiz_artifact_names,
    build_quiz_html,
    is_same_path_or_ancestor,
    sqlite_module=sqlite3,
):
    """Replace restored quiz HTML with trusted application-generated artifacts."""
    staged_root = os.path.abspath(staged_data_root)
    real_root = os.path.realpath(staged_root)
    if os.path.islink(staged_root) or not os.path.isdir(real_root):
        raise ValueError("Backup staging data is missing or unsafe")

    registry_path = os.path.join(real_root, "config", "quizzes.json")
    if os.path.isfile(registry_path) and not os.path.islink(registry_path):
        registry = validate_restored_json(registry_path, "config/quizzes.json")
    elif os.path.lexists(registry_path):
        raise ValueError("config/quizzes.json is not a safe regular file")
    else:
        registry = []

    portal_title = "Training & Practice Center"
    portal_path = os.path.join(real_root, "config", "portal.json")
    if os.path.isfile(portal_path) and not os.path.islink(portal_path):
        portal = validate_restored_json(portal_path, "config/portal.json")
        portal_title = portal.get("title") or portal_title
    elif os.path.lexists(portal_path):
        raise ValueError("config/portal.json is not a safe regular file")

    database_real = os.path.realpath(database_path)
    if not is_same_path_or_ancestor(real_root, database_real):
        raise ValueError("Staged results.db escapes the validated restore root")
    conn = None
    try:
        uri = Path(database_real).as_uri() + "?mode=ro"
        conn = sqlite_module.connect(uri, uri=True)
        canonical_quizzes = {
            int(row[0]): str(row[1] or "")
            for row in conn.execute("SELECT id, title FROM quizzes").fetchall()
        }
    except sqlite_module.Error as exc:
        raise ValueError("Staged quiz metadata could not be read safely") from exc
    finally:
        if conn is not None:
            conn.close()

    generated_root = tempfile.mkdtemp(prefix=".restore-quiz-html-", dir=real_root)
    quiz_root = os.path.join(real_root, "quizzes")
    generated = 0
    skipped = 0
    try:
        for entry in registry:
            if not entry.get("html"):
                skipped += 1
                continue
            html_name, json_name = quiz_artifact_names(entry)
            raw_quiz_id = entry.get("id")
            canonical_quiz_id = None
            if not isinstance(raw_quiz_id, bool):
                try:
                    candidate_id = int(raw_quiz_id)
                    if candidate_id > 0:
                        canonical_quiz_id = candidate_id
                except (TypeError, ValueError):
                    pass
            canonical_title = canonical_quizzes.get(canonical_quiz_id)
            quiz_title = canonical_title or entry.get("title") or "Restored Quiz"
            output_path = os.path.join(generated_root, html_name)
            build_quiz_html(
                html_name, json_name, output_path, portal_title, quiz_title,
                entry.get("logo"), canonical_quiz_id, entry.get("exam_minutes", 90),
            )
            if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
                raise ValueError(f"Generated quiz HTML is empty or missing: {html_name}")
            generated += 1

        if os.path.lexists(quiz_root):
            if os.path.islink(quiz_root) or not os.path.isdir(quiz_root):
                raise ValueError("Restored quizzes path is not a safe directory")
            shutil.rmtree(quiz_root)
        os.replace(generated_root, quiz_root)
        generated_root = None
    finally:
        if generated_root and os.path.isdir(generated_root):
            shutil.rmtree(generated_root, ignore_errors=True)
    return {"generated": generated, "skipped": skipped}


def prepare_staged_restore_database(
    staged_data_root,
    *,
    staged_database_path,
    bootstrap_database,
    validate_current_restored_database,
    regenerate_staged_quiz_html,
    unsupported_schema_error,
    future_schema_error=RestoreFutureSchemaError,
    future_schema_public_error,
    print_message=print,
):
    """Migrate, validate, and prepare staged data before live-data mutation."""
    database_path = staged_database_path(staged_data_root)
    try:
        bootstrap_result = bootstrap_database(database_path)
        validation = validate_current_restored_database(database_path)
        quiz_html = regenerate_staged_quiz_html(staged_data_root, database_path)
    except unsupported_schema_error as exc:
        print_message(f"[RESTORE DATABASE VERSION ERROR] {exc}")
        raise future_schema_error(future_schema_public_error) from exc
    except Exception as exc:
        print_message(f"[RESTORE DATABASE MIGRATION ERROR] {type(exc).__name__}: {exc}")
        raise ValueError("The staged backup database could not be migrated and validated safely") from exc
    return {"path": database_path, "bootstrap": bootstrap_result, "validation": validation, "quiz_html": quiz_html}


def restore_staging_root_for_cleanup(
    *, restore_staging_folder, app_data_dir, canonical_data_root,
    is_same_path_or_ancestor,
):
    configured_root = os.path.abspath(restore_staging_folder)
    if os.path.lexists(configured_root) and os.path.islink(configured_root):
        raise ValueError("Restore staging root must not be a symlink")
    real_root = os.path.realpath(configured_root)
    if not is_same_path_or_ancestor(canonical_data_root(app_data_dir), real_root):
        raise ValueError("Restore staging root escapes the application-data directory")
    return real_root


def restore_stage_has_regular_file(stage_dir, filename):
    path = os.path.join(stage_dir, filename)
    return os.path.isfile(path) and not os.path.islink(path)


def restore_stage_has_validated_report(
    stage_dir, *, has_regular_file, backup_schema_version,
):
    if not (has_regular_file(stage_dir, "restore.zip") and has_regular_file(stage_dir, "report.json")):
        return False
    try:
        with open(os.path.join(stage_dir, "report.json"), "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    manifest = report.get("manifest") if isinstance(report, dict) else None
    return (
        isinstance(manifest, dict)
        and manifest.get("kind") == "dlms-portable-backup"
        and manifest.get("schema_version") == backup_schema_version
        and isinstance(report.get("file_count"), int)
        and not isinstance(report.get("file_count"), bool)
        and isinstance(report.get("uncompressed_bytes"), int)
        and not isinstance(report.get("uncompressed_bytes"), bool)
    )


def restore_stage_has_valid_marker(
    stage_dir, token, *, has_regular_file, state_filename, marker,
    staging_version, has_validated_report,
):
    if not has_regular_file(stage_dir, state_filename):
        return False
    try:
        with open(os.path.join(stage_dir, state_filename), "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(state, dict) and state.get("marker") == marker
        and state.get("schema_version") == staging_version
        and state.get("token") == token
        and isinstance(state.get("created_at"), str) and bool(state["created_at"])
        and has_validated_report(stage_dir)
    )


def is_owned_validated_restore_stage(
    stage_dir, token, *, staging_root_for_cleanup, has_valid_marker,
    has_validated_report,
):
    root = staging_root_for_cleanup()
    expected = os.path.join(root, token)
    if os.path.normcase(os.path.abspath(stage_dir)) != os.path.normcase(expected):
        return False
    if not os.path.isdir(stage_dir) or os.path.islink(stage_dir):
        return False
    return has_valid_marker(stage_dir, token) or has_validated_report(stage_dir)


def restore_operation_state_exists(*, operation_root):
    root = operation_root()
    if not os.path.lexists(root):
        return False
    if os.path.islink(root) or not os.path.isdir(root):
        return True
    try:
        return bool(os.listdir(root))
    except OSError:
        return True


def cancel_validated_restore_stage(
    token, *, restore_staging_dir, staging_root_for_cleanup,
    operation_state_exists, is_owned_stage,
):
    stage_dir = restore_staging_dir(token)
    root = staging_root_for_cleanup()
    stage_dir = os.path.join(root, token)
    if not os.path.lexists(stage_dir):
        return "missing"
    if operation_state_exists():
        return "recovery"
    if not is_owned_stage(stage_dir, token):
        return "unrecognized"
    shutil.rmtree(stage_dir)
    return "removed"


def cleanup_stale_restore_staging(
    *, now=None, staging_root_for_cleanup, operation_state_exists,
    is_owned_stage, cancel_stage, token_pattern, stale_seconds,
    max_cleanup_entries, print_message=print,
):
    report = {"removed": 0, "preserved": 0, "recovery": 0, "failed": 0}
    try:
        root = staging_root_for_cleanup()
        if not os.path.lexists(root):
            return report
        if not os.path.isdir(root):
            raise ValueError("Restore staging root is not a directory")
        if operation_state_exists():
            report["recovery"] = 1
            return report
        cutoff = (time.time() if now is None else float(now)) - stale_seconds
        names = sorted(os.listdir(root))[:max_cleanup_entries]
    except Exception as exc:
        print_message("[RESTORE STAGING CLEANUP ERROR] Could not inspect restore staging: " f"{type(exc).__name__}: {exc}")
        report["failed"] += 1
        return report
    for name in names:
        if not token_pattern.fullmatch(name):
            report["preserved"] += 1
            continue
        stage_dir = os.path.join(root, name)
        try:
            if not is_owned_stage(stage_dir, name) or os.path.getmtime(stage_dir) >= cutoff:
                report["preserved"] += 1
                continue
            if cancel_stage(name) == "removed":
                report["removed"] += 1
            else:
                report["preserved"] += 1
        except Exception as exc:
            print_message(f"[RESTORE STAGING CLEANUP ERROR] {name}: {type(exc).__name__}: {exc}")
            report["failed"] += 1
    return report


def validated_staged_restore_roots(
    staged_data_root, *, safe_name, data_root_marker, excluded_top_level,
):
    staged_root = os.path.abspath(staged_data_root)
    real_staged_root = os.path.realpath(staged_root)
    if os.path.islink(staged_root) or not os.path.isdir(real_staged_root):
        raise ValueError("Backup staging data is missing or unsafe")
    roots = {}
    for root_name in sorted(os.listdir(real_staged_root), key=str.casefold):
        name = safe_name(root_name, label="restored root")
        if name.casefold() in {data_root_marker.casefold(), ".secret_key"}:
            raise ValueError(f"Restore contains protected root: {name}")
        if name.casefold() in excluded_top_level:
            raise ValueError(f"Restore contains protected root: {name}")
        key = name.casefold()
        if key in roots:
            raise ValueError("Restore contains case-colliding top-level roots")
        source = os.path.join(real_staged_root, name)
        if os.path.islink(source) or not (os.path.isfile(source) or os.path.isdir(source)):
            raise ValueError(f"Restored root is not a safe file or directory: {name}")
        roots[key] = name
    return real_staged_root, roots


def remove_live_restore_root(
    root_name, *, safe_name, data_root_marker, excluded_top_level,
    app_data_dir,
):
    name = safe_name(root_name, label="live restore root")
    if name.casefold() in {data_root_marker.casefold(), ".secret_key"}:
        raise ValueError(f"Live restore root is protected: {name}")
    if name.casefold() in excluded_top_level:
        raise ValueError(f"Live restore root is protected: {name}")
    target = os.path.join(os.path.abspath(app_data_dir), name)
    if os.path.isdir(target) and not os.path.islink(target):
        shutil.rmtree(target)
    elif os.path.lexists(target):
        os.remove(target)


def apply_restored_data(
    staged_data_root, *, require_owned_root, validated_roots,
    canonical_data_root, app_data_dir, db_path, rel_is_excluded,
    remove_live_root, ensure_runtime_data_dirs, ensure_db_initialized,
):
    require_owned_root("restore DLMS backup data")
    real_staged_root, staged_roots = validated_roots(staged_data_root)
    live_root = canonical_data_root(app_data_dir)
    staged_relative = os.path.relpath(real_staged_root, live_root)
    staged_container = None
    if staged_relative != os.pardir and not staged_relative.startswith(os.pardir + os.sep):
        staged_container = staged_relative.split(os.sep, 1)[0].casefold()
    if "results.db" in staged_roots:
        for sidecar in (db_path + "-wal", db_path + "-shm", db_path + "-journal"):
            if os.path.lexists(sidecar):
                os.remove(sidecar)
    for live_name in sorted(os.listdir(app_data_dir), key=str.casefold):
        if rel_is_excluded(live_name) or live_name.casefold() == staged_container:
            continue
        staged_name = staged_roots.get(live_name.casefold())
        if staged_name != live_name:
            remove_live_root(live_name)
    for root_name in staged_roots.values():
        src = os.path.join(real_staged_root, root_name)
        dst = os.path.join(app_data_dir, root_name)
        remove_live_root(root_name)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    ensure_runtime_data_dirs()
    ensure_db_initialized()


def restore_operation_root(app_data_dir):
    return os.path.join(app_data_dir, ".restore_operations")


def restore_operation_checkpoint(_stage, _journal):
    return None


def write_restore_operation_journal(path, journal, *, fsync_directory):
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(journal, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    with open(temp_path, "r", encoding="utf-8") as handle:
        validated = json.load(handle)
    if not isinstance(validated, dict):
        raise ValueError("Restore operation journal must contain an object")
    os.replace(temp_path, path)
    fsync_directory(os.path.dirname(path))


def update_restore_operation_journal(path, journal, state, *, states, write_journal, now=datetime.now):
    if state not in states:
        raise ValueError(f"Unsupported restore operation state: {state}")
    journal["state"] = state
    journal["updated_at"] = now().astimezone().isoformat(timespec="seconds")
    write_journal(path, journal)


def remove_restore_operation_journal(path, *, fsync_directory, print_message=print):
    try:
        if os.path.lexists(path):
            if os.path.islink(path):
                return False
            os.remove(path)
        temp_path = path + ".tmp"
        if os.path.lexists(temp_path) and not os.path.islink(temp_path):
            os.remove(temp_path)
        fsync_directory(os.path.dirname(path))
        return True
    except Exception as exc:
        print_message(f"[RESTORE RECOVERY CLEANUP ERROR] {path}: {exc}")
        return False


def restore_operation_safe_name(value, *, label, safe_name, suffix=None):
    name = safe_name(value, label=label)
    if suffix and not name.lower().endswith(suffix):
        raise ValueError(f"{label} has an unsupported filename")
    return name


def restore_operation_target(root, name, *, label, safe_target):
    return safe_target(root, name, label=label)


def validate_restore_operation_journal(
    journal, journal_path, *, journal_marker, journal_version,
    operation_id_pattern, states, token_pattern, max_files,
    data_root_marker, excluded_top_level, backup_folder,
    restore_staging_folder, operation_root, safe_name, safe_target,
):
    if not isinstance(journal, dict):
        raise ValueError("journal must contain an object")
    if journal.get("marker") != journal_marker:
        raise ValueError("unsupported restore journal marker")
    if journal.get("schema_version") != journal_version:
        raise ValueError("unsupported restore journal version")
    operation_id = journal.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id_pattern.fullmatch(operation_id):
        raise ValueError("invalid restore operation ID")
    if os.path.basename(journal_path) != f"restore_{operation_id}.json":
        raise ValueError("journal filename does not match its restore operation ID")
    if journal.get("state") not in states:
        raise ValueError("unsupported restore operation state")
    for timestamp_name in ("created_at", "updated_at"):
        value = journal.get(timestamp_name)
        if not isinstance(value, str) or not value or len(value) > 80:
            raise ValueError(f"invalid restore journal {timestamp_name}")
    safety = journal.get("safety_backup")
    staging = journal.get("staging")
    if not isinstance(safety, dict) or not isinstance(staging, dict):
        raise ValueError("restore journal path records are malformed")
    safety_name = safe_name(safety.get("name"), label="safety backup", suffix=".zip")
    token = staging.get("token")
    if not isinstance(token, str) or not token_pattern.fullmatch(token):
        raise ValueError("invalid restore staging token")
    live_roots = journal.get("live_roots")
    if not isinstance(live_roots, dict):
        raise ValueError("restore journal live-root metadata is malformed")

    def validate_root_names(values, label):
        if not isinstance(values, list) or len(values) > max_files:
            raise ValueError(f"restore journal {label} roots are malformed")
        names = []
        seen = set()
        for value in values:
            name = safe_name(value, label=f"{label} root")
            if name.casefold() in {data_root_marker.casefold(), ".secret_key"}:
                raise ValueError(f"restore journal {label} root is protected")
            if name.casefold() in excluded_top_level:
                raise ValueError(f"restore journal {label} root is excluded")
            key = name.casefold()
            if key in seen:
                raise ValueError(f"restore journal {label} roots contain duplicates")
            names.append(name)
            seen.add(key)
        return names

    restore_roots = validate_root_names(live_roots.get("restore"), "restored")
    safety_roots = validate_root_names(live_roots.get("safety"), "safety-backup")
    recovery_name = f"recovery_{operation_id}"
    return {
        "safety": safe_target(backup_folder, safety_name, label="safety backup"),
        "stage": safe_target(restore_staging_folder, token, label="restore staging directory"),
        "recovery": safe_target(operation_root(), recovery_name, label="restore recovery directory"),
        "restore_roots": restore_roots,
        "safety_roots": safety_roots,
    }


def new_restore_operation(
    token, safety_path, manifest=None, *, safety_manifest=None,
    restore_roots=None, lock, require_owned_root, token_pattern,
    backup_folder, operation_root, safe_name, safe_target,
    journal_marker, journal_version, write_journal, checkpoint,
    token_hex, now=datetime.now,
):
    with lock:
        require_owned_root("journal a DLMS restore")
        if not isinstance(token, str) or not token_pattern.fullmatch(token):
            raise ValueError("Invalid restore token")
        safety_name = os.path.basename(str(safety_path or ""))
        expected_safety = safe_target(
            backup_folder,
            safe_name(safety_name, label="safety backup", suffix=".zip"),
            label="safety backup",
        )
        if os.path.normcase(os.path.realpath(str(safety_path))) != os.path.normcase(os.path.realpath(expected_safety)):
            raise ValueError("Safety backup is outside the DLMS backups directory")
        if not os.path.isfile(expected_safety) or os.path.islink(expected_safety):
            raise ValueError("Safety backup is missing or unsafe")
        root = operation_root()
        if os.path.lexists(root) and os.path.islink(root):
            raise ValueError("Restore operation directory must not be a symlink")
        os.makedirs(root, exist_ok=True)
        if os.listdir(root):
            raise RuntimeError("A prior restore operation requires recovery before another restore can begin")
        operation_id = token_hex(16)
        timestamp = now().astimezone().isoformat(timespec="seconds")
        journal = {
            "marker": journal_marker, "schema_version": journal_version,
            "operation_id": operation_id, "created_at": timestamp,
            "updated_at": timestamp, "state": "safety_backup_created",
            "safety_backup": {"name": safety_name}, "staging": {"token": token},
            "backup_identity": {
                "created_at": (manifest or {}).get("created_at"),
                "dlms_version": (manifest or {}).get("dlms_version"),
            },
            "live_roots": {
                "restore": sorted(set(restore_roots or []), key=str.casefold),
                "safety": sorted(set((safety_manifest or {}).get("included_roots") or []), key=str.casefold),
            },
        }
        journal_path = os.path.join(root, f"restore_{operation_id}.json")
        write_journal(journal_path, journal)
        checkpoint("safety_backup_created", journal)
        return journal_path, journal


def remove_recorded_restore_directory(path):
    if not os.path.lexists(path):
        return True
    if os.path.islink(path):
        raise ValueError(f"Refusing to remove symlinked restore helper path: {path}")
    if not os.path.isdir(path):
        raise ValueError(f"Restore helper path is not a directory: {path}")
    shutil.rmtree(path)
    return True


def finish_restore_operation_cleanup(
    journal_path, paths, *, remove_stage=True, remove_directory,
    remove_journal,
):
    remove_directory(paths["recovery"])
    if remove_stage:
        remove_directory(paths["stage"])
    if not remove_journal(journal_path):
        raise RuntimeError("Restore journal cleanup did not complete")


def rollback_restore_operation(
    journal_path, journal, paths, *, update_journal, checkpoint,
    remove_directory, validate_backup, extract_backup, validate_semantics,
    prepare_database, safe_target, app_data_dir, apply_data,
    validate_current_database, db_path, reconcile_quiz_publications,
    finish_cleanup,
):
    update_journal(journal_path, journal, "rollback_pending")
    checkpoint("rollback_pending", journal)
    update_journal(journal_path, journal, "rollback_started")
    checkpoint("rollback_started", journal)
    safety_path = paths["safety"]
    if not os.path.isfile(safety_path) or os.path.islink(safety_path):
        raise RuntimeError("The recorded pre-restore safety backup is missing or unsafe")
    remove_directory(paths["recovery"])
    os.makedirs(paths["recovery"], exist_ok=False)
    try:
        safety_report = validate_backup(safety_path)
        extract_backup(safety_path, paths["recovery"], safety_report)
        validate_semantics(paths["recovery"], safety_report["manifest"])
        prepare_database(paths["recovery"])
        safety_keys = {name.casefold() for name in paths["safety_roots"]}
        for root_name in paths["restore_roots"]:
            if root_name.casefold() in safety_keys:
                continue
            restore_only_path = safe_target(app_data_dir, root_name, label="restore-introduced root")
            if os.path.isdir(restore_only_path) and not os.path.islink(restore_only_path):
                shutil.rmtree(restore_only_path)
            elif os.path.lexists(restore_only_path):
                if os.path.islink(restore_only_path):
                    raise ValueError("Restore-introduced root must not be a symlink")
                os.remove(restore_only_path)
        apply_data(paths["recovery"])
        validate_current_database(db_path)
        reconcile_quiz_publications()
        update_journal(journal_path, journal, "rollback_completed")
        checkpoint("rollback_completed", journal)
    except BaseException:
        remove_directory(paths["recovery"])
        raise
    finish_cleanup(journal_path, paths)


def read_restore_operation_journal(path, *, validate_journal):
    if os.path.islink(path):
        raise ValueError("restore journal must not be a symlink")
    with open(path, "r", encoding="utf-8") as handle:
        journal = json.load(handle)
    return journal, validate_journal(journal, path)


def recover_one_restore_operation(
    journal_path, journal, paths, *, pre_mutation_states, preserve_states,
    finish_cleanup, validate_current_database, db_path, rollback,
):
    state = journal["state"]
    if state in pre_mutation_states:
        finish_cleanup(journal_path, paths)
        return "abandoned"
    if state in preserve_states:
        try:
            validate_current_database(db_path)
        except Exception:
            rollback(journal_path, journal, paths)
            return "rolled_back"
        finish_cleanup(journal_path, paths)
        return "preserved"
    rollback(journal_path, journal, paths)
    return "rolled_back"


def reconcile_restore_operations(
    *, require_owned_root, operation_root, app_data_dir,
    canonical_data_root, is_same_path_or_ancestor, read_journal,
    recover_one, print_message=print,
):
    require_owned_root("reconcile interrupted DLMS restores")
    report = {"processed": 0, "abandoned": 0, "preserved": 0, "rolled_back": 0}
    root = operation_root()
    if not os.path.lexists(root):
        return report
    if os.path.islink(root) or not os.path.isdir(root):
        raise RuntimeError("Restore recovery directory is unsafe")
    if not is_same_path_or_ancestor(canonical_data_root(app_data_dir), os.path.realpath(root)):
        raise RuntimeError("Restore recovery directory escapes the DLMS data root")
    journal_paths = []
    unexpected = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if re.fullmatch(r"restore_[a-f0-9]{32}\.json", name):
            journal_paths.append(path)
        elif name.endswith(".tmp"):
            canonical = path[:-4]
            if os.path.islink(path) or not os.path.exists(canonical):
                unexpected.append(name)
        elif re.fullmatch(r"recovery_[a-f0-9]{32}", name):
            operation_id = name.removeprefix("recovery_")
            matching_journal = os.path.join(root, f"restore_{operation_id}.json")
            if not os.path.isfile(matching_journal) or os.path.islink(path):
                unexpected.append(name)
        else:
            unexpected.append(name)
    if unexpected:
        raise RuntimeError("Restore recovery contains malformed or unsupported helper state: " + ", ".join(unexpected[:5]))
    if len(journal_paths) > 1:
        raise RuntimeError("Multiple restore journals require manual inspection before recovery")
    for journal_path in journal_paths:
        try:
            journal, paths = read_journal(journal_path)
            initial_state = journal["state"]
            outcome = recover_one(journal_path, journal, paths)
            report["processed"] += 1
            report[outcome] += 1
            print_message(f"[RESTORE RECOVERY] {journal['operation_id']} {outcome} from state {initial_state}")
        except Exception as exc:
            print_message(f"[RESTORE RECOVERY ERROR] {os.path.basename(journal_path)}: {type(exc).__name__}: {exc}")
            raise RuntimeError("Interrupted restore recovery could not complete safely") from exc
    return report


def complete_staged_restore(
    token, *, restore_staging_dir, validate_backup, require_owned_root,
    extract_backup, validate_semantics, prepare_database, create_backup,
    new_operation, update_journal, checkpoint, apply_data,
    validate_current_database, db_path, reconcile_quiz_publications,
    read_journal, recover_one, validate_journal, finish_cleanup,
    print_message=print,
):
    journal_path = None
    journal = None
    try:
        stage_dir = restore_staging_dir(token)
        upload_path = os.path.join(stage_dir, "restore.zip")
        if not os.path.isfile(upload_path):
            raise FileNotFoundError("Staged restore file was not found or expired")
        report = validate_backup(upload_path)
        require_owned_root("restore DLMS backup data")
        temp_extract = tempfile.mkdtemp(prefix="apply-", dir=stage_dir)
        try:
            extract_backup(upload_path, temp_extract, report)
            try:
                validate_semantics(temp_extract, report["manifest"])
                prepare_database(temp_extract)
            except ValueError:
                shutil.rmtree(stage_dir, ignore_errors=True)
                raise
            safety_path, safety_manifest = create_backup("pre-restore")
            journal_path, journal = new_operation(
                token, safety_path, report.get("manifest"),
                safety_manifest=safety_manifest,
                restore_roots=os.listdir(temp_extract),
            )
            try:
                for state, operation in (
                    ("live_apply_started", lambda: apply_data(temp_extract)),
                    ("live_apply_completed", lambda: validate_current_database(db_path)),
                    ("post_apply_validated", reconcile_quiz_publications),
                ):
                    update_journal(journal_path, journal, state)
                    checkpoint(state, journal)
                    operation()
                update_journal(journal_path, journal, "reconciliation_completed")
                checkpoint("reconciliation_completed", journal)
            except Exception as restore_exc:
                print_message("[RESTORE] Apply/finalization failed; attempting automatic rollback:", restore_exc)
                try:
                    disk_journal, paths = read_journal(journal_path)
                    recover_one(journal_path, disk_journal, paths)
                except Exception as rollback_exc:
                    raise RuntimeError(
                        f"Restore failed ({restore_exc}); automatic rollback also failed ({rollback_exc}). "
                        f"Safety backup remains at {os.path.basename(safety_path)}."
                    ) from restore_exc
                raise RuntimeError(
                    "Restore failed and DLMS rolled back to the pre-restore snapshot. "
                    f"Safety backup: {os.path.basename(safety_path)}. Error: {restore_exc}"
                ) from restore_exc
        finally:
            shutil.rmtree(temp_extract, ignore_errors=True)
        cleanup_pending = False
        try:
            update_journal(journal_path, journal, "complete")
            checkpoint("complete", journal)
            paths = validate_journal(journal, journal_path)
            finish_cleanup(journal_path, paths)
        except Exception as cleanup_exc:
            cleanup_pending = True
            print_message(
                "[RESTORE CLEANUP ERROR] Restore completed; helper cleanup will "
                f"retry at startup: {type(cleanup_exc).__name__}: {cleanup_exc}"
            )
        return {"safety_path": safety_path, "cleanup_pending": cleanup_pending}
    except Exception:
        if journal_path is None:
            try:
                cleanup_stage = restore_staging_dir(token)
                if os.path.isdir(cleanup_stage) and not os.path.islink(cleanup_stage):
                    shutil.rmtree(cleanup_stage)
            except Exception as cleanup_exc:
                print_message(
                    "[RESTORE CLEANUP ERROR] Could not remove pre-mutation staging: "
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                )
        raise


def clear_directory_contents(path):
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        target = os.path.join(path, name)
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)


def reset_quiz_library_core(
    *, db_path, save_registry, folders, clear_directory, ensure_runtime_dirs,
    sqlite_module=sqlite3,
):
    conn = sqlite_module.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    cur = conn.cursor()
    cur.executescript("""
        DELETE FROM learning_events;
        DELETE FROM question_concepts;
        DELETE FROM concepts;
        DELETE FROM missed_questions;
        DELETE FROM attempt_answers;
        DELETE FROM attempts;
        DELETE FROM choices;
        DELETE FROM questions;
        DELETE FROM quizzes;
        DELETE FROM sqlite_sequence;
    """)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    save_registry([])
    for folder in folders:
        clear_directory(folder)
    ensure_runtime_dirs()


def reset_learning_intelligence_core(db_path, *, sqlite_module=sqlite3):
    conn = sqlite_module.connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM learning_events")
    finally:
        conn.close()


def reset_source_content_core(*, remove_unprotected_packs, folders, clear_directory, ensure_runtime_dirs):
    remove_unprotected_packs()
    for folder in folders:
        clear_directory(folder)
    ensure_runtime_dirs()


def reset_app_settings_core(*, portal_config, background_folder, clear_directory, load_portal_config):
    if os.path.isfile(portal_config):
        os.remove(portal_config)
    clear_directory(background_folder)
    load_portal_config()


def full_data_reset_core(
    *, app_data_dir, data_root_marker, ensure_runtime_dirs,
    ensure_db_initialized, save_registry, load_portal_config,
):
    for name in os.listdir(app_data_dir):
        if name.casefold() == "backups" or name == data_root_marker:
            continue
        target = os.path.join(app_data_dir, name)
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    ensure_runtime_dirs()
    ensure_db_initialized()
    save_registry([])
    load_portal_config()


def run_reset_with_backup(reset_label, reset_callable, *, require_owned_root, create_backup):
    require_owned_root(f"run the {reset_label} reset")
    safety_path, _ = create_backup("pre-reset-" + reset_label)
    reset_callable()
    return os.path.basename(safety_path)


def validate_destructive_data_root_path(
    root, *, canonical_data_root, data_root_path_is_dangerous,
    ownership_error=DataRootOwnershipError,
):
    target = canonical_data_root(root)
    if data_root_path_is_dangerous(target):
        raise ownership_error("DLMS refused an unsafe application-data path.")
    return target


def require_owned_app_data_root(
    operation, *, app_data_dir, validate_target, read_data_root_marker,
    ownership_error=DataRootOwnershipError,
):
    target = validate_target(app_data_dir)
    if not os.path.isdir(target):
        raise ownership_error(
            f"DLMS cannot {operation}: the configured application-data directory does not exist."
        )
    if read_data_root_marker(target) is None:
        raise ownership_error(
            f"DLMS cannot {operation}: the configured application-data directory is not verified as a dedicated DLMS data root."
        )
    return target


def remove_all_dlms_runtime_data(*, validate_removal_target):
    target = validate_removal_target()
    if os.path.isdir(target):
        shutil.rmtree(target)
    return target


def schedule_post_removal_shutdown(
    removed_path, *, shutdown_callback, timer_factory, delay=0.75,
):
    timer_factory(delay, lambda: shutdown_callback(removed_path)).start()
