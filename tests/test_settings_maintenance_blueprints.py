"""Structural and integration coverage for DLMS-061 Blueprint Batch 8."""

import ast
import dataclasses
import inspect
import re
import threading
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask, url_for

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import maintenance as maintenance_routes
from dlms.routes import settings as settings_routes


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
SETTINGS_PATH = ROOT / "dlms" / "routes" / "settings.py"
MAINTENANCE_PATH = ROOT / "dlms" / "routes" / "maintenance.py"


class SettingsMaintenanceBlueprintTests(unittest.TestCase):
    EXPECTED_RULES = {
        ("settings.settings_page", "/settings", frozenset({"GET"})),
        (
            "settings.settings_lifecycle_page",
            "/settings/lifecycle",
            frozenset({"GET"}),
        ),
        (
            "settings.save_lifecycle_settings",
            "/settings/lifecycle/save",
            frozenset({"POST"}),
        ),
        (
            "settings.settings_navigation_page",
            "/settings/navigation",
            frozenset({"GET"}),
        ),
        (
            "settings.save_navigation_settings",
            "/settings/navigation/save",
            frozenset({"POST"}),
        ),
        (
            "settings.settings_appearance_page",
            "/settings/appearance",
            frozenset({"GET"}),
        ),
        (
            "settings.save_appearance_settings",
            "/settings/appearance/save",
            frozenset({"POST"}),
        ),
        ("settings.api_set_theme", "/api/theme", frozenset({"POST"})),
        ("settings.settings_ai_page", "/settings/ai", frozenset({"GET"})),
        (
            "settings.save_ai_settings",
            "/settings/ai/save",
            frozenset({"POST"}),
        ),
        (
            "settings.settings_parsing_page",
            "/settings/parsing",
            frozenset({"GET"}),
        ),
        (
            "settings.save_parsing_settings",
            "/settings/parsing/save",
            frozenset({"POST"}),
        ),
        (
            "settings.settings_legacy_page",
            "/settings/legacy",
            frozenset({"GET"}),
        ),
        ("settings.save_settings", "/save_settings", frozenset({"POST"})),
        (
            "settings.api_portal_config",
            "/api/portal_config",
            frozenset({"GET"}),
        ),
        (
            "maintenance.admin_maintenance",
            "/admin/maintenance",
            frozenset({"GET"}),
        ),
        (
            "maintenance.reset_quiz_library",
            "/api/reset_quiz_library",
            frozenset({"POST"}),
        ),
        (
            "maintenance.reset_learning_intelligence",
            "/api/reset_learning_intelligence",
            frozenset({"POST"}),
        ),
        (
            "maintenance.reset_source_content",
            "/api/reset_source_content",
            frozenset({"POST"}),
        ),
        (
            "maintenance.reset_app_settings",
            "/api/reset_app_settings",
            frozenset({"POST"}),
        ),
        (
            "maintenance.reset_all_data",
            "/api/reset_all_data",
            frozenset({"POST"}),
        ),
        (
            "maintenance.remove_all_dlms_data",
            "/api/remove_all_dlms_data",
            frozenset({"POST"}),
        ),
        (
            "maintenance.wipe_database",
            "/api/wipe_database",
            frozenset({"POST"}),
        ),
        (
            "maintenance.settings_create_backup",
            "/settings/backup/create",
            frozenset({"POST"}),
        ),
        (
            "maintenance.settings_create_backup",
            "/settings/data/backup/create",
            frozenset({"POST"}),
        ),
        (
            "maintenance.settings_stage_restore",
            "/settings/backup/restore/stage",
            frozenset({"POST"}),
        ),
        (
            "maintenance.settings_stage_restore",
            "/settings/data/restore/stage",
            frozenset({"POST"}),
        ),
        (
            "maintenance.settings_cancel_restore",
            "/settings/backup/restore/cancel/<token>",
            frozenset({"POST"}),
        ),
        (
            "maintenance.settings_cancel_restore",
            "/settings/data/restore/cancel/<token>",
            frozenset({"POST"}),
        ),
        (
            "maintenance.settings_confirm_restore",
            "/settings/backup/restore/confirm/<token>",
            frozenset({"POST"}),
        ),
        (
            "maintenance.settings_confirm_restore",
            "/settings/data/restore/confirm/<token>",
            frozenset({"POST"}),
        ),
        (
            "maintenance.settings_data_legacy_redirect",
            "/settings/data",
            frozenset({"GET"}),
        ),
        (
            "maintenance.settings_backup_page",
            "/settings/backup",
            frozenset({"GET"}),
        ),
        (
            "maintenance.settings_reset_legacy_redirect",
            "/settings/reset",
            frozenset({"GET"}),
        ),
        (
            "maintenance.settings_reset_remove_page",
            "/settings/reset-remove",
            frozenset({"GET"}),
        ),
    }
    SETTINGS_DEPENDENCIES = {
        "default_theme",
        "default_law_ai_prompt",
        "default_study_content_pack_prompt",
        "default_medical_study_pack_ai_addendum",
        "load_portal_config",
        "write_portal_config",
        "store_background_upload",
        "validate_custom_ai_url",
        "set_browser_presence_shutdown_enabled",
        "browser_presence_shutdown_runtime_eligible",
        "print_message",
    }
    MAINTENANCE_DEPENDENCIES = {
        "backup_upload_max_bytes",
        "upload_multipart_overhead_bytes",
        "create_backup",
        "send_backup_file",
        "make_restore_token",
        "restore_staging_dir",
        "create_backup_restore_stage",
        "stage_backup",
        "discard_restore_stage",
        "restore_operation_lock",
        "cancel_validated_restore_stage",
        "complete_staged_restore",
        "restore_error",
        "safety_backup_name",
        "recent_backups",
        "app_data_dir",
        "run_quiz_library_reset",
        "run_learning_intelligence_reset",
        "run_source_content_reset",
        "run_app_settings_reset",
        "run_full_data_reset",
        "run_legacy_wipe",
        "destructive_operation_error",
        "remove_all_runtime_data",
        "schedule_post_removal_shutdown",
        "print_message",
    }

    def test_blueprints_are_registered_once_and_own_exact_reconciled_rules(self):
        self.assertEqual(1, list(dlms.app.blueprints).count("settings"))
        self.assertEqual(1, list(dlms.app.blueprints).count("maintenance"))

        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        factories = {"create_settings_blueprint", "create_maintenance_blueprint"}
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
            {factory: 1 for factory in factories},
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
        self.assertEqual(35, len(rules))
        for rule in rules:
            with self.subTest(endpoint=rule.endpoint, rule=rule.rule):
                self.assertTrue(rule.strict_slashes)
                expected_module = f"dlms.routes.{rule.endpoint.split('.', 1)[0]}"
                self.assertEqual(
                    expected_module, dlms.app.view_functions[rule.endpoint].__module__
                )

    def test_namespaced_endpoints_build_canonical_urls_and_aliases_remain(self):
        canonical = {
            "settings.settings_page": "/settings",
            "settings.settings_lifecycle_page": "/settings/lifecycle",
            "settings.save_lifecycle_settings": "/settings/lifecycle/save",
            "settings.settings_navigation_page": "/settings/navigation",
            "settings.save_navigation_settings": "/settings/navigation/save",
            "settings.settings_appearance_page": "/settings/appearance",
            "settings.save_appearance_settings": "/settings/appearance/save",
            "settings.api_set_theme": "/api/theme",
            "settings.settings_ai_page": "/settings/ai",
            "settings.save_ai_settings": "/settings/ai/save",
            "settings.settings_parsing_page": "/settings/parsing",
            "settings.save_parsing_settings": "/settings/parsing/save",
            "settings.settings_legacy_page": "/settings/legacy",
            "settings.save_settings": "/save_settings",
            "settings.api_portal_config": "/api/portal_config",
            "maintenance.admin_maintenance": "/admin/maintenance",
            "maintenance.reset_quiz_library": "/api/reset_quiz_library",
            "maintenance.reset_learning_intelligence": "/api/reset_learning_intelligence",
            "maintenance.reset_source_content": "/api/reset_source_content",
            "maintenance.reset_app_settings": "/api/reset_app_settings",
            "maintenance.reset_all_data": "/api/reset_all_data",
            "maintenance.remove_all_dlms_data": "/api/remove_all_dlms_data",
            "maintenance.wipe_database": "/api/wipe_database",
            "maintenance.settings_create_backup": "/settings/backup/create",
            "maintenance.settings_stage_restore": "/settings/backup/restore/stage",
            "maintenance.settings_cancel_restore": "/settings/backup/restore/cancel/token",
            "maintenance.settings_confirm_restore": "/settings/backup/restore/confirm/token",
            "maintenance.settings_data_legacy_redirect": "/settings/data",
            "maintenance.settings_backup_page": "/settings/backup",
            "maintenance.settings_reset_legacy_redirect": "/settings/reset",
            "maintenance.settings_reset_remove_page": "/settings/reset-remove",
        }
        values = {
            "maintenance.settings_cancel_restore": {"token": "token"},
            "maintenance.settings_confirm_restore": {"token": "token"},
        }
        with dlms.app.test_request_context():
            for endpoint, expected in canonical.items():
                with self.subTest(endpoint=endpoint):
                    self.assertEqual(
                        expected, url_for(endpoint, **values.get(endpoint, {}))
                    )

        actual_rules = {(rule.endpoint, rule.rule) for rule in dlms.app.url_map.iter_rules()}
        for endpoint, alias in (
            (
                "maintenance.settings_create_backup",
                "/settings/data/backup/create",
            ),
            (
                "maintenance.settings_stage_restore",
                "/settings/data/restore/stage",
            ),
            (
                "maintenance.settings_cancel_restore",
                "/settings/data/restore/cancel/<token>",
            ),
            (
                "maintenance.settings_confirm_restore",
                "/settings/data/restore/confirm/<token>",
            ),
        ):
            self.assertIn((endpoint, alias), actual_rules)

    def test_dependencies_are_explicit_frozen_and_modules_do_not_import_app(self):
        cases = (
            (
                settings_routes.SettingsRouteDependencies,
                self.SETTINGS_DEPENDENCIES,
                settings_routes.create_settings_blueprint,
                SETTINGS_PATH,
            ),
            (
                maintenance_routes.MaintenanceRouteDependencies,
                self.MAINTENANCE_DEPENDENCIES,
                maintenance_routes.create_maintenance_blueprint,
                MAINTENANCE_PATH,
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

    def test_migrated_handlers_are_not_app_owned_and_url_for_inventory_is_clean(self):
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

        template_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
        )
        template_targets = set(
            re.findall(r"url_for\(\s*['\"]([^'\"]+)", template_source)
        )
        self.assertTrue(old_names.isdisjoint(template_targets))
        for literal_url in (
            'href="/settings/backup"',
            'href="/settings/reset-remove"',
            'action="/settings/navigation/save"',
            'action="/settings/lifecycle/save"',
            'action="/settings/appearance/save"',
            'action="/settings/ai/save"',
            'action="/settings/parsing/save"',
            'action="/settings/backup/create"',
            'action="/settings/backup/restore/stage"',
            'fetch("/admin/rebuild_all_quiz_html", {method: "POST"})',
        ):
            self.assertIn(literal_url, template_source)

    def test_factories_use_injected_settings_reset_and_restore_lock_boundaries(self):
        settings_services = {
            name: mock.Mock() for name in self.SETTINGS_DEPENDENCIES
        }
        settings_services["load_portal_config"].return_value = {
            "study_area_visibility": {"it": True}
        }
        settings_dependencies = settings_routes.SettingsRouteDependencies(
            **settings_services
        )
        settings_app = Flask("settings-test")
        settings_app.register_blueprint(
            settings_routes.create_settings_blueprint(settings_dependencies)
        )
        with mock.patch.object(
            settings_routes, "render_template", return_value="rendered"
        ) as renderer:
            response = settings_app.test_client().get("/settings/navigation")
        self.assertEqual(200, response.status_code)
        renderer.assert_called_once_with(
            "settings/navigation.html", visibility={"it": True}
        )

        maintenance_services = {
            name: mock.Mock() for name in self.MAINTENANCE_DEPENDENCIES
        }
        maintenance_services["restore_operation_lock"] = threading.RLock()
        maintenance_services["run_quiz_library_reset"].return_value = "safety.zip"
        maintenance_services["complete_staged_restore"].return_value = {
            "safety_path": "/tmp/safety.zip",
            "cleanup_pending": False,
        }
        maintenance_services["safety_backup_name"].return_value = "safety.zip"
        maintenance_dependencies = maintenance_routes.MaintenanceRouteDependencies(
            **maintenance_services
        )
        maintenance_app = Flask("maintenance-test")
        maintenance_app.register_blueprint(
            maintenance_routes.create_maintenance_blueprint(
                maintenance_dependencies
            )
        )
        reset = maintenance_app.test_client().post("/api/reset_quiz_library")
        self.assertEqual(
            {"status": "ok", "backup": "safety.zip"}, reset.get_json()
        )
        maintenance_services["run_quiz_library_reset"].assert_called_once_with()

        with mock.patch.object(
            maintenance_routes, "render_template", return_value="complete"
        ):
            restored = maintenance_app.test_client().post(
                "/settings/backup/restore/confirm/token"
            )
        self.assertEqual(200, restored.status_code)
        maintenance_services["complete_staged_restore"].assert_called_once_with(
            "token"
        )

    def test_shutdown_stays_app_owned_and_rebuild_split_stays_quiz_owned(self):
        shutdown_rules = [
            rule for rule in dlms.app.url_map.iter_rules() if rule.rule == "/api/shutdown"
        ]
        self.assertEqual(1, len(shutdown_rules))
        self.assertEqual("shutdown_app", shutdown_rules[0].endpoint)
        self.assertEqual("app", dlms.app.view_functions["shutdown_app"].__module__)

        rebuild_rules = [
            rule
            for rule in dlms.app.url_map.iter_rules()
            if rule.rule == "/admin/rebuild_all_quiz_html"
        ]
        self.assertEqual(1, len(rebuild_rules))
        self.assertEqual("quiz.rebuild_all_quiz_html", rebuild_rules[0].endpoint)
        self.assertEqual(
            "dlms.routes.quiz.editor",
            dlms.app.view_functions["quiz.rebuild_all_quiz_html"].__module__,
        )

        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        app_routes = [
            node
            for node in app_tree.body
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr == "route"
                for decorator in node.decorator_list
            )
        ]
        self.assertEqual(["shutdown_app"], [node.name for node in app_routes])

    def test_global_security_csrf_and_strict_slash_behavior_are_preserved(self):
        client = dlms.app.test_client()
        response = client.get("/settings")
        self.assertEqual(200, response.status_code)
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])
        self.assertIn("dlms_csrf_token=", response.headers.get("Set-Cookie", ""))

        self.assertEqual(404, client.get("/settings/").status_code)
        self.assertEqual(404, client.get("/admin/maintenance/").status_code)
        self.assertEqual(400, client.post("/api/reset_all_data").status_code)


if __name__ == "__main__":
    unittest.main()
