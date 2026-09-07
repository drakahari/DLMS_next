"""Structural and integration coverage for the Quiz lifecycle Blueprint."""

import ast
import dataclasses
import inspect
import unittest
from pathlib import Path

from flask import url_for

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import quiz as quiz_routes


ROOT = Path(dlms.__file__).resolve().parent
APP_PATH = ROOT / "app.py"
QUIZ_ROUTE_ROOT = ROOT / "dlms" / "routes" / "quiz"


class QuizBlueprintTests(unittest.TestCase):
    EXPECTED_RULES = {
        "quiz.toggle_hidden": ("/toggle_hidden", {"POST"}),
        "quiz.move_quiz_folder": ("/move_quiz_folder", {"POST"}),
        "quiz.add_quiz_folder": ("/add_quiz_folder", {"POST"}),
        "quiz.set_quiz_folder_hidden": ("/set_quiz_folder_hidden", {"POST"}),
        "quiz.rename_quiz_folder": ("/rename_quiz_folder", {"POST"}),
        "quiz.delete_quiz_folder": ("/delete_quiz_folder", {"POST"}),
        "quiz.save_folder_order": ("/save_folder_order", {"POST"}),
        "quiz.save_quiz_order_in_folder": ("/save_quiz_order_in_folder", {"POST"}),
        "quiz.save_order": ("/save_order", {"POST"}),
        "quiz.export_all_quizzes_txt": ("/export/all_quizzes.txt", {"GET"}),
        "quiz.export_single_quiz_txt": ("/export/quiz/<int:quiz_id>.txt", {"GET"}),
        "quiz.quiz_library": ("/library", {"GET"}),
        "quiz.serve_data": ("/data/<path:filename>", {"GET"}),
        "quiz.serve_quiz": ("/quizzes/<path:filename>", {"GET"}),
        "quiz.edit_quiz": ("/edit_quiz/<int:quiz_id>", {"GET"}),
        "quiz.rebuild_all_quiz_html": ("/admin/rebuild_all_quiz_html", {"POST"}),
        "quiz.save_edited_quiz": ("/edit_quiz/<int:quiz_id>", {"POST"}),
        "quiz.delete_question_from_quiz": ("/delete_question/<int:quiz_id>/<int:question_id>", {"POST"}),
        "quiz.add_choices_to_question": ("/add_choices/<int:quiz_id>/<int:question_id>", {"POST"}),
        "quiz.delete_choice_from_question": ("/delete_choice/<int:quiz_id>/<int:choice_id>", {"POST"}),
        "quiz.delete_match_pair_from_question": ("/delete_match_pair/<int:quiz_id>/<int:pair_id>", {"POST"}),
        "quiz.delete_quiz": ("/delete_quiz/<int:quiz_id>", {"POST"}),
        "quiz.upload_page": ("/upload", {"GET"}),
        "quiz.paste_page": ("/paste", {"GET"}),
        "quiz.matching_bank_import": ("/matching_bank_import", {"GET", "POST"}),
        "quiz.create_short_quiz_page": ("/create_short_quiz", {"GET"}),
        "quiz.save_short_quiz": ("/create_short_quiz", {"POST"}),
        "quiz.preview_paste": ("/preview_paste", {"POST"}),
        "quiz.download_cleaned": ("/download_cleaned", {"GET", "POST"}),
        "quiz.process_paste": ("/process_paste", {"POST"}),
        "quiz.process_file": ("/process", {"POST"}),
    }
    LIBRARY_DEPENDENCIES = {
        "app_version", "logo_folder", "quiz_registry_path", "registry_lock",
        "load_registry", "save_registry", "normalize_quiz_folders",
        "get_quiz_folders", "save_quiz_folders", "get_hidden_quiz_folders",
        "save_quiz_folder_state", "get_portal_title", "resolve_logo_filename",
        "debug_print", "get_db",
    }
    EDITOR_DEPENDENCIES = {
        "app_version", "data_folder", "browser_served_data_extensions",
        "quiz_folder", "get_db", "load_registry", "normalize_exam_minutes",
        "question_concepts", "finish_quiz_mutation", "quiz_owns_question",
        "quiz_owns_choice", "quiz_owns_matching_pair", "set_question_concepts",
        "quiz_edit_validation", "publish_quiz_edit_request",
        "delete_quiz_transaction", "cleanup_deleted_quiz_artifacts",
        "rebuild_quiz_html_from_registry",
    }
    AUTHORING_DEPENDENCIES = {
        "data_folder", "logo_folder", "parse_log_path",
        "upload_folder", "matching_csv_upload_max_bytes",
        "quiz_text_upload_max_bytes", "upload_too_large_error",
        "get_portal_title", "load_portal_config",
        "matching_case_only_term_warnings", "matching_record_validation_errors",
        "publish_quiz", "read_bounded_upload", "normalize_exam_minutes",
        "finalize_logo_from_request", "save_preview_logo",
        "get_confidence_setting", "analyze_confidence", "parse_questions",
        "debug_print",
    }

    def test_blueprint_is_registered_once_and_owns_exact_route_contract(self):
        self.assertEqual(1, list(dlms.app.blueprints).count("quiz"))
        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        registrations = [
            node for node in ast.walk(app_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "app"
            and node.func.attr == "register_blueprint"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == "create_quiz_blueprint"
        ]
        self.assertEqual(1, len(registrations))

        rules = {
            rule.endpoint: rule
            for rule in dlms.app.url_map.iter_rules()
            if rule.endpoint.startswith("quiz.")
        }
        self.assertEqual(set(self.EXPECTED_RULES), set(rules))
        for endpoint, (path, methods) in self.EXPECTED_RULES.items():
            with self.subTest(endpoint=endpoint):
                rule = rules[endpoint]
                self.assertEqual(path, rule.rule)
                self.assertEqual(methods | {"OPTIONS"} | ({"HEAD"} if "GET" in methods else set()), rule.methods)
                self.assertTrue(rule.strict_slashes)
                self.assertTrue(dlms.app.view_functions[endpoint].__module__.startswith("dlms.routes.quiz."))

    def test_namespaced_endpoints_build_original_public_urls(self):
        values = {
            "quiz.export_single_quiz_txt": {"quiz_id": 7},
            "quiz.serve_data": {"filename": "parse.txt"},
            "quiz.serve_quiz": {"filename": "quiz.html"},
            "quiz.edit_quiz": {"quiz_id": 7},
            "quiz.save_edited_quiz": {"quiz_id": 7},
            "quiz.delete_question_from_quiz": {"quiz_id": 7, "question_id": 11},
            "quiz.add_choices_to_question": {"quiz_id": 7, "question_id": 11},
            "quiz.delete_choice_from_question": {"quiz_id": 7, "choice_id": 13},
            "quiz.delete_match_pair_from_question": {"quiz_id": 7, "pair_id": 17},
            "quiz.delete_quiz": {"quiz_id": 7},
        }
        expected_paths = {
            endpoint: rule.replace("<int:quiz_id>", "7")
            .replace("<int:question_id>", "11")
            .replace("<int:choice_id>", "13")
            .replace("<int:pair_id>", "17")
            .replace("<path:filename>", values.get(endpoint, {}).get("filename", ""))
            for endpoint, (rule, _methods) in self.EXPECTED_RULES.items()
        }
        with dlms.app.test_request_context():
            for endpoint, expected in expected_paths.items():
                with self.subTest(endpoint=endpoint):
                    self.assertEqual(expected, url_for(endpoint, **values.get(endpoint, {})))

    def test_dependencies_are_explicit_and_route_modules_do_not_import_app(self):
        self.assertEqual(
            self.LIBRARY_DEPENDENCIES,
            {field.name for field in dataclasses.fields(quiz_routes.QuizLibraryDependencies)},
        )
        self.assertEqual(
            self.EDITOR_DEPENDENCIES,
            {field.name for field in dataclasses.fields(quiz_routes.QuizEditorDependencies)},
        )
        self.assertEqual(
            self.AUTHORING_DEPENDENCIES,
            {field.name for field in dataclasses.fields(quiz_routes.QuizAuthoringDependencies)},
        )
        self.assertEqual(
            ["library_dependencies", "editor_dependencies", "authoring_dependencies"],
            list(inspect.signature(quiz_routes.create_quiz_blueprint).parameters),
        )

        for path in QUIZ_ROUTE_ROOT.glob("*.py"):
            with self.subTest(route_module=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imported_modules = {
                    alias.name for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for alias in node.names
                }
                imported_from = {
                    node.module for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                }
                self.assertNotIn("app", imported_modules)
                self.assertNotIn("app", imported_from)

    def test_migrated_handlers_are_not_app_owned_and_url_for_is_namespaced(self):
        app_tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        old_names = {endpoint.split(".", 1)[1] for endpoint in self.EXPECTED_RULES}
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

        route_trees = [app_tree] + [
            ast.parse(path.read_text(encoding="utf-8"))
            for path in QUIZ_ROUTE_ROOT.glob("*.py")
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
        self.assertIn("quiz.edit_quiz", url_for_targets)

    def test_global_security_headers_csrf_and_strict_slash_behavior_are_preserved(self):
        for path in ("/library", "/upload", "/paste", "/matching_bank_import", "/create_short_quiz"):
            with self.subTest(path=path):
                response = dlms.app.test_client().get(path)
                self.assertEqual(200, response.status_code)
                self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
                self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
                self.assertEqual("DENY", response.headers["X-Frame-Options"])
                self.assertIn("dlms_csrf_token=", response.headers.get("Set-Cookie", ""))
                self.assertEqual(404, dlms.app.test_client().get(f"{path}/").status_code)

        response = dlms.app.test_client().post("/toggle_hidden", data={"id": "1"})
        self.assertEqual(400, response.status_code)
        self.assertIn(b"The security token is missing or invalid.", response.data)


if __name__ == "__main__":
    unittest.main()
