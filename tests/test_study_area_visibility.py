"""Regression coverage for Settings-controlled study-area navigation visibility."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-study-area-visibility-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


class StudyAreaVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._original_paths = {
            name: getattr(dlms, name)
            for name in ("APP_DATA_DIR", "CONFIG_FOLDER", "PORTAL_CONFIG")
        }

    @classmethod
    def tearDownClass(cls):
        for name, value in cls._original_paths.items():
            setattr(dlms, name, value)
        _TEMP.cleanup()

    def setUp(self):
        self.root = Path(_TEMP.name)
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        config_folder = self.root / "config"
        config_folder.mkdir()
        dlms.APP_DATA_DIR = str(self.root)
        dlms.CONFIG_FOLDER = str(config_folder)
        dlms.PORTAL_CONFIG = str(config_folder / "portal.json")
        self.client = dlms.app.test_client()

    @staticmethod
    def _visibility():
        return {"it": True, "law": True, "medical": True, "other": True}

    def _write_config(self, data):
        Path(dlms.PORTAL_CONFIG).write_text(json.dumps(data), encoding="utf-8")

    def _save_visibility(self, **visibility):
        data = {
            "csrf_token": csrf_token(self.client, "/settings/navigation"),
        }
        data.update({f"study_area_{key}": "on" for key, enabled in visibility.items() if enabled})
        return self.client.post("/settings/navigation/save", data=data, follow_redirects=False)

    def test_fresh_and_legacy_configurations_default_all_study_areas_to_visible(self):
        fresh = dlms.load_portal_config()
        self.assertEqual(self._visibility(), fresh["study_area_visibility"])

        self._write_config({"title": "Legacy DLMS", "theme": "light"})
        legacy = dlms.load_portal_config()
        self.assertEqual(self._visibility(), legacy["study_area_visibility"])
        self.assertEqual("Legacy DLMS", legacy["title"])

    def test_malformed_visibility_values_fall_back_to_visible(self):
        self._write_config({
            "study_area_visibility": {
                "it": False,
                "law": "false",
                "medical": None,
                "other": 0,
            }
        })

        visibility = dlms.load_portal_config()["study_area_visibility"]
        self.assertEqual({"it": False, "law": True, "medical": True, "other": True}, visibility)

        self._write_config({"study_area_visibility": [False, False, False, False]})
        self.assertEqual(self._visibility(), dlms.load_portal_config()["study_area_visibility"])

    def test_navigation_settings_defaults_to_checked_toggles(self):
        page = self.client.get("/settings/navigation").get_data(as_text=True)

        self.assertIn('class="dashboard-shell"', page)
        self.assertIn('data-settings-menu', page)
        for key, label in (("it", "IT Study"), ("law", "Law Study"), ("medical", "Medical Study"), ("other", "Other Studies")):
            with self.subTest(key=key):
                self.assertIn(f'name="study_area_{key}" checked', page)
                self.assertIn(label, page)
        self.assertIn("removes it from navigation only", page)

    def test_save_visibility_preserves_unrelated_settings(self):
        self._write_config({
            "title": "Keep This Title",
            "theme": "purple-gold",
            "ai_custom_url": "http://localhost:11434",
            "study_area_visibility": self._visibility(),
        })

        response = self._save_visibility(it=True, medical=True)
        self.assertEqual(302, response.status_code)
        self.assertEqual("/settings/navigation?saved=1", response.headers["Location"])

        cfg = json.loads(Path(dlms.PORTAL_CONFIG).read_text(encoding="utf-8"))
        self.assertEqual("Keep This Title", cfg["title"])
        self.assertEqual("purple-gold", cfg["theme"])
        self.assertEqual("http://localhost:11434", cfg["ai_custom_url"])
        self.assertEqual({"it": True, "law": False, "medical": True, "other": False}, cfg["study_area_visibility"])

    def test_hiding_one_or_all_study_areas_uses_shared_normalized_navigation(self):
        self.assertEqual(302, self._save_visibility(it=True).status_code)
        self.assertEqual({"it": True, "law": False, "medical": False, "other": False}, dlms.load_portal_config()["study_area_visibility"])

        self.assertEqual(302, self._save_visibility().status_code)
        self.assertEqual({"it": False, "law": False, "medical": False, "other": False}, dlms.load_portal_config()["study_area_visibility"])

        source = Path(dlms.STATIC_ROOT, "nav-normalize.js").read_text(encoding="utf-8")
        self.assertIn("studyAreaVisibility.it ? item('it','/it','⌘','IT Study') : ''", source)
        self.assertIn("studyAreaVisibility.law ? item('law','/law','⚖','Law Study') : ''", source)
        self.assertIn("studyAreaVisibility.medical ? item('medical','/medical','✚','Medical Study') : ''", source)
        self.assertIn("studyAreaVisibility.other ? item('other','/study-packs?domain_group=other','◇','Other Studies') : ''", source)
        self.assertIn("item('study','/study-packs','▣','Study Packs')", source)
        self.assertIn("item('settings','/settings','⚙','Settings')", source)

    def test_hidden_area_urls_remain_usable_and_reenabling_restores_visibility(self):
        self.assertEqual(302, self._save_visibility().status_code)

        for path in ("/it", "/law", "/medical", "/study-packs?domain_group=other"):
            with self.subTest(path=path):
                self.assertEqual(200, self.client.get(path).status_code)

        self.assertEqual(302, self._save_visibility(law=True).status_code)
        self.assertEqual({"it": False, "law": True, "medical": False, "other": False}, dlms.load_portal_config()["study_area_visibility"])

    def test_mobile_uses_the_same_filtered_sidebar_and_customize_link(self):
        source = Path(dlms.STATIC_ROOT, "nav-normalize.js").read_text(encoding="utf-8")
        css = Path(dlms.STATIC_ROOT, "style.css").read_text(encoding="utf-8")

        self.assertIn("mountNavigation(defaultStudyAreaVisibility)", source)
        self.assertIn("mountNavigation(normalizeStudyAreaVisibility(cfg?.study_area_visibility))", source)
        self.assertIn("navigationCustomize.href = '/settings/navigation'", source)
        self.assertIn("dashboard-navigation-customize", source)
        self.assertIn(".dashboard-sidebar.open", css)


if __name__ == "__main__":
    unittest.main()
