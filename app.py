from flask import Flask, send_from_directory, send_file, request, redirect, render_template, jsonify, Response, flash, url_for, has_request_context, g
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
import os, re, json, time, sqlite3, sys, shutil, signal, threading, csv, io, random, secrets, zipfile, tempfile, html, warnings, unicodedata, ipaddress, copy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
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
from dlms.browser_presence import BrowserPresenceManager
from dlms.persistence import json_files as _json_files
from dlms.persistence import external_ai_drafts as _external_ai_draft_repository
from dlms.persistence import portal as _portal_repository
from dlms.persistence import registries as _registry_repository
from dlms.persistence import database as _database
from dlms.persistence import pdf_banks as _pdf_bank_repository
from dlms.parsing import law_packet as _law_packet_parser
from dlms.parsing import external_ai_structured as _external_ai_structured_parser
from dlms.parsing import quiz_text as _quiz_text_parser
from dlms.parsing import smart_pdf as _smart_pdf_parser
from dlms.parsing import ocr_questions as _ocr_question_parser
from dlms.parsing import pdf_raster_questions as _pdf_raster_question_parser
from dlms.rendering import quiz_artifacts as _quiz_artifact_renderer
from dlms.services import anki as _anki_service
from dlms.services import attempts as _attempt_service
from dlms.services import backups as _backup_service
from dlms.services import content_packs as _content_pack_service
from dlms.services import content_pack_mutations as _content_pack_mutation_service
from dlms.services import external_ai_structured as _external_ai_structured_service
from dlms.services import history as _history_service
from dlms.services import learning as _learning_service
from dlms.services import quiz_publication as _quiz_publication_service
from dlms.services import quiz_composition as _quiz_composition_service
from dlms.services import quiz_mutations as _quiz_mutation_service
from dlms.services import restore as _restore_service
from dlms.services import law as _law_service
from dlms.services import ocr as _ocr_service
from dlms.services import ocr_screenshots as _ocr_screenshot_service
from dlms.services import pdf_ocr as _pdf_ocr_service
from dlms.routes.core import CoreRouteDependencies, create_core_blueprint
from dlms.routes.help import create_help_blueprint
from dlms.routes.it import ITStudyDependencies, create_it_blueprint
from dlms.routes.law import LawRouteDependencies, create_law_blueprint
from dlms.routes.learning import LearningRouteDependencies, create_learning_blueprint
from dlms.routes.history import HistoryRouteDependencies, create_history_blueprint
from dlms.routes.anki import AnkiRouteDependencies, create_anki_blueprint
from dlms.routes.maintenance import (
    MaintenanceRouteDependencies,
    create_maintenance_blueprint,
)
from dlms.routes.settings import SettingsRouteDependencies, create_settings_blueprint
from dlms.routes.admin_images import (
    AdminImageRouteDependencies,
    create_admin_images_blueprint,
)
from dlms.routes.content_packs import (
    ContentPackRouteDependencies,
    create_content_packs_blueprint,
)
from dlms.routes.external_ai import (
    ExternalAIRouteDependencies,
    create_external_ai_blueprint,
)
from dlms.routes.medical import MedicalRouteDependencies, create_medical_blueprint
from dlms.routes.pdf_import import (
    PDFImportRouteDependencies,
    create_pdf_import_blueprint,
)
from dlms.routes.quiz import (
    QuizAuthoringDependencies,
    QuizEditorDependencies,
    QuizLibraryDependencies,
    create_quiz_blueprint,
)
from dlms.routes.study_packs import (
    StudyPackRouteDependencies,
    create_study_packs_blueprint,
)

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


# =========================
# APP DATA DIRECTORY
# =========================
DLMS_DATA_ROOT_MARKER = ".dlms-data-root"
DLMS_DATA_ROOT_MARKER_ID = "dlms-application-data-root"
DLMS_DATA_ROOT_MARKER_VERSION = 1
DLMS_LEGACY_DATA_ROOT_ENTRIES = {
    ".quiz_publications", ".restore_operations", ".secret_key", "backups", "config", "content_pack_staging", "content_packs",
    "data", "external_ai_drafts", "image_builder_drafts", "law", "pdf_import_drafts",
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
APP_VERSION = "3.1.0"
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
    return render_template(
        "errors/request-rejected.html",
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
        "/pdf-import/screenshots": OCR_SCREENSHOT_MAX_BATCH_BYTES + UPLOAD_MULTIPART_OVERHEAD_BYTES,
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
    return render_template("errors/request-too-large.html"), 413




# DEBUG - retained for troubleshooting static-file path issues
# print("[DEBUG] Flask static folder =", app.static_folder)
# DEBUG - retained for troubleshooting packaged/dev data-directory issues
# print("[BUILD CHECK] APP_DATA_DIR =", APP_DATA_DIR)









DEBUG_LOGS = False

def dprint(*args, **kwargs):
    if DEBUG_LOGS:
        print(*args, **kwargs)

#dprint("DEBUG TEST — YOU SHOULD NOT SEE THIS")
# DEBUG - retained for troubleshooting static-file path issues
# print("[DEBUG] Flask static folder =", app.static_folder)




# =========================
# PATH SETUP
# =========================
IS_BUNDLED = hasattr(sys, "_MEIPASS")

# DEBUG - retained for troubleshooting packaged/dev data-directory issues
# print("[BUILD CHECK] APP_DATA_DIR =", APP_DATA_DIR)



UPLOAD_FOLDER = os.path.join(APP_DATA_DIR, "uploads")
DATA_FOLDER = os.path.join(APP_DATA_DIR, "data")
QUIZ_FOLDER = os.path.join(APP_DATA_DIR, "quizzes")
CONFIG_FOLDER = os.path.join(APP_DATA_DIR, "config")

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
EXTERNAL_AI_DRAFT_FOLDER = os.path.join(APP_DATA_DIR, "external_ai_drafts")
PDF_IMPORT_DRAFT_FOLDER = os.path.join(APP_DATA_DIR, "pdf_import_drafts")
OCR_IMPORT_STAGING_FOLDER = os.path.join(UPLOAD_FOLDER, "ocr_screenshots")
PDF_OCR_STAGING_FOLDER = os.path.join(UPLOAD_FOLDER, "ocr_pdfs")
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
    EXTERNAL_AI_DRAFT_FOLDER,
    PDF_IMPORT_DRAFT_FOLDER,
    OCR_IMPORT_STAGING_FOLDER,
    PDF_OCR_STAGING_FOLDER,
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
                upload._dlms_consumed_bytes = total
                if total > max_bytes:
                    raise UploadTooLargeError(f"{label} exceeds the {_format_bytes(max_bytes)} limit.")
                destination.write(chunk)
        upload._dlms_consumed_bytes = total
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


def _decode_raster_image(
    path,
    allowed_extensions=None,
    *,
    max_pixels=IMAGE_MAX_PIXELS,
    max_width=IMAGE_MAX_WIDTH,
    max_height=IMAGE_MAX_HEIGHT,
    max_frames=IMAGE_MAX_FRAMES,
):
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
                if width > max_width or height > max_height or width * height > max_pixels:
                    raise ValueError(
                        f"image dimensions exceed {max_width}×{max_height} or {max_pixels:,} pixels"
                    )
                frame_count = int(getattr(image, "n_frames", 1) or 1)
                if frame_count > max_frames:
                    if max_frames == 1:
                        raise ValueError("animated images are not accepted by this workflow")
                    raise ValueError(f"animated image exceeds the {max_frames}-frame limit")
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


def _reencode_raster_file(
    source_path,
    destination_path,
    allowed_extensions=None,
    *,
    max_pixels=IMAGE_MAX_PIXELS,
    max_width=IMAGE_MAX_WIDTH,
    max_height=IMAGE_MAX_HEIGHT,
    max_frames=IMAGE_MAX_FRAMES,
    orient_from_exif=False,
    normalize_mode=False,
):
    """Decode and atomically re-encode a raster, stripping non-image trailing data."""
    frames, metadata = _decode_raster_image(
        source_path,
        allowed_extensions,
        max_pixels=max_pixels,
        max_width=max_width,
        max_height=max_height,
        max_frames=max_frames,
    )
    extension = os.path.splitext(destination_path)[1].lower()
    output_format = RASTER_IMAGE_FORMATS[extension]
    descriptor, temporary_path = tempfile.mkstemp(prefix=".dlms-image-", suffix=extension, dir=os.path.dirname(destination_path))
    os.close(descriptor)
    try:
        first = ImageOps.exif_transpose(frames[0]) if orient_from_exif else frames[0]
        if normalize_mode and first.mode not in {"RGB", "L"}:
            first = first.convert("RGB")
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
        _decode_raster_image(
            temporary_path,
            allowed_extensions,
            max_pixels=max_pixels,
            max_width=max_width,
            max_height=max_height,
            max_frames=max_frames,
        )
        os.replace(temporary_path, destination_path)
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass


def _store_raster_upload(
    upload,
    destination_dir,
    filename,
    allowed_extensions=None,
    max_bytes=RASTER_UPLOAD_MAX_BYTES,
    *,
    max_pixels=IMAGE_MAX_PIXELS,
    max_width=IMAGE_MAX_WIDTH,
    max_height=IMAGE_MAX_HEIGHT,
    max_frames=IMAGE_MAX_FRAMES,
    orient_from_exif=False,
    normalize_mode=False,
):
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
        _reencode_raster_file(
            raw_path,
            destination_path,
            allowed,
            max_pixels=max_pixels,
            max_width=max_width,
            max_height=max_height,
            max_frames=max_frames,
            orient_from_exif=orient_from_exif,
            normalize_mode=normalize_mode,
        )
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
                "image_url": url_for("core.content_pack_asset", pack_id=pack_id, asset_path=image.get("file")),
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


def _study_pack_catalog_domain_group(pack_id, pack):
    return _content_pack_service._study_pack_catalog_domain_group(
        pack_id,
        pack,
        is_it_pack_manifest=_is_it_pack_manifest,
        is_medical_pack_manifest=_is_medical_pack_manifest,
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
    ".restore_operations", "backups", "uploads", "content_pack_staging",
    "external_ai_drafts",
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
        EXTERNAL_AI_DRAFT_FOLDER, PDF_IMPORT_DRAFT_FOLDER, PDF_QUESTION_BANK_FOLDER,
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
        canonical_law_case_id=canonical_law_case_id,
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


def _validate_restored_law_imports(staged_data_root):
    return _backup_service.validate_restored_law_imports(
        staged_data_root,
        canonical_law_import_filename=canonical_law_import_filename,
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
        validate_restored_law_imports=_validate_restored_law_imports,
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








# =========================
# HOTSPOT CALIBRATION EDITOR
# =========================


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











# =========================
# CONTENT PACKS - STATUS
# =========================
def _schedule_dlms_shutdown(*, automatic=False):
    """Schedule the existing graceful process shutdown after a response can flush."""
    pid = os.getpid()

    def shutdown():
        if automatic and not browser_presence_manager.complete_automatic_shutdown(
            _send_shutdown_signal
        ):
            print("[SYSTEM] Automatic shutdown deferred because browser presence or a critical operation returned")
            return
        if automatic:
            return
        _send_shutdown_signal()

    def _send_shutdown_signal():
        print("[SYSTEM] Sending SIGINT to self")
        os.kill(pid, signal.SIGINT)

    # Delay lets Flask return HTTP 200 before dying
    from threading import Timer
    Timer(0.5, shutdown).start()


def _schedule_automatic_browser_shutdown():
    print("[SYSTEM] No live DLMS browser pages remain; automatic shutdown requested")
    _schedule_dlms_shutdown(automatic=True)


@app.route("/api/shutdown", methods=["POST"])
def shutdown_app():
    print("[SYSTEM] Shutdown requested via UI")
    _schedule_dlms_shutdown()

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


def _atomic_write_text(path, text, *, encoding="utf-8"):
    """Durably replace one user-owned text file."""
    return _json_files._atomic_write_text(
        path,
        text,
        encoding=encoding,
        os_module=os,
        tempfile_module=tempfile,
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


browser_presence_manager = BrowserPresenceManager(
    _schedule_automatic_browser_shutdown,
    runtime_eligible=_dlms_is_loopback_host(DLMS_SERVER_HOST),
)


def _browser_presence_setting_loaded(config):
    browser_presence_manager.set_enabled(
        bool((config or {}).get("automatic_browser_shutdown_enabled", False))
    )


def _update_browser_presence(token, closed=False):
    if closed:
        return browser_presence_manager.close(token)
    return browser_presence_manager.heartbeat(token)


def _configure_browser_presence_runtime(host):
    """Allow automatic shutdown only for an unambiguous loopback bind."""
    eligible = _dlms_is_loopback_host(host)
    browser_presence_manager.set_runtime_eligible(eligible)
    return eligible


def _browser_presence_runtime_eligible():
    return browser_presence_manager.runtime_eligible


def start_browser_presence_monitor(host=DLMS_SERVER_HOST):
    """Initialize runtime-only presence state and start its daemon monitor."""
    _configure_browser_presence_runtime(host)
    _browser_presence_setting_loaded(load_portal_config())
    return browser_presence_manager.start()


@app.before_request
def protect_critical_operation_from_automatic_shutdown():
    """Keep automatic shutdown outside all accepted state-changing requests."""
    if request.method not in app.config["WTF_CSRF_METHODS"]:
        return None
    if request.endpoint == "core.browser_presence":
        return None
    browser_presence_manager.begin_critical_operation()
    g._dlms_browser_presence_critical_operation = True
    return None


@app.teardown_request
def finish_critical_operation_for_automatic_shutdown(_error):
    if getattr(g, "_dlms_browser_presence_critical_operation", False):
        browser_presence_manager.end_critical_operation()


@app.after_request
def sync_browser_presence_after_portal_replacement(response):
    """Apply restored/reset lifecycle settings before releasing mutation guard."""
    if request.endpoint in {
        "maintenance.settings_confirm_restore",
        "maintenance.reset_app_settings",
        "maintenance.reset_all_data",
    } and response.status_code < 500:
        try:
            _browser_presence_setting_loaded(load_portal_config())
        except Exception as exc:
            print(
                "[BROWSER PRESENCE ERROR] Could not refresh restored lifecycle "
                f"setting: {type(exc).__name__}: {exc}"
            )
    return response


def _write_settings_portal_config(config):
    return _atomic_write_json(
        PORTAL_CONFIG,
        config,
        indent=4,
        expected_type=dict,
    )


def _store_settings_background_upload(upload):
    filename = secure_filename(upload.filename)
    _store_raster_upload(
        upload,
        BACKGROUND_FOLDER,
        filename,
        RASTER_IMAGE_FORMATS,
    )
    return filename


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
law_raw_import_lock = threading.Lock()

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

app.register_blueprint(create_core_blueprint(CoreRouteDependencies(
    app_version=lambda: APP_VERSION,
    get_portal_title=lambda: get_portal_title(),
    content_pack_summary=lambda: content_pack_summary(),
    load_portal_config=lambda: load_portal_config(),
    debug_print=lambda *args, **kwargs: dprint(*args, **kwargs),
    app_data_dir=lambda: APP_DATA_DIR,
    static_folder=lambda: app.static_folder,
    default_theme=lambda: DEFAULT_THEME,
    get_content_pack=lambda pack_id: get_content_pack(pack_id),
    safe_pack_child=lambda root, path: _safe_pack_child(root, path),
    decode_raster_image=lambda *args, **kwargs: _decode_raster_image(*args, **kwargs),
    passive_pack_image_extensions=lambda: PASSIVE_PACK_IMAGE_EXTENSIONS,
    raster_image_formats=lambda: RASTER_IMAGE_FORMATS,
    quiz_asset_folder=lambda: QUIZ_ASSET_FOLDER,
    browser_presence_update=lambda token, closed: _update_browser_presence(token, closed),
    browser_presence_setting_loaded=lambda config: _browser_presence_setting_loaded(config),
)))
app.register_blueprint(create_help_blueprint())



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
        return url_for("study_packs.study_pack_ai_builder")
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













def _build_content_pack_export(folder):
    return _content_pack_mutation_service.build_content_pack_export(
        folder, content_pack_folder_report=_content_pack_folder_report
    )






def _delete_content_pack_folder(folder):
    return _content_pack_mutation_service.delete_content_pack_folder(
        folder,
        content_pack_folder=CONTENT_PACK_FOLDER,
        get_content_pack=get_content_pack,
        snapshot_existing_pack_dependencies=_snapshot_existing_pack_dependencies,
        remove_tree=shutil.rmtree,
    )



























# =========================
# IT STUDY - FILTERED STUDY PACK VIEW
# =========================
app.register_blueprint(create_it_blueprint(ITStudyDependencies(
    discover_content_packs=lambda: discover_content_packs(),
    load_content_pack_dataset=lambda pack_id, dataset_id: load_content_pack_dataset(pack_id, dataset_id),
    load_content_pack_image_dataset=lambda pack_id, dataset_id: load_content_pack_image_dataset(pack_id, dataset_id),
    load_content_pack_quiz_dataset=lambda pack_id, dataset_id: load_content_pack_quiz_dataset(pack_id, dataset_id),
    is_it_pack_manifest=lambda pack_id, pack: _is_it_pack_manifest(pack_id, pack),
)))


# =========================
# GENERIC STUDY PACK PLATFORM
# =========================

















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


def canonical_law_import_filename(filename):
    return _law_packet_parser.canonical_law_import_filename(
        filename,
        secure_filename=secure_filename,
    )


def canonical_law_case_id(case_id):
    return _law_packet_parser.canonical_law_case_id(case_id)


def save_law_raw_packet(raw_packet, case_slug=""):
    return _law_service.save_law_raw_packet(
        raw_packet,
        case_slug,
        imports_folder=LAW_IMPORTS_FOLDER,
        safe_law_import_filename=safe_law_import_filename,
        now=datetime.now,
        raw_import_lock=law_raw_import_lock,
        atomic_write_text=_atomic_write_text,
        makedirs=os.makedirs,
        join_path=os.path.join,
        lexists=os.path.lexists,
    )



def parse_law_packet_sections(raw_text):
    return _law_packet_parser.parse_law_packet_sections(raw_text)


def extract_law_case_title(raw_text, fallback_filename="Untitled Case Review"):
    return _law_packet_parser.extract_law_case_title(raw_text, fallback_filename)



def get_law_case_by_id(case_id):
    return _law_service.get_law_case_by_id(
        case_id,
        load_law_registry=load_law_registry,
        canonical_law_case_id=canonical_law_case_id,
    )


def _load_law_case_data(case_path):
    return _law_service.load_law_case_data(
        case_path,
        open_file=open,
        json_module=json,
    )


def parse_socratic_questions(socratic_text):
    return _law_packet_parser.parse_socratic_questions(socratic_text)

























































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


def _rename_quiz_folder_metadata(old_folder, new_folder):
    return _quiz_mutation_service.rename_quiz_folder_metadata(
        old_folder,
        new_folder,
        registry_lock=registry_lock,
        load_registry=load_registry,
        save_registry=save_registry,
        get_quiz_folders=get_quiz_folders,
        get_hidden_quiz_folders=get_hidden_quiz_folders,
        save_quiz_folder_state=save_quiz_folder_state,
        print_message=print,
    )


def _delete_quiz_folder_metadata(folder):
    return _quiz_mutation_service.delete_quiz_folder_metadata(
        folder,
        registry_lock=registry_lock,
        load_registry=load_registry,
        save_registry=save_registry,
        get_quiz_folders=get_quiz_folders,
        get_hidden_quiz_folders=get_hidden_quiz_folders,
        save_quiz_folder_state=save_quiz_folder_state,
        print_message=print,
    )







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






# =========================
# DELETE QUESTION FROM QUIZ
# =========================


# =========================
# ADD CHOICES TO QUESTION
# =========================



# =========================
# DELETE CHOICE FROM QUESTION
# =========================


# =========================
# DELETE MATCHING PAIR FROM QUESTION
# =========================


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
            EXTERNAL_AI_DRAFT_FOLDER,
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




# Backward-compatible endpoint retained for older UI/bookmarks. Its scope remains
# the legacy quiz-library/database reset rather than the new full-data reset.


# =========================
# SAVE ORDER (DRAG + DROP)
# =========================



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
        if q.get("composition_sources") and isinstance(media_payload, dict):
            media_payload = dict(media_payload)
            media_payload["composition_sources"] = q["composition_sources"]

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
        staging_folder=CONTENT_PACK_STAGING_FOLDER,
        safe_pack_child=_safe_pack_child,
        secure_filename=secure_filename,
        validate_hotspot_shape=_validate_hotspot_shape,
        now=datetime.now,
        atomic_write_json=_atomic_write_json,
        validate_staged_content_pack=_validate_staged_content_pack,
        load_content_pack_quiz_dataset=load_content_pack_quiz_dataset,
        quiz_dataset_runtime=_quiz_dataset_runtime,
        publish_quiz=_create_quiz_from_runtime,
        copy_file=shutil.copy2,
        remove_tree=shutil.rmtree,
        promote_directory=os.rename,
        fsync_directory=_fsync_json_directory,
    )





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


# =========================================================
# EXTERNAL AI STRUCTURED QUIZ — BACKEND CONTRACT
# Additive External AI structured-text workflow. Archive builders remain separate.
# =========================================================
ExternalAIStructuredError = _external_ai_structured_parser.ExternalAIStructuredError
EXTERNAL_AI_STRUCTURED_MAX_INPUT_BYTES = (
    _external_ai_structured_parser.EXTERNAL_AI_MAX_INPUT_BYTES
)


def _build_external_ai_quiz_prompt(topic, question_count, **kwargs):
    return _external_ai_structured_service.build_external_ai_quiz_prompt(
        topic, question_count, **kwargs
    )


def _parse_external_ai_quiz_response(raw_response):
    return _external_ai_structured_parser.parse_external_ai_quiz_response(
        raw_response
    )


def _stage_external_ai_quiz_response(raw_response):
    return _external_ai_structured_service.stage_external_ai_quiz_response(
        EXTERNAL_AI_DRAFT_FOLDER, raw_response
    )


def _load_external_ai_draft(draft_id):
    return _external_ai_draft_repository.load_external_ai_draft(
        EXTERNAL_AI_DRAFT_FOLDER, draft_id
    )


def _update_external_ai_review_draft(draft_id, review_draft):
    return _external_ai_draft_repository.update_external_ai_review_draft(
        EXTERNAL_AI_DRAFT_FOLDER, draft_id, review_draft
    )


def _delete_external_ai_draft(draft_id):
    return _external_ai_draft_repository.delete_external_ai_draft(
        EXTERNAL_AI_DRAFT_FOLDER, draft_id
    )


def _prune_external_ai_drafts():
    return _external_ai_draft_repository.prune_external_ai_drafts(
        EXTERNAL_AI_DRAFT_FOLDER
    )


# =========================================================
# SMART PDF IMPORT — QUESTION BANK MVP
# Isolated from the existing text/paste/CSV parsers.
# =========================================================
PDF_IMPORT_MAX_BYTES = 64 * 1024 * 1024
OCR_SCREENSHOT_MAX_BATCH_BYTES = _ocr_screenshot_service.OCR_SCREENSHOT_MAX_BATCH_BYTES
OCR_SCREENSHOT_MAX_FILE_BYTES = _ocr_screenshot_service.OCR_SCREENSHOT_MAX_FILE_BYTES
OCR_SCREENSHOT_MAX_FILES = _ocr_screenshot_service.OCR_SCREENSHOT_MAX_FILES
OCR_SCREENSHOT_ALLOWED_EXTENSIONS = _ocr_screenshot_service.OCR_SCREENSHOT_ALLOWED_EXTENSIONS
OCR_SCREENSHOT_CANCELLATIONS = _ocr_screenshot_service.OCRTaskCancellationRegistry()
PDF_OCR_RENDER_LOCK = threading.RLock()
PDF_OCR_MAX_SELECTED_PAGES = _pdf_ocr_service.PDF_OCR_MAX_SELECTED_PAGES
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
        atomic_write_json=_atomic_write_json,
    )

def _load_pdf_import_draft(draft_id):
    return _pdf_bank_repository._load_pdf_import_draft(
        PDF_IMPORT_DRAFT_FOLDER,
        draft_id,
        path_for_id=_pdf_import_draft_path,
        os_module=os,
        json_module=json,
    )


def _save_pdf_import_upload(upload, draft_id):
    """Persist one bounded upload in configured Smart PDF draft storage."""
    temp_pdf = os.path.join(PDF_IMPORT_DRAFT_FOLDER, f"{draft_id}.pdf")
    try:
        os.makedirs(PDF_IMPORT_DRAFT_FOLDER, exist_ok=True)
        _bounded_save_upload(upload, temp_pdf, PDF_IMPORT_MAX_BYTES, "PDF")
    except Exception:
        try:
            os.remove(temp_pdf)
        except OSError:
            pass
        raise
    return temp_pdf


def _remove_pdf_import_upload(temp_pdf):
    if not temp_pdf:
        return
    try:
        os.remove(temp_pdf)
    except OSError:
        pass


def _store_pdf_ocr_screenshot(
    upload,
    destination_dir,
    source_id,
    *,
    max_bytes,
    max_pixels,
    max_side,
):
    """Store one OCR source through DLMS's trusted raster decode boundary."""
    original = secure_filename(getattr(upload, "filename", "") or "")
    extension = os.path.splitext(original)[1].lower()
    if extension not in OCR_SCREENSHOT_ALLOWED_EXTENSIONS:
        raise ValueError("unsupported screenshot type; use PNG, JPG/JPEG, or WebP")
    filename = f"{source_id}{extension}"
    _store_raster_upload(
        upload,
        destination_dir,
        filename,
        OCR_SCREENSHOT_ALLOWED_EXTENSIONS,
        max_bytes=max_bytes,
        max_pixels=max_pixels,
        max_width=max_side,
        max_height=max_side,
        max_frames=1,
        orient_from_exif=True,
        normalize_mode=True,
    )
    path = os.path.join(destination_dir, filename)
    _frames, metadata = _decode_raster_image(
        path,
        OCR_SCREENSHOT_ALLOWED_EXTENSIONS,
        max_pixels=max_pixels,
        max_width=max_side,
        max_height=max_side,
        max_frames=1,
    )
    mime_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }[extension]
    return {
        "filename": filename,
        "mime_type": mime_type,
        "width": int(metadata["size"][0]),
        "height": int(metadata["size"][1]),
        "consumed_bytes": int(getattr(upload, "_dlms_consumed_bytes", 0)),
    }


def _stage_pdf_ocr_screenshots(uploads, draft_id):
    return _ocr_screenshot_service.stage_screenshot_batch(
        OCR_IMPORT_STAGING_FOLDER,
        draft_id,
        uploads,
        store_validated_upload=_store_pdf_ocr_screenshot,
        atomic_write_json=_atomic_write_json,
    )


def _pdf_ocr_staged_source_path(draft_id, source):
    return _ocr_screenshot_service.staged_source_path(
        OCR_IMPORT_STAGING_FOLDER, draft_id, source
    )


def _cleanup_pdf_ocr_staging(draft_id):
    return _ocr_screenshot_service.cleanup_screenshot_task(
        OCR_IMPORT_STAGING_FOLDER, draft_id
    )


def _prune_pdf_ocr_staging():
    screenshot_count = _ocr_screenshot_service.prune_stale_screenshot_tasks(
        OCR_IMPORT_STAGING_FOLDER
    )
    pdf_count = _pdf_ocr_service.prune_stale_pdf_ocr_tasks(PDF_OCR_STAGING_FOLDER)
    return screenshot_count + pdf_count


def _recognize_pdf_ocr_source(draft_id, source, cancel_requested):
    path = _pdf_ocr_staged_source_path(draft_id, source)
    image_bytes = path.read_bytes()
    observations = _ocr_service.recognize_image_bytes(
        image_bytes,
        source_id=source["id"],
        source_width=int(source["width"]),
        source_height=int(source["height"]),
        page_index=int(source["index"]) - 1,
        cancel_requested=cancel_requested,
        image_suffix=path.suffix,
    )
    answer_regions = _ocr_question_parser.detect_answer_row_regions(
        image_bytes, observations
    )
    if answer_regions:
        try:
            recovered = _ocr_service.recognize_image_regions(
                image_bytes,
                answer_regions,
                source_id=source["id"],
                source_width=int(source["width"]),
                source_height=int(source["height"]),
                page_index=int(source["index"]) - 1,
                cancel_requested=cancel_requested,
            )
        except _ocr_service.OCRCancelledError:
            raise
        except _ocr_service.OCRError:
            answer_regions = ()
        else:
            if recovered:
                observations = _ocr_question_parser.merge_answer_row_observations(
                    observations, recovered, answer_regions
                )
            else:
                answer_regions = ()
    return {
        "observations": observations,
        "visual_markers": _ocr_question_parser.detect_visual_result_markers(
            image_bytes, observations, answer_regions=answer_regions
        ),
        "answer_regions": answer_regions,
    }


def _analyze_pdf_text_usefulness(pages):
    return _pdf_ocr_service.analyze_pdf_text_usefulness(pages)


def _stage_pdf_ocr_document(draft_id, pdf_path):
    return _pdf_ocr_service.stage_pdf_ocr_task(
        PDF_OCR_STAGING_FOLDER,
        draft_id,
        pdf_path,
        atomic_write_json=_atomic_write_json,
    )


def _render_pdf_ocr_page(draft_id, page_number, cancel_requested):
    return _pdf_ocr_service.render_pdf_page(
        PDF_OCR_STAGING_FOLDER,
        draft_id,
        page_number,
        render_lock=PDF_OCR_RENDER_LOCK,
        cancel_requested=cancel_requested,
    )


def _render_pdf_ocr_region(draft_id, source, cancel_requested):
    return _pdf_ocr_service.render_pdf_region(
        PDF_OCR_STAGING_FOLDER,
        draft_id,
        source["id"],
        source["page"],
        source["bbox"],
        render_lock=PDF_OCR_RENDER_LOCK,
        cancel_requested=cancel_requested,
    )


def _recognize_rendered_pdf_page(draft_id, source, cancel_requested):
    if source.get("source_type") == "question_region":
        path = _pdf_ocr_service.staged_region_path(
            PDF_OCR_STAGING_FOLDER, draft_id, source["id"]
        )
    else:
        path = _pdf_ocr_service.staged_page_path(
            PDF_OCR_STAGING_FOLDER, draft_id, source["page"]
        )
    return _ocr_service.recognize_image_bytes(
        path.read_bytes(),
        source_id=source["id"],
        source_width=int(source["width"]),
        source_height=int(source["height"]),
        page_index=int(source["page"]) - 1,
        cancel_requested=cancel_requested,
        image_suffix=".png",
    )


def _pdf_ocr_page_preview_path(draft_id, page_number):
    return _pdf_ocr_service.staged_page_path(
        PDF_OCR_STAGING_FOLDER, draft_id, page_number
    )


def _pdf_ocr_region_preview_path(draft_id, source_id):
    return _pdf_ocr_service.staged_region_path(
        PDF_OCR_STAGING_FOLDER, draft_id, source_id
    )


def _cleanup_pdf_document_ocr_staging(draft_id):
    return _pdf_ocr_service.cleanup_pdf_ocr_task(PDF_OCR_STAGING_FOLDER, draft_id)


def _delete_pdf_import_draft_file(draft_id):
    try:
        os.remove(_pdf_import_draft_path(draft_id))
    except OSError:
        pass

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


def _pdf_targeted_ocr_candidates(pages, question_result):
    return _pdf_raster_question_parser.targeted_ocr_candidates(
        pages,
        question_result,
        question_start_match=_pdf_question_start_match,
    )

# =====================================================
# SETTINGS HUB + INCREMENTAL SETTINGS MIGRATION
# =====================================================





























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




def _send_settings_backup_file(path):
    return send_from_directory(
        BACKUP_FOLDER,
        os.path.basename(path),
        as_attachment=True,
    )


def _discard_restore_stage(stage_dir):
    return shutil.rmtree(stage_dir, ignore_errors=True)


def _settings_restore_error(exc):
    public_error = (
        str(exc)
        if isinstance(exc, (DataRootOwnershipError, RestoreFutureSchemaError))
        else (
            "DLMS could not complete the restore. Existing data was preserved or "
            "rolled back. Check the local application log for details."
        )
    )
    status = (
        400
        if isinstance(exc, ValueError)
        else 409
        if isinstance(exc, DataRootOwnershipError)
        else 500
    )
    return public_error, status


def _settings_recent_backups():
    recent_backups = []
    try:
        for name in sorted(os.listdir(BACKUP_FOLDER), reverse=True):
            path = os.path.join(BACKUP_FOLDER, name)
            if name.lower().endswith(".zip") and os.path.isfile(path):
                recent_backups.append({
                    "name": name,
                    "size": _format_bytes(os.path.getsize(path)),
                    "modified": datetime.fromtimestamp(
                        os.path.getmtime(path)
                    ).strftime("%b %d, %Y %I:%M %p"),
                })
                if len(recent_backups) >= 5:
                    break
    except Exception:
        recent_backups = []
    return recent_backups























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


def _learning_foundation_summary(cur):
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
    return {
        "concepts": [dict(row) for row in concepts],
        "event_counts": {
            row["event_type"]: row["count"] for row in event_counts
        },
        "totals": (
            dict(totals)
            if totals
            else {"events": 0, "quizzes": 0, "questions": 0}
        ),
    }








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
        native_question_schedule=_native_spaced_repetition_schedule,
    )


def _native_spaced_repetition_schedule(cur, now=None):
    return _learning_service._native_spaced_repetition_schedule(cur, now=now)


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


def _adaptive_study_candidates(cur, now=None):
    return _learning_service._adaptive_study_candidates(
        cur,
        now=now,
        learning_topics_with_retention=_learning_topics_with_retention,
    )


def _adaptive_study_select_candidates(candidates, requested):
    return _learning_service._adaptive_study_select_candidates(
        candidates, requested
    )


def _daily_review_plan(cur, now=None):
    return _learning_service._daily_review_plan(
        cur,
        registry=load_registry(),
        installed_content_packs=content_pack_summary(),
        now=now,
        review_schedule_payload=_review_schedule_payload,
        learning_intelligence_payload=_learning_intelligence_payload,
        adaptive_study_candidates=_adaptive_study_candidates,
    )
















def _response_selected_labels(value):
    return _learning_service._response_selected_labels(value)


def _question_diagnostics_payload(cur):
    return _learning_service._question_diagnostics_payload(
        cur,
        question_concepts=_question_concepts,
        response_selected_labels=_response_selected_labels,
    )













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


def _clear_persistent_history():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("DELETE FROM attempt_answers")
    cur.execute("DELETE FROM missed_questions")
    cur.execute("DELETE FROM attempts")
    conn.commit()
    conn.close()














# =====================================================
# ANKI EXPORT HELPERS
# =====================================================

import genanki


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


def _load_anki_study_export_selection(quiz_id, question_numbers):
    conn = get_db()
    cur = conn.cursor()

    quiz_row = cur.execute(
        """
        SELECT title
        FROM quizzes
        WHERE id = ?
        """,
        (quiz_id,),
    ).fetchone()

    if not quiz_row:
        conn.close()
        return False, None, []

    questions = cur.execute(
        """
        SELECT id, question_number, question_text
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number, id
        """,
        (quiz_id,),
    ).fetchall()

    deck_rows = []
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
            (question["id"],),
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

        deck_rows.append({
            "front": "\n".join(front_parts),
            "back": "Correct Answer:\n" + "\n".join(correct_parts),
        })

    conn.close()
    return True, quiz_row["title"], deck_rows


def _load_anki_attempt_missed_rows(attempt_id):
    conn = get_db()
    cur = conn.cursor()
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
        [attempt_id],
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def _load_anki_missed_tsv_rows(attempt_id, attempt_qnums):
    conn = get_db()
    cur = conn.cursor()
    q_marks = ",".join("?" for _ in attempt_qnums)
    cur.execute(
        f"""
        SELECT
            mq.attempt_question_number,
            q.question_number AS question_number,
            q.question_text AS question_text,
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
    return rows
























def export_anki_tsv_for_quiz(quiz_id: int) -> str:
    return _anki_service.export_anki_tsv_for_quiz(quiz_id, get_db=get_db)


import logging

logger = logging.getLogger(__name__)


# =====================================================
# EXPORT FULL QUIZ → TSV (DIRECT DOWNLOAD)
# =====================================================

# =====================================================
# Anki Study Export (Selected Questions) → .apkg
# =====================================================





# =====================================================
# EXPORT MISSED QUESTIONS → GENANKI (.apkg)
# =====================================================







# =====================================================
# EXPORT MISSED QUESTIONS → TSV (ANKI IMPORT)
# =====================================================
def _format_anki_missed_tsv(rows):
    return _anki_service.format_anki_missed_tsv(rows, logger=logger)

































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



# =========================
# DATABASE HELPERS
# =========================
def get_db():
    dprint(f"[DB] get_db using DB_PATH = {DB_PATH}")
    return _database.get_db(DB_PATH, sqlite_module=sqlite3)




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


app.register_blueprint(create_settings_blueprint(SettingsRouteDependencies(
    default_theme=lambda: DEFAULT_THEME,
    default_law_ai_prompt=lambda: DEFAULT_LAW_AI_PROMPT,
    default_study_content_pack_prompt=lambda: DEFAULT_STUDY_CONTENT_PACK_PROMPT,
    default_medical_study_pack_ai_addendum=lambda: DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
    load_portal_config=lambda: load_portal_config(),
    write_portal_config=lambda config: _write_settings_portal_config(config),
    store_background_upload=lambda upload: _store_settings_background_upload(upload),
    validate_custom_ai_url=lambda value: _validate_custom_ai_url(value),
    set_browser_presence_shutdown_enabled=lambda enabled: browser_presence_manager.set_enabled(enabled),
    browser_presence_shutdown_runtime_eligible=lambda: _browser_presence_runtime_eligible(),
    print_message=lambda *args, **kwargs: print(*args, **kwargs),
)))


app.register_blueprint(create_maintenance_blueprint(MaintenanceRouteDependencies(
    backup_upload_max_bytes=lambda: BACKUP_UPLOAD_MAX_BYTES,
    upload_multipart_overhead_bytes=lambda: UPLOAD_MULTIPART_OVERHEAD_BYTES,
    create_backup=lambda label: _create_dlms_backup(label),
    send_backup_file=lambda path: _send_settings_backup_file(path),
    make_restore_token=lambda: secrets.token_hex(16),
    restore_staging_dir=lambda token: _restore_staging_dir(token),
    create_backup_restore_stage=lambda stage_dir: _backup_service.create_backup_restore_stage(
        stage_dir
    ),
    stage_backup=lambda upload, token, **kwargs: _stage_dlms_backup(
        upload,
        token,
        **kwargs,
    ),
    discard_restore_stage=lambda stage_dir: _discard_restore_stage(stage_dir),
    restore_operation_lock=RESTORE_OPERATION_LOCK,
    cancel_validated_restore_stage=lambda token: _cancel_validated_restore_stage(token),
    complete_staged_restore=lambda token: _complete_staged_restore(token),
    restore_error=lambda exc: _settings_restore_error(exc),
    safety_backup_name=lambda path: os.path.basename(path),
    recent_backups=lambda: _settings_recent_backups(),
    app_data_dir=lambda: APP_DATA_DIR,
    run_quiz_library_reset=lambda: _run_reset_with_backup(
        "quiz-library", _reset_quiz_library_core
    ),
    run_learning_intelligence_reset=lambda: _run_reset_with_backup(
        "learning-intelligence", _reset_learning_intelligence_core
    ),
    run_source_content_reset=lambda: _run_reset_with_backup(
        "source-content", _reset_source_content_core
    ),
    run_app_settings_reset=lambda: _run_reset_with_backup(
        "settings", _reset_app_settings_core
    ),
    run_full_data_reset=lambda: _run_reset_with_backup(
        "full-data", _full_data_reset_core
    ),
    run_legacy_wipe=lambda: _run_reset_with_backup(
        "legacy-wipe", _reset_quiz_library_core
    ),
    destructive_operation_error=lambda exc, operation: _destructive_operation_error(
        exc,
        operation,
    ),
    remove_all_runtime_data=lambda: _remove_all_dlms_runtime_data_core(),
    schedule_post_removal_shutdown=lambda removed_path: _schedule_post_removal_shutdown(
        removed_path
    ),
    print_message=lambda *args, **kwargs: print(*args, **kwargs),
)))


app.register_blueprint(create_anki_blueprint(AnkiRouteDependencies(
    app_version=lambda: APP_VERSION,
    get_anki_quiz_choices=lambda: get_anki_quiz_choices(),
    get_anki_law_case_choices=lambda: get_anki_law_case_choices(),
    get_anki_law_courses=lambda law_cases=None: get_anki_law_courses(law_cases),
    get_anki_missed_summary=lambda: get_anki_missed_summary(),
    get_anki_custom_sources=lambda: get_anki_custom_sources(),
    build_anki_rows_for_quiz=lambda quiz_id: build_anki_rows_for_quiz(quiz_id),
    build_anki_rows_for_missed=lambda quiz_id, min_misses, missed_status: build_anki_rows_for_missed(
        quiz_id,
        min_misses,
        missed_status,
    ),
    build_custom_anki_rows=lambda quiz_tokens, missed_tokens, law_tokens: build_custom_anki_rows(
        quiz_tokens,
        missed_tokens,
        law_tokens,
    ),
    load_law_flashcards_for_selection=lambda **kwargs: load_law_flashcards_for_selection(
        **kwargs
    ),
    load_law_flashcards_for_case=lambda case_id: load_law_flashcards_for_case(case_id),
    export_quiz_to_apkg=lambda deck_name, deck_rows: export_quiz_to_apkg(
        deck_name,
        deck_rows,
    ),
    send_temp_anki_package=lambda apkg_path, download_name: _send_temp_anki_package(
        apkg_path,
        download_name,
    ),
    make_safe_anki_download_name=lambda name, fallback: make_safe_anki_download_name(
        name,
        fallback,
    ),
    make_safe_anki_deck_name=lambda name, fallback: make_safe_anki_deck_name(
        name,
        fallback,
    ),
    export_anki_tsv_for_quiz=lambda quiz_id: export_anki_tsv_for_quiz(quiz_id),
    load_study_export_selection=lambda quiz_id, question_numbers: _load_anki_study_export_selection(
        quiz_id,
        question_numbers,
    ),
    load_attempt_missed_rows=lambda attempt_id: _load_anki_attempt_missed_rows(
        attempt_id
    ),
    load_missed_tsv_rows=lambda attempt_id, question_numbers: _load_anki_missed_tsv_rows(
        attempt_id,
        question_numbers,
    ),
    attempt_history_context=lambda: _attempt_history_context(),
    format_anki_missed_tsv=lambda rows: _format_anki_missed_tsv(rows),
    log_info=lambda *args, **kwargs: logger.info(*args, **kwargs),
)))


app.register_blueprint(create_learning_blueprint(LearningRouteDependencies(
    static_folder=lambda: app.static_folder,
    static_root=lambda: STATIC_ROOT,
    get_db=lambda: get_db(),
    learning_payload_error=lambda: LearningPayloadError,
    persist_attempt=lambda conn, cur, data: _attempt_service.persist_attempt(
        conn,
        cur,
        data,
        validate_attempt_payload=_validate_attempt_payload,
        attempt_retry_matches_existing=_attempt_retry_matches_existing,
        record_learning_event=_record_learning_event,
        json_module=json,
        print_message=print,
    ),
    persist_study_learning_event=lambda conn, cur, data: _attempt_service.persist_study_learning_event(
        conn,
        cur,
        data,
        learning_integer=_learning_integer,
        optional_learning_identifier=_optional_learning_identifier,
        question_response_context_by_ordinal=_question_response_context_by_ordinal,
        validate_question_response=_validate_question_response,
        record_learning_event=_record_learning_event,
        json_module=json,
    ),
    learning_foundation_summary=lambda cur: _learning_foundation_summary(cur),
    smart_review_candidates=lambda cur: _smart_review_candidates(cur),
    smart_review_select_candidates=lambda candidates, weak, requested: _smart_review_select_candidates(
        candidates, weak, requested
    ),
    review_candidates_for_topics=lambda cur, topics: _review_candidates_for_topics(
        cur, topics
    ),
    review_select_candidates=lambda candidates, topics, requested: _review_select_candidates(
        candidates, topics, requested
    ),
    adaptive_study_candidates=lambda cur: _adaptive_study_candidates(cur),
    adaptive_study_select_candidates=lambda candidates, requested: _adaptive_study_select_candidates(
        candidates, requested
    ),
    daily_review_plan=lambda cur: _daily_review_plan(cur),
    question_payload_from_db=lambda cur, question_id: _question_payload_from_db(
        cur, question_id
    ),
    publish_quiz=lambda *args, **kwargs: _publish_quiz(*args, **kwargs),
    review_schedule_payload=lambda cur: _review_schedule_payload(cur),
    question_diagnostics_payload=lambda cur: _question_diagnostics_payload(cur),
    learning_profile_payload=lambda cur: _learning_profile_payload(cur),
    learning_intelligence_payload=lambda cur: _learning_intelligence_payload(cur),
)))


app.register_blueprint(create_history_blueprint(HistoryRouteDependencies(
    static_folder=lambda: app.static_folder,
    get_db=lambda: get_db(),
    parse_attempt_pagination=lambda: _parse_attempt_pagination(),
    attempt_page=lambda cur, page, page_size, origin: _history_service.attempt_page(
        cur,
        page,
        page_size,
        origin,
        attempt_columns=_attempt_columns,
        attempt_history_context=_attempt_history_context,
        attempt_origin_where=_attempt_origin_where,
        attempt_select_sql=_attempt_select_sql,
        attempt_summary_from_row=_attempt_summary_from_row,
    ),
    attempt_overview=lambda cur: _history_service.attempt_overview(
        cur,
        attempt_columns=_attempt_columns,
        attempt_history_context=_attempt_history_context,
        attempt_select_sql=_attempt_select_sql,
        attempt_summary_from_row=_attempt_summary_from_row,
    ),
    attempt_analytics=lambda cur: _history_service.attempt_analytics(
        cur,
        attempt_columns=_attempt_columns,
        attempt_history_context=_attempt_history_context,
        attempt_summary_from_row=_attempt_summary_from_row,
    ),
    attempt_summary=lambda cur, attempt_reference: _history_service.attempt_summary(
        cur,
        attempt_reference,
        attempt_columns=_attempt_columns,
        resolve_attempt_row=_resolve_attempt_row,
        attempt_history_context=_attempt_history_context,
        attempt_summary_from_row=_attempt_summary_from_row,
    ),
    missed_questions=lambda cur, attempt_id: _history_service.missed_questions(
        cur,
        attempt_id,
        resolve_attempt_row=_resolve_attempt_row,
        missed_rows_for_attempt=_missed_rows_for_attempt,
        json_module=json,
    ),
    clear_persistent_history=lambda: _clear_persistent_history(),
)))


app.register_blueprint(create_law_blueprint(LawRouteDependencies(
    app_version=lambda: APP_VERSION,
    default_law_ai_prompt=lambda: DEFAULT_LAW_AI_PROMPT,
    get_portal_title=lambda: get_portal_title(),
    load_portal_config=lambda: load_portal_config(),
    load_law_registry=lambda: load_law_registry(),
    law_case_path=lambda case_file: os.path.join(LAW_CASES_FOLDER, case_file),
    resolve_law_import_path=lambda import_file: _law_service.resolve_law_raw_import_path(
        LAW_IMPORTS_FOLDER,
        import_file,
        listdir=os.listdir,
        join_path=os.path.join,
    ),
    make_law_case_slug=lambda case_name: make_law_case_slug(case_name),
    canonical_law_import_filename=lambda filename: canonical_law_import_filename(filename),
    canonical_law_case_id=lambda case_id: canonical_law_case_id(case_id),
    save_law_raw_packet=lambda raw_packet, case_slug="": save_law_raw_packet(raw_packet, case_slug),
    parse_law_packet_sections=lambda raw_text: parse_law_packet_sections(raw_text),
    get_law_case_by_id=lambda case_id: get_law_case_by_id(case_id),
    load_law_case_data=lambda case_path: _load_law_case_data(case_path),
    parse_socratic_questions=lambda text: parse_socratic_questions(text),
    start_pending_case_workflow=lambda registry, **kwargs: _law_service.start_pending_case_workflow(
        registry,
        save_law_registry=save_law_registry,
        **kwargs,
    ),
    cancel_pending_case_workflow=lambda registry: _law_service.cancel_pending_case_workflow(
        registry,
        save_law_registry=save_law_registry,
    ),
    list_law_raw_imports=lambda *, imports: _law_service.list_law_raw_imports(
        LAW_IMPORTS_FOLDER,
        from_timestamp=datetime.fromtimestamp,
        canonical_law_import_filename=canonical_law_import_filename,
        imports=imports,
        makedirs=os.makedirs,
        listdir=os.listdir,
        join_path=os.path.join,
        isfile=os.path.isfile,
        stat_file=os.stat,
    ),
    load_law_raw_packet=lambda import_path: _law_service.load_law_raw_packet(
        import_path,
        open_file=open,
    ),
    delete_law_raw_packet=lambda import_path: _law_service.delete_law_raw_packet(
        import_path,
        exists=os.path.exists,
        isfile=os.path.isfile,
        remove_file=os.remove,
    ),
    create_law_case_from_import=lambda safe_name, raw_packet, parsed_sections: _law_service.create_law_case_from_import(
        safe_name,
        raw_packet,
        parsed_sections,
        cases_folder=LAW_CASES_FOLDER,
        load_law_registry=load_law_registry,
        extract_law_slug_from_import_filename=extract_law_slug_from_import_filename,
        extract_law_case_title=extract_law_case_title,
        secure_filename=secure_filename,
        canonical_law_case_id=canonical_law_case_id,
        now=datetime.now,
        commit_law_case_and_registry=_commit_law_case_and_registry,
        makedirs=os.makedirs,
        join_path=os.path.join,
        isfile=os.path.isfile,
    ),
    update_law_case_details=lambda case_path, case_id, case_entry, new_title, new_course: _law_service.update_law_case_details(
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
    ),
    delete_law_case_and_registry=lambda case_path, registry, case_id: _delete_law_case_and_registry(
        case_path,
        registry,
        case_id,
    ),
    update_law_case_notes=lambda case_path, case_id, student_notes: _law_service.update_law_case_notes(
        case_path,
        case_id,
        student_notes,
        now=datetime.now,
        load_law_registry=load_law_registry,
        registry_case_for_mutation=_law_registry_case_for_mutation,
        commit_law_case_and_registry=_commit_law_case_and_registry,
        load_case_data=_load_law_case_data,
    ),
    update_law_case_socratic_answers=lambda case_path, case_id, form_data: _law_service.update_law_case_socratic_answers(
        case_path,
        case_id,
        form_data,
        now=datetime.now,
        parse_socratic_questions=parse_socratic_questions,
        load_law_registry=load_law_registry,
        registry_case_for_mutation=_law_registry_case_for_mutation,
        commit_law_case_and_registry=_commit_law_case_and_registry,
        load_case_data=_load_law_case_data,
    ),
    update_law_case_irac_response=lambda case_path, case_id, irac_response: _law_service.update_law_case_irac_response(
        case_path,
        case_id,
        irac_response,
        now=datetime.now,
        load_law_registry=load_law_registry,
        registry_case_for_mutation=_law_registry_case_for_mutation,
        commit_law_case_and_registry=_commit_law_case_and_registry,
        load_case_data=_load_law_case_data,
    ),
    build_law_case_export=lambda *args, **kwargs: _law_service.build_law_case_export(*args, **kwargs),
    secure_filename=lambda filename: secure_filename(filename),
    now=lambda: datetime.now(),
    from_timestamp=lambda timestamp: datetime.fromtimestamp(timestamp),
)))


app.register_blueprint(create_external_ai_blueprint(ExternalAIRouteDependencies(
    build_prompt=lambda topic, question_count, **kwargs: _build_external_ai_quiz_prompt(
        topic, question_count, **kwargs
    ),
    stage_response=lambda raw_response: _stage_external_ai_quiz_response(raw_response),
    load_draft=lambda draft_id: _load_external_ai_draft(draft_id),
    update_review_draft=lambda draft_id, review_draft: _update_external_ai_review_draft(
        draft_id, review_draft
    ),
    delete_draft=lambda draft_id: _delete_external_ai_draft(draft_id),
    publish_quiz=lambda *args, **kwargs: _publish_quiz(*args, **kwargs),
    normalize_exam_minutes=lambda value: normalize_exam_minutes(value),
    print_message=lambda message: print(message),
)))


app.register_blueprint(create_pdf_import_blueprint(PDFImportRouteDependencies(
    pdf_import_max_bytes=lambda: PDF_IMPORT_MAX_BYTES,
    upload_multipart_overhead_bytes=lambda: UPLOAD_MULTIPART_OVERHEAD_BYTES,
    save_pdf_import_upload=lambda upload, draft_id: _save_pdf_import_upload(upload, draft_id),
    remove_pdf_import_upload=lambda temp_pdf: _remove_pdf_import_upload(temp_pdf),
    save_pdf_import_draft=lambda draft: _save_pdf_import_draft(draft),
    load_pdf_import_draft=lambda draft_id: _load_pdf_import_draft(draft_id),
    delete_pdf_import_draft=lambda draft_id: _delete_pdf_import_draft_file(draft_id),
    list_pdf_question_banks=lambda: _list_pdf_question_banks(),
    save_pdf_question_bank=lambda bank: _save_pdf_question_bank(bank),
    load_pdf_question_bank=lambda bank_id: _load_pdf_question_bank(bank_id),
    delete_pdf_question_bank=lambda bank_id: _delete_pdf_question_bank(bank_id),
    list_pdf_terminology_banks=lambda: _list_pdf_terminology_banks(),
    save_pdf_terminology_bank=lambda bank: _save_pdf_terminology_bank(bank),
    load_pdf_terminology_bank=lambda bank_id: _load_pdf_terminology_bank(bank_id),
    delete_pdf_terminology_bank=lambda bank_id: _delete_pdf_terminology_bank(bank_id),
    extract_pdf_pages=lambda pdf_path: _pdf_extract_pages(pdf_path),
    suppress_repeated_pdf_margins=lambda pages: _pdf_suppress_repeated_margins(pages),
    parse_pdf_question_bank=lambda pages: _pdf_parse_question_bank(pages),
    parse_pdf_glossary=lambda pages: _pdf_parse_glossary(pages),
    detect_pdf_document_type=lambda *args, **kwargs: _pdf_detect_document_type(*args, **kwargs),
    recover_pdf_questions=lambda pages: _pdf_question_recovery_result(pages),
    recover_pdf_glossary=lambda pages: _pdf_glossary_recovery_result(pages),
    add_pdf_question_review_slots=lambda question: _pdf_add_question_review_slots(question),
    secure_filename=lambda filename: secure_filename(filename),
    normalize_exam_minutes=lambda value: normalize_exam_minutes(value),
    timestamp_now=lambda: datetime.now().isoformat(timespec="seconds"),
    publish_quiz=lambda *args, **kwargs: _publish_quiz(*args, **kwargs),
    create_quiz_from_runtime=lambda *args, **kwargs: _create_quiz_from_runtime(*args, **kwargs),
    ocr_screenshot_max_files=lambda: OCR_SCREENSHOT_MAX_FILES,
    ocr_screenshot_max_file_bytes=lambda: OCR_SCREENSHOT_MAX_FILE_BYTES,
    ocr_screenshot_max_batch_bytes=lambda: OCR_SCREENSHOT_MAX_BATCH_BYTES,
    detect_ocr_runtime=lambda: _ocr_service.detect_tesseract_runtime(),
    diagnose_ocr_runtime=lambda: _ocr_service.diagnose_tesseract_runtime(),
    prune_ocr_staging=lambda: _prune_pdf_ocr_staging(),
    stage_ocr_screenshots=lambda uploads, draft_id: _stage_pdf_ocr_screenshots(
        uploads, draft_id
    ),
    recognize_ocr_source=lambda draft_id, source, cancel_requested: _recognize_pdf_ocr_source(
        draft_id, source, cancel_requested
    ),
    infer_ocr_questions=lambda observations, **kwargs: _ocr_question_parser.infer_screenshot_questions(
        observations, **kwargs
    ),
    ocr_staged_source_path=lambda draft_id, source: _pdf_ocr_staged_source_path(
        draft_id, source
    ),
    cleanup_ocr_staging=lambda draft_id: _cleanup_pdf_ocr_staging(draft_id),
    pdf_ocr_max_selected_pages=lambda: PDF_OCR_MAX_SELECTED_PAGES,
    analyze_pdf_text_usefulness=lambda pages: _analyze_pdf_text_usefulness(pages),
    find_pdf_targeted_ocr_candidates=lambda pages, result: _pdf_targeted_ocr_candidates(
        pages, result
    ),
    stage_pdf_ocr_document=lambda draft_id, pdf_path: _stage_pdf_ocr_document(
        draft_id, pdf_path
    ),
    validate_pdf_ocr_selection=lambda selected, candidates: _pdf_ocr_service.validate_selected_pages(
        selected, candidates
    ),
    render_pdf_ocr_page=lambda draft_id, page_number, cancel_requested: _render_pdf_ocr_page(
        draft_id, page_number, cancel_requested
    ),
    render_pdf_ocr_region=lambda draft_id, source, cancel_requested: _render_pdf_ocr_region(
        draft_id, source, cancel_requested
    ),
    recognize_pdf_ocr_page=lambda draft_id, source, cancel_requested: _recognize_rendered_pdf_page(
        draft_id, source, cancel_requested
    ),
    parse_pdf_raster_choices=lambda observations: _pdf_raster_question_parser.parse_targeted_raster_choices(
        observations
    ),
    merge_pdf_raster_choices=lambda question, recovered, source: _pdf_raster_question_parser.merge_targeted_raster_result(
        question, recovered, source
    ),
    pdf_ocr_page_preview_path=lambda draft_id, page_number: _pdf_ocr_page_preview_path(
        draft_id, page_number
    ),
    pdf_ocr_region_preview_path=lambda draft_id, source_id: _pdf_ocr_region_preview_path(
        draft_id, source_id
    ),
    cleanup_pdf_ocr_staging=lambda draft_id: _cleanup_pdf_document_ocr_staging(
        draft_id
    ),
    ocr_cancellations=OCR_SCREENSHOT_CANCELLATIONS,
)))


app.register_blueprint(create_content_packs_blueprint(ContentPackRouteDependencies(
    content_pack_ai_workflow=lambda: CONTENT_PACK_AI_WORKFLOW,
    content_pack_upload_max_bytes=lambda: CONTENT_PACK_UPLOAD_MAX_BYTES,
    content_pack_multipart_overhead_bytes=lambda: CONTENT_PACK_MULTIPART_OVERHEAD_BYTES,
    content_pack_folder=lambda: CONTENT_PACK_FOLDER,
    stage_content_pack_upload=lambda *args, **kwargs: _stage_content_pack_upload(*args, **kwargs),
    content_pack_workflow=lambda metadata: _content_pack_workflow(metadata),
    content_pack_workflow_return_url=lambda metadata: _content_pack_workflow_return_url(metadata),
    load_staged_content_pack=lambda token: _load_staged_content_pack(token),
    validate_staged_content_pack=lambda *args, **kwargs: _validate_staged_content_pack(*args, **kwargs),
    install_staged_content_pack=lambda token: _install_staged_content_pack(token),
    cancel_staged_content_pack=lambda token: _cancel_staged_content_pack(token),
    content_pack_folder_report=lambda folder: _content_pack_folder_report(folder),
    build_content_pack_export=lambda folder: _build_content_pack_export(folder),
    content_pack_management_summary=lambda: content_pack_management_summary(),
    delete_content_pack_folder=lambda folder: _delete_content_pack_folder(folder),
    content_pack_install_error=lambda: _content_pack_mutation_service.ContentPackInstallError,
    invalid_content_pack_folder_error=lambda: _content_pack_mutation_service.InvalidContentPackFolderError,
    content_pack_folder_not_found_error=lambda: _content_pack_mutation_service.ContentPackFolderNotFoundError,
    protected_content_pack_error=lambda: _content_pack_mutation_service.ProtectedContentPackError,
)))

app.register_blueprint(create_study_packs_blueprint(StudyPackRouteDependencies(
    content_pack_ai_workflow=lambda: CONTENT_PACK_AI_WORKFLOW,
    stage_content_pack_upload=lambda *args, **kwargs: _stage_content_pack_upload(*args, **kwargs),
    discover_content_packs=lambda: discover_content_packs(),
    study_pack_catalog_domain_group=lambda pack_id, pack: _study_pack_catalog_domain_group(pack_id, pack),
    load_content_pack_dataset=lambda pack_id, dataset_id: load_content_pack_dataset(pack_id, dataset_id),
    load_content_pack_image_dataset=lambda pack_id, dataset_id: load_content_pack_image_dataset(pack_id, dataset_id),
    load_content_pack_quiz_dataset=lambda pack_id, dataset_id: load_content_pack_quiz_dataset(pack_id, dataset_id),
    get_content_pack=lambda pack_id: get_content_pack(pack_id),
    quiz_dataset_runtime=lambda pack_id, data: _quiz_dataset_runtime(pack_id, data),
    create_quiz_from_runtime=lambda *args, **kwargs: _create_quiz_from_runtime(*args, **kwargs),
    publish_quiz=lambda *args, **kwargs: _publish_quiz(*args, **kwargs),
    standalone_matching_concepts=lambda *args, **kwargs: _standalone_matching_concepts(*args, **kwargs),
    hotspot_concepts=lambda *args, **kwargs: _hotspot_concepts(*args, **kwargs),
    load_portal_config=lambda: load_portal_config(),
    default_study_content_pack_prompt=lambda: DEFAULT_STUDY_CONTENT_PACK_PROMPT,
    default_medical_study_pack_ai_addendum=lambda: DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
    safe_image_builder_draft=lambda draft_id: _safe_image_builder_draft(draft_id),
    safe_pack_child=lambda root, path: _safe_pack_child(root, path),
    passive_pack_image_extensions=lambda: PASSIVE_PACK_IMAGE_EXTENSIONS,
    decode_raster_image=lambda *args, **kwargs: _decode_raster_image(*args, **kwargs),
    image_builder_draft_folder=lambda: IMAGE_BUILDER_DRAFT_FOLDER,
    image_builder_total_upload_max_bytes=lambda: IMAGE_BUILDER_TOTAL_UPLOAD_MAX_BYTES,
    raster_upload_max_bytes=lambda: RASTER_UPLOAD_MAX_BYTES,
    store_raster_upload=lambda *args, **kwargs: _store_raster_upload(*args, **kwargs),
    create_image_study_pack=lambda *args, **kwargs: _create_image_study_pack(*args, **kwargs),
    generated_quiz_artifact_identity=lambda: _generated_quiz_artifact_identity(),
)))

app.register_blueprint(create_medical_blueprint(MedicalRouteDependencies(
    discover_content_packs=lambda: discover_content_packs(),
    is_medical_content_pack=lambda pack_id, pack: _is_medical_pack_manifest(pack_id, pack),
    load_content_pack_dataset=lambda pack_id, dataset_id: load_content_pack_dataset(pack_id, dataset_id),
    load_content_pack_image_dataset=lambda pack_id, dataset_id: load_content_pack_image_dataset(pack_id, dataset_id),
    content_pack_folder=lambda: CONTENT_PACK_FOLDER,
    get_content_pack=lambda pack_id: get_content_pack(pack_id),
    hotspot_concepts=lambda *args, **kwargs: _hotspot_concepts(*args, **kwargs),
    standalone_matching_concepts=lambda *args, **kwargs: _standalone_matching_concepts(*args, **kwargs),
    publish_quiz=lambda *args, **kwargs: _publish_quiz(*args, **kwargs),
)))

app.register_blueprint(create_admin_images_blueprint(AdminImageRouteDependencies(
    discover_content_packs=lambda: discover_content_packs(),
    load_content_pack_image_dataset=lambda pack_id, dataset_id: load_content_pack_image_dataset(pack_id, dataset_id),
    load_content_pack_quiz_dataset=lambda pack_id, dataset_id: load_content_pack_quiz_dataset(pack_id, dataset_id),
    validate_hotspot_shape=lambda shape: _validate_hotspot_shape(shape),
    get_content_pack=lambda pack_id: get_content_pack(pack_id),
    safe_pack_child=lambda root, path: _safe_pack_child(root, path),
)))


app.register_blueprint(create_quiz_blueprint(
    QuizLibraryDependencies(
        app_version=lambda: APP_VERSION,
        logo_folder=lambda: LOGO_FOLDER,
        quiz_registry_path=lambda: QUIZ_REGISTRY,
        registry_lock=lambda: registry_lock,
        load_registry=lambda: load_registry(),
        save_registry=lambda registry: save_registry(registry),
        normalize_quiz_folders=lambda registry: normalize_quiz_folders(registry),
        build_quiz_folder_identity=lambda folders, registry: (
            _quiz_mutation_service.build_quiz_folder_identity(folders, registry)
        ),
        get_quiz_folders=lambda: get_quiz_folders(),
        save_quiz_folders=lambda folders: save_quiz_folders(folders),
        get_hidden_quiz_folders=lambda folders=None: get_hidden_quiz_folders(folders),
        save_quiz_folder_state=lambda folders, hidden: save_quiz_folder_state(folders, hidden),
        rename_quiz_folder_metadata=lambda old_folder, new_folder: (
            _rename_quiz_folder_metadata(old_folder, new_folder)
        ),
        delete_quiz_folder_metadata=lambda folder: (
            _delete_quiz_folder_metadata(folder)
        ),
        get_portal_title=lambda: get_portal_title(),
        resolve_logo_filename=lambda filename: resolve_logo_filename(filename),
        debug_print=lambda *args, **kwargs: dprint(*args, **kwargs),
        get_db=lambda: get_db(),
        mixed_quiz_catalog=lambda cur, registry: (
            _quiz_composition_service.build_mixed_quiz_catalog(cur, registry)
        ),
        mixed_quiz_filter_options=lambda catalog: (
            _quiz_composition_service.mixed_quiz_filter_options(catalog)
        ),
        question_payload_from_db=lambda cur, question_id: (
            _question_payload_from_db(cur, question_id)
        ),
        publish_quiz=lambda *args, **kwargs: _publish_quiz(*args, **kwargs),
    ),
    QuizEditorDependencies(
        app_version=lambda: APP_VERSION,
        data_folder=lambda: DATA_FOLDER,
        browser_served_data_extensions=lambda: BROWSER_SERVED_DATA_EXTENSIONS,
        quiz_folder=lambda: QUIZ_FOLDER,
        get_db=lambda: get_db(),
        load_registry=lambda: load_registry(),
        normalize_exam_minutes=lambda value: normalize_exam_minutes(value),
        question_concepts=lambda cur, question_id: _question_concepts(cur, question_id),
        finish_quiz_mutation=lambda *args, **kwargs: _finish_quiz_mutation(*args, **kwargs),
        quiz_owns_question=lambda *args, **kwargs: _quiz_owns_question(*args, **kwargs),
        quiz_owns_choice=lambda *args, **kwargs: _quiz_owns_choice(*args, **kwargs),
        quiz_owns_matching_pair=lambda *args, **kwargs: _quiz_owns_matching_pair(*args, **kwargs),
        set_question_concepts=lambda *args, **kwargs: _set_question_concepts(*args, **kwargs),
        quiz_edit_validation=lambda *args, **kwargs: _quiz_edit_validation(*args, **kwargs),
        publish_quiz_edit_request=lambda *args, **kwargs: _publish_quiz_edit_request(*args, **kwargs),
        delete_quiz_transaction=lambda *args, **kwargs: _delete_quiz_transaction(*args, **kwargs),
        cleanup_deleted_quiz_artifacts=lambda *args, **kwargs: _cleanup_deleted_quiz_artifacts(*args, **kwargs),
        rebuild_quiz_html_from_registry=lambda *args, **kwargs: rebuild_quiz_html_from_registry(*args, **kwargs),
    ),
    QuizAuthoringDependencies(
        data_folder=lambda: DATA_FOLDER,
        logo_folder=lambda: LOGO_FOLDER,
        parse_log_path=lambda: PARSE_LOG,
        upload_folder=lambda: UPLOAD_FOLDER,
        matching_csv_upload_max_bytes=lambda: MATCHING_CSV_UPLOAD_MAX_BYTES,
        quiz_text_upload_max_bytes=lambda: QUIZ_TEXT_UPLOAD_MAX_BYTES,
        upload_too_large_error=lambda: UploadTooLargeError,
        get_portal_title=lambda: get_portal_title(),
        load_portal_config=lambda: load_portal_config(),
        matching_case_only_term_warnings=lambda *args, **kwargs: _matching_case_only_term_warnings(*args, **kwargs),
        matching_record_validation_errors=lambda *args, **kwargs: _matching_record_validation_errors(*args, **kwargs),
        publish_quiz=lambda *args, **kwargs: _publish_quiz(*args, **kwargs),
        read_bounded_upload=lambda *args, **kwargs: _read_bounded_upload(*args, **kwargs),
        normalize_exam_minutes=lambda value: normalize_exam_minutes(value),
        finalize_logo_from_request=lambda *args, **kwargs: finalize_logo_from_request(*args, **kwargs),
        save_preview_logo=lambda *args, **kwargs: save_preview_logo(*args, **kwargs),
        get_confidence_setting=lambda: get_confidence_setting(),
        analyze_confidence=lambda text: analyze_confidence(text),
        parse_questions=lambda source: parse_questions(source),
        debug_print=lambda *args, **kwargs: dprint(*args, **kwargs),
    ),
))





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
    try:
        startup = _dlms_parse_startup_options()
    except ValueError as exc:
        print(f"[DLMS] Startup error: {exc}", file=sys.stderr)
        raise SystemExit(2)

    server_host = startup["host"]
    start_browser_presence_monitor(server_host)
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
