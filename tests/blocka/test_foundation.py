"""No live app: isolated identity, origin and synthetic epoch contracts."""
from __future__ import annotations

import json
import os
import secrets
import unittest
from unittest.mock import patch

from PySide6.QtCore import QUrl

from desktop.isolation import profile_paths
from desktop.profile_state import new_manifest, publish_manifest, read_manifest, synthetic_epoch_change
from desktop.shell import allowed_internal, allowed_external
from dlms.runtime import _desktop_or_default_port


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.name = "blockaunit" + secrets.token_hex(4)
        self.paths = profile_paths(self.name)

    def test_stable_manifest_and_exact_origin(self):
        manifest = new_manifest(self.name, 45123)
        publish_manifest(self.paths, manifest)
        self.assertEqual(read_manifest(self.paths, self.name), manifest)
        self.assertTrue(allowed_internal(QUrl("http://127.0.0.1:45123/library"), 45123))
        for url in ("http://localhost:45123/", "http://127.0.0.1:45124/",
                    "https://127.0.0.1:45123/", "http://u@127.0.0.1:45123/"):
            self.assertFalse(allowed_internal(QUrl(url), 45123))
        self.assertFalse(allowed_external(QUrl("http://127.4.3.2/")))

    def test_manifest_failure_does_not_change_origin(self):
        manifest = new_manifest(self.name, 45123)
        with patch.dict(os.environ, {"DLMS_DESKTOP_TEST_FAIL_MANIFEST": "1"}):
            with self.assertRaises(OSError):
                publish_manifest(self.paths, manifest)
        self.assertIsNone(read_manifest(self.paths, self.name))
        self.assertFalse(list(self.paths["root"].glob(".desktop-profile.json.*.tmp")))

    def test_synthetic_epoch_quarantines_evidence(self):
        original = new_manifest(self.name, 45123)
        publish_manifest(self.paths, original)
        (self.paths["web_storage"] / "synthetic-record").write_text("pending synthetic answer")
        (self.paths["root"] / "recovery-evidence.json").write_text(json.dumps({"records": {"synthetic": "pending"}}))
        updated = synthetic_epoch_change(self.paths, self.name)
        saved = self.paths["root"] / "quarantine" / original["epoch"]
        self.assertEqual(updated["port"], original["port"])
        self.assertNotEqual(updated["epoch"], original["epoch"])
        self.assertEqual((saved / "web_storage" / "synthetic-record").read_text(), "pending synthetic answer")
        self.assertIn("pending", (saved / "recovery-evidence.json").read_text())
        self.assertFalse((self.paths["web_storage"] / "synthetic-record").exists())

    def test_web_default_unchanged(self):
        self.assertEqual(_desktop_or_default_port({}), 9001)
        self.assertEqual(_desktop_or_default_port({"DLMS_DESKTOP_PROFILE": "test", "DLMS_DESKTOP_NONCE": "x", "DLMS_DESKTOP_PORT": "45123"}), 45123)
        with self.assertRaises(ValueError):
            _desktop_or_default_port({"DLMS_DESKTOP_PROFILE": "test", "DLMS_DESKTOP_PORT": "45123"})


if __name__ == "__main__":
    unittest.main()
