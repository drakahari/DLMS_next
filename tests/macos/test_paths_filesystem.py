"""Native Darwin storage and no-replace publication qualification, synthetic only.

Run without third-party dependencies with:
python -m unittest discover -s tests/macos -p test_paths_filesystem.py -v
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desktop import backup_output, export_output, macos_paths


@unittest.skipUnless(sys.platform == "darwin", "Native macOS filesystem evidence")
class MacPathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-macos-paths-")
        self.addCleanup(self.temporary.cleanup)
        # macOS /var and /tmp are symlinks; inputs use their canonical path.
        self.base = Path(self.temporary.name).resolve()

    def root(self, name="candidate"):
        return self.base / name

    def assert_refused(self, root, **kwargs):
        with self.assertRaises((ValueError, OSError)):
            macos_paths.prepare_root(root, **kwargs)

    def test_default_uses_account_home_instead_of_scoped_home(self):
        native = self.base / "account-home"
        with patch.object(macos_paths.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=str(native))) as lookup:
            with patch.dict(os.environ, {"HOME": str(self.base / "scoped-home")}):
                self.assertEqual(macos_paths.real_home(), native)
                self.assertEqual(macos_paths.default_data_root(), native / "Library/Application Support/DLMS Desktop Preview")
        lookup.assert_called_with(os.getuid())

    def test_new_root_is_private_marked_and_reopens_unchanged(self):
        root = macos_paths.prepare_root(self.root())
        self.assertEqual(root, self.root())
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
        marker = root / macos_paths.MARKER
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        self.assertEqual(json.loads(marker.read_text()), macos_paths.IDENTITY)
        original = marker.read_bytes()
        survivor = root / "synthetic-survivor.txt"
        survivor.write_bytes(b"preserve")
        self.assertEqual(macos_paths.prepare_root(root, create=False), root)
        self.assertEqual(marker.read_bytes(), original)
        self.assertEqual(survivor.read_bytes(), b"preserve")

    def test_omitted_root_uses_only_native_default(self):
        with patch.object(macos_paths, "default_data_root", return_value=self.root()):
            self.assertEqual(macos_paths.prepare_root(), self.root())

    def test_read_only_probe_never_creates_root(self):
        self.assert_refused(self.root(), create=False)
        self.assertFalse(self.root().exists())

    def test_existing_unmarked_root_is_never_adopted(self):
        root = self.root()
        root.mkdir(mode=0o700)
        survivor = root / "synthetic-survivor.txt"
        survivor.write_bytes(b"preserve")
        self.assert_refused(root)
        self.assertEqual(survivor.read_bytes(), b"preserve")
        self.assertFalse((root / macos_paths.MARKER).exists())

    def test_symlink_root_or_ancestor_is_refused_without_writes(self):
        actual = self.base / "actual"
        actual.mkdir(mode=0o700)
        link = self.base / "linked"
        link.symlink_to(actual, target_is_directory=True)
        for root in (link, link / "child"):
            with self.subTest(root=root):
                self.assert_refused(root)
        self.assertEqual(list(actual.iterdir()), [])

    def test_non_directory_ancestor_is_refused(self):
        obstacle = self.base / "file"
        obstacle.write_bytes(b"preserve")
        self.assert_refused(obstacle / "candidate")
        self.assertEqual(obstacle.read_bytes(), b"preserve")

    def test_unprivate_root_is_refused_and_never_chmodded(self):
        root = macos_paths.prepare_root(self.root())
        root.chmod(0o750)
        self.assert_refused(root)
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o750)

    def test_ambiguous_and_relative_roots_are_refused(self):
        for root in (Path("relative-candidate"), self.base / "missing" / ".." / "candidate"):
            with self.subTest(root=root):
                self.assert_refused(root)
        self.assertFalse(self.root().exists())

    def test_application_payload_is_never_a_data_root(self):
        payload = self.base / "Synthetic.app" / "Contents" / "Frameworks"
        payload.mkdir(parents=True)
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(payload), create=True):
            for root in (payload, payload / "data", payload / ".gate1" / "data",
                         payload.parent / "MacOS" / "data", payload.parents[1] / "data"):
                with self.subTest(root=root):
                    self.assert_refused(root)

    def test_marker_schema_and_contents_are_checked(self):
        invalid = (b"not JSON", b"[]", b"null", b"{}", b"x" * 513,
                   json.dumps({**macos_paths.IDENTITY, "version": 2}).encode(),
                   json.dumps({**macos_paths.IDENTITY, "version": True}).encode(),
                   json.dumps({**macos_paths.IDENTITY, "extra": "field"}).encode())
        for index, data in enumerate(invalid):
            with self.subTest(index=index):
                root = macos_paths.prepare_root(self.root(f"invalid-{index}"))
                marker = root / macos_paths.MARKER
                marker.write_bytes(data)
                self.assert_refused(root)
                self.assertEqual(marker.read_bytes(), data)

    def test_symlink_and_unprivate_markers_are_refused(self):
        root = macos_paths.prepare_root(self.root())
        marker = root / macos_paths.MARKER
        marker.chmod(0o644)
        self.assert_refused(root)
        marker.unlink()
        other = self.base / "marker-elsewhere.json"
        other.write_text(json.dumps(macos_paths.IDENTITY))
        other.chmod(0o600)
        marker.symlink_to(other)
        self.assert_refused(root)
        self.assertTrue(marker.is_symlink())


@unittest.skipUnless(sys.platform == "darwin", "Native macOS filesystem evidence")
class MacPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-macos-publish-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()

    def fixture(self, label):
        folder = self.base / label / "Documents space é"
        folder.mkdir(mode=0o700, parents=True)
        source = folder.parent / "private-source.zip"
        source.write_bytes(b"synthetic native publication bytes\x00" * 1024)
        suffix = ".txt" if label.endswith("export_output") else ".zip"
        return source, folder / ("output space é" + suffix)

    def test_native_directory_fsync_and_roundtrip_no_overwrite(self):
        for module in (backup_output, export_output):
            with self.subTest(adapter=module.__name__):
                source, destination = self.fixture(module.__name__)
                directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                selection = module.select(destination)
                result = module.publish(source, selection)
                self.assertEqual(destination.read_bytes(), source.read_bytes())
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
                self.assertEqual(result["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(result["bytes"], source.stat().st_size)
                with self.assertRaises(FileExistsError):
                    module.select(destination)
                with self.assertRaises(FileExistsError):
                    module.publish(source, selection)
                self.assertEqual(destination.read_bytes(), source.read_bytes())

    def test_changed_parent_is_refused_without_writing_either_folder(self):
        for module in (backup_output, export_output):
            with self.subTest(adapter=module.__name__):
                source, destination = self.fixture(module.__name__)
                selection = module.select(destination)
                moved = destination.parent.with_name("retained-original-folder")
                destination.parent.rename(moved)
                destination.parent.mkdir(mode=0o700)
                with self.assertRaisesRegex(ValueError, "changed"):
                    module.publish(source, selection)
                self.assertEqual(list(moved.iterdir()), [])
                self.assertEqual(list(destination.parent.iterdir()), [])
                self.assertTrue(source.exists())

    def test_racing_destination_preserves_unrelated_winner(self):
        for module in (backup_output, export_output):
            with self.subTest(adapter=module.__name__):
                source, destination = self.fixture(module.__name__)
                def race(phase):
                    if phase == "before_publish":
                        destination.write_bytes(b"unrelated race winner")
                with self.assertRaises(FileExistsError):
                    module.publish(source, module.select(destination), checkpoint=race)
                self.assertEqual(destination.read_bytes(), b"unrelated race winner")
                self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
