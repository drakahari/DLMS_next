"""Failure-injection coverage for coordinated Quiz Library folder metadata."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services import quiz_mutations
from tests.csrf_test_utils import csrf_headers


class TrackingRLock:
    def __init__(self):
        self._lock = threading.RLock()
        self.depth = 0
        self.outer_entries = 0

    def __enter__(self):
        self._lock.acquire()
        if self.depth == 0:
            self.outer_entries += 1
        self.depth += 1
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.depth -= 1
        self._lock.release()

    @property
    def held(self):
        return self.depth > 0


class FolderStateHarness:
    def __init__(self, *, folders=None, hidden=None, registry=None):
        self.lock = TrackingRLock()
        self.portal = {
            "title": "Keep this title",
            "unknown_portal": {"preserve": True},
            "quiz_folders": list(
                folders or ["Uncategorized", "Course", "Empty"]
            ),
            "hidden_quiz_folders": list(hidden or ["Course"]),
        }
        self.registry = deepcopy(
            registry
            if registry is not None
            else [
                {
                    "id": 1,
                    "title": "Quiz",
                    "folder": "Course",
                    "unknown_quiz": {"preserve": True},
                }
            ]
        )
        self.events = []
        self.portal_save = None
        self.registry_save = None
        self.registry_load = None

    def _assert_locked(self):
        if not self.lock.held:
            raise AssertionError("folder state accessed outside registry_lock")

    def load_registry(self):
        self._assert_locked()
        self.events.append("load_registry")
        if self.registry_load is not None:
            return self.registry_load()
        return deepcopy(self.registry)

    def save_registry(self, registry):
        self._assert_locked()
        self.events.append("save_registry")
        if self.registry_save is not None:
            return self.registry_save(deepcopy(registry))
        self.registry = deepcopy(registry)

    def get_quiz_folders(self):
        self._assert_locked()
        self.events.append("get_folders")
        return list(self.portal["quiz_folders"])

    def get_hidden_quiz_folders(self, folders):
        self._assert_locked()
        self.events.append("get_hidden")
        configured = {folder.lower(): folder for folder in folders}
        return [
            configured[folder.lower()]
            for folder in self.portal["hidden_quiz_folders"]
            if folder.lower() in configured
            and folder.lower() != "uncategorized"
        ]

    def save_quiz_folder_state(self, folders, hidden):
        self._assert_locked()
        self.events.append("save_portal")
        if self.portal_save is not None:
            return self.portal_save(list(folders), list(hidden))
        self.portal["quiz_folders"] = list(folders)
        self.portal["hidden_quiz_folders"] = list(hidden)

    def dependencies(self):
        return {
            "registry_lock": self.lock,
            "load_registry": self.load_registry,
            "save_registry": self.save_registry,
            "get_quiz_folders": self.get_quiz_folders,
            "get_hidden_quiz_folders": self.get_hidden_quiz_folders,
            "save_quiz_folder_state": self.save_quiz_folder_state,
            "print_message": lambda *_args: None,
        }


class QuizFolderCoordinationTests(unittest.TestCase):
    def test_rename_computes_then_publishes_portal_before_registry_under_one_lock(self):
        state = FolderStateHarness()

        changed = quiz_mutations.rename_quiz_folder_metadata(
            "course", "Renamed", **state.dependencies()
        )

        self.assertTrue(changed)
        writes = [event for event in state.events if event.startswith("save_")]
        self.assertEqual(["save_portal", "save_registry"], writes)
        self.assertEqual(1, state.lock.outer_entries)
        self.assertEqual(
            ["Uncategorized", "Renamed", "Empty"],
            state.portal["quiz_folders"],
        )
        self.assertEqual(["Renamed"], state.portal["hidden_quiz_folders"])
        self.assertEqual("Renamed", state.registry[0]["folder"])
        self.assertEqual({"preserve": True}, state.registry[0]["unknown_quiz"])
        self.assertEqual({"preserve": True}, state.portal["unknown_portal"])

    def test_portal_failure_does_not_attempt_registry_and_changes_neither_state(self):
        state = FolderStateHarness()
        original_portal = deepcopy(state.portal)
        original_registry = deepcopy(state.registry)

        def fail_portal(_folders, _hidden):
            raise OSError("portal unavailable")

        state.portal_save = fail_portal
        with self.assertRaisesRegex(OSError, "portal unavailable"):
            quiz_mutations.rename_quiz_folder_metadata(
                "Course", "Renamed", **state.dependencies()
            )

        self.assertNotIn("save_registry", state.events)
        self.assertEqual(original_portal, state.portal)
        self.assertEqual(original_registry, state.registry)

    def test_registry_load_failure_happens_before_any_portal_access_or_write(self):
        state = FolderStateHarness()
        original_portal = deepcopy(state.portal)

        def fail_load():
            raise RuntimeError("registry cannot be normalized")

        state.registry_load = fail_load
        with self.assertRaisesRegex(RuntimeError, "registry cannot be normalized"):
            quiz_mutations.delete_quiz_folder_metadata(
                "Course", **state.dependencies()
            )

        self.assertEqual(["load_registry"], state.events)
        self.assertEqual(original_portal, state.portal)

    def test_registry_normalization_failure_happens_before_portal_write(self):
        state = FolderStateHarness(registry=["not a quiz object"])
        original_portal = deepcopy(state.portal)

        with self.assertRaises(AttributeError):
            quiz_mutations.rename_quiz_folder_metadata(
                "Course", "Renamed", **state.dependencies()
            )

        self.assertEqual(["load_registry"], state.events)
        self.assertEqual(original_portal, state.portal)

    def test_registry_failure_restores_portal_when_registry_is_still_original(self):
        state = FolderStateHarness()
        original_portal = deepcopy(state.portal)
        original_registry = deepcopy(state.registry)

        def fail_registry(_registry):
            raise OSError("registry unavailable")

        state.registry_save = fail_registry
        with self.assertRaisesRegex(OSError, "registry unavailable"):
            quiz_mutations.rename_quiz_folder_metadata(
                "Course", "Renamed", **state.dependencies()
            )

        self.assertEqual(original_portal, state.portal)
        self.assertEqual(original_registry, state.registry)
        self.assertEqual(
            ["save_portal", "save_registry", "save_portal"],
            [event for event in state.events if event.startswith("save_")],
        )

    def test_empty_folder_delete_failure_restores_portal(self):
        state = FolderStateHarness()
        original_portal = deepcopy(state.portal)

        def fail_registry(_registry):
            raise OSError("registry unavailable")

        state.registry_save = fail_registry

        with self.assertRaisesRegex(OSError, "registry unavailable"):
            quiz_mutations.delete_quiz_folder_metadata(
                "Empty", **state.dependencies()
            )

        self.assertEqual(original_portal, state.portal)
        self.assertIn("Empty", state.portal["quiz_folders"])

    def test_assignment_only_legacy_folder_rename_and_delete_are_supported(self):
        legacy = [{"id": 1, "title": "Legacy", "folder": "Legacy Course"}]
        renamed = FolderStateHarness(
            folders=["Uncategorized"], hidden=[], registry=legacy
        )
        quiz_mutations.rename_quiz_folder_metadata(
            "legacy course", "Renamed Legacy", **renamed.dependencies()
        )
        self.assertEqual(["Uncategorized"], renamed.portal["quiz_folders"])
        self.assertEqual("Renamed Legacy", renamed.registry[0]["folder"])

        deleted = FolderStateHarness(
            folders=["Uncategorized"], hidden=[], registry=legacy
        )
        quiz_mutations.delete_quiz_folder_metadata(
            "LEGACY COURSE", **deleted.dependencies()
        )
        self.assertEqual(["Uncategorized"], deleted.portal["quiz_folders"])
        self.assertEqual("Uncategorized", deleted.registry[0]["folder"])

    def test_case_insensitive_destination_collision_remains_a_no_op(self):
        state = FolderStateHarness(
            folders=["Uncategorized", "Course", "Destination"], hidden=[]
        )
        original_portal = deepcopy(state.portal)
        original_registry = deepcopy(state.registry)

        changed = quiz_mutations.rename_quiz_folder_metadata(
            "course", "dEsTiNaTiOn", **state.dependencies()
        )

        self.assertFalse(changed)
        self.assertFalse(any(event.startswith("save_") for event in state.events))
        self.assertEqual(original_portal, state.portal)
        self.assertEqual(original_registry, state.registry)

    def test_reported_failure_after_target_registry_is_durable_keeps_target_portal(self):
        state = FolderStateHarness()

        def publish_then_fail(registry):
            state.registry = deepcopy(registry)
            raise OSError("late registry failure")

        state.registry_save = publish_then_fail
        with self.assertRaisesRegex(OSError, "late registry failure"):
            quiz_mutations.rename_quiz_folder_metadata(
                "Course", "Renamed", **state.dependencies()
            )

        self.assertIn("Renamed", state.portal["quiz_folders"])
        self.assertEqual("Renamed", state.registry[0]["folder"])
        self.assertEqual(1, state.events.count("save_portal"))

    def test_unexpected_third_registry_state_is_not_blindly_overwritten(self):
        state = FolderStateHarness()
        third_state = [{"id": 99, "title": "Concurrent", "folder": "Other"}]

        def publish_third_then_fail(_registry):
            state.registry = deepcopy(third_state)
            raise OSError("registry conflict")

        state.registry_save = publish_third_then_fail
        with self.assertRaises(quiz_mutations.FolderMetadataStateConflictError):
            quiz_mutations.rename_quiz_folder_metadata(
                "Course", "Renamed", **state.dependencies()
            )

        self.assertEqual(third_state, state.registry)
        self.assertIn("Renamed", state.portal["quiz_folders"])
        self.assertEqual(1, state.events.count("save_portal"))

    def test_unreadable_durable_registry_fails_closed_without_portal_rollback(self):
        state = FolderStateHarness()
        load_count = 0

        def load_then_fail():
            nonlocal load_count
            load_count += 1
            if load_count == 1:
                return deepcopy(state.registry)
            raise OSError("durable registry unreadable")

        state.registry_load = load_then_fail

        def fail_registry(_registry):
            raise OSError("registry unavailable")

        state.registry_save = fail_registry

        with self.assertRaises(quiz_mutations.FolderMetadataStateUnknownError):
            quiz_mutations.rename_quiz_folder_metadata(
                "Course", "Renamed", **state.dependencies()
            )

        self.assertIn("Renamed", state.portal["quiz_folders"])
        self.assertEqual("Course", state.registry[0]["folder"])
        self.assertEqual(1, state.events.count("save_portal"))

    def test_rollback_failure_raises_distinct_error_and_keeps_valid_states(self):
        state = FolderStateHarness()
        portal_save_count = 0

        def save_portal(folders, hidden):
            nonlocal portal_save_count
            portal_save_count += 1
            if portal_save_count == 2:
                raise OSError("rollback unavailable")
            state.portal["quiz_folders"] = list(folders)
            state.portal["hidden_quiz_folders"] = list(hidden)

        state.portal_save = save_portal

        def fail_registry(_registry):
            raise OSError("registry unavailable")

        state.registry_save = fail_registry

        with self.assertRaises(
            quiz_mutations.FolderMetadataRollbackIncompleteError
        ):
            quiz_mutations.rename_quiz_folder_metadata(
                "Course", "Renamed", **state.dependencies()
            )

        json.dumps(state.portal)
        json.dumps(state.registry)
        self.assertIn("Renamed", state.portal["quiz_folders"])
        self.assertEqual("Course", state.registry[0]["folder"])

    def test_compensation_preserves_unrelated_portal_keys_on_disk(self):
        with tempfile.TemporaryDirectory(
            prefix="dlms-folder-compensation-"
        ) as directory:
            config = Path(directory) / "config"
            portal_path = config / "portal.json"
            registry_path = config / "quizzes.json"
            config.mkdir(parents=True)
            portal_path.write_text(
                json.dumps(
                    {
                        "title": "Preserve me",
                        "unknown": {"nested": True},
                        "quiz_folders": ["Uncategorized", "Course"],
                        "hidden_quiz_folders": ["Course"],
                    }
                ),
                encoding="utf-8",
            )
            registry_path.write_text(
                json.dumps(
                    [{"id": 1, "folder": "Course", "unknown": "keep"}]
                ),
                encoding="utf-8",
            )

            with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal_path)), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", str(registry_path)), \
                    mock.patch.object(
                        dlms,
                        "save_registry",
                        side_effect=OSError("registry unavailable"),
                    ):
                with self.assertRaisesRegex(OSError, "registry unavailable"):
                    dlms._rename_quiz_folder_metadata("Course", "Renamed")

            portal = json.loads(portal_path.read_text(encoding="utf-8"))
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual("Preserve me", portal["title"])
            self.assertEqual({"nested": True}, portal["unknown"])
            self.assertEqual(["Uncategorized", "Course"], portal["quiz_folders"])
            self.assertEqual(["Course"], portal["hidden_quiz_folders"])
            self.assertEqual(
                [{"id": 1, "folder": "Course", "unknown": "keep"}],
                registry,
            )

    def test_folder_only_routes_use_the_live_registry_lock(self):
        with tempfile.TemporaryDirectory(prefix="dlms-folder-route-lock-") as directory:
            config = Path(directory) / "config"
            portal_path = config / "portal.json"
            registry_path = config / "quizzes.json"
            config.mkdir(parents=True)
            portal_path.write_text(
                json.dumps(
                    {
                        "quiz_folders": ["Uncategorized", "Course", "Other"],
                        "hidden_quiz_folders": [],
                    }
                ),
                encoding="utf-8",
            )
            registry_path.write_text("[]", encoding="utf-8")
            tracking_lock = TrackingRLock()

            with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal_path)), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", str(registry_path)), \
                    mock.patch.object(dlms, "registry_lock", tracking_lock):
                client = dlms.app.test_client()
                requests = [
                    ("/add_quiz_folder", {"folder": "Added"}, False),
                    (
                        "/set_quiz_folder_hidden",
                        {"folder": "Course", "hidden": "1"},
                        False,
                    ),
                    (
                        "/save_folder_order",
                        {"folders": ["Other", "Course", "Added"]},
                        True,
                    ),
                    (
                        "/move_quiz_folder",
                        {"id": "999", "folder": "Other"},
                        False,
                    ),
                    (
                        "/save_quiz_order_in_folder",
                        {"folder": "Other", "order": []},
                        True,
                    ),
                    ("/save_order", {"order": []}, True),
                    ("/toggle_hidden", {"id": "999"}, False),
                ]
                for path, data, is_json in requests:
                    headers = csrf_headers(client, "/library")
                    before = tracking_lock.outer_entries
                    response = client.post(
                        path,
                        json=data if is_json else None,
                        data=None if is_json else data,
                        headers=headers,
                    )
                    self.assertIn(response.status_code, {200, 302})
                    self.assertEqual(before + 1, tracking_lock.outer_entries)

    def test_coordinator_blocks_another_folder_state_writer_until_completion(self):
        state = FolderStateHarness()
        registry_write_started = threading.Event()
        allow_registry_write = threading.Event()
        competing_writer_entered = threading.Event()
        errors = []

        def delayed_registry_save(registry):
            registry_write_started.set()
            if not allow_registry_write.wait(2):
                raise TimeoutError("test did not release registry write")
            state.registry = deepcopy(registry)

        state.registry_save = delayed_registry_save

        def rename():
            try:
                quiz_mutations.rename_quiz_folder_metadata(
                    "Course", "Renamed", **state.dependencies()
                )
            except Exception as exc:
                errors.append(exc)

        def competing_writer():
            with state.lock:
                competing_writer_entered.set()

        rename_thread = threading.Thread(target=rename)
        rename_thread.start()
        self.assertTrue(registry_write_started.wait(1))
        writer_thread = threading.Thread(target=competing_writer)
        writer_thread.start()
        self.assertFalse(competing_writer_entered.wait(0.1))
        allow_registry_write.set()
        rename_thread.join(2)
        writer_thread.join(2)

        self.assertFalse(rename_thread.is_alive())
        self.assertFalse(writer_thread.is_alive())
        self.assertEqual([], errors)
        self.assertTrue(competing_writer_entered.is_set())

    def test_successful_routes_preserve_serialized_folder_and_registry_semantics(self):
        with tempfile.TemporaryDirectory(prefix="dlms-folder-success-") as directory:
            config = Path(directory) / "config"
            portal_path = config / "portal.json"
            registry_path = config / "quizzes.json"
            config.mkdir(parents=True)
            portal_path.write_text(
                json.dumps(
                    {
                        "title": "Keep",
                        "unknown": {"preserve": True},
                        "quiz_folders": ["Uncategorized", "Course"],
                        "hidden_quiz_folders": ["course"],
                    },
                    indent=3,
                ),
                encoding="utf-8",
            )
            registry_path.write_text(
                json.dumps(
                    [
                        {"id": 1, "folder": "COURSE", "unknown": 7},
                        {"id": 2, "title": "Legacy blank"},
                    ],
                    indent=3,
                ),
                encoding="utf-8",
            )

            with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal_path)), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", str(registry_path)):
                client = dlms.app.test_client()
                response = client.post(
                    "/rename_quiz_folder",
                    data={"old_folder": "course", "new_folder": "Renamed"},
                    headers=csrf_headers(client, "/library"),
                )

            self.assertEqual(302, response.status_code)
            portal = json.loads(portal_path.read_text(encoding="utf-8"))
            self.assertEqual("Keep", portal["title"])
            self.assertEqual({"preserve": True}, portal["unknown"])
            self.assertEqual(
                ["Uncategorized", "Renamed"], portal["quiz_folders"]
            )
            self.assertEqual(["Renamed"], portal["hidden_quiz_folders"])
            self.assertEqual(
                [
                    {"id": 1, "folder": "Renamed", "unknown": 7},
                    {
                        "id": 2,
                        "title": "Legacy blank",
                        "folder": "Uncategorized",
                    },
                ],
                json.loads(registry_path.read_text(encoding="utf-8")),
            )


if __name__ == "__main__":
    unittest.main()
