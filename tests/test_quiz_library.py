import json
import os
import re
import sqlite3
import tempfile
import unittest
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


class QuizLibraryTests(unittest.TestCase):
    def test_library_uses_vendored_sortable_with_existing_order_initialization(self):
        with tempfile.TemporaryDirectory(prefix="dlms-library-sortable-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                client = dlms.app.test_client()
                response = client.get("/library")
                asset = client.get("/static/vendor/sortablejs-1.15.0.min.js")

            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn(
                'src="/static/vendor/sortablejs-1.15.0.min.js"', html
            )
            self.assertNotIn("cdnjs.cloudflare.com/ajax/libs/Sortable", html)
            self.assertIn("Sortable.create(folderList", html)
            self.assertIn(
                'draggable: ".library-folder:not(.library-view-search-only)"',
                html,
            )
            self.assertIn('handle: ".library-folder-header"', html)
            self.assertIn("document.querySelectorAll(\".library-folder-body\")", html)
            self.assertIn('draggable: ".quiz-card"', html)
            self.assertIn('handle: ".quiz-card"', html)

            self.assertEqual(asset.status_code, 200)
            try:
                self.assertTrue(
                    asset.get_data(as_text=True).startswith(
                        "/*! Sortable 1.15.0 - MIT"
                    )
                )
            finally:
                asset.close()

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
            self.assertIn('href="/settings/backup"', html)
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

    def test_empty_folder_renders_and_remains_available_through_move_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix="dlms-library-folders-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([
                    {
                        "id": 7,
                        "title": "Network Basics",
                        "html": "network.html",
                        "folder": "Uncategorized",
                    }
                ], handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                client = dlms.app.test_client()
                add_response = client.post(
                    "/add_quiz_folder",
                    data={"folder": "Course Review", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                self.assertEqual(add_response.status_code, 302)

                empty_folder_html = client.get("/library").get_data(as_text=True)
                self.assertIn("<h2>Course Review</h2>", empty_folder_html)
                self.assertIn("No quizzes in this view.", empty_folder_html)
                self.assertIn('<option value="Course Review"', empty_folder_html)
                self.assertIn("Drag folder headers to reorder folders.", empty_folder_html)
                self.assertIn("Drag quiz cards to reorder quizzes inside a folder.", empty_folder_html)
                self.assertIn("Boolean(term) && visibleCards === 0", empty_folder_html)

                move_response = client.post(
                    "/move_quiz_folder",
                    data={"id": "7", "folder": "Course Review", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                self.assertEqual(move_response.status_code, 302)
                populated_folder_html = client.get("/library").get_data(as_text=True)
                self.assertIn("<h2>Course Review</h2>", populated_folder_html)
                self.assertNotIn("No quizzes in this view.", populated_folder_html)
                self.assertNotIn("<h2>Uncategorized</h2>", populated_folder_html)

                move_back_response = client.post(
                    "/move_quiz_folder",
                    data={"id": "7", "folder": "Uncategorized", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                self.assertEqual(move_back_response.status_code, 302)
                empty_again_html = client.get("/library").get_data(as_text=True)
                self.assertIn("<h2>Course Review</h2>", empty_again_html)
                self.assertIn("No quizzes in this view.", empty_again_html)
                self.assertIn('<option value="Course Review"', empty_again_html)

                with open(portal_config, encoding="utf-8") as handle:
                    self.assertIn("Course Review", json.load(handle)["quiz_folders"])

                delete_response = client.post(
                    "/delete_quiz_folder",
                    data={"folder": "Course Review", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                self.assertEqual(delete_response.status_code, 302)
                deleted_folder_html = client.get("/library").get_data(as_text=True)
                self.assertNotIn("<h2>Course Review</h2>", deleted_folder_html)
                self.assertNotIn('<option value="Course Review"', deleted_folder_html)

    def test_deleting_last_quiz_keeps_its_explicit_hidden_folder_persistent(self):
        with tempfile.TemporaryDirectory(prefix="dlms-library-delete-last-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            db_path = os.path.join(directory, "results.db")
            quiz_folder = os.path.join(directory, "quizzes")
            data_folder = os.path.join(directory, "data")
            asset_folder = os.path.join(directory, "quiz_assets")
            logo_folder = os.path.join(directory, "logos")
            for path in (config_dir, quiz_folder, data_folder, asset_folder, logo_folder):
                os.makedirs(path, exist_ok=True)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "DB_PATH", db_path), \
                    mock.patch.object(dlms, "QUIZ_FOLDER", quiz_folder), \
                    mock.patch.object(dlms, "DATA_FOLDER", data_folder), \
                    mock.patch.object(dlms, "QUIZ_ASSET_FOLDER", asset_folder), \
                    mock.patch.object(dlms, "LOGO_FOLDER", logo_folder), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                dlms.bootstrap_database(db_path, require_owned_root=False)
                connection = sqlite3.connect(db_path)
                connection.execute(
                    "INSERT INTO quizzes (id, title, source_file) VALUES (7, ?, ?)",
                    ("Only Quiz", "only.html"),
                )
                connection.commit()
                connection.close()
                dlms.save_quiz_folder_state(
                    ["Uncategorized", "CISM"], ["CISM"]
                )
                dlms.save_registry([{
                    "id": 7,
                    "title": "Only Quiz",
                    "html": "only.html",
                    "folder": "CISM",
                }])

                client = dlms.app.test_client()
                response = client.post(
                    "/delete_quiz/7",
                    headers=csrf_headers(client, "/library"),
                )
                library_html = client.get("/library?view=hidden").get_data(as_text=True)

            self.assertEqual(302, response.status_code)
            self.assertIn("<h2>CISM ", library_html)
            self.assertIn("No quizzes in this view.", library_html)
            with open(quiz_registry, encoding="utf-8") as handle:
                self.assertEqual([], json.load(handle))
            with open(portal_config, encoding="utf-8") as handle:
                portal = json.load(handle)
                self.assertIn("CISM", portal["quiz_folders"])
                self.assertEqual(["CISM"], portal["hidden_quiz_folders"])

    def test_persistent_empty_folders_render_in_visible_and_all_but_not_hidden(self):
        with tempfile.TemporaryDirectory(prefix="dlms-library-filtered-folders-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            with open(portal_config, "w", encoding="utf-8") as handle:
                json.dump({
                    "quiz_folders": ["Uncategorized", "Persistent Empty", "Hidden Course"],
                }, handle)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([{
                    "id": 8,
                    "title": "Hidden Quiz",
                    "html": "hidden.html",
                    "folder": "Hidden Course",
                    "hidden": True,
                }], handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                client = dlms.app.test_client()
                pages = {
                    view: client.get(f"/library?view={view}").get_data(as_text=True)
                    for view in ("visible", "hidden", "all")
                }
                delete_response = client.post(
                    "/delete_quiz_folder",
                    data={"folder": "Hidden Course", "view": "visible"},
                    headers=csrf_headers(client, "/library?view=visible"),
                )
                saved_quizzes = dlms.load_registry()
                saved_folders = dlms.get_quiz_folders()

            for view in ("visible", "all"):
                html = pages[view]
                with self.subTest(view=view):
                    self.assertIn("<h2>Persistent Empty</h2>", html)
                    self.assertIn("No quizzes in this view.", html)
            self.assertNotIn("<h2>Persistent Empty</h2>", pages["hidden"])
            for view, html in pages.items():
                with self.subTest(hidden_quiz_folder_view=view):
                    self.assertIn("<h2>Hidden Course</h2>", html)
            self.assertEqual(302, delete_response.status_code)
            self.assertEqual("Uncategorized", saved_quizzes[0]["folder"])
            self.assertNotIn("Hidden Course", saved_folders)

    def test_empty_and_populated_custom_folders_keep_configured_display_order(self):
        with tempfile.TemporaryDirectory(prefix="dlms-library-folder-order-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            with open(portal_config, "w", encoding="utf-8") as handle:
                json.dump({
                    "quiz_folders": ["Uncategorized", "Empty First", "Populated", "Empty Last"],
                }, handle)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([{
                    "id": 9,
                    "title": "Placed Quiz",
                    "html": "placed.html",
                    "folder": "Populated",
                }], handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                html = dlms.app.test_client().get("/library").get_data(as_text=True)

            positions = [
                html.index(f"<h2>{folder}</h2>")
                for folder in ("Empty First", "Populated", "Empty Last")
            ]
            self.assertEqual(sorted(positions), positions)

    def test_library_renders_compact_native_keyboard_reorder_controls(self):
        with tempfile.TemporaryDirectory(prefix="dlms-library-keyboard-reorder-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            with open(portal_config, "w", encoding="utf-8") as handle:
                json.dump({"quiz_folders": ["Uncategorized", "Networking"]}, handle)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([
                    {"id": 1, "title": "Routing", "html": "routing.html", "folder": "Networking"},
                    {"id": 2, "title": "Switching", "html": "switching.html", "folder": "Networking"},
                    {"id": 3, "title": "General", "html": "general.html", "folder": "Uncategorized"},
                ], handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                response = dlms.app.test_client().get("/library")

            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            for expected in (
                'data-library-reorder="folder"',
                'data-library-reorder="quiz"',
                'data-library-reorder-direction="-1"',
                'data-library-reorder-direction="1"',
                'aria-label="Move Networking up"',
                'aria-label="Move Routing down within Networking"',
                'id="libraryReorderStatus"',
                'aria-live="polite"',
                'onclick="moveLibraryFolder(event, this, -1)"',
                'onclick="moveLibraryQuiz(event, this, 1)"',
            ):
                with self.subTest(expected=expected):
                    self.assertIn(expected, html)

            self.assertIn("function moveLibraryItem", html)
            self.assertIn("container.dataset.reorderPending", html)
            self.assertIn("function saveLibraryFolderOrder", html)
            self.assertIn("function saveLibraryQuizOrder", html)
            self.assertIn('postLibraryReorder("/save_folder_order", {', html)
            self.assertIn('view: folderList.dataset.view || "visible"', html)
            self.assertIn('postLibraryReorder("/save_quiz_order_in_folder", {folder, order})', html)
            self.assertIn('libraryDirectItems(body, ".library-quiz-card")', html)
            self.assertIn("librarySearchIsActive()", html)

    def test_folder_scoped_reorder_preserves_existing_ordering_guards(self):
        with tempfile.TemporaryDirectory(prefix="dlms-library-reorder-persistence-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            with open(portal_config, "w", encoding="utf-8") as handle:
                json.dump({"quiz_folders": ["Uncategorized", "Networking", "Security"]}, handle)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([
                    {"id": 1, "title": "Routing", "html": "routing.html", "folder": "Networking"},
                    {"id": 2, "title": "Switching", "html": "switching.html", "folder": "Networking"},
                    {"id": 3, "title": "Firewall", "html": "firewall.html", "folder": "Security"},
                ], handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry):
                client = dlms.app.test_client()
                quiz_response = client.post(
                    "/save_quiz_order_in_folder",
                    json={"folder": "Networking", "order": ["switching.html", "firewall.html", "switching.html"]},
                    headers=csrf_headers(client, "/library"),
                )
                folder_response = client.post(
                    "/save_folder_order",
                    json={"folders": ["Security", "Networking", "Security"]},
                    headers=csrf_headers(client, "/library"),
                )
                saved_quizzes = dlms.load_registry()
                saved_folders = dlms.get_quiz_folders()

            self.assertEqual(200, quiz_response.status_code)
            self.assertEqual({"status": "ok"}, quiz_response.get_json())
            self.assertEqual(200, folder_response.status_code)
            self.assertEqual({"status": "ok"}, folder_response.get_json())
            # The foreign Security ID and duplicate Network ID are ignored; the
            # existing folder-only persistence route remains the guardrail.
            self.assertEqual(
                ["switching.html", "routing.html", "firewall.html"],
                [quiz["html"] for quiz in saved_quizzes],
            )
            self.assertEqual(["Security", "Networking", "Uncategorized"], saved_folders)

    def test_folder_visibility_view_matrix_search_markup_and_effective_counts(self):
        with tempfile.TemporaryDirectory(prefix="dlms-folder-visibility-matrix-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            with open(portal_config, "w", encoding="utf-8") as handle:
                json.dump({
                    "quiz_folders": [
                        "Uncategorized", "Visible Course", "Hidden Course",
                        "Visible Only Course", "Empty Visible", "Empty Hidden",
                    ],
                    "hidden_quiz_folders": ["hidden course", "EMPTY HIDDEN"],
                }, handle)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([
                    {"id": 1, "title": "Visible Quiz", "html": "visible.html", "folder": "Visible Course"},
                    {"id": 2, "title": "Individually Hidden", "html": "individual.html", "folder": "Visible Course", "hidden": True},
                    {"id": 3, "title": "Searchable Archived Quiz", "html": "archived.html", "folder": "Hidden Course"},
                    {"id": 4, "title": "Doubly Hidden", "html": "double.html", "folder": "Hidden Course", "hidden": True},
                    {"id": 5, "title": "Visible Only Quiz", "html": "visible-only.html", "folder": "Visible Only Course"},
                ], handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                client = dlms.app.test_client()
                visible = client.get("/library?view=visible").get_data(as_text=True)
                hidden = client.get("/library?view=hidden").get_data(as_text=True)
                all_quizzes = client.get("/library?view=all").get_data(as_text=True)

            self.assertIn(
                'class="library-folder library-folder-is-hidden library-view-search-only" '
                'data-folder-name="Hidden Course"',
                visible,
            )
            self.assertIn("Searchable Archived Quiz", visible)
            self.assertIn("Folder hidden", visible)
            self.assertNotIn("Individually Hidden", visible)
            self.assertIn("<h2>Visible Only Course</h2>", visible)
            self.assertIn("Visible Only Quiz", visible)
            self.assertIn("<h2>Empty Visible</h2>", visible)
            self.assertNotIn("<h2>Empty Hidden", visible)
            self.assertIn(
                '<span>Visible</span><strong>2</strong><small>available quizzes</small>',
                visible,
            )
            self.assertIn(
                '<span>Hidden</span><strong>3</strong><small>hidden quizzes</small>',
                visible,
            )
            self.assertIn(
                '<span>This View</span><strong>2</strong><small>Visible items</small>',
                visible,
            )
            for script_fragment in (
                "library-view-search-only",
                "library-search-revealed",
                "folder.dataset.librarySearchWasCollapsed",
                'document.getElementById("libraryEmptyState")',
            ):
                self.assertIn(script_fragment, visible)

            self.assertIn("Searchable Archived Quiz", hidden)
            self.assertIn("Doubly Hidden", hidden)
            self.assertIn("Individually Hidden", hidden)
            self.assertNotIn("<h3>Visible Quiz</h3>", hidden)
            self.assertNotIn("<h2>Visible Only Course", hidden)
            self.assertNotIn("Visible Only Quiz", hidden)
            self.assertIn("<h2>Empty Hidden", hidden)
            self.assertNotIn("<h2>Empty Visible</h2>", hidden)
            self.assertIn(
                '<span>This View</span><strong>3</strong><small>Hidden items</small>',
                hidden,
            )

            for title in (
                "Visible Quiz", "Individually Hidden",
                "Searchable Archived Quiz", "Doubly Hidden", "Visible Only Quiz",
            ):
                self.assertIn(title, all_quizzes)
            self.assertIn("<h2>Empty Visible</h2>", all_quizzes)
            self.assertIn("<h2>Empty Hidden", all_quizzes)

    def test_folder_hide_move_unhide_rename_and_delete_preserve_quiz_flags(self):
        with tempfile.TemporaryDirectory(prefix="dlms-folder-visibility-lifecycle-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            original_registry = [
                {"id": 1, "title": "Visible Member", "html": "visible.html", "folder": "CISM"},
                {"id": 2, "title": "Hidden Member", "html": "hidden.html", "folder": "CISM", "hidden": True},
            ]
            with open(portal_config, "w", encoding="utf-8") as handle:
                json.dump({"quiz_folders": ["Uncategorized", "CISM", "Destination"]}, handle)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump(original_registry, handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                client = dlms.app.test_client()
                hide = client.post(
                    "/set_quiz_folder_hidden",
                    data={"folder": "cism", "hidden": "1", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                self.assertEqual(302, hide.status_code)
                self.assertEqual(["CISM"], dlms.get_hidden_quiz_folders())
                self.assertEqual(original_registry, dlms.load_registry())

                hidden_page = client.get("/library?view=hidden").get_data(as_text=True)
                self.assertIn("Visible Member", hidden_page)
                self.assertIn("Hidden Member", hidden_page)
                self.assertIn("Hidden folder", hidden_page)
                self.assertIn('<option value="CISM" selected>CISM (hidden)</option>', hidden_page)

                move_out = client.post(
                    "/move_quiz_folder",
                    data={"id": "1", "folder": "Destination", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                self.assertEqual(302, move_out.status_code)
                moved = dlms.load_registry()
                self.assertNotIn("hidden", moved[0])
                self.assertTrue(moved[1]["hidden"])
                self.assertIn("Visible Member", client.get("/library").get_data(as_text=True))

                move_back = client.post(
                    "/move_quiz_folder",
                    data={"id": "1", "folder": "CISM", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                self.assertEqual(302, move_back.status_code)
                self.assertNotIn("hidden", dlms.load_registry()[0])

                unhide = client.post(
                    "/set_quiz_folder_hidden",
                    data={"folder": "CISM", "hidden": "0", "view": "hidden"},
                    headers=csrf_headers(client, "/library?view=hidden"),
                )
                self.assertEqual(302, unhide.status_code)
                visible_page = client.get("/library").get_data(as_text=True)
                self.assertIn("Visible Member", visible_page)
                self.assertNotIn("Hidden Member", visible_page)
                self.assertTrue(dlms.load_registry()[1]["hidden"])

                client.post(
                    "/set_quiz_folder_hidden",
                    data={"folder": "CISM", "hidden": "1", "view": "all"},
                    headers=csrf_headers(client, "/library?view=all"),
                )
                rename = client.post(
                    "/rename_quiz_folder",
                    data={"old_folder": "CISM", "new_folder": "Archived CISM", "view": "all"},
                    headers=csrf_headers(client, "/library?view=all"),
                )
                self.assertEqual(302, rename.status_code)
                self.assertEqual(["Archived CISM"], dlms.get_hidden_quiz_folders())
                self.assertTrue(all(q["folder"] == "Archived CISM" for q in dlms.load_registry()))

                delete = client.post(
                    "/delete_quiz_folder",
                    data={"folder": "Archived CISM", "view": "hidden"},
                    headers=csrf_headers(client, "/library?view=hidden"),
                )
                self.assertEqual(302, delete.status_code)
                self.assertEqual([], dlms.get_hidden_quiz_folders())
                deleted_registry = dlms.load_registry()
                self.assertTrue(all(q["folder"] == "Uncategorized" for q in deleted_registry))
                self.assertNotIn("hidden", deleted_registry[0])
                self.assertTrue(deleted_registry[1]["hidden"])

    def test_empty_hidden_folder_and_hidden_last_quiz_move_remain_persistent(self):
        with tempfile.TemporaryDirectory(prefix="dlms-hidden-empty-folder-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            with open(portal_config, "w", encoding="utf-8") as handle:
                json.dump({
                    "quiz_folders": [
                        "Uncategorized", "Empty Archive", "Archive", "Destination"
                    ]
                }, handle)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([{"id": 1, "title": "Only Quiz", "html": "only.html", "folder": "Archive"}], handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                client = dlms.app.test_client()
                client.post(
                    "/set_quiz_folder_hidden",
                    data={"folder": "Empty Archive", "hidden": "1", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                self.assertNotIn(
                    "<h2>Empty Archive",
                    client.get("/library?view=visible").get_data(as_text=True),
                )
                self.assertIn(
                    "<h2>Empty Archive",
                    client.get("/library?view=hidden").get_data(as_text=True),
                )
                client.post(
                    "/set_quiz_folder_hidden",
                    data={"folder": "Empty Archive", "hidden": "0", "view": "hidden"},
                    headers=csrf_headers(client, "/library?view=hidden"),
                )
                self.assertIn(
                    "<h2>Empty Archive</h2>",
                    client.get("/library?view=visible").get_data(as_text=True),
                )

                client.post(
                    "/set_quiz_folder_hidden",
                    data={"folder": "Archive", "hidden": "1", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                client.post(
                    "/move_quiz_folder",
                    data={"id": "1", "folder": "Destination", "view": "hidden"},
                    headers=csrf_headers(client, "/library?view=hidden"),
                )
                hidden_page = client.get("/library?view=hidden").get_data(as_text=True)
                all_page = client.get("/library?view=all").get_data(as_text=True)
                visible_page = client.get("/library?view=visible").get_data(as_text=True)
                self.assertIn("<h2>Archive", hidden_page)
                self.assertIn("No quizzes in this view.", hidden_page)
                self.assertIn("<h2>Archive", all_page)
                self.assertNotIn("<h2>Archive", visible_page)
                self.assertEqual(["Archive"], dlms.get_hidden_quiz_folders())

                client.post(
                    "/set_quiz_folder_hidden",
                    data={"folder": "Archive", "hidden": "0", "view": "hidden"},
                    headers=csrf_headers(client, "/library?view=hidden"),
                )
                self.assertIn("<h2>Archive</h2>", client.get("/library").get_data(as_text=True))

    def test_uncategorized_is_not_hideable_and_legacy_hide_promotes_only_that_folder(self):
        with tempfile.TemporaryDirectory(prefix="dlms-hidden-legacy-folder-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            with open(portal_config, "w", encoding="utf-8") as handle:
                json.dump({"quiz_folders": ["Uncategorized"]}, handle)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([{"id": 1, "title": "Legacy Quiz", "html": "legacy.html", "folder": "Legacy Course"}], handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                client = dlms.app.test_client()
                for protected_name in ("Uncategorized", "uNcAtEgOrIzEd"):
                    response = client.post(
                        "/set_quiz_folder_hidden",
                        data={"folder": protected_name, "hidden": "1", "view": "visible"},
                        headers=csrf_headers(client, "/library"),
                    )
                    self.assertEqual(302, response.status_code)
                self.assertEqual([], dlms.get_hidden_quiz_folders())
                client.get("/library")
                self.assertEqual(["Uncategorized"], dlms.get_quiz_folders())

                response = client.post(
                    "/set_quiz_folder_hidden",
                    data={"folder": "legacy course", "hidden": "1", "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )
                self.assertEqual(302, response.status_code)
                self.assertEqual(
                    ["Uncategorized", "Legacy Course"], dlms.get_quiz_folders()
                )
                self.assertEqual(["Legacy Course"], dlms.get_hidden_quiz_folders())

    def test_visible_folder_reorder_preserves_omitted_hidden_folder_slot(self):
        with tempfile.TemporaryDirectory(prefix="dlms-hidden-folder-order-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            os.makedirs(config_dir, exist_ok=True)
            with open(portal_config, "w", encoding="utf-8") as handle:
                json.dump({
                    "quiz_folders": ["Uncategorized", "First", "Hidden Anchor", "Second", "Third"],
                    "hidden_quiz_folders": ["Hidden Anchor"],
                }, handle)
            with open(quiz_registry, "w", encoding="utf-8") as handle:
                json.dump([], handle)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry):
                client = dlms.app.test_client()
                response = client.post(
                    "/save_folder_order",
                    json={"folders": ["Third", "First", "Second"], "view": "visible"},
                    headers=csrf_headers(client, "/library"),
                )

                self.assertEqual(200, response.status_code)
                self.assertEqual(
                    ["Uncategorized", "Third", "Hidden Anchor", "First", "Second"],
                    dlms.get_quiz_folders(),
                )
                self.assertEqual(["Hidden Anchor"], dlms.get_hidden_quiz_folders())

    def test_quiz_library_reset_preserves_folder_hidden_state(self):
        with tempfile.TemporaryDirectory(prefix="dlms-hidden-folder-reset-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            db_path = os.path.join(directory, "results.db")
            quiz_folder = os.path.join(directory, "quizzes")
            data_folder = os.path.join(directory, "data")
            asset_folder = os.path.join(directory, "quiz_assets")
            logo_folder = os.path.join(directory, "logos")
            for path in (config_dir, quiz_folder, data_folder, asset_folder, logo_folder):
                os.makedirs(path, exist_ok=True)

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "DB_PATH", db_path), \
                    mock.patch.object(dlms, "QUIZ_FOLDER", quiz_folder), \
                    mock.patch.object(dlms, "DATA_FOLDER", data_folder), \
                    mock.patch.object(dlms, "QUIZ_ASSET_FOLDER", asset_folder), \
                    mock.patch.object(dlms, "LOGO_FOLDER", logo_folder), \
                    mock.patch.object(dlms, "_ensure_runtime_data_dirs"):
                dlms.bootstrap_database(db_path, require_owned_root=False)
                dlms.save_quiz_folder_state(
                    ["Uncategorized", "Hidden Archive"], ["Hidden Archive"]
                )
                dlms.save_registry([{
                    "id": 1,
                    "title": "Reset Quiz",
                    "html": "reset.html",
                    "folder": "Hidden Archive",
                }])

                dlms._reset_quiz_library_core()

                self.assertEqual([], dlms.load_registry())
                self.assertEqual(
                    ["Uncategorized", "Hidden Archive"], dlms.get_quiz_folders()
                )
                self.assertEqual(
                    ["Hidden Archive"], dlms.get_hidden_quiz_folders()
                )

    def test_settings_reset_clears_folder_configuration_without_changing_quizzes(self):
        with tempfile.TemporaryDirectory(prefix="dlms-hidden-folder-settings-reset-") as directory:
            config_dir = os.path.join(directory, "config")
            portal_config = os.path.join(config_dir, "portal.json")
            quiz_registry = os.path.join(config_dir, "quizzes.json")
            background_folder = os.path.join(directory, "backgrounds")
            os.makedirs(config_dir, exist_ok=True)
            os.makedirs(background_folder, exist_ok=True)
            quiz = {
                "id": 1,
                "title": "Preserved Quiz",
                "html": "preserved.html",
                "folder": "Hidden Archive",
                "hidden": True,
            }

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", quiz_registry), \
                    mock.patch.object(dlms, "BACKGROUND_FOLDER", background_folder):
                dlms.save_quiz_folder_state(
                    ["Uncategorized", "Hidden Archive"], ["Hidden Archive"]
                )
                dlms.save_registry([quiz])

                dlms._reset_app_settings_core()

                self.assertEqual(["Uncategorized"], dlms.get_quiz_folders())
                self.assertEqual([], dlms.get_hidden_quiz_folders())
                self.assertEqual([quiz], dlms.load_registry())

    def test_fresh_configuration_enables_confidence_and_ai_helpers(self):
        with tempfile.TemporaryDirectory(prefix="dlms-fresh-config-") as directory:
            portal_config = os.path.join(directory, "config", "portal.json")

            with mock.patch.object(dlms, "PORTAL_CONFIG", portal_config):
                config = dlms.load_portal_config()

            self.assertTrue(config["show_confidence"])
            self.assertTrue(config["ai_helper_enabled"])
            self.assertEqual(config["quiz_folders"], ["Uncategorized"])
            self.assertEqual(config["hidden_quiz_folders"], [])

            with open(portal_config, "r", encoding="utf-8") as file:
                persisted = json.load(file)
            self.assertTrue(persisted["show_confidence"])
            self.assertTrue(persisted["ai_helper_enabled"])
            self.assertEqual(persisted["quiz_folders"], ["Uncategorized"])
            self.assertEqual(persisted["hidden_quiz_folders"], [])

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
