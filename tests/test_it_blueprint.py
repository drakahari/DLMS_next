"""Structural and integration coverage for the IT Study Blueprint pilot."""

import ast
import dataclasses
import inspect
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask, url_for

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import it as it_routes


ROOT = Path(dlms.__file__).resolve().parent
IT_ROUTE_PATH = ROOT / "dlms" / "routes" / "it.py"


class ITBlueprintTests(unittest.TestCase):
    EXPECTED_RULES = {
        "/it": "it.it_study_home",
        "/it/matching": "it.it_matching",
        "/it/images": "it.it_images",
    }
    EXPECTED_DEPENDENCIES = {
        "discover_content_packs",
        "load_content_pack_dataset",
        "load_content_pack_image_dataset",
        "load_content_pack_quiz_dataset",
        "is_it_pack_manifest",
    }

    def setUp(self):
        self.client = dlms.app.test_client()

    def test_blueprint_is_registered_once_and_owns_exact_route_contract(self):
        self.assertEqual(1, list(dlms.app.blueprints).count("it"))

        app_tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
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
            and node.args[0].func.id == "create_it_blueprint"
        ]
        self.assertEqual(1, len(registrations))

        rules = {
            rule.rule: rule
            for rule in dlms.app.url_map.iter_rules()
            if rule.rule == "/it" or rule.rule.startswith("/it/")
        }
        self.assertEqual(set(self.EXPECTED_RULES), set(rules))
        for path, endpoint in self.EXPECTED_RULES.items():
            with self.subTest(path=path):
                rule = rules[path]
                self.assertEqual(endpoint, rule.endpoint)
                self.assertEqual({"GET", "HEAD", "OPTIONS"}, rule.methods)
                self.assertTrue(rule.strict_slashes)

        for old_endpoint in ("it_study_home", "it_matching", "it_images"):
            self.assertNotIn(old_endpoint, dlms.app.view_functions)

    def test_namespaced_endpoints_build_the_original_urls(self):
        with dlms.app.test_request_context():
            self.assertEqual("/it", url_for("it.it_study_home"))
            self.assertEqual("/it/matching", url_for("it.it_matching"))
            self.assertEqual("/it/images", url_for("it.it_images"))

    def test_trailing_slash_and_global_response_security_behavior_are_preserved(self):
        for path in self.EXPECTED_RULES:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(200, response.status_code)
                self.assertEqual("text/html", response.mimetype)
                self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
                self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
                self.assertEqual("DENY", response.headers["X-Frame-Options"])
                self.assertIn("dlms_csrf_token=", response.headers.get("Set-Cookie", ""))
                self.assertEqual(404, self.client.get(f"{path}/").status_code)

    def test_dependency_boundary_is_explicit_and_route_module_does_not_import_app(self):
        fields = {field.name for field in dataclasses.fields(it_routes.ITStudyDependencies)}
        self.assertEqual(self.EXPECTED_DEPENDENCIES, fields)
        parameters = inspect.signature(it_routes.create_it_blueprint).parameters
        self.assertEqual(["dependencies"], list(parameters))

        tree = ast.parse(IT_ROUTE_PATH.read_text(encoding="utf-8"))
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

        app_tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        app_route_functions = {
            node.name
            for node in app_tree.body
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "route"
                for decorator in node.decorator_list
            )
        }
        self.assertTrue(
            {"it_study_home", "it_matching", "it_images"}.isdisjoint(
                app_route_functions
            )
        )

    def test_blueprint_factory_preserves_populated_home_discovery_behavior(self):
        discover = mock.Mock(return_value={
            "sample": {
                "id": "sample",
                "name": "Sample IT",
                "version": "1",
            }
        })
        dependencies = it_routes.ITStudyDependencies(
            discover_content_packs=discover,
            load_content_pack_dataset=mock.Mock(),
            load_content_pack_image_dataset=mock.Mock(),
            load_content_pack_quiz_dataset=mock.Mock(),
            is_it_pack_manifest=mock.Mock(return_value=True),
        )
        application = Flask(__name__)
        application.register_blueprint(it_routes.create_it_blueprint(dependencies))

        with mock.patch.object(it_routes, "render_template", return_value="rendered"):
            response = application.test_client().get("/it")

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"rendered", response.data)
        self.assertEqual(2, discover.call_count)

    def test_aggregation_preserves_sorting_and_per_dataset_failure_recovery(self):
        packs = {
            "zulu": {
                "name": "Zulu",
                "datasets": [{"id": "z-terms"}],
                "image_datasets": [{"id": "z-images"}],
                "quiz_datasets": [{"id": "z-questions"}],
            },
            "alpha": {
                "name": "alpha",
                "datasets": [{"id": "a-terms"}],
            },
        }
        load_matching = mock.Mock(side_effect=[
            {"title": "Alpha terms", "terms": [{"term": "A"}]},
            ValueError("matching unavailable"),
        ])
        dependencies = it_routes.ITStudyDependencies(
            discover_content_packs=mock.Mock(return_value=packs),
            load_content_pack_dataset=load_matching,
            load_content_pack_image_dataset=mock.Mock(
                side_effect=ValueError("images unavailable")
            ),
            load_content_pack_quiz_dataset=mock.Mock(
                side_effect=ValueError("questions unavailable")
            ),
            is_it_pack_manifest=mock.Mock(return_value=True),
        )

        with mock.patch("builtins.print") as printed:
            pack, datasets, image_datasets, quiz_datasets = (
                it_routes._it_pack_page_data(dependencies)
            )

        self.assertEqual("it_collection", pack["id"])
        self.assertEqual("2 installed packs", pack["version"])
        self.assertEqual(["a-terms"], [dataset["id"] for dataset in datasets])
        self.assertEqual([], image_datasets)
        self.assertEqual([], quiz_datasets)
        self.assertEqual(
            [mock.call("alpha", "a-terms"), mock.call("zulu", "z-terms")],
            load_matching.call_args_list,
        )
        messages = [call.args[0] for call in printed.call_args_list]
        self.assertIn(
            "[IT STUDY] Dataset zulu/'z-terms' unavailable: matching unavailable",
            messages,
        )
        self.assertIn(
            "[IT STUDY] Image dataset zulu/'z-images' unavailable: images unavailable",
            messages,
        )
        self.assertIn(
            "[IT STUDY] Question dataset zulu/'z-questions' unavailable: questions unavailable",
            messages,
        )


if __name__ == "__main__":
    unittest.main()
