"""Focused regression coverage for the durable Law Study import workflow."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-law-workflow-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms
from tests.csrf_test_utils import csrf_token


RAW_PACKET = """Sources Used
Official reporter citation.

1. Case Brief
Full case name and citation: Palsgraf v. Long Island Railroad Co.
Facts and holding.

2. Socratic Review
1. What duty question did the court decide?

2A. Socratic Answer Key
1. Foreseeability limited the duty analysis.

3. IRAC Drill
Issue: Was the plaintiff foreseeable?

4. Rule Flashcards
Q: What limits negligence duty?
A: Foreseeability.
"""


class LawStudyWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._original_paths = {
            name: getattr(dlms, name)
            for name in (
                "APP_DATA_DIR",
                "CONFIG_FOLDER",
                "PORTAL_CONFIG",
                "LAW_FOLDER",
                "LAW_CASES_FOLDER",
                "LAW_IMPORTS_FOLDER",
                "LAW_EXPORTS_FOLDER",
                "LAW_REGISTRY",
            )
        }

    @classmethod
    def tearDownClass(cls):
        for name, value in cls._original_paths.items():
            setattr(dlms, name, value)
        _TEMP.cleanup()

    def setUp(self):
        self.root = Path(_TEMP.name)
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)

        config_folder = self.root / "config"
        law_folder = self.root / "law"
        dlms.APP_DATA_DIR = str(self.root)
        dlms.CONFIG_FOLDER = str(config_folder)
        dlms.PORTAL_CONFIG = str(config_folder / "portal.json")
        dlms.LAW_FOLDER = str(law_folder)
        dlms.LAW_CASES_FOLDER = str(law_folder / "cases")
        dlms.LAW_IMPORTS_FOLDER = str(law_folder / "imports")
        dlms.LAW_EXPORTS_FOLDER = str(law_folder / "exports")
        dlms.LAW_REGISTRY = str(config_folder / "law.json")
        for folder in (config_folder, law_folder / "cases", law_folder / "imports", law_folder / "exports"):
            folder.mkdir(parents=True, exist_ok=True)

    def _set_pending_workflow(self, *, case_name="Palsgraf Review", case_slug="palsgraf", course="Torts"):
        registry = dlms.load_law_registry()
        registry["pending_case_workflow"] = {
            "case_name": case_name,
            "case_slug": case_slug,
            "course": course,
            "created_at": "2026-08-30T12:00:00",
        }
        dlms.save_law_registry(registry)

    def _save_and_preview(self, client, raw_packet=RAW_PACKET):
        response = client.post(
            "/law/import",
            data={
                "csrf_token": csrf_token(client, "/law/import"),
                "raw_packet": raw_packet,
                "action": "save_and_preview",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        self.assertIn("/law/imports/", response.headers["Location"])
        return response.headers["Location"].rsplit("/", 1)[-1]

    def _create_case(self, client, filename):
        response = client.post(
            f"/law/imports/{filename}/create_case",
            data={"csrf_token": csrf_token(client, f"/law/imports/{filename}")},
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        return response

    def test_save_and_preview_persists_raw_packet_then_opens_its_parser_view(self):
        self._set_pending_workflow()
        client = dlms.app.test_client()

        filename = self._save_and_preview(client)

        self.assertEqual(RAW_PACKET.strip(), Path(dlms.LAW_IMPORTS_FOLDER, filename).read_text(encoding="utf-8"))
        self.assertEqual([filename], sorted(path.name for path in Path(dlms.LAW_IMPORTS_FOLDER).glob("*.txt")))
        preview = client.get(f"/law/imports/{filename}")
        self.assertEqual(200, preview.status_code)
        self.assertIn("Recognized Sections", preview.get_data(as_text=True))
        self.assertEqual([], dlms.load_law_registry()["cases"])

    def test_import_page_makes_durable_save_and_preview_the_primary_happy_path(self):
        client = dlms.app.test_client()

        page = client.get("/law/import").get_data(as_text=True)
        landing = client.get("/law").get_data(as_text=True)

        self.assertIn('value="save_and_preview" class="law-primary-action">Save &amp; Preview Case Packet', page)
        self.assertIn("Check Pasted Text", page)
        self.assertIn("Save Raw Packet Only", page)
        self.assertNotIn("Preview Packet</button>", page)
        self.assertIn("ARCHIVE / RECOVERY", landing)
        self.assertIn("guided and manual imports", landing)

    def test_failed_raw_save_creates_no_structured_case(self):
        blocked_path = Path(dlms.LAW_IMPORTS_FOLDER)
        blocked_path.rmdir()
        blocked_path.write_text("not a directory", encoding="utf-8")
        client = dlms.app.test_client()

        response = client.post(
            "/law/import",
            data={
                "csrf_token": csrf_token(client, "/law/import"),
                "raw_packet": RAW_PACKET,
                "action": "save_and_preview",
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("failed to save raw case packet", response.get_data(as_text=True).lower())
        self.assertEqual([], dlms.load_law_registry()["cases"])

    def test_create_case_uses_saved_import_metadata_and_opens_exact_case(self):
        self._set_pending_workflow(case_name="Palsgraf Case Review", case_slug="palsgraf", course="Torts")
        client = dlms.app.test_client()
        filename = self._save_and_preview(client)

        response = self._create_case(client, filename)
        location = response.headers["Location"]
        self.assertRegex(location, r"^/law/cases/law_case_")
        case_id = location.rsplit("/", 1)[-1]
        registry = dlms.load_law_registry()
        self.assertNotIn("pending_case_workflow", registry)
        self.assertEqual(1, len(registry["cases"]))
        saved_case = registry["cases"][0]
        self.assertEqual(case_id, saved_case["id"])
        self.assertEqual(filename, saved_case["source_import"])
        self.assertEqual("Palsgraf Case Review", saved_case["title"])
        self.assertEqual("Torts", saved_case["course"])
        case_data = json.loads(Path(dlms.LAW_CASES_FOLDER, saved_case["file"]).read_text(encoding="utf-8"))
        self.assertEqual(filename, case_data["source_import"])
        self.assertIn("Facts and holding", case_data["sections"]["case_brief"])
        self.assertEqual(200, client.get(location).status_code)

    def test_manual_import_without_pending_metadata_still_creates_case(self):
        client = dlms.app.test_client()
        filename = self._save_and_preview(client)

        response = self._create_case(client, filename)
        saved_case = dlms.load_law_registry()["cases"][0]
        self.assertEqual("Uncategorized", saved_case["course"])
        self.assertEqual(filename, saved_case["source_import"])
        self.assertEqual(200, client.get(response.headers["Location"]).status_code)

    def test_cancel_clears_only_pending_workflow_metadata(self):
        self._set_pending_workflow()
        raw_file = Path(dlms.LAW_IMPORTS_FOLDER, "law_import_20260830_120000_palsgraf.txt")
        raw_file.write_text(RAW_PACKET, encoding="utf-8")
        client = dlms.app.test_client()

        response = client.post(
            "/law/workflow/cancel",
            data={"csrf_token": csrf_token(client, "/law/import")},
            follow_redirects=False,
        )

        self.assertEqual(302, response.status_code)
        self.assertNotIn("pending_case_workflow", dlms.load_law_registry())
        self.assertEqual(RAW_PACKET, raw_file.read_text(encoding="utf-8"))

    def test_repeated_create_submission_reopens_existing_case_without_duplicate(self):
        client = dlms.app.test_client()
        filename = self._save_and_preview(client)

        first = self._create_case(client, filename)
        second = self._create_case(client, filename)

        self.assertEqual(first.headers["Location"], second.headers["Location"])
        registry = dlms.load_law_registry()
        self.assertEqual(1, len(registry["cases"]))
        self.assertEqual(filename, registry["cases"][0]["source_import"])

    def test_deleting_raw_import_does_not_damage_existing_structured_case(self):
        client = dlms.app.test_client()
        filename = self._save_and_preview(client)
        case_location = self._create_case(client, filename).headers["Location"]

        response = client.post(
            f"/law/imports/{filename}/delete",
            data={"csrf_token": csrf_token(client, f"/law/imports/{filename}")},
            follow_redirects=False,
        )

        self.assertEqual(302, response.status_code)
        self.assertFalse(Path(dlms.LAW_IMPORTS_FOLDER, filename).exists())
        self.assertEqual(1, len(dlms.load_law_registry()["cases"]))
        self.assertEqual(200, client.get(case_location).status_code)


if __name__ == "__main__":
    unittest.main()
