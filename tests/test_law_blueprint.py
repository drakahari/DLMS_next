"""Structural and integration coverage for DLMS-061 Blueprint Batch 5."""

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
from dlms.routes import law as law_routes


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
LAW_ROUTE_PATH = ROOT / "dlms" / "routes" / "law.py"


class LawBlueprintTests(unittest.TestCase):
    EXPECTED_RULES = {
        "law.law_study_home": ("/law", {"GET"}),
        "law.law_create_case_review": ("/law/create", {"GET", "POST"}),
        "law.law_cancel_pending_workflow": ("/law/workflow/cancel", {"POST"}),
        "law.law_import_case_packet": ("/law/import", {"GET", "POST"}),
        "law.law_saved_imports": ("/law/imports", {"GET"}),
        "law.law_view_saved_import": ("/law/imports/<path:filename>", {"GET"}),
        "law.law_delete_saved_import": (
            "/law/imports/<path:filename>/delete",
            {"POST"},
        ),
        "law.law_create_case_from_import": (
            "/law/imports/<path:filename>/create_case",
            {"POST"},
        ),
        "law.law_case_reviews": ("/law/cases", {"GET"}),
        "law.law_view_case_review": ("/law/cases/<case_id>", {"GET"}),
        "law.law_update_case_review_details": (
            "/law/cases/<case_id>/update_details",
            {"POST"},
        ),
        "law.law_delete_case_review": (
            "/law/cases/<case_id>/delete",
            {"POST"},
        ),
        "law.law_update_case_review_notes": (
            "/law/cases/<case_id>/update_notes",
            {"POST"},
        ),
        "law.law_update_socratic_answers": (
            "/law/cases/<case_id>/update_socratic_answers",
            {"POST"},
        ),
        "law.law_update_irac_response": (
            "/law/cases/<case_id>/update_irac_response",
            {"POST"},
        ),
        "law.law_export_case_review_txt": (
            "/law/cases/<case_id>/export.txt",
            {"GET"},
        ),
    }
    EXPECTED_DEPENDENCIES = {
        "app_version",
        "default_law_ai_prompt",
        "get_portal_title",
        "load_portal_config",
        "load_law_registry",
        "law_case_path",
        "law_import_path",
        "make_law_case_slug",
        "safe_law_import_filename",
        "save_law_raw_packet",
        "parse_law_packet_sections",
        "get_law_case_by_id",
        "load_law_case_data",
        "parse_socratic_questions",
        "start_pending_case_workflow",
        "cancel_pending_case_workflow",
        "list_law_raw_imports",
        "load_law_raw_packet",
        "delete_law_raw_packet",
        "create_law_case_from_import",
        "update_law_case_details",
        "delete_law_case_and_registry",
        "update_law_case_notes",
        "update_law_case_socratic_answers",
        "update_law_case_irac_response",
        "build_law_case_export",
        "secure_filename",
        "now",
        "from_timestamp",
    }

    def test_blueprint_is_registered_once_and_owns_exact_reconciled_rules(self):
        self.assertEqual(1, list(dlms.app.blueprints).count("law"))

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
            and node.args[0].func.id == "create_law_blueprint"
        ]
        self.assertEqual(1, len(registrations))

        rules = {
            rule.endpoint: rule
            for rule in dlms.app.url_map.iter_rules()
            if rule.rule == "/law" or rule.rule.startswith("/law/")
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
                    "dlms.routes.law", dlms.app.view_functions[endpoint].__module__
                )

    def test_namespaced_endpoints_build_original_public_urls_without_aliases(self):
        values = {
            "law.law_view_saved_import": {"filename": "nested/packet.txt"},
            "law.law_delete_saved_import": {"filename": "nested/packet.txt"},
            "law.law_create_case_from_import": {"filename": "nested/packet.txt"},
            "law.law_view_case_review": {"case_id": "case-1"},
            "law.law_update_case_review_details": {"case_id": "case-1"},
            "law.law_delete_case_review": {"case_id": "case-1"},
            "law.law_update_case_review_notes": {"case_id": "case-1"},
            "law.law_update_socratic_answers": {"case_id": "case-1"},
            "law.law_update_irac_response": {"case_id": "case-1"},
            "law.law_export_case_review_txt": {"case_id": "case-1"},
        }
        with dlms.app.test_request_context():
            for endpoint, (rule, _methods) in self.EXPECTED_RULES.items():
                expected = rule.replace(
                    "<path:filename>", values.get(endpoint, {}).get("filename", "")
                ).replace("<case_id>", values.get(endpoint, {}).get("case_id", ""))
                with self.subTest(endpoint=endpoint):
                    self.assertEqual(expected, url_for(endpoint, **values.get(endpoint, {})))

        law_rules = [
            rule
            for rule in dlms.app.url_map.iter_rules()
            if rule.rule == "/law" or rule.rule.startswith("/law/")
        ]
        self.assertEqual(len(self.EXPECTED_RULES), len(law_rules))

    def test_dependencies_are_explicit_frozen_and_module_does_not_import_app(self):
        self.assertEqual(
            self.EXPECTED_DEPENDENCIES,
            {field.name for field in dataclasses.fields(law_routes.LawRouteDependencies)},
        )
        self.assertTrue(law_routes.LawRouteDependencies.__dataclass_params__.frozen)
        self.assertEqual(
            ["dependencies"],
            list(inspect.signature(law_routes.create_law_blueprint).parameters),
        )

        tree = ast.parse(LAW_ROUTE_PATH.read_text(encoding="utf-8"))
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

    def test_migrated_handlers_are_not_app_owned_and_url_for_targets_are_namespaced(self):
        old_names = {endpoint.split(".", 1)[1] for endpoint in self.EXPECTED_RULES}
        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        app_functions = {
            node.name for node in app_tree.body if isinstance(node, ast.FunctionDef)
        }
        self.assertTrue(old_names.isdisjoint(app_functions))
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
        self.assertIn("law.law_view_saved_import", url_for_targets)
        self.assertIn("law.law_view_case_review", url_for_targets)

        template_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
        )
        template_targets = set(
            re.findall(r"url_for\(\s*['\"]([^'\"]+)", template_source)
        )
        self.assertTrue(old_names.isdisjoint(template_targets))
        self.assertIn('href="/anki/law"', template_source)
        self.assertIn('action="/law/create"', template_source)

    def test_factory_uses_injected_landing_boundary(self):
        services = {name: mock.Mock() for name in self.EXPECTED_DEPENDENCIES}
        services["get_portal_title"].return_value = "Injected Law Portal"
        services["load_law_registry"].return_value = {
            "cases": [{"id": "one"}],
            "folders": ["Torts", "Contracts"],
        }
        dependencies = law_routes.LawRouteDependencies(**services)
        application = Flask(__name__)
        application.register_blueprint(law_routes.create_law_blueprint(dependencies))

        with mock.patch.object(
            law_routes, "render_template", return_value="rendered"
        ) as renderer:
            response = application.test_client().get("/law")

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"rendered", response.data)
        renderer.assert_called_once_with(
            "law/index.html",
            portal_title="Injected Law Portal",
            law_registry={
                "cases": [{"id": "one"}],
                "folders": ["Torts", "Contracts"],
            },
            saved_cases=1,
            course_count=2,
        )

    def test_global_security_csrf_and_strict_slash_behavior_are_preserved(self):
        client = dlms.app.test_client()
        response = client.get("/law")
        self.assertEqual(200, response.status_code)
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])
        self.assertIn("dlms_csrf_token=", response.headers.get("Set-Cookie", ""))

        self.assertEqual(404, client.get("/law/").status_code)
        self.assertEqual(404, client.get("/law/create/").status_code)
        self.assertEqual(400, client.post("/law/workflow/cancel").status_code)


if __name__ == "__main__":
    unittest.main()
