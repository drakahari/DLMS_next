from flask import Flask, send_from_directory, request, redirect, render_template, render_template_string, jsonify, Response, flash, url_for, has_request_context
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
import os, re, json, time, sqlite3, sys, shutil, signal, threading, csv, io, random, secrets, zipfile, tempfile, html, warnings, unicodedata, ipaddress, copy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image, ImageSequence, UnidentifiedImageError
from werkzeug.utils import secure_filename

from dlms.rendering.safety import (
    _html_attribute,
    _html_text,
    _json_for_inline_script,
)
from dlms.prompts import (
    DEFAULT_AI_FEEDBACK_PROMPT,
    DEFAULT_LAW_AI_PROMPT,
    DEFAULT_MEDICAL_CONTENT_PACK_PROMPT,
    DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
    DEFAULT_STUDY_CONTENT_PACK_PROMPT,
)
from dlms.runtime import (
    DLMS_SERVER_HOST,
    DLMS_SERVER_PORT,
    _dlms_browser_host,
    _dlms_desktop_browser_available,
    _dlms_detect_lan_ip,
    _dlms_is_loopback_host,
    _dlms_parse_startup_options,
    _dlms_url_host,
    _dlms_validate_server_host,
)
from dlms.persistence import json_files as _json_files
from dlms.persistence import portal as _portal_repository
from dlms.persistence import registries as _registry_repository
from dlms.persistence import database as _database
from dlms.persistence import pdf_banks as _pdf_bank_repository
from dlms.parsing import law_packet as _law_packet_parser
from dlms.parsing import quiz_text as _quiz_text_parser
from dlms.parsing import smart_pdf as _smart_pdf_parser
from dlms.rendering import quiz_artifacts as _quiz_artifact_renderer
from dlms.services import anki as _anki_service
from dlms.services import attempts as _attempt_service
from dlms.services import backups as _backup_service
from dlms.services import content_packs as _content_pack_service
from dlms.services import content_pack_mutations as _content_pack_mutation_service
from dlms.services import history as _history_service
from dlms.services import learning as _learning_service
from dlms.services import quiz_publication as _quiz_publication_service
from dlms.services import quiz_mutations as _quiz_mutation_service
from dlms.services import restore as _restore_service
from dlms.services import law as _law_service

# =========================
# PYINSTALLER PATH HELPER
# =========================
def resource_path(relative_path: str) -> str:
    """
    Resolve paths correctly in dev and when bundled by PyInstaller.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative_path)


def purge_legacy_quizzes():
    """
    Permanently delete quizzes that lack a stored DB id (legacy test data).
    """
    registry = load_registry()
    kept = []

    conn = get_db()
    conn.execute("PRAGMA foreign_keys = ON")

    for q in registry:
        if q.get("id") is None:
            print("[PURGE] Removing legacy quiz:", q.get("title"))

            # 🔥 DB cleanup (authoritative)
            conn.execute(
                "DELETE FROM quizzes WHERE source_file = ? OR title = ?",
                (q.get("html"), q.get("title"))
            )

            # File cleanup
            html = q.get("html")
            logo = q.get("logo")

            if html:
                hp = os.path.join(QUIZ_FOLDER, html)
                jp = os.path.join(DATA_FOLDER, html.replace(".html", ".json"))

                if os.path.exists(hp):
                    os.remove(hp)
                if os.path.exists(jp):
                    os.remove(jp)

            if logo:
                lp = os.path.join(LOGO_FOLDER, logo)
                if os.path.exists(lp):
                    os.remove(lp)

        else:
            kept.append(q)

    conn.commit()
    conn.close()

    save_registry(kept)
    print(f"[PURGE] Completed. Remaining quizzes: {len(kept)}")






# =========================
# APP DATA DIRECTORY
# =========================
DLMS_DATA_ROOT_MARKER = ".dlms-data-root"
DLMS_DATA_ROOT_MARKER_ID = "dlms-application-data-root"
DLMS_DATA_ROOT_MARKER_VERSION = 1
DLMS_LEGACY_DATA_ROOT_ENTRIES = {
    ".quiz_publications", ".restore_operations", ".secret_key", "backups", "config", "content_pack_staging", "content_packs",
    "data", "image_builder_drafts", "law", "pdf_import_drafts",
    "pdf_question_banks", "pdf_terminology_banks", "quiz_assets", "quizzes",
    "results.db", "results.db-journal", "results.db-shm", "results.db-wal",
    "static", "uploads",
}
DLMS_LEGACY_DATA_ROOT_INDICATORS = {
    "config", "content_packs", "data", "law", "pdf_question_banks",
    "quiz_assets", "quizzes", "results.db", "static",
}


def _is_same_path_or_ancestor(candidate, path):
    try:
        return os.path.commonpath([candidate, path]) == candidate
    except ValueError:
        return False


def _canonical_data_root(root):
    return os.path.realpath(os.path.abspath(os.path.expanduser(root)))


def _data_root_path_is_dangerous(root):
    target = _canonical_data_root(root)
    home = _canonical_data_root(os.path.expanduser("~"))
    source_root = _canonical_data_root(os.path.dirname(__file__))
    filesystem_root = _canonical_data_root(os.path.sep)
    drive = os.path.splitdrive(target)[0]
    drive_root = _canonical_data_root(drive + os.path.sep) if drive else filesystem_root
    forbidden = {home, source_root, filesystem_root, drive_root}
    for path in ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/media", "/mnt", "/opt", "/proc", "/run", "/sbin", "/srv", "/sys", "/tmp", "/usr", "/var"]:
        if os.path.exists(path):
            forbidden.add(_canonical_data_root(path))
    return target in forbidden or _is_same_path_or_ancestor(target, source_root)


def _default_app_data_path(app_name="DLMS"):
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.abspath(os.path.expanduser(os.path.join(base, app_name)))


def _data_root_marker_path(root):
    return os.path.join(root, DLMS_DATA_ROOT_MARKER)


def _read_data_root_marker(root):
    marker_path = _data_root_marker_path(root)
    if os.path.islink(marker_path) or not os.path.isfile(marker_path):
        return None
    try:
        with open(marker_path, "r", encoding="utf-8") as marker_file:
            marker = json.load(marker_file)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(marker, dict):
        return None
    if marker.get("marker") != DLMS_DATA_ROOT_MARKER_ID:
        return None
    if marker.get("version") != DLMS_DATA_ROOT_MARKER_VERSION:
        return None
    if marker.get("application") != "DLMS":
        return None
    return marker


def _write_data_root_marker(root):
    """Claim a verified data root without replacing any existing marker file."""
    marker_path = _data_root_marker_path(root)
    marker = {
        "marker": DLMS_DATA_ROOT_MARKER_ID,
        "version": DLMS_DATA_ROOT_MARKER_VERSION,
        "application": "DLMS",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    descriptor = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as marker_file:
            descriptor = None
            json.dump(marker, marker_file, indent=2)
            marker_file.write("\n")
            marker_file.flush()
            os.fsync(marker_file.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return marker


def _looks_like_legacy_dlms_data_root(root):
    try:
        entries = set(os.listdir(root))
    except OSError:
        return False
    if not entries or any(name not in DLMS_LEGACY_DATA_ROOT_ENTRIES for name in entries):
        return False
    indicators = entries & DLMS_LEGACY_DATA_ROOT_INDICATORS
    has_database_and_structure = "results.db" in entries and bool(indicators - {"results.db"})
    has_multiple_dlms_roots = len(indicators) >= 3
    return has_database_and_structure or has_multiple_dlms_roots


def _initialize_data_root_ownership(root, *, is_default=False):
    """Mark only new, empty, default, or reliably recognizable DLMS roots."""
    if _data_root_path_is_dangerous(root):
        print(f"[DATA ROOT] Unsafe configured directory; destructive operations disabled: {root}")
        return False
    os.makedirs(root, exist_ok=True)
    marker_path = _data_root_marker_path(root)
    if os.path.lexists(marker_path):
        if _read_data_root_marker(root) is None:
            print(f"[DATA ROOT] Invalid ownership marker; destructive operations disabled: {root}")
            return False
        return True

    try:
        with os.scandir(root) as entries:
            is_empty = next(entries, None) is None
    except OSError:
        return False
    if not (is_default or is_empty or _looks_like_legacy_dlms_data_root(root)):
        print(f"[DATA ROOT] Unverified non-empty directory; destructive operations disabled: {root}")
        return False
    try:
        _write_data_root_marker(root)
        return True
    except FileExistsError:
        return _read_data_root_marker(root) is not None


def get_app_data_dir(app_name: str = "DLMS") -> str:
    override = os.getenv("QUIZAPP_DATA_DIR")
    if override:
        path = os.path.abspath(os.path.expanduser(override))
        _initialize_data_root_ownership(path, is_default=False)
        return path

    path = _default_app_data_path(app_name)
    _initialize_data_root_ownership(path, is_default=True)
    return path

APP_NAME = "DLMS"
APP_VERSION = "3.0.2"
APP_DATA_DIR = get_app_data_dir(APP_NAME)


def load_secret_key():
    """Load the managed secret or persist a stable per-installation secret."""
    configured = os.getenv("DLMS_SECRET_KEY")
    if configured:
        return configured

    secret_path = os.path.join(APP_DATA_DIR, ".secret_key")
    try:
        with open(secret_path, "r", encoding="utf-8") as secret_file:
            persisted = secret_file.read().strip()
        if persisted:
            try:
                os.chmod(secret_path, 0o600)
            except OSError:
                pass
            return persisted
    except FileNotFoundError:
        pass

    generated = secrets.token_hex(32)
    try:
        descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as secret_file:
            secret_file.write(generated)
        return generated
    except FileExistsError:
        # Another process may have initialized the same application-data path.
        with open(secret_path, "r", encoding="utf-8") as secret_file:
            persisted = secret_file.read().strip()
        if not persisted:
            raise RuntimeError("DLMS secret-key file is empty")
        return persisted

# =========================
# STATIC ROOT SELECTION
# =========================
def get_static_root():
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: static assets live inside the bundle
        return os.path.join(sys._MEIPASS, "static")
    else:
        # Dev mode: static assets live next to app.py
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


STATIC_ROOT = get_static_root()
TEMPLATE_ROOT = resource_path("templates")

# =========================
# FLASK APP
# =========================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(
    __name__,
    static_folder=STATIC_ROOT,
    static_url_path="/static",
    template_folder=TEMPLATE_ROOT,
)

# File parts spool independently; this bounds aggregate in-memory non-file form
# data while leaving ample room for PDF Review & Repair JSON payloads.
app.config["MAX_FORM_MEMORY_SIZE"] = 32 * 1024 * 1024
# Dynamic quiz editors can legitimately submit hundreds of controls. Five
# thousand parts preserves those forms while rejecting pathological multipart
# bodies before route code runs.
app.config["MAX_FORM_PARTS"] = 5000
DLMS_MAX_REQUEST_BYTES = 300 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = DLMS_MAX_REQUEST_BYTES

app.secret_key = load_secret_key()
app.config["WTF_CSRF_METHODS"] = {"POST", "PUT", "PATCH", "DELETE"}
csrf = CSRFProtect()


def _is_json_request():
    return request.is_json or request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def _csrf_failure(message, status=400):
    if _is_json_request():
        return jsonify({"error": message}), status
    return render_template_string(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Request rejected - DLMS</title></head>"
        "<body><main><h1>Request rejected</h1><p>{{ message }}</p><p><a href='javascript:history.back()'>Go back</a></p></main></body></html>",
        message=message,
    ), status


def _canonical_request_origin(value, *, allow_path=False):
    """Return a normalized (scheme, host, port) tuple for an HTTP origin."""
    try:
        parsed = urlsplit(str(value or ""))
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname.casefold() if parsed.hostname else ""
        if scheme not in {"http", "https"} or not hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if not allow_path and (parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            return None
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname, port


def _request_facing_origin():
    """Return the browser-facing origin from this request, never the bind host."""
    # HTTP_HOST is the authority the client used for this request. A wildcard
    # socket bind such as 0.0.0.0 is not a browser-facing authority and must not
    # participate in same-origin decisions.
    request_host = request.environ.get("HTTP_HOST") or request.host
    return _canonical_request_origin(f"{request.scheme}://{request_host}")


def _request_source_matches(source, *, allow_path=False):
    candidate = _canonical_request_origin(source, allow_path=allow_path)
    current = _request_facing_origin()
    return candidate is not None and current is not None and candidate == current


def _format_origin_for_log(origin):
    if not origin:
        return "invalid"
    scheme, hostname, port = origin
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    suffix = "" if port == default_port else f":{port}"
    return f"{scheme}://{display_host}{suffix}"


def _sanitize_header_value_for_log(value, limit=160):
    """Return a bounded repr that cannot inject control characters into logs."""
    raw = str(value or "")
    clipped = raw[:limit]
    if len(raw) > limit:
        clipped += "…"
    return repr(clipped)


@app.before_request
def validate_unsafe_request_origin():
    if request.method not in app.config["WTF_CSRF_METHODS"]:
        return None
    if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
        return _csrf_failure("Cross-site requests are not allowed.", 403)
    origin = request.headers.get("Origin")
    null_origin = origin == "null"
    if origin and not null_origin and not _request_source_matches(origin):
        parsed_origin = _canonical_request_origin(origin)
        received = (
            _format_origin_for_log(parsed_origin)
            if parsed_origin
            else _sanitize_header_value_for_log(origin)
        )
        print(
            "[SAME-ORIGIN] Rejected Origin "
            f"{received}; "
            "request-facing origin is "
            f"{_format_origin_for_log(_request_facing_origin())}"
        )
        return _csrf_failure("The request origin does not match DLMS.", 403)
    referer = request.headers.get("Referer")
    if (not origin or null_origin) and referer and not _request_source_matches(referer, allow_path=True):
        print(
            "[SAME-ORIGIN] Rejected Referer "
            f"{_format_origin_for_log(_canonical_request_origin(referer, allow_path=True))}; "
            "request-facing origin is "
            f"{_format_origin_for_log(_request_facing_origin())}"
        )
        return _csrf_failure("The request referrer does not match DLMS.", 403)
    if null_origin:
        print(
            "[SAME-ORIGIN] Indeterminate Origin "
            f"{_sanitize_header_value_for_log(origin)}; "
            "deferring to same-origin Referer when present and mandatory CSRF validation"
        )
    return None


@app.before_request
def reject_declared_oversized_workflow_upload():
    """Reject honest oversized multipart requests before CSRF/form parsing."""
    if request.method != "POST" or not request.content_length:
        return None
    route_limits = {
        "/pdf-import/analyze": PDF_IMPORT_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
        "/content-packs/import": CONTENT_PACK_UPLOAD_MAX_BYTES + CONTENT_PACK_MULTIPART_OVERHEAD_BYTES,
        "/settings/data/restore/stage": BACKUP_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
        "/settings/backup/restore/stage": BACKUP_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
        "/study-packs/image-builder": IMAGE_BUILDER_TOTAL_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
        "/matching_bank_import": MATCHING_CSV_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
        "/process": QUIZ_TEXT_UPLOAD_MAX_BYTES + LOGO_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
        "/preview_paste": app.config["MAX_FORM_MEMORY_SIZE"] + LOGO_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
        "/create_short_quiz": app.config["MAX_FORM_MEMORY_SIZE"] + LOGO_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
        "/settings/appearance/save": RASTER_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
        "/save_settings": app.config["MAX_FORM_MEMORY_SIZE"] + RASTER_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
    }
    limit = route_limits.get(request.path)
    if limit is None and request.path.startswith("/edit_quiz/"):
        limit = app.config["MAX_FORM_MEMORY_SIZE"] + LOGO_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES
    if limit is not None and request.content_length > limit:
        return _csrf_failure("This upload exceeds the safety limit for this workflow.", 413)
    return None


csrf.init_app(app)


@app.errorhandler(CSRFError)
def handle_csrf_error(_error):
    return _csrf_failure("The security token is missing or invalid. Refresh the page and try again.", 400)


@app.after_request
def deliver_csrf_token(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    )
    if (
        request.path.startswith("/api/")
        or request.path.startswith("/settings/data")
        or request.path.startswith("/settings/backup")
        or request.path.startswith("/settings/reset")
    ):
        response.headers.setdefault("Cache-Control", "no-store")
    if request.method == "GET" and response.status_code < 400 and response.mimetype == "text/html":
        response.set_cookie(
            "dlms_csrf_token", generate_csrf(), secure=request.is_secure,
            httponly=False, samesite="Strict", path="/",
        )
    return response


@app.errorhandler(413)
def dlms_request_too_large(_error):
    """Return a friendly page when a request or multipart parser limit is exceeded."""
    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Upload Too Large - DLMS</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home">
<div class="dashboard-shell">
<main class="dashboard-main" style="max-width:900px;margin:0 auto;padding:48px 24px">
<section class="dashboard-panel" style="padding:28px">
<div class="build-eyebrow">UPLOAD SAFETY</div>
<h1 style="margin-top:8px">Upload is too large</h1>
<p>DLMS rejected this request before processing because it exceeded a request-size, form-memory, or multipart-part safety limit.</p>
<p>Some workflows intentionally use smaller limits. Smart PDF Import accepts PDF files up to 64 MB, and Study Pack ZIP uploads are limited to 256 MB.</p>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:20px">
<a class="medical-primary-button" href="javascript:history.back()">Go Back</a>
<a class="medical-ai-secondary-button" href="/">Dashboard</a>
</div>
</section>
</main>
</div>
</body>
</html>
"""), 413




# DEBUG - retained for troubleshooting static-file path issues
# print("[DEBUG] Flask static folder =", app.static_folder)
# DEBUG - retained for troubleshooting packaged/dev data-directory issues
# print("[BUILD CHECK] APP_DATA_DIR =", APP_DATA_DIR)









import sys

DEBUG_LOGS = False

def dprint(*args, **kwargs):
    if DEBUG_LOGS:
        print(*args, **kwargs)

#dprint("DEBUG TEST — YOU SHOULD NOT SEE THIS")
# DEBUG - retained for troubleshooting static-file path issues
# print("[DEBUG] Flask static folder =", app.static_folder)




def resource_path(relative_path: str) -> str:
    """
    Resolve paths correctly in dev and when bundled by PyInstaller.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative_path)


def get_app_data_dir(app_name: str = "DLMS") -> str:
    """
    Return a user-writable directory for runtime data.
    """
    override = os.getenv("QUIZAPP_DATA_DIR")
    if override:
        path = os.path.abspath(os.path.expanduser(override))
        _initialize_data_root_ownership(path, is_default=False)
        return path

    path = _default_app_data_path(app_name)
    _initialize_data_root_ownership(path, is_default=True)
    return path




# =========================
# PATH SETUP
# =========================
BASE_DIR = resource_path("")
IS_BUNDLED = hasattr(sys, "_MEIPASS")

APP_NAME = "DLMS"
APP_DATA_DIR = get_app_data_dir(APP_NAME)

# DEBUG - retained for troubleshooting packaged/dev data-directory issues
# print("[BUILD CHECK] APP_DATA_DIR =", APP_DATA_DIR)



UPLOAD_FOLDER = os.path.join(APP_DATA_DIR, "uploads")
DATA_FOLDER = os.path.join(APP_DATA_DIR, "data")
QUIZ_FOLDER = os.path.join(APP_DATA_DIR, "quizzes")
CONFIG_FOLDER = os.path.join(APP_DATA_DIR, "config")
REGISTRY_FILE = os.path.join(APP_DATA_DIR, "config", "quizzes.json")

# Law Study module storage
LAW_FOLDER = os.path.join(APP_DATA_DIR, "law")
LAW_CASES_FOLDER = os.path.join(LAW_FOLDER, "cases")
LAW_IMPORTS_FOLDER = os.path.join(LAW_FOLDER, "imports")
LAW_EXPORTS_FOLDER = os.path.join(LAW_FOLDER, "exports")
LAW_REGISTRY = os.path.join(CONFIG_FOLDER, "law.json")

# App-data logos (used for temp storage / preview)
LOGO_FOLDER = os.path.join(APP_DATA_DIR, "static", "logos")
LOGO_TEMP_FOLDER = os.path.join(LOGO_FOLDER, "_temp")
os.makedirs(LOGO_TEMP_FOLDER, exist_ok=True)

# Flask-served logos (what the browser loads)
#STATIC_LOGO_FOLDER = os.path.join(app.root_path, "static", "logos")

BACKGROUND_FOLDER = os.path.join(APP_DATA_DIR, "static", "bg")
CONTENT_PACK_FOLDER = os.path.join(APP_DATA_DIR, "content_packs")
QUIZ_ASSET_FOLDER = os.path.join(APP_DATA_DIR, "quiz_assets")
IMAGE_BUILDER_DRAFT_FOLDER = os.path.join(APP_DATA_DIR, "image_builder_drafts")
PDF_IMPORT_DRAFT_FOLDER = os.path.join(APP_DATA_DIR, "pdf_import_drafts")
PDF_QUESTION_BANK_FOLDER = os.path.join(APP_DATA_DIR, "pdf_question_banks")
PDF_TERMINOLOGY_BANK_FOLDER = os.path.join(APP_DATA_DIR, "pdf_terminology_banks")
CONTENT_PACK_STAGING_FOLDER = os.path.join(APP_DATA_DIR, "content_pack_staging")
BACKUP_FOLDER = os.path.join(APP_DATA_DIR, "backups")
BACKUP_RESTORE_STAGING_FOLDER = os.path.join(BACKUP_FOLDER, "restore_staging")


for d in [
    UPLOAD_FOLDER,
    DATA_FOLDER,
    QUIZ_FOLDER,
    CONFIG_FOLDER,
    BACKGROUND_FOLDER,
    CONTENT_PACK_FOLDER,
    QUIZ_ASSET_FOLDER,
    IMAGE_BUILDER_DRAFT_FOLDER,
    PDF_IMPORT_DRAFT_FOLDER,
    PDF_QUESTION_BANK_FOLDER,
    PDF_TERMINOLOGY_BANK_FOLDER,
    CONTENT_PACK_STAGING_FOLDER,
    BACKUP_FOLDER,
    BACKUP_RESTORE_STAGING_FOLDER,
    LOGO_FOLDER,
    LAW_FOLDER,
    LAW_CASES_FOLDER,
    LAW_IMPORTS_FOLDER,
    LAW_EXPORTS_FOLDER,
    #STATIC_LOGO_FOLDER,
]:
    os.makedirs(d, exist_ok=True)


RASTER_IMAGE_FORMATS = {
    ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG",
    ".gif": "GIF", ".webp": "WEBP",
}
PASSIVE_PACK_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
# Browser-served runtime data contains generated quiz JSON plus plain-text parser
# logs. Other formats have no supported role beneath /data and must not cross a
# backup restore into that same-origin route.
BROWSER_SERVED_DATA_EXTENSIONS = frozenset({".json", ".txt"})
UPLOAD_STREAM_CHUNK_BYTES = 1024 * 1024
QUIZ_TEXT_UPLOAD_MAX_BYTES = 16 * 1024 * 1024
MATCHING_CSV_UPLOAD_MAX_BYTES = 16 * 1024 * 1024
RASTER_UPLOAD_MAX_BYTES = 32 * 1024 * 1024
LOGO_UPLOAD_MAX_BYTES = 16 * 1024 * 1024
IMAGE_BUILDER_TOTAL_UPLOAD_MAX_BYTES = 192 * 1024 * 1024
# Reserve 2 MB beneath the existing 300 MB request ceiling for multipart
# framing while preserving nearly all of the prior effective restore capacity.
BACKUP_UPLOAD_MAX_BYTES = 298 * 1024 * 1024
UPLOAD_MULTIPART_OVERHEAD_BYTES = 2 * 1024 * 1024

# 8K study images are about 33 MP. These limits allow substantially larger
# diagrams/photos while bounding decode memory and animated-image work.
IMAGE_MAX_PIXELS = 80_000_000
IMAGE_MAX_WIDTH = 16_000
IMAGE_MAX_HEIGHT = 16_000
IMAGE_MAX_FRAMES = 100


def _validate_custom_ai_url(value, *, browser_origin=None):
    """Return one safe absolute web URL or raise for an unsafe custom target."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Custom AI URL must be text")
    candidate = value.strip()
    if not candidate:
        return ""
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        raise ValueError("Custom AI URL contains unsupported control characters")
    if "\\" in candidate:
        raise ValueError("Custom AI URL contains an unsupported path separator")

    parsed = urlsplit(candidate)
    origin = _canonical_request_origin(candidate, allow_path=True)
    if origin is None or parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Custom AI URL must be an absolute HTTP or HTTPS URL")

    if browser_origin is None and has_request_context():
        browser_origin = _request_facing_origin()
    if browser_origin is not None and origin == browser_origin:
        raise ValueError("Custom AI URL must not point back to this DLMS instance")

    # A backup may have been created through a different loopback hostname than
    # the one used during restore. Reject that local DLMS origin as well, while
    # preserving local AI services on their own ports (for example :11434).
    dlms_port = int(globals().get("DLMS_SERVER_PORT", 9001))
    hostname = origin[1].rstrip(".")
    try:
        loopback_target = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback_target = hostname == "localhost" or hostname.endswith(".localhost")
    same_browser_host = browser_origin is not None and origin[1] == browser_origin[1]
    if (loopback_target or same_browser_host) and origin[2] == dlms_port:
        raise ValueError("Custom AI URL must not point back to this DLMS instance")

    return candidate


class UploadTooLargeError(ValueError):
    pass


def _bounded_save_upload(upload, destination_path, max_bytes, label="Uploaded file"):
    """Stream an upload to disk with a hard byte ceiling and failure cleanup."""
    declared = int(getattr(upload, "content_length", 0) or 0)
    if declared > max_bytes:
        raise UploadTooLargeError(f"{label} exceeds the {_format_bytes(max_bytes)} limit.")
    total = 0
    try:
        with open(destination_path, "wb") as destination:
            while True:
                chunk = upload.stream.read(UPLOAD_STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadTooLargeError(f"{label} exceeds the {_format_bytes(max_bytes)} limit.")
                destination.write(chunk)
        return total
    except Exception:
        try:
            os.remove(destination_path)
        except FileNotFoundError:
            pass
        raise


def _read_bounded_upload(upload, max_bytes, label="Uploaded file"):
    """Read a small upload into memory without allowing a lying length header."""
    output = io.BytesIO()
    total = 0
    declared = int(getattr(upload, "content_length", 0) or 0)
    if declared > max_bytes:
        raise UploadTooLargeError(f"{label} exceeds the {_format_bytes(max_bytes)} limit.")
    while True:
        chunk = upload.stream.read(min(UPLOAD_STREAM_CHUNK_BYTES, max_bytes + 1 - total))
        if not chunk:
            return output.getvalue()
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(f"{label} exceeds the {_format_bytes(max_bytes)} limit.")
        output.write(chunk)


def _decode_raster_image(path, allowed_extensions=None):
    """Fully decode a raster and ensure its bytes match its declared extension."""
    extension = os.path.splitext(path)[1].lower()
    allowed = set(allowed_extensions or RASTER_IMAGE_FORMATS)
    if extension not in allowed or extension not in RASTER_IMAGE_FORMATS:
        raise ValueError("unsupported image type; SVG and other active formats are not accepted")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                actual_format = str(image.format or "").upper()
                if actual_format != RASTER_IMAGE_FORMATS[extension]:
                    raise ValueError("image bytes do not match the filename extension")
                width, height = image.size
                if width > IMAGE_MAX_WIDTH or height > IMAGE_MAX_HEIGHT or width * height > IMAGE_MAX_PIXELS:
                    raise ValueError(
                        f"image dimensions exceed {IMAGE_MAX_WIDTH}×{IMAGE_MAX_HEIGHT} or {IMAGE_MAX_PIXELS:,} pixels"
                    )
                frame_count = int(getattr(image, "n_frames", 1) or 1)
                if frame_count > IMAGE_MAX_FRAMES:
                    raise ValueError(f"animated image exceeds the {IMAGE_MAX_FRAMES}-frame limit")
                frames = [frame.copy() for frame in ImageSequence.Iterator(image)]
                if not frames:
                    raise ValueError("image contains no decodable frames")
                metadata = {
                    "format": actual_format,
                    "size": image.size,
                    "duration": image.info.get("duration"),
                    "loop": image.info.get("loop", 0),
                }
                return frames, metadata
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("file is not a valid supported raster image") from exc


def _reencode_raster_file(source_path, destination_path, allowed_extensions=None):
    """Decode and atomically re-encode a raster, stripping non-image trailing data."""
    frames, metadata = _decode_raster_image(source_path, allowed_extensions)
    extension = os.path.splitext(destination_path)[1].lower()
    output_format = RASTER_IMAGE_FORMATS[extension]
    descriptor, temporary_path = tempfile.mkstemp(prefix=".dlms-image-", suffix=extension, dir=os.path.dirname(destination_path))
    os.close(descriptor)
    try:
        first = frames[0]
        options = {}
        if output_format == "JPEG":
            if first.mode not in {"RGB", "L"}:
                first = first.convert("RGB")
            options.update(quality=95, subsampling=0)
        elif output_format == "WEBP":
            options["lossless"] = True
        elif output_format == "GIF" and len(frames) > 1:
            options.update(save_all=True, append_images=frames[1:], loop=metadata["loop"])
            if metadata["duration"] is not None:
                options["duration"] = metadata["duration"]
        first.save(temporary_path, format=output_format, **options)
        _decode_raster_image(temporary_path, allowed_extensions)
        os.replace(temporary_path, destination_path)
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass


def _store_raster_upload(upload, destination_dir, filename, allowed_extensions=None, max_bytes=RASTER_UPLOAD_MAX_BYTES):
    """Store an uploaded image only after full decode and safe raster re-encoding."""
    filename = secure_filename(filename or "")
    extension = os.path.splitext(filename)[1].lower()
    allowed = set(allowed_extensions or RASTER_IMAGE_FORMATS)
    if not filename or extension not in allowed:
        raise ValueError("unsupported image type; use PNG, JPEG, GIF, or WebP as allowed by this workflow")
    os.makedirs(destination_dir, exist_ok=True)
    raw_descriptor, raw_path = tempfile.mkstemp(prefix=".dlms-upload-", suffix=extension, dir=destination_dir)
    os.close(raw_descriptor)
    destination_path = os.path.join(destination_dir, filename)
    try:
        consumed_bytes = _bounded_save_upload(upload, raw_path, max_bytes, "Image upload")
        upload._dlms_consumed_bytes = consumed_bytes
        _reencode_raster_file(raw_path, destination_path, allowed)
    finally:
        try:
            os.remove(raw_path)
        except FileNotFoundError:
            pass
    return filename




# =========================
# CONTENT PACK FRAMEWORK
# =========================
CONTENT_PACK_SCHEMA_VERSION = 1

def _safe_pack_child(pack_root, relative_path):
    return _content_pack_service._safe_pack_child(pack_root, relative_path)


def discover_content_packs():
    os.makedirs(CONTENT_PACK_FOLDER, exist_ok=True)
    return _content_pack_service.discover_content_packs(
        CONTENT_PACK_FOLDER,
        expected_schema_version=CONTENT_PACK_SCHEMA_VERSION,
    )


def get_content_pack(pack_id):
    return _content_pack_service.get_content_pack(
        pack_id,
        discover_content_packs=discover_content_packs,
    )


def load_content_pack_dataset(pack_id, dataset_id):
    return _content_pack_service.load_content_pack_dataset(
        pack_id,
        dataset_id,
        get_content_pack=get_content_pack,
        schema_version=CONTENT_PACK_SCHEMA_VERSION,
        safe_pack_child=_safe_pack_child,
        matching_record_validation_errors=_matching_record_validation_errors,
        set_content_pack_concepts=_set_content_pack_concepts,
        standalone_matching_concepts=_standalone_matching_concepts,
    )


def load_content_pack_image_dataset(pack_id, dataset_id):
    return _content_pack_service.load_content_pack_image_dataset(
        pack_id,
        dataset_id,
        get_content_pack=get_content_pack,
        schema_version=CONTENT_PACK_SCHEMA_VERSION,
        safe_pack_child=_safe_pack_child,
        decode_raster_image=_decode_raster_image,
        passive_pack_image_extensions=PASSIVE_PACK_IMAGE_EXTENSIONS,
        set_content_pack_concepts=_set_content_pack_concepts,
    )


def load_content_pack_quiz_dataset(pack_id, dataset_id):
    return _content_pack_service.load_content_pack_quiz_dataset(
        pack_id,
        dataset_id,
        get_content_pack=get_content_pack,
        schema_version=CONTENT_PACK_SCHEMA_VERSION,
        safe_pack_child=_safe_pack_child,
        decode_raster_image=_decode_raster_image,
        passive_pack_image_extensions=PASSIVE_PACK_IMAGE_EXTENSIONS,
        matching_comparison_key=_matching_comparison_key,
        matching_record_validation_errors=_matching_record_validation_errors,
        normalize_content_pack_choice_question=_normalize_content_pack_choice_question,
        set_content_pack_concepts=_set_content_pack_concepts,
    )


def _quiz_dataset_runtime(pack_id, data):
    images = {str(im.get("id")): im for im in (data.get("images") or []) if isinstance(im, dict)}
    runtime_questions, db_questions = [], []
    pack = data.get("_pack") or {}
    for raw in data.get("questions") or []:
        qtype = str(raw.get("type") or "choice").strip().lower()
        image = images.get(str(raw.get("image_id") or "").strip())
        source = (raw.get("source") if isinstance(raw.get("source"), dict) else {}) or \
                 ((image or {}).get("source") if isinstance((image or {}).get("source"), dict) else {}) or \
                 (data.get("source") if isinstance(data.get("source"), dict) else {})
        media = {}
        if image:
            media = {
                "image_url": url_for("content_pack_asset", pack_id=pack_id, asset_path=image.get("file")),
                "image_alt": image.get("alt_text") or data.get("title") or "Study image",
                "image_edits": image.get("edits") or [],
                "image_source": {
                    "organization": source.get("organization") or "",
                    "work": source.get("work") or "",
                    "url": source.get("url") or image.get("source_url") or "",
                    "license": source.get("license") or image.get("license") or "",
                    "attribution": source.get("attribution") or image.get("attribution") or "",
                },
            }
        common = {
            "type": qtype, "question": raw.get("question") or "",
            "explanation": raw.get("explanation") or "",
            "concepts": _content_pack_concepts(
                raw, context=f"quiz dataset question {raw.get('question')!r}"
            ),
            **media
        }
        db_source = {
            "organization": source.get("organization") or "",
            "dataset": source.get("dataset") or data.get("title") or "",
            "version": source.get("version") or pack.get("version") or "",
            "url": source.get("url") or "",
            "license": source.get("license") or "",
        }

        if qtype == "matching":
            pairs = []
            for pair in raw.get("pairs") or []:
                if not isinstance(pair, dict): continue
                left, right = str(pair.get("left") or "").strip(), str(pair.get("right") or "").strip()
                if left and right:
                    pairs.append({"left": left, "right": right})
            if len(pairs) < 2: continue
            runtime = {**common, "pairs": pairs, "round_size": raw.get("round_size"), "direction": raw.get("direction") or "term_to_definition"}
            db = {**runtime, "source": db_source, "media": media}
        elif qtype == "hotspot":
            if not image: continue
            hotspot_id = str(raw.get("hotspot_id") or "").strip()
            hotspot = next((h for h in (image.get("hotspots") or []) if isinstance(h, dict) and str(h.get("id") or "").strip() == hotspot_id), None)
            if not hotspot: continue
            label = str(hotspot.get("label") or raw.get("target_label") or "").strip()
            if not label: continue
            concepts = _hotspot_concepts(
                raw, image, hotspot, data,
                context=f"quiz dataset hotspot question {raw.get('question')!r}",
            )
            runtime = {**common, "type": "hotspot", "concepts": concepts, "target": hotspot.get("shape") or {}, "target_label": label, "verification": hotspot.get("verification") or {}}
            db = {
                "type": "choice", "question": (raw.get("question") or "") + " [Image hotspot]",
                "choices": [{"label": "A", "text": label, "is_correct": True}],
                "explanation": raw.get("explanation") or "", "concepts": concepts,
                "source": db_source, "media": media,
            }
        else:
            normalized = _normalize_content_pack_choice_question(
                raw,
                context=f"quiz dataset runtime choice question {raw.get('question')!r}",
            )
            choices = normalized["choices"]
            correct = [choice["label"] for choice in choices if choice["is_correct"]]
            runtime = {**common, "type": "choice", "choices": choices, "correct": correct}
            db = {**runtime, "source": db_source, "media": media}

        runtime_questions.append(runtime)
        db_questions.append(db)

    for n, q in enumerate(runtime_questions, 1): q["number"] = n
    for n, q in enumerate(db_questions, 1): q["number"] = n
    return runtime_questions, db_questions


def _quiz_publication_staging_root():
    return _quiz_publication_service.quiz_publication_staging_root(
        APP_DATA_DIR, join_path=os.path.join
    )


QUIZ_PUBLICATION_JOURNAL_MARKER = (
    _quiz_publication_service.QUIZ_PUBLICATION_JOURNAL_MARKER
)
QUIZ_PUBLICATION_JOURNAL_VERSION = (
    _quiz_publication_service.QUIZ_PUBLICATION_JOURNAL_VERSION
)
QUIZ_PUBLICATION_STATES = _quiz_publication_service.QUIZ_PUBLICATION_STATES
QUIZ_PUBLICATION_ID_RE = _quiz_publication_service.QUIZ_PUBLICATION_ID_RE
QUIZ_PUBLICATION_ARTIFACT_RE = _quiz_publication_service.QUIZ_PUBLICATION_ARTIFACT_RE
QUIZ_PUBLICATION_LOGO_RE = _quiz_publication_service.QUIZ_PUBLICATION_LOGO_RE


def _fsync_quiz_publication_directory(path):
    return _quiz_publication_service.fsync_quiz_publication_directory(
        path,
        open_descriptor=os.open,
        fsync=os.fsync,
        close_descriptor=os.close,
        read_only_flag=os.O_RDONLY,
    )


def _write_quiz_publication_journal(path, journal):
    return _quiz_publication_service.write_quiz_publication_journal(
        path,
        journal,
        fsync_directory=_fsync_quiz_publication_directory,
        open_file=open,
        json_module=json,
        fsync=os.fsync,
        replace_file=os.replace,
        dirname=os.path.dirname,
    )


def _update_quiz_publication_journal(path, journal, *, state=None):
    return _quiz_publication_service.update_quiz_publication_journal(
        path,
        journal,
        state=state,
        states=QUIZ_PUBLICATION_STATES,
        write_journal=_write_quiz_publication_journal,
        now=datetime.now,
    )


def _remove_quiz_publication_journal(path):
    return _quiz_publication_service.remove_quiz_publication_journal(
        path,
        fsync_directory=_fsync_quiz_publication_directory,
        lexists=os.path.lexists,
        islink=os.path.islink,
        remove_file=os.remove,
        dirname=os.path.dirname,
        print_message=print,
    )


def _quiz_publication_checkpoint(_stage, _journal):
    return _quiz_publication_service.quiz_publication_checkpoint(_stage, _journal)


def _write_staged_quiz_json(path, payload):
    return _quiz_artifact_renderer._write_staged_quiz_json(
        path,
        payload,
        open_file=open,
        json_module=json,
        fsync=os.fsync,
    )


def _commit_quiz_publication(conn):
    return _quiz_publication_service.commit_quiz_publication(conn)


def _promote_quiz_artifact(staged_path, final_path):
    return _quiz_publication_service.promote_quiz_artifact(
        staged_path,
        final_path,
        makedirs=os.makedirs,
        dirname=os.path.dirname,
        lexists=os.path.lexists,
        replace_file=os.replace,
    )


def _remove_quiz_publication_path(path):
    return _quiz_publication_service.remove_quiz_publication_path(
        path,
        isdir=os.path.isdir,
        islink=os.path.islink,
        remove_tree=shutil.rmtree,
        lexists=os.path.lexists,
        remove_file=os.remove,
        print_message=print,
    )


def _delete_published_quiz_rows(quiz_id):
    return _quiz_publication_service.delete_published_quiz_rows(
        quiz_id, get_db=get_db
    )


def _remove_exact_quiz_registry_entry(quiz_id, html_name):
    return _quiz_publication_service.remove_exact_quiz_registry_entry(
        quiz_id,
        html_name,
        registry_lock=registry_lock,
        load_registry=load_registry,
        save_registry=save_registry,
    )


def _safe_quiz_publication_name(value, *, label, pattern=None):
    return _quiz_publication_service.safe_quiz_publication_name(
        value,
        label=label,
        pattern=pattern,
        isabs=os.path.isabs,
        basename=os.path.basename,
    )


def _safe_quiz_publication_target(root, name, *, label):
    return _quiz_publication_service.safe_quiz_publication_target(
        root,
        name,
        label=label,
        app_data_dir=APP_DATA_DIR,
        canonical_data_root=_canonical_data_root,
        is_same_path_or_ancestor=_is_same_path_or_ancestor,
        abspath=os.path.abspath,
        realpath=os.path.realpath,
        lexists=os.path.lexists,
        islink=os.path.islink,
        join_path=os.path.join,
        dirname=os.path.dirname,
    )


def _validate_quiz_publication_journal(journal, journal_path):
    return _quiz_publication_service.validate_quiz_publication_journal(
        journal,
        journal_path,
        staging_root=_quiz_publication_staging_root,
        data_folder=DATA_FOLDER,
        quiz_folder=QUIZ_FOLDER,
        quiz_asset_folder=QUIZ_ASSET_FOLDER,
        logo_folder=LOGO_FOLDER,
        safe_name=_safe_quiz_publication_name,
        safe_target=_safe_quiz_publication_target,
        journal_marker=QUIZ_PUBLICATION_JOURNAL_MARKER,
        journal_version=QUIZ_PUBLICATION_JOURNAL_VERSION,
        states=QUIZ_PUBLICATION_STATES,
        publication_id_re=QUIZ_PUBLICATION_ID_RE,
        artifact_re=QUIZ_PUBLICATION_ARTIFACT_RE,
        logo_re=QUIZ_PUBLICATION_LOGO_RE,
        basename=os.path.basename,
        splitext=os.path.splitext,
    )


def _quiz_publication_db_status(journal):
    return _quiz_publication_service.quiz_publication_db_status(
        journal, get_db=get_db
    )


def _quiz_publication_registry_status(journal):
    return _quiz_publication_service.quiz_publication_registry_status(
        journal, load_registry=load_registry
    )


def _quiz_publication_artifacts_valid(journal, paths):
    return _quiz_publication_service.quiz_publication_artifacts_valid(
        journal,
        paths,
        open_file=open,
        json_module=json,
        isfile=os.path.isfile,
        getsize=os.path.getsize,
        isdir=os.path.isdir,
        islink=os.path.islink,
    )


def _delete_recorded_quiz_rows(journal):
    return _quiz_publication_service.delete_recorded_quiz_rows(
        journal, get_db=get_db
    )


def _rollback_recorded_quiz_publication(journal, paths):
    return _quiz_publication_service.rollback_recorded_quiz_publication(
        journal,
        paths,
        db_status=_quiz_publication_db_status,
        registry_status=_quiz_publication_registry_status,
        remove_registry_entry=_remove_exact_quiz_registry_entry,
        remove_path=_remove_quiz_publication_path,
        delete_rows=_delete_recorded_quiz_rows,
    )


def _reconcile_quiz_publication_journal(journal_path):
    return _quiz_publication_service.reconcile_quiz_publication_journal(
        journal_path,
        validate_journal=_validate_quiz_publication_journal,
        db_status=_quiz_publication_db_status,
        registry_status=_quiz_publication_registry_status,
        artifacts_valid=_quiz_publication_artifacts_valid,
        remove_path=_remove_quiz_publication_path,
        remove_journal=_remove_quiz_publication_journal,
        update_journal=_update_quiz_publication_journal,
        rollback_publication=_rollback_recorded_quiz_publication,
        open_file=open,
        json_module=json,
        islink=os.path.islink,
        print_message=print,
    )


def reconcile_quiz_publications():
    return _quiz_publication_service.reconcile_quiz_publications(
        app_data_dir=APP_DATA_DIR,
        read_data_root_marker=_read_data_root_marker,
        staging_root=_quiz_publication_staging_root,
        is_same_path_or_ancestor=_is_same_path_or_ancestor,
        canonical_data_root=_canonical_data_root,
        reconcile_journal=_reconcile_quiz_publication_journal,
        remove_journal=_remove_quiz_publication_journal,
        exists=os.path.exists,
        realpath=os.path.realpath,
        islink=os.path.islink,
        listdir=os.listdir,
        join_path=os.path.join,
        print_message=print,
    )


def _normalize_quiz_question_ordinals(runtime_questions, db_questions):
    return _quiz_publication_service.normalize_quiz_question_ordinals(
        runtime_questions, db_questions
    )


def _publish_quiz(
    quiz_title,
    runtime_questions,
    db_questions=None,
    *,
    filename_prefix="quiz",
    exam_minutes=90,
    logo_filename=None,
    source_file=None,
    source_pack_id=None,
    source_dataset_id=None,
    snapshot_existing_assets=False,
    rollback_logo_filename=None,
):
    return _quiz_publication_service.publish_quiz(
        quiz_title,
        runtime_questions,
        db_questions,
        filename_prefix=filename_prefix,
        exam_minutes=exam_minutes,
        logo_filename=logo_filename,
        source_file=source_file,
        source_pack_id=source_pack_id,
        source_dataset_id=source_dataset_id,
        snapshot_existing_assets=snapshot_existing_assets,
        rollback_logo_filename=rollback_logo_filename,
        generated_artifact_names=_generated_quiz_artifact_names,
        staging_root=_quiz_publication_staging_root,
        normalize_ordinals=_normalize_quiz_question_ordinals,
        write_journal=_write_quiz_publication_journal,
        remove_journal=_remove_quiz_publication_journal,
        fsync_directory=_fsync_quiz_publication_directory,
        checkpoint=_quiz_publication_checkpoint,
        snapshot_runtime_questions=_snapshot_runtime_questions,
        snapshot_existing_quiz_asset_refs=_snapshot_existing_quiz_asset_refs,
        write_staged_quiz_json=_write_staged_quiz_json,
        get_db=get_db,
        insert_quiz_rows=_insert_quiz_rows,
        update_journal=_update_quiz_publication_journal,
        build_quiz_html=build_quiz_html,
        get_portal_title=get_portal_title,
        normalize_exam_minutes=normalize_exam_minutes,
        commit_publication=_commit_quiz_publication,
        promote_artifact=_promote_quiz_artifact,
        add_quiz_to_registry=add_quiz_to_registry,
        remove_path=_remove_quiz_publication_path,
        remove_registry_entry=_remove_exact_quiz_registry_entry,
        delete_recorded_rows=_delete_recorded_quiz_rows,
        data_folder=DATA_FOLDER,
        quiz_folder=QUIZ_FOLDER,
        quiz_asset_folder=QUIZ_ASSET_FOLDER,
        logo_folder=LOGO_FOLDER,
        logo_re=QUIZ_PUBLICATION_LOGO_RE,
        token_hex=secrets.token_hex,
        splitext=os.path.splitext,
        makedirs=os.makedirs,
        mkdir=os.mkdir,
        join_path=os.path.join,
        isdir=os.path.isdir,
        isfile=os.path.isfile,
        getsize=os.path.getsize,
        basename=os.path.basename,
        now=datetime.now,
        print_message=print,
    )


def _create_quiz_from_runtime(quiz_title, runtime_questions, db_questions, filename_prefix="study_image", exam_minutes=90, source_pack_id=None, source_dataset_id=None):
    """Compatibility wrapper for existing runtime/database payload callers."""
    return _publish_quiz(
        quiz_title,
        runtime_questions,
        db_questions,
        filename_prefix=filename_prefix,
        exam_minutes=exam_minutes,
        source_pack_id=source_pack_id,
        source_dataset_id=source_dataset_id,
    )


def _generated_quiz_artifact_identity():
    return _quiz_artifact_renderer._generated_quiz_artifact_identity(
        time_ns=time.time_ns,
        token_hex=secrets.token_hex,
    )


def _generated_quiz_artifact_names(prefix):
    return _quiz_artifact_renderer._generated_quiz_artifact_names(
        prefix,
        artifact_identity=_generated_quiz_artifact_identity,
    )


@app.route("/content-packs/<pack_id>/assets/<path:asset_path>")
def content_pack_asset(pack_id, asset_path):
    """Serve a file from an installed content pack without allowing path traversal."""
    pack = get_content_pack(pack_id)
    if not pack:
        return "Content pack not found", 404

    try:
        file_path = _safe_pack_child(pack["_root"], asset_path)
    except ValueError:
        return "Invalid content-pack asset path", 400

    if not os.path.isfile(file_path):
        return "Content-pack asset not found", 404

    allowed = PASSIVE_PACK_IMAGE_EXTENSIONS
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in allowed:
        return "Unsupported content-pack asset type", 415
    try:
        _decode_raster_image(file_path, allowed)
    except ValueError:
        return "Invalid content-pack image", 415

    return send_from_directory(
        os.path.dirname(file_path),
        os.path.basename(file_path),
        conditional=True
    )



def _quiz_asset_url(bucket, relative_path):
    rel = str(relative_path or "").replace("\\", "/").lstrip("/")
    return f"/quiz-assets/{bucket}/{rel}"


def _snapshot_one_pack_asset(
    pack_id, asset_url, bucket, *, destination_root=None, created_assets=None
):
    return _content_pack_mutation_service._snapshot_one_pack_asset(
        pack_id,
        asset_url,
        bucket,
        destination_root=destination_root,
        created_assets=created_assets,
        get_content_pack=get_content_pack,
        safe_pack_child=_safe_pack_child,
        decode_raster_image=_decode_raster_image,
        passive_pack_image_extensions=PASSIVE_PACK_IMAGE_EXTENSIONS,
        quiz_asset_folder=QUIZ_ASSET_FOLDER,
        quiz_asset_url=_quiz_asset_url,
        copy_file=shutil.copy2,
        replace_file=os.replace,
    )


def _snapshot_pack_refs_recursive(
    pack_id, value, bucket, *, destination_root=None, created_assets=None
):
    return _content_pack_mutation_service._snapshot_pack_refs_recursive(
        pack_id,
        value,
        bucket,
        destination_root=destination_root,
        created_assets=created_assets,
        snapshot_one_pack_asset=_snapshot_one_pack_asset,
    )


def _cleanup_new_pack_migration_assets(created_assets):
    return _content_pack_mutation_service._cleanup_new_pack_migration_assets(
        created_assets, quiz_asset_folder=QUIZ_ASSET_FOLDER
    )


def _snapshot_runtime_questions(pack_id, runtime_questions, db_questions, bucket, *, destination_root=None):
    return _content_pack_mutation_service._snapshot_runtime_questions(
        pack_id,
        runtime_questions,
        db_questions,
        bucket,
        destination_root=destination_root,
        snapshot_pack_refs_recursive=_snapshot_pack_refs_recursive,
    )


@app.route("/quiz-assets/<asset_bucket>/<path:asset_path>")
def quiz_asset(asset_bucket, asset_path):
    """Serve quiz-owned snapshots independently of the source Study Pack."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,140}", str(asset_bucket or "")):
        return "Invalid quiz asset bucket", 400
    root = os.path.join(QUIZ_ASSET_FOLDER, asset_bucket)
    try:
        file_path = _safe_pack_child(root, asset_path)
    except ValueError:
        return "Invalid quiz asset path", 400
    if not os.path.isfile(file_path):
        return "Quiz asset not found", 404
    if os.path.splitext(file_path)[1].lower() not in PASSIVE_PACK_IMAGE_EXTENSIONS:
        return "Unsupported quiz asset", 415
    try:
        _decode_raster_image(file_path, PASSIVE_PACK_IMAGE_EXTENSIONS)
    except ValueError:
        return "Invalid quiz asset", 415
    # Keep the request path in URL/POSIX form. On Windows, os.path.relpath()
    # returns backslashes (for example ``images\\diagram.png``). Werkzeug's
    # send_from_directory() treats backslashes as unsafe alternate separators,
    # which can make otherwise valid quiz-owned Study Pack images return 404.
    # ``asset_path`` came from Flask's <path:...> converter and has already been
    # resolved/validated above with _safe_pack_child(), so pass its normalized
    # URL form directly to send_from_directory().
    safe_asset_path = str(asset_path or "").replace("\\", "/").lstrip("/")
    return send_from_directory(root, safe_asset_path, conditional=True)


def _snapshot_existing_pack_dependencies(pack_id):
    return _content_pack_mutation_service._snapshot_existing_pack_dependencies(
        pack_id,
        data_folder=DATA_FOLDER,
        snapshot_pack_refs_recursive=_snapshot_pack_refs_recursive,
        atomic_write_json=_atomic_write_json,
        get_db=get_db,
        cleanup_new_pack_migration_assets=_cleanup_new_pack_migration_assets,
        row_factory=sqlite3.Row,
    )


def _content_pack_tracked_quiz_count(pack_id):
    return _content_pack_service._content_pack_tracked_quiz_count(
        pack_id, load_registry()
    )


def _folder_size_bytes(path):
    return _content_pack_service._folder_size_bytes(path)


def _format_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024



CONTENT_PACK_UPLOAD_MAX_BYTES = 256 * 1024 * 1024
CONTENT_PACK_MULTIPART_OVERHEAD_BYTES = 2 * 1024 * 1024
CONTENT_PACK_IMPORT_MAX_FILES = 1000
CONTENT_PACK_IMPORT_MAX_UNCOMPRESSED = 512 * 1024 * 1024
CONTENT_PACK_IMPORT_MAX_SINGLE_FILE = 128 * 1024 * 1024
CONTENT_PACK_IMPORT_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")


def _content_pack_validation_record(name, status, detail):
    return _content_pack_service._content_pack_validation_record(
        name, status, detail
    )


def _matching_comparison_key(value, *, fold_case=True):
    return _content_pack_service._matching_comparison_key(
        value, fold_case=fold_case
    )


def _matching_case_only_term_warnings(
    records, *, context, left_key="term", record_name="item"
):
    return _content_pack_service._matching_case_only_term_warnings(
        records,
        context=context,
        left_key=left_key,
        record_name=record_name,
        matching_comparison_key=_matching_comparison_key,
    )


def _matching_record_validation_errors(
    records, *, context, left_key="term", right_key="definition", record_name="item"
):
    return _content_pack_service._matching_record_validation_errors(
        records,
        context=context,
        left_key=left_key,
        right_key=right_key,
        record_name=record_name,
        matching_comparison_key=_matching_comparison_key,
    )


def _content_pack_choice_question_errors(
    question, *, context, require_single_select=False
):
    return _content_pack_service._content_pack_choice_question_errors(
        question,
        context=context,
        require_single_select=require_single_select,
        matching_comparison_key=_matching_comparison_key,
    )


def _normalize_content_pack_choice_question(
    question, *, context, require_single_select=False
):
    return _content_pack_service._normalize_content_pack_choice_question(
        question,
        context=context,
        require_single_select=require_single_select,
        content_pack_choice_question_errors=_content_pack_choice_question_errors,
    )


def _content_pack_answer_position_concentration(questions):
    return _content_pack_service._content_pack_answer_position_concentration(
        questions
    )


def _randomize_staged_ai_answer_positions(pack_root, manifest):
    return _content_pack_mutation_service._randomize_staged_ai_answer_positions(
        pack_root,
        manifest,
        safe_pack_child=_safe_pack_child,
        answer_position_concentration=_content_pack_answer_position_concentration,
        rng_factory=random.SystemRandom,
        replace_file=os.replace,
    )


def _safe_zip_member_name(name):
    return _content_pack_service._safe_zip_member_name(name)


def _inspect_content_pack_zip(zip_path):
    return _content_pack_service._inspect_content_pack_zip(
        zip_path,
        max_files=CONTENT_PACK_IMPORT_MAX_FILES,
        max_uncompressed_bytes=CONTENT_PACK_IMPORT_MAX_UNCOMPRESSED,
        max_single_file_bytes=CONTENT_PACK_IMPORT_MAX_SINGLE_FILE,
        safe_zip_member_name=_safe_zip_member_name,
    )


def _extract_content_pack_zip(zip_path, stage_root):
    return _content_pack_mutation_service._extract_content_pack_zip(
        zip_path, stage_root, safe_zip_member_name=_safe_zip_member_name
    )


def _read_json_file(path, label, errors):
    return _content_pack_service._read_json_file(path, label, errors)


def _validate_staged_content_pack(
    pack_root, *, normalize_images=False, require_single_select=False
):
    normalized_image_paths = set()

    def validate_raster_image(image_path):
        if normalize_images and image_path not in normalized_image_paths:
            _reencode_raster_file(
                image_path, image_path, PASSIVE_PACK_IMAGE_EXTENSIONS
            )
            normalized_image_paths.add(image_path)
        else:
            _decode_raster_image(image_path, PASSIVE_PACK_IMAGE_EXTENSIONS)

    return _content_pack_service._validate_staged_content_pack(
        pack_root,
        require_single_select=require_single_select,
        expected_schema_version=CONTENT_PACK_SCHEMA_VERSION,
        safe_pack_child=_safe_pack_child,
        read_json_file=_read_json_file,
        validation_record=_content_pack_validation_record,
        matching_comparison_key=_matching_comparison_key,
        matching_record_validation_errors=_matching_record_validation_errors,
        matching_case_only_term_warnings=_matching_case_only_term_warnings,
        content_pack_choice_question_errors=_content_pack_choice_question_errors,
        content_pack_answer_position_concentration=_content_pack_answer_position_concentration,
        content_pack_concepts=_content_pack_concepts,
        standalone_matching_concepts=_standalone_matching_concepts,
        validate_hotspot_shape=_validate_hotspot_shape,
        validate_raster_image=validate_raster_image,
    )


def _content_pack_stage_path(token):
    return _content_pack_mutation_service._content_pack_stage_path(
        token,
        token_pattern=CONTENT_PACK_IMPORT_TOKEN_RE,
        staging_folder=CONTENT_PACK_STAGING_FOLDER,
    )


def _load_staged_content_pack(token):
    return _content_pack_mutation_service._load_staged_content_pack(
        token,
        content_pack_stage_path=_content_pack_stage_path,
        safe_pack_child=_safe_pack_child,
    )


def _remove_content_pack_stage(token):
    return _content_pack_mutation_service._remove_content_pack_stage(
        token,
        content_pack_stage_path=_content_pack_stage_path,
        remove_tree=shutil.rmtree,
    )


def content_pack_management_summary():
    return _content_pack_service.content_pack_management_summary(
        CONTENT_PACK_FOLDER,
        discover_content_packs=discover_content_packs,
        validate_staged_content_pack=_validate_staged_content_pack,
        content_pack_tracked_quiz_count=_content_pack_tracked_quiz_count,
        validation_record=_content_pack_validation_record,
        format_bytes=_format_bytes,
        folder_size_bytes=_folder_size_bytes,
        datetime_class=datetime,
    )


def _content_pack_folder_report(folder):
    return _content_pack_service._content_pack_folder_report(
        folder,
        CONTENT_PACK_FOLDER,
        validate_staged_content_pack=_validate_staged_content_pack,
        get_content_pack=get_content_pack,
        validation_record=_content_pack_validation_record,
        format_bytes=_format_bytes,
        content_pack_tracked_quiz_count=_content_pack_tracked_quiz_count,
        folder_size_bytes=_folder_size_bytes,
        datetime_class=datetime,
    )


def _is_medical_pack_manifest(pack_id, pack):
    return _content_pack_service._is_medical_pack_manifest(pack_id, pack)


def _medical_content_available(packs=None):
    return _content_pack_service._medical_content_available(
        packs,
        discover_content_packs=discover_content_packs,
        is_medical_pack_manifest=_is_medical_pack_manifest,
    )


def _normalized_content_domain(value):
    return _content_pack_service._normalized_content_domain(value)


def _is_it_pack_manifest(pack_id, pack):
    return _content_pack_service._is_it_pack_manifest(
        pack_id,
        pack,
        normalized_content_domain=_normalized_content_domain,
    )


def _it_content_available(packs=None):
    return _content_pack_service._it_content_available(
        packs,
        discover_content_packs=discover_content_packs,
        is_it_pack_manifest=_is_it_pack_manifest,
    )


def content_pack_summary():
    return _content_pack_service.content_pack_summary(
        discover_content_packs=discover_content_packs,
    )


@app.context_processor
def inject_content_pack_state():
    packs = discover_content_packs()
    return {
        "content_packs": packs,
        # Medical Study is a built-in DLMS capability. Medical content packs
        # are optional; this legacy template flag now means "show the feature."
        "medical_pack_installed": True,
        "medical_content_available": _medical_content_available(packs),
        "it_study_available": True,
        "it_content_available": _it_content_available(packs),
    }


PORTAL_CONFIG = os.path.join(CONFIG_FOLDER, "portal.json")
DEFAULT_THEME = "purple-gold"
QUIZ_REGISTRY = os.path.join(CONFIG_FOLDER, "quizzes.json")
DB_PATH = os.path.join(APP_DATA_DIR, "results.db")




DLMS_SCHEMA_VERSION = _database.DLMS_SCHEMA_VERSION
DLMS_LEGACY_SCHEMA_VERSION = _database.DLMS_LEGACY_SCHEMA_VERSION
DLMS_SCHEMA_COLUMNS = _database.DLMS_SCHEMA_COLUMNS
DLMS_SCHEMA_INDEXES = _database.DLMS_SCHEMA_INDEXES
DLMS_LEGACY_CORE_TABLES = _database.DLMS_LEGACY_CORE_TABLES
UnsupportedDatabaseSchemaVersionError = _database.UnsupportedDatabaseSchemaVersionError


def _database_table_names(conn):
    return _database._database_table_names(conn)


def _database_column_info(conn, table):
    return _database._database_column_info(conn, table)


def _create_current_database_schema(conn):
    init_sql_path = resource_path("init.sql")
    return _database._create_current_database_schema(
        conn,
        init_sql_path,
        debug_print=dprint,
    )


def _rebuild_legacy_missed_questions(conn, columns):
    return _database._rebuild_legacy_missed_questions(conn, columns)


def _migrate_schema_to_v2(conn):
    return _database._migrate_schema_to_v2(
        conn,
        database_column_info=_database_column_info,
        rebuild_legacy_missed_questions=_rebuild_legacy_missed_questions,
    )


DLMS_SCHEMA_MIGRATIONS = {2: _migrate_schema_to_v2}


def _read_database_schema_version(conn, tables):
    return _database._read_database_schema_version(
        conn,
        tables,
        database_column_info=_database_column_info,
    )


def _validate_current_database_schema(conn):
    return _database._validate_current_database_schema(
        conn,
        schema_columns=DLMS_SCHEMA_COLUMNS,
        schema_indexes=DLMS_SCHEMA_INDEXES,
        database_table_names=_database_table_names,
        database_column_info=_database_column_info,
    )


def _validate_bootstrap_target(db_path, require_owned_root):
    path = os.path.realpath(os.path.abspath(os.path.expanduser(db_path)))
    if not require_owned_root:
        return path
    root = _canonical_data_root(APP_DATA_DIR)
    if _read_data_root_marker(root) is None:
        raise RuntimeError("DLMS database bootstrap requires a verified application-data root")
    if not _is_same_path_or_ancestor(root, path):
        raise RuntimeError("DLMS database path escapes the verified application-data root")
    return path


def bootstrap_database(db_path=None, *, require_owned_root=True):
    """Create or migrate one DLMS database before normal connections are used."""
    target = _validate_bootstrap_target(db_path or DB_PATH, require_owned_root)
    return _database.bootstrap_database(
        target,
        schema_version=DLMS_SCHEMA_VERSION,
        legacy_schema_version=DLMS_LEGACY_SCHEMA_VERSION,
        legacy_core_tables=DLMS_LEGACY_CORE_TABLES,
        migrations=DLMS_SCHEMA_MIGRATIONS,
        create_current_schema=_create_current_database_schema,
        database_table_names=_database_table_names,
        read_schema_version=_read_database_schema_version,
        validate_current_schema=_validate_current_database_schema,
        sqlite_module=sqlite3,
    )







def ensure_db_initialized():
    """Compatibility wrapper for startup, reset, and tests that rebind DB_PATH."""
    dprint(f"[DB] ensure_db_initialized using DB_PATH = {DB_PATH}")
    return bootstrap_database(DB_PATH)


# =========================
# DATA SAFETY / BACKUP & RESTORE
# =========================
DLMS_BACKUP_SCHEMA_VERSION = 1
DLMS_BACKUP_MANIFEST = "DLMS_BACKUP_MANIFEST.json"
DLMS_BACKUP_DATA_PREFIX = "DLMS_DATA/"
DLMS_BACKUP_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
DLMS_BACKUP_MAX_FILES = 20000
DLMS_BACKUP_MAX_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
DLMS_BACKUP_MAX_COMPRESSED = DLMS_BACKUP_MAX_UNCOMPRESSED
DLMS_BACKUP_MAX_SINGLE_FILE = 768 * 1024 * 1024
DLMS_BACKUP_MAX_COMPRESSION_RATIO = 1000
DLMS_BACKUP_RATIO_MIN_UNCOMPRESSED = 16 * 1024 * 1024
DLMS_BACKUP_EXCLUDED_TOP_LEVEL = {
    ".restore_operations", "backups", "uploads", "content_pack_staging"
}
DLMS_BACKUP_CORE_DB_SCHEMA = {
    "quizzes": {"id", "title", "source_file"},
    "questions": {"id", "quiz_id", "question_number", "question_text"},
    "choices": {"id", "question_id", "label", "text", "is_correct"},
    "attempts": {"id", "quiz_id", "score", "total", "percent", "mode"},
    "attempt_answers": {"id", "attempt_id", "question_id", "was_correct"},
    "missed_questions": {"id", "attempt_id"},
}
DLMS_BACKUP_CRITICAL_JSON_TYPES = {
    "config/portal.json": dict,
    "config/quizzes.json": list,
    "config/law.json": dict,
}
RESTORE_FUTURE_SCHEMA_PUBLIC_ERROR = (
    "This backup uses a newer DLMS database schema and cannot be restored by this version."
)
RESTORE_STAGING_MARKER = "dlms-validated-restore-stage"
RESTORE_STAGING_VERSION = 1
RESTORE_STAGING_STATE_FILENAME = "restore-stage.json"
# A restore confirmation is normally completed in minutes. Keeping an
# abandoned validated archive for 24 hours gives an interrupted user ample
# time to return while preventing repeated large uploads from accumulating.
RESTORE_STAGING_STALE_SECONDS = 24 * 60 * 60
RESTORE_STAGING_MAX_CLEANUP_ENTRIES = 1000


RestoreFutureSchemaError = _restore_service.RestoreFutureSchemaError


def _ensure_runtime_data_dirs():
    """Recreate writable runtime directories after a restore or full reset."""
    for path in [
        UPLOAD_FOLDER, DATA_FOLDER, QUIZ_FOLDER, CONFIG_FOLDER, BACKGROUND_FOLDER,
        CONTENT_PACK_FOLDER, QUIZ_ASSET_FOLDER, IMAGE_BUILDER_DRAFT_FOLDER,
        PDF_IMPORT_DRAFT_FOLDER, PDF_QUESTION_BANK_FOLDER,
        PDF_TERMINOLOGY_BANK_FOLDER, CONTENT_PACK_STAGING_FOLDER, BACKUP_FOLDER,
        BACKUP_RESTORE_STAGING_FOLDER, LOGO_FOLDER, LOGO_TEMP_FOLDER, LAW_FOLDER,
        LAW_CASES_FOLDER, LAW_IMPORTS_FOLDER, LAW_EXPORTS_FOLDER,
    ]:
        os.makedirs(path, exist_ok=True)


def _backup_rel_is_excluded(rel_path):
    return _backup_service.backup_rel_is_excluded(
        rel_path,
        data_root_marker=DLMS_DATA_ROOT_MARKER,
        excluded_top_level=DLMS_BACKUP_EXCLUDED_TOP_LEVEL,
    )


def _backup_file_inventory():
    """Return stable runtime files to include in a portable DLMS backup."""
    return _backup_service.backup_file_inventory(
        APP_DATA_DIR,
        DB_PATH,
        rel_is_excluded=_backup_rel_is_excluded,
    )


def _backup_summary():
    return _backup_service.backup_summary(
        db_path=DB_PATH,
        content_pack_folder=CONTENT_PACK_FOLDER,
        pdf_question_bank_folder=PDF_QUESTION_BANK_FOLDER,
        pdf_terminology_bank_folder=PDF_TERMINOLOGY_BANK_FOLDER,
        load_registry=load_registry,
        sqlite_module=sqlite3,
    )


def _create_dlms_backup(label="manual"):
    """Create a portable ZIP snapshot without mutating the live data set."""
    return _backup_service.create_dlms_backup(
        label,
        ensure_runtime_data_dirs=_ensure_runtime_data_dirs,
        backup_folder=BACKUP_FOLDER,
        app_data_dir=APP_DATA_DIR,
        db_path=DB_PATH,
        app_version=APP_VERSION,
        backup_schema_version=DLMS_BACKUP_SCHEMA_VERSION,
        backup_manifest=DLMS_BACKUP_MANIFEST,
        backup_data_prefix=DLMS_BACKUP_DATA_PREFIX,
        file_inventory=_backup_file_inventory,
        summary=_backup_summary,
        now=datetime.now,
        platform=sys.platform,
        sqlite_module=sqlite3,
    )


def _safe_backup_member_name(name):
    return _backup_service.safe_backup_member_name(name)


def _validate_dlms_backup(zip_path):
    """Validate archive structure, CRCs, limits, and the DLMS backup manifest."""
    return _backup_service.validate_dlms_backup(
        zip_path,
        backup_manifest=DLMS_BACKUP_MANIFEST,
        backup_data_prefix=DLMS_BACKUP_DATA_PREFIX,
        backup_schema_version=DLMS_BACKUP_SCHEMA_VERSION,
        max_files=DLMS_BACKUP_MAX_FILES,
        max_uncompressed=DLMS_BACKUP_MAX_UNCOMPRESSED,
        max_compressed=DLMS_BACKUP_MAX_COMPRESSED,
        max_single_file=DLMS_BACKUP_MAX_SINGLE_FILE,
        max_compression_ratio=DLMS_BACKUP_MAX_COMPRESSION_RATIO,
        ratio_min_uncompressed=DLMS_BACKUP_RATIO_MIN_UNCOMPRESSED,
        rel_is_excluded=_backup_rel_is_excluded,
        safe_member_name=_safe_backup_member_name,
    )


def _extract_validated_backup(zip_path, target_root, report):
    return _backup_service.extract_validated_backup(
        zip_path,
        target_root,
        report,
        backup_data_prefix=DLMS_BACKUP_DATA_PREFIX,
        safe_member_name=_safe_backup_member_name,
    )


def _validate_restored_sqlite(path, relative_path="results.db"):
    """Validate a restored DLMS database without running writable migrations."""
    return _backup_service.validate_restored_sqlite(
        path,
        relative_path,
        core_db_schema=DLMS_BACKUP_CORE_DB_SCHEMA,
        sqlite_module=sqlite3,
    )


def _validate_restored_json(path, relative_path):
    return _backup_service.validate_restored_json(
        path,
        relative_path,
        critical_json_types=DLMS_BACKUP_CRITICAL_JSON_TYPES,
        raster_image_formats=RASTER_IMAGE_FORMATS,
    )


def _validate_restored_browser_data(staged_data_root):
    """Allow only the runtime JSON and parser logs served beneath /data."""
    return _backup_service.validate_restored_browser_data(
        staged_data_root,
        browser_served_data_extensions=BROWSER_SERVED_DATA_EXTENSIONS,
    )


def _normalize_restored_portal_custom_ai_url(staged_data_root):
    """Clear an unsafe optional AI URL without rejecting an otherwise safe backup."""
    return _backup_service.normalize_restored_portal_custom_ai_url(
        staged_data_root,
        validate_restored_json=_validate_restored_json,
        validate_custom_ai_url=_validate_custom_ai_url,
        atomic_write_json=_atomic_write_json,
    )


def _validate_restored_assets(staged_data_root):
    return _backup_service.validate_restored_assets(
        staged_data_root,
        raster_image_formats=RASTER_IMAGE_FORMATS,
        passive_pack_image_extensions=PASSIVE_PACK_IMAGE_EXTENSIONS,
        decode_raster_image=_decode_raster_image,
        validate_staged_content_pack=_validate_staged_content_pack,
    )


def _validate_backup_manifest_semantics(manifest, staged_data_root):
    return _backup_service.validate_backup_manifest_semantics(
        manifest,
        staged_data_root,
        backup_schema_version=DLMS_BACKUP_SCHEMA_VERSION,
    )


def _validate_staged_backup_semantics(staged_data_root, manifest):
    """Validate extracted backup data completely before any live-data mutation."""
    return _backup_service.validate_staged_backup_semantics(
        staged_data_root,
        manifest,
        validate_manifest_semantics=_validate_backup_manifest_semantics,
        validate_restored_sqlite=_validate_restored_sqlite,
        validate_restored_json=_validate_restored_json,
        validate_restored_browser_data=_validate_restored_browser_data,
        normalize_restored_portal_custom_ai_url=_normalize_restored_portal_custom_ai_url,
        validate_restored_assets=_validate_restored_assets,
    )
def _staged_restore_database_path(staged_data_root):
    return _restore_service.staged_restore_database_path(
        staged_data_root,
        is_same_path_or_ancestor=_is_same_path_or_ancestor,
    )


def _validate_current_restored_database(database_path):
    return _restore_service.validate_current_restored_database(
        database_path,
        validate_restored_sqlite=_validate_restored_sqlite,
        database_table_names=_database_table_names,
        read_database_schema_version=_read_database_schema_version,
        validate_current_database_schema=_validate_current_database_schema,
        schema_version=DLMS_SCHEMA_VERSION,
        sqlite_module=sqlite3,
    )


def _regenerate_staged_quiz_html(staged_data_root, database_path):
    return _restore_service.regenerate_staged_quiz_html(
        staged_data_root,
        database_path,
        validate_restored_json=_validate_restored_json,
        quiz_artifact_names=_quiz_artifact_names,
        build_quiz_html=build_quiz_html,
        is_same_path_or_ancestor=_is_same_path_or_ancestor,
        sqlite_module=sqlite3,
    )


def _prepare_staged_restore_database(staged_data_root):
    return _restore_service.prepare_staged_restore_database(
        staged_data_root,
        staged_database_path=_staged_restore_database_path,
        bootstrap_database=bootstrap_database,
        validate_current_restored_database=_validate_current_restored_database,
        regenerate_staged_quiz_html=_regenerate_staged_quiz_html,
        unsupported_schema_error=UnsupportedDatabaseSchemaVersionError,
        future_schema_error=RestoreFutureSchemaError,
        future_schema_public_error=RESTORE_FUTURE_SCHEMA_PUBLIC_ERROR,
        print_message=print,
    )

def _restore_staging_dir(token):
    return _backup_service.restore_staging_dir(
        token,
        token_pattern=DLMS_BACKUP_TOKEN_RE,
        restore_staging_folder=BACKUP_RESTORE_STAGING_FOLDER,
    )


def _stage_dlms_backup(upload, token, *, stage_dir=None):
    if stage_dir is None:
        stage_dir = _restore_staging_dir(token)
    return _backup_service.stage_backup_restore(
        upload,
        token,
        stage_dir=stage_dir,
        upload_max_bytes=BACKUP_UPLOAD_MAX_BYTES,
        bounded_save_upload=_bounded_save_upload,
        validate_backup=_validate_dlms_backup,
        extract_backup=_extract_validated_backup,
        validate_semantics=_validate_staged_backup_semantics,
        atomic_write_json=_atomic_write_json,
        staging_state_filename=RESTORE_STAGING_STATE_FILENAME,
        staging_marker=RESTORE_STAGING_MARKER,
        staging_version=RESTORE_STAGING_VERSION,
        now=datetime.now,
    )


def _restore_staging_root_for_cleanup():
    return _restore_service.restore_staging_root_for_cleanup(
        restore_staging_folder=BACKUP_RESTORE_STAGING_FOLDER,
        app_data_dir=APP_DATA_DIR,
        canonical_data_root=_canonical_data_root,
        is_same_path_or_ancestor=_is_same_path_or_ancestor,
    )


def _restore_stage_has_regular_file(stage_dir, filename):
    return _restore_service.restore_stage_has_regular_file(stage_dir, filename)


def _restore_stage_has_validated_report(stage_dir):
    return _restore_service.restore_stage_has_validated_report(
        stage_dir,
        has_regular_file=_restore_stage_has_regular_file,
        backup_schema_version=DLMS_BACKUP_SCHEMA_VERSION,
    )


def _restore_stage_has_valid_marker(stage_dir, token):
    return _restore_service.restore_stage_has_valid_marker(
        stage_dir,
        token,
        has_regular_file=_restore_stage_has_regular_file,
        state_filename=RESTORE_STAGING_STATE_FILENAME,
        marker=RESTORE_STAGING_MARKER,
        staging_version=RESTORE_STAGING_VERSION,
        has_validated_report=_restore_stage_has_validated_report,
    )


def _is_owned_validated_restore_stage(stage_dir, token):
    return _restore_service.is_owned_validated_restore_stage(
        stage_dir,
        token,
        staging_root_for_cleanup=_restore_staging_root_for_cleanup,
        has_valid_marker=_restore_stage_has_valid_marker,
        has_validated_report=_restore_stage_has_validated_report,
    )


def _restore_operation_state_exists():
    return _restore_service.restore_operation_state_exists(
        operation_root=_restore_operation_root,
    )


def _cancel_validated_restore_stage(token):
    return _restore_service.cancel_validated_restore_stage(
        token,
        restore_staging_dir=_restore_staging_dir,
        staging_root_for_cleanup=_restore_staging_root_for_cleanup,
        operation_state_exists=_restore_operation_state_exists,
        is_owned_stage=_is_owned_validated_restore_stage,
    )


def _cleanup_stale_restore_staging(*, now=None):
    return _restore_service.cleanup_stale_restore_staging(
        now=now,
        staging_root_for_cleanup=_restore_staging_root_for_cleanup,
        operation_state_exists=_restore_operation_state_exists,
        is_owned_stage=_is_owned_validated_restore_stage,
        cancel_stage=_cancel_validated_restore_stage,
        token_pattern=DLMS_BACKUP_TOKEN_RE,
        stale_seconds=RESTORE_STAGING_STALE_SECONDS,
        max_cleanup_entries=RESTORE_STAGING_MAX_CLEANUP_ENTRIES,
        print_message=print,
    )

def _validated_staged_restore_roots(staged_data_root):
    return _restore_service.validated_staged_restore_roots(
        staged_data_root,
        safe_name=_restore_operation_safe_name,
        data_root_marker=DLMS_DATA_ROOT_MARKER,
        excluded_top_level=DLMS_BACKUP_EXCLUDED_TOP_LEVEL,
    )


def _remove_live_restore_root(root_name):
    return _restore_service.remove_live_restore_root(
        root_name,
        safe_name=_restore_operation_safe_name,
        data_root_marker=DLMS_DATA_ROOT_MARKER,
        excluded_top_level=DLMS_BACKUP_EXCLUDED_TOP_LEVEL,
        app_data_dir=APP_DATA_DIR,
    )


def _apply_restored_data(staged_data_root):
    return _restore_service.apply_restored_data(
        staged_data_root,
        require_owned_root=_require_owned_app_data_root,
        validated_roots=_validated_staged_restore_roots,
        canonical_data_root=_canonical_data_root,
        app_data_dir=APP_DATA_DIR,
        db_path=DB_PATH,
        rel_is_excluded=_backup_rel_is_excluded,
        remove_live_root=_remove_live_restore_root,
        ensure_runtime_data_dirs=_ensure_runtime_data_dirs,
        ensure_db_initialized=ensure_db_initialized,
    )

RESTORE_OPERATION_JOURNAL_MARKER = "dlms-restore-operation"
RESTORE_OPERATION_JOURNAL_VERSION = 1
RESTORE_OPERATION_ID_RE = re.compile(r"^[a-f0-9]{32}$")
RESTORE_OPERATION_STATES = {
    "safety_backup_created",
    "live_apply_started",
    "live_apply_completed",
    "post_apply_validated",
    "reconciliation_completed",
    "complete",
    "rollback_pending",
    "rollback_started",
    "rollback_completed",
}
RESTORE_OPERATION_PRE_MUTATION_STATES = {"safety_backup_created"}
RESTORE_OPERATION_PRESERVE_STATES = {
    "reconciliation_completed", "complete", "rollback_completed"
}
RESTORE_OPERATION_LOCK = threading.RLock()


def _restore_operation_root():
    return _restore_service.restore_operation_root(APP_DATA_DIR)


def _restore_operation_checkpoint(_stage, _journal):
    return _restore_service.restore_operation_checkpoint(_stage, _journal)


def _write_restore_operation_journal(path, journal):
    return _restore_service.write_restore_operation_journal(
        path,
        journal,
        fsync_directory=_fsync_quiz_publication_directory,
    )


def _update_restore_operation_journal(path, journal, state):
    return _restore_service.update_restore_operation_journal(
        path,
        journal,
        state,
        states=RESTORE_OPERATION_STATES,
        write_journal=_write_restore_operation_journal,
        now=datetime.now,
    )


def _remove_restore_operation_journal(path):
    return _restore_service.remove_restore_operation_journal(
        path,
        fsync_directory=_fsync_quiz_publication_directory,
        print_message=print,
    )


def _restore_operation_safe_name(value, *, label, suffix=None):
    return _restore_service.restore_operation_safe_name(
        value,
        label=label,
        suffix=suffix,
        safe_name=_safe_quiz_publication_name,
    )


def _restore_operation_target(root, name, *, label):
    return _restore_service.restore_operation_target(
        root,
        name,
        label=label,
        safe_target=_safe_quiz_publication_target,
    )


def _validate_restore_operation_journal(journal, journal_path):
    return _restore_service.validate_restore_operation_journal(
        journal,
        journal_path,
        journal_marker=RESTORE_OPERATION_JOURNAL_MARKER,
        journal_version=RESTORE_OPERATION_JOURNAL_VERSION,
        operation_id_pattern=RESTORE_OPERATION_ID_RE,
        states=RESTORE_OPERATION_STATES,
        token_pattern=DLMS_BACKUP_TOKEN_RE,
        max_files=DLMS_BACKUP_MAX_FILES,
        data_root_marker=DLMS_DATA_ROOT_MARKER,
        excluded_top_level=DLMS_BACKUP_EXCLUDED_TOP_LEVEL,
        backup_folder=BACKUP_FOLDER,
        restore_staging_folder=BACKUP_RESTORE_STAGING_FOLDER,
        operation_root=_restore_operation_root,
        safe_name=_restore_operation_safe_name,
        safe_target=_restore_operation_target,
    )


def _new_restore_operation(
    token,
    safety_path,
    manifest=None,
    *,
    safety_manifest=None,
    restore_roots=None,
):
    return _restore_service.new_restore_operation(
        token,
        safety_path,
        manifest,
        safety_manifest=safety_manifest,
        restore_roots=restore_roots,
        lock=RESTORE_OPERATION_LOCK,
        require_owned_root=_require_owned_app_data_root,
        token_pattern=DLMS_BACKUP_TOKEN_RE,
        backup_folder=BACKUP_FOLDER,
        operation_root=_restore_operation_root,
        safe_name=_restore_operation_safe_name,
        safe_target=_restore_operation_target,
        journal_marker=RESTORE_OPERATION_JOURNAL_MARKER,
        journal_version=RESTORE_OPERATION_JOURNAL_VERSION,
        write_journal=_write_restore_operation_journal,
        checkpoint=_restore_operation_checkpoint,
        token_hex=secrets.token_hex,
        now=datetime.now,
    )


def _remove_recorded_restore_directory(path):
    return _restore_service.remove_recorded_restore_directory(path)


def _finish_restore_operation_cleanup(journal_path, paths, *, remove_stage=True):
    return _restore_service.finish_restore_operation_cleanup(
        journal_path,
        paths,
        remove_stage=remove_stage,
        remove_directory=_remove_recorded_restore_directory,
        remove_journal=_remove_restore_operation_journal,
    )


def _rollback_restore_operation(journal_path, journal, paths):
    return _restore_service.rollback_restore_operation(
        journal_path,
        journal,
        paths,
        update_journal=_update_restore_operation_journal,
        checkpoint=_restore_operation_checkpoint,
        remove_directory=_remove_recorded_restore_directory,
        validate_backup=_validate_dlms_backup,
        extract_backup=_extract_validated_backup,
        validate_semantics=_validate_staged_backup_semantics,
        prepare_database=_prepare_staged_restore_database,
        safe_target=_restore_operation_target,
        app_data_dir=APP_DATA_DIR,
        apply_data=_apply_restored_data,
        validate_current_database=_validate_current_restored_database,
        db_path=DB_PATH,
        reconcile_quiz_publications=reconcile_quiz_publications,
        finish_cleanup=_finish_restore_operation_cleanup,
    )


def _read_restore_operation_journal(path):
    return _restore_service.read_restore_operation_journal(
        path,
        validate_journal=_validate_restore_operation_journal,
    )


def _recover_one_restore_operation(journal_path, journal, paths):
    return _restore_service.recover_one_restore_operation(
        journal_path,
        journal,
        paths,
        pre_mutation_states=RESTORE_OPERATION_PRE_MUTATION_STATES,
        preserve_states=RESTORE_OPERATION_PRESERVE_STATES,
        finish_cleanup=_finish_restore_operation_cleanup,
        validate_current_database=_validate_current_restored_database,
        db_path=DB_PATH,
        rollback=_rollback_restore_operation,
    )


def reconcile_restore_operations():
    return _restore_service.reconcile_restore_operations(
        require_owned_root=_require_owned_app_data_root,
        operation_root=_restore_operation_root,
        app_data_dir=APP_DATA_DIR,
        canonical_data_root=_canonical_data_root,
        is_same_path_or_ancestor=_is_same_path_or_ancestor,
        read_journal=_read_restore_operation_journal,
        recover_one=_recover_one_restore_operation,
        print_message=print,
    )

# =========================
# SERVE RUNTIME LOGOS
# =========================
#@app.route("/static/logos/<path:filename>")
#def serve_runtime_logos(filename):
    #return send_from_directory(LOGO_FOLDER, filename)



def finalize_logo_from_request(app, ts, *, logo_file=None, temp_logo_name=None):
    """
    Finalizes a quiz logo from either:
      - a temp preview logo (_temp)
      - a direct upload
      - or no logo at all

    Final logos ALWAYS live in APP_DATA_DIR/static/logos
    """

    os.makedirs(LOGO_FOLDER, exist_ok=True)
    os.makedirs(LOGO_TEMP_FOLDER, exist_ok=True)

    temp_logo_name = (temp_logo_name or "").strip()

    # =========================
    # Case 1: Finalize preview logo
    # =========================
    if temp_logo_name and temp_logo_name.lower() != "none":
        src = os.path.join(LOGO_TEMP_FOLDER, temp_logo_name)

        if not os.path.exists(src):
            print("[LOGO WARNING] Temp logo missing:", src)
            return None

        ext = os.path.splitext(temp_logo_name)[1].lower()
        if ext not in RASTER_IMAGE_FORMATS:
            return None
        logo_filename = f"logo_{ts}_{secrets.token_hex(4)}{ext}"
        dst = os.path.join(LOGO_FOLDER, logo_filename)
        try:
            _reencode_raster_file(src, dst, RASTER_IMAGE_FORMATS)
        except ValueError:
            return None
        os.remove(src)
        assert os.path.exists(dst), f"Logo finalize invariant violated: {dst}"

        print(f"[LOGO] Finalized logo → {dst}")
        return logo_filename

    # =========================
    # Case 2: Direct upload
    # =========================
    if logo_file and logo_file.filename:
        ext = os.path.splitext(logo_file.filename)[1].lower()
        if ext in RASTER_IMAGE_FORMATS:
            logo_filename = f"logo_{ts}_{secrets.token_hex(4)}{ext}"
            try:
                _store_raster_upload(logo_file, LOGO_FOLDER, logo_filename, RASTER_IMAGE_FORMATS, LOGO_UPLOAD_MAX_BYTES)
            except ValueError:
                return None

            print(f"[LOGO] Uploaded logo → {os.path.join(LOGO_FOLDER, logo_filename)}")
            return logo_filename

    # =========================
    # Case 3: No logo supplied
    # =========================
    return None




def save_preview_logo(app, logo_file):
    """
    Saves a temporary preview logo for paste preview.
    Preview logos live ONLY in APP_DATA_DIR/static/logos/_temp
    """

    if not logo_file or not logo_file.filename:
        return None

    ext = os.path.splitext(logo_file.filename)[1].lower()
    if ext not in RASTER_IMAGE_FORMATS:
        return None

    os.makedirs(LOGO_TEMP_FOLDER, exist_ok=True)

    name = f"temp_{int(time.time())}{ext}"
    try:
        _store_raster_upload(logo_file, LOGO_TEMP_FOLDER, name, RASTER_IMAGE_FORMATS, LOGO_UPLOAD_MAX_BYTES)
    except ValueError:
        return None

    print(f"[LOGO PREVIEW] Saved temp logo → {os.path.join(LOGO_TEMP_FOLDER, name)}")
    return name




@app.route("/help/")
def help_index():
    return send_from_directory("static", "help.html")

@app.route("/help/about")
def help_about():
    return send_from_directory("static", "about.html")

@app.route("/help/quiz-help")
def help_quiz():
    return send_from_directory("static", "quiz-help.html")

@app.route("/help/advanced-features")
def help_advanced():
    return send_from_directory("static", "advanced-features.html")

HELP_TOPIC_FILES = {
    "getting-started": "help-getting-started.html",
    "quizzes": "help-quizzes.html",
    "build-quiz": "help-build-quiz.html",
    "smart-pdf": "help-smart-pdf.html",
    "study-packs": "help-study-packs.html",
    "study-modules": "help-study-modules.html",
    "content-management": "help-content-management.html",
    "history-analytics": "help-history-analytics.html",
    "learning-intelligence": "help-learning-intelligence.html",
    "anki": "help-anki.html",
    "settings": "help-settings.html",
    "maintenance": "help-maintenance.html",
    "troubleshooting": "help-troubleshooting.html",
}

@app.route("/help/<topic>")
def help_topic(topic):
    filename = HELP_TOPIC_FILES.get(str(topic or "").strip().lower())
    if not filename:
        return "Help topic not found", 404
    return send_from_directory("static", filename)

@app.route("/regex-help")
@app.route("/regex-help/")
def regex_help():
    return send_from_directory(app.static_folder, "regex-help.html")


@app.route("/user-static/<path:filename>")
def user_static(filename):
    normalized = str(filename or "").replace("\\", "/").lstrip("/")
    if not normalized.startswith("logos/"):
        return "Unsupported user asset", 415
    root = os.path.join(APP_DATA_DIR, "static")
    try:
        file_path = _safe_pack_child(root, normalized)
        if not os.path.isfile(file_path):
            return "User image not found", 404
        _decode_raster_image(file_path, RASTER_IMAGE_FORMATS)
    except ValueError:
        return "Invalid user image", 415
    return send_from_directory(
        root,
        normalized
    )

def _settings_shell_sidebar(label="Settings"):
    """Minimal sidebar seed populated by the canonical navigation normalizer."""
    return f"""
<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark" aria-hidden="true">⚙</div>
        <div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div>
    </div>
    <nav class="dashboard-nav" aria-label="Primary navigation">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
    </nav>
    <div class="dashboard-sidebar-version">{html.escape(label)}</div>
</aside>"""


app.jinja_env.globals["settings_shell_sidebar"] = _settings_shell_sidebar


@app.route("/admin/maintenance")
def admin_maintenance():
    return render_template("admin/maintenance.html")




# =========================
# HOTSPOT CALIBRATION EDITOR
# =========================
def _hotspot_editor_catalog():
    catalog = []
    for pack_id, pack in discover_content_packs().items():
        for kind, key in (("hotspot", "image_datasets"), ("quiz", "quiz_datasets")):
            for descriptor in (pack.get(key) or []):
                dataset_id = str(descriptor.get("id") or "").strip()
                if not dataset_id:
                    continue
                try:
                    data = load_content_pack_image_dataset(pack_id, dataset_id) if kind == "hotspot" else load_content_pack_quiz_dataset(pack_id, dataset_id)
                except Exception as exc:
                    print(f"[IMAGE EDITOR] Unable to load {pack_id}/{kind}/{dataset_id}: {exc}")
                    continue
                images = data.get("images") or []
                if not images:
                    continue
                catalog.append({
                    "pack_id": pack_id,
                    "pack_name": pack.get("name") or pack_id,
                    "dataset_id": dataset_id,
                    "dataset_kind": kind,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "images": len(images),
                    "hotspots": sum(len(im.get("hotspots") or []) for im in images if isinstance(im, dict)),
                })
    return catalog


def _validate_hotspot_shape(shape):
    if not isinstance(shape, dict):
        raise ValueError("Shape must be an object")
    shape_type = str(shape.get("type") or "").strip().lower()
    if shape_type == "circle":
        x = float(shape.get("x")); y = float(shape.get("y")); radius = float(shape.get("radius"))
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < radius <= 0.5):
            raise ValueError("Circle coordinates must be normalized and radius must be > 0")
        return {"type":"circle","x":round(x,6),"y":round(y,6),"radius":round(radius,6)}
    if shape_type == "polygon":
        points = shape.get("points")
        if not isinstance(points, list) or len(points) < 3:
            raise ValueError("Polygon needs at least three points")
        cleaned=[]
        for point in points:
            if not isinstance(point,(list,tuple)) or len(point)!=2:
                raise ValueError("Each polygon point must contain x and y")
            x,y=float(point[0]),float(point[1])
            if not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError("Polygon coordinates must be normalized from 0 to 1")
            cleaned.append([round(x,6),round(y,6)])
        return {"type":"polygon","points":cleaned}
    raise ValueError("Shape type must be circle or polygon")


@app.route("/admin/image-editor")
@app.route("/admin/hotspots")
def admin_hotspot_editor():
    catalog = _hotspot_editor_catalog()
    selected_pack = request.args.get("pack", "").strip()
    selected_dataset = request.args.get("dataset", "").strip()
    selected_kind = request.args.get("kind", "").strip().lower()
    if selected_kind not in {"hotspot", "quiz"}:
        selected_kind = ""
    if (not selected_pack or not selected_dataset) and catalog:
        selected_pack = catalog[0]["pack_id"]
        selected_dataset = catalog[0]["dataset_id"]
        selected_kind = catalog[0]["dataset_kind"]
    if not selected_kind and selected_pack and selected_dataset:
        match = next((c for c in catalog if c["pack_id"] == selected_pack and c["dataset_id"] == selected_dataset), None)
        selected_kind = (match or {}).get("dataset_kind") or "hotspot"

    editor_data = None
    load_error = None
    if selected_pack and selected_dataset:
        try:
            data = load_content_pack_quiz_dataset(selected_pack, selected_dataset) if selected_kind == "quiz" else load_content_pack_image_dataset(selected_pack, selected_dataset)
            images = []
            for image in data.get("images") or []:
                images.append({
                    "id": image.get("id") or image.get("file"),
                    "file": image.get("file") or "",
                    "url": url_for("content_pack_asset", pack_id=selected_pack, asset_path=image.get("file")),
                    "alt_text": image.get("alt_text") or data.get("title") or "Study image",
                    "hotspots": image.get("hotspots") or [],
                    "edits": image.get("edits") or [],
                })
            editor_data = {
                "pack_id": selected_pack, "dataset_id": selected_dataset,
                "dataset_kind": selected_kind, "title": data.get("title") or selected_dataset,
                "images": images,
            }
        except Exception as exc:
            print(f"[IMAGE EDITOR LOAD ERROR] {type(exc).__name__}: {exc}")
            load_error = "The selected image dataset could not be loaded. Check the local DLMS log for details."
    return render_template_string(
        HOTSPOT_EDITOR_TEMPLATE,
        catalog=catalog, selected_pack=selected_pack, selected_dataset=selected_dataset,
        selected_kind=selected_kind, editor_data=editor_data, load_error=load_error,
        medical_pack_installed=True,
    )


@app.route("/admin/image-editor/hotspot/save", methods=["POST"])
@app.route("/admin/hotspots/save", methods=["POST"])
def admin_hotspot_save():
    payload=request.get_json(force=True) or {}
    pack_id=str(payload.get("pack_id") or "").strip().lower()
    dataset_id=str(payload.get("dataset_id") or "").strip()
    image_id=str(payload.get("image_id") or "").strip()
    hotspot_id=str(payload.get("hotspot_id") or "").strip()
    try:
        shape=_validate_hotspot_shape(payload.get("shape"))
        pack=get_content_pack(pack_id)
        if not pack: raise FileNotFoundError("Content pack is not installed")
        dataset_kind=str(payload.get("dataset_kind") or "hotspot").strip().lower()
        descriptor_key="quiz_datasets" if dataset_kind=="quiz" else "image_datasets"
        descriptor=next((d for d in (pack.get(descriptor_key) or []) if isinstance(d,dict) and str(d.get("id") or "").strip()==dataset_id),None)
        if not descriptor: raise KeyError("Image-capable dataset is not declared by this pack")
        dataset_path=_safe_pack_child(pack["_root"],str(descriptor.get("path") or "").strip())
        with open(dataset_path,"r",encoding="utf-8") as f: data=json.load(f)
        target_image=next((im for im in (data.get("images") or []) if str(im.get("id") or im.get("file") or "")==image_id),None)
        if not target_image: raise KeyError("Image record not found")
        target_hotspot=next((h for h in (target_image.get("hotspots") or []) if str(h.get("id") or "")==hotspot_id),None)
        if not target_hotspot: raise KeyError("Hotspot record not found")
        backup_path=dataset_path+".pre_editor.bak"
        backup_created=False
        if not os.path.exists(backup_path): shutil.copy2(dataset_path,backup_path); backup_created=True
        target_hotspot["shape"]=shape
        target_hotspot["calibration"]={"tool":"DLMS Image Study Editor","updated_at":datetime.now().isoformat(timespec="seconds")}
        tmp_path=dataset_path+".tmp"
        with open(tmp_path,"w",encoding="utf-8") as f:
            json.dump(data,f,indent=2,ensure_ascii=False); f.write("\n")
        os.replace(tmp_path,dataset_path)
        return jsonify({"ok":True,"shape":shape,"backup_created":backup_created})
    except Exception as exc:
        print(f"[IMAGE EDITOR HOTSPOT SAVE ERROR] {type(exc).__name__}: {exc}")
        return jsonify({"error": "The hotspot could not be saved. Verify the selected dataset and geometry."}), 400


@app.route("/admin/image-editor/edits/save", methods=["POST"])
def admin_image_edits_save():
    """Persist non-destructive study-image masks and text labels in the image dataset JSON."""
    payload = request.get_json(force=True) or {}
    pack_id = str(payload.get("pack_id") or "").strip().lower()
    dataset_id = str(payload.get("dataset_id") or "").strip()
    image_id = str(payload.get("image_id") or "").strip()
    edits = payload.get("edits") or []
    try:
        if not isinstance(edits, list) or len(edits) > 200:
            raise ValueError("Image edits must be a list of at most 200 items")
        cleaned = []
        for raw in edits:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("type") or "").strip().lower()
            if kind == "mask":
                x=float(raw.get("x")); y=float(raw.get("y")); w=float(raw.get("w")); h=float(raw.get("h"))
                style=str(raw.get("style") or "blur").strip().lower()
                if style not in {"blur","white","black"}: style="blur"
                if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1 and x+w <= 1.001 and y+h <= 1.001):
                    raise ValueError("Mask rectangle must use normalized coordinates inside the image")
                cleaned.append({"type":"mask","x":round(x,6),"y":round(y,6),"w":round(w,6),"h":round(h,6),"style":style})
            elif kind == "text":
                x=float(raw.get("x")); y=float(raw.get("y")); text=str(raw.get("text") or "").strip()
                size=int(raw.get("size") or 18)
                tone=str(raw.get("tone") or "light").strip().lower()
                if tone not in {"light","dark"}: tone="light"
                if not text: raise ValueError("Text label cannot be empty")
                if len(text) > 180: raise ValueError("Text label is too long")
                if not (0 <= x <= 1 and 0 <= y <= 1): raise ValueError("Text position must be normalized")
                size=max(10,min(size,48))
                cleaned.append({"type":"text","x":round(x,6),"y":round(y,6),"text":text,"size":size,"tone":tone})
            else:
                raise ValueError("Unsupported image edit type")

        pack=get_content_pack(pack_id)
        if not pack: raise FileNotFoundError("Content pack is not installed")
        dataset_kind=str(payload.get("dataset_kind") or "hotspot").strip().lower()
        descriptor_key="quiz_datasets" if dataset_kind=="quiz" else "image_datasets"
        descriptor=next((d for d in (pack.get(descriptor_key) or []) if isinstance(d,dict) and str(d.get("id") or "").strip()==dataset_id),None)
        if not descriptor: raise KeyError("Image-capable dataset is not declared by this pack")
        dataset_path=_safe_pack_child(pack["_root"],str(descriptor.get("path") or "").strip())
        with open(dataset_path,"r",encoding="utf-8") as f: data=json.load(f)
        target_image=next((im for im in (data.get("images") or []) if isinstance(im,dict) and str(im.get("id") or im.get("file") or "")==image_id),None)
        if not target_image: raise KeyError("Image record not found")
        backup_path=dataset_path+".pre_editor.bak"
        backup_created=False
        if not os.path.exists(backup_path): shutil.copy2(dataset_path,backup_path); backup_created=True
        target_image["edits"] = cleaned
        target_image["edit_metadata"] = {"tool":"DLMS Image Study Editor","updated_at":datetime.now().isoformat(timespec="seconds"),"non_destructive":True}
        tmp_path=dataset_path+".tmp"
        with open(tmp_path,"w",encoding="utf-8") as f:
            json.dump(data,f,indent=2,ensure_ascii=False); f.write("\n")
        os.replace(tmp_path,dataset_path)
        return jsonify({"ok":True,"edits":cleaned,"backup_created":backup_created})
    except Exception as exc:
        print(f"[IMAGE EDITOR PREP SAVE ERROR] {type(exc).__name__}: {exc}")
        return jsonify({"error": "The image preparation changes could not be saved. Verify the submitted edits."}), 400


HOTSPOT_EDITOR_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Image Study Editor - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home hotspot-editor-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar">
<div class="dashboard-brand"><div class="dashboard-brand-mark">◎</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div>
<nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>{% if medical_pack_installed %}<a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>{% endif %}</nav>
<div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item active" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a></nav><div class="dashboard-sidebar-version">Image Study Editor</div></aside>
<main class="dashboard-main hotspot-editor-main"><header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="build-eyebrow">MAINTENANCE · IMAGE STUDY</div><h1>Image Study Editor</h1><p>Prepare study images without altering the original file: mask unwanted text, add simple labels, and calibrate clickable regions for image-based quizzes.</p></div></header>
<section class="dashboard-panel hotspot-editor-picker"><form method="GET" action="/admin/image-editor"><label><span>Installed image dataset</span><select id="datasetKey">{% for item in catalog %}<option value="{{ item.pack_id }}::{{ item.dataset_kind }}::{{ item.dataset_id }}" {% if item.pack_id == selected_pack and item.dataset_id == selected_dataset and item.dataset_kind == selected_kind %}selected{% endif %}>{{ item.pack_name }} — {{ item.title }}{% if item.dataset_kind == 'quiz' %} · Question Set{% endif %}</option>{% endfor %}</select></label><input type="hidden" name="pack" id="packField" value="{{ selected_pack }}"><input type="hidden" name="kind" id="kindField" value="{{ selected_kind }}"><input type="hidden" name="dataset" id="datasetField" value="{{ selected_dataset }}"><button type="submit">Load Dataset</button></form>{% if load_error %}<div class="flash error">{{ load_error }}</div>{% endif %}{% if not catalog %}<p>No installed content pack currently declares an image dataset.</p>{% endif %}</section>
{% if editor_data %}<section class="dashboard-panel hotspot-editor-workspace">
<div class="image-editor-mode-tabs"><button type="button" id="hotspotModeBtn" class="active">Clickable Regions</button><button type="button" id="prepModeBtn">Image Prep</button></div>
<div class="hotspot-editor-toolbar"><label><span>Image</span><select id="imageSelect"></select></label><label class="hotspot-only"><span>Target / Structure</span><select id="hotspotSelect"></select></label><label class="hotspot-only"><span>Shape</span><select id="shapeMode"><option value="polygon">Polygon</option><option value="circle">Circle</option></select></label><label class="hotspot-only" id="radiusControl"><span>Circle radius <strong id="radiusValue">0.050</strong></span><input id="circleRadius" type="range" min="0.01" max="0.30" step="0.005" value="0.05"></label></div>
<div id="hotspotPanel"><div class="hotspot-editor-actions"><button type="button" id="loadExistingBtn">Load Existing</button><button type="button" id="undoBtn">Undo Point</button><button type="button" id="clearBtn">Clear Shape</button><button type="button" id="testBtn">Test Shape</button><button type="button" id="saveBtn" class="build-primary-button">Save Region</button></div><p class="hotspot-editor-help">Polygon: click around the true clickable boundary. Circle: click the center and adjust the radius.</p></div>
<div id="prepPanel" hidden><div class="image-prep-controls"><label><span>Prep tool</span><select id="prepTool"><option value="mask">Hide / cover text</option><option value="text">Add text label</option></select></label><label id="maskStyleLabel"><span>Cover style</span><select id="maskStyle"><option value="blur">Blur</option><option value="white">White box</option><option value="black">Black box</option></select></label><label id="maskWidthLabel"><span>Width <strong id="maskWVal">0.18</strong></span><input id="maskW" type="range" min="0.03" max="0.60" step="0.01" value="0.18"></label><label id="maskHeightLabel"><span>Height <strong id="maskHVal">0.07</strong></span><input id="maskH" type="range" min="0.02" max="0.35" step="0.01" value="0.07"></label><label id="textValueLabel" hidden><span>Text</span><input id="textValue" type="text" maxlength="180" placeholder="Label text"></label><label id="textSizeLabel" hidden><span>Text size</span><input id="textSize" type="number" min="10" max="48" value="18"></label><label id="textToneLabel" hidden><span>Label style</span><select id="textTone"><option value="light">Light</option><option value="dark">Dark</option></select></label></div><div class="hotspot-editor-actions"><button type="button" id="undoEditBtn">Undo Last Edit</button><button type="button" id="clearEditsBtn">Clear Image Edits</button><button type="button" id="saveEditsBtn" class="build-primary-button">Save Image Prep</button></div><p class="hotspot-editor-help">Edits are non-destructive overlays stored in the content-pack JSON. The original source image is never modified.</p></div>
<div class="hotspot-editor-stage"><img id="editorImage" alt="Study image" draggable="false"><div id="editorOverlay" class="image-edit-overlay"></div><svg id="editorSvg" viewBox="0 0 1000 1000" preserveAspectRatio="none"><polygon id="polygonShape"></polygon><circle id="circleShape"></circle><g id="pointHandles"></g></svg><div id="testMarker" class="hotspot-editor-test-marker" hidden></div></div><div class="hotspot-editor-status" id="editorStatus">Choose an image and editing mode.</div><details class="hotspot-editor-json"><summary>Current geometry / image-prep metadata</summary><pre id="geometryPreview">{}</pre></details></section>{% endif %}
<div class="review-return-row"><a class="review-return-link" href="/admin/maintenance">← System Tools</a></div></main></div>
<script>
const EDITOR_DATA={{ editor_data|tojson }};let currentImage=null,currentHotspot=null,points=[],circleCenter=null,testMode=false,editorMode='hotspot',imageEdits=[];
const imageSelect=document.getElementById('imageSelect'),hotspotSelect=document.getElementById('hotspotSelect'),shapeMode=document.getElementById('shapeMode'),radius=document.getElementById('circleRadius'),radiusValue=document.getElementById('radiusValue'),img=document.getElementById('editorImage'),poly=document.getElementById('polygonShape'),circle=document.getElementById('circleShape'),handles=document.getElementById('pointHandles'),statusEl=document.getElementById('editorStatus'),preview=document.getElementById('geometryPreview'),marker=document.getElementById('testMarker'),overlay=document.getElementById('editorOverlay');
function esc(s){return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;')}
function setStatus(t,k=''){statusEl.textContent=t;statusEl.className='hotspot-editor-status '+k}
function currentShape(){if(shapeMode.value==='circle'){if(!circleCenter)return null;return {type:'circle',x:circleCenter[0],y:circleCenter[1],radius:Number(radius.value)}}return points.length>=3?{type:'polygon',points:points}:null}
function renderEdits(){overlay.innerHTML='';imageEdits.forEach((e,i)=>{const d=document.createElement('div');d.className='image-edit-item '+(e.type==='mask'?'mask '+(e.style||'blur'):'text '+(e.tone||'light'));d.dataset.index=i;if(e.type==='mask'){d.style.left=`${e.x*100}%`;d.style.top=`${e.y*100}%`;d.style.width=`${e.w*100}%`;d.style.height=`${e.h*100}%`}else{d.style.left=`${e.x*100}%`;d.style.top=`${e.y*100}%`;d.style.fontSize=`${e.size||18}px`;d.textContent=e.text||''}overlay.appendChild(d)})}
function draw(){const s=currentShape();preview.textContent=JSON.stringify(editorMode==='hotspot'?(s||{}):imageEdits,null,2);poly.setAttribute('points','');circle.setAttribute('r','0');handles.innerHTML='';if(editorMode==='hotspot'){if(shapeMode.value==='polygon'&&points.length){poly.setAttribute('points',points.map(p=>`${p[0]*1000},${p[1]*1000}`).join(' '));points.forEach(p=>{const c=document.createElementNS('http://www.w3.org/2000/svg','circle');c.setAttribute('cx',p[0]*1000);c.setAttribute('cy',p[1]*1000);c.setAttribute('r','8');c.setAttribute('class','hotspot-editor-handle');handles.appendChild(c)})}else if(shapeMode.value==='circle'&&circleCenter){circle.setAttribute('cx',circleCenter[0]*1000);circle.setAttribute('cy',circleCenter[1]*1000);circle.setAttribute('r',Number(radius.value)*1000)}radiusValue.textContent=Number(radius.value).toFixed(3)}renderEdits();document.getElementById('radiusControl').style.display=editorMode==='hotspot'&&shapeMode.value==='circle'?'flex':'none'}
function populateImages(){imageSelect.innerHTML='';EDITOR_DATA.images.forEach((im,i)=>{const o=document.createElement('option');o.value=i;o.textContent=im.id||im.file;imageSelect.appendChild(o)});loadImage()}
function loadImage(){currentImage=EDITOR_DATA.images[Number(imageSelect.value)||0];img.src=currentImage.url;img.alt=currentImage.alt_text||'Study image';imageEdits=JSON.parse(JSON.stringify(currentImage.edits||[]));hotspotSelect.innerHTML='';(currentImage.hotspots||[]).forEach((h,i)=>{const o=document.createElement('option');o.value=i;o.textContent=h.label||h.id;hotspotSelect.appendChild(o)});loadHotspot();renderEdits()}
function loadHotspot(){currentHotspot=(currentImage.hotspots||[])[Number(hotspotSelect.value)||0]||null;if(!currentHotspot){points=[];circleCenter=null;draw();return}loadExisting()}
function loadExisting(){const s=currentHotspot&&currentHotspot.shape||{};points=[];circleCenter=null;if(s.type==='polygon'&&Array.isArray(s.points)){shapeMode.value='polygon';points=s.points.map(p=>[Number(p[0]),Number(p[1])])}else if(s.type==='circle'){shapeMode.value='circle';circleCenter=[Number(s.x),Number(s.y)];radius.value=Number(s.radius)||.05}draw();setStatus(`Loaded ${currentHotspot?.label||'target'}: ${s.type||'no shape'}.`)}
function norm(ev){const r=img.getBoundingClientRect();return [Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(ev.clientY-r.top)/r.height))]}
function inside(x,y,s){if(!s)return false;if(s.type==='circle'){const dx=x-s.x,dy=y-s.y;return dx*dx+dy*dy<=s.radius*s.radius}if(s.type==='polygon'){let z=false,p=s.points;for(let i=0,j=p.length-1;i<p.length;j=i++){const xi=p[i][0],yi=p[i][1],xj=p[j][0],yj=p[j][1];if(((yi>y)!=(yj>y))&&(x<(xj-xi)*(y-yi)/((yj-yi)||Number.EPSILON)+xi))z=!z}return z}return false}
function updatePrepVisibility(){const isText=document.getElementById('prepTool').value==='text';['textValueLabel','textSizeLabel','textToneLabel'].forEach(id=>document.getElementById(id).hidden=!isText);['maskStyleLabel','maskWidthLabel','maskHeightLabel'].forEach(id=>document.getElementById(id).hidden=isText)}
function setMode(mode){editorMode=mode;document.getElementById('hotspotPanel').hidden=mode!=='hotspot';document.getElementById('prepPanel').hidden=mode!=='prep';document.querySelectorAll('.hotspot-only').forEach(el=>el.style.display=mode==='hotspot'?'':'none');document.getElementById('hotspotModeBtn').classList.toggle('active',mode==='hotspot');document.getElementById('prepModeBtn').classList.toggle('active',mode==='prep');testMode=false;marker.hidden=true;draw();setStatus(mode==='hotspot'?'Clickable-region mode.':'Image-prep mode: click the image to place the selected overlay.')}
img.addEventListener('click',ev=>{const p=norm(ev);if(editorMode==='prep'){const tool=document.getElementById('prepTool').value;if(tool==='mask'){const w=Number(document.getElementById('maskW').value),h=Number(document.getElementById('maskH').value);imageEdits.push({type:'mask',x:Math.max(0,Math.min(1-w,p[0]-w/2)),y:Math.max(0,Math.min(1-h,p[1]-h/2)),w,h,style:document.getElementById('maskStyle').value})}else{const text=document.getElementById('textValue').value.trim();if(!text){setStatus('Enter label text first.','error');return}imageEdits.push({type:'text',x:p[0],y:p[1],text,size:Number(document.getElementById('textSize').value)||18,tone:document.getElementById('textTone').value})}draw();setStatus('Overlay added. Save Image Prep when finished.');return}if(testMode){const ok=inside(p[0],p[1],currentShape());marker.hidden=false;marker.style.left=`${p[0]*100}%`;marker.style.top=`${p[1]*100}%`;marker.className='hotspot-editor-test-marker '+(ok?'inside':'outside');setStatus(ok?'✓ Test click is inside the region.':'✕ Test click is outside the region.',ok?'success':'error');return}marker.hidden=true;if(shapeMode.value==='polygon')points.push(p);else circleCenter=p;draw()});
imageSelect.addEventListener('change',loadImage);hotspotSelect.addEventListener('change',loadHotspot);shapeMode.addEventListener('change',()=>{testMode=false;marker.hidden=true;draw()});radius.addEventListener('input',draw);document.getElementById('datasetKey').addEventListener('change',e=>{const [p,k,d]=e.target.value.split('::');document.getElementById('packField').value=p;document.getElementById('kindField').value=k;document.getElementById('datasetField').value=d});document.getElementById('hotspotModeBtn').onclick=()=>setMode('hotspot');document.getElementById('prepModeBtn').onclick=()=>setMode('prep');document.getElementById('loadExistingBtn').onclick=loadExisting;document.getElementById('undoBtn').onclick=()=>{if(shapeMode.value==='polygon')points.pop();else circleCenter=null;draw()};document.getElementById('clearBtn').onclick=()=>{points=[];circleCenter=null;marker.hidden=true;testMode=false;draw()};document.getElementById('testBtn').onclick=()=>{if(!currentShape()){setStatus('Draw a valid region before testing.','error');return}testMode=!testMode;setStatus(testMode?'Test mode enabled. Click anywhere on the image.':'Test mode disabled.')};
document.getElementById('prepTool').addEventListener('change',updatePrepVisibility);document.getElementById('maskW').addEventListener('input',e=>document.getElementById('maskWVal').textContent=Number(e.target.value).toFixed(2));document.getElementById('maskH').addEventListener('input',e=>document.getElementById('maskHVal').textContent=Number(e.target.value).toFixed(2));document.getElementById('undoEditBtn').onclick=()=>{imageEdits.pop();draw()};document.getElementById('clearEditsBtn').onclick=()=>{if(confirm('Clear all image-prep overlays for this image?')){imageEdits=[];draw()}};
document.getElementById('saveBtn').onclick=async()=>{const shape=currentShape();if(!currentHotspot||!shape){setStatus('Choose a target and draw a valid region first.','error');return}if(!confirm(`Save ${shape.type} geometry for ${currentHotspot.label}?`))return;try{const res=await fetch('/admin/image-editor/hotspot/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pack_id:EDITOR_DATA.pack_id,dataset_id:EDITOR_DATA.dataset_id,dataset_kind:EDITOR_DATA.dataset_kind,image_id:currentImage.id,hotspot_id:currentHotspot.id,shape})});const b=await res.json();if(!res.ok)throw new Error(b.error||'Save failed');currentHotspot.shape=shape;setStatus(`✓ Saved ${currentHotspot.label}. Backup: ${b.backup_created?'created':'already exists'}.`,'success')}catch(e){setStatus('Save failed: '+e.message,'error')}};
document.getElementById('saveEditsBtn').onclick=async()=>{try{const res=await fetch('/admin/image-editor/edits/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pack_id:EDITOR_DATA.pack_id,dataset_id:EDITOR_DATA.dataset_id,dataset_kind:EDITOR_DATA.dataset_kind,image_id:currentImage.id,edits:imageEdits})});const b=await res.json();if(!res.ok)throw new Error(b.error||'Save failed');currentImage.edits=JSON.parse(JSON.stringify(b.edits||[]));setStatus(`✓ Image prep saved. ${imageEdits.length} overlay(s).`,'success')}catch(e){setStatus('Image prep save failed: '+e.message,'error')}};
document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));updatePrepVisibility();populateImages();
const totalEditorHotspots=(EDITOR_DATA?.images||[]).reduce((n,im)=>n+((im.hotspots||[]).length),0);
if(!totalEditorHotspots){document.getElementById('hotspotModeBtn').disabled=true;setMode('prep');setStatus('This question set has no clickable regions. Image Prep is available.');}else{setMode('hotspot');}
</script><script src="/static/nav-normalize.js"></script>
</body></html>
"""



# =========================
# CONTENT PACKS - STATUS
# =========================
@app.route("/api/shutdown", methods=["POST"])
def shutdown_app():
    print("[SYSTEM] Shutdown requested via UI")

    pid = os.getpid()

    def shutdown():
        print("[SYSTEM] Sending SIGINT to self")
        os.kill(pid, signal.SIGINT)

    # Delay lets Flask return HTTP 200 before dying
    from threading import Timer
    Timer(0.5, shutdown).start()

    return jsonify(status="ok")




@app.route("/config/portal.json")
def serve_portal_config():
    """
    Serve the portal configuration as JSON.
    This is the single source of truth for UI settings
    (title, background image, feature toggles).
    """
    dprint("\n[PORTAL CONFIG] ===== SERVING /config/portal.json =====")

    cfg = load_portal_config()

    dprint("[PORTAL CONFIG] Loaded config:", cfg)
    dprint("[PORTAL CONFIG] ===== END SERVE =====\n")

    return jsonify(cfg)





@app.route("/dynamic.css")
def dynamic_css():
    cfg = load_portal_config()

    bg = (cfg.get("background_image") or "").strip()
    if not bg:
        css_bg = "none"
    else:
        user_bg = os.path.join(APP_DATA_DIR, "static", "bg", bg)
        static_bg = os.path.join(app.static_folder, "bg", bg)
        if os.path.exists(user_bg):
            css_bg = f"url('/user-bg/{bg}')"
        elif os.path.exists(static_bg):
            css_bg = f"url('/static/bg/{bg}')"
        else:
            css_bg = "none"

    theme = str(cfg.get("theme") or DEFAULT_THEME).strip().lower()
    palettes = {
        "dark": {
            "scheme": "dark", "page": "#eaf2ff", "muted": "#b8c2cc", "heading": "#ffffff",
            "body_base": "#020814", "body_overlay": "rgba(2,8,20,.72)", "body_overlay_2": "rgba(2,8,20,.84)",
            "shell": "rgba(3,12,28,.66)", "sidebar1": "rgba(5,18,40,.96)", "sidebar2": "rgba(3,13,30,.94)",
            "main1": "rgba(3,12,28,.60)", "main2": "rgba(2,10,23,.78)",
            "panel1": "rgba(6,20,45,.82)", "panel2": "rgba(5,17,38,.74)",
            "surface": "rgba(5,18,39,.58)", "surface2": "rgba(17,31,56,.78)",
            "input_bg": "rgba(3,13,30,.78)", "input_text": "#eaf3ff", "border": "rgba(86,158,255,.35)",
            "border_soft": "rgba(98,155,255,.24)", "nav_text": "#e8f2ff", "nav_muted": "#b9c8dc",
            "accent": "#1b9ff2", "accent2": "#138ad6", "accent3": "#0f6fb3", "accent_text": "#78bfff",
            "link": "#62b5ff", "link_hover": "#9bd2ff", "shadow": "rgba(0,0,0,.42)"
        },
        "light": {
            "scheme": "light", "page": "#17253a", "muted": "#53657d", "heading": "#0b1b33",
            "body_base": "#eaf0f7", "body_overlay": "rgba(239,244,250,.84)", "body_overlay_2": "rgba(229,237,246,.90)",
            "shell": "rgba(248,251,255,.92)", "sidebar1": "rgba(247,250,254,.98)", "sidebar2": "rgba(237,244,251,.98)",
            "main1": "rgba(250,252,255,.94)", "main2": "rgba(239,245,251,.96)",
            "panel1": "rgba(255,255,255,.97)", "panel2": "rgba(244,248,252,.97)",
            "surface": "rgba(237,244,251,.96)", "surface2": "rgba(230,238,248,.96)",
            "input_bg": "#ffffff", "input_text": "#10213a", "border": "rgba(55,103,153,.34)",
            "border_soft": "rgba(71,111,151,.24)", "nav_text": "#26384f", "nav_muted": "#61738a",
            "accent": "#076fb5", "accent2": "#08659e", "accent3": "#084f7c", "accent_text": "#075f9f",
            "link": "#075f9f", "link_hover": "#043f6c", "shadow": "rgba(29,52,76,.16)"
        },
        "purple-gold": {
            "scheme": "dark", "page": "#fff8e8", "muted": "#d7cbe6", "heading": "#ffffff",
            "body_base": "#160b2b", "body_overlay": "rgba(24,10,47,.74)", "body_overlay_2": "rgba(13,7,29,.86)",
            "shell": "rgba(28,11,53,.82)", "sidebar1": "rgba(38,13,69,.97)", "sidebar2": "rgba(22,8,43,.97)",
            "main1": "rgba(28,12,51,.78)", "main2": "rgba(15,8,31,.90)",
            "panel1": "rgba(43,20,75,.88)", "panel2": "rgba(27,13,50,.86)",
            "surface": "rgba(56,27,92,.66)", "surface2": "rgba(65,31,103,.72)",
            "input_bg": "rgba(29,14,52,.92)", "input_text": "#fff8e8", "border": "rgba(255,198,47,.48)",
            "border_soft": "rgba(220,183,88,.30)", "nav_text": "#fff8e8", "nav_muted": "#d7cbe6",
            "accent": "#f2c230", "accent2": "#d8a914", "accent3": "#a87c00", "accent_text": "#ffd85a",
            "link": "#ffd85a", "link_hover": "#fff0a6", "shadow": "rgba(0,0,0,.48)"
        },
        "maroon-gold": {
            "scheme": "dark", "page": "#f5f2ed", "muted": "#bfc2c9", "heading": "#ffffff",
            "body_base": "#0d0e10", "body_overlay": "rgba(18,8,11,.80)", "body_overlay_2": "rgba(8,9,10,.92)",
            "shell": "rgba(18,19,22,.94)", "sidebar1": "rgba(91,0,19,.98)", "sidebar2": "rgba(60,0,13,.99)",
            "main1": "rgba(22,23,26,.94)", "main2": "rgba(11,12,14,.97)",
            "panel1": "rgba(31,32,36,.95)", "panel2": "rgba(23,24,27,.95)",
            "surface": "rgba(43,44,49,.90)", "surface2": "rgba(35,36,40,.94)",
            "input_bg": "rgba(16,17,20,.97)", "input_text": "#f5f2ed", "border": "rgba(255,204,51,.24)",
            "border_soft": "rgba(190,194,202,.20)", "nav_text": "#fff8f1", "nav_muted": "#dbc8cc",
            "accent": "#ffcc33", "accent2": "#ffb71e", "accent3": "#c69214", "accent_text": "#ffde7a",
            "link": "#ffde7a", "link_hover": "#fff0b8", "shadow": "rgba(0,0,0,.56)"
        }
    }
    p = palettes.get(theme, palettes[DEFAULT_THEME])
    vars_css = "\n".join([
        f"  --portal-bg: {css_bg};",
        f"  --theme-color-scheme: {p['scheme']};",
        f"  --theme-page-text: {p['page']};",
        f"  --theme-muted-text: {p['muted']};",
        f"  --theme-heading: {p['heading']};",
        f"  --theme-body-base: {p['body_base']};",
        f"  --theme-body-overlay: {p['body_overlay']};",
        f"  --theme-body-overlay-2: {p['body_overlay_2']};",
        f"  --theme-shell-bg: {p['shell']};",
        f"  --theme-sidebar-1: {p['sidebar1']};",
        f"  --theme-sidebar-2: {p['sidebar2']};",
        f"  --theme-main-1: {p['main1']};",
        f"  --theme-main-2: {p['main2']};",
        f"  --theme-panel-1: {p['panel1']};",
        f"  --theme-panel-2: {p['panel2']};",
        f"  --theme-surface: {p['surface']};",
        f"  --theme-surface-2: {p['surface2']};",
        f"  --theme-input-bg: {p['input_bg']};",
        f"  --theme-input-text: {p['input_text']};",
        f"  --theme-border: {p['border']};",
        f"  --theme-border-soft: {p['border_soft']};",
        f"  --theme-nav-text: {p['nav_text']};",
        f"  --theme-nav-muted: {p['nav_muted']};",
        f"  --theme-accent: {p['accent']};",
        f"  --theme-accent-2: {p['accent2']};",
        f"  --theme-accent-3: {p['accent3']};",
        f"  --theme-accent-text: {p['accent_text']};",
        f"  --theme-link: {p['link']};",
        f"  --theme-link-hover: {p['link_hover']};",
        f"  --theme-shadow: {p['shadow']};"
    ])
    return f":root {{\n{vars_css}\n}}\n", 200, {"Content-Type": "text/css", "Cache-Control": "no-store"}





# =========================
# SERVE USER BACKGROUNDS (RUNTIME SAFE)
# =========================
@app.route("/user-bg/<path:filename>")
def serve_user_background(filename):
    bg_dir = os.path.join(APP_DATA_DIR, "static", "bg")
    try:
        file_path = _safe_pack_child(bg_dir, filename)
        if not os.path.isfile(file_path):
            return "Background image not found", 404
        _decode_raster_image(file_path, RASTER_IMAGE_FORMATS)
    except ValueError:
        return "Invalid background image", 415
    return send_from_directory(bg_dir, filename)





@app.route("/history")
def history():
    return send_from_directory(app.static_folder, "history.html")


@app.route("/history.html")
def history_html_redirect():
    attempt = request.args.get("attempt")
    if attempt:
        return redirect(f"/history?attempt={attempt}", code=301)
    return redirect("/history", code=301)

@app.route("/review")
@app.route("/review.html")
def review():
    return send_from_directory(app.static_folder, "review.html")



@app.route("/dashboard")
@app.route("/dashboard.html")
def dashboard():
    return send_from_directory(app.static_folder, "dashboard.html")


@app.route("/toggle_hidden", methods=["POST"])
def toggle_hidden():
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


@app.route("/move_quiz_folder", methods=["POST"])
def move_quiz_folder():
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


@app.route("/add_quiz_folder", methods=["POST"])
def add_quiz_folder():
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


@app.route("/set_quiz_folder_hidden", methods=["POST"])
def set_quiz_folder_hidden():
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


@app.route("/rename_quiz_folder", methods=["POST"])
def rename_quiz_folder():
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


@app.route("/delete_quiz_folder", methods=["POST"])
def delete_quiz_folder():
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


@app.route("/save_folder_order", methods=["POST"])
def save_folder_order():
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


@app.route("/save_quiz_order_in_folder", methods=["POST"])
def save_quiz_order_in_folder():
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


# =========================
# Auto Logo Removal
# =========================
def cleanup_temp_logos(max_age_minutes=30):
    now = time.time()

    for fname in os.listdir(LOGO_FOLDER):
        if not fname.startswith("temp_logo_"):
            continue

        path = os.path.join(LOGO_FOLDER, fname)

        try:
            stat = os.stat(path)
            age_minutes = (now - stat.st_mtime) / 60

            if age_minutes > max_age_minutes:
                os.remove(path)
                print(f"[CLEANUP] Removed abandoned temp logo: {fname}")

        except Exception as e:
            print(f"[CLEANUP ERROR] {fname}: {e}")

cleanup_temp_logos()


# =========================
# PORTAL CONFIG MANAGEMENT
# =========================
def _fsync_json_directory(path):
    """Best-effort directory durability after replacing a durable JSON file."""
    return _json_files._fsync_json_directory(path, os_module=os)


def _preserve_malformed_json(path):
    """Keep one recoverable copy of malformed JSON without backup-file churn."""
    return _json_files._preserve_malformed_json(
        path,
        os_module=os,
        tempfile_module=tempfile,
        fsync_directory=_fsync_json_directory,
    )


def _atomic_write_json(path, payload, *, indent=2, ensure_ascii=True, expected_type=None):
    """Durably replace one user-owned JSON file while retaining malformed input."""
    return _json_files._atomic_write_json(
        path,
        payload,
        indent=indent,
        ensure_ascii=ensure_ascii,
        expected_type=expected_type,
        os_module=os,
        tempfile_module=tempfile,
        json_module=json,
        preserve_malformed=_preserve_malformed_json,
        fsync_directory=_fsync_json_directory,
    )


def load_portal_config():
    return _portal_repository.load_portal_config(
        PORTAL_CONFIG,
        default_theme=DEFAULT_THEME,
        default_ai_feedback_prompt=DEFAULT_AI_FEEDBACK_PROMPT,
        default_law_ai_prompt=DEFAULT_LAW_AI_PROMPT,
        default_study_content_pack_prompt=DEFAULT_STUDY_CONTENT_PACK_PROMPT,
        default_medical_study_pack_ai_addendum=DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
        validate_custom_ai_url=_validate_custom_ai_url,
        atomic_write_json=_atomic_write_json,
        preserve_malformed_json=_preserve_malformed_json,
    )


def save_portal_config(title, show_confidence=False, enable_regex_replace=False, background_image=None):
    return _portal_repository.save_portal_config(
        PORTAL_CONFIG,
        title,
        show_confidence,
        enable_regex_replace,
        background_image,
        load_config=load_portal_config,
        atomic_write_json=_atomic_write_json,
    )


def get_quiz_folders():
    return _portal_repository.get_quiz_folders(load_config=load_portal_config)


def save_quiz_folders(folders):
    return _portal_repository.save_quiz_folders(
        PORTAL_CONFIG,
        folders,
        load_config=load_portal_config,
        atomic_write_json=_atomic_write_json,
        clean_hidden_quiz_folders=_clean_hidden_quiz_folders,
    )


def _clean_hidden_quiz_folders(hidden_folders, configured_folders):
    """Return safe hidden-folder names using configured display spelling."""
    return _portal_repository._clean_hidden_quiz_folders(
        hidden_folders, configured_folders
    )


def get_hidden_quiz_folders(configured_folders=None):
    return _portal_repository.get_hidden_quiz_folders(
        configured_folders,
        get_folders=get_quiz_folders,
        load_config=load_portal_config,
        clean_hidden_quiz_folders=_clean_hidden_quiz_folders,
    )


def save_quiz_folder_state(folders, hidden_folders):
    """Persist folder order and hidden state together in portal.json."""
    return _portal_repository.save_quiz_folder_state(
        PORTAL_CONFIG,
        folders,
        hidden_folders,
        load_config=load_portal_config,
        atomic_write_json=_atomic_write_json,
        clean_hidden_quiz_folders=_clean_hidden_quiz_folders,
    )



def get_portal_title():
    return _portal_repository.get_portal_title(load_config=load_portal_config)


def get_confidence_setting():
    return _portal_repository.get_confidence_setting(load_config=load_portal_config)


# =========================
# LAW STUDY REGISTRY
# =========================
def load_law_registry():
    return _registry_repository.load_law_registry(
        LAW_REGISTRY,
        atomic_write_json=_atomic_write_json,
        preserve_malformed_json=_preserve_malformed_json,
    )


def save_law_registry(registry):
    return _registry_repository.save_law_registry(
        LAW_REGISTRY,
        registry,
        atomic_write_json=_atomic_write_json,
    )


def _law_registry_case_for_mutation(registry, case_id):
    return _law_service._law_registry_case_for_mutation(registry, case_id)


def _commit_law_case_and_registry(
    case_path, case_data, registry, *, previous_case_data=None, new_case=False
):
    return _law_service._commit_law_case_and_registry(
        case_path,
        case_data,
        registry,
        previous_case_data=previous_case_data,
        new_case=new_case,
        atomic_write_json=_atomic_write_json,
        save_law_registry=save_law_registry,
        lexists=os.path.lexists,
        isfile=os.path.isfile,
        remove_file=os.remove,
    )


def _delete_law_case_and_registry(case_path, registry, case_id):
    return _law_service._delete_law_case_and_registry(
        case_path,
        registry,
        case_id,
        registry_case_for_mutation=_law_registry_case_for_mutation,
        save_law_registry=save_law_registry,
        lexists=os.path.lexists,
        isfile=os.path.isfile,
        remove_file=os.remove,
    )



# =========================
# QUIZ REGISTRY
# =========================
registry_lock = threading.RLock()

def load_registry():
    return _registry_repository.load_registry(
        QUIZ_REGISTRY,
        registry_lock=registry_lock,
    )

def save_registry(registry):
    return _registry_repository.save_registry(
        QUIZ_REGISTRY,
        registry,
        registry_lock=registry_lock,
        atomic_write_json=_atomic_write_json,
    )


def normalize_quiz_folders(registry):
    return _registry_repository.normalize_quiz_folders(
        registry,
        registry_lock=registry_lock,
        save_registry=save_registry,
    )

def normalize_exam_minutes(value, default=90):
    """
    Normalize a per-quiz Exam Mode duration.
    Existing quizzes and blank/invalid values safely fall back to 90 minutes.
    """
    try:
        minutes = int(str(value).strip())
    except (TypeError, ValueError):
        return default

    if minutes < 1:
        return default

    # Keep the value reasonable while still allowing long certification exams.
    return min(minutes, 1440)


def add_quiz_to_registry(quiz_id, html, title, logo=None, exam_minutes=90, source_pack_id=None, source_dataset_id=None):
    """
    Canonical registry update:
    - quiz_id is the DATABASE quizzes.id (authoritative)
    - Registry is a UI index only
    """
    print(
        f"[REGISTRY] add_quiz_to_registry "
        f"db_id={quiz_id} title={title!r} logo={logo!r}"
    )

    with registry_lock:
        registry = load_registry()

        try:
            quiz_id = int(quiz_id)
        except Exception:
            raise ValueError(
                "add_quiz_to_registry requires a numeric DB quiz_id"
            )

        kept = []

        for q in registry:
            # De-dupe by database quiz ID
            same_id = (
                q.get("id") == quiz_id
                or str(q.get("id")) == str(quiz_id)
            )

            # De-dupe by generated HTML filename
            same_html = (
                q.get("html") == html
                if html
                else False
            )

            if same_id or same_html:
                continue

            kept.append(q)

        source_pack_key = str(source_pack_id or "").strip().lower()
        source_type = None
        if source_pack_key:
            source_pack = get_content_pack(source_pack_key) or {}
            if _is_medical_pack_manifest(source_pack_key, source_pack):
                source_type = "medical"
            elif _is_it_pack_manifest(source_pack_key, source_pack):
                source_type = "it"
            else:
                source_type = "study-pack"

        kept.append({
            "id": quiz_id,
            "html": html,
            "title": title,
            "logo": logo,
            "exam_minutes": normalize_exam_minutes(exam_minutes),
            "timestamp": int(time.time()),
            "source_pack_id": source_pack_key or None,
            "source_dataset_id": str(source_dataset_id or "").strip() or None,
            "source_type": source_type,
        })

        save_registry(kept)





# =========================
# ROOT + STATIC (ORDER MATTERS)
# =========================

@app.route("/")
def home():
    portal_title = get_portal_title()

    index_path = os.path.join(app.static_folder, "index.html")

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    return render_template_string(
    html,
    portal_title=portal_title,
    app_version=APP_VERSION,
    installed_content_packs=content_pack_summary()
)



# =========================
# CONTENT PACKS - STATUS
# =========================

CONTENT_PACK_AI_WORKFLOW = "ai-study-pack"


def _content_pack_workflow(metadata):
    """Return the one supported guided-import workflow, if any."""
    if isinstance(metadata, dict) and metadata.get("workflow") == CONTENT_PACK_AI_WORKFLOW:
        return CONTENT_PACK_AI_WORKFLOW
    return None


def _content_pack_workflow_return_url(metadata):
    if _content_pack_workflow(metadata) == CONTENT_PACK_AI_WORKFLOW:
        return url_for("study_pack_ai_builder")
    return "/content-packs"


def _stage_content_pack_upload(upload, *, workflow=None):
    return _content_pack_mutation_service.stage_content_pack_upload(
        upload,
        workflow=workflow,
        allowed_workflow=CONTENT_PACK_AI_WORKFLOW,
        content_length=request.content_length,
        upload_max_bytes=CONTENT_PACK_UPLOAD_MAX_BYTES,
        multipart_overhead_bytes=CONTENT_PACK_MULTIPART_OVERHEAD_BYTES,
        upload_too_large_error=UploadTooLargeError,
        token_hex=secrets.token_hex,
        content_pack_stage_path=_content_pack_stage_path,
        bounded_save_upload=_bounded_save_upload,
        inspect_content_pack_zip=_inspect_content_pack_zip,
        extract_content_pack_zip=_extract_content_pack_zip,
        safe_pack_child=_safe_pack_child,
        validate_staged_content_pack=_validate_staged_content_pack,
        randomize_staged_ai_answer_positions=_randomize_staged_ai_answer_positions,
        secure_filename=secure_filename,
        now=datetime.now,
    )


def _install_staged_content_pack(token):
    return _content_pack_mutation_service.install_staged_content_pack(
        token,
        load_staged_content_pack=_load_staged_content_pack,
        validate_staged_content_pack=_validate_staged_content_pack,
        workflow_for_metadata=_content_pack_workflow,
        ai_workflow=CONTENT_PACK_AI_WORKFLOW,
        discover_content_packs=discover_content_packs,
        content_pack_folder=CONTENT_PACK_FOLDER,
        remove_content_pack_stage=_remove_content_pack_stage,
        move=shutil.move,
    )


def _cancel_staged_content_pack(token):
    return _content_pack_mutation_service.cancel_staged_content_pack(
        token,
        load_staged_content_pack=_load_staged_content_pack,
        remove_content_pack_stage=_remove_content_pack_stage,
    )

@app.route("/content-packs/import", methods=["POST"])
def content_pack_import():
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
        return redirect(url_for("content_pack_import_review", token=token))
    except Exception as exc:
        print(f"[CONTENT PACK IMPORT ERROR] {type(exc).__name__}: {exc}")
        flash("Study Pack ZIP could not be validated. Check the local DLMS log for details.", "error")
        return redirect("/content-packs")


@app.route("/study-packs/ai-builder/import", methods=["POST"])
def study_pack_ai_builder_import():
    """Return a completed AI-generated ZIP to the standard import pipeline."""
    try:
        token = _stage_content_pack_upload(
            request.files.get("pack_zip"), workflow=CONTENT_PACK_AI_WORKFLOW
        )
        return redirect(url_for("content_pack_import_review", token=token))
    except Exception as exc:
        print(f"[AI STUDY PACK IMPORT ERROR] {type(exc).__name__}: {exc}")
        flash("Study Pack ZIP could not be validated. Check the local DLMS log for details.", "error")
        return redirect(url_for("study_pack_ai_builder"))


@app.route("/content-packs/import/<token>")
def content_pack_import_review(token):
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


@app.route("/content-packs/import/<token>/install", methods=["POST"])
def content_pack_import_install(token):
    if request.form.get("confirm_install") != "yes":
        flash("Study Pack installation was not confirmed.", "error")
        return redirect(url_for("content_pack_import_review", token=token))

    metadata = {}
    try:
        result = _install_staged_content_pack(token)
        metadata = result["metadata"]
        if result["status"] == "invalid":
            flash("Study Pack is no longer valid; installation was blocked.", "error")
            return redirect(url_for("content_pack_import_review", token=token))
        pack_id = result["pack_id"]
        installed = result["installed"]
        flash(f"Installed Study Pack '{installed.get('name') or pack_id}' successfully.", "success")
        if _content_pack_workflow(metadata) == CONTENT_PACK_AI_WORKFLOW:
            return redirect(url_for("study_packs_home", installed=pack_id))
        return redirect("/content-packs")
    except Exception as install_error:
        if isinstance(
            install_error, _content_pack_mutation_service.ContentPackInstallError
        ):
            exc = install_error.original
            metadata = install_error.metadata
        else:
            exc = install_error
        print(f"[CONTENT PACK INSTALL ERROR] {type(exc).__name__}: {exc}")
        flash("The Study Pack was not installed. Existing installed content was left unchanged.", "error")
        try:
            _load_staged_content_pack(token)
            return redirect(url_for("content_pack_import_review", token=token))
        except Exception:
            return redirect(_content_pack_workflow_return_url(metadata))


@app.route("/content-packs/import/<token>/cancel", methods=["POST"])
def content_pack_import_cancel(token):
    metadata = _cancel_staged_content_pack(token)
    flash("Study Pack import cancelled; staging files were removed.", "success")
    return redirect(_content_pack_workflow_return_url(metadata))


@app.route("/content-packs/details/<folder>")
def content_pack_details(folder):
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


def _build_content_pack_export(folder):
    return _content_pack_mutation_service.build_content_pack_export(
        folder, content_pack_folder_report=_content_pack_folder_report
    )


@app.route("/content-packs/export/<folder>")
def export_content_pack(folder):
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


@app.route("/content-packs")
def content_packs_page():
    packs = content_pack_management_summary()
    return render_template(
        "content_packs/index.html",
        packs=packs,
        pack_folder=CONTENT_PACK_FOLDER,
        medical_pack_installed=True,
    )


def _delete_content_pack_folder(folder):
    return _content_pack_mutation_service.delete_content_pack_folder(
        folder,
        content_pack_folder=CONTENT_PACK_FOLDER,
        get_content_pack=get_content_pack,
        snapshot_existing_pack_dependencies=_snapshot_existing_pack_dependencies,
        remove_tree=shutil.rmtree,
    )


@app.route("/content-packs/delete", methods=["POST"])
def delete_content_pack():
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
    except _content_pack_mutation_service.InvalidContentPackFolderError:
        flash("Invalid Content Pack folder.", "error")
    except _content_pack_mutation_service.ContentPackFolderNotFoundError:
        flash("Content Pack folder was not found.", "error")
    except _content_pack_mutation_service.ProtectedContentPackError:
        flash("This Content Pack declares itself protected and cannot be deleted here.", "error")
    except Exception as exc:
        print(f"[CONTENT PACK DELETE ERROR] {type(exc).__name__}: {exc}")
        flash(
            "The Study Pack could not be deleted. Any completed legacy-asset "
            "preservation remains safe and can be reused when deletion is retried.",
            "error",
        )

    return redirect("/content-packs")


# =========================
# MEDICAL STUDY - CONTENT PACK
# =========================
def _is_medical_content_pack(pack_id, pack):
    """True for any installed pack that declares medical study content."""
    return _is_medical_pack_manifest(pack_id, pack)


def _medical_pack_page_data():
    """Aggregate validated datasets from every installed medical-domain Study Pack."""
    packs = discover_content_packs()
    medical_packs = [
        (pack_id, candidate)
        for pack_id, candidate in packs.items()
        if _is_medical_content_pack(pack_id, candidate)
    ]
    if not medical_packs:
        return None, [], []

    # Keep the historical base pack first when installed, but never require it.
    medical_packs.sort(key=lambda item: (item[0] != "medical", str(item[1].get("name") or item[0]).casefold()))

    if len(medical_packs) == 1:
        pack = dict(medical_packs[0][1])
    else:
        pack = {
            "id": "medical_collection",
            "name": "DLMS Medical Study",
            "version": f"{len(medical_packs)} installed packs",
            "description": "Aggregated medical study content from installed Medical-domain Study Packs.",
        }

    datasets = []
    image_datasets = []

    for pack_id, source_pack in medical_packs:
        for descriptor in source_pack.get("datasets", []):
            if not isinstance(descriptor, dict):
                print(f"[MEDICAL PACK] Skipping invalid dataset descriptor in {pack_id!r}: {descriptor!r}")
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = load_content_pack_dataset(pack_id, dataset_id)
                datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "type": descriptor.get("type") or data.get("type") or "matching",
                    "term_count": len(data.get("terms") or []),
                    "category": data.get("category") or "",
                })
            except Exception as exc:
                print(f"[MEDICAL PACK] Dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

        for descriptor in source_pack.get("image_datasets", []):
            if not isinstance(descriptor, dict):
                print(f"[MEDICAL PACK] Skipping invalid image dataset descriptor in {pack_id!r}: {descriptor!r}")
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = load_content_pack_image_dataset(pack_id, dataset_id)
                image_count = len(data.get("images") or [])
                hotspot_count = sum(len(img.get("hotspots") or []) for img in (data.get("images") or []))
                image_datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "image_count": image_count,
                    "hotspot_count": hotspot_count,
                    "category": data.get("category") or "Anatomy",
                })
            except Exception as exc:
                print(f"[MEDICAL PACK] Image dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

    return pack, datasets, image_datasets


def _medical_not_installed():
    """Render Medical Study as an available feature even when no content is installed."""
    empty_pack = {
        "name": "Medical Study",
        "version": "No packs installed",
    }
    template = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Medical Study - DLMS</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home medical-study-page">
<div class="dashboard-shell">
    """ + _MEDICAL_SIDEBAR + r"""

    <main class="dashboard-main medical-main">
        <header class="dashboard-header medical-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="medical-eyebrow">MEDICAL STUDY</div>
                <h1>Medical Study</h1>
                <p>Medical Study is ready to use. Add a Medical-domain Study Pack when you want terminology, image, or mixed-question medical content.</p>
            </div>
        </header>

        <section class="medical-summary-grid">
            <article class="dashboard-stat-card">
                <span>Installed Packs</span>
                <strong>0</strong>
                <small>medical content is optional</small>
            </article>
            <article class="dashboard-stat-card">
                <span>Study Banks</span>
                <strong>0</strong>
                <small>install or create content to begin</small>
            </article>
            <article class="dashboard-stat-card">
                <span>Image Sets</span>
                <strong>0</strong>
                <small>no medical images installed</small>
            </article>
        </section>

        <section class="medical-section-launch-grid">
            <a class="dashboard-panel medical-section-launch-card" href="/study-packs/ai-builder?domain=Medical&amp;from=medical">
                <div class="medical-section-launch-icon">AI</div>
                <div class="medical-section-launch-copy">
                    <span class="medical-eyebrow">CREATE</span>
                    <h2>Create a Medical Study Pack</h2>
                    <p>Use the unified AI Study Pack Builder with Medical safeguards, source requirements, and image provenance rules automatically enabled.</p>
                    <span class="medical-section-launch-action">Open AI Study Pack Builder →</span>
                </div>
            </a>

            <a class="dashboard-panel medical-section-launch-card" href="/content-packs">
                <div class="medical-section-launch-icon">⬡</div>
                <div class="medical-section-launch-copy">
                    <span class="medical-eyebrow">INSTALL / MANAGE</span>
                    <h2>Content Packs</h2>
                    <p>Manage installed Study Packs. Any valid pack declaring a Medical content domain will automatically appear in Medical Study.</p>
                    <span class="medical-section-launch-action">Open Content Packs →</span>
                </div>
            </a>
        </section>

        <section class="dashboard-panel medical-ai-builder-panel medical-empty-state-panel">
            <div class="medical-ai-builder-heading">
                <div>
                    <span class="medical-eyebrow">OPTIONAL CONTENT</span>
                    <h2>No Medical Study Packs Installed</h2>
                    <p>DLMS itself does not require or bundle medical subject matter. You can leave Medical Study empty, create your own pack, or install a Medical Study Pack later.</p>
                </div>
                <span class="medical-ai-safety-pill">Medical Study Ready</span>
            </div>
            <p class="medical-empty-pack-path"><strong>Study Pack folder:</strong> <code>{{ pack_folder }}</code></p>
        </section>
    </main>
</div>

<script>
document.getElementById("menuButton")?.addEventListener("click", () => {
    document.getElementById("dashboardSidebar")?.classList.toggle("open");
});
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
"""
    return render_template_string(
        template,
        pack=empty_pack,
        pack_folder=CONTENT_PACK_FOLDER,
        medical_section="home",
    )


_MEDICAL_SIDEBAR = r"""
<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark">✚</div>
        <div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div>
    </div>
    <nav class="dashboard-nav">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
        <a class="dashboard-nav-item active" href="/medical" {% if medical_section == "home" %}aria-current="page"{% endif %}>
            <span class="dashboard-nav-icon">✚</span><span>Medical Study</span>
        </a>
        <div class="dashboard-nav-subitems medical-nav-subitems">
            <a class="dashboard-nav-subitem {% if medical_section == 'matching' %}active{% endif %}" href="/medical/matching"
               {% if medical_section == "matching" %}aria-current="page"{% endif %}>
                <span class="dashboard-nav-subicon">↔</span><span>Terminology &amp; Matching</span>
            </a>
            <a class="dashboard-nav-subitem {% if medical_section == 'anatomy' %}active{% endif %}" href="/medical/anatomy"
               {% if medical_section == "anatomy" %}aria-current="page"{% endif %}>
                <span class="dashboard-nav-subicon">◎</span><span>Anatomy &amp; Images</span>
            </a>
            <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
        </div>
        <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
        <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
        <div class="dashboard-nav-group"><a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a><div class="dashboard-nav-submenu"><a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a><a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a></div></div>
    </nav>
    <div class="dashboard-nav-section-label"><span>System</span></div>
    <nav class="dashboard-nav dashboard-nav-system">
        <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
        <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
        <a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a>
        <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
        <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
    </nav>
    <div class="dashboard-sidebar-version">{{ pack.name }} v{{ pack.version }}</div>
</aside>
"""


@app.route("/medical")
def medical_study_home():
    pack, datasets, image_datasets = _medical_pack_page_data()
    if not pack:
        return _medical_not_installed()

    total_terms = sum(d["term_count"] for d in datasets)
    total_images = sum(d["image_count"] for d in image_datasets)
    total_hotspots = sum(d["hotspot_count"] for d in image_datasets)

    template = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Medical Study - DLMS</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home medical-study-page">
<div class="dashboard-shell">
    """ + _MEDICAL_SIDEBAR + r"""

    <main class="dashboard-main medical-main">
        <header class="dashboard-header medical-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="medical-eyebrow">MEDICAL STUDY</div>
                <h1>{{ pack.name }}</h1>
                <p>Choose a study area. Terminology practice and visual anatomy are separated so each workspace stays focused as the Medical Pack grows.</p>
            </div>
        </header>

        <section class="medical-summary-grid">
            <article class="dashboard-stat-card"><span>Pack Version</span><strong>{{ pack.version }}</strong><small>independent of DLMS core</small></article>
            <article class="dashboard-stat-card"><span>Study Banks</span><strong>{{ datasets|length }}</strong><small>{{ total_terms }} terminology terms</small></article>
            <article class="dashboard-stat-card"><span>Image Sets</span><strong>{{ image_datasets|length }}</strong><small>{{ total_hotspots }} visual structures</small></article>
        </section>

        <section class="medical-section-launch-grid">
            <a class="dashboard-panel medical-section-launch-card" href="/medical/matching">
                <div class="medical-section-launch-icon">↔</div>
                <div class="medical-section-launch-copy">
                    <span class="medical-eyebrow">TEXT STUDY</span>
                    <h2>Terminology &amp; Matching</h2>
                    <p>Practice foundational medical terminology and system-specific vocabulary with configurable matching rounds.</p>
                    <div class="medical-dataset-meta">
                        <span>{{ datasets|length }} study banks</span>
                        <span>{{ total_terms }} terms</span>
                    </div>
                    <span class="medical-section-launch-action">Open Terminology &amp; Matching →</span>
                </div>
            </a>

            <a class="dashboard-panel medical-section-launch-card" href="/medical/anatomy">
                <div class="medical-section-launch-icon">◎</div>
                <div class="medical-section-launch-copy">
                    <span class="medical-eyebrow">VISUAL STUDY</span>
                    <h2>Anatomy &amp; Images</h2>
                    <p>Identify structures directly on source-documented anatomy images using calibrated circle and polygon hotspots.</p>
                    <div class="medical-dataset-meta">
                        <span>{{ image_datasets|length }} image sets</span>
                        <span>{{ total_images }} images</span>
                        <span>{{ total_hotspots }} structures</span>
                    </div>
                    <span class="medical-section-launch-action">Open Anatomy &amp; Images →</span>
                </div>
            </a>
        </section>

        <section class="dashboard-panel medical-ai-builder-teaser">
            <div class="medical-ai-builder-teaser-icon">AI</div>
            <div class="medical-ai-builder-teaser-copy">
                <span class="medical-eyebrow">CUSTOM CONTENT</span>
                <h2>AI Study Pack Builder</h2>
                <p>Describe what you want to study and let DLMS build a controlled research prompt that requires source-verified, legally reusable material in the exact DLMS add-on pack format.</p>
                <div class="medical-ai-builder-points">
                    <span>✓ authoritative sources</span>
                    <span>✓ open-license checks</span>
                    <span>✓ DLMS-ready schema</span>
                    <span>✓ no invented content</span>
                </div>
            </div>
            <a class="medical-primary-button medical-ai-builder-open" href="/study-packs/ai-builder?domain=Medical&amp;from=medical">Build Custom Content</a>
        </section>
    </main>
</div>
<script>
const menuButton=document.getElementById("menuButton");
const sidebar=document.getElementById("dashboardSidebar");
if(menuButton&&sidebar){menuButton.addEventListener("click",()=>sidebar.classList.toggle("open"));}
</script>
<script src="/static/nav-normalize.js"></script>
</body></html>
"""
    return render_template_string(
        template,
        pack=pack,
        datasets=datasets,
        image_datasets=image_datasets,
        total_terms=total_terms,
        total_images=total_images,
        total_hotspots=total_hotspots,
        medical_section="home",
    )



@app.route("/medical/ai-builder", methods=["GET", "POST"])
def medical_ai_content_builder():
    """Compatibility entry point: use the unified Study Pack AI Builder."""
    query = {"domain": "Medical", "from": "medical"}
    topic = str(request.values.get("topic") or "").strip()
    if topic:
        query["topic"] = topic
    return redirect(url_for("study_pack_ai_builder", **query))


@app.route("/medical/matching")
def medical_matching():
    pack, datasets, image_datasets = _medical_pack_page_data()
    if not pack:
        return _medical_not_installed()

    total_terms = sum(d["term_count"] for d in datasets)

    template = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Terminology & Matching - DLMS</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home medical-study-page">
<div class="dashboard-shell">
    """ + _MEDICAL_SIDEBAR + r"""

    <main class="dashboard-main medical-main">
        <header class="dashboard-header medical-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="medical-eyebrow">MEDICAL STUDY · TERMINOLOGY</div>
                <h1>Terminology &amp; Matching</h1>
                <p>Choose a source-documented study bank, then configure the number of pairs and matching direction for the practice round.</p>
            </div>
        </header>

        <section class="medical-summary-grid medical-subpage-summary">
            <article class="dashboard-stat-card"><span>Study Banks</span><strong>{{ datasets|length }}</strong><small>installed terminology datasets</small></article>
            <article class="dashboard-stat-card"><span>Total Terms</span><strong>{{ total_terms }}</strong><small>across available study banks</small></article>
            <article class="dashboard-stat-card medical-subpage-back-card">
                <span>Medical Study</span>
                <a href="/medical">← Back to Medical Study</a>
                <small>choose another study area</small>
            </article>
        </section>

        {% if datasets %}
        <section class="dashboard-panel medical-compact-dataset-panel">
            <div class="medical-compact-panel-heading">
                <div>
                    <span class="medical-eyebrow">INSTALLED TERMINOLOGY</span>
                    <h2>Study Banks</h2>
                    <p>Choose a bank, configure the round, and expand any row for its description and source pack.</p>
                </div>
                <div class="medical-compact-panel-actions">
                    <button type="button" class="medical-ai-secondary-button" data-medical-expand="matching">Expand All</button>
                    <button type="button" class="medical-ai-secondary-button" data-medical-collapse="matching">Collapse All</button>
                </div>
            </div>
            <div class="study-dataset-table-wrap medical-dataset-table-wrap">
                <table class="study-dataset-table medical-dataset-table">
                    <thead>
                        <tr>
                            <th>Type</th>
                            <th>Study Bank</th>
                            <th>Terms</th>
                            <th>Round Options</th>
                            <th class="study-dataset-action-col">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                    {% for dataset in datasets %}
                        <tr class="medical-dataset-main-row">
                            <td><span class="study-type-badge matching">Matching</span></td>
                            <td>
                                <button type="button"
                                        class="study-dataset-title-button medical-dataset-toggle"
                                        data-medical-detail="matching-detail-{{ loop.index }}"
                                        aria-expanded="false">
                                    <span class="medical-row-caret">›</span>
                                    {{ dataset.title }}
                                </button>
                                <small>{{ dataset.category or "Terminology" }}</small>
                            </td>
                            <td><strong>{{ dataset.term_count }}</strong><small>terms</small></td>
                            <td>
                                <form method="POST" action="/medical/generate" class="study-table-inline-form medical-table-generator-form">
                                    <input type="hidden" name="pack_id" value="{{ dataset.pack_id }}">
                                    <input type="hidden" name="dataset_id" value="{{ dataset.id }}">
                                    <label><span>Pairs</span>
                                        <input type="number" name="round_size" min="2" max="{{ dataset.term_count }}" value="{{ 10 if dataset.term_count >= 10 else dataset.term_count }}">
                                    </label>
                                    <label><span>Direction</span>
                                        <select name="direction">
                                            <option value="random" selected>Random</option>
                                            <option value="term_to_definition">Term → Definition</option>
                                            <option value="definition_to_term">Definition → Term</option>
                                        </select>
                                    </label>
                            </td>
                            <td class="study-dataset-action-col">
                                    <button class="medical-primary-button study-table-primary" type="submit">Create Quiz</button>
                                </form>
                            </td>
                        </tr>
                        <tr id="matching-detail-{{ loop.index }}" class="study-dataset-detail-row medical-dataset-detail-row" hidden>
                            <td colspan="5">
                                <div class="medical-dataset-detail-content">
                                    <p>{{ dataset.description }}</p>
                                    <div class="medical-dataset-detail-meta">
                                        <span><strong>Category:</strong> {{ dataset.category or "Terminology" }}</span>
                                        <span><strong>Dataset:</strong> {{ dataset.id }}</span>
                                        <span><strong>Pack:</strong> {{ dataset.pack_name }}</span>
                                    </div>
                                </div>
                            </td>
                        </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </section>
        {% else %}
        <section class="dashboard-panel pack-empty-card">
            <h2>No usable terminology datasets</h2>
            <p>No valid Medical terminology datasets are currently installed.</p>
        </section>
        {% endif %}
    </main>
</div>
<script>
const menuButton=document.getElementById("menuButton");
const sidebar=document.getElementById("dashboardSidebar");
if(menuButton&&sidebar){menuButton.addEventListener("click",()=>sidebar.classList.toggle("open"));}

function setMedicalDetail(toggle, open){
    const targetId=toggle?.dataset?.medicalDetail;
    const detail=targetId ? document.getElementById(targetId) : null;
    if(!detail) return;
    detail.hidden=!open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.querySelector(".medical-row-caret")?.classList.toggle("open", open);
}
document.querySelectorAll(".medical-dataset-toggle").forEach(toggle=>{
    toggle.addEventListener("click",()=>{
        const detail=document.getElementById(toggle.dataset.medicalDetail);
        setMedicalDetail(toggle, !!detail?.hidden);
    });
});
document.querySelectorAll("[data-medical-expand]").forEach(button=>{
    button.addEventListener("click",()=>{
        document.querySelectorAll(".medical-dataset-toggle").forEach(toggle=>setMedicalDetail(toggle,true));
    });
});
document.querySelectorAll("[data-medical-collapse]").forEach(button=>{
    button.addEventListener("click",()=>{
        document.querySelectorAll(".medical-dataset-toggle").forEach(toggle=>setMedicalDetail(toggle,false));
    });
});
</script>
<script src="/static/nav-normalize.js"></script>
</body></html>
"""
    return render_template_string(
        template,
        pack=pack,
        datasets=datasets,
        total_terms=total_terms,
        medical_section="matching",
    )


@app.route("/medical/anatomy")
def medical_anatomy():
    pack, datasets, image_datasets = _medical_pack_page_data()
    if not pack:
        return _medical_not_installed()

    total_images = sum(d["image_count"] for d in image_datasets)
    total_hotspots = sum(d["hotspot_count"] for d in image_datasets)
    image_framework = pack.get("image_framework") or {}

    template = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anatomy & Images - DLMS</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home medical-study-page">
<div class="dashboard-shell">
    """ + _MEDICAL_SIDEBAR + r"""

    <main class="dashboard-main medical-main">
        <header class="dashboard-header medical-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="medical-eyebrow">MEDICAL STUDY · VISUAL PRACTICE</div>
                <h1>Anatomy &amp; Images</h1>
                <p>Practice structure identification directly on source-documented images. Hotspots can use calibrated circles or polygons to follow actual anatomy.</p>
            </div>
        </header>

        <section class="medical-summary-grid medical-subpage-summary">
            <article class="dashboard-stat-card"><span>Image Sets</span><strong>{{ image_datasets|length }}</strong><small>available visual datasets</small></article>
            <article class="dashboard-stat-card"><span>Structures</span><strong>{{ total_hotspots }}</strong><small>across {{ total_images }} image{% if total_images != 1 %}s{% endif %}</small></article>
            <article class="dashboard-stat-card medical-subpage-back-card">
                <span>Medical Study</span>
                <a href="/medical">← Back to Medical Study</a>
                <small>choose another study area</small>
            </article>
        </section>

        {% if image_framework %}
        <section class="dashboard-panel medical-image-framework-card medical-image-framework-compact">
            <div class="medical-dataset-heading">
                <div class="medical-dataset-icon">◎</div>
                <div>
                    <span class="medical-eyebrow">IMAGE CONTENT FRAMEWORK</span>
                    <h2>{{ image_framework.get("name", "Anatomy Image / Hotspot Schema") }}</h2>
                </div>
            </div>
            <p>{{ image_framework.get("description", "") }}</p>
            <div class="medical-dataset-meta">
                <span>Schema {{ image_framework.get("schema_version", 1) }}</span>
                <span>{{ image_framework.get("status", "ready")|capitalize }}</span>
            </div>
        </section>
        {% endif %}

        {% if image_datasets %}
        <section class="dashboard-panel medical-compact-dataset-panel">
            <div class="medical-compact-panel-heading">
                <div>
                    <span class="medical-eyebrow">INSTALLED VISUAL CONTENT</span>
                    <h2>Image Study Sets</h2>
                    <p>Launch image practice directly from the table, or expand a row for dataset details and source pack information.</p>
                </div>
                <div class="medical-compact-panel-actions">
                    <button type="button" class="medical-ai-secondary-button" data-medical-expand="anatomy">Expand All</button>
                    <button type="button" class="medical-ai-secondary-button" data-medical-collapse="anatomy">Collapse All</button>
                </div>
            </div>
            <div class="study-dataset-table-wrap medical-dataset-table-wrap">
                <table class="study-dataset-table medical-dataset-table">
                    <thead>
                        <tr>
                            <th>Type</th>
                            <th>Image Study Set</th>
                            <th>Images</th>
                            <th>Structures</th>
                            <th class="study-dataset-action-col">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                    {% for dataset in image_datasets %}
                        <tr class="medical-dataset-main-row">
                            <td><span class="study-type-badge image">Image</span></td>
                            <td>
                                <button type="button"
                                        class="study-dataset-title-button medical-dataset-toggle"
                                        data-medical-detail="anatomy-detail-{{ loop.index }}"
                                        aria-expanded="false">
                                    <span class="medical-row-caret">›</span>
                                    {{ dataset.title }}
                                </button>
                                <small>{{ dataset.category or "Visual Practice" }}</small>
                            </td>
                            <td><strong>{{ dataset.image_count }}</strong><small>image{% if dataset.image_count != 1 %}s{% endif %}</small></td>
                            <td><strong>{{ dataset.hotspot_count }}</strong><small>structures</small></td>
                            <td class="study-dataset-action-col">
                                <form method="POST" action="/medical/anatomy/generate">
                                    <input type="hidden" name="pack_id" value="{{ dataset.pack_id }}">
                                    <input type="hidden" name="dataset_id" value="{{ dataset.id }}">
                                    <button class="medical-primary-button study-table-primary" type="submit">Create Quiz</button>
                                </form>
                            </td>
                        </tr>
                        <tr id="anatomy-detail-{{ loop.index }}" class="study-dataset-detail-row medical-dataset-detail-row" hidden>
                            <td colspan="5">
                                <div class="medical-dataset-detail-content">
                                    <p>{{ dataset.description }}</p>
                                    <div class="medical-dataset-detail-meta">
                                        <span><strong>Category:</strong> {{ dataset.category or "Visual Practice" }}</span>
                                        <span><strong>Dataset:</strong> {{ dataset.id }}</span>
                                        <span><strong>Pack:</strong> {{ dataset.pack_name }}</span>
                                    </div>
                                </div>
                            </td>
                        </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </section>
        {% else %}
        <section class="dashboard-panel pack-empty-card">
            <h2>No usable image datasets</h2>
            <p>No valid Medical image datasets are currently installed.</p>
        </section>
        {% endif %}
    </main>
</div>
<script>
const menuButton=document.getElementById("menuButton");
const sidebar=document.getElementById("dashboardSidebar");
if(menuButton&&sidebar){menuButton.addEventListener("click",()=>sidebar.classList.toggle("open"));}

function setMedicalDetail(toggle, open){
    const targetId=toggle?.dataset?.medicalDetail;
    const detail=targetId ? document.getElementById(targetId) : null;
    if(!detail) return;
    detail.hidden=!open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.querySelector(".medical-row-caret")?.classList.toggle("open", open);
}
document.querySelectorAll(".medical-dataset-toggle").forEach(toggle=>{
    toggle.addEventListener("click",()=>{
        const detail=document.getElementById(toggle.dataset.medicalDetail);
        setMedicalDetail(toggle, !!detail?.hidden);
    });
});
document.querySelectorAll("[data-medical-expand]").forEach(button=>{
    button.addEventListener("click",()=>{
        document.querySelectorAll(".medical-dataset-toggle").forEach(toggle=>setMedicalDetail(toggle,true));
    });
});
document.querySelectorAll("[data-medical-collapse]").forEach(button=>{
    button.addEventListener("click",()=>{
        document.querySelectorAll(".medical-dataset-toggle").forEach(toggle=>setMedicalDetail(toggle,false));
    });
});
</script>
<script src="/static/nav-normalize.js"></script>
</body></html>
"""
    return render_template_string(
        template,
        pack=pack,
        image_datasets=image_datasets,
        total_images=total_images,
        total_hotspots=total_hotspots,
        image_framework=image_framework,
        medical_section="anatomy",
    )



@app.route("/medical/anatomy/generate", methods=["POST"])
def medical_generate_anatomy_quiz():
    pack_id = request.form.get("pack_id", "medical").strip().lower() or "medical"
    pack = get_content_pack(pack_id)
    if not pack or not _is_medical_content_pack(pack_id, pack):
        flash("Requested Medical Study content pack is not installed.", "error")
        return redirect("/content-packs")

    dataset_id = request.form.get("dataset_id", "").strip()
    try:
        data = load_content_pack_image_dataset(pack_id, dataset_id)
    except Exception as exc:
        print(f"[MEDICAL ANATOMY LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to load the selected anatomy dataset.", "error")
        return redirect("/medical/anatomy")

    runtime_questions = []
    db_questions = []
    qnum = 1

    for image in data.get("images", []):
        image_url = url_for(
            "content_pack_asset",
            pack_id=pack_id,
            asset_path=image.get("file")
        )
        source = image.get("source") or data.get("source") or {}

        hotspots = list(image.get("hotspots") or [])
        random.shuffle(hotspots)

        for hotspot in hotspots:
            label = str(hotspot.get("label") or "").strip()
            if not label:
                continue
            prompt = str(hotspot.get("prompt") or f"Identify the {label}.").strip()
            concepts = _hotspot_concepts(
                hotspot,
                image,
                hotspot,
                data,
                context=f"medical anatomy hotspot {hotspot.get('id') or label!r}",
            )

            runtime_questions.append({
                "number": qnum,
                "type": "hotspot",
                "question": prompt,
                "image_url": image_url,
                "image_alt": image.get("alt_text") or data.get("title") or "Study image",
                "image_edits": image.get("edits") or [],
                "target": hotspot.get("shape") or {},
                "target_label": label,
                "explanation": hotspot.get("explanation") or "",
                "concepts": concepts,
                "verification": hotspot.get("verification") or {},
                "image_source": {
                    "organization": source.get("organization") or "",
                    "work": source.get("work") or "",
                    "url": source.get("url") or image.get("source_url") or "",
                    "license": source.get("license") or image.get("license") or "",
                    "attribution": source.get("attribution") or image.get("attribution") or "",
                }
            })

            # Database/history surrogate. Runtime scoring still uses hotspot geometry.
            db_questions.append({
                "number": qnum,
                "type": "choice",
                "question": prompt + " [Image hotspot]",
                "choices": [
                    {"label": "A", "text": label, "is_correct": True}
                ],
                "concepts": concepts,
                "source": {
                    "organization": source.get("organization") or "",
                    "dataset": data.get("title") or dataset_id,
                    "version": pack.get("version") or "",
                    "url": source.get("url") or image.get("source_url") or "",
                    "license": source.get("license") or image.get("license") or "",
                }
            })
            qnum += 1

    if not runtime_questions:
        flash("This anatomy dataset contains no usable hotspots.", "error")
        return redirect("/medical/anatomy")

    title = str(data.get("title") or data["_descriptor"].get("title") or "Medical Anatomy").strip()
    quiz_title = f"{title} — Hotspot Practice"

    safe_pack = re.sub(r"[^a-z0-9]+", "_", pack_id.lower()).strip("_") or "medical"
    safe_id = re.sub(r"[^a-z0-9]+", "_", dataset_id.lower()).strip("_") or "anatomy"
    quiz_id, html_name = _publish_quiz(
        quiz_title,
        runtime_questions,
        db_questions,
        filename_prefix=f"medical_anatomy_{safe_pack}_{safe_id}",
        exam_minutes=90,
        source_pack_id=pack_id,
        source_dataset_id=dataset_id,
    )

    return redirect(f"/quizzes/{html_name}")


@app.route("/medical/generate", methods=["POST"])
def medical_generate_quiz():
    pack_id = request.form.get("pack_id", "medical").strip().lower() or "medical"
    pack = get_content_pack(pack_id)
    if not pack or not _is_medical_content_pack(pack_id, pack):
        flash("Requested Medical Study content pack is not installed.", "error")
        return redirect("/content-packs")

    dataset_id = request.form.get("dataset_id", "").strip()
    direction = request.form.get("direction", "random").strip()
    if direction not in {"term_to_definition", "definition_to_term", "random"}:
        direction = "random"

    try:
        data = load_content_pack_dataset(pack_id, dataset_id)
    except Exception as exc:
        print(f"[MEDICAL DATASET LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to load the selected medical dataset.", "error")
        return redirect("/medical/matching")

    terms = data.get("terms") or []
    if len(terms) < 2:
        flash("This medical dataset does not contain enough terms.", "error")
        return redirect("/medical/matching")

    try:
        round_size = int(request.form.get("round_size", "10"))
    except (TypeError, ValueError):
        round_size = 10
    round_size = max(2, min(round_size, min(100, len(terms))))

    title = str(data.get("title") or data["_descriptor"].get("title") or "Medical Practice").strip()
    quiz_title = f"{title} — {round_size}-Pair Practice"
    source = data.get("source") or {}

    pairs = [
        {
            "left": item["term"],
            "right": item["definition"],
            "category": item.get("category", ""),
            "explanation": (
                item.get("explanation")
                or item.get("study_explanation")
                or ""
            ),
            "verification": item.get("verification") or data.get("verification") or {},
            "source": item.get("source") or source or {},
        }
        for item in terms
    ]
    quiz_data = [{
        "number": 1,
        "type": "matching",
        "question": str(data.get("question_text") or "Match each medical term with its correct definition.").strip(),
        "pairs": pairs,
        "round_size": round_size,
        "direction": direction,
        "concepts": _standalone_matching_concepts(
            data, context=f"matching dataset {dataset_id!r}"
        ),
        "source": {
            "organization": source.get("organization") or pack.get("publisher") or "",
            "dataset": source.get("dataset") or title,
            "version": source.get("version") or pack.get("version") or "",
            "url": source.get("url") or "",
            "license": source.get("license") or "",
        },
    }]

    safe_pack = re.sub(r"[^a-z0-9]+", "_", pack_id.lower()).strip("_") or "medical"
    safe_id = re.sub(r"[^a-z0-9]+", "_", dataset_id.lower()).strip("_") or "medical"
    quiz_id, html_name = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix=f"medical_{safe_pack}_{safe_id}",
        exam_minutes=90,
        source_pack_id=pack_id,
        source_dataset_id=dataset_id,
    )

    return redirect(f"/quizzes/{html_name}")



# =========================
# IT STUDY - FILTERED STUDY PACK VIEW
# =========================
def _it_pack_page_data():
    """Aggregate validated datasets from installed IT / Cybersecurity Study Packs."""
    packs = discover_content_packs()
    it_packs = [
        (pack_id, candidate)
        for pack_id, candidate in packs.items()
        if _is_it_pack_manifest(pack_id, candidate)
    ]
    it_packs.sort(key=lambda item: str(item[1].get("name") or item[0]).casefold())

    if not it_packs:
        return None, [], [], []

    if len(it_packs) == 1:
        pack = dict(it_packs[0][1])
    else:
        pack = {
            "id": "it_collection",
            "name": "DLMS IT Study",
            "version": f"{len(it_packs)} installed packs",
            "description": "Aggregated IT and cybersecurity study content from installed Study Packs.",
        }

    datasets, image_datasets, quiz_datasets = [], [], []
    for pack_id, source_pack in it_packs:
        for descriptor in source_pack.get("datasets") or []:
            if not isinstance(descriptor, dict):
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = load_content_pack_dataset(pack_id, dataset_id)
                datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "type": descriptor.get("type") or data.get("type") or "matching",
                    "term_count": len(data.get("terms") or []),
                    "category": data.get("category") or "IT / Cybersecurity",
                })
            except Exception as exc:
                print(f"[IT STUDY] Dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

        for descriptor in source_pack.get("image_datasets") or []:
            if not isinstance(descriptor, dict):
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = load_content_pack_image_dataset(pack_id, dataset_id)
                images = data.get("images") or []
                image_datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "image_count": len(images),
                    "hotspot_count": sum(len(im.get("hotspots") or []) for im in images if isinstance(im, dict)),
                    "category": data.get("category") or "Diagrams & Images",
                })
            except Exception as exc:
                print(f"[IT STUDY] Image dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

        for descriptor in source_pack.get("quiz_datasets") or []:
            if not isinstance(descriptor, dict):
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = load_content_pack_quiz_dataset(pack_id, dataset_id)
                quiz_datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "question_count": len(data.get("questions") or []),
                    "image_count": len(data.get("images") or []),
                    "category": data.get("category") or "Question Set",
                })
            except Exception as exc:
                print(f"[IT STUDY] Question dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

    return pack, datasets, image_datasets, quiz_datasets


_IT_SIDEBAR = r"""
<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark">⌘</div>
        <div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div>
    </div>
    <nav class="dashboard-nav">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
        <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        <a class="dashboard-nav-item active" href="/it" {% if it_section == "home" %}aria-current="page"{% endif %}><span class="dashboard-nav-icon">⌘</span><span>IT Study</span></a>
        <div class="dashboard-nav-subitems medical-nav-subitems">
            <a class="dashboard-nav-subitem {% if it_section == 'matching' %}active{% endif %}" href="/it/matching" {% if it_section == "matching" %}aria-current="page"{% endif %}><span class="dashboard-nav-subicon">↔</span><span>Concepts &amp; Matching</span></a>
            <a class="dashboard-nav-subitem {% if it_section == 'images' %}active{% endif %}" href="/it/images" {% if it_section == "images" %}aria-current="page"{% endif %}><span class="dashboard-nav-subicon">◎</span><span>Diagrams &amp; Images</span></a>
            <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=IT%20/%20Cybersecurity&amp;from=it"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
        </div>
        <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
        <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
        <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
        <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
        <div class="dashboard-nav-group"><a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a></div>
    </nav>
    <div class="dashboard-nav-section-label"><span>System</span></div>
    <nav class="dashboard-nav dashboard-nav-system">
        <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
        <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
        <a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a>
        <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
        <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
    </nav>
    <div class="dashboard-sidebar-version">{{ pack.name }} · {{ pack.version }}</div>
</aside>
"""


def _it_empty_page():
    pack = {"name": "IT Study", "version": "No packs installed"}
    return render_template_string(r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>IT Study - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home medical-study-page it-study-page"><div class="dashboard-shell">""" + _IT_SIDEBAR + r"""
<main class="dashboard-main medical-main">
<header class="dashboard-header medical-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="medical-eyebrow">IT STUDY</div><h1>DLMS IT Study</h1><p>IT Study is ready. Install or create IT / Cybersecurity Study Packs to populate focused concept and diagram practice.</p></div></header>
<section class="medical-summary-grid"><article class="dashboard-stat-card"><span>Installed Packs</span><strong>0</strong><small>IT content is optional</small></article><article class="dashboard-stat-card"><span>Study Banks</span><strong>0</strong><small>create or install content</small></article><article class="dashboard-stat-card"><span>Image Sets</span><strong>0</strong><small>no diagrams installed</small></article></section>
<section class="medical-section-launch-grid">
<a class="dashboard-panel medical-section-launch-card" href="/study-packs/ai-builder?domain=IT%20/%20Cybersecurity&amp;from=it"><div class="medical-section-launch-icon">AI</div><div class="medical-section-launch-copy"><span class="medical-eyebrow">CREATE</span><h2>Create an IT Study Pack</h2><p>Open the unified AI Study Pack Builder with IT / Cybersecurity preselected.</p><span class="medical-section-launch-action">Open AI Study Pack Builder →</span></div></a>
<a class="dashboard-panel medical-section-launch-card" href="/content-packs"><div class="medical-section-launch-icon">⬡</div><div class="medical-section-launch-copy"><span class="medical-eyebrow">INSTALL / MANAGE</span><h2>Content Packs</h2><p>Install a validated IT Study Pack ZIP or manage existing packs.</p><span class="medical-section-launch-action">Open Content Packs →</span></div></a>
</section>
</main></div><script>document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));</script><script src="/static/nav-normalize.js"></script></body></html>
""", pack=pack, it_section="home")


@app.route("/it")
def it_study_home():
    pack, datasets, image_datasets, quiz_datasets = _it_pack_page_data()
    if not pack:
        return _it_empty_page()
    total_terms = sum(d["term_count"] for d in datasets)
    total_images = sum(d["image_count"] for d in image_datasets)
    total_hotspots = sum(d["hotspot_count"] for d in image_datasets)
    total_questions = sum(d["question_count"] for d in quiz_datasets)
    return render_template_string(r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>IT Study - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home medical-study-page it-study-page"><div class="dashboard-shell">""" + _IT_SIDEBAR + r"""
<main class="dashboard-main medical-main">
<header class="dashboard-header medical-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="medical-eyebrow">IT STUDY</div><h1>DLMS IT Study</h1><p>Focused IT and cybersecurity practice collected automatically from installed IT-domain Study Packs.</p></div></header>
<section class="medical-summary-grid"><article class="dashboard-stat-card"><span>Installed Packs</span><strong>{{ pack_count }}</strong><small>IT / Cybersecurity packs</small></article><article class="dashboard-stat-card"><span>Study Banks</span><strong>{{ datasets|length }}</strong><small>{{ total_terms }} concepts</small></article><article class="dashboard-stat-card"><span>Visual Sets</span><strong>{{ image_datasets|length }}</strong><small>{{ total_hotspots }} targets across {{ total_images }} images</small></article></section>
<section class="medical-section-launch-grid">
<a class="dashboard-panel medical-section-launch-card" href="/it/matching"><div class="medical-section-launch-icon">↔</div><div class="medical-section-launch-copy"><span class="medical-eyebrow">TEXT STUDY</span><h2>Concepts &amp; Matching</h2><p>Practice protocols, models, terminology, commands, security concepts, and other source-documented IT material.</p><div class="medical-dataset-meta"><span>{{ datasets|length }} study banks</span><span>{{ total_terms }} concepts</span></div><span class="medical-section-launch-action">Open Concepts &amp; Matching →</span></div></a>
<a class="dashboard-panel medical-section-launch-card" href="/it/images"><div class="medical-section-launch-icon">◎</div><div class="medical-section-launch-copy"><span class="medical-eyebrow">VISUAL STUDY</span><h2>Diagrams &amp; Images</h2><p>Practice network diagrams, hardware, interfaces, architecture, and other image-based identification.</p><div class="medical-dataset-meta"><span>{{ image_datasets|length }} image sets</span><span>{{ total_images }} images</span><span>{{ total_hotspots }} targets</span></div><span class="medical-section-launch-action">Open Diagrams &amp; Images →</span></div></a>
</section>
{% if quiz_datasets %}<section class="dashboard-panel medical-ai-builder-teaser"><div class="medical-ai-builder-teaser-icon">Q</div><div class="medical-ai-builder-teaser-copy"><span class="medical-eyebrow">MIXED PRACTICE</span><h2>{{ quiz_datasets|length }} Question Set{% if quiz_datasets|length != 1 %}s{% endif %}</h2><p>{{ total_questions }} mixed questions are available through the main Study Packs workspace.</p></div><a class="medical-primary-button medical-ai-builder-open" href="/study-packs">Open Study Packs</a></section>{% endif %}
<section class="dashboard-panel medical-ai-builder-teaser"><div class="medical-ai-builder-teaser-icon">AI</div><div class="medical-ai-builder-teaser-copy"><span class="medical-eyebrow">CUSTOM CONTENT</span><h2>AI Study Pack Builder</h2><p>Create source-disciplined IT / Cybersecurity Study Packs using the same validated content-pack workflow.</p><div class="medical-ai-builder-points"><span>✓ authoritative sources</span><span>✓ version-aware technical content</span><span>✓ open-license checks</span><span>✓ DLMS-ready schema</span></div></div><a class="medical-primary-button medical-ai-builder-open" href="/study-packs/ai-builder?domain=IT%20/%20Cybersecurity&amp;from=it">Build Custom Content</a></section>
</main></div><script>document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));</script><script src="/static/nav-normalize.js"></script></body></html>
""", pack=pack, datasets=datasets, image_datasets=image_datasets, quiz_datasets=quiz_datasets, total_terms=total_terms, total_images=total_images, total_hotspots=total_hotspots, total_questions=total_questions, pack_count=len([1 for pid,p in discover_content_packs().items() if _is_it_pack_manifest(pid,p)]), it_section="home")


@app.route("/it/matching")
def it_matching():
    pack, datasets, image_datasets, quiz_datasets = _it_pack_page_data()
    if not pack:
        return _it_empty_page()
    total_terms = sum(d["term_count"] for d in datasets)
    return render_template_string(r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>IT Concepts & Matching - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home medical-study-page it-study-page"><div class="dashboard-shell">""" + _IT_SIDEBAR + r"""
<main class="dashboard-main medical-main"><header class="dashboard-header medical-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="medical-eyebrow">IT STUDY · CONCEPTS</div><h1>Concepts &amp; Matching</h1><p>Choose an installed IT study bank, configure the round, and launch focused matching practice.</p></div></header>
<section class="medical-summary-grid medical-subpage-summary"><article class="dashboard-stat-card"><span>Study Banks</span><strong>{{ datasets|length }}</strong><small>installed IT datasets</small></article><article class="dashboard-stat-card"><span>Total Concepts</span><strong>{{ total_terms }}</strong><small>across available banks</small></article><article class="dashboard-stat-card medical-subpage-back-card"><span>IT Study</span><a href="/it">← Back to IT Study</a><small>choose another study area</small></article></section>
{% if datasets %}<section class="dashboard-panel medical-compact-dataset-panel"><div class="medical-compact-panel-heading"><div><span class="medical-eyebrow">INSTALLED IT CONTENT</span><h2>Study Banks</h2><p>Expand a row for details or launch a quiz directly.</p></div><div class="medical-compact-panel-actions"><button type="button" class="medical-ai-secondary-button" onclick="document.querySelectorAll('.it-detail-row').forEach(r=>r.hidden=false)">Expand All</button><button type="button" class="medical-ai-secondary-button" onclick="document.querySelectorAll('.it-detail-row').forEach(r=>r.hidden=true)">Collapse All</button></div></div><div class="study-dataset-table-wrap medical-dataset-table-wrap"><table class="study-dataset-table medical-dataset-table"><thead><tr><th>Type</th><th>Study Bank</th><th>Concepts</th><th>Round Options</th><th class="study-dataset-action-col">Action</th></tr></thead><tbody>
{% for d in datasets %}<tr><td><span class="study-type-badge matching">Matching</span></td><td><button type="button" class="study-dataset-title-button" onclick="const r=document.getElementById('it-match-{{ loop.index }}');r.hidden=!r.hidden">{{ d.title }}</button><small>{{ d.category }}</small></td><td><strong>{{ d.term_count }}</strong><small>items</small></td><td><form id="it-match-form-{{ loop.index }}" method="POST" action="/study-packs/generate"></form><div class="study-table-inline-form"><input form="it-match-form-{{ loop.index }}" type="hidden" name="pack_id" value="{{ d.pack_id }}"><input form="it-match-form-{{ loop.index }}" type="hidden" name="dataset_id" value="{{ d.id }}"><label><span>Pairs</span><input form="it-match-form-{{ loop.index }}" type="number" name="round_size" min="2" max="{{ d.term_count }}" value="{{ 10 if d.term_count >= 10 else d.term_count }}"></label><label><span>Direction</span><select form="it-match-form-{{ loop.index }}" name="direction"><option value="random">Random</option><option value="term_to_definition">Term → Definition</option><option value="definition_to_term">Definition → Term</option></select></label></div></td><td class="study-dataset-action-col"><button form="it-match-form-{{ loop.index }}" class="medical-primary-button study-table-primary" type="submit">Create Quiz</button></td></tr><tr id="it-match-{{ loop.index }}" class="study-dataset-detail-row it-detail-row" hidden><td colspan="5"><div class="medical-dataset-detail-content"><p>{{ d.description or 'No additional description supplied.' }}</p><div class="medical-dataset-detail-meta"><span><strong>Pack:</strong> {{ d.pack_name }}</span><span><strong>Dataset:</strong> {{ d.id }}</span></div></div></td></tr>{% endfor %}
</tbody></table></div></section>{% else %}<section class="dashboard-panel pack-empty-card"><h2>No IT matching datasets installed</h2><p>Create or install an IT / Cybersecurity Study Pack to populate this page.</p></section>{% endif %}
</main></div><script>document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));</script><script src="/static/nav-normalize.js"></script></body></html>
""", pack=pack, datasets=datasets, total_terms=total_terms, it_section="matching")


@app.route("/it/images")
def it_images():
    pack, datasets, image_datasets, quiz_datasets = _it_pack_page_data()
    if not pack:
        return _it_empty_page()
    total_images = sum(d["image_count"] for d in image_datasets)
    total_hotspots = sum(d["hotspot_count"] for d in image_datasets)
    return render_template_string(r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>IT Diagrams & Images - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home medical-study-page it-study-page"><div class="dashboard-shell">""" + _IT_SIDEBAR + r"""
<main class="dashboard-main medical-main"><header class="dashboard-header medical-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="medical-eyebrow">IT STUDY · VISUAL PRACTICE</div><h1>Diagrams &amp; Images</h1><p>Practice visual identification from installed IT diagrams, hardware images, architecture figures, and other source-documented visuals.</p></div></header>
<section class="medical-summary-grid medical-subpage-summary"><article class="dashboard-stat-card"><span>Image Sets</span><strong>{{ image_datasets|length }}</strong><small>installed visual datasets</small></article><article class="dashboard-stat-card"><span>Targets</span><strong>{{ total_hotspots }}</strong><small>across {{ total_images }} images</small></article><article class="dashboard-stat-card medical-subpage-back-card"><span>IT Study</span><a href="/it">← Back to IT Study</a><small>choose another study area</small></article></section>
{% if image_datasets %}<section class="dashboard-panel medical-compact-dataset-panel"><div class="medical-compact-panel-heading"><div><span class="medical-eyebrow">INSTALLED VISUAL CONTENT</span><h2>Image Study Sets</h2><p>Launch image practice or expand a row for source-pack details.</p></div></div><div class="study-dataset-table-wrap medical-dataset-table-wrap"><table class="study-dataset-table medical-dataset-table"><thead><tr><th>Type</th><th>Image Study Set</th><th>Images</th><th>Targets</th><th class="study-dataset-action-col">Action</th></tr></thead><tbody>
{% for d in image_datasets %}<tr><td><span class="study-type-badge image">Image</span></td><td><button type="button" class="study-dataset-title-button" onclick="const r=document.getElementById('it-image-{{ loop.index }}');r.hidden=!r.hidden">{{ d.title }}</button><small>{{ d.category }}</small></td><td><strong>{{ d.image_count }}</strong></td><td><strong>{{ d.hotspot_count }}</strong></td><td class="study-dataset-action-col"><form method="POST" action="/study-packs/image/generate"><input type="hidden" name="pack_id" value="{{ d.pack_id }}"><input type="hidden" name="dataset_id" value="{{ d.id }}"><button class="medical-primary-button study-table-primary" type="submit">Create Quiz</button></form></td></tr><tr id="it-image-{{ loop.index }}" class="study-dataset-detail-row" hidden><td colspan="5"><div class="medical-dataset-detail-content"><p>{{ d.description or 'No additional description supplied.' }}</p><div class="medical-dataset-detail-meta"><span><strong>Pack:</strong> {{ d.pack_name }}</span><span><strong>Dataset:</strong> {{ d.id }}</span></div></div></td></tr>{% endfor %}
</tbody></table></div></section>{% else %}<section class="dashboard-panel pack-empty-card"><h2>No IT image datasets installed</h2><p>Create or install an IT / Cybersecurity Study Pack with image datasets to populate this page.</p></section>{% endif %}
</main></div><script>document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));</script><script src="/static/nav-normalize.js"></script></body></html>
""", pack=pack, image_datasets=image_datasets, total_images=total_images, total_hotspots=total_hotspots, it_section="images")


# =========================
# GENERIC STUDY PACK PLATFORM
# =========================

def _study_pack_catalog():
    result = []
    for pack_id, pack in discover_content_packs().items():
        datasets, image_datasets, quiz_datasets = [], [], []
        for d in pack.get("datasets") or []:
            if not isinstance(d, dict): continue
            did = str(d.get("id") or "").strip()
            if not did: continue
            try:
                data = load_content_pack_dataset(pack_id, did)
                datasets.append({"id": did, "title": d.get("title") or data.get("title") or did, "description": d.get("description") or data.get("description") or "", "term_count": len(data.get("terms") or []), "category": data.get("category") or ""})
            except Exception as exc:
                print(f"[STUDY PACKS] Skipping {pack_id}/{did}: {exc}")
        for d in pack.get("image_datasets") or []:
            if not isinstance(d, dict): continue
            did = str(d.get("id") or "").strip()
            if not did: continue
            try:
                data = load_content_pack_image_dataset(pack_id, did)
                images = data.get("images") or []
                image_datasets.append({"id": did, "title": d.get("title") or data.get("title") or did, "description": d.get("description") or data.get("description") or "", "image_count": len(images), "hotspot_count": sum(len(i.get("hotspots") or []) for i in images), "category": data.get("category") or "Image Study"})
            except Exception as exc:
                print(f"[STUDY PACKS] Skipping image {pack_id}/{did}: {exc}")
        for d in pack.get("quiz_datasets") or []:
            if not isinstance(d, dict): continue
            did = str(d.get("id") or "").strip()
            if not did: continue
            try:
                data = load_content_pack_quiz_dataset(pack_id, did)
                qs, images = data.get("questions") or [], data.get("images") or []
                quiz_datasets.append({"id": did, "title": d.get("title") or data.get("title") or did, "description": d.get("description") or data.get("description") or "", "question_count": len(qs), "image_count": len(images), "hotspot_count": sum(1 for q in qs if str(q.get("type") or "") == "hotspot"), "category": data.get("category") or "Question Set"})
            except Exception as exc:
                print(f"[STUDY PACKS] Skipping questions {pack_id}/{did}: {exc}")
        if datasets or image_datasets or quiz_datasets:
            result.append({"id": pack_id, "name": pack.get("name") or pack_id, "version": pack.get("version") or "", "description": pack.get("description") or "", "domain": pack.get("content_domain") or ("medical" if pack_id == "medical" else "general"), "datasets": datasets, "image_datasets": image_datasets, "quiz_datasets": quiz_datasets})
    return sorted(result, key=lambda p: p["name"].casefold())


@app.route("/study-packs")
def study_packs_home():
    packs = _study_pack_catalog()
    domain_group = str(request.args.get("domain_group") or "").strip().lower()
    requested_installed_id = str(request.args.get("installed") or "").strip().lower()
    other_mode = domain_group == "other"
    if other_mode:
        def _is_other_pack(pack):
            raw = str(pack.get("domain") or "").strip().lower()
            normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
            return normalized not in {"medical", "it", "it_cybersecurity", "cybersecurity", "law", "legal"}
        packs = [pack for pack in packs if _is_other_pack(pack)]
    installed_pack_id = next(
        (pack["id"] for pack in packs if pack["id"] == requested_installed_id), ""
    )
    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{{ "Other Studies" if other_mode else "Study Packs" }} - DLMS</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home study-packs-page">
<div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark">▣</div>
        <div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div>
    </div>
    <nav class="dashboard-nav">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
        <a class="dashboard-nav-item active" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
        {% if medical_pack_installed %}<a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>{% endif %}
        <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
        <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
        <div class="dashboard-nav-group"><a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a><div class="dashboard-nav-submenu"><a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a><a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a></div></div>
    </nav>
    <div class="dashboard-nav-section-label"><span>System</span></div>
    <nav class="dashboard-nav dashboard-nav-system">
        <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
        <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
        <a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a>
        <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
        <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
    </nav>
    <div class="dashboard-sidebar-version">{{ "Other Studies" if other_mode else "Study Packs" }}</div>
</aside>

<main class="dashboard-main study-packs-main">
    <header class="dashboard-header">
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
        <div>
            <div class="medical-eyebrow">{{ "CROSS-DOMAIN STUDY" if other_mode else "CUSTOM STUDY CONTENT" }}</div>
            <h1>{{ "Other Studies" if other_mode else "Study Packs" }}</h1>
            <p>{{ "Study subjects outside the dedicated IT, Law, and Medical workspaces." if other_mode else "Launch focused practice from installed study content without scrolling through large card grids." }}</p>
        </div>
    </header>

    {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
    <div class="content-pack-flashes">
        {% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}
    </div>
    {% endif %}
    {% endwith %}

    {% if installed_pack_id %}
    <section class="dashboard-panel study-pack-installed-notice" aria-label="Newly installed Study Pack">
        <div><span class="medical-eyebrow">STUDY PACK INSTALLED</span><strong>{{ installed_pack_id }}</strong><p>Your validated Study Pack is ready. Open it below and choose the dataset you want to study.</p></div>
        <a class="medical-primary-button" href="#installed-study-pack">Open Study Pack</a>
    </section>
    {% endif %}

    <section class="study-pack-launch-grid">
        <a class="dashboard-panel study-pack-launch" href="{{ '/study-packs/ai-builder?domain=Other&from=other' if other_mode else '/study-packs/ai-builder' }}">
            <div class="study-pack-launch-icon">AI</div>
            <div><span class="medical-eyebrow">CREATE</span><h2>AI Study Pack Builder</h2><p>{{ "Create a source-disciplined prompt for a subject outside IT, Law, or Medical." if other_mode else "Create a source-disciplined DLMS pack prompt for any subject." }}</p></div>
        </a>
        <a class="dashboard-panel study-pack-launch" href="/study-packs/image-builder">
            <div class="study-pack-launch-icon">▧</div>
            <div><span class="medical-eyebrow">BUILD</span><h2>Build from Images</h2><p>Use your own images for regular questions, matching, or hotspots.</p></div>
        </a>
        <a class="dashboard-panel study-pack-launch" href="/admin/image-editor">
            <div class="study-pack-launch-icon">◎</div>
            <div><span class="medical-eyebrow">EDIT</span><h2>Image Study Editor</h2><p>Prepare images and refine clickable regions without changing originals.</p></div>
        </a>
    </section>

    {% if packs %}
    <div class="study-pack-toolbar">
        <div>
            <span class="medical-eyebrow">INSTALLED CONTENT</span>
            <strong>{{ packs|length }} study pack{{ '' if packs|length == 1 else 's' }}</strong>
        </div>
        <div class="study-pack-toolbar-actions">
            <a class="medical-ai-secondary-button study-pack-manage-link" href="/content-packs">Manage Packs</a>
            <button type="button" class="medical-ai-secondary-button" id="expandAllPacks">Expand All</button>
            <button type="button" class="medical-ai-secondary-button" id="collapseAllPacks">Collapse All</button>
        </div>
    </div>

    {% for pack in packs %}
    <details id="{{ 'installed-study-pack' if pack.id == installed_pack_id else '' }}" class="dashboard-panel study-pack-section study-pack-collapsible {% if pack.id == installed_pack_id %}is-newly-installed{% endif %}" data-pack-id="{{ pack.id }}" {% if loop.first or pack.id == installed_pack_id %}open{% endif %}>
        <summary class="study-pack-summary">
            <div class="study-pack-summary-main">
                <span class="study-pack-chevron" aria-hidden="true">›</span>
                <div>
                    <span class="medical-eyebrow">{{ pack.domain|upper }} · {{ pack.version }}</span>
                    <h2>{{ pack.name }}</h2>
                    <p>{{ pack.description }}</p>
                </div>
            </div>
            <div class="study-pack-summary-meta">
                <span class="pack-count-pill">{{ pack.datasets|length + pack.image_datasets|length + pack.quiz_datasets|length }} datasets</span>
                {% if pack.datasets %}<span>{{ pack.datasets|length }} matching</span>{% endif %}
                {% if pack.image_datasets %}<span>{{ pack.image_datasets|length }} image</span>{% endif %}
                {% if pack.quiz_datasets %}<span>{{ pack.quiz_datasets|length }} mixed</span>{% endif %}
            </div>
        </summary>

        <div class="study-pack-body study-pack-table-body">
            <div class="study-dataset-table-wrap">
            <table class="study-dataset-table">
                <thead>
                    <tr>
                        <th>Type</th>
                        <th>Dataset</th>
                        <th>Content</th>
                        <th>Options</th>
                        <th class="study-dataset-action-col">Action</th>
                    </tr>
                </thead>
                <tbody>
                {% for d in pack.quiz_datasets %}
                    <tr>
                        <td><span class="study-type-badge mixed">Mixed</span></td>
                        <td>
                            <button type="button" class="study-dataset-title-button" onclick="toggleDatasetDetails('{{ pack.id }}-mixed-{{ loop.index }}')">{{ d.title }}</button>
                            {% if d.category %}<small>{{ d.category }}</small>{% endif %}
                        </td>
                        <td><span>{{ d.question_count }} questions</span>{% if d.image_count %}<small>{{ d.image_count }} images{% if d.hotspot_count %} · {{ d.hotspot_count }} hotspots{% endif %}</small>{% endif %}</td>
                        <td><span class="study-options-muted">Ready to generate</span></td>
                        <td class="study-dataset-action-col">
                            <form method="POST" action="/study-packs/quiz/generate">
                                <input type="hidden" name="pack_id" value="{{ pack.id }}">
                                <input type="hidden" name="dataset_id" value="{{ d.id }}">
                                <button class="study-table-primary" type="submit">Create Quiz</button>
                            </form>
                        </td>
                    </tr>
                    <tr class="study-dataset-detail-row" id="dataset-{{ pack.id }}-mixed-{{ loop.index }}" hidden>
                        <td colspan="5"><p>{{ d.description or 'No additional description supplied.' }}</p></td>
                    </tr>
                {% endfor %}

                {% for d in pack.datasets %}
                    <tr>
                        <td><span class="study-type-badge matching">Matching</span></td>
                        <td>
                            <button type="button" class="study-dataset-title-button" onclick="toggleDatasetDetails('{{ pack.id }}-matching-{{ loop.index }}')">{{ d.title }}</button>
                            {% if d.category %}<small>{{ d.category }}</small>{% endif %}
                        </td>
                        <td><span>{{ d.term_count }} items</span></td>
                        <td>
                            <div class="study-table-inline-form">
                                <label><span>Pairs</span><input form="matchForm-{{ pack.id }}-{{ loop.index }}" type="number" name="round_size" min="2" max="{{ d.term_count }}" value="{{ 10 if d.term_count >= 10 else d.term_count }}"></label>
                                <label><span>Direction</span>
                                    <select form="matchForm-{{ pack.id }}-{{ loop.index }}" name="direction">
                                        <option value="random">Random</option>
                                        <option value="term_to_definition">Term → Definition</option>
                                        <option value="definition_to_term">Definition → Term</option>
                                    </select>
                                </label>
                            </div>
                        </td>
                        <td class="study-dataset-action-col">
                            <form id="matchForm-{{ pack.id }}-{{ loop.index }}" method="POST" action="/study-packs/generate">
                                <input type="hidden" name="pack_id" value="{{ pack.id }}">
                                <input type="hidden" name="dataset_id" value="{{ d.id }}">
                                <button class="study-table-primary" type="submit">Create Quiz</button>
                            </form>
                        </td>
                    </tr>
                    <tr class="study-dataset-detail-row" id="dataset-{{ pack.id }}-matching-{{ loop.index }}" hidden>
                        <td colspan="5"><p>{{ d.description or 'No additional description supplied.' }}</p></td>
                    </tr>
                {% endfor %}

                {% for d in pack.image_datasets %}
                    <tr>
                        <td><span class="study-type-badge image">Image</span></td>
                        <td>
                            <button type="button" class="study-dataset-title-button" onclick="toggleDatasetDetails('{{ pack.id }}-image-{{ loop.index }}')">{{ d.title }}</button>
                            {% if d.category %}<small>{{ d.category }}</small>{% endif %}
                        </td>
                        <td><span>{{ d.image_count }} image{{ '' if d.image_count == 1 else 's' }}</span><small>{{ d.hotspot_count }} targets</small></td>
                        <td><span class="study-options-muted">Hotspot practice</span></td>
                        <td class="study-dataset-action-col">
                            <form method="POST" action="/study-packs/image/generate">
                                <input type="hidden" name="pack_id" value="{{ pack.id }}">
                                <input type="hidden" name="dataset_id" value="{{ d.id }}">
                                <button class="study-table-primary" type="submit">Create Quiz</button>
                            </form>
                        </td>
                    </tr>
                    <tr class="study-dataset-detail-row" id="dataset-{{ pack.id }}-image-{{ loop.index }}" hidden>
                        <td colspan="5"><p>{{ d.description or 'No additional description supplied.' }}</p></td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
            </div>
        </div>
    </details>
    {% endfor %}
    {% else %}
    <section class="dashboard-panel pack-empty-card">
        <h2>{{ "No Other Studies packs installed yet" if other_mode else "No usable study packs yet" }}</h2>
        <p>{{ "Create a pack with the AI Study Pack Builder or install a compatible Content Pack whose domain is outside IT, Law, and Medical." if other_mode else "Create one with the AI Study Pack Builder, Build from Images, or install a compatible Content Pack." }}</p>
    </section>
    {% endif %}
</main>
</div>

<script>
const sidebar=document.getElementById('dashboardSidebar');
document.getElementById('menuButton')?.addEventListener('click',()=>sidebar?.classList.toggle('open'));

const packDetails=[...document.querySelectorAll('.study-pack-collapsible')];
const stateKey='dlms.studyPacks.openState.v1';
function readPackState(){try{return JSON.parse(localStorage.getItem(stateKey)||'{}')||{}}catch(e){return {}}}
function savePackState(){const state={};packDetails.forEach(el=>state[el.dataset.packId]=el.open);try{localStorage.setItem(stateKey,JSON.stringify(state))}catch(e){}}
const savedState=readPackState();
packDetails.forEach(el=>{if(Object.prototype.hasOwnProperty.call(savedState,el.dataset.packId))el.open=!!savedState[el.dataset.packId];el.addEventListener('toggle',savePackState)});
const installedPack=document.getElementById('installed-study-pack');
if(installedPack){
    installedPack.open=true;
    requestAnimationFrame(()=>installedPack.scrollIntoView({block:'start',behavior:'smooth'}));
}
document.getElementById('expandAllPacks')?.addEventListener('click',()=>{packDetails.forEach(el=>el.open=true);savePackState()});
document.getElementById('collapseAllPacks')?.addEventListener('click',()=>{packDetails.forEach(el=>el.open=false);savePackState()});
function toggleDatasetDetails(id){
    const row=document.getElementById(`dataset-${id}`);
    if(row) row.hidden=!row.hidden;
}
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""", packs=packs, medical_pack_installed=True, other_mode=other_mode,
       installed_pack_id=installed_pack_id)




@app.route("/study-packs/quiz/generate", methods=["POST"])
def study_pack_generate_quiz_dataset():
    pack_id = str(request.form.get("pack_id") or "").strip().lower()
    dataset_id = str(request.form.get("dataset_id") or "").strip()
    pack = get_content_pack(pack_id)
    if not pack:
        flash("Study pack is not installed.", "error")
        return redirect("/study-packs")
    try:
        data = load_content_pack_quiz_dataset(pack_id, dataset_id)
        runtime_questions, db_questions = _quiz_dataset_runtime(pack_id, data)
        title = str(data.get("title") or data["_descriptor"].get("title") or "Study Questions").strip()
        _, html_name = _create_quiz_from_runtime(
            f"{title} — Practice", runtime_questions, db_questions,
            filename_prefix=f"study_questions_{pack_id}_{dataset_id}", exam_minutes=90,
            source_pack_id=pack_id, source_dataset_id=dataset_id
        )
        return redirect(f"/quizzes/{html_name}")
    except Exception as exc:
        print(f"[STUDY PACK QUIZ BUILD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to build the selected Study Pack quiz.", "error")
        return redirect("/study-packs")


@app.route("/study-packs/generate", methods=["POST"])
def study_pack_generate_matching():
    pack_id=str(request.form.get("pack_id") or "").strip().lower(); dataset_id=str(request.form.get("dataset_id") or "").strip(); direction=str(request.form.get("direction") or "random").strip()
    if direction not in {"term_to_definition","definition_to_term","random"}: direction="random"
    pack=get_content_pack(pack_id)
    if not pack: flash("Study pack is not installed.","error"); return redirect("/study-packs")
    try: data=load_content_pack_dataset(pack_id,dataset_id)
    except Exception as exc:
        print(f"[STUDY PACK DATASET LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to load the selected study dataset.", "error")
        return redirect("/study-packs")
    terms=data.get("terms") or []
    if len(terms)<2: flash("This dataset does not contain enough items.","error"); return redirect("/study-packs")
    try: round_size=int(request.form.get("round_size","10"))
    except (TypeError,ValueError): round_size=10
    round_size=max(2,min(round_size,min(100,len(terms))))
    title=str(data.get("title") or data["_descriptor"].get("title") or "Study Practice").strip(); source=data.get("source") or {}
    pairs=[{"left":i["term"],"right":i["definition"],"category":i.get("category","") ,"explanation":i.get("explanation") or i.get("study_explanation") or "","verification":i.get("verification") or data.get("verification") or {},"source":i.get("source") or source or {}} for i in terms]
    quiz_data=[{"number":1,"type":"matching","question":str(data.get("question_text") or "Match each item with its best answer.").strip(),"pairs":pairs,"round_size":round_size,"direction":direction,"concepts":_standalone_matching_concepts(data, context=f"matching dataset {dataset_id!r}"),"source":{"organization":source.get("organization") or pack.get("publisher") or "","dataset":source.get("dataset") or title,"version":source.get("version") or pack.get("version") or "","url":source.get("url") or "","license":source.get("license") or ""}}]
    safe_pack=re.sub(r"[^a-z0-9]+","_",pack_id).strip("_") or "study"; safe_id=re.sub(r"[^a-z0-9]+","_",dataset_id.lower()).strip("_") or "dataset"; quiz_title=f"{title} — {round_size}-Pair Practice"
    quiz_id,html_name=_publish_quiz(quiz_title,quiz_data,filename_prefix=f"study_{safe_pack}_{safe_id}",exam_minutes=90,source_pack_id=pack_id,source_dataset_id=dataset_id)
    return redirect(f"/quizzes/{html_name}")


@app.route("/study-packs/image/generate", methods=["POST"])
def study_pack_generate_image():
    pack_id=str(request.form.get("pack_id") or "").strip().lower(); dataset_id=str(request.form.get("dataset_id") or "").strip(); pack=get_content_pack(pack_id)
    if not pack: flash("Study pack is not installed.","error"); return redirect("/study-packs")
    try: data=load_content_pack_image_dataset(pack_id,dataset_id)
    except Exception as exc:
        print(f"[STUDY PACK IMAGE LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to load the selected image dataset.", "error")
        return redirect("/study-packs")
    runtime_questions=[]; db_questions=[]; qnum=1
    for image in data.get("images") or []:
        image_url=url_for("content_pack_asset",pack_id=pack_id,asset_path=image.get("file")); source=image.get("source") or data.get("source") or {}; hotspots=list(image.get("hotspots") or []); random.shuffle(hotspots)
        for hotspot in hotspots:
            label=str(hotspot.get("label") or "").strip()
            if not label: continue
            prompt=str(hotspot.get("prompt") or f"Identify {label}.").strip()
            runtime_questions.append({"number":qnum,"type":"hotspot","question":prompt,"image_url":image_url,"image_alt":image.get("alt_text") or data.get("title") or "Study image","image_edits":image.get("edits") or [],"target":hotspot.get("shape") or {},"target_label":label,"explanation":hotspot.get("explanation") or "","verification":hotspot.get("verification") or {},"image_source":{"organization":source.get("organization") or "","work":source.get("work") or "","url":source.get("url") or image.get("source_url") or "","license":source.get("license") or image.get("license") or "","attribution":source.get("attribution") or image.get("attribution") or ""}})
            concepts=_hotspot_concepts(hotspot, image, hotspot, data, context=f"image dataset hotspot {hotspot.get('id') or label!r}")
            runtime_questions[-1]["concepts"]=concepts
            db_questions.append({"number":qnum,"type":"choice","question":prompt+" [Image hotspot]","choices":[{"label":"A","text":label,"is_correct":True}],"concepts":concepts,"source":{"organization":source.get("organization") or "","dataset":data.get("title") or dataset_id,"version":pack.get("version") or "","url":source.get("url") or image.get("source_url") or "","license":source.get("license") or image.get("license") or ""}}); qnum+=1
    if not runtime_questions: flash("This image dataset contains no usable targets.","error"); return redirect("/study-packs")
    title=str(data.get("title") or data["_descriptor"].get("title") or "Image Study").strip(); quiz_title=f"{title} — Image Practice"; safe_pack=re.sub(r"[^a-z0-9]+","_",pack_id).strip("_") or "study"; safe_id=re.sub(r"[^a-z0-9]+","_",dataset_id.lower()).strip("_") or "images"
    quiz_id,html_name=_publish_quiz(quiz_title,runtime_questions,db_questions,filename_prefix=f"study_image_{safe_pack}_{safe_id}",exam_minutes=90,source_pack_id=pack_id,source_dataset_id=dataset_id)
    return redirect(f"/quizzes/{html_name}")


@app.route("/study-packs/ai-builder", methods=["GET","POST"])
def study_pack_ai_builder():
    cfg = load_portal_config()

    allowed_domains = ["IT / Cybersecurity", "General", "Science", "Medical", "History", "Language", "Other"]
    requested_domain = str(request.args.get("domain") or "").strip()
    domain = requested_domain if requested_domain in allowed_domains else "IT / Cybersecurity"
    from_section = str(request.args.get("from") or "").strip().lower()

    topic = str(request.args.get("topic") or "").strip()
    difficulty = "Foundational" if domain == "Medical" else "Intermediate"
    size = "Standard"
    image_count = "2–3"
    image_style = "Mixed"
    include_matching = True
    include_images = True
    include_multiple_choice = False
    generated_prompt = ""

    ai_provider = str(cfg.get("ai_provider") or "chatgpt").strip().lower()
    if ai_provider not in {"chatgpt","claude","gemini","local"}:
        ai_provider = "chatgpt"

    if request.method == "POST":
        topic = str(request.form.get("topic") or "").strip()
        domain = str(request.form.get("domain") or "General").strip()
        if domain not in allowed_domains:
            domain = "General"
        difficulty = str(request.form.get("difficulty") or "Intermediate").strip()
        size = str(request.form.get("size") or "Standard").strip()
        image_count = str(request.form.get("image_count") or "2–3").strip()
        image_style = str(request.form.get("image_style") or "Mixed").strip()
        ai_provider = str(request.form.get("ai_provider") or ai_provider).strip().lower()
        from_section = str(request.form.get("from_section") or "").strip().lower()

        include_matching = "include_matching" in request.form
        include_images = "include_images" in request.form
        include_multiple_choice = "include_multiple_choice" in request.form

        if difficulty not in {"Foundational","Intermediate","Comprehensive"}:
            difficulty = "Intermediate"
        if size not in {"Compact","Standard","Large"}:
            size = "Standard"
        if image_count not in {"None","1","2–3","4–6"}:
            image_count = "2–3"
        if image_style not in {"Real / photographic","Diagram / schematic","Drawn educational illustration","Mixed"}:
            image_style = "Mixed"
        if ai_provider not in {"chatgpt","claude","gemini","local"}:
            ai_provider = "chatgpt"

        requested = []
        if include_matching:
            requested.append(
                "Create one or more high-quality matching datasets with unique terms, unique record IDs where IDs are used, "
                "one-to-one term/answer mappings, meaningfully distinct answers, no duplicate or near-duplicate pairs, "
                "and enough semantic distinction to remain unambiguous when shuffled. Repair all collisions before delivery, "
                "and include source-supported Study Mode explanations."
            )
        if include_multiple_choice:
            mcq_counts = {
                "Compact": "about 10–15",
                "Standard": "about 20–30",
                "Large": "about 40–60",
            }
            requested.append(
                f"Create {mcq_counts[size]} source-supported single-select multiple-choice questions. "
                "Use the DLMS choice-question JSON contract: 2–26 distinct choices, exactly one true "
                "JSON is_correct value, a concise explanation, and question-level source support. "
                "Vary the supplied correct-choice position naturally across the question set; do not put "
                "every correct answer in the same position and do not force perfect equality. "
                "Do not guess: omit any question whose correct answer cannot be supported reliably."
            )
        if include_images:
            requested.append("Create image/diagram hotspot datasets when they genuinely improve learning, following the image count and style request below.")
        if not requested:
            requested.append("Choose the most appropriate DLMS study content types for this topic.")
        requested.append(
            "For every generated question, include the exact question-level field \"concepts\" with 1–3 "
            "specific reusable concepts. Reuse spelling for the same skill; avoid broad metadata labels."
        )

        size_map = {
            "Compact": "Keep the pack focused: about 20–40 high-value matching items per dataset.",
            "Standard": "Aim for useful depth: about 40–80 distinct matching items per dataset when supported.",
            "Large": "Build broad coverage without padding; split large subjects into multiple focused datasets."
        }

        if include_images and image_count != "None":
            image_guidance = (
                f"Request {image_count} useful image(s) when possible. Preferred style: {image_style}. "
                "Bundle exact legally reusable images and create separate hotspot lists for each image. "
                "If multiple images cover different subtopics, create separate image datasets."
            )
        else:
            image_guidance = "Do not create image datasets for this request."

        domain_slug = re.sub(r"[^a-z0-9]+","_",domain.lower()).strip("_") or "general"

        if topic:
            study_pack_template = str(cfg.get("study_pack_ai_prompt_template") or DEFAULT_STUDY_CONTENT_PACK_PROMPT)
            medical_addendum = str(cfg.get("medical_study_pack_ai_addendum") or DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM)
            generated_prompt = (
                study_pack_template
                .replace("{{domain}}", domain)
                .replace("{{domain_slug}}", domain_slug)
                .replace("{{topic}}", topic)
                .replace("{{content_request}}", "\n".join(f"- {x}" for x in requested))
                .replace("{{difficulty}}", difficulty)
                .replace("{{size_guidance}}", size_map.get(size, size_map["Standard"]))
                .replace("{{image_guidance}}", image_guidance)
            )
            if domain == "Medical":
                generated_prompt += "\n\n" + medical_addendum.strip()
        else:
            generated_prompt = "Enter a study topic before generating the prompt."

    providers = {
        "chatgpt":"https://chatgpt.com/",
        "claude":"https://claude.ai/",
        "gemini":"https://gemini.google.com/",
        "local":str(cfg.get("ai_custom_url") or "").strip()
    }
    ai_url = providers.get(ai_provider,"")
    if from_section == "medical" or domain == "Medical":
        back_url, back_label = "/medical", "Medical Study"
    elif from_section == "other":
        back_url, back_label = "/study-packs?domain_group=other", "Other Studies"
    else:
        back_url, back_label = "/study-packs", "Study Packs"

    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI Study Pack Builder - DLMS</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home medical-ai-builder-page">
<div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand"><div class="dashboard-brand-mark">AI</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div>
    <nav class="dashboard-nav">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
        <a class="dashboard-nav-item active" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        {% if medical_pack_installed %}<a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>{% endif %}
        <a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a>
    </nav>
    <div class="dashboard-sidebar-version">AI Study Pack Builder</div>
</aside>

<main class="dashboard-main medical-main">
    <header class="dashboard-header">
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
        <div>
            <div class="medical-eyebrow">ANY SUBJECT · CUSTOM CONTENT</div>
            <h1>AI Study Pack Builder</h1>
            <p>One domain-aware builder creates controlled DLMS-ready content-pack prompts for medical, IT, science, history, and other study subjects.</p>
        </div>
    </header>

    <ol class="study-pack-workflow-steps" aria-label="AI Study Pack workflow">
        <li class="{{ 'is-complete' if generated_prompt else 'is-current' }}">Configure</li><li class="{{ 'is-current' if generated_prompt else '' }}">Generate Prompt</li><li>Bring Back ZIP</li><li>Validate</li><li>Install</li><li>Study</li>
    </ol>

    <section class="dashboard-panel medical-ai-builder-panel">
        <form method="POST" class="medical-ai-builder-form">
            <input type="hidden" name="from_section" value="{{ from_section }}">
            <label class="medical-ai-topic-field">
                <span>What do you want to study?</span>
                <input type="text" name="topic" value="{{ topic }}" required placeholder="Examples: AWS networking, cranial nerves, Linux permissions, cellular biology">
            </label>

            <div class="study-ai-grid">
                <label><span>Subject / Domain</span>
                    <select name="domain" id="studyDomain">
                    {% for x in domains %}<option {% if domain==x %}selected{% endif %}>{{ x }}</option>{% endfor %}
                    </select>
                </label>
                <label><span>Difficulty</span><select name="difficulty">{% for x in ['Foundational','Intermediate','Comprehensive'] %}<option {% if difficulty==x %}selected{% endif %}>{{ x }}</option>{% endfor %}</select></label>
                <label><span>Pack Size</span><select name="size">{% for x in ['Compact','Standard','Large'] %}<option {% if size==x %}selected{% endif %}>{{ x }}</option>{% endfor %}</select></label>
                <label><span>Images Requested</span><select name="image_count">{% for x in ['None','1','2–3','4–6'] %}<option {% if image_count==x %}selected{% endif %}>{{ x }}</option>{% endfor %}</select></label>
                <label><span>Image Style</span><select name="image_style">{% for x in ['Real / photographic','Diagram / schematic','Drawn educational illustration','Mixed'] %}<option {% if image_style==x %}selected{% endif %}>{{ x }}</option>{% endfor %}</select></label>
                <label><span>AI Provider</span><select name="ai_provider"><option value="chatgpt" {% if ai_provider=='chatgpt' %}selected{% endif %}>ChatGPT</option><option value="claude" {% if ai_provider=='claude' %}selected{% endif %}>Claude</option><option value="gemini" {% if ai_provider=='gemini' %}selected{% endif %}>Gemini</option><option value="local" {% if ai_provider=='local' %}selected{% endif %}>Local / Custom</option></select></label>
            </div>

            <div id="medicalGuardrailNotice" class="study-ai-domain-notice {% if domain != 'Medical' %}is-hidden{% endif %}">
                <strong>Medical safeguards enabled</strong>
                <span>Medical selections automatically add stricter source, licensing, provenance, and non-synthetic-image requirements to the prompt.</span>
            </div>

            <div class="medical-ai-option-grid">
                <label class="medical-ai-option-card"><input type="checkbox" name="include_matching" {% if include_matching %}checked{% endif %}><div><strong>Matching / Terminology</strong><span>Create source-supported matching datasets with Study Mode explanations.</span></div></label>
                <label class="medical-ai-option-card"><input type="checkbox" name="include_multiple_choice" {% if include_multiple_choice %}checked{% endif %}><div><strong>Multiple-Choice Questions</strong><span>Create source-supported single-select questions with DLMS-assigned A–Z labels.</span></div></label>
                <label class="medical-ai-option-card"><input type="checkbox" name="include_images" {% if include_images %}checked{% endif %}><div><strong>Images / Diagrams</strong><span>Create one or multiple image-based hotspot datasets when useful.</span></div></label>
            </div>

            <div class="medical-ai-action-row">
                <button class="medical-primary-button" type="submit">Generate AI Prompt</button>
                <a class="medical-ai-quiet-link" href="{{ back_url }}">← Back to {{ back_label }}</a>
            </div>
        </form>
    </section>

    {% if generated_prompt %}
    <section class="dashboard-panel medical-ai-prompt-panel">
        <div class="medical-ai-builder-heading">
            <div><span class="medical-eyebrow">GENERATED PROMPT</span><h2>Ready for {{ ai_provider|capitalize }}</h2><p>Edit if desired, then copy it to your AI provider.</p></div>
            <span class="medical-ai-safety-pill">{{ 'Medical guardrails' if domain == 'Medical' else 'Source-first' }}</span>
        </div>
        <textarea id="studyPrompt" class="medical-ai-prompt-box" rows="30">{{ generated_prompt }}</textarea>
        <div class="medical-ai-action-row">
            {% if ai_url %}<button type="button" class="medical-primary-button" onclick='copyAndOpen({{ ai_url|tojson }})'>Copy Prompt &amp; Open AI</button>{% endif %}
            <button type="button" class="medical-ai-secondary-button" onclick="copyPrompt()">Copy Prompt</button>
        </div>
    </section>

    {% if topic %}
    <section class="dashboard-panel study-pack-builder-return-panel">
        <div class="medical-ai-builder-heading">
            <div><span class="medical-eyebrow">STEP 3 · BRING BACK ZIP</span><h2>Bring Back Study Pack ZIP</h2><p>Upload the completed DLMS Study Pack ZIP from your AI provider. DLMS will stage and independently validate it before installation.</p></div>
            <span class="medical-ai-safety-pill">ZIP required</span>
        </div>
        <form method="POST" action="/study-packs/ai-builder/import" enctype="multipart/form-data" class="content-pack-upload-form study-pack-builder-return-form">
            <label class="build-field"><span>Completed Study Pack ZIP</span><input type="file" name="pack_zip" accept=".zip,application/zip" required><small>One top-level Study Pack folder with manifest.json. Text-only AI responses are not installable until packaged with their required files and assets.</small></label>
            <button class="medical-primary-button" type="submit">Validate Study Pack ZIP</button>
        </form>
    </section>
    {% endif %}
    {% endif %}
</main>
</div>

<script>
function box(){return document.getElementById('studyPrompt')}
function selectP(){const b=box();if(!b)return null;b.focus();b.select();b.setSelectionRange(0,b.value.length);return b}
function copyPrompt(show=true){const b=selectP();if(!b)return false;let ok=false;try{ok=document.execCommand('copy')}catch(e){}if(show)alert(ok?'Prompt copied.':'Prompt selected; press Ctrl+C.');return ok}
function copyAndOpen(u){copyPrompt(false);window.open(u,'_blank','noopener,noreferrer')}
document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));
document.getElementById('studyDomain')?.addEventListener('change', (event) => {
    document.getElementById('medicalGuardrailNotice')?.classList.toggle('is-hidden', event.target.value !== 'Medical');
});
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""",
        topic=topic,
        domain=domain,
        domains=allowed_domains,
        difficulty=difficulty,
        size=size,
        image_count=image_count,
        image_style=image_style,
        ai_provider=ai_provider,
        include_matching=include_matching,
        include_images=include_images,
        include_multiple_choice=include_multiple_choice,
        generated_prompt=generated_prompt,
        ai_url=ai_url,
        from_section=from_section,
        back_url=back_url,
        back_label=back_label,
        medical_pack_installed=True,
    )




# =========================
# LAW STUDY MODULE - LANDING
# =========================
@app.route("/law")
def law_study_home():
    portal_title = get_portal_title()
    law_registry = load_law_registry()
    saved_cases = len(law_registry.get("cases", []))
    course_count = len(law_registry.get("folders", []))

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Law Study - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home law-hub-page">
<div class="dashboard-shell">
    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>

        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item active" href="/law" aria-current="page"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck &amp; Printable Cards</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>

        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>

        <button class="dashboard-shutdown" id="shutdownBtn" type="button">
            <span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span>
        </button>
        <div class="dashboard-sidebar-version">Law Study</div>
    </aside>

    <main class="dashboard-main law-hub-main">
        <header class="dashboard-header law-hub-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="law-hub-eyebrow">LAW STUDY</div>
                <h1>Casework &amp; Review</h1>
                <p>Build structured case reviews, preserve AI-assisted study packets, and organize course material.</p>
            </div>
        </header>

        <section class="law-hub-summary" aria-label="Law Study summary">
            <article class="law-hub-stat">
                <span>Saved Cases</span><strong>{{ saved_cases }}</strong><small>case reviews</small>
            </article>
            <article class="law-hub-stat">
                <span>Courses</span><strong>{{ course_count }}</strong><small>study folders</small>
            </article>
            <article class="law-hub-stat law-hub-stat-ai">
                <span>Workflow</span><strong>AI Ready</strong><small>prompt + import workflow</small>
            </article>
        </section>

        <section class="law-hub-grid" aria-label="Law Study tools">
            <a class="law-hub-card primary" href="/law/create">
                <div class="law-hub-card-icon">§</div>
                <div><span class="law-hub-card-kicker">CREATE</span><h2>Create Case Review</h2><p>Build a case brief, Socratic questions, IRAC drill, and flashcards.</p></div>
                <span class="law-hub-card-arrow">›</span>
            </a>

            <a class="law-hub-card" href="/law/import">
                <div class="law-hub-card-icon">⇩</div>
                <div><span class="law-hub-card-kicker">IMPORT</span><h2>Import Case Packet</h2><p>Paste AI-generated study output for preview and saving.</p></div>
                <span class="law-hub-card-arrow">›</span>
            </a>

            <a class="law-hub-card" href="/law/cases">
                <div class="law-hub-card-icon">⚖</div>
                <div><span class="law-hub-card-kicker">LIBRARY</span><h2>My Case Reviews</h2><p>Browse saved cases organized by course and topic.</p></div>
                <span class="law-hub-card-arrow">›</span>
            </a>

            <a class="law-hub-card" href="/law/imports">
                <div class="law-hub-card-icon">▤</div>
                <div><span class="law-hub-card-kicker">ARCHIVE / RECOVERY</span><h2>Saved Imports</h2><p>Inspect, reparse, or manage raw packets retained from guided and manual imports.</p></div>
                <span class="law-hub-card-arrow">›</span>
            </a>
        </section>

        <section class="law-hub-coming dashboard-panel">
            <div class="law-hub-coming-heading">
                <div><span class="law-hub-eyebrow">PLANNED TOOLS</span><h2>Future Study Modes</h2></div>
                <span class="law-hub-coming-badge">Coming later</span>
            </div>
            <div class="law-hub-coming-grid">
                <div class="law-hub-coming-item"><strong>IRAC Practice</strong><span>Issue spotting and structured analysis drills.</span></div>
                <div class="law-hub-coming-item"><strong>Socratic Prep</strong><span>Cold-call style review before class.</span></div>
                <div class="law-hub-coming-item"><strong>Rule Flashcards</strong><span>Rules and holdings from saved cases.</span></div>
                <div class="law-hub-coming-item"><strong>Case Compare</strong><span>Compare facts, holdings, and reasoning.</span></div>
            </div>
        </section>
    </main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");
menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));

document.addEventListener("click", (event) => {
    if (window.innerWidth > 820) return;
    if (!sidebar.classList.contains("open")) return;
    if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
    sidebar.classList.remove("open");
});

document.getElementById("shutdownBtn").addEventListener("click", async () => {
    if (!confirm("SHUTDOWN DLMS\\n\\nThis will stop the application.\\n\\nYou will need to restart it manually.\\n\\nContinue?")) return;
    try {
        await fetch("/api/shutdown", { method: "POST" });
        document.body.innerHTML = '<div class="shutdown-screen"><div class="shutdown-screen-card"><h1>DLMS has been shut down.</h1><p>You can close this browser tab.</p></div></div>';
    } catch (err) {
        alert("DLMS may already be shutting down.");
    }
});
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""", portal_title=portal_title, law_registry=law_registry, saved_cases=saved_cases, course_count=course_count)


# =========================
# LAW STUDY MODULE - CREATE CASE REVIEW FORM
# =========================
@app.route("/law/create", methods=["GET", "POST"])
def law_create_case_review():
    portal_title = get_portal_title()
    law_registry = load_law_registry()
    law_folders = law_registry.get("folders", [])

    case_name = ""
    course = law_folders[0] if law_folders else "Torts"
    ai_provider = "chatgpt"
    generated_prompt = ""
    ai_provider_url = ""
    case_slug = ""

    include_case_brief = True
    include_socratic = True
    include_irac = True
    include_flashcards = True

    if request.method == "POST":
        case_name = request.form.get("case_name", "").strip()
        course = request.form.get("course", course).strip()
        ai_provider = request.form.get("ai_provider", "chatgpt").strip().lower()

        case_slug = make_law_case_slug(case_name)

        if case_name:
            try:
                _law_service.start_pending_case_workflow(
                    law_registry,
                    case_name=case_name,
                    case_slug=case_slug,
                    course=course,
                    created_at=datetime.now().isoformat(timespec="seconds"),
                    save_law_registry=save_law_registry,
                )
            except Exception as e:
                print(f"[LAW WORKFLOW ERROR] Failed starting case workflow: {e}")
                return "Failed to start Law case workflow", 500

        provider_urls = {
            "chatgpt": "https://chatgpt.com/",
            "claude": "https://claude.ai/",
            "gemini": "https://gemini.google.com/",
            "local": load_portal_config().get("ai_custom_url", "")
        }

        ai_provider_url = provider_urls.get(ai_provider, "")

        include_case_brief = "include_case_brief" in request.form
        include_socratic = "include_socratic" in request.form
        include_irac = "include_irac" in request.form
        include_flashcards = "include_flashcards" in request.form

        requested_sections = []

        if include_case_brief:
            requested_sections.append("""
1. Case Brief
   - Full case name and citation
   - Court and year
   - Procedural posture
   - Key facts
   - Issue
   - Rule
   - Holding
   - Reasoning
   - Important concurrence or dissent, if any
""".strip())

        if include_socratic:
            requested_sections.append("""
    2. Socratic Review
    - Five cold-call style questions
    - One fact-change question
    - One policy question
    - Do not place the model answers directly under the questions

    2A. Socratic Answer Key
    - Provide short model guidance for each Socratic question
    - Keep each answer concise
    - This section should be treated as hidden-by-default in DLMS
    - Label each answer so it clearly matches the question number
    """.strip())

        if include_irac:
            requested_sections.append("""
3. IRAC Drill
   - One short practice fact pattern based on the case
   - Issue
   - Rule
   - Application / Analysis
   - Conclusion
   - Model IRAC answer
""".strip())

        if include_flashcards:
            requested_sections.append("""
4. Rule Flashcards
   - Five active-recall flashcards
   - Front: question
   - Back: concise answer
   - Focus on rule, holding, reasoning, and key facts
""".strip())

        if case_name:
            cfg = load_portal_config()
            law_prompt_template = str(cfg.get("law_ai_prompt_template") or DEFAULT_LAW_AI_PROMPT).strip()

            # Law Study uses its own prompt template so quiz-explanation prompts remain independent.
            generated_prompt = (
                law_prompt_template
                .replace("{{case_name}}", case_name)
                .replace("{{course}}", course)
                .replace("{{study_sections}}", chr(10).join(requested_sections))
            )

        else:
            generated_prompt = "Please enter a case name before generating the AI prompt."

    return render_template_string("""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Create Case Review - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home law-subpage law-create-page">
<div class="dashboard-shell">

<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="img">
                <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div>
            <div class="dashboard-brand-title">DLMS</div>
            <div class="dashboard-brand-subtitle">Training Center</div>
        </div>
    </div>

    <nav class="dashboard-nav" aria-label="Primary navigation">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        <a class="dashboard-nav-item active" href="/law" aria-current="page"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
        {% if medical_pack_installed %}
        <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
        {% endif %}
        <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
        <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
    </nav>

    <div class="dashboard-nav-section-label"><span>System</span></div>

    <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
        <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
        <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
        <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
        <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
    </nav>

    <button class="dashboard-shutdown" id="shutdownBtn" type="button">
        <span class="dashboard-shutdown-icon">⏻</span>
        <span>Shutdown DLMS</span>
    </button>
    <div class="dashboard-sidebar-version">Law Study</div>
</aside>

<main class="dashboard-main law-subpage-main">
    <header class="dashboard-header law-subpage-header">
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
        <div>
            <div class="law-subpage-eyebrow">LAW STUDY</div>
            <h1>Create Case Review</h1>
            <p>Build a structured case-study prompt for your preferred AI provider.</p>
        </div>
    </header>

    <section class="dashboard-panel law-workspace-panel">
        <div class="law-panel-heading">
            <div>
                <span class="law-subpage-eyebrow">NEW CASE WORKFLOW</span>
                <h2>Case Study Setup</h2>
                <p>Enter the case, choose a course, and select the study tools you want included.</p>
            </div>
            <span class="law-status-pill success">AI Ready</span>
        </div>

        <form method="POST" action="/law/create" class="law-form">
            <div class="law-form-grid">
                <label class="law-field law-field-wide">
                    <span>Case Name</span>
                    <input type="text" name="case_name" value="{{ case_name }}" required
                           placeholder="Example: Palsgraf v. Long Island Railroad Co.">
                </label>

                <label class="law-field">
                    <span>Course / Folder</span>
                    <select name="course">
                        {% for folder in law_folders %}
                        <option value="{{ folder }}" {% if folder == course %}selected{% endif %}>{{ folder }}</option>
                        {% endfor %}
                    </select>
                </label>

                <label class="law-field">
                    <span>AI Provider</span>
                    <select name="ai_provider">
                        <option value="chatgpt" {% if ai_provider == "chatgpt" %}selected{% endif %}>ChatGPT</option>
                        <option value="claude" {% if ai_provider == "claude" %}selected{% endif %}>Claude</option>
                        <option value="gemini" {% if ai_provider == "gemini" %}selected{% endif %}>Gemini</option>
                        <option value="local" {% if ai_provider == "local" %}selected{% endif %}>Local / Custom</option>
                    </select>
                </label>
            </div>

            <div class="law-options-heading">
                <span class="law-subpage-eyebrow">STUDY PACKET</span>
                <h3>Include these sections</h3>
            </div>

            <div class="law-option-grid">
                <label class="law-option-card">
                    <input type="checkbox" name="include_case_brief" {% if include_case_brief %}checked{% endif %}>
                    <div><strong>Case Brief</strong><span>Facts, issue, rule, holding, and reasoning.</span></div>
                </label>
                <label class="law-option-card">
                    <input type="checkbox" name="include_socratic" {% if include_socratic %}checked{% endif %}>
                    <div><strong>Socratic Review</strong><span>Cold-call questions and a concise answer key.</span></div>
                </label>
                <label class="law-option-card">
                    <input type="checkbox" name="include_irac" {% if include_irac %}checked{% endif %}>
                    <div><strong>IRAC Drill</strong><span>Issue, rule, analysis, conclusion, and model response.</span></div>
                </label>
                <label class="law-option-card">
                    <input type="checkbox" name="include_flashcards" {% if include_flashcards %}checked{% endif %}>
                    <div><strong>Rule Flashcards</strong><span>Active-recall cards for rule, holding, and key facts.</span></div>
                </label>
            </div>

            <div class="law-action-row">
                <button type="submit" class="law-primary-action">Generate AI Prompt</button>
                <button type="button" class="law-secondary-action" onclick="location.href='/law/import'">Proceed to Import Case Packet</button>
                <button type="button" class="law-quiet-action" onclick="location.href='/law'">Back to Law Study</button>
            </div>
        </form>

        {% if generated_prompt %}
        <section class="law-generated-panel">
            <div class="law-panel-heading compact">
                <div><span class="law-subpage-eyebrow">GENERATED PROMPT</span><h2>Ready for AI</h2></div>
            </div>
            <textarea id="lawPromptBox" class="law-prompt-box" rows="18">{{ generated_prompt }}</textarea>
            <div class="law-action-row">
                {% if ai_provider_url %}
                <button type="button" class="law-primary-action" onclick='copyPromptAndOpenAi({{ ai_provider_url|tojson }})'>Copy Prompt &amp; Open AI</button>
                {% endif %}
                <button type="button" class="law-secondary-action" onclick="copyLawPrompt()">Copy Prompt</button>
            </div>
            {% if not ai_provider_url %}
            <p class="law-helper-text">No custom AI URL is configured for Local / Custom.</p>
            {% endif %}
        </section>
        {% endif %}
    </section>
</main>
</div>

<script>
function copyLawPromptToClipboard(showAlert = true) {
    const box = document.getElementById("lawPromptBox");
    if (!box) {
        if (showAlert) alert("Prompt box not found.");
        return false;
    }
    box.focus();
    box.select();
    box.setSelectionRange(0, box.value.length);
    let copied = false;
    try { copied = document.execCommand("copy"); } catch (err) { copied = false; }
    if (copied) {
        if (showAlert) alert("Prompt copied to clipboard.");
        return true;
    }
    if (showAlert) alert("Copy failed. The prompt is selected, so press Ctrl+C manually.");
    return false;
}
function copyLawPrompt() { copyLawPromptToClipboard(true); }
function openSelectedAi(url) {
    if (!url) { alert("No AI provider URL is configured."); return; }
    window.open(url, "_blank", "noopener,noreferrer");
}
function copyPromptAndOpenAi(url) {
    const copied = copyLawPromptToClipboard(false);
    if (!copied) alert("The prompt could not be copied automatically. It is selected, so press Ctrl+C manually. The AI site will now open.");
    openSelectedAi(url);
}
</script>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");

if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));

    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}

const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("Shut down DLMS? You will need to restart it manually.")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) {
            alert("Failed to shut down DLMS.");
        }
    });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>""",
    portal_title=portal_title,
    law_folders=law_folders,
    case_name=case_name,
    case_slug=case_slug,
    course=course,
    ai_provider=ai_provider,
    generated_prompt=generated_prompt,
    ai_provider_url=ai_provider_url,
    include_case_brief=include_case_brief,
    include_socratic=include_socratic,
    include_irac=include_irac,
    include_flashcards=include_flashcards
    )

# =========================
# LAW STUDY HELPER FUNCTIONS
# =========================

def make_law_case_slug(case_name):
    return _law_packet_parser.make_law_case_slug(case_name)


def extract_law_slug_from_import_filename(filename):
    return _law_packet_parser.extract_law_slug_from_import_filename(
        filename,
        secure_filename=secure_filename,
    )






def safe_law_import_filename(filename):
    return _law_packet_parser.safe_law_import_filename(
        filename,
        secure_filename=secure_filename,
    )


def save_law_raw_packet(raw_packet, case_slug=""):
    return _law_service.save_law_raw_packet(
        raw_packet,
        case_slug,
        imports_folder=LAW_IMPORTS_FOLDER,
        safe_law_import_filename=safe_law_import_filename,
        now=datetime.now,
        makedirs=os.makedirs,
        join_path=os.path.join,
        open_file=open,
    )



def parse_law_packet_sections(raw_text):
    return _law_packet_parser.parse_law_packet_sections(raw_text)


def extract_law_case_title(raw_text, fallback_filename="Untitled Case Review"):
    return _law_packet_parser.extract_law_case_title(raw_text, fallback_filename)



def get_law_case_by_id(case_id):
    return _law_service.get_law_case_by_id(
        case_id,
        load_law_registry=load_law_registry,
    )


def _load_law_case_data(case_path):
    return _law_service.load_law_case_data(
        case_path,
        open_file=open,
        json_module=json,
    )


def parse_socratic_questions(socratic_text):
    return _law_packet_parser.parse_socratic_questions(socratic_text)



# =========================
# LAW STUDY MODULE - CANCEL PENDING WORKFLOW
# =========================
@app.route("/law/workflow/cancel", methods=["POST"])
def law_cancel_pending_workflow():
    registry = load_law_registry()

    if "pending_case_workflow" in registry:
        try:
            _law_service.cancel_pending_case_workflow(
                registry,
                save_law_registry=save_law_registry,
            )
        except Exception as e:
            print(f"[LAW WORKFLOW ERROR] Failed cancelling case workflow: {e}")
            return "Failed to cancel Law case workflow", 500

    return redirect("/law/import?workflow_cancelled=1")





# =========================
# LAW STUDY MODULE - IMPORT CASE PACKET
# =========================
@app.route("/law/import", methods=["GET", "POST"])
def law_import_case_packet():
    portal_title = get_portal_title()

    law_registry = load_law_registry()
    pending_workflow = law_registry.get("pending_case_workflow", {}) or {}

    case_name = request.values.get("case_name", "").strip()
    case_slug = request.values.get("case_slug", "").strip()

    if not case_name:
        case_name = str(pending_workflow.get("case_name", "")).strip()

    if not case_slug:
        case_slug = str(pending_workflow.get("case_slug", "")).strip()

    if case_name and not case_slug:
        case_slug = make_law_case_slug(case_name)

    raw_packet = ""
    packet_submitted = False
    line_count = 0
    char_count = 0
    saved_file = ""
    save_message = ""

    if request.method == "POST":
        raw_packet = request.form.get("raw_packet", "").strip()
        action = request.form.get("action", "preview")

        packet_submitted = bool(raw_packet)

        if raw_packet:
            line_count = len(raw_packet.splitlines())
            char_count = len(raw_packet)

            if action in {"save_and_preview", "save_raw"}:
                try:
                    saved_file = save_law_raw_packet(raw_packet, case_slug)

                    if action == "save_and_preview":
                        return redirect(url_for("law_view_saved_import", filename=saved_file))

                    save_message = f"Saved raw case packet as {saved_file}"

                except Exception as e:
                    print(f"[LAW IMPORT ERROR] Failed saving raw packet: {e}")
                    save_message = "Error: failed to save raw case packet."

    return render_template_string("""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Import Case Packet - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home law-subpage law-import-page">
<div class="dashboard-shell">

<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="img">
                <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div>
            <div class="dashboard-brand-title">DLMS</div>
            <div class="dashboard-brand-subtitle">Training Center</div>
        </div>
    </div>

    <nav class="dashboard-nav" aria-label="Primary navigation">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        <a class="dashboard-nav-item active" href="/law" aria-current="page"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
        {% if medical_pack_installed %}
        <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
        {% endif %}
        <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
        <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
    </nav>

    <div class="dashboard-nav-section-label"><span>System</span></div>

    <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
        <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
        <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
        <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
        <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
    </nav>

    <button class="dashboard-shutdown" id="shutdownBtn" type="button">
        <span class="dashboard-shutdown-icon">⏻</span>
        <span>Shutdown DLMS</span>
    </button>
    <div class="dashboard-sidebar-version">Law Study</div>
</aside>

<main class="dashboard-main law-subpage-main">
    <header class="dashboard-header law-subpage-header">
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
        <div>
            <div class="law-subpage-eyebrow">LAW STUDY</div>
            <h1>Import Case Packet</h1>
            <p>Paste AI output, preview the packet, and save it for structured review.</p>
        </div>
    </header>

    <section class="dashboard-panel law-workspace-panel">
        <div class="law-panel-heading">
            <div>
                <span class="law-subpage-eyebrow">CASE PACKET</span>
                <h2>Paste AI-Generated Study Packet</h2>
                <p>Keep the complete DLMS import block intact so it can be saved and parsed later.</p>
            </div>
            <span class="law-status-pill info">Import Workspace</span>
        </div>

        {% if request.args.get('workflow_cancelled') %}
        <div class="law-notice success"><strong>Active case workflow cancelled.</strong><span>Pending case metadata has been cleared.</span></div>
        {% endif %}

        {% if case_name %}
        <div class="law-workflow-banner">
            <div>
                <span class="law-subpage-eyebrow">ACTIVE WORKFLOW</span>
                <strong>{{ case_name }}</strong>
                <small>File slug: {{ case_slug }}</small>
            </div>
            <form method="POST" action="/law/workflow/cancel"
                  onsubmit="return confirm('Cancel the active Law Study workflow? This will not delete saved imports or case reviews.');">
                <button type="submit" class="law-quiet-action">Cancel Workflow</button>
            </form>
        </div>
        {% else %}
        <div class="law-notice warning">
            <div><strong>No active case workflow.</strong><span>Start with Create Case Review if you want this import tied to a case name and course.</span></div>
            <button type="button" class="law-secondary-action" onclick="location.href='/law/create'">Start Case Review</button>
        </div>
        {% endif %}

        <form method="POST" action="/law/import" class="law-form">
            <input type="hidden" name="case_name" value="{{ case_name }}">
            <input type="hidden" name="case_slug" value="{{ case_slug }}">

            <label class="law-field law-field-wide">
                <span>Case Packet Text</span>
                <textarea name="raw_packet" class="law-import-textarea" rows="22"
                          placeholder="Paste the AI-generated case brief, Socratic review, IRAC drill, and flashcards here...">{{ raw_packet }}</textarea>
            </label>

            <div class="law-action-row">
                <button type="submit" name="action" value="save_and_preview" class="law-primary-action">Save &amp; Preview Case Packet</button>
                <button type="submit" name="action" value="preview" class="law-secondary-action">Check Pasted Text</button>
                <button type="submit" name="action" value="save_raw" class="law-quiet-action">Save Raw Packet Only</button>
                <button type="button" class="law-secondary-action" onclick="location.href='/law/imports'">Saved Imports Archive</button>
                <button type="button" class="law-secondary-action" onclick="location.href='/law/create'">Create Another Prompt</button>
                <button type="button" class="law-quiet-action" onclick="location.href='/law'">Back to Law Study</button>
            </div>
        </form>

        {% if save_message %}
        <div class="law-notice success"><strong>{{ save_message }}</strong></div>
        {% endif %}

        {% if packet_submitted %}
        <section class="law-preview-panel">
            <div class="law-panel-heading compact">
                <div><span class="law-subpage-eyebrow">PACKET PREVIEW</span><h2>Import Summary</h2></div>
            </div>
            <div class="law-metric-grid">
                <div class="law-metric-card"><span>Lines</span><strong>{{ line_count }}</strong></div>
                <div class="law-metric-card"><span>Characters</span><strong>{{ char_count }}</strong></div>
                <div class="law-metric-card"><span>Status</span><strong>Ready</strong></div>
            </div>
        </section>
        {% endif %}
    </section>
</main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");

if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));

    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}

const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("Shut down DLMS? You will need to restart it manually.")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) {
            alert("Failed to shut down DLMS.");
        }
    });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>""",
    portal_title=portal_title,
    case_name=case_name,
    case_slug=case_slug,
    raw_packet=raw_packet,
    packet_submitted=packet_submitted,
    line_count=line_count,
    char_count=char_count,
    saved_file=saved_file,
    save_message=save_message
    )


# =========================
# LAW STUDY MODULE - SAVED RAW IMPORTS
# =========================
@app.route("/law/imports")
def law_saved_imports():
    portal_title = get_portal_title()

    imports = []

    try:
        imports = _law_service.list_law_raw_imports(
            LAW_IMPORTS_FOLDER,
            from_timestamp=datetime.fromtimestamp,
            imports=imports,
            makedirs=os.makedirs,
            listdir=os.listdir,
            join_path=os.path.join,
            isfile=os.path.isfile,
            stat_file=os.stat,
        )

    except Exception as e:
        print(f"[LAW IMPORTS ERROR] Failed loading saved imports: {e}")

    return render_template_string("""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Saved Law Imports - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home law-subpage law-list-page">
<div class="dashboard-shell">

<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="img">
                <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div>
            <div class="dashboard-brand-title">DLMS</div>
            <div class="dashboard-brand-subtitle">Training Center</div>
        </div>
    </div>

    <nav class="dashboard-nav" aria-label="Primary navigation">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        <a class="dashboard-nav-item active" href="/law" aria-current="page"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
        {% if medical_pack_installed %}
        <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
        {% endif %}
        <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
        <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
    </nav>

    <div class="dashboard-nav-section-label"><span>System</span></div>

    <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
        <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
        <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
        <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
        <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
    </nav>

    <button class="dashboard-shutdown" id="shutdownBtn" type="button">
        <span class="dashboard-shutdown-icon">⏻</span>
        <span>Shutdown DLMS</span>
    </button>
    <div class="dashboard-sidebar-version">Law Study</div>
</aside>

<main class="dashboard-main law-subpage-main">
    <header class="dashboard-header law-subpage-header">
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
        <div>
            <div class="law-subpage-eyebrow">LAW STUDY</div>
            <h1>Saved Law Imports</h1>
            <p>Raw AI-generated case packets saved for future parsing and review.</p>
        </div>
    </header>

    <section class="dashboard-panel law-workspace-panel">
        <div class="law-panel-heading">
            <div>
                <span class="law-subpage-eyebrow">RAW PACKETS</span>
                <h2>Saved Imports</h2>
                <p>Open an import to inspect it or create a structured case review.</p>
            </div>
            <span class="law-count-pill">{{ imports|length }} saved</span>
        </div>

        {% if request.args.get('deleted') %}
        <div class="law-notice success"><strong>Saved import deleted.</strong><span>Structured case reviews were not changed.</span></div>
        {% endif %}

        {% if imports %}
        <div class="law-record-list">
            {% for item in imports %}
            <article class="law-record-row">
                <div class="law-record-icon" aria-hidden="true">▤</div>
                <div class="law-record-copy">
                    <h3>{{ item.filename }}</h3>
                    <div class="law-record-meta">
                        <span>{{ item.size }} bytes</span>
                        <span>•</span>
                        <span>Modified {{ item.modified }}</span>
                    </div>
                </div>
                <div class="law-record-actions">
                    <button type="button" class="law-open-action" onclick="location.href='/law/imports/{{ item.filename }}'">Open</button>
                    <form method="POST" action="/law/imports/{{ item.filename }}/delete"
                          onsubmit="return confirm('Delete this saved raw import? This will not delete any structured case reviews already created from it.');">
                        <button type="submit" class="law-trash-action" aria-label="Delete import" title="Delete import">🗑</button>
                    </form>
                </div>
            </article>
            {% endfor %}
        </div>
        {% else %}
        <div class="law-empty-state">
            <h3>No saved imports yet</h3>
            <p>Use Import Case Packet to paste and save an AI-generated study packet.</p>
        </div>
        {% endif %}

        <div class="law-action-row law-footer-actions">
            <button type="button" class="law-primary-action" onclick="location.href='/law/import'">Import Case Packet</button>
            <button type="button" class="law-quiet-action" onclick="location.href='/law'">Back to Law Study</button>
        </div>
    </section>
</main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");

if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));

    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}

const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("Shut down DLMS? You will need to restart it manually.")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) {
            alert("Failed to shut down DLMS.");
        }
    });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>""",
    portal_title=portal_title,
    imports=imports
    )







# =========================
# LAW STUDY MODULE - VIEW SAVED RAW IMPORT
# =========================
@app.route("/law/imports/<path:filename>")
def law_view_saved_import(filename):
    portal_title = get_portal_title()

    safe_name = safe_law_import_filename(filename)

    if not safe_name:
        return "Invalid import filename", 400

    import_path = os.path.join(LAW_IMPORTS_FOLDER, safe_name)

    if not os.path.exists(import_path) or not os.path.isfile(import_path):
        return "Saved import not found", 404

    try:
        raw_packet = _law_service.load_law_raw_packet(import_path, open_file=open)
    except Exception as e:
        print(f"[LAW IMPORT ERROR] Failed reading saved import: {e}")
        return "Failed to read saved import", 500

    line_count = len(raw_packet.splitlines())
    char_count = len(raw_packet)

    modified = datetime.fromtimestamp(os.stat(import_path).st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    size = os.stat(import_path).st_size
    parsed_sections = parse_law_packet_sections(raw_packet)

    return render_template_string("""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>View Law Import - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home law-subpage law-import-detail-page">
<div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="img">
                <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div>
    </div>
    <nav class="dashboard-nav" aria-label="Primary navigation">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        <a class="dashboard-nav-item active" href="/law" aria-current="page"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
        {% if medical_pack_installed %}
        <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
        {% endif %}
        <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
        <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
    </nav>
    <div class="dashboard-nav-section-label"><span>System</span></div>
    <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
        <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
        <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
        <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
        <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
    </nav>
    <button class="dashboard-shutdown" id="shutdownBtn" type="button"><span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span></button>
    <div class="dashboard-sidebar-version">Law Study</div>
</aside>
<main class="dashboard-main law-subpage-main">
    <header class="dashboard-header law-subpage-header">
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
        <div><div class="law-subpage-eyebrow">LAW STUDY · SAVED IMPORT</div><h1>View Law Import</h1><p>Inspect the raw packet and recognized study sections before creating a structured case review.</p></div>
    </header>

    <section class="dashboard-panel law-detail-panel">
        <div class="law-detail-heading">
            <div><span class="law-subpage-eyebrow">RAW CASE PACKET</span><h2>{{ filename }}</h2><p>Saved AI-generated source packet awaiting or supporting structured case review.</p></div>
            <span class="law-status-pill">Raw Import</span>
        </div>

        <div class="law-detail-stat-grid">
            <div class="law-detail-stat"><span>Lines</span><strong>{{ line_count }}</strong></div>
            <div class="law-detail-stat"><span>Characters</span><strong>{{ char_count }}</strong></div>
            <div class="law-detail-stat"><span>Size</span><strong>{{ size }} bytes</strong></div>
            <div class="law-detail-stat"><span>Modified</span><strong class="law-detail-date">{{ modified }}</strong></div>
        </div>

        {% if request.args.get('created_case') %}
        <div class="law-message success"><strong>Case review created.</strong><span>The structured case file was saved and added to the Law Study registry.</span></div>
        {% endif %}

        <div class="law-section-heading"><span class="law-subpage-eyebrow">PARSER</span><h3>Recognized Sections</h3></div>
        {% if parsed_sections %}
        <div class="law-parse-grid">
            {% for section in parsed_sections %}
            <article class="law-parse-card"><div class="law-parse-check">✓</div><div><h3>{{ section.title }}</h3><p>{{ section.line_count }} lines · {{ section.char_count }} characters</p></div></article>
            {% endfor %}
        </div>
        <div class="law-message success"><strong>Parser preview:</strong><span>DLMS found {{ parsed_sections|length }} recognized section{% if parsed_sections|length != 1 %}s{% endif %}. Nothing new is saved until you create the case review.</span></div>
        <form method="POST" action="/law/imports/{{ filename }}/create_case" class="law-detail-primary-form">
            <button type="submit" class="law-primary-action" onclick="return confirm('Create a structured Law Case Review from this import?');">Create Case Review From Import</button>
        </form>
        {% else %}
        <div class="law-message warning"><strong>No recognized Law Study headings found.</strong><span>Expected headings include Case Brief, Socratic Review, Socratic Answer Key, IRAC Drill, and Rule Flashcards.</span></div>
        {% endif %}

        <div class="law-section-heading"><span class="law-subpage-eyebrow">SOURCE</span><h3>Raw Packet Text</h3></div>
        <textarea class="law-raw-packet" readonly rows="24">{{ raw_packet }}</textarea>

        <div class="law-detail-actions">
            <button type="button" class="law-secondary-action" onclick="location.href='/law/imports'">Back to Saved Imports</button>
            <button type="button" class="law-secondary-action" onclick="location.href='/law/cases'">My Case Reviews</button>
            <button type="button" class="law-secondary-action" onclick="location.href='/law/import'">Import Another Packet</button>
        </div>
    </section>
</main>
</div>
<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");
if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}
const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("Shut down DLMS? You will need to restart it manually.")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) { alert("Failed to shut down DLMS."); }
    });
}
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""",
    portal_title=portal_title,
    filename=safe_name,
    raw_packet=raw_packet,
    line_count=line_count,
    char_count=char_count,
    modified=modified,
    size=size,
    parsed_sections=parsed_sections
    )



# =========================
# LAW STUDY MODULE - DELETE SAVED RAW IMPORT
# =========================
@app.route("/law/imports/<path:filename>/delete", methods=["POST"])
def law_delete_saved_import(filename):
    safe_name = safe_law_import_filename(filename)

    if not safe_name:
        return "Invalid import filename", 400

    import_path = os.path.join(LAW_IMPORTS_FOLDER, safe_name)

    try:
        _law_service.delete_law_raw_packet(
            import_path,
            exists=os.path.exists,
            isfile=os.path.isfile,
            remove_file=os.remove,
        )

    except Exception as e:
        print(f"[LAW IMPORT ERROR] Failed deleting saved import: {e}")
        return "Failed to delete saved import", 500

    return redirect("/law/imports?deleted=1")



# =========================
# LAW STUDY MODULE - CREATE CASE REVIEW FROM IMPORT
# =========================
@app.route("/law/imports/<path:filename>/create_case", methods=["POST"])
def law_create_case_from_import(filename):
    safe_name = safe_law_import_filename(filename)

    if not safe_name:
        return "Invalid import filename", 400

    import_path = os.path.join(LAW_IMPORTS_FOLDER, safe_name)

    if not os.path.exists(import_path) or not os.path.isfile(import_path):
        return "Saved import not found", 404

    try:
        raw_packet = _law_service.load_law_raw_packet(import_path, open_file=open)
    except Exception as e:
        print(f"[LAW CASE ERROR] Failed reading import: {e}")
        return "Failed to read saved import", 500

    parsed_sections = parse_law_packet_sections(raw_packet)

    if not parsed_sections:
        return "No recognized Law Study sections were found. Cannot create case review yet.", 400

    try:
        case_id = _law_service.create_law_case_from_import(
            safe_name,
            raw_packet,
            parsed_sections,
            cases_folder=LAW_CASES_FOLDER,
            load_law_registry=load_law_registry,
            extract_law_slug_from_import_filename=extract_law_slug_from_import_filename,
            extract_law_case_title=extract_law_case_title,
            secure_filename=secure_filename,
            now=datetime.now,
            commit_law_case_and_registry=_commit_law_case_and_registry,
            makedirs=os.makedirs,
            join_path=os.path.join,
            isfile=os.path.isfile,
        )
    except Exception as e:
        print(f"[LAW CASE ERROR] Failed creating case review: {e}")
        return "Failed to create case review", 500

    return redirect(url_for("law_view_case_review", case_id=case_id))



# =========================
# LAW STUDY MODULE - SAVED CASE REVIEWS
# =========================
@app.route("/law/cases")
def law_case_reviews():
    portal_title = get_portal_title()
    registry = load_law_registry()

    cases = registry.get("cases", [])

    # newest first
    cases = sorted(
        cases,
        key=lambda c: str(c.get("created_at", "")),
        reverse=True
    )

    return render_template_string("""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>My Case Reviews - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home law-subpage law-list-page">
<div class="dashboard-shell">

<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="img">
                <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div>
            <div class="dashboard-brand-title">DLMS</div>
            <div class="dashboard-brand-subtitle">Training Center</div>
        </div>
    </div>

    <nav class="dashboard-nav" aria-label="Primary navigation">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        <a class="dashboard-nav-item active" href="/law" aria-current="page"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
        {% if medical_pack_installed %}
        <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
        {% endif %}
        <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
        <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
    </nav>

    <div class="dashboard-nav-section-label"><span>System</span></div>

    <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
        <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
        <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
        <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
        <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
    </nav>

    <button class="dashboard-shutdown" id="shutdownBtn" type="button">
        <span class="dashboard-shutdown-icon">⏻</span>
        <span>Shutdown DLMS</span>
    </button>
    <div class="dashboard-sidebar-version">Law Study</div>
</aside>

<main class="dashboard-main law-subpage-main">
    <header class="dashboard-header law-subpage-header">
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
        <div>
            <div class="law-subpage-eyebrow">LAW STUDY</div>
            <h1>My Case Reviews</h1>
            <p>Saved case briefs, Socratic review, and IRAC practice in one place.</p>
        </div>
    </header>

    <section class="dashboard-panel law-workspace-panel">
        <div class="law-panel-heading">
            <div>
                <span class="law-subpage-eyebrow">CASE LIBRARY</span>
                <h2>Saved Case Reviews</h2>
                <p>Open a structured review or remove one you no longer need.</p>
            </div>
            <span class="law-count-pill">{{ cases|length }} saved</span>
        </div>

        {% if request.args.get('deleted') %}
        <div class="law-notice success"><strong>Case review deleted.</strong><span>The original raw import was not changed.</span></div>
        {% endif %}

        {% if cases %}
        <div class="law-record-list">
            {% for case in cases %}
            <article class="law-record-row">
                <div class="law-record-icon" aria-hidden="true">§</div>
                <div class="law-record-copy">
                    <h3>{{ case.title }}</h3>
                    <div class="law-record-meta">
                        <span>{{ case.course or "Uncategorized" }}</span>
                        <span>•</span>
                        <span>Created {{ case.created_at }}</span>
                    </div>
                    <div class="law-record-source">Source: {{ case.source_import }}</div>
                </div>
                <div class="law-record-actions">
                    <button type="button" class="law-open-action" onclick="location.href='/law/cases/{{ case.id }}'">Open</button>
                    <form method="POST" action="/law/cases/{{ case.id }}/delete"
                          onsubmit="return confirm('Delete this Law Case Review? This will remove the saved case review JSON file, but it will not delete the original raw import.');">
                        <button type="submit" class="law-trash-action" aria-label="Delete case review" title="Delete case review">🗑</button>
                    </form>
                </div>
            </article>
            {% endfor %}
        </div>
        {% else %}
        <div class="law-empty-state">
            <h3>No case reviews yet</h3>
            <p>Create a case review from a saved import to see it here.</p>
        </div>
        {% endif %}

        <div class="law-action-row law-footer-actions">
            <button type="button" class="law-primary-action" onclick="location.href='/law/imports'">Saved Imports</button>
            <button type="button" class="law-secondary-action" onclick="location.href='/law/import'">Import Case Packet</button>
            <button type="button" class="law-quiet-action" onclick="location.href='/law'">Back to Law Study</button>
        </div>
    </section>
</main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");

if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));

    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}

const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("Shut down DLMS? You will need to restart it manually.")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) {
            alert("Failed to shut down DLMS.");
        }
    });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>""",
    portal_title=portal_title,
    cases=cases
    )



# =========================
# LAW STUDY MODULE - VIEW CASE REVIEW
# =========================
@app.route("/law/cases/<case_id>")
def law_view_case_review(case_id):
    portal_title = get_portal_title()
    law_registry = load_law_registry()
    law_folders = law_registry.get("folders", [])

    case_entry = get_law_case_by_id(case_id)

    if not case_entry:
        return "Law case review not found", 404

    case_file = secure_filename(case_entry.get("file") or "")

    if not case_file.lower().endswith(".json"):
        return "Invalid case file", 400

    case_path = os.path.join(LAW_CASES_FOLDER, case_file)

    if not os.path.exists(case_path) or not os.path.isfile(case_path):
        return "Law case file not found", 404

    try:
        case_data = _load_law_case_data(case_path)
    except Exception as e:
        print(f"[LAW CASE ERROR] Failed reading case review: {e}")
        return "Failed to read case review", 500

    sections = case_data.get("sections", {}) or {}
    sources_used = case_data.get("sources_used", "")

    section_cards = [
        {
            "key": "case_brief",
            "title": "Case Brief",
            "icon": "📄",
            "content": sections.get("case_brief", "")
        }
    ]

    irac_drill_content = sections.get("irac_drill", "")
    rule_flashcards_content = sections.get("rule_flashcards", "")
    socratic_answer_key = sections.get("socratic_answer_key", "")
    socratic_questions = parse_socratic_questions(sections.get("socratic_review", ""))
    socratic_student_answers = case_data.get("socratic_student_answers", {}) or {}
    irac_student_response = case_data.get("irac_student_response", {}) or {}
    socratic_total = len(socratic_questions)

    socratic_answered = 0
    for question in socratic_questions:
        qid = question.get("id")
        answer = str(socratic_student_answers.get(qid, "")).strip()
        if answer:
            socratic_answered += 1

    socratic_progress_text = f"{socratic_answered} of {socratic_total} answered"

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{{ case_data.title }} - DLMS Law Study</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">

</head>

<body class="dashboard-home law-subpage law-case-detail-page">
<div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar">
    <div class="dashboard-brand">
        <div class="dashboard-brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="img">
                <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div>
    </div>
    <nav class="dashboard-nav" aria-label="Primary navigation">
        <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
        <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
        <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
        <a class="dashboard-nav-item active" href="/law" aria-current="page"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
        {% if medical_pack_installed %}
        <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
        {% endif %}
        <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
        <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
    </nav>
    <div class="dashboard-nav-section-label"><span>System</span></div>
    <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
        <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
        <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
        <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
        <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
    </nav>
    <button class="dashboard-shutdown" id="shutdownBtn" type="button"><span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span></button>
    <div class="dashboard-sidebar-version">Law Study</div>
</aside>
<main class="dashboard-main law-subpage-main law-study-view">
    <header class="dashboard-header law-subpage-header">
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
        <div><div class="law-subpage-eyebrow">LAW STUDY · CASE REVIEW</div><h1>{{ case_data.title }}</h1><p>{{ case_data.course or "Uncategorized" }} · Structured case review</p></div>
    </header>

    <section class="dashboard-panel law-detail-panel law-case-detail-shell">

        <div style="
            display:flex;
            justify-content:space-between;
            align-items:flex-start;
            gap:16px;
            flex-wrap:wrap;
            margin-bottom:20px;
        ">
            <div>
                <h2 style="margin-bottom:6px;">{{ case_data.title }}</h2>

                <p style="opacity:.85; margin-top:0;">
                    <strong>Course:</strong> {{ case_data.course or "Uncategorized" }}<br>
                    <strong>Created:</strong> {{ case_data.created_at }}<br>
                    <strong>Source Import:</strong> {{ case_data.source_import }}
                </p>

        {% if sources_used %}
        <div style="
            margin-top:12px;
            padding:12px;
            border-radius:12px;
            background:rgba(0,120,255,.08);
            border:1px solid rgba(0,120,255,.25);
        ">
            <strong>Sources Used:</strong>

            <pre style="
                white-space:pre-wrap;
                word-wrap:break-word;
                font-family:inherit;
                line-height:1.45;
                margin:8px 0 0 0;
            ">{{ sources_used }}</pre>
        </div>
        {% endif %}
                                                                             
            </div>

            <span style="
                display:inline-block;
                padding:7px 12px;
                border-radius:999px;
                background:rgba(0,120,255,.12);
                border:1px solid rgba(0,120,255,.35);
                font-size:13px;
                font-weight:700;
                white-space:nowrap;
            ">
                Structured case review
            </span>
        </div>

        {% if request.args.get('updated') %}
        <div style="
            margin-bottom:18px;
            padding:14px;
            border-radius:12px;
            background:rgba(0,180,100,.12);
            border:1px solid rgba(0,180,100,.35);
        ">
            <strong>Case details updated.</strong>
            The title and course were saved successfully.
        </div>
        {% endif %}

        {% if request.args.get('notes_updated') %}
        <div style="
            margin-bottom:18px;
            padding:14px;
            border-radius:12px;
            background:rgba(0,180,100,.12);
            border:1px solid rgba(0,180,100,.35);
        ">
            <strong>Student notes updated.</strong>
            Your notes were saved successfully.
        </div>
        {% endif %}   

          {% if request.args.get('socratic_answers_updated') %}
        <div style="
            margin-bottom:18px;
            padding:14px;
            border-radius:12px;
            background:rgba(0,180,100,.12);
            border:1px solid rgba(0,180,100,.35);
        ">
            <strong>Socratic answers updated.</strong>
            Your practice answers were saved successfully.
        </div>
        {% endif %}                     

        {% if request.args.get('irac_updated') %}
        <div style="
            margin-bottom:18px;
            padding:14px;
            border-radius:12px;
            background:rgba(0,180,100,.12);
            border:1px solid rgba(0,180,100,.35);
        ">
            <strong>IRAC response updated.</strong>
            Your practice response was saved successfully.
        </div>
        {% endif %}                       


        <div style="
            margin-bottom:18px;
            padding:14px;
            border-radius:12px;
            background:rgba(255,180,0,.10);
            border:1px solid rgba(255,180,0,.35);
        ">
            <strong>Reminder:</strong>
            Verify citations, holdings, quotations, and procedural history against the original opinion or an approved legal research source.
        </div>

        <div class="portal-card law-case-section">
    <h2 style="margin-top:0;">✏️ Edit Case Details</h2>

    <form method="POST" action="/law/cases/{{ case_data.id }}/update_details">
        <label><strong>Case Title</strong></label><br>
        <input type="text"
               name="title"
               value="{{ case_data.title }}"
               style="width:100%; padding:10px; border-radius:8px; box-sizing:border-box;">

        <br><br>

        <label><strong>Course</strong></label><br>
        <select name="course"
                style="width:100%; padding:10px; border-radius:8px; box-sizing:border-box;">
            <option value="Uncategorized" {% if case_data.course == "Uncategorized" %}selected{% endif %}>
                Uncategorized
            </option>

            {% for folder in law_folders %}
            <option value="{{ folder }}" {% if case_data.course == folder %}selected{% endif %}>
                {{ folder }}
            </option>
            {% endfor %}
        </select>

        <br><br>

        <button type="submit">
            💾 Save Case Details
        </button>
    </form>
</div>
                                  
        {% for section in section_cards %}
            {% if section.content %}
            <div class="portal-card law-case-section">
                <h2 style="margin-top:0;">{{ section.icon }} {{ section.title }}</h2>

                <pre style="
                    white-space:pre-wrap;
                    word-wrap:break-word;
                    font-family:inherit;
                    line-height:1.45;
                    margin-bottom:0;
                ">{{ section.content }}</pre>
            </div>
            {% endif %}
        {% endfor %}

  {% if case_data.sections.irac_drill %}
    <div class="portal-card law-case-section">
        <h2 style="margin-top:0;">🧠 IRAC Practice Response</h2>

        <p style="opacity:.8;">
            Write your own IRAC response before revealing the imported IRAC Drill guidance.
        </p>

        <form method="POST" action="/law/cases/{{ case_data.id }}/update_irac_response">
            <label><strong>Issue</strong></label><br>
            <textarea class="law-detail-textarea" name="irac_issue"
                    rows="4"
                    placeholder="State the legal issue..."
                    style="width:100%; padding:12px; border-radius:10px; box-sizing:border-box;">{{ irac_student_response.get("issue", "") }}</textarea>

            <br><br>

            <label><strong>Rule</strong></label><br>
            <textarea class="law-detail-textarea" name="irac_rule"
                    rows="4"
                    placeholder="State the governing rule..."
                    style="width:100%; padding:12px; border-radius:10px; box-sizing:border-box;">{{ irac_student_response.get("rule", "") }}</textarea>

            <br><br>

            <label><strong>Analysis / Application</strong></label><br>
            <textarea class="law-detail-textarea" name="irac_analysis"
                    rows="7"
                    placeholder="Apply the rule to the facts..."
                    style="width:100%; padding:12px; border-radius:10px; box-sizing:border-box;">{{ irac_student_response.get("analysis", "") }}</textarea>

            <br><br>

            <label><strong>Conclusion</strong></label><br>
            <textarea class="law-detail-textarea" name="irac_conclusion"
                    rows="4"
                    placeholder="State the likely result..."
                    style="width:100%; padding:12px; border-radius:10px; box-sizing:border-box;">{{ irac_student_response.get("conclusion", "") }}</textarea>

            <br><br>

            <button type="submit">
                💾 Save IRAC Response
            </button>
        </form>
    </div>

    <div class="portal-card law-case-section">
        <h2 style="margin-top:0;">🔒 IRAC Drill</h2>

        <p style="opacity:.8;">
            Hidden by default for active recall. Try writing your own IRAC response first, then reveal the imported drill guidance.
        </p>

        <button type="button" onclick="toggleIracDrill()">
            👁 Reveal / Hide IRAC Drill
        </button>

        <div id="iracDrillBox" style="display:none; margin-top:14px;">
            <pre style="
                white-space:pre-wrap;
                word-wrap:break-word;
                font-family:inherit;
                line-height:1.45;
                margin-bottom:0;
            ">{{ case_data.sections.irac_drill }}</pre>
        </div>
    </div>
    {% endif %}                                

                                 

                                  
{% if socratic_questions %}
<div class="portal-card law-case-section">
    <div style="
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:12px;
        flex-wrap:wrap;
    ">
        <div>
            <h2 style="margin-top:0;">🎓 Socratic Practice</h2>

            <p style="opacity:.8;">
                Type your own answer before revealing the answer key. Your answers are saved with this case review.
            </p>
        </div>

        <span style="
            display:inline-block;
            padding:7px 12px;
            border-radius:999px;
            background:rgba(0,120,255,.12);
            border:1px solid rgba(0,120,255,.35);
            font-size:13px;
            font-weight:700;
            white-space:nowrap;
        ">
            {{ socratic_progress_text }}
        </span>
    </div>

    <form id="socraticAnswersForm"
      method="POST"
      action="/law/cases/{{ case_data.id }}/update_socratic_answers">
        <div style="display:grid; gap:12px;">
            {% for question in socratic_questions %}
            <div style="
                padding:14px;
                border-radius:12px;
                background:rgba(255,255,255,.06);
                border:1px solid rgba(255,255,255,.16);
            ">
                <h3 style="margin-top:0;">Question {{ question.number }}</h3>

                <pre style="
                    white-space:pre-wrap;
                    word-wrap:break-word;
                    font-family:inherit;
                    line-height:1.45;
                    margin-bottom:12px;
                ">{{ question.text }}</pre>

                <label><strong>Your Answer</strong></label><br>
                <textarea class="law-detail-textarea" name="answer_{{ question.id }}"
                          rows="5"
                          placeholder="Type your answer before revealing the guidance..."
                          style="width:100%; padding:12px; border-radius:10px; box-sizing:border-box;">{{ socratic_student_answers.get(question.id, "") }}</textarea>
            </div>
            {% endfor %}
        </div>

        <br>

        <button type="submit" form="socraticAnswersForm">
            💾 Save Socratic Answers
        </button>
    </form>
</div>
{% endif %}

    
                                                                    
        {% if socratic_answer_key %}
        <div class="portal-card law-case-section">
            <h2 style="margin-top:0;">🔒 Socratic Answer Key</h2>

            <p style="opacity:.8;">
                Hidden by default for active recall. Try answering the Socratic questions first, then reveal the guidance.
            </p>

            <button type="button" onclick="toggleSocraticAnswerKey()">
                👁 Reveal / Hide Answer Key
            </button>

            <div id="socraticAnswerKey" style="display:none; margin-top:14px;">
                <pre style="
                    white-space:pre-wrap;
                    word-wrap:break-word;
                    font-family:inherit;
                    line-height:1.45;
                    margin-bottom:0;
                ">{{ socratic_answer_key }}</pre>
            </div>
        </div>
        {% endif %}

        {% if rule_flashcards_content %}
        <div class="portal-card law-case-section">
            <h2 style="margin-top:0;">🃏 Rule Flashcards</h2>

            <pre style="
                white-space:pre-wrap;
                word-wrap:break-word;
                font-family:inherit;
                line-height:1.45;
                margin-bottom:0;
            ">{{ rule_flashcards_content }}</pre>
        </div>
        {% endif %}
                                  
        <div class="portal-card law-case-section">
            <h2 style="margin-top:0;">📝 Student Notes</h2>

            <p style="opacity:.8;">
                Add your own class notes, professor comments, questions, or reminders here.
            </p>

            <form method="POST" action="/law/cases/{{ case_data.id }}/update_notes">
                <textarea class="law-detail-textarea" name="student_notes"
                        rows="10"
                        placeholder="Add your own notes about this case..."
                        style="width:100%; padding:12px; border-radius:10px; box-sizing:border-box;">{{ case_data.student_notes }}</textarea>

                <br><br>

                <button type="submit">
                    💾 Save Student Notes
                </button>
            </form>
        </div>

        <br>

        <button type="button" onclick="location.href='/law/cases/{{ case_data.id }}/export.txt'">
            ⬇️ Export Case Review
        </button>

        <button type="button" onclick="location.href='/law/cases'">
            ⬅ Back To My Case Reviews
        </button>

        <button type="button" onclick="location.href='/law/imports'">
            📁 Saved Imports
        </button>

        <button type="button" onclick="location.href='/law'">
            ⚖️ Law Study Hub
        </button>

    </section>
</main>
</div>

<script>
function toggleIracDrill() {
    const box = document.getElementById("iracDrillBox");

    if (!box) {
        return;
    }

    if (box.style.display === "none" || box.style.display === "") {
        box.style.display = "block";
    } else {
        box.style.display = "none";
    }
}

function toggleSocraticAnswerKey() {
    const box = document.getElementById("socraticAnswerKey");

    if (!box) {
        return;
    }

    if (box.style.display === "none" || box.style.display === "") {
        box.style.display = "block";
    } else {
        box.style.display = "none";
    }
}

const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");
if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}
const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("Shut down DLMS? You will need to restart it manually.")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) { alert("Failed to shut down DLMS."); }
    });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>
""",
    portal_title=portal_title,
    case_entry=case_entry,
    case_data=case_data,
    rule_flashcards_content=rule_flashcards_content,
    section_cards=section_cards,
    socratic_answer_key=socratic_answer_key,
    socratic_questions=socratic_questions,
    socratic_student_answers=socratic_student_answers,
    socratic_total=socratic_total,
    socratic_answered=socratic_answered,
    socratic_progress_text=socratic_progress_text,
    sources_used=sources_used,
    irac_student_response=irac_student_response,
    irac_drill_content=irac_drill_content,
    law_folders=law_folders
    )



# =========================
# LAW STUDY MODULE - UPDATE CASE REVIEW DETAILS
# =========================
@app.route("/law/cases/<case_id>/update_details", methods=["POST"])
def law_update_case_review_details(case_id):
    case_entry = get_law_case_by_id(case_id)

    if not case_entry:
        return "Law case review not found", 404

    case_file = secure_filename(case_entry.get("file") or "")

    if not case_file.lower().endswith(".json"):
        return "Invalid case file", 400

    case_path = os.path.join(LAW_CASES_FOLDER, case_file)

    if not os.path.exists(case_path) or not os.path.isfile(case_path):
        return "Law case file not found", 404

    new_title = request.form.get("title", "").strip()
    new_course = request.form.get("course", "").strip()

    try:
        _law_service.update_law_case_details(
            case_path,
            case_id,
            case_entry,
            new_title,
            new_course,
            now=datetime.now,
            load_law_registry=load_law_registry,
            registry_case_for_mutation=_law_registry_case_for_mutation,
            commit_law_case_and_registry=_commit_law_case_and_registry,
            load_case_data=_load_law_case_data,
        )

    except Exception as e:
        print(f"[LAW CASE ERROR] Failed updating case review details: {e}")
        return "Failed to update case review details", 500

    return redirect(f"/law/cases/{case_id}?updated=1")


# =========================
# LAW STUDY MODULE - DELETE CASE REVIEW
# =========================
@app.route("/law/cases/<case_id>/delete", methods=["POST"])
def law_delete_case_review(case_id):
    case_entry = get_law_case_by_id(case_id)

    if not case_entry:
        return "Law case review not found", 404

    case_file = secure_filename(case_entry.get("file") or "")

    if not case_file.lower().endswith(".json"):
        return "Invalid case file", 400

    case_path = os.path.join(LAW_CASES_FOLDER, case_file)

    try:
        registry = load_law_registry()
        _delete_law_case_and_registry(case_path, registry, case_id)

    except Exception as e:
        print(f"[LAW CASE ERROR] Failed deleting case review: {e}")
        return "Failed to delete case review", 500

    return redirect("/law/cases?deleted=1")





@app.route("/data/<path:filename>")
def serve_data(filename):
    extension = os.path.splitext(str(filename or ""))[1].lower()
    if extension not in BROWSER_SERVED_DATA_EXTENSIONS:
        return "Unsupported data file", 415
    return send_from_directory(DATA_FOLDER, filename)


@app.route("/quizzes/<path:filename>")
def serve_quiz(filename):
    if os.path.splitext(str(filename or ""))[1].lower() != ".html":
        return "Unsupported quiz file", 415
    return send_from_directory(QUIZ_FOLDER, filename)


#@app.route("/<path:path>")
#def static_proxy(path):
    #return send_from_directory(".", path)


# =========================
# EDIT QUIZ - FORM
# =========================
@app.route("/edit_quiz/<int:quiz_id>")
def edit_quiz(quiz_id):
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

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Edit Quiz - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home build-modern-page edit-quiz-page">
<div class="dashboard-shell">

    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>

        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item active" href="/library" aria-current="page"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>

        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>

        <button class="dashboard-shutdown" id="shutdownBtn" type="button">
            <span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span>
        </button>
        <div class="dashboard-sidebar-version">DLMS v{{ app_version }}</div>
    </aside>

    <main class="dashboard-main build-modern-main edit-quiz-main">
        <header class="dashboard-header build-page-header edit-quiz-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="build-eyebrow">QUIZ LIBRARY</div>
                <h1>Edit Quiz</h1>
                <p>Update quiz details, questions, answer choices, and Exam Mode settings.</p>
            </div>
        </header>

        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}

        <form id="edit-quiz-form"
              class="build-workspace"
              method="POST"
              action="/edit_quiz/{{ quiz['id'] }}"
              enctype="multipart/form-data">

            <section class="dashboard-panel build-section">
                <div class="build-section-heading">
                    <div class="build-step-number">1</div>
                    <div>
                        <h2>Quiz Basics</h2>
                        <p>Update the quiz title, Exam Mode timer, or logo.</p>
                    </div>
                </div>

                <div class="edit-quiz-meta-row" aria-label="Quiz metadata">
                    <span><strong>Quiz ID</strong> {{ quiz["id"] }}</span>
                    <span class="edit-quiz-source"><strong>Source</strong> {{ quiz["source_file"] }}</span>
                </div>

                <div class="build-two-column-fields edit-quiz-basics-grid">
                    <label class="build-field">
                        <span>Quiz Display Title</span>
                        <input type="text"
                               name="quiz_title"
                               value="{{ quiz['title'] }}"
                               required>
                    </label>

                    <label class="build-field">
                        <span>Quiz Logo <em>Optional</em></span>
                        <input type="file" name="quiz_logo" accept="image/*">
                        <small>Uploading a new logo replaces the current quiz logo.</small>
                    </label>

                    <label class="build-field">
                        <span>Exam Mode Timer <em>Minutes</em></span>
                        <input type="number"
                               name="exam_minutes"
                               min="1"
                               max="1440"
                               value="{{ exam_minutes }}"
                               inputmode="numeric">
                        <small>Existing quizzes default to 90 minutes. Change this value to customize Exam Mode.</small>
                    </label>
                </div>
            </section>

            <section class="build-question-section">
                <div class="build-section-heading build-question-section-heading">
                    <div class="build-step-number">2</div>
                    <div>
                        <h2>Questions &amp; Answers</h2>
                        <p>Edit question text and answer choices. Every question must retain at least one correct answer.</p>
                    </div>
                </div>

                <div class="build-question-list">
                    {% for q in questions %}
                    <article class="build-question-card question-block">
                        <div class="build-question-heading-row">
                            <h3>Question {{ q.number }}</h3>
                            <button type="submit"
                                    form="delete-question-{{ q.id }}"
                                    class="build-icon-danger btn-delete"
                                    onclick="return confirm('Delete this question permanently?');"
                                    title="Delete question"
                                    aria-label="Delete question">×</button>
                        </div>

                        <label class="build-field">
                            <span>Question Text</span>
                            <textarea class="question-text"
                                      name="question_{{ q.id }}">{{ q.text }}</textarea>
                        </label>

                        <label class="build-field edit-quiz-concepts-field">
                            <span>Concepts / Tags <em>Optional</em></span>
                            <input type="text" name="concepts_{{ q.id }}" value="{{ q.concepts | join(', ') }}" placeholder="Example: IAM, authentication, least privilege">
                            <small>Separate concepts with commas. DLMS uses these labels as the foundation for topic-level learning analytics and targeted review.</small>
                        </label>

                        {% if q.type == "matching" %}
                        <div class="build-choice-heading">
                            <span>Matching Pairs</span>
                            <small>Edit either side of each pair. The right-side answers are shuffled during play.</small>
                        </div>
                        <div class="build-two-column-fields matching-settings-grid">
                            <label class="build-field">
                                <span>Pairs Per Round</span>
                                <input type="number" name="matching_round_size_{{ q.id }}" min="2" max="100" value="{{ q.round_size or '' }}" placeholder="All pairs">
                                <small>Leave blank to show every pair.</small>
                            </label>
                            <label class="build-field">
                                <span>Direction</span>
                                <select name="matching_direction_{{ q.id }}">
                                    <option value="term_to_definition" {% if q.direction == 'term_to_definition' %}selected{% endif %}>Term → Definition</option>
                                    <option value="definition_to_term" {% if q.direction == 'definition_to_term' %}selected{% endif %}>Definition → Term</option>
                                    <option value="random" {% if q.direction == 'random' %}selected{% endif %}>Random Each Attempt</option>
                                </select>
                            </label>
                        </div>
                        {% if q.source.organization or q.source.dataset %}
                        <div class="build-tip-card matching-source-card">
                            <strong>Content source</strong>
                            <span>{{ q.source.organization or '' }}{% if q.source.dataset %} — {{ q.source.dataset }}{% endif %}{% if q.source.version %} ({{ q.source.version }}){% endif %}</span>
                            {% if q.source.license %}<small>License/terms: {{ q.source.license }}</small>{% endif %}
                        </div>
                        {% endif %}
                        <div class="matching-pairs-list">
                        {% for pair in q.pairs %}
                            <div class="build-match-pair">
                                <span class="match-number">{{ loop.index }}</span>
                                <input type="text" name="match_left_{{ pair['id'] }}" value="{{ pair['left_text'] }}">
                                <span class="match-arrow">↔</span>
                                <input type="text" name="match_right_{{ pair['id'] }}" value="{{ pair['right_text'] }}">
                                <button type="submit" form="delete-match-pair-{{ pair.id }}" class="build-choice-delete btn-delete" onclick="return confirm('Delete this matching pair?');" title="Delete pair" aria-label="Delete pair">×</button>
                            </div>
                        {% endfor %}
                        </div>
                        <button class="build-add-choice" type="submit" name="action" value="add_match_pair_{{ q.id }}">＋ Add Pair</button>
                        <label class="build-field edit-quiz-explanation-field">
                            <span>Study Mode Explanation <em>Optional</em></span>
                            <textarea name="explanation_{{ q.id }}" rows="4" placeholder="Add or edit the explanation shown in Study Mode.">{{ q.explanation }}</textarea>
                            <small>Preserves imported Smart PDF explanations and allows you to add or correct the teaching explanation manually.</small>
                        </label>
                        {% else %}
                        <div class="build-choice-heading">
                            <span>Answer Choices</span>
                            <small>Select Correct for every valid answer.</small>
                        </div>

                        <ul class="build-choice-list edit-quiz-choice-list">
                        {% for c in q.choices %}
                            <li>
                                <b class="choice-label">{{ c["label"] }}.</b>

                                <input type="text"
                                       name="choice_{{ c['id'] }}"
                                       value="{{ c['text'] }}">

                                <label class="build-correct-toggle">
                                    <input type="checkbox"
                                           name="correct_{{ c['id'] }}"
                                           {% if c["is_correct"] %}checked{% endif %}>
                                    <span>Correct</span>
                                </label>

                                <button type="submit"
                                        form="delete-choice-{{ c.id }}"
                                        class="build-choice-delete btn-delete"
                                        onclick="return confirm('Delete this answer choice?');"
                                        title="Delete choice"
                                        aria-label="Delete choice">×</button>
                            </li>
                        {% endfor %}
                        </ul>

                        <div class="edit-quiz-add-choice-row">
                            <label class="build-field edit-quiz-choice-count">
                                <span>Add answer choices</span>
                                <input type="number"
                                       name="choice_count"
                                       value="1"
                                       min="1"
                                       max="10"
                                       inputmode="numeric">
                            </label>

                            <button class="build-add-choice"
                                    type="submit"
                                    name="action"
                                    value="add_choices_{{ q.id }}">＋ Add Choices</button>
                        </div>
                        <label class="build-field edit-quiz-explanation-field">
                            <span>Study Mode Explanation <em>Optional</em></span>
                            <textarea name="explanation_{{ q.id }}" rows="4" placeholder="Add or edit the explanation shown in Study Mode.">{{ q.explanation }}</textarea>
                            <small>Preserves imported Smart PDF explanations and allows you to add or correct the teaching explanation manually.</small>
                        </label>
                        {% endif %}
                    </article>
                    {% endfor %}
                </div>

                <button class="build-add-question"
                        type="submit"
                        name="action"
                        value="add_question">＋ Add New Question</button>
            </section>

            <section class="dashboard-panel build-finalize-bar edit-quiz-finalize">
                <div>
                    <strong>Ready to save?</strong>
                    <span>DLMS will validate the quiz and rebuild its generated quiz page.</span>
                </div>
                <div class="build-submit-row">
                    <a class="build-secondary-link" href="/library">Back to Quiz Library</a>
                    <button class="build-primary-button" type="submit">Save Changes</button>
                </div>
            </section>
        </form>

        <!-- Kept outside the main form so destructive actions remain isolated. -->
        {% for q in questions %}
        <form id="delete-question-{{ q.id }}"
              method="POST"
              action="/delete_question/{{ quiz['id'] }}/{{ q.id }}"></form>

            {% for c in q.choices %}
            <form id="delete-choice-{{ c.id }}"
                  method="POST"
                  action="/delete_choice/{{ quiz['id'] }}/{{ c.id }}"></form>
            {% endfor %}
            {% for pair in q.pairs %}
            <form id="delete-match-pair-{{ pair.id }}"
                  method="POST"
                  action="/delete_match_pair/{{ quiz['id'] }}/{{ pair.id }}"></form>
            {% endfor %}
        {% endfor %}
    </main>
</div>

<script>
document.getElementById("edit-quiz-form").addEventListener("submit", function(e) {
    const questions = document.querySelectorAll(".question-block");

    for (let i = 0; i < questions.length; i++) {
        const checkboxes = questions[i].querySelectorAll('input[type="checkbox"]');
        if (checkboxes.length === 0) continue;
        const checked = questions[i].querySelectorAll('input[type="checkbox"]:checked');

        if (checked.length === 0) {
            e.preventDefault();
            alert(`Question ${i + 1} must have at least one correct answer.`);
            questions[i].scrollIntoView({ behavior: "smooth", block: "center" });
            return;
        }
    }
});

const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");

if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));

    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}

const shutdownBtn = document.getElementById("shutdownBtn");

if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("SHUTDOWN DLMS\\n\\nThis will stop the application.\\n\\nYou will need to restart it manually.\\n\\nContinue?")) return;

        try {
            await fetch("/api/shutdown", { method: "POST" });
            document.body.innerHTML = '<div class="shutdown-screen"><div class="shutdown-screen-card"><h1>DLMS has been shut down.</h1><p>You can close this browser tab.</p></div></div>';
        } catch (err) {
            alert("DLMS may already be shutting down.");
        }
    });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>
""", quiz=quiz, questions=question_list, exam_minutes=exam_minutes, app_version=APP_VERSION)


# =========================
# LAW STUDY MODULE - UPDATE CASE REVIEW NOTES
# =========================
@app.route("/law/cases/<case_id>/update_notes", methods=["POST"])
def law_update_case_review_notes(case_id):
    case_entry = get_law_case_by_id(case_id)

    if not case_entry:
        return "Law case review not found", 404

    case_file = secure_filename(case_entry.get("file") or "")

    if not case_file.lower().endswith(".json"):
        return "Invalid case file", 400

    case_path = os.path.join(LAW_CASES_FOLDER, case_file)

    if not os.path.exists(case_path) or not os.path.isfile(case_path):
        return "Law case file not found", 404

    student_notes = request.form.get("student_notes", "").strip()

    try:
        _law_service.update_law_case_notes(
            case_path,
            case_id,
            student_notes,
            now=datetime.now,
            load_law_registry=load_law_registry,
            registry_case_for_mutation=_law_registry_case_for_mutation,
            commit_law_case_and_registry=_commit_law_case_and_registry,
            load_case_data=_load_law_case_data,
        )

    except Exception as e:
        print(f"[LAW CASE ERROR] Failed updating case review notes: {e}")
        return "Failed to update case review notes", 500

    return redirect(f"/law/cases/{case_id}?notes_updated=1")


# =========================
# LAW STUDY MODULE - UPDATE SOCRATIC ANSWERS
# =========================
@app.route("/law/cases/<case_id>/update_socratic_answers", methods=["POST"])
def law_update_socratic_answers(case_id):
    case_entry = get_law_case_by_id(case_id)

    if not case_entry:
        return "Law case review not found", 404

    case_file = secure_filename(case_entry.get("file") or "")

    if not case_file.lower().endswith(".json"):
        return "Invalid case file", 400

    case_path = os.path.join(LAW_CASES_FOLDER, case_file)

    if not os.path.exists(case_path) or not os.path.isfile(case_path):
        return "Law case file not found", 404

    try:
        _law_service.update_law_case_socratic_answers(
            case_path,
            case_id,
            request.form.to_dict(flat=True),
            now=datetime.now,
            parse_socratic_questions=parse_socratic_questions,
            load_law_registry=load_law_registry,
            registry_case_for_mutation=_law_registry_case_for_mutation,
            commit_law_case_and_registry=_commit_law_case_and_registry,
            load_case_data=_load_law_case_data,
        )

    except Exception as e:
        print(f"[LAW CASE ERROR] Failed updating Socratic answers: {e}")
        return "Failed to update Socratic answers", 500

    return redirect(f"/law/cases/{case_id}?socratic_answers_updated=1")


# =========================
# LAW STUDY MODULE - UPDATE IRAC RESPONSE
# =========================
@app.route("/law/cases/<case_id>/update_irac_response", methods=["POST"])
def law_update_irac_response(case_id):
    case_entry = get_law_case_by_id(case_id)

    if not case_entry:
        return "Law case review not found", 404

    case_file = secure_filename(case_entry.get("file") or "")

    if not case_file.lower().endswith(".json"):
        return "Invalid case file", 400

    case_path = os.path.join(LAW_CASES_FOLDER, case_file)

    if not os.path.exists(case_path) or not os.path.isfile(case_path):
        return "Law case file not found", 404

    irac_response = {
        "issue": request.form.get("irac_issue", "").strip(),
        "rule": request.form.get("irac_rule", "").strip(),
        "analysis": request.form.get("irac_analysis", "").strip(),
        "conclusion": request.form.get("irac_conclusion", "").strip()
    }

    try:
        _law_service.update_law_case_irac_response(
            case_path,
            case_id,
            irac_response,
            now=datetime.now,
            load_law_registry=load_law_registry,
            registry_case_for_mutation=_law_registry_case_for_mutation,
            commit_law_case_and_registry=_commit_law_case_and_registry,
            load_case_data=_load_law_case_data,
        )

    except Exception as e:
        print(f"[LAW CASE ERROR] Failed updating IRAC response: {e}")
        return "Failed to update IRAC response", 500

    return redirect(f"/law/cases/{case_id}?irac_updated=1")



# =========================
# LAW STUDY MODULE - EXPORT CASE REVIEW
# =========================
@app.route("/law/cases/<case_id>/export.txt")
def law_export_case_review_txt(case_id):
    case_entry = get_law_case_by_id(case_id)

    if not case_entry:
        return "Law case review not found", 404

    case_file = secure_filename(case_entry.get("file") or "")

    if not case_file.lower().endswith(".json"):
        return "Invalid case file", 400

    case_path = os.path.join(LAW_CASES_FOLDER, case_file)

    if not os.path.exists(case_path) or not os.path.isfile(case_path):
        return "Law case file not found", 404

    try:
        case_data = _load_law_case_data(case_path)
    except Exception as e:
        print(f"[LAW CASE ERROR] Failed exporting case review: {e}")
        return "Failed to export case review", 500

    export_text, filename = _law_service.build_law_case_export(
        case_data,
        case_id,
        app_version=APP_VERSION,
        exported_on=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    return Response(
        export_text,
        mimetype="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )





def _quiz_json_payload_from_db(cur, quiz_id):
    return _quiz_artifact_renderer._quiz_json_payload_from_db(
        cur,
        quiz_id,
        question_concepts=_question_concepts,
        json_module=json,
    )


def _quiz_registry_entry(registry, quiz_id):
    return _quiz_artifact_renderer._quiz_registry_entry(
        registry,
        quiz_id,
    )


def _quiz_artifact_names(quiz_entry):
    return _quiz_artifact_renderer._quiz_artifact_names(
        quiz_entry,
        basename=os.path.basename,
    )


def rebuild_quiz_json_from_db(quiz_id, *, conn=None, quiz_entry=None, output_path=None):
    return _quiz_artifact_renderer.rebuild_quiz_json_from_db(
        quiz_id,
        conn=conn,
        quiz_entry=quiz_entry,
        output_path=output_path,
        get_db=get_db,
        row_factory=sqlite3.Row,
        load_registry=load_registry,
        quiz_registry_entry=_quiz_registry_entry,
        quiz_artifact_names=_quiz_artifact_names,
        quiz_json_payload_from_db=_quiz_json_payload_from_db,
        data_folder=DATA_FOLDER,
        write_staged_quiz_json=_write_staged_quiz_json,
        token_hex=secrets.token_hex,
        makedirs=os.makedirs,
        dirname=os.path.dirname,
        join_path=os.path.join,
        replace_file=os.replace,
        exists=os.path.exists,
        remove_file=os.remove,
        print_message=print,
    )



def rebuild_quiz_html_from_registry(quiz_id, *, quiz_entry=None, output_path=None):
    return _quiz_artifact_renderer.rebuild_quiz_html_from_registry(
        quiz_id,
        quiz_entry=quiz_entry,
        output_path=output_path,
        load_registry=load_registry,
        quiz_registry_entry=_quiz_registry_entry,
        quiz_artifact_names=_quiz_artifact_names,
        quiz_folder=QUIZ_FOLDER,
        build_quiz_html=build_quiz_html,
        get_portal_title=get_portal_title,
        token_hex=secrets.token_hex,
        makedirs=os.makedirs,
        dirname=os.path.dirname,
        join_path=os.path.join,
        isfile=os.path.isfile,
        getsize=os.path.getsize,
        replace_file=os.replace,
        exists=os.path.exists,
        remove_file=os.remove,
        print_message=print,
    )


def _commit_quiz_mutation(conn):
    return _quiz_mutation_service.commit_quiz_mutation(conn)


def _stage_quiz_mutation_artifacts(conn, quiz_id, quiz_entry):
    return _quiz_mutation_service.stage_quiz_mutation_artifacts(
        conn,
        quiz_id,
        quiz_entry,
        staging_root=_quiz_publication_staging_root,
        quiz_artifact_names=_quiz_artifact_names,
        rebuild_quiz_json=rebuild_quiz_json_from_db,
        rebuild_quiz_html=rebuild_quiz_html_from_registry,
        data_folder=DATA_FOLDER,
        quiz_folder=QUIZ_FOLDER,
        makedirs=os.makedirs,
        make_temp_dir=tempfile.mkdtemp,
        join_path=os.path.join,
        remove_tree=shutil.rmtree,
    )


def _promote_quiz_mutation_artifacts(staged):
    return _quiz_mutation_service.promote_quiz_mutation_artifacts(
        staged,
        restore_artifacts=_restore_quiz_mutation_artifacts,
        makedirs=os.makedirs,
        dirname=os.path.dirname,
        join_path=os.path.join,
        basename=os.path.basename,
        isfile=os.path.isfile,
        copy_file=shutil.copy2,
        replace_file=os.replace,
    )


def _restore_quiz_mutation_artifacts(promoted):
    return _quiz_mutation_service.restore_quiz_mutation_artifacts(
        promoted,
        isfile=os.path.isfile,
        replace_file=os.replace,
        lexists=os.path.lexists,
        islink=os.path.islink,
        remove_file=os.remove,
    )


def _remove_new_quiz_logo(filename, original_registry):
    return _quiz_mutation_service.remove_new_quiz_logo(
        filename,
        original_registry,
        logo_folder=LOGO_FOLDER,
        join_path=os.path.join,
        basename=os.path.basename,
        isfile=os.path.isfile,
        islink=os.path.islink,
        remove_file=os.remove,
    )


def _finish_quiz_mutation(
    conn, quiz_id, registry_updates=None, new_logo_filename=None
):
    return _quiz_mutation_service.finish_quiz_mutation(
        conn,
        quiz_id,
        registry_updates=registry_updates,
        new_logo_filename=new_logo_filename,
        registry_lock=registry_lock,
        load_registry=load_registry,
        save_registry=save_registry,
        quiz_registry_entry=_quiz_registry_entry,
        stage_artifacts=_stage_quiz_mutation_artifacts,
        promote_artifacts=_promote_quiz_mutation_artifacts,
        commit_mutation=_commit_quiz_mutation,
        restore_artifacts=_restore_quiz_mutation_artifacts,
        remove_new_logo=_remove_new_quiz_logo,
        remove_tree=shutil.rmtree,
    )


@app.route("/admin/rebuild_all_quiz_html", methods=["POST"])
def rebuild_all_quiz_html():
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





# =========================
# EDIT QUIZ - SAVE CHANGES
# =========================
def _quiz_owns_question(cur, quiz_id, question_id):
    return _quiz_mutation_service.quiz_owns_question(cur, quiz_id, question_id)


def _quiz_owns_choice(cur, quiz_id, choice_id):
    return _quiz_mutation_service.quiz_owns_choice(cur, quiz_id, choice_id)


def _quiz_owns_matching_pair(cur, quiz_id, pair_id):
    return _quiz_mutation_service.quiz_owns_matching_pair(cur, quiz_id, pair_id)


def _quiz_edit_validation(cur, quiz_id):
    return _quiz_mutation_service.quiz_edit_validation(
        cur,
        quiz_id,
        matching_record_validation_errors=_matching_record_validation_errors,
        matching_case_only_term_warnings=_matching_case_only_term_warnings,
    )


def _publish_quiz_edit_request(
    conn, quiz_id, *, title, exam_minutes, logo_file, timestamp
):
    return _quiz_mutation_service.publish_quiz_edit_request(
        conn,
        quiz_id,
        title=title,
        exam_minutes=exam_minutes,
        logo_file=logo_file,
        timestamp=timestamp,
        flask_app=app,
        finalize_logo=finalize_logo_from_request,
        finish_mutation=_finish_quiz_mutation,
        remove_new_logo=_remove_new_quiz_logo,
        load_registry=load_registry,
    )


@app.route("/edit_quiz/<int:quiz_id>", methods=["POST"])
def save_edited_quiz(quiz_id):
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
        return redirect(url_for("edit_quiz", quiz_id=quiz_id))
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




# =========================
# DELETE QUESTION FROM QUIZ
# =========================
@app.route("/delete_question/<int:quiz_id>/<int:question_id>", methods=["POST"])
def delete_question_from_quiz(quiz_id, question_id):
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


# =========================
# ADD CHOICES TO QUESTION
# =========================
@app.route("/add_choices/<int:quiz_id>/<int:question_id>", methods=["POST"])
def add_choices_to_question(quiz_id, question_id):
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



# =========================
# DELETE CHOICE FROM QUESTION
# =========================
@app.route("/delete_choice/<int:quiz_id>/<int:choice_id>", methods=["POST"])
def delete_choice_from_question(quiz_id, choice_id):
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


# =========================
# DELETE MATCHING PAIR FROM QUESTION
# =========================
@app.route("/delete_match_pair/<int:quiz_id>/<int:pair_id>", methods=["POST"])
def delete_match_pair_from_question(quiz_id, pair_id):
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


# =========================
# DELETE QUIZ (AUTHORITATIVE)
# =========================
def _commit_quiz_deletion(conn):
    return _quiz_mutation_service.commit_quiz_deletion(conn)


def _cleanup_deleted_quiz_artifacts(quiz_entry, remaining_registry):
    return _quiz_mutation_service.cleanup_deleted_quiz_artifacts(
        quiz_entry,
        remaining_registry,
        quiz_artifact_names=_quiz_artifact_names,
        quiz_folder=QUIZ_FOLDER,
        data_folder=DATA_FOLDER,
        quiz_asset_folder=QUIZ_ASSET_FOLDER,
        logo_folder=LOGO_FOLDER,
        join_path=os.path.join,
        splitext=os.path.splitext,
        basename=os.path.basename,
        isfile=os.path.isfile,
        isdir=os.path.isdir,
        islink=os.path.islink,
        remove_file=os.remove,
        remove_tree=shutil.rmtree,
        print_message=print,
    )


def _delete_quiz_transaction(quiz_id):
    return _quiz_mutation_service.delete_quiz_transaction(
        quiz_id,
        get_db=get_db,
        registry_lock=registry_lock,
        load_registry=load_registry,
        save_registry=save_registry,
        commit_deletion=_commit_quiz_deletion,
        print_message=print,
    )


@app.route("/delete_quiz/<int:quiz_id>", methods=["POST"])
def delete_quiz(quiz_id):
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

# =========================
# RESET / RECOVERY OPERATIONS
# =========================
def _clear_directory_contents(path):
    return _restore_service.clear_directory_contents(path)


def _reset_quiz_library_core():
    return _restore_service.reset_quiz_library_core(
        db_path=DB_PATH,
        save_registry=save_registry,
        folders=[QUIZ_FOLDER, DATA_FOLDER, QUIZ_ASSET_FOLDER, LOGO_FOLDER],
        clear_directory=_clear_directory_contents,
        ensure_runtime_dirs=_ensure_runtime_data_dirs,
        sqlite_module=sqlite3,
    )


def _reset_learning_intelligence_core():
    return _restore_service.reset_learning_intelligence_core(
        DB_PATH,
        sqlite_module=sqlite3,
    )

def _remove_unprotected_content_packs():
    return _content_pack_mutation_service.remove_unprotected_content_packs(
        content_pack_folder=CONTENT_PACK_FOLDER,
        get_content_pack=get_content_pack,
        snapshot_existing_pack_dependencies=_snapshot_existing_pack_dependencies,
        remove_tree=shutil.rmtree,
    )


def _reset_source_content_core():
    return _restore_service.reset_source_content_core(
        remove_unprotected_packs=_remove_unprotected_content_packs,
        folders=[
            PDF_QUESTION_BANK_FOLDER,
            PDF_TERMINOLOGY_BANK_FOLDER,
            PDF_IMPORT_DRAFT_FOLDER,
            IMAGE_BUILDER_DRAFT_FOLDER,
            CONTENT_PACK_STAGING_FOLDER,
            UPLOAD_FOLDER,
        ],
        clear_directory=_clear_directory_contents,
        ensure_runtime_dirs=_ensure_runtime_data_dirs,
    )


def _reset_app_settings_core():
    return _restore_service.reset_app_settings_core(
        portal_config=PORTAL_CONFIG,
        background_folder=BACKGROUND_FOLDER,
        clear_directory=_clear_directory_contents,
        load_portal_config=load_portal_config,
    )


def _full_data_reset_core():
    return _restore_service.full_data_reset_core(
        app_data_dir=APP_DATA_DIR,
        data_root_marker=DLMS_DATA_ROOT_MARKER,
        ensure_runtime_dirs=_ensure_runtime_data_dirs,
        ensure_db_initialized=ensure_db_initialized,
        save_registry=save_registry,
        load_portal_config=load_portal_config,
    )


def _run_reset_with_backup(reset_label, reset_callable):
    return _restore_service.run_reset_with_backup(
        reset_label,
        reset_callable,
        require_owned_root=_require_owned_app_data_root,
        create_backup=_create_dlms_backup,
    )

@app.route("/api/reset_quiz_library", methods=["POST"])
def reset_quiz_library():
    try:
        backup_name = _run_reset_with_backup("quiz-library", _reset_quiz_library_core)
        return jsonify(status="ok", backup=backup_name)
    except Exception as exc:
        print("[RESET QUIZ LIBRARY ERROR]", exc)
        message, status = _destructive_operation_error(exc, "Quiz-library reset")
        return jsonify(status="error", error=message), status


@app.route("/api/reset_learning_intelligence", methods=["POST"])
def reset_learning_intelligence():
    try:
        backup_name = _run_reset_with_backup(
            "learning-intelligence", _reset_learning_intelligence_core
        )
        return jsonify(status="ok", backup=backup_name)
    except Exception as exc:
        print("[RESET LEARNING INTELLIGENCE ERROR]", exc)
        message, status = _destructive_operation_error(exc, "Learning Intelligence reset")
        return jsonify(status="error", error=message), status


@app.route("/api/reset_source_content", methods=["POST"])
def reset_source_content():
    try:
        backup_name = _run_reset_with_backup("source-content", _reset_source_content_core)
        return jsonify(status="ok", backup=backup_name)
    except Exception as exc:
        print("[RESET SOURCE CONTENT ERROR]", exc)
        message, status = _destructive_operation_error(exc, "Source-content reset")
        return jsonify(status="error", error=message), status


@app.route("/api/reset_app_settings", methods=["POST"])
def reset_app_settings():
    try:
        backup_name = _run_reset_with_backup("settings", _reset_app_settings_core)
        return jsonify(status="ok", backup=backup_name)
    except Exception as exc:
        print("[RESET SETTINGS ERROR]", exc)
        message, status = _destructive_operation_error(exc, "Settings reset")
        return jsonify(status="error", error=message), status


@app.route("/api/reset_all_data", methods=["POST"])
def reset_all_data():
    try:
        backup_name = _run_reset_with_backup("full-data", _full_data_reset_core)
        return jsonify(status="ok", backup=backup_name)
    except Exception as exc:
        print("[RESET ALL DATA ERROR]", exc)
        message, status = _destructive_operation_error(exc, "Full-data reset")
        return jsonify(status="error", error=message), status


DataRootOwnershipError = _restore_service.DataRootOwnershipError


def _destructive_operation_error(exc, operation):
    if isinstance(exc, DataRootOwnershipError):
        return str(exc), 409
    return f"{operation} failed. Check the local DLMS log for details.", 500


def _validate_destructive_data_root_path(root=None):
    return _restore_service.validate_destructive_data_root_path(
        root or APP_DATA_DIR,
        canonical_data_root=_canonical_data_root,
        data_root_path_is_dangerous=_data_root_path_is_dangerous,
        ownership_error=DataRootOwnershipError,
    )


def _require_owned_app_data_root(operation="perform this destructive operation"):
    return _restore_service.require_owned_app_data_root(
        operation,
        app_data_dir=APP_DATA_DIR,
        validate_target=_validate_destructive_data_root_path,
        read_data_root_marker=_read_data_root_marker,
        ownership_error=DataRootOwnershipError,
    )


def _validate_app_data_removal_target():
    """Retained entry point for permanent removal with positive ownership."""
    return _require_owned_app_data_root("remove all DLMS data")


def _remove_all_dlms_runtime_data_core():
    return _restore_service.remove_all_dlms_runtime_data(
        validate_removal_target=_validate_app_data_removal_target,
    )


def _shutdown_after_data_removal(removed_path, pid):
    print(f"[REMOVE ALL DLMS DATA] Removed runtime data: {removed_path}")
    print("[REMOVE ALL DLMS DATA] Shutting down DLMS; executable/source files were preserved.")
    os.kill(pid, signal.SIGINT)


def _schedule_post_removal_shutdown(removed_path):
    from threading import Timer
    pid = os.getpid()
    return _restore_service.schedule_post_removal_shutdown(
        removed_path,
        shutdown_callback=lambda path: _shutdown_after_data_removal(path, pid),
        timer_factory=Timer,
        delay=0.75,
    )


@app.route("/api/remove_all_dlms_data", methods=["POST"])
def remove_all_dlms_data():
    payload = request.get_json(silent=True) or {}
    confirmation = str(payload.get("confirmation") or "").strip()
    if confirmation != "REMOVE DLMS DATA":
        return jsonify(status="error", error="Type REMOVE DLMS DATA exactly to confirm permanent removal."), 400

    try:
        removed_path = _remove_all_dlms_runtime_data_core()
    except Exception as exc:
        print("[REMOVE ALL DLMS DATA ERROR]", exc)
        message, status = _destructive_operation_error(exc, "Permanent DLMS data removal")
        return jsonify(status="error", error=message), status

    # The executable/source installation is intentionally left untouched.
    _schedule_post_removal_shutdown(removed_path)

    return jsonify(status="ok", removed_path=removed_path, executable_removed=False)


# Backward-compatible endpoint retained for older UI/bookmarks. Its scope remains
# the legacy quiz-library/database reset rather than the new full-data reset.
@app.route("/api/wipe_database", methods=["POST"])
def wipe_database():
    try:
        backup_name = _run_reset_with_backup("legacy-wipe", _reset_quiz_library_core)
        return jsonify(status="ok", backup=backup_name)
    except Exception as exc:
        print("[LEGACY WIPE ERROR]", exc)
        message, status = _destructive_operation_error(exc, "Database wipe")
        return jsonify(status="error", error=message), status


# =========================
# SAVE ORDER (DRAG + DROP)
# =========================

@app.route("/save_order", methods=["POST"])
def save_order():

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


# =========================
# QUIZ DB SAVE HELPER (UPLOAD + PASTE)
# =========================
def _insert_quiz_rows(conn, quiz_title, source_file, quiz_data, logo_filename=None):
    """Insert a complete quiz on the caller's current transaction."""
    cur = conn.cursor()

    # Insert quiz (now stores registry_id too)
    cur.execute(
        """
        INSERT INTO quizzes (title, source_file)
        VALUES (?, ?)
        """,
        (quiz_title, source_file),
    )

    quiz_id = cur.lastrowid  # ✅ CAPTURE DB ID

    # Insert questions + question-specific answer data
    for q in quiz_data:
        question_number = q.get("number")
        question_text = q.get("question") or q.get("text") or ""
        question_type = (q.get("type") or "choice").strip().lower()
        if question_type not in {"choice", "matching"}:
            question_type = "choice"
        media_payload = q.get("media") or {
            key: q.get(key)
            for key in ("image_url", "image_alt", "image_edits", "image_source")
            if q.get(key) is not None
        }
        if q.get("source_number") is not None and isinstance(media_payload, dict):
            media_payload = dict(media_payload)
            media_payload["source_number"] = q["source_number"]

        cur.execute(
            """
            INSERT INTO questions (
                quiz_id,
                question_number,
                question_text,
                question_type,
                matching_round_size,
                matching_direction,
                source_organization,
                source_dataset,
                source_version,
                source_url,
                source_license,
                explanation,
                media_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quiz_id, question_number, question_text, question_type,
                q.get("round_size"), q.get("direction", "term_to_definition"),
                (q.get("source") or {}).get("organization"),
                (q.get("source") or {}).get("dataset"),
                (q.get("source") or {}).get("version"),
                (q.get("source") or {}).get("url"),
                (q.get("source") or {}).get("license"),
                q.get("explanation") or "",
                json.dumps(media_payload, ensure_ascii=False),
            ),
        )

        question_id = cur.lastrowid

        _set_question_concepts(cur, question_id, q.get("concepts") or q.get("tags") or [])

        if question_type == "matching":
            for pair_order, pair in enumerate(q.get("pairs", []), start=1):
                cur.execute(
                    """
                    INSERT INTO matching_pairs (
                        question_id, pair_order, left_text, right_text,
                        category, explanation, verification_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        question_id,
                        pair_order,
                        pair.get("left", ""),
                        pair.get("right", ""),
                        pair.get("category", ""),
                        pair.get("explanation", ""),
                        json.dumps(pair.get("verification") or {}, ensure_ascii=False),
                    ),
                )
        else:
            for c in q.get("choices", []):
                cur.execute(
                    """
                    INSERT INTO choices (question_id, label, text, is_correct)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        question_id,
                        c.get("label"),
                        c.get("text"),
                        1 if c.get("is_correct") else 0,
                    ),
                )

    return quiz_id  # ✅ REQUIRED FOR REGISTRY + DELETE


def save_quiz_to_db(quiz_title, source_file, quiz_data, logo_filename=None):
    """Compatibility wrapper that owns and commits one quiz transaction."""
    conn = get_db()
    try:
        conn.execute("BEGIN")
        quiz_id = _insert_quiz_rows(
            conn, quiz_title, source_file, quiz_data, logo_filename
        )
        conn.commit()
        return quiz_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



# =========================
# EXPORT ALL QUIZZES
# =========================
@app.route("/export/all_quizzes.txt")
def export_all_quizzes_txt():
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


# =========================
# EXPORT SINGLE QUIZ
# =========================
@app.route("/export/quiz/<int:quiz_id>.txt")
def export_single_quiz_txt(quiz_id):
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




# =========================
# LIBRARY (WITH DRAG + DROP!)
# =========================
# =====================================================================
# MODERN QUIZ LIBRARY UI
# Introduced: 2026-08-21 (DLMS 2.3 UI modernization)
#
# Historical note:
# The original embedded Quiz Library implementation was preserved at:
# archive/legacy_library_ui_2026-08-21.txt
#
# This block owns the current Quiz Library presentation and its existing
# folder-management forms and APIs.
# =====================================================================
@app.route("/library")
def quiz_library():
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

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quiz Library - {{ portal_title }}</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
    <script src="/static/vendor/sortablejs-1.15.0.min.js"></script>
</head>
<body class="dashboard-home library-page">
<div class="dashboard-shell">

    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>

        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item active" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>

        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>

        <button class="dashboard-shutdown" id="shutdownBtn" type="button">
            <span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span>
        </button>
        <div class="dashboard-sidebar-version">DLMS v{{ app_version }}</div>
    </aside>

    <main class="dashboard-main library-main">
        <header class="dashboard-header library-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <h1>{{ portal_title }}</h1>
                <p>Quiz Library <span>•</span> Organize <span>•</span> Launch <span>•</span> Manage</p>
            </div>
        </header>

        <section class="library-hero dashboard-panel">
            <div>
                <span class="library-eyebrow">QUIZ LIBRARY</span>
                <h2>Your training content, organized.</h2>
                <p>Launch quizzes, organize folders, manage visibility, and export content from one workspace.</p>
            </div>
            <div class="library-hero-actions">
                <a class="library-primary-action" href="/upload">＋ Build Quiz</a>
            </div>
        </section>

        <section class="library-summary-grid" aria-label="Library summary">
            <div class="library-stat-card"><span>Visible</span><strong>{{ visible_count }}</strong><small>available quizzes</small></div>
            <div class="library-stat-card"><span>Hidden</span><strong>{{ hidden_count }}</strong><small>hidden quizzes</small></div>
            <div class="library-stat-card"><span>Folders</span><strong>{{ normal_display_folder_names|length }}</strong><small>folders in this view</small></div>
            <div class="library-stat-card"><span>This View</span><strong>{{ view_quiz_count }}</strong><small>{{ view|capitalize }} items</small></div>
        </section>

        <section class="library-toolbar dashboard-panel">
            <div class="library-toolbar-left">
                <form method="GET" action="/library" class="library-view-switcher" aria-label="Library view">
                    <span>View</span>
                    <label class="library-view-option {% if view == 'visible' %}selected{% endif %}">
                        <input type="radio" name="view" value="visible" onchange="this.form.submit()" {% if view == 'visible' %}checked{% endif %}>Visible
                    </label>
                    <label class="library-view-option {% if view == 'hidden' %}selected{% endif %}">
                        <input type="radio" name="view" value="hidden" onchange="this.form.submit()" {% if view == 'hidden' %}checked{% endif %}>Hidden
                    </label>
                    <label class="library-view-option {% if view == 'all' %}selected{% endif %}">
                        <input type="radio" name="view" value="all" onchange="this.form.submit()" {% if view == 'all' %}checked{% endif %}>All
                    </label>
                </form>

                <div class="library-search-wrap">
                    <span aria-hidden="true">⌕</span>
                    <input id="librarySearch" type="search" placeholder="Search quizzes..." autocomplete="off" aria-label="Search quizzes">
                </div>
            </div>

            <div class="add-folder-control library-add-folder">
                <button type="button" class="library-secondary-action" onclick="showAddFolderForm(event, this)">
                    <svg class="dlms-folder-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <path d="M3.5 7.25A2.25 2.25 0 0 1 5.75 5h4.1l2 2h6.4a2.25 2.25 0 0 1 2.25 2.25v7A2.25 2.25 0 0 1 18.25 18.5H5.75A2.25 2.25 0 0 1 3.5 16.25z"/>
                    </svg> New Folder
                </button>
                <form method="POST" action="/add_quiz_folder" class="add-folder-form library-inline-form" style="display:none;">
                    <input type="hidden" name="view" value="{{ view }}">
                    <input type="text" name="folder" placeholder="New folder name" required>
                    <button type="submit">Save</button>
                    <button type="button" class="library-quiet-button" onclick="hideAddFolderForm(event, this)">Cancel</button>
                </form>
            </div>
        </section>

        <div class="library-tip">Drag folder headers to reorder folders. Drag quiz cards to reorder quizzes inside a folder. Use the Up and Down buttons for keyboard reordering.</div>
        <div id="libraryReorderStatus" class="library-reorder-status" aria-live="polite" aria-atomic="true"></div>

        {% if display_folder_names %}
        <section id="quizList" class="library-folder-list" data-view="{{ view }}">
            {% for folder_name in display_folder_names %}
            {% set folder_quizzes = grouped_quizzes.get(folder_name, []) %}
            {% set folder_is_hidden = folder_name|lower in hidden_folder_keys %}
            {% set folder_is_search_only = view == 'visible' and folder_is_hidden %}
            <article class="library-folder{% if folder_is_hidden %} library-folder-is-hidden{% endif %}{% if folder_is_search_only %} library-view-search-only{% endif %}" data-folder-name="{{ folder_name }}" data-folder-hidden="{{ 'true' if folder_is_hidden else 'false' }}" data-folder-draggable="true">
                <div class="library-folder-header" onclick="toggleLibraryFolder(event, this)">
                    <div class="library-folder-title-group">
                        <button type="button" class="folder-toggle-icon library-folder-toggle-button" aria-label="Collapse {{ folder_name }}" aria-expanded="true" aria-controls="library-folder-body-{{ loop.index }}" onclick="toggleLibraryFolder(event, this)">▼</button>
                        <svg class="dlms-folder-icon dlms-folder-icon-large" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                            <path d="M3.5 7.25A2.25 2.25 0 0 1 5.75 5h4.1l2 2h6.4a2.25 2.25 0 0 1 2.25 2.25v7A2.25 2.25 0 0 1 18.25 18.5H5.75A2.25 2.25 0 0 1 3.5 16.25z"/>
                        </svg>
                        <div>
                            <h2>{{ folder_name }}{% if folder_is_hidden %} <span class="library-folder-hidden-badge">Hidden folder</span>{% endif %}</h2>
                            <span class="library-folder-subtitle">{{ folder_quizzes|length }} quiz{% if folder_quizzes|length != 1 %}zes{% endif %}</span>
                        </div>
                    </div>

                    <div class="library-folder-actions">
                        {% if normal_display_folder_names|length > 1 and not folder_is_search_only %}
                        <div class="library-reorder-controls" role="group" aria-label="Reorder {{ folder_name }}">
                            <button type="button" class="library-icon-button library-reorder-button" data-library-reorder="folder" data-library-reorder-direction="-1" onclick="moveLibraryFolder(event, this, -1)" aria-label="Move {{ folder_name }} up" title="Move folder up" {% if loop.first %}disabled{% endif %}>↑</button>
                            <button type="button" class="library-icon-button library-reorder-button" data-library-reorder="folder" data-library-reorder-direction="1" onclick="moveLibraryFolder(event, this, 1)" aria-label="Move {{ folder_name }} down" title="Move folder down" {% if loop.last %}disabled{% endif %}>↓</button>
                        </div>
                        {% endif %}
                    {% if folder_name|lower != "uncategorized" %}
                        <form method="POST" action="/set_quiz_folder_hidden" class="library-action-form">
                            <input type="hidden" name="folder" value="{{ folder_name }}">
                            <input type="hidden" name="hidden" value="{{ '0' if folder_is_hidden else '1' }}">
                            <input type="hidden" name="view" value="{{ view }}">
                            <button type="submit" class="library-secondary-action compact library-folder-visibility-action" aria-label="{{ 'Unhide' if folder_is_hidden else 'Hide' }} {{ folder_name }} folder">{% if folder_is_hidden %}👁 Unhide{% else %}◌ Hide{% endif %}</button>
                        </form>
                        <div class="folder-actions">
                            <button type="button" class="library-icon-button" onclick="showRenameFolderForm(event, this)" title="Rename folder" aria-label="Rename {{ folder_name }}">✎</button>
                            <form method="POST" action="/rename_quiz_folder" class="rename-folder-form library-inline-form" style="display:none;">
                                <input type="hidden" name="old_folder" value="{{ folder_name }}">
                                <input type="hidden" name="view" value="{{ view }}">
                                <input type="text" name="new_folder" value="{{ folder_name }}" required>
                                <button type="submit">Save</button>
                                <button type="button" class="library-quiet-button" onclick="hideRenameFolderForm(event, this)">Cancel</button>
                            </form>
                        </div>
                        <form method="POST" action="/delete_quiz_folder" onsubmit="return confirm('Delete this folder? Quizzes inside it will move to Uncategorized.');">
                            <input type="hidden" name="folder" value="{{ folder_name }}">
                            <input type="hidden" name="view" value="{{ view }}">
                            <button type="submit" class="library-icon-button library-danger-icon" title="Delete folder" aria-label="Delete {{ folder_name }} folder">🗑</button>
                        </form>
                    {% endif %}
                    </div>
                </div>

                <div class="library-folder-body" id="library-folder-body-{{ loop.index }}" data-folder-name="{{ folder_name }}">
                    {% if not folder_quizzes %}
                    <p class="library-folder-empty">No quizzes in this view.</p>
                    {% endif %}
                    {% for q in folder_quizzes %}
                    <article class="quiz-card library-quiz-card" data-id="{{ q['html'] }}" data-title="{{ q['title']|lower }}" data-search="{{ (q['title'] ~ ' ' ~ folder_name)|lower }}">
                        <div class="library-quiz-main">
                            <div class="library-quiz-title-row">
                                {% if q['logo'] %}
                                <div class="library-quiz-logo-frame" aria-hidden="true">
                                    <img class="library-quiz-logo" src="/user-static/logos/{{ q['logo'] }}" alt="">
                                </div>
                                {% endif %}
                                <div class="library-quiz-heading">
                                    <h3>{{ q['title'] }}</h3>
                                    <div class="library-quiz-meta">
                                        <span>Quiz #{{ q['id'] }}</span>
                                        <span>•</span>
                                        <span>{{ folder_name }}</span>
                                        {% if q.get('hidden') %}<span class="library-hidden-badge">Hidden</span>{% endif %}
                                        {% if folder_is_hidden %}<span class="library-folder-hidden-badge">Folder hidden</span>{% endif %}
                                    </div>
                                </div>
                            </div>

                            <div class="library-quiz-actions">
                                <a class="library-primary-action compact" href="/quizzes/{{ q['html'] }}">▶ Open Quiz</a>
                                <a class="library-secondary-action compact" href="/edit_quiz/{{ q['id'] }}">✎ Edit</a>
                                <a class="library-secondary-action compact" href="/export/quiz/{{ q['id'] }}.txt" title="Exports this quiz as an import-friendly DLMS text file.">⇩ Export</a>

                                {% if folder_quizzes|length > 1 %}
                                <div class="library-reorder-controls" role="group" aria-label="Reorder {{ q['title'] }} within {{ folder_name }}">
                                    <button type="button" class="library-icon-button library-reorder-button" data-library-reorder="quiz" data-library-reorder-direction="-1" onclick="moveLibraryQuiz(event, this, -1)" aria-label="Move {{ q['title'] }} up within {{ folder_name }}" title="Move quiz up" {% if loop.first %}disabled{% endif %}>↑</button>
                                    <button type="button" class="library-icon-button library-reorder-button" data-library-reorder="quiz" data-library-reorder-direction="1" onclick="moveLibraryQuiz(event, this, 1)" aria-label="Move {{ q['title'] }} down within {{ folder_name }}" title="Move quiz down" {% if loop.last %}disabled{% endif %}>↓</button>
                                </div>
                                {% endif %}

                                <form method="POST" action="/toggle_hidden" class="library-action-form">
                                    <input type="hidden" name="id" value="{{ q['id'] }}">
                                    <input type="hidden" name="view" value="{{ view }}">
                                    <button type="submit" class="library-secondary-action compact">{% if q.get('hidden') %}👁 Unhide{% else %}◌ Hide{% endif %}</button>
                                </form>

                                <div class="quiz-move-control">
                                    <button type="button" class="library-secondary-action compact" onclick="showMoveQuizForm(event, this)">▣ Move</button>
                                    <form method="POST" action="/move_quiz_folder" class="move-quiz-form library-inline-form" style="display:none;">
                                        <input type="hidden" name="id" value="{{ q['id'] }}">
                                        <input type="hidden" name="view" value="{{ view }}">
                                        <select name="folder">
                                            {% for folder in folder_names %}
                                            <option value="{{ folder }}" {% if q.get('folder', 'Uncategorized') == folder %}selected{% endif %}>{{ folder }}{% if folder|lower in hidden_folder_keys %} (hidden){% endif %}</option>
                                            {% endfor %}
                                        </select>
                                        <button type="submit">Save</button>
                                        <button type="button" class="library-quiet-button" onclick="hideMoveQuizForm(event, this)">Cancel</button>
                                    </form>
                                </div>

                                <form method="POST" action="/delete_quiz/{{ q['id'] }}" class="library-delete-form" onsubmit="return confirm('Delete this quiz permanently?');">
                                    <button type="submit" class="library-delete-button" title="Delete quiz" aria-label="Delete quiz">
                                        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                                            <path d="M4 7h16"></path>
                                            <path d="M9 7V4h6v3"></path>
                                            <path d="M7 7l1 13h8l1-13"></path>
                                            <path d="M10 11v5"></path>
                                            <path d="M14 11v5"></path>
                                        </svg>
                                    </button>
                                </form>
                            </div>
                        </div>
                    </article>
                    {% endfor %}
                </div>
            </article>
            {% endfor %}
        </section>
        {% endif %}
        {% if not normal_display_folder_names %}
        <section id="libraryEmptyState" class="library-empty dashboard-panel">
            <div class="library-empty-icon">▤</div>
            <h2>No quizzes found</h2>
            <p>There are no quizzes in the selected {{ view }} view.</p>
            <a class="library-primary-action" href="/upload">Build a Quiz</a>
        </section>
        {% endif %}

        <section class="library-footer-actions dashboard-panel">
            <div>
                <h2>Library Tools</h2>
                <p>Download a human-readable TXT reference of your complete quiz library. This reference is not a restorable or importable library package. Use <strong>Export</strong> on an individual quiz for an import-friendly classic MCQ text file, or <a href="/settings/backup">Settings → Backup &amp; Restore</a> portable backup for migration or full restore.</p>
            </div>
            <div class="library-footer-buttons">
                <a class="library-secondary-action" href="/create_short_quiz">✎ Create Short Quiz</a>
                <a class="library-secondary-action" href="/export/all_quizzes.txt" title="Downloads a human-readable reference only; it cannot restore or import a quiz library.">⇩ Download Quiz Library Reference (TXT)</a>
            </div>
        </section>
    </main>
</div>

<script>
function getCollapsedLibraryFolders() {
    try { return JSON.parse(localStorage.getItem("dlmsCollapsedLibraryFolders") || "[]"); }
    catch { return []; }
}

function saveCollapsedLibraryFolders(folders) {
    localStorage.setItem("dlmsCollapsedLibraryFolders", JSON.stringify(folders));
}

function setLibraryFolderCollapsed(folder, collapsed) {
    const body = folder.querySelector(".library-folder-body");
    const icon = folder.querySelector(".folder-toggle-icon");
    if (!body || !icon) return;
    body.style.display = collapsed ? "none" : "";
    icon.textContent = collapsed ? "▶" : "▼";
    icon.setAttribute("aria-expanded", String(!collapsed));
    const folderName = folder.getAttribute("data-folder-name") || "folder";
    icon.setAttribute("aria-label", `${collapsed ? "Expand" : "Collapse"} ${folderName}`);
    folder.classList.toggle("collapsed", collapsed);
}

function toggleLibraryFolder(event, header) {
    const nativeToggle = header.matches(".library-folder-toggle-button");
    if (!nativeToggle && event.target.closest("form, input, button, select, textarea, a")) return;
    const folder = header.closest(".library-folder");
    const folderName = folder.getAttribute("data-folder-name");
    if (!folderName) return;
    const collapsedFolders = getCollapsedLibraryFolders();
    const isCollapsed = collapsedFolders.includes(folderName);
    setLibraryFolderCollapsed(folder, !isCollapsed);
    saveCollapsedLibraryFolders(
        isCollapsed ? collapsedFolders.filter(name => name !== folderName) : [...collapsedFolders, folderName]
    );
}

function showRenameFolderForm(event, button) {
    event.stopPropagation();
    const actions = button.closest(".folder-actions");
    const form = actions && actions.querySelector(".rename-folder-form");
    if (!form) return;
    button.style.display = "none";
    form.style.display = "inline-flex";
    const input = form.querySelector('input[name="new_folder"]');
    if (input) { input.focus(); input.select(); }
}

function hideRenameFolderForm(event, button) {
    event.stopPropagation();
    const form = button.closest(".rename-folder-form");
    const actions = form && form.closest(".folder-actions");
    const renameButton = actions && actions.querySelector('button[onclick*="showRenameFolderForm"]');
    if (!form || !renameButton) return;
    form.style.display = "none";
    renameButton.style.display = "";
    renameButton.focus();
}

function showAddFolderForm(event, button) {
    event.stopPropagation();
    const control = button.closest(".add-folder-control");
    const form = control && control.querySelector(".add-folder-form");
    if (!form) return;
    button.style.display = "none";
    form.style.display = "inline-flex";
    const input = form.querySelector('input[name="folder"]');
    if (input) input.focus();
}

function hideAddFolderForm(event, button) {
    event.stopPropagation();
    const form = button.closest(".add-folder-form");
    const control = form && form.closest(".add-folder-control");
    const newFolderButton = control && control.querySelector('button[onclick*="showAddFolderForm"]');
    if (!form || !newFolderButton) return;
    form.style.display = "none";
    newFolderButton.style.display = "";
    newFolderButton.focus();
}

function showMoveQuizForm(event, button) {
    event.stopPropagation();
    const control = button.closest(".quiz-move-control");
    const form = control && control.querySelector(".move-quiz-form");
    if (!form) return;
    button.style.display = "none";
    form.style.display = "inline-flex";
    const select = form.querySelector('select[name="folder"]');
    if (select) select.focus();
}

function hideMoveQuizForm(event, button) {
    event.stopPropagation();
    const form = button.closest(".move-quiz-form");
    const control = form && form.closest(".quiz-move-control");
    const moveButton = control && control.querySelector('button[onclick*="showMoveQuizForm"]');
    if (!form || !moveButton) return;
    form.style.display = "none";
    moveButton.style.display = "";
    moveButton.focus();
}

function libraryReorderStatus(message) {
    const status = document.getElementById("libraryReorderStatus");
    if (status) status.textContent = message;
}

function libraryDirectItems(container, selector) {
    return [...container.children].filter(item => item.matches(selector));
}

function librarySearchIsActive() {
    return Boolean(document.getElementById("librarySearch")?.value.trim());
}

function updateLibraryReorderControls() {
    const searchIsActive = librarySearchIsActive();
    document.querySelectorAll('[data-library-reorder="folder"]').forEach(button => {
        const folder = button.closest(".library-folder");
        const list = folder && folder.parentElement;
        const folders = list ? libraryDirectItems(
            list, ".library-folder:not(.library-view-search-only)"
        ) : [];
        const position = folders.indexOf(folder);
        const direction = Number(button.dataset.libraryReorderDirection);
        button.disabled = searchIsActive || list?.dataset.reorderPending === "true" ||
            position < 0 || position + direction < 0 || position + direction >= folders.length;
    });
    document.querySelectorAll('[data-library-reorder="quiz"]').forEach(button => {
        const card = button.closest(".library-quiz-card");
        const body = card && card.parentElement;
        const cards = body ? libraryDirectItems(body, ".library-quiz-card") : [];
        const position = cards.indexOf(card);
        const direction = Number(button.dataset.libraryReorderDirection);
        button.disabled = searchIsActive || body?.dataset.reorderPending === "true" ||
            position < 0 || position + direction < 0 || position + direction >= cards.length;
    });
}

async function postLibraryReorder(url, payload) {
    const response = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status !== "ok") throw new Error("Could not save the new order.");
}

function saveLibraryFolderOrder(folderList) {
    const folders = libraryDirectItems(
        folderList, ".library-folder:not(.library-view-search-only)"
    )
        .map(folder => folder.getAttribute("data-folder-name"))
        .filter(Boolean);
    return postLibraryReorder("/save_folder_order", {
        folders,
        view: folderList.dataset.view || "visible"
    });
}

function saveLibraryQuizOrder(body) {
    const folder = body.getAttribute("data-folder-name") || "Uncategorized";
    const order = libraryDirectItems(body, ".library-quiz-card")
        .map(card => card.getAttribute("data-id"))
        .filter(Boolean);
    return postLibraryReorder("/save_quiz_order_in_folder", {folder, order});
}

async function moveLibraryItem(item, container, selector, direction, saveOrder, label) {
    if (!item || !container || ![-1, 1].includes(direction) ||
        container.dataset.reorderPending === "true" || librarySearchIsActive()) return;
    const items = libraryDirectItems(container, selector);
    const position = items.indexOf(item);
    const target = items[position + direction];
    if (!target) return;

    if (direction < 0) container.insertBefore(item, target);
    else container.insertBefore(target, item);
    container.dataset.reorderPending = "true";
    updateLibraryReorderControls();

    try {
        await saveOrder(container);
        libraryReorderStatus(`${label} moved ${direction < 0 ? "up" : "down"}.`);
    } catch {
        if (direction < 0) container.insertBefore(target, item);
        else container.insertBefore(item, target);
        libraryReorderStatus("The new order could not be saved. The item was returned to its previous position.");
    } finally {
        delete container.dataset.reorderPending;
        updateLibraryReorderControls();
    }
}

function moveLibraryFolder(event, button, direction) {
    event.preventDefault();
    event.stopPropagation();
    const folder = button.closest(".library-folder");
    void moveLibraryItem(
        folder, folder?.parentElement,
        ".library-folder:not(.library-view-search-only)", direction,
        saveLibraryFolderOrder, folder?.getAttribute("data-folder-name") || "Folder");
}

function moveLibraryQuiz(event, button, direction) {
    event.preventDefault();
    event.stopPropagation();
    const card = button.closest(".library-quiz-card");
    const label = card?.querySelector(".library-quiz-title-row h3")?.textContent.trim() || "Quiz";
    void moveLibraryItem(card, card?.parentElement, ".library-quiz-card", direction,
        saveLibraryQuizOrder, label);
}

document.addEventListener("DOMContentLoaded", function() {
    const collapsedFolders = getCollapsedLibraryFolders();
    document.querySelectorAll(".library-folder").forEach(folder => {
        const folderName = folder.getAttribute("data-folder-name");
        if (folderName && collapsedFolders.includes(folderName)) setLibraryFolderCollapsed(folder, true);
    });

    const search = document.getElementById("librarySearch");
    if (search) {
        search.addEventListener("input", function() {
            const term = search.value.trim().toLowerCase();
            let totalMatches = 0;
            document.querySelectorAll(".library-folder").forEach(folder => {
                let visibleCards = 0;
                folder.querySelectorAll(".library-quiz-card").forEach(card => {
                    const searchableText = card.dataset.search || card.dataset.title || "";
                    const matches = !term || searchableText.includes(term);
                    card.style.display = matches ? "" : "none";
                    if (matches) visibleCards += 1;
                });
                totalMatches += term ? visibleCards : 0;
                const hasSearchResult = Boolean(term) && visibleCards > 0;
                folder.classList.toggle(
                    "library-search-revealed",
                    folder.classList.contains("library-view-search-only") && hasSearchResult
                );
                folder.classList.toggle(
                    "library-search-empty",
                    Boolean(term) && visibleCards === 0
                );
                if (hasSearchResult && folder.classList.contains("collapsed")) {
                    folder.dataset.librarySearchWasCollapsed = "true";
                    setLibraryFolderCollapsed(folder, false);
                } else if (!term && folder.dataset.librarySearchWasCollapsed === "true") {
                    setLibraryFolderCollapsed(folder, true);
                    delete folder.dataset.librarySearchWasCollapsed;
                }
            });
            const emptyState = document.getElementById("libraryEmptyState");
            if (emptyState) {
                emptyState.style.display = term && totalMatches > 0 ? "none" : "";
            }
            updateLibraryReorderControls();
        });
    }

    const folderList = document.getElementById("quizList");
    if (folderList && window.Sortable) {
        Sortable.create(folderList, {
            animation: 150,
            draggable: ".library-folder:not(.library-view-search-only)",
            handle: ".library-folder-header",
            filter: "form, input, button, select, textarea, a",
            preventOnFilter: false,
            onEnd: function() {
                void saveLibraryFolderOrder(folderList).catch(() => {
                    libraryReorderStatus("The new folder order could not be saved.");
                });
                updateLibraryReorderControls();
            }
        });
    }

    if (window.Sortable) {
        document.querySelectorAll(".library-folder-body").forEach(body => {
            Sortable.create(body, {
                animation: 150,
                draggable: ".quiz-card",
                handle: ".quiz-card",
                filter: "form, input, button, select, textarea, a",
                preventOnFilter: false,
                onEnd: function() {
                    void saveLibraryQuizOrder(body).catch(() => {
                        libraryReorderStatus("The new quiz order could not be saved.");
                    });
                    updateLibraryReorderControls();
                }
            });
        });
    }

    updateLibraryReorderControls();
});

const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("🛑 SHUTDOWN DLMS 🛑\\n\\nThis will stop the application.\\n\\nYou will need to restart it manually.\\n\\nContinue?")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) { alert("❌ Failed to shut down DLMS."); }
    });
}

const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");
if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", (event) => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""", quizzes=quizzes, grouped_quizzes=grouped_quizzes, folder_names=folder_names,
       display_folder_names=display_folder_names,
       normal_display_folder_names=normal_display_folder_names,
       hidden_folder_keys=hidden_folder_keys, portal_title=portal_title,
       visible_count=visible_count, hidden_count=hidden_count,
       view_quiz_count=view_quiz_count, view=view, app_version=APP_VERSION)



# =========================
# UPLOAD PAGE
# =========================

# =========================
# BUILD FROM IMAGES
# =========================
def _safe_image_builder_draft(draft_id):
    draft_id = str(draft_id or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", draft_id):
        raise ValueError("Invalid image-builder draft")
    path = _safe_pack_child(IMAGE_BUILDER_DRAFT_FOLDER, draft_id)
    if not os.path.isdir(path):
        raise FileNotFoundError("Image-builder draft not found")
    return path


@app.route("/image-builder/drafts/<draft_id>/<path:filename>")
def image_builder_draft_asset(draft_id, filename):
    try:
        draft_root = _safe_image_builder_draft(draft_id)
        file_path = _safe_pack_child(draft_root, filename)
    except Exception:
        return "Draft image not found", 404
    if not os.path.isfile(file_path):
        return "Draft image not found", 404
    if os.path.splitext(file_path)[1].lower() not in PASSIVE_PACK_IMAGE_EXTENSIONS:
        return "Unsupported image", 415
    try:
        _decode_raster_image(file_path, PASSIVE_PACK_IMAGE_EXTENSIONS)
    except ValueError:
        return "Invalid draft image", 415
    return send_from_directory(draft_root, os.path.relpath(file_path, draft_root))


@app.route("/study-packs/image-builder", methods=["GET", "POST"])
def image_quiz_builder():
    draft = None
    if request.method == "POST":
        files = [f for f in request.files.getlist("study_images") if f and f.filename]
        if not files:
            flash("Choose at least one image.", "error")
            return redirect("/study-packs/image-builder")
        if len(files) > 12:
            flash("Upload at most 12 images at one time.", "error")
            return redirect("/study-packs/image-builder")

        draft_id = f"{int(time.time())}_{secrets.token_hex(5)}"
        draft_root = os.path.join(IMAGE_BUILDER_DRAFT_FOLDER, draft_id)
        os.makedirs(draft_root, exist_ok=False)
        images, used = [], set()
        remaining_upload_bytes = IMAGE_BUILDER_TOTAL_UPLOAD_MAX_BYTES
        for n, uploaded in enumerate(files, 1):
            original = secure_filename(uploaded.filename or "")
            ext = os.path.splitext(original)[1].lower()
            if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
                shutil.rmtree(draft_root, ignore_errors=True)
                flash("Images must be PNG, JPG/JPEG, or WEBP.", "error")
                return redirect("/study-packs/image-builder")
            base = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(original)[0]).strip("_") or f"image_{n}"
            filename = f"{base}{ext}"
            counter = 2
            while filename.casefold() in used:
                filename = f"{base}_{counter}{ext}"
                counter += 1
            used.add(filename.casefold())
            try:
                _store_raster_upload(
                    uploaded, draft_root, filename, PASSIVE_PACK_IMAGE_EXTENSIONS,
                    min(RASTER_UPLOAD_MAX_BYTES, remaining_upload_bytes),
                )
                remaining_upload_bytes -= int(getattr(uploaded, "_dlms_consumed_bytes", 0))
            except ValueError as exc:
                shutil.rmtree(draft_root, ignore_errors=True)
                flash(f"Image {uploaded.filename!r} was rejected: {exc}", "error")
                return redirect("/study-packs/image-builder")
            images.append({
                "id": f"image_{n}", "filename": filename,
                "original_name": uploaded.filename,
                "url": url_for("image_builder_draft_asset", draft_id=draft_id, filename=filename),
            })
        draft = {"id": draft_id, "images": images}

    return render_template_string(
        IMAGE_QUIZ_BUILDER_TEMPLATE, draft=draft,
        medical_pack_installed=True
    )


@app.route("/study-packs/image-builder/save", methods=["POST"])
def image_quiz_builder_save():
    draft_id = str(request.form.get("draft_id") or "").strip()
    title = str(request.form.get("pack_title") or "").strip()
    subject = str(request.form.get("subject") or "General").strip()
    description = str(request.form.get("description") or "").strip()
    source_note = str(request.form.get("source_note") or "").strip()
    rights_ok = bool(request.form.get("rights_ok"))
    if not title:
        return "Study pack title is required", 400
    if not rights_ok:
        return "Confirm permission to use the uploaded images.", 400

    try:
        draft_root = _safe_image_builder_draft(draft_id)
        payload = json.loads(str(request.form.get("builder_payload") or ""))
    except Exception as exc:
        print(f"[IMAGE BUILDER INPUT ERROR] {type(exc).__name__}: {exc}")
        return "Invalid image-builder data. Restart the image workflow and try again.", 400

    images_payload = payload.get("images") or []
    questions_payload = payload.get("questions") or []
    if not images_payload or not questions_payload:
        return "At least one image and one question are required.", 400

    try:
        result = _create_image_study_pack(
            draft_root=draft_root,
            title=title,
            subject=subject,
            description=description,
            source_note=source_note,
            images_payload=images_payload,
            questions_payload=questions_payload,
            artifact_identity=_generated_quiz_artifact_identity(),
            exam_minutes=request.form.get("exam_minutes"),
        )
        flash("Image study pack and quiz created successfully.", "success")
        return redirect(f"/quizzes/{result['html_name']}")
    except Exception as exc:
        print(f"[IMAGE BUILDER CREATE ERROR] {type(exc).__name__}: {exc}")
        return "Unable to create the image Study Pack. Check the local DLMS log for details.", 400


def _create_image_study_pack(
    *,
    draft_root,
    title,
    subject,
    description,
    source_note,
    images_payload,
    questions_payload,
    artifact_identity,
    exam_minutes,
):
    return _content_pack_mutation_service.create_image_study_pack(
        draft_root=draft_root,
        title=title,
        subject=subject,
        description=description,
        source_note=source_note,
        images_payload=images_payload,
        questions_payload=questions_payload,
        artifact_identity=artifact_identity,
        exam_minutes=exam_minutes,
        content_pack_folder=CONTENT_PACK_FOLDER,
        safe_pack_child=_safe_pack_child,
        secure_filename=secure_filename,
        validate_hotspot_shape=_validate_hotspot_shape,
        now=datetime.now,
        load_content_pack_quiz_dataset=load_content_pack_quiz_dataset,
        quiz_dataset_runtime=_quiz_dataset_runtime,
        publish_quiz=_create_quiz_from_runtime,
        copy_file=shutil.copy2,
        remove_tree=shutil.rmtree,
    )


IMAGE_QUIZ_BUILDER_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Build from Images - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home image-builder-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar"><div class="dashboard-brand"><div class="dashboard-brand-mark">▧</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div>
<nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item active" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>{% if medical_pack_installed %}<a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>{% endif %}</nav>
<div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a></nav><div class="dashboard-sidebar-version">Build from Images</div></aside>
<main class="dashboard-main image-builder-main"><header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="build-eyebrow">IMAGE-BASED QUIZ BUILDER</div><h1>Build from Images</h1><p>Use images exactly as they are, attach questions below them, or create clickable hotspot questions. Editing is optional.</p></div></header>

{% if not draft %}
<section class="dashboard-panel image-builder-intro"><div class="image-builder-step-badge">1</div><div><span class="build-method-label">UPLOAD</span><h2>Choose one or more images</h2><p>Upload clean diagrams, screenshots, photographs, figures, or other study images. You can use them as-is.</p></div>
<form method="POST" enctype="multipart/form-data" class="image-builder-upload-form"><label class="build-field"><span>Study Images</span><input type="file" name="study_images" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" multiple required><small>PNG, JPG/JPEG, or WEBP · up to 12 images.</small></label><button class="build-primary-button" type="submit">Upload &amp; Continue</button></form></section>
<section class="image-builder-feature-grid"><div class="dashboard-panel"><strong>Use As-Is</strong><p>No editing is required. The image can simply appear above a normal question.</p></div><div class="dashboard-panel"><strong>Normal Questions</strong><p>Create multiple-choice, multi-select, or matching questions tied to an image.</p></div><div class="dashboard-panel"><strong>Clickable Regions</strong><p>Create a hotspot target now and refine it later in Image Study Editor if needed.</p></div></section>
{% else %}
<form method="POST" action="/study-packs/image-builder/save" id="builderForm"><input type="hidden" name="draft_id" value="{{ draft.id }}"><input type="hidden" name="builder_payload" id="builderPayload">
<section class="dashboard-panel image-builder-settings"><div class="image-builder-section-heading"><div class="image-builder-step-badge">2</div><div><span class="build-method-label">STUDY PACK</span><h2>Name and organize the study material</h2></div></div>
<div class="image-builder-settings-grid"><label class="build-field"><span>Study Pack / Quiz Title</span><input name="pack_title" required placeholder="Example: OSI Model Diagram Review"></label><label class="build-field"><span>Subject / Domain</span><select name="subject"><option>IT / Cybersecurity</option><option>General</option><option>Science</option><option>Medical</option><option>History</option><option>Language</option><option>Other</option></select></label><label class="build-field"><span>Exam Mode Timer</span><input type="number" name="exam_minutes" min="1" max="1440" value="90"></label><label class="build-field image-builder-wide"><span>Description <em>Optional</em></span><input name="description" placeholder="What this image study pack covers"></label><label class="build-field image-builder-wide"><span>Source / Credit Note <em>Optional</em></span><input name="source_note" placeholder="Example: My own diagram, instructor-provided image, vendor documentation screenshot"></label></div></section>
<section class="dashboard-panel image-builder-images"><div class="image-builder-section-heading"><div class="image-builder-step-badge">3</div><div><span class="build-method-label">IMAGES</span><h2>Your uploaded images</h2><p>These are used as-is. You can edit them later in Image Study Editor.</p></div></div><div class="image-builder-thumb-grid">{% for image in draft.images %}<article class="image-builder-thumb"><img src="{{ image.url }}" alt="{{ image.original_name }}"><strong>{{ image.original_name }}</strong><input class="image-alt-input" data-image-id="{{ image.id }}" value="{{ image.original_name }}" placeholder="Accessible image description"></article>{% endfor %}</div></section>
<section class="dashboard-panel image-builder-questions"><div class="image-builder-section-heading"><div class="image-builder-step-badge">4</div><div><span class="build-method-label">QUESTIONS</span><h2>Add questions to the images</h2><p>The same image can be reused for several different question types.</p></div><button type="button" class="build-primary-button" id="addQuestionBtn">+ Add Question</button></div><div id="questionList"></div></section>
<section class="dashboard-panel image-builder-finish"><label class="image-builder-rights"><input type="checkbox" name="rights_ok" required><span>I have permission to use these uploaded images for my study material. DLMS will mark the generated pack as user-supplied and not cleared for redistribution.</span></label><div class="image-builder-submit-row"><button class="build-primary-button" type="submit">Create Study Pack &amp; Quiz</button><a class="medical-ai-quiet-link" href="/study-packs/image-builder">Start Over</a></div></section></form>

<script>
const DRAFT={{ draft|tojson }};let qCounter=0;const list=document.getElementById('questionList');
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}
function imageOptions(){return DRAFT.images.map(i=>`<option value="${esc(i.id)}">${esc(i.original_name)}</option>`).join('')}
function choiceRow(){return `<div class="image-builder-choice-row"><input type="checkbox" class="choice-correct" title="Correct answer"><input type="text" class="choice-text" placeholder="Answer choice"><button type="button" class="image-builder-small-delete" onclick="this.parentElement.remove()">×</button></div>`}
function pairRow(){return `<div class="image-builder-pair-row"><input class="pair-left" placeholder="Left item"><span>↔</span><input class="pair-right" placeholder="Matching answer"><button type="button" class="image-builder-small-delete" onclick="this.parentElement.remove()">×</button></div>`}
function addQuestion(){qCounter++;const el=document.createElement('article');el.className='image-builder-question-card';el.innerHTML=`<div class="image-builder-question-head"><strong>Question ${qCounter}</strong><button type="button" class="image-builder-small-delete" onclick="this.closest('.image-builder-question-card').remove()">Remove</button></div><div class="image-builder-question-grid"><label class="build-field"><span>Image</span><select class="q-image">${imageOptions()}</select></label><label class="build-field"><span>Question Type</span><select class="q-type"><option value="choice">Multiple Choice / Multi-select</option><option value="matching">Matching</option><option value="hotspot">Clickable Hotspot</option></select></label><label class="build-field image-builder-wide"><span>Question</span><textarea class="q-text" rows="2" placeholder="Ask a question about the selected image"></textarea></label><label class="build-field image-builder-wide"><span>Study Mode Explanation <em>Optional</em></span><textarea class="q-explanation" rows="2" placeholder="Explain why the answer is correct"></textarea></label></div><div class="q-choice-editor"><div class="image-builder-subhead"><strong>Answer choices</strong><span>Check every correct answer. One checked = multiple choice; more than one = multi-select.</span></div><div class="choice-list">${choiceRow()}${choiceRow()}${choiceRow()}${choiceRow()}</div><button type="button" class="medical-ai-secondary-button add-choice">+ Choice</button></div><div class="q-matching-editor" hidden><div class="image-builder-subhead"><strong>Matching pairs</strong><span>Add at least two pairs.</span></div><div class="pair-list">${pairRow()}${pairRow()}</div><button type="button" class="medical-ai-secondary-button add-pair">+ Pair</button></div><div class="q-hotspot-editor" hidden><div class="image-builder-subhead"><strong>Clickable target</strong><span>Choose a circle or polygon, then click the image to define the region.</span></div><div class="image-builder-hotspot-controls"><label class="build-field"><span>Target Label</span><input class="hotspot-label" placeholder="Example: Firewall"></label><label class="build-field"><span>Shape</span><select class="hotspot-shape"><option value="circle">Circle</option><option value="polygon">Polygon</option></select></label><label class="build-field"><span>Circle Radius <b class="radius-readout">0.060</b></span><input type="range" class="hotspot-radius" min="0.015" max="0.30" step="0.005" value="0.06"></label></div><div class="image-builder-hotspot-stage"><img class="hotspot-preview" draggable="false"><svg viewBox="0 0 1000 1000" preserveAspectRatio="none"><polygon></polygon><circle></circle><g></g></svg></div><div class="image-builder-hotspot-actions"><button type="button" class="medical-ai-secondary-button clear-hotspot">Clear Region</button><span class="hotspot-status">Circle: click the target center.</span></div></div>`;list.appendChild(el);initQuestion(el)}
function initQuestion(el){const type=el.querySelector('.q-type'),imageSel=el.querySelector('.q-image'),choiceEd=el.querySelector('.q-choice-editor'),matchEd=el.querySelector('.q-matching-editor'),hotEd=el.querySelector('.q-hotspot-editor'),img=el.querySelector('.hotspot-preview'),svg=el.querySelector('.image-builder-hotspot-stage svg'),poly=svg.querySelector('polygon'),circle=svg.querySelector('circle'),handles=svg.querySelector('g');el._shape={center:null,points:[]};function refreshImage(){const i=DRAFT.images.find(x=>x.id===imageSel.value)||DRAFT.images[0];if(i)img.src=i.url}function refreshType(){choiceEd.hidden=type.value!=='choice';matchEd.hidden=type.value!=='matching';hotEd.hidden=type.value!=='hotspot';if(type.value==='hotspot')refreshImage()}function draw(){const kind=el.querySelector('.hotspot-shape').value,r=Number(el.querySelector('.hotspot-radius').value);poly.setAttribute('points','');circle.setAttribute('r','0');handles.innerHTML='';if(kind==='circle'&&el._shape.center){circle.setAttribute('cx',el._shape.center[0]*1000);circle.setAttribute('cy',el._shape.center[1]*1000);circle.setAttribute('r',r*1000)}if(kind==='polygon'&&el._shape.points.length){poly.setAttribute('points',el._shape.points.map(p=>`${p[0]*1000},${p[1]*1000}`).join(' '));el._shape.points.forEach(p=>{const c=document.createElementNS('http://www.w3.org/2000/svg','circle');c.setAttribute('cx',p[0]*1000);c.setAttribute('cy',p[1]*1000);c.setAttribute('r','8');c.setAttribute('class','image-builder-hotspot-handle');handles.appendChild(c)})}}type.addEventListener('change',refreshType);imageSel.addEventListener('change',refreshImage);el.querySelector('.add-choice').onclick=()=>el.querySelector('.choice-list').insertAdjacentHTML('beforeend',choiceRow());el.querySelector('.add-pair').onclick=()=>el.querySelector('.pair-list').insertAdjacentHTML('beforeend',pairRow());el.querySelector('.hotspot-shape').addEventListener('change',()=>{el._shape={center:null,points:[]};draw()});el.querySelector('.hotspot-radius').addEventListener('input',e=>{el.querySelector('.radius-readout').textContent=Number(e.target.value).toFixed(3);draw()});el.querySelector('.clear-hotspot').onclick=()=>{el._shape={center:null,points:[]};draw()};img.addEventListener('click',ev=>{const r=img.getBoundingClientRect(),x=Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width)),y=Math.max(0,Math.min(1,(ev.clientY-r.top)/r.height));if(el.querySelector('.hotspot-shape').value==='circle')el._shape.center=[x,y];else el._shape.points.push([x,y]);draw()});refreshType();refreshImage()}
function collect(){const images=DRAFT.images.map(i=>{const alt=document.querySelector(`.image-alt-input[data-image-id="${i.id}"]`);return {...i,alt_text:alt?.value||i.original_name}}),questions=[];document.querySelectorAll('.image-builder-question-card').forEach(el=>{const type=el.querySelector('.q-type').value,q={type,image_id:el.querySelector('.q-image').value,question:el.querySelector('.q-text').value.trim(),explanation:el.querySelector('.q-explanation').value.trim()};if(type==='choice')q.choices=[...el.querySelectorAll('.image-builder-choice-row')].map(r=>({text:r.querySelector('.choice-text').value.trim(),is_correct:r.querySelector('.choice-correct').checked})).filter(c=>c.text);if(type==='matching')q.pairs=[...el.querySelectorAll('.image-builder-pair-row')].map(r=>({left:r.querySelector('.pair-left').value.trim(),right:r.querySelector('.pair-right').value.trim()})).filter(p=>p.left||p.right);if(type==='hotspot'){q.target_label=el.querySelector('.hotspot-label').value.trim();const kind=el.querySelector('.hotspot-shape').value;q.shape=kind==='circle'?(el._shape.center?{type:'circle',x:el._shape.center[0],y:el._shape.center[1],radius:Number(el.querySelector('.hotspot-radius').value)}:null):{type:'polygon',points:el._shape.points}}questions.push(q)});return {images,questions}}
document.getElementById('addQuestionBtn').onclick=addQuestion;document.getElementById('builderForm').addEventListener('submit',ev=>{const p=collect();if(!p.questions.length){ev.preventDefault();alert('Add at least one question.');return}for(let i=0;i<p.questions.length;i++){const q=p.questions[i];if(!q.question){ev.preventDefault();alert(`Question ${i+1} needs question text.`);return}if(q.type==='choice'&&(!q.choices||q.choices.length<2||!q.choices.some(c=>c.is_correct))){ev.preventDefault();alert(`Question ${i+1} needs at least two choices and one correct answer.`);return}if(q.type==='matching'&&(!q.pairs||q.pairs.length<2||q.pairs.some(x=>!x.left||!x.right))){ev.preventDefault();alert(`Question ${i+1} needs at least two complete matching pairs.`);return}if(q.type==='hotspot'&&(!q.target_label||!q.shape||(q.shape.type==='polygon'&&q.shape.points.length<3))){ev.preventDefault();alert(`Question ${i+1} needs a target label and valid hotspot region.`);return}}document.getElementById('builderPayload').value=JSON.stringify(p)});addQuestion();
</script>
{% endif %}
</main></div><script>document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));</script><script src="/static/nav-normalize.js"></script>
</body></html>
"""



# =========================================================
# PERSISTENT PDF QUESTION BANKS
# =========================================================
def _pdf_bank_safe_id(value):
    return _pdf_bank_repository._pdf_bank_safe_id(value)

def _pdf_bank_path(bank_id):
    return _pdf_bank_repository._pdf_bank_path(
        PDF_QUESTION_BANK_FOLDER,
        bank_id,
        safe_id=_pdf_bank_safe_id,
        safe_child=_safe_pack_child,
    )

def _save_pdf_question_bank(bank):
    return _pdf_bank_repository._save_pdf_question_bank(
        PDF_QUESTION_BANK_FOLDER,
        bank,
        safe_id=_pdf_bank_safe_id,
        path_for_id=_pdf_bank_path,
        timestamp_now=lambda: datetime.now().isoformat(timespec="seconds"),
        atomic_write_json=_atomic_write_json,
        os_module=os,
    )

def _load_pdf_question_bank(bank_id):
    return _pdf_bank_repository._load_pdf_question_bank(
        PDF_QUESTION_BANK_FOLDER,
        bank_id,
        path_for_id=_pdf_bank_path,
        os_module=os,
        json_module=json,
    )

def _list_pdf_question_banks():
    return _pdf_bank_repository._list_pdf_question_banks(
        PDF_QUESTION_BANK_FOLDER,
        os_module=os,
        json_module=json,
        print_message=print,
    )

def _delete_pdf_question_bank(bank_id):
    return _pdf_bank_repository._delete_pdf_question_bank(
        PDF_QUESTION_BANK_FOLDER,
        bank_id,
        load_bank=_load_pdf_question_bank,
        path_for_id=_pdf_bank_path,
        os_module=os,
    )


def _pdf_bank_active_questions(bank):
    active = [
        q for q in (bank.get("questions") or [])
        if isinstance(q, dict) and q.get("active", True)
    ]
    return sorted(
        active,
        key=lambda q: (int(q.get("original_number") or q.get("number") or 0), int(q.get("number") or 0))
    )

def _select_pdf_bank_questions(bank, mode="random", count=50, start_number=1, end_number=None):
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
            q for q in active
            if start_number <= int(q.get("original_number") or q.get("number") or 0) <= end_number
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
            q for q in active
            if int(q.get("original_number") or q.get("number") or 0) >= start_number
        ]
        if not candidates:
            raise ValueError("No active questions exist at or after that starting question number.")
        return candidates[:count]

    if mode == "unused":
        used = {int(n) for n in (bank.get("used_question_numbers") or []) if str(n).isdigit()}
        candidates = [
            q for q in active
            if int(q.get("original_number") or q.get("number") or 0) not in used
        ]
        if not candidates:
            raise ValueError("All active questions in this bank have already been used.")
        return random.sample(candidates, min(count, len(candidates)))

    # Default: random from the entire active bank.
    return random.sample(active, count)

def _pdf_bank_question_to_quiz(question, number, bank):
    choices = []
    correct = str(question.get("correct") or "").strip().upper()
    for raw in question.get("choices") or []:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip().upper()
        text = str(raw.get("text") or "").strip()
        if label and text:
            choices.append({
                "label": label,
                "text": text,
                "is_correct": label == correct,
            })
    if len(choices) < 2 or correct not in {c["label"] for c in choices}:
        raise ValueError(
            f"Bank question {question.get('original_number') or question.get('number')} is incomplete."
        )
    return {
        "number": number,
        "type": "choice",
        "question": str(question.get("question") or "").strip(),
        "choices": choices,
        "correct": [correct],
        "explanation": str(question.get("explanation") or "").strip(),
        "source": {
            "organization": "User-provided document",
            "dataset": bank.get("source_name") or bank.get("title") or "PDF question bank",
            "version": "",
            "url": "",
            "license": "User-provided; redistribution not cleared",
        },
    }


# =========================================================
# PERSISTENT PDF TERMINOLOGY BANKS
# Kept separate from question-bank storage for backward compatibility.
# =========================================================
def _pdf_term_bank_safe_id(value):
    return _pdf_bank_repository._pdf_term_bank_safe_id(value)

def _pdf_term_bank_path(bank_id):
    return _pdf_bank_repository._pdf_term_bank_path(
        PDF_TERMINOLOGY_BANK_FOLDER,
        bank_id,
        safe_id=_pdf_term_bank_safe_id,
        safe_child=_safe_pack_child,
    )

def _save_pdf_terminology_bank(bank):
    return _pdf_bank_repository._save_pdf_terminology_bank(
        PDF_TERMINOLOGY_BANK_FOLDER,
        bank,
        safe_id=_pdf_term_bank_safe_id,
        path_for_id=_pdf_term_bank_path,
        timestamp_now=lambda: datetime.now().isoformat(timespec="seconds"),
        atomic_write_json=_atomic_write_json,
        os_module=os,
    )

def _load_pdf_terminology_bank(bank_id):
    return _pdf_bank_repository._load_pdf_terminology_bank(
        PDF_TERMINOLOGY_BANK_FOLDER,
        bank_id,
        path_for_id=_pdf_term_bank_path,
        os_module=os,
        json_module=json,
    )

def _list_pdf_terminology_banks():
    return _pdf_bank_repository._list_pdf_terminology_banks(
        PDF_TERMINOLOGY_BANK_FOLDER,
        os_module=os,
        json_module=json,
        print_message=print,
    )

def _delete_pdf_terminology_bank(bank_id):
    return _pdf_bank_repository._delete_pdf_terminology_bank(
        PDF_TERMINOLOGY_BANK_FOLDER,
        bank_id,
        load_bank=_load_pdf_terminology_bank,
        path_for_id=_pdf_term_bank_path,
        os_module=os,
    )


def _pdf_term_bank_active_terms(bank):
    active = [
        t for t in (bank.get("terms") or [])
        if isinstance(t, dict) and t.get("active", True)
    ]
    return sorted(active, key=lambda t: int(t.get("number") or 0))

def _select_pdf_term_bank_items(bank, mode="random", count=25, start_number=1, end_number=None):
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
        selected = [t for t in active if start_number <= int(t.get("number") or 0) <= end_number]
        if not selected:
            raise ValueError("No active terms fall within that range.")
        return selected

    if mode == "sequential":
        try:
            start_number = int(start_number)
        except Exception:
            start_number = 1
        candidates = [t for t in active if int(t.get("number") or 0) >= start_number]
        if not candidates:
            raise ValueError("No active terms exist at or after that starting number.")
        return candidates[:count]

    if mode == "unused":
        used = {int(n) for n in (bank.get("used_term_numbers") or []) if str(n).isdigit()}
        candidates = [t for t in active if int(t.get("number") or 0) not in used]
        if not candidates:
            raise ValueError("All active terms in this bank have already been used.")
        return random.sample(candidates, min(count, len(candidates)))

    return random.sample(active, count)

def _pdf_term_source(bank):
    return {
        "organization": "User-provided document",
        "dataset": bank.get("source_name") or bank.get("title") or "PDF terminology bank",
        "version": "",
        "url": "",
        "license": "User-provided; redistribution not cleared",
    }

def _pdf_terms_matching_questions(bank, selected, direction="random"):
    pairs = [
        {"left": str(t.get("term") or "").strip(), "right": str(t.get("definition") or "").strip()}
        for t in selected
        if str(t.get("term") or "").strip() and str(t.get("definition") or "").strip()
    ]
    if len(pairs) < 2:
        raise ValueError("Matching practice requires at least two complete terms.")
    q = {
        "number": 1,
        "type": "matching",
        "question": "Match each term with its correct definition.",
        "pairs": pairs,
        "round_size": len(pairs),
        "direction": direction if direction in {"random", "term_to_definition", "definition_to_term"} else "random",
        "explanation": "Definitions are taken from the reviewed user-provided terminology bank.",
        "source": _pdf_term_source(bank),
    }
    return [q], [dict(q)]

def _pdf_terms_mc_questions(bank, selected, direction="definition_to_term"):
    pool = _pdf_term_bank_active_terms(bank)
    if len(pool) < 4:
        raise ValueError("Multiple-choice terminology practice requires at least four active terms.")

    runtime, db_questions = [], []
    for number, target in enumerate(selected, 1):
        target_term = str(target.get("term") or "").strip()
        target_def = str(target.get("definition") or "").strip()
        if not target_term or not target_def:
            continue

        distractor_pool = [t for t in pool if int(t.get("number") or 0) != int(target.get("number") or 0)]
        distractors = random.sample(distractor_pool, 3)
        option_terms = [target] + distractors
        random.shuffle(option_terms)

        choices = []
        correct = []
        for option in option_terms:
            label = chr(65 + len(choices))
            is_correct = int(option.get("number") or 0) == int(target.get("number") or 0)
            if direction == "term_to_definition":
                text = str(option.get("definition") or "").strip()
            else:
                text = str(option.get("term") or "").strip()
            choices.append({"label": label, "text": text, "is_correct": is_correct})
            if is_correct:
                correct.append(label)

        if direction == "term_to_definition":
            question = f"Which definition best matches the term: {target_term}?"
        else:
            question = f"Which term best matches this definition? {target_def}"

        q = {
            "number": number,
            "type": "choice",
            "question": question,
            "choices": choices,
            "correct": correct,
            "explanation": f"{target_term}: {target_def}",
            "source": _pdf_term_source(bank),
        }
        runtime.append(q)
        db_questions.append(dict(q))

    if not runtime:
        raise ValueError("No usable multiple-choice questions were generated.")
    return runtime, db_questions

# =========================================================
# SMART PDF IMPORT — QUESTION BANK MVP
# Isolated from the existing text/paste/CSV parsers.
# =========================================================
PDF_IMPORT_MAX_BYTES = 64 * 1024 * 1024
# Two thousand pages covers unusually large study manuals/question banks while
# placing a deterministic bound on per-request PDF work.
PDF_IMPORT_MAX_PAGES = _smart_pdf_parser.PDF_IMPORT_MAX_PAGES
PDF_IMPORT_MAX_EXTRACTED_TEXT_BYTES = _smart_pdf_parser.PDF_IMPORT_MAX_EXTRACTED_TEXT_BYTES
PDF_IMPORT_MAX_PAGE_TEXT_BYTES = _smart_pdf_parser.PDF_IMPORT_MAX_PAGE_TEXT_BYTES
PDFResourceLimitError = _smart_pdf_parser.PDFResourceLimitError

def _pdf_import_safe_id(value):
    return _pdf_bank_repository._pdf_import_safe_id(value)

def _pdf_import_draft_path(draft_id):
    return _pdf_bank_repository._pdf_import_draft_path(
        PDF_IMPORT_DRAFT_FOLDER,
        draft_id,
        safe_id=_pdf_import_safe_id,
        safe_child=_safe_pack_child,
    )

def _save_pdf_import_draft(draft):
    return _pdf_bank_repository._save_pdf_import_draft(
        PDF_IMPORT_DRAFT_FOLDER,
        draft,
        safe_id=_pdf_import_safe_id,
        path_for_id=_pdf_import_draft_path,
        os_module=os,
        json_module=json,
    )

def _load_pdf_import_draft(draft_id):
    return _pdf_bank_repository._load_pdf_import_draft(
        PDF_IMPORT_DRAFT_FOLDER,
        draft_id,
        path_for_id=_pdf_import_draft_path,
        os_module=os,
        json_module=json,
    )

def _pdf_clean_line(line):
    return _smart_pdf_parser._pdf_clean_line(line)


def _pdf_extract_pages(pdf_path):
    return _smart_pdf_parser._pdf_extract_pages(
        pdf_path,
        max_pages=PDF_IMPORT_MAX_PAGES,
        max_extracted_text_bytes=PDF_IMPORT_MAX_EXTRACTED_TEXT_BYTES,
        max_page_text_bytes=PDF_IMPORT_MAX_PAGE_TEXT_BYTES,
        resource_limit_error=PDFResourceLimitError,
        format_bytes=_format_bytes,
        clean_line=_pdf_clean_line,
    )


def _pdf_suppress_repeated_margins(pages):
    return _smart_pdf_parser._pdf_suppress_repeated_margins(pages)


def _pdf_lines_to_stream(pages):
    return _smart_pdf_parser._pdf_lines_to_stream(pages)


def _pdf_join_wrapped(lines):
    return _smart_pdf_parser._pdf_join_wrapped(lines)


def _pdf_parse_question_chunk(number, records):
    return _smart_pdf_parser._pdf_parse_question_chunk(number, records)


def _pdf_glossary_term_like(text):
    return _smart_pdf_parser._pdf_glossary_term_like(text)


def _pdf_glossary_definition_like(text):
    return _smart_pdf_parser._pdf_glossary_definition_like(text)


def _pdf_split_glossary_line(line):
    return _smart_pdf_parser._pdf_split_glossary_line(line)


def _pdf_styled_glossary_header(text):
    return _smart_pdf_parser._pdf_styled_glossary_header(text)


def _pdf_style_glossary_line(line):
    return _smart_pdf_parser._pdf_style_glossary_line(line)


def _pdf_parse_glossary_styled(pages):
    return _smart_pdf_parser._pdf_parse_glossary_styled(pages)


def _pdf_parse_glossary(pages):
    return _smart_pdf_parser._pdf_parse_glossary(
        pages,
        parse_glossary_styled=_pdf_parse_glossary_styled,
        lines_to_stream=_pdf_lines_to_stream,
        split_glossary_line=_pdf_split_glossary_line,
        glossary_term_like=_pdf_glossary_term_like,
        glossary_definition_like=_pdf_glossary_definition_like,
        join_wrapped=_pdf_join_wrapped,
    )


def _pdf_question_start_match(text):
    return _smart_pdf_parser._pdf_question_start_match(text)


def _pdf_question_chunk_structure(records):
    return _smart_pdf_parser._pdf_question_chunk_structure(records)


def _pdf_add_question_review_slots(question, minimum_labels=("A", "B", "C", "D")):
    return _smart_pdf_parser._pdf_add_question_review_slots(question, minimum_labels)


def _pdf_question_recovery_result(pages):
    return _smart_pdf_parser._pdf_question_recovery_result(pages)


def _pdf_glossary_recovery_result(pages):
    return _smart_pdf_parser._pdf_glossary_recovery_result(pages)


def _pdf_detect_document_type(pages, question_result=None, glossary_result=None):
    if not isinstance(question_result, dict):
        question_result = _pdf_parse_question_bank(pages)
    if not isinstance(glossary_result, dict):
        glossary_result = _pdf_parse_glossary(pages)
    return _smart_pdf_parser._pdf_detect_document_type(
        pages,
        question_result=question_result,
        glossary_result=glossary_result,
    )


def _pdf_parse_question_bank(pages):
    return _smart_pdf_parser._pdf_parse_question_bank(
        pages,
        lines_to_stream=_pdf_lines_to_stream,
        question_start_match=_pdf_question_start_match,
        question_chunk_structure=_pdf_question_chunk_structure,
        parse_question_chunk=_pdf_parse_question_chunk,
    )

@app.route("/pdf-import")
def pdf_import_page():
    template = r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Smart PDF Import - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico">
<style>
/* Smart PDF page-local containment. Keeps long text, form controls, and grids inside panels. */
.pdf-import-page *,
.pdf-import-page *::before,
.pdf-import-page *::after { box-sizing: border-box; }

.pdf-import-page .dashboard-main,
.pdf-import-page .dashboard-header,
.pdf-import-page .dashboard-panel,
.pdf-import-page .pdf-import-intro,
.pdf-import-page .pdf-bank-list-panel,
.pdf-import-page .pdf-bank-generator,
.pdf-import-page .pdf-bank-source-panel,
.pdf-import-page .pdf-import-create-bar {
    min-width: 0;
    max-width: 100%;
}

.pdf-import-page .dashboard-header > div,
.pdf-import-page .dashboard-header p,
.pdf-import-page .pdf-bank-panel-heading,
.pdf-import-page .pdf-bank-panel-heading > div,
.pdf-import-page .pdf-bank-row > *,
.pdf-import-page .pdf-bank-mode-help > *,
.pdf-import-page .pdf-import-intro > * {
    min-width: 0;
    overflow-wrap: anywhere;
    word-break: normal;
}

.pdf-import-page .pdf-import-upload-form,
.pdf-import-page .pdf-bank-generator-form {
    min-width: 0;
    width: 100%;
}

.pdf-import-page .pdf-import-upload-form > *,
.pdf-import-page .pdf-bank-generator-form > *,
.pdf-import-page .build-field {
    min-width: 0;
}

.pdf-import-page input[type="text"],
.pdf-import-page input[type="number"],
.pdf-import-page input[type="file"],
.pdf-import-page select,
.pdf-import-page textarea {
    width: 100%;
    max-width: 100%;
    min-width: 0;
}

.pdf-import-page input[type="file"] {
    overflow: hidden;
}

.pdf-import-page .pdf-bank-row {
    min-width: 0;
}

.pdf-import-page .pdf-bank-row > div:first-child strong,
.pdf-import-page .pdf-bank-row > div:first-child small {
    display: block;
    max-width: 100%;
    overflow-wrap: anywhere;
}

.pdf-import-page .pdf-bank-generator-form {
    grid-template-columns: minmax(0, 2fr) minmax(120px, .7fr) minmax(180px, 1fr);
}

.pdf-import-page .pdf-bank-question-table-wrap {
    width: 100%;
    max-width: 100%;
    overflow-x: auto;
}

.pdf-import-page .pdf-bank-question-table {
    width: 100%;
    table-layout: fixed;
}

.pdf-import-page .pdf-bank-question-table th:nth-child(1),
.pdf-import-page .pdf-bank-question-table td:nth-child(1) { width: 6%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(2),
.pdf-import-page .pdf-bank-question-table td:nth-child(2) { width: 14%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(3),
.pdf-import-page .pdf-bank-question-table td:nth-child(3) { width: 62%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(4),
.pdf-import-page .pdf-bank-question-table td:nth-child(4) { width: 9%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(5),
.pdf-import-page .pdf-bank-question-table td:nth-child(5) { width: 9%; }

.pdf-import-page .pdf-bank-question-table td {
    overflow-wrap: anywhere;
    vertical-align: top;
}

.pdf-review-bulk-bar {
    display:flex;
    align-items:center;
    gap:10px;
    flex-wrap:wrap;
    margin:12px 0 16px;
}
.pdf-review-bulk-bar button {
    width:auto;
}
.pdf-review-bulk-bar .pdf-review-danger-action {
    display:inline-flex;
    align-items:center;
    justify-content:center;
    width:auto;
    min-width:0;
    min-height:36px;
    padding:8px 13px;
    border-radius:9px;
    white-space:nowrap;
    line-height:1.2;
    color:#ff9ca5 !important;
    background:rgba(96,15,28,.26) !important;
    border:1px solid rgba(255,77,92,.40) !important;
    box-shadow:none !important;
}
.pdf-review-bulk-status {
    margin-left:auto;
    color:#9eb3c8;
    font-size:13px;
}
.pdf-review-select-toggle {
    display:inline-flex;
    align-items:center;
    gap:7px;
    margin-right:12px;
    color:#cbd9e7;
    font-size:13px;
}
.pdf-review-select-toggle input {
    width:auto;
}

@media (max-width: 1180px) {
    .pdf-import-page .pdf-import-upload-form,
    .pdf-import-page .pdf-bank-generator-form {
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    }
    .pdf-import-page .pdf-import-upload-form .build-submit-row,
    .pdf-import-page .pdf-import-upload-form .pdf-import-rights,
    .pdf-import-page .pdf-bank-generator-form .build-submit-row {
        grid-column: 1 / -1;
    }
}

@media (max-width: 760px) {
    .pdf-import-page .pdf-import-upload-form,
    .pdf-import-page .pdf-bank-generator-form {
        grid-template-columns: minmax(0, 1fr);
    }
    .pdf-import-page .pdf-import-upload-form .build-submit-row,
    .pdf-import-page .pdf-import-upload-form .pdf-import-rights,
    .pdf-import-page .pdf-bank-generator-form .build-submit-row {
        grid-column: auto;
    }
    .pdf-import-page .pdf-bank-row {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
</head>
<body class="dashboard-home pdf-import-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar">
<div class="dashboard-brand"><div class="dashboard-brand-mark">▤</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div>
<nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a><a class="dashboard-nav-item active" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a><a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a><a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a><a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a><a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a></nav>
<div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a><a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a><a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a></nav>
<div class="dashboard-sidebar-version">Smart PDF Import</div></aside>
<main class="dashboard-main pdf-import-main">
{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}
<div class="pdf-import-flash-stack">
{% for category, message in messages %}
<div class="flash {{ category }}">{{ message }}</div>
{% endfor %}
</div>
{% endif %}
{% endwith %}
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="build-eyebrow">SMART PDF IMPORT</div><h1>Import Study Content from PDF</h1><p>DLMS can recognize structured question banks or glossary/terminology material, parse the full source, and let you review it before generating manageable quizzes.</p></div></header>
<section class="dashboard-panel pdf-import-intro"><div><span class="build-method-label">SAFE ADDITIVE WORKFLOW</span><h2>Your existing parsers are untouched</h2><p>This is a separate importer. The original text upload, paste parser, CSV matching importer, manual builder, and image builder continue to work exactly as before.</p></div>
<div class="pdf-import-badges"><span>Question banks</span><span>Glossary / terminology</span><span>Automatic detection</span><span>Cross-page content</span><span>Inline repair</span></div></section>
<section class="dashboard-panel">
<form action="/pdf-import/analyze" method="POST" enctype="multipart/form-data" class="pdf-import-upload-form">
<label class="build-field"><span>PDF file</span><input type="file" name="pdf_file" accept=".pdf,application/pdf" required><small>Selectable-text PDFs work best. This preview does not perform OCR.</small></label>
<label class="build-field"><span>Source bank title</span><input type="text" name="quiz_title" placeholder="Example: CISM Glossary or PenTest+ Practice"><small>You can change this again on the review screen.</small></label>
<label class="build-field"><span>Content type</span><select name="pdf_content_type"><option value="auto">Auto-detect</option><option value="question_bank">Question bank</option><option value="glossary">Glossary / terminology</option></select><small>Choose manually if the PDF has an unusual layout.</small></label>
<label class="build-field"><span>Exam timer</span><input type="number" name="exam_minutes" min="1" max="1440" value="90"></label>
<label class="pdf-import-rights"><input type="checkbox" name="rights_ok" required><span>I have permission to use this document for my own study. DLMS will treat the imported material as user-provided and not cleared for redistribution.</span></label>
<div class="build-submit-row"><a class="build-secondary-link" href="/upload">Back to Build Quiz</a><button class="build-primary-button" type="submit">Analyze PDF</button></div>
</form></section>
<section class="dashboard-panel pdf-import-note"><strong>Current Smart PDF scope</strong><p>DLMS handles selectable-text multiple-choice question banks and glossary/terminology layouts. Ambiguous records are flagged for review instead of being guessed. OCR and arbitrary textbook/chapter interpretation are intentionally out of scope for this release candidate.</p></section>
{% if banks or term_banks %}
<div class="pdf-bank-toolbar">
<div><strong>Saved PDF source banks</strong><span>Collapse large collections or enable management controls when you need them.</span></div>
<div class="pdf-bank-toolbar-actions">
<button type="button" class="pdf-bank-quiet-button" id="pdfExpandBanks">Expand All</button>
<button type="button" class="pdf-bank-quiet-button" id="pdfCollapseBanks">Collapse All</button>
<button type="button" class="pdf-bank-manage-button" id="pdfManageBanks" aria-pressed="false">Manage Banks</button>
</div>
</div>
{% endif %}

{% if banks %}
<details class="dashboard-panel pdf-bank-list-panel pdf-bank-collapsible" data-pdf-bank-section>
<summary class="pdf-bank-section-summary">
<div class="pdf-bank-section-copy"><span class="build-method-label">SAVED SOURCE BANKS</span><h2>Question Banks</h2><p>Reviewed source questions remain available here. Generate manageable quizzes without re-parsing the PDF.</p></div>
<div class="pdf-bank-section-meta"><span>{{ banks|length }} bank{% if banks|length != 1 %}s{% endif %}</span><span class="pdf-bank-chevron">›</span></div>
</summary>
<div class="pdf-bank-section-body">
<div class="pdf-bank-list">
{% for bank in banks %}
<div class="pdf-bank-row">
<a class="pdf-bank-row-main" href="/pdf-import/bank/{{ bank.id }}">
<div><strong>{{ bank.title }}</strong><small>Question bank · {{ bank.source_name }}</small></div>
<div class="pdf-bank-row-stats"><span>{{ bank.active_count }} active</span><span>{{ bank.used_count }} used</span><span>{{ bank.generated_count }} quizzes</span></div>
<span class="pdf-bank-open">Open →</span>
</a>
<form class="pdf-bank-manage-action" method="POST" action="/pdf-import/bank/{{ bank.id }}/delete" onsubmit="return confirm('Delete source question bank “{{ bank.title|e }}”? Existing quizzes generated from it will remain available.');">
<button class="pdf-bank-delete-button" type="submit">Delete</button>
</form>
</div>
{% endfor %}
</div>
</div>
</details>
{% endif %}

{% if term_banks %}
<details class="dashboard-panel pdf-bank-list-panel pdf-bank-collapsible" data-pdf-bank-section>
<summary class="pdf-bank-section-summary">
<div class="pdf-bank-section-copy"><span class="build-method-label">SAVED TERMINOLOGY</span><h2>Terminology Banks</h2><p>Reviewed glossary terms can generate matching or multiple-choice practice without re-parsing the PDF.</p></div>
<div class="pdf-bank-section-meta"><span>{{ term_banks|length }} bank{% if term_banks|length != 1 %}s{% endif %}</span><span class="pdf-bank-chevron">›</span></div>
</summary>
<div class="pdf-bank-section-body">
<div class="pdf-bank-list">
{% for bank in term_banks %}
<div class="pdf-bank-row">
<a class="pdf-bank-row-main" href="/pdf-import/terms/{{ bank.id }}">
<div><strong>{{ bank.title }}</strong><small>Terminology bank · {{ bank.source_name }}</small></div>
<div class="pdf-bank-row-stats"><span>{{ bank.active_count }} active</span><span>{{ bank.used_count }} used</span><span>{{ bank.generated_count }} quizzes</span></div>
<span class="pdf-bank-open">Open →</span>
</a>
<form class="pdf-bank-manage-action" method="POST" action="/pdf-import/terms/{{ bank.id }}/delete" onsubmit="return confirm('Delete source terminology bank “{{ bank.title|e }}”? Existing quizzes generated from it will remain available.');">
<button class="pdf-bank-delete-button" type="submit">Delete</button>
</form>
</div>
{% endfor %}
</div>
</div>
</details>
{% endif %}
</main></div>
<script>
document.getElementById("menuButton")?.addEventListener("click",()=>document.getElementById("dashboardSidebar")?.classList.toggle("open"));
const pdfBankSections=[...document.querySelectorAll("[data-pdf-bank-section]")];
document.getElementById("pdfExpandBanks")?.addEventListener("click",()=>pdfBankSections.forEach(section=>section.open=true));
document.getElementById("pdfCollapseBanks")?.addEventListener("click",()=>pdfBankSections.forEach(section=>section.open=false));
document.getElementById("pdfManageBanks")?.addEventListener("click",event=>{
    const enabled=document.body.classList.toggle("pdf-bank-manage-mode");
    event.currentTarget.setAttribute("aria-pressed",enabled?"true":"false");
    event.currentTarget.textContent=enabled?"Done Managing":"Manage Banks";
});
</script>
<script src="/static/nav-normalize.js"></script></body></html>
"""
    return render_template_string(template, banks=_list_pdf_question_banks(), term_banks=_list_pdf_terminology_banks())

@app.route("/pdf-import/bank/<bank_id>/delete", methods=["POST"])
def pdf_question_bank_delete(bank_id):
    try:
        title = _delete_pdf_question_bank(bank_id)
        flash(
            f"Deleted source question bank '{title}'. Existing generated quizzes were not deleted.",
            "success",
        )
    except FileNotFoundError:
        flash("PDF question bank was already removed or could not be found.", "error")
    except Exception as exc:
        print(f"[PDF QUESTION BANK DELETE ERROR] {type(exc).__name__}: {exc}")
        flash("Could not delete the PDF question bank.", "error")
    return redirect("/pdf-import")


@app.route("/pdf-import/terms/<bank_id>/delete", methods=["POST"])
def pdf_terminology_bank_delete(bank_id):
    try:
        title = _delete_pdf_terminology_bank(bank_id)
        flash(
            f"Deleted source terminology bank '{title}'. Existing generated quizzes were not deleted.",
            "success",
        )
    except FileNotFoundError:
        flash("PDF terminology bank was already removed or could not be found.", "error")
    except Exception as exc:
        print(f"[PDF TERMINOLOGY BANK DELETE ERROR] {type(exc).__name__}: {exc}")
        flash("Could not delete the PDF terminology bank.", "error")
    return redirect("/pdf-import")


@app.route("/pdf-import/analyze", methods=["POST"])
def pdf_import_analyze():
    upload = request.files.get("pdf_file")
    if not upload or not upload.filename:
        flash("Choose a PDF to analyze.", "error")
        return redirect("/pdf-import")
    if not str(upload.filename).lower().endswith(".pdf"):
        flash("Smart PDF Import currently accepts PDF files only.", "error")
        return redirect("/pdf-import")
    if not request.form.get("rights_ok"):
        flash("Confirm that you have permission to use the document for your own study.", "error")
        return redirect("/pdf-import")
    if request.content_length and request.content_length > PDF_IMPORT_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES:
        flash("PDF exceeds the 64 MB Smart PDF Import limit.", "error")
        return redirect("/pdf-import")

    draft_id = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:20]
    source_name = secure_filename(upload.filename) or "study.pdf"
    temp_pdf = os.path.join(PDF_IMPORT_DRAFT_FOLDER, f"{draft_id}.pdf")
    try:
        os.makedirs(PDF_IMPORT_DRAFT_FOLDER, exist_ok=True)
        _bounded_save_upload(upload, temp_pdf, PDF_IMPORT_MAX_BYTES, "PDF")
        pages = _pdf_extract_pages(temp_pdf)
        pages, removed_margins = _pdf_suppress_repeated_margins(pages)

        requested_type = (request.form.get("pdf_content_type") or "auto").strip().lower()
        question_result = _pdf_parse_question_bank(pages)
        glossary_result = _pdf_parse_glossary(pages)

        if requested_type == "question_bank":
            document_type = "question_bank"
            detection = {"forced": True}
        elif requested_type == "glossary":
            document_type = "glossary"
            detection = {"forced": True}
        else:
            document_type, detection = _pdf_detect_document_type(
                pages, question_result=question_result, glossary_result=glossary_result
            )

        if document_type == "question_bank":
            result = question_result
            if not result.get("questions"):
                result = _pdf_question_recovery_result(pages)
                detection = {**(detection or {}), "recovery_mode": True, "reason": "no_structured_question_records"}
        elif document_type == "glossary":
            result = glossary_result
            if not result.get("terms"):
                result = _pdf_glossary_recovery_result(pages)
                detection = {**(detection or {}), "recovery_mode": True, "reason": "no_structured_glossary_records"}
        else:
            # Auto-detect may still be inconclusive for an unusual layout. Preserve
            # the extracted text in Review & Repair rather than throwing it away.
            answer_markers = sum(1 for p in pages for line in p.get("lines", []) if re.search(r"Correct\s+Answer:", line, re.I))
            choice_lines = sum(1 for p in pages for line in p.get("lines", []) if re.match(r"^[A-Z]\.\s+", line))
            if answer_markers or choice_lines >= 2:
                document_type = "question_bank"
                result = _pdf_question_recovery_result(pages)
                detection = {**(detection or {}), "recovery_mode": True, "reason": "auto_low_confidence_question_like"}
            elif glossary_result.get("terms"):
                document_type = "glossary"
                result = glossary_result
            else:
                document_type = "question_bank"
                result = _pdf_question_recovery_result(pages)
                detection = {**(detection or {}), "recovery_mode": True, "reason": "auto_unstructured_recovery"}

        if document_type == "question_bank":
            result["questions"] = [_pdf_add_question_review_slots(q) for q in (result.get("questions") or [])]
            if not result.get("questions"):
                raise ValueError("No selectable text could be recovered from this PDF. OCR is not enabled.")
        elif document_type == "glossary" and not result.get("terms"):
            raise ValueError("No selectable text could be recovered from this PDF. OCR is not enabled.")

        draft = {
            "id": draft_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_name": source_name,
            "source_kind": "user-provided-pdf",
            "redistribution_status": "not-cleared-for-redistribution",
            "document_type": document_type,
            "detection": detection,
            "quiz_title": (request.form.get("quiz_title") or "").strip() or os.path.splitext(source_name)[0],
            "exam_minutes": normalize_exam_minutes(request.form.get("exam_minutes")),
            "page_count": len(pages),
            "removed_margin_text": removed_margins,
            **result,
        }
        _save_pdf_import_draft(draft)
    except Exception as exc:
        print(f"[PDF ANALYSIS ERROR] {type(exc).__name__}: {exc}")
        flash("PDF analysis failed. The document may be malformed, encrypted, or outside the supported limits.", "error")
        return redirect("/pdf-import")
    finally:
        try:
            os.remove(temp_pdf)
        except OSError:
            pass
    return redirect(f"/pdf-import/review/{draft_id}")

def _render_pdf_glossary_review(draft):
    template = r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Review PDF Terminology - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico">
<style>
.pdf-import-page *, .pdf-import-page *::before, .pdf-import-page *::after { box-sizing:border-box; }
.pdf-import-page .dashboard-main,.pdf-import-page .dashboard-panel,.pdf-import-page .dashboard-header { min-width:0;max-width:100%; }
.pdf-import-page input,.pdf-import-page textarea,.pdf-import-page select { width:100%;max-width:100%;min-width:0; }
.pdf-term-review-list { display:grid;gap:12px; }
.pdf-term-review-card { min-width:0; }
.pdf-term-review-grid { display:grid;grid-template-columns:minmax(180px,.7fr) minmax(0,2fr);gap:12px;align-items:start; }
.pdf-term-review-grid textarea { min-height:96px; }
.pdf-term-page { color:#8299b3;font-size:11px; }
.pdf-review-bulk-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:12px 0 16px;}
.pdf-review-bulk-bar button{width:auto;}
.pdf-review-bulk-bar .pdf-review-danger-action{display:inline-flex;align-items:center;justify-content:center;width:auto;min-width:0;min-height:36px;padding:8px 13px;border-radius:9px;white-space:nowrap;line-height:1.2;color:#ff9ca5!important;background:rgba(96,15,28,.26)!important;border:1px solid rgba(255,77,92,.40)!important;box-shadow:none!important;}
.pdf-review-bulk-status{margin-left:auto;color:#9eb3c8;font-size:13px;}
.pdf-review-select-toggle{display:inline-flex;align-items:center;gap:7px;margin-right:12px;color:#cbd9e7;font-size:13px;}
.pdf-review-select-toggle input{width:auto;}
@media(max-width:760px){.pdf-term-review-grid{grid-template-columns:1fr;}.pdf-review-bulk-status{width:100%;margin-left:0;}}
</style></head>
<body class="dashboard-home pdf-import-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar"><div class="dashboard-brand"><div class="dashboard-brand-mark">▤</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div><nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a><a class="dashboard-nav-item active" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a><a class="dashboard-nav-item" href="/it"><span class="dashboard-nav-icon">⌘</span><span>IT Study</span></a><a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a><a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a><a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a><a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a></nav><div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a><a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a><a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a></nav><div class="dashboard-sidebar-version">Terminology Review</div></aside>
<main class="dashboard-main pdf-import-main">
{% with messages=get_flashed_messages(with_categories=true) %}{% if messages %}<div class="pdf-import-flash-stack">{% for category,message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}</div>{% endif %}{% endwith %}
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="build-eyebrow">SMART PDF IMPORT · TERMINOLOGY</div><h1>Review &amp; Repair</h1><p>{{ draft.source_name }} · {{ draft.page_count }} page{% if draft.page_count != 1 %}s{% endif %}. {% if draft.recovery_mode or draft.detection.recovery_mode %}Automatic parsing confidence was low, so DLMS preserved recoverable text for manual term/definition reconstruction.{% else %}Review every detected term/definition pair before saving the reusable terminology bank.{% endif %}</p></div></header>
<section class="pdf-import-summary-grid"><article class="dashboard-stat-card"><span>Detected</span><strong>{{ draft.summary.detected }}</strong><small>terms</small></article><article class="dashboard-stat-card"><span>Complete</span><strong>{{ draft.summary.complete }}</strong><small>ready</small></article><article class="dashboard-stat-card"><span>Review</span><strong>{{ draft.summary.review }}</strong><small>needs attention</small></article><article class="dashboard-stat-card"><span>Incomplete</span><strong>{{ draft.summary.incomplete }}</strong><small>repair or exclude</small></article></section>
<div class="pdf-import-filter-row"><button type="button" data-filter="all" class="active">All</button><button type="button" data-filter="complete">Complete</button><button type="button" data-filter="review">Needs Review</button><button type="button" data-filter="incomplete">Incomplete</button></div>
<details class="pdf-review-bulk-help">
<summary>How filters and bulk actions work</summary>
<div class="pdf-review-bulk-help-body">
<p>Filters change which terminology cards are visible. <strong>Select All Visible</strong> selects only cards in the current filtered view; selections remain when you switch filters. <strong>Clear Selection</strong> clears selections across every filter.</p>
<p><strong>Exclude Selected</strong> turns on each selected card's Exclude term setting. <strong>Keep Selected</strong> turns it back off. Nothing is committed until you choose <strong>Save Reviewed Terminology Bank</strong>.</p>
</div>
</details>
<div class="dashboard-panel pdf-review-bulk-bar" aria-label="Bulk terminology actions"><div class="pdf-review-bulk-actions"><button type="button" class="build-secondary-link" id="pdfTermSelectAllVisible">Select All Visible</button><button type="button" class="build-secondary-link" id="pdfTermClearSelection">Clear Selection</button><button type="button" class="build-secondary-link" id="pdfTermExcludeSelected">Exclude Selected</button><button type="button" class="build-secondary-link" id="pdfTermKeepSelected">Keep Selected</button></div><span class="pdf-review-bulk-status" id="pdfTermSelectionCount" aria-live="polite">0 selected</span></div>
<form method="POST" action="/pdf-import/save/{{ draft.id }}" id="pdfTermReviewForm"><input type="hidden" name="term_review_payload" id="pdfTermReviewPayload">
<section class="dashboard-panel pdf-import-finalize"><div class="build-two-column-fields"><label class="build-field"><span>Terminology bank title</span><input name="quiz_title" value="{{ draft.quiz_title }}" required></label><label class="build-field"><span>Default exam timer</span><input type="number" name="exam_minutes" min="1" max="1440" value="{{ draft.exam_minutes }}"></label></div><div class="pdf-import-source-note">Source: user-provided PDF · redistribution status: not cleared for redistribution</div></section>
<div class="pdf-term-review-list">
{% for t in draft.terms %}
<article class="dashboard-panel pdf-term-review-card status-{{ t.status }}" data-status="{{ t.status }}" data-term-index="{{ loop.index0 }}" data-term-number="{{ t.number }}">
<div class="pdf-import-question-head"><div><label class="pdf-review-select-toggle"><input type="checkbox" data-term-role="select"><span>Select</span></label><span class="pdf-status {{ t.status }}">{{ t.status|upper }}</span><strong>Term {{ t.number }}</strong><small class="pdf-term-page">PDF page{% if t.pages|length != 1 %}s{% endif %} {{ t.pages|join(", ") }}</small></div><label class="pdf-delete-toggle"><input type="checkbox" data-term-role="exclude"><span>Exclude term</span></label></div>
{% if t.issues %}<div class="pdf-import-issues">{% for issue in t.issues %}<div>⚠ {{ issue }}</div>{% endfor %}</div>{% endif %}
<div class="pdf-term-review-grid"><label class="build-field"><span>Term</span><input data-term-role="term" value="{{ t.term }}"></label><label class="build-field"><span>Definition</span><textarea data-term-role="definition" rows="4">{{ t.definition }}</textarea></label></div>
</article>
{% endfor %}
</div>
<section class="dashboard-panel pdf-import-create-bar"><div><strong>Save the complete reviewed terminology bank.</strong><span>Excluded records are preserved in the source bank but are never used for generated practice.</span></div><div class="build-submit-row"><a class="build-secondary-link" href="/pdf-import">Start Over</a><button class="build-primary-button" type="submit">Save Reviewed Terminology Bank</button></div></section>
</form></main></div>
<script>
document.getElementById("menuButton")?.addEventListener("click",()=>document.getElementById("dashboardSidebar")?.classList.toggle("open"));
const pdfTermCards=[...document.querySelectorAll(".pdf-term-review-card")];
const pdfTermSelectionCount=document.getElementById("pdfTermSelectionCount");
function pdfTermUpdateSelectionCount(){const selected=pdfTermCards.filter(card=>card.querySelector('[data-term-role="select"]')?.checked).length;if(pdfTermSelectionCount)pdfTermSelectionCount.textContent=`${selected} selected`;}
function pdfTermSelectedCards(){return pdfTermCards.filter(card=>card.querySelector('[data-term-role="select"]')?.checked);}
document.querySelectorAll(".pdf-import-filter-row button").forEach(btn=>btn.addEventListener("click",()=>{document.querySelectorAll(".pdf-import-filter-row button").forEach(b=>b.classList.remove("active"));btn.classList.add("active");const f=btn.dataset.filter;pdfTermCards.forEach(card=>card.hidden=f!=="all"&&card.dataset.status!==f)}));
pdfTermCards.forEach(card=>card.querySelector('[data-term-role="select"]')?.addEventListener("change",pdfTermUpdateSelectionCount));
document.getElementById("pdfTermSelectAllVisible")?.addEventListener("click",()=>{pdfTermCards.filter(card=>!card.hidden).forEach(card=>{const box=card.querySelector('[data-term-role="select"]');if(box)box.checked=true;});pdfTermUpdateSelectionCount();});
document.getElementById("pdfTermClearSelection")?.addEventListener("click",()=>{pdfTermCards.forEach(card=>{const box=card.querySelector('[data-term-role="select"]');if(box)box.checked=false;});pdfTermUpdateSelectionCount();});
document.getElementById("pdfTermExcludeSelected")?.addEventListener("click",()=>{const cards=pdfTermSelectedCards();if(!cards.length)return;if(!confirm(`Exclude ${cards.length} selected term(s) from generated practice?`))return;cards.forEach(card=>{const box=card.querySelector('[data-term-role="exclude"]');if(box)box.checked=true;});});
document.getElementById("pdfTermKeepSelected")?.addEventListener("click",()=>{pdfTermSelectedCards().forEach(card=>{const box=card.querySelector('[data-term-role="exclude"]');if(box)box.checked=false;});});
pdfTermUpdateSelectionCount();
document.getElementById("pdfTermReviewForm")?.addEventListener("submit",()=>{const payload=[];pdfTermCards.forEach(card=>payload.push({index:Number(card.dataset.termIndex||0),number:Number(card.dataset.termNumber||0),exclude:!!card.querySelector('[data-term-role="exclude"]')?.checked,term:card.querySelector('[data-term-role="term"]')?.value||"",definition:card.querySelector('[data-term-role="definition"]')?.value||""}));document.getElementById("pdfTermReviewPayload").value=JSON.stringify(payload)});
</script><script src="/static/nav-normalize.js"></script></body></html>
"""
    return render_template_string(template, draft=draft)

@app.route("/pdf-import/review/<draft_id>")
def pdf_import_review(draft_id):
    try:
        draft = _load_pdf_import_draft(draft_id)
    except Exception as exc:
        print(f"[PDF REVIEW LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("The PDF review session is unavailable or expired.", "error")
        return redirect("/pdf-import")

    if draft.get("document_type") == "glossary":
        return _render_pdf_glossary_review(draft)

    template = r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Review PDF Import - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico">
<style>
/* Smart PDF page-local containment. Keeps long text, form controls, and grids inside panels. */
.pdf-import-page *,
.pdf-import-page *::before,
.pdf-import-page *::after { box-sizing: border-box; }

.pdf-import-page .dashboard-main,
.pdf-import-page .dashboard-header,
.pdf-import-page .dashboard-panel,
.pdf-import-page .pdf-import-intro,
.pdf-import-page .pdf-bank-list-panel,
.pdf-import-page .pdf-bank-generator,
.pdf-import-page .pdf-bank-source-panel,
.pdf-import-page .pdf-import-create-bar {
    min-width: 0;
    max-width: 100%;
}

.pdf-import-page .dashboard-header > div,
.pdf-import-page .dashboard-header p,
.pdf-import-page .pdf-bank-panel-heading,
.pdf-import-page .pdf-bank-panel-heading > div,
.pdf-import-page .pdf-bank-row > *,
.pdf-import-page .pdf-bank-mode-help > *,
.pdf-import-page .pdf-import-intro > * {
    min-width: 0;
    overflow-wrap: anywhere;
    word-break: normal;
}

.pdf-import-page .pdf-import-upload-form,
.pdf-import-page .pdf-bank-generator-form {
    min-width: 0;
    width: 100%;
}

.pdf-import-page .pdf-import-upload-form > *,
.pdf-import-page .pdf-bank-generator-form > *,
.pdf-import-page .build-field {
    min-width: 0;
}

.pdf-import-page input[type="text"],
.pdf-import-page input[type="number"],
.pdf-import-page input[type="file"],
.pdf-import-page select,
.pdf-import-page textarea {
    width: 100%;
    max-width: 100%;
    min-width: 0;
}

.pdf-import-page input[type="file"] {
    overflow: hidden;
}

.pdf-import-page .pdf-bank-row {
    min-width: 0;
}

.pdf-import-page .pdf-bank-row > div:first-child strong,
.pdf-import-page .pdf-bank-row > div:first-child small {
    display: block;
    max-width: 100%;
    overflow-wrap: anywhere;
}

.pdf-import-page .pdf-bank-generator-form {
    grid-template-columns: minmax(0, 2fr) minmax(120px, .7fr) minmax(180px, 1fr);
}

.pdf-import-page .pdf-bank-question-table-wrap {
    width: 100%;
    max-width: 100%;
    overflow-x: auto;
}

.pdf-import-page .pdf-bank-question-table {
    width: 100%;
    table-layout: fixed;
}

.pdf-import-page .pdf-bank-question-table th:nth-child(1),
.pdf-import-page .pdf-bank-question-table td:nth-child(1) { width: 6%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(2),
.pdf-import-page .pdf-bank-question-table td:nth-child(2) { width: 14%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(3),
.pdf-import-page .pdf-bank-question-table td:nth-child(3) { width: 62%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(4),
.pdf-import-page .pdf-bank-question-table td:nth-child(4) { width: 9%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(5),
.pdf-import-page .pdf-bank-question-table td:nth-child(5) { width: 9%; }

.pdf-import-page .pdf-bank-question-table td {
    overflow-wrap: anywhere;
    vertical-align: top;
}

@media (max-width: 1180px) {
    .pdf-import-page .pdf-import-upload-form,
    .pdf-import-page .pdf-bank-generator-form {
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    }
    .pdf-import-page .pdf-import-upload-form .build-submit-row,
    .pdf-import-page .pdf-import-upload-form .pdf-import-rights,
    .pdf-import-page .pdf-bank-generator-form .build-submit-row {
        grid-column: 1 / -1;
    }
}

@media (max-width: 760px) {
    .pdf-import-page .pdf-import-upload-form,
    .pdf-import-page .pdf-bank-generator-form {
        grid-template-columns: minmax(0, 1fr);
    }
    .pdf-import-page .pdf-import-upload-form .build-submit-row,
    .pdf-import-page .pdf-import-upload-form .pdf-import-rights,
    .pdf-import-page .pdf-bank-generator-form .build-submit-row {
        grid-column: auto;
    }
    .pdf-import-page .pdf-bank-row {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
</head>
<body class="dashboard-home pdf-import-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar"><div class="dashboard-brand"><div class="dashboard-brand-mark">▤</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div><nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a><a class="dashboard-nav-item active" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a><a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a><a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a><a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a><a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a></nav><div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a><a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a><a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a></nav><div class="dashboard-sidebar-version">PDF Review</div></aside>
<main class="dashboard-main pdf-import-main">
{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}
<div class="pdf-import-flash-stack">
{% for category, message in messages %}
<div class="flash {{ category }}">{{ message }}</div>
{% endfor %}
</div>
{% endif %}
{% endwith %}
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="build-eyebrow">SMART PDF IMPORT · REVIEW</div><h1>Review &amp; Repair</h1><p>{{ draft.source_name }} · {{ draft.page_count }} page{% if draft.page_count != 1 %}s{% endif %}. {% if draft.recovery_mode or draft.detection.recovery_mode %}Automatic parsing confidence was low, so DLMS preserved recoverable text and editable fields for manual reconstruction. Verify each kept record carefully.{% else %}DLMS parsed the full source. Repair anything misread or exclude unusable questions, then save the reusable question bank.{% endif %}</p></div></header>
<section class="pdf-import-summary-grid">
<article class="dashboard-stat-card"><span>Detected</span><strong>{{ draft.summary.detected }}</strong><small>questions</small></article>
<article class="dashboard-stat-card"><span>Complete</span><strong>{{ draft.summary.complete }}</strong><small>ready</small></article>
<article class="dashboard-stat-card"><span>Review</span><strong>{{ draft.summary.review }}</strong><small>needs attention</small></article>
<article class="dashboard-stat-card"><span>Incomplete</span><strong>{{ draft.summary.incomplete }}</strong><small>repair or remove</small></article>
</section>
<div class="pdf-import-filter-row"><button type="button" data-filter="all" class="active">All</button><button type="button" data-filter="complete">Complete</button><button type="button" data-filter="review">Needs Review</button><button type="button" data-filter="incomplete">Incomplete</button></div>
<details class="pdf-review-bulk-help">
<summary>How filters and bulk actions work</summary>
<div class="pdf-review-bulk-help-body">
<p>Filters change which question cards are visible. <strong>Select All Visible</strong> selects only cards in the current filtered view; selections remain when you switch filters. <strong>Clear Selection</strong> clears selections across every filter.</p>
<p><strong>Mark Selected for Deletion</strong> turns on each selected card's Delete question setting. <strong>Keep Selected</strong> turns it back off. Nothing is committed until you choose <strong>Save Reviewed Question Bank</strong>.</p>
</div>
</details>
<div class="dashboard-panel pdf-review-bulk-bar" aria-label="Bulk question actions"><div class="pdf-review-bulk-actions"><button type="button" class="build-secondary-link" id="pdfSelectAllVisible">Select All Visible</button><button type="button" class="build-secondary-link" id="pdfClearSelection">Clear Selection</button><button type="button" class="build-secondary-link pdf-review-danger-action" id="pdfDeleteSelected">Mark Selected for Deletion</button><button type="button" class="build-secondary-link" id="pdfKeepSelected">Keep Selected</button></div><span class="pdf-review-bulk-status" id="pdfSelectionCount" aria-live="polite">0 selected</span></div>
<form method="POST" action="/pdf-import/save/{{ draft.id }}" id="pdfReviewForm">
<input type="hidden" name="review_payload" id="pdfReviewPayload" value="">
<section class="dashboard-panel pdf-import-finalize"><div class="build-two-column-fields"><label class="build-field"><span>Question bank title</span><input name="quiz_title" value="{{ draft.quiz_title }}" required form="pdfReviewForm"></label><label class="build-field"><span>Exam timer</span><input type="number" name="exam_minutes" min="1" max="1440" value="{{ draft.exam_minutes }}" form="pdfReviewForm"></label></div><div class="pdf-import-source-note">Source: user-provided PDF · redistribution status: not cleared for redistribution</div></section>
<div class="pdf-import-question-list">
{% for q in draft.questions %}
<article class="dashboard-panel pdf-import-question-card status-{{ q.status }}" data-status="{{ q.status }}" data-question-index="{{ loop.index0 }}" data-question-number="{{ q.number }}">
<div class="pdf-import-question-head"><div><label class="pdf-review-select-toggle"><input type="checkbox" data-pdf-role="select"><span>Select</span></label><span class="pdf-status {{ q.status }}">{{ q.status|replace("_"," ")|upper }}</span><strong>Question {{ q.number }}</strong><small>PDF page{% if q.pages|length != 1 %}s{% endif %} {{ q.pages|join(", ") }}</small></div><label class="pdf-delete-toggle"><input type="checkbox" name="delete_{{ loop.index0 }}" value="1" form="pdfReviewForm" data-pdf-role="delete"><span>Delete question</span></label></div>
{% if q.issues %}<div class="pdf-import-issues">{% for issue in q.issues %}<div>⚠ {{ issue }}</div>{% endfor %}</div>{% endif %}
<input type="hidden" name="original_number_{{ loop.index0 }}" value="{{ q.number }}" form="pdfReviewForm">
<label class="build-field"><span>Question text</span><textarea name="question_{{ loop.index0 }}" rows="4" form="pdfReviewForm" data-pdf-role="question">{{ q.question }}</textarea></label>
<div class="pdf-import-choice-grid">
{% for choice in q.choices %}
<label class="build-field pdf-choice-field"><span>{{ choice.label }}{% if choice.label == q.correct %} · detected correct{% endif %}</span><input name="choice_{{ loop.index0 }}_{{ choice.label }}" value="{{ choice.text }}" form="pdfReviewForm" data-pdf-role="choice" data-choice-label="{{ choice.label }}"></label>
{% endfor %}
</div>
<div class="build-two-column-fields">
<label class="build-field"><span>Correct answer</span><select name="correct_{{ loop.index0 }}" form="pdfReviewForm" data-pdf-role="correct"><option value="" {% if not q.correct %}selected{% endif %}>Choose a correct answer</option>{% for choice in q.choices %}<option value="{{ choice.label }}" {% if choice.label == q.correct %}selected{% endif %}>{{ choice.label }} — {{ choice.text }}</option>{% endfor %}</select></label>
<label class="build-field"><span>Detected answer text</span><input value="{{ q.declared_answer_text }}" readonly></label>
</div>
<label class="build-field"><span>Study Mode explanation</span><textarea name="explanation_{{ loop.index0 }}" rows="4" form="pdfReviewForm" data-pdf-role="explanation">{{ q.explanation }}</textarea></label>
{% if q.choice_feedback %}<details class="pdf-feedback-details"><summary>Detected incorrect-choice explanations</summary><div class="pdf-feedback-grid">{% for label, text in q.choice_feedback.items() %}<label class="build-field"><span>{{ label }} feedback</span><textarea name="feedback_{{ loop.index0 }}_{{ label }}" rows="2" form="pdfReviewForm" data-pdf-role="feedback" data-choice-label="{{ label }}">{{ text }}</textarea></label>{% endfor %}</div></details>{% endif %}
</article>
{% endfor %}
</div>
<section class="dashboard-panel pdf-import-create-bar"><div><strong>Save the complete reviewed source bank.</strong><span>Questions marked Delete are preserved in the bank as excluded, not used for generated quizzes. You can later generate random, sequential, range-based, or unused-question quizzes of any manageable size.</span></div><div class="build-submit-row"><a class="build-secondary-link" href="/pdf-import">Start Over</a><button class="build-primary-button" type="submit" form="pdfReviewForm">Save Reviewed Question Bank</button></div></section>
</form></main></div>
<script>
document.getElementById("menuButton")?.addEventListener("click",()=>document.getElementById("dashboardSidebar")?.classList.toggle("open"));
const pdfQuestionCards=[...document.querySelectorAll(".pdf-import-question-card")];
const pdfSelectionCount=document.getElementById("pdfSelectionCount");
function pdfUpdateSelectionCount(){
 const selected=pdfQuestionCards.filter(card=>card.querySelector('[data-pdf-role="select"]')?.checked).length;
 if(pdfSelectionCount) pdfSelectionCount.textContent=`${selected} selected`;
}
function pdfSelectedCards(){return pdfQuestionCards.filter(card=>card.querySelector('[data-pdf-role="select"]')?.checked);}
document.querySelectorAll(".pdf-import-filter-row button").forEach(btn=>btn.addEventListener("click",()=>{
 document.querySelectorAll(".pdf-import-filter-row button").forEach(b=>b.classList.remove("active"));btn.classList.add("active");
 const f=btn.dataset.filter;pdfQuestionCards.forEach(card=>card.hidden=f!=="all"&&card.dataset.status!==f);
}));
pdfQuestionCards.forEach(card=>card.querySelector('[data-pdf-role="select"]')?.addEventListener("change",pdfUpdateSelectionCount));
document.getElementById("pdfSelectAllVisible")?.addEventListener("click",()=>{pdfQuestionCards.filter(card=>!card.hidden).forEach(card=>{const box=card.querySelector('[data-pdf-role="select"]');if(box) box.checked=true;});pdfUpdateSelectionCount();});
document.getElementById("pdfClearSelection")?.addEventListener("click",()=>{pdfQuestionCards.forEach(card=>{const box=card.querySelector('[data-pdf-role="select"]');if(box) box.checked=false;});pdfUpdateSelectionCount();});
document.getElementById("pdfDeleteSelected")?.addEventListener("click",()=>{const cards=pdfSelectedCards();if(!cards.length)return;if(!confirm(`Mark ${cards.length} selected question(s) for deletion/exclusion?`))return;cards.forEach(card=>{const box=card.querySelector('[data-pdf-role="delete"]');if(box) box.checked=true;});});
document.getElementById("pdfKeepSelected")?.addEventListener("click",()=>{pdfSelectedCards().forEach(card=>{const box=card.querySelector('[data-pdf-role="delete"]');if(box) box.checked=false;});});
pdfUpdateSelectionCount();
const pdfReviewForm=document.getElementById("pdfReviewForm");
if(pdfReviewForm){
 pdfReviewForm.addEventListener("submit",()=>{
  const payload=[];
  document.querySelectorAll(".pdf-import-question-card").forEach(card=>{
   const choices=[];
   card.querySelectorAll('[data-pdf-role="choice"]').forEach(input=>{
    choices.push({label:input.dataset.choiceLabel||"",text:input.value||""});
   });
   const feedback={};
   card.querySelectorAll('[data-pdf-role="feedback"]').forEach(input=>{
    feedback[input.dataset.choiceLabel||""]=input.value||"";
   });
   payload.push({
    index:Number(card.dataset.questionIndex||0),
    number:Number(card.dataset.questionNumber||0),
    delete:!!card.querySelector('[data-pdf-role="delete"]')?.checked,
    question:card.querySelector('[data-pdf-role="question"]')?.value||"",
    choices,
    correct:card.querySelector('[data-pdf-role="correct"]')?.value||"",
    explanation:card.querySelector('[data-pdf-role="explanation"]')?.value||"",
    feedback
   });
  });
  const hidden=document.getElementById("pdfReviewPayload");
  if(hidden) hidden.value=JSON.stringify(payload);
 });
}
</script><script src="/static/nav-normalize.js"></script></body></html>
"""
    return render_template_string(template, draft=draft)

@app.route("/pdf-import/save/<draft_id>", methods=["POST"])
def pdf_import_save(draft_id):
    try:
        draft = _load_pdf_import_draft(draft_id)
    except Exception as exc:
        print(f"[PDF REVIEW SAVE ERROR] {type(exc).__name__}: {exc}")
        flash("The PDF review session is unavailable or expired.", "error")
        return redirect("/pdf-import")

    if draft.get("document_type") == "glossary":
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
        for idx, original in enumerate(originals):
            submitted = next(
                (x for x in submitted_items if isinstance(x, dict) and int(x.get("index", -1)) == idx),
                None,
            )
            excluded = bool((submitted or {}).get("exclude"))
            term = str((submitted or {}).get("term") if submitted is not None else original.get("term") or "").strip()
            definition = str((submitted or {}).get("definition") if submitted is not None else original.get("definition") or "").strip()
            valid = bool(term and definition)
            if not excluded and not valid:
                flash(
                    f"Term {original.get('number')} needs both a term and definition. Repair it or exclude it.",
                    "error",
                )
                return redirect(f"/pdf-import/review/{draft_id}")
            bank_terms.append({
                "number": idx + 1,
                "term": term,
                "definition": definition,
                "pages": original.get("pages") or [],
                "parser_status": original.get("status") or ("complete" if valid else "incomplete"),
                "parser_issues": original.get("issues") or [],
                "active": not excluded and valid,
            })

        if not bank_terms:
            flash("No terminology records were available to save.", "error")
            return redirect(f"/pdf-import/review/{draft_id}")

        bank_id = "pdfterms_" + secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:14]
        bank = {
            "schema_version": 1,
            "id": bank_id,
            "kind": "terminology",
            "title": bank_title,
            "source_name": draft.get("source_name") or "PDF import",
            "source_kind": "user-provided-pdf",
            "redistribution_status": "not-cleared-for-redistribution",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "default_exam_minutes": normalize_exam_minutes(request.form.get("exam_minutes")),
            "page_count": draft.get("page_count") or 0,
            "terms": bank_terms,
            "used_term_numbers": [],
            "generated_quizzes": [],
        }
        _save_pdf_terminology_bank(bank)
        try:
            os.remove(_pdf_import_draft_path(draft_id))
        except OSError:
            pass

        active_count = len(_pdf_term_bank_active_terms(bank))
        excluded_count = len(bank_terms) - active_count
        flash(
            f"Saved terminology bank '{bank_title}' with {active_count} active term(s)"
            + (f" and {excluded_count} excluded source record(s)." if excluded_count else "."),
            "success",
        )
        return redirect(f"/pdf-import/terms/{bank_id}")

    bank_title = (request.form.get("quiz_title") or "").strip()
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))
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

    for idx, original in enumerate(originals):
        submitted = None
        if submitted_items is not None:
            submitted = next(
                (item for item in submitted_items
                 if isinstance(item, dict) and int(item.get("index", -1)) == idx),
                None,
            )

        excluded = False
        if submitted is not None:
            excluded = bool(submitted.get("delete"))
            question = str(submitted.get("question") or "").strip()
            choices = []
            for raw_choice in submitted.get("choices") or []:
                if not isinstance(raw_choice, dict):
                    continue
                label = str(raw_choice.get("label") or "").strip().upper()
                text = str(raw_choice.get("text") or "").strip()
                if label and text:
                    choices.append({"label": label, "text": text})
            correct = str(submitted.get("correct") or "").strip().upper()
            explanation = str(submitted.get("explanation") or "").strip()
            feedback = submitted.get("feedback") if isinstance(submitted.get("feedback"), dict) else {}
        else:
            excluded = bool(request.form.get(f"delete_{idx}"))
            question = (request.form.get(f"question_{idx}") or original.get("question") or "").strip()
            choices = []
            for choice in original.get("choices") or []:
                label = str(choice.get("label") or "").strip().upper()
                text = (request.form.get(f"choice_{idx}_{label}") or choice.get("text") or "").strip()
                if label and text:
                    choices.append({"label": label, "text": text})
            correct = (request.form.get(f"correct_{idx}") or original.get("correct") or "").strip().upper()
            explanation = (request.form.get(f"explanation_{idx}") or original.get("explanation") or "").strip()
            feedback = original.get("choice_feedback") if isinstance(original.get("choice_feedback"), dict) else {}

        labels = {c["label"] for c in choices}
        valid = bool(question and len(choices) >= 2 and correct in labels)

        # An active question must be structurally complete. Excluded questions are
        # preserved exactly so the user never loses parsed source material.
        if not excluded and not valid:
            missing = []
            if not question:
                missing.append("question text")
            if len(choices) < 2:
                missing.append(f"answer choices ({len(choices)} detected/submitted)")
            if not correct:
                missing.append("correct answer")
            elif correct not in labels:
                missing.append(f"correct answer {correct} does not match submitted choices")
            flash(
                f"Question {original.get('number')} cannot be active in the bank: "
                f"{', '.join(missing)}. Repair it or mark it for deletion/exclusion.",
                "error",
            )
            return redirect(f"/pdf-import/review/{draft_id}")

        feedback_parts = []
        for c in choices:
            fb = str((feedback or {}).get(c["label"]) or "").strip()
            if fb:
                feedback_parts.append(f"{c['label']}: {fb}")
        stored_explanation = explanation
        if feedback_parts:
            stored_explanation = (
                f"{stored_explanation}\n\nOther option notes: " + " | ".join(feedback_parts)
            ).strip()

        bank_questions.append({
            "number": idx + 1,
            "original_number": int(original.get("number") or idx + 1),
            "question": question,
            "choices": choices,
            "correct": correct,
            "explanation": stored_explanation,
            "choice_feedback": feedback or {},
            "pages": original.get("pages") or [],
            "parser_status": original.get("status") or ("complete" if valid else "incomplete"),
            "parser_issues": original.get("issues") or [],
            "active": not excluded and valid,
        })

    if not bank_questions:
        flash("No parsed questions were available to save.", "error")
        return redirect(f"/pdf-import/review/{draft_id}")

    bank_id = "pdfbank_" + secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:14]
    bank = {
        "schema_version": 1,
        "id": bank_id,
        "title": bank_title,
        "source_name": draft.get("source_name") or "PDF import",
        "source_kind": "user-provided-pdf",
        "redistribution_status": "not-cleared-for-redistribution",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "default_exam_minutes": exam_minutes,
        "page_count": draft.get("page_count") or 0,
        "questions": bank_questions,
        "used_question_numbers": [],
        "generated_quizzes": [],
    }
    _save_pdf_question_bank(bank)

    try:
        os.remove(_pdf_import_draft_path(draft_id))
    except OSError:
        pass

    active_count = len(_pdf_bank_active_questions(bank))
    excluded_count = len(bank_questions) - active_count
    flash(
        f"Saved question bank '{bank_title}' with {active_count} active question(s)"
        + (f" and {excluded_count} excluded source question(s)." if excluded_count else "."),
        "success",
    )
    return redirect(f"/pdf-import/bank/{bank_id}")


@app.route("/pdf-import/banks")
def pdf_question_banks_page():
    return redirect("/pdf-import")


@app.route("/pdf-import/bank/<bank_id>")
def pdf_question_bank_page(bank_id):
    try:
        bank = _load_pdf_question_bank(bank_id)
    except Exception as exc:
        print(f"[PDF QUESTION BANK LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("The selected PDF question bank could not be loaded.", "error")
        return redirect("/pdf-import")

    questions = bank.get("questions") or []
    active = _pdf_bank_active_questions(bank)
    excluded = [q for q in questions if isinstance(q, dict) and not q.get("active", True)]
    used = {int(n) for n in (bank.get("used_question_numbers") or []) if str(n).isdigit()}
    max_number = max(
        [int(q.get("original_number") or q.get("number") or 0) for q in questions if isinstance(q, dict)] or [1]
    )
    default_count = min(50, len(active)) if active else 1

    template = r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PDF Question Bank - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico">
<style>
/* Smart PDF page-local containment. Keeps long text, form controls, and grids inside panels. */
.pdf-import-page *,
.pdf-import-page *::before,
.pdf-import-page *::after { box-sizing: border-box; }

.pdf-import-page .dashboard-main,
.pdf-import-page .dashboard-header,
.pdf-import-page .dashboard-panel,
.pdf-import-page .pdf-import-intro,
.pdf-import-page .pdf-bank-list-panel,
.pdf-import-page .pdf-bank-generator,
.pdf-import-page .pdf-bank-source-panel,
.pdf-import-page .pdf-import-create-bar {
    min-width: 0;
    max-width: 100%;
}

.pdf-import-page .dashboard-header > div,
.pdf-import-page .dashboard-header p,
.pdf-import-page .pdf-bank-panel-heading,
.pdf-import-page .pdf-bank-panel-heading > div,
.pdf-import-page .pdf-bank-row > *,
.pdf-import-page .pdf-bank-mode-help > *,
.pdf-import-page .pdf-import-intro > * {
    min-width: 0;
    overflow-wrap: anywhere;
    word-break: normal;
}

.pdf-import-page .pdf-import-upload-form,
.pdf-import-page .pdf-bank-generator-form {
    min-width: 0;
    width: 100%;
}

.pdf-import-page .pdf-import-upload-form > *,
.pdf-import-page .pdf-bank-generator-form > *,
.pdf-import-page .build-field {
    min-width: 0;
}

.pdf-import-page input[type="text"],
.pdf-import-page input[type="number"],
.pdf-import-page input[type="file"],
.pdf-import-page select,
.pdf-import-page textarea {
    width: 100%;
    max-width: 100%;
    min-width: 0;
}

.pdf-import-page input[type="file"] {
    overflow: hidden;
}

.pdf-import-page .pdf-bank-row {
    min-width: 0;
}

.pdf-import-page .pdf-bank-row > div:first-child strong,
.pdf-import-page .pdf-bank-row > div:first-child small {
    display: block;
    max-width: 100%;
    overflow-wrap: anywhere;
}

.pdf-import-page .pdf-bank-generator-form {
    grid-template-columns: minmax(0, 2fr) minmax(120px, .7fr) minmax(180px, 1fr);
}

.pdf-import-page .pdf-bank-question-table-wrap {
    width: 100%;
    max-width: 100%;
    overflow-x: auto;
}

.pdf-import-page .pdf-bank-question-table {
    width: 100%;
    table-layout: fixed;
}

.pdf-import-page .pdf-bank-question-table th:nth-child(1),
.pdf-import-page .pdf-bank-question-table td:nth-child(1) { width: 6%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(2),
.pdf-import-page .pdf-bank-question-table td:nth-child(2) { width: 14%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(3),
.pdf-import-page .pdf-bank-question-table td:nth-child(3) { width: 62%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(4),
.pdf-import-page .pdf-bank-question-table td:nth-child(4) { width: 9%; }
.pdf-import-page .pdf-bank-question-table th:nth-child(5),
.pdf-import-page .pdf-bank-question-table td:nth-child(5) { width: 9%; }

.pdf-import-page .pdf-bank-question-table td {
    overflow-wrap: anywhere;
    vertical-align: top;
}

@media (max-width: 1180px) {
    .pdf-import-page .pdf-import-upload-form,
    .pdf-import-page .pdf-bank-generator-form {
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    }
    .pdf-import-page .pdf-import-upload-form .build-submit-row,
    .pdf-import-page .pdf-import-upload-form .pdf-import-rights,
    .pdf-import-page .pdf-bank-generator-form .build-submit-row {
        grid-column: 1 / -1;
    }
}

@media (max-width: 760px) {
    .pdf-import-page .pdf-import-upload-form,
    .pdf-import-page .pdf-bank-generator-form {
        grid-template-columns: minmax(0, 1fr);
    }
    .pdf-import-page .pdf-import-upload-form .build-submit-row,
    .pdf-import-page .pdf-import-upload-form .pdf-import-rights,
    .pdf-import-page .pdf-bank-generator-form .build-submit-row {
        grid-column: auto;
    }
    .pdf-import-page .pdf-bank-row {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
</head>
<body class="dashboard-home pdf-import-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar"><div class="dashboard-brand"><div class="dashboard-brand-mark">▤</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div><nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a><a class="dashboard-nav-item active" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a><a class="dashboard-nav-item" href="/it"><span class="dashboard-nav-icon">⌘</span><span>IT Study</span></a><a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a><a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a><a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a><a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a></nav><div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a><a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a><a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a></nav><div class="dashboard-sidebar-version">PDF Question Bank</div></aside>
<main class="dashboard-main pdf-import-main">
{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}<div class="pdf-import-flash-stack">{% for category,message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}</div>{% endif %}{% endwith %}
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="build-eyebrow">PDF QUESTION BANK</div><h1>{{ bank.title }}</h1><p>{{ bank.source_name }} · All parsed source questions are retained. Generate as many manageable quizzes as you want without re-importing the PDF.</p></div></header>
<section class="pdf-import-summary-grid">
<article class="dashboard-stat-card"><span>Parsed</span><strong>{{ questions|length }}</strong><small>source questions</small></article>
<article class="dashboard-stat-card"><span>Active</span><strong>{{ active|length }}</strong><small>available</small></article>
<article class="dashboard-stat-card"><span>Used</span><strong>{{ used|length }}</strong><small>unique questions</small></article>
<article class="dashboard-stat-card"><span>Generated</span><strong>{{ bank.generated_quizzes|length }}</strong><small>quizzes</small></article>
</section>

<section class="dashboard-panel pdf-bank-generator">
<div class="pdf-bank-panel-heading"><div><span class="build-method-label">GENERATE PRACTICE</span><h2>Create Quiz from Question Bank</h2><p>The bank stays intact. Only the selected questions are copied into the generated quiz.</p></div></div>
<form method="POST" action="/pdf-import/bank/{{ bank.id }}/generate" class="pdf-bank-generator-form">
<label class="build-field"><span>Quiz title</span><input type="text" name="quiz_title" value="{{ bank.title }} — Practice" required></label>
<label class="build-field"><span>Question count</span><input type="number" name="question_count" min="1" max="{{ active|length }}" value="{{ default_count }}" required></label>
<label class="build-field"><span>Selection</span><select name="selection_mode" id="pdfBankSelection">
<option value="random">Random questions</option>
<option value="unused">Random unused questions</option>
<option value="sequential">Sequential from question number</option>
<option value="range">Specific question range</option>
<option value="all">All active questions</option>
</select></label>
<label class="build-field pdf-bank-start"><span>Start question #</span><input type="number" name="start_number" min="1" max="{{ max_number }}" value="1"></label>
<label class="build-field pdf-bank-end"><span>End question #</span><input type="number" name="end_number" min="1" max="{{ max_number }}" value="{{ [50,max_number]|min }}"></label>
<label class="build-field"><span>Exam timer</span><input type="number" name="exam_minutes" min="1" max="1440" value="{{ bank.default_exam_minutes or 90 }}"></label>
<div class="build-submit-row"><a class="build-secondary-link" href="/pdf-import">All PDF Banks</a><button class="build-primary-button" type="submit">Create Quiz</button></div>
</form>
<div class="pdf-bank-mode-help">
<strong>Selection behavior</strong>
<span><b>Random:</b> any active questions.</span>
<span><b>Unused:</b> only questions never used by this bank before.</span>
<span><b>Sequential:</b> starts at the question number you choose and takes the requested count.</span>
<span><b>Range:</b> includes all active source questions in the selected number range.</span>
</div>
</section>

<section class="dashboard-panel pdf-bank-source-panel">
<div class="pdf-bank-panel-heading"><div><span class="build-method-label">SOURCE INVENTORY</span><h2>Parsed Questions</h2><p>{{ active|length }} active · {{ excluded|length }} excluded but preserved</p></div></div>
<div class="pdf-bank-question-table-wrap"><table class="study-dataset-table pdf-bank-question-table"><thead><tr><th>#</th><th>Status</th><th>Question</th><th>Used</th><th>Page</th></tr></thead><tbody>
{% for q in questions %}
<tr class="{% if not q.active %}pdf-bank-excluded-row{% endif %}">
<td>{{ q.original_number }}</td>
<td>{% if q.active %}<span class="pdf-status complete">ACTIVE</span>{% else %}<span class="pdf-status incomplete">EXCLUDED</span>{% endif %}</td>
<td>{{ q.question or "(source question incomplete)" }}</td>
<td>{% if q.original_number in used %}Yes{% else %}No{% endif %}</td>
<td>{{ q.pages|join(", ") }}</td>
</tr>
{% endfor %}
</tbody></table></div>
</section>
</main></div>
<script>
document.getElementById("menuButton")?.addEventListener("click",()=>document.getElementById("dashboardSidebar")?.classList.toggle("open"));
</script><script src="/static/nav-normalize.js"></script></body></html>
"""
    return render_template_string(
        template, bank=bank, questions=questions, active=active, excluded=excluded,
        used=used, default_count=default_count, max_number=max_number
    )


@app.route("/pdf-import/bank/<bank_id>/generate", methods=["POST"])
def pdf_question_bank_generate(bank_id):
    try:
        bank = _load_pdf_question_bank(bank_id)
        quiz_title = (request.form.get("quiz_title") or "").strip()
        if not quiz_title:
            raise ValueError("Quiz title is required.")
        exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))
        mode = (request.form.get("selection_mode") or "random").strip().lower()
        selected = _select_pdf_bank_questions(
            bank,
            mode=mode,
            count=request.form.get("question_count") or 50,
            start_number=request.form.get("start_number") or 1,
            end_number=request.form.get("end_number"),
        )

        quiz_data = [
            _pdf_bank_question_to_quiz(q, i, bank)
            for i, q in enumerate(selected, 1)
        ]
        quiz_id, _ = _publish_quiz(
            quiz_title,
            quiz_data,
            filename_prefix="pdf_bank",
            exam_minutes=exam_minutes,
        )

        try:
            selected_numbers = [
                int(q.get("original_number") or q.get("number") or 0)
                for q in selected
            ]
            used = {int(n) for n in (bank.get("used_question_numbers") or []) if str(n).isdigit()}
            used.update(n for n in selected_numbers if n)
            bank["used_question_numbers"] = sorted(used)
            bank.setdefault("generated_quizzes", []).append({
                "quiz_id": quiz_id,
                "title": quiz_title,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "selection_mode": mode,
                "question_count": len(selected),
                "question_numbers": selected_numbers,
            })
            _save_pdf_question_bank(bank)
        except Exception as exc:
            print(f"[PDF QUIZ ACCOUNTING ERROR] Published quiz {quiz_id}: {type(exc).__name__}: {exc}")
            flash("Quiz created, but source-bank usage tracking could not be updated.", "warning")

        flash(
            f"Created '{quiz_title}' with {len(selected)} question(s) from '{bank.get('title')}'. "
            f"The source bank remains intact.",
            "success",
        )
        return redirect(f"/edit_quiz/{quiz_id}")
    except Exception as exc:
        print(f"[PDF QUIZ GENERATION ERROR] {type(exc).__name__}: {exc}")
        flash("Could not generate a quiz from the selected PDF question bank.", "error")
        return redirect(f"/pdf-import/bank/{bank_id}")


@app.route("/pdf-import/terms")
def pdf_terminology_banks_page():
    return redirect("/pdf-import")


@app.route("/pdf-import/terms/<bank_id>")
def pdf_terminology_bank_page(bank_id):
    try:
        bank = _load_pdf_terminology_bank(bank_id)
    except Exception as exc:
        print(f"[PDF TERMINOLOGY BANK LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("The selected PDF terminology bank could not be loaded.", "error")
        return redirect("/pdf-import")

    terms = bank.get("terms") or []
    active = _pdf_term_bank_active_terms(bank)
    excluded = [t for t in terms if isinstance(t, dict) and not t.get("active", True)]
    used = {int(n) for n in (bank.get("used_term_numbers") or []) if str(n).isdigit()}
    max_number = max([int(t.get("number") or 0) for t in terms if isinstance(t, dict)] or [1])
    default_count = min(25, len(active)) if active else 1

    template = r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PDF Terminology Bank - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico">
<style>
.pdf-import-page *, .pdf-import-page *::before, .pdf-import-page *::after { box-sizing:border-box; }
.pdf-import-page .dashboard-main,.pdf-import-page .dashboard-panel,.pdf-import-page .dashboard-header { min-width:0;max-width:100%; }
.pdf-import-page input,.pdf-import-page textarea,.pdf-import-page select{width:100%;max-width:100%;min-width:0;}
.pdf-term-generator-form{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(120px,.55fr) minmax(190px,.9fr);gap:12px;align-items:end;margin-top:16px;}
.pdf-term-generator-form .build-submit-row{grid-column:1/-1;}
.pdf-term-table-wrap{overflow-x:auto;width:100%;}
.pdf-term-table{width:100%;table-layout:fixed;}
.pdf-term-table th:nth-child(1),.pdf-term-table td:nth-child(1){width:6%}.pdf-term-table th:nth-child(2),.pdf-term-table td:nth-child(2){width:13%}.pdf-term-table th:nth-child(3),.pdf-term-table td:nth-child(3){width:23%}.pdf-term-table th:nth-child(4),.pdf-term-table td:nth-child(4){width:46%}.pdf-term-table th:nth-child(5),.pdf-term-table td:nth-child(5){width:6%}.pdf-term-table th:nth-child(6),.pdf-term-table td:nth-child(6){width:6%}
.pdf-term-table td{vertical-align:top;overflow-wrap:anywhere}.pdf-bank-excluded-row{opacity:.58}
@media(max-width:1050px){.pdf-term-generator-form{grid-template-columns:1fr 1fr}.pdf-term-generator-form .build-submit-row{grid-column:1/-1}}
@media(max-width:700px){.pdf-term-generator-form{grid-template-columns:1fr}.pdf-term-generator-form .build-submit-row{grid-column:auto}}
</style></head>
<body class="dashboard-home pdf-import-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar"><div class="dashboard-brand"><div class="dashboard-brand-mark">▤</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div><nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a><a class="dashboard-nav-item active" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a><a class="dashboard-nav-item" href="/it"><span class="dashboard-nav-icon">⌘</span><span>IT Study</span></a><a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a><a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a><a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a><a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a></nav><div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a><a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a><a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a></nav><div class="dashboard-sidebar-version">PDF Terminology Bank</div></aside>
<main class="dashboard-main pdf-import-main">
{% with messages=get_flashed_messages(with_categories=true) %}{% if messages %}<div class="pdf-import-flash-stack">{% for category,message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}</div>{% endif %}{% endwith %}
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button><div><div class="build-eyebrow">PDF TERMINOLOGY BANK</div><h1>{{ bank.title }}</h1><p>{{ bank.source_name }} · The reviewed glossary stays intact while DLMS generates matching or multiple-choice practice from selected terms.</p></div></header>
<section class="pdf-import-summary-grid"><article class="dashboard-stat-card"><span>Parsed</span><strong>{{ terms|length }}</strong><small>source terms</small></article><article class="dashboard-stat-card"><span>Active</span><strong>{{ active|length }}</strong><small>available</small></article><article class="dashboard-stat-card"><span>Used</span><strong>{{ used|length }}</strong><small>unique terms</small></article><article class="dashboard-stat-card"><span>Generated</span><strong>{{ bank.generated_quizzes|length }}</strong><small>quizzes</small></article></section>
<section class="dashboard-panel pdf-bank-generator"><div class="pdf-bank-panel-heading"><div><span class="build-method-label">GENERATE PRACTICE</span><h2>Create Practice from Terminology Bank</h2><p>Choose a manageable set. The source bank remains unchanged.</p></div></div>
<form method="POST" action="/pdf-import/terms/{{ bank.id }}/generate" class="pdf-term-generator-form">
<label class="build-field"><span>Quiz title</span><input name="quiz_title" value="{{ bank.title }} — Practice" required></label>
<label class="build-field"><span>Term count</span><input type="number" name="term_count" min="2" max="{{ active|length }}" value="{{ default_count }}" required></label>
<label class="build-field"><span>Practice type</span><select name="practice_type"><option value="matching">Matching</option><option value="multiple_choice">Multiple choice</option></select></label>
<label class="build-field"><span>Selection</span><select name="selection_mode"><option value="random">Random terms</option><option value="unused">Random unused terms</option><option value="sequential">Sequential from term number</option><option value="range">Specific term range</option><option value="all">All active terms</option></select></label>
<label class="build-field"><span>Direction</span><select name="direction"><option value="random">Random each attempt (matching)</option><option value="term_to_definition">Term → Definition</option><option value="definition_to_term">Definition → Term</option></select></label>
<label class="build-field"><span>Exam timer</span><input type="number" name="exam_minutes" min="1" max="1440" value="{{ bank.default_exam_minutes or 90 }}"></label>
<label class="build-field"><span>Start term #</span><input type="number" name="start_number" min="1" max="{{ max_number }}" value="1"></label>
<label class="build-field"><span>End term #</span><input type="number" name="end_number" min="1" max="{{ max_number }}" value="{{ [25,max_number]|min }}"></label>
<div class="build-submit-row"><a class="build-secondary-link" href="/pdf-import">All PDF Banks</a><button class="build-primary-button" type="submit">Create Practice Quiz</button></div>
</form></section>
<section class="dashboard-panel pdf-bank-source-panel"><div class="pdf-bank-panel-heading"><div><span class="build-method-label">SOURCE INVENTORY</span><h2>Parsed Terminology</h2><p>{{ active|length }} active · {{ excluded|length }} excluded but preserved</p></div></div>
<div class="pdf-term-table-wrap"><table class="study-dataset-table pdf-term-table"><thead><tr><th>#</th><th>Status</th><th>Term</th><th>Definition</th><th>Used</th><th>Page</th></tr></thead><tbody>
{% for t in terms %}<tr class="{% if not t.active %}pdf-bank-excluded-row{% endif %}"><td>{{ t.number }}</td><td>{% if t.active %}<span class="pdf-status complete">ACTIVE</span>{% else %}<span class="pdf-status incomplete">EXCLUDED</span>{% endif %}</td><td><strong>{{ t.term }}</strong></td><td>{{ t.definition }}</td><td>{% if t.number in used %}Yes{% else %}No{% endif %}</td><td>{{ t.pages|join(", ") }}</td></tr>{% endfor %}
</tbody></table></div></section>
</main></div><script>document.getElementById("menuButton")?.addEventListener("click",()=>document.getElementById("dashboardSidebar")?.classList.toggle("open"));</script><script src="/static/nav-normalize.js"></script></body></html>
"""
    return render_template_string(template, bank=bank, terms=terms, active=active, excluded=excluded, used=used, max_number=max_number, default_count=default_count)


@app.route("/pdf-import/terms/<bank_id>/generate", methods=["POST"])
def pdf_terminology_bank_generate(bank_id):
    try:
        bank = _load_pdf_terminology_bank(bank_id)
        quiz_title = (request.form.get("quiz_title") or "").strip()
        if not quiz_title:
            raise ValueError("Quiz title is required.")
        exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))
        mode = (request.form.get("selection_mode") or "random").strip().lower()
        practice_type = (request.form.get("practice_type") or "matching").strip().lower()
        direction = (request.form.get("direction") or "random").strip().lower()

        selected = _select_pdf_term_bank_items(
            bank,
            mode=mode,
            count=request.form.get("term_count") or 25,
            start_number=request.form.get("start_number") or 1,
            end_number=request.form.get("end_number"),
        )

        if practice_type == "multiple_choice":
            mc_direction = direction if direction in {"term_to_definition", "definition_to_term"} else "definition_to_term"
            runtime, db_questions = _pdf_terms_mc_questions(bank, selected, mc_direction)
        else:
            runtime, db_questions = _pdf_terms_matching_questions(bank, selected, direction)

        quiz_id, _ = _create_quiz_from_runtime(
            quiz_title,
            runtime,
            db_questions,
            filename_prefix="pdf_terms",
            exam_minutes=exam_minutes,
        )

        try:
            selected_numbers = [int(t.get("number") or 0) for t in selected]
            used = {int(n) for n in (bank.get("used_term_numbers") or []) if str(n).isdigit()}
            used.update(n for n in selected_numbers if n)
            bank["used_term_numbers"] = sorted(used)
            bank.setdefault("generated_quizzes", []).append({
                "quiz_id": quiz_id,
                "title": quiz_title,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "practice_type": practice_type,
                "selection_mode": mode,
                "direction": direction,
                "term_count": len(selected),
                "term_numbers": selected_numbers,
            })
            _save_pdf_terminology_bank(bank)
        except Exception as exc:
            print(f"[PDF TERMINOLOGY ACCOUNTING ERROR] Published quiz {quiz_id}: {type(exc).__name__}: {exc}")
            flash("Practice quiz created, but source-bank usage tracking could not be updated.", "warning")

        flash(
            f"Created '{quiz_title}' from {len(selected)} terminology item(s). The source bank remains intact.",
            "success",
        )
        return redirect(f"/edit_quiz/{quiz_id}")
    except Exception as exc:
        print(f"[PDF TERMINOLOGY GENERATION ERROR] {type(exc).__name__}: {exc}")
        flash("Could not generate practice from the selected terminology bank.", "error")
        return redirect(f"/pdf-import/terms/{bank_id}")


@app.route("/upload")
def upload_page():
    portal_title = get_portal_title()

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Build Quiz</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home build-modern-page">
<div class="dashboard-shell">

    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>
        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item active" href="/upload" aria-current="page"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>
        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>
        <button class="dashboard-shutdown" id="shutdownBtn" type="button"><span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span></button>
        <div class="dashboard-sidebar-version">Build Quiz</div>
    </aside>
    <main class="dashboard-main build-modern-main">
        <header class="dashboard-header build-page-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="build-eyebrow">QUIZ BUILDER</div>
                <h1>Create a New Quiz</h1>
                <p>Choose the workflow that fits the source material you already have.</p>
            </div>
        </header>

        <section class="build-method-grid" aria-label="Quiz creation methods">
            <article class="build-method-card build-method-primary">
                <div class="build-method-icon" aria-hidden="true">⇧</div>
                <div class="build-method-copy">
                    <span class="build-method-label">UPLOAD FILE</span>
                    <h2>Build from a text file</h2>
                    <p>Upload a properly formatted .txt file and optionally attach a quiz logo.</p>
                </div>
                <form class="build-upload-form" action="/process" method="POST" enctype="multipart/form-data">
                    <label class="build-field">
                        <span>Quiz Display Title</span>
                        <input type="text" name="quiz_title" placeholder="Example: Cloud+ Networking Practice" required>
                    </label>
                    <label class="build-field">
                        <span>Quiz Text File</span>
                        <input type="file" name="file" accept=".txt" required>
                        <small>Use a properly formatted .txt question file.</small>
                    </label>
                    <label class="build-field">
                        <span>Quiz Logo <em>Optional</em></span>
                        <input type="file" name="quiz_logo" accept="image/*">
                        <small>PNG, JPG, GIF, or WEBP.</small>
                    </label>
                    <label class="build-field">
                        <span>Exam Mode Timer <em>Optional</em></span>
                        <input type="number" name="exam_minutes" min="1" max="1440" value="90" inputmode="numeric">
                        <small>Minutes available in Exam Mode. Leave blank or use 90 for the standard DLMS timer.</small>
                    </label>
                    <button class="build-primary-button" type="submit">Upload &amp; Build Quiz</button>
                </form>
            </article>

            <div class="build-alternate-stack">
                <a class="build-option-card" href="/paste">
                    <div class="build-option-icon" aria-hidden="true">▤</div>
                    <div>
                        <span class="build-method-label">PASTE TEXT</span>
                        <h2>Paste questions</h2>
                        <p>Paste a full question set, preview parsing, then create the quiz.</p>
                    </div>
                    <span class="build-option-arrow" aria-hidden="true">›</span>
                </a>
                <a class="build-option-card build-option-card-pdf" href="/pdf-import">
                    <div class="build-option-icon" aria-hidden="true">PDF</div>
                    <div>
                        <span class="build-method-label">SMART PDF IMPORT</span>
                        <h2>Import PDF study content</h2>
                        <p>Parse question banks or glossary/terminology PDFs, review the extracted source, and manage reusable PDF source banks.</p>
                    </div>
                    <span class="build-option-arrow" aria-hidden="true">›</span>
                </a>
                <a class="build-option-card" href="/create_short_quiz">
                    <div class="build-option-icon" aria-hidden="true">✎</div>
                    <div>
                        <span class="build-method-label">MANUAL ENTRY</span>
                        <h2>Create a short quiz</h2>
                        <p>Enter questions and answers manually with guided fields.</p>
                    </div>
                    <span class="build-option-arrow" aria-hidden="true">›</span>
                </a>
                <a class="build-option-card" href="/matching_bank_import">
                    <div class="build-option-icon" aria-hidden="true">⇄</div>
                    <div>
                        <span class="build-method-label">MATCHING BANK</span>
                        <h2>Import matching pairs</h2>
                        <p>Load a CSV terminology bank, choose round size and direction, and retain source metadata.</p>
                    </div>
                    <span class="build-option-arrow" aria-hidden="true">›</span>
                </a>
                <a class="build-option-card build-option-card-image" href="/study-packs/image-builder">
                    <div class="build-option-icon" aria-hidden="true">▧</div>
                    <div><span class="build-method-label">IMAGE STUDY</span><h2>Build from image(s)</h2><p>Use images as-is for normal questions, or add clickable regions when you want hotspot practice.</p></div>
                    <span class="build-option-arrow" aria-hidden="true">›</span>
                </a>
                <div class="build-tip-card">
                    <strong>Not sure which to use?</strong>
                    <span>Paste Text is best for copied exam material. Manual Entry is best for a smaller custom set.</span>
                </div>
            </div>
        </section>
    </main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");
if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}
const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("SHUTDOWN DLMS\\n\\nThis will stop the application.\\n\\nYou will need to restart it manually.\\n\\nContinue?")) return;
        try {
            await fetch("/api/shutdown", { method: "POST" });
            document.body.innerHTML = '<div class="shutdown-screen"><div class="shutdown-screen-card"><h1>DLMS has been shut down.</h1><p>You can close this browser tab.</p></div></div>';
        } catch (err) {
            alert("DLMS may already be shutting down.");
        }
    });
}
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
    """, portal_title=portal_title)


# =========================
# PASTE QUIZ PAGE
# =========================
@app.route("/paste")
def paste_page():
    portal_title = get_portal_title()
    cfg = load_portal_config()

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paste Quiz Questions</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home build-modern-page">
<div class="dashboard-shell">

    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>
        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item active" href="/upload" aria-current="page"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>
        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>
        <button class="dashboard-shutdown" id="shutdownBtn" type="button"><span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span></button>
        <div class="dashboard-sidebar-version">Build Quiz</div>
    </aside>
    <main class="dashboard-main build-modern-main">
        <header class="dashboard-header build-page-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="build-eyebrow">PASTE QUESTIONS</div>
                <h1>Create from Pasted Text</h1>
                <p>Paste the source, optionally clean it up, then preview before the quiz is created.</p>
            </div>
        </header>

        <form class="build-workspace" action="/preview_paste" method="POST" enctype="multipart/form-data">
            <section class="dashboard-panel build-section">
                <div class="build-section-heading">
                    <div class="build-step-number">1</div>
                    <div><h2>Quiz Basics</h2><p>Name the quiz and paste your questions.</p></div>
                </div>
                <label class="build-field">
                    <span>Quiz Display Title</span>
                    <input type="text" name="quiz_title" placeholder="Example: Linux+ Practice Set" required>
                </label>
                <label class="build-field">
                    <span>Exam Mode Timer <em>Optional</em></span>
                    <input type="number" name="exam_minutes" min="1" max="1440" value="90" inputmode="numeric">
                    <small>Minutes available in Exam Mode. Leave blank or use 90 for the standard DLMS timer.</small>
                </label>
                <label class="build-field">
                    <span>Questions + Answers</span>
                    <textarea class="build-source-textarea" name="quiz_text" required placeholder="Paste your formatted questions here..."></textarea>
                </label>
                <div class="build-format-note">
                    <strong>Required answer format</strong>
                    <p>Each question needs a final line such as <code>Suggested Answer: B</code> or <code>Correct Answer: D</code>. A bare letter or <code>Answer: B</code> is not detected.</p>
                </div>
            </section>

            <section class="dashboard-panel build-section">
                <div class="build-section-heading">
                    <div class="build-step-number">2</div>
                    <div><h2>Clean Up Source Text</h2><p>Optional tools that run before parsing.</p></div>
                </div>
                <label class="build-field">
                    <span>Remove Unwanted Lines <em>Optional</em></span>
                    <textarea name="strip_text" class="build-small-textarea" placeholder="Topic
Exam Version
Practice Only"></textarea>
                    <small>One value per line, case-insensitive. Any matching line will be removed.</small>
                </label>

                {% if cfg.enable_regex_replace %}
                <div class="build-advanced-block">
                    <div class="build-advanced-heading">
                        <div>
                            <span class="build-method-label">ADVANCED PARSING</span>
                            <h3>Regex Replace Rules</h3>
                        </div>
                        <a class="build-help-link" href="/static/regex-help.html" target="_blank" rel="noopener">Regex Help ↗</a>
                    </div>
                    <label class="build-field">
                        <span>Manual Rules <em>Optional</em></span>
                        <textarea name="replace_rules" class="build-small-textarea" placeholder="^\\d+\\.\\s* => 
Question\\s*#\\d+ => "></textarea>
                        <small>Format: REGEX =&gt; REPLACEMENT. Rules run before parsing.</small>
                    </label>
                    <div class="build-preset-list">
                        <label><input type="checkbox" name="preset_number_prefix" value="1"><span><strong>Remove numbered prefixes</strong><small>Removes leading values such as 1., 22., or 5.</small></span></label>
                        <label><input type="checkbox" name="preset_pdf_spacing" value="1"><span><strong>Fix PDF / Microsoft wrapping</strong><small>Attempts to repair broken line wrapping and hyphenation.</small></span></label>
                        <label><input type="checkbox" name="preset_headers" value="1"><span><strong>Remove page headers / footers</strong><small>Attempts to strip repeating header and footer text.</small></span></label>
                    </div>
                </div>
                {% endif %}
            </section>

            <section class="dashboard-panel build-section">
                <div class="build-section-heading">
                    <div class="build-step-number">3</div>
                    <div><h2>Logo &amp; Preview</h2><p>Add an optional logo, then inspect the parsed result before committing.</p></div>
                </div>
                <label class="build-field">
                    <span>Quiz Logo <em>Optional</em></span>
                    <input type="file" name="quiz_logo" accept="image/*">
                    <small>PNG, JPG, GIF, or WEBP.</small>
                </label>
                <div class="build-submit-row">
                    <a class="build-secondary-link" href="/upload">Back to Build Options</a>
                    <button class="build-primary-button" type="submit">Preview &amp; Continue</button>
                </div>
            </section>
        </form>
    </main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");
if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}
const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("SHUTDOWN DLMS\\n\\nThis will stop the application.\\n\\nYou will need to restart it manually.\\n\\nContinue?")) return;
        try {
            await fetch("/api/shutdown", { method: "POST" });
            document.body.innerHTML = '<div class="shutdown-screen"><div class="shutdown-screen-card"><h1>DLMS has been shut down.</h1><p>You can close this browser tab.</p></div></div>';
        } catch (err) {
            alert("DLMS may already be shutting down.");
        }
    });
}
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
    """, portal_title=portal_title, cfg=cfg)


# =========================
# CREATE SHORT QUIZ PAGE
# =========================
# =========================
# MATCHING BANK - CSV IMPORT
# =========================
@app.route("/matching_bank_import", methods=["GET", "POST"])
def matching_bank_import():
    if request.method == "POST":
        quiz_title = request.form.get("quiz_title", "").strip()
        question_text = request.form.get("question_text", "Match each term with its correct definition.").strip()
        direction = request.form.get("direction", "term_to_definition").strip()
        if direction not in {"term_to_definition", "definition_to_term", "random"}:
            direction = "term_to_definition"
        raw_round_size = request.form.get("round_size", "10").strip()
        try:
            round_size = max(2, min(int(raw_round_size), 100))
        except (TypeError, ValueError):
            round_size = 10

        source = {
            "organization": request.form.get("source_organization", "").strip(),
            "dataset": request.form.get("source_dataset", "").strip(),
            "version": request.form.get("source_version", "").strip(),
            "url": request.form.get("source_url", "").strip(),
            "license": request.form.get("source_license", "").strip(),
        }
        upload = request.files.get("csv_file")
        if not quiz_title or not upload or not upload.filename:
            flash("Quiz title and CSV file are required.", "error")
            return redirect("/matching_bank_import")
        try:
            text = _read_bounded_upload(upload, MATCHING_CSV_UPLOAD_MAX_BYTES, "Matching CSV").decode("utf-8-sig")
        except UploadTooLargeError as exc:
            flash(str(exc), "error")
            return redirect("/matching_bank_import")
        except UnicodeDecodeError:
            flash("CSV must be UTF-8 encoded.", "error")
            return redirect("/matching_bank_import")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            flash("CSV is missing a header row.", "error")
            return redirect("/matching_bank_import")
        normalized = {name.strip().lower(): name for name in reader.fieldnames if name}
        term_col = normalized.get("term") or normalized.get("left")
        def_col = normalized.get("definition") or normalized.get("right") or normalized.get("match")
        if not term_col or not def_col:
            flash("CSV must contain term + definition columns (left + right are also accepted).", "error")
            return redirect("/matching_bank_import")
        pairs = []
        for row in reader:
            left = (row.get(term_col) or "").strip()
            right = (row.get(def_col) or "").strip()
            if not left or not right:
                continue
            pairs.append({"left": left, "right": right})
        matching_errors = _matching_record_validation_errors(
            pairs,
            context="matching CSV import",
            left_key="left",
            right_key="right",
            record_name="row",
        )
        if matching_errors:
            flash("; ".join(matching_errors), "error")
            return redirect("/matching_bank_import")
        for warning in _matching_case_only_term_warnings(
            pairs,
            context="matching CSV import",
            left_key="left",
            record_name="row",
        ):
            flash(warning, "warning")
        round_size = min(round_size, len(pairs))
        quiz_data = [{
            "number": 1,
            "type": "matching",
            "question": question_text or "Match each term with its correct definition.",
            "pairs": pairs,
            "round_size": round_size,
            "direction": direction,
            "source": source,
        }]
        quiz_id, _ = _publish_quiz(
            quiz_title,
            quiz_data,
            filename_prefix="matching_bank",
            exam_minutes=90,
        )
        flash(f"Matching bank imported: {len(pairs)} pairs; {round_size} shown per attempt.", "success")
        return redirect(f"/edit_quiz/{quiz_id}")

    return render_template_string("""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Import Matching Bank - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home build-modern-page">
<div class="dashboard-shell">

    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>

        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item active" href="/upload" aria-current="page"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>

        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>

        <button class="dashboard-shutdown" id="shutdownBtn" type="button">
            <span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span>
        </button>
        <div class="dashboard-sidebar-version">Build Quiz</div>
    </aside>

    <main class="dashboard-main build-modern-main">
        <header class="dashboard-header build-page-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="build-eyebrow">BUILD QUIZ</div>
                <h1>Import Matching Bank</h1>
                <p>Import a CSV bank without manually entering each pair.</p>
            </div>
        </header>
{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category,message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}{% endif %}{% endwith %}
<form class="build-workspace" method="POST" enctype="multipart/form-data"><section class="dashboard-panel build-section"><div class="build-section-heading"><div class="build-step-number">1</div><div><h2>Matching Bank</h2><p>Required CSV headers: <strong>term,definition</strong>. The aliases <strong>left,right</strong> also work.</p></div></div>
<div class="build-two-column-fields"><label class="build-field"><span>Quiz Title</span><input type="text" name="quiz_title" required placeholder="Medical Terminology — Foundations"></label><label class="build-field"><span>CSV File</span><input type="file" name="csv_file" accept=".csv,text/csv" required></label><label class="build-field"><span>Pairs Per Round</span><input type="number" name="round_size" min="2" max="100" value="10"></label><label class="build-field"><span>Direction</span><select name="direction"><option value="term_to_definition">Term → Definition</option><option value="definition_to_term">Definition → Term</option><option value="random">Random Each Attempt</option></select></label></div>
<label class="build-field"><span>Instructions</span><input type="text" name="question_text" value="Match each term with its correct definition."></label></section>
<details class="dashboard-panel build-section build-optional-source">
<summary><span class="build-optional-source-title">Optional Source Metadata</span><span class="build-optional-source-hint">For third-party or distributable banks</span></summary>
<div class="build-optional-source-body">
<p class="build-optional-source-copy">Most personal CSV imports can leave this section blank. Use it when you want the quiz to retain attribution, version, licensing, or source information.</p>
<div class="build-two-column-fields"><label class="build-field"><span>Source Organization</span><input type="text" name="source_organization" placeholder="Organization or author"></label><label class="build-field"><span>Dataset / Work</span><input type="text" name="source_dataset" placeholder="Dataset, book, course, or collection"></label><label class="build-field"><span>Version</span><input type="text" name="source_version" placeholder="Version or publication year"></label><label class="build-field"><span>License / Terms</span><input type="text" name="source_license" placeholder="License or reuse terms"></label></div><label class="build-field"><span>Source URL</span><input type="url" name="source_url" placeholder="https://..."></label>
</div>
</details>
<div class="build-submit-row"><a class="build-secondary-link" href="/upload">Back to Build Options</a><button class="build-primary-button" type="submit">Import Matching Bank</button></div>
</form>
</main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");
if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}

const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("SHUTDOWN DLMS\\n\\nThis will stop the application.\\n\\nYou will need to restart it manually.\\n\\nContinue?")) return;
        try {
            await fetch("/api/shutdown", { method: "POST" });
            document.body.innerHTML = '<div class="shutdown-screen"><div class="shutdown-screen-card"><h1>DLMS has been shut down.</h1><p>You can close this browser tab.</p></div></div>';
        } catch (err) {
            alert("DLMS may already be shutting down.");
        }
    });
}
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
    """)

@app.route("/create_short_quiz")
def create_short_quiz_page():
    portal_title = get_portal_title()

    # Two-stage manual builder:
    # 1) Ask how many question blocks to start with.
    # 2) Render exactly that many blocks. Users can still add/delete afterward.
    raw_count = request.args.get("count")
    builder_ready = raw_count is not None

    if builder_ready:
        try:
            starting_question_count = int(str(raw_count).strip())
        except (TypeError, ValueError):
            starting_question_count = 10

        # Keep the initial render reasonable while preserving the existing
        # dynamic Add/Delete Question controls once the builder is open.
        starting_question_count = max(1, min(starting_question_count, 100))
    else:
        starting_question_count = 10

    questions = []
    if builder_ready:
        for qnum in range(1, starting_question_count + 1):
            questions.append({
                "number": qnum,
                "choices": ["A", "B", "C", "D"]
            })

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Create Short Quiz</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home build-modern-page">
<div class="dashboard-shell">

    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>
        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item active" href="/upload" aria-current="page"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>
        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>
        <button class="dashboard-shutdown" id="shutdownBtn" type="button"><span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span></button>
        <div class="dashboard-sidebar-version">Build Quiz</div>
    </aside>
    <main class="dashboard-main build-modern-main">
        <header class="dashboard-header build-page-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="build-eyebrow">MANUAL QUIZ BUILDER</div>
                <h1>Create a Short Quiz</h1>
                <p>Build a custom quiz question by question. Add or remove questions and choices as needed.</p>
            </div>
        </header>

        {% if not builder_ready %}
        <section class="dashboard-panel build-section build-short-basics">
            <div class="build-section-heading">
                <div class="build-step-number">1</div>
                <div>
                    <h2>Choose Starting Question Count</h2>
                    <p>Start with only the number of question blocks you need. You can add or delete questions at any time in the builder.</p>
                </div>
            </div>

            <form method="GET" action="/create_short_quiz" class="build-workspace">
                <label class="build-field" style="max-width:340px;">
                    <span>How many questions would you like to start with?</span>
                    <input type="number"
                           name="count"
                           min="1"
                           max="100"
                           value="10"
                           inputmode="numeric"
                           required>
                    <small>Choose 1–100. The default is 10.</small>
                </label>

                <div class="build-submit-row" style="margin-top:18px;">
                    <a class="build-secondary-link" href="/upload">Back to Build Options</a>
                    <button class="build-primary-button" type="submit">Start Quiz Builder</button>
                </div>
            </form>
        </section>
        {% else %}

        <form id="create-short-quiz-form" class="build-workspace" method="POST" action="/create_short_quiz" enctype="multipart/form-data">
            <section class="dashboard-panel build-section build-short-basics">
                <div class="build-section-heading">
                    <div class="build-step-number">1</div>
                    <div><h2>Quiz Basics</h2><p>Give the quiz a title and optional logo.</p></div>
                </div>
                <div class="build-two-column-fields">
                    <label class="build-field">
                        <span>Quiz Display Title</span>
                        <input type="text" name="quiz_title" placeholder="Example: Quick Practice Quiz" required>
                    </label>
                    <label class="build-field">
                        <span>Quiz Logo <em>Optional</em></span>
                        <input type="file" name="quiz_logo" accept="image/*">
                        <small>PNG, JPG, GIF, or WEBP.</small>
                    </label>
                    <label class="build-field">
                        <span>Exam Mode Timer <em>Optional</em></span>
                        <input type="number" name="exam_minutes" min="1" max="1440" value="90" inputmode="numeric">
                        <small>Minutes available in Exam Mode. Leave blank or use 90 for the standard DLMS timer.</small>
                    </label>
                </div>
            </section>

            <section class="build-question-section">
                <div class="build-section-heading build-question-section-heading">
                    <div class="build-step-number">2</div>
                    <div><h2>Questions &amp; Answers</h2><p>Mark every answer that should be accepted as correct.</p></div>
                </div>
                <div id="questions-container" class="build-question-list">
                    {% for q in questions %}
                    <article class="build-question-card question-block" data-question-number="{{ q.number }}">
                        <div class="build-question-heading-row">
                            <h3 class="question-heading">Question {{ q.number }}</h3>
                            <button type="button" class="build-icon-danger btn-delete" onclick="deleteQuestion(this)" title="Delete question" aria-label="Delete question">×</button>
                        </div>
                        <div class="build-two-column-fields">
                            <label class="build-field">
                                <span>Question Type</span>
                                <select class="question-type" name="question_type_{{ q.number }}" onchange="changeQuestionType(this)">
                                    <option value="choice">Multiple Choice / Multi-Select</option>
                                    <option value="matching">Matching</option>
                                </select>
                            </label>
                        </div>
                        <label class="build-field">
                            <span>Question Text / Instructions</span>
                            <textarea class="question-text" name="question_{{ q.number }}" placeholder="Enter question text here..."></textarea>
                        </label>
                        <div class="choice-editor">
                            <div class="build-choice-heading"><span>Answer Choices</span><small>Select Correct for every valid answer.</small></div>
                            <ul class="choices-list build-choice-list">
                            {% for label in q.choices %}
                                <li>
                                    <b class="choice-label">{{ label }}.</b>
                                    <input type="text" class="choice-text" name="choice_{{ q.number }}_{{ label }}" placeholder="Option {{ label }}">
                                    <label class="build-correct-toggle"><input type="checkbox" class="choice-correct" name="correct_{{ q.number }}_{{ label }}"><span>Correct</span></label>
                                    <button type="button" class="build-choice-delete btn-delete" onclick="deleteChoice(this)" title="Delete choice" aria-label="Delete choice">×</button>
                                </li>
                            {% endfor %}
                            </ul>
                            <button class="build-add-choice" type="button" onclick="addChoice(this)">＋ Add Choice</button>
                        </div>
                        <div class="matching-editor" hidden>
                            <div class="build-choice-heading"><span>Matching Pairs</span><small>Each left item must have one matching right item. Answers are shuffled during play.</small></div>
                            <div class="build-two-column-fields matching-settings-grid">
                                <label class="build-field"><span>Pairs Per Round</span><input type="number" class="matching-round-size" min="2" max="100" placeholder="All pairs"><small>Leave blank to show every pair.</small></label>
                                <label class="build-field"><span>Direction</span><select class="matching-direction"><option value="term_to_definition">Term → Definition</option><option value="definition_to_term">Definition → Term</option><option value="random">Random Each Attempt</option></select></label>
                            </div>
                            <div class="matching-pairs-list">
                                <div class="build-match-pair"><span class="match-number">1</span><input type="text" class="match-left" placeholder="Term / prompt"><span class="match-arrow">↔</span><input type="text" class="match-right" placeholder="Definition / match"><button type="button" class="build-choice-delete btn-delete" onclick="deleteMatchPair(this)" aria-label="Delete pair">×</button></div>
                                <div class="build-match-pair"><span class="match-number">2</span><input type="text" class="match-left" placeholder="Term / prompt"><span class="match-arrow">↔</span><input type="text" class="match-right" placeholder="Definition / match"><button type="button" class="build-choice-delete btn-delete" onclick="deleteMatchPair(this)" aria-label="Delete pair">×</button></div>
                                <div class="build-match-pair"><span class="match-number">3</span><input type="text" class="match-left" placeholder="Term / prompt"><span class="match-arrow">↔</span><input type="text" class="match-right" placeholder="Definition / match"><button type="button" class="build-choice-delete btn-delete" onclick="deleteMatchPair(this)" aria-label="Delete pair">×</button></div>
                                <div class="build-match-pair"><span class="match-number">4</span><input type="text" class="match-left" placeholder="Term / prompt"><span class="match-arrow">↔</span><input type="text" class="match-right" placeholder="Definition / match"><button type="button" class="build-choice-delete btn-delete" onclick="deleteMatchPair(this)" aria-label="Delete pair">×</button></div>
                            </div>
                            <button class="build-add-choice" type="button" onclick="addMatchPair(this)">＋ Add Pair</button>
                        </div>
                    </article>
                    {% endfor %}
                </div>
                <button class="build-add-question" type="button" onclick="addQuestion()">＋ Add New Question</button>
            </section>

            <section class="dashboard-panel build-finalize-bar">
                <div><strong>Ready to create?</strong><span>DLMS will validate the questions and save the new quiz to the library.</span></div>
                <div class="build-submit-row">
                    <a class="build-secondary-link" href="/upload">Back to Build Options</a>
                    <button class="build-primary-button" type="submit">Create Quiz</button>
                </div>
            </section>
        </form>
        {% endif %}
    </main>
</div>
<script>

function getChoiceLabel(index) {
    return String.fromCharCode(65 + index);
}

function renumberMatchPairs(question, qNumber) {
    const pairs = question.querySelectorAll(".build-match-pair");
    pairs.forEach((pair, pIndex) => {
        pair.querySelector(".match-number").textContent = pIndex + 1;
        const left = pair.querySelector(".match-left");
        const right = pair.querySelector(".match-right");
        left.name = `match_left_${qNumber}_${pIndex + 1}`;
        right.name = `match_right_${qNumber}_${pIndex + 1}`;
    });
}

function changeQuestionType(select) {
    const question = select.closest(".question-block");
    const isMatching = select.value === "matching";
    question.querySelector(".choice-editor").hidden = isMatching;
    question.querySelector(".matching-editor").hidden = !isMatching;
    renumberQuestions();
}

function addMatchPair(button) {
    const question = button.closest(".question-block");
    const list = question.querySelector(".matching-pairs-list");
    const row = document.createElement("div");
    row.className = "build-match-pair";
    row.innerHTML = `<span class="match-number"></span><input type="text" class="match-left" placeholder="Term / prompt"><span class="match-arrow">↔</span><input type="text" class="match-right" placeholder="Definition / match"><button type="button" class="build-choice-delete btn-delete" onclick="deleteMatchPair(this)" aria-label="Delete pair">×</button>`;
    list.appendChild(row);
    renumberQuestions();
}

function deleteMatchPair(button) {
    const question = button.closest(".question-block");
    if (question.querySelectorAll(".build-match-pair").length <= 2) {
        alert("A matching question needs at least two pairs.");
        return;
    }
    button.closest(".build-match-pair").remove();
    renumberQuestions();
}

function renumberQuestions() {
    const questions = document.querySelectorAll(".question-block");

    questions.forEach((question, qIndex) => {
        const qNumber = qIndex + 1;
        question.dataset.questionNumber = qNumber;

        question.querySelector(".question-heading").textContent = `Question ${qNumber}`;

        const questionType = question.querySelector(".question-type");
        questionType.name = `question_type_${qNumber}`;
        const roundSize = question.querySelector(".matching-round-size");
        const direction = question.querySelector(".matching-direction");
        if (roundSize) roundSize.name = `matching_round_size_${qNumber}`;
        if (direction) direction.name = `matching_direction_${qNumber}`;

        const questionText = question.querySelector(".question-text");
        const savedQuestionText = questionText.value;
        questionText.name = `question_${qNumber}`;
        questionText.value = savedQuestionText;

        renumberMatchPairs(question, qNumber);

        const choices = question.querySelectorAll(".choices-list li");

        choices.forEach((choice, cIndex) => {
            const label = getChoiceLabel(cIndex);

            choice.querySelector(".choice-label").textContent = `${label}.`;

            const choiceText = choice.querySelector(".choice-text");
            const savedChoiceText = choiceText.value;
            choiceText.name = `choice_${qNumber}_${label}`;
            choiceText.placeholder = `Option ${label}`;
            choiceText.value = savedChoiceText;

            const correctBox = choice.querySelector(".choice-correct");
            const savedChecked = correctBox.checked;
            correctBox.name = `correct_${qNumber}_${label}`;
            correctBox.checked = savedChecked;
        });
    });
}

function addQuestion() {
    const container = document.getElementById("questions-container");
    const template = document.querySelector(".question-block");
    const block = template.cloneNode(true);

    block.querySelectorAll("input[type='text'], textarea").forEach(el => el.value = "");
    block.querySelectorAll("input[type='checkbox']").forEach(el => el.checked = false);
    const typeSelect = block.querySelector(".question-type");
    typeSelect.value = "choice";
    block.querySelector(".choice-editor").hidden = false;
    block.querySelector(".matching-editor").hidden = true;

    container.appendChild(block);
    renumberQuestions();
}

function deleteQuestion(button) {
    const questions = document.querySelectorAll(".question-block");

    if (questions.length <= 1) {
        alert("A quiz must have at least one question.");
        return;
    }

    if (!confirm("Delete this question?")) return;

    button.closest(".question-block").remove();
    renumberQuestions();
}

function addChoice(button) {
    const question = button.closest(".question-block");
    const choicesList = question.querySelector(".choices-list");
    const choiceCount = choicesList.querySelectorAll("li").length;

    if (choiceCount >= 26) {
        alert("Maximum answer choices reached.");
        return;
    }

    const label = getChoiceLabel(choiceCount);

    const li = document.createElement("li");
    
    li.innerHTML = `
        <b class="choice-label">${label}.</b>

        <input type="text"
               class="choice-text"
               placeholder="Option ${label}"
               >

        <input type="checkbox"
               class="choice-correct">
        Correct

        <button type="button"
                class="btn-delete"
                onclick="deleteChoice(this)"
                >
            ❌
        </button>
    `;

    choicesList.appendChild(li);
    renumberQuestions();
}

function deleteChoice(button) {
    const question = button.closest(".question-block");
    const choices = question.querySelectorAll(".choices-list li");

    if (choices.length <= 1) {
        alert("A question must have at least one answer choice.");
        return;
    }

    button.closest("li").remove();
    renumberQuestions();
}

const shortQuizForm = document.getElementById("create-short-quiz-form");
if (shortQuizForm) {
shortQuizForm.addEventListener("submit", function(e) {
    renumberQuestions();

    const questions = document.querySelectorAll(".question-block");

    for (let i = 0; i < questions.length; i++) {
        const questionText = questions[i].querySelector(".question-text").value.trim();
        const questionType = questions[i].querySelector(".question-type").value;

        if (!questionText) {
            e.preventDefault();
            alert(`Question ${i + 1} needs question text.`);
            questions[i].scrollIntoView({ behavior: "smooth", block: "center" });
            return;
        }

        if (questionType === "matching") {
            const pairRows = Array.from(questions[i].querySelectorAll(".build-match-pair"));
            const completed = pairRows.filter(row => row.querySelector(".match-left").value.trim() && row.querySelector(".match-right").value.trim());
            const partial = pairRows.find(row => Boolean(row.querySelector(".match-left").value.trim()) !== Boolean(row.querySelector(".match-right").value.trim()));
            if (partial || completed.length < 2) {
                e.preventDefault();
                alert(`Question ${i + 1} needs at least two complete matching pairs.`);
                questions[i].scrollIntoView({ behavior: "smooth", block: "center" });
                return;
            }
            continue;
        }

        const choiceRows = questions[i].querySelectorAll(".choices-list li");
        const checked = questions[i].querySelectorAll(".choice-correct:checked");
        let hasChoiceText = false;
        choiceRows.forEach(row => { if (row.querySelector(".choice-text").value.trim()) hasChoiceText = true; });
        if (!hasChoiceText) {
            e.preventDefault();
            alert(`Question ${i + 1} needs at least one answer choice.`);
            questions[i].scrollIntoView({ behavior: "smooth", block: "center" });
            return;
        }
        if (checked.length === 0) {
            e.preventDefault();
            alert(`Question ${i + 1} must have at least one correct answer selected.`);
            questions[i].scrollIntoView({ behavior: "smooth", block: "center" });
            return;
        }
        for (const box of checked) {
            const choiceRow = box.closest("li");
            if (!choiceRow.querySelector(".choice-text").value.trim()) {
                e.preventDefault();
                alert(`Question ${i + 1} has a correct answer selected, but that answer choice is blank.`);
                choiceRow.scrollIntoView({ behavior: "smooth", block: "center" });
                return;
            }
        }
    }
});
}

</script>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");
if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}
const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("SHUTDOWN DLMS\\n\\nThis will stop the application.\\n\\nYou will need to restart it manually.\\n\\nContinue?")) return;
        try {
            await fetch("/api/shutdown", { method: "POST" });
            document.body.innerHTML = '<div class="shutdown-screen"><div class="shutdown-screen-card"><h1>DLMS has been shut down.</h1><p>You can close this browser tab.</p></div></div>';
        } catch (err) {
            alert("DLMS may already be shutting down.");
        }
    });
}
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
    """,
        portal_title=portal_title,
        questions=questions,
        builder_ready=builder_ready,
        starting_question_count=starting_question_count
    )


# =========================
# CREATE SHORT QUIZ - SAVE
# =========================
@app.route("/create_short_quiz", methods=["POST"])
def save_short_quiz():
    quiz_title = request.form.get("quiz_title", "").strip()
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))

    if not quiz_title:
        flash("Quiz title is required.", "error")
        return redirect("/create_short_quiz")

    quiz_data = []

    # Dynamically detect all submitted questions
    question_numbers = sorted(
        int(key.replace("question_", ""))
        for key in request.form.keys()
        if key.startswith("question_")
        and key.replace("question_", "").isdigit()
    )

    for qnum in question_numbers:
        question_text = request.form.get(f"question_{qnum}", "").strip()
        question_type = request.form.get(f"question_type_{qnum}", "choice").strip().lower()

        if not question_text:
            continue

        if question_type == "matching":
            pairs = []
            pair_prefix = f"match_left_{qnum}_"
            pair_indexes = sorted(
                int(key.replace(pair_prefix, ""))
                for key in request.form.keys()
                if key.startswith(pair_prefix) and key.replace(pair_prefix, "").isdigit()
            )

            for pair_index in pair_indexes:
                left = request.form.get(f"match_left_{qnum}_{pair_index}", "").strip()
                right = request.form.get(f"match_right_{qnum}_{pair_index}", "").strip()
                if not left and not right:
                    continue
                if not left or not right:
                    flash(f"Question {qnum} has an incomplete matching pair.", "error")
                    return redirect("/create_short_quiz")
                pairs.append({"left": left, "right": right})

            if len(pairs) < 2:
                flash(f"Question {qnum} needs at least two matching pairs.", "error")
                return redirect("/create_short_quiz")

            matching_errors = _matching_record_validation_errors(
                pairs,
                context=f"manual matching question {qnum}",
                left_key="left",
                right_key="right",
                record_name="pair",
            )
            if matching_errors:
                flash("; ".join(matching_errors), "error")
                return redirect("/create_short_quiz")
            for warning in _matching_case_only_term_warnings(
                pairs,
                context=f"manual matching question {qnum}",
                left_key="left",
                record_name="pair",
            ):
                flash(warning, "warning")

            raw_round_size = request.form.get(f"matching_round_size_{qnum}", "").strip()
            try:
                round_size = int(raw_round_size) if raw_round_size else None
            except ValueError:
                round_size = None
            if round_size is not None:
                round_size = max(2, min(round_size, len(pairs)))
            direction = request.form.get(f"matching_direction_{qnum}", "term_to_definition").strip()
            if direction not in {"term_to_definition", "definition_to_term", "random"}:
                direction = "term_to_definition"
            quiz_data.append({
                "number": len(quiz_data) + 1,
                "type": "matching",
                "question": question_text,
                "pairs": pairs,
                "round_size": round_size,
                "direction": direction
            })
            continue

        choices = []
        correct_letters = []
        choice_prefix = f"choice_{qnum}_"
        choice_labels = sorted(
            [key.replace(choice_prefix, "") for key in request.form.keys() if key.startswith(choice_prefix)],
            key=lambda label: ord(label[0]) if label else 999
        )

        for label in choice_labels:
            choice_text = request.form.get(f"choice_{qnum}_{label}", "").strip()
            is_correct = bool(request.form.get(f"correct_{qnum}_{label}"))
            if not choice_text:
                continue
            if is_correct:
                correct_letters.append(label)
            choices.append({"label": label, "text": choice_text, "is_correct": is_correct})

        if not choices:
            flash(f"Question {qnum} must have at least one answer choice.", "error")
            return redirect("/create_short_quiz")
        if not correct_letters:
            flash(f"Question {qnum} must have at least one correct answer.", "error")
            return redirect("/create_short_quiz")

        quiz_data.append({
            "number": len(quiz_data) + 1,
            "type": "choice",
            "question": question_text,
            "choices": choices,
            "correct": correct_letters
        })

    if not quiz_data:
        flash("You must enter at least one question.", "error")
        return redirect("/create_short_quiz")

    ts = int(time.time())

    quiz_logo = request.files.get("quiz_logo")

    logo_filename = finalize_logo_from_request(
        app,
        ts,
        logo_file=quiz_logo
    )

    quiz_id, _ = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="short_quiz",
        exam_minutes=exam_minutes,
        logo_filename=logo_filename,
        rollback_logo_filename=logo_filename,
    )

    flash("Short quiz created successfully.", "success")
    return redirect(f"/edit_quiz/{quiz_id}")






# =========================================================
# SMART SUGGESTIONS ENGINE — FINAL CONSOLIDATED
# =========================================================
def build_smart_suggestions(original_text, cleaned_text):
    suggestions = []
    import re

    # Normalize safely
    o = (original_text or "").strip()
    c = (cleaned_text or "").strip()

    # ---------------------------------------
    # 1️⃣ Detect numbered prefixes
    # ---------------------------------------
    if re.search(r"^\s*\d+\.\s+", o, re.MULTILINE):
        suggestions.append({
            "title": "Numbered Questions Detected",
            "detail": "Questions appear to start with numbers like '1. 2. 3.'.",
            "recommend": "Enable Number Prefix Removal preset"
        })

    # ---------------------------------------
    # 2️⃣ PDF WRAP — warn ONLY if CLEANED TEXT still broken
    # ---------------------------------------
    pdf_wrap_detected = False

    # hyphen wrap still present
    if re.search(r"-\s*\n\s*", c):
        pdf_wrap_detected = True

    # mid-sentence linebreak still present
    elif re.search(r"(?<![.!?:])\s*\n\s*[A-Za-z]", c):
        pdf_wrap_detected = True

    if pdf_wrap_detected:
        suggestions.append({
            "title": "Possible PDF Wrap Detected",
            "detail": "Lines appear split mid-sentence.",
            "recommend": "Enable PDF Line Wrapping Fix preset."
        })

    # ---------------------------------------
    # 3️⃣ HEADER / FOOTER repetition detector
    # ---------------------------------------
    lines = [l.strip() for l in o.splitlines() if l.strip()]
    repeats = [l for l in set(lines) if lines.count(l) >= 3]

    if repeats:
        suggestions.append({
            "title": "Repeated Header/Footer Detected",
            "detail": "Document contains repeating page headers or footers.",
            "recommend": "Enable Header/Footer Cleanup preset"
        })

    # ---------------------------------------
    # 4️⃣ MULTIPLE QUESTION COLLAPSE DETECTOR
    # ---------------------------------------
    answer_markers_pattern = re.compile(
        r"(Correct\s*Answer[s]?|Suggested\s*Answer[s]?)",
        re.IGNORECASE
    )

    total_markers = (
        len(answer_markers_pattern.findall(o)) +
        len(answer_markers_pattern.findall(c))
    )

    if total_markers >= 2:
        suggestions.append({
            "title": "Multiple Questions Detected in a Single Block",
            "detail": (
                "Detected multiple answer markers inside one block. "
                "This usually means more than one question exists but "
                "isn't clearly separated. The parser may merge them."
            ),
            "recommend": (
                "Insert a BLANK LINE between each question, "
                "or number them 1., 2., 3."
            )
        })

    # ---------------------------------------
    # 5️⃣ BOM / Unicode trouble detector
    # ---------------------------------------
    trouble_chars = ["\uFEFF", "\u200B", "\u200C", "\u200D", "\u2060"]

    if any(t in o for t in trouble_chars):
        suggestions.append({
            "title": "Hidden Unicode Characters Present",
            "detail": "Detected BOM or zero-width Unicode in source text.",
            "recommend": "Keep Invisible Character Cleanup Enabled"
        })

    # ---------------------------------------
    # 6️⃣ EVERYTHING LOOKS GOOD fallback
    # ---------------------------------------
    if not suggestions:
        suggestions.append({
            "title": "Formatting Looks Excellent",
            "detail": "No structural or formatting problems detected.",
            "recommend": "You can safely continue 👍"
        })

    return suggestions


# =============================
# 12A – STRUCTURAL VALIDATION
# =============================
def quick_structural_scan(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    issues = []
    question_blocks = 0
    current_block_has_answer = False
    current_block_has_correct = False

    for line in lines:
        
        # Detect likely question
        if re.match(r"^\d+[\).\-]?\s", line) or line.lower().startswith("question"):
            question_blocks += 1

            # if previous question existed but had no answer
            if not current_block_has_answer and question_blocks > 1:
                issues.append("A question appears without any A/B/C/D answer choices.")

            current_block_has_answer = False
            current_block_has_correct = False
        
        # Detect answer choices (A–Z supported)
        if re.match(r"^[A-Za-z][\).\-]?\s", line):
            current_block_has_answer = True

        
        # Detect correct answer
        if "correct answer" in line.lower():
            current_block_has_correct = True

    # Final block sanity check
    if question_blocks == 0:
        issues.append("No recognizable questions were detected.")

    if question_blocks > 0 and not current_block_has_answer:
        issues.append("Last detected question has no answer choices.")

    if question_blocks > 0 and not current_block_has_correct:
        issues.append("No 'Correct Answer' lines were found — quiz may fail to grade.")

    return {
        "question_blocks": question_blocks,
        "issues": issues
    }





# =========================
# PREVIEW CLEAN TEXT BEFORE PARSE
# =========================
@app.route("/preview_paste", methods=["POST"])
def preview_paste():
    #cleanup_temp_logos()   # 🧹 optional cleanup (leave commented)

    quiz_text = request.form.get("quiz_text", "").strip()
    quiz_title = request.form.get("quiz_title", "Generated Quiz From Paste")
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))
    strip_rules_raw = request.form.get("strip_text", "").strip()

    # =========================
    # HANDLE LOGO PREVIEW (TEMP ONLY)
    # =========================
    preview_logo_name = save_preview_logo(
        app,
        request.files.get("quiz_logo")
    )





    if not quiz_text:
        return "No text provided.", 400

    # Start with raw text
    clean_text = quiz_text

    # Normalize ALL newline styles (Windows, Linux, literal \n)
    clean_text = (
        clean_text
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    # =========================
    # APPLY STRIP RULES (optional regex mode)
    # =========================
    strip_rules = []
    if strip_rules_raw:
        strip_rules = [r.strip() for r in strip_rules_raw.splitlines() if r.strip()]

    cfg = load_portal_config()
    regex_mode = cfg.get("enable_regex_strip", False)
    regex_replace_enabled = cfg.get("enable_regex_replace", False)
    
    if strip_rules:
        cleaned_lines = []

        for line in clean_text.splitlines():
            test = line
            remove = False

            for rule in strip_rules:

                # --- REGEX MODE ---
                if regex_mode:
                    try:
                        if re.search(rule, test, re.IGNORECASE):
                            remove = True
                            break
                    except re.error:
                        # Ignore bad regex patterns
                        pass

                # --- PLAIN TEXT MODE ---
                else:
                    if rule.lower() in test.lower():
                        remove = True
                        break

            if not remove:
                cleaned_lines.append(line)

        clean_text = "\n".join(cleaned_lines)

    # =========================
    # REGEX REPLACE ENGINE
    # =========================
    regex_replace_enabled = cfg.get("enable_regex_replace", False)

    replace_rules_raw = request.form.get("replace_rules", "").strip()
    applied_rules = []

    # -------------------------
    # MANUAL USER REGEX RULES
    # -------------------------
    if regex_replace_enabled and replace_rules_raw:
        for line in replace_rules_raw.splitlines():
            line = line.strip()
            if "=>" not in line:
                continue

            pattern, replacement = line.split("=>", 1)
            pattern = pattern.strip()
            replacement = replacement.strip()

            if not pattern:
                continue

            try:
                new_text = re.sub(
                    pattern,
                    replacement,
                    clean_text,
                    flags=re.IGNORECASE | re.MULTILINE
                )

                if new_text != clean_text:
                    applied_rules.append(pattern)

                clean_text = new_text

            except re.error:
                applied_rules.append(f"[INVALID REGEX] {pattern}")

    # =========================================================
    # REGEX PRESETS (state preserved for the template)
    # =========================================================
    preset_number_prefix_checked = bool(request.form.get("preset_number_prefix"))
    preset_pdf_spacing_checked = bool(request.form.get("preset_pdf_spacing"))
    preset_headers_checked = bool(request.form.get("preset_headers"))

    if regex_replace_enabled:
        preset_patterns = []

    # 1️⃣ Remove numbered prefixes FIRST
    if preset_number_prefix_checked:
        preset_patterns.append((
            r"^\s*\d+\.\s*",
            "",
            "Removed numbered prefixes"
        ))

    # 2️⃣ REMOVE HEADERS / FOOTERS SECOND
    if preset_headers_checked:
        preset_patterns.append((
            r"^\s*(Page\s+\d+.*|Copyright.*|All\s+Rights\s+Reserved.*)$",
            "",
            "Removed header/footer text"
        ))

    # 2️⃣ Fix PDF / Microsoft wrapped lines + hyphenation
    if preset_pdf_spacing_checked:
        preset_patterns.append((
            r"-\s*\n\s*",
            "",
            "Fixed PDF hyphen wraps"
        ))

        # SUPER SAFE PDF WRAP JOIN
        # Will NOT join across question boundaries
        preset_patterns.append((
            r"(?<=[a-z,;])\n(?=\s*[a-z])",
            " ",
            "Joined wrapped lines safely"
        ))





        # ---------- APPLY PRESETS ----------
        for pattern, replacement, label in preset_patterns:
            try:
                new_text = re.sub(
                    pattern,
                    replacement,
                    clean_text,
                    flags=re.IGNORECASE | re.MULTILINE
                )

                if new_text != clean_text:
                    applied_rules.append(label)

                clean_text = new_text

            except re.error:
                applied_rules.append(f"[INVALID PRESET REGEX] {pattern}")

    # =========================
    # AUTO MULTI-QUESTION SPLIT FIX
    # =========================
    safe_split_pattern = re.compile(
        r"(Correct\s*Answer[s]?:.*?\n)(?=\S)",
        re.IGNORECASE
    )

    # Also support Suggested Answer
    safe_split_pattern_2 = re.compile(
        r"(Suggested\s*Answer[s]?:.*?\n)(?=\S)",
        re.IGNORECASE
    )

    new_text = clean_text

    new_text = safe_split_pattern.sub(r"\1\n", new_text)
    new_text = safe_split_pattern_2.sub(r"\1\n", new_text)

    if new_text != clean_text:
        applied_rules.append("Auto Question Splitter")
        clean_text = new_text

    # =========================
    # FORCE MCQ OPTIONS ON CLEAN LINES
    # =========================
    # 1️⃣ Ensure every choice letter starts a new line
    choice_line_fix = re.compile(
        r"\s+(?=([A-Z]\.\s))"
    )

    new_text = clean_text
    new_text = choice_line_fix.sub(r"\n", new_text)

    # 2️⃣ Remove accidental double newlines caused by above
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)

    if new_text != clean_text:
        applied_rules.append("Normalized MCQ Choices")
        clean_text = new_text




    # =========================
    # AUTO BOM / INVISIBLE CLEAN
    # =========================
    invis_cleanup_enabled = cfg.get("auto_bom_clean", False)
    removed_unicode = []

    if invis_cleanup_enabled:
        invisibles = [
            ("\uFEFF", "BOM"),
            ("\u200B", "Zero-Width Space"),
            ("\u200C", "Zero-Width Non-Joiner"),
            ("\u200D", "Zero-Width Joiner"),
            ("\u2060", "Word Joiner"),
        ]

        before = clean_text

        for char, label in invisibles:
            if char in clean_text:
                removed_unicode.append(label)
                clean_text = clean_text.replace(char, "")

        # Normalize multiple blank lines
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

        # If BOM only at start
        if before != clean_text and "BOM" not in removed_unicode:
            if before.startswith("\uFEFF"):
                removed_unicode.append("BOM")
                clean_text = clean_text.lstrip("\uFEFF")

    # -------- CONFIDENCE ANALYSIS --------
    conf_summary = conf_details = None
    if get_confidence_setting():
        conf_summary, conf_details = analyze_confidence(clean_text)

    # -------- SMART SUGGESTIONS --------
    smart_suggestions = []

    def add_suggestion(title, detail, recommend, rule=None):
        smart_suggestions.append({
            "title": title,
            "detail": detail,
            "recommend": recommend,
            "suggest_rule": rule
        })

    text = clean_text

    # 1️⃣ Detect wrapped PDF text
    if re.search(r"(?<![.!?])\n(?!\n)", text):
        add_suggestion(
            "Possible PDF Wrap Detected",
            "Lines appear split where they should be continuous sentences.",
            "Enable PDF Line Wrapping Fix preset.",
            "Enable preset: PDF Wrapping"
        )

    # 2️⃣ Detect numbered prefixes like 1. Question
    if re.search(r"^\s*\d+\.\s+", text, re.MULTILINE):
        add_suggestion(
            "Numbered Question Prefixes Found",
            "Detected numbering like '1.' or '22.' before questions.",
            "Enable Number Prefix Removal preset.",
            r"^\s*\d+\.\s* => "
        )

    # 3️⃣ Detect repeated header/footer patterns
    if re.search(r"Page\s+\d+", text) or re.search(r"Copyright", text, re.I):
        add_suggestion(
            "Likely Headers/Footers Detected",
            "Repeated structural text such as page numbers or copyright text found.",
            "Enable Header/Footer Cleanup preset.",
            "Enable preset: Headers"
        )

    # 4️⃣ Detect if nothing changed
    if quiz_text == clean_text:
        add_suggestion(
            "No Formatting Changes Applied",
            "None of your strip or regex rules changed the text.",
            "Try enabling presets or adding regex rules."
        )

    # 5️⃣ If no warnings, say it’s clean
    if len(smart_suggestions) == 0:
        add_suggestion(
            "Formatting Looks Excellent",
            "No structural or formatting problems detected.",
            "You can safely continue 👍"
        )


    # =========================
    # UI SUPPORT LOGIC — ensure template displays correctly
    # =========================

    # If global regex replace enabled but user did not submit rules,
    # keep replace_rules list empty but still treat engine as active
    replace_rules = replace_rules_raw.splitlines() if replace_rules_raw else []

    # Make template show replace rules section when enabled globally
    if regex_replace_enabled and not replace_rules:
        replace_rules = ["(Regex engine enabled — no manual rules entered)"]


    # ---------- RENDER PREVIEW ----------
    return render_template_string("""

<html>
<head>
    <title>Preview Before Parsing</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
                              
</head>

<body class="paste-preview-page">

  <script>
    fetch("/config/portal.json")
    .then(r => r.json())
    .then(cfg => {
        if (cfg.background_image) {
            document.documentElement.style.setProperty(
                "--portal-bg",
                `url(${cfg.background_image})`
            );
        }
    });
    </script>
                             

<div class="container">
    
    <h1 class="hero-title">👀 Preview Quiz Before Building</h1>

    <div class="card">
        <h2>Quiz Title:</h2>
        <p><b>{{quiz_title}}</b></p>

        <!-- STEP 7: PRE-PROCESS SUMMARY PANEL -->
<div class="paste-preview-summary">
    <h2>🧪 Pre-Processing Summary</h2>

    <!-- =============================
          REGEX STRIP + STRIP RULES
    ============================== -->
    {% if regex_mode %}
    <p><b>Regex Strip Mode:</b> Enabled ✔</p>

        {% if strip_rules %}
        <h3>Lines Removed By Strip Rules</h3>
        <ul>
            {% for r in strip_rules %}
            <li>{{r}}</li>
            {% endfor %}
        </ul>
        {% endif %}
    {% endif %}

    <!-- =============================
          MANUAL REGEX RULES
    ============================== -->
    {% if replace_rules %}
    <h3>Manual Regex Replace Rules</h3>
    <ul>
        {% for r in replace_rules %}
        <li>{{r}}</li>
        {% endfor %}
    </ul>
    {% endif %}

    <!-- =============================
          PRESETS — ONLY IF ANY USED
    ============================== -->
    {% if preset_number_prefix_checked or preset_pdf_spacing_checked or preset_headers_checked %}
    <h3>✨ Regex Presets</h3>
    <ul>
        {% if preset_number_prefix_checked %}
        <li>Number Prefix Removal Enabled ✔</li>
        {% endif %}

        {% if preset_pdf_spacing_checked %}
        <li>PDF Line Wrapping Fix Enabled ✔</li>
        {% endif %}

        {% if preset_headers_checked %}
        <li>Header/Footer Cleanup Enabled ✔</li>
        {% endif %}
    </ul>
    {% endif %}

    <!-- =============================
          RULES THAT ACTUALLY FIRED
    ============================== -->
    {% if applied_rules %}
    <h3>Rules That Actually Changed Text</h3>
    <ul>
        {% for r in applied_rules %}
        <li>✔ {{r}}</li>
        {% endfor %}
    </ul>
    {% endif %}

    <!-- =============================
          INVISIBLE CLEAN
    ============================== -->
    {% if invis_cleanup_enabled %}
    <h3>Invisible Character Cleanup</h3>

        {% if removed_unicode %}
        <p>Removed:</p>
        <ul>
            {% for u in removed_unicode %}
            <li>{{u}}</li>
            {% endfor %}
        </ul>
        {% else %}
        <p>No hidden Unicode issues found 🎉</p>
        {% endif %}
    {% endif %}
</div>


                       <!-- SMART SUGGESTIONS -->
                    <h3 class="paste-preview-suggestions-heading">💡 Smart Suggestions</h3>

                    {% if smart_suggestions and smart_suggestions|length > 0 %}
                    <ul class="paste-preview-suggestions">
                    {% for s in smart_suggestions %}
                    <li class="paste-preview-suggestion">
                        <b class="paste-preview-suggestion-title">{{s.title}}</b><br>
                        <span class="paste-preview-suggestion-detail">{{s.detail}}</span><br>
                        <span class="paste-preview-suggestion-recommendation">Recommendation: {{s.recommend}}</span>

                        {% if s.suggest_rule %}
                        <br>
                        <code class="paste-preview-suggestion-rule">
                            {{s.suggest_rule}}
                        </code>
                        {% endif %}

                        <!-- APPLY BUTTON -->
                        <form action="/preview_paste" method="POST" style="margin-top:8px;">

                            <!-- always resend original data -->
                            <input type="hidden" name="quiz_title" value="{{quiz_title}}">
                            <textarea name="quiz_text" style="display:none;">{{original}}</textarea>

                            <!-- preserve user cleanup fields if they existed -->
                            <textarea name="strip_text" style="display:none;">
                    {% for r in strip_rules %}{{r}}
                    {% endfor %}
                            </textarea>

                            <textarea name="replace_rules" style="display:none;">
                    {% for r in replace_rules %}{{r}}
                    {% endfor %}
                            </textarea>

                            <!-- turn on correct preset -->
                            {% if "PDF" in s.title %}
                                <input type="hidden" name="preset_pdf_spacing" value="1">
                            {% endif %}

                            {% if "Number" in s.title %}
                                <input type="hidden" name="preset_number_prefix" value="1">
                            {% endif %}

                            {% if "Header" in s.title or "Footer" in s.title %}
                                <input type="hidden" name="preset_headers" value="1">
                            {% endif %}

                            <button type="submit">⚙ Apply This Fix</button>
                        </form>

                    </li>
                    {% endfor %}
                    </ul>
                    {% else %}
                    <p>No suggestions — formatting already looks great 🎯</p>
                    {% endif %}


        </div>
        <!-- END SUMMARY -->

        <h2>Original Text</h2>
        <pre id="origBox" class="paste-preview-source">{{original}}</pre>

        <h2>Text To Be Parsed: (passed to quiz)</h2>
        <pre id="cleanBox" class="paste-preview-source paste-preview-source-clean">{{cleaned}}</pre>

        <br>
        <button onclick="toggleInvisible()" style="margin-top:5px;">
            👁 Show / Hide Invisible Characters
        </button>

        <p class="paste-preview-helper">
            This helps detect BOM, zero-width, Unicode junk, and newline issues.
        </p>

        <div id="visualPanel" style="display:none; margin-top:15px;">
            <h2>🔍 Visualized Text</h2>

            <h3>Original Input</h3>
            <pre id="visualOrig" class="paste-preview-source"></pre>

            <h3>Parsed (Cleaned) Version</h3>
            <pre id="visualClean" class="paste-preview-source paste-preview-source-clean"></pre>
        </div>

        <script>
        function visualize(text) {
            return text
                .replace(/\\u200B/g, "[ZWSP]")
                .replace(/\\u200C/g, "[ZWNJ]")
                .replace(/\\u200D/g, "[ZWJ]")
                .replace(/\\u2060/g, "[WJ]")
                .replace(/\\uFEFF/g, "[BOM]")
                .replace(/ /g, "·")
                .replace(/\\n/g, "\\\\n\\n");
        }

        function toggleInvisible() {
            const panel = document.getElementById("visualPanel");
            const show = panel.style.display === "none";

            if (show) {
                document.getElementById("visualOrig").innerText =
                    visualize(document.getElementById("origBox").innerText);

                document.getElementById("visualClean").innerText =
                    visualize(document.getElementById("cleanBox").innerText);
            }

            panel.style.display = show ? "block" : "none";
        }
        </script>

        <!-- 🔍 DIFF VIEW -->
        <button onclick="toggleDiff()" style="margin-top:10px;">
            🔍 Show / Hide Differences
        </button>

        <div id="diffPanel" style="display:none; margin-top:15px;">
            <h2>⚖️ Text Differences</h2>

            <h3>Original vs Cleaned Comparison</h3>
            <pre id="diffView" class="paste-preview-source"></pre>

            <p class="paste-preview-helper">
                <span style="color:#4cff4c;font-weight:bold;">Green</span> = added ·
                <span style="color:#ff4c4c;font-weight:bold;">Red</span> = removed
            </p>

        </div>

        <script>
function toggleDiff() {
    const panel = document.getElementById("diffPanel");
    const show = panel.style.display === "none";
    if (show) runDiff();
    panel.style.display = show ? "block" : "none";
}

function normalizeKey(s) {
    return (s || "")
        .replace(/\\r/g, "")
        .replace(/[\\u200B\\u200C\\u200D\\u2060]/g, "")
        .replace(/\\uFEFF/g, "")
        .replace(/\\u00A0/g, " ")
        .replace(/\\s+/g, " ")
        .trim();
}

function runDiff() {
    const origLines = document.getElementById("origBox").innerText
        .split("\\n")
        .map(normalizeKey)
        .filter(Boolean);

    const cleanLines = document.getElementById("cleanBox").innerText
        .split("\\n")
        .map(normalizeKey)
        .filter(Boolean);

    let out = "";

    // REMOVED
    for (const line of origLines) {
        if (!cleanLines.includes(line)) {
            out += "<span class='diff-removed'>[REMOVED] " + line + "</span><br>";


        }
    }

    // ADDED
    for (const line of cleanLines) {
        if (!origLines.includes(line)) {
            out += "<span class='diff-added'>[ADDED] " + line + "</span><br>";


        }
    }

    if (!out.trim()) {
        out = "No structural differences detected.";
    }

    document.getElementById("diffView").innerHTML = out;
}
</script>



        {% if conf_details %}
        <h2 class="paste-preview-confidence">🧠 Confidence Analysis</h2>
        <p class="paste-preview-confidence-summary">
            <b>Total blocks:</b> {{conf_summary.total}}<br>
            ✅ High: {{conf_summary.high}} &nbsp;
            ⚠ Medium: {{conf_summary.medium}} &nbsp;
            ❌ Low: {{conf_summary.low}}
        </p>

        <ul class="paste-preview-confidence-list">
            {% for item in conf_details %}
            <li class="paste-preview-suggestion">
                <b>Block {{item.index}} ({{item.confidence|capitalize}})</b><br>
                <span class="paste-preview-confidence-title">{{item.title}}</span><br>
                <span class="paste-preview-confidence-reason">{{item.reason}}</span>
            </li>
            {% endfor %}
        </ul>
        {% endif %}

        <p class="paste-preview-helper">
            If this looks correct, continue. Otherwise, go back and adjust rules.
        </p>

        <form action="/download_cleaned" method="POST" style="display:inline;">
            <textarea name="clean_text" style="display:none;">{{cleaned}}</textarea>
            <button type="submit">📥 Download Cleaned Text</button>
        </form>

        <!-- IMPORTANT: Send CLEANED text forward -->
        <form action="/process_paste" method="POST">
            <input type="hidden" name="quiz_title" value="{{ quiz_title }}">
            <input type="hidden" name="exam_minutes" value="{{ exam_minutes }}">
            <input type="hidden" name="temp_logo_name" value="{{ preview_logo_name }}">
            <textarea name="quiz_text" style="display:none;">{{ cleaned }}</textarea>

            <button type="submit">✅ Yes, Build My Quiz</button>
        </form>


        <br>
        <button onclick="history.back()">⬅ Go Back & Edit</button>
        <button onclick="location.href='/'">🏠 Return To Dashboard</button>
    </div>
</div>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""",

        quiz_title=quiz_title,
        exam_minutes=exam_minutes,
        original=quiz_text,
        cleaned=clean_text,
        conf_summary=conf_summary,
        conf_details=conf_details,
        preview_logo_name=preview_logo_name,
        regex_mode=regex_mode,
        strip_rules=strip_rules,
        replace_rules=replace_rules,
        applied_rules=applied_rules,
        invis_cleanup_enabled=invis_cleanup_enabled,
        removed_unicode=removed_unicode,
        preset_number_prefix_checked=preset_number_prefix_checked,
        preset_pdf_spacing_checked=preset_pdf_spacing_checked,
        preset_headers_checked=preset_headers_checked,
        smart_suggestions=smart_suggestions
        )











from flask import send_file
from io import BytesIO

@app.route("/download_cleaned", methods=["GET","POST"])
def download_cleaned():
    cleaned = request.form.get("clean_text", "").strip()

    if not cleaned:
        return "No cleaned text available.", 400

    buf = BytesIO()
    buf.write(cleaned.encode("utf-8"))
    buf.seek(0)

    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name="cleaned_quiz_text.txt"
    )




# =========================
# PROCESS PASTED QUIZ
# =========================
@app.route("/process_paste", methods=["POST"])
def process_paste():
    #cleanup_temp_logos()   # 🧹 clean abandoned logos again

    quiz_text = request.form.get("quiz_text", "").strip()
    quiz_title = request.form.get("quiz_title", "Generated Quiz From Paste")
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))

    # Checkbox flag (Auto Junk Cleanup)
    auto_cleanup = request.form.get("auto_cleanup") == "1"

    if not quiz_text:
        return "No text provided.", 400

    clean_text = quiz_text

    # Normalize ALL newline styles (Windows, Linux, Literal \n)
    clean_text = (
        clean_text
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    # Optional auto cleanup (only runs if you wire a checkbox)
    if auto_cleanup:
        cleaned_lines = []
        junk_patterns = [
            "topic",
            "chapter",
            "exam version",
            "objective",
            "learning goal",
            "case study",
            "scenario",
            "explanation",
            "rationale",
            "reference",
            "page",
        ]

        for line in clean_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            low = stripped.lower()
            if any(p in low for p in junk_patterns):
                continue
            cleaned_lines.append(line)

        clean_text = "\n".join(cleaned_lines)

    # Save cleaned text (for debugging / consistency)
    path = os.path.join(UPLOAD_FOLDER, "pasted.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(clean_text)

    # =========================
    # PARSE QUIZ
    # =========================
    quiz_data = parse_questions(clean_text)

    # Always save a parse log (success or failure)
    ts = int(time.time())
    log_filename = f"parse_log_{ts}.txt"
    with open(os.path.join(DATA_FOLDER, log_filename), "w", encoding="utf-8") as f:
        f.write("\n".join(PARSE_LOG))

    # If no questions parsed, show failure UI + log link
    if not quiz_data:
        return render_template_string("""
        <html>
        <head>
            <title>Parse Failed</title>
            <link rel="stylesheet" href="/static/style.css">
            <link rel="icon" href="/static/favicon.ico">
        </head>
        <body>
        <script>
        fetch("/config/portal.json")
        .then(r => r.json())
        .then(cfg => {
            if (cfg.background_image) {
                document.documentElement.style.setProperty(
                    "--portal-bg",
                    `url(${cfg.background_image})`
                );
            }
        });
        </script>

        <div class="container">
            <h1 class="hero-title">⚠️ Could Not Parse Any Questions</h1>

            <div class="card">
                <p>No valid questions were parsed. Please check the formatting.</p>
                <p>You can download the parser log for troubleshooting:</p>

                <button onclick="location.href='/data/{{log_filename}}'">
                    📥 Download Parse Log
                </button>

                <br><br>

                <button onclick="location.href='/upload'">
                    ⬅ Back To Upload Page
                </button>

                <button onclick="location.href='/paste'">
                    📋 Try Paste Mode Instead
                </button>

                <button onclick="location.href='/'">
                    🏠 Return To Dashboard
                </button>
            </div>
        </div>
        <script src="/static/nav-normalize.js"></script>
</body>
        </html>
        """, log_filename=log_filename), 400

    # =========================
    # HANDLE LOGO (FINAL, SINGLE SOURCE OF TRUTH)
    # =========================
    logo_filename = finalize_logo_from_request(
        app,
        ts,
        logo_file=request.files.get("quiz_logo"),
        temp_logo_name=request.form.get("temp_logo_name"),
    )


    # =========================
    # REGISTRY ID (CANONICAL)
    # =========================
    


    # =========================
    # SAVE QUIZ
    # =========================
    source_file = f"quiz_upload_{ts}_{int(time.time() * 1000)}"

    db_quiz_id, html_name = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="quiz",
        exam_minutes=exam_minutes,
        logo_filename=logo_filename,
        source_file=source_file,
        rollback_logo_filename=logo_filename,
    )


    # FINAL SAFETY: only register logo if file actually exists
    if logo_filename:
        final_logo_path = os.path.join(LOGO_FOLDER, logo_filename)
        if not os.path.exists(final_logo_path):
            dprint("[LOGO FIX] Prevented registering missing logo:", logo_filename)
            logo_filename = None

    #add_quiz_to_registry(html_name, quiz_title, logo_filename)

    return redirect("/library")



@app.route("/process", methods=["POST"])
def process_file():
    #cleanup_temp_logos()  # 🧹 clean abandoned logos
    file = request.files.get("file")
    quiz_title = request.form.get("quiz_title", "Generated Quiz")
    quiz_logo = request.files.get("quiz_logo")
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))

    logo_filename = None  # ✅ ensure always defined
    source_file = None    # ✅ canonical quiz identifier

    if not file:
        return "No file uploaded", 400

    # ---- determine source_file (required by schema) ----
    if file.filename:
        now = int(time.time())
        source_file = f"quiz_upload_{now}_{int(time.time() * 1000)}"



    else:
        source_file = f"manual_paste_{int(time.time())}"

    # The uploaded source is needed only for this parse. Read it through the
    # workflow ceiling instead of persisting an unbounded temporary file.
    try:
        raw_text = _read_bounded_upload(file, QUIZ_TEXT_UPLOAD_MAX_BYTES, "Quiz text file").decode(
            "utf-8", errors="ignore"
        ).strip()
    except UploadTooLargeError as exc:
        return str(exc), 413

    if not raw_text:
        return "Uploaded file is empty.", 400

    # Normalize ALL newline styles (MATCH PASTE MODE)
    clean_text = (
        raw_text
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    # =========================
    # PARSE QUIZ (SAME AS PASTE MODE)
    # =========================
    quiz_data = parse_questions(clean_text)

    # Always save a parse log (success or failure)
    ts = int(time.time())
    log_filename = f"parse_log_{ts}.txt"
    with open(os.path.join(DATA_FOLDER, log_filename), "w", encoding="utf-8") as f:
        f.write("\n".join(PARSE_LOG))

    if not quiz_data:
        return render_template_string("""
        <html>
        <head>
            <title>Parse Failed</title>
            <link rel="stylesheet" href="/static/style.css">
            <link rel="icon" href="/static/favicon.ico">
        </head>
        <body>
        <script>
        fetch("/config/portal.json")
        .then(r => r.json())
        .then(cfg => {
            if (cfg.background_image) {
                document.documentElement.style.setProperty(
                    "--portal-bg",
                    `url(${cfg.background_image})`
                );
            }
        });
        </script>

        <div class="container">
            <h1 class="hero-title">⚠️ Could Not Parse Any Questions</h1>

            <div class="card">
                <p>No valid questions were parsed. Please check the formatting.</p>
                <p>You can download the parser log for troubleshooting:</p>

                <button onclick="location.href='/data/{{log_filename}}'">
                    📥 Download Parse Log
                </button>

                <br><br>

                <button onclick="location.href='/upload'">
                    ⬅ Back To Upload Page
                </button>

                <button onclick="location.href='/paste'">
                    📋 Try Paste Mode Instead
                </button>

                <button onclick="location.href='/'">
                    🏠 Return To Dashboard
                </button>
            </div>
        </div>
        <script src="/static/nav-normalize.js"></script>
</body>
        </html>
        """, log_filename=log_filename), 400

    print("UPLOAD MODE FINAL PARSE COUNT:", len(quiz_data))

    # =========================
    # PARSE DIAGNOSTICS (TEMP)
    # =========================
    for i, q in enumerate(quiz_data, 1):
        choices = q.get("choices", [])
        has_correct = any(c.get("is_correct") for c in choices)

        if not choices or not has_correct:
            dprint(f"[PARSE WARNING] Q{i} missing choices or correct answer")


    # =========================
    # HANDLE LOGO (FINAL, SINGLE SOURCE OF TRUTH)
    # =========================
    logo_filename = finalize_logo_from_request(
        app,
        ts,
        logo_file=quiz_logo,
    )

    # =========================
    # REGISTRY ID (CANONICAL)
    # =========================
    

    quiz_id, html_name = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="quiz",
        exam_minutes=exam_minutes,
        logo_filename=logo_filename,
        source_file=source_file,
        rollback_logo_filename=logo_filename,
    )


    return redirect("/library")




# =====================================================
# SETTINGS HUB + INCREMENTAL SETTINGS MIGRATION
# =====================================================
@app.route("/settings")
def settings_page():
    """Settings landing page for the completed category-based settings UI."""
    return render_template("settings/index.html")


@app.route("/settings/navigation")
def settings_navigation_page():
    cfg = load_portal_config()
    visibility = cfg["study_area_visibility"]

    return render_template("settings/navigation.html", visibility=visibility)


@app.route("/settings/navigation/save", methods=["POST"])
def save_navigation_settings():
    cfg = load_portal_config()
    cfg["study_area_visibility"] = {
        "it": "study_area_it" in request.form,
        "law": "study_area_law" in request.form,
        "medical": "study_area_medical" in request.form,
        "other": "study_area_other" in request.form,
    }

    _atomic_write_json(PORTAL_CONFIG, cfg, indent=4, expected_type=dict)

    return redirect("/settings/navigation?saved=1")


@app.route("/settings/appearance")
def settings_appearance_page():
    cfg = load_portal_config()
    return render_template("settings/appearance.html", cfg=cfg)


@app.route("/settings/appearance/save", methods=["POST"])
def save_appearance_settings():
    """Save only Appearance settings.

    Deliberately does not update checkbox-based parsing or AI values so a
    partial settings form cannot accidentally disable unrelated features.
    """
    cfg = load_portal_config()

    requested_theme = str(request.form.get("theme") or cfg.get("theme") or DEFAULT_THEME).strip().lower()
    cfg["theme"] = requested_theme if requested_theme in {"dark", "light", "purple-gold", "maroon-gold"} else DEFAULT_THEME

    title = request.form.get("portal_title", "").strip()
    if title:
        cfg["title"] = title

    file = request.files.get("background_image")
    if file and file.filename and file.filename.strip():
        filename = secure_filename(file.filename)
        try:
            _store_raster_upload(file, BACKGROUND_FOLDER, filename, RASTER_IMAGE_FORMATS)
        except ValueError as exc:
            return f"Invalid background image: {html.escape(str(exc))}", 400
        cfg["background_image"] = filename

    _atomic_write_json(PORTAL_CONFIG, cfg, indent=4, expected_type=dict)

    return redirect("/settings/appearance?saved=1")


@app.route("/api/theme", methods=["POST"])
def api_set_theme():
    cfg = load_portal_config()
    payload = request.get_json(silent=True) or request.form
    requested = str(payload.get("theme") or "").strip().lower()
    if requested not in {"dark", "light", "purple-gold", "maroon-gold"}:
        return jsonify({"ok": False, "error": "Unsupported theme"}), 400
    cfg["theme"] = requested
    _atomic_write_json(PORTAL_CONFIG, cfg, indent=4, expected_type=dict)
    return jsonify({"ok": True, "theme": requested})


@app.route("/settings/ai")
def settings_ai_page():
    cfg = load_portal_config()

    cfg.setdefault("ai_helper_enabled", False)
    cfg.setdefault("ai_provider", "chatgpt")
    cfg.setdefault("ai_custom_url", "")
    cfg.setdefault("ai_auto_copy_prompt", True)
    cfg.setdefault("ai_prompt_template", "")
    cfg.setdefault("study_pack_ai_prompt_template", DEFAULT_STUDY_CONTENT_PACK_PROMPT)
    cfg.setdefault("medical_study_pack_ai_addendum", DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM)
    cfg.setdefault("law_ai_prompt_template", DEFAULT_LAW_AI_PROMPT)

    return render_template(
        "settings/ai.html",
        cfg=cfg,
        law_default_prompt=DEFAULT_LAW_AI_PROMPT,
        study_pack_default_prompt=DEFAULT_STUDY_CONTENT_PACK_PROMPT,
        medical_study_pack_default_addendum=DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
    )


@app.route("/settings/ai/save", methods=["POST"])
def save_ai_settings():
    """Save only AI Integration settings.

    This deliberately leaves Appearance and Parsing values untouched.
    """
    cfg = load_portal_config()

    cfg["ai_helper_enabled"] = ("ai_helper_enabled" in request.form)
    cfg["ai_auto_copy_prompt"] = ("ai_auto_copy_prompt" in request.form)

    valid_ai_providers = {"chatgpt", "claude", "gemini", "local"}
    provider = request.form.get("ai_provider", "chatgpt").strip().lower()
    cfg["ai_provider"] = provider if provider in valid_ai_providers else "chatgpt"

    try:
        cfg["ai_custom_url"] = _validate_custom_ai_url(
            request.form.get("ai_custom_url", "")
        )
    except ValueError as exc:
        return str(exc), 400
    cfg["ai_prompt_template"] = request.form.get("ai_prompt_template", "").strip()
    cfg["study_pack_ai_prompt_template"] = request.form.get("study_pack_ai_prompt_template", "").strip() or DEFAULT_STUDY_CONTENT_PACK_PROMPT
    cfg["medical_study_pack_ai_addendum"] = request.form.get("medical_study_pack_ai_addendum", "").strip() or DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM
    cfg["law_ai_prompt_template"] = request.form.get("law_ai_prompt_template", "").strip() or DEFAULT_LAW_AI_PROMPT

    _atomic_write_json(PORTAL_CONFIG, cfg, indent=4, expected_type=dict)

    return redirect("/settings/ai?saved=1")



@app.route("/settings/parsing")
def settings_parsing_page():
    cfg = load_portal_config()

    cfg.setdefault("show_confidence", True)
    cfg.setdefault("enable_regex_replace", False)
    cfg.setdefault("auto_bom_clean", False)
    cfg.setdefault("enable_show_invisibles", True)

    return render_template("settings/parsing.html", cfg=cfg)


@app.route("/settings/parsing/save", methods=["POST"])
def save_parsing_settings():
    """Save only Parsing settings.

    Checkbox values are intentionally scoped to this dedicated form so
    Appearance and AI configuration remain untouched.
    """
    cfg = load_portal_config()

    cfg["show_confidence"] = ("show_confidence" in request.form)
    cfg["enable_regex_replace"] = ("enable_regex_replace" in request.form)
    cfg["auto_bom_clean"] = ("auto_bom_clean" in request.form)
    cfg["enable_show_invisibles"] = ("enable_show_invisibles" in request.form)

    _atomic_write_json(PORTAL_CONFIG, cfg, indent=4, expected_type=dict)

    return redirect("/settings/parsing?saved=1")


@app.route("/settings/data/backup/create", methods=["POST"])
@app.route("/settings/backup/create", methods=["POST"])
def settings_create_backup():
    try:
        path, _manifest = _create_dlms_backup("manual")
        return send_from_directory(BACKUP_FOLDER, os.path.basename(path), as_attachment=True)
    except Exception as exc:
        print("[BACKUP ERROR]", exc)
        return render_template("settings/backup-failed.html", error="DLMS could not create the backup. Check the local application log for details."), 500


@app.route("/settings/data/restore/stage", methods=["POST"])
@app.route("/settings/backup/restore/stage", methods=["POST"])
def settings_stage_restore():
    upload = request.files.get("backup_file")
    if not upload or not upload.filename:
        return redirect("/settings/backup?restore_error=no-file")
    if not upload.filename.lower().endswith(".zip"):
        return redirect("/settings/backup?restore_error=not-zip")
    if request.content_length and request.content_length > BACKUP_UPLOAD_MAX_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES:
        return "Backup exceeds the 298 MB restore upload limit.", 413

    token = secrets.token_hex(16)
    stage_dir = _restore_staging_dir(token)
    _backup_service.create_backup_restore_stage(stage_dir)
    try:
        report, semantic_result = _stage_dlms_backup(
            upload, token, stage_dir=stage_dir
        )
    except Exception as exc:
        shutil.rmtree(stage_dir, ignore_errors=True)
        print(f"[RESTORE VALIDATION ERROR] {type(exc).__name__}: {exc}")
        return render_template("settings/restore-validation-failed.html", error="The backup failed validation and was not accepted. Check the local DLMS log for details."), 400

    manifest = report["manifest"]
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    return render_template("settings/restore-confirm.html", manifest=manifest, report=report, semantic_validation=semantic_result, summary=summary, token=token)


@app.route("/settings/data/restore/cancel/<token>", methods=["POST"])
@app.route("/settings/backup/restore/cancel/<token>", methods=["POST"])
def settings_cancel_restore(token):
    with RESTORE_OPERATION_LOCK:
        try:
            result = _cancel_validated_restore_stage(token)
        except ValueError:
            return "Invalid restore cancellation request", 400
        except Exception as exc:
            print(
                "[RESTORE STAGING CLEANUP ERROR] Could not cancel restore stage: "
                f"{type(exc).__name__}: {exc}"
            )
            return "Could not cancel the staged restore", 500

    if result == "unrecognized":
        return "Restore staging is not available", 404
    if result == "recovery":
        return "Restore recovery is in progress or requires recovery", 409
    return redirect("/settings/backup?restore_cancelled=1")


@app.route("/settings/data/restore/confirm/<token>", methods=["POST"])
@app.route("/settings/backup/restore/confirm/<token>", methods=["POST"])
def settings_confirm_restore(token):
    with RESTORE_OPERATION_LOCK:
        return _settings_confirm_restore_locked(token)


def _complete_staged_restore(token):
    return _restore_service.complete_staged_restore(
        token,
        restore_staging_dir=_restore_staging_dir,
        validate_backup=_validate_dlms_backup,
        require_owned_root=_require_owned_app_data_root,
        extract_backup=_extract_validated_backup,
        validate_semantics=_validate_staged_backup_semantics,
        prepare_database=_prepare_staged_restore_database,
        create_backup=_create_dlms_backup,
        new_operation=_new_restore_operation,
        update_journal=_update_restore_operation_journal,
        checkpoint=_restore_operation_checkpoint,
        apply_data=_apply_restored_data,
        validate_current_database=_validate_current_restored_database,
        db_path=DB_PATH,
        reconcile_quiz_publications=reconcile_quiz_publications,
        read_journal=_read_restore_operation_journal,
        recover_one=_recover_one_restore_operation,
        validate_journal=_validate_restore_operation_journal,
        finish_cleanup=_finish_restore_operation_cleanup,
        print_message=print,
    )


def _settings_confirm_restore_locked(token):
    try:
        result = _complete_staged_restore(token)
        safety_path = result["safety_path"]
        cleanup_pending = result["cleanup_pending"]

        return render_template("settings/restore-complete.html", safety_name=os.path.basename(safety_path), cleanup_pending=cleanup_pending)
    except Exception as exc:
        print("[RESTORE ERROR]", exc)
        public_error = (
            str(exc) if isinstance(exc, (DataRootOwnershipError, RestoreFutureSchemaError))
            else "DLMS could not complete the restore. Existing data was preserved or rolled back. Check the local application log for details."
        )
        return render_template("settings/restore-failed.html", error=public_error), (
            400 if isinstance(exc, ValueError)
            else 409 if isinstance(exc, DataRootOwnershipError)
            else 500
        )


@app.route("/settings/data")
def settings_data_legacy_redirect():
    return redirect("/settings/backup")


@app.route("/settings/backup")
def settings_backup_page():
    recent_backups = []
    try:
        for name in sorted(os.listdir(BACKUP_FOLDER), reverse=True):
            path = os.path.join(BACKUP_FOLDER, name)
            if name.lower().endswith(".zip") and os.path.isfile(path):
                recent_backups.append({
                    "name": name,
                    "size": _format_bytes(os.path.getsize(path)),
                    "modified": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%b %d, %Y %I:%M %p"),
                })
                if len(recent_backups) >= 5:
                    break
    except Exception:
        recent_backups = []

    return render_template("settings/backup.html", recent_backups=recent_backups)


@app.route("/settings/reset")
def settings_reset_legacy_redirect():
    return redirect("/settings/reset-remove")


@app.route("/settings/reset-remove")
def settings_reset_remove_page():
    return render_template(
        "settings/reset-remove.html",
        app_data_dir=APP_DATA_DIR,
    )


@app.route("/settings/legacy")
def settings_legacy_page():
    """Redirect retired all-in-one Settings bookmarks to Appearance."""
    return redirect("/settings/appearance", code=302)






@app.route("/save_settings", methods=["POST"])
def save_settings():
    # A cached copy of the retired legacy form can still submit here. Redirect
    # without parsing or storing its fields/files so it cannot create partial
    # settings state. The supported Settings pages own their scoped saves.
    return redirect("/settings/appearance", code=303)







# =====================================================
# RECORD QUIZ ATTEMPT (DB-ID CANONICAL)
# =====================================================
LearningPayloadError = _attempt_service.LearningPayloadError
LEARNING_MODES = _attempt_service.LEARNING_MODES
LEARNING_QUESTION_TYPES = _attempt_service.LEARNING_QUESTION_TYPES


def _learning_integer(value, field, *, minimum=None, maximum=None, allow_numeric_string=False):
    return _attempt_service._learning_integer(
        value,
        field,
        minimum=minimum,
        maximum=maximum,
        allow_numeric_string=allow_numeric_string,
    )


def _learning_identifier(value, field, *, maximum=128):
    return _attempt_service._learning_identifier(value, field, maximum=maximum)


def _optional_learning_identifier(value, field, *, maximum=128):
    return _attempt_service._optional_learning_identifier(
        value,
        field,
        maximum=maximum,
        learning_identifier=_learning_identifier,
    )


def _attempt_timestamp(value, field):
    return _attempt_service._attempt_timestamp(value, field)


def _attempt_percent(score, total):
    return _attempt_service._attempt_percent(score, total)


def _question_response_context(cur, quiz_id, question_number):
    return _attempt_service._question_response_context(cur, quiz_id, question_number)


def _question_response_context_by_ordinal(cur, quiz_id, ordinal):
    return _attempt_service._question_response_context_by_ordinal(
        cur, quiz_id, ordinal
    )


def _learning_question_type(value, question, field):
    return _attempt_service._learning_question_type(
        value,
        question,
        field,
        learning_question_types=LEARNING_QUESTION_TYPES,
    )


def _strict_correctness(value, field, *, allow_none=False):
    return _attempt_service._strict_correctness(
        value, field, allow_none=allow_none
    )


def _choice_response(cur, question_id, selected, *, study):
    return _attempt_service._choice_response(
        cur, question_id, selected, study=study
    )


def _matching_response(cur, question_id, selected, *, study):
    return _attempt_service._matching_response(
        cur,
        question_id,
        selected,
        study=study,
        learning_integer=_learning_integer,
    )


def _hotspot_response(selected, *, study):
    return _attempt_service._hotspot_response(selected, study=study)


def _validate_question_response(
    cur, question, detail, *, study, field, attempt_question_number=None
):
    return _attempt_service._validate_question_response(
        cur,
        question,
        detail,
        study=study,
        field=field,
        attempt_question_number=attempt_question_number,
        learning_question_type=_learning_question_type,
        strict_correctness=_strict_correctness,
        choice_response=_choice_response,
        matching_response=_matching_response,
        hotspot_response=_hotspot_response,
    )


def _validate_missed_details(cur, raw_details, questions, responses):
    return _attempt_service._validate_missed_details(
        cur,
        raw_details,
        questions,
        responses,
        validate_hotspot_shape=_validate_hotspot_shape,
        learning_integer=_learning_integer,
    )


def _validate_attempt_payload(cur, data):
    return _attempt_service._validate_attempt_payload(
        cur,
        data,
        learning_integer=_learning_integer,
        learning_identifier=_learning_identifier,
        optional_learning_identifier=_optional_learning_identifier,
        validate_question_response=_validate_question_response,
        attempt_percent=_attempt_percent,
        attempt_timestamp=_attempt_timestamp,
        validate_missed_details=_validate_missed_details,
        learning_modes=LEARNING_MODES,
    )


def _attempt_retry_matches_existing(cur, validated, attempt_columns):
    return _attempt_service._attempt_retry_matches_existing(
        cur, validated, attempt_columns, json_module=json
    )


@app.route("/record_attempt", methods=["POST"])
def record_attempt():
    data = request.get_json(silent=True)

    conn = get_db()
    cur = conn.cursor()

    try:
        acknowledgement = _attempt_service.persist_attempt(
            conn,
            cur,
            data,
            validate_attempt_payload=_validate_attempt_payload,
            attempt_retry_matches_existing=_attempt_retry_matches_existing,
            record_learning_event=_record_learning_event,
            json_module=json,
            print_message=print,
        )
        return jsonify(acknowledgement), 200
    except LearningPayloadError as exc:
        conn.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        conn.rollback()
        print(f"DB ERROR in /record_attempt: {exc}")
        return jsonify({"error": "The quiz attempt could not be recorded."}), 500
    finally:
        conn.close()


@app.route("/api/learning-events/study-response", methods=["POST"])
def record_study_learning_event():
    data = request.get_json(silent=True)

    conn = get_db()
    cur = conn.cursor()
    try:
        acknowledgement, status = _attempt_service.persist_study_learning_event(
            conn,
            cur,
            data,
            learning_integer=_learning_integer,
            optional_learning_identifier=_optional_learning_identifier,
            question_response_context_by_ordinal=_question_response_context_by_ordinal,
            validate_question_response=_validate_question_response,
            record_learning_event=_record_learning_event,
            json_module=json,
        )
        return jsonify(acknowledgement), status
    except LearningPayloadError as exc:
        conn.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        conn.rollback()
        print(f"[LEARNING EVENT ERROR] {type(exc).__name__}: {exc}")
        return jsonify({"error": "The learning event could not be recorded."}), 500
    finally:
        conn.close()


@app.route("/api/learning-foundation/summary")
def learning_foundation_summary():
    """Diagnostics for DLMS-006/007; Phase 2 dashboards build on this data."""
    conn = get_db()
    cur = conn.cursor()
    concepts = cur.execute("""
        SELECT c.id, c.name, COUNT(DISTINCT qc.question_id) AS question_count
        FROM concepts c
        LEFT JOIN question_concepts qc ON qc.concept_id = c.id
        GROUP BY c.id, c.name
        ORDER BY c.name COLLATE NOCASE
    """).fetchall()
    event_counts = cur.execute("""
        SELECT event_type, COUNT(*) AS count
        FROM learning_events
        GROUP BY event_type
        ORDER BY event_type
    """).fetchall()
    totals = cur.execute("""
        SELECT COUNT(*) AS events, COUNT(DISTINCT quiz_id) AS quizzes,
               COUNT(DISTINCT question_id) AS questions
        FROM learning_events
    """).fetchone()
    out = {
        "concepts": [dict(r) for r in concepts],
        "event_counts": {r["event_type"]: r["count"] for r in event_counts},
        "totals": dict(totals) if totals else {"events": 0, "quizzes": 0, "questions": 0},
    }
    conn.close()
    return jsonify(out)


def _learning_intelligence_topics(cur, now=None):
    return _learning_service._learning_intelligence_topics(cur, now=now)


def _retention_schedule_for_topic(topic, now=None):
    return _learning_service._retention_schedule_for_topic(topic, now=now)


def _learning_topics_with_retention(cur, now=None):
    return _learning_service._learning_topics_with_retention(
        cur,
        now=now,
        learning_intelligence_topics=_learning_intelligence_topics,
        retention_schedule_for_topic=_retention_schedule_for_topic,
    )


def _review_schedule_payload(cur, now=None):
    return _learning_service._review_schedule_payload(
        cur,
        now=now,
        learning_topics_with_retention=_learning_topics_with_retention,
    )


def _learning_intelligence_payload(cur, now=None):
    return _learning_service._learning_intelligence_payload(
        cur,
        now=now,
        learning_topics_with_retention=_learning_topics_with_retention,
    )


def _learning_profile_payload(cur):
    return _learning_service._learning_profile_payload(
        cur,
        learning_intelligence_payload=_learning_intelligence_payload,
        review_schedule_payload=_review_schedule_payload,
    )


def _question_payload_from_db(cur, question_id):
    return _learning_service._question_payload_from_db(
        cur,
        question_id,
        question_concepts=_question_concepts,
    )


def _snapshot_existing_quiz_asset_refs(value, bucket, *, destination_root=None, strict=False):
    """Copy existing quiz-owned asset URLs so Smart Review survives source-quiz deletion."""
    if isinstance(value, dict):
        return {
            k: _snapshot_existing_quiz_asset_refs(
                v, bucket, destination_root=destination_root, strict=strict
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _snapshot_existing_quiz_asset_refs(
                v, bucket, destination_root=destination_root, strict=strict
            )
            for v in value
        ]
    if not isinstance(value, str) or not value.startswith("/quiz-assets/"):
        return value
    rel_url = value[len("/quiz-assets/"):].lstrip("/")
    parts = rel_url.split("/", 1)
    if len(parts) != 2:
        return value
    old_bucket, rel = parts
    try:
        src_root = os.path.join(QUIZ_ASSET_FOLDER, old_bucket)
        src = _safe_pack_child(src_root, rel)
        if not os.path.isfile(src):
            return value
        dest_root = destination_root or os.path.join(QUIZ_ASSET_FOLDER, bucket)
        dest = _safe_pack_child(dest_root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not os.path.isfile(dest):
            shutil.copy2(src, dest)
        return _quiz_asset_url(bucket, rel)
    except Exception:
        if strict:
            raise
        return value



def _review_candidates_for_topics(cur, topics):
    return _learning_service._review_candidates_for_topics(cur, topics)


def _smart_review_candidates(cur):
    return _learning_service._smart_review_candidates(
        cur,
        learning_intelligence_topics=_learning_intelligence_topics,
        review_candidates_for_topics=_review_candidates_for_topics,
    )


def _smart_review_select_candidates(candidates, weak, requested):
    return _learning_service._smart_review_select_candidates(
        candidates, weak, requested
    )


def _review_select_candidates(candidates, topics, requested):
    return _learning_service._review_select_candidates(
        candidates,
        topics,
        requested,
        smart_review_select_candidates=_smart_review_select_candidates,
    )


@app.route("/api/smart-review/preview")
def smart_review_preview_api():
    conn = get_db(); cur = conn.cursor()
    try:
        candidates, weak = _smart_review_candidates(cur)
        return jsonify({
            "weak_topics": [{"name": t["name"], "mastery": t["mastery"], "accuracy": t["accuracy"], "evidence": t["evidence"]} for t in weak],
            "candidate_questions": len(candidates),
            "questions": [{"question_id": c["question_id"], "question": c["question_text"], "topics": c["topic_names"]} for c in candidates[:50]],
        })
    finally:
        conn.close()


@app.route("/smart-review/generate", methods=["POST"])
def smart_review_generate():
    try:
        requested = int(request.form.get("question_count", "20"))
    except (TypeError, ValueError):
        requested = 20
    requested = max(3, min(requested, 50))

    conn = get_db(); cur = conn.cursor()
    try:
        candidates, weak = _smart_review_candidates(cur)
        if not weak:
            flash("No weak areas currently meet the evidence threshold. Keep practicing to build evidence.", "info")
            return redirect("/learning-intelligence")
        if not candidates:
            flash("Weak areas were detected, but no tagged source questions are available for review.", "error")
            return redirect("/learning-intelligence")
        selected = _smart_review_select_candidates(candidates, weak, requested)
        quiz_data = []
        for number, candidate in enumerate(selected, start=1):
            item = _question_payload_from_db(cur, candidate["question_id"])
            if not item:
                continue
            item["number"] = number
            quiz_data.append(item)
    finally:
        conn.close()

    if not quiz_data:
        flash("No usable source questions were available for Smart Review.", "error")
        return redirect("/learning-intelligence")

    topic_names = [t["name"] for t in weak[:3]]
    suffix = ", ".join(topic_names)
    if len(weak) > 3:
        suffix += f" +{len(weak)-3} more"
    quiz_title = f"Smart Review — {suffix}"
    quiz_id, html_name = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="smart_review",
        exam_minutes=90,
        snapshot_existing_assets=True,
    )
    return redirect(f"/quizzes/{html_name}")


@app.route("/review-schedule")
def review_schedule_page():
    return send_from_directory(app.static_folder, "review-schedule.html")


@app.route("/api/review-schedule")
def review_schedule_api():
    conn = get_db(); cur = conn.cursor()
    try:
        return jsonify(_review_schedule_payload(cur))
    finally:
        conn.close()


@app.route("/api/spaced-review/preview")
def spaced_review_preview_api():
    scope = str(request.args.get("scope") or "due").strip().lower()
    conn = get_db(); cur = conn.cursor()
    try:
        schedule = _review_schedule_payload(cur)
        topics = schedule.get("topics") or []
        if scope == "upcoming":
            chosen = [t for t in topics if t.get("review_state") in ("overdue", "due", "due_soon")]
        elif scope == "all":
            chosen = topics
        else:
            chosen = [t for t in topics if t.get("review_state") in ("overdue", "due")]
        candidates = _review_candidates_for_topics(cur, chosen)
        return jsonify({
            "scope": scope,
            "topics": [{"name": t["name"], "review_state": t["review_state"], "next_review": t["next_review"], "retained_mastery": t["retained_mastery"]} for t in chosen],
            "candidate_questions": len(candidates),
            "questions": [{"question_id": c["question_id"], "question": c["question_text"], "topics": c["topic_names"]} for c in candidates[:50]],
        })
    finally:
        conn.close()


@app.route("/spaced-review/generate", methods=["POST"])
def spaced_review_generate():
    try:
        requested = int(request.form.get("question_count", "20"))
    except (TypeError, ValueError):
        requested = 20
    requested = max(1, min(requested, 50))
    scope = str(request.form.get("scope") or "due").strip().lower()

    conn = get_db(); cur = conn.cursor()
    try:
        schedule = _review_schedule_payload(cur)
        topics = schedule.get("topics") or []
        if scope == "upcoming":
            chosen = [t for t in topics if t.get("review_state") in ("overdue", "due", "due_soon")]
        elif scope == "all":
            chosen = topics
        else:
            chosen = [t for t in topics if t.get("review_state") in ("overdue", "due")]
        if not chosen:
            flash("No topics match the selected spaced-review window yet.", "info")
            return redirect("/review-schedule")
        candidates = _review_candidates_for_topics(cur, chosen)
        if not candidates:
            flash("Review topics are scheduled, but no tagged source questions are available.", "error")
            return redirect("/review-schedule")
        selected = _review_select_candidates(candidates, chosen, requested)
        quiz_data = []
        for number, candidate in enumerate(selected, start=1):
            item = _question_payload_from_db(cur, candidate["question_id"])
            if not item:
                continue
            item["number"] = number
            quiz_data.append(item)
    finally:
        conn.close()

    if not quiz_data:
        flash("No usable source questions were available for Spaced Review.", "error")
        return redirect("/review-schedule")

    topic_names = [t["name"] for t in chosen[:3]]
    suffix = ", ".join(topic_names)
    if len(chosen) > 3:
        suffix += f" +{len(chosen)-3} more"
    quiz_title = f"Spaced Review — {suffix}"
    quiz_id, html_name = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="spaced_review",
        exam_minutes=90,
        snapshot_existing_assets=True,
    )
    return redirect(f"/quizzes/{html_name}")




def _response_selected_labels(value):
    return _learning_service._response_selected_labels(value)


def _question_diagnostics_payload(cur):
    return _learning_service._question_diagnostics_payload(
        cur,
        question_concepts=_question_concepts,
        response_selected_labels=_response_selected_labels,
    )


@app.route('/learning-diagnostics')
def learning_diagnostics_page():
    return send_from_directory(STATIC_ROOT, 'learning-diagnostics.html')


@app.route('/api/learning-diagnostics')
def learning_diagnostics_api():
    conn=get_db(); cur=conn.cursor()
    try:
        return jsonify(_question_diagnostics_payload(cur))
    finally:
        conn.close()


@app.route("/learning-profile")
def learning_profile_page():
    return send_from_directory(app.static_folder, "learning-profile.html")


@app.route("/api/learning-profile")
def learning_profile_api():
    conn = get_db(); cur = conn.cursor()
    try:
        return jsonify(_learning_profile_payload(cur))
    finally:
        conn.close()

@app.route("/learning-intelligence")
def learning_intelligence_page():
    return send_from_directory(app.static_folder, "learning-intelligence.html")


@app.route("/api/learning-intelligence/topics")
def learning_intelligence_topics_api():
    conn = get_db()
    cur = conn.cursor()
    try:
        return jsonify(_learning_intelligence_payload(cur))
    finally:
        conn.close()


def _quiz_history_origin(registry_entry, packs=None):
    return _history_service._quiz_history_origin(
        registry_entry,
        packs,
        discover_content_packs=discover_content_packs,
        is_medical_pack_manifest=_is_medical_pack_manifest,
        is_it_pack_manifest=_is_it_pack_manifest,
    )


_ATTEMPT_HISTORY_ORIGINS = _history_service.ATTEMPT_HISTORY_ORIGINS
_ATTEMPT_HISTORY_DEFAULT_PAGE_SIZE = _history_service.ATTEMPT_HISTORY_DEFAULT_PAGE_SIZE
_ATTEMPT_HISTORY_MAX_PAGE_SIZE = _history_service.ATTEMPT_HISTORY_MAX_PAGE_SIZE


def _attempt_history_context():
    installed_packs = discover_content_packs()
    return _history_service._attempt_history_context(
        load_registry(),
        installed_packs,
        quiz_history_origin=_quiz_history_origin,
    )


def _parse_attempt_pagination():
    return _history_service._parse_attempt_pagination(
        request.args,
        origins=_ATTEMPT_HISTORY_ORIGINS,
        default_page_size=_ATTEMPT_HISTORY_DEFAULT_PAGE_SIZE,
        max_page_size=_ATTEMPT_HISTORY_MAX_PAGE_SIZE,
    )


def _attempt_columns(cur):
    return _history_service._attempt_columns(cur)


def _attempt_origin_where(origin, origin_by_quiz_id):
    return _history_service._attempt_origin_where(origin, origin_by_quiz_id)


def _attempt_select_sql(has_attempt_id_col):
    return _history_service._attempt_select_sql(has_attempt_id_col)


def _attempt_summary_from_row(row, registry_map, installed_packs):
    return _history_service._attempt_summary_from_row(
        row,
        registry_map,
        installed_packs,
        quiz_history_origin=_quiz_history_origin,
    )


def _resolve_attempt_row(cur, attempt_reference, has_attempt_id_col=None):
    return _history_service._resolve_attempt_row(
        cur,
        attempt_reference,
        has_attempt_id_col,
        attempt_columns=_attempt_columns,
        attempt_select_sql=_attempt_select_sql,
    )


def _missed_rows_for_attempt(cur, attempt_row):
    return _history_service._missed_rows_for_attempt(cur, attempt_row)


@app.route("/api/attempts")
def api_attempts():
    try:
        page, page_size, origin = _parse_attempt_pagination()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    conn = get_db()
    try:
        return jsonify(_history_service.attempt_page(
            conn.cursor(),
            page,
            page_size,
            origin,
            attempt_columns=_attempt_columns,
            attempt_history_context=_attempt_history_context,
            attempt_origin_where=_attempt_origin_where,
            attempt_select_sql=_attempt_select_sql,
            attempt_summary_from_row=_attempt_summary_from_row,
        ))
    finally:
        conn.close()


@app.route("/api/attempts/overview")
def api_attempts_overview():
    conn = get_db()
    try:
        return jsonify(_history_service.attempt_overview(
            conn.cursor(),
            attempt_columns=_attempt_columns,
            attempt_history_context=_attempt_history_context,
            attempt_select_sql=_attempt_select_sql,
            attempt_summary_from_row=_attempt_summary_from_row,
        ))
    finally:
        conn.close()


@app.route("/api/attempts/analytics")
def api_attempts_analytics():
    conn = get_db()
    try:
        return jsonify(_history_service.attempt_analytics(
            conn.cursor(),
            attempt_columns=_attempt_columns,
            attempt_history_context=_attempt_history_context,
            attempt_summary_from_row=_attempt_summary_from_row,
        ))
    finally:
        conn.close()


@app.route("/api/attempts/<attempt_reference>")
def api_attempt_summary(attempt_reference):
    conn = get_db()
    try:
        summary = _history_service.attempt_summary(
            conn.cursor(),
            attempt_reference,
            attempt_columns=_attempt_columns,
            resolve_attempt_row=_resolve_attempt_row,
            attempt_history_context=_attempt_history_context,
            attempt_summary_from_row=_attempt_summary_from_row,
        )
        if summary is None:
            return jsonify({"error": "Attempt not found"}), 404
        return jsonify(summary)
    finally:
        conn.close()






# =====================================================
# ANKI EXPORT HELPERS
# =====================================================

import genanki
import random
import os
import tempfile
import html


def export_quiz_to_apkg(deck_name, deck_rows):
    return _anki_service.export_quiz_to_apkg(
        deck_name,
        deck_rows,
        genanki_module=genanki,
        random_module=random,
        tempfile_module=tempfile,
        os_module=os,
        html_module=html,
    )


def _remove_temp_anki_package(path):
    """Best-effort cleanup for a generated temporary Anki package."""
    return _anki_service._remove_temp_anki_package(
        path,
        os_module=os,
        print_message=print,
    )


def _send_temp_anki_package(apkg_path, download_name):
    """Stream a temporary package and remove it when the response closes."""
    try:
        response = send_file(
            apkg_path,
            as_attachment=True,
            download_name=download_name,
            mimetype="application/octet-stream"
        )
    except Exception:
        _remove_temp_anki_package(apkg_path)
        raise

    response.call_on_close(lambda: _remove_temp_anki_package(apkg_path))
    # send_file enables direct_passthrough, which bypasses Response.close and
    # therefore its call_on_close callbacks. Keep the response streamed while
    # ensuring the WSGI closing iterator closes the file before cleanup runs.
    response.direct_passthrough = False
    return response








# =====================================================
# ANKI TOOLS WORKSPACE
# =====================================================

def build_anki_rows_for_quiz(quiz_id):
    return _anki_service.build_anki_rows_for_quiz(quiz_id, get_db=get_db)


def build_anki_rows_for_missed(quiz_id=None, min_misses=1, status_filter="all"):
    return _anki_service.build_anki_rows_for_missed(
        quiz_id,
        min_misses,
        status_filter,
        get_db=get_db,
    )


def get_anki_missed_summary(quiz_id=None):
    return _anki_service.get_anki_missed_summary(
        quiz_id,
        build_rows_for_missed=build_anki_rows_for_missed,
    )

def parse_law_flashcards_text(raw_text):
    return _anki_service.parse_law_flashcards_text(raw_text)

def load_law_flashcards_for_case(case_id):
    case_entry = get_law_case_by_id(case_id)
    if not case_entry:
        return None, []

    case_file = secure_filename(case_entry.get("file") or "")
    if not case_file.lower().endswith(".json"):
        return None, []

    case_path = os.path.join(LAW_CASES_FOLDER, case_file)
    if not os.path.exists(case_path):
        return None, []

    try:
        case_data = _load_law_case_data(case_path)
    except Exception:
        return None, []

    sections = case_data.get("sections", {}) or {}
    flashcard_text = sections.get("rule_flashcards", "")
    cards = parse_law_flashcards_text(flashcard_text)

    meta = {
        "id": str(case_data.get("id") or case_id),
        "title": case_data.get("title") or case_entry.get("title") or "Law Study",
        "course": case_data.get("course") or case_entry.get("course") or "Uncategorized",
    }

    return meta, cards


def get_anki_quiz_choices():
    return _anki_service.get_anki_quiz_choices(get_db=get_db)


def get_anki_law_case_choices():
    return _anki_service.get_anki_law_case_choices(
        load_law_registry=load_law_registry,
        load_law_flashcards_for_case=load_law_flashcards_for_case,
    )



def get_anki_law_courses(law_cases=None):
    return _anki_service.get_anki_law_courses(
        law_cases,
        get_law_case_choices=get_anki_law_case_choices,
    )


def load_law_flashcards_for_selection(case_ids=None, course=None):
    return _anki_service.load_law_flashcards_for_selection(
        case_ids,
        course,
        get_law_case_choices=get_anki_law_case_choices,
        load_law_flashcards_for_case=load_law_flashcards_for_case,
    )



def get_anki_custom_sources():
    return _anki_service.get_anki_custom_sources(
        get_quiz_choices=get_anki_quiz_choices,
        build_rows_for_quiz=build_anki_rows_for_quiz,
        build_rows_for_missed=build_anki_rows_for_missed,
        get_law_case_choices=get_anki_law_case_choices,
        load_law_flashcards_for_case=load_law_flashcards_for_case,
    )


def build_custom_anki_rows(quiz_tokens=None, missed_tokens=None, law_tokens=None):
    return _anki_service.build_custom_anki_rows(
        quiz_tokens,
        missed_tokens,
        law_tokens,
        get_quiz_choices=get_anki_quiz_choices,
        build_rows_for_quiz=build_anki_rows_for_quiz,
        build_rows_for_missed=build_anki_rows_for_missed,
        get_law_case_choices=get_anki_law_case_choices,
        load_law_flashcards_for_case=load_law_flashcards_for_case,
    )


def make_safe_anki_download_name(name, fallback="dlms_anki_deck"):
    return _anki_service.make_safe_anki_download_name(
        name,
        fallback,
        secure_filename=secure_filename,
        os_module=os,
    )


def make_safe_anki_deck_name(name, fallback="DLMS Anki Deck"):
    return _anki_service.make_safe_anki_deck_name(name, fallback)


@app.route("/anki")
def anki_tools():
    quizzes = get_anki_quiz_choices()
    law_cases = get_anki_law_case_choices()

    anki_source = (request.args.get("source") or "").strip().lower()
    preview_rows = []
    preview_title = ""
    preview_message = ""

    selected_quiz_id = request.args.get("quiz_id", "")
    selected_missed_quiz = request.args.get("missed_quiz_id", "all")
    selected_min_misses = request.args.get("min_misses", "1")
    selected_missed_status = request.args.get("missed_status", "all")

    if anki_source == "quiz" and selected_quiz_id:
        quiz_title, preview_rows = build_anki_rows_for_quiz(selected_quiz_id)
        if quiz_title:
            preview_title = f"{quiz_title} - Quiz Deck"
        else:
            preview_message = "That quiz could not be found."

    elif anki_source == "missed":
        preview_rows = build_anki_rows_for_missed(
            selected_missed_quiz,
            selected_min_misses,
            selected_missed_status
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
            "Missed Questions"
        )
        if not preview_rows:
            preview_message = "No missed questions match those filters."

    missed_summary = get_anki_missed_summary()
    total_missed_cards = missed_summary["total"]
    total_law_cards = sum(case["card_count"] for case in law_cases)

    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Anki Tools - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home anki-tools-page">
<div class="dashboard-shell">

    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>

        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item active" href="/anki" aria-current="page"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck &amp; Printable Cards</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>

        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>

        <button class="dashboard-shutdown" id="shutdownBtn" type="button">
            <span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span>
        </button>
        <div class="dashboard-sidebar-version">DLMS v{{ app_version }}</div>
    </aside>

    <main class="dashboard-main anki-tools-main">
        <header class="dashboard-header anki-tools-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="anki-tools-eyebrow">STUDY EXPORTS</div>
                <h1>Anki Tools</h1>
                <p>Build Anki decks from existing quizzes and your DLMS performance history. Law Study exports are available from the Anki Tools submenu.</p>
            </div>
        </header>

        <section class="anki-tools-summary" aria-label="Anki Tools summary">
            <div class="dashboard-stat-card anki-summary-card" role="group" aria-labelledby="ankiQuizSummaryTitle">
                <p class="anki-summary-primary" id="ankiQuizSummaryTitle">
                    <span>Quizzes</span>
                    <strong>{{ quizzes|length }}</strong>
                </p>
                <span class="anki-summary-support">Available to export</span>
            </div>
            <div class="dashboard-stat-card anki-summary-card anki-missed-summary-card" role="group" aria-labelledby="ankiMissedSummaryTitle" aria-describedby="ankiMissedOverlapNote">
                <p class="anki-summary-primary anki-missed-summary-total" id="ankiMissedSummaryTitle">
                    <span>Questions Ever Missed:</span>
                    <strong>{{ total_missed_cards }}</strong>
                </p>
                <ul class="anki-missed-summary-metrics" aria-label="Missed-question details">
                    <li><strong>{{ missed_summary.currently_weak }}</strong> <span>not yet revisited</span></li>
                    <li><strong>{{ missed_summary.recovered }}</strong> <span>revisited later</span></li>
                    <li><strong>{{ missed_summary.repeated }}</strong> <span>missed more than once</span></li>
                </ul>
                <small class="anki-missed-summary-note" id="ankiMissedOverlapNote">Repeat count overlaps revisit status.</small>
            </div>
            <div class="dashboard-stat-card anki-summary-card" role="group" aria-labelledby="ankiLawSummaryTitle">
                <p class="anki-summary-primary" id="ankiLawSummaryTitle">
                    <span>Law Flashcards</span>
                    <strong>{{ total_law_cards }}</strong>
                </p>
                <span class="anki-summary-support">Recognized cards</span>
            </div>
        </section>

        <section class="anki-tools-grid">

            <article class="dashboard-panel anki-source-card">
                <div class="anki-source-heading">
                    <span class="anki-source-icon">▤</span>
                    <div>
                        <span class="anki-source-kicker">EXISTING QUIZ</span>
                        <h2>Quiz → Anki</h2>
                        <p>Create one card per quiz question with all choices on the front and the correct answer on the back.</p>
                    </div>
                </div>

                {% if quizzes %}
                <form method="GET" action="/anki" class="anki-source-form">
                    <input type="hidden" name="source" value="quiz">
                    <label>
                        <span>Source Quiz</span>
                        <select name="quiz_id" required>
                            <option value="">Choose a quiz...</option>
                            {% for quiz in quizzes %}
                            <option value="{{ quiz.id }}" {% if selected_quiz_id|string == quiz.id|string %}selected{% endif %}>
                                {{ quiz.title }} ({{ quiz.question_count }})
                            </option>
                            {% endfor %}
                        </select>
                    </label>
                    <button type="submit" class="anki-preview-button">Preview Cards</button>
                </form>

                <form method="POST" action="/anki/export/quiz" class="anki-export-form">
                    <label>
                        <span>Quiz to Export</span>
                        <select name="quiz_id" required>
                            <option value="">Choose a quiz...</option>
                            {% for quiz in quizzes %}
                            <option value="{{ quiz.id }}" {% if selected_quiz_id|string == quiz.id|string %}selected{% endif %}>
                                {{ quiz.title }}
                            </option>
                            {% endfor %}
                        </select>
                    </label>
                    <button type="submit" class="anki-export-button">Export .apkg</button>
                </form>
                {% else %}
                <div class="anki-empty-message">No quizzes are currently available.</div>
                {% endif %}
            </article>

            <article class="dashboard-panel anki-source-card">
                <div class="anki-source-heading">
                    <span class="anki-source-icon">↶</span>
                    <div>
                        <span class="anki-source-kicker">PERFORMANCE DATA</span>
                        <h2>Missed Questions → Anki</h2>
                        <p>Build a focused deck from questions DLMS has recorded as missed across your attempt history.</p>
                    </div>
                </div>

                <form method="GET" action="/anki" class="anki-source-form" id="missedAnkiForm">
                    <input type="hidden" name="source" value="missed">

                    <div class="anki-two-field-row">
                        <label>
                            <span>Quiz</span>
                            <select name="missed_quiz_id">
                                <option value="all" {% if selected_missed_quiz == "all" %}selected{% endif %}>All Quizzes</option>
                                {% for quiz in quizzes %}
                                <option value="{{ quiz.id }}" {% if selected_missed_quiz|string == quiz.id|string %}selected{% endif %}>
                                    {{ quiz.title }}
                                </option>
                                {% endfor %}
                            </select>
                        </label>

                        <label>
                            <span>Minimum Times Missed</span>
                            <input type="number" name="min_misses" value="{{ selected_min_misses }}" min="1" max="100">
                        </label>
                    </div>

                    <label>
                        <span>Focus</span>
                        <select name="missed_status">
                            <option value="all" {% if selected_missed_status == "all" %}selected{% endif %}>All Missed Questions</option>
                            <option value="currently_weak" {% if selected_missed_status == "currently_weak" %}selected{% endif %}>Currently Weak</option>
                            <option value="repeated" {% if selected_missed_status == "repeated" %}selected{% endif %}>Repeatedly Missed</option>
                            <option value="recovered" {% if selected_missed_status == "recovered" %}selected{% endif %}>Recovered Later</option>
                            <option value="once" {% if selected_missed_status == "once" %}selected{% endif %}>Missed Once</option>
                        </select>
                    </label>

                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                        <button type="submit" class="anki-preview-button">Preview Cards</button>
                        <button type="button" class="anki-export-button" id="exportMissedAnki">Export .apkg</button>
                    </div>
                </form>
            </article>


        </section>

        {% if anki_source %}
        <section class="dashboard-panel anki-preview-panel" id="ankiPreview">
            <div class="anki-preview-heading">
                <div>
                    <span class="anki-source-kicker">EXPORT PREVIEW</span>
                    <h2>{{ preview_title or "Preview" }}</h2>
                </div>
                <span class="anki-count-pill">{{ preview_rows|length }} card{% if preview_rows|length != 1 %}s{% endif %}</span>
            </div>

            {% if preview_message %}
            <div class="anki-empty-message">{{ preview_message }}</div>
            {% endif %}

            {% if preview_rows %}
            <div class="anki-preview-list">
                {% for card in preview_rows[:20] %}
                <article class="anki-preview-card">
                    <div class="anki-preview-number">Card {{ loop.index }}</div>
                    <div class="anki-card-side">
                        <span>FRONT</span>
                        <pre>{{ card.front }}</pre>
                    </div>
                    <div class="anki-card-side anki-card-back">
                        <span>BACK</span>
                        <pre>{{ card.back }}</pre>
                    </div>
                </article>
                {% endfor %}
            </div>

            {% if preview_rows|length > 20 %}
            <div class="anki-preview-more">
                Previewing the first 20 of {{ preview_rows|length }} cards. The export includes all matching cards.
            </div>
            {% endif %}
            {% endif %}
        </section>
        {% endif %}

    </main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");

if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));

    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}


const exportMissedAnki = document.getElementById("exportMissedAnki");

if (exportMissedAnki) {
    exportMissedAnki.addEventListener("click", () => {
        const form = document.getElementById("missedAnkiForm");
        if (!form) return;

        const quizSelect = form.querySelector('[name="missed_quiz_id"]');
        const minMisses = form.querySelector('[name="min_misses"]');
        const statusSelect = form.querySelector('[name="missed_status"]');

        const exportForm = document.createElement("form");
        exportForm.method = "POST";
        exportForm.action = "/anki/export/missed";
        exportForm.style.display = "none";

        const fields = {
            quiz_id: quizSelect ? quizSelect.value : "all",
            min_misses: minMisses ? minMisses.value : "1",
            missed_status: statusSelect ? statusSelect.value : "all"
        };

        Object.entries(fields).forEach(([name, value]) => {
            const input = document.createElement("input");
            input.type = "hidden";
            input.name = name;
            input.value = value;
            exportForm.appendChild(input);
        });

        window.dlmsProtectForm(exportForm);
        document.body.appendChild(exportForm);
        exportForm.submit();
    });
}

const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("Shut down DLMS? You will need to restart it manually.")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) {
            alert("Failed to shut down DLMS.");
        }
    });
}

if (window.location.hash === "#ankiPreview") {
    const preview = document.getElementById("ankiPreview");
    if (preview) preview.scrollIntoView({ behavior: "smooth", block: "start" });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>
""",
        app_version=APP_VERSION,
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




@app.route("/anki/custom", methods=["GET", "POST"])
def anki_custom_deck():
    sources = get_anki_custom_sources()

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
            f"quiz:{quiz.get('id')}:{card.get('question_id')}" in selected_quiz_tokens
            for card in quiz.get("cards", [])
        )
        quiz_groups.append(quiz_view)

    missed_cards = sources["missed_cards"]
    selected_missed_count = sum(
        (
            f"missed:{card.get('quiz_id')}:"
            f"{card.get('question_id') if card.get('question_id') is not None else card.get('question_number')}"
        ) in selected_missed_tokens
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
        preview_rows = build_custom_anki_rows(
            selected_quiz,
            selected_missed,
            selected_law,
        )

    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Custom Anki Deck - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home anki-tools-page">
<div class="dashboard-shell">

    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>

        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>

            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item active" href="/anki" aria-current="page"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem active" href="/anki/custom" aria-current="page"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck &amp; Printable Cards</span></a>
                    <a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>

        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>

        <button class="dashboard-shutdown" id="shutdownBtn" type="button">
            <span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span>
        </button>
        <div class="dashboard-sidebar-version">DLMS v{{ app_version }}</div>
    </aside>

    <main class="dashboard-main anki-tools-main">
        <header class="dashboard-header anki-tools-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="anki-tools-eyebrow">ANKI TOOLS · CUSTOM DECK</div>
                <h1>Build a Custom Anki Deck</h1>
                <p>Combine selected quiz questions, performance-history questions, and Law Study flashcards into one DLMS deck.</p>
            </div>
        </header>

        <form method="POST" class="anki-source-form" id="customAnkiForm">
            <section class="dashboard-panel anki-source-card anki-source-card-wide">
                <div class="anki-source-heading">
                    <span class="anki-source-icon">◆</span>
                    <div>
                        <span class="anki-source-kicker">DECK SETTINGS</span>
                        <h2>Name Your Deck</h2>
                        <p>The exported deck is flat in Anki and does not create nested subdecks.</p>
                    </div>
                </div>

                <label>
                    <span>Deck Name</span>
                    <input type="text"
                           class="anki-custom-deck-name"
                           name="deck_name"
                           value="{{ deck_name }}"
                           maxlength="120"
                           required
                           style="width:100%;min-height:42px;box-sizing:border-box;padding:9px 11px;border-radius:9px;font:inherit;">
                </label>
            </section>

            <section class="dashboard-panel anki-source-card anki-source-card-wide" style="margin-top:18px;">
                <div class="anki-source-heading">
                    <span class="anki-source-icon">▤</span>
                    <div>
                        <span class="anki-source-kicker">QUIZ LIBRARY</span>
                        <h2>Select Quiz Questions</h2>
                        <p>Open a quiz and choose only the questions you want in this custom deck.</p>
                    </div>
                </div>

                {% if quiz_groups %}
                    <div class="anki-custom-quiz-toolbar">
                        <label class="anki-custom-quiz-filter" for="ankiQuizFilter">
                            <span>Filter quizzes</span>
                            <input type="search"
                                   id="ankiQuizFilter"
                                   placeholder="Search by quiz name"
                                   autocomplete="off"
                                   aria-describedby="ankiQuizFilterStatus">
                        </label>
                        <div class="anki-custom-quiz-toolbar-actions" aria-label="Quiz accordion controls">
                            <button type="button" class="anki-custom-quiz-control" id="ankiExpandAllQuizzes" aria-controls="ankiQuizGroups">Expand All</button>
                            <button type="button" class="anki-custom-quiz-control" id="ankiCollapseAllQuizzes" aria-controls="ankiQuizGroups">Collapse All</button>
                        </div>
                        <span class="anki-custom-quiz-filter-status" id="ankiQuizFilterStatus" aria-live="polite">{{ quiz_groups|length }} quiz{% if quiz_groups|length != 1 %}zes{% endif %} shown</span>
                    </div>
                    <div id="ankiQuizGroups">
                    {% for quiz in quiz_groups %}
                    <details class="anki-custom-selection-group anki-custom-bulk-group anki-custom-quiz-group"
                             data-anki-selection-name="quiz_cards"
                             id="ankiQuizGroup{{ loop.index }}"
                             style="margin:10px 0;border-radius:11px;">
                        <summary class="anki-custom-selection-summary" style="cursor:pointer;padding:12px 14px;font-weight:700;">
                            <span class="anki-custom-quiz-title">{{ quiz.title }}</span>
                            <span class="anki-custom-quiz-summary-meta">
                                <span>{{ quiz.cards|length }} question{% if quiz.cards|length != 1 %}s{% endif %}</span>
                                <span class="anki-custom-quiz-selection-count" data-anki-group-selection-count data-anki-quiz-selection-count>{{ quiz.selected_count }} of {{ quiz.cards|length }} selected</span>
                            </span>
                        </summary>
                        <div class="anki-custom-quiz-content" id="ankiQuizQuestions{{ loop.index }}" style="padding:0 14px 12px;">
                            <div class="anki-custom-quiz-bulk-actions" aria-label="Question selection controls for {{ quiz.title }}">
                                <button type="button" class="anki-custom-quiz-control" data-anki-group-select-all data-anki-quiz-select-all aria-controls="ankiQuizQuestions{{ loop.index }}">Select All Questions</button>
                                <button type="button" class="anki-custom-quiz-control" data-anki-group-clear data-anki-quiz-clear aria-controls="ankiQuizQuestions{{ loop.index }}" {% if quiz.selected_count == 0 %}disabled{% endif %}>Clear Quiz Selection</button>
                            </div>
                            {% for card in quiz.cards %}
                            {% set token = "quiz:" ~ quiz.id ~ ":" ~ card.question_id %}
                            <label class="anki-custom-selection-row" style="display:flex;gap:10px;align-items:flex-start;padding:9px 0;">
                                <input type="checkbox" name="quiz_cards" value="{{ token }}" {% if token in selected_quiz %}checked{% endif %}>
                                <span><strong>Q{{ card.question_number }}</strong> · {{ card.front.split("\n")[0] }}</span>
                            </label>
                            {% endfor %}
                        </div>
                    </details>
                    {% endfor %}
                    </div>
                {% else %}
                    <div class="anki-empty-message">No quizzes are currently available.</div>
                {% endif %}
            </section>

            <section class="dashboard-panel anki-source-card anki-source-card-wide" style="margin-top:18px;">
                <div class="anki-source-heading">
                    <span class="anki-source-icon">↶</span>
                    <div>
                        <span class="anki-source-kicker">PERFORMANCE DATA</span>
                        <h2>Select Missed / Weak Questions</h2>
                        <p>Add individual questions from your DLMS attempt history. Status and miss counts are shown for context.</p>
                    </div>
                </div>

                {% if missed_cards %}
                <details open class="anki-custom-selection-group anki-custom-bulk-group anki-custom-performance-group"
                         data-anki-selection-name="missed_cards"
                         id="ankiPerformanceGroup"
                         style="margin:10px 0;border-radius:11px;">
                    <summary class="anki-custom-selection-summary" style="cursor:pointer;padding:12px 14px;font-weight:700;">
                        <span>Performance History</span>
                        <span class="anki-custom-quiz-summary-meta">
                            <span>{{ missed_cards|length }} unique missed question{% if missed_cards|length != 1 %}s{% endif %}</span>
                            <span class="anki-custom-quiz-selection-count" id="ankiPerformanceSelectionCount" data-anki-group-selection-count>{{ selected_missed_count }} of {{ missed_cards|length }} selected</span>
                        </span>
                    </summary>
                    <div class="anki-custom-quiz-content" id="ankiPerformanceQuestions" style="padding:0 14px 12px;max-height:420px;overflow:auto;">
                        <div class="anki-custom-quiz-bulk-actions" aria-label="Performance History question selection controls">
                            <button type="button" class="anki-custom-quiz-control" data-anki-group-select-all aria-controls="ankiPerformanceQuestions">Select All Questions</button>
                            <button type="button" class="anki-custom-quiz-control" data-anki-group-clear aria-controls="ankiPerformanceQuestions" {% if selected_missed_count == 0 %}disabled{% endif %}>Clear Performance Selection</button>
                        </div>
                        {% for card in missed_cards %}
                        {% set stable_id = card.question_id if card.question_id is not none else card.question_number %}
                        {% set token = "missed:" ~ card.quiz_id ~ ":" ~ stable_id %}
                        <label class="anki-custom-selection-row" style="display:flex;gap:10px;align-items:flex-start;padding:9px 0;">
                            <input type="checkbox" name="missed_cards" value="{{ token }}" {% if token in selected_missed %}checked{% endif %}>
                            <span>
                                <strong>{{ card.quiz_title }} · Q{{ card.question_number }}</strong><br>
                                {{ card.front.split("\n")[0] }}
                                <small class="anki-custom-selection-meta" style="display:block;margin-top:3px;">
                                    {{ card.miss_count }} miss{% if card.miss_count != 1 %}es{% endif %} ·
                                    {% if card.recovery_status == "currently_weak" %}Currently Weak{% else %}Recovered Later{% endif %}
                                </small>
                            </span>
                        </label>
                        {% endfor %}
                    </div>
                </details>
                {% else %}
                    <div class="anki-empty-message">No missed-question history is currently available.</div>
                {% endif %}
            </section>

            <section class="dashboard-panel anki-source-card anki-source-card-wide" style="margin-top:18px;">
                <div class="anki-source-heading">
                    <span class="anki-source-icon">⚖</span>
                    <div>
                        <span class="anki-source-kicker">LAW STUDY</span>
                        <h2>Select Law Flashcards</h2>
                        <p>Choose individual Rule Flashcards from saved Law Study cases.</p>
                    </div>
                </div>

                {% if law_groups %}
                    <div class="anki-custom-quiz-toolbar">
                        <label class="anki-custom-quiz-filter" for="ankiLawFilter">
                            <span>Filter cases</span>
                            <input type="search"
                                   id="ankiLawFilter"
                                   placeholder="Search by case or course"
                                   autocomplete="off"
                                   aria-describedby="ankiLawFilterStatus">
                        </label>
                        <div class="anki-custom-quiz-toolbar-actions" aria-label="Law Study case accordion controls">
                            <button type="button" class="anki-custom-quiz-control" id="ankiExpandAllLawCases" aria-controls="ankiLawGroups">Expand All</button>
                            <button type="button" class="anki-custom-quiz-control" id="ankiCollapseAllLawCases" aria-controls="ankiLawGroups">Collapse All</button>
                        </div>
                        <span class="anki-custom-quiz-filter-status" id="ankiLawFilterStatus" aria-live="polite">{{ law_groups|length }} case{% if law_groups|length != 1 %}s{% endif %} shown</span>
                    </div>
                    <div id="ankiLawGroups">
                    {% for case in law_groups %}
                    <details class="anki-custom-selection-group anki-custom-bulk-group anki-custom-law-group"
                             data-anki-selection-name="law_cards"
                             id="ankiLawGroup{{ loop.index }}"
                             style="margin:10px 0;border-radius:11px;">
                        <summary class="anki-custom-selection-summary" style="cursor:pointer;padding:12px 14px;font-weight:700;">
                            <span class="anki-custom-law-title">{{ case.course }} · {{ case.title }}</span>
                            <span class="anki-custom-quiz-summary-meta">
                                <span>{{ case.cards|length }} card{% if case.cards|length != 1 %}s{% endif %}</span>
                                <span class="anki-custom-quiz-selection-count" id="ankiLawSelectionCount{{ loop.index }}" data-anki-group-selection-count>{{ case.selected_count }} of {{ case.cards|length }} selected</span>
                            </span>
                        </summary>
                        <div class="anki-custom-quiz-content" id="ankiLawCards{{ loop.index }}" style="padding:0 14px 12px;">
                            <div class="anki-custom-quiz-bulk-actions" aria-label="Card selection controls for {{ case.course }} · {{ case.title }}">
                                <button type="button" class="anki-custom-quiz-control" data-anki-group-select-all aria-controls="ankiLawCards{{ loop.index }}">Select All Cards</button>
                                <button type="button" class="anki-custom-quiz-control" data-anki-group-clear aria-controls="ankiLawCards{{ loop.index }}" {% if case.selected_count == 0 %}disabled{% endif %}>Clear Case Selection</button>
                            </div>
                            {% for card in case.cards %}
                            {% set token = "law:" ~ case.id ~ ":" ~ loop.index %}
                            <label class="anki-custom-selection-row" style="display:flex;gap:10px;align-items:flex-start;padding:9px 0;">
                                <input type="checkbox" name="law_cards" value="{{ token }}" {% if token in selected_law %}checked{% endif %}>
                                <span><strong>Card {{ loop.index }}</strong> · {{ card.front.split("\n")[0] }}</span>
                            </label>
                            {% endfor %}
                        </div>
                    </details>
                    {% endfor %}
                    </div>
                {% else %}
                    <div class="anki-empty-message">No recognized Law Study flashcards are currently available.</div>
                {% endif %}
            </section>

            <section class="dashboard-panel anki-source-card anki-source-card-wide" id="printableCards" style="margin-top:18px;">
                <div class="anki-source-heading">
                    <span class="anki-source-icon">▤</span>
                    <div>
                        <span class="anki-source-kicker">PRINTABLE FLASHCARDS</span>
                        <h2>Avery 5388 · 3 × 5 Index Cards</h2>
                        <p>Use the same selected DLMS cards for Anki or a browser-printable 3-card-per-sheet Avery layout.</p>
                    </div>
                </div>
                <div class="anki-two-field-row" style="margin:12px 0 14px;">
                    <label><span>Template</span><select disabled><option>Avery 5388 — 3 × 5, 3 per sheet</option></select></label>
                    <label><span>Duplex flip</span><select name="duplex_flip"><option value="long">Long edge — same card order</option><option value="short">Short edge — reverse back order</option></select></label>
                </div>
                <div class="anki-custom-selection-toolbar" aria-label="Selected card controls">
                    <span class="anki-custom-selection-count" id="ankiSelectedCount" aria-live="polite">0 cards selected</span>
                    <button type="button" class="anki-clear-selection-button" id="ankiClearSelection" disabled>Clear Selected Cards</button>
                </div>
                <div class="anki-action-grid anki-action-grid-three">
                    <button type="submit" class="anki-preview-button" formaction="/anki/custom" formmethod="POST">Preview Deck</button>
                    <button type="submit" class="anki-export-button" formaction="/anki/export/custom" formmethod="POST">Export .apkg</button>
                    <button type="submit" class="anki-export-button printable-flashcard-button" formaction="/anki/printable" formmethod="POST" formtarget="_blank">Open Avery Print Layout</button>
                </div>
                <div class="anki-print-note">Official Avery 5388 stock uses 3 × 5 inch cards, 3 cards per US Letter sheet. Print one duplex test sheet before a large batch.</div>
            </section>
        </form>

        {% if preview_requested %}
        <section class="dashboard-panel anki-preview-panel" id="ankiPreview">
            <div class="anki-preview-heading">
                <div>
                    <span class="anki-source-kicker">CUSTOM DECK PREVIEW</span>
                    <h2>{{ deck_name }}</h2>
                </div>
                <span class="anki-count-pill">{{ preview_rows|length }} card{% if preview_rows|length != 1 %}s{% endif %}</span>
            </div>

            {% if not preview_rows %}
                <div class="anki-empty-message">Select at least one DLMS item to build this deck.</div>
            {% else %}
                <div class="anki-preview-list">
                    {% for card in preview_rows[:20] %}
                    <article class="anki-preview-card">
                        <div class="anki-preview-number">Card {{ loop.index }}</div>
                        <div class="anki-card-side">
                            <span>FRONT</span>
                            <pre>{{ card.front }}</pre>
                        </div>
                        <div class="anki-card-side anki-card-back">
                            <span>BACK</span>
                            <pre>{{ card.back }}</pre>
                        </div>
                    </article>
                    {% endfor %}
                </div>

                {% if preview_rows|length > 20 %}
                <div class="anki-preview-more">
                    Previewing the first 20 of {{ preview_rows|length }} cards. The export includes all selected cards.
                </div>
                {% endif %}
            {% endif %}
        </section>
        {% endif %}
    </main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");

if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));

    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}

const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("Shut down DLMS? You will need to restart it manually.")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) {
            alert("Failed to shut down DLMS.");
        }
    });
}

const customAnkiForm = document.getElementById("customAnkiForm");
const ankiSelectedCount = document.getElementById("ankiSelectedCount");
const ankiClearSelection = document.getElementById("ankiClearSelection");
const ankiQuizFilter = document.getElementById("ankiQuizFilter");
const ankiQuizFilterStatus = document.getElementById("ankiQuizFilterStatus");
const ankiExpandAllQuizzes = document.getElementById("ankiExpandAllQuizzes");
const ankiCollapseAllQuizzes = document.getElementById("ankiCollapseAllQuizzes");
const ankiLawFilter = document.getElementById("ankiLawFilter");
const ankiLawFilterStatus = document.getElementById("ankiLawFilterStatus");
const ankiExpandAllLawCases = document.getElementById("ankiExpandAllLawCases");
const ankiCollapseAllLawCases = document.getElementById("ankiCollapseAllLawCases");
const ankiPerformanceGroup = document.getElementById("ankiPerformanceGroup");
const ankiPerformanceOpenStateKey = "dlms.anki.custom.performanceHistory.openState.v1";
const customAnkiCardSelections = customAnkiForm
    ? Array.from(customAnkiForm.querySelectorAll('input[type="checkbox"][name$="_cards"]'))
    : [];
const customAnkiSelectionGroups = customAnkiForm
    ? Array.from(customAnkiForm.querySelectorAll(".anki-custom-bulk-group"))
    : [];
const customAnkiQuizGroups = customAnkiForm
    ? Array.from(customAnkiForm.querySelectorAll(".anki-custom-quiz-group"))
    : [];
const customAnkiLawGroups = customAnkiForm
    ? Array.from(customAnkiForm.querySelectorAll(".anki-custom-law-group"))
    : [];

function readCustomAnkiPerformanceOpenState() {
    try {
        const savedState = JSON.parse(localStorage.getItem(ankiPerformanceOpenStateKey) || "null");
        return typeof savedState === "boolean" ? savedState : null;
    } catch (error) {
        return null;
    }
}

if (ankiPerformanceGroup) {
    const savedOpenState = readCustomAnkiPerformanceOpenState();
    if (savedOpenState !== null) ankiPerformanceGroup.open = savedOpenState;
    ankiPerformanceGroup.addEventListener("toggle", () => {
        try {
            localStorage.setItem(
                ankiPerformanceOpenStateKey,
                JSON.stringify(ankiPerformanceGroup.open),
            );
        } catch (error) {}
    });
}

function getCustomAnkiGroupSelections(selectionGroup) {
    const selectionName = selectionGroup.dataset.ankiSelectionName;
    return Array.from(selectionGroup.querySelectorAll('input[type="checkbox"]'))
        .filter(checkbox => checkbox.name === selectionName);
}

function updateCustomAnkiGroupSelectionCount(selectionGroup) {
    const groupSelections = getCustomAnkiGroupSelections(selectionGroup);
    const selectedCount = groupSelections.filter(checkbox => checkbox.checked).length;
    const selectionCount = selectionGroup.querySelector("[data-anki-group-selection-count]");
    const selectAll = selectionGroup.querySelector("[data-anki-group-select-all]");
    const clearSelection = selectionGroup.querySelector("[data-anki-group-clear]");
    if (selectionCount) {
        selectionCount.textContent = `${selectedCount} of ${groupSelections.length} selected`;
    }
    if (selectAll) selectAll.disabled = groupSelections.length === 0 || selectedCount === groupSelections.length;
    if (clearSelection) clearSelection.disabled = selectedCount === 0;
}

function updateCustomAnkiSelectionCount(changedSelectionGroup = null) {
    const selectedCount = customAnkiCardSelections.filter(checkbox => checkbox.checked).length;
    if (ankiSelectedCount) {
        ankiSelectedCount.textContent = `${selectedCount} card${selectedCount === 1 ? "" : "s"} selected`;
    }
    if (ankiClearSelection) ankiClearSelection.disabled = selectedCount === 0;
    if (changedSelectionGroup) updateCustomAnkiGroupSelectionCount(changedSelectionGroup);
    else customAnkiSelectionGroups.forEach(updateCustomAnkiGroupSelectionCount);
}

function visibleCustomAnkiQuizGroups() {
    return customAnkiQuizGroups.filter(quizGroup => !quizGroup.hidden);
}

function updateCustomAnkiQuizFilter() {
    const query = (ankiQuizFilter?.value || "").trim().toLocaleLowerCase();
    let visibleCount = 0;
    customAnkiQuizGroups.forEach(quizGroup => {
        const title = quizGroup.querySelector(".anki-custom-quiz-title")?.textContent || "";
        const matches = !query || title.toLocaleLowerCase().includes(query);
        quizGroup.hidden = !matches;
        if (matches) visibleCount += 1;
    });
    if (ankiQuizFilterStatus) {
        const total = customAnkiQuizGroups.length;
        ankiQuizFilterStatus.textContent = query
            ? `${visibleCount} of ${total} quizzes shown`
            : `${total} quiz${total === 1 ? "" : "zes"} shown`;
    }
    const noVisibleQuizzes = visibleCount === 0;
    if (ankiExpandAllQuizzes) ankiExpandAllQuizzes.disabled = noVisibleQuizzes;
    if (ankiCollapseAllQuizzes) ankiCollapseAllQuizzes.disabled = noVisibleQuizzes;
}

customAnkiCardSelections.forEach(checkbox => {
    checkbox.addEventListener("change", () => {
        updateCustomAnkiSelectionCount(checkbox.closest(".anki-custom-bulk-group"));
    });
});

customAnkiSelectionGroups.forEach(selectionGroup => {
    const groupSelections = getCustomAnkiGroupSelections(selectionGroup);
    selectionGroup.querySelector("[data-anki-group-select-all]")?.addEventListener("click", () => {
        groupSelections.forEach(checkbox => { checkbox.checked = true; });
        updateCustomAnkiSelectionCount(selectionGroup);
    });
    selectionGroup.querySelector("[data-anki-group-clear]")?.addEventListener("click", () => {
        groupSelections.forEach(checkbox => { checkbox.checked = false; });
        updateCustomAnkiSelectionCount(selectionGroup);
    });
});

ankiQuizFilter?.addEventListener("input", updateCustomAnkiQuizFilter);
ankiExpandAllQuizzes?.addEventListener("click", () => {
    visibleCustomAnkiQuizGroups().forEach(quizGroup => { quizGroup.open = true; });
});
ankiCollapseAllQuizzes?.addEventListener("click", () => {
    visibleCustomAnkiQuizGroups().forEach(quizGroup => { quizGroup.open = false; });
});

function visibleCustomAnkiLawGroups() {
    return customAnkiLawGroups.filter(lawGroup => !lawGroup.hidden);
}

function updateCustomAnkiLawFilter() {
    const query = (ankiLawFilter?.value || "").trim().toLocaleLowerCase();
    let visibleCount = 0;
    customAnkiLawGroups.forEach(lawGroup => {
        const title = lawGroup.querySelector(".anki-custom-law-title")?.textContent || "";
        const matches = !query || title.toLocaleLowerCase().includes(query);
        lawGroup.hidden = !matches;
        if (matches) visibleCount += 1;
    });
    if (ankiLawFilterStatus) {
        const total = customAnkiLawGroups.length;
        ankiLawFilterStatus.textContent = query
            ? `${visibleCount} of ${total} cases shown`
            : `${total} case${total === 1 ? "" : "s"} shown`;
    }
    const noVisibleCases = visibleCount === 0;
    if (ankiExpandAllLawCases) ankiExpandAllLawCases.disabled = noVisibleCases;
    if (ankiCollapseAllLawCases) ankiCollapseAllLawCases.disabled = noVisibleCases;
}

ankiLawFilter?.addEventListener("input", updateCustomAnkiLawFilter);
ankiExpandAllLawCases?.addEventListener("click", () => {
    visibleCustomAnkiLawGroups().forEach(lawGroup => { lawGroup.open = true; });
});
ankiCollapseAllLawCases?.addEventListener("click", () => {
    visibleCustomAnkiLawGroups().forEach(lawGroup => { lawGroup.open = false; });
});

if (ankiClearSelection) {
    ankiClearSelection.addEventListener("click", () => {
        customAnkiCardSelections.forEach(checkbox => { checkbox.checked = false; });
        updateCustomAnkiSelectionCount();
    });
}

updateCustomAnkiSelectionCount();
updateCustomAnkiQuizFilter();
updateCustomAnkiLawFilter();

if (window.location.hash === "#ankiPreview" || {{ "true" if preview_requested else "false" }}) {
    const preview = document.getElementById("ankiPreview");
    if (preview) preview.scrollIntoView({ behavior: "smooth", block: "start" });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>
""",
        app_version=APP_VERSION,
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


@app.route("/anki/export/custom", methods=["POST"])
def anki_export_custom():
    deck_name = (request.form.get("deck_name") or "DLMS Custom Deck").strip()

    deck_rows = build_custom_anki_rows(
        request.form.getlist("quiz_cards"),
        request.form.getlist("missed_cards"),
        request.form.getlist("law_cards"),
    )

    if not deck_rows:
        return "Select at least one DLMS item before exporting a custom deck.", 400

    apkg_path = export_quiz_to_apkg(deck_name, deck_rows)

    return _send_temp_anki_package(
        apkg_path,
        make_safe_anki_download_name(
            deck_name,
            "DLMS_Custom_Deck"
        )
    )



def _chunk_printable_cards(rows, size=3):
    rows = list(rows or [])
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def _printable_back_sheet(cards, duplex_flip="long"):
    cards = list(cards or [])
    if duplex_flip == "short":
        return list(reversed(cards))
    return cards


@app.route("/anki/printable", methods=["POST"])
def anki_printable_flashcards():
    deck_name = (request.form.get("deck_name") or "DLMS Printable Flashcards").strip()
    duplex_flip = (request.form.get("duplex_flip") or "long").strip().lower()
    if duplex_flip not in {"long", "short"}:
        duplex_flip = "long"

    rows = build_custom_anki_rows(
        request.form.getlist("quiz_cards"),
        request.form.getlist("missed_cards"),
        request.form.getlist("law_cards"),
    )
    if not rows:
        return "Select at least one DLMS item before creating printable flashcards.", 400

    sheets = []
    for sheet_number, cards in enumerate(_chunk_printable_cards(rows, 3), start=1):
        sheets.append({
            "number": sheet_number,
            "fronts": cards,
            "backs": _printable_back_sheet(cards, duplex_flip),
        })

    return render_template_string(r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ deck_name }} — Avery 5388 Print Layout</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#e7ebef;color:#111;font-family:Arial,Helvetica,sans-serif}
.print-toolbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 18px;background:#0a1b31;color:white;box-shadow:0 2px 12px rgba(0,0,0,.25)}
.print-toolbar h1{font-size:18px;margin:0}.print-toolbar p{margin:3px 0 0;font-size:12px;color:#c9d5e3}.print-toolbar button{border:0;border-radius:8px;background:#188fe0;color:white;font-weight:800;padding:10px 16px;cursor:pointer}
.print-note{max-width:8.5in;margin:18px auto;padding:12px 16px;background:#fff7d8;border:1px solid #d4b656;border-radius:8px;font-size:13px;line-height:1.45}
.avery-sheet{position:relative;width:8.5in;height:11in;margin:18px auto;background:white;padding:1in 1.75in;display:flex;flex-direction:column;box-shadow:0 4px 18px rgba(0,0,0,.18);overflow:hidden}
.sheet-label{position:absolute;top:.25in;left:.35in;font-size:10px;color:#777}
.avery-card{width:5in;height:3in;flex:0 0 3in;border:1px dashed #a7a7a7;padding:.20in .24in;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-start;background:white}
.avery-card pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:11pt/1.28 Arial,Helvetica,sans-serif}
.avery-card.compact pre{font-size:9.5pt;line-height:1.2}
.card-side-label{font-size:8pt;letter-spacing:.08em;font-weight:800;color:#777;margin-bottom:.10in}
@page{size:Letter portrait;margin:0}
@media print{
 body{background:white}.print-toolbar,.print-note,.sheet-label,.card-side-label{display:none!important}
 .avery-sheet{margin:0;box-shadow:none;page-break-after:always;break-after:page}
 .avery-sheet:last-child{page-break-after:auto;break-after:auto}
 .avery-card{border-color:transparent}
}
</style>
</head>
<body>
<div class="print-toolbar"><div><h1>{{ deck_name }}</h1><p>Avery 5388 · 3 × 5 in · 3 cards per US Letter sheet · {{ rows|length }} cards</p></div><button type="button" onclick="window.print()">Print Cards</button></div>
<div class="print-note"><strong>Duplex guidance:</strong> This layout alternates each front sheet with its matching back sheet. Your selected setting is <strong>{{ 'long-edge' if duplex_flip == 'long' else 'short-edge' }} flip</strong>. Print one test sheet before a large run and use your printer's cardstock/index-card setting when available.</div>
{% for sheet in sheets %}
<section class="avery-sheet front-sheet"><div class="sheet-label">Sheet {{ sheet.number }} fronts</div>
{% for card in sheet.fronts %}<article class="avery-card {% if card.front|length > 850 %}compact{% endif %}"><div class="card-side-label">FRONT</div><pre>{{ card.front }}</pre></article>{% endfor %}
{% for _ in range(3 - sheet.fronts|length) %}<article class="avery-card"></article>{% endfor %}
</section>
<section class="avery-sheet back-sheet"><div class="sheet-label">Sheet {{ sheet.number }} backs</div>
{% for card in sheet.backs %}<article class="avery-card {% if card.back|length > 850 %}compact{% endif %}"><div class="card-side-label">BACK</div><pre>{{ card.back }}</pre></article>{% endfor %}
{% for _ in range(3 - sheet.backs|length) %}<article class="avery-card"></article>{% endfor %}
</section>
{% endfor %}
</body></html>
""", deck_name=deck_name, rows=rows, sheets=sheets, duplex_flip=duplex_flip)


@app.route("/anki/law")
def anki_law_tools():
    law_cases = get_anki_law_case_choices()
    law_courses = get_anki_law_courses(law_cases)

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
                selection_meta, preview_rows = load_law_flashcards_for_selection(
                    course=selected_law_course
                )
                preview_title = f"{selected_law_course} - Rule Flashcards"
                if not preview_rows:
                    preview_message = "No recognized Rule Flashcards were found for that course."
            else:
                preview_message = "Choose a course before previewing."

        else:
            if selected_case_ids:
                selection_meta, preview_rows = load_law_flashcards_for_selection(
                    case_ids=selected_case_ids
                )
                case_count = selection_meta.get("case_count", 0)
                preview_title = (
                    f"{case_count} Saved Cases - Rule Flashcards"
                    if case_count != 1
                    else "Saved Case - Rule Flashcards"
                )
                if not preview_rows:
                    preview_message = "No recognized Rule Flashcards were found in the selected cases."
            else:
                preview_message = "Choose at least one saved case before previewing."

    total_law_cards = sum(case["card_count"] for case in law_cases)

    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Law Study Anki - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home anki-tools-page">
<div class="dashboard-shell">

    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                    <path d="M4 5.5 12 3l8 2.5v5.7c0 4.9-3.3 8.1-8 9.8-4.7-1.7-8-4.9-8-9.8V5.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/>
                    <path d="m8 12 2.3-2.4 2.1 2.1L16 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="dashboard-brand-title">DLMS</div>
                <div class="dashboard-brand-subtitle">Training Center</div>
            </div>
        </div>

        <nav class="dashboard-nav" aria-label="Primary navigation">
            <a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
            <a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
            <a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
            <a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
            <a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
            {% if medical_pack_installed %}
            <a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
            <div class="dashboard-nav-submenu medical-global-submenu">
                <a class="dashboard-nav-subitem" href="/medical/matching"><span class="dashboard-nav-subicon">↳</span><span>Terminology &amp; Matching</span></a>
                <a class="dashboard-nav-subitem" href="/medical/anatomy"><span class="dashboard-nav-subicon">↳</span><span>Anatomy &amp; Images</span></a>
                <a class="dashboard-nav-subitem" href="/study-packs/ai-builder?domain=Medical&amp;from=medical"><span class="dashboard-nav-subicon">↳</span><span>AI Study Pack Builder</span></a>
            </div>
            {% endif %}
            <a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
            <a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
            <div class="dashboard-nav-group">
                <a class="dashboard-nav-item active" href="/anki" aria-current="page"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu">
                    <a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck &amp; Printable Cards</span></a>
                    <a class="dashboard-nav-subitem active" href="/anki/law" aria-current="page"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a>
                </div>
            </div>
        </nav>

        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>

        <button class="dashboard-shutdown" id="shutdownBtn" type="button">
            <span class="dashboard-shutdown-icon">⏻</span><span>Shutdown DLMS</span>
        </button>
        <div class="dashboard-sidebar-version">DLMS v{{ app_version }}</div>
    </aside>

    <main class="dashboard-main anki-tools-main">
        <header class="dashboard-header anki-tools-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation" aria-controls="dashboardSidebar" aria-expanded="false">☰</button>
            <div>
                <div class="anki-tools-eyebrow">ANKI TOOLS · LAW STUDY</div>
                <h1>Law Study → Anki</h1>
                <p>Build a focused Anki deck from one case, several saved cases, or an entire Law Study course.</p>
            </div>
        </header>

        <section class="anki-tools-summary" aria-label="Law Anki summary">
            <div class="dashboard-stat-card">
                <span class="dashboard-stat-label">Saved Cases</span>
                <strong>{{ law_cases|length }}</strong>
                <span class="dashboard-stat-note">available case reviews</span>
            </div>
            <div class="dashboard-stat-card">
                <span class="dashboard-stat-label">Courses</span>
                <strong>{{ law_courses|length }}</strong>
                <span class="dashboard-stat-note">with saved cases</span>
            </div>
            <div class="dashboard-stat-card">
                <span class="dashboard-stat-label">Law Flashcards</span>
                <strong>{{ total_law_cards }}</strong>
                <span class="dashboard-stat-note">recognized cards</span>
            </div>
        </section>

        <section class="dashboard-panel anki-source-card anki-source-card-wide">
            <div class="anki-source-heading">
                <span class="anki-source-icon">⚖</span>
                <div>
                    <span class="anki-source-kicker">LAW STUDY EXPORT</span>
                    <h2>Choose Your Deck Source</h2>
                    <p>Select individual cases or an entire course. Preview cards before creating the .apkg file.</p>
                </div>
            </div>

            {% if law_cases %}
            <form method="GET" action="/anki/law" class="anki-source-form" id="lawAnkiForm">
                <input type="hidden" name="preview" value="1">

                <label>
                    <span>Export Scope</span>
                    <select name="law_scope">
                        <option value="cases" {% if selected_law_scope == "cases" %}selected{% endif %}>Selected Cases</option>
                        <option value="course" {% if selected_law_scope == "course" %}selected{% endif %}>Entire Course</option>
                    </select>
                </label>

                <label>
                    <span>Saved Cases — Ctrl/Cmd-click to select more than one</span>
                    <select name="case_ids" multiple size="6">
                        {% for case in law_cases %}
                        <option value="{{ case.id }}" {% if case.id in selected_case_ids %}selected{% endif %}>
                            {{ case.course }} · {{ case.title }} ({{ case.card_count }})
                        </option>
                        {% endfor %}
                    </select>
                </label>

                <label>
                    <span>Course</span>
                    <select name="law_course">
                        <option value="">Choose a course...</option>
                        {% for course in law_courses %}
                        <option value="{{ course.course }}" {% if selected_law_course == course.course %}selected{% endif %}>
                            {{ course.course }} · {{ course.case_count }} cases · {{ course.card_count }} cards
                        </option>
                        {% endfor %}
                    </select>
                </label>

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <button type="submit" class="anki-preview-button">Preview Cards</button>
                    <button type="button" class="anki-export-button" id="exportLawAnki">Export .apkg</button>
                </div>
            </form>
            {% else %}
            <div class="anki-empty-message">No saved Law Study cases are currently available.</div>
            {% endif %}
        </section>

        {% if preview_requested %}
        <section class="dashboard-panel anki-preview-panel" id="ankiPreview">
            <div class="anki-preview-heading">
                <div>
                    <span class="anki-source-kicker">EXPORT PREVIEW</span>
                    <h2>{{ preview_title or "Law Study Preview" }}</h2>
                </div>
                <span class="anki-count-pill">{{ preview_rows|length }} card{% if preview_rows|length != 1 %}s{% endif %}</span>
            </div>

            {% if preview_message %}
            <div class="anki-empty-message">{{ preview_message }}</div>
            {% endif %}

            {% if preview_rows %}
            <div class="anki-preview-list">
                {% for card in preview_rows[:20] %}
                <article class="anki-preview-card">
                    <div class="anki-preview-number">Card {{ loop.index }}</div>
                    <div class="anki-card-side">
                        <span>FRONT</span>
                        <pre>{{ card.front }}</pre>
                    </div>
                    <div class="anki-card-side anki-card-back">
                        <span>BACK</span>
                        <pre>{{ card.back }}</pre>
                    </div>
                </article>
                {% endfor %}
            </div>

            {% if preview_rows|length > 20 %}
            <div class="anki-preview-more">
                Previewing the first 20 of {{ preview_rows|length }} cards. The export includes all matching cards.
            </div>
            {% endif %}
            {% endif %}
        </section>
        {% endif %}

        <div style="margin-top:18px;">
            <button type="button"
                    class="anki-preview-button"
                    onclick="location.href='/anki'">
                ← Back to Anki Tools
            </button>
        </div>
    </main>
</div>

<script>
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("dashboardSidebar");

if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => sidebar.classList.toggle("open"));

    document.addEventListener("click", event => {
        if (window.innerWidth > 820 || !sidebar.classList.contains("open")) return;
        if (sidebar.contains(event.target) || menuButton.contains(event.target)) return;
        sidebar.classList.remove("open");
    });
}


const exportLawAnki = document.getElementById("exportLawAnki");

if (exportLawAnki) {
    exportLawAnki.addEventListener("click", () => {
        const form = document.getElementById("lawAnkiForm");
        if (!form) return;

        const scopeSelect = form.querySelector('[name="law_scope"]');
        const caseSelect = form.querySelector('[name="case_ids"]');
        const courseSelect = form.querySelector('[name="law_course"]');

        const exportForm = document.createElement("form");
        exportForm.method = "POST";
        exportForm.action = "/anki/export/law";
        exportForm.style.display = "none";

        const addHidden = (name, value) => {
            const input = document.createElement("input");
            input.type = "hidden";
            input.name = name;
            input.value = value;
            exportForm.appendChild(input);
        };

        addHidden("law_scope", scopeSelect ? scopeSelect.value : "cases");
        addHidden("law_course", courseSelect ? courseSelect.value : "");

        if (caseSelect) {
            Array.from(caseSelect.selectedOptions).forEach(option => {
                addHidden("case_ids", option.value);
            });
        }

        window.dlmsProtectForm(exportForm);
        document.body.appendChild(exportForm);
        exportForm.submit();
    });
}

const shutdownBtn = document.getElementById("shutdownBtn");
if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
        if (!confirm("Shut down DLMS? You will need to restart it manually.")) return;
        try {
            const res = await fetch("/api/shutdown", { method: "POST" });
            const data = await res.json();
            if (data.status === "ok") alert("DLMS is shutting down.");
            else throw new Error();
        } catch (err) {
            alert("Failed to shut down DLMS.");
        }
    });
}

if (window.location.search.includes("preview=1")) {
    const preview = document.getElementById("ankiPreview");
    if (preview) preview.scrollIntoView({ behavior: "smooth", block: "start" });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>
""",
        app_version=APP_VERSION,
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


@app.route("/anki/export/quiz", methods=["POST"])
def anki_export_quiz():
    quiz_id = request.form.get("quiz_id")
    quiz_title, deck_rows = build_anki_rows_for_quiz(quiz_id)

    if not quiz_title or not deck_rows:
        return "No quiz cards were available to export.", 404

    deck_name = f"{quiz_title} - DLMS"
    apkg_path = export_quiz_to_apkg(deck_name, deck_rows)

    return _send_temp_anki_package(
        apkg_path,
        make_safe_anki_download_name(
            f"{quiz_title}_DLMS",
            "dlms_quiz"
        )
    )


@app.route("/anki/export/missed", methods=["POST"])
def anki_export_missed():
    quiz_id = request.form.get("quiz_id", "all")
    min_misses = request.form.get("min_misses", "1")
    missed_status = request.form.get("missed_status", "all")

    deck_rows = build_anki_rows_for_missed(
        quiz_id,
        min_misses,
        missed_status
    )

    if not deck_rows:
        return "No missed questions matched those filters.", 404

    if quiz_id not in ("", "all", None):
        quiz_title, _unused = build_anki_rows_for_quiz(quiz_id)
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

    apkg_path = export_quiz_to_apkg(deck_name, deck_rows)

    return _send_temp_anki_package(
        apkg_path,
        make_safe_anki_download_name(
            file_base,
            "dlms_missed_questions"
        )
    )


@app.route("/anki/export/law", methods=["POST"])
def anki_export_law():
    law_scope = (request.form.get("law_scope") or "cases").strip().lower()
    case_ids = request.form.getlist("case_ids")
    law_course = (request.form.get("law_course") or "").strip()

    # Backward compatibility with the original single-case Anki Tools form.
    legacy_case_id = request.form.get("case_id")
    if legacy_case_id and not case_ids:
        case_ids = [legacy_case_id]

    if law_scope == "course":
        if not law_course:
            return "Choose a Law Study course to export.", 400

        selection_meta, deck_rows = load_law_flashcards_for_selection(
            course=law_course
        )

        if not deck_rows:
            return "No recognized Rule Flashcards were found for that course.", 404

        deck_name = f"DLMS - Law - {law_course}"
        file_base = f"{law_course}_rule_flashcards"

    else:
        if not case_ids:
            return "Choose at least one saved Law Study case to export.", 400

        selection_meta, deck_rows = load_law_flashcards_for_selection(
            case_ids=case_ids
        )

        if not deck_rows:
            return "No recognized Rule Flashcards were found in the selected cases.", 404

        if selection_meta["case_count"] == 1:
            title = selection_meta["case_titles"][0]
            # Recover the course for the single case so existing deck naming stays familiar.
            case_meta, _cards = load_law_flashcards_for_case(case_ids[0])
            course = (case_meta or {}).get("course") or "Law Study"
            deck_name = f"DLMS - Law - {course} - {title}"
            file_base = f"{course}_{title}_flashcards"
        else:
            deck_name = f"DLMS - Law - Selected Cases ({selection_meta['case_count']})"
            file_base = f"DLMS_Law_{selection_meta['case_count']}_selected_cases"

    apkg_path = export_quiz_to_apkg(deck_name, deck_rows)

    return _send_temp_anki_package(
        apkg_path,
        make_safe_anki_download_name(
            file_base,
            "dlms_law_flashcards"
        )
    )

def export_anki_tsv_for_quiz(quiz_id: int) -> str:
    return _anki_service.export_anki_tsv_for_quiz(quiz_id, get_db=get_db)


from flask import Response, request, send_file
import logging

logger = logging.getLogger(__name__)


# =====================================================
# EXPORT FULL QUIZ → TSV (DIRECT DOWNLOAD)
# =====================================================
@app.route("/export/anki/quiz/<int:quiz_id>")
def export_anki_quiz_tsv(quiz_id):
    tsv = export_anki_tsv_for_quiz(quiz_id)

    logger.info("[ANKI-TSV] Export quiz TSV | quiz_id=%s | bytes=%s",
                quiz_id, len(tsv.encode("utf-8")))

    return Response(
        tsv,
        mimetype="text/tab-separated-values; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=quiz_{quiz_id}_anki.tsv"
        }
    )

# =====================================================
# Anki Study Export (Selected Questions) → .apkg
# =====================================================

@app.route("/export/anki/study", methods=["POST"])
def export_anki_study():
    data = request.get_json(force=True) or {}

    quiz_id = data.get("quiz_id")
    question_numbers = data.get("question_numbers") or []

    try:
        quiz_id = int(quiz_id)
        question_numbers = sorted({
            int(n)
            for n in question_numbers
            if str(n).isdigit() and int(n) > 0
        })
    except (TypeError, ValueError):
        return {"error": "Invalid quiz or question selection"}, 400

    if not question_numbers:
        return {"error": "No study questions selected"}, 400

    conn = get_db()
    cur = conn.cursor()

    quiz_row = cur.execute(
        """
        SELECT title
        FROM quizzes
        WHERE id = ?
        """,
        (quiz_id,)
    ).fetchone()

    if not quiz_row:
        conn.close()
        return {"error": "Quiz not found"}, 404

    # Load questions in the same order used by the quiz.
    questions = cur.execute(
        """
        SELECT id, question_number, question_text
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number, id
        """,
        (quiz_id,)
    ).fetchall()

    deck_rows = []

    # question_numbers from Study Mode are 1-based positions
    # in the currently displayed quiz.
    for position in question_numbers:
        question_index = position - 1

        if question_index < 0 or question_index >= len(questions):
            continue

        question = questions[question_index]

        choices = cur.execute(
            """
            SELECT label, text, is_correct
            FROM choices
            WHERE question_id = ?
            ORDER BY label
            """,
            (question["id"],)
        ).fetchall()

        front_parts = [question["question_text"] or ""]

        if choices:
            front_parts.append("")

            for choice in choices:
                front_parts.append(
                    f"{choice['label']}. {choice['text'] or ''}"
                )

        correct_parts = []

        for choice in choices:
            if choice["is_correct"]:
                correct_parts.append(
                    f"{choice['label']}. {choice['text'] or ''}"
                )

        back = "Correct Answer:\n" + "\n".join(correct_parts)

        deck_rows.append({
            "front": "\n".join(front_parts),
            "back": back
        })

    conn.close()

    if not deck_rows:
        return {"error": "No valid questions were selected"}, 400

    quiz_title = quiz_row["title"] or "DLMS Study Questions"
    deck_name = f"{quiz_title} - Study Review"

    apkg_path = export_quiz_to_apkg(
        deck_name,
        deck_rows
    )

    return _send_temp_anki_package(
        apkg_path,
        "dlms_study_selected.apkg"
    )




# =====================================================
# EXPORT MISSED QUESTIONS → GENANKI (.apkg)
# =====================================================
@app.route("/export/anki", methods=["POST"])
def export_anki_genanki():
    data = request.get_json(force=True) or {}

    attempt_id = data.get("attempt_id")

    if not attempt_id:
        return {"error": "Missing attempt_id"}, 400

    conn = get_db()
    cur = conn.cursor()

    # 🔑 IMPORTANT: use SNAPSHOT DATA ONLY
    cur.execute(
        """
        SELECT
            mq.attempt_question_number,
            mq.question_text,
            mq.choices_text,
            mq.correct_text,
            qu.id AS quiz_id,
            qu.title AS quiz_title
        FROM missed_questions mq
        JOIN attempts a ON a.id = mq.attempt_id
        JOIN quizzes qu ON qu.id = a.quiz_id
        WHERE mq.attempt_id = ?
        ORDER BY mq.attempt_question_number
        """,
        [attempt_id]
    )

    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {"error": "No missed questions found for this attempt"}, 404

    print(f"[ANKI] exporting {len(rows)} missed questions")

    # -----------------------------
    # Transform rows for genanki
    # -----------------------------
    deck_rows = []

    for r in rows:
        question = (r["question_text"] or "").strip()
        choices_text = (r["choices_text"] or "").strip()
        correct_text = (r["correct_text"] or "").strip()

        # FRONT = question + ALL choices
        front_parts = [question]
        if choices_text:
            front_parts.append("")
            front_parts.append(choices_text)

        front = "\n".join(front_parts)

        # BACK = correct answer(s) only
        back = "Correct Answer\n" + correct_text

        deck_rows.append({
            "front": front,
            "back": back
        })

    quiz_id = rows[0]["quiz_id"]
    registry_map, _installed_packs, _origin_by_quiz_id = _attempt_history_context()
    registry_entry = registry_map.get(int(quiz_id), {}) if quiz_id is not None else {}
    source_title = registry_entry.get("title") or rows[0]["quiz_title"] or "DLMS Quiz"
    safe_title = make_safe_anki_deck_name(source_title, "DLMS Quiz")
    deck_name = f"{safe_title} - Missed Questions"
    download_name = make_safe_anki_download_name(
        f"{safe_title}_Missed_Questions",
        "DLMS_Missed_Questions",
    )

    apkg_path = export_quiz_to_apkg(deck_name, deck_rows)

    return _send_temp_anki_package(
        apkg_path,
        download_name,
    )







# =====================================================
# EXPORT MISSED QUESTIONS → TSV (ANKI IMPORT)
# =====================================================
def _format_anki_missed_tsv(rows):
    return _anki_service.format_anki_missed_tsv(rows, logger=logger)


@app.route("/export/anki/missed", methods=["POST"])
def export_anki_missed_tsv():
    data = request.get_json(force=True) or {}

    attempt_id = data.get("attempt_id")
    attempt_qnums = data.get("attempt_question_numbers") or data.get("question_numbers") or []

    if not attempt_id or not attempt_qnums:
        print("[ANKI DEBUG] raw payload:", data)
        return {"error": "Missing attempt_id or attempt_question_numbers"}, 400

    attempt_qnums = [
    int(x) for x in attempt_qnums
    if x is not None and str(x).isdigit()
]

    if not attempt_qnums:
        return {"error": "No valid question numbers after filtering"}, 400


    conn = get_db()
    cur = conn.cursor()

    q_marks = ",".join("?" for _ in attempt_qnums)

    cur.execute(
        f"""
        SELECT
            mq.attempt_question_number,
            q.number AS question_number,
            q.text AS question_text,
            (
                SELECT GROUP_CONCAT(x, CHAR(10))
                FROM (
                    SELECT c2.label || '. ' || c2.text AS x
                    FROM choices c2
                    WHERE c2.question_id = q.id
                    ORDER BY c2.label
                )
            ) AS choices_text,
            (
                SELECT GROUP_CONCAT(c3.label, ', ')
                FROM choices c3
                WHERE c3.question_id = q.id
                  AND c3.is_correct = 1
                ORDER BY c3.label
            ) AS correct_letters,
            (
                SELECT GROUP_CONCAT(x, CHAR(10))
                FROM (
                    SELECT c4.label || '. ' || c4.text AS x
                    FROM choices c4
                    WHERE c4.question_id = q.id
                      AND c4.is_correct = 1
                    ORDER BY c4.label
                )
            ) AS correct_text,
            qu.title AS quiz_title
        FROM missed_questions mq
        JOIN questions q ON q.id = mq.question_id
        JOIN attempts a ON a.id = mq.attempt_id
        JOIN quizzes qu ON qu.id = a.quiz_id
        WHERE mq.attempt_id = ?
          AND mq.attempt_question_number IN ({q_marks})
        ORDER BY mq.attempt_question_number
        """,
        [attempt_id, *attempt_qnums],
    )

    rows = cur.fetchall()
    conn.close()

    logger.info("[ANKI-TSV] Missed TSV rows fetched: %s | attempt_id=%s",
                len(rows), attempt_id)

    tsv = _format_anki_missed_tsv(rows)

    return Response(
        tsv,
        mimetype="text/tab-separated-values; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=missed_questions_anki.tsv"
        }
    )




# Review loads a selected summary from /api/attempts/<attempt-id> and then
# retrieves only that attempt's missed-question snapshot below.

# @app.route("/api/missed_questions")
# def api_missed_questions():
#     return {"error": "Deprecated endpoint. Use /api/attempts."}, 410


@app.route("/api/missed_questions")
def api_missed_questions():
    attempt_id = request.args.get("attempt")

    if not attempt_id:
        return {"error": "Missing attempt id"}, 400

    conn = get_db()
    try:
        missed = _history_service.missed_questions(
            conn.cursor(),
            attempt_id,
            resolve_attempt_row=_resolve_attempt_row,
            missed_rows_for_attempt=_missed_rows_for_attempt,
            json_module=json,
        )
        if missed is None:
            return jsonify({"error": "Attempt not found"}), 404
        return jsonify(missed)
    finally:
        conn.close()










@app.route("/api/clear_db_history", methods=["POST"])
def clear_db_history():
    try:
        conn = get_db()
        cur = conn.cursor()

        # Ensure FK enforcement
        cur.execute("PRAGMA foreign_keys = ON")

        # Delete deepest dependencies first
        cur.execute("DELETE FROM attempt_answers")
        cur.execute("DELETE FROM missed_questions")
        cur.execute("DELETE FROM attempts")

        conn.commit()
        conn.close()

        print("[DB] Persistent exam history fully cleared")

        return {
            "status": "ok",
            "message": "Persistent history cleared"
        }

    except Exception as e:
        print("DB CLEAR ERROR:", e)
        return {
            "status": "error",
            "error": "Saved history could not be cleared. Check the local DLMS log for details."
        }, 500





@app.route("/api/portal_config")
def api_portal_config():
    try:
        cfg = load_portal_config()
        return jsonify(cfg)
    except Exception as e:
        print("portal_config API error:", e)
        return jsonify({"error": "failed"}), 500






# =========================
# CONFIDENCE ANALYSIS ENGINE
# =========================
def analyze_confidence(text):
    import re

    blocks = re.split(
        r"(?=^\s*(?:Question\s*#?\s*\d+|\d+\s*[.) ]))",
        text,
        flags=re.IGNORECASE | re.MULTILINE
    )

    details = []
    total = len(blocks)
    high = medium = low = 0

    for block in blocks:
        b = block.strip()
        if not b:
            continue

        score = 0
        reasons = []

        # --- Choices Check ---
        choices = re.findall(r"^[A-Z][\.\)]", b, flags=re.MULTILINE)
        if len(choices) >= 2:
            score += 40
            reasons.append("Detected multiple answer choices")
        else:
            reasons.append("Missing or too few answer choices")

        # --- Has Correct Answer ---
        if re.search(r"correct answer|suggested answer", b, re.IGNORECASE):
            score += 40
            reasons.append("Detected an answer key line")
        else:
            reasons.append("No clear answer key line found")

        # --- Length / Structure ---
        if len(b) > 120:
            score += 20
            reasons.append("Looks like full valid question text")
        else:
            reasons.append("Question block looks short/incomplete")

        # ---------- Confidence Bucket ----------
        if score >= 80:
            level = "HIGH"
            high += 1
        elif score >= 40:
            level = "MEDIUM"
            medium += 1
        else:
            level = "LOW"
            low += 1

        details.append({
            "confidence": level,
            "score": score,
            "preview": b[:400],
            "reasons": reasons
        })

    summary = {
        "total": total,
        "high": high,
        "medium": medium,
        "low": low
    }

    return summary, details




# =========================
# ROBUST PARSER + LOGGING
# =========================
DEBUG_PARSE = True
PARSE_LOG = []


def dbg(*msg):
    text = " ".join(str(m) for m in msg)
    if DEBUG_PARSE:
        dprint("[PARSE]", text)
    PARSE_LOG.append(text)


def parse_questions(source):
    return _quiz_text_parser.parse_questions(
        source,
        parse_log=PARSE_LOG,
        debug_log=dbg,
    )








# =========================
# CONFIDENCE ANALYZER (for preview only)
# =========================
def analyze_confidence(clean_text):
    return _quiz_text_parser.analyze_confidence(clean_text)


# =========================
# QUIZ HTML BUILDER
# =========================

def build_quiz_html(name, jsonfile, outpath, portal_title, quiz_title, logo_filename, quiz_id, exam_minutes=90):
    return _quiz_artifact_renderer.build_quiz_html(
        name,
        jsonfile,
        outpath,
        portal_title,
        quiz_title,
        logo_filename,
        quiz_id,
        exam_minutes,
        normalize_exam_minutes=normalize_exam_minutes,
        html_text=_html_text,
        html_attribute=_html_attribute,
        json_for_inline_script=_json_for_inline_script,
        open_file=open,
    )





# =========================
# DATABASE CONFIG
# =========================



def get_or_create_question(conn, quiz_id, q):
    """
    Returns canonical question_id for a question.
    Creates it if it does not already exist.
    Matches the ACTUAL questions table schema.
    """
    cur = conn.cursor()

    number = q.get("number")
    text = q.get("question")

   # Look up / define canonical question values
    question_number = q.get("number")
    question_text = q.get("question") or q.get("text") or ""

    cur.execute(
        """
        INSERT INTO questions (
            quiz_id,
            question_number,
            question_text
        )
        VALUES (?, ?, ?)
        """,
        (quiz_id, question_number, question_text),
    )



    row = cur.fetchone()
    if row:
        return row[0]

    # Insert canonical question (schema-aligned)
    cur.execute("""
        INSERT INTO questions (
            quiz_id,
            number,
            text
        ) VALUES (?, ?, ?)
    """, (
        quiz_id,
        number,
        text
    ))

    question_id = cur.lastrowid

    # ---------- INSERT CHOICES ----------
    for c in choices:
        cur.execute("""
            INSERT INTO choices (
                question_id,
                label,
                text,
                is_correct
            ) VALUES (?, ?, ?, ?)
        """, (
            question_id,
            c["label"],
            c["text"],
            1 if c.get("is_correct") else 0
        ))

    conn.commit()
    return question_id



# =========================
# DATABASE HELPERS
# =========================
def get_db():
    dprint(f"[DB] get_db using DB_PATH = {DB_PATH}")
    return _database.get_db(DB_PATH, sqlite_module=sqlite3)




def db_execute(query, params=()):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("DB ERROR:", e)
        return False


def _normalize_concept_names(value):
    return _learning_service._normalize_concept_names(value)


def _content_pack_concepts(record, *, context):
    return _content_pack_service._content_pack_concepts(
        record,
        context=context,
        normalize_concept_names=_normalize_concept_names,
    )


def _set_content_pack_concepts(record, *, context):
    return _content_pack_service._set_content_pack_concepts(
        record,
        context=context,
        content_pack_concepts=_content_pack_concepts,
        normalize_concept_names=_normalize_concept_names,
    )


def _standalone_matching_concepts(data, *, context):
    return _content_pack_service._standalone_matching_concepts(
        data,
        context=context,
        content_pack_concepts=_content_pack_concepts,
        normalize_concept_names=_normalize_concept_names,
    )


def _hotspot_concepts(question, image, hotspot, dataset, *, context):
    return _content_pack_service._hotspot_concepts(
        question,
        image,
        hotspot,
        dataset,
        context=context,
        content_pack_concepts=_content_pack_concepts,
        normalize_concept_names=_normalize_concept_names,
    )


def _question_concepts(cur, question_id):
    return _learning_service._question_concepts(cur, question_id)


def _set_question_concepts(cur, question_id, names):
    names = _normalize_concept_names(names)
    cur.execute("DELETE FROM question_concepts WHERE question_id = ?", (question_id,))
    for name in names:
        cur.execute("INSERT OR IGNORE INTO concepts(name) VALUES (?)", (name,))
        row = cur.execute("SELECT id FROM concepts WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if row:
            cur.execute("INSERT OR IGNORE INTO question_concepts(question_id, concept_id) VALUES (?, ?)", (question_id, row[0]))
    # Remove orphan concept labels so the catalog stays tied to real content.
    cur.execute("DELETE FROM concepts WHERE id NOT IN (SELECT DISTINCT concept_id FROM question_concepts)")
    return names


def _record_learning_event(cur, *, event_type, quiz_id=None, question_id=None, attempt_id=None, session_id=None, mode=None, was_correct=None, response=None):
    return _attempt_service._record_learning_event(
        cur,
        event_type=event_type,
        quiz_id=quiz_id,
        question_id=question_id,
        attempt_id=attempt_id,
        session_id=session_id,
        mode=mode,
        was_correct=was_correct,
        response=response,
        json_module=json,
    )


def resolve_logo_filename(logo_filename):
    """
    Returns a valid logo filename or None if missing on disk.
    """
    if not logo_filename:
        return None

    logo_path = os.path.join(APP_DATA_DIR, "static", "logos", logo_filename)
    if not os.path.exists(logo_path):
        print(f"[LOGO AUTO-HEAL] Missing logo file: {logo_filename}")
        return None

    return logo_filename



@app.route("/history_db")
def history_db():
    # No shipped page calls this legacy endpoint.  Retire the unbounded N+1
    # response rather than leaving a second production scalability trap.
    return jsonify({
        "error": "Deprecated endpoint. Use /api/attempts for paged summaries and "
                 "/api/missed_questions for selected-attempt detail."
    }), 410


# @app.route("/export/anki", methods=["POST"])
# def export_anki():
#     data = request.json or {}
#     attempt_ids = data.get("attempt_ids", [])

#     if not attempt_ids:
#         return jsonify({"error": "No attempts selected"}), 400

#     # 1️⃣ Pull attempts from DB
#     conn = sqlite3.connect(DB_PATH)
#     conn.row_factory = sqlite3.Row
#     cur = conn.cursor()

#     placeholders = ",".join("?" for _ in attempt_ids)
#     cur.execute(
#         f"SELECT * FROM attempts WHERE id IN ({placeholders})",
#         attempt_ids
#     )

#     rows = cur.fetchall()
#     conn.close()

#     if not rows:
#         return jsonify({"error": "No attempts found"}), 404

#     # 2️⃣ Extract missed questions
#     questions = []

#     for row in rows:
#         missed = json.loads(row["missedQuestions"] or "[]")

#         for m in missed:
#             questions.append({
#                 "question": m.get("question", ""),
#                 "choices": m.get("allChoices", []),
#                 "correct": m.get("correctText", []),
#                 "selected": m.get("selectedText", []),
#                 "quiz_title": row["quiz_title"],
#                 "attempt_id": row["id"],
#             })

#     if not questions:
#         return jsonify({"error": "No missed questions to export"}), 400

#     # 3️⃣ Generate deck
#     from anki_deck import build_anki_deck

#     filename = build_anki_deck(
#         questions=questions,
#         deck_name="Missed Questions"
#     )

#     return send_from_directory(
#         directory=os.path.dirname(filename),
#         path=os.path.basename(filename),
#         as_attachment=True
#     )






# =========================
# RUN
# =========================
def _dlms_wait_and_open_browser(port, host="127.0.0.1"):
    """Open the selected local endpoint after its server socket is ready."""
    import socket
    import webbrowser

    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=0.4):
                break
        except OSError:
            time.sleep(0.15)
    else:
        print("[DLMS] Browser launch skipped: server readiness was not confirmed.")
        return

    url = f"http://{_dlms_url_host(host)}:{int(port)}"
    try:
        opened = webbrowser.open(url, new=2)
        if not opened:
            print(f"[DLMS] Browser could not be opened automatically. Use {url}")
    except Exception as exc:
        print(f"[DLMS] Browser launch failed ({exc}). Use {url}")


def _dlms_print_access_urls(host, port):
    host = str(host or DLMS_SERVER_HOST)
    local_url = f"http://127.0.0.1:{int(port)}"
    if _dlms_is_loopback_host(host):
        display_host = "127.0.0.1" if host == "localhost" else host
        print(f"[DLMS] Local access:   http://{_dlms_url_host(display_host)}:{int(port)}")
        return

    if host in {"0.0.0.0", "::"}:
        print(f"[DLMS] Local access:   {local_url}")
        lan_ip = _dlms_detect_lan_ip()
        if lan_ip:
            print(f"[DLMS] Network access: http://{lan_ip}:{int(port)}")
        else:
            print(f"[DLMS] Network bind:   {host}:{int(port)} (all interfaces)")
    else:
        print(f"[DLMS] Network access: http://{_dlms_url_host(host)}:{int(port)}")

    print("[DLMS] WARNING: DLMS is bound to a non-loopback interface.")
    print("[DLMS] WARNING: Authentication is not yet provided; expose DLMS only on a trusted network.")


def _run_quiz_publication_startup_reconciliation():
    """Run journal recovery after ownership setup, DB initialization, and helpers."""
    try:
        return reconcile_quiz_publications()
    except Exception as exc:
        print(
            "[QUIZ PUBLICATION RECOVERY] startup recovery could not complete; "
            f"it will retry next launch ({type(exc).__name__}: {exc})"
        )
        return {"processed": 0, "preserved": 0, "rolled_back": 0, "unsafe": 0, "failed": 1}


def _run_restore_startup_reconciliation():
    """Recover interrupted live-data replacement before normal DB startup."""
    try:
        return reconcile_restore_operations()
    except Exception as exc:
        print(
            "[RESTORE RECOVERY] startup recovery could not complete safely; "
            f"DLMS startup is stopping ({type(exc).__name__}: {exc})"
        )
        raise


def _run_restore_staging_startup_cleanup():
    """Discard only old validated uploads after restore recovery is settled."""
    try:
        return _cleanup_stale_restore_staging()
    except Exception as exc:
        print(
            "[RESTORE STAGING CLEANUP ERROR] startup cleanup will retry next launch "
            f"({type(exc).__name__}: {exc})"
        )
        return {"removed": 0, "preserved": 0, "recovery": 0, "failed": 1}


_run_restore_startup_reconciliation()
_run_restore_staging_startup_cleanup()
ensure_db_initialized()
_run_quiz_publication_startup_reconciliation()


if __name__ == "__main__":
    #purge_legacy_quizzes()   # REMOVE after one run

    try:
        startup = _dlms_parse_startup_options()
    except ValueError as exc:
        print(f"[DLMS] Startup error: {exc}", file=sys.stderr)
        raise SystemExit(2)

    server_host = startup["host"]
    _dlms_print_access_urls(server_host, DLMS_SERVER_PORT)
    if startup["disable_browser"]:
        print("[DLMS] Automatic browser launch disabled (--no-browser / DLMS_NO_BROWSER).")
    elif startup["open_browser"]:
        print("[DLMS] Browser will open after the local server is ready. Use --no-browser to disable this behavior.")
        browser_host = _dlms_browser_host(server_host)
        threading.Thread(target=_dlms_wait_and_open_browser, args=(DLMS_SERVER_PORT, browser_host), daemon=True).start()
    else:
        print("[DLMS] Headless/server session detected; browser launch skipped. Use --browser to force it.")

    # Bind behavior intentionally remains independent of browser-launch behavior.
    app.run(
        host=server_host,
        port=DLMS_SERVER_PORT,
        debug=False,
        use_reloader=False
    )
