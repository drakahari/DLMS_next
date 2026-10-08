"""Settings configuration routes."""

import html
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, jsonify, redirect, render_template, request
from dlms.persistence.portal import DASHBOARD_CARD_GROUPS, dashboard_card_defaults
from dlms.themes import THEME_IDS, theme_groups
from dlms.prompts import DEFAULT_CERTIFICATION_PROMPT, DEFAULT_PORTFOLIO_PROMPT


Dependency = Callable[..., Any]
THEMES = THEME_IDS
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
    set_browser_presence_shutdown_enabled: Dependency
    browser_presence_shutdown_runtime_eligible: Dependency
    print_message: Dependency
    registry_lock: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        # Settings replace the whole portal document. Share the folder/registry
        # lock from the initial read through publication (and lifecycle update).
        if request.method == "POST":
            with dependencies.registry_lock():
                return view_func(dependencies, **view_args)
        return view_func(dependencies, **view_args)

    return bound_view


def settings_page(_dependencies):
    """Settings landing page for the completed category-based settings UI."""
    return render_template("settings/index.html")


def settings_lifecycle_page(dependencies):
    cfg = dependencies.load_portal_config()
    return render_template(
        "settings/lifecycle.html",
        automatic_browser_shutdown_enabled=bool(
            cfg.get("automatic_browser_shutdown_enabled", False)
        ),
        browser_presence_shutdown_runtime_eligible=bool(
            dependencies.browser_presence_shutdown_runtime_eligible()
        ),
    )


def save_lifecycle_settings(dependencies):
    cfg = dependencies.load_portal_config()
    saved_enabled = bool(cfg.get("automatic_browser_shutdown_enabled", False))
    if not dependencies.browser_presence_shutdown_runtime_eligible():
        dependencies.set_browser_presence_shutdown_enabled(saved_enabled)
        return redirect("/settings/lifecycle?unavailable=1")
    enabled = "automatic_browser_shutdown_enabled" in request.form
    cfg["automatic_browser_shutdown_enabled"] = enabled
    dependencies.write_portal_config(cfg)
    dependencies.set_browser_presence_shutdown_enabled(enabled)
    return redirect("/settings/lifecycle?saved=1")


def _layout_redirect(section, saved=False):
    saved = saved or request.args.get("saved") == "1"
    return redirect("/settings/layout" + ("?saved=1" if saved else "") + "#" + section)


def settings_navigation_page(_dependencies):
    return _layout_redirect("study-areas")


def settings_dashboard_page(_dependencies):
    return _layout_redirect("dashboard-panels")


def settings_layout_page(dependencies):
    cfg = dependencies.load_portal_config()
    return render_template(
        "settings/dashboard.html", groups=DASHBOARD_CARD_GROUPS,
        visibility=cfg.get("dashboard_card_visibility", dashboard_card_defaults()),
        sidebar_visibility=cfg["study_area_visibility"],
        show_certifications=cfg.get("show_certifications",True),
    )


def save_layout_settings(dependencies):
    action = request.form.get("action", "save")
    if action not in {"save", "dashboard_defaults", "sidebar_defaults"}:
        return "Unknown layout settings action", 400
    cfg = dependencies.load_portal_config()
    if action == "dashboard_defaults":
        cfg["dashboard_card_visibility"] = dashboard_card_defaults()
    elif action == "sidebar_defaults":
        cfg["study_area_visibility"] = dict.fromkeys(("it", "law", "medical", "other"), True)
    else:
        cfg["dashboard_card_visibility"] = {
            key: f"dashboard_card_{key}" in request.form for key in dashboard_card_defaults()
        }
        cfg["study_area_visibility"] = {
            key: f"study_area_{key}" in request.form for key in ("it", "law", "medical", "other")
        }
    if action == "save" and request.form.get("certifications_visibility_present") == "yes":
        cfg["show_certifications"] = "show_certifications" in request.form
    dependencies.write_portal_config(cfg)
    return redirect("/settings/layout?saved=1")


def save_dashboard_settings(dependencies):
    action = request.form.get("action", "save")
    if action not in {"save", "defaults"}:
        return "Unknown dashboard settings action", 400
    cfg = dependencies.load_portal_config()
    defaults = dashboard_card_defaults()
    cfg["dashboard_card_visibility"] = defaults if action == "defaults" else {
        key: f"dashboard_card_{key}" in request.form for key in defaults
    }
    dependencies.write_portal_config(cfg)
    return _layout_redirect("dashboard-panels", saved=True)


def save_navigation_settings(dependencies):
    cfg = dependencies.load_portal_config()
    cfg["study_area_visibility"] = {
        "it": "study_area_it" in request.form,
        "law": "study_area_law" in request.form,
        "medical": "study_area_medical" in request.form,
        "other": "study_area_other" in request.form,
    }
    dependencies.write_portal_config(cfg)
    return _layout_redirect("study-areas", saved=True)


def settings_appearance_page(dependencies):
    cfg = dependencies.load_portal_config()
    return render_template("settings/appearance.html", cfg=cfg, theme_groups=theme_groups())


def save_appearance_settings(dependencies):
    """Save only Appearance settings without changing other categories."""
    cfg = dependencies.load_portal_config()
    default_theme = dependencies.default_theme()
    requested_theme = str(
        request.form.get("theme") or cfg.get("theme") or default_theme
    ).strip().lower()
    if requested_theme not in THEMES:
        return render_template("settings/appearance.html", cfg=cfg, theme_groups=theme_groups(),
                               theme_error="Choose a supported theme. Settings were not saved."), 400
    cfg["theme"] = requested_theme

    title = request.form.get("portal_title", "").strip()
    if title:
        cfg["title"] = title

    upload = request.files.get("background_image")
    if upload and upload.filename and upload.filename.strip():
        try:
            cfg["background_image"] = dependencies.store_background_upload(upload)
        except ValueError as exc:
            return f"Invalid background image: {html.escape(str(exc))}", 400

    try:
        dependencies.write_portal_config(cfg)
    except OSError:
        return render_template("settings/appearance.html", cfg=cfg, theme_groups=theme_groups(),
                               theme_error="DLMS could not save settings. Your saved choice is unchanged. Try saving again."), 503
    return redirect("/settings/appearance?saved=1")


def api_set_theme(dependencies):
    payload = request.get_json(silent=True) if request.is_json else request.form
    value = payload.get("theme") if hasattr(payload, "get") else None
    requested = value.strip().lower() if isinstance(value, str) else ""
    if requested not in THEMES:
        return jsonify({"ok": False, "error": "Unsupported theme"}), 400
    # Reject invalid submissions before loading/recovering configuration, so
    # even a missing or malformed settings file cannot be changed by this call.
    cfg = dependencies.load_portal_config()
    cfg["theme"] = requested
    try:
        dependencies.write_portal_config(cfg)
    except OSError:
        return jsonify({"ok": False, "error": "Could not save theme. Your saved choice is unchanged."}), 503
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
        certification_default_prompt=DEFAULT_CERTIFICATION_PROMPT,
        portfolio_default_prompt=DEFAULT_PORTFOLIO_PROMPT,
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

    cfg["certification_ai_prompt_template"] = request.form.get("certification_ai_prompt_template", cfg.get("certification_ai_prompt_template", DEFAULT_CERTIFICATION_PROMPT)).strip() or DEFAULT_CERTIFICATION_PROMPT
    if len(cfg["certification_ai_prompt_template"]) > 20000:
        return "Certification prompt exceeds 20,000 characters.", 400
    cfg["portfolio_ai_prompt_template"] = request.form.get("portfolio_ai_prompt_template", cfg.get("portfolio_ai_prompt_template", DEFAULT_PORTFOLIO_PROMPT)).strip() or DEFAULT_PORTFOLIO_PROMPT
    if len(cfg["portfolio_ai_prompt_template"]) > 20000:
        return "Portfolio prompt exceeds 20,000 characters.", 400
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
        ("/settings/layout", "settings_layout_page", settings_layout_page, ["GET"]),
        ("/settings/layout/save", "save_layout_settings", save_layout_settings, ["POST"]),
        ("/settings/dashboard", "settings_dashboard_page", settings_dashboard_page, ["GET"]),
        ("/settings/dashboard/save", "save_dashboard_settings", save_dashboard_settings, ["POST"]),
        ("/settings", "settings_page", settings_page, ["GET"]),
        (
            "/settings/lifecycle",
            "settings_lifecycle_page",
            settings_lifecycle_page,
            ["GET"],
        ),
        (
            "/settings/lifecycle/save",
            "save_lifecycle_settings",
            save_lifecycle_settings,
            ["POST"],
        ),
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
