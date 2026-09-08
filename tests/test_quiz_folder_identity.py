"""DLMS-115 canonical Quiz Library folder identity regressions."""

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services import quiz_mutations
from tests.csrf_test_utils import csrf_headers


class QuizFolderIdentityTests(unittest.TestCase):
    @contextmanager
    def folder_state(self, portal, registry):
        with tempfile.TemporaryDirectory(
            prefix="dlms-folder-identity-"
        ) as directory:
            config = Path(directory) / "config"
            config.mkdir()
            portal_path = config / "portal.json"
            registry_path = config / "quizzes.json"
            portal_path.write_text(
                json.dumps(portal, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            registry_path.write_text(
                json.dumps(registry, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal_path)), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", str(registry_path)), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                yield dlms.app.test_client(), portal_path, registry_path

    @staticmethod
    def post(client, path, *, data=None, json_data=None):
        response = client.post(
            path,
            data=data,
            json=json_data,
            headers=csrf_headers(client, "/library"),
        )
        return response

    def test_identity_prefers_configured_spelling_and_deduplicates_assignments(self):
        configured = ["Uncategorized", "Course"]
        registry = [
            {"id": 1, "folder": "course"},
            {"id": 2, "folder": "Legacy Z"},
            {"id": 3, "folder": "legacy z"},
            {"id": 4, "folder": "Legacy A"},
        ]
        original = deepcopy(registry)

        identity = quiz_mutations.build_quiz_folder_identity(
            configured, registry
        )

        self.assertEqual(
            ("Uncategorized", "Course", "Legacy A", "Legacy Z"),
            identity.folders,
        )
        self.assertEqual("Course", identity.resolve("cOuRsE"))
        self.assertEqual("Legacy Z", identity.resolve("LEGACY Z"))
        self.assertTrue(identity.is_configured("COURSE"))
        self.assertFalse(identity.is_configured("legacy a"))
        self.assertEqual(original, registry)

    def test_add_rejects_configured_exact_and_case_only_duplicates(self):
        portal = {
            "title": "Keep",
            "quiz_folders": ["Uncategorized", "Course"],
            "hidden_quiz_folders": ["Course"],
        }
        registry = [{"id": 1, "html": "one.html", "folder": "Course"}]
        with self.folder_state(portal, registry) as (
            client, portal_path, registry_path
        ):
            csrf_headers(client, "/library")
            original_portal = portal_path.read_bytes()
            original_registry = registry_path.read_bytes()
            for duplicate in ("Course", "cOuRsE"):
                with self.subTest(duplicate=duplicate):
                    response = self.post(
                        client,
                        "/add_quiz_folder",
                        data={"folder": duplicate, "view": "visible"},
                    )
                    self.assertEqual(302, response.status_code)
                    response.close()
                    self.assertEqual(original_portal, portal_path.read_bytes())
                    self.assertEqual(original_registry, registry_path.read_bytes())

    def test_add_promotes_assignment_only_identity_using_stored_spelling(self):
        portal = {"quiz_folders": ["Uncategorized"], "unknown": "keep"}
        registry = [
            {
                "id": 1,
                "html": "legacy.html",
                "folder": "Legacy Course",
                "unknown": {"keep": True},
            }
        ]
        with self.folder_state(portal, registry) as (
            client, portal_path, registry_path
        ):
            original_registry = registry_path.read_bytes()
            response = self.post(
                client,
                "/add_quiz_folder",
                data={"folder": "legacy course", "view": "visible"},
            )
            response.close()

            saved_portal = json.loads(portal_path.read_text(encoding="utf-8"))
            self.assertEqual(
                ["Uncategorized", "Legacy Course"],
                saved_portal["quiz_folders"],
            )
            self.assertEqual("keep", saved_portal["unknown"])
            self.assertEqual(original_registry, registry_path.read_bytes())

    def test_rename_rejects_collision_but_case_only_updates_display_spelling(self):
        portal = {
            "quiz_folders": ["Uncategorized", "Course", "Existing"],
            "hidden_quiz_folders": ["course"],
            "unknown": "keep",
        }
        registry = [
            {"id": 1, "html": "one.html", "folder": "COURSE"},
            {"id": 2, "html": "two.html", "folder": "course"},
        ]
        with self.folder_state(portal, registry) as (
            client, portal_path, registry_path
        ):
            csrf_headers(client, "/library")
            original_portal = portal_path.read_bytes()
            original_registry = registry_path.read_bytes()
            collision = self.post(
                client,
                "/rename_quiz_folder",
                data={"old_folder": "course", "new_folder": "eXiStInG"},
            )
            self.assertEqual(302, collision.status_code)
            collision.close()
            self.assertEqual(original_portal, portal_path.read_bytes())
            self.assertEqual(original_registry, registry_path.read_bytes())

            renamed = self.post(
                client,
                "/rename_quiz_folder",
                data={"old_folder": "COURSE", "new_folder": "cOURSe"},
            )
            self.assertEqual(302, renamed.status_code)
            renamed.close()

            saved_portal = json.loads(portal_path.read_text(encoding="utf-8"))
            saved_registry = json.loads(
                registry_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                ["Uncategorized", "cOURSe", "Existing"],
                saved_portal["quiz_folders"],
            )
            self.assertEqual(["cOURSe"], saved_portal["hidden_quiz_folders"])
            self.assertEqual("keep", saved_portal["unknown"])
            self.assertTrue(
                all(quiz["folder"] == "cOURSe" for quiz in saved_registry)
            )

    def test_move_resolves_known_case_and_rejects_unknown_without_writing(self):
        portal = {"quiz_folders": ["Uncategorized", "Course"]}
        registry = [
            {"id": 1, "html": "one.html", "folder": "Uncategorized"}
        ]
        with self.folder_state(portal, registry) as (
            client, portal_path, registry_path
        ):
            csrf_headers(client, "/library")
            original_portal = portal_path.read_bytes()
            original_registry = registry_path.read_bytes()
            unknown = self.post(
                client,
                "/move_quiz_folder",
                data={"id": "1", "folder": "Client Invented"},
            )
            self.assertEqual(302, unknown.status_code)
            unknown.close()
            self.assertEqual(original_portal, portal_path.read_bytes())
            self.assertEqual(original_registry, registry_path.read_bytes())

            known = self.post(
                client,
                "/move_quiz_folder",
                data={"id": "1", "folder": "cOuRsE"},
            )
            self.assertEqual(302, known.status_code)
            known.close()
            self.assertEqual(
                "Course",
                json.loads(registry_path.read_text(encoding="utf-8"))[0][
                    "folder"
                ],
            )

            uncategorized = self.post(
                client,
                "/move_quiz_folder",
                data={"id": "1", "folder": "uNcAtEgOrIzEd"},
            )
            self.assertEqual(302, uncategorized.status_code)
            uncategorized.close()
            self.assertEqual(
                "Uncategorized",
                json.loads(registry_path.read_text(encoding="utf-8"))[0][
                    "folder"
                ],
            )
            self.assertEqual(original_portal, portal_path.read_bytes())

    def test_move_recognizes_assignment_only_folder_without_promoting_it(self):
        portal = {"quiz_folders": ["Uncategorized"], "unknown": "keep"}
        registry = [
            {"id": 1, "html": "legacy.html", "folder": "Legacy Course"},
            {"id": 2, "html": "moving.html", "folder": "Uncategorized"},
        ]
        with self.folder_state(portal, registry) as (
            client, portal_path, registry_path
        ):
            original_portal = portal_path.read_bytes()
            response = self.post(
                client,
                "/move_quiz_folder",
                data={"id": "2", "folder": "legacy course"},
            )
            self.assertEqual(302, response.status_code)
            response.close()

            saved_registry = json.loads(
                registry_path.read_text(encoding="utf-8")
            )
            self.assertEqual("Legacy Course", saved_registry[1]["folder"])
            self.assertEqual(original_portal, portal_path.read_bytes())

    def test_assignment_only_render_does_not_promote_and_uses_one_display_identity(self):
        portal = {"quiz_folders": ["Uncategorized"]}
        registry = [
            {"id": 1, "title": "One", "html": "one.html", "folder": "Legacy Course"},
            {"id": 2, "title": "Two", "html": "two.html", "folder": "legacy course"},
        ]
        with self.folder_state(portal, registry) as (
            client, portal_path, _registry_path
        ):
            original_portal = portal_path.read_bytes()
            response = client.get("/library")
            self.assertEqual(200, response.status_code)
            html = response.get_data(as_text=True)
            response.close()

            self.assertEqual(1, html.count("<h2>Legacy Course</h2>"))
            self.assertIn("One", html)
            self.assertIn("Two", html)
            self.assertEqual(original_portal, portal_path.read_bytes())

    def test_render_uses_configured_spelling_for_case_variant_assignments_and_hidden_state(self):
        portal = {
            "quiz_folders": ["Uncategorized", "Course"],
            "hidden_quiz_folders": ["COURSE"],
        }
        registry = [
            {"id": 1, "title": "One", "html": "one.html", "folder": "course"},
            {"id": 2, "title": "Two", "html": "two.html", "folder": "COURSE"},
        ]
        with self.folder_state(portal, registry) as (
            client, _portal_path, _registry_path
        ):
            response = client.get("/library?view=hidden")
            self.assertEqual(200, response.status_code)
            html = response.get_data(as_text=True)
            response.close()

            self.assertEqual(1, html.count("<h2>Course"))
            self.assertNotIn("<h2>course", html)
            self.assertIn("One", html)
            self.assertIn("Two", html)
            self.assertIn('value="Course" selected', html)

    def test_rename_rejects_collision_with_assignment_only_identity(self):
        portal = {"quiz_folders": ["Uncategorized", "Course"]}
        registry = [
            {"id": 1, "html": "one.html", "folder": "Course"},
            {"id": 2, "html": "legacy.html", "folder": "Legacy Course"},
        ]
        with self.folder_state(portal, registry) as (
            client, portal_path, registry_path
        ):
            csrf_headers(client, "/library")
            original_portal = portal_path.read_bytes()
            original_registry = registry_path.read_bytes()
            response = self.post(
                client,
                "/rename_quiz_folder",
                data={"old_folder": "Course", "new_folder": "legacy course"},
            )
            self.assertEqual(302, response.status_code)
            response.close()
            self.assertEqual(original_portal, portal_path.read_bytes())
            self.assertEqual(original_registry, registry_path.read_bytes())

    def test_assignment_only_hide_promotes_then_case_insensitive_unhide_preserves_it(self):
        portal = {"quiz_folders": ["Uncategorized"], "unknown": 7}
        registry = [
            {"id": 1, "html": "legacy.html", "folder": "Legacy Course"}
        ]
        with self.folder_state(portal, registry) as (
            client, portal_path, registry_path
        ):
            original_registry = registry_path.read_bytes()
            hidden = self.post(
                client,
                "/set_quiz_folder_hidden",
                data={"folder": "LEGACY COURSE", "hidden": "1"},
            )
            self.assertEqual(302, hidden.status_code)
            hidden.close()
            self.assertEqual(
                ["Uncategorized", "Legacy Course"], dlms.get_quiz_folders()
            )
            self.assertEqual(
                ["Legacy Course"], dlms.get_hidden_quiz_folders()
            )

            unhidden = self.post(
                client,
                "/set_quiz_folder_hidden",
                data={"folder": "legacy course", "hidden": "0"},
            )
            self.assertEqual(302, unhidden.status_code)
            unhidden.close()
            self.assertEqual([], dlms.get_hidden_quiz_folders())
            saved_portal = json.loads(portal_path.read_text(encoding="utf-8"))
            self.assertEqual(7, saved_portal["unknown"])
            self.assertEqual(original_registry, registry_path.read_bytes())

    def test_assignment_only_rename_and_delete_use_the_same_identity(self):
        portal = {"quiz_folders": ["Uncategorized"], "unknown": "keep"}
        registry = [
            {"id": 1, "html": "legacy.html", "folder": "Legacy Course"}
        ]
        with self.folder_state(portal, registry) as (
            client, portal_path, registry_path
        ):
            renamed = self.post(
                client,
                "/rename_quiz_folder",
                data={
                    "old_folder": "legacy course",
                    "new_folder": "Renamed Legacy",
                },
            )
            self.assertEqual(302, renamed.status_code)
            renamed.close()
            self.assertEqual(
                "Renamed Legacy",
                json.loads(registry_path.read_text(encoding="utf-8"))[0][
                    "folder"
                ],
            )
            self.assertEqual(
                ["Uncategorized"],
                json.loads(portal_path.read_text(encoding="utf-8"))[
                    "quiz_folders"
                ],
            )

            deleted = self.post(
                client,
                "/delete_quiz_folder",
                data={"folder": "RENAMED LEGACY"},
            )
            self.assertEqual(302, deleted.status_code)
            deleted.close()
            self.assertEqual(
                "Uncategorized",
                json.loads(registry_path.read_text(encoding="utf-8"))[0][
                    "folder"
                ],
            )
            self.assertEqual(
                "keep",
                json.loads(portal_path.read_text(encoding="utf-8"))["unknown"],
            )

    def test_folder_reorder_resolves_spelling_promotes_legacy_and_ignores_unknown(self):
        portal = {
            "quiz_folders": ["Uncategorized", "First", "Second"],
            "hidden_quiz_folders": ["SECOND"],
        }
        registry = [
            {"id": 1, "html": "legacy.html", "folder": "Legacy Course"}
        ]
        with self.folder_state(portal, registry) as (
            client, _portal_path, registry_path
        ):
            original_registry = registry_path.read_bytes()
            response = self.post(
                client,
                "/save_folder_order",
                json_data={
                    "folders": [
                        "second", "Unknown Client Folder", "legacy course",
                        "FIRST",
                    ],
                    "view": "all",
                },
            )
            self.assertEqual(200, response.status_code)
            self.assertEqual({"status": "ok"}, response.get_json())
            response.close()
            self.assertEqual(
                ["Second", "Legacy Course", "First", "Uncategorized"],
                dlms.get_quiz_folders(),
            )
            self.assertEqual(["Second"], dlms.get_hidden_quiz_folders())
            self.assertEqual(original_registry, registry_path.read_bytes())

    def test_quiz_reorder_resolves_known_case_and_rejects_unknown_folder(self):
        portal = {"quiz_folders": ["Uncategorized", "Networking"]}
        registry = [
            {"id": 1, "html": "one.html", "folder": "networking"},
            {"id": 2, "html": "two.html", "folder": "NETWORKING"},
        ]
        with self.folder_state(portal, registry) as (
            client, _portal_path, registry_path
        ):
            known = self.post(
                client,
                "/save_quiz_order_in_folder",
                json_data={"folder": "nEtWoRkInG", "order": ["two.html"]},
            )
            self.assertEqual(200, known.status_code)
            known.close()
            self.assertEqual(
                ["two.html", "one.html"],
                [
                    quiz["html"]
                    for quiz in json.loads(
                        registry_path.read_text(encoding="utf-8")
                    )
                ],
            )

            before_unknown = registry_path.read_bytes()
            unknown = self.post(
                client,
                "/save_quiz_order_in_folder",
                json_data={"folder": "Unknown", "order": ["one.html"]},
            )
            self.assertEqual(400, unknown.status_code)
            self.assertEqual(
                {"status": "error", "error": "Unknown quiz folder"},
                unknown.get_json(),
            )
            unknown.close()
            self.assertEqual(before_unknown, registry_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
