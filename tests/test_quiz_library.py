import json
import os
import re
import sqlite3
import tempfile
import unittest
from unittest import mock

import app as dlms


class QuizLibraryTests(unittest.TestCase):
    def test_library_tools_identifies_reference_export_and_portability_options(self):
        with tempfile.TemporaryDirectory(prefix="dlms-library-export-ui-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                response = dlms.app.test_client().get("/library")

            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn("Download Quiz Library Reference (TXT)", html)
            self.assertIn('href="/export/all_quizzes.txt"', html)
            self.assertIn("human-readable TXT reference", html)
            self.assertIn("not a restorable or importable library package", html)
            self.assertIn("import-friendly classic MCQ text file", html)
            self.assertIn('href="/settings/data"', html)
            self.assertIn("portable backup for migration or full restore", html)
            self.assertNotIn("⇩ Export All Quizzes", html)

    def test_quiz_library_reference_keeps_existing_text_export_contract(self):
        with tempfile.TemporaryDirectory(prefix="dlms-library-reference-") as directory:
            db_path = os.path.join(directory, "results.db")
            quiz_registry = os.path.join(directory, "quizzes.json")
            conn = sqlite3.connect(db_path)
            conn.executescript("""
                CREATE TABLE quizzes (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_file TEXT NOT NULL
                );
                CREATE TABLE questions (
                    id INTEGER PRIMARY KEY,
                    quiz_id INTEGER NOT NULL,
                    question_number INTEGER NOT NULL,
                    question_text TEXT NOT NULL
                );
                CREATE TABLE choices (
                    id INTEGER PRIMARY KEY,
                    question_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    text TEXT NOT NULL,
                    is_correct INTEGER NOT NULL
                );
                INSERT INTO quizzes VALUES (7, 'Network Basics', 'network.html');
                INSERT INTO questions VALUES (11, 7, 1, 'Which protocol resolves names?');
                INSERT INTO choices VALUES (21, 11, 'A', 'DNS', 1);
                INSERT INTO choices VALUES (22, 11, 'B', 'SSH', 0);
            """)
            conn.commit()
            conn.close()
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([
                    {
                        "id": 7,
                        "title": "Network Basics",
                        "html": "network.html",
                        "folder": "Networking",
                    }
                ], handle)

            with mock.patch.object(dlms, "DB_PATH", db_path), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry):
                response = dlms.app.test_client().get("/export/all_quizzes.txt")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "text/plain")
            self.assertEqual(
                response.headers["Content-Disposition"],
                "attachment; filename=dlms_all_quizzes_export.txt",
            )
            export = response.get_data(as_text=True)
            for expected in (
                "# DLMS Quiz Export",
                f"# Exported from DLMS v{dlms.APP_VERSION}",
                "# Format: DLMS text",
                "# Import compatible: No - contains multiple quizzes",
                "# Total quizzes: 1",
                "QUIZ: Network Basics",
                "QUIZ ID: 7",
                "FOLDER: Networking",
                "1. Which protocol resolves names?",
                "A. DNS",
                "B. SSH",
                "Correct Answer: A",
            ):
                with self.subTest(expected=expected):
                    self.assertIn(expected, export)

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
