"""Whole-application structural closure gate for DLMS-061."""

import ast
import dataclasses
import hashlib
import importlib
import inspect
import json
import pkgutil
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from flask import url_for
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import RequestEntityTooLarge

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
import dlms.routes as route_package


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
ROUTE_ROOT = ROOT / "dlms" / "routes"
TEMPLATE_ROOT = ROOT / "templates"


class BlueprintClosureTests(unittest.TestCase):
    EXPECTED_BLUEPRINT_RULE_COUNTS = {
        "admin_images": 5,
        "anki": 12,
        "content_packs": 8,
        "core": 7,
        "help": 7,
        "history": 13,
        "it": 3,
        "law": 16,
        "learning": 15,
        "maintenance": 20,
        "medical": 6,
        "pdf_import": 12,
        "quiz": 31,
        "settings": 13,
        "study_packs": 9,
    }
    EXPECTED_FACTORY_NAMES = {
        "create_admin_images_blueprint",
        "create_anki_blueprint",
        "create_content_packs_blueprint",
        "create_core_blueprint",
        "create_help_blueprint",
        "create_history_blueprint",
        "create_it_blueprint",
        "create_law_blueprint",
        "create_learning_blueprint",
        "create_maintenance_blueprint",
        "create_medical_blueprint",
        "create_pdf_import_blueprint",
        "create_quiz_blueprint",
        "create_settings_blueprint",
        "create_study_packs_blueprint",
    }
    EXPECTED_DEPENDENCY_TYPES = {
        "dlms.routes.admin_images.AdminImageRouteDependencies": 6,
        "dlms.routes.anki.AnkiRouteDependencies": 22,
        "dlms.routes.content_packs.ContentPackRouteDependencies": 19,
        "dlms.routes.core.CoreRouteDependencies": 14,
        "dlms.routes.history.HistoryRouteDependencies": 9,
        "dlms.routes.it.ITStudyDependencies": 5,
        "dlms.routes.law.LawRouteDependencies": 30,
        "dlms.routes.learning.LearningRouteDependencies": 17,
        "dlms.routes.maintenance.MaintenanceRouteDependencies": 26,
        "dlms.routes.medical.MedicalRouteDependencies": 9,
        "dlms.routes.pdf_import.PDFImportRouteDependencies": 28,
        "dlms.routes.quiz.dependencies.QuizAuthoringDependencies": 20,
        "dlms.routes.quiz.dependencies.QuizEditorDependencies": 18,
        "dlms.routes.quiz.dependencies.QuizLibraryDependencies": 18,
        "dlms.routes.settings.SettingsRouteDependencies": 9,
        "dlms.routes.study_packs.StudyPackRouteDependencies": 25,
    }
    EXPECTED_ROUTE_SIGNATURE_SHA256 = (
        "43622e2af75b32145b25e49b9a1e3e60deaf02d3db512ac115c1f036442f0f72"
    )
    EXPECTED_CANONICAL_ALIASES = {
        "admin_images.admin_hotspot_editor": ("/admin/hotspots", {}),
        "admin_images.admin_hotspot_save": ("/admin/hotspots/save", {}),
        "help.regex_help": ("/regex-help/", {}),
        "history.dashboard": ("/dashboard", {}),
        "history.review": ("/review", {}),
        "maintenance.settings_create_backup": (
            "/settings/backup/create",
            {},
        ),
        "maintenance.settings_stage_restore": (
            "/settings/backup/restore/stage",
            {},
        ),
        "maintenance.settings_cancel_restore": (
            "/settings/backup/restore/cancel/token",
            {"token": "token"},
        ),
        "maintenance.settings_confirm_restore": (
            "/settings/backup/restore/confirm/token",
            {"token": "token"},
        ),
    }

    @staticmethod
    def _explicit_rules():
        return [
            rule for rule in dlms.app.url_map.iter_rules() if rule.endpoint != "static"
        ]

    @staticmethod
    def _route_signature(rules):
        rows = [
            {
                "rule": rule.rule,
                "endpoint": rule.endpoint,
                "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
                "strict_slashes": rule.strict_slashes,
                "converters": {
                    name: type(converter).__name__
                    for name, converter in sorted(rule._converters.items())
                },
                "module": dlms.app.view_functions[rule.endpoint].__module__,
            }
            for rule in rules
        ]
        rows.sort(key=lambda row: (row["rule"], row["endpoint"], row["methods"]))
        return json.dumps(rows, sort_keys=True, separators=(",", ":"))

    def test_entire_explicit_url_map_matches_the_178_rule_closure_signature(self):
        rules = self._explicit_rules()
        self.assertEqual(178, len(rules))

        blueprint_rules = [rule for rule in rules if "." in rule.endpoint]
        app_rules = [rule for rule in rules if "." not in rule.endpoint]
        self.assertEqual(177, len(blueprint_rules))
        self.assertEqual([("/api/shutdown", "shutdown_app")], [
            (rule.rule, rule.endpoint) for rule in app_rules
        ])

        counts = Counter(rule.endpoint.split(".", 1)[0] for rule in blueprint_rules)
        self.assertEqual(self.EXPECTED_BLUEPRINT_RULE_COUNTS, dict(counts))
        self.assertTrue(all(rule.strict_slashes is True for rule in rules))

        signature = self._route_signature(rules)
        self.assertEqual(
            self.EXPECTED_ROUTE_SIGNATURE_SHA256,
            hashlib.sha256(signature.encode("utf-8")).hexdigest(),
            signature,
        )

        method_owners = defaultdict(list)
        for rule in rules:
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                method_owners[(rule.rule, method)].append(rule.endpoint)
        self.assertFalse(
            {
                route_method: endpoints
                for route_method, endpoints in method_owners.items()
                if len(endpoints) > 1
            }
        )

    def test_only_shutdown_is_app_owned_and_static_is_framework_owned(self):
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        decorated = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            app_routes = [
                decorator
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr == "route"
            ]
            if app_routes:
                decorated.append((node.name, app_routes))
        self.assertEqual(["shutdown_app"], [name for name, _routes in decorated])

        shutdown = next(
            rule for rule in self._explicit_rules() if rule.endpoint == "shutdown_app"
        )
        self.assertEqual("/api/shutdown", shutdown.rule)
        self.assertEqual({"POST"}, shutdown.methods - {"HEAD", "OPTIONS"})
        self.assertEqual("app", dlms.app.view_functions["shutdown_app"].__module__)

        static_rules = [
            rule for rule in dlms.app.url_map.iter_rules() if rule.endpoint == "static"
        ]
        self.assertEqual(1, len(static_rules))
        self.assertEqual("/static/<path:filename>", static_rules[0].rule)
        self.assertEqual("flask.app", dlms.app.view_functions["static"].__module__)

    def test_all_fifteen_blueprints_are_registered_exactly_once(self):
        self.assertEqual(
            set(self.EXPECTED_BLUEPRINT_RULE_COUNTS), set(dlms.app.blueprints)
        )
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        registrations = [
            node.args[0].func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "app"
            and node.func.attr == "register_blueprint"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
        ]
        self.assertEqual(self.EXPECTED_FACTORY_NAMES, set(registrations))
        self.assertEqual(
            {name: 1 for name in self.EXPECTED_FACTORY_NAMES},
            {name: registrations.count(name) for name in self.EXPECTED_FACTORY_NAMES},
        )

    def test_route_modules_have_frozen_family_dependencies_and_no_app_import(self):
        route_paths = sorted(ROUTE_ROOT.rglob("*.py"))
        self.assertEqual(20, len(route_paths))
        for path in route_paths:
            with self.subTest(route_module=path.relative_to(ROOT)):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imported = {
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
                self.assertNotIn("app", imported)
                self.assertNotIn("app", imported_from)

        modules = [
            importlib.import_module(info.name)
            for info in pkgutil.walk_packages(
                route_package.__path__, route_package.__name__ + "."
            )
        ]
        dependency_types = {
            f"{value.__module__}.{name}": value
            for module in modules
            for name, value in vars(module).items()
            if inspect.isclass(value)
            and name.endswith("Dependencies")
            and dataclasses.is_dataclass(value)
            and value.__module__ == module.__name__
        }
        self.assertEqual(
            self.EXPECTED_DEPENDENCY_TYPES,
            {
                name: len(dataclasses.fields(dependency_type))
                for name, dependency_type in dependency_types.items()
            },
        )
        self.assertTrue(
            all(
                dependency_type.__dataclass_params__.frozen
                for dependency_type in dependency_types.values()
            )
        )
        self.assertFalse(
            {"AppDependencies", "ApplicationDependencies", "RouteDependencies"}
            & {dependency_type.__name__ for dependency_type in dependency_types.values()}
        )

    def test_active_url_for_targets_are_namespaced_and_aliases_stay_canonical(self):
        endpoint_names = {rule.endpoint for rule in dlms.app.url_map.iter_rules()}
        source_paths = [APP_PATH, *sorted((ROOT / "dlms").rglob("*.py"))]
        python_targets = set()
        for path in source_paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            python_targets.update(
                node.args[0].value
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "url_for"
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == "url_for"
                )
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            )

        template_targets = {
            target
            for path in TEMPLATE_ROOT.rglob("*.html")
            for target in re.findall(
                r"url_for\(\s*['\"]([^'\"]+)",
                path.read_text(encoding="utf-8"),
            )
        }
        targets = python_targets | template_targets
        self.assertTrue(targets.issubset(endpoint_names))
        self.assertTrue(all(target == "static" or "." in target for target in targets))

        groups = defaultdict(list)
        for rule in self._explicit_rules():
            groups[rule.endpoint].append(rule)
        aliases = {endpoint for endpoint, rules in groups.items() if len(rules) > 1}
        self.assertEqual(set(self.EXPECTED_CANONICAL_ALIASES), aliases)

        with dlms.app.test_request_context():
            for endpoint, (expected_url, values) in self.EXPECTED_CANONICAL_ALIASES.items():
                with self.subTest(endpoint=endpoint):
                    self.assertEqual(expected_url, url_for(endpoint, **values))

    def test_global_flask_policy_is_registered_at_application_scope(self):
        self.assertEqual(
            [
                "validate_unsafe_request_origin",
                "reject_declared_oversized_workflow_upload",
                "csrf_protect",
            ],
            [
                function.__name__
                for function in dlms.app.before_request_funcs.get(None, [])
            ],
        )
        self.assertEqual(
            ["deliver_csrf_token"],
            [
                function.__name__
                for function in dlms.app.after_request_funcs.get(None, [])
            ],
        )
        context_processors = dlms.app.template_context_processors.get(None, [])
        self.assertEqual(3, len(context_processors))
        self.assertIn(
            "inject_content_pack_state",
            {function.__name__ for function in context_processors},
        )
        self.assertIs(
            dlms.handle_csrf_error,
            dlms.app.error_handler_spec[None][400][CSRFError],
        )
        self.assertIs(
            dlms.dlms_request_too_large,
            dlms.app.error_handler_spec[None][413][RequestEntityTooLarge],
        )

        representative_routes = {
            "admin_images": "/admin/image-editor",
            "anki": "/anki",
            "content_packs": "/content-packs",
            "core": "/",
            "help": "/help/",
            "history": "/history",
            "it": "/it",
            "law": "/law",
            "learning": "/learning-intelligence",
            "maintenance": "/admin/maintenance",
            "medical": "/medical",
            "pdf_import": "/pdf-import",
            "quiz": "/library",
            "settings": "/settings",
            "study_packs": "/study-packs",
        }
        for blueprint, path in representative_routes.items():
            with self.subTest(blueprint=blueprint):
                response = dlms.app.test_client().get(path)
                self.assertEqual(200, response.status_code)
                self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
                self.assertEqual("DENY", response.headers["X-Frame-Options"])
                self.assertIn(
                    "dlms_csrf_token=", response.headers.get("Set-Cookie", "")
                )


if __name__ == "__main__":
    unittest.main()
