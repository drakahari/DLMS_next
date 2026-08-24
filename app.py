from flask import Flask, send_from_directory, request, redirect, render_template_string, jsonify, Response, flash, url_for
import os, re, json, time, sqlite3, sys, shutil, signal, threading, csv, io, random, secrets, zipfile
from datetime import datetime
from werkzeug.utils import secure_filename

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
def get_app_data_dir(app_name: str = "DLMS") -> str:
    override = os.getenv("QUIZAPP_DATA_DIR")
    if override:
        os.makedirs(override, exist_ok=True)
        return override

    if sys.platform == "win32":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    path = os.path.join(base, app_name)
    os.makedirs(path, exist_ok=True)
    return path

APP_NAME = "DLMS"
APP_VERSION = "3.0.0"
APP_DATA_DIR = get_app_data_dir(APP_NAME)

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

# =========================
# FLASK APP
# =========================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(
    __name__,
    static_folder=STATIC_ROOT,
    static_url_path="/static"
)
app.secret_key = "dlms-dev"




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
        os.makedirs(override, exist_ok=True)
        return override

    if sys.platform == "win32":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    path = os.path.join(base, app_name)
    os.makedirs(path, exist_ok=True)
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
    LOGO_FOLDER,
    LAW_FOLDER,
    LAW_CASES_FOLDER,
    LAW_IMPORTS_FOLDER,
    LAW_EXPORTS_FOLDER,
    #STATIC_LOGO_FOLDER,
]:
    os.makedirs(d, exist_ok=True)




# =========================
# CONTENT PACK FRAMEWORK
# =========================
CONTENT_PACK_SCHEMA_VERSION = 1

def _safe_pack_child(pack_root, relative_path):
    """Resolve a pack-relative path without allowing traversal outside the pack."""
    pack_root = os.path.realpath(pack_root)
    candidate = os.path.realpath(os.path.join(pack_root, relative_path))
    if candidate != pack_root and not candidate.startswith(pack_root + os.sep):
        raise ValueError("Content pack path escapes its pack directory")
    return candidate


def discover_content_packs():
    """
    Discover valid content packs under APP_DATA_DIR/content_packs.

    A pack is a directory containing manifest.json. Invalid packs are skipped
    rather than preventing DLMS from starting.
    """
    packs = {}
    os.makedirs(CONTENT_PACK_FOLDER, exist_ok=True)

    try:
        entries = sorted(os.listdir(CONTENT_PACK_FOLDER))
    except OSError as exc:
        print(f"[CONTENT PACKS] Unable to list {CONTENT_PACK_FOLDER}: {exc}")
        return packs

    for entry in entries:
        pack_root = os.path.join(CONTENT_PACK_FOLDER, entry)
        manifest_path = os.path.join(pack_root, "manifest.json")
        if not os.path.isdir(pack_root) or not os.path.isfile(manifest_path):
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f) or {}

            pack_id = str(manifest.get("id") or "").strip().lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", pack_id):
                raise ValueError("manifest id must contain only lowercase letters, numbers, _ or -")

            schema_version = int(manifest.get("schema_version", 0))
            if schema_version != CONTENT_PACK_SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported schema_version {schema_version}; "
                    f"expected {CONTENT_PACK_SCHEMA_VERSION}"
                )

            datasets = manifest.get("datasets") or []
            if not isinstance(datasets, list):
                raise ValueError("datasets must be a list")
            invalid_dataset_entries = [
                item for item in datasets
                if not isinstance(item, dict)
            ]
            if invalid_dataset_entries:
                raise ValueError(
                    "datasets entries must be descriptor objects, not string paths"
                )

            image_datasets = manifest.get("image_datasets") or []
            if not isinstance(image_datasets, list):
                raise ValueError("image_datasets must be a list")
            invalid_image_entries = [
                item for item in image_datasets
                if not isinstance(item, dict)
            ]
            if invalid_image_entries:
                raise ValueError(
                    "image_datasets entries must be descriptor objects, not string paths"
                )

            quiz_datasets = manifest.get("quiz_datasets") or []
            if not isinstance(quiz_datasets, list):
                raise ValueError("quiz_datasets must be a list")
            if any(not isinstance(item, dict) for item in quiz_datasets):
                raise ValueError("quiz_datasets entries must be descriptor objects, not string paths")

            manifest["_root"] = pack_root
            manifest["_manifest_path"] = manifest_path
            packs[pack_id] = manifest

        except Exception as exc:
            print(f"[CONTENT PACKS] Skipping invalid pack {entry!r}: {exc}")

    return packs


def get_content_pack(pack_id):
    return discover_content_packs().get(str(pack_id or "").strip().lower())


def load_content_pack_dataset(pack_id, dataset_id):
    """Load and validate one JSON dataset declared in a pack manifest."""
    pack = get_content_pack(pack_id)
    if not pack:
        raise FileNotFoundError(f"Content pack {pack_id!r} is not installed")

    dataset_id = str(dataset_id or "").strip()
    descriptor = next(
        (item for item in pack.get("datasets", [])
         if str(item.get("id") or "").strip() == dataset_id),
        None
    )
    if not descriptor:
        raise KeyError(f"Dataset {dataset_id!r} is not declared by pack {pack_id!r}")

    rel_path = str(descriptor.get("path") or "").strip()
    if not rel_path:
        raise ValueError("Dataset descriptor is missing path")

    dataset_path = _safe_pack_child(pack["_root"], rel_path)
    if not os.path.isfile(dataset_path):
        raise FileNotFoundError(f"Dataset file not found: {rel_path}")

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}

    if int(data.get("schema_version", 0)) != CONTENT_PACK_SCHEMA_VERSION:
        raise ValueError("Dataset schema version is not supported")

    terms = data.get("terms") or []
    if not isinstance(terms, list):
        raise ValueError("Dataset terms must be a list")

    cleaned = []
    seen = set()
    for item in terms:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        definition = str(item.get("definition") or "").strip()
        if not term or not definition:
            continue
        key = (term.casefold(), definition.casefold())
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({
            "term": term,
            "definition": definition,
            "category": str(item.get("category") or "").strip(),
            "explanation": str(item.get("explanation") or "").strip(),
            "verification": item.get("verification") if isinstance(item.get("verification"), dict) else {},
        })

    data["terms"] = cleaned
    data["_descriptor"] = descriptor
    data["_pack"] = pack
    return data



def load_content_pack_image_dataset(pack_id, dataset_id):
    """Load one image/hotspot dataset declared by an installed content pack."""
    pack = get_content_pack(pack_id)
    if not pack:
        raise FileNotFoundError(f"Content pack {pack_id!r} is not installed")

    dataset_id = str(dataset_id or "").strip()
    descriptor = next(
        (item for item in (pack.get("image_datasets") or [])
         if str(item.get("id") or "").strip() == dataset_id),
        None
    )
    if not descriptor:
        raise KeyError(f"Image dataset {dataset_id!r} is not declared by pack {pack_id!r}")

    rel_path = str(descriptor.get("path") or "").strip()
    if not rel_path:
        raise ValueError("Image dataset descriptor is missing path")

    dataset_path = _safe_pack_child(pack["_root"], rel_path)
    if not os.path.isfile(dataset_path):
        raise FileNotFoundError(f"Image dataset file not found: {rel_path}")

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}

    if int(data.get("schema_version", 0)) != CONTENT_PACK_SCHEMA_VERSION:
        raise ValueError("Image dataset schema version is not supported")

    images = data.get("images") or []
    if not isinstance(images, list) or not images:
        raise ValueError("Image dataset must contain at least one image")

    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Each image record must be an object")
        rel_file = str(image.get("file") or "").strip()
        if not rel_file:
            raise ValueError("Image record is missing file")
        image_path = _safe_pack_child(pack["_root"], rel_file)
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Pack image not found: {rel_file}")
        hotspots = image.get("hotspots") or []
        if not isinstance(hotspots, list) or not hotspots:
            raise ValueError(f"Image {rel_file!r} has no hotspots")

    data["_descriptor"] = descriptor
    data["_pack"] = pack
    return data


def load_content_pack_quiz_dataset(pack_id, dataset_id):
    """Load a generic mixed-question dataset declared by an installed content pack."""
    pack = get_content_pack(pack_id)
    if not pack:
        raise FileNotFoundError(f"Content pack {pack_id!r} is not installed")
    dataset_id = str(dataset_id or "").strip()
    descriptor = next(
        (item for item in (pack.get("quiz_datasets") or [])
         if isinstance(item, dict) and str(item.get("id") or "").strip() == dataset_id),
        None
    )
    if not descriptor:
        raise KeyError(f"Quiz dataset {dataset_id!r} is not declared by pack {pack_id!r}")
    rel_path = str(descriptor.get("path") or "").strip()
    if not rel_path:
        raise ValueError("Quiz dataset descriptor is missing path")
    dataset_path = _safe_pack_child(pack["_root"], rel_path)
    if not os.path.isfile(dataset_path):
        raise FileNotFoundError(f"Quiz dataset file not found: {rel_path}")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
    if int(data.get("schema_version", 0)) != CONTENT_PACK_SCHEMA_VERSION:
        raise ValueError("Quiz dataset schema version is not supported")

    images = data.get("images") or []
    if not isinstance(images, list):
        raise ValueError("Quiz dataset images must be a list")
    image_ids = set()
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Each quiz dataset image must be an object")
        image_id = str(image.get("id") or "").strip()
        rel_file = str(image.get("file") or "").strip()
        if not image_id or not rel_file:
            raise ValueError("Each quiz dataset image requires id and file")
        if image_id in image_ids:
            raise ValueError(f"Duplicate image id: {image_id}")
        image_ids.add(image_id)
        if not os.path.isfile(_safe_pack_child(pack["_root"], rel_file)):
            raise FileNotFoundError(f"Pack image not found: {rel_file}")
        if not isinstance(image.get("hotspots") or [], list):
            raise ValueError("Image hotspots must be a list")

    questions = data.get("questions") or []
    if not isinstance(questions, list) or not questions:
        raise ValueError("Quiz dataset must contain at least one question")
    allowed = {"choice", "matching", "hotspot"}
    cleaned = []
    for raw in questions:
        if not isinstance(raw, dict):
            continue
        qtype = str(raw.get("type") or "choice").strip().lower()
        question = str(raw.get("question") or "").strip()
        if qtype not in allowed or not question:
            continue
        image_id = str(raw.get("image_id") or "").strip()
        if image_id and image_id not in image_ids:
            raise ValueError(f"Question references unknown image id: {image_id}")
        item = dict(raw)
        item["type"] = qtype
        item["question"] = question
        cleaned.append(item)
    if not cleaned:
        raise ValueError("Quiz dataset has no usable questions")
    data["questions"] = cleaned
    data["_descriptor"] = descriptor
    data["_pack"] = pack
    data["_dataset_path"] = dataset_path
    return data


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
            "explanation": raw.get("explanation") or "", **media
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
            runtime = {**common, "type": "hotspot", "target": hotspot.get("shape") or {}, "target_label": label, "verification": hotspot.get("verification") or {}}
            db = {
                "type": "choice", "question": (raw.get("question") or "") + " [Image hotspot]",
                "choices": [{"label": "A", "text": label, "is_correct": True}],
                "explanation": raw.get("explanation") or "", "source": db_source, "media": media,
            }
        else:
            choices, correct = [], []
            for choice in raw.get("choices") or []:
                if not isinstance(choice, dict): continue
                text = str(choice.get("text") or "").strip()
                if not text: continue
                label = chr(65 + len(choices))
                is_correct = bool(choice.get("is_correct"))
                choices.append({"label": label, "text": text, "is_correct": is_correct})
                if is_correct: correct.append(label)
            if len(choices) < 2 or not correct: continue
            runtime = {**common, "type": "choice", "choices": choices, "correct": correct}
            db = {**runtime, "source": db_source, "media": media}

        runtime_questions.append(runtime)
        db_questions.append(db)

    for n, q in enumerate(runtime_questions, 1): q["number"] = n
    for n, q in enumerate(db_questions, 1): q["number"] = n
    return runtime_questions, db_questions


def _create_quiz_from_runtime(quiz_title, runtime_questions, db_questions, filename_prefix="study_image", exam_minutes=90, source_pack_id=None, source_dataset_id=None):
    if not runtime_questions:
        raise ValueError("No usable questions were produced")
    ts = int(time.time() * 1000)
    safe_prefix = re.sub(r"[^a-z0-9_]+", "_", str(filename_prefix).lower()).strip("_") or "study"
    html_name = f"{safe_prefix}_{ts}.html"
    json_name = f"{safe_prefix}_{ts}.json"

    if source_pack_id:
        bucket = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(html_name)[0])[:120]
        runtime_questions, db_questions, _ = _snapshot_runtime_questions(
            str(source_pack_id).strip().lower(), runtime_questions, db_questions, bucket
        )

    with open(os.path.join(DATA_FOLDER, json_name), "w", encoding="utf-8") as f:
        json.dump(runtime_questions, f, indent=4, ensure_ascii=False)
    quiz_id = save_quiz_to_db(quiz_title, html_name, db_questions)
    add_quiz_to_registry(
        quiz_id=quiz_id, html=html_name, title=quiz_title, logo=None,
        exam_minutes=normalize_exam_minutes(exam_minutes),
        source_pack_id=source_pack_id, source_dataset_id=source_dataset_id
    )
    build_quiz_html(html_name, json_name, os.path.join(QUIZ_FOLDER, html_name), get_portal_title(), quiz_title, None, quiz_id, normalize_exam_minutes(exam_minutes))
    return quiz_id, html_name


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

    allowed = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in allowed:
        return "Unsupported content-pack asset type", 415

    return send_from_directory(
        os.path.dirname(file_path),
        os.path.basename(file_path),
        conditional=True
    )



def _quiz_asset_url(bucket, relative_path):
    rel = str(relative_path or "").replace("\\", "/").lstrip("/")
    return f"/quiz-assets/{bucket}/{rel}"


def _snapshot_one_pack_asset(pack_id, asset_url, bucket):
    """Copy one content-pack asset into quiz-owned storage and return its stable runtime URL."""
    asset_url = str(asset_url or "")
    prefix = f"/content-packs/{pack_id}/assets/"
    if not asset_url.startswith(prefix):
        return asset_url, False

    pack = get_content_pack(pack_id)
    if not pack:
        raise FileNotFoundError(f"Content pack {pack_id!r} is not installed")

    rel = asset_url[len(prefix):].lstrip("/")
    src = _safe_pack_child(pack["_root"], rel)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"Content-pack asset not found: {rel}")

    ext = os.path.splitext(src)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise ValueError(f"Unsupported quiz asset type: {ext}")

    dest_root = os.path.join(QUIZ_ASSET_FOLDER, bucket)
    dest = _safe_pack_child(dest_root, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.isfile(dest):
        shutil.copy2(src, dest)
    return _quiz_asset_url(bucket, rel), True


def _snapshot_pack_refs_recursive(pack_id, value, bucket):
    """Recursively rewrite any runtime content-pack asset URLs to quiz-owned copies."""
    changed = 0
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            new_item, n = _snapshot_pack_refs_recursive(pack_id, item, bucket)
            out[key] = new_item
            changed += n
        return out, changed
    if isinstance(value, list):
        out = []
        for item in value:
            new_item, n = _snapshot_pack_refs_recursive(pack_id, item, bucket)
            out.append(new_item)
            changed += n
        return out, changed
    if isinstance(value, str):
        new_value, did_change = _snapshot_one_pack_asset(pack_id, value, bucket)
        return new_value, int(did_change)
    return value, 0


def _snapshot_runtime_questions(pack_id, runtime_questions, db_questions, bucket):
    """Make generated image quizzes independent of the source content pack."""
    runtime_copy, runtime_count = _snapshot_pack_refs_recursive(pack_id, runtime_questions, bucket)
    db_copy, db_count = _snapshot_pack_refs_recursive(pack_id, db_questions, bucket)
    return runtime_copy, db_copy, runtime_count + db_count


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
    if os.path.splitext(file_path)[1].lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return "Unsupported quiz asset", 415
    return send_from_directory(root, os.path.relpath(file_path, root))


def _snapshot_existing_pack_dependencies(pack_id):
    """
    Before deleting a pack, migrate legacy runtime/DB/history JSON references
    from /content-packs/<id>/assets/... to quiz-owned snapshots.
    """
    migrated_files = 0
    migrated_refs = 0

    # Runtime quiz JSON files.
    if os.path.isdir(DATA_FOLDER):
        for name in os.listdir(DATA_FOLDER):
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(DATA_FOLDER, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            bucket = "legacy_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(name)[0])[:110]
            new_payload, count = _snapshot_pack_refs_recursive(pack_id, payload, bucket)
            if count:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(new_payload, f, indent=4, ensure_ascii=False)
                migrated_files += 1
                migrated_refs += count

    # DB question media, so later quiz rebuilds stay independent.
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    columns = {r["name"] for r in cur.execute("PRAGMA table_info(questions)").fetchall()}
    if "media_json" in columns:
        rows = cur.execute("""
            SELECT q.id AS question_id, q.quiz_id, q.media_json
            FROM questions q
            WHERE q.media_json IS NOT NULL AND q.media_json != ''
        """).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["media_json"])
            except Exception:
                continue
            bucket = f"legacy_quiz_{row['quiz_id']}"
            new_payload, count = _snapshot_pack_refs_recursive(pack_id, payload, bucket)
            if count:
                cur.execute("UPDATE questions SET media_json = ? WHERE id = ?",
                            (json.dumps(new_payload, ensure_ascii=False), row["question_id"]))
                migrated_refs += count

    # Saved hotspot-attempt response JSON, if this schema version has it.
    answer_columns = {r["name"] for r in cur.execute("PRAGMA table_info(attempt_answers)").fetchall()}
    if "response_json" in answer_columns:
        rows = cur.execute("""
            SELECT id, attempt_id, response_json
            FROM attempt_answers
            WHERE response_json IS NOT NULL AND response_json != ''
        """).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["response_json"])
            except Exception:
                continue
            bucket = "legacy_attempt_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", str(row["attempt_id"]))[:100]
            new_payload, count = _snapshot_pack_refs_recursive(pack_id, payload, bucket)
            if count:
                cur.execute("UPDATE attempt_answers SET response_json = ? WHERE id = ?",
                            (json.dumps(new_payload, ensure_ascii=False), row["id"]))
                migrated_refs += count

    conn.commit()
    conn.close()
    return {"files": migrated_files, "references": migrated_refs}


def _content_pack_tracked_quiz_count(pack_id):
    return sum(
        1 for item in load_registry()
        if str(item.get("source_pack_id") or "").strip().lower() == str(pack_id or "").strip().lower()
    )


def _folder_size_bytes(path):
    total = 0
    for root_dir, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root_dir, name))
            except OSError:
                pass
    return total


def _format_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024



CONTENT_PACK_IMPORT_MAX_FILES = 1000
CONTENT_PACK_IMPORT_MAX_UNCOMPRESSED = 512 * 1024 * 1024
CONTENT_PACK_IMPORT_MAX_SINGLE_FILE = 128 * 1024 * 1024
CONTENT_PACK_IMPORT_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")


def _content_pack_validation_record(name, status, detail):
    return {"name": str(name), "status": str(status), "detail": str(detail)}


def _safe_zip_member_name(name):
    """Return a normalized safe archive member path or raise ValueError."""
    raw = str(name or "").replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ValueError("archive contains an absolute path")
    parts = [p for p in raw.split("/") if p not in {"", "."}]
    if not parts or any(p == ".." for p in parts):
        raise ValueError("archive contains an unsafe relative path")
    return "/".join(parts)


def _inspect_content_pack_zip(zip_path):
    """Security-check a pack ZIP and return its single top-level folder name."""
    total_size = 0
    file_count = 0
    top_levels = set()
    seen_names = set()

    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        if not infos:
            raise ValueError("ZIP is empty")

        for info in infos:
            normalized = _safe_zip_member_name(info.filename)
            top_levels.add(normalized.split("/", 1)[0])

            # Reject duplicate normalized paths and Unix symlinks.
            key = normalized.casefold()
            if key in seen_names:
                raise ValueError(f"ZIP contains duplicate path: {normalized}")
            seen_names.add(key)
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if (unix_mode & 0o170000) == 0o120000:
                raise ValueError(f"ZIP contains a symbolic link: {normalized}")

            if info.is_dir():
                continue
            file_count += 1
            total_size += int(info.file_size or 0)
            if file_count > CONTENT_PACK_IMPORT_MAX_FILES:
                raise ValueError(f"ZIP contains more than {CONTENT_PACK_IMPORT_MAX_FILES} files")
            if int(info.file_size or 0) > CONTENT_PACK_IMPORT_MAX_SINGLE_FILE:
                raise ValueError(f"ZIP member is too large: {normalized}")
            if total_size > CONTENT_PACK_IMPORT_MAX_UNCOMPRESSED:
                raise ValueError("ZIP expands beyond the permitted size limit")

    if len(top_levels) != 1:
        raise ValueError("ZIP must contain exactly one top-level Study Pack folder")
    root_name = next(iter(top_levels))
    if root_name in {".", ".."} or not root_name.strip():
        raise ValueError("ZIP top-level folder name is invalid")
    return {"root_name": root_name, "file_count": file_count, "uncompressed_bytes": total_size}


def _extract_content_pack_zip(zip_path, stage_root):
    """Safely extract a previously inspected Study Pack ZIP."""
    os.makedirs(stage_root, exist_ok=False)
    real_stage = os.path.realpath(stage_root)
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            normalized = _safe_zip_member_name(info.filename)
            target = os.path.realpath(os.path.join(stage_root, normalized))
            if target != real_stage and not target.startswith(real_stage + os.sep):
                raise ValueError("ZIP path escapes staging directory")
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _read_json_file(path, label, errors):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return None


def _validate_staged_content_pack(pack_root):
    """Independently validate a staged pack before installation."""
    errors, warnings, checks = [], [], []
    pack_root = os.path.realpath(pack_root)
    manifest_path = os.path.join(pack_root, "manifest.json")

    if not os.path.isfile(manifest_path):
        errors.append("Top-level Study Pack folder is missing manifest.json")
        return {"valid": False, "errors": errors, "warnings": warnings, "checks": checks, "manifest": {}}

    manifest = _read_json_file(manifest_path, "manifest.json", errors)
    if not isinstance(manifest, dict):
        if manifest is not None:
            errors.append("manifest.json must contain a JSON object")
        return {"valid": False, "errors": errors, "warnings": warnings, "checks": checks, "manifest": {}}

    schema = manifest.get("schema_version")
    if schema == CONTENT_PACK_SCHEMA_VERSION:
        checks.append(_content_pack_validation_record("Manifest schema", "PASS", f"schema_version {schema}"))
    else:
        errors.append(f"manifest schema_version must be {CONTENT_PACK_SCHEMA_VERSION}")
        checks.append(_content_pack_validation_record("Manifest schema", "FAIL", f"found {schema!r}"))

    pack_id = str(manifest.get("id") or "").strip().lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", pack_id):
        checks.append(_content_pack_validation_record("Pack ID", "PASS", pack_id))
    else:
        errors.append("manifest id must use lowercase letters, numbers, _ or -")
        checks.append(_content_pack_validation_record("Pack ID", "FAIL", pack_id or "missing"))

    descriptor_groups = [
        ("datasets", "matching"),
        ("image_datasets", "hotspot"),
        ("quiz_datasets", "mixed"),
    ]
    descriptor_ids = set()
    declared_paths = []
    all_descriptors_valid = True
    parsed_dataset_files = []

    for key, kind in descriptor_groups:
        entries = manifest.get(key) or []
        if not isinstance(entries, list):
            errors.append(f"{key} must be a list")
            all_descriptors_valid = False
            continue
        for index, descriptor in enumerate(entries, 1):
            if not isinstance(descriptor, dict):
                errors.append(f"{key}[{index}] must be a descriptor object, not a path string")
                all_descriptors_valid = False
                continue
            did = str(descriptor.get("id") or "").strip()
            title = str(descriptor.get("title") or "").strip()
            dtype = str(descriptor.get("type") or "").strip()
            rel_path = str(descriptor.get("path") or "").strip()
            if not did or not title or not dtype or not rel_path:
                errors.append(f"{key}[{index}] requires id, title, type, and path")
                all_descriptors_valid = False
                continue
            if did in descriptor_ids:
                errors.append(f"duplicate dataset id: {did}")
                all_descriptors_valid = False
            descriptor_ids.add(did)
            try:
                dataset_path = _safe_pack_child(pack_root, rel_path)
            except Exception:
                errors.append(f"{key}[{index}] path escapes the pack: {rel_path}")
                all_descriptors_valid = False
                continue
            declared_paths.append(rel_path)
            if not os.path.isfile(dataset_path):
                errors.append(f"declared dataset file is missing: {rel_path}")
                all_descriptors_valid = False
                continue
            data = _read_json_file(dataset_path, rel_path, errors)
            if isinstance(data, dict):
                parsed_dataset_files.append((key, did, rel_path, data))

    checks.append(_content_pack_validation_record(
        "Dataset descriptors",
        "PASS" if all_descriptors_valid else "FAIL",
        f"{len(descriptor_ids)} descriptor(s) checked"
    ))

    # Validate dataset internals and all referenced image files.
    referenced_files_ok = True
    duplicates_ok = True
    image_license_missing = 0
    dataset_source_missing = 0

    for group, did, rel_path, data in parsed_dataset_files:
        if data.get("schema_version") != CONTENT_PACK_SCHEMA_VERSION:
            errors.append(f"{rel_path}: schema_version must be {CONTENT_PACK_SCHEMA_VERSION}")

        data_id = str(data.get("id") or "").strip()
        if data_id and data_id != did:
            errors.append(f"{rel_path}: dataset id {data_id!r} does not match manifest descriptor id {did!r}")

        if not isinstance(data.get("source"), dict) or not data.get("source"):
            dataset_source_missing += 1

        if group == "datasets":
            terms = data.get("terms") or []
            if not isinstance(terms, list) or not terms:
                errors.append(f"{rel_path}: matching dataset must contain terms")
                continue
            seen_terms, seen_definitions = set(), set()
            for n, term in enumerate(terms, 1):
                if not isinstance(term, dict):
                    errors.append(f"{rel_path}: term {n} must be an object")
                    continue
                t = str(term.get("term") or "").strip()
                d = str(term.get("definition") or "").strip()
                if not t or not d:
                    errors.append(f"{rel_path}: term {n} has an empty term or definition")
                tk, dk = t.casefold(), d.casefold()
                if tk in seen_terms or dk in seen_definitions:
                    duplicates_ok = False
                    errors.append(f"{rel_path}: duplicate term or definition detected near item {n}")
                seen_terms.add(tk)
                seen_definitions.add(dk)

        elif group in {"image_datasets", "quiz_datasets"}:
            images = data.get("images") or []
            if group == "image_datasets" and (not isinstance(images, list) or not images):
                errors.append(f"{rel_path}: image dataset must contain at least one image")
                continue
            if not isinstance(images, list):
                errors.append(f"{rel_path}: images must be a list")
                continue

            image_ids = set()
            for n, image in enumerate(images, 1):
                if not isinstance(image, dict):
                    errors.append(f"{rel_path}: image {n} must be an object")
                    continue
                image_id = str(image.get("id") or f"image_{n}").strip()
                if image_id in image_ids:
                    duplicates_ok = False
                    errors.append(f"{rel_path}: duplicate image id {image_id}")
                image_ids.add(image_id)
                rel_image = str(image.get("file") or "").strip()
                if not rel_image:
                    errors.append(f"{rel_path}: image {n} is missing file")
                    referenced_files_ok = False
                    continue
                try:
                    image_path = _safe_pack_child(pack_root, rel_image)
                except Exception:
                    errors.append(f"{rel_path}: image path escapes pack: {rel_image}")
                    referenced_files_ok = False
                    continue
                if not os.path.isfile(image_path):
                    errors.append(f"{rel_path}: referenced image is missing: {rel_image}")
                    referenced_files_ok = False

                source = image.get("source") if isinstance(image.get("source"), dict) else {}
                license_text = str(image.get("license") or source.get("license") or "").strip()
                if not license_text:
                    image_license_missing += 1

                hotspots = image.get("hotspots") or []
                if not isinstance(hotspots, list):
                    errors.append(f"{rel_path}: hotspots for {rel_image} must be a list")
                    continue
                for h, hotspot in enumerate(hotspots, 1):
                    if not isinstance(hotspot, dict):
                        errors.append(f"{rel_path}: hotspot {h} for {rel_image} must be an object")
                        continue
                    shape = hotspot.get("shape")
                    try:
                        _validate_hotspot_shape(shape)
                    except Exception as exc:
                        errors.append(f"{rel_path}: invalid hotspot geometry for {rel_image}: {exc}")

            if group == "quiz_datasets":
                questions = data.get("questions") or []
                if not isinstance(questions, list) or not questions:
                    errors.append(f"{rel_path}: mixed question dataset must contain questions")

    checks.append(_content_pack_validation_record(
        "Referenced files", "PASS" if referenced_files_ok else "FAIL",
        "all declared dataset/image paths resolved" if referenced_files_ok else "one or more files are missing or unsafe"
    ))
    checks.append(_content_pack_validation_record(
        "Duplicate IDs / terms", "PASS" if duplicates_ok else "FAIL",
        "no duplicate dataset/image IDs or matching terms/definitions found" if duplicates_ok else "duplicates were detected"
    ))

    if image_license_missing:
        warnings.append(f"{image_license_missing} image record(s) do not contain explicit license metadata")
        checks.append(_content_pack_validation_record("Image licenses", "WARN", f"{image_license_missing} image record(s) need review"))
    else:
        checks.append(_content_pack_validation_record("Image licenses", "PASS", "all image records include license metadata or no images are present"))

    if dataset_source_missing:
        warnings.append(f"{dataset_source_missing} dataset file(s) do not contain top-level source metadata")
        checks.append(_content_pack_validation_record("Dataset sources", "WARN", f"{dataset_source_missing} dataset(s) need source review"))
    else:
        checks.append(_content_pack_validation_record("Dataset sources", "PASS", "top-level source metadata present"))

    # AI self-validation is informative only; DLMS never trusts it in place of its own validation.
    ai_validation_path = os.path.join(pack_root, "PACK_VALIDATION.json")
    if os.path.isfile(ai_validation_path):
        ai_validation = _read_json_file(ai_validation_path, "PACK_VALIDATION.json", warnings)
        ai_status = "PASS"
        ai_detail = "present; independently revalidated by DLMS"
        if not isinstance(ai_validation, dict):
            ai_status = "WARN"
            ai_detail = "present but not a usable JSON object"
        else:
            declared_pack_id = str(ai_validation.get("pack_id") or "").strip().lower()
            overall_status = str(ai_validation.get("overall_status") or "").strip().upper()
            ai_checks = ai_validation.get("checks")
            ai_issues = []
            if declared_pack_id and declared_pack_id != pack_id:
                ai_issues.append(f"declares pack_id {declared_pack_id!r}, expected {pack_id!r}")
            if overall_status and overall_status != "PASS":
                ai_issues.append(f"overall_status is {overall_status}")
            if ai_checks is not None and not isinstance(ai_checks, list):
                ai_issues.append("checks is not a list")
            if ai_issues:
                ai_status = "WARN"
                ai_detail = "; ".join(ai_issues)
                warnings.append("PACK_VALIDATION.json self-check needs review: " + ai_detail)
        checks.append(_content_pack_validation_record("AI self-validation", ai_status, ai_detail))
    else:
        checks.append(_content_pack_validation_record(
            "Validation metadata",
            "INFO",
            "PACK_VALIDATION.json not present; optional for legacy/hand-built packs. Current AI Builder outputs include it."
        ))

    checks.append(_content_pack_validation_record(
        "JSON parse check", "PASS" if not any("valid JSON" in e for e in errors) else "FAIL",
        f"{1 + len(parsed_dataset_files)} JSON file(s) inspected"
    ))
    checks.append(_content_pack_validation_record("Top-level folder", "PASS", os.path.basename(pack_root)))

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "manifest": manifest,
        "pack_id": pack_id,
        "pack_name": str(manifest.get("name") or pack_id or os.path.basename(pack_root)),
        "dataset_count": len(descriptor_ids),
    }


def _content_pack_stage_path(token):
    if not CONTENT_PACK_IMPORT_TOKEN_RE.fullmatch(str(token or "")):
        raise ValueError("Invalid import token")
    return os.path.join(CONTENT_PACK_STAGING_FOLDER, token)


def _load_staged_content_pack(token):
    stage_dir = _content_pack_stage_path(token)
    metadata_path = os.path.join(stage_dir, "stage.json")
    if not os.path.isfile(metadata_path):
        raise FileNotFoundError("Staged Content Pack was not found or has expired")
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    pack_root = _safe_pack_child(stage_dir, metadata["root_name"])
    if not os.path.isdir(pack_root):
        raise FileNotFoundError("Staged Content Pack root folder is missing")
    return stage_dir, pack_root, metadata


def _remove_content_pack_stage(token):
    try:
        stage_dir = _content_pack_stage_path(token)
    except Exception:
        return
    shutil.rmtree(stage_dir, ignore_errors=True)


def content_pack_management_summary():
    """Return every installed pack folder, including invalid packs, with independent validation state."""
    discovered = discover_content_packs()
    by_root = {os.path.realpath(p.get("_root")): (pid, p) for pid, p in discovered.items()}
    rows = []
    try:
        entries = sorted(os.listdir(CONTENT_PACK_FOLDER), key=str.casefold)
    except OSError:
        entries = []

    for folder in entries:
        root = os.path.join(CONTENT_PACK_FOLDER, folder)
        if not os.path.isdir(root):
            continue

        report = _validate_staged_content_pack(root)
        manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
        resolved = by_root.get(os.path.realpath(root))
        pack_id = str(report.get("pack_id") or manifest.get("id") or "").strip().lower()
        runtime_pack = resolved[1] if resolved else {}
        matching = len(manifest.get("datasets") or []) if isinstance(manifest.get("datasets") or [], list) else 0
        image = len(manifest.get("image_datasets") or []) if isinstance(manifest.get("image_datasets") or [], list) else 0
        mixed = len(manifest.get("quiz_datasets") or []) if isinstance(manifest.get("quiz_datasets") or [], list) else 0
        protected = bool(manifest.get("protected"))
        generated = _content_pack_tracked_quiz_count(pack_id) if pack_id and resolved else 0
        if report.get("valid") and pack_id and not resolved:
            report["valid"] = False
            report.setdefault("errors", []).append("Pack is structurally valid but is not discoverable at runtime, usually because another installed folder uses the same pack id.")
            report.setdefault("checks", []).append(_content_pack_validation_record("Runtime discovery", "FAIL", "pack id conflict or runtime discovery failure"))
        warning_count = len(report.get("warnings") or [])
        error_count = len(report.get("errors") or [])
        if report.get("valid") and warning_count:
            status = "Valid with warnings"
            status_detail = f"DLMS validation passed with {warning_count} warning(s)."
        elif report.get("valid"):
            status = "Valid"
            status_detail = "DLMS independent validation passed without warnings."
        else:
            status = "Invalid"
            first_error = (report.get("errors") or ["Pack failed independent validation."])[0]
            status_detail = first_error

        try:
            installed_at = datetime.fromtimestamp(os.path.getmtime(root)).strftime("%b %d, %Y %I:%M %p")
        except OSError:
            installed_at = "Unavailable"

        rows.append({
            "folder": folder,
            "id": pack_id,
            "name": manifest.get("name") or runtime_pack.get("name") or folder,
            "version": manifest.get("version") or runtime_pack.get("version") or "",
            "description": manifest.get("description") or runtime_pack.get("description") or "",
            "domain": manifest.get("content_domain") or manifest.get("extends") or "General",
            "matching_count": matching,
            "image_count": image,
            "mixed_count": mixed,
            "dataset_count": matching + image + mixed,
            "file_count": sum(len(files) for _, _, files in os.walk(root)),
            "size": _format_bytes(_folder_size_bytes(root)),
            "status": status,
            "status_detail": status_detail,
            "protected": protected,
            "generated_quizzes": generated,
            "warning_count": warning_count,
            "error_count": error_count,
            "validation_report": report,
            "installed_at": installed_at,
            "exportable": bool(report.get("valid")),
        })
    return rows


def _content_pack_folder_report(folder):
    """Safely load one installed pack folder and return its independent validation report."""
    folder = str(folder or "").strip()
    if not folder or folder in {".", ".."} or os.path.basename(folder) != folder:
        raise ValueError("Invalid Content Pack folder")
    root = os.path.realpath(os.path.join(CONTENT_PACK_FOLDER, folder))
    content_root = os.path.realpath(CONTENT_PACK_FOLDER)
    if os.path.dirname(root) != content_root or not os.path.isdir(root):
        raise FileNotFoundError("Content Pack folder was not found")
    report = _validate_staged_content_pack(root)
    pack_id = str(report.get("pack_id") or "").strip().lower()
    discovered = get_content_pack(pack_id) if pack_id else None
    if report.get("valid") and pack_id and (not discovered or os.path.realpath(discovered.get("_root") or "") != root):
        report["valid"] = False
        report.setdefault("errors", []).append("Pack is structurally valid but is not discoverable at runtime, usually because another installed folder uses the same pack id.")
        report.setdefault("checks", []).append(_content_pack_validation_record("Runtime discovery", "FAIL", "pack id conflict or runtime discovery failure"))
    report["folder"] = folder
    report["root"] = root
    report["file_count"] = sum(len(files) for _, _, files in os.walk(root))
    report["size"] = _format_bytes(_folder_size_bytes(root))
    report["generated_quizzes"] = _content_pack_tracked_quiz_count(pack_id) if pack_id and discovered else 0
    try:
        report["installed_at"] = datetime.fromtimestamp(os.path.getmtime(root)).strftime("%b %d, %Y %I:%M %p")
    except OSError:
        report["installed_at"] = "Unavailable"
    return report


def _is_medical_pack_manifest(pack_id, pack):
    """Return True when an installed pack declares itself as medical content."""
    if not isinstance(pack, dict):
        return False
    return (
        str(pack.get("content_domain") or "").strip().lower() == "medical"
        or str(pack.get("extends") or "").strip().lower() == "medical"
        # Backward compatibility for the original Medical Study Pack manifest.
        or str(pack_id or "").strip().lower() == "medical"
    )


def _medical_content_available(packs=None):
    """Return whether Medical Study currently has installed Medical-domain content."""
    packs = packs if isinstance(packs, dict) else discover_content_packs()
    return any(_is_medical_pack_manifest(pack_id, pack) for pack_id, pack in packs.items())


def _normalized_content_domain(value):
    """Normalize a human-readable content domain into a stable comparison key."""
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _is_it_pack_manifest(pack_id, pack):
    """Return True for Study Packs intended for IT / Cybersecurity study."""
    if not isinstance(pack, dict):
        return False
    domain = _normalized_content_domain(pack.get("content_domain") or pack.get("extends"))
    return domain in {"it", "it_cybersecurity", "cybersecurity", "information_technology"}


def _it_content_available(packs=None):
    packs = packs if isinstance(packs, dict) else discover_content_packs()
    return any(_is_it_pack_manifest(pack_id, pack) for pack_id, pack in packs.items())


def content_pack_summary():
    packs = discover_content_packs()
    summary = []
    for pack_id, pack in packs.items():
        dataset_count = (
            len(pack.get("datasets") or [])
            + len(pack.get("image_datasets") or [])
            + len(pack.get("quiz_datasets") or [])
        )
        summary.append({
            "id": pack_id,
            "name": pack.get("name") or pack_id,
            "version": pack.get("version") or "",
            "description": pack.get("description") or "",
            "modules": pack.get("modules") or [],
            "dataset_count": dataset_count,
        })
    return summary


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
QUIZ_REGISTRY = os.path.join(CONFIG_FOLDER, "quizzes.json")
DB_PATH = os.path.join(APP_DATA_DIR, "results.db")




REQUIRED_TABLES = {
    "quizzes",
    "questions",
    "choices",
    "attempts",
    "attempt_answers",
    "missed_questions",
    "schema_meta",
}




def ensure_db_initialized():
    """
    Ensure the SQLite database exists and has all required tables.
    Runs exactly once at import time.
    """
    dprint(f"[DB] ensure_db_initialized using DB_PATH = {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Fetch all existing table names
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
    """)
    existing_tables = {row[0] for row in cur.fetchall()}

    # Determine which required tables are missing
    missing_tables = REQUIRED_TABLES - existing_tables

    if missing_tables:
        dprint(f"[DB] Missing tables detected: {missing_tables}")

        init_sql_path = resource_path("init.sql")
        dprint(f"[DB] init.sql path = {init_sql_path}")

        with open(init_sql_path, "r", encoding="utf-8") as f:
            sql = f.read()

        conn.executescript(sql)
        conn.commit()

        print("[DB] Database schema initialized / updated")

    conn.close()


# ✅ INITIALIZE DATABASE ONCE, AT IMPORT TIME
ensure_db_initialized()

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
        logo_filename = f"logo_{ts}{ext}"
        dst = os.path.join(LOGO_FOLDER, logo_filename)

        os.rename(src, dst)
        assert os.path.exists(dst), f"Logo finalize invariant violated: {dst}"

        print(f"[LOGO] Finalized logo → {dst}")
        return logo_filename

    # =========================
    # Case 2: Direct upload
    # =========================
    if logo_file and logo_file.filename:
        ext = os.path.splitext(logo_file.filename)[1].lower()
        if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            logo_filename = f"logo_{ts}{ext}"
            dst = os.path.join(LOGO_FOLDER, logo_filename)

            logo_file.save(dst)
            assert os.path.exists(dst), f"Logo upload invariant violated: {dst}"

            print(f"[LOGO] Uploaded logo → {dst}")
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
    if ext not in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        return None

    os.makedirs(LOGO_TEMP_FOLDER, exist_ok=True)

    name = f"temp_{int(time.time())}{ext}"
    dst = os.path.join(LOGO_TEMP_FOLDER, name)

    logo_file.save(dst)
    assert os.path.exists(dst), f"Preview logo invariant violated: {dst}"

    print(f"[LOGO PREVIEW] Saved temp logo → {dst}")
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

@app.route("/regex-help")
@app.route("/regex-help/")
def regex_help():
    return send_from_directory(app.static_folder, "regex-help.html")


@app.route("/user-static/<path:filename>")
def user_static(filename):
    return send_from_directory(
        os.path.join(APP_DATA_DIR, "static"),
        filename
    )

@app.route("/admin/maintenance")
def admin_maintenance():
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Admin Maintenance - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>

<body>
<div class="container">

    <h1 class="hero-title">🛠 Admin Maintenance</h1>

    <div class="card">

        <h2>Quiz Maintenance</h2>

        <p style="opacity:.8;">
            Rebuild all existing quiz pages using the current DLMS application template.
            This is useful after upgrading DLMS so older quizzes receive new interface features.
        </p>

        <p style="opacity:.7; font-size:13px;">
            Quiz questions, answers, IDs, registry entries, and attempt history are not changed.
        </p>

        <button id="rebuildAllBtn">
            🔄 Rebuild All Quiz Pages
        </button>

        <p id="rebuildStatus" style="margin-top:10px;"></p>

        <hr style="margin:24px 0; opacity:.35">
        <h2>Image Study Editor</h2>
        <p style="opacity:.8;">Prepare images for study, hide or add simple text overlays, draw precise circle or polygon hit regions, test them, and save the study metadata directly into an installed content pack.</p>
        <button onclick="location.href='/admin/image-editor'">◎ Open Image Study Editor</button>

        <br><br>

        <button onclick="location.href='/'">
            ⬅ Back To Dashboard
        </button>

    </div>
</div>

<script>
const rebuildBtn = document.getElementById("rebuildAllBtn");
const rebuildStatus = document.getElementById("rebuildStatus");

rebuildBtn.addEventListener("click", async () => {
    const ok = confirm(
        "Rebuild all quiz pages using the current DLMS template?\\n\\n" +
        "Quiz questions, answers, IDs, and history will not be changed."
    );

    if (!ok) return;

    rebuildBtn.disabled = true;
    rebuildStatus.textContent = "Rebuilding quiz pages...";

    try {
        const response = await fetch("/admin/rebuild_all_quiz_html");

        if (!response.ok) {
            throw new Error("Rebuild request failed");
        }

        const data = await response.json();

        rebuildStatus.textContent =
            `Complete: ${data.rebuilt} rebuilt, ${data.failed.length} failed.`;

    } catch (err) {
        console.error(err);
        rebuildStatus.textContent = "Rebuild failed. Check the server log.";
    } finally {
        rebuildBtn.disabled = false;
    }
});
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>
""")




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
            load_error = str(exc)
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
        return jsonify({"error":str(exc)}),400


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
            json.dump(data,f,indent=2,ensure_ascii=False); f.write("\\n")
        os.replace(tmp_path,dataset_path)
        return jsonify({"ok":True,"edits":cleaned,"backup_created":backup_created})
    except Exception as exc:
        return jsonify({"error":str(exc)}),400


HOTSPOT_EDITOR_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Image Study Editor - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home hotspot-editor-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar">
<div class="dashboard-brand"><div class="dashboard-brand-mark">◎</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div>
<nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>{% if medical_pack_installed %}<a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>{% endif %}</nav>
<div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item active" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a></nav><div class="dashboard-sidebar-version">Image Study Editor</div></aside>
<main class="dashboard-main hotspot-editor-main"><header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="build-eyebrow">MAINTENANCE · IMAGE STUDY</div><h1>Image Study Editor</h1><p>Prepare study images without altering the original file: mask unwanted text, add simple labels, and calibrate clickable regions for image-based quizzes.</p></div></header>
<section class="dashboard-panel hotspot-editor-picker"><form method="GET" action="/admin/image-editor"><label><span>Installed image dataset</span><select id="datasetKey">{% for item in catalog %}<option value="{{ item.pack_id }}::{{ item.dataset_kind }}::{{ item.dataset_id }}" {% if item.pack_id == selected_pack and item.dataset_id == selected_dataset and item.dataset_kind == selected_kind %}selected{% endif %}>{{ item.pack_name }} — {{ item.title }}{% if item.dataset_kind == 'quiz' %} · Question Set{% endif %}</option>{% endfor %}</select></label><input type="hidden" name="pack" id="packField" value="{{ selected_pack }}"><input type="hidden" name="kind" id="kindField" value="{{ selected_kind }}"><input type="hidden" name="dataset" id="datasetField" value="{{ selected_dataset }}"><button type="submit">Load Dataset</button></form>{% if load_error %}<div class="flash error">{{ load_error }}</div>{% endif %}{% if not catalog %}<p>No installed content pack currently declares an image dataset.</p>{% endif %}</section>
{% if editor_data %}<section class="dashboard-panel hotspot-editor-workspace">
<div class="image-editor-mode-tabs"><button type="button" id="hotspotModeBtn" class="active">Clickable Regions</button><button type="button" id="prepModeBtn">Image Prep</button></div>
<div class="hotspot-editor-toolbar"><label><span>Image</span><select id="imageSelect"></select></label><label class="hotspot-only"><span>Target / Structure</span><select id="hotspotSelect"></select></label><label class="hotspot-only"><span>Shape</span><select id="shapeMode"><option value="polygon">Polygon</option><option value="circle">Circle</option></select></label><label class="hotspot-only" id="radiusControl"><span>Circle radius <strong id="radiusValue">0.050</strong></span><input id="circleRadius" type="range" min="0.01" max="0.30" step="0.005" value="0.05"></label></div>
<div id="hotspotPanel"><div class="hotspot-editor-actions"><button type="button" id="loadExistingBtn">Load Existing</button><button type="button" id="undoBtn">Undo Point</button><button type="button" id="clearBtn">Clear Shape</button><button type="button" id="testBtn">Test Shape</button><button type="button" id="saveBtn" class="build-primary-button">Save Region</button></div><p class="hotspot-editor-help">Polygon: click around the true clickable boundary. Circle: click the center and adjust the radius.</p></div>
<div id="prepPanel" hidden><div class="image-prep-controls"><label><span>Prep tool</span><select id="prepTool"><option value="mask">Hide / cover text</option><option value="text">Add text label</option></select></label><label id="maskStyleLabel"><span>Cover style</span><select id="maskStyle"><option value="blur">Blur</option><option value="white">White box</option><option value="black">Black box</option></select></label><label id="maskWidthLabel"><span>Width <strong id="maskWVal">0.18</strong></span><input id="maskW" type="range" min="0.03" max="0.60" step="0.01" value="0.18"></label><label id="maskHeightLabel"><span>Height <strong id="maskHVal">0.07</strong></span><input id="maskH" type="range" min="0.02" max="0.35" step="0.01" value="0.07"></label><label id="textValueLabel" hidden><span>Text</span><input id="textValue" type="text" maxlength="180" placeholder="Label text"></label><label id="textSizeLabel" hidden><span>Text size</span><input id="textSize" type="number" min="10" max="48" value="18"></label><label id="textToneLabel" hidden><span>Label style</span><select id="textTone"><option value="light">Light</option><option value="dark">Dark</option></select></label></div><div class="hotspot-editor-actions"><button type="button" id="undoEditBtn">Undo Last Edit</button><button type="button" id="clearEditsBtn">Clear Image Edits</button><button type="button" id="saveEditsBtn" class="build-primary-button">Save Image Prep</button></div><p class="hotspot-editor-help">Edits are non-destructive overlays stored in the content-pack JSON. The original source image is never modified.</p></div>
<div class="hotspot-editor-stage"><img id="editorImage" alt="Study image" draggable="false"><div id="editorOverlay" class="image-edit-overlay"></div><svg id="editorSvg" viewBox="0 0 1000 1000" preserveAspectRatio="none"><polygon id="polygonShape"></polygon><circle id="circleShape"></circle><g id="pointHandles"></g></svg><div id="testMarker" class="hotspot-editor-test-marker" hidden></div></div><div class="hotspot-editor-status" id="editorStatus">Choose an image and editing mode.</div><details class="hotspot-editor-json"><summary>Current geometry / image-prep metadata</summary><pre id="geometryPreview">{}</pre></details></section>{% endif %}
<div class="review-return-row"><a class="review-return-link" href="/admin/maintenance">← Back to Maintenance</a></div></main></div>
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

    # DEBUG - retained for troubleshooting configured background images
# print("[DYNAMIC.CSS] background_image =", cfg.get("background_image"))

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

    return f""":root {{
  --portal-bg: {css_bg};
}}
""", 200, {"Content-Type": "text/css"}





# =========================
# SERVE USER BACKGROUNDS (RUNTIME SAFE)
# =========================
@app.route("/user-bg/<path:filename>")
def serve_user_background(filename):
    bg_dir = os.path.join(APP_DATA_DIR, "static", "bg")
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

    save_quiz_folders(renamed_folders)

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
    folders = [
        f for f in folders
        if f.lower() != folder.lower()
    ]
    save_quiz_folders(folders)

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

    # Preserve any folders that were not included in the request
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
# DEFAULT LAW STUDY AI PROMPT
# =========================
DEFAULT_LAW_AI_PROMPT = r"""You are helping a first-year law student study a judicial opinion.

Case:
{{case_name}}

Course:
{{course}}

Please create a law-school study packet for this case.

Use only accurate information. Do not invent citations, quotations, facts, holdings, or procedural history. If you are uncertain, say so clearly.

Prefer public legal sources when available, such as official court sources, Cornell LII, Justia, Oyez, CourtListener, or other reliable public legal sources. If you cannot verify the case from a reliable source, clearly state that verification is needed. Include the source links used in the Sources Used section of the DLMS IMPORT BLOCK.

Create the following sections:

{{study_sections}}

Formatting requirements:
- Use clear headings.
- Keep explanations beginner-friendly but law-school appropriate.
- Avoid long block quotes.
- Do not invent citations, quotations, facts, holdings, or procedural history.
- Include a final warning outside the DLMS import block reminding the student to verify the case against the original opinion or an approved legal research source.

Return your response as one clearly marked, copyable fenced code block using plain text format.

The fenced code block must begin with this heading:

DLMS IMPORT BLOCK

Inside the DLMS IMPORT BLOCK:
- This entire block should be downloadable/copyable as a single plain-text block.
- Include a Sources Used section at the top of the block.
- In Sources Used, list the public legal sources used to verify the case, including source name and URL when available.
- Prefer official court sources, Cornell LII, Justia, Oyez, CourtListener, or other reliable public legal sources.
- Include only the requested study sections after Sources Used.
- Include only Sources Used and sections 1, 2, 2A, 3, and 4 when those sections were requested.
- Do not include extra commentary inside the DLMS IMPORT BLOCK.
- Do not include the verification warning inside the DLMS IMPORT BLOCK.
- Use clean plain-text headings so the block can be pasted into DLMS.

Do not provide a separate explanation before the fenced code block.
Do not provide a separate explanation after the fenced code block.

The response format should be:

```text
DLMS IMPORT BLOCK

Sources Used
- Source name: URL

1. Case Brief
...

2. Socratic Review
...

2A. Socratic Answer Key
...

3. IRAC Drill
...

4. Rule Flashcards
...
```
"""

# =========================
# PORTAL CONFIG MANAGEMENT
# =========================
def load_portal_config():
    default = {
        "title": "Training & Practice Center",
        "show_confidence": False,
        "enable_regex_replace": False,
        "background_image": None,
        "quiz_folders": ["Uncategorized", "A+", "Network+", "Security+", "Data+", "Cloud+", "Linux+"],

        # AI Explanation Helper
        "ai_helper_enabled": False,
        "ai_provider": "chatgpt",
        "ai_custom_url": "",
        "ai_auto_copy_prompt": True,
        "ai_prompt_template": """You are a technical tutor helping a student learn from mistakes.

        For each question:
        1. Explain why the correct answer is correct
        2. Explain why the selected answer is incorrect
        3. Give a short memory tip
        4. Keep explanations concise but clear
        5. Return your answer in clearly separated sections per question.

        ---

        {{questions}}
        """,
        "law_ai_prompt_template": DEFAULT_LAW_AI_PROMPT,
    }

    # Ensure config directory exists
    os.makedirs(os.path.dirname(PORTAL_CONFIG), exist_ok=True)

    # First run: create portal.json
    if not os.path.exists(PORTAL_CONFIG):
        try:
            with open(PORTAL_CONFIG, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2)
            print("[PORTAL CONFIG] Created default portal.json")
        except Exception as e:
            print("[PORTAL CONFIG][ERROR] Failed to create portal.json:", e)

        return default.copy()

    # Normal load (MERGE, do not FILTER)
    try:
        with open(PORTAL_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f) or {}

        # Merge defaults with stored values
        cfg = default.copy()
        cfg.update(data)

        # Normalize booleans (checkbox safety)
        cfg["show_confidence"] = bool(cfg.get("show_confidence", False))
        cfg["enable_regex_replace"] = bool(cfg.get("enable_regex_replace", False))

        # Normalize title
        cfg["title"] = str(cfg.get("title") or default["title"]).strip()

        # Normalize background
        bg = cfg.get("background_image")
        cfg["background_image"] = bg.strip() if isinstance(bg, str) and bg.strip() else None

        cfg["ai_helper_enabled"] = bool(cfg.get("ai_helper_enabled", False))
        cfg["ai_auto_copy_prompt"] = bool(cfg.get("ai_auto_copy_prompt", True))

        valid_ai_providers = {"chatgpt", "claude", "gemini", "local"}
        provider = str(cfg.get("ai_provider") or "chatgpt").strip().lower()
        cfg["ai_provider"] = provider if provider in valid_ai_providers else "chatgpt"

        cfg["ai_custom_url"] = str(cfg.get("ai_custom_url") or "").strip()

        return cfg

    except Exception as e:
        print("[PORTAL CONFIG][ERROR] Failed to load portal.json:", e)
        return default.copy()


def save_portal_config(title, show_confidence=False, enable_regex_replace=False, background_image=None):
    cfg = load_portal_config()

    cfg["title"] = title
    cfg["show_confidence"] = bool(show_confidence)
    cfg["enable_regex_replace"] = bool(enable_regex_replace)

    if background_image is not None:
        cfg["background_image"] = background_image

    with open(PORTAL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def get_quiz_folders():
    cfg = load_portal_config()

    folders = cfg.get("quiz_folders") or []

    cleaned = []
    seen = set()

    for folder in folders:
        name = str(folder or "").strip()

        if not name:
            continue

        key = name.lower()

        if key in seen:
            continue

        cleaned.append(name)
        seen.add(key)

    if "uncategorized" not in seen:
        cleaned.insert(0, "Uncategorized")

    return cleaned


def save_quiz_folders(folders):
    cfg = load_portal_config()

    cleaned = []
    seen = set()

    for folder in folders:
        name = str(folder or "").strip()

        if not name:
            continue

        key = name.lower()

        if key in seen:
            continue

        cleaned.append(name)
        seen.add(key)

    if "uncategorized" not in seen:
        cleaned.insert(0, "Uncategorized")

    cfg["quiz_folders"] = cleaned

    with open(PORTAL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)



def get_portal_title():
    return load_portal_config().get("title", "Training & Practice Center")


def get_confidence_setting():
    return load_portal_config().get("show_confidence", False)


# =========================
# LAW STUDY REGISTRY
# =========================
def load_law_registry():
    default = {
        "version": "1",
        "cases": [],
        "folders": [
            "Torts",
            "Contracts",
            "Civil Procedure",
            "Criminal Law",
            "Property",
            "Constitutional Law",
            "Legal Writing"
        ]
    }

    os.makedirs(os.path.dirname(LAW_REGISTRY), exist_ok=True)

    if not os.path.exists(LAW_REGISTRY):
        try:
            with open(LAW_REGISTRY, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2)
            return default.copy()
        except Exception as e:
            print(f"[LAW REGISTRY ERROR] create failed: {e}")
            return default.copy()

    try:
        with open(LAW_REGISTRY, "r", encoding="utf-8") as f:
            data = json.load(f) or {}

        cfg = default.copy()
        cfg.update(data)

        if not isinstance(cfg.get("cases"), list):
            cfg["cases"] = []

        if not isinstance(cfg.get("folders"), list):
            cfg["folders"] = default["folders"]

        return cfg

    except Exception as e:
        print(f"[LAW REGISTRY ERROR] load failed: {e}")
        return default.copy()


def save_law_registry(registry):
    try:
        os.makedirs(os.path.dirname(LAW_REGISTRY), exist_ok=True)

        if not isinstance(registry, dict):
            registry = {
                "version": "1",
                "cases": [],
                "folders": []
            }

        registry.setdefault("version", "1")
        registry.setdefault("cases", [])
        registry.setdefault("folders", [])

        with open(LAW_REGISTRY, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)

    except Exception as e:
        print(f"[LAW REGISTRY ERROR] save failed: {e}")



# =========================
# QUIZ REGISTRY
# =========================
registry_lock = threading.RLock()

def load_registry():
    with registry_lock:
        if not os.path.exists(QUIZ_REGISTRY):
            return []

        try:
            with open(QUIZ_REGISTRY, "r", encoding="utf-8") as f:
                registry = json.load(f)

            if registry is None:
                return []

            if not isinstance(registry, list):
                raise ValueError("Quiz registry must contain a JSON list")

            return registry

        except Exception as e:
            print(f"[REGISTRY ERROR] load_registry failed: {e}")
            raise RuntimeError(
                f"Quiz registry could not be loaded safely: {e}"
            ) from e

def save_registry(registry):
    temp_file = QUIZ_REGISTRY + ".tmp"

    try:
        os.makedirs(os.path.dirname(QUIZ_REGISTRY), exist_ok=True)

        with registry_lock:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=4)
                f.flush()
                os.fsync(f.fileno())

            # Validate the temporary file before replacing the live registry
            with open(temp_file, "r", encoding="utf-8") as f:
                validated = json.load(f)

            if not isinstance(validated, list):
                raise ValueError("Quiz registry must contain a JSON list")

            os.replace(temp_file, QUIZ_REGISTRY)

    except Exception as e:
        print(f"[REGISTRY ERROR] save_registry failed: {e}")

        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass
        raise


def normalize_quiz_folders(registry):
    """
    Backward-compatible folder support for the Quiz Library.

    Existing quizzes may not have a folder field yet.
    This guarantees every quiz has one without changing quiz files,
    quiz IDs, history, results, or generated HTML/JSON.
    """
    with registry_lock:
        changed = False

        for q in registry:
            folder = str(q.get("folder") or "").strip()

            if not folder:
                q["folder"] = "Uncategorized"
                changed = True

        if changed:
            save_registry(registry)

        return registry

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

@app.route("/content-packs/import", methods=["POST"])
def content_pack_import():
    upload = request.files.get("pack_zip")
    if not upload or not upload.filename:
        flash("Choose a DLMS Study Pack ZIP to validate.", "error")
        return redirect("/content-packs")
    if not str(upload.filename).lower().endswith(".zip"):
        flash("Content Packs must be uploaded as ZIP files.", "error")
        return redirect("/content-packs")

    if request.content_length and request.content_length > 256 * 1024 * 1024:
        flash("Study Pack ZIP is too large. Maximum upload size is 256 MB.", "error")
        return redirect("/content-packs")

    token = secrets.token_hex(16)
    stage_dir = _content_pack_stage_path(token)
    os.makedirs(stage_dir, exist_ok=False)
    zip_path = os.path.join(stage_dir, "upload.zip")

    try:
        upload.save(zip_path)
        if not zipfile.is_zipfile(zip_path):
            raise ValueError("uploaded file is not a valid ZIP archive")
        inspection = _inspect_content_pack_zip(zip_path)
        extract_root = os.path.join(stage_dir, "extracted")
        _extract_content_pack_zip(zip_path, extract_root)
        pack_root = _safe_pack_child(extract_root, inspection["root_name"])
        report = _validate_staged_content_pack(pack_root)

        metadata = {
            "token": token,
            "root_name": inspection["root_name"],
            "extract_root": "extracted",
            "uploaded_name": secure_filename(upload.filename) or "study_pack.zip",
            "file_count": inspection["file_count"],
            "uncompressed_bytes": inspection["uncompressed_bytes"],
            "report": report,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        # Store only relative pack-root information; never trust client paths.
        metadata["root_name"] = f"extracted/{inspection['root_name']}"
        with open(os.path.join(stage_dir, "stage.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return redirect(url_for("content_pack_import_review", token=token))
    except Exception as exc:
        shutil.rmtree(stage_dir, ignore_errors=True)
        flash(f"Study Pack ZIP could not be validated: {exc}", "error")
        return redirect("/content-packs")


@app.route("/content-packs/import/<token>")
def content_pack_import_review(token):
    try:
        stage_dir, pack_root, metadata = _load_staged_content_pack(token)
        # Revalidate on every review instead of trusting the saved report.
        report = _validate_staged_content_pack(pack_root)
        metadata["report"] = report
    except Exception as exc:
        flash(f"Study Pack validation session is unavailable: {exc}", "error")
        return redirect("/content-packs")

    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Validate Content Pack - DLMS</title>
<link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home content-packs-page">
<div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar">
<div class="dashboard-brand"><div class="dashboard-brand-mark">✓</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div>
<nav class="dashboard-nav">
<a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
<a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
<a class="dashboard-nav-item active" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
<a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
</nav>
<div class="dashboard-sidebar-version">Pack Validation</div>
</aside>
<main class="dashboard-main content-packs-main">
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="medical-eyebrow">CONTENT PACK IMPORT</div><h1>Validate Study Pack</h1><p>DLMS independently checks the ZIP before anything is installed.</p></div></header>

<section class="dashboard-panel pack-review-summary">
<div>
<span class="medical-eyebrow">{{ 'READY TO INSTALL' if report.valid else 'INSTALL BLOCKED' }}</span>
<h2>{{ report.pack_name or metadata.uploaded_name }}</h2>
<p>{{ metadata.uploaded_name }} · {{ metadata.file_count }} files · {{ "%.1f"|format(metadata.uncompressed_bytes / 1048576) }} MB expanded</p>
</div>
<span class="content-pack-status {{ 'is-valid' if report.valid else 'is-invalid' }}">{{ 'Valid' if report.valid else 'Invalid' }}</span>
</section>

<section class="dashboard-panel pack-validation-panel">
<div class="content-pack-manager-heading"><div><span class="medical-eyebrow">DLMS VALIDATION</span><h2>Validation Report</h2></div><span class="pack-count-pill">{{ report.dataset_count }} dataset{{ '' if report.dataset_count == 1 else 's' }}</span></div>
<div class="pack-validation-summary-grid"><div><span>Passed</span><strong>{{ report.checks|selectattr('status','equalto','PASS')|list|length }}</strong></div><div><span>Warnings</span><strong>{{ report.warnings|length }}</strong></div><div><span>Errors</span><strong>{{ report.errors|length }}</strong></div></div>
<div class="pack-validation-checks">
{% for check in report.checks %}
<div class="pack-validation-check"><span class="pack-validation-state {{ check.status|lower }}">{{ check.status }}</span><strong>{{ check.name }}</strong><span>{{ check.detail }}</span></div>
{% endfor %}
</div>
{% if report.errors %}
<div class="pack-validation-messages errors"><h3>Blocking problems</h3><ul>{% for item in report.errors %}<li>{{ item }}</li>{% endfor %}</ul></div>
{% endif %}
{% if report.warnings %}
<div class="pack-validation-messages warnings"><h3>Warnings</h3><ul>{% for item in report.warnings %}<li>{{ item }}</li>{% endfor %}</ul></div>
{% endif %}
</section>

<section class="dashboard-panel pack-review-actions">
{% if report.valid %}
<form method="POST" action="/content-packs/import/{{ token }}/install">
<label class="content-pack-confirm-check"><input type="checkbox" name="confirm_install" value="yes" required><span>Install this validated Study Pack into DLMS.</span></label>
<button class="medical-primary-button" type="submit">Install Study Pack</button>
</form>
{% else %}
<p>Installation is disabled until the blocking validation problems are corrected.</p>
{% endif %}
<form method="POST" action="/content-packs/import/{{ token }}/cancel"><button class="medical-ai-secondary-button" type="submit">Cancel &amp; Remove Staging Files</button></form>
<a class="medical-ai-quiet-link" href="/content-packs">← Back to Content Packs</a>
</section>
</main></div>
<script>document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));</script>
<script src="/static/nav-normalize.js"></script>
</body></html>
""", token=token, metadata=metadata, report=report, medical_pack_installed=True)


@app.route("/content-packs/import/<token>/install", methods=["POST"])
def content_pack_import_install(token):
    if request.form.get("confirm_install") != "yes":
        flash("Study Pack installation was not confirmed.", "error")
        return redirect(url_for("content_pack_import_review", token=token))

    destination = None
    pack_root = None
    try:
        stage_dir, pack_root, metadata = _load_staged_content_pack(token)
        report = _validate_staged_content_pack(pack_root)
        if not report["valid"]:
            flash("Study Pack is no longer valid; installation was blocked.", "error")
            return redirect(url_for("content_pack_import_review", token=token))

        manifest = report["manifest"]
        pack_id = str(manifest.get("id") or "").strip().lower()
        current = discover_content_packs()
        if pack_id in current:
            raise ValueError(f"a Study Pack with id '{pack_id}' is already installed")

        folder_name = os.path.basename(pack_root)
        destination = os.path.realpath(os.path.join(CONTENT_PACK_FOLDER, folder_name))
        if os.path.dirname(destination) != os.path.realpath(CONTENT_PACK_FOLDER):
            raise ValueError("Study Pack destination is unsafe")
        if os.path.exists(destination):
            raise ValueError(f"destination folder '{folder_name}' already exists")

        # Move only after all pre-install checks succeed.
        shutil.move(pack_root, destination)

        # Verify through normal runtime discovery. Roll back on failure.
        installed = discover_content_packs().get(pack_id)
        if not installed:
            raise ValueError("DLMS could not discover the pack after installation")

        _remove_content_pack_stage(token)
        flash(f"Installed Study Pack '{installed.get('name') or pack_id}' successfully.", "success")
        return redirect("/content-packs")
    except Exception as exc:
        # If the move occurred but runtime validation failed, restore the staged
        # pack when possible so the review session remains usable.
        try:
            if destination and os.path.isdir(destination) and pack_root:
                os.makedirs(os.path.dirname(pack_root), exist_ok=True)
                if not os.path.exists(pack_root):
                    shutil.move(destination, pack_root)
        except Exception as rollback_exc:
            print(f"[CONTENT PACKS] Import rollback failed: {rollback_exc}")
        flash(f"Study Pack was not installed: {exc}", "error")
        try:
            _load_staged_content_pack(token)
            return redirect(url_for("content_pack_import_review", token=token))
        except Exception:
            return redirect("/content-packs")


@app.route("/content-packs/import/<token>/cancel", methods=["POST"])
def content_pack_import_cancel(token):
    _remove_content_pack_stage(token)
    flash("Study Pack import cancelled; staging files were removed.", "success")
    return redirect("/content-packs")


@app.route("/content-packs/details/<folder>")
def content_pack_details(folder):
    try:
        report = _content_pack_folder_report(folder)
    except Exception as exc:
        flash(f"Content Pack details are unavailable: {exc}", "error")
        return redirect("/content-packs")
    manifest = report.get("manifest") or {}
    matching = len(manifest.get("datasets") or []) if isinstance(manifest.get("datasets") or [], list) else 0
    image = len(manifest.get("image_datasets") or []) if isinstance(manifest.get("image_datasets") or [], list) else 0
    mixed = len(manifest.get("quiz_datasets") or []) if isinstance(manifest.get("quiz_datasets") or [], list) else 0
    return render_template_string(r"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Content Pack Details - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home content-packs-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar">
<div class="dashboard-brand"><div class="dashboard-brand-mark">⬡</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div>
<nav class="dashboard-nav">
<a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a>
<a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a>
<a class="dashboard-nav-item" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a>
<a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>
<a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a>
<a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>
<a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a>
<a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a>
<div class="dashboard-nav-group"><a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a><div class="dashboard-nav-submenu"><a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a><a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a></div></div>
</nav>
<div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system">
<a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
<a class="dashboard-nav-item active" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
<a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a>
<a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
<a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
</nav><div class="dashboard-sidebar-version">Pack Details</div></aside>
<main class="dashboard-main content-packs-main"><header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="medical-eyebrow">CONTENT PACK REPORT</div><h1>{{ report.pack_name }}</h1><p>Installed Study Pack metadata and independent DLMS validation.</p></div></header>
<section class="dashboard-panel pack-detail-hero"><div><span class="medical-eyebrow">{{ manifest.get('content_domain') or manifest.get('extends') or 'GENERAL' }}{% if manifest.get('version') %} · v{{ manifest.get('version') }}{% endif %}</span><h2>{{ report.pack_name }}</h2><p>{{ manifest.get('description') or 'No pack description provided.' }}</p></div><span class="content-pack-status {{ 'is-valid' if report.valid else 'is-invalid' }}">{{ 'Valid' if report.valid else 'Invalid' }}</span></section>
<section class="pack-detail-stat-grid"><article class="dashboard-stat-card"><span>Datasets</span><strong>{{ matching + image + mixed }}</strong><small>{{ matching }} matching · {{ image }} image · {{ mixed }} mixed</small></article><article class="dashboard-stat-card"><span>Storage</span><strong>{{ report.size }}</strong><small>{{ report.file_count }} files</small></article><article class="dashboard-stat-card"><span>Generated Quizzes</span><strong>{{ report.generated_quizzes }}</strong><small>tracked from this pack</small></article><article class="dashboard-stat-card"><span>Warnings</span><strong>{{ report.warnings|length }}</strong><small>{{ report.errors|length }} blocking errors</small></article></section>
<section class="dashboard-panel pack-validation-panel"><div class="content-pack-manager-heading"><div><span class="medical-eyebrow">INDEPENDENT VALIDATION</span><h2>Validation Report</h2></div><span class="pack-count-pill">{{ report.checks|length }} checks</span></div><div class="pack-validation-checks">{% for check in report.checks %}<div class="pack-validation-check"><span class="pack-validation-state {{ check.status|lower }}">{{ check.status }}</span><strong>{{ check.name }}</strong><span>{{ check.detail }}</span></div>{% endfor %}</div>{% if report.errors %}<div class="pack-validation-messages errors"><h3>Blocking problems</h3><ul>{% for item in report.errors %}<li>{{ item }}</li>{% endfor %}</ul></div>{% endif %}{% if report.warnings %}<div class="pack-validation-messages warnings"><h3>Warnings</h3><ul>{% for item in report.warnings %}<li>{{ item }}</li>{% endfor %}</ul></div>{% endif %}</section>
<section class="dashboard-panel pack-detail-meta"><div><strong>Pack ID</strong><span>{{ report.pack_id or 'Unavailable' }}</span></div><div><strong>Folder</strong><span>{{ report.folder }}</span></div><div><strong>Installed / modified</strong><span>{{ report.installed_at }}</span></div><div><strong>Schema</strong><span>{{ manifest.get('schema_version', 'Unavailable') }}</span></div></section>
<section class="pack-detail-actions"><a class="medical-ai-secondary-button" href="/content-packs">← Back to Content Packs</a>{% if report.valid %}<a class="medical-primary-button" href="/content-packs/export/{{ report.folder }}">Export Study Pack ZIP</a>{% endif %}</section>
</main></div><script>document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));</script><script src="/static/nav-normalize.js"></script>
</body></html>
""", report=report, manifest=manifest, matching=matching, image=image, mixed=mixed, medical_pack_installed=True)


@app.route("/content-packs/export/<folder>")
def export_content_pack(folder):
    try:
        report = _content_pack_folder_report(folder)
        if not report.get("valid"):
            raise ValueError("invalid Study Packs cannot be exported until validation errors are corrected")
        pack_root = report["root"]
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for walk_root, dirs, files in os.walk(pack_root):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(walk_root, d))]
                for name in files:
                    source = os.path.join(walk_root, name)
                    if os.path.islink(source) or not os.path.isfile(source):
                        continue
                    relative = os.path.relpath(source, pack_root).replace(os.sep, "/")
                    zf.write(source, arcname=f"{folder}/{relative}")
        archive.seek(0)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", folder).strip("._") or "DLMS_Study_Pack"
        return Response(
            archive.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.zip"'}
        )
    except Exception as exc:
        flash(f"Study Pack export failed: {exc}", "error")
        return redirect("/content-packs")


@app.route("/content-packs")
def content_packs_page():
    packs = content_pack_management_summary()
    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Content Packs - DLMS</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">
</head>
<body class="dashboard-home content-packs-page">
<div class="dashboard-shell">
    <aside class="dashboard-sidebar" id="dashboardSidebar">
        <div class="dashboard-brand">
            <div class="dashboard-brand-mark">◇</div>
            <div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div>
        </div>
        <nav class="dashboard-nav">
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
                <a class="dashboard-nav-item" href="/anki"><span class="dashboard-nav-icon">◆</span><span>Anki Tools</span></a>
                <div class="dashboard-nav-submenu"><a class="dashboard-nav-subitem" href="/anki/custom"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a><a class="dashboard-nav-subitem" href="/anki/law"><span class="dashboard-nav-subicon">↳</span><span>Law Study Anki</span></a></div>
            </div>
        </nav>
        <div class="dashboard-nav-section-label"><span>System</span></div>
        <nav class="dashboard-nav dashboard-nav-system">
            <a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a>
            <a class="dashboard-nav-item active" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a>
            <a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a>
            <a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a>
            <a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a>
        </nav>
        <div class="dashboard-sidebar-version">Content Packs</div>
    </aside>

    <main class="dashboard-main content-packs-main">
        <header class="dashboard-header">
            <button class="dashboard-menu-button" id="menuButton" type="button">☰</button>
            <div><div class="medical-eyebrow">CONTENT MANAGEMENT</div><h1>Content Packs</h1>
            <p>Validate, inspect, open, and safely remove installed study content.</p></div>
        </header>

        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        <div class="content-pack-flashes">
            {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
        </div>
        {% endif %}
        {% endwith %}

        <section class="dashboard-panel content-pack-upload-panel">
            <div class="content-pack-upload-copy">
                <span class="medical-eyebrow">INSTALL STUDY CONTENT</span>
                <h2>Install Content Pack</h2>
                <p>Select a DLMS Study Pack ZIP. DLMS stages and independently validates the archive first; nothing is installed until you review the report and confirm.</p>
                <div class="content-pack-upload-guardrails">
                    <span>One top-level pack folder</span>
                    <span>Safe archive paths</span>
                    <span>Manifest + JSON validation</span>
                    <span>Referenced-file checks</span>
                </div>
            </div>
            <form method="POST" action="/content-packs/import" enctype="multipart/form-data" class="content-pack-upload-form">
                <label class="build-field"><span>Study Pack ZIP</span><input type="file" name="pack_zip" accept=".zip,application/zip" required><small>The ZIP is validated before installation.</small></label>
                <button class="medical-primary-button" type="submit">Validate ZIP</button>
            </form>
        </section>

        <section class="dashboard-panel pack-install-panel">
            <div class="pack-install-heading">
                <div><span class="medical-eyebrow">INSTALL LOCATION</span><h2>Content Pack Folder</h2></div>
                <span class="pack-count-pill">{{ packs|length }} installed folder{{ '' if packs|length == 1 else 's' }}</span>
            </div>
            <code class="pack-path">{{ pack_folder }}</code>
            <p>Each pack should be one direct child folder containing <strong>manifest.json</strong>. Deleting a pack removes its source datasets and images; generated quizzes and history are preserved.</p>
        </section>

        <section class="dashboard-panel content-pack-manager">
            <div class="content-pack-manager-heading">
                <div><span class="medical-eyebrow">INSTALLED CONTENT</span><h2>Pack Manager</h2></div>
                <a class="medical-primary-button" href="/study-packs">Open Study Packs</a>
            </div>

            {% if packs %}
            <div class="content-pack-table-wrap">
            <table class="content-pack-table">
                <thead>
                    <tr>
                        <th>Pack</th>
                        <th>Status</th>
                        <th>Content</th>
                        <th>Storage</th>
                        <th>Quizzes</th>
                        <th class="content-pack-actions-col">Actions</th>
                    </tr>
                </thead>
                <tbody>
                {% for pack in packs %}
                    <tr>
                        <td>
                            <div class="content-pack-name">
                                <strong>{{ pack.name }}</strong>
                                <span>{{ pack.domain }}{% if pack.version %} · v{{ pack.version }}{% endif %}</span>
                                <small>{{ pack.folder }}</small>
                            </div>
                        </td>
                        <td>
                            <span class="content-pack-status {{ 'is-invalid' if pack.status == 'Invalid' else ('is-warning' if pack.warning_count else 'is-valid') }}">{{ pack.status }}</span>
                            {% if pack.protected %}<span class="content-pack-protected">Protected</span>{% endif %}
                        </td>
                        <td>
                            <div class="content-pack-counts">
                                {% if pack.matching_count %}<span>{{ pack.matching_count }} matching</span>{% endif %}
                                {% if pack.image_count %}<span>{{ pack.image_count }} image</span>{% endif %}
                                {% if pack.mixed_count %}<span>{{ pack.mixed_count }} mixed</span>{% endif %}
                                {% if not pack.dataset_count %}<span>—</span>{% endif %}
                            </div>
                        </td>
                        <td><span class="content-pack-storage">{{ pack.size }}</span><small>{{ pack.file_count }} files</small></td>
                        <td>
                            <span class="content-pack-storage">{{ pack.generated_quizzes }}</span>
                            <small>tracked generated</small>
                        </td>
                        <td class="content-pack-actions-col">
                            <div class="content-pack-actions">
                                {% if pack.exportable %}
                                <a class="content-pack-action" href="/study-packs">Open</a>
                                <a class="content-pack-action" href="/content-packs/export/{{ pack.folder }}">Export</a>
                                {% endif %}
                                <a class="content-pack-action" href="/content-packs/details/{{ pack.folder }}">Details</a>
                                {% if pack.protected %}
                                <span class="content-pack-action disabled">Delete</span>
                                {% else %}
                                <button type="button" class="content-pack-action danger" onclick='openDeletePack({{ pack.folder|tojson }},{{ pack.name|tojson }})'>Delete</button>
                                {% endif %}
                            </div>
                        </td>
                    </tr>
                    <tr class="content-pack-detail-row content-pack-inline-status-row">
                        <td colspan="6"><div class="content-pack-inline-status">
                            <span>{{ pack.status_detail }}</span>
                            {% if pack.warning_count %}<span class="content-pack-inline-warning">{{ pack.warning_count }} warning{{ '' if pack.warning_count == 1 else 's' }}</span>{% endif %}
                            {% if pack.error_count %}<span class="content-pack-inline-error">{{ pack.error_count }} error{{ '' if pack.error_count == 1 else 's' }}</span>{% endif %}
                        </div></td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
            </div>
            {% else %}
            <div class="pack-empty-card"><h2>No content packs installed</h2><p>DLMS core is working normally. Install or create a Study Pack to manage it here.</p></div>
            {% endif %}
        </section>
    </main>
</div>

<div class="content-pack-delete-backdrop" id="deletePackDialog" hidden>
    <div class="content-pack-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="deletePackTitle">
        <span class="medical-eyebrow">REMOVE STUDY CONTENT</span>
        <h2 id="deletePackTitle">Delete Study Pack?</h2>
        <p id="deletePackMessage"></p>
        <div class="content-pack-delete-note">
            <strong>Generated quizzes and attempt history are kept.</strong>
            <span>Before removal, DLMS copies any legacy quiz images that still depend on this pack into quiz-owned storage.</span>
        </div>
        <form method="POST" action="/content-packs/delete" id="deletePackForm">
            <input type="hidden" name="folder" id="deletePackFolder">
            <label class="content-pack-confirm-check">
                <input type="checkbox" name="confirm_delete" value="yes" required>
                <span>I understand the installed source pack will be removed.</span>
            </label>
            <div class="content-pack-delete-actions">
                <button type="button" class="medical-ai-secondary-button" onclick="closeDeletePack()">Cancel</button>
                <button type="submit" class="content-pack-delete-button">Delete Study Pack</button>
            </div>
        </form>
    </div>
</div>

<script>
const menuButton=document.getElementById("menuButton");
const sidebar=document.getElementById("dashboardSidebar");
if(menuButton&&sidebar){menuButton.addEventListener("click",()=>sidebar.classList.toggle("open"));}

function openDeletePack(folder,name){
    document.getElementById("deletePackFolder").value=folder;
    document.getElementById("deletePackMessage").textContent=`Delete “${name}” from installed Content Packs?`;
    document.getElementById("deletePackDialog").hidden=false;
}
function closeDeletePack(){
    const dialog=document.getElementById("deletePackDialog");
    dialog.hidden=true;
    const check=dialog.querySelector('input[name="confirm_delete"]');
    if(check) check.checked=false;
}
document.getElementById("deletePackDialog")?.addEventListener("click",(event)=>{
    if(event.target.id==="deletePackDialog") closeDeletePack();
});
</script>
<script src="/static/nav-normalize.js"></script>
</body></html>
    """, packs=packs, pack_folder=CONTENT_PACK_FOLDER, medical_pack_installed=True)


@app.route("/content-packs/delete", methods=["POST"])
def delete_content_pack():
    folder = str(request.form.get("folder") or "").strip()
    confirmed = request.form.get("confirm_delete") == "yes"
    if not confirmed:
        flash("Study Pack deletion was not confirmed.", "error")
        return redirect("/content-packs")
    if not folder or folder in {".", ".."} or os.path.basename(folder) != folder:
        flash("Invalid Content Pack folder.", "error")
        return redirect("/content-packs")

    pack_root = os.path.realpath(os.path.join(CONTENT_PACK_FOLDER, folder))
    content_root = os.path.realpath(CONTENT_PACK_FOLDER)
    if os.path.dirname(pack_root) != content_root or not os.path.isdir(pack_root):
        flash("Content Pack folder was not found.", "error")
        return redirect("/content-packs")

    manifest_path = os.path.join(pack_root, "manifest.json")
    pack_id = ""
    protected = False
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f) or {}
        pack_id = str(manifest.get("id") or "").strip().lower()
        protected = bool(manifest.get("protected"))
    except Exception:
        manifest = {}

    if protected:
        flash("This Content Pack declares itself protected and cannot be deleted here.", "error")
        return redirect("/content-packs")

    try:
        migration = {"files": 0, "references": 0}
        if pack_id and get_content_pack(pack_id):
            migration = _snapshot_existing_pack_dependencies(pack_id)
        shutil.rmtree(pack_root)
        message = f"Deleted Study Pack folder '{folder}'. Existing quizzes and history were kept."
        if migration["references"]:
            message += f" Preserved {migration['references']} legacy image reference(s) in quiz-owned storage."
        flash(message, "success")
    except Exception as exc:
        flash(f"Study Pack was not deleted: {exc}", "error")

    return redirect("/content-packs")


# =========================
# DEFAULT MEDICAL CONTENT PACK AI PROMPT
# =========================
DEFAULT_MEDICAL_CONTENT_PACK_PROMPT = r"""You are creating a self-contained DLMS Medical Study add-on content pack for educational study.

REQUESTED TOPIC
{{topic}}

CONTENT REQUEST
{{content_request}}

DIFFICULTY / DEPTH
{{difficulty}}

TARGET SIZE
{{size_guidance}}

NON-NEGOTIABLE ACCURACY AND SOURCE RULES
1. Research the requested topic before creating the pack. Do not rely on memory alone when authoritative sources can be checked.
2. Do not invent facts, definitions, citations, URLs, licenses, authors, image provenance, anatomical labels, or source claims.
3. If a fact or asset cannot be verified, OMIT it. Do not guess and do not fill gaps with plausible-sounding material.
4. Prefer authoritative educational and government sources with clear reuse rights, such as:
   - OpenStax material with an explicitly compatible open license
   - NIH, NLM, NCI, CDC, or other U.S. Government material when the individual asset is confirmed public domain or otherwise reusable
   - Wikimedia Commons ONLY when the exact file page clearly states a compatible license and provenance
   - Other reputable OER sources with explicit redistribution rights
5. For bundled images, use ONLY exact original files that are Public Domain, CC0, CC BY, or CC BY-SA, or another license that clearly permits redistribution in this pack.
6. Do NOT use copyrighted "all rights reserved" images, fair-use-only images, unclear-license images, stock imagery, watermarked imagery, or images copied from search-result thumbnails.
7. Do NOT use AI-generated or synthetic anatomy, histology, pathology, or microscopy images as authoritative medical study images.
8. Record image-level creator, source page, exact license, attribution, dimensions, and whether DLMS modified the image.
9. When an image license is share-alike, preserve all required share-alike obligations.
10. Do not claim physician review, faculty review, clinical validation, or peer review unless such review actually occurred and can be documented.
11. Label source-checked educational wording as "source-aligned" or "source-basis-verified", not "clinically validated".
12. This is foundational educational material, not clinical decision support, diagnosis, or treatment guidance.

STUDY QUALITY RULES
- Matching definitions must be concise enough to work well as matching choices.
- Avoid multiple definitions in the same dataset that are so similar that matching becomes arbitrary.
- Each term should have:
  - term
  - concise definition
  - category
  - a separate Study Mode explanation when a useful source-supported teaching point is available
  - verification metadata
- The explanation must add educational value rather than merely repeating the definition.
- Prefer an empty explanation over unsupported filler.
- Use standard medical terminology and preserve meaningful distinctions.
- If sources disagree, use the consensus/standard educational framing or omit the disputed item and document the issue.

DLMS PACK ARCHITECTURE
Create an independent Medical-domain Study Pack. Do not overwrite any existing installed Study Pack.

The root folder MUST be:
DLMS_Medical_<TOPIC_SLUG>/

The root manifest.json MUST include:
{
  "schema_version": 1,
  "id": "medical_<topic_slug>",
  "name": "DLMS Medical — <Readable Topic>",
  "version": "1.0.0",
  "requires_dlms": ">=3.0.0",
  "publisher": "User-generated DLMS study pack",
  "content_domain": "medical",
  "extends": "medical",
  "description": "...",
  "modules": ["terminology"],
  "datasets": [],
  "image_datasets": []
}

Use a lowercase unique id containing only letters, numbers, underscores, or hyphens.

MATCHING DATASET FORMAT
Each matching dataset is JSON and MUST use this structure:
{
  "schema_version": 1,
  "id": "unique_dataset_id",
  "title": "Readable title",
  "category": "Readable category",
  "type": "matching",
  "description": "What the student will study",
  "question_text": "Match each term with its best definition.",
  "source": {
    "organization": "...",
    "dataset": "...",
    "version": "...",
    "url": "https://...",
    "license": "...",
    "verification_status": "source-basis-verified"
  },
  "verification": {
    "status": "source-aligned",
    "verified_date": "YYYY-MM-DD",
    "method": "...",
    "sources": ["https://..."],
    "clinical_peer_reviewed": false
  },
  "terms": [
    {
      "term": "...",
      "definition": "...",
      "category": "...",
      "explanation": "...",
      "verification": {
        "status": "source-aligned",
        "verified_date": "YYYY-MM-DD",
        "reference_basis": "...",
        "source_urls": ["https://..."],
        "wording": "DLMS-authored concise wording; concept aligned to cited open reference",
        "clinical_peer_reviewed": false
      }
    }
  ]
}

IMAGE / HOTSPOT DATASET FORMAT
Only create an image dataset when you can legally bundle the exact source image in the output pack.

Each image dataset MUST use:
{
  "schema_version": 1,
  "id": "unique_image_dataset_id",
  "title": "Readable title",
  "category": "Anatomy, Histology, Cell Biology, etc.",
  "type": "hotspot",
  "description": "...",
  "source": {
    "organization": "...",
    "work": "...",
    "url": "exact source page URL",
    "license": "exact reusable license",
    "attribution": "required attribution"
  },
  "reference": {
    "organization": "...",
    "work": "...",
    "url": "https://...",
    "license": "..."
  },
  "images": [
    {
      "id": "stable_image_id",
      "file": "images/<category>/<filename>",
      "width": 0,
      "height": 0,
      "alt_text": "...",
      "source_url": "exact source page URL",
      "license": "...",
      "attribution": "...",
      "modified": false,
      "modification_note": "",
      "hotspots": [
        {
          "id": "stable_structure_id",
          "label": "Structure name",
          "prompt": "Identify the ...",
          "explanation": "Source-supported Study Mode teaching point.",
          "shape": {
            "type": "circle",
            "x": 0.5,
            "y": 0.5,
            "radius": 0.05
          },
          "calibration_status": "needs-dlms-editor-review",
          "verification": {
            "status": "source-aligned",
            "reference_basis": "...",
            "source_url": "https://...",
            "clinical_peer_reviewed": false
          }
        }
      ]
    }
  ]
}

IMPORTANT HOTSPOT RULE
Do NOT pretend guessed hotspot coordinates are final. If you cannot accurately calibrate against the exact bundled image, provide conservative starter regions and set:
"calibration_status": "needs-dlms-editor-review"
DLMS includes a Hotspot Calibration Editor for final circle/polygon calibration.

PACK FILE LAYOUT
At minimum:
DLMS_Medical_<TOPIC_SLUG>/
├── manifest.json
├── data/
│   ├── <matching datasets>.json
│   └── anatomy_or_images/
│       └── <image datasets>.json
├── images/
│   └── <exact legally reusable source image files>
├── LICENSES/
├── PROVENANCE.txt
├── SOURCE_POLICY.md
└── VALIDATION_REPORT.md

MANIFEST REGISTRATION
Every matching JSON file must be listed in manifest.json "datasets".
Every hotspot/image JSON file must be listed in manifest.json "image_datasets".
Do not declare an image dataset unless its referenced image file is actually included.

CRITICAL MANIFEST RULE:
"datasets" and "image_datasets" MUST be arrays of descriptor OBJECTS.
They MUST NOT be arrays of filename/path strings.

CORRECT:
"datasets": [
  {
    "id": "liver_histology_foundations",
    "title": "Liver Histology — Foundations",
    "type": "matching",
    "path": "data/liver_histology_foundations.json",
    "description": "..."
  }
]

WRONG — DO NOT DO THIS:
"datasets": [
  "data/liver_histology_foundations.json"
]

The same object-descriptor rule applies to "image_datasets".

VALIDATION REPORT
Before presenting the pack, verify and report:
- every JSON file parses
- every declared file exists
- no duplicate term within a dataset
- no duplicate definition within a dataset
- every term and definition is non-empty
- every dataset has source metadata
- every bundled image has exact provenance and a compatible redistribution license
- every image path resolves inside the pack
- every hotspot uses normalized coordinates from 0 to 1
- all uncertain hotspot geometry is explicitly marked for DLMS editor review
- clinical_peer_reviewed is false unless documented otherwise

DELIVERABLE
If your environment can create files:
1. Build the complete folder.
2. Include the exact legally reusable image files when image content was requested and verified.
3. ZIP the root folder.
4. Give the user ONE downloadable ZIP.
5. Also provide a concise source/license summary and validation result.

If your environment cannot create downloadable files:
- Output every required text file in clearly named fenced code blocks.
- Give exact source URLs for any omitted image assets.
- Clearly state that the pack is incomplete until those exact assets are legally obtained and placed at the declared paths.
- Do NOT claim the pack is installation-ready.

INSTALLATION TARGET
The completed add-on folder is placed directly under:
APP_DATA_DIR/content_packs/

Example:
content_packs/
└── DLMS_Medical_<TOPIC_SLUG>/

Medical Study Packs are optional and independently installable/removable. Do not assume a base Medical pack is present.

Do not nest the add-on folder inside another folder of the same name.

FINAL RESPONSE
Keep commentary short. Provide the finished pack first when possible, then the source/license summary, validation status, and any hotspot-calibration items that still require DLMS editor review.
"""


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
            <button class="dashboard-menu-button" id="menuButton" type="button">☰</button>
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

        <section class="dashboard-panel medical-ai-builder-panel">
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
            <button class="dashboard-menu-button" id="menuButton" type="button">☰</button>
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
            <button class="dashboard-menu-button" id="menuButton" type="button">☰</button>
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
            <button class="dashboard-menu-button" id="menuButton" type="button">☰</button>
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
        flash(f"Unable to load anatomy dataset: {exc}", "error")
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

    ts = int(time.time())
    safe_pack = re.sub(r"[^a-z0-9]+", "_", pack_id.lower()).strip("_") or "medical"
    safe_id = re.sub(r"[^a-z0-9]+", "_", dataset_id.lower()).strip("_") or "anatomy"
    html_name = f"medical_anatomy_{safe_pack}_{safe_id}_{ts}.html"
    json_name = f"medical_anatomy_{safe_pack}_{safe_id}_{ts}.json"
    json_path = os.path.join(DATA_FOLDER, json_name)
    html_path = os.path.join(QUIZ_FOLDER, html_name)

    bucket = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(html_name)[0])[:120]
    runtime_questions, db_questions, _ = _snapshot_runtime_questions(
        pack_id, runtime_questions, db_questions, bucket
    )

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(runtime_questions, f, indent=4, ensure_ascii=False)

    quiz_id = save_quiz_to_db(quiz_title, html_name, db_questions)
    add_quiz_to_registry(
        quiz_id=quiz_id,
        html=html_name,
        title=quiz_title,
        logo=None,
        exam_minutes=90,
        source_pack_id=pack_id,
        source_dataset_id=dataset_id
    )
    build_quiz_html(
        html_name, json_name, html_path, get_portal_title(),
        quiz_title, None, quiz_id, 90
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
        flash(f"Unable to load medical dataset: {exc}", "error")
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
        "source": {
            "organization": source.get("organization") or pack.get("publisher") or "",
            "dataset": source.get("dataset") or title,
            "version": source.get("version") or pack.get("version") or "",
            "url": source.get("url") or "",
            "license": source.get("license") or "",
        },
    }]

    ts = int(time.time())
    safe_pack = re.sub(r"[^a-z0-9]+", "_", pack_id.lower()).strip("_") or "medical"
    safe_id = re.sub(r"[^a-z0-9]+", "_", dataset_id.lower()).strip("_") or "medical"
    html_name = f"medical_{safe_pack}_{safe_id}_{ts}.html"
    json_name = f"medical_{safe_pack}_{safe_id}_{ts}.json"
    json_path = os.path.join(DATA_FOLDER, json_name)
    html_path = os.path.join(QUIZ_FOLDER, html_name)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=4, ensure_ascii=False)

    quiz_id = save_quiz_to_db(quiz_title, html_name, quiz_data)
    add_quiz_to_registry(
        quiz_id=quiz_id,
        html=html_name,
        title=quiz_title,
        logo=None,
        exam_minutes=90,
        source_pack_id=pack_id,
        source_dataset_id=dataset_id
    )
    build_quiz_html(
        html_name, json_name, html_path, get_portal_title(),
        quiz_title, None, quiz_id, 90
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
<header class="dashboard-header medical-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="medical-eyebrow">IT STUDY</div><h1>DLMS IT Study</h1><p>IT Study is ready. Install or create IT / Cybersecurity Study Packs to populate focused concept and diagram practice.</p></div></header>
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
<header class="dashboard-header medical-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="medical-eyebrow">IT STUDY</div><h1>DLMS IT Study</h1><p>Focused IT and cybersecurity practice collected automatically from installed IT-domain Study Packs.</p></div></header>
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
<main class="dashboard-main medical-main"><header class="dashboard-header medical-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="medical-eyebrow">IT STUDY · CONCEPTS</div><h1>Concepts &amp; Matching</h1><p>Choose an installed IT study bank, configure the round, and launch focused matching practice.</p></div></header>
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
<main class="dashboard-main medical-main"><header class="dashboard-header medical-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="medical-eyebrow">IT STUDY · VISUAL PRACTICE</div><h1>Diagrams &amp; Images</h1><p>Practice visual identification from installed IT diagrams, hardware images, architecture figures, and other source-documented visuals.</p></div></header>
<section class="medical-summary-grid medical-subpage-summary"><article class="dashboard-stat-card"><span>Image Sets</span><strong>{{ image_datasets|length }}</strong><small>installed visual datasets</small></article><article class="dashboard-stat-card"><span>Targets</span><strong>{{ total_hotspots }}</strong><small>across {{ total_images }} images</small></article><article class="dashboard-stat-card medical-subpage-back-card"><span>IT Study</span><a href="/it">← Back to IT Study</a><small>choose another study area</small></article></section>
{% if image_datasets %}<section class="dashboard-panel medical-compact-dataset-panel"><div class="medical-compact-panel-heading"><div><span class="medical-eyebrow">INSTALLED VISUAL CONTENT</span><h2>Image Study Sets</h2><p>Launch image practice or expand a row for source-pack details.</p></div></div><div class="study-dataset-table-wrap medical-dataset-table-wrap"><table class="study-dataset-table medical-dataset-table"><thead><tr><th>Type</th><th>Image Study Set</th><th>Images</th><th>Targets</th><th class="study-dataset-action-col">Action</th></tr></thead><tbody>
{% for d in image_datasets %}<tr><td><span class="study-type-badge image">Image</span></td><td><button type="button" class="study-dataset-title-button" onclick="const r=document.getElementById('it-image-{{ loop.index }}');r.hidden=!r.hidden">{{ d.title }}</button><small>{{ d.category }}</small></td><td><strong>{{ d.image_count }}</strong></td><td><strong>{{ d.hotspot_count }}</strong></td><td class="study-dataset-action-col"><form method="POST" action="/study-packs/image/generate"><input type="hidden" name="pack_id" value="{{ d.pack_id }}"><input type="hidden" name="dataset_id" value="{{ d.id }}"><button class="medical-primary-button study-table-primary" type="submit">Create Quiz</button></form></td></tr><tr id="it-image-{{ loop.index }}" class="study-dataset-detail-row" hidden><td colspan="5"><div class="medical-dataset-detail-content"><p>{{ d.description or 'No additional description supplied.' }}</p><div class="medical-dataset-detail-meta"><span><strong>Pack:</strong> {{ d.pack_name }}</span><span><strong>Dataset:</strong> {{ d.id }}</span></div></div></td></tr>{% endfor %}
</tbody></table></div></section>{% else %}<section class="dashboard-panel pack-empty-card"><h2>No IT image datasets installed</h2><p>Create or install an IT / Cybersecurity Study Pack with image datasets to populate this page.</p></section>{% endif %}
</main></div><script>document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));</script><script src="/static/nav-normalize.js"></script></body></html>
""", pack=pack, image_datasets=image_datasets, total_images=total_images, total_hotspots=total_hotspots, it_section="images")


# =========================
# GENERIC STUDY PACK PLATFORM
# =========================
DEFAULT_STUDY_CONTENT_PACK_PROMPT = r"""You are creating a self-contained DLMS Study Pack for educational use.

SUBJECT / DOMAIN
{{domain}}

REQUESTED TOPIC
{{topic}}

CONTENT REQUEST
{{content_request}}

DIFFICULTY / DEPTH
{{difficulty}}

TARGET SIZE
{{size_guidance}}

IMAGE REQUEST
{{image_guidance}}

SOURCE AND ACCURACY RULES
1. Research the requested topic before creating the pack. Prefer authoritative primary documentation, reputable open educational resources, standards bodies, government sources, and official vendor/project documentation.
2. Do not invent facts, commands, quotations, citations, URLs, versions, licenses, authors, image provenance, labels, or source claims.
3. If a fact or asset cannot be verified, omit it rather than guessing.
4. Every dataset must include useful source metadata. Each Study Mode explanation must add supported teaching value rather than merely repeating the definition.
5. For redistributable images, use only exact files with a clearly compatible license such as Public Domain, CC0, CC BY, or CC BY-SA. Record creator, exact source page, exact license, attribution, dimensions, and modification status.
6. Never copy images from search-result thumbnails or from sources with unclear rights.
7. Real screenshots/photos must be legitimately redistributable. If a requested real image cannot be redistributed, omit it and document why.
8. Educational diagrams may be newly drawn when the domain permits it, but mark them clearly as "DLMS-created educational schematic" and never imply that a schematic is an authentic screenshot, specimen, photograph, or authoritative medical image.
9. For medical/anatomical/histology/pathology content, do NOT use synthetic or AI-generated images as authoritative identification material; use source-verified open images only.
10. The pack is study material, not professional, clinical, legal, financial, or operational decision support.

STUDY QUALITY RULES
- Matching definitions must be concise and unambiguous.
- Avoid padding a dataset with weak or duplicative terms.
- Each term should include term, definition, category, explanation when source-supported, and verification/source metadata.
- For technical content, exact commands/configuration examples must be checked against the cited version/source.
- Image questions should identify visually meaningful regions; do not create arbitrary hotspots.

MULTI-IMAGE RULES
- A single image dataset may contain multiple images.
- Each image has its own hotspot list and source metadata.
- DLMS will turn hotspots across all images in the dataset into individual quiz questions, so multiple requested images are supported naturally.
- Use multiple datasets instead when the images represent substantially different subtopics.
- Do not combine unrelated diagrams into one giant composite image merely to reduce file count.

DLMS PACK ARCHITECTURE
Create an ADD-ON pack. Do not overwrite DLMS core or an existing pack.
Root folder: DLMS_Study_<TOPIC_SLUG>/

manifest.json MUST include descriptor OBJECTS, never path strings:
{
  "schema_version": 1,
  "id": "study_<topic_slug>",
  "name": "DLMS Study — <Readable Topic>",
  "version": "1.0.0",
  "requires_dlms": ">=3.0.0",
  "publisher": "User-generated DLMS study pack",
  "content_domain": "{{domain_slug}}",
  "description": "...",
  "datasets": [
    {"id":"dataset_id","title":"Readable title","type":"matching","path":"data/dataset.json","description":"..."}
  ],
  "image_datasets": [
    {"id":"image_dataset_id","title":"Readable title","type":"hotspot","path":"data/images/dataset.json","description":"..."}
  ],
  "quiz_datasets": [
    {"id":"mixed_dataset_id","title":"Readable title","type":"quiz","path":"data/questions/dataset.json","description":"..."}
  ]
}

MATCHING DATASET FORMAT
{
  "schema_version": 1,
  "id": "unique_dataset_id",
  "title": "Readable title",
  "category": "Readable category",
  "type": "matching",
  "description": "...",
  "question_text": "Match each item with its best answer.",
  "source": {"organization":"...","dataset":"...","version":"...","url":"https://...","license":"...","verification_status":"source-basis-verified"},
  "verification": {"status":"source-aligned","verified_date":"YYYY-MM-DD","method":"...","sources":["https://..."]},
  "terms": [
    {"term":"...","definition":"...","category":"...","explanation":"...","verification":{"status":"source-aligned","reference_basis":"...","source_urls":["https://..."]}}
  ]
}

IMAGE / HOTSPOT DATASET FORMAT
{
  "schema_version": 1,
  "id": "unique_image_dataset_id",
  "title": "Readable title",
  "category": "Diagram / Hardware / Anatomy / Map / etc.",
  "type": "hotspot",
  "description": "...",
  "source": {"organization":"...","work":"...","url":"exact source page","license":"...","attribution":"..."},
  "images": [
    {
      "id":"stable_image_id",
      "file":"images/category/file.png",
      "width":0,"height":0,"alt_text":"...",
      "source_url":"...","license":"...","attribution":"...","modified":false,"modification_note":"",
      "edits": [],
      "hotspots":[
        {"id":"target_id","label":"Target name","prompt":"Identify ...","explanation":"...","shape":{"type":"circle","x":0.5,"y":0.5,"radius":0.05},"calibration_status":"needs-dlms-editor-review","verification":{"status":"source-aligned","reference_basis":"...","source_url":"https://..."}}
      ]
    }
  ]
}

IMAGE PREP
DLMS has an Image Study Editor that can non-destructively hide labels/text with blur/white/black masks, add simple text labels, and calibrate circle/polygon clickable regions. If exact hotspot geometry cannot be confidently calibrated, use conservative starter regions and set calibration_status to "needs-dlms-editor-review".

PACK FILE LAYOUT
DLMS_Study_<TOPIC_SLUG>/
├── manifest.json
├── data/
├── images/
├── LICENSES/
├── PROVENANCE.txt
├── SOURCE_POLICY.md
└── VALIDATION_REPORT.md

VALIDATION BEFORE DELIVERY
You MUST validate the finished pack after all files are created. Do not merely state that it should validate.
- every JSON file parses
- manifest.json uses schema_version 1
- datasets, image_datasets, and quiz_datasets (when used) contain descriptor OBJECTS, never path strings
- every descriptor has id, title, type, path, and the declared file exists
- every dataset file id matches its manifest descriptor id
- there are no duplicate dataset IDs, image IDs, matching terms, or matching definitions
- every term and definition is non-empty
- every dataset has source metadata
- every bundled image exists at its declared path
- every bundled image records exact provenance and redistribution/license metadata
- every hotspot uses valid normalized coordinates from 0 through 1
- uncertain hotspot geometry is marked needs-dlms-editor-review
- the ZIP contains exactly ONE top-level Study Pack folder
- the top-level Study Pack folder directly contains manifest.json
- no archive path is absolute, uses .. traversal, or escapes the Study Pack folder

REQUIRED MACHINE-READABLE VALIDATION FILE
Include PACK_VALIDATION.json at the root of the Study Pack. This is an AI self-check for the user and does NOT replace DLMS's independent installer validation.

Use this structure:
{
  "schema_version": 1,
  "validator": "AI self-validation",
  "pack_id": "<same id as manifest.json>",
  "validated_at": "YYYY-MM-DD",
  "overall_status": "PASS",
  "checks": [
    {"name":"Manifest schema","status":"PASS","detail":"schema_version 1"},
    {"name":"Dataset descriptors","status":"PASS","detail":"All descriptor entries are objects with id/title/type/path"},
    {"name":"Referenced files","status":"PASS","detail":"All declared dataset and image files exist"},
    {"name":"Duplicate IDs","status":"PASS","detail":"No duplicate dataset/image IDs or matching terms/definitions"},
    {"name":"Image licenses","status":"PASS","detail":"Every bundled image has verified redistribution/license metadata"},
    {"name":"JSON parse check","status":"PASS","detail":"Every JSON file parses successfully"},
    {"name":"Top-level folder","status":"PASS","detail":"Exactly one top-level DLMS Study Pack folder contains manifest.json"}
  ],
  "errors": [],
  "warnings": []
}

If ANY required check fails:
- set overall_status to "FAIL"
- identify the exact error in errors
- FIX the pack and rerun validation before delivery
- do not describe the ZIP as installation-ready while overall_status is FAIL

Also include the human-readable VALIDATION_REPORT.md, but PACK_VALIDATION.json is required for AI-generated packs.

FINAL RESPONSE VALIDATION SUMMARY
In the response that accompanies the ZIP, print this concise summary using the actual results from the completed pack:
PACK VALIDATION
Manifest schema: PASS
Dataset descriptors: PASS
Referenced files: PASS
Duplicate IDs: PASS
Image licenses: PASS
JSON parse check: PASS
Top-level folder: PASS

Do not print PASS for a check you did not actually perform.

DELIVERABLE
If file creation is available, build the complete folder, include the exact permitted assets, include PACK_VALIDATION.json, ZIP the single root folder, and provide ONE downloadable ZIP plus the concise validation/source summary. If file creation is unavailable, do not claim the result is installation-ready.

INSTALLATION
The ZIP must contain exactly one root folder named DLMS_Study_<TOPIC_SLUG>/ with manifest.json directly inside it. DLMS can then validate and install that ZIP from Content Packs. Never nest the same root folder inside itself.
"""


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
    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Study Packs - DLMS</title>
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
    <div class="dashboard-sidebar-version">Study Packs</div>
</aside>

<main class="dashboard-main study-packs-main">
    <header class="dashboard-header">
        <button class="dashboard-menu-button" id="menuButton" type="button">☰</button>
        <div>
            <div class="medical-eyebrow">CUSTOM STUDY CONTENT</div>
            <h1>Study Packs</h1>
            <p>Launch focused practice from installed study content without scrolling through large card grids.</p>
        </div>
    </header>

    {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
    <div class="content-pack-flashes">
        {% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}
    </div>
    {% endif %}
    {% endwith %}

    <section class="study-pack-launch-grid">
        <a class="dashboard-panel study-pack-launch" href="/study-packs/ai-builder">
            <div class="study-pack-launch-icon">AI</div>
            <div><span class="medical-eyebrow">CREATE</span><h2>AI Study Pack Builder</h2><p>Create a source-disciplined DLMS pack prompt for any subject.</p></div>
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
    <details class="dashboard-panel study-pack-section study-pack-collapsible" data-pack-id="{{ pack.id }}" {% if loop.first %}open{% endif %}>
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
    <section class="dashboard-panel">
        <h2>No usable study packs yet</h2>
        <p>Create one with the AI Study Pack Builder, Build from Images, or install a compatible Content Pack.</p>
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
""", packs=packs, medical_pack_installed=True)




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
        flash(f"Unable to build question-set quiz: {exc}", "error")
        return redirect("/study-packs")


@app.route("/study-packs/generate", methods=["POST"])
def study_pack_generate_matching():
    pack_id=str(request.form.get("pack_id") or "").strip().lower(); dataset_id=str(request.form.get("dataset_id") or "").strip(); direction=str(request.form.get("direction") or "random").strip()
    if direction not in {"term_to_definition","definition_to_term","random"}: direction="random"
    pack=get_content_pack(pack_id)
    if not pack: flash("Study pack is not installed.","error"); return redirect("/study-packs")
    try: data=load_content_pack_dataset(pack_id,dataset_id)
    except Exception as exc: flash(f"Unable to load study dataset: {exc}","error"); return redirect("/study-packs")
    terms=data.get("terms") or []
    if len(terms)<2: flash("This dataset does not contain enough items.","error"); return redirect("/study-packs")
    try: round_size=int(request.form.get("round_size","10"))
    except (TypeError,ValueError): round_size=10
    round_size=max(2,min(round_size,min(100,len(terms))))
    title=str(data.get("title") or data["_descriptor"].get("title") or "Study Practice").strip(); source=data.get("source") or {}
    pairs=[{"left":i["term"],"right":i["definition"],"category":i.get("category","") ,"explanation":i.get("explanation") or i.get("study_explanation") or "","verification":i.get("verification") or data.get("verification") or {},"source":i.get("source") or source or {}} for i in terms]
    quiz_data=[{"number":1,"type":"matching","question":str(data.get("question_text") or "Match each item with its best answer.").strip(),"pairs":pairs,"round_size":round_size,"direction":direction,"source":{"organization":source.get("organization") or pack.get("publisher") or "","dataset":source.get("dataset") or title,"version":source.get("version") or pack.get("version") or "","url":source.get("url") or "","license":source.get("license") or ""}}]
    ts=int(time.time()); safe_pack=re.sub(r"[^a-z0-9]+","_",pack_id).strip("_") or "study"; safe_id=re.sub(r"[^a-z0-9]+","_",dataset_id.lower()).strip("_") or "dataset"; quiz_title=f"{title} — {round_size}-Pair Practice"; html_name=f"study_{safe_pack}_{safe_id}_{ts}.html"; json_name=f"study_{safe_pack}_{safe_id}_{ts}.json"; json_path=os.path.join(DATA_FOLDER,json_name); html_path=os.path.join(QUIZ_FOLDER,html_name)
    with open(json_path,"w",encoding="utf-8") as f: json.dump(quiz_data,f,indent=4,ensure_ascii=False)
    quiz_id=save_quiz_to_db(quiz_title,html_name,quiz_data); add_quiz_to_registry(quiz_id=quiz_id,html=html_name,title=quiz_title,logo=None,exam_minutes=90,source_pack_id=pack_id,source_dataset_id=dataset_id); build_quiz_html(html_name,json_name,html_path,get_portal_title(),quiz_title,None,quiz_id,90)
    return redirect(f"/quizzes/{html_name}")


@app.route("/study-packs/image/generate", methods=["POST"])
def study_pack_generate_image():
    pack_id=str(request.form.get("pack_id") or "").strip().lower(); dataset_id=str(request.form.get("dataset_id") or "").strip(); pack=get_content_pack(pack_id)
    if not pack: flash("Study pack is not installed.","error"); return redirect("/study-packs")
    try: data=load_content_pack_image_dataset(pack_id,dataset_id)
    except Exception as exc: flash(f"Unable to load image dataset: {exc}","error"); return redirect("/study-packs")
    runtime_questions=[]; db_questions=[]; qnum=1
    for image in data.get("images") or []:
        image_url=url_for("content_pack_asset",pack_id=pack_id,asset_path=image.get("file")); source=image.get("source") or data.get("source") or {}; hotspots=list(image.get("hotspots") or []); random.shuffle(hotspots)
        for hotspot in hotspots:
            label=str(hotspot.get("label") or "").strip()
            if not label: continue
            prompt=str(hotspot.get("prompt") or f"Identify {label}.").strip()
            runtime_questions.append({"number":qnum,"type":"hotspot","question":prompt,"image_url":image_url,"image_alt":image.get("alt_text") or data.get("title") or "Study image","image_edits":image.get("edits") or [],"target":hotspot.get("shape") or {},"target_label":label,"explanation":hotspot.get("explanation") or "","verification":hotspot.get("verification") or {},"image_source":{"organization":source.get("organization") or "","work":source.get("work") or "","url":source.get("url") or image.get("source_url") or "","license":source.get("license") or image.get("license") or "","attribution":source.get("attribution") or image.get("attribution") or ""}})
            db_questions.append({"number":qnum,"type":"choice","question":prompt+" [Image hotspot]","choices":[{"label":"A","text":label,"is_correct":True}],"source":{"organization":source.get("organization") or "","dataset":data.get("title") or dataset_id,"version":pack.get("version") or "","url":source.get("url") or image.get("source_url") or "","license":source.get("license") or image.get("license") or ""}}); qnum+=1
    if not runtime_questions: flash("This image dataset contains no usable targets.","error"); return redirect("/study-packs")
    title=str(data.get("title") or data["_descriptor"].get("title") or "Image Study").strip(); quiz_title=f"{title} — Image Practice"; ts=int(time.time()); safe_pack=re.sub(r"[^a-z0-9]+","_",pack_id).strip("_") or "study"; safe_id=re.sub(r"[^a-z0-9]+","_",dataset_id.lower()).strip("_") or "images"; html_name=f"study_image_{safe_pack}_{safe_id}_{ts}.html"; json_name=f"study_image_{safe_pack}_{safe_id}_{ts}.json"; json_path=os.path.join(DATA_FOLDER,json_name); html_path=os.path.join(QUIZ_FOLDER,html_name)
    bucket=re.sub(r"[^A-Za-z0-9_.-]+","_",os.path.splitext(html_name)[0])[:120]
    runtime_questions,db_questions,_=_snapshot_runtime_questions(pack_id,runtime_questions,db_questions,bucket)
    with open(json_path,"w",encoding="utf-8") as f: json.dump(runtime_questions,f,indent=4,ensure_ascii=False)
    quiz_id=save_quiz_to_db(quiz_title,html_name,db_questions); add_quiz_to_registry(quiz_id=quiz_id,html=html_name,title=quiz_title,logo=None,exam_minutes=90,source_pack_id=pack_id,source_dataset_id=dataset_id); build_quiz_html(html_name,json_name,html_path,get_portal_title(),quiz_title,None,quiz_id,90)
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
            requested.append("Create one or more high-quality matching datasets with concise answers and source-supported Study Mode explanations.")
        if include_images:
            requested.append("Create image/diagram hotspot datasets when they genuinely improve learning, following the image count and style request below.")
        if not requested:
            requested.append("Choose the most appropriate DLMS study content types for this topic.")

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
            generated_prompt = (
                DEFAULT_STUDY_CONTENT_PACK_PROMPT
                .replace("{{domain}}", domain)
                .replace("{{domain_slug}}", domain_slug)
                .replace("{{topic}}", topic)
                .replace("{{content_request}}", "\\n".join(f"- {x}" for x in requested))
                .replace("{{difficulty}}", difficulty)
                .replace("{{size_guidance}}", size_map.get(size, size_map["Standard"]))
                .replace("{{image_guidance}}", image_guidance)
            )
            if domain == "Medical":
                generated_prompt += r"""

MEDICAL-SPECIFIC SAFETY AND SOURCE REQUIREMENTS
- Treat this as educational medical study content only.
- Prefer authoritative medical/OER/government sources and exact source-verified terminology.
- Do not invent clinical facts, diagnostic claims, citations, licenses, structures, or image provenance.
- Do not use synthetic or AI-generated anatomy, histology, pathology, radiology, or microscopy images as authoritative identification material.
- Use only exact legally redistributable medical images with source/license/creator attribution documented at image level.
- Keep concise matching definitions separate from richer Study Mode explanations.
- Mark uncertain image hotspot geometry for DLMS Image Study Editor review rather than pretending it is calibrated.
"""
        else:
            generated_prompt = "Enter a study topic before generating the prompt."

    providers = {
        "chatgpt":"https://chatgpt.com/",
        "claude":"https://claude.ai/",
        "gemini":"https://gemini.google.com/",
        "local":str(cfg.get("ai_custom_url") or "").strip()
    }
    ai_url = providers.get(ai_provider,"")
    back_url = "/medical" if from_section == "medical" or domain == "Medical" else "/study-packs"
    back_label = "Medical Study" if back_url == "/medical" else "Study Packs"

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
        <button class="dashboard-menu-button" id="menuButton" type="button">☰</button>
        <div>
            <div class="medical-eyebrow">ANY SUBJECT · CUSTOM CONTENT</div>
            <h1>AI Study Pack Builder</h1>
            <p>One domain-aware builder creates controlled DLMS-ready content-pack prompts for medical, IT, science, history, and other study subjects.</p>
        </div>
    </header>

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
            {% if ai_url %}<button type="button" class="medical-primary-button" onclick="copyAndOpen('{{ ai_url }}')">Copy Prompt &amp; Open AI</button>{% endif %}
            <button type="button" class="medical-ai-secondary-button" onclick="copyPrompt()">Copy Prompt</button>
        </div>
    </section>
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
        <div class="dashboard-sidebar-version">Law Study</div>
    </aside>

    <main class="dashboard-main law-hub-main">
        <header class="dashboard-header law-hub-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
                <div><span class="law-hub-card-kicker">ARCHIVE</span><h2>Saved Imports</h2><p>Open raw AI-generated packets retained for future parsing.</p></div>
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
            law_registry["pending_case_workflow"] = {
                "case_name": case_name,
                "case_slug": case_slug,
                "course": course,
                "created_at": datetime.now().isoformat(timespec="seconds")
            }
            save_law_registry(law_registry)

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
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
                <button type="button" class="law-primary-action" onclick="copyPromptAndOpenAi('{{ ai_provider_url }}')">Copy Prompt &amp; Open AI</button>
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
    """
    Create a safe, readable slug from a case name for filenames.
    Example: Hadley v. Baxendale -> hadley_v_baxendale
    """
    slug = str(case_name or "").strip().lower()

    # Normalize common case-name punctuation/spacing
    slug = slug.replace(" v. ", " v ")
    slug = slug.replace(" vs. ", " v ")
    slug = slug.replace(" versus ", " v ")

    # Keep only letters, numbers, and underscores
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")

    return slug[:80] or "untitled_case"


def extract_law_slug_from_import_filename(filename):
    """
    Extract the case slug from a raw Law import filename.

    Example:
    law_import_20260510_133709_hadley_v_baxendale.txt
    -> hadley_v_baxendale
    """
    name = secure_filename(filename or "")
    base = os.path.splitext(name)[0]

    match = re.match(r"^law_import_\d{8}_\d{6}_(.+)$", base)

    if match:
        slug = match.group(1).strip("_")
        return slug[:80] or ""

    return ""






def safe_law_import_filename(filename):
    """
    Restrict Law import filenames to saved .txt files in LAW_IMPORTS_FOLDER.
    Prevents path traversal.
    """
    filename = secure_filename(filename or "")

    if not filename.lower().endswith(".txt"):
        return ""

    return filename



def parse_law_packet_sections(raw_text):
    """
    Lightweight parser for previewing DLMS Law Study import sections.
    Does not save anything. It only splits recognized headings.
    """
    headings = [
        ("sources_used", "Sources Used"),
        ("case_brief", "1. Case Brief"),
        ("socratic_review", "2. Socratic Review"),
        ("socratic_answer_key", "2A. Socratic Answer Key"),
        ("irac_drill", "3. IRAC Drill"),
        ("rule_flashcards", "4. Rule Flashcards"),
    ]

    found = []

    for key, title in headings:
        pattern = re.compile(rf"(?im)^\s*{re.escape(title)}\s*$")
        match = pattern.search(raw_text)

        if match:
            found.append({
                "key": key,
                "title": title,
                "start": match.start(),
                "end": match.end()
            })

    found.sort(key=lambda x: x["start"])

    sections = []

    for idx, item in enumerate(found):
        content_start = item["end"]
        content_end = found[idx + 1]["start"] if idx + 1 < len(found) else len(raw_text)
        content = raw_text[content_start:content_end].strip()

        sections.append({
            "key": item["key"],
            "title": item["title"],
            "content": content,
            "char_count": len(content),
            "line_count": len(content.splitlines()) if content else 0
        })

    return sections


def extract_law_case_title(raw_text, fallback_filename="Untitled Case Review"):
    """
    Best-effort title extraction from a Law Study import packet.
    """
    patterns = [
        r"(?im)^\s*Full case name and citation\s*:\s*(.+)$",
        r"(?im)^\s*Case\s*:\s*(.+)$",
        r"(?im)^\s*Case Name\s*:\s*(.+)$",
        r"(?im)^\s*#\s*(.+)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw_text)
        if match:
            title = match.group(1).strip()
            if title:
                return title[:160]

    name = os.path.splitext(fallback_filename)[0]
    name = name.replace("law_import_", "Case Review ")
    name = name.replace("_", " ")
    return name.strip() or "Untitled Case Review"



def get_law_case_by_id(case_id):
    """
    Look up a Law Study case review by ID from law.json.
    Returns the registry entry or None.
    """
    case_id = str(case_id or "").strip()

    if not case_id:
        return None

    registry = load_law_registry()

    for case in registry.get("cases", []):
        if str(case.get("id")) == case_id:
            return case

    return None


def parse_socratic_questions(socratic_text):
    """
    Best-effort parser for Socratic questions.
    Supports common AI formats:
    - 1. Question text
    - 1) Question text
    - Q1. Question text
    - Question 1: Question text
    - 1. **Question text**
    """
    questions = []

    if not socratic_text:
        return questions

    text = socratic_text.strip()

    # Match numbered question blocks.
    # Captures:
    # 1. Question text
    # 1) Question text
    # Q1. Question text
    # Q1) Question text
    # Question 1: Question text
    pattern = re.compile(
        r"""(?imsx)
        ^\s*
        (?:
            Question\s+(\d+)\s*[:\.\)]      # Question 1:
            |
            Q?(\d+)\s*[\.\)]                # 1. / 1) / Q1.
        )
        \s+
        (.*?)
        (?=
            ^\s*(?:Question\s+\d+\s*[:\.\)]|Q?\d+\s*[\.\)])\s+
            |
            \Z
        )
        """
    )

    for match in pattern.finditer(text):
        number = match.group(1) or match.group(2)
        question_text = match.group(3).strip()

        # Clean common markdown wrapping.
        question_text = re.sub(r"^\*+", "", question_text).strip()
        question_text = re.sub(r"\*+$", "", question_text).strip()

        if number and question_text:
            questions.append({
                "id": f"q{number}",
                "number": number,
                "text": question_text
            })

    # Fallback: detect bullet questions if no numbered questions were found.
    # Example:
    # - What fact mattered most to the court?
    if not questions:
        bullet_pattern = re.compile(r"(?im)^\s*[-*]\s+(.+\?)\s*$")

        for idx, match in enumerate(bullet_pattern.finditer(text), start=1):
            question_text = match.group(1).strip()

            if question_text:
                questions.append({
                    "id": f"q{idx}",
                    "number": str(idx),
                    "text": question_text
                })

    return questions



# =========================
# LAW STUDY MODULE - CANCEL PENDING WORKFLOW
# =========================
@app.route("/law/workflow/cancel", methods=["POST"])
def law_cancel_pending_workflow():
    registry = load_law_registry()

    if "pending_case_workflow" in registry:
        registry.pop("pending_case_workflow", None)
        save_law_registry(registry)

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

            if action == "save_raw":
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")

                if case_slug:
                    saved_file = f"law_import_{ts}_{case_slug}.txt"
                else:
                    saved_file = f"law_import_{ts}.txt"

                save_path = os.path.join(LAW_IMPORTS_FOLDER, saved_file)

                try:
                    os.makedirs(LAW_IMPORTS_FOLDER, exist_ok=True)

                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(raw_packet)

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
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
                <button type="submit" name="action" value="preview" class="law-primary-action">Preview Packet</button>
                <button type="submit" name="action" value="save_raw" class="law-secondary-action">Save Raw Packet</button>
                <button type="button" class="law-secondary-action" onclick="location.href='/law/imports'">Saved Imports</button>
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
        os.makedirs(LAW_IMPORTS_FOLDER, exist_ok=True)

        for name in sorted(os.listdir(LAW_IMPORTS_FOLDER), reverse=True):
            if not name.lower().endswith(".txt"):
                continue

            path = os.path.join(LAW_IMPORTS_FOLDER, name)

            if not os.path.isfile(path):
                continue

            stat = os.stat(path)

            imports.append({
                "filename": name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            })

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
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
        with open(import_path, "r", encoding="utf-8") as f:
            raw_packet = f.read()
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
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
        if os.path.exists(import_path) and os.path.isfile(import_path):
            os.remove(import_path)

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
        with open(import_path, "r", encoding="utf-8") as f:
            raw_packet = f.read()
    except Exception as e:
        print(f"[LAW CASE ERROR] Failed reading import: {e}")
        return "Failed to read saved import", 500

    parsed_sections = parse_law_packet_sections(raw_packet)

    if not parsed_sections:
        return "No recognized Law Study sections were found. Cannot create case review yet.", 400

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    case_slug = extract_law_slug_from_import_filename(safe_name)

    if case_slug:
        case_id = f"law_case_{ts}_{case_slug}"
    else:
        case_id = f"law_case_{ts}"

    case_file = f"{case_id}.json"
    case_path = os.path.join(LAW_CASES_FOLDER, case_file)

    section_map = {
        section["key"]: section["content"]
        for section in parsed_sections
    }

    title = extract_law_case_title(raw_packet, safe_name)
    course = "Uncategorized"

    registry = load_law_registry()
    pending_workflow = registry.get("pending_case_workflow", {}) or {}

    pending_slug = str(pending_workflow.get("case_slug", "")).strip()
    pending_case_name = str(pending_workflow.get("case_name", "")).strip()
    pending_course = str(pending_workflow.get("course", "")).strip()

    if case_slug and pending_slug and case_slug == pending_slug:
        if pending_case_name:
            title = pending_case_name

        if pending_course:
            course = pending_course

    case_data = {
        "id": case_id,
        "type": "law_case_review",
        "title": title,
        "course": course,
        "source_import": safe_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "verified": False,
        "sources_used": section_map.get("sources_used", ""),
        "sections": {
            "case_brief": section_map.get("case_brief", ""),
            "socratic_review": section_map.get("socratic_review", ""),
            "socratic_answer_key": section_map.get("socratic_answer_key", ""),
            "irac_drill": section_map.get("irac_drill", ""),
            "rule_flashcards": section_map.get("rule_flashcards", "")
        },
        "student_notes": ""
    }

    try:
        os.makedirs(LAW_CASES_FOLDER, exist_ok=True)

        with open(case_path, "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2)

        cases = registry.get("cases", [])

        cases.append({
            "id": case_id,
            "title": title,
            "course": course,
            "file": case_file,
            "source_import": safe_name,
            "created_at": case_data["created_at"],
            "updated_at": case_data["updated_at"],
            "hidden": False
        })

        registry["cases"] = cases

        # Clear completed pending workflow so a future unrelated import
        # does not accidentally reuse the previous case name/slug/course.
        if "pending_case_workflow" in registry:
            registry.pop("pending_case_workflow", None)

        save_law_registry(registry)

    except Exception as e:
        print(f"[LAW CASE ERROR] Failed creating case review: {e}")
        return "Failed to create case review", 500

    return redirect(f"/law/imports/{safe_name}?created_case={case_id}")



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
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
        with open(case_path, "r", encoding="utf-8") as f:
            case_data = json.load(f) or {}
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
        <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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

    if not new_title:
        new_title = case_entry.get("title") or "Untitled Case Review"

    if not new_course:
        new_course = "Uncategorized"

    try:
        with open(case_path, "r", encoding="utf-8") as f:
            case_data = json.load(f) or {}

        now = datetime.now().isoformat(timespec="seconds")

        case_data["title"] = new_title
        case_data["course"] = new_course
        case_data["updated_at"] = now

        with open(case_path, "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2)

        registry = load_law_registry()

        for case in registry.get("cases", []):
            if str(case.get("id")) == str(case_id):
                case["title"] = new_title
                case["course"] = new_course
                case["updated_at"] = now
                break

        save_law_registry(registry)

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
        # Remove case JSON file
        if os.path.exists(case_path) and os.path.isfile(case_path):
            os.remove(case_path)

        # Remove case from registry
        registry = load_law_registry()

        remaining_cases = [
            case for case in registry.get("cases", [])
            if str(case.get("id")) != str(case_id)
        ]

        registry["cases"] = remaining_cases
        save_law_registry(registry)

    except Exception as e:
        print(f"[LAW CASE ERROR] Failed deleting case review: {e}")
        return "Failed to delete case review", 500

    return redirect("/law/cases?deleted=1")





@app.route("/data/<path:filename>")
def serve_data(filename):
    return send_from_directory(DATA_FOLDER, filename)


@app.route("/quizzes/<path:filename>")
def serve_quiz(filename):
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
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
        with open(case_path, "r", encoding="utf-8") as f:
            case_data = json.load(f) or {}

        now = datetime.now().isoformat(timespec="seconds")

        case_data["student_notes"] = student_notes
        case_data["updated_at"] = now

        with open(case_path, "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2)

        registry = load_law_registry()

        for case in registry.get("cases", []):
            if str(case.get("id")) == str(case_id):
                case["updated_at"] = now
                break

        save_law_registry(registry)

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
        with open(case_path, "r", encoding="utf-8") as f:
            case_data = json.load(f) or {}

        sections = case_data.get("sections", {}) or {}
        socratic_questions = parse_socratic_questions(sections.get("socratic_review", ""))

        answers = {}

        for question in socratic_questions:
            qid = question.get("id")
            if not qid:
                continue

            answers[qid] = request.form.get(f"answer_{qid}", "").strip()

        now = datetime.now().isoformat(timespec="seconds")

        case_data["socratic_student_answers"] = answers
        case_data["updated_at"] = now

        with open(case_path, "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2)

        registry = load_law_registry()

        for case in registry.get("cases", []):
            if str(case.get("id")) == str(case_id):
                case["updated_at"] = now
                break

        save_law_registry(registry)

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
        with open(case_path, "r", encoding="utf-8") as f:
            case_data = json.load(f) or {}

        now = datetime.now().isoformat(timespec="seconds")

        case_data["irac_student_response"] = irac_response
        case_data["updated_at"] = now

        with open(case_path, "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2)

        registry = load_law_registry()

        for case in registry.get("cases", []):
            if str(case.get("id")) == str(case_id):
                case["updated_at"] = now
                break

        save_law_registry(registry)

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
        with open(case_path, "r", encoding="utf-8") as f:
            case_data = json.load(f) or {}
    except Exception as e:
        print(f"[LAW CASE ERROR] Failed exporting case review: {e}")
        return "Failed to export case review", 500

    sections = case_data.get("sections", {}) or {}

    exported_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    title = case_data.get("title") or "Untitled Case Review"
    course = case_data.get("course") or "Uncategorized"
    source_import = case_data.get("source_import") or ""
    created_at = case_data.get("created_at") or ""
    updated_at = case_data.get("updated_at") or ""

    lines = []

    lines.append("# DLMS Law Case Review Export")
    lines.append(f"# Exported from DLMS v{APP_VERSION}")
    lines.append(f"# Exported on: {exported_on}")
    lines.append("# Format: DLMS Law Study text")
    lines.append("")

    lines.append("=" * 60)
    lines.append(f"CASE REVIEW: {title}")
    lines.append(f"COURSE: {course}")
    lines.append(f"SOURCE IMPORT: {source_import}")
    lines.append(f"CREATED: {created_at}")
    lines.append(f"UPDATED: {updated_at}")
    lines.append("=" * 60)
    lines.append("")

    section_order = [
        ("1. Case Brief", sections.get("case_brief", "")),
        ("2. Socratic Review", sections.get("socratic_review", "")),
        ("2A. Socratic Answer Key", sections.get("socratic_answer_key", "")),
        ("3. IRAC Drill", sections.get("irac_drill", "")),
        ("4. Rule Flashcards", sections.get("rule_flashcards", "")),
    ]

    for heading, content in section_order:
        if not content:
            continue

        lines.append(heading)
        lines.append("-" * len(heading))
        lines.append(content.strip())
        lines.append("")
        lines.append("")

    student_notes = case_data.get("student_notes", "")

    if student_notes:
        lines.append("Student Notes")
        lines.append("-------------")
        lines.append(student_notes.strip())
        lines.append("")
        lines.append("")

    lines.append("Verification Reminder")
    lines.append("---------------------")
    lines.append("Verify citations, holdings, quotations, and procedural history against the original opinion or an approved legal research source.")
    lines.append("")

    export_text = "\n".join(lines)

    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_")

    if not safe_title:
        safe_title = case_id

    filename = f"dlms_law_case_{safe_title}.txt"

    return Response(
        export_text,
        mimetype="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )





def rebuild_quiz_json_from_db(quiz_id):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    registry = load_registry()
    quiz_entry = next((q for q in registry if q.get("id") == quiz_id), None)

    if not quiz_entry or not quiz_entry.get("html"):
        conn.close()
        print("[EDIT] Could not find quiz registry entry for JSON rebuild:", quiz_id)
        return False

    json_name = quiz_entry["html"].replace(".html", ".json")
    json_path = os.path.join(DATA_FOLDER, json_name)

    questions = cur.execute(
        """
        SELECT id, question_number, question_text,
               COALESCE(question_type, 'choice') AS question_type,
               matching_round_size,
               COALESCE(matching_direction, 'term_to_definition') AS matching_direction,
               COALESCE(explanation, '') AS explanation,
               COALESCE(media_json, '{}') AS media_json,
               source_organization, source_dataset, source_version, source_url, source_license
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number, id
        """,
        (quiz_id,)
    ).fetchall()

    quiz_data = []

    for q in questions:
        if q["question_type"] == "matching":
            pairs = cur.execute(
                """
                SELECT left_text, right_text, category, explanation, verification_json
                FROM matching_pairs
                WHERE question_id = ?
                ORDER BY pair_order, id
                """,
                (q["id"],)
            ).fetchall()
            item = {
                "number": q["question_number"],
                "type": "matching",
                "question": q["question_text"],
                "pairs": [
                    {
                        "left": pair["left_text"],
                        "right": pair["right_text"],
                        "category": pair["category"] or "",
                        "explanation": pair["explanation"] or "",
                        "verification": (
                            json.loads(pair["verification_json"])
                            if pair["verification_json"] else {}
                        ),
                    }
                    for pair in pairs
                ],
                "round_size": q["matching_round_size"],
                "direction": q["matching_direction"],
                "explanation": q["explanation"] or "",
            }
            try:
                media = json.loads(q["media_json"] or "{}")
            except Exception:
                media = {}
            if isinstance(media, dict):
                item.update(media)
            source = {
                "organization": q["source_organization"],
                "dataset": q["source_dataset"],
                "version": q["source_version"],
                "url": q["source_url"],
                "license": q["source_license"],
            }
            if any(source.values()):
                item["source"] = source
            quiz_data.append(item)
            continue

        choices = cur.execute(
            """
            SELECT label, text, is_correct
            FROM choices
            WHERE question_id = ?
            ORDER BY label
            """,
            (q["id"],)
        ).fetchall()

        correct_letters = [c["label"] for c in choices if c["is_correct"]]

        choice_item = {
            "number": q["question_number"],
            "type": "choice",
            "question": q["question_text"],
            "explanation": q["explanation"] or "",
            "choices": [
                {
                    "label": c["label"],
                    "text": c["text"],
                    "is_correct": bool(c["is_correct"])
                }
                for c in choices
            ],
            "correct": correct_letters
        }
        try:
            media = json.loads(q["media_json"] or "{}")
        except Exception:
            media = {}
        if isinstance(media, dict):
            choice_item.update(media)
        source = {
            "organization": q["source_organization"],
            "dataset": q["source_dataset"],
            "version": q["source_version"],
            "url": q["source_url"],
            "license": q["source_license"],
        }
        if any(source.values()):
            choice_item["source"] = source
        quiz_data.append(choice_item)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=4)

    conn.close()
    print("[EDIT] Rebuilt quiz JSON:", json_path)
    return True



def rebuild_quiz_html_from_registry(quiz_id):
    registry = load_registry()
    quiz_entry = next((q for q in registry if q.get("id") == quiz_id), None)

    if not quiz_entry or not quiz_entry.get("html"):
        print("[EDIT] Could not find quiz registry entry for HTML rebuild:", quiz_id)
        return False

    html_name = quiz_entry["html"]
    json_name = html_name.replace(".html", ".json")

    html_path = os.path.join(QUIZ_FOLDER, html_name)

    build_quiz_html(
        html_name,
        json_name,
        html_path,
        get_portal_title(),
        quiz_entry.get("title") or "Edited Quiz",
        quiz_entry.get("logo"),
        quiz_id,
        quiz_entry.get("exam_minutes", 90)
    )

    print("[EDIT] Rebuilt quiz HTML:", html_path)
    return True


@app.route("/admin/rebuild_all_quiz_html")
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
@app.route("/edit_quiz/<int:quiz_id>", methods=["POST"])
def save_edited_quiz(quiz_id):
    conn = get_db()
    cur = conn.cursor()

    action = request.form.get("action", "")

    ts = int(time.time())

    quiz_logo = request.files.get("quiz_logo")

    logo_filename = finalize_logo_from_request(
        app,
        ts,
        logo_file=quiz_logo
    )

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

        with registry_lock:
            registry = load_registry()

            for q in registry:
                if q.get("id") == quiz_id:
                    q["title"] = new_title

                    if logo_filename:
                        q["logo"] = logo_filename

                    break

            save_registry(registry)

    # Save per-quiz Exam Mode duration independently of the SQLite schema.
    with registry_lock:
        registry = load_registry()
        for q in registry:
            if str(q.get("id")) == str(quiz_id):
                q["exam_minutes"] = exam_minutes
                break
        save_registry(registry)

    questions = cur.execute(
        "SELECT id, COALESCE(question_type, 'choice') FROM questions WHERE quiz_id = ?",
        (quiz_id,)
    ).fetchall()

    for q in questions:
        question_id = q[0]
        question_type = q[1]
        new_question_text = request.form.get(f"question_{question_id}", "").strip()
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
                "UPDATE questions SET question_text = ?, matching_round_size = ?, matching_direction = ? WHERE id = ?",
                (new_question_text, round_size, direction, question_id)
            )
        else:
            cur.execute(
                "UPDATE questions SET question_text = ? WHERE id = ?",
                (new_question_text, question_id)
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

        conn.commit()
        conn.close()

        rebuild_quiz_json_from_db(quiz_id)
        rebuild_quiz_html_from_registry(quiz_id)

        return redirect(f"/edit_quiz/{quiz_id}")

    # =========================
    # ADD PAIR TO MATCHING QUESTION
    # =========================
    if action.startswith("add_match_pair_"):
        try:
            question_id = int(action.replace("add_match_pair_", "", 1))
        except ValueError:
            conn.rollback(); conn.close()
            flash("Invalid matching question.", "error")
            return redirect(f"/edit_quiz/{quiz_id}")

        row = cur.execute("SELECT MAX(pair_order) FROM matching_pairs WHERE question_id = ?", (question_id,)).fetchone()
        next_order = (row[0] or 0) + 1
        cur.execute(
            "INSERT INTO matching_pairs(question_id, pair_order, left_text, right_text) VALUES (?, ?, ?, ?)",
            (question_id, next_order, "New term", "New match")
        )
        conn.commit(); conn.close()
        rebuild_quiz_json_from_db(quiz_id)
        rebuild_quiz_html_from_registry(quiz_id)
        return redirect(f"/edit_quiz/{quiz_id}")

    # =========================
    # ADD CHOICES TO EXISTING QUESTION
    # =========================
    if action.startswith("add_choices_"):
        try:
            question_id = int(action.replace("add_choices_", "", 1))
        except ValueError:
            conn.rollback()
            conn.close()
            flash("Invalid question selected for adding choices.", "error")
            return redirect(f"/edit_quiz/{quiz_id}")

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

        conn.commit()
        conn.close()

        rebuild_quiz_json_from_db(quiz_id)
        rebuild_quiz_html_from_registry(quiz_id)

        return redirect(f"/edit_quiz/{quiz_id}")

    # =========================
    # VALIDATION: each question must have at least one correct answer
    # =========================
    questions = cur.execute(
        """
        SELECT id, question_number, COALESCE(question_type, 'choice') AS question_type
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number
        """,
        (quiz_id,)
    ).fetchall()

    for q in questions:
        if q["question_type"] == "matching":
            pair_rows = cur.execute(
                "SELECT left_text, right_text FROM matching_pairs WHERE question_id = ?",
                (q["id"],)
            ).fetchall()
            if len(pair_rows) < 2 or any(not (r[0] or "").strip() or not (r[1] or "").strip() for r in pair_rows):
                conn.rollback(); conn.close()
                flash(f"Question {q['question_number']} must have at least two complete matching pairs.", "error")
                return redirect(url_for("edit_quiz", quiz_id=quiz_id))
            continue

        correct_count = cur.execute(
            "SELECT COUNT(*) FROM choices WHERE question_id = ? AND is_correct = 1",
            (q["id"],)
        ).fetchone()[0]
        if correct_count == 0:
            conn.rollback(); conn.close()
            flash(f"Question {q['question_number']} must have at least one correct answer.", "error")
            return redirect(url_for("edit_quiz", quiz_id=quiz_id))

    conn.commit()
    conn.close()

    rebuild_quiz_json_from_db(quiz_id)
    rebuild_quiz_html_from_registry(quiz_id)

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

    conn.commit()
    conn.close()

    rebuild_quiz_json_from_db(quiz_id)
    rebuild_quiz_html_from_registry(quiz_id)

    return redirect(f"/edit_quiz/{quiz_id}")


# =========================
# ADD CHOICES TO QUESTION
# =========================
@app.route("/add_choices/<int:quiz_id>/<int:question_id>", methods=["POST"])
def add_choices_to_question(quiz_id, question_id):
    conn = get_db()
    cur = conn.cursor()

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

    conn.commit()
    conn.close()

    rebuild_quiz_json_from_db(quiz_id)
    rebuild_quiz_html_from_registry(quiz_id)

    return redirect(f"/edit_quiz/{quiz_id}")



# =========================
# DELETE CHOICE FROM QUESTION
# =========================
@app.route("/delete_choice/<int:quiz_id>/<int:choice_id>", methods=["POST"])
def delete_choice_from_question(quiz_id, choice_id):
    conn = get_db()
    cur = conn.cursor()

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

    conn.commit()
    conn.close()

    rebuild_quiz_json_from_db(quiz_id)
    rebuild_quiz_html_from_registry(quiz_id)

    return redirect(f"/edit_quiz/{quiz_id}")


# =========================
# DELETE MATCHING PAIR FROM QUESTION
# =========================
@app.route("/delete_match_pair/<int:quiz_id>/<int:pair_id>", methods=["POST"])
def delete_match_pair_from_question(quiz_id, pair_id):
    conn = get_db()
    cur = conn.cursor()
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
    conn.commit()
    conn.close()
    rebuild_quiz_json_from_db(quiz_id)
    rebuild_quiz_html_from_registry(quiz_id)
    return redirect(f"/edit_quiz/{quiz_id}")


# =========================
# DELETE QUIZ (AUTHORITATIVE)
# =========================
@app.route("/delete_quiz/<int:quiz_id>", methods=["POST"])
def delete_quiz(quiz_id):
    print("[DELETE] Requested quiz_id:", quiz_id)

    # -------------------------
    # Load registry FIRST
    # -------------------------
    with registry_lock:
        registry = load_registry()
        kept = []

        html_file = None
        json_file = None
        logo_file = None

        for q in registry:
            if q.get("id") == quiz_id:
                print("[DELETE] Removing registry entry:", q)

                html_file = q.get("html")

                if html_file:
                    json_file = html_file.replace(".html", ".json")

                logo_file = q.get("logo")
                continue

            kept.append(q)

        save_registry(kept)

    # -------------------------
    # Delete DB rows (authoritative)
    # -------------------------
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
    conn.commit()
    conn.close()

    # -------------------------
    # Delete files (best effort)
    # -------------------------
    if html_file:
        hp = os.path.join(QUIZ_FOLDER, html_file)
        if os.path.exists(hp):
            os.remove(hp)

    if json_file:
        jp = os.path.join(DATA_FOLDER, json_file)
        if os.path.exists(jp):
            os.remove(jp)

    if html_file:
        asset_bucket = os.path.splitext(os.path.basename(html_file))[0]
        asset_dir = os.path.join(QUIZ_ASSET_FOLDER, asset_bucket)
        if os.path.isdir(asset_dir):
            shutil.rmtree(asset_dir, ignore_errors=True)

    if logo_file:
        lp = os.path.join(LOGO_FOLDER, logo_file)
        if os.path.exists(lp):
            os.remove(lp)

    print("[DELETE] Completed quiz_id:", quiz_id)
    return redirect("/library")

# =========================
# WIPE DATABASE (FULL RESET)
# =========================
@app.route("/api/wipe_database", methods=["POST"])
def wipe_database():
    print("[DB] FULL FACTORY RESET REQUESTED")

    # -----------------------------
    # 1️⃣ WIPE DATABASE COMPLETELY
    # -----------------------------
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = OFF")
    cur = conn.cursor()

    cur.executescript("""
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

    print("[DB] Database tables cleared and IDs reset")

    # -----------------------------
    # 2️⃣ CLEAR QUIZ REGISTRY
    # -----------------------------

    try:
        save_registry([])
        print("[REGISTRY] quizzes.json reset")
    except Exception as e:
        print("[REGISTRY ERROR]", e)
        return jsonify(status="error", error="Failed to reset quiz registry"), 500

    # -----------------------------
    # 3️⃣ DELETE GENERATED QUIZ FILES
    # -----------------------------
    quiz_dirs = [
        os.path.join(APP_DATA_DIR, "quizzes"),
        QUIZ_ASSET_FOLDER,
        os.path.join(APP_DATA_DIR, "static", "logos"),
        os.path.join(APP_DATA_DIR, "static", "logos", "_temp"),
    ]

    for d in quiz_dirs:
        if os.path.exists(d):
            for name in os.listdir(d):
                path = os.path.join(d, name)
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path)
                except Exception as e:
                    print(f"[FILE DELETE ERROR] {path}", e)
                    return jsonify(status="error", error=f"Failed deleting {path}"), 500

    print("[FILES] All quiz files and logos removed")

    print("[FACTORY RESET] COMPLETE")

    return jsonify(status="ok")




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
def save_quiz_to_db(quiz_title, source_file, quiz_data, logo_filename=None):
    conn = get_db()
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
                json.dumps(q.get("media") or {
                    key: q.get(key)
                    for key in ("image_url", "image_alt", "image_edits", "image_source")
                    if q.get(key) is not None
                }, ensure_ascii=False),
            ),
        )

        question_id = cur.lastrowid

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

    conn.commit()
    conn.close()

    return quiz_id  # ✅ REQUIRED FOR REGISTRY + DELETE



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
# Backend routes and quiz/folder behaviors remain unchanged. This block
# modernizes presentation while preserving existing forms and APIs.
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

    if view == "hidden":
        filtered = [q for q in registry if q.get("hidden", False)]
    elif view == "all":
        filtered = registry
    else:
        view = "visible"
        filtered = [q for q in registry if not q.get("hidden", False)]

    quizzes = [
        {**q, "logo": resolve_logo_filename(q.get("logo"))}
        for q in filtered
    ]

    folder_names = get_quiz_folders()
    grouped_quizzes = {folder: [] for folder in folder_names}

    for q in quizzes:
        folder = str(q.get("folder") or "Uncategorized").strip() or "Uncategorized"
        if folder not in grouped_quizzes:
            grouped_quizzes[folder] = []
        grouped_quizzes[folder].append(q)

    registry_folder_names = sorted({
        str(q.get("folder") or "Uncategorized").strip() or "Uncategorized"
        for q in registry
    })

    for folder in registry_folder_names:
        if folder not in folder_names:
            folder_names.append(folder)
            grouped_quizzes[folder] = []

    # Only render folders that contain quizzes in the selected view.
    # Keep folder_names complete so Create/Move/Rename logic still has access
    # to every configured folder, including currently empty folders.
    display_folder_names = [
        folder for folder in folder_names
        if grouped_quizzes.get(folder)
    ]

    visible_count = sum(1 for q in registry if not q.get("hidden", False))
    hidden_count = sum(1 for q in registry if q.get("hidden", False))

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quiz Library - {{ portal_title }}</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.0/Sortable.min.js"></script>
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
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
            <div class="library-stat-card"><span>Folders</span><strong>{{ folder_names|length }}</strong><small>library folders</small></div>
            <div class="library-stat-card"><span>This View</span><strong>{{ quizzes|length }}</strong><small>{{ view|capitalize }} items</small></div>
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
                    <input id="librarySearch" type="search" placeholder="Search quizzes..." autocomplete="off">
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

        <div class="library-tip">Drag folder headers to reorder folders. Drag quiz cards to reorder quizzes inside a folder.</div>

        {% if quizzes %}
        <section id="quizList" class="library-folder-list">
            {% for folder_name in display_folder_names %}
            {% set folder_quizzes = grouped_quizzes.get(folder_name, []) %}
            <article class="library-folder" data-folder-name="{{ folder_name }}" data-folder-draggable="true">
                <div class="library-folder-header" onclick="toggleLibraryFolder(event, this)">
                    <div class="library-folder-title-group">
                        <span class="folder-toggle-icon">▼</span>
                        <svg class="dlms-folder-icon dlms-folder-icon-large" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                            <path d="M3.5 7.25A2.25 2.25 0 0 1 5.75 5h4.1l2 2h6.4a2.25 2.25 0 0 1 2.25 2.25v7A2.25 2.25 0 0 1 18.25 18.5H5.75A2.25 2.25 0 0 1 3.5 16.25z"/>
                        </svg>
                        <div>
                            <h2>{{ folder_name }}</h2>
                            <span class="library-folder-subtitle">{{ folder_quizzes|length }} quiz{% if folder_quizzes|length != 1 %}zes{% endif %}</span>
                        </div>
                    </div>

                    {% if folder_name|lower != "uncategorized" %}
                    <div class="library-folder-actions">
                        <div class="folder-actions">
                            <button type="button" class="library-icon-button" onclick="showRenameFolderForm(event, this)" title="Rename folder">✎</button>
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
                            <button type="submit" class="library-icon-button library-danger-icon" title="Delete folder">🗑</button>
                        </form>
                    </div>
                    {% endif %}
                </div>

                <div class="library-folder-body" data-folder-name="{{ folder_name }}">
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
                                    </div>
                                </div>
                            </div>

                            <div class="library-quiz-actions">
                                <a class="library-primary-action compact" href="/quizzes/{{ q['html'] }}">▶ Open Quiz</a>
                                <a class="library-secondary-action compact" href="/edit_quiz/{{ q['id'] }}">✎ Edit</a>
                                <a class="library-secondary-action compact" href="/export/quiz/{{ q['id'] }}.txt" title="Exports this quiz as an import-friendly DLMS text file.">⇩ Export</a>

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
                                            <option value="{{ folder }}" {% if q.get('folder', 'Uncategorized') == folder %}selected{% endif %}>{{ folder }}</option>
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
        {% else %}
        <section class="library-empty dashboard-panel">
            <div class="library-empty-icon">▤</div>
            <h2>No quizzes found</h2>
            <p>There are no quizzes in the selected {{ view }} view.</p>
            <a class="library-primary-action" href="/upload">Build a Quiz</a>
        </section>
        {% endif %}

        <section class="library-footer-actions dashboard-panel">
            <div>
                <h2>Library Tools</h2>
                <p>Create new content or export a backup/reference copy of your complete library.</p>
            </div>
            <div class="library-footer-buttons">
                <a class="library-secondary-action" href="/create_short_quiz">✎ Create Short Quiz</a>
                <a class="library-secondary-action" href="/export/all_quizzes.txt" title="Export All creates a backup/reference file. Use Export Quiz on an individual quiz for an import-friendly file.">⇩ Export All Quizzes</a>
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
    folder.classList.toggle("collapsed", collapsed);
}

function toggleLibraryFolder(event, header) {
    if (event.target.closest("form, input, button, select, textarea, a")) return;
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
            document.querySelectorAll(".library-folder").forEach(folder => {
                let visibleCards = 0;
                folder.querySelectorAll(".library-quiz-card").forEach(card => {
                    const searchableText = card.dataset.search || card.dataset.title || "";
                    const matches = !term || searchableText.includes(term);
                    card.style.display = matches ? "" : "none";
                    if (matches) visibleCards += 1;
                });
                folder.classList.toggle("library-search-empty", visibleCards === 0);
            });
        });
    }

    const folderList = document.getElementById("quizList");
    if (folderList && window.Sortable) {
        Sortable.create(folderList, {
            animation: 150,
            draggable: ".library-folder",
            handle: ".library-folder-header",
            filter: "form, input, button, select, textarea, a",
            preventOnFilter: false,
            onEnd: function() {
                const folders = [...document.querySelectorAll(".library-folder")]
                    .map(folder => folder.getAttribute("data-folder-name"))
                    .filter(Boolean);
                fetch("/save_folder_order", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ folders })
                });
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
                    const folderName = body.getAttribute("data-folder-name") || "Uncategorized";
                    const order = [...body.querySelectorAll(".quiz-card")]
                        .map(card => card.getAttribute("data-id"))
                        .filter(Boolean);
                    fetch("/save_quiz_order_in_folder", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({ folder: folderName, order: order })
                    });
                }
            });
        });
    }
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
       display_folder_names=display_folder_names, portal_title=portal_title,
       visible_count=visible_count, hidden_count=hidden_count,
       view=view, app_version=APP_VERSION)



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
    if os.path.splitext(file_path)[1].lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return "Unsupported image", 415
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
            uploaded.save(os.path.join(draft_root, filename))
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
        return f"Invalid image-builder data: {exc}", 400

    images_payload = payload.get("images") or []
    questions_payload = payload.get("questions") or []
    if not images_payload or not questions_payload:
        return "At least one image and one question are required.", 400

    ts = int(time.time())
    title_slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:60] or "Image_Study"
    pack_id = f"user_{title_slug.lower()}_{ts}"
    pack_root = os.path.join(CONTENT_PACK_FOLDER, f"DLMS_Study_{title_slug}_{ts}")
    images_root = os.path.join(pack_root, "images")
    data_root = os.path.join(pack_root, "data")
    os.makedirs(images_root, exist_ok=False)
    os.makedirs(data_root, exist_ok=True)

    try:
        image_records, image_map = [], {}
        for n, raw in enumerate(images_payload, 1):
            image_id = str(raw.get("id") or f"image_{n}").strip()
            filename = secure_filename(str(raw.get("filename") or ""))
            src = _safe_pack_child(draft_root, filename)
            if not filename or not os.path.isfile(src):
                raise FileNotFoundError(f"Draft image missing: {filename}")
            shutil.copy2(src, os.path.join(images_root, filename))
            rec = {
                "id": image_id, "file": f"images/{filename}",
                "alt_text": str(raw.get("alt_text") or raw.get("original_name") or title).strip(),
                "edits": [], "hotspots": [],
                "source": {
                    "organization": "User supplied",
                    "work": str(raw.get("original_name") or filename),
                    "attribution": source_note or "User-supplied image for personal study",
                    "license": "User-supplied; redistribution rights not asserted by DLMS",
                    "redistribution_status": "not-cleared-for-redistribution",
                },
            }
            image_records.append(rec)
            image_map[image_id] = rec

        cleaned, qnum = [], 1
        for raw in questions_payload:
            if not isinstance(raw, dict): continue
            qtype = str(raw.get("type") or "choice").strip().lower()
            question = str(raw.get("question") or "").strip()
            image_id = str(raw.get("image_id") or "").strip()
            explanation = str(raw.get("explanation") or "").strip()
            if qtype not in {"choice", "matching", "hotspot"} or not question or image_id not in image_map:
                continue

            if qtype == "matching":
                pairs = []
                for pair in raw.get("pairs") or []:
                    left = str((pair or {}).get("left") or "").strip()
                    right = str((pair or {}).get("right") or "").strip()
                    if left and right: pairs.append({"left": left, "right": right})
                if len(pairs) < 2:
                    raise ValueError(f"Question {qnum} needs at least two complete matching pairs")
                cleaned.append({"id": f"q{qnum}", "type": "matching", "question": question, "image_id": image_id, "pairs": pairs, "direction": "term_to_definition", "explanation": explanation})
            elif qtype == "hotspot":
                shape = _validate_hotspot_shape(raw.get("shape"))
                label = str(raw.get("target_label") or "").strip()
                if not label:
                    raise ValueError(f"Question {qnum} needs a hotspot target label")
                hotspot_id = f"hotspot_{qnum}"
                image_map[image_id]["hotspots"].append({
                    "id": hotspot_id, "label": label, "prompt": question,
                    "shape": shape, "explanation": explanation,
                    "calibration": {"tool": "DLMS Build from Images", "updated_at": datetime.now().isoformat(timespec="seconds")},
                })
                cleaned.append({"id": f"q{qnum}", "type": "hotspot", "question": question, "image_id": image_id, "hotspot_id": hotspot_id, "target_label": label, "explanation": explanation})
            else:
                choices = []
                for choice in raw.get("choices") or []:
                    text = str((choice or {}).get("text") or "").strip()
                    if text:
                        choices.append({"label": chr(65 + len(choices)), "text": text, "is_correct": bool((choice or {}).get("is_correct"))})
                if len(choices) < 2 or not any(c["is_correct"] for c in choices):
                    raise ValueError(f"Question {qnum} needs at least two choices and one correct answer")
                cleaned.append({"id": f"q{qnum}", "type": "choice", "question": question, "image_id": image_id, "choices": choices, "explanation": explanation})
            qnum += 1

        if not cleaned:
            raise ValueError("No usable questions were submitted")

        dataset_id = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:64] or "image_questions"
        dataset = {
            "schema_version": 1, "id": dataset_id, "title": title, "type": "quiz",
            "category": subject or "General",
            "description": description or f"User-created image-supported question set for {title}.",
            "source": {"organization": "User supplied", "dataset": title, "license": "User-supplied study material", "notes": source_note},
            "images": image_records, "questions": cleaned,
        }
        dataset_rel = f"data/{dataset_id}.json"
        with open(os.path.join(pack_root, dataset_rel), "w", encoding="utf-8") as f:
            json.dump(dataset, f, indent=2, ensure_ascii=False); f.write("\n")
        manifest = {
            "schema_version": 1, "id": pack_id, "name": title, "version": "1.0.0",
            "publisher": "DLMS user", "content_domain": subject or "General",
            "description": dataset["description"], "datasets": [], "image_datasets": [],
            "quiz_datasets": [{"id": dataset_id, "title": title, "type": "quiz", "path": dataset_rel, "description": dataset["description"]}],
            "user_supplied_assets": True, "redistribution_status": "not-cleared-for-redistribution",
        }
        with open(os.path.join(pack_root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False); f.write("\n")

        data = load_content_pack_quiz_dataset(pack_id, dataset_id)
        runtime, db_questions = _quiz_dataset_runtime(pack_id, data)
        _, html_name = _create_quiz_from_runtime(
            f"{title} — Practice", runtime, db_questions,
            filename_prefix=f"user_image_{dataset_id}",
            exam_minutes=request.form.get("exam_minutes"),
            source_pack_id=pack_id, source_dataset_id=dataset_id
        )
        shutil.rmtree(draft_root, ignore_errors=True)
        flash("Image study pack and quiz created successfully.", "success")
        return redirect(f"/quizzes/{html_name}")
    except Exception as exc:
        shutil.rmtree(pack_root, ignore_errors=True)
        return f"Unable to create image study pack: {exc}", 400


IMAGE_QUIZ_BUILDER_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Build from Images - DLMS</title><link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/favicon.ico"></head>
<body class="dashboard-home image-builder-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar"><div class="dashboard-brand"><div class="dashboard-brand-mark">▧</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div>
<nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item active" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a>{% if medical_pack_installed %}<a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a>{% endif %}</nav>
<div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a></nav><div class="dashboard-sidebar-version">Build from Images</div></aside>
<main class="dashboard-main image-builder-main"><header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="build-eyebrow">IMAGE-BASED QUIZ BUILDER</div><h1>Build from Images</h1><p>Use images exactly as they are, attach questions below them, or create clickable hotspot questions. Editing is optional.</p></div></header>

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
    value = re.sub(r"[^A-Za-z0-9_-]+", "", str(value or ""))
    return value[:80]

def _pdf_bank_path(bank_id):
    bank_id = _pdf_bank_safe_id(bank_id)
    if not bank_id:
        raise ValueError("Invalid PDF question-bank id")
    return _safe_pack_child(PDF_QUESTION_BANK_FOLDER, f"{bank_id}.json")

def _save_pdf_question_bank(bank):
    bank_id = _pdf_bank_safe_id(bank.get("id"))
    if not bank_id:
        raise ValueError("Question bank is missing an id")
    os.makedirs(PDF_QUESTION_BANK_FOLDER, exist_ok=True)
    bank["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(_pdf_bank_path(bank_id), "w", encoding="utf-8") as f:
        json.dump(bank, f, indent=2, ensure_ascii=False)

def _load_pdf_question_bank(bank_id):
    path = _pdf_bank_path(bank_id)
    if not os.path.isfile(path):
        raise FileNotFoundError("PDF question bank not found")
    with open(path, "r", encoding="utf-8") as f:
        bank = json.load(f) or {}
    if not isinstance(bank.get("questions"), list):
        raise ValueError("PDF question bank is malformed")
    return bank

def _list_pdf_question_banks():
    os.makedirs(PDF_QUESTION_BANK_FOLDER, exist_ok=True)
    banks = []
    for name in sorted(os.listdir(PDF_QUESTION_BANK_FOLDER)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(PDF_QUESTION_BANK_FOLDER, name), "r", encoding="utf-8") as f:
                bank = json.load(f) or {}
            questions = bank.get("questions") or []
            active = [q for q in questions if isinstance(q, dict) and q.get("active", True)]
            banks.append({
                "id": bank.get("id") or os.path.splitext(name)[0],
                "title": bank.get("title") or "PDF Question Bank",
                "source_name": bank.get("source_name") or "",
                "question_count": len(questions),
                "active_count": len(active),
                "used_count": len(set(bank.get("used_question_numbers") or [])),
                "generated_count": len(bank.get("generated_quizzes") or []),
                "created_at": bank.get("created_at") or "",
                "updated_at": bank.get("updated_at") or "",
            })
        except Exception as exc:
            print(f"[PDF BANKS] Skipping invalid bank {name!r}: {exc}")
    return banks

def _delete_pdf_question_bank(bank_id):
    bank = _load_pdf_question_bank(bank_id)
    path = _pdf_bank_path(bank_id)
    title = str(bank.get("title") or "PDF Question Bank").strip()
    os.remove(path)
    return title


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
    value = re.sub(r"[^A-Za-z0-9_-]+", "", str(value or ""))
    return value[:80]

def _pdf_term_bank_path(bank_id):
    bank_id = _pdf_term_bank_safe_id(bank_id)
    if not bank_id:
        raise ValueError("Invalid PDF terminology-bank id")
    return _safe_pack_child(PDF_TERMINOLOGY_BANK_FOLDER, f"{bank_id}.json")

def _save_pdf_terminology_bank(bank):
    bank_id = _pdf_term_bank_safe_id(bank.get("id"))
    if not bank_id:
        raise ValueError("Terminology bank is missing an id")
    os.makedirs(PDF_TERMINOLOGY_BANK_FOLDER, exist_ok=True)
    bank["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(_pdf_term_bank_path(bank_id), "w", encoding="utf-8") as f:
        json.dump(bank, f, indent=2, ensure_ascii=False)

def _load_pdf_terminology_bank(bank_id):
    path = _pdf_term_bank_path(bank_id)
    if not os.path.isfile(path):
        raise FileNotFoundError("PDF terminology bank not found")
    with open(path, "r", encoding="utf-8") as f:
        bank = json.load(f) or {}
    if not isinstance(bank.get("terms"), list):
        raise ValueError("PDF terminology bank is malformed")
    return bank

def _list_pdf_terminology_banks():
    os.makedirs(PDF_TERMINOLOGY_BANK_FOLDER, exist_ok=True)
    banks = []
    for name in sorted(os.listdir(PDF_TERMINOLOGY_BANK_FOLDER)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(PDF_TERMINOLOGY_BANK_FOLDER, name), "r", encoding="utf-8") as f:
                bank = json.load(f) or {}
            terms = bank.get("terms") or []
            active = [t for t in terms if isinstance(t, dict) and t.get("active", True)]
            banks.append({
                "id": bank.get("id") or os.path.splitext(name)[0],
                "kind": "terminology",
                "title": bank.get("title") or "PDF Terminology Bank",
                "source_name": bank.get("source_name") or "",
                "term_count": len(terms),
                "active_count": len(active),
                "used_count": len(set(bank.get("used_term_numbers") or [])),
                "generated_count": len(bank.get("generated_quizzes") or []),
                "created_at": bank.get("created_at") or "",
                "updated_at": bank.get("updated_at") or "",
            })
        except Exception as exc:
            print(f"[PDF TERMS] Skipping invalid bank {name!r}: {exc}")
    return banks

def _delete_pdf_terminology_bank(bank_id):
    bank = _load_pdf_terminology_bank(bank_id)
    path = _pdf_term_bank_path(bank_id)
    title = str(bank.get("title") or "PDF Terminology Bank").strip()
    os.remove(path)
    return title


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

def _pdf_import_safe_id(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "", str(value or ""))
    return value[:80]

def _pdf_import_draft_path(draft_id):
    draft_id = _pdf_import_safe_id(draft_id)
    if not draft_id:
        raise ValueError("Invalid PDF import draft id")
    return _safe_pack_child(PDF_IMPORT_DRAFT_FOLDER, f"{draft_id}.json")

def _save_pdf_import_draft(draft):
    draft_id = _pdf_import_safe_id(draft.get("id"))
    if not draft_id:
        raise ValueError("PDF import draft is missing an id")
    os.makedirs(PDF_IMPORT_DRAFT_FOLDER, exist_ok=True)
    with open(_pdf_import_draft_path(draft_id), "w", encoding="utf-8") as f:
        json.dump(draft, f, indent=2, ensure_ascii=False)

def _load_pdf_import_draft(draft_id):
    path = _pdf_import_draft_path(draft_id)
    if not os.path.isfile(path):
        raise FileNotFoundError("PDF import draft not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f) or {}

def _pdf_clean_line(line):
    line = str(line or "").replace("\u00ad", "").replace("\u200b", "")
    line = line.replace("\ufeff", "").replace("\u00a0", " ")
    line = re.sub(r"[ \t]+", " ", line).strip()
    return line

def _pdf_extract_pages(pdf_path):
    """
    Extract selectable PDF text. No OCR is performed in this MVP.

    The legacy plain-text ``lines`` representation is preserved exactly for the
    existing question-bank parser. We also collect optional font/style metadata
    for glossary PDFs. If style extraction is unavailable for a particular PDF,
    Smart PDF Import simply falls back to the existing heuristic glossary parser.
    """
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError(
            "Smart PDF Import requires the 'pypdf' package. Install project requirements and rebuild the binary."
        ) from exc

    reader = PdfReader(pdf_path)
    pages = []
    for page_number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        lines = [_pdf_clean_line(line) for line in text.splitlines()]
        page_record = {"page": page_number, "lines": [line for line in lines if line]}

        # Style metadata is additive only. The question-bank parser never reads it.
        fragments = []
        try:
            def _visitor_text(fragment_text, cm, tm, font_dict, font_size):
                cleaned = _pdf_clean_line(str(fragment_text or "").replace("\\n", " "))
                if not cleaned:
                    return
                font_name = str((font_dict or {}).get("/BaseFont") or "")
                fragments.append({
                    "text": cleaned,
                    "x": float(tm[4]) if tm and len(tm) > 4 else 0.0,
                    "y": float(tm[5]) if tm and len(tm) > 5 else 0.0,
                    "font": font_name,
                    "bold": bool(re.search(r"(?:bold|black|heavy|demi|semibold)", font_name, re.I)),
                })

            page.extract_text(visitor_text=_visitor_text)
            styled_lines = []
            for frag in fragments:
                if styled_lines and abs(float(styled_lines[-1]["y"]) - float(frag["y"])) <= 1.25:
                    styled_lines[-1]["fragments"].append(frag)
                else:
                    styled_lines.append({"y": frag["y"], "fragments": [frag]})

            normalized_styled = []
            for styled in styled_lines:
                parts = sorted(styled["fragments"], key=lambda item: float(item.get("x") or 0.0))
                text_parts = [str(item.get("text") or "").strip() for item in parts if str(item.get("text") or "").strip()]
                line_text = _pdf_clean_line(" ".join(text_parts))
                if not line_text:
                    continue
                normalized_styled.append({"text": line_text, "y": styled["y"], "fragments": parts})
            if normalized_styled:
                page_record["styled_lines"] = normalized_styled
        except Exception:
            pass

        pages.append(page_record)
    return pages

def _pdf_suppress_repeated_margins(pages):
    """
    Suppress likely repeated headers/footers/watermarks before semantic parsing.

    We intentionally do not delete arbitrary repeated body text. A line must either:
    - repeat in page margins on at least half the pages, or
    - repeat on at least half the pages and look watermark-like (short brand text,
      not question/choice/answer content).
    """
    if len(pages) < 2:
        return pages, []

    occurrences = {}
    margin_occurrences = {}
    locations = {}

    def _is_structural(line):
        return bool(re.match(
            r"^(?:question\s*#?\s*\d+|[A-Z]\.\s+|correct\s+answer:|why\s+the\s+other\s+options)",
            line,
            re.I,
        ))

    for page in pages:
        lines = page["lines"]
        margin_indexes = set(range(min(3, len(lines))))
        margin_indexes.update(range(max(0, len(lines) - 3), len(lines)))

        seen_on_page = set()
        seen_margin_on_page = set()
        for idx, line in enumerate(lines):
            if not line or _is_structural(line):
                continue
            norm = re.sub(r"\s+", " ", line).strip().casefold()
            if not norm:
                continue
            if norm not in seen_on_page:
                occurrences[norm] = occurrences.get(norm, 0) + 1
                locations.setdefault(norm, set()).add(page["page"])
                seen_on_page.add(norm)
            if idx in margin_indexes and norm not in seen_margin_on_page:
                margin_occurrences[norm] = margin_occurrences.get(norm, 0) + 1
                seen_margin_on_page.add(norm)

    threshold = max(2, (len(pages) + 1) // 2)
    repeated = set()

    for norm, count in occurrences.items():
        if count < threshold or len(locations.get(norm, ())) < threshold:
            continue

        # Strong case: repeated in page margins.
        if margin_occurrences.get(norm, 0) >= threshold:
            repeated.add(norm)
            continue

        # Watermark-like repeated brand text anywhere on the page.
        # Keep this conservative: short, no sentence punctuation, and not study prose.
        if (
            len(norm) <= 48
            and not re.search(r"[?.!,:;]", norm)
            and len(norm.split()) <= 5
            and not re.search(
                r"\b(?:question|answer|correct|incorrect|tester|application|security|penetration|which|following)\b",
                norm,
                re.I,
            )
        ):
            repeated.add(norm)

    removed = sorted({
        line
        for page in pages
        for line in page["lines"]
        if re.sub(r"\s+", " ", line).strip().casefold() in repeated
    })

    cleaned = []
    for page in pages:
        item = {
            "page": page["page"],
            "lines": [
                line for line in page["lines"]
                if re.sub(r"\s+", " ", line).strip().casefold() not in repeated
            ]
        }
        if isinstance(page.get("styled_lines"), list):
            item["styled_lines"] = [
                line for line in page["styled_lines"]
                if re.sub(r"\s+", " ", str(line.get("text") or "")).strip().casefold() not in repeated
            ]
        cleaned.append(item)
    return cleaned, removed

def _pdf_lines_to_stream(pages):
    records = []
    for page in pages:
        for line in page["lines"]:
            records.append({"page": page["page"], "text": line})
    return records

def _pdf_join_wrapped(lines):
    """Join wrapped PDF lines while preserving structural markers."""
    if not lines:
        return ""
    out = ""
    structural = re.compile(
        r"^(?:Question\s*#?\s*\d+|[A-Z]\.\s+|Correct Answer:|Why The Other Options Are Incorrect)",
        re.I,
    )
    for raw in lines:
        line = _pdf_clean_line(raw)
        if not line:
            continue
        if not out:
            out = line
            continue
        if out.endswith("-") and line[:1].islower():
            out = out[:-1] + line
        elif structural.match(line):
            out += "\n" + line
        else:
            out += " " + line
    return out.strip()

def _pdf_parse_question_chunk(number, records):
    lines = [r["text"] for r in records if r.get("text")]
    pages = sorted({int(r["page"]) for r in records if r.get("page")})
    if not lines:
        return None

    answer_idx = None
    answer_match = None
    for i, line in enumerate(lines):
        m = re.search(r"Correct\s+Answer:\s*([A-Z])(?:\s*[—–-]\s*(.*?))?\s*✅?\s*$", line, re.I)
        if m:
            answer_idx = i
            answer_match = m
            break

    choice_scan_end = answer_idx if answer_idx is not None else len(lines)
    choice_starts = []
    for i in range(choice_scan_end):
        m = re.match(r"^([A-Z])\.\s+(.+)$", lines[i])
        if m:
            choice_starts.append((i, m.group(1).upper(), m.group(2).strip()))

    # Keep a contiguous A/B/C... option run. Explanatory A./B. lines occur after the answer marker.
    choices = []
    if choice_starts:
        run = [choice_starts[0]]
        for item in choice_starts[1:]:
            prev_label = run[-1][1]
            if ord(item[1]) == ord(prev_label) + 1:
                run.append(item)
            elif len(run) < 2:
                run = [item]
            else:
                break
        if len(run) >= 2:
            for pos, (line_idx, label, first_text) in enumerate(run):
                end = run[pos + 1][0] if pos + 1 < len(run) else choice_scan_end
                extra = lines[line_idx + 1:end]
                text = _pdf_join_wrapped([first_text] + extra)
                choices.append({"label": label, "text": text})

    first_choice_index = choice_starts[0][0] if choices else choice_scan_end
    stem_lines = lines[:first_choice_index]
    question_text = _pdf_join_wrapped(stem_lines)

    correct_label = answer_match.group(1).upper() if answer_match else ""
    declared_answer_text = (answer_match.group(2) or "").strip(" ✅") if answer_match else ""

    # Some PDFs wrap the printed "Correct Answer: X — answer text" across lines.
    # Reconstruct that wrapped answer text before we decide where the explanation begins.
    answer_continuation_count = 0
    if answer_idx is not None and declared_answer_text and correct_label:
        selected_choice_text = next(
            (c["text"] for c in choices if c.get("label") == correct_label),
            "",
        )

        def _answer_cmp(value):
            return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())

        selected_norm = _answer_cmp(selected_choice_text)
        declared_norm = _answer_cmp(declared_answer_text)

        if selected_norm and declared_norm and selected_norm.startswith(declared_norm):
            candidate = declared_answer_text
            for next_line in lines[answer_idx + 1:]:
                if re.match(r"^Why The Other Options Are Incorrect", next_line, re.I):
                    break
                candidate_next = _pdf_join_wrapped([candidate, next_line])
                candidate_norm = _answer_cmp(candidate_next)

                # Consume only lines that continue to be a prefix of the already-detected
                # correct choice. This prevents explanation prose from being swallowed.
                if candidate_norm and selected_norm.startswith(candidate_norm):
                    candidate = candidate_next
                    answer_continuation_count += 1
                    if candidate_norm == selected_norm:
                        break
                else:
                    break

            declared_answer_text = candidate

    explanation = ""
    feedback = {}
    if answer_idx is not None:
        after = lines[answer_idx + 1 + answer_continuation_count:]
        why_idx = next(
            (i for i, line in enumerate(after) if re.match(r"^Why The Other Options Are Incorrect", line, re.I)),
            None,
        )
        explanation_lines = after if why_idx is None else after[:why_idx]
        explanation = _pdf_join_wrapped(explanation_lines)
        feedback_lines = [] if why_idx is None else after[why_idx + 1:]
        current = None
        buffer = []
        for line in feedback_lines:
            # PDF extraction sometimes collapses "C. A true..." into "C.A true..."
            # or "/etc" examples into "A./etc...". Accept both forms here only.
            m = re.match(r"^([A-Z])\.\s*(.+)$", line)
            if m:
                if current:
                    feedback[current] = _pdf_join_wrapped(buffer)
                current = m.group(1).upper()
                buffer = [m.group(2)]
            elif current:
                buffer.append(line)
        if current:
            feedback[current] = _pdf_join_wrapped(buffer)

    issues = []
    status = "complete"
    labels = {c["label"] for c in choices}
    if not question_text:
        issues.append("Question text was not detected.")
    if len(choices) < 2:
        issues.append("Fewer than two answer choices were detected.")
    if not correct_label:
        issues.append("A correct-answer marker was not detected.")
    elif correct_label not in labels:
        issues.append(f"Correct answer {correct_label} does not match a detected choice.")
    if declared_answer_text and correct_label in labels:
        selected = next((c["text"] for c in choices if c["label"] == correct_label), "")
        a = re.sub(r"\W+", "", selected).casefold()
        b = re.sub(r"\W+", "", declared_answer_text).casefold()
        if a and b and a != b:
            issues.append("Correct-answer text does not exactly match the selected choice; review recommended.")

    embedded_cue = re.search(
        r"""(?ix)
        \b(
            refer\s+to\s+(?:the\s+)?(?:exhibit|image|figure|diagram|screenshot|output|result)
          | review\s+(?:the\s+)?(?:exhibit|image|figure|diagram|screenshot|output|result)
          | shown\s+below
          | displayed\s+below
          | based\s+on\s+(?:the\s+)?(?:output|result|scan|report|exhibit)
          | see\s+(?:the\s+)?following\s+(?:code|command|snippet|payload|output|result|diagram|image|figure|screenshot)
          | given\s+(?:the\s+)?following\s+(?:code|command|snippet|payload|output|result|diagram|image|figure|screenshot)
          | following\s+(?:code\s+snippet|code|command|payload|output|result|diagram|image|figure|screenshot|vulnerability)
          | analyze\s+(?:the\s+)?(?:following\s+)?(?:code|command|payload|output|result|diagram|image|figure|screenshot)
        )\b
        """,
        question_text,
    )

    # Evidence that the referenced material actually survived text extraction.
    # Do not treat a mere word such as "Nmap" as proof that its output table is present.
    embedded_material_present = re.search(
        r"""(?ix)
        <\?xml
        | <!DOCTYPE
        | </?\s*script\b
        | </?\s*[a-z][a-z0-9:_-]*\b[^>]*>
        | \b(?:powershell|cmd|bash|sh|python)\b[^\n]{0,40}[>$#]
        | \b[a-z]:\\[^\s]+
        | \\\\[a-z0-9_.-]+
        | \b(?:tcp|udp)/\d+\b
        | \b\d{1,5}/(?:tcp|udp)\b
        | \b(?:open|filtered|closed)\s+(?:ssh|smtp|http|https|nfs|rpcbind|ftp|telnet)\b
        | \bSELECT\b.+\bFROM\b
        | \bcurl\b\s+\S+
        | \bnmap\b\s+-\S+
        | \bfindstr\b\s+/
        | \bpsexec(?:\.exe)?\b
        | \bsc\s+config\b
        | \bfor\s+\w+\s+in\s+
        | \bif\s+.+:
        """,
        question_text,
    )

    # Some scanner/result blocks are plain prose rather than code. If the cue is followed
    # by several distinct data-looking clauses before the actual question, treat that as
    # preserved embedded material (for example cloud scanner findings).
    if embedded_cue and not embedded_material_present:
        cue_tail = question_text[embedded_cue.end():]
        before_question = re.split(
            r"\bWhich\s+of\s+the\s+following\b|\bWhat\s+should\b|\bBased\s+on\b",
            cue_tail,
            maxsplit=1,
            flags=re.I,
        )[0]
        data_tokens = re.findall(
            r"\b(?:vulnerability|port\s+\d+|publicly\s+accessible|server-side|cross-site|storage|ssh|http|metadata|severity|issue\s+\d+)\b",
            before_question,
            re.I,
        )
        if len(data_tokens) >= 3 and len(before_question.split()) >= 12:
            embedded_material_present = True

    if embedded_cue and not embedded_material_present:
        issues.append("Prompt references embedded/code/visual content that may not be present in extracted text.")

    if issues:
        status = "review" if question_text and len(choices) >= 2 else "incomplete"

    return {
        "number": int(number),
        "question": question_text,
        "choices": choices,
        "correct": correct_label,
        "declared_answer_text": declared_answer_text,
        "explanation": explanation,
        "choice_feedback": feedback,
        "pages": pages,
        "status": status,
        "issues": issues,
        "keep": True,
    }


def _pdf_glossary_term_like(text):
    text = _pdf_clean_line(text)
    if not text or len(text) < 2 or len(text) > 120:
        return False
    if re.search(r"[.!?;:]$", text):
        return False
    if re.match(r"^(?:question|correct answer|why the other options|chapter|page)\b", text, re.I):
        return False
    words = text.split()
    if len(words) > 14:
        return False

    significant = [re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9)]+$", "", w) for w in words]
    significant = [w for w in significant if w]
    if not significant:
        return False

    titleish = 0
    for word in significant:
        raw = word.strip("()")
        if not raw:
            continue
        if raw.isupper() or raw[:1].isupper() or re.fullmatch(r"[A-Z][A-Za-z0-9+/#.-]*", raw):
            titleish += 1
    return titleish >= max(1, int(len(significant) * 0.65))

def _pdf_glossary_definition_like(text):
    text = _pdf_clean_line(text)
    if not text or len(text) < 18:
        return False
    words = text.split()
    if len(words) < 4:
        return False
    return bool(
        re.search(r"[.!?]$", text)
        or re.match(r"^(?:\(\d+\)\s*)?(?:A|An|The|Any|Evidence|Process|Method|Technique|System|Tool|Software|Hardware)\b", text)
        or re.search(r"\b(?:is|are|refers to|used to|means|describes|consists of|provides|allows|supports)\b", text, re.I)
    )

def _pdf_split_glossary_line(line):
    """
    Split a same-line 'Term Definition...' record conservatively.
    Candidate term prefixes must look heading-like and the remaining text must
    look like substantive definition prose.
    """
    line = _pdf_clean_line(line)
    words = line.split()
    if len(words) < 6:
        return None

    # Try short prefixes first so "Admissible Evidence Evidence that..." becomes
    # "Admissible Evidence" + "Evidence that..." rather than swallowing prose.
    max_prefix = min(12, len(words) - 4)
    for cut in range(1, max_prefix + 1):
        term = " ".join(words[:cut]).strip()
        definition = " ".join(words[cut:]).strip()
        if not _pdf_glossary_term_like(term):
            continue
        if not _pdf_glossary_definition_like(definition):
            continue

        # Avoid splitting multi-word terms after their first title-cased word.
        # A plausible definition normally starts with prose (A/An/The/This/etc.),
        # a numbered sense marker, or a repetition of the term's final word such
        # as "Admissible Evidence Evidence that...".
        first_token = definition.split()[0]
        first = first_token.strip("()")
        last_term = term.split()[-1].strip("()")
        prose_starters = {
            "a", "an", "the", "this", "these", "those", "it", "they", "any",
            "one", "two", "evidence", "information", "data", "software", "hardware",
            "process", "method", "technique", "system", "tool", "practice", "capability",
        }
        numbered = bool(re.fullmatch(r"\(?\d+[.)]?\)?", first_token))
        repeated_last_word = bool(first and last_term and first.casefold() == last_term.casefold())
        if not numbered and first.casefold() not in prose_starters and not repeated_last_word:
            if first[:1].isupper():
                continue
        return term, definition
    return None


def _pdf_styled_glossary_header(text):
    """Return True for common glossary running headers and A-Z section dividers."""
    text = _pdf_clean_line(text)
    return bool(
        re.fullmatch(r"(?:\d+\s+Glossary|Glossary\s+\d+)", text, re.I)
        or re.fullmatch(r"[A-Z]", text)
    )


def _pdf_style_glossary_line(line):
    """Return (term, first_definition_text) for a bold-term/regular-definition line."""
    if not isinstance(line, dict):
        return None
    text = _pdf_clean_line(line.get("text"))
    if not text or _pdf_styled_glossary_header(text):
        return None
    fragments = line.get("fragments") or []
    if not isinstance(fragments, list) or len(fragments) < 2:
        return None

    term_parts, definition_parts = [], []
    saw_regular = False
    for frag in fragments:
        frag_text = _pdf_clean_line(frag.get("text"))
        if not frag_text:
            continue
        if not saw_regular and bool(frag.get("bold")):
            term_parts.append(frag_text)
            continue
        saw_regular = True
        definition_parts.append(frag_text)

    term = _pdf_clean_line(" ".join(term_parts))
    definition = _pdf_clean_line(" ".join(definition_parts))
    if not term or not definition or len(term) > 180:
        return None
    return term, definition


def _pdf_parse_glossary_styled(pages):
    """
    Use PDF font/style information when a source reliably distinguishes bold
    glossary terms from regular definition prose. Returns None if the style
    signal is too weak, leaving the existing heuristic parser as fallback.
    """
    styled_stream = []
    styled_pages = 0
    for page in pages:
        styled_lines = page.get("styled_lines")
        if not isinstance(styled_lines, list) or not styled_lines:
            continue
        styled_pages += 1
        for line in styled_lines:
            if isinstance(line, dict):
                styled_stream.append({
                    "page": int(page.get("page") or 0),
                    "line": line,
                    "text": _pdf_clean_line(line.get("text")),
                })
    if not styled_stream or not styled_pages:
        return None

    starts = []
    for idx, rec in enumerate(styled_stream):
        parsed = _pdf_style_glossary_line(rec["line"])
        if parsed:
            starts.append((idx, parsed[0], parsed[1], rec["page"]))
    if len(starts) < 4:
        return None

    terms = []
    for pos, (start_idx, term, first_definition, start_page) in enumerate(starts):
        end_idx = starts[pos + 1][0] if pos + 1 < len(starts) else len(styled_stream)
        definition_lines = [first_definition]
        pages_used = {start_page}
        for rec in styled_stream[start_idx + 1:end_idx]:
            text = rec["text"]
            if not text or _pdf_styled_glossary_header(text):
                continue
            definition_lines.append(text)
            pages_used.add(rec["page"])
        definition = _pdf_join_wrapped(definition_lines).strip()
        issues = []
        status = "complete"
        if not definition:
            status = "incomplete"
            issues.append("No definition text was confidently associated with this term.")
        terms.append({
            "number": len(terms) + 1,
            "term": term,
            "definition": definition,
            "pages": sorted(p for p in pages_used if p),
            "status": status,
            "issues": issues,
        })

    complete = sum(1 for item in terms if item["status"] == "complete")
    if not terms or complete / max(1, len(terms)) < 0.90:
        return None
    return {
        "terms": terms,
        "summary": {
            "detected": len(terms),
            "complete": complete,
            "review": sum(1 for item in terms if item["status"] == "review"),
            "incomplete": sum(1 for item in terms if item["status"] == "incomplete"),
        },
        "parser_mode": "style-aware",
    }


def _pdf_parse_glossary(pages):
    """
    Deterministic glossary/terminology parser.

    Supported patterns:
    - standalone heading followed by definition prose
    - term and definition beginning on the same extracted line
    - definition paragraph immediately preceding a standalone term (flagged REVIEW)

    It intentionally keeps uncertain records editable instead of inventing content.
    """
    styled_result = _pdf_parse_glossary_styled(pages)
    if isinstance(styled_result, dict) and styled_result.get("terms"):
        return styled_result

    stream = _pdf_lines_to_stream(pages)
    if not stream:
        return {"terms": [], "summary": {"detected": 0, "complete": 0, "review": 0, "incomplete": 0}}

    events = []
    for idx, rec in enumerate(stream):
        text = rec["text"]
        split = _pdf_split_glossary_line(text)

        # Distinguish a real inline glossary record such as:
        #   "Access Control A process used to restrict access..."
        # from a normal definition sentence such as:
        #   "A chronological record of system activities and events."
        #
        # Looking at the whole line with _pdf_glossary_definition_like() was too
        # aggressive because valid inline glossary records naturally contain
        # definition-style prose after the term. Instead, only suppress splitting
        # when the line itself begins like ordinary definition prose.
        prose_definition_start = bool(re.match(
            r"^(?:A|An|The|Any)\s+[a-z]|"
            r"^(?:Evidence|Process|Method|Technique|System|Tool|Software|Hardware)\s+"
            r"(?:that|which|used|designed|intended|provides|allows|supports)\b",
            text,
        ))

        if split and not prose_definition_start:
            events.append({
                "index": idx,
                "page": rec["page"],
                "kind": "inline",
                "term": split[0],
                "inline_definition": split[1],
            })
        elif _pdf_glossary_term_like(text) and not _pdf_glossary_definition_like(text):
            events.append({
                "index": idx,
                "page": rec["page"],
                "kind": "standalone",
                "term": text,
                "inline_definition": "",
            })

    # Detect the less-common PDF reading order where a definition paragraph is
    # emitted immediately before its standalone bold term. Claim that tail for
    # the later term so it is not also swallowed by the previous entry.
    reverse_claims = {}
    claimed_indices = set()
    for epos, event in enumerate(events):
        if event["kind"] != "standalone":
            continue
        idx = event["index"]
        next_idx = events[epos + 1]["index"] if epos + 1 < len(events) else len(stream)
        forward = [r for r in stream[idx + 1:next_idx] if r.get("text")]
        if forward:
            continue
        prev_event_idx = events[epos - 1]["index"] if epos > 0 else -1
        j = idx - 1
        tail_indices = []
        while j > prev_event_idx and len(tail_indices) < 6:
            text = str(stream[j].get("text") or "").strip()
            if not text:
                j -= 1
                continue
            tail_indices.append(j)
            prev_j = j - 1
            if prev_j <= prev_event_idx:
                break
            prev_text = str(stream[prev_j].get("text") or "").strip()
            # A sentence-ending line before the collected tail is a reasonable
            # paragraph boundary in selectable-text glossary PDFs.
            if re.search(r"[.!?]$", prev_text):
                break
            j -= 1
        tail_indices = sorted(tail_indices)
        tail_text = _pdf_join_wrapped([stream[i]["text"] for i in tail_indices]).strip()
        if _pdf_glossary_definition_like(tail_text):
            reverse_claims[idx] = tail_indices
            claimed_indices.update(tail_indices)

    terms = []
    for epos, event in enumerate(events):
        idx = event["index"]
        next_idx = events[epos + 1]["index"] if epos + 1 < len(events) else len(stream)
        between = [
            r for i, r in enumerate(stream[idx + 1:next_idx], start=idx + 1)
            if r.get("text") and i not in claimed_indices
        ]

        definition_lines = []
        issues = []
        pages_used = {int(event["page"])}

        if event["inline_definition"]:
            definition_lines.append(event["inline_definition"])
            definition_lines.extend(r["text"] for r in between)
            pages_used.update(int(r["page"]) for r in between)
        elif between:
            definition_lines.extend(r["text"] for r in between)
            pages_used.update(int(r["page"]) for r in between)

        definition = _pdf_join_wrapped(definition_lines).strip()

        # If a standalone term has no following definition, inspect the unclaimed
        # prose immediately before it. This handles PDF reading order where the
        # definition is emitted before the bold glossary heading.
        if not definition and event["kind"] == "standalone" and idx in reverse_claims:
            tail = [stream[i] for i in reverse_claims[idx]]
            definition = _pdf_join_wrapped([r["text"] for r in tail]).strip()
            pages_used.update(int(r["page"]) for r in tail)
            issues.append("Definition appeared before the term in PDF reading order; review recommended.")

        if not definition:
            issues.append("No definition text was confidently associated with this term.")

        status = "complete" if definition and not issues else ("review" if definition else "incomplete")
        terms.append({
            "number": len(terms) + 1,
            "term": event["term"],
            "definition": definition,
            "pages": sorted(pages_used),
            "status": status,
            "issues": issues,
        })

    # Remove obvious false-positive headings and duplicate term records.
    cleaned = []
    seen = set()
    for item in terms:
        term = str(item.get("term") or "").strip()
        definition = str(item.get("definition") or "").strip()
        key = term.casefold()
        if not term or key in seen:
            continue
        if term.casefold() in {"glossary", "terms", "definitions", "index"}:
            continue
        # A useful glossary record needs either a definition or a reviewable term.
        if len(term) < 2:
            continue
        seen.add(key)
        cleaned.append(item)

    for n, item in enumerate(cleaned, 1):
        item["number"] = n

    summary = {
        "detected": len(cleaned),
        "complete": sum(1 for t in cleaned if t["status"] == "complete"),
        "review": sum(1 for t in cleaned if t["status"] == "review"),
        "incomplete": sum(1 for t in cleaned if t["status"] == "incomplete"),
    }
    return {"terms": cleaned, "summary": summary}

def _pdf_detect_document_type(pages, question_result=None, glossary_result=None):
    question_result = question_result if isinstance(question_result, dict) else _pdf_parse_question_bank(pages)
    glossary_result = glossary_result if isinstance(glossary_result, dict) else _pdf_parse_glossary(pages)

    stream = _pdf_lines_to_stream(pages)
    question_markers = sum(1 for r in stream if re.match(r"^Question\s*#?\s*\d+", r["text"], re.I))
    answer_markers = sum(1 for r in stream if re.search(r"Correct\s+Answer:", r["text"], re.I))
    q_detected = int((question_result.get("summary") or {}).get("detected") or 0)
    g_detected = int((glossary_result.get("summary") or {}).get("detected") or 0)

    # Strong structural question-bank evidence always wins.
    if question_markers >= 2 and answer_markers >= 1 and q_detected >= 2:
        return "question_bank", {
            "question_markers": question_markers,
            "answer_markers": answer_markers,
            "question_records": q_detected,
            "glossary_records": g_detected,
        }

    if g_detected >= 4:
        return "glossary", {
            "question_markers": question_markers,
            "answer_markers": answer_markers,
            "question_records": q_detected,
            "glossary_records": g_detected,
        }

    return "unknown", {
        "question_markers": question_markers,
        "answer_markers": answer_markers,
        "question_records": q_detected,
        "glossary_records": g_detected,
    }

def _pdf_parse_question_bank(pages):
    stream = _pdf_lines_to_stream(pages)
    starts = []
    for idx, record in enumerate(stream):
        m = re.match(r"^Question\s*#?\s*(\d+)\s*$", record["text"], re.I)
        if m:
            starts.append((idx, int(m.group(1))))

    questions = []
    for pos, (start_idx, number) in enumerate(starts):
        end_idx = starts[pos + 1][0] if pos + 1 < len(starts) else len(stream)
        q = _pdf_parse_question_chunk(number, stream[start_idx + 1:end_idx])
        if q:
            questions.append(q)

    complete = sum(q["status"] == "complete" for q in questions)
    review = sum(q["status"] == "review" for q in questions)
    incomplete = sum(q["status"] == "incomplete" for q in questions)
    return {
        "type": "multiple_choice_question_bank",
        "questions": questions,
        "summary": {
            "detected": len(questions),
            "complete": complete,
            "review": review,
            "incomplete": incomplete,
        }
    }

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
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="build-eyebrow">SMART PDF IMPORT</div><h1>Import Study Content from PDF</h1><p>DLMS can recognize structured question banks or glossary/terminology material, parse the full source, and let you review it before generating manageable quizzes.</p></div></header>
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
        flash(f"Could not delete PDF question bank: {exc}", "error")
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
        flash(f"Could not delete PDF terminology bank: {exc}", "error")
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

    draft_id = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:20]
    source_name = secure_filename(upload.filename) or "study.pdf"
    temp_pdf = os.path.join(PDF_IMPORT_DRAFT_FOLDER, f"{draft_id}.pdf")
    os.makedirs(PDF_IMPORT_DRAFT_FOLDER, exist_ok=True)
    upload.save(temp_pdf)
    try:
        if os.path.getsize(temp_pdf) > PDF_IMPORT_MAX_BYTES:
            raise ValueError("PDF exceeds the 64 MB Smart PDF Import limit.")
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
                raise ValueError("No structured question-bank records were detected.")
        elif document_type == "glossary":
            result = glossary_result
            if not result.get("terms"):
                raise ValueError("No glossary/terminology records were detected.")
        else:
            raise ValueError(
                "DLMS could not confidently classify this PDF as a question bank or glossary. "
                "Try again and choose the Content type manually."
            )

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
        try:
            os.remove(temp_pdf)
        except OSError:
            pass
        flash(f"PDF analysis failed: {exc}", "error")
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
@media(max-width:760px){.pdf-term-review-grid{grid-template-columns:1fr;}}
</style></head>
<body class="dashboard-home pdf-import-page"><div class="dashboard-shell">
<aside class="dashboard-sidebar" id="dashboardSidebar"><div class="dashboard-brand"><div class="dashboard-brand-mark">▤</div><div><div class="dashboard-brand-title">DLMS</div><div class="dashboard-brand-subtitle">Training Center</div></div></div><nav class="dashboard-nav"><a class="dashboard-nav-item" href="/"><span class="dashboard-nav-icon">⌂</span><span>Dashboard</span></a><a class="dashboard-nav-item" href="/library"><span class="dashboard-nav-icon">▤</span><span>Quiz Library</span></a><a class="dashboard-nav-item active" href="/upload"><span class="dashboard-nav-icon">✎</span><span>Build Quiz</span></a><a class="dashboard-nav-item" href="/study-packs"><span class="dashboard-nav-icon">▣</span><span>Study Packs</span></a><a class="dashboard-nav-item" href="/it"><span class="dashboard-nav-icon">⌘</span><span>IT Study</span></a><a class="dashboard-nav-item" href="/law"><span class="dashboard-nav-icon">⚖</span><span>Law Study</span></a><a class="dashboard-nav-item" href="/medical"><span class="dashboard-nav-icon">✚</span><span>Medical Study</span></a><a class="dashboard-nav-item" href="/history"><span class="dashboard-nav-icon">↶</span><span>History</span></a><a class="dashboard-nav-item" href="/dashboard"><span class="dashboard-nav-icon">▥</span><span>Analytics</span></a></nav><div class="dashboard-nav-section-label"><span>System</span></div><nav class="dashboard-nav dashboard-nav-system"><a class="dashboard-nav-item" href="/settings"><span class="dashboard-nav-icon">⚙</span><span>Settings</span></a><a class="dashboard-nav-item" href="/content-packs"><span class="dashboard-nav-icon">⬡</span><span>Content Packs</span></a><a class="dashboard-nav-item" href="/admin/image-editor"><span class="dashboard-nav-icon">◎</span><span>Image Study Editor</span></a><a class="dashboard-nav-item" href="/help"><span class="dashboard-nav-icon">?</span><span>Help</span></a><a class="dashboard-nav-item" href="/admin/maintenance"><span class="dashboard-nav-icon">⌘</span><span>Maintenance</span></a></nav><div class="dashboard-sidebar-version">Terminology Review</div></aside>
<main class="dashboard-main pdf-import-main">
{% with messages=get_flashed_messages(with_categories=true) %}{% if messages %}<div class="pdf-import-flash-stack">{% for category,message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}</div>{% endif %}{% endwith %}
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="build-eyebrow">SMART PDF IMPORT · TERMINOLOGY</div><h1>Review &amp; Repair</h1><p>{{ draft.source_name }} · {{ draft.page_count }} page{% if draft.page_count != 1 %}s{% endif %}. Review every detected term/definition pair before saving the reusable terminology bank.</p></div></header>
<section class="pdf-import-summary-grid"><article class="dashboard-stat-card"><span>Detected</span><strong>{{ draft.summary.detected }}</strong><small>terms</small></article><article class="dashboard-stat-card"><span>Complete</span><strong>{{ draft.summary.complete }}</strong><small>ready</small></article><article class="dashboard-stat-card"><span>Review</span><strong>{{ draft.summary.review }}</strong><small>needs attention</small></article><article class="dashboard-stat-card"><span>Incomplete</span><strong>{{ draft.summary.incomplete }}</strong><small>repair or exclude</small></article></section>
<div class="pdf-import-filter-row"><button type="button" data-filter="all" class="active">All</button><button type="button" data-filter="complete">Complete</button><button type="button" data-filter="review">Needs Review</button><button type="button" data-filter="incomplete">Incomplete</button></div>
<form method="POST" action="/pdf-import/save/{{ draft.id }}" id="pdfTermReviewForm"><input type="hidden" name="term_review_payload" id="pdfTermReviewPayload">
<section class="dashboard-panel pdf-import-finalize"><div class="build-two-column-fields"><label class="build-field"><span>Terminology bank title</span><input name="quiz_title" value="{{ draft.quiz_title }}" required></label><label class="build-field"><span>Default exam timer</span><input type="number" name="exam_minutes" min="1" max="1440" value="{{ draft.exam_minutes }}"></label></div><div class="pdf-import-source-note">Source: user-provided PDF · redistribution status: not cleared for redistribution</div></section>
<div class="pdf-term-review-list">
{% for t in draft.terms %}
<article class="dashboard-panel pdf-term-review-card status-{{ t.status }}" data-status="{{ t.status }}" data-term-index="{{ loop.index0 }}" data-term-number="{{ t.number }}">
<div class="pdf-import-question-head"><div><span class="pdf-status {{ t.status }}">{{ t.status|upper }}</span><strong>Term {{ t.number }}</strong><small class="pdf-term-page">PDF page{% if t.pages|length != 1 %}s{% endif %} {{ t.pages|join(", ") }}</small></div><label class="pdf-delete-toggle"><input type="checkbox" data-term-role="exclude"><span>Exclude term</span></label></div>
{% if t.issues %}<div class="pdf-import-issues">{% for issue in t.issues %}<div>⚠ {{ issue }}</div>{% endfor %}</div>{% endif %}
<div class="pdf-term-review-grid"><label class="build-field"><span>Term</span><input data-term-role="term" value="{{ t.term }}"></label><label class="build-field"><span>Definition</span><textarea data-term-role="definition" rows="4">{{ t.definition }}</textarea></label></div>
</article>
{% endfor %}
</div>
<section class="dashboard-panel pdf-import-create-bar"><div><strong>Save the complete reviewed terminology bank.</strong><span>Excluded records are preserved in the source bank but are never used for generated practice.</span></div><div class="build-submit-row"><a class="build-secondary-link" href="/pdf-import">Start Over</a><button class="build-primary-button" type="submit">Save Reviewed Terminology Bank</button></div></section>
</form></main></div>
<script>
document.getElementById("menuButton")?.addEventListener("click",()=>document.getElementById("dashboardSidebar")?.classList.toggle("open"));
document.querySelectorAll(".pdf-import-filter-row button").forEach(btn=>btn.addEventListener("click",()=>{document.querySelectorAll(".pdf-import-filter-row button").forEach(b=>b.classList.remove("active"));btn.classList.add("active");const f=btn.dataset.filter;document.querySelectorAll(".pdf-term-review-card").forEach(card=>card.hidden=f!=="all"&&card.dataset.status!==f)}));
document.getElementById("pdfTermReviewForm")?.addEventListener("submit",()=>{const payload=[];document.querySelectorAll(".pdf-term-review-card").forEach(card=>payload.push({index:Number(card.dataset.termIndex||0),number:Number(card.dataset.termNumber||0),exclude:!!card.querySelector('[data-term-role="exclude"]')?.checked,term:card.querySelector('[data-term-role="term"]')?.value||"",definition:card.querySelector('[data-term-role="definition"]')?.value||""}));document.getElementById("pdfTermReviewPayload").value=JSON.stringify(payload)});
</script><script src="/static/nav-normalize.js"></script></body></html>
"""
    return render_template_string(template, draft=draft)

@app.route("/pdf-import/review/<draft_id>")
def pdf_import_review(draft_id):
    try:
        draft = _load_pdf_import_draft(draft_id)
    except Exception as exc:
        flash(str(exc), "error")
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
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="build-eyebrow">SMART PDF IMPORT · REVIEW</div><h1>Review &amp; Repair</h1><p>{{ draft.source_name }} · {{ draft.page_count }} page{% if draft.page_count != 1 %}s{% endif %}. DLMS parsed the full source. Repair anything misread or exclude unusable questions, then save the reusable question bank.</p></div></header>
<section class="pdf-import-summary-grid">
<article class="dashboard-stat-card"><span>Detected</span><strong>{{ draft.summary.detected }}</strong><small>questions</small></article>
<article class="dashboard-stat-card"><span>Complete</span><strong>{{ draft.summary.complete }}</strong><small>ready</small></article>
<article class="dashboard-stat-card"><span>Review</span><strong>{{ draft.summary.review }}</strong><small>needs attention</small></article>
<article class="dashboard-stat-card"><span>Incomplete</span><strong>{{ draft.summary.incomplete }}</strong><small>repair or remove</small></article>
</section>
<div class="pdf-import-filter-row"><button type="button" data-filter="all" class="active">All</button><button type="button" data-filter="complete">Complete</button><button type="button" data-filter="review">Needs Review</button><button type="button" data-filter="incomplete">Incomplete</button></div>
<form method="POST" action="/pdf-import/save/{{ draft.id }}" id="pdfReviewForm">
<input type="hidden" name="review_payload" id="pdfReviewPayload" value="">
<section class="dashboard-panel pdf-import-finalize"><div class="build-two-column-fields"><label class="build-field"><span>Question bank title</span><input name="quiz_title" value="{{ draft.quiz_title }}" required form="pdfReviewForm"></label><label class="build-field"><span>Exam timer</span><input type="number" name="exam_minutes" min="1" max="1440" value="{{ draft.exam_minutes }}" form="pdfReviewForm"></label></div><div class="pdf-import-source-note">Source: user-provided PDF · redistribution status: not cleared for redistribution</div></section>
<div class="pdf-import-question-list">
{% for q in draft.questions %}
<article class="dashboard-panel pdf-import-question-card status-{{ q.status }}" data-status="{{ q.status }}" data-question-index="{{ loop.index0 }}" data-question-number="{{ q.number }}">
<div class="pdf-import-question-head"><div><span class="pdf-status {{ q.status }}">{{ q.status|replace("_"," ")|upper }}</span><strong>Question {{ q.number }}</strong><small>PDF page{% if q.pages|length != 1 %}s{% endif %} {{ q.pages|join(", ") }}</small></div><label class="pdf-delete-toggle"><input type="checkbox" name="delete_{{ loop.index0 }}" value="1" form="pdfReviewForm" data-pdf-role="delete"><span>Delete question</span></label></div>
{% if q.issues %}<div class="pdf-import-issues">{% for issue in q.issues %}<div>⚠ {{ issue }}</div>{% endfor %}</div>{% endif %}
<input type="hidden" name="original_number_{{ loop.index0 }}" value="{{ q.number }}" form="pdfReviewForm">
<label class="build-field"><span>Question text</span><textarea name="question_{{ loop.index0 }}" rows="4" form="pdfReviewForm" data-pdf-role="question">{{ q.question }}</textarea></label>
<div class="pdf-import-choice-grid">
{% for choice in q.choices %}
<label class="build-field pdf-choice-field"><span>{{ choice.label }}{% if choice.label == q.correct %} · detected correct{% endif %}</span><input name="choice_{{ loop.index0 }}_{{ choice.label }}" value="{{ choice.text }}" form="pdfReviewForm" data-pdf-role="choice" data-choice-label="{{ choice.label }}"></label>
{% endfor %}
</div>
<div class="build-two-column-fields">
<label class="build-field"><span>Correct answer</span><select name="correct_{{ loop.index0 }}" form="pdfReviewForm" data-pdf-role="correct">{% for choice in q.choices %}<option value="{{ choice.label }}" {% if choice.label == q.correct %}selected{% endif %}>{{ choice.label }} — {{ choice.text }}</option>{% endfor %}</select></label>
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
document.querySelectorAll(".pdf-import-filter-row button").forEach(btn=>btn.addEventListener("click",()=>{
 document.querySelectorAll(".pdf-import-filter-row button").forEach(b=>b.classList.remove("active"));btn.classList.add("active");
 const f=btn.dataset.filter;document.querySelectorAll(".pdf-import-question-card").forEach(card=>card.hidden=f!=="all"&&card.dataset.status!==f);
}));
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
        flash(str(exc), "error")
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
        flash(str(exc), "error")
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
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="build-eyebrow">PDF QUESTION BANK</div><h1>{{ bank.title }}</h1><p>{{ bank.source_name }} · All parsed source questions are retained. Generate as many manageable quizzes as you want without re-importing the PDF.</p></div></header>
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
        ts = int(time.time() * 1000)
        html_name = f"pdf_bank_{ts}.html"
        json_name = f"pdf_bank_{ts}.json"

        with open(os.path.join(DATA_FOLDER, json_name), "w", encoding="utf-8") as f:
            json.dump(quiz_data, f, indent=4, ensure_ascii=False)

        quiz_id = save_quiz_to_db(quiz_title, html_name, quiz_data)
        add_quiz_to_registry(
            quiz_id=quiz_id,
            html=html_name,
            title=quiz_title,
            logo=None,
            exam_minutes=exam_minutes,
        )
        build_quiz_html(
            html_name, json_name, os.path.join(QUIZ_FOLDER, html_name),
            get_portal_title(), quiz_title, None, quiz_id, exam_minutes
        )

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

        flash(
            f"Created '{quiz_title}' with {len(selected)} question(s) from '{bank.get('title')}'. "
            f"The source bank remains intact.",
            "success",
        )
        return redirect(f"/edit_quiz/{quiz_id}")
    except Exception as exc:
        flash(f"Could not generate quiz: {exc}", "error")
        return redirect(f"/pdf-import/bank/{bank_id}")


@app.route("/pdf-import/terms")
def pdf_terminology_banks_page():
    return redirect("/pdf-import")


@app.route("/pdf-import/terms/<bank_id>")
def pdf_terminology_bank_page(bank_id):
    try:
        bank = _load_pdf_terminology_bank(bank_id)
    except Exception as exc:
        flash(str(exc), "error")
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
<header class="dashboard-header"><button class="dashboard-menu-button" id="menuButton" type="button">☰</button><div><div class="build-eyebrow">PDF TERMINOLOGY BANK</div><h1>{{ bank.title }}</h1><p>{{ bank.source_name }} · The reviewed glossary stays intact while DLMS generates matching or multiple-choice practice from selected terms.</p></div></header>
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

        flash(
            f"Created '{quiz_title}' from {len(selected)} terminology item(s). The source bank remains intact.",
            "success",
        )
        return redirect(f"/edit_quiz/{quiz_id}")
    except Exception as exc:
        flash(f"Could not generate terminology practice: {exc}", "error")
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
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
            text = upload.stream.read().decode("utf-8-sig")
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
        seen = set()
        for row in reader:
            left = (row.get(term_col) or "").strip()
            right = (row.get(def_col) or "").strip()
            if not left or not right:
                continue
            key = (left.casefold(), right.casefold())
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"left": left, "right": right})
        if len(pairs) < 2:
            flash("The CSV needs at least two complete unique pairs.", "error")
            return redirect("/matching_bank_import")
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
        ts = int(time.time())
        html_name = f"matching_bank_{ts}.html"
        json_name = f"matching_bank_{ts}.json"
        json_path = os.path.join(DATA_FOLDER, json_name)
        html_path = os.path.join(QUIZ_FOLDER, html_name)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(quiz_data, f, indent=4, ensure_ascii=False)
        quiz_id = save_quiz_to_db(quiz_title, html_name, quiz_data)
        add_quiz_to_registry(quiz_id=quiz_id, html=html_name, title=quiz_title, logo=None, exam_minutes=90)
        build_quiz_html(html_name, json_name, html_path, get_portal_title(), quiz_title, None, quiz_id, 90)
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
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
        const roundSize = block.querySelector(".matching-round-size");
        const direction = block.querySelector(".matching-direction");
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

    html_name = f"short_quiz_{ts}.html"
    json_name = f"short_quiz_{ts}.json"

    json_path = os.path.join(DATA_FOLDER, json_name)
    html_path = os.path.join(QUIZ_FOLDER, html_name)

    # Save JSON file
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=4)

    # Save quiz into DB using existing helper
    quiz_id = save_quiz_to_db(
        quiz_title=quiz_title,
        source_file=html_name,
        quiz_data=quiz_data,
        logo_filename=logo_filename
    )

    # Add to library registry
    add_quiz_to_registry(
        quiz_id=quiz_id,
        html=html_name,
        title=quiz_title,
        logo=logo_filename,
        exam_minutes=exam_minutes
    )

    # Build playable quiz HTML
    build_quiz_html(
        html_name,
        json_name,
        html_path,
        get_portal_title(),
        quiz_title,
        logo_filename,
        quiz_id,
        exam_minutes
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
    
    <h1 class="hero-title">👀 Preview Quiz Before Building</h1>

    <div class="card">
        <h2>Quiz Title:</h2>
        <p><b>{{quiz_title}}</b></p>

        <!-- STEP 7: PRE-PROCESS SUMMARY PANEL -->
<div style="background:#1a1a1a; padding:12px; border-radius:8px; margin-bottom:18px;">
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
                    <h3>💡 Smart Suggestions</h3>

                    {% if smart_suggestions and smart_suggestions|length > 0 %}
                    <ul>
                    {% for s in smart_suggestions %}
                    <li style="margin-bottom:10px;">
                        <b>{{s.title}}</b><br>
                        <span style="opacity:.85">{{s.detail}}</span><br>
                        <span style="opacity:.7">Recommendation: {{s.recommend}}</span>

                        {% if s.suggest_rule %}
                        <br>
                        <code style="background:#222;padding:4px 6px;border-radius:6px;">
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
        <pre id="origBox" style="background:black;padding:10px;border-radius:8px;white-space:pre-wrap;">{{original}}</pre>

        <h2>Text To Be Parsed: (passed to quiz)</h2>
        <pre id="cleanBox" style="background:#102020;padding:10px;border-radius:8px;white-space:pre-wrap;">{{cleaned}}</pre>

        <br>
        <button onclick="toggleInvisible()" style="margin-top:5px;">
            👁 Show / Hide Invisible Characters
        </button>

        <p style="opacity:.7">
            This helps detect BOM, zero-width, Unicode junk, and newline issues.
        </p>

        <div id="visualPanel" style="display:none; margin-top:15px;">
            <h2>🔍 Visualized Text</h2>

            <h3>Original Input</h3>
            <pre id="visualOrig" style="background:#222;padding:10px;border-radius:8px;white-space:pre-wrap;"></pre>

            <h3>Parsed (Cleaned) Version</h3>
            <pre id="visualClean" style="background:#333;padding:10px;border-radius:8px;white-space:pre-wrap;"></pre>
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
            <pre id="diffView"
                 style="background:#252525;padding:10px;border-radius:8px;white-space:pre-wrap;"></pre>

            <p style="opacity:.7">
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
        <h2>🧠 Confidence Analysis</h2>
        <p>
            <b>Total blocks:</b> {{conf_summary.total}}<br>
            ✅ High: {{conf_summary.high}} &nbsp;
            ⚠ Medium: {{conf_summary.medium}} &nbsp;
            ❌ Low: {{conf_summary.low}}
        </p>

        <ul>
            {% for item in conf_details %}
            <li style="margin-bottom:8px;">
                <b>Block {{item.index}} ({{item.confidence|capitalize}})</b><br>
                <span style="opacity:.85">{{item.title}}</span><br>
                <span style="opacity:.6; font-size:12px;">{{item.reason}}</span>
            </li>
            {% endfor %}
        </ul>
        {% endif %}

        <p style="opacity:.7">
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

    db_quiz_id = save_quiz_to_db(
        quiz_title,
        source_file,
        quiz_data,
        logo_filename
    )






   # =========================
    # SAVE JSON + HTML quiz (kept for UI compatibility)
    # =========================
    json_name = f"quiz_{ts}.json"
    html_name = f"quiz_{ts}.html"

    with open(os.path.join(DATA_FOLDER, json_name), "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=4)

    # =========================
    # REGISTER QUIZ (AFTER html_name EXISTS)
    # =========================
    dprint("[DEBUG] Registering quiz:",
        html_name,
        quiz_title,
        logo_filename)

    add_quiz_to_registry(
        db_quiz_id,
        html_name,
        quiz_title,
        logo_filename,
        exam_minutes
    )




    build_quiz_html(
        html_name,
        json_name,
        os.path.join(QUIZ_FOLDER, html_name),
        get_portal_title(),
        quiz_title,
        logo_filename,
        db_quiz_id,
        exam_minutes
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

    # ---- save uploaded text file ----
    path = os.path.join(UPLOAD_FOLDER, source_file)
    file.save(path)



    # =========================
    # READ FILE CONTENT (CRITICAL FIX)
    # =========================
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw_text = f.read().strip()

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
    

    quiz_id = save_quiz_to_db(
        quiz_title,
        source_file,
        quiz_data,
        logo_filename
    )






    # =========================
    # SAVE JSON + HTML quiz (UI compatibility)
    # =========================
    json_name = f"quiz_{ts}.json"
    html_name = f"quiz_{ts}.html"

    with open(os.path.join(DATA_FOLDER, json_name), "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=4)

    build_quiz_html(
        html_name,
        json_name,
        os.path.join(QUIZ_FOLDER, html_name),
        get_portal_title(),
        quiz_title,
        logo_filename,
        quiz_id,
        exam_minutes
    )


    add_quiz_to_registry(
    quiz_id,
    html_name,
    quiz_title,
    logo_filename,
    exam_minutes
)


    return redirect("/library")




# =====================================================
# SETTINGS HUB + INCREMENTAL SETTINGS MIGRATION
# =====================================================
@app.route("/settings")
def settings_page():
    """Settings landing page for the completed category-based settings UI."""
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Settings - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="settings-hub-page">
<div class="settings-page-shell">
    <div class="settings-page-header">
        <div>
            <span class="settings-eyebrow">SYSTEM</span>
            <h1>⚙️ Settings</h1>
            <p>Configure DLMS by category. Each settings area saves independently.</p>
        </div>
        <button type="button" class="settings-back-button" onclick="location.href='/'">← Dashboard</button>
    </div>

    <div class="settings-hub-grid">
        <a class="settings-hub-card is-ready" href="/settings/appearance">
            <div class="settings-hub-icon icon-blue">🎨</div>
            <div class="settings-hub-copy">
                <div class="settings-card-kicker">AVAILABLE</div>
                <h2>Appearance</h2>
                <p>Change the dashboard title and site background image.</p>
            </div>
            <span class="settings-hub-arrow">›</span>
        </a>

        <a class="settings-hub-card is-ready" href="/settings/ai">
            <div class="settings-hub-icon icon-purple">🤖</div>
            <div class="settings-hub-copy">
                <div class="settings-card-kicker">AVAILABLE</div>
                <h2>AI Integration</h2>
                <p>AI helper, provider, custom URL, and explanation prompt template.</p>
            </div>
            <span class="settings-hub-arrow">›</span>
        </a>

        <a class="settings-hub-card is-ready" href="/settings/parsing">
            <div class="settings-hub-icon icon-orange">🧩</div>
            <div class="settings-hub-copy">
                <div class="settings-card-kicker">AVAILABLE</div>
                <h2>Parsing</h2>
                <p>Confidence analysis, regex tools, BOM cleanup, and invisible characters.</p>
            </div>
            <span class="settings-hub-arrow">›</span>
        </a>

        <a class="settings-hub-card is-ready" href="/settings/data">
            <div class="settings-hub-icon icon-green">💾</div>
            <div class="settings-hub-copy">
                <div class="settings-card-kicker">AVAILABLE</div>
                <h2>Data &amp; History</h2>
                <p>Manage persistent attempt history and missed-question records.</p>
            </div>
            <span class="settings-hub-arrow">›</span>
        </a>

        <a class="settings-hub-card is-ready settings-danger-card" href="/settings/reset">
            <div class="settings-hub-icon icon-red">⚠</div>
            <div class="settings-hub-copy">
                <div class="settings-card-kicker">DESTRUCTIVE ACTIONS</div>
                <h2>Reset &amp; Recovery</h2>
                <p>Factory reset and destructive recovery operations.</p>
            </div>
            <span class="settings-hub-arrow">›</span>
        </a>

        <a class="settings-hub-card is-ready" href="/admin/maintenance">
            <div class="settings-hub-icon icon-cyan">🛠</div>
            <div class="settings-hub-copy">
                <div class="settings-card-kicker">SYSTEM TOOL</div>
                <h2>Maintenance</h2>
                <p>Rebuild existing quiz pages using the current DLMS template.</p>
            </div>
            <span class="settings-hub-arrow">›</span>
        </a>
    </div>

    <div class="settings-migration-note">
        <strong>Settings migration complete:</strong> Appearance, AI Integration, Parsing, Data &amp; History, and Reset &amp; Recovery now have dedicated pages. The original settings page remains available at <code>/settings/legacy</code> during this test phase as a hidden safety fallback.
    </div>
</div>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""")


@app.route("/settings/appearance")
def settings_appearance_page():
    cfg = load_portal_config()
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Appearance Settings - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="settings-detail-page">
<div class="settings-page-shell settings-detail-shell">
    <div class="settings-page-header">
        <div>
            <span class="settings-eyebrow">SETTINGS / APPEARANCE</span>
            <h1>🎨 Appearance</h1>
            <p>Customize the DLMS dashboard identity without changing quiz, AI, parsing, or history settings.</p>
        </div>
        <button type="button" class="settings-back-button" onclick="location.href='/settings'">← Settings</button>
    </div>

    {% if request.args.get('saved') == '1' %}
    <div class="settings-success-banner">✓ Appearance settings saved.</div>
    {% endif %}

    <form class="settings-detail-card" action="/settings/appearance/save" method="POST" enctype="multipart/form-data">
        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-blue">Aa</div>
                <div>
                    <h2>Dashboard Title</h2>
                    <p>This title appears on the DLMS dashboard.</p>
                </div>
            </div>

            <label class="settings-field-label" for="portalTitle">Dashboard Title</label>
            <input class="settings-text-input"
                   id="portalTitle"
                   type="text"
                   name="portal_title"
                   value="{{ cfg.title }}"
                   required>
        </section>

        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-green">▧</div>
                <div>
                    <h2>Background Image</h2>
                    <p>Upload a replacement background. Leaving the file field empty keeps your current background.</p>
                </div>
            </div>

            {% if cfg.background_image %}
            <div class="settings-current-value">
                <span>Current background</span>
                <strong>{{ cfg.background_image }}</strong>
            </div>
            {% else %}
            <div class="settings-current-value">
                <span>Current background</span>
                <strong>None configured</strong>
            </div>
            {% endif %}

            <div class="settings-image-guidance">
                <strong>Recommended:</strong> landscape image, at least 1600×900, JPG or PNG, and preferably under 3–4 MB.
            </div>

            <input class="settings-file-input"
                   type="file"
                   name="background_image"
                   accept="image/*">
        </section>

        <div class="settings-form-actions">
            <button type="submit" class="settings-primary-button">💾 Save Appearance</button>
            <button type="button" class="settings-secondary-button" onclick="location.href='/settings'">Cancel</button>
        </div>
    </form>

    <div class="settings-scope-note">
        <strong>Safe migration behavior:</strong> saving this page changes only the dashboard title and background image. It does not touch parsing or AI settings.
    </div>
</div>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""", cfg=cfg)


@app.route("/settings/appearance/save", methods=["POST"])
def save_appearance_settings():
    """Save only Appearance settings.

    Deliberately does not update checkbox-based parsing or AI values so a
    partial settings form cannot accidentally disable unrelated features.
    """
    cfg = load_portal_config()

    title = request.form.get("portal_title", "").strip()
    if title:
        cfg["title"] = title

    file = request.files.get("background_image")
    if file and file.filename and file.filename.strip():
        filename = secure_filename(file.filename)
        os.makedirs(BACKGROUND_FOLDER, exist_ok=True)
        save_path = os.path.join(BACKGROUND_FOLDER, filename)
        file.save(save_path)

        if not os.path.exists(save_path):
            raise RuntimeError(f"Background image failed to save: {save_path}")

        cfg["background_image"] = filename

    with open(PORTAL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

    return redirect("/settings/appearance?saved=1")


@app.route("/settings/ai")
def settings_ai_page():
    cfg = load_portal_config()

    cfg.setdefault("ai_helper_enabled", False)
    cfg.setdefault("ai_provider", "chatgpt")
    cfg.setdefault("ai_custom_url", "")
    cfg.setdefault("ai_auto_copy_prompt", True)
    cfg.setdefault("ai_prompt_template", "")
    cfg.setdefault("law_ai_prompt_template", DEFAULT_LAW_AI_PROMPT)

    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Integration Settings - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="settings-detail-page">
<div class="settings-page-shell settings-detail-shell">
    <div class="settings-page-header">
        <div>
            <span class="settings-eyebrow">SETTINGS / AI INTEGRATION</span>
            <h1>🤖 AI Integration</h1>
            <p>Configure how DLMS prepares explanation prompts and opens your preferred AI provider.</p>
        </div>
        <button type="button" class="settings-back-button" onclick="location.href='/settings'">← Settings</button>
    </div>

    {% if request.args.get('saved') == '1' %}
    <div class="settings-success-banner">✓ AI integration settings saved.</div>
    {% endif %}

    <form class="settings-detail-card" action="/settings/ai/save" method="POST">
        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-purple">AI</div>
                <div>
                    <h2>AI Helper</h2>
                    <p>Enable AI-assisted explanation tools on missed-question review pages.</p>
                </div>
            </div>

            <label class="settings-toggle-row">
                <input type="checkbox"
                       name="ai_helper_enabled"
                       {% if cfg.ai_helper_enabled %}checked{% endif %}>
                <span>
                    <strong>Enable AI helper buttons</strong>
                    <small>Shows AI explanation controls when reviewing missed questions.</small>
                </span>
            </label>

            <label class="settings-toggle-row">
                <input type="checkbox"
                       name="ai_auto_copy_prompt"
                       {% if cfg.ai_auto_copy_prompt %}checked{% endif %}>
                <span>
                    <strong>Automatically copy the explanation prompt</strong>
                    <small>Copies the prepared DLMS prompt before opening the selected AI provider.</small>
                </span>
            </label>
        </section>

        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-blue">↗</div>
                <div>
                    <h2>Provider</h2>
                    <p>Select the AI service DLMS should open for explanation workflows.</p>
                </div>
            </div>

            <label class="settings-field-label" for="aiProvider">AI Provider</label>
            <select class="settings-select-input" id="aiProvider" name="ai_provider">
                <option value="chatgpt" {% if cfg.ai_provider == "chatgpt" %}selected{% endif %}>ChatGPT</option>
                <option value="claude" {% if cfg.ai_provider == "claude" %}selected{% endif %}>Claude</option>
                <option value="gemini" {% if cfg.ai_provider == "gemini" %}selected{% endif %}>Gemini</option>
                <option value="local" {% if cfg.ai_provider == "local" %}selected{% endif %}>Local / Custom URL</option>
            </select>

            <label class="settings-field-label" for="aiCustomUrl">Custom AI URL</label>
            <input class="settings-text-input"
                   id="aiCustomUrl"
                   type="text"
                   name="ai_custom_url"
                   value="{{ cfg.ai_custom_url }}"
                   placeholder="Example: http://192.168.1.50:3000"
                   style="margin-bottom:10px;">

            <div class="settings-field-help">
                Used only when the provider is Local / Custom URL.
            </div>
        </section>

        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-green">✎</div>
                <div>
                    <h2>Explanation Prompt Template</h2>
                    <p>Customize the prompt DLMS prepares for missed-question explanations.</p>
                </div>
            </div>

            <div class="settings-image-guidance">
                Include <code>{{ '{{questions}}' }}</code> where DLMS should insert the selected questions.
            </div>

            <textarea class="settings-textarea"
                      id="aiPromptTemplate"
                      name="ai_prompt_template"
                      rows="14">{{ cfg.ai_prompt_template }}</textarea>

            <div class="settings-inline-actions">
                <button type="button" class="settings-secondary-button" id="resetAIPromptBtn">🔄 Reset to Default Prompt</button>
            </div>
        </section>

        <section class="settings-form-section settings-law-prompt-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-blue">⚖</div>
                <div>
                    <h2>Law Study Prompt Template</h2>
                    <p>Customize the prompt DLMS uses to generate Law Study case packets.</p>
                </div>
            </div>

            <div class="settings-image-guidance settings-placeholder-guide">
                Keep these placeholders where you want DLMS to insert Law Study data:
                <code>{{ '{{case_name}}' }}</code>
                <code>{{ '{{course}}' }}</code>
                <code>{{ '{{study_sections}}' }}</code>
            </div>

            <textarea class="settings-textarea settings-law-prompt-textarea"
                      id="lawAIPromptTemplate"
                      name="law_ai_prompt_template"
                      rows="24">{{ cfg.law_ai_prompt_template }}</textarea>

            <div class="settings-inline-actions">
                <button type="button" class="settings-secondary-button" id="resetLawPromptBtn">🔄 Reset to Default Law Prompt</button>
            </div>
        </section>

        <div class="settings-form-actions">
            <button type="submit" class="settings-primary-button">💾 Save AI Settings</button>
            <button type="button" class="settings-secondary-button" onclick="location.href='/settings'">Cancel</button>
        </div>
    </form>

    <div class="settings-scope-note">
        <strong>Safe migration behavior:</strong> saving this page changes only AI-related configuration. Appearance and parsing settings are not modified.
    </div>
</div>

<script>
const AI_QUESTIONS_PLACEHOLDER = "{" + "{questions}" + "}";
const DEFAULT_AI_PROMPT =
`You are a technical tutor helping a student learn from mistakes.

For each question:
1. Explain why the correct answer is correct
2. Explain why the selected answer is incorrect
3. Give a short memory tip
4. Keep explanations concise but clear
5. Return your answer in clearly separated sections per question.

---

${AI_QUESTIONS_PLACEHOLDER}`;

const DEFAULT_LAW_AI_PROMPT = {{ law_default_prompt|tojson }};

const resetAIPromptBtn = document.getElementById("resetAIPromptBtn");
const aiPromptTemplate = document.getElementById("aiPromptTemplate");
const resetLawPromptBtn = document.getElementById("resetLawPromptBtn");
const lawAIPromptTemplate = document.getElementById("lawAIPromptTemplate");

if (resetAIPromptBtn && aiPromptTemplate) {
    resetAIPromptBtn.addEventListener("click", () => {
        aiPromptTemplate.value = DEFAULT_AI_PROMPT;
        aiPromptTemplate.focus();
    });
}

if (resetLawPromptBtn && lawAIPromptTemplate) {
    resetLawPromptBtn.addEventListener("click", () => {
        lawAIPromptTemplate.value = DEFAULT_LAW_AI_PROMPT;
        lawAIPromptTemplate.focus();
    });
}
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""", cfg=cfg, law_default_prompt=DEFAULT_LAW_AI_PROMPT)


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

    cfg["ai_custom_url"] = request.form.get("ai_custom_url", "").strip()
    cfg["ai_prompt_template"] = request.form.get("ai_prompt_template", "").strip()
    cfg["law_ai_prompt_template"] = request.form.get("law_ai_prompt_template", "").strip() or DEFAULT_LAW_AI_PROMPT

    with open(PORTAL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

    return redirect("/settings/ai?saved=1")



@app.route("/settings/parsing")
def settings_parsing_page():
    cfg = load_portal_config()

    cfg.setdefault("show_confidence", True)
    cfg.setdefault("enable_regex_replace", False)
    cfg.setdefault("auto_bom_clean", False)
    cfg.setdefault("enable_show_invisibles", True)

    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Parsing Settings - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="settings-detail-page">
<div class="settings-page-shell settings-detail-shell">
    <div class="settings-page-header">
        <div>
            <span class="settings-eyebrow">SETTINGS / PARSING</span>
            <h1>🧩 Parsing</h1>
            <p>Control optional quiz-preview and text-cleanup tools used when preparing imported or pasted question content.</p>
        </div>
        <button type="button" class="settings-back-button" onclick="location.href='/settings'">← Settings</button>
    </div>

    {% if request.args.get('saved') == '1' %}
    <div class="settings-success-banner">✓ Parsing settings saved.</div>
    {% endif %}

    <form class="settings-detail-card" action="/settings/parsing/save" method="POST">
        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-blue">🧠</div>
                <div>
                    <h2>Confidence Analysis</h2>
                    <p>Controls whether the Confidence Analysis panel appears on quiz preview.</p>
                </div>
            </div>

            <label class="settings-toggle-row">
                <input type="checkbox"
                       name="show_confidence"
                       value="1"
                       {% if cfg.show_confidence %}checked{% endif %}>
                <span>
                    <strong>Enable Confidence Analysis on Preview</strong>
                    <small>Shows the optional confidence-analysis panel while reviewing parsed quiz content.</small>
                </span>
            </label>
        </section>

        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-orange">.*</div>
                <div>
                    <h2>Regex Strip / Replace Engine</h2>
                    <p>Enables advanced regular-expression cleanup tools when pasting quiz content.</p>
                </div>
            </div>

            <label class="settings-toggle-row">
                <input type="checkbox"
                       name="enable_regex_replace"
                       value="1"
                       {% if cfg.enable_regex_replace %}checked{% endif %}>
                <span>
                    <strong>Enable Regex Replace Engine</strong>
                    <small>Makes the regex cleanup workflow available before quiz parsing.</small>
                </span>
            </label>
        </section>

        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-green">⌫</div>
                <div>
                    <h2>Invisible / BOM Cleanup</h2>
                    <p>Automatically removes hidden Unicode characters that can interfere with parsing.</p>
                </div>
            </div>

            <label class="settings-toggle-row">
                <input type="checkbox"
                       name="auto_bom_clean"
                       value="1"
                       {% if cfg.auto_bom_clean %}checked{% endif %}>
                <span>
                    <strong>Enable Invisible Character &amp; BOM Cleanup</strong>
                    <small>Removes BOM characters, zero-width spaces, and similar hidden text artifacts commonly introduced by PDF or Word copy/paste.</small>
                </span>
            </label>
        </section>

        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-purple">¶</div>
                <div>
                    <h2>Show Invisible Characters Tool</h2>
                    <p>Controls whether hidden-character visualization is available during preview.</p>
                </div>
            </div>

            <label class="settings-toggle-row">
                <input type="checkbox"
                       name="enable_show_invisibles"
                       value="1"
                       {% if cfg.enable_show_invisibles %}checked{% endif %}>
                <span>
                    <strong>Enable “Show Invisible Characters” Debug Tool</strong>
                    <small>Lets you reveal hidden characters when diagnosing difficult parsing problems.</small>
                </span>
            </label>
        </section>

        <div class="settings-form-actions">
            <button type="submit" class="settings-primary-button">💾 Save Parsing Settings</button>
            <button type="button" class="settings-secondary-button" onclick="location.href='/settings'">Cancel</button>
        </div>
    </form>

    <div class="settings-scope-note">
        <strong>Safe migration behavior:</strong> saving this page changes only parsing-related configuration. Appearance and AI settings are not modified.
    </div>
</div>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""", cfg=cfg)


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

    with open(PORTAL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

    return redirect("/settings/parsing?saved=1")


@app.route("/settings/data")
def settings_data_page():
    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Data & History Settings - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="settings-detail-page">
<div class="settings-page-shell settings-detail-shell">
    <div class="settings-page-header">
        <div>
            <span class="settings-eyebrow">SETTINGS / DATA &amp; HISTORY</span>
            <h1>💾 Data &amp; History</h1>
            <p>Manage persistent quiz-attempt and missed-question history without deleting quizzes.</p>
        </div>
        <button type="button" class="settings-back-button" onclick="location.href='/settings'">← Settings</button>
    </div>

    <div class="settings-detail-card">
        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-green">↶</div>
                <div>
                    <h2>Persistent Exam Result Storage</h2>
                    <p>DLMS stores completed attempts and missed-question history in the application database.</p>
                </div>
            </div>

            <div class="settings-warning-panel">
                <strong>This action cannot be undone.</strong>
                <span>Clearing history permanently removes all saved attempts, attempt answers, and missed-question records. Quizzes remain in the Quiz Library.</span>
            </div>

            <button id="clearDBBtn" class="settings-danger-button" type="button">
                🗑 Clear Saved Results from Database and Dashboard
            </button>
            <div id="clearDBStatus" class="settings-operation-status" aria-live="polite"></div>
        </section>

        <div class="settings-form-actions">
            <button type="button" class="settings-secondary-button" onclick="location.href='/settings'">← Back to Settings</button>
            <button type="button" class="settings-secondary-button" onclick="location.href='/history'">📜 View History</button>
        </div>
    </div>

    <div class="settings-scope-note">
        <strong>Scope:</strong> this page uses the existing DLMS history-clear API. It does not delete quizzes or change configuration settings.
    </div>
</div>

<script>
const clearDBBtn = document.getElementById("clearDBBtn");
const clearDBStatus = document.getElementById("clearDBStatus");

clearDBBtn.addEventListener("click", async () => {
    if (!confirm(
        "Clear all saved quiz attempts and missed-question history?\n\n" +
        "Your quizzes will remain available.\n\n" +
        "This cannot be undone."
    )) return;

    clearDBBtn.disabled = true;
    clearDBStatus.textContent = "Clearing saved history...";

    try {
        const res = await fetch("/api/clear_db_history", { method: "POST" });
        const data = await res.json();
        if (!res.ok || data.status !== "ok") {
            throw new Error(data.error || "History clear failed");
        }
        clearDBStatus.textContent = "✅ Saved attempt and missed-question history cleared.";
    } catch (err) {
        console.error("[SETTINGS] Clear history failed:", err);
        clearDBStatus.textContent = "❌ History clear failed. Check the server log.";
    } finally {
        clearDBBtn.disabled = false;
    }
});
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""")


@app.route("/settings/reset")
def settings_reset_page():
    return render_template_string(r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reset & Recovery Settings - DLMS</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="icon" href="/static/favicon.ico">
</head>
<body class="settings-detail-page settings-reset-page">
<div class="settings-page-shell settings-detail-shell">
    <div class="settings-page-header">
        <div>
            <span class="settings-eyebrow">SETTINGS / RESET &amp; RECOVERY</span>
            <h1>⚠️ Reset &amp; Recovery</h1>
            <p>Destructive database reset operations are isolated here to reduce the chance of accidental use.</p>
        </div>
        <button type="button" class="settings-back-button" onclick="location.href='/settings'">← Settings</button>
    </div>

    <div class="settings-detail-card settings-reset-card">
        <section class="settings-form-section">
            <div class="settings-section-heading">
                <div class="settings-section-icon icon-red">!</div>
                <div>
                    <h2>Full Factory Reset</h2>
                    <p>Return the quiz database and quiz registry to a fresh state.</p>
                </div>
            </div>

            <div class="settings-critical-panel">
                <strong>Factory Reset permanently deletes:</strong>
                <ul>
                    <li>All quizzes</li>
                    <li>All quiz questions and choices</li>
                    <li>All attempts and missed-question history</li>
                    <li>Generated quiz files and quiz records handled by the existing reset operation</li>
                    <li>Database sequence state, resetting quiz IDs back to 1</li>
                </ul>
                <span>This cannot be undone. Use only when you intentionally want to start over.</span>
            </div>

            <button id="wipeDBBtn" class="settings-critical-button" type="button">
                🧨 Clear ALL DATABASE AND QUIZ RECORDS (FULL RESET)
            </button>
            <div id="wipeDBStatus" class="settings-operation-status" aria-live="polite"></div>
        </section>

        <div class="settings-form-actions">
            <button type="button" class="settings-secondary-button" onclick="location.href='/settings'">← Back to Settings</button>
        </div>
    </div>

    <div class="settings-scope-note">
        <strong>Safety:</strong> this page calls the existing DLMS factory-reset API. The backend reset logic itself has not been rewritten as part of the settings migration.
    </div>
</div>

<script>
const wipeDBBtn = document.getElementById("wipeDBBtn");
const wipeDBStatus = document.getElementById("wipeDBStatus");

wipeDBBtn.addEventListener("click", async () => {
    if (!confirm(`⚠ FACTORY RESET ⚠

This will permanently delete ALL quizzes, attempts, and history.

Quiz IDs will be reset back to 1.

This cannot be undone.

Continue?`)) return;

    wipeDBBtn.disabled = true;
    wipeDBStatus.textContent = "Factory reset in progress...";

    try {
        const res = await fetch("/api/wipe_database", { method: "POST" });
        const data = await res.json();
        if (!res.ok || data.status !== "ok") {
            throw new Error(data.error || "Factory reset returned non-ok status");
        }
        wipeDBStatus.textContent = "✅ FULL RESET completed successfully.";
        alert("Factory reset completed. Application will reload.");
        location.href = "/";
    } catch (err) {
        console.error("[SETTINGS] Factory reset failed:", err);
        wipeDBStatus.textContent = "❌ FULL RESET failed. Check the server log.";
        wipeDBBtn.disabled = false;
    }
});
</script>
<script src="/static/nav-normalize.js"></script>
</body>
</html>
""")


@app.route("/settings/legacy")
def settings_legacy_page():
    cfg = load_portal_config()

    # Ensure safe defaults if missing from portal.json
    cfg.setdefault("show_confidence", True)
    cfg.setdefault("enable_regex_replace", False)
    cfg.setdefault("auto_bom_clean", False)
    cfg.setdefault("enable_show_invisibles", True)

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<title>Dashboard Settings</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">
</head>

<body>

<!--
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
-->

<div class="container">

    <h1 class="hero-title">
        ⚙️ Dashboard Configuration
    </h1>

    <div class="card">

        <!-- NOTE: enctype added so we can upload files -->
        <form action="/save_settings" method="POST" enctype="multipart/form-data">

            <!-- ============================
                 DASHBOARD TITLE
                 ============================ -->
            <h3>Dashboard Title</h3>
            <input type="text"
                   name="portal_title"
                   value="{{ cfg.title }}"
                   required style="width:100%; padding:6px">

            <br><br>

            <!-- ============================
                 BACKGROUND IMAGE UPLOAD
                 ============================ -->
            <h3>Background Image (Optional)</h3>
            <p style="opacity:.75; font-size:13px">
                This image is used as the main background for the entire site.
                For best results, use:
            </p>
            <ul style="opacity:.8; font-size:13px; margin-top:2px;">
                <li>Landscape image (wider than tall)</li>
                <li>Minimum 1600×900 (Full HD 1920×1080 recommended)</li>
                <li>JPG or PNG, preferably under 3–4 MB</li>
                <li>Not too bright or busy (subtle textures work best)</li>
            </ul>

            <input type="file"
                   name="background_image"
                   accept="image/*"
                   style="margin-top:6px;">

            <br><br>

            <!-- ============================
                 ADVANCED PARSING TOGGLE
                 ============================ -->
            <button type="button"
                    id="toggleAdvancedBtn"
                    style="margin-top:10px;">
                🔧 Show Advanced Parsing Settings
            </button>

            <div id="advParsingPanel"
                 style="margin-top:15px; display:none; padding:12px; border-radius:8px;
                        background:rgba(0,0,0,0.6); border:1px solid rgba(255,255,255,0.25);">

                <h3>Confidence Analysis</h3>
                <p style="opacity:.7">
                    Controls whether the 🧠 Confidence Analysis panel appears on quiz preview.
                </p>

                <label style="display:flex; gap:10px; align-items:center;">
                    <input type="checkbox" name="show_confidence"
                           value="1"
                           {% if cfg.show_confidence %}checked{% endif %}>
                    Enable Confidence Analysis on Preview
                </label>

                <br><br>

                <h3>Regex Strip / Replace Engine</h3>
                <p style="opacity:.7">
                    Enables advanced REGEX-based cleanup tools when pasting quiz content.
                </p>

                <label style="display:flex; gap:10px; align-items:center;">
                    <input type="checkbox" name="enable_regex_replace"
                           value="1"
                           {% if cfg.enable_regex_replace %}checked{% endif %}>
                    Enable Regex Replace Engine
                </label>

                <br><br>

                <h3>Invisible / BOM Cleanup</h3>
                <p style="opacity:.7">
                    Automatically removes BOM characters, zero-width spaces, and hidden Unicode junk
                    that can break parsing when copying text from PDFs or Microsoft Word.
                </p>

                <label style="display:flex; gap:10px; align-items:center;">
                    <input type="checkbox"
                           name="auto_bom_clean"
                           value="1"
                           {% if cfg.auto_bom_clean %}checked{% endif %}>
                    Enable Invisible Character & BOM Cleanup
                </label>

                <br><br>

                <h3>Show Invisible Characters Tool</h3>
                <p style="opacity:.7">
                    Allows user to toggle visualization of hidden characters during preview.
                </p>

                <label style="display:flex; gap:10px; align-items:center;">
                    <input type="checkbox"
                        name="enable_show_invisibles"
                        value="1"
                        {% if cfg.enable_show_invisibles %}checked{% endif %}>
                    Enable "Show Invisible Characters" Debug Tool
                </label>

            </div> <!-- /advParsingPanel -->

            <br><br>

            <hr style="margin:25px 0; opacity:.5">

            <h3>🤖 AI Explanation Helper</h3>

            <label>
                <input type="checkbox"
                       name="ai_helper_enabled"
                       {% if cfg.ai_helper_enabled %}checked{% endif %}>
                Enable AI helper buttons on missed-question review
            </label>

            <br><br>

            <label><b>AI Provider</b></label><br>
            <select name="ai_provider" style="width:100%; padding:6px;">
                <option value="chatgpt" {% if cfg.ai_provider == "chatgpt" %}selected{% endif %}>ChatGPT</option>
                <option value="claude" {% if cfg.ai_provider == "claude" %}selected{% endif %}>Claude</option>
                <option value="gemini" {% if cfg.ai_provider == "gemini" %}selected{% endif %}>Gemini</option>
                <option value="local" {% if cfg.ai_provider == "local" %}selected{% endif %}>Local / Custom URL</option>
            </select>

            <br><br>

            <label><b>Custom AI URL</b></label><br>
            <input type="text"
                   name="ai_custom_url"
                   value="{{ cfg.ai_custom_url }}"
                   placeholder="Example: http://192.168.1.50:3000"
                   style="width:100%; padding:6px;">

            <p style="opacity:.75; font-size:12px;">
                Used only when provider is Local / Custom URL.
            </p>

            <label>
                <input type="checkbox"
                       name="ai_auto_copy_prompt"
                       {% if cfg.ai_auto_copy_prompt %}checked{% endif %}>
                Copy explanation prompt before opening AI site
            </label>

            <br><br>

            <h3>📝 AI Prompt Template</h3>

            <p style="opacity:.75; font-size:13px;">
                Customize how DLMS asks the selected AI to explain missed questions.
                Use <code>{&#123;&#123;questions&#125;&#125;}</code> where the missed questions should be inserted.
            </p>

            <textarea id="aiPromptTemplate"
                      name="ai_prompt_template"
                      rows="12"
                      style="width:100%; padding:10px; font-size:13px;">{{ cfg.ai_prompt_template }}</textarea>

            <br><br>

            <button type="button" id="resetAIPromptBtn">
                🔄 Reset to Default Prompt
            </button>

            <p style="opacity:.65; font-size:12px;">
                Leave blank to use the built-in DLMS default prompt. Click reset to restore the default text into this box.
            </p>

            <br><br>

            <button type="submit">💾 Save Settings</button>
        </form>

        <br>

        <hr>

        <h3>Persistent Exam Result Storage</h3>
        <p style="opacity:.75">
            These results are stored in the application database.
            Resetting will permanently delete <strong>all attempts, and missed-question history</strong>,
            quizzes will remain in the quiz library.
        </p>

        <button id="clearDBBtn" style="
            background:#ff4d4d;
            color:white;
            padding:10px 14px;
            border-radius:8px;
            border:1px solid rgba(255,255,255,.3);
        ">
            🗑 Clear Saved Results from Database and Dashboard
        </button>

        <p id="clearDBStatus" style="margin-top:6px;"></p>

        <br>
        <button onclick="location.href='/'">⬅ Back To Dashboard</button>

    </div>

    <hr style="margin:20px 0">

    <h3 style="color:#b30000">⚠️ Factory Reset</h3>
    <p style="opacity:.75">
        This will permanently delete <b>ALL quizzes</b>, <b>ALL attempts</b>,
        and <b>reset quiz IDs back to 1</b>.
    </p>

    <button id="wipeDBBtn" style="background:#b30000;color:white">
        🧨 Clear ALL DATABASE AND QUIZ RECORDS (FULL RESET)
    </button>

    <div id="wipeDBStatus" style="margin-top:8px;font-size:13px;"></div>

</div>

<script>
// =========================
// ADVANCED PARSING PANEL
// =========================
(function() {
    const btn  = document.getElementById("toggleAdvancedBtn");
    const panel = document.getElementById("advParsingPanel");
    if (!btn || !panel) return;

    let open = false;
    btn.addEventListener("click", () => {
        open = !open;
        panel.style.display = open ? "block" : "none";
        btn.textContent = open
            ? "🔧 Hide Advanced Parsing Settings"
            : "🔧 Show Advanced Parsing Settings";
    });
})();

// =========================
// AI PROMPT TEMPLATE RESET
// =========================
// IMPORTANT:
// Do not type the literal placeholder with double curly braces in this template.
// This page is rendered by Flask/Jinja, so we construct it from pieces in JavaScript.
const AI_QUESTIONS_PLACEHOLDER = "{" + "{questions}" + "}";

const DEFAULT_AI_PROMPT =
`You are a technical tutor helping a student learn from mistakes.

For each question:
1. Explain why the correct answer is correct
2. Explain why the selected answer is incorrect
3. Give a short memory tip
4. Keep explanations concise but clear
5. Return your answer in clearly separated sections per question.

---

${AI_QUESTIONS_PLACEHOLDER}
`;

const resetAIPromptBtn = document.getElementById("resetAIPromptBtn");
if (resetAIPromptBtn) {
    resetAIPromptBtn.addEventListener("click", () => {
        const box = document.getElementById("aiPromptTemplate");
        if (!box) {
            alert("AI prompt template box not found.");
            return;
        }

        box.value = DEFAULT_AI_PROMPT;
        box.focus();
    });
}

// =========================
// CLEAR DB HISTORY BUTTON
// =========================
const clearDBBtn = document.getElementById("clearDBBtn");
if (clearDBBtn) {
    clearDBBtn.addEventListener("click", async () => {
        if (!confirm(`⚠ This will permanently delete ALL saved exam results and missed question records.

This cannot be undone.

Continue?`)) return;

        try {
            const res = await fetch("/api/clear_db_history", { method: "POST" });
            const data = await res.json();

            if (data.status === "ok") {
                document.getElementById("clearDBStatus").innerText =
                    "✅ Persistent history deleted successfully";
                alert("Persistent DB history cleared!");
                location.reload();
            } else {
                throw new Error("Clear DB history returned non-ok status");
            }

        } catch (err) {
            console.error("[SETTINGS] Clear DB history failed:", err);
            document.getElementById("clearDBStatus").innerText =
                "⚠️ Failed to clear persistent history.";
        }
    });
}

// =========================
// FULL FACTORY RESET BUTTON
// =========================
const wipeDBBtn = document.getElementById("wipeDBBtn");
if (wipeDBBtn) {
    wipeDBBtn.addEventListener("click", async () => {
        if (!confirm(`⚠ FACTORY RESET ⚠

This will permanently delete ALL quizzes, attempts, and history.

Quiz IDs will be reset back to 1.

This cannot be undone.

Continue?`)) return;

        try {
            const res = await fetch("/api/wipe_database", { method: "POST" });
            const data = await res.json();

            if (data.status === "ok") {
                const el = document.getElementById("wipeDBStatus");
                if (el) el.innerText = "✅ FULL RESET completed successfully.";
                alert("Factory reset completed. Application will reload.");
                location.reload();
            } else {
                throw new Error("Factory reset returned non-ok status");
            }

        } catch (err) {
            console.error("[SETTINGS] Factory reset failed:", err);
            const el = document.getElementById("wipeDBStatus");
            if (el) el.innerText = "❌ FULL RESET failed.";
        }
    });
}
</script>

<script src="/static/nav-normalize.js"></script>
</body>
</html>



    """, cfg=cfg)







# def load_portal_config():
#     default = {
#         "title": "Training & Practice Center",
#         "show_confidence": True,
#         "enable_regex_replace": False,
#         "auto_bom_clean": False,
#         "enable_show_invisibles": False,
#         "background_image": None,
#     }

#     if not os.path.exists(PORTAL_CONFIG):
#         return default.copy()

#     try:
#         with open(PORTAL_CONFIG, "r") as f:
#             data = json.load(f) or {}

#         # Backward compatibility
#         if "auto_clean_hidden" in data and "auto_bom_clean" not in data:
#             data["auto_bom_clean"] = bool(data.get("auto_clean_hidden"))

#         cfg = default.copy()
#         cfg.update(data)

#         return cfg

#     except Exception:
#         return default.copy()





@app.route("/save_settings", methods=["POST"])
def save_settings():
    cfg = load_portal_config()

    dprint("\n[SETTINGS] ===== SAVE_SETTINGS CALLED =====")
    dprint("[SETTINGS] Incoming form keys:", list(request.form.keys()))
    dprint("[SETTINGS] Incoming file keys:", list(request.files.keys()))
    dprint("[SETTINGS] PORTAL_CONFIG path:", PORTAL_CONFIG)
    dprint("[SETTINGS] Existing config BEFORE update:", cfg)

    # =========================
    # Portal title
    # =========================
    title = request.form.get("portal_title", cfg.get("title", "Training & Practice Center")).strip()
    cfg["title"] = title
    dprint("[SETTINGS] Updated title:", title)

    # =========================
    # Advanced toggles
    # =========================
    cfg["show_confidence"]        = ("show_confidence" in request.form)
    cfg["enable_regex_replace"]   = ("enable_regex_replace" in request.form)
    cfg["auto_bom_clean"]         = ("auto_bom_clean" in request.form)
    cfg["enable_show_invisibles"] = ("enable_show_invisibles" in request.form)
    # =========================
    # AI EXPLANATION HELPER SETTINGS
    # =========================
    cfg["ai_helper_enabled"] = ("ai_helper_enabled" in request.form)
    cfg["ai_auto_copy_prompt"] = ("ai_auto_copy_prompt" in request.form)

    valid_ai_providers = {"chatgpt", "claude", "gemini", "local"}
    provider = request.form.get("ai_provider", "chatgpt").strip().lower()
    cfg["ai_provider"] = provider if provider in valid_ai_providers else "chatgpt"

    cfg["ai_custom_url"] = request.form.get("ai_custom_url", "").strip()
    # =========================
    # AI PROMPT TEMPLATE
    # =========================
    template = request.form.get("ai_prompt_template", "").strip()

    # Always save whatever the user entered (including blank)
    cfg["ai_prompt_template"] = template
    
    dprint("[SETTINGS] Toggles:", {
        "show_confidence": cfg["show_confidence"],
        "enable_regex_replace": cfg["enable_regex_replace"],
        "auto_bom_clean": cfg["auto_bom_clean"],
        "enable_show_invisibles": cfg["enable_show_invisibles"],
    })

    # =========================
    # BACKGROUND IMAGE UPLOAD
    # =========================
    file = request.files.get("background_image")

    if file:
        dprint("[SETTINGS] Background file received:", file.filename)

    if file and file.filename.strip():
        filename = secure_filename(file.filename)

        # Ensure folder exists
        os.makedirs(BACKGROUND_FOLDER, exist_ok=True)
        dprint("[SETTINGS] BACKGROUND_FOLDER:", BACKGROUND_FOLDER)

        save_path = os.path.join(BACKGROUND_FOLDER, filename)
        file.save(save_path)

        # 🔒 HARD ASSERT: ensure the file actually exists
        if not os.path.exists(save_path):
            raise RuntimeError(
                f"Background image failed to save: {save_path}"
            )

        cfg["background_image"] = filename



        dprint("[SETTINGS] Background saved to:", save_path)
        dprint("[SETTINGS] background_image set to:", cfg["background_image"])
    else:
        dprint("[SETTINGS] No background image uploaded this request")

    # =========================
    # SAVE CONFIG
    # =========================
    try:
        with open(PORTAL_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        dprint("[SETTINGS] Config successfully written to disk")
    except Exception as e:
        print("[SETTINGS][ERROR] Failed to write portal config:", e)

    dprint("[SETTINGS] Final config AFTER update:", cfg)
    dprint("[SETTINGS] ===== SAVE_SETTINGS COMPLETE =====\n")

    return redirect("/settings/legacy")






# =====================================================
# RECORD QUIZ ATTEMPT (DB-ID CANONICAL)
# =====================================================
@app.route("/record_attempt", methods=["POST"])
def record_attempt():
    data = request.get_json(force=True) or {}

    # --- Input from UI ---
    quiz_id = data.get("quizId")      # REGISTRY ID (from frontend)
    quiz_title = (data.get("quizTitle") or "").strip()

    score = data.get("score")
    total = data.get("total")
    percent = data.get("percent")
    attempt_id = data.get("attemptId")
    started_at = data.get("startedAt")
    completed_at = data.get("completedAt")
    time_remaining = data.get("timeRemaining")
    mode = data.get("mode") or "Study"
    missed_details = data.get("missedDetails") or []

    # --- Basic validation ---
    if quiz_id is None:
        return jsonify({"error": "Missing quizId"}), 400
    if not attempt_id:
        return jsonify({"error": "Missing attemptId"}), 400
    if score is None or total is None:
        return jsonify({"error": "Missing score/total"}), 400

    try:
        quiz_id = int(quiz_id)
    except (TypeError, ValueError):
        return jsonify({"error": f"Invalid quizId: {quiz_id}"}), 400

    conn = get_db()
    cur = conn.cursor()

    try:
        # ------------------------------------------------------------
        # 1) Resolve REGISTRY ID → DB QUIZ ID (AUTHORITATIVE)
        # ------------------------------------------------------------
        

        # ------------------------------------------------------------
        # 2) Insert attempt
        # ------------------------------------------------------------
        cur.execute("PRAGMA table_info(attempts)")
        acols = [r[1] for r in cur.fetchall()]

        if "attempt_id" in acols:
            cur.execute("""
                INSERT INTO attempts (
                    attempt_id, quiz_id, score, total, percent,
                    started_at, completed_at, time_remaining, mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                attempt_id, quiz_id, score, total, percent,
                started_at, completed_at, time_remaining, mode
            ))
            cur.execute(
                "SELECT id FROM attempts WHERE attempt_id = ?",
                (attempt_id,)
            )
            row = cur.fetchone()
            attempt_pk = row[0] if row else None
        else:
            cur.execute("""
                INSERT INTO attempts (
                    id, quiz_id, score, total, percent,
                    started_at, completed_at, time_remaining, mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                attempt_id, quiz_id, score, total, percent,
                started_at, completed_at, time_remaining, mode
            ))
            attempt_pk = attempt_id

        # ------------------------------------------------------------
        # 3) Save missed questions (RECONSTRUCT SNAPSHOT)
        # ------------------------------------------------------------
        missed_attempt_ref = attempt_pk if attempt_pk is not None else attempt_id

        for md in missed_details:
            aqn = md.get("attemptQuestionNumber")
            if aqn is None:
                continue

            # 🔑 Pull authoritative question snapshot from DB
            cur.execute("""
                SELECT q.question_text, q.id, COALESCE(q.question_type, 'choice') AS question_type
                FROM questions q
                WHERE q.quiz_id = ? AND q.question_number = ?
            """, (quiz_id, aqn))
            qrow = cur.fetchone()

            submitted_question_type = str(md.get("questionType") or "").strip().lower()
            question_id = qrow["id"] if qrow else None

            # Hotspot quizzes deliberately use a lightweight choice surrogate in
            # the canonical questions table. Preserve the runtime type supplied by
            # the quiz player so History/Review can reconstruct the image response.
            if submitted_question_type == "hotspot":
                question_type = "hotspot"
                question_text = md.get("question") or (qrow["question_text"] if qrow else "")
            else:
                question_type = qrow["question_type"] if qrow else (submitted_question_type or "choice")
                question_text = qrow["question_text"] if qrow else (md.get("question") or "")

            if not question_id:
                print(f"[WARN] Missing question snapshot for quiz_id={quiz_id}, qnum={aqn}")


            # Pull answer snapshot. Matching questions use their term/pair rows.
            # Hotspots carry their visual response snapshot in response_json.
            choices_text = ""
            response_json = ""
            if question_type == "hotspot":
                hotspot_data = md.get("hotspot") if isinstance(md.get("hotspot"), dict) else {}
                response_json = json.dumps(hotspot_data, ensure_ascii=False)
            elif question_id and question_type == "matching":
                cur.execute("""
                    SELECT left_text, right_text
                    FROM matching_pairs
                    WHERE question_id = ?
                    ORDER BY pair_order, id
                """, (question_id,))
                choices_text = "\n".join(f"{r['left_text']} ↔ {r['right_text']}" for r in cur.fetchall())
            elif question_id:
                cur.execute("""
                    SELECT label, text
                    FROM choices
                    WHERE question_id = ?
                    ORDER BY label
                """, (question_id,))
                choices_text = "\n".join(f"{r['label']} — {r['text']}" for r in cur.fetchall())

            correct_letters = md.get("correctLetters") or []
            selected_letters = md.get("selectedLetters") or []

            # Normalize types
            if isinstance(correct_letters, str):
                correct_letters = [correct_letters]
            if isinstance(selected_letters, str):
                selected_letters = [selected_letters]

            correct_letters = [str(x) for x in correct_letters if x]
            selected_letters = [str(x) for x in selected_letters if x]



            correct_text = ""
            selected_text = ""

            if question_type == "hotspot":
                correct_text = "\n".join(str(x) for x in (md.get("correctText") or []))
                selected_text = "\n".join(str(x) for x in (md.get("selectedText") or []))
            elif question_type == "matching":
                correct_text = "\n".join(str(x) for x in (md.get("correctText") or []))
                selected_text = "\n".join(str(x) for x in (md.get("selectedText") or []))
            elif question_id:
                # Resolve correct text
                cur.execute("""
                    SELECT label, text
                    FROM choices
                    WHERE question_id = ? AND is_correct = 1
                """, (question_id,))
                correct_text = "\n".join(
                    f"{r['label']} — {r['text']}"
                    for r in cur.fetchall()
                )

                # Resolve selected text
                if selected_letters:
                    cur.execute(f"""
                        SELECT label, text
                        FROM choices
                        WHERE question_id = ?
                        AND label IN ({",".join("?" * len(selected_letters))})
                    """, (question_id, *selected_letters))
                    selected_text = "\n".join(
                        f"{r['label']} — {r['text']}"
                        for r in cur.fetchall()
                    )

            cur.execute("""
                INSERT INTO missed_questions (
                    attempt_id,
                    attempt_question_number,
                    question_text,
                    choices_text,
                    correct_letters,
                    correct_text,
                    selected_letters,
                    selected_text,
                    question_type,
                    response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                missed_attempt_ref,
                aqn,
                question_text,
                choices_text,
                ",".join(correct_letters),
                correct_text,
                ",".join(selected_letters),
                selected_text,
                question_type,
                response_json,
            ))



        conn.commit()
        return jsonify({"ok": True, "attempt_id": attempt_id}), 200

    except Exception as e:
        conn.rollback()
        print(f"DB ERROR in /record_attempt: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()















def _quiz_history_origin(registry_entry, packs=None):
    """Return a user-facing origin label for History without changing DB schema."""
    entry = registry_entry if isinstance(registry_entry, dict) else {}
    explicit = str(entry.get("source_type") or "").strip().lower()
    explicit_labels = {
        "law": {"key": "law", "label": "Law"},
        "medical": {"key": "medical", "label": "Medical"},
        "it": {"key": "it", "label": "IT"},
        "study-pack": {"key": "study-pack", "label": "Study Pack"},
    }
    if explicit in explicit_labels:
        return explicit_labels[explicit]

    source_pack_id = str(entry.get("source_pack_id") or "").strip().lower()
    if source_pack_id:
        packs = packs if isinstance(packs, dict) else discover_content_packs()
        pack = packs.get(source_pack_id) or {}
        if _is_medical_pack_manifest(source_pack_id, pack):
            return {"key": "medical", "label": "Medical"}
        if _is_it_pack_manifest(source_pack_id, pack):
            return {"key": "it", "label": "IT"}
        return {"key": "study-pack", "label": "Study Pack"}
    return {"key": "quiz", "label": "Quiz"}


@app.route("/api/attempts")
def api_attempts():
    conn = get_db()
    cur = conn.cursor()

    # -------------------------
    # Detect schema variants
    # -------------------------
    cur.execute("PRAGMA table_info(attempts)")
    attempt_cols = {r[1] for r in cur.fetchall()}
    has_attempt_id_col = "attempt_id" in attempt_cols  # UI timestamp string storage

    # -------------------------
    # Load registry map (id -> entry)
    # -------------------------
    registry = load_registry()

    registry_map = {}
    installed_packs = discover_content_packs()
    for q in registry:
        rid = q.get("id", q.get("quiz_id", q.get("timestamp")))
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            continue
        registry_map[rid] = q

    # DEBUG - retained for troubleshooting attempt-to-quiz registry matching
# print(f"[DEBUG] Registry map keys: {sorted(registry_map.keys())}")

    # -------------------------
    # Query attempts
    # Return IDs that the UI actually uses (attempt_id string if available)
    # -------------------------
    if has_attempt_id_col:
        cur.execute("""
            SELECT
                a.id AS attempt_pk,
                a.attempt_id AS attempt_id,
                a.quiz_id,
                q.title AS db_quiz_title,
                a.score,
                a.total,
                a.percent,
                a.started_at,
                a.completed_at,
                a.time_remaining,
                a.mode
            FROM attempts a
            LEFT JOIN quizzes q ON q.id = a.quiz_id
            ORDER BY a.completed_at DESC
        """)
    else:
        cur.execute("""
            SELECT
                a.id AS attempt_pk,
                NULL AS attempt_id,
                a.quiz_id,
                q.title AS db_quiz_title,
                a.score,
                a.total,
                a.percent,
                a.started_at,
                a.completed_at,
                a.time_remaining,
                a.mode
            FROM attempts a
            LEFT JOIN quizzes q ON q.id = a.quiz_id
            ORDER BY a.completed_at DESC
        """)

    out = []

    rows = cur.fetchall()
    for row in rows:
        # Normalize quiz_id to int for registry lookup
        qid_raw = row["quiz_id"]
        try:
            quiz_id_norm = int(qid_raw)
        except (TypeError, ValueError):
            quiz_id_norm = qid_raw

        # Title resolution:
        # 1) Registry title (best for file-based quizzes)
        # 2) DB title
        # 3) Fallback
        quiz_title = None
        if isinstance(quiz_id_norm, int) and quiz_id_norm in registry_map:
            quiz_title = registry_map[quiz_id_norm].get("title")

        if not quiz_title:
            quiz_title = row["db_quiz_title"]

        if not quiz_title:
            quiz_title = "Unknown Quiz"

        # Choose the ID the UI should use in URLs:
        # - prefer attempts.attempt_id (timestamp string) when available
        # - else fall back to integer PK
        public_attempt_id = row["attempt_id"] or row["attempt_pk"]

        registry_entry = registry_map.get(quiz_id_norm, {}) if isinstance(quiz_id_norm, int) else {}
        origin = _quiz_history_origin(registry_entry, installed_packs)

        attempt_obj = {
            # UI fields expected by history/dashboard/review:
            "id": public_attempt_id,
            "quiz_id": quiz_id_norm,
            "quiz_title": quiz_title,
            "score": row["score"],
            "total": row["total"],
            "percent": row["percent"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "time_remaining": row["time_remaining"],
            "mode": row["mode"],
            "origin_key": origin["key"],
            "origin": origin["label"],
            "source_pack_id": registry_entry.get("source_pack_id") if isinstance(registry_entry, dict) else None,
            "source_dataset_id": registry_entry.get("source_dataset_id") if isinstance(registry_entry, dict) else None,

            # Extra debug/compat fields:
            "attempt_pk": row["attempt_pk"],
            "attempt_id": row["attempt_id"],

            # Some pages check this:
            "missedQuestions": []
        }

        # Attach missed questions (best-effort across schema variants)
        # Try by PK first, then by attempt_id string if needed.
        missed_rows = []
        try:
            cur.execute("""
                SELECT
                    attempt_question_number,
                    question_text,
                    correct_letters,
                    correct_text,
                    selected_letters,
                    selected_text
                FROM missed_questions
                WHERE attempt_id = ?
                ORDER BY attempt_question_number
            """, (row["attempt_pk"],))
            missed_rows = cur.fetchall()
        except Exception:
            missed_rows = []

        if not missed_rows and row["attempt_id"]:
            cur.execute("""
                SELECT
                    attempt_question_number,
                    question_text,
                    correct_letters,
                    correct_text,
                    selected_letters,
                    selected_text
                FROM missed_questions
                WHERE attempt_id = ?
                ORDER BY attempt_question_number
            """, (row["attempt_id"],))
            missed_rows = cur.fetchall()

        for m in missed_rows:
            attempt_obj["missedQuestions"].append({
                "attempt_question_number": m["attempt_question_number"],
                "question_text": m["question_text"],
                "correct_letters": m["correct_letters"],
                "correct_text": m["correct_text"],
                "selected_letters": m["selected_letters"],
                "selected_text": m["selected_text"],
            })

        out.append(attempt_obj)

    conn.close()

    # IMPORTANT: return object with "attempts" to satisfy dashboard/review.html
    return jsonify({"attempts": out})







# =====================================================
# ANKI EXPORT HELPERS
# =====================================================

import genanki
import random
import os
import tempfile
import html


def export_quiz_to_apkg(deck_name, deck_rows):
    """
    deck_rows = [
        {
            "front": str,
            "back": str
        }
    ]
    """

    model = genanki.Model(
        1607392319,
        "AutoQuiz Model",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "<hr id='answer'>{{Back}}",
            },
        ],
    )

    deck = genanki.Deck(
        random.randrange(1 << 30, 1 << 31),
        deck_name,
    )

    for row in deck_rows:
        # Escape FIRST (prevents invalid HTML warnings)
        front = html.escape(row.get("front") or "")
        back = html.escape(row.get("back") or "")

        # THEN restore intended formatting
        front = front.replace("\n", "<br>")
        back = back.replace("\n", "<br>")

        note = genanki.Note(
            model=model,
            fields=[front, back],
        )

        deck.add_note(note)

    fd, path = tempfile.mkstemp(suffix=".apkg")
    os.close(fd)

    genanki.Package(deck).write_to_file(path)

    return path








# =====================================================
# ANKI TOOLS WORKSPACE
# =====================================================

def build_anki_rows_for_quiz(quiz_id):
    """
    Build standard front/back rows for every question in one DLMS quiz.
    This is intentionally separate from the existing Study Mode and
    Review exports so those working workflows remain unchanged.
    """
    try:
        quiz_id = int(quiz_id)
    except (TypeError, ValueError):
        return None, []

    conn = get_db()
    cur = conn.cursor()

    quiz = cur.execute(
        """
        SELECT id, title
        FROM quizzes
        WHERE id = ?
        """,
        (quiz_id,)
    ).fetchone()

    if not quiz:
        conn.close()
        return None, []

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

    for question in questions:
        choices = cur.execute(
            """
            SELECT label, text, is_correct
            FROM choices
            WHERE question_id = ?
            ORDER BY label
            """,
            (question["id"],)
        ).fetchall()

        front_parts = [(question["question_text"] or "").strip()]

        if choices:
            front_parts.append("")
            for choice in choices:
                front_parts.append(
                    f"{choice['label']}. {(choice['text'] or '').strip()}"
                )

        correct_parts = [
            f"{choice['label']}. {(choice['text'] or '').strip()}"
            for choice in choices
            if choice["is_correct"]
        ]

        back = "Correct Answer"
        if correct_parts:
            back += "\n" + "\n".join(correct_parts)

        deck_rows.append({
            "front": "\n".join(front_parts).strip(),
            "back": back.strip(),
            "question_number": question["question_number"],
            "question_id": question["id"],
            "quiz_id": quiz_id,
        })

    conn.close()
    return quiz["title"] or "DLMS Quiz", deck_rows


def build_anki_rows_for_missed(quiz_id=None, min_misses=1, status_filter="all"):
    """
    Aggregate DLMS snapshot data from missed_questions and classify each
    question using later completed attempts of the same quiz.

    Status meanings:
      currently_weak = the most recent attempt for that quiz still missed it
      recovered      = a later completed attempt exists after the last miss
      repeated       = missed two or more times (can also be weak/recovered)
      once           = missed exactly once

    The existing two-argument calls remain backward compatible.
    """
    try:
        min_misses = max(1, min(int(min_misses or 1), 100))
    except (TypeError, ValueError):
        min_misses = 1

    status_filter = str(status_filter or "all").strip().lower()
    valid_filters = {"all", "currently_weak", "repeated", "recovered", "once"}
    if status_filter not in valid_filters:
        status_filter = "all"

    selected_quiz_id = None
    if quiz_id not in (None, "", "all"):
        try:
            selected_quiz_id = int(quiz_id)
        except (TypeError, ValueError):
            selected_quiz_id = None

    conn = get_db()
    cur = conn.cursor()

    # Completed attempts provide the timeline used to decide whether a
    # previously missed question was later recovered.
    attempt_sql = """
        SELECT id, quiz_id, completed_at
        FROM attempts
        WHERE completed_at IS NOT NULL
    """
    attempt_params = []

    if selected_quiz_id is not None:
        attempt_sql += " AND quiz_id = ? "
        attempt_params.append(selected_quiz_id)

    attempt_sql += """
        ORDER BY
            completed_at ASC,
            id ASC
    """

    attempt_rows = cur.execute(attempt_sql, attempt_params).fetchall()

    attempts_by_quiz = {}
    attempt_order = {}

    for position, row in enumerate(attempt_rows):
        qid = row["quiz_id"]
        attempts_by_quiz.setdefault(qid, []).append(row["id"])
        attempt_order[row["id"]] = position

    sql = """
        SELECT
            mq.id AS missed_id,
            mq.attempt_id,
            mq.question_id,
            mq.attempt_question_number,
            mq.question_text,
            mq.choices_text,
            mq.correct_text,
            mq.correct_letters,
            a.quiz_id,
            a.completed_at,
            qu.title AS quiz_title
        FROM missed_questions mq
        JOIN attempts a ON a.id = mq.attempt_id
        LEFT JOIN quizzes qu ON qu.id = a.quiz_id
        WHERE a.completed_at IS NOT NULL
    """
    params = []

    if selected_quiz_id is not None:
        sql += " AND a.quiz_id = ? "
        params.append(selected_quiz_id)

    sql += """
        ORDER BY
            a.completed_at DESC,
            a.id DESC,
            mq.id DESC
    """

    rows = cur.execute(sql, params).fetchall()
    conn.close()

    aggregated = {}

    for row in rows:
        question_text = (row["question_text"] or "").strip()
        if not question_text:
            continue

        question_id = row["question_id"]
        if question_id is not None:
            key = ("id", row["quiz_id"], question_id)
        else:
            key = ("text", row["quiz_id"], question_text.casefold())

        if key not in aggregated:
            aggregated[key] = {
                "question_text": question_text,
                "choices_text": (row["choices_text"] or "").strip(),
                "correct_text": (row["correct_text"] or "").strip(),
                "correct_letters": (row["correct_letters"] or "").strip(),
                "quiz_title": row["quiz_title"] or "Unknown Quiz",
                "quiz_id": row["quiz_id"],
                "question_number": row["attempt_question_number"],
                "question_id": row["question_id"],
                "miss_count": 0,
                "latest_miss_attempt_id": row["attempt_id"],
            }

        aggregated[key]["miss_count"] += 1

    cards = []

    for item in aggregated.values():
        if item["miss_count"] < min_misses:
            continue

        latest_miss_attempt_id = item["latest_miss_attempt_id"]
        quiz_attempt_ids = attempts_by_quiz.get(item["quiz_id"], [])
        latest_miss_position = attempt_order.get(latest_miss_attempt_id, -1)

        has_later_attempt = any(
            attempt_order.get(attempt_id, -1) > latest_miss_position
            for attempt_id in quiz_attempt_ids
        )

        recovery_status = "recovered" if has_later_attempt else "currently_weak"

        if status_filter == "currently_weak" and recovery_status != "currently_weak":
            continue
        if status_filter == "recovered" and recovery_status != "recovered":
            continue
        if status_filter == "repeated" and item["miss_count"] < 2:
            continue
        if status_filter == "once" and item["miss_count"] != 1:
            continue

        front_parts = [item["question_text"]]
        if item["choices_text"]:
            front_parts.extend(["", item["choices_text"]])

        correct = item["correct_text"] or item["correct_letters"]
        back_parts = ["Correct Answer"]
        if correct:
            back_parts.append(correct)

        back_parts.extend([
            "",
            f"Missed in DLMS: {item['miss_count']} "
            + ("times" if item["miss_count"] != 1 else "time"),
            "DLMS status: "
            + ("Currently Weak" if recovery_status == "currently_weak" else "Recovered Later"),
        ])

        cards.append({
            "front": "\n".join(front_parts).strip(),
            "back": "\n".join(back_parts).strip(),
            "quiz_title": item["quiz_title"],
            "quiz_id": item["quiz_id"],
            "question_number": item["question_number"],
            "question_id": item["question_id"],
            "miss_count": item["miss_count"],
            "recovery_status": recovery_status,
        })

    cards.sort(
        key=lambda x: (
            0 if x["recovery_status"] == "currently_weak" else 1,
            -x["miss_count"],
            str(x["quiz_title"]).casefold(),
            x["question_number"] if isinstance(x["question_number"], int) else 999999
        )
    )

    return cards


def get_anki_missed_summary(quiz_id=None):
    """
    Return non-destructive performance counts for the Anki Tools UI.
    Counts are derived from existing attempts/missed_questions data only.
    """
    all_cards = build_anki_rows_for_missed(quiz_id, 1, "all")

    return {
        "total": len(all_cards),
        "currently_weak": sum(
            1 for card in all_cards
            if card.get("recovery_status") == "currently_weak"
        ),
        "recovered": sum(
            1 for card in all_cards
            if card.get("recovery_status") == "recovered"
        ),
        "repeated": sum(
            1 for card in all_cards
            if int(card.get("miss_count") or 0) >= 2
        ),
        "once": sum(
            1 for card in all_cards
            if int(card.get("miss_count") or 0) == 1
        ),
    }

def parse_law_flashcards_text(raw_text):
    """
    Convert the Law Study Rule Flashcards section into front/back pairs.

    Recognized labels include:
      Front / Back
      Question / Answer
      Q / A

    Bullets and Markdown emphasis around the labels are tolerated.

    Standalone headings such as "Flashcard 1", "**Flashcard 2**", or
    "Flashcard #3:" are treated as separators only and are not included
    in the front or back of the exported Anki card.
    """
    text = str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    # AI-generated Law Study packets commonly number cards with standalone
    # headings. Without removing those headings, "Flashcard 3" can become
    # trailing text on Flashcard 2's Back field because the next Front label
    # is what normally ends the current block.
    flashcard_heading_pattern = re.compile(
        r"(?im)^\s*(?:[-*+]\s*)?(?:\*\*|__)?"
        r"flashcard\s*#?\s*\d+"
        r"(?:\*\*|__)?\s*:?\s*$"
    )
    text = flashcard_heading_pattern.sub("", text)

    label_pattern = re.compile(
        r"(?im)^\s*(?:[-*+]\s*)?(?:\*\*|__)?"
        r"(front|back|question|answer|q|a)"
        r"(?:\*\*|__)?\s*:\s*(.*)$"
    )

    matches = list(label_pattern.finditer(text))
    if not matches:
        return []

    pieces = []

    for idx, match in enumerate(matches):
        label = match.group(1).lower()
        inline_value = (match.group(2) or "").strip()
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        continuation = text[match.end():block_end].strip()

        value_parts = []
        if inline_value:
            value_parts.append(inline_value)
        if continuation:
            value_parts.append(continuation)

        value = "\n".join(value_parts).strip()

        if label in ("front", "question", "q"):
            normalized = "front"
        else:
            normalized = "back"

        pieces.append((normalized, value))

    cards = []
    pending_front = None

    for label, value in pieces:
        if label == "front":
            if pending_front:
                # A second front before a back means the prior card was incomplete.
                pending_front = value
            else:
                pending_front = value
        elif label == "back" and pending_front:
            if pending_front.strip() and value.strip():
                cards.append({
                    "front": pending_front.strip(),
                    "back": value.strip()
                })
            pending_front = None

    return cards

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
        with open(case_path, "r", encoding="utf-8") as f:
            case_data = json.load(f) or {}
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
    conn = get_db()
    rows = conn.execute(
        """
        SELECT
            qu.id,
            qu.title,
            COUNT(q.id) AS question_count
        FROM quizzes qu
        LEFT JOIN questions q ON q.quiz_id = qu.id
        GROUP BY qu.id, qu.title
        ORDER BY LOWER(qu.title), qu.id
        """
    ).fetchall()
    conn.close()

    return [
        {
            "id": row["id"],
            "title": row["title"] or f"Quiz {row['id']}",
            "question_count": row["question_count"] or 0,
        }
        for row in rows
    ]


def get_anki_law_case_choices():
    registry = load_law_registry()
    cases = registry.get("cases", []) or []
    results = []

    for case in cases:
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            continue

        meta, cards = load_law_flashcards_for_case(case_id)

        results.append({
            "id": case_id,
            "title": (meta or {}).get("title") or case.get("title") or "Untitled Case",
            "course": (meta or {}).get("course") or case.get("course") or "Uncategorized",
            "card_count": len(cards),
        })

    results.sort(
        key=lambda item: (
            str(item["course"]).casefold(),
            str(item["title"]).casefold()
        )
    )

    return results



def get_anki_law_courses(law_cases=None):
    law_cases = law_cases if law_cases is not None else get_anki_law_case_choices()
    course_map = {}

    for case in law_cases:
        course = str(case.get("course") or "Uncategorized").strip() or "Uncategorized"
        info = course_map.setdefault(course, {"course": course, "case_count": 0, "card_count": 0})
        info["case_count"] += 1
        info["card_count"] += int(case.get("card_count") or 0)

    return sorted(
        course_map.values(),
        key=lambda item: item["course"].casefold()
    )


def load_law_flashcards_for_selection(case_ids=None, course=None):
    """
    Combine Rule Flashcards from multiple saved cases or an entire course.
    Existing single-case loading remains unchanged.
    """
    law_cases = get_anki_law_case_choices()

    selected_ids = {
        str(case_id).strip()
        for case_id in (case_ids or [])
        if str(case_id).strip()
    }

    selected_course = str(course or "").strip()

    if selected_course:
        selected_cases = [
            case for case in law_cases
            if str(case.get("course") or "").strip().casefold() == selected_course.casefold()
        ]
    else:
        selected_cases = [
            case for case in law_cases
            if str(case.get("id") or "").strip() in selected_ids
        ]

    deck_rows = []
    loaded_cases = []

    for case in selected_cases:
        meta, cards = load_law_flashcards_for_case(case["id"])
        if not meta:
            continue

        loaded_cases.append(meta)

        for card in cards:
            row = dict(card)
            row["front"] = f"{meta['title']}\n\n{row.get('front', '')}".strip()
            deck_rows.append(row)

    selection_meta = {
        "course": selected_course or None,
        "case_count": len(loaded_cases),
        "case_titles": [case["title"] for case in loaded_cases],
    }

    return selection_meta, deck_rows



def get_anki_custom_sources():
    """
    Return selectable DLMS content for the Custom Anki Deck workspace.

    No data is copied or persisted. The workspace reads the same quiz,
    performance-history, and Law Study sources already used by Anki Tools.
    """
    quiz_groups = []
    for quiz in get_anki_quiz_choices():
        quiz_title, cards = build_anki_rows_for_quiz(quiz["id"])
        quiz_groups.append({
            "id": quiz["id"],
            "title": quiz_title or quiz["title"],
            "cards": cards,
        })

    missed_cards = build_anki_rows_for_missed(None, 1, "all")

    law_groups = []
    for case in get_anki_law_case_choices():
        meta, cards = load_law_flashcards_for_case(case["id"])
        law_groups.append({
            "id": case["id"],
            "title": (meta or {}).get("title") or case["title"],
            "course": (meta or {}).get("course") or case["course"],
            "cards": cards,
        })

    return {
        "quiz_groups": quiz_groups,
        "missed_cards": missed_cards,
        "law_groups": law_groups,
    }


def build_custom_anki_rows(quiz_tokens=None, missed_tokens=None, law_tokens=None):
    """
    Assemble selected DLMS content into one set of front/back rows.

    Token formats:
      quiz:<quiz_id>:<question_id>
      missed:<quiz_id>:<question_id-or-question-number>
      law:<case_id>:<1-based-card-index>
    """
    quiz_tokens = set(quiz_tokens or [])
    missed_tokens = set(missed_tokens or [])
    law_tokens = set(law_tokens or [])

    rows = []

    # Existing quiz questions.
    for quiz in get_anki_quiz_choices():
        quiz_title, cards = build_anki_rows_for_quiz(quiz["id"])
        for card in cards:
            token = f"quiz:{quiz['id']}:{card.get('question_id')}"
            if token not in quiz_tokens:
                continue

            row = dict(card)
            row["front"] = (
                f"{quiz_title}\n\n{row.get('front', '')}"
            ).strip()
            rows.append(row)

    # Performance-history questions.
    for card in build_anki_rows_for_missed(None, 1, "all"):
        stable_id = card.get("question_id")
        if stable_id is None:
            stable_id = card.get("question_number")

        token = f"missed:{card.get('quiz_id')}:{stable_id}"
        if token not in missed_tokens:
            continue

        row = dict(card)
        row["front"] = (
            f"{card.get('quiz_title', 'DLMS Quiz')}\n\n"
            f"{row.get('front', '')}"
        ).strip()
        rows.append(row)

    # Law Study flashcards.
    for case in get_anki_law_case_choices():
        meta, cards = load_law_flashcards_for_case(case["id"])
        if not meta:
            continue

        for index, card in enumerate(cards, start=1):
            token = f"law:{case['id']}:{index}"
            if token not in law_tokens:
                continue

            row = dict(card)
            row["front"] = (
                f"{meta['course']} · {meta['title']}\n\n"
                f"{row.get('front', '')}"
            ).strip()
            rows.append(row)

    # Avoid accidental duplicates when the same question is selected from
    # both the Quiz and Missed Questions sections.
    unique_rows = []
    seen = set()

    for row in rows:
        key = (
            str(row.get("front") or "").strip().casefold(),
            str(row.get("back") or "").strip().casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)

    return unique_rows


def make_safe_anki_download_name(name, fallback="dlms_anki_deck"):
    cleaned = secure_filename(str(name or "").strip())
    cleaned = os.path.splitext(cleaned)[0]
    if not cleaned:
        cleaned = fallback
    return f"{cleaned}.apkg"


@app.route("/anki")
def anki_tools():
    quizzes = get_anki_quiz_choices()

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

    <main class="dashboard-main anki-tools-main">
        <header class="dashboard-header anki-tools-header">
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
            <div>
                <div class="anki-tools-eyebrow">STUDY EXPORTS</div>
                <h1>Anki Tools</h1>
                <p>Build Anki decks from existing quizzes and your DLMS performance history. Law Study exports are available from the Anki Tools submenu.</p>
            </div>
        </header>

        <section class="anki-tools-summary" aria-label="Anki Tools summary">
            <div class="dashboard-stat-card">
                <span class="dashboard-stat-label">Quizzes</span>
                <strong>{{ quizzes|length }}</strong>
                <span class="dashboard-stat-note">available to export</span>
            </div>
            <div class="dashboard-stat-card">
                <span class="dashboard-stat-label">Missed Questions</span>
                <strong>{{ total_missed_cards }}</strong>
                <span class="dashboard-stat-note">{{ missed_summary.currently_weak }} weak · {{ missed_summary.repeated }} repeated · {{ missed_summary.recovered }} recovered</span>
            </div>
            <div class="dashboard-stat-card">
                <span class="dashboard-stat-label">Law Flashcards</span>
                <strong>{{ total_law_cards }}</strong>
                <span class="dashboard-stat-note">recognized cards</span>
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
    )




@app.route("/anki/custom", methods=["GET", "POST"])
def anki_custom_deck():
    sources = get_anki_custom_sources()

    deck_name = (request.form.get("deck_name") or "DLMS Custom Deck").strip()
    selected_quiz = request.form.getlist("quiz_cards")
    selected_missed = request.form.getlist("missed_cards")
    selected_law = request.form.getlist("law_cards")

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
                    <a class="dashboard-nav-subitem active" href="/anki/custom" aria-current="page"><span class="dashboard-nav-subicon">↳</span><span>Custom Deck</span></a>
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
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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
                           name="deck_name"
                           value="{{ deck_name }}"
                           maxlength="120"
                           required
                           style="width:100%;min-height:42px;box-sizing:border-box;padding:9px 11px;color:#eaf3ff;background:rgba(3,13,30,.78);border:1px solid rgba(91,146,215,.42);border-radius:9px;font:inherit;">
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
                    {% for quiz in quiz_groups %}
                    <details style="margin:10px 0;border:1px solid rgba(90,147,215,.20);border-radius:11px;background:rgba(3,13,29,.42);">
                        <summary style="cursor:pointer;padding:12px 14px;font-weight:700;">
                            {{ quiz.title }} · {{ quiz.cards|length }} questions
                        </summary>
                        <div style="padding:0 14px 12px;">
                            {% for card in quiz.cards %}
                            {% set token = "quiz:" ~ quiz.id ~ ":" ~ card.question_id %}
                            <label style="display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-top:1px solid rgba(90,147,215,.10);">
                                <input type="checkbox" name="quiz_cards" value="{{ token }}" {% if token in selected_quiz %}checked{% endif %}>
                                <span><strong>Q{{ card.question_number }}</strong> · {{ card.front.split("\n")[0] }}</span>
                            </label>
                            {% endfor %}
                        </div>
                    </details>
                    {% endfor %}
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
                <details open style="margin:10px 0;border:1px solid rgba(90,147,215,.20);border-radius:11px;background:rgba(3,13,29,.42);">
                    <summary style="cursor:pointer;padding:12px 14px;font-weight:700;">
                        Performance History · {{ missed_cards|length }} unique missed questions
                    </summary>
                    <div style="padding:0 14px 12px;max-height:420px;overflow:auto;">
                        {% for card in missed_cards %}
                        {% set stable_id = card.question_id if card.question_id is not none else card.question_number %}
                        {% set token = "missed:" ~ card.quiz_id ~ ":" ~ stable_id %}
                        <label style="display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-top:1px solid rgba(90,147,215,.10);">
                            <input type="checkbox" name="missed_cards" value="{{ token }}" {% if token in selected_missed %}checked{% endif %}>
                            <span>
                                <strong>{{ card.quiz_title }} · Q{{ card.question_number }}</strong><br>
                                {{ card.front.split("\n")[0] }}
                                <small style="display:block;margin-top:3px;color:#8fa7c1;">
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
                    {% for case in law_groups %}
                    <details style="margin:10px 0;border:1px solid rgba(90,147,215,.20);border-radius:11px;background:rgba(3,13,29,.42);">
                        <summary style="cursor:pointer;padding:12px 14px;font-weight:700;">
                            {{ case.course }} · {{ case.title }} · {{ case.cards|length }} cards
                        </summary>
                        <div style="padding:0 14px 12px;">
                            {% for card in case.cards %}
                            {% set token = "law:" ~ case.id ~ ":" ~ loop.index %}
                            <label style="display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-top:1px solid rgba(90,147,215,.10);">
                                <input type="checkbox" name="law_cards" value="{{ token }}" {% if token in selected_law %}checked{% endif %}>
                                <span><strong>Card {{ loop.index }}</strong> · {{ card.front.split("\n")[0] }}</span>
                            </label>
                            {% endfor %}
                        </div>
                    </details>
                    {% endfor %}
                {% else %}
                    <div class="anki-empty-message">No recognized Law Study flashcards are currently available.</div>
                {% endif %}
            </section>

            <section class="dashboard-panel anki-source-card anki-source-card-wide" style="margin-top:18px;">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <button type="submit"
                            class="anki-preview-button"
                            formaction="/anki/custom"
                            formmethod="POST">
                        Preview Deck
                    </button>
                    <button type="submit"
                            class="anki-export-button"
                            formaction="/anki/export/custom"
                            formmethod="POST">
                        Export .apkg
                    </button>
                </div>
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
        quiz_groups=sources["quiz_groups"],
        missed_cards=sources["missed_cards"],
        law_groups=sources["law_groups"],
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

    return send_file(
        apkg_path,
        as_attachment=True,
        download_name=make_safe_anki_download_name(
            deck_name,
            "DLMS_Custom_Deck"
        ),
        mimetype="application/octet-stream"
    )


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
            <button class="dashboard-menu-button" id="menuButton" type="button" aria-label="Toggle navigation">☰</button>
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

    return send_file(
        apkg_path,
        as_attachment=True,
        download_name=make_safe_anki_download_name(
            f"{quiz_title}_DLMS",
            "dlms_quiz"
        ),
        mimetype="application/octet-stream"
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

    return send_file(
        apkg_path,
        as_attachment=True,
        download_name=make_safe_anki_download_name(
            file_base,
            "dlms_missed_questions"
        ),
        mimetype="application/octet-stream"
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

    return send_file(
        apkg_path,
        as_attachment=True,
        download_name=make_safe_anki_download_name(
            file_base,
            "dlms_law_flashcards"
        ),
        mimetype="application/octet-stream"
    )

def export_anki_tsv_for_quiz(quiz_id: int) -> str:
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            q.number AS question_number,
            q.text   AS question_text,
            qu.title AS quiz_title,
            GROUP_CONCAT(
                c.label || '. ' || c.text,
                CHAR(10)
            ) AS choices,
            GROUP_CONCAT(
                CASE WHEN c.is_correct = 1 THEN c.label END,
                ', '
            ) AS correct_letters,
            GROUP_CONCAT(
                CASE WHEN c.is_correct = 1 THEN c.label || '. ' || c.text END,
                CHAR(10)
            ) AS correct_text
        FROM questions q
        JOIN quizzes qu ON qu.id = q.quiz_id
        JOIN choices c ON c.question_id = q.id
        WHERE q.quiz_id = ?
        GROUP BY q.id
        ORDER BY q.number
    """, (quiz_id,))

    rows = cur.fetchall()
    conn.close()

    lines = ["Front\tBack\tTags"]

    for r in rows:
        # ---------- FRONT ----------
        front = (
            f"<b>{r['question_text']}</b><br><br>"
            + "<br>".join((r["choices"] or "").split("\n"))
        ).replace("\t", " ")

        # ---------- BACK ----------
        back = (
            f"<b>Correct answer:</b> {r['correct_letters']}<br><br>"
            + "<br>".join((r["correct_text"] or "").split("\n"))
        ).replace("\t", " ")

        # ---------- TAGS ----------
        quiz_tag = (r["quiz_title"] or "autoquiz").replace(" ", "_")
        tags = quiz_tag

        lines.append(f"{front}\t{back}\t{tags}")

    return "\n".join(lines)


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

    return send_file(
        apkg_path,
        as_attachment=True,
        download_name="dlms_study_selected.apkg",
        mimetype="application/octet-stream"
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

    deck_name = rows[0]["quiz_title"] or "DLMS Missed Questions"

    apkg_path = export_quiz_to_apkg(deck_name, deck_rows)

    return send_file(
        apkg_path,
        as_attachment=True,
        download_name="dlms_missed_questions.apkg",
        mimetype="application/octet-stream"
    )







# =====================================================
# EXPORT MISSED QUESTIONS → TSV (ANKI IMPORT)
# =====================================================
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

    # TSV header required by Anki
    lines = ["Front\tBack\tTags"]

    for idx, r in enumerate(rows, start=1):
        if not r["question_text"]:
            logger.warning("[ANKI-TSV] Empty question_text | row=%s", idx)

        # ---------- FRONT ----------
        front_parts = [r["question_text"] or ""]
        if r["choices_text"]:
            front_parts.extend(["", r["choices_text"]])

        front = "\n".join(front_parts).replace("\t", " ")

        # ---------- BACK ----------
        back_parts = []
        if r["correct_letters"]:
            back_parts.append(f"Correct: {r['correct_letters']}")
        if r["correct_text"]:
            back_parts.append(r["correct_text"])

        back = "\n".join(back_parts).replace("\t", " ")

        # ---------- TAGS ----------
        quiz_tag = (r["quiz_title"] or "autoquiz").replace(" ", "_")
        tags = f"{quiz_tag} missed"

        lines.append(f"{front}\t{back}\t{tags}")

        if idx == 1:
            logger.debug("[ANKI-TSV] First card preview:\nFRONT:\n%s\nBACK:\n%s",
                         front[:500], back[:500])

    tsv = "\n".join(lines)

    logger.info("[ANKI-TSV] TSV generated | lines=%s | bytes=%s",
                len(lines), len(tsv.encode("utf-8")))

    return Response(
        tsv,
        mimetype="text/tab-separated-values; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=missed_questions_anki.tsv"
        }
    )




# Legacy endpoint intentionally disabled.
# Review data is now served exclusively via /api/attempts.
# Kept as a placeholder to prevent accidental reintroduction.

# @app.route("/api/missed_questions")
# def api_missed_questions():
#     return {"error": "Deprecated endpoint. Use /api/attempts."}, 410


@app.route("/api/missed_questions")
def api_missed_questions():
    attempt_id = request.args.get("attempt")

    if not attempt_id:
        return {"error": "Missing attempt id"}, 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            attempt_question_number,
            question_text,
            correct_text,
            correct_letters,
            selected_text,
            selected_letters,
            COALESCE(question_type, 'choice') AS question_type,
            response_json
        FROM missed_questions
        WHERE attempt_id = ?
        ORDER BY attempt_question_number
    """, (attempt_id,))


    rows = cur.fetchall()
    conn.close()

    return jsonify([
        {
            "attempt_question_number": r["attempt_question_number"],
            "question_text": r["question_text"],
            "correct_text": r["correct_text"],
            "correct_letters": r["correct_letters"],
            "selected_text": r["selected_text"],
            "selected_letters": r["selected_letters"],
            "question_type": r["question_type"],
            "response_data": (
                json.loads(r["response_json"])
                if r["response_json"] else None
            ),
        }
        for r in rows
    ])












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
            "error": str(e)
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
    import re, os

    global PARSE_LOG
    PARSE_LOG.clear()
    dbg("=== NEW PARSE SESSION STARTED ===")

    # Allow BOTH: file paths OR already-loaded quiz text
    if isinstance(source, str) and os.path.isfile(source):
        dbg("Input detected as FILE path → reading file")
        with open(source, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    else:
        dbg("Input detected as RAW TEXT → using directly")
        raw = source

    # Normalize newlines
    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    # Remove UTF-8 BOM if present
    text = text.lstrip("\ufeff")
    dbg("BOM stripped (if present)")

    # Split into question blocks
    blocks = re.split(
        r"(?=^\s*(?:Question\s*#?\s*\d+|\d+\s*[.) ]))",
        text,
        flags=re.IGNORECASE | re.MULTILINE
    )

    dbg("Total detected blocks:", len(blocks))

    questions = []
    fallback_number = 1

    for block in blocks:
        original_block = block
        block = block.strip()
        if not block:
            dbg("Skipped: empty block")
            continue

        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if len(lines) < 2:
            dbg("Skipped: too few lines:", repr(lines))
            continue

        qnum_match = re.match(
            r'^\s*(?:Question\s*#?\s*(\d+)|(\d+)\s*[.)])',
            lines[0],
            re.IGNORECASE
        )

        source_number = None
        if qnum_match:
            source_number = int(qnum_match.group(1) or qnum_match.group(2))

        q_number = source_number if source_number is not None else fallback_number

        dbg(f"\n--- Parsing Question Candidate #{q_number} ---")
        dbg(lines[0])

        q_lines = []
        raw_choices = []
        correct_letters = []
        choices_started = False

        for line in lines:
            lower = line.lower()

            # -------- Detect Choices --------
            mchoice = re.match(r"^\s*([A-Za-z])[\.\)]\s+(.*)", line)
            if mchoice:
                label = mchoice.group(1).upper()
                text_choice = mchoice.group(2).strip()
                dbg(f"Choice detected: {label} → {text_choice}")
                choices_started = True

                raw_choices.append({
                    "label": label,
                    "text": text_choice
                })
                continue

            # -------- Detect Correct Answer --------
            if "correct answer" in lower or "suggested answer" in lower:
                dbg("Found answer line:", line)

                m = re.search(r"[:\-]\s*([A-Za-z]+)", line)
                if m:
                    ans = re.sub(r"[^A-Za-z]", "", m.group(1)).upper()
                    if ans:
                        correct_letters = list(dict.fromkeys(list(ans)))
                        dbg("Parsed correct letters:", correct_letters)
                continue

            # -------- Question Text --------
            if not choices_started:
                if not (
                    lower.startswith("correct answer")
                    or lower.startswith("suggested answer")
                ):
                    q_lines.append(line)

        # ================================
        # VALIDATION
        # ================================
        if not correct_letters:
            dbg("!! Skipped: NO correct answer found")
            dbg(original_block[:200])
            continue

        if len(raw_choices) < 2:
            dbg("!! Skipped: Not enough choices:", raw_choices)
            continue

        # Build question text
        question_text = " ".join(q_lines)
        question_text = re.sub(
            r'^(?:Question\s*#?\s*\d+[\).\s-]*|\d+[\).\s-]*)\s*',
            '',
            question_text,
            flags=re.IGNORECASE
        ).strip()

        # ================================
        # FINALIZE CHOICES (ADD is_correct)
        # ================================
        choices = []
        for c in raw_choices:
            choices.append({
                "label": c["label"],
                "text": c["text"],
                "is_correct": c["label"] in correct_letters
            })

        dbg("Final Question Built:", question_text[:150])

        questions.append({
            "number": q_number,
            "question": question_text,
            "choices": choices,
            "correct": correct_letters
        })

        dbg("✓ Question Accepted\n")
        fallback_number += 1

    dbg("\n==== PARSE COMPLETE ====")
    dbg("Total questions parsed:", len(questions))

    return questions








# =========================
# CONFIDENCE ANALYZER (for preview only)
# =========================
def analyze_confidence(clean_text):
    """
    Heuristic pre-check of the raw text BEFORE parsing.
    Used only for preview so the user can see if their input
    looks parse-friendly.
    """
    import re

    blocks = re.split(
        r"(?=^\s*(?:Question\s*#?\s*\d+|\d+\s*[.) ]))",
        clean_text,
        flags=re.IGNORECASE | re.MULTILINE
    )

    details = []
    high = med = low = 0
    idx = 0

    for raw in blocks:
        block = raw.strip()
        if not block:
            continue

        idx += 1
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        txt = " ".join(lines)

        # Basic signals
        # Detect ANY lettered choices A–Z
        has_choice = any(re.match(r"^[A-Za-z][\.\)]\s+", l) for l in lines)

        has_answer_line = any(
            ("correct answer" in l.lower()) or ("suggested answer" in l.lower())
            for l in lines
        )
        num_choices = sum(
            1 for l in lines if re.match(r"^[A-Za-z][\.\)]\s+", l)

        )

        score = 0
        reason = []

        if has_choice:
            score += 1
            reason.append("Found A–Z answer choices")
        else:
            reason.append("No A–Z answer choices found")

        if has_answer_line:
            score += 1
            reason.append("Found 'Correct/Suggested Answer' line")
        else:
            reason.append("No explicit correct-answer line found")

        if num_choices >= 2:

            score += 1
            reason.append(f"{num_choices} choices detected")
        else:
            reason.append(f"{num_choices} choices detected (unusual count)")

        if score == 3:
            conf = "high"
            high += 1
        elif score == 2:
            conf = "medium"
            med += 1
        else:
            conf = "low"
            low += 1

        title = lines[0][:80] if lines else "[empty]"

        details.append({
            "index": idx,
            "title": title,
            "confidence": conf,
            "reason": "; ".join(reason),
        })

    summary = {
        "high": high,
        "medium": med,
        "low": low,
        "total": len(details),
    }
    return summary, details


# =========================
# QUIZ HTML BUILDER
# =========================

def build_quiz_html(name, jsonfile, outpath, portal_title, quiz_title, logo_filename, quiz_id, exam_minutes=90):
    exam_minutes = normalize_exam_minutes(exam_minutes)
    # Optional logo for mode banner (left/right)
    if logo_filename:
        mode_logo = f'<img src="/user-static/logos/{logo_filename}" class="mode-badge">'
    else:
        mode_logo = ""


    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{quiz_title}</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">

<!-- 🔑 Canonical quiz identity for script.js + DB -->
<script>
  window.quiz_title = "{quiz_title}";
  window.examDurationMinutes = {exam_minutes};
</script>

</head>

<body>

<!-- 🔹 Background is handled by /static/style.css importing /dynamic.css -->

<!-- 🔹 Overlay shown when exam is paused -->
<div id="pauseOverlay" class="pause-overlay">
    <div class="pause-overlay-content">
        <h2>Exam Paused</h2>
        <p>Your time is frozen. Click Resume to continue.</p>
        <button onclick="resumeExam()">Resume</button>
    </div>
</div>

<!-- 🔹 Everything that should blur goes inside this wrapper -->
<div id="quizWrapper" class="blur-wrapper">
    <div class="container">

        <!-- Readable Centered Banner -->
        <h1 class="hero-title">
            {portal_title}<br>
            <span style="font-size:20px;opacity:.85">{quiz_title}</span>
        </h1>

                <!-- Mode Select -->
        <div id="modeSelect" class="card quiz-mode-card">
            <div class="mode-banner">
                <div class="mode-logo-slot">
                    {mode_logo}
                </div>

                <div class="mode-center">
                    <h2>Select Mode</h2>

                    <div class="mode-button-row">
                        <button class="mode-btn study-mode-btn" onclick="startQuiz(false)">
                            📖 Study Mode
                        </button>

                        <button class="mode-btn exam-mode-btn" onclick="startQuiz(true)">
                            🛡️ Exam Mode
                        </button>
                    </div>
                </div>

                <div class="mode-logo-slot">
                    {mode_logo}
                </div>
            </div>
        </div>

                <!-- Quiz Area -->
        <div id="quiz" class="hidden quiz-shell">
                        <!-- Active Quiz Logo Banner -->
            <div class="active-quiz-logo-banner">
                <div class="active-logo-slot">
                    {mode_logo}
                </div>

                <div class="active-quiz-title">
                    {quiz_title}
                </div>

                <div class="active-logo-slot">
                    {mode_logo}
                </div>
            </div>

            <!-- TOP BAR -->
            <div class="top-bar quiz-toolbar">

                <!-- LEFT -->
                <div class="top-left">
                    <button onclick="submitQuiz()" id="submitBtn" class="danger">
                        📄 Submit Exam
                    </button>
                </div>

                <!-- RIGHT -->
                <div id="timer" class="hidden timerBox top-right quiz-timer-group">
                    <span id="timerLabel">Time Remaining:</span>
                    <span id="timeDisplay">--:--</span>
                    <button id="pauseBtn" onclick="pauseExam()">⏸ Pause</button>
                </div>

            </div>

            <!-- Progress Bar -->
            <div class="quiz-progress-card">
                <div class="quiz-progress-meta">
                    <span>Question Progress</span>
                    <span></span>
                </div>

                <div id="progressBarOuter">
                    <div id="progressBarInner"></div>
                </div>
            </div>

            <!-- Question Area -->
            <div class="quiz-question-card">
                <div id="qHeader"></div>
                <div id="qText"></div>
                <div id="choices"></div>
            </div>

            <!-- Navigation Controls -->
            <div class="controls quiz-nav-buttons">
                <button id="prevBtn" onclick="prev()">← Previous Question</button>

                <button id="nextBtn" onclick="next()">Next Question →</button>

                <button id="studyAiBtn"
                        type="button"
                        class="hidden"
                        onclick="reviewCurrentQuestionWithAI()">
                    ✨ Review This Question with AI
                </button>

                <button id="studyAnkiBtn"
                        type="button"
                        class="hidden"
                        onclick="toggleCurrentQuestionForAnki()">
                    ⭐ Mark for Anki
                </button>

                <button id="studyAnkiExportBtn"
                        type="button"
                        class="hidden"
                        onclick="exportStudyAnkiSelections()">
                    📦 Export Selected to Anki
                </button>
            </div>
        </div>

        <div id="result" class="hidden"></div>

        <br>

        <div class="quiz-return-buttons">
            <button id="returnPortalBtn" onclick="location.href='/'">
                🏠 Return To Dashboard
            </button>

            <button id="returnLibraryBtn" onclick="location.href='/library'">
                📚 Return To Quiz Library
            </button>
        </div>
</div>
</div>

<!-- 🔹 Tell script.js which quiz + JSON file to load -->
<script>
  const QUIZ_FILE = "/data/{jsonfile}";
  window.QUIZ_ID = {quiz_id};
</script>

<script src="/static/script.js"></script>


<script src="/static/nav-normalize.js"></script>
</body>
</html>
"""

    with open(outpath, "w", encoding="utf-8") as f:
        f.write(html)





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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # 🔒 Ensure schema is always up to date
    ensure_schema(conn)

    return conn




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


def ensure_schema(conn):
    cur = conn.cursor()

    # -------------------------------------------------
    # Introspect existing schema (if table exists)
    # -------------------------------------------------
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='missed_questions'
    """)
    table_exists = cur.fetchone() is not None

    cols = {}
    if table_exists:
        cur.execute("PRAGMA table_info(missed_questions)")
        cols = {row[1]: row for row in cur.fetchall()}

    # -------------------------------------------------
    # Helper flags (explicit, no assumptions)
    # -------------------------------------------------
    has_question_id = "question_id" in cols
    has_question_text = "question_text" in cols
    has_choices_text = "choices_text" in cols
    has_correct_text = "correct_text" in cols
    has_selected_text = "selected_text" in cols
    has_attempt_qnum = "attempt_question_number" in cols

    qid_col = cols.get("question_id")
    qid_not_null = qid_col and qid_col[3] == 1  # NOT NULL flag

    # -------------------------------------------------
    # FULL REBUILD REQUIRED?
    #
    # Rebuild if:
    #  - table exists AND
    #  - question_id is NOT NULL (legacy constraint)
    #
    # Rebuild is SAFE because we NEVER reference
    # missing columns — we inject NULLs explicitly.
    # -------------------------------------------------
    if table_exists and qid_not_null:
        print("[DB MIGRATION] Rebuilding missed_questions (safe rebuild, binary-compatible)")

        cur.executescript("""
            BEGIN;

            ALTER TABLE missed_questions RENAME TO missed_questions_old;

            CREATE TABLE missed_questions (
                id INTEGER PRIMARY KEY,
                attempt_id TEXT NOT NULL,
                question_id INTEGER,
                correct_letters TEXT,
                question_text TEXT,
                choices_text TEXT,
                selected_letters TEXT,
                selected_text TEXT,
                correct_text TEXT,
                attempt_question_number INTEGER,
                question_type TEXT DEFAULT 'choice',
                response_json TEXT
            );
        """)

        # -------------------------------------------------
        # Build SELECT list dynamically — NO ASSUMPTIONS
        # -------------------------------------------------
        def col_or_null(name):
            return name if name in cols else "NULL AS " + name

        insert_sql = f"""
            INSERT INTO missed_questions (
                id,
                attempt_id,
                question_id,
                correct_letters,
                question_text,
                choices_text,
                selected_letters,
                selected_text,
                correct_text,
                attempt_question_number,
                question_type,
                response_json
            )
            SELECT
                id,
                attempt_id,
                {col_or_null("question_id")},
                {col_or_null("correct_letters")},
                {col_or_null("question_text")},
                {col_or_null("choices_text")},
                {col_or_null("selected_letters")},
                {col_or_null("selected_text")},
                {col_or_null("correct_text")},
                {col_or_null("attempt_question_number")},
                {col_or_null("question_type")},
                {col_or_null("response_json")}
            FROM missed_questions_old;
        """

        cur.execute(insert_sql)
        cur.execute("DROP TABLE missed_questions_old")
        conn.commit()

        # Refresh schema info after rebuild
        cur.execute("PRAGMA table_info(missed_questions)")
        cols = {row[1]: row for row in cur.fetchall()}

    # -------------------------------------------------
    # INCREMENTAL ADD-COLUMN MIGRATIONS
    # (for non-rebuild cases)
    # -------------------------------------------------
    migrations = []

    def add_col(name, coldef):
        if name not in cols:
            migrations.append(f"ALTER TABLE missed_questions ADD COLUMN {name} {coldef}")

    add_col("question_id", "INTEGER")
    add_col("question_text", "TEXT")
    add_col("choices_text", "TEXT")
    add_col("correct_letters", "TEXT")
    add_col("selected_letters", "TEXT")
    add_col("selected_text", "TEXT")
    add_col("correct_text", "TEXT")
    add_col("attempt_question_number", "INTEGER")
    add_col("question_type", "TEXT DEFAULT 'choice'")
    add_col("response_json", "TEXT")

    for sql in migrations:
        print("[DB MIGRATION]", sql)
        cur.execute(sql)

    if migrations:
        conn.commit()

    # =================================================
    # QUIZZES TABLE MIGRATION (ADD REGISTRY ID)
    # =================================================
    cur.execute("PRAGMA table_info(quizzes)")
    quiz_cols = {row[1] for row in cur.fetchall()}

    if "registry_id" not in quiz_cols:
        print("[DB MIGRATION] Adding registry_id column to quizzes")
        cur.execute("ALTER TABLE quizzes ADD COLUMN registry_id INTEGER")
        conn.commit()

    # =================================================
    # QUESTIONS TABLE MIGRATION (QUESTION TYPE)
    # =================================================
    cur.execute("PRAGMA table_info(questions)")
    question_cols = {row[1] for row in cur.fetchall()}

    if "question_type" not in question_cols:
        print("[DB MIGRATION] Adding question_type column to questions")
        cur.execute("ALTER TABLE questions ADD COLUMN question_type TEXT NOT NULL DEFAULT 'choice'")
        conn.commit()

    question_migrations = {
        "matching_round_size": "INTEGER",
        "matching_direction": "TEXT NOT NULL DEFAULT 'term_to_definition'",
        "source_organization": "TEXT",
        "source_dataset": "TEXT",
        "source_version": "TEXT",
        "source_url": "TEXT",
        "source_license": "TEXT",
        "explanation": "TEXT",
        "media_json": "TEXT",
    }
    cur.execute("PRAGMA table_info(questions)")
    question_cols = {row[1] for row in cur.fetchall()}
    for col, definition in question_migrations.items():
        if col not in question_cols:
            print(f"[DB MIGRATION] Adding questions.{col}")
            cur.execute(f"ALTER TABLE questions ADD COLUMN {col} {definition}")
    conn.commit()

    # =================================================
    # MATCHING PAIRS TABLE
    # =================================================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS matching_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            pair_order INTEGER NOT NULL,
            left_text TEXT NOT NULL,
            right_text TEXT NOT NULL,
            category TEXT,
            explanation TEXT,
            verification_json TEXT,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        )
    """)
    cur.execute("PRAGMA table_info(matching_pairs)")
    matching_pair_cols = {row[1] for row in cur.fetchall()}
    matching_pair_migrations = {
        "category": "TEXT",
        "explanation": "TEXT",
        "verification_json": "TEXT",
    }
    for col, definition in matching_pair_migrations.items():
        if col not in matching_pair_cols:
            print(f"[DB MIGRATION] Adding matching_pairs.{col}")
            cur.execute(f"ALTER TABLE matching_pairs ADD COLUMN {col} {definition}")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_matching_pairs_question ON matching_pairs(question_id)")
    conn.commit()





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
    conn = get_db()
    cur = conn.cursor()

    # 1️⃣ Pull all attempts with quiz name
    cur.execute("""
        SELECT 
            a.id,
            q.title AS quiz_title,
            a.score,
            a.total,
            a.percent,
            a.mode,
            a.started_at,
            a.completed_at,
            a.time_remaining
        FROM attempts a
        LEFT JOIN quizzes q ON a.quiz_id = q.id
        ORDER BY a.completed_at DESC
    """)
    attempts = cur.fetchall()

    results = []

    for row in attempts:
        attempt_id = row["id"]

        # 2️⃣ Pull missed questions for this attempt
        cur.execute("""
            SELECT
                question_number,
                question_text,
                correct_letters,
                correct_text,
                selected_letters,
                selected_text
            FROM missed_questions
            WHERE attempt_id = ?
        """, (attempt_id,))

        missed = [dict(m) for m in cur.fetchall()]

        results.append({
            "id": row["id"],
            "quiz_title": row["quiz_title"] or "Unknown Quiz",
            "score": row["score"],
            "total": row["total"],
            "percent": row["percent"],
            "mode": row["mode"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "time_remaining": row["time_remaining"],
            "missed": missed
        })

    conn.close()
    return jsonify(results)


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
if __name__ == "__main__":
    #purge_legacy_quizzes()   # REMOVE after one run

    app.run(
        host="0.0.0.0",
        port=9001,
        debug=False,
        use_reloader=False
    )


