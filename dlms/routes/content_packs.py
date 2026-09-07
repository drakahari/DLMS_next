"""Content Pack catalog, staging, installation, export, and deletion routes."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class ContentPackRouteDependencies:
    content_pack_ai_workflow: Dependency
    content_pack_upload_max_bytes: Dependency
    content_pack_multipart_overhead_bytes: Dependency
    content_pack_folder: Dependency
    stage_content_pack_upload: Dependency
    content_pack_workflow: Dependency
    content_pack_workflow_return_url: Dependency
    load_staged_content_pack: Dependency
    validate_staged_content_pack: Dependency
    install_staged_content_pack: Dependency
    cancel_staged_content_pack: Dependency
    content_pack_folder_report: Dependency
    build_content_pack_export: Dependency
    content_pack_management_summary: Dependency
    delete_content_pack_folder: Dependency
    content_pack_install_error: Dependency
    invalid_content_pack_folder_error: Dependency
    content_pack_folder_not_found_error: Dependency
    protected_content_pack_error: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def content_pack_import(dependencies):
    CONTENT_PACK_UPLOAD_MAX_BYTES = dependencies.content_pack_upload_max_bytes()
    CONTENT_PACK_MULTIPART_OVERHEAD_BYTES = dependencies.content_pack_multipart_overhead_bytes()
    _stage_content_pack_upload = dependencies.stage_content_pack_upload

    upload = request.files.get("pack_zip")
    if not upload or not upload.filename:
        flash("Choose a DLMS Study Pack ZIP to validate.", "error")
        return redirect("/content-packs")
    if not str(upload.filename).lower().endswith(".zip"):
        flash("Content Packs must be uploaded as ZIP files.", "error")
        return redirect("/content-packs")
    if request.content_length and request.content_length > CONTENT_PACK_UPLOAD_MAX_BYTES + CONTENT_PACK_MULTIPART_OVERHEAD_BYTES:
        flash("Study Pack ZIP is too large. Maximum upload size is 256 MB.", "error")
        return redirect("/content-packs")
    try:
        token = _stage_content_pack_upload(upload)
        return redirect(url_for("content_packs.content_pack_import_review", token=token))
    except Exception as exc:
        print(f"[CONTENT PACK IMPORT ERROR] {type(exc).__name__}: {exc}")
        flash("Study Pack ZIP could not be validated. Check the local DLMS log for details.", "error")
        return redirect("/content-packs")

def content_pack_import_review(dependencies, token):
    CONTENT_PACK_AI_WORKFLOW = dependencies.content_pack_ai_workflow()
    _content_pack_workflow = dependencies.content_pack_workflow
    _content_pack_workflow_return_url = dependencies.content_pack_workflow_return_url
    _load_staged_content_pack = dependencies.load_staged_content_pack
    _validate_staged_content_pack = dependencies.validate_staged_content_pack

    try:
        stage_dir, pack_root, metadata = _load_staged_content_pack(token)
        # Revalidate on every review instead of trusting the saved report.
        report = _validate_staged_content_pack(
            pack_root,
            require_single_select=(
                _content_pack_workflow(metadata) == CONTENT_PACK_AI_WORKFLOW
            ),
        )
        report["warnings"].extend(metadata.get("answer_position_corrections") or [])
        metadata["report"] = report
    except Exception as exc:
        print(f"[CONTENT PACK REVIEW ERROR] {type(exc).__name__}: {exc}")
        flash("The Study Pack validation session is unavailable or expired.", "error")
        return redirect("/content-packs")

    ai_workflow = _content_pack_workflow(metadata) == CONTENT_PACK_AI_WORKFLOW
    return_url = _content_pack_workflow_return_url(metadata)
    return_label = "AI Study Pack Builder" if ai_workflow else "Content Packs"

    return render_template(
        "content_packs/import-review.html",
        token=token,
        metadata=metadata,
        report=report,
        ai_workflow=ai_workflow,
        return_url=return_url,
        return_label=return_label,
        medical_pack_installed=True,
    )

def content_pack_import_install(dependencies, token):
    CONTENT_PACK_AI_WORKFLOW = dependencies.content_pack_ai_workflow()
    _content_pack_workflow = dependencies.content_pack_workflow
    _content_pack_workflow_return_url = dependencies.content_pack_workflow_return_url
    _load_staged_content_pack = dependencies.load_staged_content_pack
    _install_staged_content_pack = dependencies.install_staged_content_pack
    ContentPackInstallError = dependencies.content_pack_install_error()

    if request.form.get("confirm_install") != "yes":
        flash("Study Pack installation was not confirmed.", "error")
        return redirect(url_for("content_packs.content_pack_import_review", token=token))

    metadata = {}
    try:
        result = _install_staged_content_pack(token)
        metadata = result["metadata"]
        if result["status"] == "invalid":
            flash("Study Pack is no longer valid; installation was blocked.", "error")
            return redirect(url_for("content_packs.content_pack_import_review", token=token))
        pack_id = result["pack_id"]
        installed = result["installed"]
        flash(f"Installed Study Pack '{installed.get('name') or pack_id}' successfully.", "success")
        if _content_pack_workflow(metadata) == CONTENT_PACK_AI_WORKFLOW:
            return redirect(url_for("study_packs.study_packs_home", installed=pack_id))
        return redirect("/content-packs")
    except Exception as install_error:
        if isinstance(
            install_error, ContentPackInstallError
        ):
            exc = install_error.original
            metadata = install_error.metadata
        else:
            exc = install_error
        print(f"[CONTENT PACK INSTALL ERROR] {type(exc).__name__}: {exc}")
        flash("The Study Pack was not installed. Existing installed content was left unchanged.", "error")
        try:
            _load_staged_content_pack(token)
            return redirect(url_for("content_packs.content_pack_import_review", token=token))
        except Exception:
            return redirect(_content_pack_workflow_return_url(metadata))

def content_pack_import_cancel(dependencies, token):
    _content_pack_workflow_return_url = dependencies.content_pack_workflow_return_url
    _cancel_staged_content_pack = dependencies.cancel_staged_content_pack

    metadata = _cancel_staged_content_pack(token)
    flash("Study Pack import cancelled; staging files were removed.", "success")
    return redirect(_content_pack_workflow_return_url(metadata))

def content_pack_details(dependencies, folder):
    _content_pack_folder_report = dependencies.content_pack_folder_report

    try:
        report = _content_pack_folder_report(folder)
    except Exception as exc:
        print(f"[CONTENT PACK DETAILS ERROR] {type(exc).__name__}: {exc}")
        flash("Content Pack details are unavailable. Check the local DLMS log for details.", "error")
        return redirect("/content-packs")
    manifest = report.get("manifest") or {}
    matching = len(manifest.get("datasets") or []) if isinstance(manifest.get("datasets") or [], list) else 0
    image = len(manifest.get("image_datasets") or []) if isinstance(manifest.get("image_datasets") or [], list) else 0
    mixed = len(manifest.get("quiz_datasets") or []) if isinstance(manifest.get("quiz_datasets") or [], list) else 0
    return render_template(
        "content_packs/detail.html",
        report=report,
        manifest=manifest,
        matching=matching,
        image=image,
        mixed=mixed,
        medical_pack_installed=True,
    )

def export_content_pack(dependencies, folder):
    _build_content_pack_export = dependencies.build_content_pack_export

    try:
        archive_bytes, safe_name = _build_content_pack_export(folder)
        return Response(
            archive_bytes,
            mimetype="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.zip"'}
        )
    except Exception as exc:
        print(f"[CONTENT PACK EXPORT ERROR] {type(exc).__name__}: {exc}")
        flash("Study Pack export failed. Check the local DLMS log for details.", "error")
        return redirect("/content-packs")

def content_packs_page(dependencies):
    CONTENT_PACK_FOLDER = dependencies.content_pack_folder()
    content_pack_management_summary = dependencies.content_pack_management_summary

    packs = content_pack_management_summary()
    return render_template(
        "content_packs/index.html",
        packs=packs,
        pack_folder=CONTENT_PACK_FOLDER,
        medical_pack_installed=True,
    )

def delete_content_pack(dependencies):
    _delete_content_pack_folder = dependencies.delete_content_pack_folder
    InvalidContentPackFolderError = dependencies.invalid_content_pack_folder_error()
    ContentPackFolderNotFoundError = dependencies.content_pack_folder_not_found_error()
    ProtectedContentPackError = dependencies.protected_content_pack_error()

    confirmed = request.form.get("confirm_delete") == "yes"
    if not confirmed:
        flash("Study Pack deletion was not confirmed.", "error")
        return redirect("/content-packs")
    folder = str(request.form.get("folder") or "").strip()
    try:
        result = _delete_content_pack_folder(folder)
        migration = result["migration"]
        message = f"Deleted Study Pack folder '{folder}'. Existing quizzes and history were kept."
        if migration["references"]:
            message += f" Preserved {migration['references']} legacy image reference(s) in quiz-owned storage."
        flash(message, "success")
    except InvalidContentPackFolderError:
        flash("Invalid Content Pack folder.", "error")
    except ContentPackFolderNotFoundError:
        flash("Content Pack folder was not found.", "error")
    except ProtectedContentPackError:
        flash("This Content Pack declares itself protected and cannot be deleted here.", "error")
    except Exception as exc:
        print(f"[CONTENT PACK DELETE ERROR] {type(exc).__name__}: {exc}")
        flash(
            "The Study Pack could not be deleted. Any completed legacy-asset "
            "preservation remains safe and can be reused when deletion is retried.",
            "error",
        )

    return redirect("/content-packs")

def create_content_packs_blueprint(dependencies: ContentPackRouteDependencies) -> Blueprint:
    blueprint = Blueprint("content_packs", __name__)
    routes = (
        ("/content-packs/import", "content_pack_import", content_pack_import, ["POST"]),
        ("/content-packs/import/<token>", "content_pack_import_review", content_pack_import_review, ["GET"]),
        ("/content-packs/import/<token>/install", "content_pack_import_install", content_pack_import_install, ["POST"]),
        ("/content-packs/import/<token>/cancel", "content_pack_import_cancel", content_pack_import_cancel, ["POST"]),
        ("/content-packs/details/<folder>", "content_pack_details", content_pack_details, ["GET"]),
        ("/content-packs/export/<folder>", "export_content_pack", export_content_pack, ["GET"]),
        ("/content-packs", "content_packs_page", content_packs_page, ["GET"]),
        ("/content-packs/delete", "delete_content_pack", delete_content_pack, ["POST"]),
    )
    for rule, endpoint, view_func, methods in routes:
        blueprint.add_url_rule(rule, endpoint=endpoint, view_func=_bind_dependencies(view_func, dependencies), methods=methods)
    return blueprint
