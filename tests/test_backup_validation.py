import json
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class BackupValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="dlms-backup-validation-")
        self.addCleanup(self.temp_dir.cleanup)

    def _path(self, name="backup.zip"):
        return Path(self.temp_dir.name) / name

    def _manifest(self, file_count=1):
        return {
            "schema_version": dlms.DLMS_BACKUP_SCHEMA_VERSION,
            "kind": "dlms-portable-backup",
            "file_count": file_count,
        }

    def _write_backup(self, members=None, manifest_count=None, compression=zipfile.ZIP_DEFLATED):
        members = list(members or [("DLMS_DATA/config/portal.json", b"{}")])
        if manifest_count is None:
            manifest_count = len(members)
        path = self._path()
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(self._manifest(manifest_count)))
            for name, data in members:
                archive.writestr(name, data)
        return path

    def _assert_rejected_before_testzip(self, path, message):
        with mock.patch.object(zipfile.ZipFile, "testzip") as testzip:
            with self.assertRaisesRegex(ValueError, message):
                dlms._validate_dlms_backup(path)
            testzip.assert_not_called()

    def test_valid_normal_backup_is_accepted(self):
        path = self._write_backup()
        report = dlms._validate_dlms_backup(path)
        self.assertEqual(report["file_count"], 1)
        self.assertEqual(report["members"], [("DLMS_DATA/config/portal.json", "config/portal.json")])

    def test_excessive_member_count_is_rejected_before_decompression(self):
        path = self._write_backup([
            ("DLMS_DATA/data/one.json", b"{}"),
            ("DLMS_DATA/data/two.json", b"{}"),
        ])
        with mock.patch.object(dlms, "DLMS_BACKUP_MAX_FILES", 2):
            self._assert_rejected_before_testzip(path, "more than")

    def test_oversized_single_member_is_rejected_before_decompression(self):
        path = self._write_backup([("DLMS_DATA/data/large.bin", b"12345")])
        with mock.patch.object(dlms, "DLMS_BACKUP_MAX_SINGLE_FILE", 4):
            self._assert_rejected_before_testzip(path, "oversized single file")

    def test_excessive_total_size_is_rejected_before_decompression(self):
        path = self._write_backup([
            ("DLMS_DATA/data/one.bin", b"12345"),
            ("DLMS_DATA/data/two.bin", b"67890"),
        ])
        with zipfile.ZipFile(path) as archive:
            declared_total = sum(info.file_size for info in archive.infolist())
            largest_member = max(info.file_size for info in archive.infolist())
        with mock.patch.object(dlms, "DLMS_BACKUP_MAX_UNCOMPRESSED", declared_total - 1), \
             mock.patch.object(dlms, "DLMS_BACKUP_MAX_SINGLE_FILE", largest_member):
            self._assert_rejected_before_testzip(path, "expands beyond")

    def test_excessive_compressed_size_is_rejected_before_decompression(self):
        path = self._write_backup([
            ("DLMS_DATA/data/one.bin", b"12345"),
            ("DLMS_DATA/data/two.bin", b"67890"),
        ])
        with zipfile.ZipFile(path) as archive:
            declared_compressed = sum(info.compress_size for info in archive.infolist())
        with mock.patch.object(dlms, "DLMS_BACKUP_MAX_COMPRESSED", declared_compressed - 1):
            self._assert_rejected_before_testzip(path, "compressed data exceeds")

    def test_suspicious_ratio_is_rejected_before_decompression(self):
        path = self._write_backup([("DLMS_DATA/data/compressible.bin", b"0" * 4096)])
        with mock.patch.object(dlms, "DLMS_BACKUP_RATIO_MIN_UNCOMPRESSED", 1024), \
             mock.patch.object(dlms, "DLMS_BACKUP_MAX_COMPRESSION_RATIO", 10):
            self._assert_rejected_before_testzip(path, "suspicious compression ratio")

    def test_unsafe_paths_are_rejected_before_decompression(self):
        for index, unsafe_name in enumerate(("../escape", "/absolute", "C:/windows/path")):
            with self.subTest(name=unsafe_name):
                path = self._path(f"unsafe-{index}.zip")
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(self._manifest(1)))
                    archive.writestr(unsafe_name, b"x")
                self._assert_rejected_before_testzip(path, "absolute|unsafe relative")

    def test_symlink_is_rejected_before_decompression(self):
        path = self._path("symlink.zip")
        link = zipfile.ZipInfo("DLMS_DATA/config/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(self._manifest(1)))
            archive.writestr(link, "target")
        self._assert_rejected_before_testzip(path, "symbolic link")

    def test_special_file_is_rejected_before_decompression(self):
        path = self._path("fifo.zip")
        fifo = zipfile.ZipInfo("DLMS_DATA/config/fifo")
        fifo.create_system = 3
        fifo.external_attr = (stat.S_IFIFO | 0o600) << 16
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(self._manifest(1)))
            archive.writestr(fifo, "data")
        self._assert_rejected_before_testzip(path, "special file")

    def test_duplicate_normalized_name_is_rejected_before_decompression(self):
        path = self._path("duplicate.zip")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(dlms.DLMS_BACKUP_MANIFEST, json.dumps(self._manifest(2)))
                archive.writestr("DLMS_DATA/config/item.json", "{}")
                archive.writestr("DLMS_DATA/config/./item.json", "{}")
        self._assert_rejected_before_testzip(path, "duplicate path")

    def test_corrupted_crc_is_rejected_after_metadata_validation(self):
        path = self._write_backup(
            [("DLMS_DATA/config/portal.json", b"unique-crc-payload")],
            compression=zipfile.ZIP_STORED,
        )
        damaged = bytearray(path.read_bytes())
        payload_at = damaged.index(b"unique-crc-payload")
        damaged[payload_at] ^= 0x01
        path.write_bytes(damaged)

        calls = []
        original_testzip = zipfile.ZipFile.testzip

        def tracking_testzip(archive):
            calls.append(archive.filename)
            return original_testzip(archive)

        with mock.patch.object(zipfile.ZipFile, "testzip", tracking_testzip):
            with self.assertRaisesRegex(ValueError, "integrity check failed"):
                dlms._validate_dlms_backup(path)
        self.assertEqual(calls, [str(path)])


if __name__ == "__main__":
    unittest.main()
