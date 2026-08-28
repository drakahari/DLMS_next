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


if __name__ == "__main__":
    unittest.main()
