"""DLMS-091 regression coverage for malformed portal structured fields."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


class PortalStructuredNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="dlms-portal-structured-normalization-"
        )
        self.addCleanup(self.temporary.cleanup)
        self.portal_path = Path(self.temporary.name) / "config" / "portal.json"
        self.portal_path.parent.mkdir(parents=True)

    def test_malformed_quiz_folders_are_preserved_then_normalized_before_use(self):
        malformed = b'{"title":"Recovery repro","quiz_folders":"oops"}'
        self.portal_path.write_bytes(malformed)

        with mock.patch.object(dlms, "PORTAL_CONFIG", str(self.portal_path)):
            config = dlms.load_portal_config()
            self.assertEqual(["Uncategorized"], config["quiz_folders"])
            self.assertEqual(["Uncategorized"], dlms.get_quiz_folders())

            recovery_copy = Path(str(self.portal_path) + ".corrupt")
            self.assertEqual(malformed, recovery_copy.read_bytes())

            # A later normal save consumes only the safe normalized value and
            # leaves the original malformed document available for recovery.
            dlms.save_quiz_folders(dlms.get_quiz_folders())
            self.assertEqual(malformed, recovery_copy.read_bytes())
            self.assertEqual(
                ["Uncategorized"],
                json.loads(self.portal_path.read_text(encoding="utf-8"))["quiz_folders"],
            )

    def test_valid_custom_quiz_folders_remain_unchanged(self):
        valid = {
            "title": "Existing DLMS",
            "quiz_folders": ["Uncategorized", "My Courses", "A+"],
        }
        self.portal_path.write_text(json.dumps(valid, indent=2), encoding="utf-8")

        with mock.patch.object(dlms, "PORTAL_CONFIG", str(self.portal_path)):
            config = dlms.load_portal_config()
            folders = dlms.get_quiz_folders()

        self.assertEqual(valid["quiz_folders"], config["quiz_folders"])
        self.assertEqual(valid["quiz_folders"], folders)
        self.assertEqual(valid, json.loads(self.portal_path.read_text(encoding="utf-8")))
        self.assertFalse(Path(str(self.portal_path) + ".corrupt").exists())


if __name__ == "__main__":
    unittest.main()
