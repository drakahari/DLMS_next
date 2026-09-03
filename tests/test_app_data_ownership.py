import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="dlms-ownership-app-")
os.environ["QUIZAPP_DATA_DIR"] = _IMPORT_DATA.name

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


class AppDataOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-ownership-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _owned_root(self, name="owned"):
        root = self.root / name
        root.mkdir()
        self.assertTrue(dlms._initialize_data_root_ownership(str(root)))
        return root

    def test_new_default_and_empty_custom_roots_are_marked(self):
        for name, is_default in (("default", True), ("custom", False)):
            with self.subTest(name=name):
                root = self.root / name
                self.assertTrue(dlms._initialize_data_root_ownership(str(root), is_default=is_default))
                marker = dlms._read_data_root_marker(str(root))
                self.assertEqual(marker["marker"], dlms.DLMS_DATA_ROOT_MARKER_ID)
                self.assertEqual(marker["version"], 1)
                self.assertEqual(marker["application"], "DLMS")

    def test_path_resolver_marks_default_and_environment_custom_roots(self):
        custom = self.root / "portable-volume"
        with mock.patch.dict(os.environ, {"QUIZAPP_DATA_DIR": str(custom)}):
            self.assertEqual(dlms.get_app_data_dir(), str(custom))
        self.assertIsNotNone(dlms._read_data_root_marker(str(custom)))

        default = self.root / "desktop-default"
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(dlms, "_default_app_data_path", return_value=str(default)):
            os.environ.pop("QUIZAPP_DATA_DIR", None)
            self.assertEqual(dlms.get_app_data_dir(), str(default))
        self.assertIsNotNone(dlms._read_data_root_marker(str(default)))

    def test_recognizable_legacy_root_is_migrated(self):
        root = self.root / "legacy"
        for name in ("config", "quizzes", "data", ".quiz_publications"):
            (root / name).mkdir(parents=True, exist_ok=True)
        self.assertTrue(dlms._initialize_data_root_ownership(str(root)))
        self.assertIsNotNone(dlms._read_data_root_marker(str(root)))

    def test_ambiguous_nonempty_root_is_not_claimed(self):
        root = self.root / "shared"
        root.mkdir()
        unrelated = root / "family-photos.txt"
        unrelated.write_text("keep", encoding="utf-8")
        self.assertFalse(dlms._initialize_data_root_ownership(str(root)))
        self.assertFalse((root / dlms.DLMS_DATA_ROOT_MARKER).exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

        # DLMS-created directories do not erase the evidence of ambiguity on restart.
        for name in ("config", "quizzes", "data"):
            (root / name).mkdir()
        self.assertFalse(dlms._initialize_data_root_ownership(str(root)))

    def test_invalid_marker_is_not_overwritten(self):
        root = self.root / "tampered"
        root.mkdir()
        marker = root / dlms.DLMS_DATA_ROOT_MARKER
        marker.write_text('{"marker":"other-application"}', encoding="utf-8")
        self.assertFalse(dlms._initialize_data_root_ownership(str(root)))
        self.assertEqual(json.loads(marker.read_text(encoding="utf-8"))["marker"], "other-application")

    def test_dangerous_roots_and_source_ancestors_are_rejected(self):
        source = Path(dlms.__file__).resolve().parent
        candidates = [Path(os.path.sep), Path.home(), source, source.parent]
        for candidate in candidates:
            with self.subTest(path=candidate):
                with self.assertRaises(dlms.DataRootOwnershipError):
                    dlms._validate_destructive_data_root_path(str(candidate))

    def test_normal_custom_root_is_accepted_and_symlink_cannot_bypass_checks(self):
        owned = self._owned_root()
        with mock.patch.object(dlms, "APP_DATA_DIR", str(owned)):
            self.assertEqual(dlms._require_owned_app_data_root(), str(owned.resolve()))

        link = self.root / "source-link"
        link.symlink_to(Path(dlms.__file__).resolve().parent, target_is_directory=True)
        with self.assertRaises(dlms.DataRootOwnershipError):
            dlms._validate_destructive_data_root_path(str(link))

    def test_remove_all_requires_valid_marker_before_deletion(self):
        owned = self._owned_root("remove")
        with mock.patch.object(dlms, "APP_DATA_DIR", str(owned)), \
             mock.patch.object(dlms.shutil, "rmtree") as remove:
            self.assertEqual(dlms._remove_all_dlms_runtime_data_core(), str(owned.resolve()))
            remove.assert_called_once_with(str(owned.resolve()))

        for name, marker_content in (("unmarked", None), ("invalid", "{}")):
            with self.subTest(name=name):
                root = self.root / name
                root.mkdir()
                sentinel = root / "keep.txt"
                sentinel.write_text("unchanged", encoding="utf-8")
                if marker_content is not None:
                    (root / dlms.DLMS_DATA_ROOT_MARKER).write_text(marker_content, encoding="utf-8")
                with mock.patch.object(dlms, "APP_DATA_DIR", str(root)), \
                     mock.patch.object(dlms.shutil, "rmtree") as remove:
                    with self.assertRaises(dlms.DataRootOwnershipError):
                        dlms._remove_all_dlms_runtime_data_core()
                    remove.assert_not_called()
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_remove_all_confirmation_still_precedes_ownership_check(self):
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_remove_all_dlms_runtime_data_core") as remove:
            response = client.post(
                "/api/remove_all_dlms_data",
                json={"confirmation": "wrong"},
                headers=csrf_headers(client),
            )
        self.assertEqual(response.status_code, 400)
        remove.assert_not_called()

    def test_remove_all_route_reports_unverified_root_without_deleting(self):
        client = dlms.app.test_client()
        root = self.root / "route-unowned"
        root.mkdir()
        sentinel = root / "keep.txt"
        sentinel.write_text("safe", encoding="utf-8")
        with mock.patch.object(dlms, "APP_DATA_DIR", str(root)):
            response = client.post(
                "/api/remove_all_dlms_data",
                json={"confirmation": "REMOVE DLMS DATA"},
                headers=csrf_headers(client),
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("not verified", response.get_json()["error"])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "safe")

    def test_reset_refuses_unowned_root_before_backup_or_mutation(self):
        root = self.root / "unowned-reset"
        root.mkdir()
        reset = mock.Mock()
        with mock.patch.object(dlms, "APP_DATA_DIR", str(root)), \
             mock.patch.object(dlms, "_create_dlms_backup") as backup:
            with self.assertRaises(dlms.DataRootOwnershipError):
                dlms._run_reset_with_backup("test", reset)
        backup.assert_not_called()
        reset.assert_not_called()

    def test_restore_apply_requires_ownership_and_accepts_verified_root(self):
        staged = self.root / "staged"
        staged.mkdir()
        unowned = self.root / "unowned-restore"
        unowned.mkdir()
        with mock.patch.object(dlms, "APP_DATA_DIR", str(unowned)):
            with self.assertRaises(dlms.DataRootOwnershipError):
                dlms._apply_restored_data(str(staged))

        owned = self._owned_root("restore")
        with mock.patch.object(dlms, "APP_DATA_DIR", str(owned)), \
             mock.patch.object(dlms, "_ensure_runtime_data_dirs"), \
             mock.patch.object(dlms, "ensure_db_initialized"):
            dlms._apply_restored_data(str(staged))

    def test_restore_apply_stops_before_live_mutation_if_sqlite_sidecar_removal_fails(self):
        staged = self.root / "sidecar-staged"
        staged.mkdir()
        (staged / "results.db").write_bytes(b"staged database")
        owned = self._owned_root("sidecar-restore")
        database = owned / "results.db"
        database.write_bytes(b"live database")
        sidecar = owned / "results.db-wal"
        sidecar.write_bytes(b"live wal")

        with mock.patch.object(dlms, "APP_DATA_DIR", str(owned)), \
             mock.patch.object(dlms, "DB_PATH", str(database)), \
             mock.patch.object(dlms, "_remove_live_restore_root") as remove_root, \
             mock.patch.object(dlms.os, "remove", side_effect=PermissionError("sidecar busy")), \
             mock.patch.object(dlms, "_ensure_runtime_data_dirs"), \
             mock.patch.object(dlms, "ensure_db_initialized"):
            with self.assertRaisesRegex(PermissionError, "sidecar busy"):
                dlms._apply_restored_data(str(staged))

        remove_root.assert_not_called()
        self.assertEqual(b"live database", database.read_bytes())
        self.assertEqual(b"live wal", sidecar.read_bytes())

    def test_exact_restore_unlinks_stale_live_symlink_without_touching_target(self):
        staged = self.root / "symlink-staged"
        staged.mkdir()
        owned = self._owned_root("symlink-restore")
        external = self.root / "external-data"
        external.mkdir()
        sentinel = external / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        linked = owned / "stale-linked-root"
        try:
            linked.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")

        with mock.patch.object(dlms, "APP_DATA_DIR", str(owned)), \
             mock.patch.object(dlms, "_ensure_runtime_data_dirs"), \
             mock.patch.object(dlms, "ensure_db_initialized"):
            dlms._apply_restored_data(str(staged))

        self.assertFalse(linked.exists())
        self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_fresh_state_reset_preserves_ownership_marker(self):
        owned = self._owned_root("reset-root")
        (owned / "discard.txt").write_text("data", encoding="utf-8")
        backup_dir = owned / "backups"
        backup_dir.mkdir()
        with mock.patch.object(dlms, "APP_DATA_DIR", str(owned)), \
             mock.patch.object(dlms, "_ensure_runtime_data_dirs"), \
             mock.patch.object(dlms, "ensure_db_initialized"), \
             mock.patch.object(dlms, "save_registry"), \
             mock.patch.object(dlms, "load_portal_config"):
            dlms._full_data_reset_core()
        self.assertIsNotNone(dlms._read_data_root_marker(str(owned)))
        self.assertTrue(backup_dir.exists())
        self.assertFalse((owned / "discard.txt").exists())


if __name__ == "__main__":
    unittest.main()
