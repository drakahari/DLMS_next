"""Backup, restore, destructive-data, and System Tools routes."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, jsonify, redirect, render_template, request


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class MaintenanceRouteDependencies:
    """Configured application services required by administrative routes."""

    backup_upload_max_bytes: Dependency
    upload_multipart_overhead_bytes: Dependency
    create_backup: Dependency
    send_backup_file: Dependency
    make_restore_token: Dependency
    restore_staging_dir: Dependency
    create_backup_restore_stage: Dependency
    stage_backup: Dependency
    discard_restore_stage: Dependency
    restore_operation_lock: Any
    cancel_validated_restore_stage: Dependency
    complete_staged_restore: Dependency
    restore_error: Dependency
    safety_backup_name: Dependency
    recent_backups: Dependency
    app_data_dir: Dependency
    run_quiz_library_reset: Dependency
    run_learning_intelligence_reset: Dependency
    run_source_content_reset: Dependency
    run_app_settings_reset: Dependency
    run_full_data_reset: Dependency
    run_legacy_wipe: Dependency
    destructive_operation_error: Dependency
    remove_all_runtime_data: Dependency
    schedule_post_removal_shutdown: Dependency
    print_message: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def admin_maintenance(_dependencies):
    return render_template("admin/maintenance.html")


def _run_reset(dependencies, reset_callable, *, log_label, operation):
    try:
        backup_name = reset_callable()
        return jsonify(status="ok", backup=backup_name)
    except Exception as exc:
        dependencies.print_message(log_label, exc)
        message, status = dependencies.destructive_operation_error(exc, operation)
        return jsonify(status="error", error=message), status


def reset_quiz_library(dependencies):
    return _run_reset(
        dependencies,
        dependencies.run_quiz_library_reset,
        log_label="[RESET QUIZ LIBRARY ERROR]",
        operation="Quiz-library reset",
    )


def reset_learning_intelligence(dependencies):
    return _run_reset(
        dependencies,
        dependencies.run_learning_intelligence_reset,
        log_label="[RESET LEARNING INTELLIGENCE ERROR]",
        operation="Learning Intelligence reset",
    )


def reset_source_content(dependencies):
    return _run_reset(
        dependencies,
        dependencies.run_source_content_reset,
        log_label="[RESET SOURCE CONTENT ERROR]",
        operation="Source-content reset",
    )


def reset_app_settings(dependencies):
    return _run_reset(
        dependencies,
        dependencies.run_app_settings_reset,
        log_label="[RESET SETTINGS ERROR]",
        operation="Settings reset",
    )


def reset_all_data(dependencies):
    return _run_reset(
        dependencies,
        dependencies.run_full_data_reset,
        log_label="[RESET ALL DATA ERROR]",
        operation="Full-data reset",
    )


def remove_all_dlms_data(dependencies):
    payload = request.get_json(silent=True) or {}
    confirmation = str(payload.get("confirmation") or "").strip()
    if confirmation != "REMOVE DLMS DATA":
        return jsonify(
            status="error",
            error="Type REMOVE DLMS DATA exactly to confirm permanent removal.",
        ), 400

    try:
        removed_path = dependencies.remove_all_runtime_data()
    except Exception as exc:
        dependencies.print_message("[REMOVE ALL DLMS DATA ERROR]", exc)
        message, status = dependencies.destructive_operation_error(
            exc, "Permanent DLMS data removal"
        )
        return jsonify(status="error", error=message), status

    dependencies.schedule_post_removal_shutdown(removed_path)
    return jsonify(
        status="ok", removed_path=removed_path, executable_removed=False
    )


def wipe_database(dependencies):
    return _run_reset(
        dependencies,
        dependencies.run_legacy_wipe,
        log_label="[LEGACY WIPE ERROR]",
        operation="Database wipe",
    )


def settings_create_backup(dependencies):
    try:
        path, _manifest = dependencies.create_backup("manual")
        return dependencies.send_backup_file(path)
    except Exception as exc:
        dependencies.print_message("[BACKUP ERROR]", exc)
        return render_template(
            "settings/backup-failed.html",
            error=(
                "DLMS could not create the backup. Check the local application "
                "log for details."
            ),
        ), 500


def settings_stage_restore(dependencies):
    upload = request.files.get("backup_file")
    if not upload or not upload.filename:
        return redirect("/settings/backup?restore_error=no-file")
    if not upload.filename.lower().endswith(".zip"):
        return redirect("/settings/backup?restore_error=not-zip")
    upload_limit = (
        dependencies.backup_upload_max_bytes()
        + dependencies.upload_multipart_overhead_bytes()
    )
    if request.content_length and request.content_length > upload_limit:
        return "Backup exceeds the 298 MB restore upload limit.", 413

    token = dependencies.make_restore_token()
    stage_dir = dependencies.restore_staging_dir(token)
    dependencies.create_backup_restore_stage(stage_dir)
    try:
        report, semantic_result = dependencies.stage_backup(
            upload, token, stage_dir=stage_dir
        )
    except Exception as exc:
        dependencies.discard_restore_stage(stage_dir)
        dependencies.print_message(
            f"[RESTORE VALIDATION ERROR] {type(exc).__name__}: {exc}"
        )
        return render_template(
            "settings/restore-validation-failed.html",
            error=(
                "The backup failed validation and was not accepted. Check the "
                "local DLMS log for details."
            ),
        ), 400

    manifest = report["manifest"]
    summary = (
        manifest.get("summary")
        if isinstance(manifest.get("summary"), dict)
        else {}
    )
    return render_template(
        "settings/restore-confirm.html",
        manifest=manifest,
        report=report,
        semantic_validation=semantic_result,
        summary=summary,
        token=token,
    )


def settings_cancel_restore(dependencies, token):
    with dependencies.restore_operation_lock:
        try:
            result = dependencies.cancel_validated_restore_stage(token)
        except ValueError:
            return "Invalid restore cancellation request", 400
        except Exception as exc:
            dependencies.print_message(
                "[RESTORE STAGING CLEANUP ERROR] Could not cancel restore stage: "
                f"{type(exc).__name__}: {exc}"
            )
            return "Could not cancel the staged restore", 500

    if result == "unrecognized":
        return "Restore staging is not available", 404
    if result == "recovery":
        return "Restore recovery is in progress or requires recovery", 409
    return redirect("/settings/backup?restore_cancelled=1")


def settings_confirm_restore(dependencies, token):
    with dependencies.restore_operation_lock:
        try:
            result = dependencies.complete_staged_restore(token)
            return render_template(
                "settings/restore-complete.html",
                safety_name=dependencies.safety_backup_name(result["safety_path"]),
                cleanup_pending=result["cleanup_pending"],
            )
        except Exception as exc:
            dependencies.print_message("[RESTORE ERROR]", exc)
            public_error, status = dependencies.restore_error(exc)
            return render_template(
                "settings/restore-failed.html", error=public_error
            ), status


def settings_data_legacy_redirect(_dependencies):
    return redirect("/settings/backup")


def settings_backup_page(dependencies):
    return render_template(
        "settings/backup.html", recent_backups=dependencies.recent_backups()
    )


def settings_reset_legacy_redirect(_dependencies):
    return redirect("/settings/reset-remove")


def settings_reset_remove_page(dependencies):
    return render_template(
        "settings/reset-remove.html", app_data_dir=dependencies.app_data_dir()
    )


def create_maintenance_blueprint(dependencies):
    blueprint = Blueprint("maintenance", __name__)
    rules = (
        (
            "/admin/maintenance",
            "admin_maintenance",
            admin_maintenance,
            ["GET"],
        ),
        (
            "/api/reset_quiz_library",
            "reset_quiz_library",
            reset_quiz_library,
            ["POST"],
        ),
        (
            "/api/reset_learning_intelligence",
            "reset_learning_intelligence",
            reset_learning_intelligence,
            ["POST"],
        ),
        (
            "/api/reset_source_content",
            "reset_source_content",
            reset_source_content,
            ["POST"],
        ),
        (
            "/api/reset_app_settings",
            "reset_app_settings",
            reset_app_settings,
            ["POST"],
        ),
        (
            "/api/reset_all_data",
            "reset_all_data",
            reset_all_data,
            ["POST"],
        ),
        (
            "/api/remove_all_dlms_data",
            "remove_all_dlms_data",
            remove_all_dlms_data,
            ["POST"],
        ),
        (
            "/api/wipe_database",
            "wipe_database",
            wipe_database,
            ["POST"],
        ),
        (
            "/settings/backup/create",
            "settings_create_backup",
            settings_create_backup,
            ["POST"],
        ),
        (
            "/settings/data/backup/create",
            "settings_create_backup",
            settings_create_backup,
            ["POST"],
        ),
        (
            "/settings/backup/restore/stage",
            "settings_stage_restore",
            settings_stage_restore,
            ["POST"],
        ),
        (
            "/settings/data/restore/stage",
            "settings_stage_restore",
            settings_stage_restore,
            ["POST"],
        ),
        (
            "/settings/backup/restore/cancel/<token>",
            "settings_cancel_restore",
            settings_cancel_restore,
            ["POST"],
        ),
        (
            "/settings/data/restore/cancel/<token>",
            "settings_cancel_restore",
            settings_cancel_restore,
            ["POST"],
        ),
        (
            "/settings/backup/restore/confirm/<token>",
            "settings_confirm_restore",
            settings_confirm_restore,
            ["POST"],
        ),
        (
            "/settings/data/restore/confirm/<token>",
            "settings_confirm_restore",
            settings_confirm_restore,
            ["POST"],
        ),
        (
            "/settings/data",
            "settings_data_legacy_redirect",
            settings_data_legacy_redirect,
            ["GET"],
        ),
        (
            "/settings/backup",
            "settings_backup_page",
            settings_backup_page,
            ["GET"],
        ),
        (
            "/settings/reset",
            "settings_reset_legacy_redirect",
            settings_reset_legacy_redirect,
            ["GET"],
        ),
        (
            "/settings/reset-remove",
            "settings_reset_remove_page",
            settings_reset_remove_page,
            ["GET"],
        ),
    )
    bound_views = {}
    for rule, endpoint, view_func, methods in rules:
        bound_view = bound_views.setdefault(
            endpoint, _bind_dependencies(view_func, dependencies)
        )
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=bound_view,
            methods=methods,
        )
    return blueprint
