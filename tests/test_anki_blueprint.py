"""Structural and integration coverage for DLMS-061 Blueprint Batch 7."""

import ast
import dataclasses
import inspect
import re
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask, Response, url_for

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import anki as anki_routes
from tests.csrf_test_utils import csrf_token


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
ANKI_ROUTE_PATH = ROOT / "dlms" / "routes" / "anki.py"


class AnkiBlueprintTests(unittest.TestCase):
    EXPECTED_RULES = {
        "anki.anki_tools": ("/anki", {"GET"}),
        "anki.anki_custom_deck": ("/anki/custom", {"GET", "POST"}),
        "anki.anki_export_custom": ("/anki/export/custom", {"POST"}),
        "anki.anki_export_law": ("/anki/export/law", {"POST"}),
        "anki.anki_export_missed": ("/anki/export/missed", {"POST"}),
        "anki.anki_export_quiz": ("/anki/export/quiz", {"POST"}),
        "anki.anki_law_tools": ("/anki/law", {"GET"}),
        "anki.anki_printable_flashcards": ("/anki/printable", {"POST"}),
        "anki.export_anki_genanki": ("/export/anki", {"POST"}),
        "anki.export_anki_missed_tsv": ("/export/anki/missed", {"POST"}),
        "anki.export_anki_quiz_tsv": (
            "/export/anki/quiz/<int:quiz_id>",
            {"GET"},
        ),
        "anki.export_anki_study": ("/export/anki/study", {"POST"}),
    }
    EXPECTED_DEPENDENCIES = {
        "app_version",
        "get_anki_quiz_choices",
        "get_anki_law_case_choices",
        "get_anki_law_courses",
        "get_anki_missed_summary",
        "get_anki_custom_sources",
        "build_anki_rows_for_quiz",
        "build_anki_rows_for_missed",
        "build_custom_anki_rows",
        "load_law_flashcards_for_selection",
        "load_law_flashcards_for_case",
        "export_quiz_to_apkg",
        "send_temp_anki_package",
        "make_safe_anki_download_name",
        "make_safe_anki_deck_name",
        "export_anki_tsv_for_quiz",
        "load_study_export_selection",
        "load_attempt_missed_rows",
        "load_missed_tsv_rows",
        "attempt_history_context",
        "format_anki_missed_tsv",
        "log_info",
    }

    def test_blueprint_is_registered_once_and_owns_exact_reconciled_rules(self):
        self.assertEqual(1, list(dlms.app.blueprints).count("anki"))

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
            and node.args[0].func.id == "create_anki_blueprint"
        ]
        self.assertEqual(1, len(registrations))

        expected_paths = {path for path, _methods in self.EXPECTED_RULES.values()}
        rules = {
            rule.endpoint: rule
            for rule in dlms.app.url_map.iter_rules()
            if rule.rule in expected_paths
        }
        self.assertEqual(set(self.EXPECTED_RULES), set(rules))
        self.assertEqual(12, len(rules))
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
                    "dlms.routes.anki", dlms.app.view_functions[endpoint].__module__
                )

    def test_namespaced_endpoints_build_original_public_urls_without_aliases(self):
        values = {"anki.export_anki_quiz_tsv": {"quiz_id": 7}}
        with dlms.app.test_request_context():
            for endpoint, (rule, _methods) in self.EXPECTED_RULES.items():
                with self.subTest(endpoint=endpoint):
                    expected = rule.replace("<int:quiz_id>", "7")
                    self.assertEqual(
                        expected,
                        url_for(endpoint, **values.get(endpoint, {})),
                    )

        anki_rules = [
            rule
            for rule in dlms.app.url_map.iter_rules()
            if rule.rule == "/anki"
            or rule.rule.startswith("/anki/")
            or rule.rule == "/export/anki"
            or rule.rule.startswith("/export/anki/")
        ]
        self.assertEqual(len(self.EXPECTED_RULES), len(anki_rules))

    def test_dependencies_are_explicit_frozen_and_module_does_not_import_app(self):
        self.assertEqual(
            self.EXPECTED_DEPENDENCIES,
            {
                field.name
                for field in dataclasses.fields(anki_routes.AnkiRouteDependencies)
            },
        )
        self.assertTrue(anki_routes.AnkiRouteDependencies.__dataclass_params__.frozen)
        self.assertEqual(
            ["dependencies"],
            list(inspect.signature(anki_routes.create_anki_blueprint).parameters),
        )

        tree = ast.parse(ANKI_ROUTE_PATH.read_text(encoding="utf-8"))
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

    def test_migrated_handlers_are_not_app_owned_and_url_for_inventory_is_clean(self):
        old_names = {endpoint.split(".", 1)[1] for endpoint in self.EXPECTED_RULES}
        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        app_functions = {
            node.name for node in app_tree.body if isinstance(node, ast.FunctionDef)
        }
        self.assertTrue(old_names.isdisjoint(app_functions))
        self.assertTrue(old_names.isdisjoint(dlms.app.view_functions))

        source_paths = [APP_PATH]
        source_paths.extend((ROOT / "dlms" / "routes").glob("*.py"))
        url_for_targets = {
            node.args[0].value
            for path in source_paths
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "url_for"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        self.assertTrue(old_names.isdisjoint(url_for_targets))
        self.assertFalse(
            {target for target in url_for_targets if target.startswith("anki.")}
        )

        template_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
        )
        template_targets = set(
            re.findall(r"url_for\(\s*['\"]([^'\"]+)", template_source)
        )
        self.assertTrue(old_names.isdisjoint(template_targets))
        for literal_url in (
            'href="/anki"',
            'href="/anki/custom"',
            'href="/anki/law"',
            'action="/anki/export/quiz"',
            'exportForm.action = "/anki/export/law"',
            'formaction="/anki/export/custom"',
            'formaction="/anki/printable"',
        ):
            self.assertIn(literal_url, template_source)

    def test_factory_uses_injected_export_and_response_lifecycle_boundaries(self):
        services = {name: mock.Mock() for name in self.EXPECTED_DEPENDENCIES}
        services["build_custom_anki_rows"].return_value = [
            {"front": "Question", "back": "Answer"}
        ]
        services["export_quiz_to_apkg"].return_value = "/tmp/injected.apkg"
        services["make_safe_anki_download_name"].return_value = "injected.apkg"
        services["send_temp_anki_package"].return_value = Response(
            b"package", mimetype="application/octet-stream"
        )
        dependencies = anki_routes.AnkiRouteDependencies(**services)
        application = Flask(__name__)
        application.register_blueprint(
            anki_routes.create_anki_blueprint(dependencies)
        )

        response = application.test_client().post(
            "/anki/export/custom",
            data={"deck_name": "Injected", "quiz_cards": "quiz:1:1"},
        )

        self.assertEqual(200, response.status_code)
        services["build_custom_anki_rows"].assert_called_once_with(
            ["quiz:1:1"], [], []
        )
        services["export_quiz_to_apkg"].assert_called_once_with(
            "Injected", [{"front": "Question", "back": "Answer"}]
        )
        services["send_temp_anki_package"].assert_called_once_with(
            "/tmp/injected.apkg", "injected.apkg"
        )

    def test_study_export_preserves_fallback_for_quiz_with_empty_title(self):
        client = dlms.app.test_client()
        with mock.patch.object(
            dlms,
            "_load_anki_study_export_selection",
            return_value=(True, None, [{"front": "Question", "back": "Answer"}]),
        ), mock.patch.object(
            dlms, "export_quiz_to_apkg", return_value="/tmp/study.apkg"
        ) as exporter, mock.patch.object(
            dlms,
            "_send_temp_anki_package",
            return_value=Response(b"package"),
        ):
            response = client.post(
                "/export/anki/study",
                json={"quiz_id": 1, "question_numbers": [1]},
                headers={"X-CSRFToken": csrf_token(client)},
            )

        self.assertEqual(200, response.status_code)
        exporter.assert_called_once_with(
            "DLMS Study Questions - Study Review",
            [{"front": "Question", "back": "Answer"}],
        )

    def test_global_security_csrf_and_strict_slash_behavior_are_preserved(self):
        client = dlms.app.test_client()
        response = client.get("/anki")
        self.assertEqual(200, response.status_code)
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])
        self.assertIn("dlms_csrf_token=", response.headers.get("Set-Cookie", ""))

        self.assertEqual(404, client.get("/anki/").status_code)
        self.assertEqual(404, client.get("/anki/custom/").status_code)
        self.assertEqual(400, client.post("/anki/export/custom").status_code)


if __name__ == "__main__":
    unittest.main()
