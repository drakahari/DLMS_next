"""Structural and integration coverage for DLMS-061 Blueprint Batch 4."""

import ast
import dataclasses
import inspect
import re
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask, url_for

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import pdf_import as pdf_import_routes


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
PDF_IMPORT_ROUTE_PATH = ROOT / "dlms" / "routes" / "pdf_import.py"


class PDFImportBlueprintTests(unittest.TestCase):
    EXPECTED_RULES = {
        "pdf_import.pdf_import_page": ("/pdf-import", {"GET"}),
        "pdf_import.pdf_question_bank_delete": (
            "/pdf-import/bank/<bank_id>/delete",
            {"POST"},
        ),
        "pdf_import.pdf_terminology_bank_delete": (
            "/pdf-import/terms/<bank_id>/delete",
            {"POST"},
        ),
        "pdf_import.pdf_import_analyze": ("/pdf-import/analyze", {"POST"}),
        "pdf_import.pdf_import_review": (
            "/pdf-import/review/<draft_id>",
            {"GET"},
        ),
        "pdf_import.pdf_import_save": (
            "/pdf-import/save/<draft_id>",
            {"POST"},
        ),
        "pdf_import.pdf_question_banks_page": ("/pdf-import/banks", {"GET"}),
        "pdf_import.pdf_question_bank_page": (
            "/pdf-import/bank/<bank_id>",
            {"GET"},
        ),
        "pdf_import.pdf_question_bank_generate": (
            "/pdf-import/bank/<bank_id>/generate",
            {"POST"},
        ),
        "pdf_import.pdf_terminology_banks_page": (
            "/pdf-import/terms",
            {"GET"},
        ),
        "pdf_import.pdf_terminology_bank_page": (
            "/pdf-import/terms/<bank_id>",
            {"GET"},
        ),
        "pdf_import.pdf_terminology_bank_generate": (
            "/pdf-import/terms/<bank_id>/generate",
            {"POST"},
        ),
    }
    EXPECTED_DEPENDENCIES = {
        "pdf_import_max_bytes",
        "upload_multipart_overhead_bytes",
        "save_pdf_import_upload",
        "remove_pdf_import_upload",
        "save_pdf_import_draft",
        "load_pdf_import_draft",
        "delete_pdf_import_draft",
        "list_pdf_question_banks",
        "save_pdf_question_bank",
        "load_pdf_question_bank",
        "delete_pdf_question_bank",
        "list_pdf_terminology_banks",
        "save_pdf_terminology_bank",
        "load_pdf_terminology_bank",
        "delete_pdf_terminology_bank",
        "extract_pdf_pages",
        "suppress_repeated_pdf_margins",
        "parse_pdf_question_bank",
        "parse_pdf_glossary",
        "detect_pdf_document_type",
        "recover_pdf_questions",
        "recover_pdf_glossary",
        "add_pdf_question_review_slots",
        "secure_filename",
        "normalize_exam_minutes",
        "timestamp_now",
        "publish_quiz",
        "create_quiz_from_runtime",
    }

    def test_blueprint_is_registered_once_and_owns_exact_reconciled_rules(self):
        self.assertEqual(1, list(dlms.app.blueprints).count("pdf_import"))

        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        registrations = [
            node
            for node in ast.walk(app_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "app"
            and node.func.attr == "register_blueprint"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == "create_pdf_import_blueprint"
        ]
        self.assertEqual(1, len(registrations))

        rules = {
            rule.endpoint: rule
            for rule in dlms.app.url_map.iter_rules()
            if rule.rule == "/pdf-import" or rule.rule.startswith("/pdf-import/")
        }
        self.assertEqual(set(self.EXPECTED_RULES), set(rules))
        for endpoint, (path, methods) in self.EXPECTED_RULES.items():
            with self.subTest(endpoint=endpoint):
                rule = rules[endpoint]
                self.assertEqual(path, rule.rule)
                expected_methods = methods | {"OPTIONS"}
                if "GET" in methods:
                    expected_methods.add("HEAD")
                self.assertEqual(expected_methods, rule.methods)
                self.assertTrue(rule.strict_slashes)
                self.assertEqual(
                    "dlms.routes.pdf_import",
                    dlms.app.view_functions[endpoint].__module__,
                )

    def test_namespaced_endpoints_build_original_public_urls(self):
        values = {
            "pdf_import.pdf_question_bank_delete": {"bank_id": "question_bank"},
            "pdf_import.pdf_terminology_bank_delete": {"bank_id": "term_bank"},
            "pdf_import.pdf_import_review": {"draft_id": "draft"},
            "pdf_import.pdf_import_save": {"draft_id": "draft"},
            "pdf_import.pdf_question_bank_page": {"bank_id": "question_bank"},
            "pdf_import.pdf_question_bank_generate": {"bank_id": "question_bank"},
            "pdf_import.pdf_terminology_bank_page": {"bank_id": "term_bank"},
            "pdf_import.pdf_terminology_bank_generate": {"bank_id": "term_bank"},
        }
        expected_paths = {
            endpoint: path.replace("<bank_id>", values.get(endpoint, {}).get("bank_id", ""))
            .replace("<draft_id>", values.get(endpoint, {}).get("draft_id", ""))
            for endpoint, (path, _methods) in self.EXPECTED_RULES.items()
        }
        with dlms.app.test_request_context():
            for endpoint, expected in expected_paths.items():
                with self.subTest(endpoint=endpoint):
                    self.assertEqual(
                        expected, url_for(endpoint, **values.get(endpoint, {}))
                    )

    def test_dependencies_are_explicit_frozen_and_module_does_not_import_app(self):
        self.assertEqual(
            self.EXPECTED_DEPENDENCIES,
            {
                field.name
                for field in dataclasses.fields(
                    pdf_import_routes.PDFImportRouteDependencies
                )
            },
        )
        self.assertTrue(
            pdf_import_routes.PDFImportRouteDependencies.__dataclass_params__.frozen
        )
        self.assertEqual(
            ["dependencies"],
            list(
                inspect.signature(
                    pdf_import_routes.create_pdf_import_blueprint
                ).parameters
            ),
        )

        tree = ast.parse(PDF_IMPORT_ROUTE_PATH.read_text(encoding="utf-8"))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_from = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        self.assertNotIn("app", imported_modules)
        self.assertNotIn("app", imported_from)

    def test_migrated_handlers_are_not_app_owned_and_url_for_targets_are_safe(self):
        old_names = {endpoint.split(".", 1)[1] for endpoint in self.EXPECTED_RULES}
        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        app_route_functions = {
            node.name
            for node in app_tree.body
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"route", "get", "post"}
                for decorator in node.decorator_list
            )
        }
        self.assertTrue(old_names.isdisjoint(app_route_functions))
        self.assertTrue(old_names.isdisjoint(dlms.app.view_functions))

        route_trees = [app_tree] + [
            ast.parse(path.read_text(encoding="utf-8"))
            for path in (ROOT / "dlms" / "routes").rglob("*.py")
        ]
        url_for_targets = {
            node.args[0].value
            for tree in route_trees
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "url_for"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        self.assertTrue(old_names.isdisjoint(url_for_targets))

        template_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
        )
        template_targets = set(
            re.findall(r"url_for\(\s*['\"]([^'\"]+)", template_source)
        )
        self.assertTrue(old_names.isdisjoint(template_targets))
        self.assertTrue(
            all(
                target.startswith("pdf_import.")
                for target in template_targets
                if target.startswith("pdf_import")
            )
        )

    def test_factory_uses_the_injected_catalog_boundary(self):
        services = {
            name: mock.Mock() for name in self.EXPECTED_DEPENDENCIES
        }
        services["list_pdf_question_banks"].return_value = [{"id": "questions"}]
        services["list_pdf_terminology_banks"].return_value = [{"id": "terms"}]
        dependencies = pdf_import_routes.PDFImportRouteDependencies(**services)
        application = Flask(__name__)
        application.register_blueprint(
            pdf_import_routes.create_pdf_import_blueprint(dependencies)
        )

        with mock.patch.object(
            pdf_import_routes, "render_template", return_value="rendered"
        ) as rendered:
            response = application.test_client().get("/pdf-import")

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"rendered", response.data)
        rendered.assert_called_once_with(
            "pdf_import/index.html",
            banks=[{"id": "questions"}],
            term_banks=[{"id": "terms"}],
        )

    def test_global_security_and_strict_slash_behavior_are_preserved(self):
        client = dlms.app.test_client()
        response = client.get("/pdf-import")
        self.assertEqual(200, response.status_code)
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])
        self.assertIn("dlms_csrf_token=", response.headers.get("Set-Cookie", ""))

        for endpoint, (path, methods) in self.EXPECTED_RULES.items():
            if methods != {"GET"} or "<" in path:
                continue
            with self.subTest(endpoint=endpoint):
                self.assertEqual(404, client.get(f"{path}/").status_code)


if __name__ == "__main__":
    unittest.main()
