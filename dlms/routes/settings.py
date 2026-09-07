"""Settings configuration routes."""

import html
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, jsonify, redirect, render_template, request


Dependency = Callable[..., Any]
THEMES = {"dark", "light", "purple-gold", "maroon-gold"}
AI_PROVIDERS = {"chatgpt", "claude", "gemini", "local"}


@dataclass(frozen=True)
class SettingsRouteDependencies:
    """Configured application services required by Settings routes."""

    default_theme: Dependency
    default_law_ai_prompt: Dependency
    default_study_content_pack_prompt: Dependency
    default_medical_study_pack_ai_addendum: Dependency
    load_portal_config: Dependency
    write_portal_config: Dependency
    store_background_upload: Dependency
    validate_custom_ai_url: Dependency
    print_message: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def settings_page(_dependencies):
    """Settings landing page for the completed category-based settings UI."""
    return render_template("settings/index.html")


def settings_navigation_page(dependencies):
    cfg = dependencies.load_portal_config()
    visibility = cfg["study_area_visibility"]
    return render_template("settings/navigation.html", visibility=visibility)


def save_navigation_settings(dependencies):
    cfg = dependencies.load_portal_config()
    cfg["study_area_visibility"] = {
        "it": "study_area_it" in request.form,
        "law": "study_area_law" in request.form,
        "medical": "study_area_medical" in request.form,
        "other": "study_area_other" in request.form,
    }
    dependencies.write_portal_config(cfg)
    return redirect("/settings/navigation?saved=1")


def settings_appearance_page(dependencies):
    cfg = dependencies.load_portal_config()
    return render_template("settings/appearance.html", cfg=cfg)


def save_appearance_settings(dependencies):
    """Save only Appearance settings without changing other categories."""
    cfg = dependencies.load_portal_config()
    default_theme = dependencies.default_theme()
    requested_theme = str(
        request.form.get("theme") or cfg.get("theme") or default_theme
    ).strip().lower()
    cfg["theme"] = requested_theme if requested_theme in THEMES else default_theme

    title = request.form.get("portal_title", "").strip()
    if title:
        cfg["title"] = title

    upload = request.files.get("background_image")
    if upload and upload.filename and upload.filename.strip():
        try:
            cfg["background_image"] = dependencies.store_background_upload(upload)
        except ValueError as exc:
            return f"Invalid background image: {html.escape(str(exc))}", 400

    dependencies.write_portal_config(cfg)
    return redirect("/settings/appearance?saved=1")


def api_set_theme(dependencies):
    cfg = dependencies.load_portal_config()
    payload = request.get_json(silent=True) or request.form
    requested = str(payload.get("theme") or "").strip().lower()
    if requested not in THEMES:
        return jsonify({"ok": False, "error": "Unsupported theme"}), 400
    cfg["theme"] = requested
    dependencies.write_portal_config(cfg)
    return jsonify({"ok": True, "theme": requested})


def settings_ai_page(dependencies):
    cfg = dependencies.load_portal_config()
    study_prompt = dependencies.default_study_content_pack_prompt()
    medical_addendum = dependencies.default_medical_study_pack_ai_addendum()
    law_prompt = dependencies.default_law_ai_prompt()

    cfg.setdefault("ai_helper_enabled", False)
    cfg.setdefault("ai_provider", "chatgpt")
    cfg.setdefault("ai_custom_url", "")
    cfg.setdefault("ai_auto_copy_prompt", True)
    cfg.setdefault("ai_prompt_template", "")
    cfg.setdefault("study_pack_ai_prompt_template", study_prompt)
    cfg.setdefault("medical_study_pack_ai_addendum", medical_addendum)
    cfg.setdefault("law_ai_prompt_template", law_prompt)

    return render_template(
        "settings/ai.html",
        cfg=cfg,
        law_default_prompt=law_prompt,
        study_pack_default_prompt=study_prompt,
        medical_study_pack_default_addendum=medical_addendum,
    )


def save_ai_settings(dependencies):
    """Save only AI Integration settings."""
    cfg = dependencies.load_portal_config()
    cfg["ai_helper_enabled"] = "ai_helper_enabled" in request.form
    cfg["ai_auto_copy_prompt"] = "ai_auto_copy_prompt" in request.form

    provider = request.form.get("ai_provider", "chatgpt").strip().lower()
    cfg["ai_provider"] = provider if provider in AI_PROVIDERS else "chatgpt"

    try:
        cfg["ai_custom_url"] = dependencies.validate_custom_ai_url(
            request.form.get("ai_custom_url", "")
        )
    except ValueError as exc:
        return str(exc), 400

    cfg["ai_prompt_template"] = request.form.get(
        "ai_prompt_template", ""
    ).strip()
    cfg["study_pack_ai_prompt_template"] = (
        request.form.get("study_pack_ai_prompt_template", "").strip()
        or dependencies.default_study_content_pack_prompt()
    )
    cfg["medical_study_pack_ai_addendum"] = (
        request.form.get("medical_study_pack_ai_addendum", "").strip()
        or dependencies.default_medical_study_pack_ai_addendum()
    )
    cfg["law_ai_prompt_template"] = (
        request.form.get("law_ai_prompt_template", "").strip()
        or dependencies.default_law_ai_prompt()
    )

    dependencies.write_portal_config(cfg)
    return redirect("/settings/ai?saved=1")


def settings_parsing_page(dependencies):
    cfg = dependencies.load_portal_config()
    cfg.setdefault("show_confidence", True)
    cfg.setdefault("enable_regex_replace", False)
    cfg.setdefault("auto_bom_clean", False)
    cfg.setdefault("enable_show_invisibles", True)
    return render_template("settings/parsing.html", cfg=cfg)


def save_parsing_settings(dependencies):
    """Save only Parsing settings."""
    cfg = dependencies.load_portal_config()
    cfg["show_confidence"] = "show_confidence" in request.form
    cfg["enable_regex_replace"] = "enable_regex_replace" in request.form
    cfg["auto_bom_clean"] = "auto_bom_clean" in request.form
    cfg["enable_show_invisibles"] = "enable_show_invisibles" in request.form
    dependencies.write_portal_config(cfg)
    return redirect("/settings/parsing?saved=1")


def settings_legacy_page(_dependencies):
    """Redirect retired all-in-one Settings bookmarks to Appearance."""
    return redirect("/settings/appearance", code=302)


def save_settings(_dependencies):
    return redirect("/settings/appearance", code=303)


def api_portal_config(dependencies):
    try:
        return jsonify(dependencies.load_portal_config())
    except Exception as exc:
        dependencies.print_message("portal_config API error:", exc)
        return jsonify({"error": "failed"}), 500


def create_settings_blueprint(dependencies):
    blueprint = Blueprint("settings", __name__)
    rules = (
        ("/settings", "settings_page", settings_page, ["GET"]),
        (
            "/settings/navigation",
            "settings_navigation_page",
            settings_navigation_page,
            ["GET"],
        ),
        (
            "/settings/navigation/save",
            "save_navigation_settings",
            save_navigation_settings,
            ["POST"],
        ),
        (
            "/settings/appearance",
            "settings_appearance_page",
            settings_appearance_page,
            ["GET"],
        ),
        (
            "/settings/appearance/save",
            "save_appearance_settings",
            save_appearance_settings,
            ["POST"],
        ),
        ("/api/theme", "api_set_theme", api_set_theme, ["POST"]),
        ("/settings/ai", "settings_ai_page", settings_ai_page, ["GET"]),
        (
            "/settings/ai/save",
            "save_ai_settings",
            save_ai_settings,
            ["POST"],
        ),
        (
            "/settings/parsing",
            "settings_parsing_page",
            settings_parsing_page,
            ["GET"],
        ),
        (
            "/settings/parsing/save",
            "save_parsing_settings",
            save_parsing_settings,
            ["POST"],
        ),
        (
            "/settings/legacy",
            "settings_legacy_page",
            settings_legacy_page,
            ["GET"],
        ),
        ("/save_settings", "save_settings", save_settings, ["POST"]),
        ("/api/portal_config", "api_portal_config", api_portal_config, ["GET"]),
    )
    for rule, endpoint, view_func, methods in rules:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
    return blueprint
