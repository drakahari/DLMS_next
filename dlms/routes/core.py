"""Platform shell and safe asset-serving routes."""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify, render_template, send_from_directory


@dataclass(frozen=True)
class CoreRouteDependencies:
    """Configured application services and paths required by core routes."""

    app_version: Callable[[], str]
    get_portal_title: Callable[[], str]
    content_pack_summary: Callable[[], list[dict[str, Any]]]
    load_portal_config: Callable[[], dict[str, Any]]
    debug_print: Callable[..., None]
    app_data_dir: Callable[[], str]
    static_folder: Callable[[], str]
    default_theme: Callable[[], str]
    get_content_pack: Callable[[str], dict[str, Any] | None]
    safe_pack_child: Callable[[str, str], str]
    decode_raster_image: Callable[..., Any]
    passive_pack_image_extensions: Callable[[], set[str]]
    raster_image_formats: Callable[[], set[str]]
    quiz_asset_folder: Callable[[], str]


def create_core_blueprint(dependencies: CoreRouteDependencies) -> Blueprint:
    """Create platform shell and safe asset-serving routes."""
    blueprint = Blueprint("core", __name__)

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
        dependencies.debug_print(
            "\n[PORTAL CONFIG] ===== SERVING /config/portal.json ====="
        )

        cfg = dependencies.load_portal_config()

        dependencies.debug_print("[PORTAL CONFIG] Loaded config:", cfg)
        dependencies.debug_print(
            "[PORTAL CONFIG] ===== END SERVE =====\n"
        )

        return jsonify(cfg)

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
        p = palettes.get(theme, palettes[default_theme])
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
            portal_title=portal_title,
            app_version=dependencies.app_version(),
            installed_content_packs=dependencies.content_pack_summary(),
        )

    return blueprint
