"""Structural and integration coverage for the core and Help Blueprints."""

import ast
import dataclasses
import inspect
import unittest
from pathlib import Path

from flask import url_for

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import core as core_routes
from dlms.routes import help as help_routes


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
CORE_ROUTE_PATH = ROOT / "dlms" / "routes" / "core.py"
HELP_ROUTE_PATH = ROOT / "dlms" / "routes" / "help.py"


class CoreHelpBlueprintTests(unittest.TestCase):
    EXPECTED_RULES = {
        "/": "core.home",
        "/config/portal.json": "core.serve_portal_config",
        "/content-packs/<pack_id>/assets/<path:asset_path>": "core.content_pack_asset",
        "/dynamic.css": "core.dynamic_css",
        "/quiz-assets/<asset_bucket>/<path:asset_path>": "core.quiz_asset",
        "/user-bg/<path:filename>": "core.serve_user_background",
        "/user-static/<path:filename>": "core.user_static",
        "/help/": "help.help_index",
        "/help/<topic>": "help.help_topic",
        "/help/about": "help.help_about",
        "/help/advanced-features": "help.help_advanced",
        "/help/quiz-help": "help.help_quiz",
        "/regex-help": "help.regex_help",
        "/regex-help/": "help.regex_help",
    }
    CORE_DEPENDENCIES = {
        "app_version",
        "get_portal_title",
        "content_pack_summary",
        "load_portal_config",
        "debug_print",
        "app_data_dir",
        "static_folder",
        "default_theme",
        "get_content_pack",
        "safe_pack_child",
        "decode_raster_image",
        "passive_pack_image_extensions",
        "raster_image_formats",
        "quiz_asset_folder",
    }
    OLD_ENDPOINTS = {
        "home",
        "serve_portal_config",
        "dynamic_css",
        "content_pack_asset",
        "quiz_asset",
        "serve_user_background",
        "user_static",
        "help_index",
        "help_topic",
        "help_about",
        "help_advanced",
        "help_quiz",
        "regex_help",
    }

    def setUp(self):
        self.client = dlms.app.test_client()

    def test_blueprints_are_each_registered_exactly_once(self):
        self.assertEqual(1, list(dlms.app.blueprints).count("core"))
        self.assertEqual(1, list(dlms.app.blueprints).count("help"))

        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
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
            and node.args[0].func.id in {
                "create_core_blueprint",
                "create_help_blueprint",
            }
        ]
        self.assertEqual(
            ["create_core_blueprint", "create_help_blueprint"],
            sorted(registrations),
        )

    def test_url_map_methods_and_strict_slash_contract_are_preserved(self):
        rules = {
            rule.rule: rule
            for rule in dlms.app.url_map.iter_rules()
            if rule.endpoint.startswith(("core.", "help."))
        }
        self.assertEqual(set(self.EXPECTED_RULES), set(rules))
        for path, endpoint in self.EXPECTED_RULES.items():
            with self.subTest(path=path):
                rule = rules[path]
                self.assertEqual(endpoint, rule.endpoint)
                self.assertEqual({"GET", "HEAD", "OPTIONS"}, rule.methods)
                self.assertTrue(rule.strict_slashes)

        for old_endpoint in self.OLD_ENDPOINTS:
            self.assertNotIn(old_endpoint, dlms.app.view_functions)

    def test_namespaced_endpoints_build_original_public_urls(self):
        with dlms.app.test_request_context():
            expected = {
                "core.home": ("/", {}),
                "core.serve_portal_config": ("/config/portal.json", {}),
                "core.dynamic_css": ("/dynamic.css", {}),
                "core.content_pack_asset": (
                    "/content-packs/pack/assets/images/example.png",
                    {"pack_id": "pack", "asset_path": "images/example.png"},
                ),
                "core.quiz_asset": (
                    "/quiz-assets/bucket/images/example.png",
                    {"asset_bucket": "bucket", "asset_path": "images/example.png"},
                ),
                "core.serve_user_background": (
                    "/user-bg/example.png",
                    {"filename": "example.png"},
                ),
                "core.user_static": (
                    "/user-static/logos/example.png",
                    {"filename": "logos/example.png"},
                ),
                "help.help_index": ("/help/", {}),
                "help.help_about": ("/help/about", {}),
                "help.help_quiz": ("/help/quiz-help", {}),
                "help.help_advanced": ("/help/advanced-features", {}),
                "help.help_topic": ("/help/settings", {"topic": "settings"}),
                "help.regex_help": ("/regex-help/", {}),
            }
            for endpoint, (path, values) in expected.items():
                with self.subTest(endpoint=endpoint):
                    self.assertEqual(path, url_for(endpoint, **values))

    def test_route_modules_do_not_import_app_and_dependencies_are_explicit(self):
        fields = {
            field.name for field in dataclasses.fields(core_routes.CoreRouteDependencies)
        }
        self.assertEqual(self.CORE_DEPENDENCIES, fields)
        self.assertEqual(
            ["dependencies"],
            list(inspect.signature(core_routes.create_core_blueprint).parameters),
        )
        self.assertEqual(
            [], list(inspect.signature(help_routes.create_help_blueprint).parameters)
        )

        for path in (CORE_ROUTE_PATH, HELP_ROUTE_PATH):
            with self.subTest(route_module=path.name):
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

    def test_migrated_handlers_are_not_app_owned_and_internal_links_are_namespaced(self):
        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        app_route_functions = {
            node.name
            for node in app_tree.body
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"route", "get"}
                for decorator in node.decorator_list
            )
        }
        self.assertTrue(self.OLD_ENDPOINTS.isdisjoint(app_route_functions))

        route_trees = [app_tree] + [
            ast.parse(path.read_text(encoding="utf-8"))
            for path in (ROOT / "dlms" / "routes").rglob("*.py")
        ]
        endpoint_strings = [
            node.value
            for tree in route_trees
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        self.assertNotIn("content_pack_asset", endpoint_strings)
        self.assertEqual(4, endpoint_strings.count("core.content_pack_asset"))

    def test_global_response_policy_and_public_failure_contracts_are_preserved(self):
        expected = {
            "/": 200,
            "/config/portal.json": 200,
            "/dynamic.css": 200,
            "/help": 308,
            "/help/": 200,
            "/help/not-a-topic": 404,
            "/regex-help": 200,
            "/regex-help/": 200,
            "/content-packs/missing/assets/image.png": 404,
            "/quiz-assets/invalid!/image.png": 400,
            "/quiz-assets/bucket/missing.png": 404,
            "/user-static/page.html": 415,
            "/user-static/logos/missing.png": 404,
            "/user-bg/missing.png": 404,
        }
        for path, status in expected.items():
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(status, response.status_code)
                self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
                self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
                self.assertEqual("DENY", response.headers["X-Frame-Options"])

        self.assertTrue(
            self.client.get("/help", follow_redirects=False).headers["Location"].endswith(
                "/help/"
            )
        )
        dynamic = self.client.get("/dynamic.css")
        self.assertEqual("text/css", dynamic.mimetype)
        self.assertEqual("no-store", dynamic.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
