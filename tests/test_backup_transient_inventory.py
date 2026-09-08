"""Portable-backup coverage for repository-owned persistence temp files."""

import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from dlms.persistence import json_files
from dlms.services import backups


class _AtomicOsProxy:
    def __init__(self, replace):
        self._replace = replace

    def __getattr__(self, name):
        return getattr(os, name)

    def replace(self, source, target):
        return self._replace(source, target)


class BackupTransientInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="dlms-backup-transient-inventory-"
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.backup_folder = self.root / "backups"
        self.backup_folder.mkdir()

    @staticmethod
    def _rel_is_excluded(rel_path):
        return backups.backup_rel_is_excluded(
            rel_path,
            data_root_marker=".dlms-data-root",
            excluded_top_level={
                ".restore_operations", "backups", "uploads",
                "content_pack_staging",
            },
        )

    def _inventory(self):
        return backups.backup_file_inventory(
            str(self.root),
            str(self.root / "results.db"),
            rel_is_excluded=self._rel_is_excluded,
        )

    def _create_backup(self, label="transient-test"):
        return backups.create_dlms_backup(
            label,
            ensure_runtime_data_dirs=lambda: None,
            backup_folder=str(self.backup_folder),
            app_data_dir=str(self.root),
            db_path=str(self.root / "results.db"),
            app_version="test",
            backup_schema_version=1,
            backup_manifest="DLMS_BACKUP_MANIFEST.json",
            backup_data_prefix="DLMS_DATA/",
            file_inventory=self._inventory,
            summary=lambda: {"quizzes": 0},
            now=lambda: datetime(2026, 9, 8, 12, 0, 0),
            platform="test",
        )

    def test_inventory_and_manifest_exclude_only_repository_atomic_temps(self):
        files = {
            "config/portal.json": b'{"title":"durable"}',
            "config/.portal.json.abcdefgh.tmp": b'{"title":"transient"}',
            "config/portal.json.corrupt": b"{malformed",
            "config/.portal.json.corrupt-1234_ab5.tmp": b"{malformed",
            "law/imports/law_import_20260908_120000_torts.txt": b"durable law packet",
            "law/imports/.law_import_20260908_120000_torts.txt.a1b2c3d4.tmp": b"transient law packet",
            "config/notes.tmp": b"legitimate generic temporary suffix",
            "config/.portal.json.manual.tmp": b"legitimate non-tempfile token",
            "content_packs/example/.dataset.json.abcdefgh.tmp": b"legitimate pack file",
        }
        for relative, content in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        inventory = {relative for _, relative in self._inventory()}
        self.assertNotIn("config/.portal.json.abcdefgh.tmp", inventory)
        self.assertNotIn("config/.portal.json.corrupt-1234_ab5.tmp", inventory)
        self.assertNotIn(
            "law/imports/.law_import_20260908_120000_torts.txt.a1b2c3d4.tmp",
            inventory,
        )
        expected = set(files) - {
            "config/.portal.json.abcdefgh.tmp",
            "config/.portal.json.corrupt-1234_ab5.tmp",
            "law/imports/.law_import_20260908_120000_torts.txt.a1b2c3d4.tmp",
        }
        self.assertEqual(expected, inventory)

        backup_path, manifest = self._create_backup()
        expected_members = {
            "DLMS_BACKUP_MANIFEST.json",
            *(f"DLMS_DATA/{relative}" for relative in expected),
        }
        self.assertEqual(len(expected), manifest["file_count"])
        self.assertEqual(
            sum(len(files[relative]) for relative in expected),
            manifest["total_uncompressed_bytes"],
        )
        self.assertEqual(
            sorted({relative.split("/", 1)[0] for relative in expected}),
            manifest["included_roots"],
        )
        with zipfile.ZipFile(backup_path) as archive:
            self.assertEqual(expected_members, set(archive.namelist()))

        report = backups.validate_dlms_backup(
            backup_path,
            backup_manifest="DLMS_BACKUP_MANIFEST.json",
            backup_data_prefix="DLMS_DATA/",
            backup_schema_version=1,
            max_files=100,
            max_uncompressed=1024 * 1024,
            max_compressed=1024 * 1024,
            max_single_file=1024 * 1024,
            max_compression_ratio=1000,
            ratio_min_uncompressed=1024 * 1024,
            rel_is_excluded=self._rel_is_excluded,
        )
        self.assertEqual(len(expected), report["file_count"])

    def test_backup_racing_atomic_replace_archives_prior_durable_json(self):
        config = self.root / "config"
        config.mkdir()
        portal = config / "portal.json"
        prior = {"title": "Prior durable state"}
        target = {"title": "Final durable state"}
        portal.write_text(json.dumps(prior), encoding="utf-8")
        captured = {}

        def replace_after_backup(source, destination):
            captured["temp_name"] = Path(source).name
            captured["backup"] = self._create_backup("during-replace")[0]
            os.replace(source, destination)

        json_files._atomic_write_json(
            portal,
            target,
            expected_type=dict,
            os_module=_AtomicOsProxy(replace_after_backup),
        )

        self.assertEqual(
            "portal.json",
            json_files._atomic_persistence_target_name(captured["temp_name"]),
        )
        with zipfile.ZipFile(captured["backup"]) as archive:
            names = archive.namelist()
            self.assertEqual(
                prior,
                json.loads(archive.read("DLMS_DATA/config/portal.json")),
            )
            self.assertFalse(any(name.endswith(".tmp") for name in names))
        self.assertEqual(target, json.loads(portal.read_text(encoding="utf-8")))

    def test_restore_validation_compatibility_for_existing_archives_is_unchanged(self):
        archive_path = self.root / "artifact.zip"
        manifest = {
            "schema_version": 1,
            "kind": "dlms-portable-backup",
            "file_count": 1,
        }
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(
                "DLMS_BACKUP_MANIFEST.json",
                json.dumps(manifest),
            )
            archive.writestr(
                "DLMS_DATA/config/.portal.json.abcdefgh.tmp",
                "{}",
            )

        report = backups.validate_dlms_backup(
            archive_path,
            backup_manifest="DLMS_BACKUP_MANIFEST.json",
            backup_data_prefix="DLMS_DATA/",
            backup_schema_version=1,
            max_files=100,
            max_uncompressed=1024 * 1024,
            max_compressed=1024 * 1024,
            max_single_file=1024 * 1024,
            max_compression_ratio=1000,
            ratio_min_uncompressed=1024 * 1024,
            rel_is_excluded=self._rel_is_excluded,
        )
        self.assertEqual(
            [(
                "DLMS_DATA/config/.portal.json.abcdefgh.tmp",
                "config/.portal.json.abcdefgh.tmp",
            )],
            report["members"],
        )


if __name__ == "__main__":
    unittest.main()
