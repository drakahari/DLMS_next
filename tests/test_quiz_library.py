import json
import os
import re
import tempfile
import unittest
from unittest import mock

import app as dlms


class QuizLibraryTests(unittest.TestCase):
    def test_fresh_empty_library_does_not_count_unrendered_default_folders(self):
        with tempfile.TemporaryDirectory(prefix="dlms-empty-library-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                response = dlms.app.test_client().get("/library")
                configured_folders = dlms.get_quiz_folders()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(configured_folders, ["Uncategorized"])
            for personal_folder in ("A+", "Network+", "Security+", "Data+", "Cloud+", "Linux+"):
                self.assertNotIn(personal_folder, configured_folders)

            html = response.get_data(as_text=True)
            folder_count = re.search(
                r'<span>Folders</span><strong>(\d+)</strong><small>folders in this view</small>',
                html,
            )
            self.assertIsNotNone(folder_count)
            self.assertEqual(folder_count.group(1), "0")
            self.assertNotIn('class="library-folder"', html)

    def test_fresh_configuration_enables_confidence_and_ai_helpers(self):
        with tempfile.TemporaryDirectory(prefix="dlms-fresh-config-") as directory:
            portal_config = os.path.join(directory, "config", "portal.json")

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config):
                config = dlms.load_portal_config()

            self.assertTrue(config["show_confidence"])
            self.assertTrue(config["ai_helper_enabled"])
            self.assertEqual(config["quiz_folders"], ["Uncategorized"])

            with open(portal_config, "r", encoding="utf-8") as file:
                persisted = json.load(file)
            self.assertTrue(persisted["show_confidence"])
            self.assertTrue(persisted["ai_helper_enabled"])
            self.assertEqual(persisted["quiz_folders"], ["Uncategorized"])

    def test_persisted_false_settings_and_existing_folders_take_precedence(self):
        with tempfile.TemporaryDirectory(prefix="dlms-existing-config-") as directory:
            portal_config = os.path.join(directory, "config", "portal.json")
            os.makedirs(os.path.dirname(portal_config), exist_ok=True)
            existing = {
                "title": "Existing DLMS",
                "show_confidence": False,
                "ai_helper_enabled": False,
                "quiz_folders": ["Uncategorized", "My Courses", "A+"],
            }
            with open(portal_config, "w", encoding="utf-8") as file:
                json.dump(existing, file, indent=2)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config):
                config = dlms.load_portal_config()
                folders = dlms.get_quiz_folders()

            self.assertFalse(config["show_confidence"])
            self.assertFalse(config["ai_helper_enabled"])
            self.assertEqual(folders, ["Uncategorized", "My Courses", "A+"])

            with open(portal_config, "r", encoding="utf-8") as file:
                self.assertEqual(json.load(file), existing)


if __name__ == "__main__":
    unittest.main()
