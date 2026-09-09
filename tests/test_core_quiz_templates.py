import ast
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import core as core_routes
from markupsafe import escape


ROOT = Path(dlms.__file__).resolve().parent
TEMPLATE_ROOT = Path(dlms.TEMPLATE_ROOT)


class CoreQuizExternalTemplateTests(unittest.TestCase):
    ROUTE_TEMPLATES = {
        "_csrf_failure": "errors/request-rejected.html",
        "dlms_request_too_large": "errors/request-too-large.html",
        "home": "dashboard/index.html",
        "quiz_library": "quiz/library.html",
        "edit_quiz": "quiz/edit.html",
        "upload_page": "quiz/upload.html",
        "paste_page": "quiz/paste.html",
        "matching_bank_import": "quiz/matching-bank-import.html",
        "create_short_quiz_page": "quiz/short-builder.html",
        "preview_paste": "quiz/paste-preview.html",
        "process_paste": "quiz/parse-failed.html",
        "process_file": "quiz/parse-failed.html",
    }

    def setUp(self):
        self.previous_testing = dlms.app.config.get("TESTING")
        dlms.app.config["TESTING"] = True
        self.addCleanup(dlms.app.config.__setitem__, "TESTING", self.previous_testing)

    def test_inventory_items_use_external_templates_under_template_root(self):
        source = Path(dlms.__file__).read_text(encoding="utf-8")
        trees = [
            ast.parse(source),
            *[
                ast.parse(path.read_text(encoding="utf-8"))
                for path in sorted((ROOT / "dlms" / "routes").rglob("*.py"))
            ],
        ]

        for function_name, template_name in self.ROUTE_TEMPLATES.items():
            with self.subTest(function=function_name):
                function = next(
                    node
                    for tree in trees
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == function_name
                )
                external_calls = [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "render_template"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == template_name
                ]
                self.assertEqual(1, len(external_calls))
                self.assertTrue((TEMPLATE_ROOT / template_name).is_file())

        self.assertNotIn("def _settings_shell_sidebar", source)
        self.assertNotIn('app.jinja_env.globals["settings_shell_sidebar"]', source)
        self.assertFalse((ROOT / "static" / "index.html").exists())

    def test_shared_sidebar_macro_preserves_seed_markup_and_escaping(self):
        with dlms.app.app_context():
            macro = dlms.app.jinja_env.get_template(
                "shared/_settings-sidebar.html"
            ).module.settings_shell_sidebar

            rendered = str(macro('<Settings & "Tools">'))

        self.assertTrue(rendered.startswith("\n<aside"))
        self.assertTrue(rendered.endswith("</aside>"))
        self.assertIn('aria-label="Primary navigation"', rendered)
        self.assertIn("&lt;Settings &amp; &#34;Tools&#34;&gt;", rendered)
        self.assertNotIn('<Settings & "Tools">', rendered)

        consumers = [
            TEMPLATE_ROOT / "admin" / "maintenance.html",
            *sorted((TEMPLATE_ROOT / "settings").glob("*.html")),
        ]
        for path in consumers:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIn(
                    '{% from "shared/_settings-sidebar.html" import settings_shell_sidebar -%}',
                    source,
                )

    def test_csrf_failure_keeps_html_json_status_and_escaping_contracts(self):
        marker = '</p><script id="csrf-injection">alert(1)</script>&'
        with dlms.app.test_request_context("/set_quiz_folder_hidden", method="POST"):
            body, status = dlms._csrf_failure(marker, 403)

        self.assertEqual(403, status)
        self.assertIn("<h1>Request rejected</h1>", body)
        self.assertIn(str(escape(marker)), body)
        self.assertNotIn('id="csrf-injection"', body)
        self.assertIn("javascript:history.back()", body)

        with dlms.app.test_request_context("/api/theme", method="POST", json={}):
            response, status = dlms._csrf_failure(marker, 400)

        self.assertEqual(400, status)
        self.assertEqual({"error": marker}, response.get_json())

    def test_request_too_large_page_keeps_status_copy_and_recovery_links(self):
        with dlms.app.test_request_context("/upload", method="POST"):
            body, status = dlms.dlms_request_too_large(None)

        self.assertEqual(413, status)
        self.assertIn("Upload is too large", body)
        self.assertIn("Smart PDF Import accepts PDF files up to 64 MB", body)
        self.assertIn('href="javascript:history.back()"', body)
        self.assertIn('href="/"', body)

    def test_dashboard_renders_from_template_with_exact_context_and_escaping(self):
        marker = '</title><script id="dashboard-injection">alert(1)</script>'
        packs = [{"id": "ignored-by-current-dashboard"}]
        client = dlms.app.test_client()

        with mock.patch.object(dlms, "get_portal_title", return_value=marker), mock.patch.object(
            dlms, "content_pack_summary", return_value=packs
        ):
            response = client.get("/")

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn(str(escape(marker)), body)
        self.assertNotIn('id="dashboard-injection"', body)
        self.assertIn("/api/attempts/overview", body)
        self.assertIn("function escapeHtml(value)", body)
        self.assertIn('fetch("/api/shutdown", { method: "POST" })', body)
        self.assertIn('aria-label="Primary navigation"', body)

        with mock.patch.object(core_routes, "render_template", return_value="dashboard-sentinel") as render:
            with mock.patch.object(dlms, "get_portal_title", return_value="Portal"), mock.patch.object(
                dlms, "content_pack_summary", return_value=packs
            ):
                result = dlms.app.view_functions["core.home"]()
        self.assertEqual("dashboard-sentinel", result)
        render.assert_called_once_with(
            "dashboard/index.html",
            portal_title="Portal",
            app_version=dlms.APP_VERSION,
            installed_content_packs=packs,
        )

    def test_library_template_preserves_forms_states_javascript_and_escaping(self):
        folder = '<Folder "unsafe">'
        quiz = {
            "id": 73,
            "html": 'unsafe" quiz.html',
            "title": '</h3><script id="quiz-injection">alert(1)</script>',
            "logo": None,
            "hidden": False,
            "folder": folder,
        }
        context = {
            "quizzes": [quiz],
            "grouped_quizzes": {folder: [quiz]},
            "folder_names": [folder],
            "display_folder_names": [folder],
            "normal_display_folder_names": [folder],
            "hidden_folder_keys": set(),
            "portal_title": "Portal",
            "visible_count": 1,
            "hidden_count": 0,
            "view_quiz_count": 1,
            "view": "visible",
            "app_version": dlms.APP_VERSION,
            "active_quiz_ids": [str(quiz["id"])],
        }
        with dlms.app.test_request_context("/library"):
            body = dlms.render_template("quiz/library.html", **context)

        self.assertNotIn('id="quiz-injection"', body)
        self.assertIn(str(escape(quiz["title"])), body)
        self.assertIn("&lt;Folder &#34;unsafe&#34;&gt;", body)
        for action in (
            "/toggle_hidden",
            "/move_quiz_folder",
            "/set_quiz_folder_hidden",
            "/rename_quiz_folder",
            "/delete_quiz_folder",
            "/delete_quiz/73",
        ):
            self.assertIn(f'action="{action}"', body)
        self.assertIn('aria-live="polite"', body)
        self.assertIn("Sortable.create", body)
        self.assertIn("JSON.stringify(payload)", body)
        self.assertIn('id="libraryQuizIdentityData"', body)
        self.assertIn('src="/static/quiz-recovery.js"', body)
        self.assertIn('/static/nav-normalize.js', body)

    def test_classic_builder_templates_preserve_form_and_script_contracts(self):
        contracts = {
            "quiz/upload.html": (
                'action="/process"',
                'enctype="multipart/form-data"',
                'name="file"',
                'name="quiz_logo"',
                'href="/paste"',
            ),
            "quiz/paste.html": (
                'action="/preview_paste"',
                'enctype="multipart/form-data"',
                'name="quiz_text"',
                'name="quiz_logo"',
            ),
            "quiz/matching-bank-import.html": (
                'method="POST"',
                'enctype="multipart/form-data"',
                'name="csv_file"',
                'name="round_size"',
                'name="direction"',
            ),
            "quiz/short-builder.html": (
                'action="/create_short_quiz"',
                'id="create-short-quiz-form"',
                'name="count"',
                "renumberQuestions()",
                'shortQuizForm.addEventListener("submit"',
            ),
        }
        for template_name, expected in contracts.items():
            source = (TEMPLATE_ROOT / template_name).read_text(encoding="utf-8")
            with self.subTest(template=template_name):
                for value in expected:
                    self.assertIn(value, source)
                self.assertIn('/static/nav-normalize.js', source)

    def test_edit_template_preserves_dynamic_question_and_deletion_contracts(self):
        source = (TEMPLATE_ROOT / "quiz" / "edit.html").read_text(encoding="utf-8")
        for expected in (
            'id="edit-quiz-form"',
            'action="/edit_quiz/{{ quiz[\'id\'] }}"',
            'name="question_{{ q.id }}"',
            'name="matching_round_size_{{ q.id }}"',
            'name="matching_direction_{{ q.id }}"',
            'name="choice_{{ c[\'id\'] }}"',
            'value="add_match_pair_{{ q.id }}"',
            'value="add_choices_{{ q.id }}"',
            'id="delete-question-{{ q.id }}"',
            'id="delete-choice-{{ c.id }}"',
            'id="delete-match-pair-{{ pair.id }}"',
            "Delete this question permanently?",
            "Delete this answer choice?",
            "Delete this matching pair?",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, source)
        self.assertIn('/static/nav-normalize.js', source)

    def test_paste_preview_escapes_round_tripped_text_and_preserves_controls(self):
        original = '</pre><script id="original-injection">alert(1)</script>&\u2028\u2029'
        cleaned = '</textarea><script id="clean-injection">alert(2)</script>&\u2028\u2029'
        context = {
            "quiz_title": '<Quiz "unsafe">',
            "exam_minutes": 90,
            "original": original,
            "cleaned": cleaned,
            "conf_summary": {"total": 0, "high": 0, "medium": 0, "low": 0},
            "conf_details": [],
            "preview_logo_name": "",
            "regex_mode": False,
            "strip_rules": [],
            "replace_rules": [],
            "applied_rules": [],
            "invis_cleanup_enabled": True,
            "removed_unicode": [],
            "preset_number_prefix_checked": False,
            "preset_pdf_spacing_checked": False,
            "preset_headers_checked": False,
            "smart_suggestions": [],
        }
        with dlms.app.test_request_context("/preview_paste", method="POST"):
            body = dlms.render_template("quiz/paste-preview.html", **context)

        self.assertNotIn('id="original-injection"', body)
        self.assertNotIn('id="clean-injection"', body)
        self.assertGreaterEqual(body.count("&lt;script"), 4)
        self.assertIn("\u2028\u2029", body)
        self.assertIn('action="/download_cleaned" method="POST"', body)
        self.assertIn('action="/process_paste" method="POST"', body)
        self.assertIn('name="quiz_text"', body)
        self.assertIn('name="clean_text"', body)
        self.assertIn(
            '<form action="/preview_paste" method="POST"',
            (TEMPLATE_ROOT / "quiz" / "paste-preview.html").read_text(encoding="utf-8"),
        )

    def test_shared_parse_failure_template_preserves_status_recovery_and_escaping(self):
        filename = 'parse" onmouseover="bad<script>.txt'
        with dlms.app.test_request_context("/process_paste", method="POST"):
            body = dlms.render_template("quiz/parse-failed.html", log_filename=filename)

        self.assertIn("Could Not Parse Any Questions", body)
        self.assertIn("/upload", body)
        self.assertIn("/paste", body)
        self.assertIn("/data/parse&#34; onmouseover=&#34;bad&lt;script&gt;.txt", body)
        self.assertNotIn("bad<script>", body)
        self.assertIn('/static/nav-normalize.js', body)


if __name__ == "__main__":
    unittest.main()
