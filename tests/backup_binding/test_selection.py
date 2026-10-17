"""Focused byte-binding tests using new disposable Desktop profiles only."""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import shutil
import unittest
import zipfile

from desktop import backup_selection as binding
from desktop.isolation import profile_paths
from desktop.profile_state import new_manifest, publish_manifest
from desktop.transition import begin


def backup(path: Path, *, marker: str = "first") -> None:
    manifest = {"kind": "dlms-portable-backup", "schema_version": 1,
                "file_count": 1, "summary": {"quizzes": 1}}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("DLMS_BACKUP_MANIFEST.json", json.dumps(manifest))
        archive.writestr("DLMS_DATA/synthetic.txt", marker)


class BackupSelectionTests(unittest.TestCase):
    def setUp(self):
        self.name = "bind" + secrets.token_hex(5)
        self.paths = profile_paths(self.name)
        publish_manifest(self.paths, new_manifest(self.name, 49000))
        self.source = self.paths["downloads"] / "source.zip"
        backup(self.source)

    def test_confirmed_copy_is_the_selected_bytes_even_if_source_is_replaced(self):
        selected = binding.prepare(self.paths, self.name, self.source)
        original = self.source.read_bytes()
        backup(self.source.with_name("replacement.zip"), marker="later")
        os.replace(self.source.with_name("replacement.zip"), self.source)
        self.assertNotEqual(original, self.source.read_bytes())
        binding.advance(self.paths, self.name, selected["token"], "ready", "confirmed")
        receipt = binding.read(self.paths, self.name, selected["token"], state="confirmed")
        self.assertEqual(receipt["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(binding._archive_path(self.paths, selected["token"]).read_bytes(), original)
        binding.advance(self.paths, self.name, selected["token"], "confirmed", "claimed")
        with self.assertRaisesRegex(ValueError, "already used"):
            binding.advance(self.paths, self.name, selected["token"], "confirmed", "claimed")

    def test_same_size_timestamp_restored_rewrite_during_copy_is_refused(self):
        before = self.source.stat()
        def modify(_total):
            with self.source.open("r+b") as stream:
                stream.seek(-1, os.SEEK_END)
                last = stream.read(1)
                stream.seek(-1, os.SEEK_END)
                stream.write(bytes([last[0] ^ 1]))
            os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, "changed"):
            binding.prepare(self.paths, self.name, self.source, after_chunk=modify)
        self.assertEqual(self.source.stat().st_size, before.st_size)
        self.assertEqual(self.source.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertFalse(list((self.paths["root"] / "imports").glob("*.json")))

    def test_growing_source_is_bounded_while_reading(self):
        old = binding.MAX_ARCHIVE_BYTES
        binding.MAX_ARCHIVE_BYTES = self.source.stat().st_size + 10
        try:
            def grow(_total):
                with self.source.open("ab") as stream:
                    stream.write(b"x" * 100)
            with self.assertRaisesRegex(ValueError, "grew beyond"):
                binding.prepare(self.paths, self.name, self.source, after_chunk=grow)
        finally:
            binding.MAX_ARCHIVE_BYTES = old

    def test_replacement_during_copy_is_refused(self):
        before = self.source.stat()
        replacement = self.source.with_name("replacement.zip")
        backup(replacement, marker="other")
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        def replace(_total):
            os.replace(replacement, self.source)
        with self.assertRaisesRegex(ValueError, "changed"):
            binding.prepare(self.paths, self.name, self.source, after_chunk=replace)
        self.assertFalse(list((self.paths["root"] / "imports").glob("*.json")))

    def test_parent_directory_symlink_substitution_during_copy_is_refused(self):
        folder = self.paths["downloads"] / "source-parent"
        folder.mkdir(mode=0o700)
        nested = folder / "backup.zip"
        shutil.copyfile(self.source, nested)
        moved = self.paths["downloads"] / "moved-parent"
        def redirect(_total):
            folder.rename(moved)
            folder.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "changed"):
            binding.prepare(self.paths, self.name, nested, after_chunk=redirect)
        self.assertFalse(list((self.paths["root"] / "imports").glob("*.json")))

    def test_symlinks_and_private_copy_tampering_fail_closed(self):
        link = self.paths["downloads"] / "link.zip"
        link.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            binding.prepare(self.paths, self.name, link)
        selected = binding.prepare(self.paths, self.name, self.source)
        archive = binding._archive_path(self.paths, selected["token"])
        archive.chmod(0o600)
        with archive.open("r+b") as stream:
            stream.seek(-1, os.SEEK_END)
            byte = stream.read(1)
            stream.seek(-1, os.SEEK_END)
            stream.write(bytes([byte[0] ^ 1]))
        with self.assertRaisesRegex(ValueError, "private backup bytes changed"):
            binding.advance(self.paths, self.name, selected["token"], "ready", "confirmed")

    def test_profile_epoch_and_token_binding(self):
        selected = binding.prepare(self.paths, self.name, self.source)
        other = "bind" + secrets.token_hex(5)
        other_paths = profile_paths(other)
        publish_manifest(other_paths, new_manifest(other, 49001))
        other_imports = other_paths["root"] / "imports"
        other_imports.mkdir(mode=0o700)
        shutil.copy2(binding._receipt_path(self.paths, selected["token"]),
                     other_imports / f"{selected['token']}.json")
        shutil.copy2(binding._archive_path(self.paths, selected["token"]),
                     other_imports / f"{selected['token']}.zip")
        with self.assertRaisesRegex(ValueError, "receipt is invalid"):
            binding.read(other_paths, other, selected["token"])
        manifest = new_manifest(self.name, 49000)
        publish_manifest(self.paths, manifest)
        with self.assertRaisesRegex(ValueError, "another profile or dataset epoch"):
            binding.advance(self.paths, self.name, selected["token"], "ready", "confirmed")

    def test_concurrent_confirmation_claims_once(self):
        selected = binding.prepare(self.paths, self.name, self.source)
        token = selected["token"]
        binding.advance(self.paths, self.name, token, "ready", "confirmed")
        with self.assertRaisesRegex(ValueError, "already used"):
            binding.advance(self.paths, self.name, token, "ready", "confirmed")
        def claim():
            try:
                return binding.advance(self.paths, self.name, token, "confirmed", "claimed")["state"]
            except ValueError:
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _n: claim(), range(2)))
        self.assertCountEqual(outcomes, ["claimed", "rejected"])

    def test_confirmed_stage_replacement_or_symlink_cannot_publish_marker(self):
        selected = binding.prepare(self.paths, self.name, self.source)
        token = selected["token"]
        binding.advance(self.paths, self.name, token, "ready", "confirmed")
        archive = binding._archive_path(self.paths, token)
        archive.unlink()
        archive.symlink_to(self.source)
        with self.assertRaises(ValueError):
            binding.advance(self.paths, self.name, token, "confirmed", "claimed")
        self.assertFalse((self.paths["root"] / "desktop-data-transition.json").exists())
        archive.unlink()
        archive.write_bytes(b"different bytes")
        with self.assertRaisesRegex(ValueError, "private backup bytes changed"):
            binding.advance(self.paths, self.name, token, "confirmed", "claimed")
        archive.unlink()
        archive.symlink_to(self.source)
        with self.assertRaises(ValueError):
            begin(self.paths, self.name, object(), token, archive,
                  expected_digest=selected["sha256"])
        self.assertFalse((self.paths["root"] / "desktop-data-transition.json").exists())
        # The worker can claim a sound receipt and then observe a malicious
        # stage-path swap before transition publication. It must still stop.
        later = binding.prepare(self.paths, self.name, self.source)
        later_token = later["token"]
        binding.advance(self.paths, self.name, later_token, "ready", "confirmed")
        binding.advance(self.paths, self.name, later_token, "confirmed", "claimed")
        later_archive = binding._archive_path(self.paths, later_token)
        later_archive.unlink()
        later_archive.symlink_to(self.source)
        with self.assertRaises(ValueError):
            begin(self.paths, self.name, object(), later_token, later_archive,
                  expected_digest=later["sha256"])
        self.assertEqual(json.loads(binding._receipt_path(self.paths, later_token).read_text())["state"],
                         "claimed")
        self.assertFalse((self.paths["root"] / "desktop-data-transition.json").exists())

    def test_cancel_and_failure_do_not_publish_import_authority(self):
        selected = binding.prepare(self.paths, self.name, self.source)
        binding.cancel(self.paths, self.name, selected["token"])
        with self.assertRaisesRegex(ValueError, "already used"):
            binding.advance(self.paths, self.name, selected["token"], "ready", "confirmed")
        self.assertFalse(binding._archive_path(self.paths, selected["token"]).exists())
        with self.assertRaisesRegex(OSError, "synthetic copy failure"):
            binding.prepare(self.paths, self.name, self.source,
                            after_chunk=lambda _total: (_ for _ in ()).throw(OSError("synthetic copy failure")))
        self.assertFalse(list((self.paths["root"] / "imports").glob("*.part")))


if __name__ == "__main__":
    unittest.main()
