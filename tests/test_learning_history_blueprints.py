"""Structural and integration coverage for DLMS-061 Blueprint Batch 6."""

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
from dlms.routes import history as history_routes
from dlms.routes import learning as learning_routes


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
LEARNING_ROUTE_PATH = ROOT / "dlms" / "routes" / "learning.py"
HISTORY_ROUTE_PATH = ROOT / "dlms" / "routes" / "history.py"


class LearningHistoryBlueprintTests(unittest.TestCase):
    EXPECTED_RULES = {
        ("learning.record_attempt", "/record_attempt", frozenset({"POST"})),
        (
            "learning.record_study_learning_event",
            "/api/learning-events/study-response",
            frozenset({"POST"}),
        ),
        (
            "learning.learning_foundation_summary",
            "/api/learning-foundation/summary",
            frozenset({"GET"}),
        ),
        (
            "learning.daily_review_plan_api",
            "/api/daily-review-plan",
            frozenset({"GET"}),
        ),
        (
            "learning.smart_review_preview_api",
            "/api/smart-review/preview",
            frozenset({"GET"}),
        ),
        (
            "learning.smart_review_generate",
            "/smart-review/generate",
            frozenset({"POST"}),
        ),
        (
            "learning.adaptive_study_generate",
            "/adaptive-study/generate",
            frozenset({"POST"}),
        ),
        (
            "learning.concept_review_generate",
            "/concept-review/generate",
            frozenset({"POST"}),
        ),
        (
            "learning.review_schedule_page",
            "/review-schedule",
            frozenset({"GET"}),
        ),
        (
            "learning.review_schedule_api",
            "/api/review-schedule",
            frozenset({"GET"}),
        ),
        (
            "learning.spaced_review_preview_api",
            "/api/spaced-review/preview",
            frozenset({"GET"}),
        ),
        (
            "learning.spaced_review_generate",
            "/spaced-review/generate",
            frozenset({"POST"}),
        ),
        (
            "learning.native_spaced_review_generate",
            "/native-spaced-review/generate",
            frozenset({"POST"}),
        ),
        (
            "learning.learning_diagnostics_page",
            "/learning-diagnostics",
            frozenset({"GET"}),
        ),
        (
            "learning.learning_diagnostics_api",
            "/api/learning-diagnostics",
            frozenset({"GET"}),
        ),
        (
            "learning.learning_profile_page",
            "/learning-profile",
            frozenset({"GET"}),
        ),
        (
            "learning.learning_profile_api",
            "/api/learning-profile",
            frozenset({"GET"}),
        ),
        (
            "learning.learning_intelligence_page",
            "/learning-intelligence",
            frozenset({"GET"}),
        ),
        (
            "learning.learning_intelligence_topics_api",
            "/api/learning-intelligence/topics",
            frozenset({"GET"}),
        ),
        ("history.history", "/history", frozenset({"GET"})),
        (
            "history.history_html_redirect",
            "/history.html",
            frozenset({"GET"}),
        ),
        ("history.review", "/review", frozenset({"GET"})),
        ("history.review", "/review.html", frozenset({"GET"})),
        ("history.dashboard", "/dashboard", frozenset({"GET"})),
        ("history.dashboard", "/dashboard.html", frozenset({"GET"})),
        ("history.api_attempts", "/api/attempts", frozenset({"GET"})),
        (
            "history.api_attempts_overview",
            "/api/attempts/overview",
            frozenset({"GET"}),
        ),
        (
            "history.api_attempts_analytics",
            "/api/attempts/analytics",
            frozenset({"GET"}),
        ),
        (
            "history.api_attempt_summary",
            "/api/attempts/<attempt_reference>",
            frozenset({"GET"}),
        ),
        (
            "history.api_missed_questions",
            "/api/missed_questions",
            frozenset({"GET"}),
        ),
        (
            "history.clear_db_history",
            "/api/clear_db_history",
            frozenset({"POST"}),
        ),
        ("history.history_db", "/history_db", frozenset({"GET"})),
    }
    LEARNING_DEPENDENCIES = {
        "static_folder",
        "static_root",
        "get_db",
        "learning_payload_error",
        "persist_attempt",
        "persist_study_learning_event",
        "learning_foundation_summary",
        "smart_review_candidates",
        "smart_review_select_candidates",
        "review_candidates_for_topics",
        "review_select_candidates",
        "adaptive_study_candidates",
        "adaptive_study_select_candidates",
        "daily_review_plan",
        "question_payload_from_db",
        "publish_quiz",
        "review_schedule_payload",
        "question_diagnostics_payload",
        "learning_profile_payload",
        "learning_intelligence_payload",
    }
    HISTORY_DEPENDENCIES = {
        "static_folder",
        "get_db",
        "parse_attempt_pagination",
        "attempt_page",
        "attempt_overview",
        "attempt_analytics",
        "attempt_summary",
        "missed_questions",
        "clear_persistent_history",
    }

    def test_blueprints_are_registered_once_and_own_exact_reconciled_rules(self):
        self.assertEqual(1, list(dlms.app.blueprints).count("learning"))
        self.assertEqual(1, list(dlms.app.blueprints).count("history"))

        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        factories = {"create_learning_blueprint", "create_history_blueprint"}
        registrations = [
            node.args[0].func.id
            for node in ast.walk(app_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "app"
            and node.func.attr == "register_blueprint"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id in factories
        ]
        self.assertEqual(
            {"create_learning_blueprint": 1, "create_history_blueprint": 1},
            {factory: registrations.count(factory) for factory in factories},
        )

        expected_paths = {path for _endpoint, path, _methods in self.EXPECTED_RULES}
        rules = [
            rule for rule in dlms.app.url_map.iter_rules() if rule.rule in expected_paths
        ]
        actual = {
            (
                rule.endpoint,
                rule.rule,
                frozenset(rule.methods - {"HEAD", "OPTIONS"}),
            )
            for rule in rules
        }
        self.assertEqual(self.EXPECTED_RULES, actual)
        self.assertEqual(32, len(rules))
        for rule in rules:
            with self.subTest(endpoint=rule.endpoint, rule=rule.rule):
                self.assertTrue(rule.strict_slashes)
                expected_module = f"dlms.routes.{rule.endpoint.split('.', 1)[0]}"
                self.assertEqual(
                    expected_module, dlms.app.view_functions[rule.endpoint].__module__
                )

    def test_namespaced_endpoints_build_original_public_urls_and_aliases_remain(self):
        canonical = {
            endpoint: path
            for endpoint, path, _methods in self.EXPECTED_RULES
            if path not in {"/review.html", "/dashboard.html"}
        }
        values = {
            "history.api_attempt_summary": {"attempt_reference": "attempt-1"}
        }
        with dlms.app.test_request_context():
            for endpoint, expected in canonical.items():
                with self.subTest(endpoint=endpoint):
                    self.assertEqual(
                        expected.replace("<attempt_reference>", "attempt-1"),
                        url_for(endpoint, **values.get(endpoint, {})),
                    )

        rules = {(rule.endpoint, rule.rule) for rule in dlms.app.url_map.iter_rules()}
        self.assertIn(("history.review", "/review.html"), rules)
        self.assertIn(("history.dashboard", "/dashboard.html"), rules)

    def test_dependencies_are_explicit_frozen_and_modules_do_not_import_app(self):
        cases = (
            (
                learning_routes.LearningRouteDependencies,
                self.LEARNING_DEPENDENCIES,
                learning_routes.create_learning_blueprint,
                LEARNING_ROUTE_PATH,
            ),
            (
                history_routes.HistoryRouteDependencies,
                self.HISTORY_DEPENDENCIES,
                history_routes.create_history_blueprint,
                HISTORY_ROUTE_PATH,
            ),
        )
        for dependency_type, expected, factory, path in cases:
            with self.subTest(module=path.name):
                self.assertEqual(
                    expected,
                    {field.name for field in dataclasses.fields(dependency_type)},
                )
                self.assertTrue(dependency_type.__dataclass_params__.frozen)
                self.assertEqual(
                    ["dependencies"], list(inspect.signature(factory).parameters)
                )
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imported_modules = {
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Import)
                    for alias in node.names
                }
                imported_from = {
                    node.module
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                }
                self.assertNotIn("app", imported_modules)
                self.assertNotIn("app", imported_from)

    def test_migrated_handlers_are_not_app_owned_and_url_for_targets_are_namespaced(self):
        old_names = {
            endpoint.split(".", 1)[1]
            for endpoint, _path, _methods in self.EXPECTED_RULES
        }
        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        app_functions = {
            node.name for node in app_tree.body if isinstance(node, ast.FunctionDef)
        }
        self.assertTrue(old_names.isdisjoint(app_functions))
        self.assertTrue(old_names.isdisjoint(dlms.app.view_functions))

        sources = [APP_PATH, LEARNING_ROUTE_PATH, HISTORY_ROUTE_PATH]
        sources.extend((ROOT / "dlms" / "routes").glob("*.py"))
        url_for_targets = set()
        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            url_for_targets.update(
                node.args[0].value
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "url_for"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            )
        self.assertTrue(old_names.isdisjoint(url_for_targets))

        template_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
        )
        template_targets = set(
            re.findall(r"url_for\(\s*['\"]([^'\"]+)", template_source)
        )
        self.assertTrue(old_names.isdisjoint(template_targets))

    def test_learning_factory_uses_injected_mutation_boundary(self):
        services = {name: mock.Mock() for name in self.LEARNING_DEPENDENCIES}

        class PayloadError(ValueError):
            pass

        connection = mock.Mock()
        cursor = connection.cursor.return_value
        services["get_db"].return_value = connection
        services["learning_payload_error"].return_value = PayloadError
        services["persist_attempt"].return_value = {
            "status": "ok",
            "attemptId": "injected-attempt",
        }
        dependencies = learning_routes.LearningRouteDependencies(**services)
        application = Flask(__name__)
        application.register_blueprint(
            learning_routes.create_learning_blueprint(dependencies)
        )

        response = application.test_client().post(
            "/record_attempt", json={"attemptId": "injected-attempt"}
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("injected-attempt", response.get_json()["attemptId"])
        services["persist_attempt"].assert_called_once_with(
            connection, cursor, {"attemptId": "injected-attempt"}
        )
        connection.close.assert_called_once_with()

    def test_history_factory_uses_injected_query_boundary(self):
        services = {name: mock.Mock() for name in self.HISTORY_DEPENDENCIES}
        connection = mock.Mock()
        cursor = connection.cursor.return_value
        services["get_db"].return_value = connection
        services["parse_attempt_pagination"].return_value = (2, 25, "quiz")
        services["attempt_page"].return_value = {"attempts": [], "page": 2}
        dependencies = history_routes.HistoryRouteDependencies(**services)
        application = Flask(__name__)
        application.register_blueprint(
            history_routes.create_history_blueprint(dependencies)
        )

        response = application.test_client().get("/api/attempts?page=2")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"attempts": [], "page": 2}, response.get_json())
        services["attempt_page"].assert_called_once_with(cursor, 2, 25, "quiz")
        connection.close.assert_called_once_with()

    def test_global_security_csrf_redirect_and_strict_slash_behavior_are_preserved(self):
        client = dlms.app.test_client()
        response = client.get("/history")
        self.assertEqual(200, response.status_code)
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])
        self.assertIn("dlms_csrf_token=", response.headers.get("Set-Cookie", ""))
        response.close()

        alias = client.get("/history.html?attempt=attempt-1")
        self.assertEqual(301, alias.status_code)
        self.assertEqual("/history?attempt=attempt-1", alias.location)
        self.assertEqual(404, client.get("/history/").status_code)
        self.assertEqual(404, client.get("/api/attempts/").status_code)
        self.assertEqual(400, client.post("/record_attempt", json={}).status_code)
        self.assertEqual(400, client.post("/api/clear_db_history").status_code)


if __name__ == "__main__":
    unittest.main()
