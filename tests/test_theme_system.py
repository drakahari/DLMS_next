import json
import os
import tempfile
import unittest
from unittest import mock

import app as dlms


class ThemeSystemTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
