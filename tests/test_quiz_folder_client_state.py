"""DLMS-116 Quiz Library browser-state contract regressions."""

import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


ROOT = Path(__file__).resolve().parents[1]
LIBRARY_TEMPLATE = ROOT / "templates" / "quiz" / "library.html"


class QuizFolderClientStateTests(unittest.TestCase):
    def test_library_emits_all_canonical_folder_names_for_client_reconciliation(self):
        portal = {
            "quiz_folders": ["Uncategorized", "Configured Course"],
            "hidden_quiz_folders": [],
        }
        registry = [
            {
                "id": 1,
                "title": "Legacy Quiz",
                "html": "legacy.html",
                "folder": "Legacy Course",
            }
        ]

        with tempfile.TemporaryDirectory(
            prefix="dlms-folder-client-state-"
        ) as directory:
            config = Path(directory) / "config"
            config.mkdir()
            portal_path = config / "portal.json"
            registry_path = config / "quizzes.json"
            portal_path.write_text(json.dumps(portal), encoding="utf-8")
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal_path)), \
                    mock.patch.object(dlms, "QUIZ_REGISTRY", str(registry_path)), \
                    mock.patch.object(dlms, "discover_content_packs", return_value={}):
                response = dlms.app.test_client().get("/library")

            self.assertEqual(200, response.status_code)
            page = response.get_data(as_text=True)
            response.close()
            saved_portal = json.loads(portal_path.read_text(encoding="utf-8"))

        identity_data = re.search(
            r'<script id="libraryFolderIdentityData" type="application/json">'
            r'(.*?)</script>',
            page,
        )
        self.assertIsNotNone(identity_data)
        self.assertEqual(
            ["Uncategorized", "Configured Course", "Legacy Course"],
            json.loads(identity_data.group(1)),
        )
        self.assertEqual(portal, saved_portal)

    def test_client_state_uses_the_existing_key_and_dlms_115_identity_rule(self):
        source = LIBRARY_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn(
            'collapsedLibraryFoldersStorageKey = "dlmsCollapsedLibraryFolders"',
            source,
        )
        self.assertIn(
            'return String(folderName || "").trim().toLowerCase();',
            source,
        )
        self.assertIn("function normalizeCollapsedLibraryFolders", source)
        self.assertIn("function reconcileCollapsedLibraryFolders", source)
        self.assertIn("const collapsedFolders = reconcileCollapsedLibraryFolders();", source)
        self.assertIn("canonicalFolders.get(identity)", source)
        self.assertIn("seen.has(identity)", source)

    def test_rename_and_delete_forms_track_only_pending_client_state_mutations(self):
        source = LIBRARY_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn(
            'pendingLibraryFolderMutationStorageKey = '
            '"dlmsPendingLibraryFolderMutation"',
            source,
        )
        self.assertIn('document.querySelectorAll(".rename-folder-form")', source)
        self.assertIn('document.querySelectorAll(".delete-folder-form")', source)
        self.assertIn('type: "rename"', source)
        self.assertIn('type: "delete"', source)
        self.assertIn("oldStillExists", source)
        self.assertIn("renameSucceeded", source)
        self.assertIn("!canonicalFolders.has(deletedIdentity)", source)
        self.assertNotIn("fetch(\"/rename_quiz_folder\"", source)
        self.assertNotIn("fetch(\"/delete_quiz_folder\"", source)


if __name__ == "__main__":
    unittest.main()
