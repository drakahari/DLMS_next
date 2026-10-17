"""Quiz Library routes for DLMS portable quiz bundle export/import."""

from functools import wraps

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from .dependencies import QuizBundleDependencies
from dlms.services.portable_quiz_exports import ExportSelectionError, ExportBusyError, preflight_admission


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def _catalog(dependencies):
    with dependencies.registry_lock():
        registry = dependencies.load_registry()
    connection = dependencies.get_db()
    try:
        return dependencies.export_catalog(connection.cursor(), registry)
    finally:
        connection.close()


def portable_quiz_bundles(dependencies, *, error=None, status=200, selected=None, search="", folder="", preflight=None):
    return render_template(
        "quiz/bundles.html",
        app_version=dependencies.app_version(),
        portal_title=dependencies.get_portal_title(),
        catalog=_catalog(dependencies),
        upload_max_mb=dependencies.upload_max_bytes() // (1024 * 1024),
        error=error,
        preflight=preflight,
        selected=set(str(value) for value in (selected or [])),
        export_search=search[:240],
        export_folder=folder[:120],
    ), status


def export_portable_quiz_bundle(dependencies):
    selected = request.form.getlist("quiz_ids")
    with dependencies.registry_lock():
        registry = dependencies.load_registry()
    connection = dependencies.get_db()
    try:
        connection.execute('BEGIN')
        if dependencies.preflight_export:
            with preflight_admission():
                report = dependencies.preflight_export(connection.cursor(), registry, selected)
            if report['blocked_quizzes'] or request.form.get('export_action') == 'check' or (report['warning_quizzes'] and (request.form.get('export_action') != 'preserve' or request.form.get('warning_snapshot') != report['signature'])):
                return portable_quiz_bundles(dependencies, preflight=report,
                    error='Export is blocked. No quizzes were exported; all selections are retained.' if report['blocked_quizzes'] else None,
                    status=400 if report['blocked_quizzes'] else 200, selected=selected,
                    search=request.form.get('export_search',''), folder=request.form.get('export_folder',''))
        download = dependencies.build_export(
            connection.cursor(), registry, selected
        )
    except Exception as exc:
        dependencies.print_message(
            f"[PORTABLE QUIZ EXPORT ERROR] {type(exc).__name__}: {exc}"
            + (f"; cause: {type(exc.__cause__).__name__}: {exc.__cause__}" if exc.__cause__ else "")
        )
        public_error = str(exc) if isinstance(exc, (ExportSelectionError, ExportBusyError)) else (
            "The export could not be created because of a storage or server error. Your selection is retained. Try again, or use a full backup and report the failure."
        )
        return portable_quiz_bundles(
            dependencies,
            error=public_error,
            status=503 if isinstance(exc, ExportBusyError) else (400 if isinstance(exc, ExportSelectionError) else 500),
            selected=selected,
            preflight=getattr(exc, "report", None),
            search=request.form.get("export_search", ""),
            folder=request.form.get("export_folder", ""),
        )
    finally:
        connection.close()
    def chunks():
        try:
            with download.path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    yield chunk
        finally:
            download.close()

    response = Response(
        chunks(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{download.filename}"',
                 "Content-Length": str(download.path.stat().st_size),
                 "Cache-Control": "no-store"},
    )
    response.call_on_close(download.close)
    return response


def stage_portable_quiz_bundle(dependencies):
    upload = request.files.get("bundle_zip")
    declared_limit = (
        dependencies.upload_max_bytes() + dependencies.multipart_overhead_bytes()
    )
    if request.content_length and request.content_length > declared_limit:
        return portable_quiz_bundles(
            dependencies,
            error="Portable quiz bundle exceeds the upload size limit.",
            status=413,
        )
    try:
        token = dependencies.stage_upload(upload)
    except Exception as exc:
        dependencies.print_message(
            f"[PORTABLE QUIZ IMPORT VALIDATION ERROR] {type(exc).__name__}: {exc}"
        )
        return portable_quiz_bundles(
            dependencies,
            error="That archive is not a valid, safe DLMS portable quiz bundle.",
            status=400,
        )
    return redirect(url_for("quiz.review_portable_quiz_bundle", token=token))


def _review_context(dependencies, token, *, error=None):
    _stage_dir, _archive_path, metadata, report = dependencies.load_staged(token)
    progress = dependencies.import_progress(token) if dependencies.import_progress else None
    connection = dependencies.get_db()
    try:
        existing_titles = [
            row[0]
            for row in connection.execute(
                "SELECT title FROM quizzes ORDER BY id"
            ).fetchall()
        ]
    finally:
        connection.close()
    plans = dependencies.plan_import(report["manifest"], existing_titles)
    if progress and progress["items"]:
        if len(progress["items"]) != len(plans):
            raise ValueError("Accepted import item count differs from the staged bundle")
        for plan, item in zip(plans, progress["items"]):
            if plan["bundle_id"] != item["bundle_id"]:
                raise ValueError("Accepted import item identity differs from the staged bundle")
            plan["import_title"] = item["title"]
            plan["renamed"] = item["renamed"]
    return {
        "app_version": dependencies.app_version(),
        "portal_title": dependencies.get_portal_title(),
        "token": token,
        "metadata": metadata,
        "report": report,
        "plans": plans,
        "import_progress": progress,
        "error": error,
    }


def _unavailable_import_message(dependencies, token):
    if dependencies.import_progress:
        try:
            progress = dependencies.import_progress(token)
            if progress["state"] != "new":
                return (f"This accepted import's staged input is unavailable or changed. "
                        f"{progress['committed']} item(s) have confirmed durable receipts; "
                        "another publication outcome may still be uncertain. No retry was attempted. Keep the operation evidence and "
                        "restore the exact reviewed stage before retrying. A new upload is a separate import.")
        except Exception:
            return "Accepted import evidence is unavailable or conflicting. A publication outcome may be uncertain; no retry was attempted. Inspect this profile before retrying."
    return "Portable bundle import session is unavailable or no longer valid."


def review_portable_quiz_bundle(dependencies, token):
    if dependencies.import_progress:
        try:
            progress = dependencies.import_progress(token)
            if progress["state"] == "complete":
                try:
                    dependencies.load_staged(token)
                except FileNotFoundError:
                    flash(f"This import already completed: {progress['committed']} quizzes. No new copies were created.", "success")
                    return redirect(url_for("quiz.portable_quiz_bundles"))
        except Exception:
            pass
    try:
        context = _review_context(dependencies, token)
    except Exception as exc:
        dependencies.print_message(
            f"[PORTABLE QUIZ REVIEW ERROR] {type(exc).__name__}: {exc}"
        )
        flash(_unavailable_import_message(dependencies, token), "error")
        return redirect(url_for("quiz.portable_quiz_bundles"))
    return render_template("quiz/bundle-review.html", **context)


def confirm_portable_quiz_bundle(dependencies, token):
    if request.form.get("confirm_import") != "yes":
        flash("Confirm the portable quiz import before publishing.", "error")
        return redirect(url_for("quiz.review_portable_quiz_bundle", token=token))
    try:
        result = dependencies.install_staged(token)
    except Exception as exc:
        dependencies.print_message(
            f"[PORTABLE QUIZ IMPORT ERROR] {type(exc).__name__}: {exc}"
        )
        progress = None
        if dependencies.import_progress:
            try:
                progress = dependencies.import_progress(token)
            except Exception:
                pass
        try:
            context = _review_context(
                dependencies,
                token,
                error=(f"{progress['committed']} quizzes have confirmed durable receipts; final stage cleanup is still pending. {exc} Retrying this token will not publish another copy."
                       if progress and progress["state"] == "complete" else
                       f"{progress['committed']} of {progress['committed'] + progress['remaining']} quizzes have confirmed durable receipts; "
                       f"temporary cleanup is still pending. {exc} Retrying this token will not publish another copy."
                       if progress and progress["state"] == "cleanup_pending" else
                       f"{progress['committed']} of {progress['committed'] + progress['remaining']} quizzes have confirmed durable receipts; "
                       f"{progress['remaining']} need reconciliation and may include a committed result. {exc} "
                       "No new copy will be published unless the earlier outcome is proven."
                       if progress and progress["remaining"] is not None else
                       (str(exc) if dependencies.import_progress else
                        "The bundle was not imported. No completed bundle quizzes were kept.")),
            )
        except Exception:
            flash(_unavailable_import_message(dependencies, token), "error")
            return redirect(url_for("quiz.portable_quiz_bundles"))
        return render_template("quiz/bundle-review.html", **context), 409 if dependencies.import_progress else 500

    published = result["published"]
    renamed = sum(bool(item["renamed"]) for item in published)
    message = f"Imported {len(published)} quiz{'zes' if len(published) != 1 else ''}."
    if result.get("replayed"):
        message = f"This import already completed: {len(published)} quizzes. No new copies were created."
    if renamed:
        message += f" {renamed} title{'s were' if renamed != 1 else ' was'} renamed to avoid a collision."
    flash(message, "success")
    return redirect(url_for("quiz.portable_quiz_bundles"))


def cancel_portable_quiz_bundle(dependencies, token):
    try:
        dependencies.cancel_staged(token)
    except Exception as exc:
        flash(str(exc) if dependencies.import_progress else "Import cancellation failed; staging was retained.", "error")
        return redirect(url_for("quiz.review_portable_quiz_bundle", token=token))
    flash("Portable quiz bundle import cancelled; staged files were removed.", "success")
    return redirect(url_for("quiz.portable_quiz_bundles"))


def register_bundle_routes(
    blueprint: Blueprint, dependencies: QuizBundleDependencies
) -> None:
    routes = (
        ("/quiz-bundles", "portable_quiz_bundles", portable_quiz_bundles, ["GET"]),
        ("/quiz-bundles/export", "export_portable_quiz_bundle", export_portable_quiz_bundle, ["POST"]),
        ("/quiz-bundles/import", "stage_portable_quiz_bundle", stage_portable_quiz_bundle, ["POST"]),
        ("/quiz-bundles/import/<token>", "review_portable_quiz_bundle", review_portable_quiz_bundle, ["GET"]),
        ("/quiz-bundles/import/<token>/confirm", "confirm_portable_quiz_bundle", confirm_portable_quiz_bundle, ["POST"]),
        ("/quiz-bundles/import/<token>/cancel", "cancel_portable_quiz_bundle", cancel_portable_quiz_bundle, ["POST"]),
    )
    for rule, endpoint, view_func, methods in routes:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
