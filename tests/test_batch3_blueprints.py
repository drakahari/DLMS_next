"""Structural and integration coverage for DLMS-061 Blueprint Batch 3."""

import ast
import dataclasses
import inspect
import unittest
from pathlib import Path

from flask import url_for

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import admin_images as admin_image_routes
from dlms.routes import content_packs as content_pack_routes
from dlms.routes import medical as medical_routes
from dlms.routes import study_packs as study_pack_routes


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
ROUTE_MODULES = {
    "content_packs": content_pack_routes,
    "study_packs": study_pack_routes,
    "medical": medical_routes,
    "admin_images": admin_image_routes,
}


class Batch3BlueprintTests(unittest.TestCase):
    EXPECTED_RULES = {
        ("/content-packs/import", "content_packs.content_pack_import", frozenset({"POST"})),
        ("/content-packs/import/<token>", "content_packs.content_pack_import_review", frozenset({"GET"})),
        ("/content-packs/import/<token>/install", "content_packs.content_pack_import_install", frozenset({"POST"})),
        ("/content-packs/import/<token>/cancel", "content_packs.content_pack_import_cancel", frozenset({"POST"})),
        ("/content-packs/details/<folder>", "content_packs.content_pack_details", frozenset({"GET"})),
        ("/content-packs/export/<folder>", "content_packs.export_content_pack", frozenset({"GET"})),
        ("/content-packs", "content_packs.content_packs_page", frozenset({"GET"})),
        ("/content-packs/delete", "content_packs.delete_content_pack", frozenset({"POST"})),
        ("/study-packs/ai-builder/import", "study_packs.study_pack_ai_builder_import", frozenset({"POST"})),
        ("/study-packs", "study_packs.study_packs_home", frozenset({"GET"})),
        ("/study-packs/quiz/generate", "study_packs.study_pack_generate_quiz_dataset", frozenset({"POST"})),
        ("/study-packs/generate", "study_packs.study_pack_generate_matching", frozenset({"POST"})),
        ("/study-packs/image/generate", "study_packs.study_pack_generate_image", frozenset({"POST"})),
        ("/study-packs/ai-builder", "study_packs.study_pack_ai_builder", frozenset({"GET", "POST"})),
        ("/image-builder/drafts/<draft_id>/<path:filename>", "study_packs.image_builder_draft_asset", frozenset({"GET"})),
        ("/study-packs/image-builder", "study_packs.image_quiz_builder", frozenset({"GET", "POST"})),
        ("/study-packs/image-builder/save", "study_packs.image_quiz_builder_save", frozenset({"POST"})),
        ("/medical", "medical.medical_study_home", frozenset({"GET"})),
        ("/medical/ai-builder", "medical.medical_ai_content_builder", frozenset({"GET", "POST"})),
        ("/medical/matching", "medical.medical_matching", frozenset({"GET"})),
        ("/medical/anatomy", "medical.medical_anatomy", frozenset({"GET"})),
        ("/medical/anatomy/generate", "medical.medical_generate_anatomy_quiz", frozenset({"POST"})),
        ("/medical/generate", "medical.medical_generate_quiz", frozenset({"POST"})),
        ("/admin/hotspots", "admin_images.admin_hotspot_editor", frozenset({"GET"})),
        ("/admin/image-editor", "admin_images.admin_hotspot_editor", frozenset({"GET"})),
        ("/admin/hotspots/save", "admin_images.admin_hotspot_save", frozenset({"POST"})),
        ("/admin/image-editor/hotspot/save", "admin_images.admin_hotspot_save", frozenset({"POST"})),
        ("/admin/image-editor/edits/save", "admin_images.admin_image_edits_save", frozenset({"POST"})),
    }

    DEPENDENCIES = {
        content_pack_routes.ContentPackRouteDependencies: {
            "content_pack_ai_workflow", "content_pack_upload_max_bytes",
            "content_pack_multipart_overhead_bytes", "content_pack_folder",
            "stage_content_pack_upload", "content_pack_workflow",
            "content_pack_workflow_return_url", "load_staged_content_pack",
            "validate_staged_content_pack", "install_staged_content_pack",
            "cancel_staged_content_pack", "content_pack_folder_report",
            "build_content_pack_export", "content_pack_management_summary",
            "delete_content_pack_folder", "content_pack_install_error",
            "invalid_content_pack_folder_error",
            "content_pack_folder_not_found_error", "protected_content_pack_error",
        },
        study_pack_routes.StudyPackRouteDependencies: {
            "content_pack_ai_workflow", "stage_content_pack_upload",
            "discover_content_packs", "study_pack_catalog_domain_group",
            "load_content_pack_dataset",
            "load_content_pack_image_dataset", "load_content_pack_quiz_dataset",
            "get_content_pack", "quiz_dataset_runtime", "create_quiz_from_runtime",
            "publish_quiz", "standalone_matching_concepts", "hotspot_concepts",
            "load_portal_config", "default_study_content_pack_prompt",
            "default_medical_study_pack_ai_addendum", "safe_image_builder_draft",
            "safe_pack_child", "passive_pack_image_extensions",
            "decode_raster_image", "image_builder_draft_folder",
            "image_builder_total_upload_max_bytes", "raster_upload_max_bytes",
            "store_raster_upload", "create_image_study_pack",
            "generated_quiz_artifact_identity",
        },
        medical_routes.MedicalRouteDependencies: {
            "discover_content_packs", "is_medical_content_pack",
            "load_content_pack_dataset", "load_content_pack_image_dataset",
            "content_pack_folder", "get_content_pack", "hotspot_concepts",
            "standalone_matching_concepts", "publish_quiz",
        },
        admin_image_routes.AdminImageRouteDependencies: {
            "discover_content_packs", "load_content_pack_image_dataset",
            "load_content_pack_quiz_dataset", "validate_hotspot_shape",
            "get_content_pack", "safe_pack_child",
        },
    }

    def test_blueprints_are_registered_once_and_own_exact_reconciled_rules(self):
        for blueprint_name in ROUTE_MODULES:
            with self.subTest(blueprint=blueprint_name):
                self.assertEqual(1, list(dlms.app.blueprints).count(blueprint_name))

        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        factory_names = {
            "create_content_packs_blueprint", "create_study_packs_blueprint",
            "create_medical_blueprint", "create_admin_images_blueprint",
        }
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
            and node.args[0].func.id in factory_names
        ]
        self.assertEqual(factory_names, set(registrations))
        self.assertEqual(4, len(registrations))

        actual = set()
        for rule in dlms.app.url_map.iter_rules():
            if rule.endpoint.split(".", 1)[0] not in ROUTE_MODULES:
                continue
            methods = frozenset(rule.methods - {"HEAD", "OPTIONS"})
            actual.add((rule.rule, rule.endpoint, methods))
            self.assertTrue(rule.strict_slashes)
            self.assertTrue(
                dlms.app.view_functions[rule.endpoint].__module__.startswith(
                    "dlms.routes."
                )
            )
        self.assertEqual(self.EXPECTED_RULES, actual)

    def test_namespaced_endpoints_build_original_urls_and_alias_order(self):
        cases = {
            "content_packs.content_pack_import": ("/content-packs/import", {}),
            "content_packs.content_pack_import_review": ("/content-packs/import/token", {"token": "token"}),
            "content_packs.content_pack_import_install": ("/content-packs/import/token/install", {"token": "token"}),
            "content_packs.content_pack_import_cancel": ("/content-packs/import/token/cancel", {"token": "token"}),
            "content_packs.content_pack_details": ("/content-packs/details/folder", {"folder": "folder"}),
            "content_packs.export_content_pack": ("/content-packs/export/folder", {"folder": "folder"}),
            "content_packs.content_packs_page": ("/content-packs", {}),
            "content_packs.delete_content_pack": ("/content-packs/delete", {}),
            "study_packs.study_pack_ai_builder_import": ("/study-packs/ai-builder/import", {}),
            "study_packs.study_packs_home": ("/study-packs", {}),
            "study_packs.study_pack_generate_quiz_dataset": ("/study-packs/quiz/generate", {}),
            "study_packs.study_pack_generate_matching": ("/study-packs/generate", {}),
            "study_packs.study_pack_generate_image": ("/study-packs/image/generate", {}),
            "study_packs.study_pack_ai_builder": ("/study-packs/ai-builder", {}),
            "study_packs.image_builder_draft_asset": ("/image-builder/drafts/draft1234/image.png", {"draft_id": "draft1234", "filename": "image.png"}),
            "study_packs.image_quiz_builder": ("/study-packs/image-builder", {}),
            "study_packs.image_quiz_builder_save": ("/study-packs/image-builder/save", {}),
            "medical.medical_study_home": ("/medical", {}),
            "medical.medical_ai_content_builder": ("/medical/ai-builder", {}),
            "medical.medical_matching": ("/medical/matching", {}),
            "medical.medical_anatomy": ("/medical/anatomy", {}),
            "medical.medical_generate_anatomy_quiz": ("/medical/anatomy/generate", {}),
            "medical.medical_generate_quiz": ("/medical/generate", {}),
            "admin_images.admin_hotspot_editor": ("/admin/hotspots", {}),
            "admin_images.admin_hotspot_save": ("/admin/hotspots/save", {}),
            "admin_images.admin_image_edits_save": ("/admin/image-editor/edits/save", {}),
        }
        with dlms.app.test_request_context():
            for endpoint, (expected, values) in cases.items():
                with self.subTest(endpoint=endpoint):
                    self.assertEqual(expected, url_for(endpoint, **values))

    def test_dependencies_are_explicit_and_route_modules_do_not_import_app(self):
        factories = {
            content_pack_routes.create_content_packs_blueprint,
            study_pack_routes.create_study_packs_blueprint,
            medical_routes.create_medical_blueprint,
            admin_image_routes.create_admin_images_blueprint,
        }
        for dependency_type, expected_fields in self.DEPENDENCIES.items():
            with self.subTest(dependencies=dependency_type.__name__):
                self.assertEqual(
                    expected_fields,
                    {field.name for field in dataclasses.fields(dependency_type)},
                )
        for factory in factories:
            self.assertEqual(["dependencies"], list(inspect.signature(factory).parameters))

        for module in ROUTE_MODULES.values():
            path = Path(module.__file__)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported_modules = {
                alias.name for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names
            }
            imported_from = {
                node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            }
            self.assertNotIn("app", imported_modules)
            self.assertNotIn("app", imported_from)

    def test_migrated_handlers_are_not_app_owned_and_url_for_targets_are_namespaced(self):
        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        old_names = {endpoint.split(".", 1)[1] for _, endpoint, _ in self.EXPECTED_RULES}
        app_route_functions = {
            node.name for node in app_tree.body
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

        trees = [app_tree] + [
            ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            for module in ROUTE_MODULES.values()
        ]
        url_for_targets = {
            node.args[0].value
            for tree in trees for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "url_for"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        self.assertTrue(old_names.isdisjoint(url_for_targets))
        self.assertIn("content_packs.content_pack_import_review", url_for_targets)
        self.assertIn("study_packs.study_pack_ai_builder", url_for_targets)
        self.assertIn("study_packs.image_builder_draft_asset", url_for_targets)

    def test_global_security_csrf_and_strict_slash_behavior_are_preserved(self):
        client = dlms.app.test_client()
        for path in (
            "/content-packs", "/study-packs", "/study-packs/ai-builder",
            "/study-packs/image-builder", "/medical", "/medical/matching",
            "/medical/anatomy", "/admin/image-editor", "/admin/hotspots",
        ):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(200, response.status_code)
                self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
                self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
                self.assertEqual("DENY", response.headers["X-Frame-Options"])
                self.assertIn("dlms_csrf_token=", response.headers.get("Set-Cookie", ""))
                self.assertEqual(404, client.get(path + "/").status_code)

        for path in (
            "/content-packs/import", "/content-packs/delete",
            "/study-packs/generate", "/medical/generate",
            "/admin/hotspots/save",
        ):
            with self.subTest(path=path):
                response = client.post(path)
                self.assertEqual(400, response.status_code)
                self.assertIn(b"The security token is missing or invalid.", response.data)


if __name__ == "__main__":
    unittest.main()
