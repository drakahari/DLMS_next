"""Captured theme roles used by Qt Settings remain readable and complete."""
from __future__ import annotations

from PySide6.QtGui import QColor

from desktop.settings_surface import THEME_REGISTRY, _solid
from desktop.shell import SETTINGS_NAV_DESTINATIONS, safe_native_navigation
from dlms.themes import contrast


def test_all_registered_themes_have_readable_native_roles():
    assert len(THEME_REGISTRY) == 26
    for name, entry in THEME_REGISTRY.items():
        colors, extra = entry["colors"], entry["extra_tokens"]
        base = colors["body_base"]
        for role in ("main1", "panel1", "sidebar1", "surface2", "border"):
            assert QColor(_solid(colors[role], base)).isValid(), (name, role)
        for role, foreground, background in (
            ("main", colors["page"], _solid(colors["main1"], base)),
            ("card", colors["page"], _solid(colors["panel1"], base)),
            ("sidebar", colors["nav_text"], _solid(colors["sidebar1"], base)),
            ("focus", extra.get("--theme-focus-ring", colors["accent_text"]), _solid(colors["surface2"], base)),
        ):
            assert contrast(foreground, background) >= 4.5, (name, role)


def test_unknown_theme_has_captured_default():
    assert "purple-gold" in THEME_REGISTRY


def test_native_sidebar_destinations_are_only_reviewed_get_pages():
    assert all(safe_native_navigation(path) for path in SETTINGS_NAV_DESTINATIONS)
    for path in ("//remote.example", "http://remote.example/", "/_desktop/ready",
                 "/api/reset_settings", "/settings/backup/create", "/admin/maintenance",
                 "/settings/backup/restore/stage", "/library/../_desktop/ready", "/%2fremote"):
        assert not safe_native_navigation(path)
