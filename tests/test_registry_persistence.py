"""Characterization coverage for Quiz and Law registry persistence."""

import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.persistence import registries


BUILT_IN_LAW_FOLDERS = [
    "Torts",
    "Contracts",
    "Civil Procedure",
    "Criminal Law",
    "Property",
    "Constitutional Law",
    "Legal Writing",
]


class TrackingRLock:
    def __init__(self):
        self._lock = threading.RLock()
        self.entries = 0

    def __enter__(self):
        self._lock.acquire()
        self.entries += 1
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._lock.release()


class RegistryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-registries-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.quiz_registry = self.root / "config" / "quizzes.json"
        self.law_registry = self.root / "config" / "law.json"

    def test_missing_empty_and_null_quiz_registries_load_as_empty(self):
        with mock.patch.object(dlms, "QUIZ_REGISTRY", str(self.quiz_registry)):
            self.assertEqual([], dlms.load_registry())

            self.quiz_registry.parent.mkdir(parents=True)
            for payload in ([], None):
                with self.subTest(payload=payload):
                    self.quiz_registry.write_text(json.dumps(payload), encoding="utf-8")
                    self.assertEqual([], dlms.load_registry())

    def test_quiz_load_preserves_order_and_legacy_fields_without_rewriting(self):
        registry = [
            {
                "id": "legacy-two",
                "title": "Second",
                "folder": "Archive",
                "legacy_metadata": {"keep": True},
            },
            {"id": 1, "title": "First", "custom_field": "preserve"},
        ]
        original = json.dumps(registry, indent=3)
        self.quiz_registry.parent.mkdir(parents=True)
        self.quiz_registry.write_text(original, encoding="utf-8")

        with mock.patch.object(dlms, "QUIZ_REGISTRY", str(self.quiz_registry)):
            loaded = dlms.load_registry()

        self.assertEqual(registry, loaded)
        self.assertEqual(original, self.quiz_registry.read_text(encoding="utf-8"))

    def test_malformed_quiz_registry_raises_without_rewriting(self):
        self.quiz_registry.parent.mkdir(parents=True)
        malformed = b'{"registry":"must be a list"}'
        self.quiz_registry.write_bytes(malformed)

        with mock.patch.object(dlms, "QUIZ_REGISTRY", str(self.quiz_registry)):
            with self.assertRaisesRegex(
                RuntimeError, "Quiz registry must contain a JSON list"
            ):
                dlms.load_registry()

        self.assertEqual(malformed, self.quiz_registry.read_bytes())

    def test_normalize_quiz_folders_preserves_order_and_metadata(self):
        registry = [
            {"id": 3, "title": "Third", "folder": "  Existing  ", "extra": 1},
            {"id": 1, "title": "First", "folder": "", "extra": 2},
            {"id": 2, "title": "Second", "extra": 3},
        ]

        with mock.patch.object(dlms, "QUIZ_REGISTRY", str(self.quiz_registry)):
            normalized = dlms.normalize_quiz_folders(registry)

        self.assertIs(registry, normalized)
        self.assertEqual([3, 1, 2], [entry["id"] for entry in normalized])
        self.assertEqual("  Existing  ", normalized[0]["folder"])
        self.assertEqual("Uncategorized", normalized[1]["folder"])
        self.assertEqual("Uncategorized", normalized[2]["folder"])
        self.assertEqual([1, 2, 3], [entry["extra"] for entry in normalized])
        self.assertEqual(
            normalized,
            json.loads(self.quiz_registry.read_text(encoding="utf-8")),
        )

    def test_quiz_save_preserves_order_and_four_space_json_format(self):
        registry = [
            {"id": 2, "title": "Second", "unknown": "keep"},
            {"id": 1, "title": "First"},
        ]

        with mock.patch.object(dlms, "QUIZ_REGISTRY", str(self.quiz_registry)):
            dlms.save_registry(registry)

        serialized = self.quiz_registry.read_text(encoding="utf-8")
        self.assertTrue(serialized.startswith('[\n    {\n        "id": 2,'))
        self.assertFalse(serialized.endswith("\n"))
        self.assertEqual(registry, json.loads(serialized))

    def test_quiz_save_rejects_non_list_root_with_existing_error(self):
        with mock.patch.object(dlms, "QUIZ_REGISTRY", str(self.quiz_registry)):
            with self.assertRaisesRegex(
                ValueError, "Quiz registry must contain a JSON list"
            ):
                dlms.save_registry({"quiz": "not a list"})

        self.assertFalse(self.quiz_registry.exists())

    def test_quiz_operations_use_the_live_app_registry_lock(self):
        self.quiz_registry.parent.mkdir(parents=True)
        self.quiz_registry.write_text("[]", encoding="utf-8")
        replacement_lock = TrackingRLock()

        with mock.patch.object(dlms, "QUIZ_REGISTRY", str(self.quiz_registry)), \
                mock.patch.object(dlms, "registry_lock", replacement_lock):
            dlms.load_registry()
            dlms.save_registry([])
            dlms.normalize_quiz_folders([])

        self.assertEqual(3, replacement_lock.entries)

    def test_app_atomic_write_patch_intercepts_quiz_registry_save(self):
        payload = [{"id": 2, "title": "Second"}, {"id": 1, "title": "First"}]

        with mock.patch.object(dlms, "QUIZ_REGISTRY", str(self.quiz_registry)), \
                mock.patch.object(dlms, "_atomic_write_json") as atomic_write:
            dlms.save_registry(payload)

        atomic_write.assert_called_once_with(
            str(self.quiz_registry),
            payload,
            indent=4,
            expected_type=list,
        )

    def test_registry_repository_does_not_own_an_independent_lock(self):
        self.assertFalse(hasattr(registries, "registry_lock"))

    def test_missing_law_registry_creates_exact_defaults_at_live_path(self):
        with mock.patch.object(dlms, "LAW_REGISTRY", str(self.law_registry)):
            loaded = dlms.load_law_registry()

        expected = {"version": "1", "cases": [], "folders": BUILT_IN_LAW_FOLDERS}
        self.assertEqual(expected, loaded)
        self.assertEqual(
            expected,
            json.loads(self.law_registry.read_text(encoding="utf-8")),
        )

    def test_empty_law_registry_uses_defaults_without_rewriting(self):
        self.law_registry.parent.mkdir(parents=True)
        self.law_registry.write_text("{}", encoding="utf-8")

        with mock.patch.object(dlms, "LAW_REGISTRY", str(self.law_registry)):
            loaded = dlms.load_law_registry()

        self.assertEqual(
            {"version": "1", "cases": [], "folders": BUILT_IN_LAW_FOLDERS},
            loaded,
        )
        self.assertEqual("{}", self.law_registry.read_text(encoding="utf-8"))

    def test_law_load_preserves_order_unknown_fields_and_legacy_file(self):
        legacy = {
            "cases": [
                {"id": "second", "unknown_case_field": "keep"},
                {"id": "first"},
            ],
            "folders": ["Evidence", "Torts"],
            "unknown_registry_field": {"keep": True},
        }
        original = json.dumps(legacy, indent=3)
        self.law_registry.parent.mkdir(parents=True)
        self.law_registry.write_text(original, encoding="utf-8")

        with mock.patch.object(dlms, "LAW_REGISTRY", str(self.law_registry)):
            loaded = dlms.load_law_registry()

        self.assertEqual("1", loaded["version"])
        self.assertEqual(legacy["cases"], loaded["cases"])
        self.assertEqual(legacy["folders"], loaded["folders"])
        self.assertEqual(legacy["unknown_registry_field"], loaded["unknown_registry_field"])
        self.assertEqual(original, self.law_registry.read_text(encoding="utf-8"))

    def test_app_atomic_write_patch_intercepts_law_registry_save(self):
        payload = {
            "version": "legacy",
            "cases": [{"id": "case-one", "unknown": "keep"}],
            "folders": ["Evidence"],
            "unknown_registry_field": True,
        }

        with mock.patch.object(dlms, "LAW_REGISTRY", str(self.law_registry)), \
                mock.patch.object(dlms, "_atomic_write_json") as atomic_write:
            dlms.save_law_registry(payload)

        atomic_write.assert_called_once_with(
            str(self.law_registry), payload, expected_type=dict
        )


if __name__ == "__main__":
    unittest.main()
