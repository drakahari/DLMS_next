"""Persistence and normalization helpers for DLMS portal settings."""

import json
import os

from dlms.persistence import json_files


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
        "show_confidence": True,
        "enable_regex_replace": False,
        "background_image": None,
        "theme": default_theme,
        "quiz_folders": ["Uncategorized"],
        "hidden_quiz_folders": [],
        "study_area_visibility": {
            "it": True,
            "law": True,
            "medical": True,
            "other": True,
        },

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
    malformed_study_area_visibility = (
        "study_area_visibility" in data
        and not isinstance(data["study_area_visibility"], dict)
    )
    if (
        malformed_quiz_folders
        or malformed_hidden_quiz_folders
        or malformed_study_area_visibility
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

    valid_themes = {"dark", "light", "purple-gold", "maroon-gold"}
    theme = str(cfg.get("theme") or default_theme).strip().lower()
    cfg["theme"] = theme if theme in valid_themes else default_theme

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
    atomic_write_json(portal_path, cfg, expected_type=dict)


def get_portal_title(*, load_config):
    return load_config().get("title", "Training & Practice Center")


def get_confidence_setting(*, load_config):
    return load_config().get("show_confidence", False)
