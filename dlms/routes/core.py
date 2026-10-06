"""Platform shell and safe asset-serving routes."""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify, render_template, request, send_from_directory
from flask_wtf.csrf import generate_csrf
from dlms.persistence.portal import dashboard_card_defaults
from dlms.themes import get_theme, theme_groups


@dataclass(frozen=True)
class CoreRouteDependencies:
    """Configured application services and paths required by core routes."""

    app_version: Callable[[], str]
    get_portal_title: Callable[[], str]
    content_pack_summary: Callable[[], list[dict[str, Any]]]
    load_portal_config: Callable[[], dict[str, Any]]
    app_data_dir: Callable[[], str]
    static_folder: Callable[[], str]
    default_theme: Callable[[], str]
    get_content_pack: Callable[[str], dict[str, Any] | None]
    safe_pack_child: Callable[[str, str], str]
    decode_raster_image: Callable[..., Any]
    passive_pack_image_extensions: Callable[[], set[str]]
    raster_image_formats: Callable[[], set[str]]
    quiz_asset_folder: Callable[[], str]
    browser_presence_update: Callable[[str, bool], bool]
    browser_presence_setting_loaded: Callable[[dict[str, Any]], None]
    browser_presence_runtime_eligible: Callable[[], bool]


def create_core_blueprint(dependencies: CoreRouteDependencies) -> Blueprint:
    """Create platform shell and safe asset-serving routes."""
    blueprint = Blueprint("core", __name__)

    @blueprint.get("/api/csrf-token")
    def refresh_csrf_token():
        # A custom header requires a cross-origin preflight; no CORS access is
        # granted. The app's same-origin guard also applies to this GET endpoint.
        if request.headers.get("X-DLMS-CSRF-Refresh") != "1":
            return jsonify(error="Same-origin security renewal is required."), 403
        return jsonify(csrf_token=generate_csrf())

    @blueprint.get("/content-packs/<pack_id>/assets/<path:asset_path>")
    def content_pack_asset(pack_id, asset_path):
        """Serve a file from an installed content pack without allowing path traversal."""
        pack = dependencies.get_content_pack(pack_id)
        if not pack:
            return "Content pack not found", 404

        try:
            file_path = dependencies.safe_pack_child(pack["_root"], asset_path)
        except ValueError:
            return "Invalid content-pack asset path", 400

        if not os.path.isfile(file_path):
            return "Content-pack asset not found", 404

        allowed = dependencies.passive_pack_image_extensions()
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in allowed:
            return "Unsupported content-pack asset type", 415
        try:
            dependencies.decode_raster_image(file_path, allowed)
        except ValueError:
            return "Invalid content-pack image", 415

        return send_from_directory(
            os.path.dirname(file_path),
            os.path.basename(file_path),
            conditional=True
        )

    @blueprint.get("/quiz-assets/<asset_bucket>/<path:asset_path>")
    def quiz_asset(asset_bucket, asset_path):
        """Serve quiz-owned snapshots independently of the source Study Pack."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,140}", str(asset_bucket or "")):
            return "Invalid quiz asset bucket", 400
        root = os.path.join(dependencies.quiz_asset_folder(), asset_bucket)
        try:
            file_path = dependencies.safe_pack_child(root, asset_path)
        except ValueError:
            return "Invalid quiz asset path", 400
        if not os.path.isfile(file_path):
            return "Quiz asset not found", 404
        if os.path.splitext(file_path)[1].lower() not in dependencies.passive_pack_image_extensions():
            return "Unsupported quiz asset", 415
        try:
            dependencies.decode_raster_image(
                file_path, dependencies.passive_pack_image_extensions()
            )
        except ValueError:
            return "Invalid quiz asset", 415
        # Keep the request path in URL/POSIX form. On Windows, os.path.relpath()
        # returns backslashes (for example ``images\\diagram.png``). Werkzeug's
        # send_from_directory() treats backslashes as unsafe alternate separators,
        # which can make otherwise valid quiz-owned Study Pack images return 404.
        # ``asset_path`` came from Flask's <path:...> converter and has already been
        # resolved/validated above with safe_pack_child(), so pass its normalized
        # URL form directly to send_from_directory().
        safe_asset_path = str(asset_path or "").replace("\\", "/").lstrip("/")
        return send_from_directory(root, safe_asset_path, conditional=True)

    @blueprint.get("/user-static/<path:filename>")
    def user_static(filename):
        normalized = str(filename or "").replace("\\", "/").lstrip("/")
        if not normalized.startswith("logos/"):
            return "Unsupported user asset", 415
        root = os.path.join(dependencies.app_data_dir(), "static")
        try:
            file_path = dependencies.safe_pack_child(root, normalized)
            if not os.path.isfile(file_path):
                return "User image not found", 404
            dependencies.decode_raster_image(
                file_path, dependencies.raster_image_formats()
            )
        except ValueError:
            return "Invalid user image", 415
        return send_from_directory(
            root,
            normalized
        )

    @blueprint.get("/config/portal.json")
    def serve_portal_config():
        """
        Serve the portal configuration as JSON.
        This is the single source of truth for UI settings
        (title, background image, feature toggles).
        """
        cfg = dict(dependencies.load_portal_config())
        cfg["theme_groups"] = theme_groups()
        dependencies.browser_presence_setting_loaded(cfg)

        # Runtime mode is deliberately not persisted in portal.json.  It is
        # derived from the host selected for this process and tells the shared
        # browser shell whether process shutdown is a valid desktop action.
        cfg["manual_shutdown_available"] = bool(
            dependencies.browser_presence_runtime_eligible()
        )
        cfg["runtime_mode"] = (
            "local" if cfg["manual_shutdown_available"] else "lan_server"
        )

        return jsonify(cfg)

    @blueprint.post("/api/browser-presence")
    def browser_presence():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "Invalid presence payload"}), 400
        token = payload.get("token")
        event = payload.get("event", "present")
        if event not in {"present", "closed"}:
            return jsonify({"ok": False, "error": "Invalid presence event"}), 400
        closed = event == "closed"
        try:
            accepted = dependencies.browser_presence_update(token, closed)
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid presence token"}), 400
        return jsonify({"ok": True, "accepted": bool(accepted)})

    @blueprint.get("/dynamic.css")
    def dynamic_css():
        cfg = dependencies.load_portal_config()

        bg = (cfg.get("background_image") or "").strip()
        if not bg:
            css_bg = "none"
        else:
            user_bg = os.path.join(dependencies.app_data_dir(), "static", "bg", bg)
            static_bg = os.path.join(dependencies.static_folder(), "bg", bg)
            if os.path.exists(user_bg):
                css_bg = f"url('/user-bg/{bg}')"
            elif os.path.exists(static_bg):
                css_bg = f"url('/static/bg/{bg}')"
            else:
                css_bg = "none"

        default_theme = dependencies.default_theme()
        theme = str(cfg.get("theme") or default_theme).strip().lower()
        entry = get_theme(theme)
        p = entry["colors"]
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
            f"  --theme-on-accent: {p['on_accent']};",
            f"  --theme-link: {p['link']};",
            f"  --theme-link-hover: {p['link_hover']};",
            f"  --theme-shadow: {p['shadow']};"
        ])
        if entry["extra_tokens"]:
            vars_css += "\n" + "\n".join(
                f"  {key}: {value};" for key, value in entry["extra_tokens"].items()
            )
        return f":root {{\n{vars_css}\n}}\n", 200, {"Content-Type": "text/css", "Cache-Control": "no-store"}

    @blueprint.get("/user-bg/<path:filename>")
    def serve_user_background(filename):
        bg_dir = os.path.join(dependencies.app_data_dir(), "static", "bg")
        try:
            file_path = dependencies.safe_pack_child(bg_dir, filename)
            if not os.path.isfile(file_path):
                return "Background image not found", 404
            dependencies.decode_raster_image(
                file_path, dependencies.raster_image_formats()
            )
        except ValueError:
            return "Invalid background image", 415
        return send_from_directory(bg_dir, filename)

    @blueprint.get("/")
    def home():
        portal_title = dependencies.get_portal_title()

        return render_template(
            "dashboard/index.html",
            visibility=dependencies.load_portal_config().get("dashboard_card_visibility", dashboard_card_defaults()),
            portal_title=portal_title,
            app_version=dependencies.app_version(),
            installed_content_packs=dependencies.content_pack_summary(),
        )

    return blueprint
