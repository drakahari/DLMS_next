"""Exercise shared publication primitives on the actual native Mac filesystem."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

from desktop import backup_output, export_output


@unittest.skipUnless(sys.platform == 'darwin', 'Native Darwin filesystem check')
class DarwinPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='dlms-macos-publish-')
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root/'completed-source.zip'
        self.source.write_bytes(b'Complete synthetic output bytes')

    def tearDown(self): self.temporary.cleanup()

    def each_module(self):
        return ((backup_output, '.zip'), (export_output, '.txt'))

    def test_unicode_publication_and_no_overwrite(self):
        for module, suffix in self.each_module():
            with self.subTest(module=module.__name__):
                destination = self.root/('Visible output é space'+suffix)
                selection = module.select(destination)
                result = module.publish(self.source, selection)
                self.assertEqual(destination.read_bytes(), self.source.read_bytes())
                self.assertEqual(result['bytes'], self.source.stat().st_size)
                with self.assertRaises(FileExistsError): module.select(destination)
                with self.assertRaises(FileExistsError): module.publish(self.source, selection)
                self.assertEqual(destination.read_bytes(), self.source.read_bytes())

    def test_collision_after_consent_never_replaces_existing_file(self):
        for module, suffix in self.each_module():
            with self.subTest(module=module.__name__):
                destination = self.root/('collision'+suffix)
                selection = module.select(destination)
                destination.write_bytes(b'Unrelated winner')
                with self.assertRaises(FileExistsError): module.publish(self.source, selection)
                self.assertEqual(destination.read_bytes(), b'Unrelated winner')
                self.assertFalse(list(self.root.glob('.dlms-*.part')))

    def test_changed_source_is_not_published(self):
        for module, suffix in self.each_module():
            with self.subTest(module=module.__name__):
                self.source.write_bytes(b'Initial complete synthetic bytes')
                destination = self.root/('source-changed'+suffix)
                selection = module.select(destination)
                changed = False
                def checkpoint(phase):
                    nonlocal changed
                    if phase == 'copy' and not changed:
                        changed = True
                        self.source.write_bytes(b'Changed private output bytes')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    module.publish(self.source, selection, checkpoint=checkpoint)
                self.assertFalse(destination.exists())
                self.assertFalse(list(self.root.glob('.dlms-*.part')))

    def test_linked_destination_parent_is_refused(self):
        linked = self.root/'linked'; linked.symlink_to(self.root, target_is_directory=True)
        for module, suffix in self.each_module():
            with self.subTest(module=module.__name__), self.assertRaises(OSError):
                module.select(linked/('unsafe'+suffix))


if __name__ == '__main__': unittest.main()
