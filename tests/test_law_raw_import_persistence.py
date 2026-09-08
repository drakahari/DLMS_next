"""Durability and collision regression coverage for saved Law raw imports."""

from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.persistence import json_files
from tests.csrf_test_utils import csrf_token


RAW_PACKET = """Sources Used
Official reporter citation.

1. Case Brief
Full case name and citation: Hadley v. Baxendale
Facts and holding.
"""


class FrozenDateTime:
    @classmethod
    def now(cls):
        return datetime(2026, 9, 8, 14, 5, 7)

    @classmethod
    def fromtimestamp(cls, timestamp):
        return datetime.fromtimestamp(timestamp)


class LawRawImportPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-law-raw-import-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.imports = self.root / "law" / "imports"
        self.cases = self.root / "law" / "cases"
        self.registry = self.root / "config" / "law.json"
        self.imports.mkdir(parents=True)
        self.cases.mkdir(parents=True)
        self.registry.parent.mkdir(parents=True)
        self.paths = mock.patch.multiple(
            dlms,
            LAW_IMPORTS_FOLDER=str(self.imports),
            LAW_CASES_FOLDER=str(self.cases),
            LAW_REGISTRY=str(self.registry),
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def test_successful_atomic_save_preserves_exact_unicode_and_newlines(self):
        raw_packet = "Café v. Thé\n第一行\r\nFinal line\n"

        with mock.patch.object(dlms, "datetime", FrozenDateTime):
            saved = dlms.save_law_raw_packet(raw_packet, "cafe_v_the")

        self.assertEqual(
            "law_import_20260908_140507_cafe_v_the.txt", saved
        )
        self.assertEqual(
            raw_packet,
            (self.imports / saved).read_text(encoding="utf-8", newline=""),
        )
        self.assertEqual([], list(self.imports.glob(".*.tmp")))

    def test_atomic_write_and_replace_failures_preserve_target_and_clean_temp(self):
        for failure_point in ("fsync", "replace"):
            with self.subTest(failure_point=failure_point):
                target = self.imports / f"existing-{failure_point}.txt"
                target.write_text("existing valid packet", encoding="utf-8")
                patcher = mock.patch.object(
                    json_files.os,
                    failure_point,
                    side_effect=OSError(f"{failure_point} blocked"),
                )

                with patcher:
                    with self.assertRaisesRegex(
                        OSError, f"{failure_point} blocked"
                    ):
                        dlms._atomic_write_text(
                            str(target), "replacement packet"
                        )

                self.assertEqual(
                    "existing valid packet", target.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    [], list(self.imports.glob(f".{target.name}.*.tmp"))
                )

    def test_atomic_writer_syncs_file_and_containing_directory(self):
        target = self.imports / "durable.txt"
        real_fsync = os.fsync
        directory_sync = mock.Mock()

        with mock.patch.object(
            json_files.os, "fsync", side_effect=real_fsync
        ) as file_sync:
            json_files._atomic_write_text(
                str(target),
                "durable packet",
                fsync_directory=directory_sync,
            )

        file_sync.assert_called_once()
        directory_sync.assert_called_once_with(str(self.imports))
        self.assertEqual("durable packet", target.read_text(encoding="utf-8"))

    def test_same_slug_and_second_allocate_distinct_legacy_style_names(self):
        with mock.patch.object(dlms, "datetime", FrozenDateTime):
            first = dlms.save_law_raw_packet("first packet", "hadley_v_baxendale")
            second = dlms.save_law_raw_packet("second packet", "hadley_v_baxendale")

        self.assertEqual(
            "law_import_20260908_140507_hadley_v_baxendale.txt", first
        )
        self.assertEqual(
            "law_import_20260908_140508_hadley_v_baxendale.txt", second
        )
        self.assertNotEqual(first, second)
        self.assertEqual("first packet", (self.imports / first).read_text())
        self.assertEqual("second packet", (self.imports / second).read_text())
        self.assertEqual(
            "hadley_v_baxendale",
            dlms.extract_law_slug_from_import_filename(second),
        )

    def test_concurrent_same_second_saves_are_serialized_without_overwrite(self):
        saved = []
        errors = []
        start = threading.Barrier(3)

        def save_packet(content):
            try:
                start.wait(timeout=2)
                saved.append(dlms.save_law_raw_packet(content, "concurrent"))
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(dlms, "datetime", FrozenDateTime):
            threads = [
                threading.Thread(target=save_packet, args=(content,))
                for content in ("first concurrent packet", "second concurrent packet")
            ]
            for thread in threads:
                thread.start()
            start.wait(timeout=2)
            for thread in threads:
                thread.join(timeout=2)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([], errors)
        self.assertEqual(2, len(set(saved)))
        contents = {(self.imports / filename).read_text() for filename in saved}
        self.assertEqual(
            {"first concurrent packet", "second concurrent packet"}, contents
        )

    def test_collision_allocation_remains_safe_after_hostile_slug_sanitization(self):
        hostile_slug = '../../Torts ? "quoted" & résumé'
        with mock.patch.object(dlms, "datetime", FrozenDateTime):
            first = dlms.save_law_raw_packet("one", hostile_slug)
            second = dlms.save_law_raw_packet("two", hostile_slug)

        self.assertNotEqual(first, second)
        for filename, expected in ((first, "one"), (second, "two")):
            with self.subTest(filename=filename):
                self.assertEqual(filename, os.path.basename(filename))
                self.assertEqual(filename, dlms.safe_law_import_filename(filename))
                self.assertEqual(expected, (self.imports / filename).read_text())
                self.assertEqual(self.imports, (self.imports / filename).parent)

    def test_collision_filename_remains_linked_to_pending_and_case_metadata(self):
        registry = dlms.load_law_registry()
        registry["pending_case_workflow"] = {
            "case_name": "Hadley Collision Review",
            "case_slug": "hadley_v_baxendale",
            "course": "Contracts",
            "created_at": "2026-09-08T14:05:07",
        }
        dlms.save_law_registry(registry)

        with mock.patch.object(dlms, "datetime", FrozenDateTime):
            dlms.save_law_raw_packet("first", "hadley_v_baxendale")
            second = dlms.save_law_raw_packet(
                RAW_PACKET, "hadley_v_baxendale"
            )
            client = dlms.app.test_client()
            response = client.post(
                f"/law/imports/{second}/create_case",
                data={
                    "csrf_token": csrf_token(
                        client, f"/law/imports/{second}"
                    )
                },
                follow_redirects=False,
            )

        self.assertEqual(302, response.status_code)
        saved_registry = dlms.load_law_registry()
        self.assertEqual(1, len(saved_registry["cases"]))
        case = saved_registry["cases"][0]
        self.assertEqual(second, case["source_import"])
        self.assertEqual("Hadley Collision Review", case["title"])
        self.assertEqual("Contracts", case["course"])
        case_data = json.loads(
            Path(dlms.LAW_CASES_FOLDER, case["file"]).read_text(encoding="utf-8")
        )
        self.assertEqual(second, case_data["source_import"])

    def test_existing_saved_import_remains_readable(self):
        existing = self.imports / "law_import_20200101_000000_legacy.txt"
        existing.write_text("Legacy packet Ω\n", encoding="utf-8")

        self.assertEqual(
            "Legacy packet Ω\n",
            dlms._law_service.load_law_raw_packet(str(existing)),
        )


if __name__ == "__main__":
    unittest.main()
