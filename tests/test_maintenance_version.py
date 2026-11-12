"""Shared version and honest unpublished Desktop build identity."""
import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop import build_info

ROOT = Path(__file__).resolve().parents[1]


class MaintenanceVersionTests(unittest.TestCase):
    def test_source_about_and_backend_use_one_application_version_without_startup(self):
        self.assertEqual(build_info.application_version(), '3.3.2 RC1')
        self.assertEqual(build_info.information()['application_version'], '3.3.2 RC1')
        self.assertIn('unpublished', build_info.information()['release'])

    def test_version_parser_rejects_ambiguous_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'app.py').write_text('APP_VERSION="3.3.1"\nAPP_VERSION="3.3.0"\n')
            with self.assertRaises(ValueError):
                build_info.application_version(root)

    def test_frozen_public_identity_is_strict_and_expanded_provenance_is_separate(self):
        identity = dict(application_version='3.3.1', release='linux-331-preview1-candidate',
                        source_commit='a'*40, target='Linux x86_64', support='Unpublished preview candidate')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'desktop_assets').mkdir()
            path = root/'desktop_assets/build-info.json'
            path.write_text(json.dumps(identity))
            with patch.object(build_info.sys, 'frozen', True, create=True), patch.object(build_info.sys, '_MEIPASS', directory, create=True):
                self.assertEqual(build_info.information(), identity)
                path.write_text(json.dumps({**identity, 'application_base': 'a'*40}))
                with self.assertRaises(ValueError):
                    build_info.information()
        tree = ast.parse((ROOT/'package_macos/build.py').read_text())
        assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'public_identity' for target in node.targets))
        self.assertEqual(set(ast.literal_eval(assignment.value.generators[0].iter)), set(identity))
