"""DLMS-089 regression coverage for coordinated Law case mutations."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
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


class LawMutationAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="dlms-law-mutation-atomicity-"
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        config_folder = self.root / "config"
        law_folder = self.root / "law"
        self.cases_folder = law_folder / "cases"
        self.imports_folder = law_folder / "imports"
        self.exports_folder = law_folder / "exports"
        self.registry_path = config_folder / "law.json"
        for folder in (
            config_folder,
            self.cases_folder,
            self.imports_folder,
            self.exports_folder,
        ):
            folder.mkdir(parents=True, exist_ok=True)

        path_patcher = mock.patch.multiple(
            dlms,
            APP_DATA_DIR=str(self.root),
            CONFIG_FOLDER=str(config_folder),
            PORTAL_CONFIG=str(config_folder / "portal.json"),
            LAW_FOLDER=str(law_folder),
            LAW_CASES_FOLDER=str(self.cases_folder),
            LAW_IMPORTS_FOLDER=str(self.imports_folder),
            LAW_EXPORTS_FOLDER=str(self.exports_folder),
            LAW_REGISTRY=str(self.registry_path),
        )
        path_patcher.start()
        self.addCleanup(path_patcher.stop)

        self.client = dlms.app.test_client()
        self.csrf = csrf_token(self.client, "/law")
        self.real_atomic_write = dlms._atomic_write_json

    def _write_json(self, path, value):
        Path(path).write_text(json.dumps(value, indent=2), encoding="utf-8")

    def _read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def _seed_cases(self):
        target_case = {
            "id": "case-target",
            "type": "law_case_review",
            "title": "Original title",
            "course": "Torts",
            "source_import": "target.txt",
            "created_at": "2026-09-01T10:00:00",
            "updated_at": "2026-09-01T10:00:00",
            "verified": False,
            "sources_used": "Reporter",
            "sections": {
                "case_brief": "Original brief",
                "socratic_review": "1. What duty was owed?",
                "socratic_answer_key": "1. A foreseeable duty.",
                "irac_drill": "Analyze duty.",
                "rule_flashcards": "Q: Duty?\nA: Foreseeability.",
            },
            "student_notes": "Original notes",
            "socratic_student_answers": {"q1": "Original answer"},
            "irac_student_response": {
                "issue": "Old issue",
                "rule": "Old rule",
                "analysis": "Old analysis",
                "conclusion": "Old conclusion",
            },
        }
        other_case = {
            "id": "case-other",
            "type": "law_case_review",
            "title": "Unrelated case",
            "course": "Contracts",
            "created_at": "2026-09-01T11:00:00",
            "updated_at": "2026-09-01T11:00:00",
            "sections": {},
            "student_notes": "Keep me",
        }
        registry = {
            "version": "1",
            "cases": [
                {
                    "id": "case-target",
                    "title": "Original title",
                    "course": "Torts",
                    "file": "case-target.json",
                    "source_import": "target.txt",
                    "created_at": "2026-09-01T10:00:00",
                    "updated_at": "2026-09-01T10:00:00",
                    "hidden": False,
                },
                {
                    "id": "case-other",
                    "title": "Unrelated case",
                    "course": "Contracts",
                    "file": "case-other.json",
                    "created_at": "2026-09-01T11:00:00",
                    "updated_at": "2026-09-01T11:00:00",
                    "hidden": False,
                },
            ],
            "folders": ["Torts", "Contracts"],
        }
        self._write_json(self.cases_folder / "case-target.json", target_case)
        self._write_json(self.cases_folder / "case-other.json", other_case)
        self._write_json(self.registry_path, registry)
        return copy.deepcopy(registry), copy.deepcopy(target_case), copy.deepcopy(other_case)

    def _fail_atomic_path(self, failed_path):
        failed_path = Path(failed_path)

        def side_effect(path, payload, **kwargs):
            if Path(path) == failed_path:
                raise OSError(f"simulated write failure for {failed_path.name}")
            return self.real_atomic_write(path, payload, **kwargs)

        return mock.patch.object(dlms, "_atomic_write_json", side_effect=side_effect)

    def _assert_preserved(self, registry, target_case, other_case):
        self.assertEqual(registry, self._read_json(self.registry_path))
        self.assertEqual(
            target_case, self._read_json(self.cases_folder / "case-target.json")
        )
        self.assertEqual(
            other_case, self._read_json(self.cases_folder / "case-other.json")
        )

    def test_save_law_registry_propagates_atomic_write_failure(self):
        with self._fail_atomic_path(self.registry_path):
            with self.assertRaisesRegex(OSError, "simulated write failure"):
                dlms.save_law_registry({"version": "1", "cases": [], "folders": []})

    def test_delete_registry_failure_keeps_case_and_does_not_report_success(self):
        registry, target_case, other_case = self._seed_cases()

        with self._fail_atomic_path(self.registry_path):
            response = self.client.post(
                "/law/cases/case-target/delete",
                data={"csrf_token": self.csrf},
                follow_redirects=False,
            )

        self.assertEqual(500, response.status_code)
        self.assertNotIn("deleted=1", response.headers.get("Location", ""))
        self._assert_preserved(registry, target_case, other_case)

    def test_delete_remove_failure_rolls_registry_back_without_data_loss(self):
        registry, target_case, other_case = self._seed_cases()
        target_path = self.cases_folder / "case-target.json"
        real_remove = os.remove

        def fail_target_remove(path):
            if Path(path) == target_path:
                raise OSError("simulated case removal failure")
            return real_remove(path)

        with mock.patch.object(dlms.os, "remove", side_effect=fail_target_remove):
            response = self.client.post(
                "/law/cases/case-target/delete",
                data={"csrf_token": self.csrf},
                follow_redirects=False,
            )

        self.assertEqual(500, response.status_code)
        self.assertNotIn("deleted=1", response.headers.get("Location", ""))
        self._assert_preserved(registry, target_case, other_case)

    def test_create_registry_failure_removes_new_case_and_preserves_import(self):
        registry, target_case, other_case = self._seed_cases()
        registry["pending_case_workflow"] = {
            "case_name": "New case",
            "case_slug": "new-case",
            "course": "Torts",
            "created_at": "2026-09-01T12:00:00",
        }
        self._write_json(self.registry_path, registry)
        import_path = self.imports_folder / "new-case.txt"
        import_path.write_text(RAW_PACKET, encoding="utf-8")

        with self._fail_atomic_path(self.registry_path):
            response = self.client.post(
                "/law/imports/new-case.txt/create_case",
                data={"csrf_token": self.csrf},
                follow_redirects=False,
            )

        self.assertEqual(500, response.status_code)
        self.assertEqual("", response.headers.get("Location", ""))
        self._assert_preserved(registry, target_case, other_case)
        self.assertEqual(RAW_PACKET, import_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {"case-target.json", "case-other.json"},
            {path.name for path in self.cases_folder.glob("*.json")},
        )

    def test_create_case_file_failure_does_not_change_registry(self):
        registry, target_case, other_case = self._seed_cases()
        import_path = self.imports_folder / "new-case.txt"
        import_path.write_text(RAW_PACKET, encoding="utf-8")

        def fail_new_case_write(path, payload, **kwargs):
            if Path(path).parent == self.cases_folder and Path(path).name not in {
                "case-target.json",
                "case-other.json",
            }:
                raise OSError("simulated new case write failure")
            return self.real_atomic_write(path, payload, **kwargs)

        with mock.patch.object(
            dlms, "_atomic_write_json", side_effect=fail_new_case_write
        ):
            response = self.client.post(
                "/law/imports/new-case.txt/create_case",
                data={"csrf_token": self.csrf},
                follow_redirects=False,
            )

        self.assertEqual(500, response.status_code)
        self._assert_preserved(registry, target_case, other_case)
        self.assertEqual(
            {"case-target.json", "case-other.json"},
            {path.name for path in self.cases_folder.glob("*.json")},
        )

    def test_all_case_updates_roll_back_when_registry_write_fails(self):
        updates = (
            (
                "/law/cases/case-target/update_details",
                {"title": "Changed title", "course": "Evidence"},
                "updated=1",
            ),
            (
                "/law/cases/case-target/update_notes",
                {"student_notes": "Changed notes"},
                "notes_updated=1",
            ),
            (
                "/law/cases/case-target/update_socratic_answers",
                {"answer_q1": "Changed answer"},
                "socratic_answers_updated=1",
            ),
            (
                "/law/cases/case-target/update_irac_response",
                {
                    "irac_issue": "Changed issue",
                    "irac_rule": "Changed rule",
                    "irac_analysis": "Changed analysis",
                    "irac_conclusion": "Changed conclusion",
                },
                "irac_updated=1",
            ),
        )

        for route, form_data, success_marker in updates:
            with self.subTest(route=route):
                registry, target_case, other_case = self._seed_cases()
                with self._fail_atomic_path(self.registry_path):
                    response = self.client.post(
                        route,
                        data={"csrf_token": self.csrf, **form_data},
                        follow_redirects=False,
                    )

                self.assertEqual(500, response.status_code)
                self.assertNotIn(
                    success_marker, response.headers.get("Location", "")
                )
                self._assert_preserved(registry, target_case, other_case)

    def test_update_case_file_failure_does_not_change_registry(self):
        registry, target_case, other_case = self._seed_cases()

        with self._fail_atomic_path(self.cases_folder / "case-target.json"):
            response = self.client.post(
                "/law/cases/case-target/update_details",
                data={
                    "csrf_token": self.csrf,
                    "title": "Changed title",
                    "course": "Evidence",
                },
                follow_redirects=False,
            )

        self.assertEqual(500, response.status_code)
        self._assert_preserved(registry, target_case, other_case)

    def test_pending_workflow_registry_failures_do_not_report_success(self):
        original_registry = {
            "version": "1",
            "cases": [],
            "folders": ["Torts"],
            "pending_case_workflow": {
                "case_name": "Existing workflow",
                "case_slug": "existing-workflow",
                "course": "Torts",
                "created_at": "2026-09-01T12:00:00",
            },
        }
        self._write_json(self.registry_path, original_registry)

        with self._fail_atomic_path(self.registry_path):
            create_response = self.client.post(
                "/law/create",
                data={
                    "csrf_token": self.csrf,
                    "case_name": "Replacement workflow",
                    "course": "Contracts",
                    "ai_provider": "chatgpt",
                },
                follow_redirects=False,
            )
            cancel_response = self.client.post(
                "/law/workflow/cancel",
                data={"csrf_token": self.csrf},
                follow_redirects=False,
            )

        self.assertEqual(500, create_response.status_code)
        self.assertEqual(500, cancel_response.status_code)
        self.assertEqual("", create_response.headers.get("Location", ""))
        self.assertEqual("", cancel_response.headers.get("Location", ""))
        self.assertEqual(original_registry, self._read_json(self.registry_path))

    def test_successful_create_updates_and_delete_preserve_existing_behavior(self):
        registry, _, other_case = self._seed_cases()
        registry["cases"] = [registry["cases"][1]]
        self._write_json(self.registry_path, registry)
        (self.cases_folder / "case-target.json").unlink()
        import_path = self.imports_folder / "new-case.txt"
        import_path.write_text(RAW_PACKET, encoding="utf-8")

        create_response = self.client.post(
            "/law/imports/new-case.txt/create_case",
            data={"csrf_token": self.csrf},
            follow_redirects=False,
        )
        self.assertEqual(302, create_response.status_code)
        case_id = create_response.headers["Location"].rsplit("/", 1)[-1]
        created_entry = next(
            case
            for case in dlms.load_law_registry()["cases"]
            if case["id"] == case_id
        )
        case_path = self.cases_folder / created_entry["file"]
        self.assertTrue(case_path.is_file())

        requests = (
            (
                f"/law/cases/{case_id}/update_details",
                {"title": "Updated title", "course": "Evidence"},
                "updated=1",
            ),
            (
                f"/law/cases/{case_id}/update_notes",
                {"student_notes": "Updated notes"},
                "notes_updated=1",
            ),
            (
                f"/law/cases/{case_id}/update_socratic_answers",
                {"answer_q1": "Updated Socratic answer"},
                "socratic_answers_updated=1",
            ),
            (
                f"/law/cases/{case_id}/update_irac_response",
                {
                    "irac_issue": "Updated issue",
                    "irac_rule": "Updated rule",
                    "irac_analysis": "Updated analysis",
                    "irac_conclusion": "Updated conclusion",
                },
                "irac_updated=1",
            ),
        )
        for route, form_data, success_marker in requests:
            response = self.client.post(
                route,
                data={"csrf_token": self.csrf, **form_data},
                follow_redirects=False,
            )
            self.assertEqual(302, response.status_code)
            self.assertIn(success_marker, response.headers["Location"])

        updated_case = self._read_json(case_path)
        self.assertEqual("Updated title", updated_case["title"])
        self.assertEqual("Evidence", updated_case["course"])
        self.assertEqual("Updated notes", updated_case["student_notes"])
        self.assertEqual(
            "Updated Socratic answer",
            updated_case["socratic_student_answers"]["q1"],
        )
        self.assertEqual(
            "Updated analysis", updated_case["irac_student_response"]["analysis"]
        )
        updated_entry = next(
            case
            for case in dlms.load_law_registry()["cases"]
            if case["id"] == case_id
        )
        self.assertEqual("Updated title", updated_entry["title"])
        self.assertEqual("Evidence", updated_entry["course"])

        delete_response = self.client.post(
            f"/law/cases/{case_id}/delete",
            data={"csrf_token": self.csrf},
            follow_redirects=False,
        )
        self.assertEqual(302, delete_response.status_code)
        self.assertIn("deleted=1", delete_response.headers["Location"])
        self.assertFalse(case_path.exists())
        remaining_registry = dlms.load_law_registry()
        self.assertEqual(["case-other"], [c["id"] for c in remaining_registry["cases"]])
        self.assertEqual(
            other_case, self._read_json(self.cases_folder / "case-other.json")
        )


if __name__ == "__main__":
    unittest.main()
