"""Structural closure gate for DLMS-062 template externalization."""

import ast
import re
import unittest
from pathlib import Path

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
TEMPLATE_ROOT = ROOT / "templates"
ROUTE_ROOT = ROOT / "dlms" / "routes"


class Dlms062TemplateClosureTests(unittest.TestCase):
    FIXED_INVENTORY = {
        1: ("_csrf_failure", "errors/request-rejected.html"),
        2: ("dlms_request_too_large", "errors/request-too-large.html"),
        3: (None, "shared/_settings-sidebar.html"),
        4: ("home", "dashboard/index.html"),
        5: ("quiz_library", "quiz/library.html"),
        6: ("edit_quiz", "quiz/edit.html"),
        7: ("upload_page", "quiz/upload.html"),
        8: ("paste_page", "quiz/paste.html"),
        9: ("matching_bank_import", "quiz/matching-bank-import.html"),
        10: ("create_short_quiz_page", "quiz/short-builder.html"),
        11: ("preview_paste", "quiz/paste-preview.html"),
        12: ("process_paste", "quiz/parse-failed.html"),
        13: ("process_file", "quiz/parse-failed.html"),
        14: ("pdf_import_page", "pdf_import/index.html"),
        15: ("_render_pdf_glossary_review", "pdf_import/review-glossary.html"),
        16: ("pdf_import_review", "pdf_import/review-question-bank.html"),
        17: ("pdf_question_bank_page", "pdf_import/question-bank.html"),
        18: ("pdf_terminology_bank_page", "pdf_import/terminology-bank.html"),
        19: ("study_pack_ai_builder", "study_packs/ai-builder.html"),
        20: ("image_quiz_builder", "study_packs/image-builder.html"),
        21: ("admin_hotspot_editor", "admin/image-editor.html"),
        22: ("law_view_case_review", "law/case-detail.html"),
        23: ("anki_tools", "anki/index.html"),
        24: ("anki_custom_deck", "anki/custom.html"),
        25: ("anki_printable_flashcards", "anki/printable.html"),
        26: ("anki_law_tools", "anki/law.html"),
    }

    @classmethod
    def setUpClass(cls):
        cls.app_source = APP_PATH.read_text(encoding="utf-8")
        cls.source_trees = {
            APP_PATH: ast.parse(cls.app_source),
            **{
                path: ast.parse(path.read_text(encoding="utf-8"))
                for path in sorted(ROUTE_ROOT.rglob("*.py"))
            },
        }

    def test_fixed_inventory_one_through_twenty_six_is_external_and_present(self):
        self.assertEqual(list(range(1, 27)), sorted(self.FIXED_INVENTORY))
        functions = [
            (path, node)
            for path, tree in self.source_trees.items()
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]

        for item, (function_name, template_name) in self.FIXED_INVENTORY.items():
            with self.subTest(item=item, template=template_name):
                template_path = (TEMPLATE_ROOT / template_name).resolve()
                self.assertTrue(template_path.is_relative_to(TEMPLATE_ROOT.resolve()))
                self.assertTrue(template_path.is_file())
                if function_name is None:
                    continue
                matching_calls = [
                    (path, call)
                    for path, function in functions
                    if function.name == function_name
                    for call in ast.walk(function)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "render_template"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and call.args[0].value == template_name
                ]
                self.assertEqual(1, len(matching_calls))

        shared_sidebar = (TEMPLATE_ROOT / "shared/_settings-sidebar.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("{% macro settings_shell_sidebar", shared_sidebar)
        consumers = [
            TEMPLATE_ROOT / "admin/maintenance.html",
            *sorted((TEMPLATE_ROOT / "settings").glob("*.html")),
        ]
        for consumer in consumers:
            with self.subTest(sidebar_consumer=consumer.relative_to(TEMPLATE_ROOT)):
                self.assertIn(
                    '{% from "shared/_settings-sidebar.html" import settings_shell_sidebar -%}',
                    consumer.read_text(encoding="utf-8"),
                )

    def test_active_route_sources_have_no_string_renderer_or_embedded_page_payload(self):
        html_fragment = re.compile(
            r"<!doctype\s+html|<(?:html|head|body|title|main|aside|nav|section|form|script|style)\b",
            re.IGNORECASE,
        )
        jinja_statement = re.compile(
            r"{%-?\s*(?:extends|include|import|from|block|macro|if|for|set|call|filter|with)\b"
        )
        jinja_expression = re.compile(r"{{-?\s*[A-Za-z_]", re.MULTILINE)
        for path, tree in self.source_trees.items():
            with self.subTest(route_source=path.relative_to(ROOT)):
                flask_imports = [
                    alias.name
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom) and node.module == "flask"
                    for alias in node.names
                ]
                self.assertNotIn("render_template_string", flask_imports)

                string_renderer_calls = [
                    node.lineno
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and (
                        isinstance(node.func, ast.Name)
                        and node.func.id == "render_template_string"
                        or isinstance(node.func, ast.Attribute)
                        and node.func.attr == "render_template_string"
                    )
                ]
                self.assertEqual([], string_renderer_calls)

                payloads = []
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                        continue
                    value = node.value
                    looks_like_page = html_fragment.search(value) or jinja_statement.search(value)
                    looks_like_multiline_jinja = "\n" in value and jinja_expression.search(value)
                    if looks_like_page or looks_like_multiline_jinja:
                        payloads.append((node.lineno, value[:80]))
                self.assertEqual([], payloads)

    def test_template_root_dashboard_static_pages_and_inventory_are_normalized(self):
        self.assertEqual(TEMPLATE_ROOT.resolve(), Path(dlms.TEMPLATE_ROOT).resolve())
        self.assertEqual(TEMPLATE_ROOT.resolve(), Path(dlms.app.template_folder).resolve())

        templates = sorted(TEMPLATE_ROOT.rglob("*.html"))
        self.assertEqual(58, len(templates))
        self.assertTrue((TEMPLATE_ROOT / "dashboard/index.html").is_file())
        self.assertFalse((ROOT / "static/index.html").exists())
        self.assertNotIn("static/index.html", self.app_source)
        self.assertNotIn("static/index.html", (ROOT / "DLMS.spec").read_text(encoding="utf-8"))

        static_pages = sorted((ROOT / "static").glob("*.html"))
        self.assertEqual(25, len(static_pages))
        for page in static_pages:
            source = page.read_text(encoding="utf-8")
            with self.subTest(static_page=page.name):
                self.assertNotRegex(source, r"{%[-\s]")
                expressions = set(re.findall(r"{{\s*[^}]+\s*}}", source))
                if page.name == "review.html":
                    self.assertEqual({"{{questions}}"}, expressions)
                else:
                    self.assertEqual(set(), expressions)

    def test_packaging_includes_template_root_and_generated_quiz_html_stays_separate(self):
        spec_source = (ROOT / "DLMS.spec").read_text(encoding="utf-8")
        spec_tree = ast.parse(spec_source)
        bundle_assignment = next(
            node
            for node in spec_tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "bundle_data" for target in node.targets)
        )
        destinations = {
            item.elts[1].value
            for item in bundle_assignment.value.elts
            if isinstance(item, ast.Tuple)
            and len(item.elts) == 2
            and isinstance(item.elts[1], ast.Constant)
        }
        source_expressions = {
            ast.unparse(item.elts[0])
            for item in bundle_assignment.value.elts
            if isinstance(item, ast.Tuple) and len(item.elts) == 2
        }
        self.assertEqual({".", "static", "templates"}, destinations)
        self.assertIn("str(project_root / 'templates')", source_expressions)
        self.assertIn("str(project_root / 'static')", source_expressions)

        artifact_path = ROOT / "dlms/rendering/quiz_artifacts.py"
        artifact_source = artifact_path.read_text(encoding="utf-8")
        artifact_tree = ast.parse(artifact_source)
        builder = next(
            node
            for node in artifact_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_quiz_html"
        )
        builder_source = ast.get_source_segment(artifact_source, builder)
        self.assertIn('html = f"""<!DOCTYPE html>', builder_source)
        self.assertIn('open_file(outpath, "w", encoding="utf-8")', builder_source)
        self.assertIn("f.write(html)", builder_source)
        self.assertNotIn("render_template", builder_source)

    def test_cross_repository_source_scanners_include_external_templates(self):
        expected_markers = {
            "tests/test_accessibility_cleanup.py": '(ROOT / "templates").rglob("*.html")',
            "tests/test_csrf_protection.py": 'Path(dlms.TEMPLATE_ROOT).rglob("*.html")',
            "tests/test_theme_system.py": 'Path(dlms.TEMPLATE_ROOT, "anki", name)',
            "tests/test_backup_browser_content_allowlist.py": 'Path(dlms.TEMPLATE_ROOT) / "study_packs" / "ai-builder.html"',
            "tests/test_release_hygiene.py": '(ROOT / "templates").rglob("*.html")',
        }
        for relative_path, marker in expected_markers.items():
            with self.subTest(source_scanner=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
