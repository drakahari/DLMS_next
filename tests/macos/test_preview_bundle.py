"""Packaging-only checks; no Qt import or installed application is required."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from package_macos.preview_bundle import (
    FAMILIES, QML, OPTIONAL_PLUGINS, exclusion, needed, prune, verify_payload,
)


class PreviewBundleTests(unittest.TestCase):
    def test_reviewed_frameworks_bindings_dylibs_and_qml(self):
        for family in FAMILIES:
            for name in (
                f'PySide6/Qt/lib/Qt{family}.framework/Versions/A/Qt{family}',
                f'Contents/Resources/PySide6/Qt/lib/Qt{family}.framework/Resources/Info.plist',
                f'libQt6{family}.6.dylib', f'PySide6/Qt{family}.abi3.so',
                f'@rpath/Qt{family}',
            ):
                with self.subTest(name=name):
                    self.assertIsNotNone(exclusion(name))
            for root in QML[family]:
                self.assertIsNotNone(exclusion(f'PySide6/Qt/qml/{root}/qmldir'))
                self.assertIsNotNone(exclusion(f'Contents/Resources/PySide6/Qt/qml/{root}/qmldir'))

    def test_family_satellites_are_excluded(self):
        for name in ('QtGraphsWidgets.abi3.so',
                     'PySide6/Qt/lib/QtQuick3DUtils.framework/Versions/A/QtQuick3DUtils',
                     'libQt6QuickTimelineBlendTrees.6.dylib'):
            self.assertIsNotNone(exclusion(name))

    def test_webengine_quick_qml_pdf_and_ocr_are_retained(self):
        for name in (
            'PySide6/Qt/lib/QtWebEngineCore.framework/Versions/A/QtWebEngineCore',
            'PySide6/Qt/lib/QtQuick.framework/Versions/A/QtQuick',
            'PySide6/Qt/lib/QtQml.framework/Versions/A/QtQml',
            'PySide6/Qt/qml/QtQuick/Controls/libqtquickcontrols2plugin.dylib',
            'PySide6/Qt/qml/QtQuick/TimelineExtras/qmldir',
            'PySide6/Qt/lib/QtPdf.framework/Versions/A/QtPdf',
            'ocr/tesseract/bin/tesseract', 'libtiff.6.dylib',
            'static/Quick3D-notes.html',
        ):
            with self.subTest(name=name):
                self.assertIsNone(exclusion(name))

    def test_only_reviewed_optional_consumers_are_removed(self):
        core = ('PySide6/Qt/lib/QtWebEngineCore.framework/Versions/A/QtWebEngineCore', 'core', 'BINARY')
        plugins = [(name, 'plugin', 'BINARY') for name in sorted(OPTIONAL_PLUGINS)]
        kept, data, removed = prune([core, *plugins], [], lambda source: [])
        self.assertEqual(kept, [core])
        self.assertEqual(data, [])
        self.assertEqual({row['path'] for row in removed}, OPTIONAL_PLUGINS)

    def test_unexpected_framework_consumer_fails_closed(self):
        core = ('PySide6/Qt/lib/QtWebEngineCore.framework/Versions/A/QtWebEngineCore', 'core', 'BINARY')
        with self.assertRaisesRegex(ValueError, 'Unexpected retained dependency'):
            prune([core], [], lambda source: ['@rpath/QtCharts.framework/Versions/A/QtCharts'])

    def test_unknown_qml_or_data_consumer_is_not_silently_removed(self):
        for kind in ('BINARY', 'DATA'):
            row = ('PySide6/Qt/qml/QtQuick/Controls/plugin.dylib', 'consumer', kind)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'Unexpected retained dependency'):
                prune([], [row], lambda source: ['@rpath/QtGraphs.framework/Versions/A/QtGraphs'])

    def test_framework_aliases_and_data_alias_chain_are_removed(self):
        library = ('PySide6/Qt/lib/QtCharts.framework/Versions/A/QtCharts', 'library', 'BINARY')
        alias = ('QtCharts', library[0], 'SYMLINK')
        chain = ('renamed-native', 'QtCharts', 'SYMLINK')
        resource = ('PySide6/Qt/lib/QtCharts.framework/Resources', 'Versions/A/Resources', 'SYMLINK')
        kept = ('QtCore', 'PySide6/Qt/lib/QtCore.framework/Versions/A/QtCore', 'SYMLINK')
        b, d, removed = prune([library, kept], [chain, alias, resource], lambda source: [])
        self.assertEqual(b, [kept])
        self.assertEqual(d, [])
        self.assertEqual(len(removed), 4)

    def test_dependency_on_renamed_removed_alias_is_rejected(self):
        library = ('PySide6/Qt/lib/QtCharts.framework/Versions/A/QtCharts', 'library', 'BINARY')
        alias = ('renamed-native', library[0], 'SYMLINK')
        consumer = ('unknown.dylib', 'consumer', 'BINARY')
        with self.assertRaisesRegex(ValueError, 'Unexpected retained dependency'):
            prune([library, consumer], [alias],
                  lambda source: ['@rpath/renamed-native'] if source == 'consumer' else [])

    def test_escaping_and_cyclic_aliases_fail(self):
        cases = [[('evil', '../../outside', 'SYMLINK')],
                 [('evil', '/outside', 'SYMLINK')],
                 [('a', 'b', 'SYMLINK'), ('b', 'a', 'SYMLINK')]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                prune([], rows, lambda source: [])

    def test_load_command_parser_includes_weak_reexport_and_upward_not_id(self):
        output = '''Load command 1
          cmd LC_ID_DYLIB
      cmdsize 72
         name @rpath/self.dylib (offset 24)
Load command 2
          cmd LC_LOAD_DYLIB
         name @rpath/QtCore.framework/Versions/A/QtCore (offset 24)
Load command 3
          cmd LC_LOAD_WEAK_DYLIB
         name /usr/lib/libSystem.B.dylib (offset 24)
Load command 4
          cmd LC_REEXPORT_DYLIB
         name @loader_path/dep.dylib (offset 24)
Load command 5
          cmd LC_LOAD_UPWARD_DYLIB
         name @rpath/up.dylib (offset 24)
'''
        with tempfile.TemporaryDirectory() as directory:
            native = Path(directory) / 'native'
            native.write_bytes(b'\xcf\xfa\xed\xfe' + b'fake')
            completed = subprocess.CompletedProcess([], 0, stdout=output)
            with patch('package_macos.preview_bundle.subprocess.run', return_value=completed) as run:
                self.assertEqual(needed(native), [
                    '@rpath/QtCore.framework/Versions/A/QtCore', '/usr/lib/libSystem.B.dylib',
                    '@loader_path/dep.dylib', '@rpath/up.dylib'])
                run.assert_called_once_with(['/usr/bin/otool', '-l', str(native)],
                                            capture_output=True, text=True, check=True)

    def test_non_native_data_does_not_call_otool(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'resource'
            data.write_bytes(b'resource')
            with patch('package_macos.preview_bundle.subprocess.run') as run:
                self.assertEqual(needed(data), [])
                run.assert_not_called()
            with self.assertRaises(FileNotFoundError):
                needed(data.with_name('missing'))

    def test_payload_rejects_excluded_framework_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / 'Contents/Resources/PySide6/Qt/lib/QtCharts.framework/Resources/Info.plist'
            resource.parent.mkdir(parents=True)
            resource.write_bytes(b'plist')
            with self.assertRaisesRegex(ValueError, 'Excluded component remains'):
                verify_payload(directory)

    def test_payload_dependencies_and_alias_containment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'app'
            root.mkdir()
            native = root / 'native'
            native.write_bytes(b'synthetic')
            (root / 'alias').symlink_to('native')
            verify_payload(root, lambda source: ['/usr/lib/libSystem.B.dylib',
                                                  '/System/Library/Frameworks/AppKit.framework/AppKit',
                                                  '@rpath/QtCore.framework/Versions/A/QtCore'])
            for bad in ('/opt/homebrew/lib/libtiff.dylib', '/Users/builder/lib.dylib',
                        '/usr/lib-untrusted/lib.dylib', 'relative.dylib',
                        '@rpath/QtCharts.framework/Versions/A/QtCharts'):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    verify_payload(root, lambda source: [bad])
            outside = Path(directory) / 'outside'
            outside.write_bytes(b'outside')
            (root / 'escape').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'Escaping packaged alias'):
                verify_payload(root, lambda source: [])

    def test_payload_refuses_dangling_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'dangling').symlink_to('missing')
            with self.assertRaises(FileNotFoundError):
                verify_payload(directory)


if __name__ == '__main__':
    unittest.main()
