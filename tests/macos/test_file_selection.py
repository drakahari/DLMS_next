"""Native Darwin filesystem checks; run without Qt or third-party test tools."""
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from desktop import macos_file_selection as fs


@unittest.skipUnless(sys.platform == 'darwin', 'Darwin immutable flags required')
class DarwinSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='dlms-macos-selection-')
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'Visible quiz é space.txt'
        self.source.write_bytes(b'Original selected bytes\n')
        self.store = fs.Snapshots(self.root)
        self.retained = fs._retained

    def tearDown(self):
        self.store.close()
        self.assertEqual(fs._retained, self.retained)
        self.temporary.cleanup()

    def test_private_immutable_copy_preserves_name_and_bytes(self):
        selected = Path(self.store.stage([self.source])[0])
        self.assertEqual(selected.name, self.source.name)
        self.assertFalse(selected.is_symlink())
        self.assertEqual(selected.stat().st_mode & 0o777, 0o400)
        self.assertTrue(selected.stat().st_flags & stat.UF_IMMUTABLE)
        self.assertTrue(selected.parent.stat().st_flags & stat.UF_IMMUTABLE)
        self.source.write_bytes(b'Later source change')
        self.assertEqual(selected.read_bytes(), b'Original selected bytes\n')
        self.assertEqual(hashlib.sha256(selected.read_bytes()).hexdigest(), self.store.items[0][3])
        for descriptor in (self.store.root_fd, self.store.items[0][0], self.store.items[0][4]):
            self.assertFalse(os.get_inheritable(descriptor))
        for operation in (lambda: selected.write_bytes(b'changed'),
                          lambda: os.chmod(selected, 0o600),
                          lambda: selected.unlink(),
                          lambda: selected.parent.rename(self.root/'replacement')):
            with self.assertRaises(PermissionError): operation()
        self.store.close()
        self.assertFalse(selected.exists())
        self.assertFalse(self.store.directory.exists())

    def test_source_changes_or_replacement_refused_atomically(self):
        for phase in ('opened', 'copying', 'copied'):
            for replace in (False, True):
                with self.subTest(phase=phase, replace=replace):
                    self.source.write_bytes(b'A' * (fs.CHUNK + 10))
                    before = self.source.stat()
                    changed = False
                    def checkpoint(at, path):
                        nonlocal changed
                        if changed or at != phase: return
                        changed = True
                        if replace:
                            alternate = self.root/'replacement.txt'
                            alternate.write_bytes(b'Z' * before.st_size)
                            os.replace(alternate, self.source)
                        else: self.source.write_bytes(b'Z' * before.st_size)
                        os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
                    with self.assertRaisesRegex(ValueError, 'changed|replaced'):
                        self.store.stage([self.source], checkpoint=checkpoint)
                    self.assertFalse(self.store.items)
                    self.assertEqual(fs._retained, self.retained)

    def test_selected_source_handle_pinned_before_consent(self):
        descriptor, original = fs.open_source(self.source)
        try:
            replacement = self.root/'new.txt'; replacement.write_bytes(b'Private replacement')
            os.replace(replacement, self.source)
            with self.assertRaisesRegex(ValueError, 'changed|replaced'):
                self.store.stage([self.source], captured=[(descriptor, original)], expected=[fs._identity(original)])
        finally: os.close(descriptor)

    def test_staged_tamper_detected_and_retired(self):
        for restore_flags in (False, True):
            with self.subTest(restore_flags=restore_flags):
                def checkpoint(phase, path):
                    if phase != 'sealed': return
                    # Explicit same-uid flag clearing demonstrates the
                    # documented authority limit. Reapplying the flags still
                    # cannot escape exact staged-byte verification.
                    fd = os.open(path, os.O_RDONLY)
                    try: fs._flags(fd, 0)
                    finally: os.close(fd)
                    path.chmod(0o600)
                    path.write_bytes(b'Changed staged bytes')
                    if restore_flags:
                        path.chmod(0o400)
                        fd = os.open(path, os.O_RDONLY)
                        try: fs._flags(fd, stat.UF_IMMUTABLE)
                        finally: os.close(fd)
                with self.assertRaisesRegex(ValueError, 'snapshot changed'):
                    self.store.stage([self.source], checkpoint=checkpoint)
                self.assertFalse(self.store.items)
                self.assertEqual(list(self.store.directory.iterdir()), [])

    def test_unsafe_types_and_private_sources_refused(self):
        cases = []
        link = self.root/'link.txt'; link.symlink_to(self.source); cases.append(link)
        linked = self.root/'linked'; linked.symlink_to(self.root, target_is_directory=True); cases.append(linked/self.source.name)
        fifo = self.root/'pipe.txt'; os.mkfifo(fifo); cases.append(fifo)
        directory = self.root/'dir.txt'; directory.mkdir(); cases.append(directory)
        empty = self.root/'empty.txt'; empty.write_bytes(b''); cases.append(empty)
        unreadable = self.root/'unreadable.txt'; unreadable.write_bytes(b'blocked'); unreadable.chmod(0); cases.append(unreadable)
        invalid = self.root/'wrong.exe'; invalid.write_bytes(b'blocked'); cases.append(invalid)
        oversized = self.root/'large.txt'
        with oversized.open('wb') as stream: stream.truncate(fs.LIMITS['.txt']+1)
        cases.append(oversized)
        for path in cases:
            with self.subTest(path=path.name), self.assertRaises((ValueError, OSError)):
                self.store.stage([path])
        with self.assertRaises(ValueError): self.store.stage([self.source], forbidden=[self.root])
        self.assertFalse(self.store.items)

    def test_private_equivalent_case_and_unicode_spellings_refused(self):
        private = self.root/'Private É'; private.mkdir()
        source = private/'secret.txt'; source.write_text('private source')
        alternate = self.root/'private É'/'secret.txt'
        with self.assertRaisesRegex(ValueError, 'private data'):
            fs.open_source(alternate, forbidden=[private])
        descriptor, _ = fs.open_source(source, forbidden=[private], permitted_private=[private])
        os.close(descriptor)

    def test_hardlink_refused(self):
        other = self.root/'hardlink.txt'; os.link(self.source, other)
        with self.assertRaisesRegex(ValueError, 'hard links'):
            self.store.stage([other])

    def test_invalid_pdf_and_zip_refused(self):
        for suffix in ('.pdf', '.zip'):
            path = self.root/('broken'+suffix); path.write_bytes(b'Invalid contents')
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                self.store.stage([path])

    def test_cancel_failed_batch_and_discard_preserve_prior_files(self):
        first = self.store.stage([self.source])
        second = self.store.stage([self.source])
        self.assertEqual(self.store.discard(second), [])
        self.assertTrue(Path(first[0]).exists())
        self.assertFalse(Path(second[0]).exists())
        with self.assertRaisesRegex(ValueError, 'canceled'):
            self.store.stage([self.source], valid=lambda: False)
        with self.assertRaises(ValueError): self.store.stage([self.source, self.root/'unknown.exe'])
        self.assertEqual(len(self.store.items), 1)
        self.assertEqual(list(self.store.directory.iterdir()), [Path(first[0]).parent])

    def test_quotas_refused_without_retaining_partial_files(self):
        with patch.object(fs, 'PAGE_LIMIT', 1), self.assertRaisesRegex(ValueError, 'page limit'):
            self.store.stage([self.source])
        with patch.object(fs, 'PROCESS_LIMIT', self.retained), self.assertRaisesRegex(ValueError, 'Too much'):
            self.store.stage([self.source])
        with patch.object(fs, 'MAX_RETAINED_FILES', 0), self.assertRaisesRegex(ValueError, 'Too many'):
            self.store.stage([self.source])
        self.assertFalse(self.store.items)

    def test_write_failure_releases_resources(self):
        with patch.object(fs.os, 'write', side_effect=OSError('Synthetic copy failure')):
            with self.assertRaisesRegex(OSError, 'Synthetic'): self.store.stage([self.source])
        self.assertEqual(fs._retained, self.retained)
        self.assertEqual(list(self.store.directory.iterdir()), [])

    def test_flag_failure_fails_closed_without_quota_leak(self):
        with patch.object(fs, '_flags', side_effect=OSError('Synthetic unsupported filesystem')):
            with self.assertRaisesRegex(OSError, 'Synthetic'): self.store.stage([self.source])
        self.assertEqual(fs._retained, self.retained)
        # Failed flag operations leave evidence, never a selected path.
        self.assertFalse(self.store.items)
        for path in self.store.directory.iterdir():
            for child in path.iterdir(): child.unlink()
            path.rmdir()

    def test_changed_store_root_never_publishes_substituted_path(self):
        moved = self.root/'moved-private-selection'
        def checkpoint(phase, path):
            if phase == 'sealed': self.store.directory.rename(moved)
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.store.stage([self.source], checkpoint=checkpoint)
        self.assertFalse(self.store.items)
        self.assertEqual(list(moved.iterdir()), [])
        moved.rename(self.store.directory)


if __name__ == '__main__': unittest.main()
