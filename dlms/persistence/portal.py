"""Persistence and normalization helpers for DLMS portal settings."""

import json
import os

from dlms.persistence import json_files
from dlms.themes import normalize_theme
from dlms.services import certification_display


DASHBOARD_CARD_GROUPS = (
    ("Panels", (("welcome", "Welcome"), ("daily_review", "Study next & Continue studying"),
                ("recent_activity", "Recent quiz activity"), ("certifications", "My Certifications"), ("overview", "Results overview"))),
    ("Quick access", (("library", "Quiz Library"), ("build", "Build Quiz"),
                      ("study_packs", "Study Packs"), ("it", "IT Study"),
                      ("law", "Law Study"), ("medical", "Medical Study"),
                      ("study_history", "Study History"), ("history", "Exam History"), ("analytics", "Analytics"),
                      ("settings", "Settings"))),
)


def dashboard_card_defaults():
    return {key: True for _, cards in DASHBOARD_CARD_GROUPS for key, _ in cards}


def _portal_defaults(
    *,
    default_theme,
    default_ai_feedback_prompt,
    default_law_ai_prompt,
    default_study_content_pack_prompt,
    default_medical_study_pack_ai_addendum,
):
    return {
        "title": "Training & Practice Center",
        "dashboard_card_visibility": dashboard_card_defaults(),
        "show_certifications": True,
        "certification_display_count": "3",
        "certification_sort": "earned",
        "show_confidence": True,
        "enable_regex_replace": False,
        "background_image": None,
        "theme": default_theme,
        "quiz_folders": ["Uncategorized"],
        "hidden_quiz_folders": [],
        "excluded_learning_folders": [],
        "study_area_visibility": {
            "it": True,
            "law": True,
            "medical": True,
            "other": True,
        },
        "automatic_browser_shutdown_enabled": False,

        # AI Explanation Helper
        "ai_helper_enabled": True,
        "ai_provider": "chatgpt",
        "ai_custom_url": "",
        "ai_auto_copy_prompt": True,
        "ai_prompt_template": default_ai_feedback_prompt,
        "law_ai_prompt_template": default_law_ai_prompt,
        "study_pack_ai_prompt_template": default_study_content_pack_prompt,
        "medical_study_pack_ai_addendum": default_medical_study_pack_ai_addendum,
    }


def load_portal_config(
    portal_path,
    *,
    default_theme,
    default_ai_feedback_prompt,
    default_law_ai_prompt,
    default_study_content_pack_prompt,
    default_medical_study_pack_ai_addendum,
    validate_custom_ai_url,
    atomic_write_json=json_files._atomic_write_json,
    preserve_malformed_json=json_files._preserve_malformed_json,
):
    default = _portal_defaults(
        default_theme=default_theme,
        default_ai_feedback_prompt=default_ai_feedback_prompt,
        default_law_ai_prompt=default_law_ai_prompt,
        default_study_content_pack_prompt=default_study_content_pack_prompt,
        default_medical_study_pack_ai_addendum=default_medical_study_pack_ai_addendum,
    )

    # Ensure config directory exists
    os.makedirs(os.path.dirname(portal_path), exist_ok=True)

    # First run: create portal.json
    if not os.path.exists(portal_path):
        try:
            atomic_write_json(portal_path, default, expected_type=dict)
            print("[PORTAL CONFIG] Created default portal.json")
        except Exception as e:
            print("[PORTAL CONFIG][ERROR] Failed to create portal.json:", e)

        return default.copy()

    # Normal load (MERGE, do not FILTER)
    try:
        with open(portal_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeError) as e:
        try:
            preserve_malformed_json(portal_path)
        except Exception as preserve_error:
            raise RuntimeError(
                "Malformed portal.json could not be preserved safely"
            ) from preserve_error
        print("[PORTAL CONFIG][ERROR] Failed to load portal.json:", e)
        return default.copy()
    except Exception as e:
        print("[PORTAL CONFIG][ERROR] Failed to load portal.json:", e)
        return default.copy()

    if not isinstance(data, dict):
        try:
            preserve_malformed_json(portal_path)
        except Exception as preserve_error:
            raise RuntimeError(
                "Malformed portal.json could not be preserved safely"
            ) from preserve_error
        print("[PORTAL CONFIG][ERROR] portal.json must contain a JSON object")
        return default.copy()

    malformed_quiz_folders = (
        "quiz_folders" in data and not isinstance(data["quiz_folders"], list)
    )
    malformed_hidden_quiz_folders = (
        "hidden_quiz_folders" in data
        and (
            not isinstance(data["hidden_quiz_folders"], list)
            or any(
                not isinstance(folder, str)
                for folder in data["hidden_quiz_folders"]
            )
        )
    )
    malformed_excluded_learning_folders = (
        "excluded_learning_folders" in data
        and (
            not isinstance(data["excluded_learning_folders"], list)
            or any(not isinstance(folder, str) for folder in data["excluded_learning_folders"])
        )
    )
    malformed_study_area_visibility = (
        "study_area_visibility" in data
        and not isinstance(data["study_area_visibility"], dict)
    )
    malformed_dashboard_visibility = (
        "dashboard_card_visibility" in data
        and not isinstance(data["dashboard_card_visibility"], dict)
    )
    if (
        malformed_quiz_folders
        or malformed_hidden_quiz_folders
        or malformed_excluded_learning_folders
        or malformed_study_area_visibility
        or malformed_dashboard_visibility
    ):
        preserve_malformed_json(portal_path)

    # Preserve the original malformed document first, then ensure a structured
    # field cannot be merged into active configuration in the wrong shape.
    # study_area_visibility is normalized below before use; quiz_folders needs
    # the same boundary because get_quiz_folders() iterates its value directly.
    if malformed_quiz_folders:
        data = data.copy()
        data["quiz_folders"] = list(default["quiz_folders"])
    if malformed_hidden_quiz_folders:
        data = data.copy()
        data["hidden_quiz_folders"] = []
    if malformed_excluded_learning_folders:
        data = data.copy()
        data["excluded_learning_folders"] = []

    # Merge defaults with stored values
    cfg = default.copy()
    cfg.update(data)
    # An absent or malformed setting always retains the pre-scope behavior.
    cfg["excluded_learning_folders"] = clean_excluded_learning_folders(
        cfg.get("excluded_learning_folders")
    )

    # Normalize booleans (checkbox safety)
    cfg["show_confidence"] = bool(cfg.get("show_confidence", False))
    cfg["enable_regex_replace"] = bool(cfg.get("enable_regex_replace", False))
    cfg["automatic_browser_shutdown_enabled"] = bool(
        cfg.get("automatic_browser_shutdown_enabled", False)
    )

    # Normalize title
    cfg["title"] = str(cfg.get("title") or default["title"]).strip()

    # Normalize background
    bg = cfg.get("background_image")
    cfg["background_image"] = bg.strip() if isinstance(bg, str) and bg.strip() else None

    cfg["theme"] = normalize_theme(cfg.get("theme"), default_theme)

    cfg["ai_helper_enabled"] = bool(cfg.get("ai_helper_enabled", False))
    cfg["ai_auto_copy_prompt"] = bool(cfg.get("ai_auto_copy_prompt", True))

    valid_ai_providers = {"chatgpt", "claude", "gemini", "local"}
    provider = str(cfg.get("ai_provider") or "chatgpt").strip().lower()
    cfg["ai_provider"] = provider if provider in valid_ai_providers else "chatgpt"

    try:
        cfg["ai_custom_url"] = validate_custom_ai_url(cfg.get("ai_custom_url"))
    except ValueError:
        # Legacy or manually edited settings remain loadable, but an unsafe
        # target is never exposed to browser-side launch helpers.
        cfg["ai_custom_url"] = ""

    raw_study_area_visibility = cfg.get("study_area_visibility")
    if not isinstance(raw_study_area_visibility, dict):
        raw_study_area_visibility = {}
    cfg["study_area_visibility"] = {
        key: raw_study_area_visibility.get(key)
        if isinstance(raw_study_area_visibility.get(key), bool)
        else True
        for key in ("it", "law", "medical", "other")
    }

    cfg["show_certifications"] = cfg.get("show_certifications") if isinstance(cfg.get("show_certifications"), bool) else True
    for key, validator, default in (('certification_display_count', certification_display.count, '3'), ('certification_sort', certification_display.sort, 'earned')):
        try:cfg[key] = validator(cfg.get(key, default))
        except ValueError:cfg[key] = default
    raw_dashboard = cfg.get("dashboard_card_visibility")
    if not isinstance(raw_dashboard, dict):
        raw_dashboard = {}
    defaults = dashboard_card_defaults()
    # An added shortcut must not reappear for someone who hid History.
    defaults["study_history"] = raw_dashboard.get("history") if isinstance(raw_dashboard.get("history"), bool) else True
    cfg["dashboard_card_visibility"] = {
        key: raw_dashboard[key] if isinstance(raw_dashboard.get(key), bool) else default
        for key, default in defaults.items()
    }
    return cfg


def save_portal_config(
    portal_path,
    title,
    show_confidence=False,
    enable_regex_replace=False,
    background_image=None,
    *,
    load_config,
    atomic_write_json=json_files._atomic_write_json,
):
    cfg = load_config()

    cfg["title"] = title
    cfg["show_confidence"] = bool(show_confidence)
    cfg["enable_regex_replace"] = bool(enable_regex_replace)

    if background_image is not None:
        cfg["background_image"] = background_image

    atomic_write_json(portal_path, cfg, expected_type=dict)


def get_quiz_folders(*, load_config):
    cfg = load_config()

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


def clean_excluded_learning_folders(value):
    """Validate case-insensitive folder identities without guessing bad data."""
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return []
    cleaned = []
    seen = set()
    for item in value:
        name = item.strip()
        key = name.lower()
        if not name or key in seen:
            continue
        cleaned.append(name)
        seen.add(key)
    return cleaned


def save_quiz_folders(
    portal_path,
    folders,
    *,
    load_config,
    atomic_write_json=json_files._atomic_write_json,
    clean_hidden_quiz_folders=None,
):
    if clean_hidden_quiz_folders is None:
        clean_hidden_quiz_folders = _clean_hidden_quiz_folders

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

    cfg = load_config()
    cfg["quiz_folders"] = cleaned
    cfg["hidden_quiz_folders"] = clean_hidden_quiz_folders(
        cfg.get("hidden_quiz_folders"), cleaned
    )

    atomic_write_json(portal_path, cfg, expected_type=dict)


def _clean_hidden_quiz_folders(hidden_folders, configured_folders):
    """Return safe hidden-folder names using configured display spelling."""
    if not isinstance(hidden_folders, list):
        return []

    configured_by_key = {
        folder.lower(): folder
        for folder in configured_folders
        if folder.lower() != "uncategorized"
    }
    cleaned = []
    seen = set()

    for folder in hidden_folders:
        if not isinstance(folder, str):
            continue
        key = folder.strip().lower()
        if not key or key == "uncategorized" or key in seen:
            continue
        configured_name = configured_by_key.get(key)
        if configured_name is None:
            continue
        cleaned.append(configured_name)
        seen.add(key)

    return cleaned


def get_hidden_quiz_folders(
    configured_folders=None,
    *,
    get_folders,
    load_config,
    clean_hidden_quiz_folders=None,
):
    if clean_hidden_quiz_folders is None:
        clean_hidden_quiz_folders = _clean_hidden_quiz_folders
    folders = configured_folders or get_folders()
    cfg = load_config()
    return clean_hidden_quiz_folders(
        cfg.get("hidden_quiz_folders"), folders
    )


def save_quiz_folder_state(
    portal_path,
    folders,
    hidden_folders,
    *,
    load_config,
    atomic_write_json=json_files._atomic_write_json,
    clean_hidden_quiz_folders=None,
    excluded_learning_folders=None,
):
    """Persist folder order and hidden state together in portal.json."""
    if clean_hidden_quiz_folders is None:
        clean_hidden_quiz_folders = _clean_hidden_quiz_folders
    cleaned_folders = []
    seen = set()

    for folder in folders:
        name = str(folder or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        cleaned_folders.append(name)
        seen.add(key)

    if "uncategorized" not in seen:
        cleaned_folders.insert(0, "Uncategorized")

    cfg = load_config()
    cfg["quiz_folders"] = cleaned_folders
    cfg["hidden_quiz_folders"] = clean_hidden_quiz_folders(
        hidden_folders, cleaned_folders
    )
    if excluded_learning_folders is not None:
        cfg["excluded_learning_folders"] = clean_excluded_learning_folders(
            excluded_learning_folders
        )
    atomic_write_json(portal_path, cfg, expected_type=dict)


def get_portal_title(*, load_config):
    return load_config().get("title", "Training & Practice Center")


def get_confidence_setting(*, load_config):
    return load_config().get("show_confidence", False)
