import json
import os
import re
import tempfile
import unittest
from unittest import mock

import app as dlms


class ThemeSystemTests(unittest.TestCase):
    @staticmethod
    def _style_css():
        path = os.path.join(os.path.dirname(dlms.__file__), "static", "style.css")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_portal_config_default_theme_is_dark(self):
        with tempfile.TemporaryDirectory() as td:
            portal = os.path.join(td, "config", "portal.json")
            with mock.patch.object(dlms, "PORTAL_CONFIG", portal):
                cfg = dlms.load_portal_config()
            self.assertEqual(cfg["theme"], "dark")

    def test_dynamic_css_contains_theme_variables(self):
        client = dlms.app.test_client()
        response = client.get("/dynamic.css")
        self.assertEqual(response.status_code, 200)
        css = response.get_data(as_text=True)
        self.assertIn("--theme-page-text", css)
        self.assertIn("--theme-accent", css)
        self.assertIn("--theme-color-scheme", css)

    def test_theme_api_rejects_unknown_theme(self):
        client = dlms.app.test_client()
        response = client.post("/api/theme", json={"theme": "neon-rainbow"})
        self.assertEqual(response.status_code, 400)

    def test_theme_api_accepts_supported_theme(self):
        client = dlms.app.test_client()
        with tempfile.TemporaryDirectory() as td:
            portal = os.path.join(td, "portal.json")
            with mock.patch.object(dlms, "PORTAL_CONFIG", portal):
                with mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "dark"}):
                    response = client.post("/api/theme", json={"theme": "purple-gold"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["theme"], "purple-gold")
                with open(portal, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved["theme"], "purple-gold")

    def test_theme_api_accepts_maroon_gold_theme(self):
        client = dlms.app.test_client()
        with tempfile.TemporaryDirectory() as td:
            portal = os.path.join(td, "portal.json")
            with mock.patch.object(dlms, "PORTAL_CONFIG", portal):
                with mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "dark"}):
                    response = client.post("/api/theme", json={"theme": "maroon-gold"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["theme"], "maroon-gold")
                with open(portal, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved["theme"], "maroon-gold")

    def test_maroon_gold_dynamic_css_uses_umn_palette(self):
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "maroon-gold", "background_image": None}):
            response = client.get("/dynamic.css")
        self.assertEqual(response.status_code, 200)
        css = response.get_data(as_text=True).lower()
        self.assertIn("--theme-accent: #ffcc33", css)
        self.assertIn("--theme-accent-2: #ffb71e", css)
        self.assertIn("--theme-link: #ffde7a", css)
        self.assertIn("--theme-sidebar-1: rgba(91,0,19,.98)", css)
        self.assertIn("--theme-panel-1: rgba(31,32,36,.95)", css)
        self.assertIn("--theme-body-base: #0d0e10", css)

    def test_live_color_scheme_marks_only_light_palette_as_light(self):
        client = dlms.app.test_client()
        expected = {
            "light": "light",
            "dark": "dark",
            "purple-gold": "dark",
            "maroon-gold": "dark",
        }
        for theme, scheme in expected.items():
            with self.subTest(theme=theme):
                with mock.patch.object(dlms, "load_portal_config", return_value={
                    "title": "DLMS", "theme": theme, "background_image": None,
                }):
                    css = client.get("/dynamic.css").get_data(as_text=True)
                self.assertIn(f"--theme-color-scheme: {scheme}", css)

    def test_light_readability_colors_preserve_dark_component_colors(self):
        css = self._style_css()
        expected_rules = {
            ".history-table-review": "color: light-dark(#285d8f, #dcecff) !important",
            ".analytics-review-button": "color: light-dark(#285d8f, #a9d4ff) !important",
            ".analytics-history-link": "color: light-dark(#285d8f, #9fd0ff) !important",
            ".analytics-score-pill.good": "color: light-dark(#16784f, #7ee5ab) !important",
            ".analytics-score-pill.warn": "color: light-dark(#8a6300, #ffd37a) !important",
            ".analytics-score-pill.bad": "color: light-dark(#b93d52, #ff9eaa) !important",
            ".history-score-badge.good": "color: light-dark(#16784f, #86e8bb) !important",
            ".history-score-badge.warn": "color: light-dark(#8a6300, #edd681) !important",
            ".history-score-badge.bad": "color: light-dark(#b93d52, #ff9da3) !important",
            ".analytics-trend.good": "color:light-dark(#19764e, #7ee5ab) !important",
            ".analytics-trend.bad": "color:light-dark(#c43d52, #ff9eaa) !important",
            ".li-weak-score": "color: light-dark(#b5374d, #ff9ca7) !important",
            ".li-status-weak": "color:#ff9ba6",
        }
        for selector, declaration in expected_rules.items():
            with self.subTest(selector=selector):
                blocks = [
                    body for prelude, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
                    if selector in {item.strip() for item in prelude.split(",")}
                ]
                self.assertTrue(blocks, f"Missing CSS rule for {selector}")
                self.assertTrue(
                    any(declaration in block for block in blocks),
                    f"{selector} must select its accessible dark color through light-dark()",
                )


if __name__ == "__main__":
    unittest.main()
