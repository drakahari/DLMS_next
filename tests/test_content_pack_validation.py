"""DLMS Study Pack validation regression tests.
Run from the project root with: python -m unittest tests.test_content_pack_validation
The suite uses an isolated temporary APP_DATA_DIR and never touches real DLMS data.
"""
import io, json, os, tempfile, unittest, zipfile
from pathlib import Path
from unittest import mock

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-pack-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms
from tests.csrf_test_utils import csrf_token


def _bind_dlms_test_paths():
    """Rebind app module paths so this suite is isolated regardless of import order."""
    root = Path(_TEMP.name)
    dlms.APP_DATA_DIR = str(root)
    dlms.CONTENT_PACK_FOLDER = str(root / "content_packs")
    dlms.QUIZ_ASSET_FOLDER = str(root / "quiz_assets")
    dlms.DATA_FOLDER = str(root / "data")
    dlms.QUIZ_FOLDER = str(root / "quizzes")
    dlms.CONFIG_FOLDER = str(root / "config")
    dlms.REGISTRY_FILE = str(root / "config" / "quizzes.json")
    dlms.CONTENT_PACK_STAGING_FOLDER = str(root / "content_pack_staging")
    for path in (
        dlms.CONTENT_PACK_FOLDER,
        dlms.QUIZ_ASSET_FOLDER,
        dlms.DATA_FOLDER,
        dlms.QUIZ_FOLDER,
        dlms.CONFIG_FOLDER,
        dlms.CONTENT_PACK_STAGING_FOLDER,
    ):
        os.makedirs(path, exist_ok=True)


class ContentPackValidationTests(unittest.TestCase):
    def setUp(self):
        _bind_dlms_test_paths()
    def make_pack(self, name="DLMS_Study_test"):
        root = Path(_TEMP.name)/name
        (root/"data").mkdir(parents=True, exist_ok=True)
        manifest = {"schema_version":1,"id":"study_test","name":"Study Test","version":"1.0.0","content_domain":"it_cybersecurity","datasets":[{"id":"terms","title":"Terms","type":"matching","path":"data/terms.json"}],"image_datasets":[],"quiz_datasets":[]}
        data = {"schema_version":1,"id":"terms","title":"Terms","source":{"organization":"Test","license":"CC0"},"terms":[{"term":"Layer","definition":"A level in a model."},{"term":"Frame","definition":"A data-link unit."}]}
        (root/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
        (root/"data/terms.json").write_text(json.dumps(data),encoding="utf-8")
        (root/"PACK_VALIDATION.json").write_text(json.dumps({"schema_version":1,"pack_id":"study_test","overall_status":"PASS","checks":[]}),encoding="utf-8")
        return root

    def make_mixed_choice_pack(self, name, questions, *, pack_id="study_choice"):
        root = self.make_pack(name)
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["id"] = pack_id
        manifest["quiz_datasets"] = [{
            "id": "questions", "title": "Questions", "type": "quiz",
            "path": "data/questions.json",
        }]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        data = {
            "schema_version": 1,
            "id": "questions",
            "title": "Questions",
            "source": {"organization": "DLMS Test", "license": "CC0"},
            "questions": questions,
        }
        (root / "data" / "questions.json").write_text(json.dumps(data), encoding="utf-8")
        return root

    def test_valid_matching_pack_passes(self):
        root = self.make_pack()
        report = dlms._validate_staged_content_pack(str(root))
        self.assertTrue(report["valid"], report["errors"])

    def test_mixed_choice_questions_are_normalized_and_preserve_tags_compatibility(self):
        root = self.make_mixed_choice_pack("DLMS_Study_choice_valid", [{
            "type": "choice",
            "question": "Which option is documented?",
            "tags": "choice-skill, documented-option",
            "explanation": "The documented option is supported by the source.",
            "choices": [
                {"label": "Z", "text": "Correct", "is_correct": True},
                {"label": "Q", "text": "Incorrect", "is_correct": False},
            ],
        }])
        report = dlms._validate_staged_content_pack(str(root))
        self.assertTrue(report["valid"], report["errors"])

        installed = Path(dlms.CONTENT_PACK_FOLDER) / root.name
        root.rename(installed)
        data = dlms.load_content_pack_quiz_dataset("study_choice", "questions")
        question = data["questions"][0]
        self.assertEqual(["A", "B"], [choice["label"] for choice in question["choices"]])
        self.assertEqual(["choice-skill", "documented-option"], question["concepts"])
        self.assertNotIn("tags", question)

    def test_mixed_choice_validation_rejects_malformed_structure_and_truthy_flags(self):
        cases = {
            "missing-choices": {
                "type": "choice", "question": "Missing choices", "choices": "not-a-list",
            },
            "empty-choice": {
                "type": "choice", "question": "Empty choice", "choices": [
                    {"text": "", "is_correct": True}, {"text": "Other", "is_correct": False},
                ],
            },
            "truthy-string": {
                "type": "choice", "question": "Truthy string", "choices": [
                    {"text": "Correct", "is_correct": "false"}, {"text": "Other", "is_correct": False},
                ],
            },
            "duplicate-text": {
                "type": "choice", "question": "Duplicate text", "choices": [
                    {"text": " Same answer ", "is_correct": True}, {"text": "same   answer", "is_correct": False},
                ],
            },
            "no-correct": {
                "type": "choice", "question": "No correct", "choices": [
                    {"text": "One", "is_correct": False}, {"text": "Two", "is_correct": False},
                ],
            },
            "too-many": {
                "type": "choice", "question": "Too many", "choices": [
                    {"text": f"Choice {index}", "is_correct": index == 0}
                    for index in range(27)
                ],
            },
        }
        for name, question in cases.items():
            with self.subTest(name=name):
                root = self.make_mixed_choice_pack(
                    f"DLMS_Study_choice_{name}", [question], pack_id=f"study_choice_{name}"
                )
                report = dlms._validate_staged_content_pack(str(root))
                self.assertFalse(report["valid"])
                self.assertTrue(report["errors"])

    def test_ai_workflow_requires_exactly_one_correct_choice_but_manual_pack_keeps_multi_select(self):
        question = {
            "type": "choice", "question": "Select the valid options.", "choices": [
                {"text": "One", "is_correct": True}, {"text": "Two", "is_correct": True},
            ],
        }
        root = self.make_mixed_choice_pack("DLMS_Study_choice_multi", [question])
        manual_report = dlms._validate_staged_content_pack(str(root))
        ai_report = dlms._validate_staged_content_pack(str(root), require_single_select=True)
        self.assertTrue(manual_report["valid"], manual_report["errors"])
        self.assertFalse(ai_report["valid"])
        self.assertTrue(any("exactly one correct choice" in error for error in ai_report["errors"]))

    def test_validator_warns_for_pathological_answer_position_concentration(self):
        questions = [
            {
                "type": "choice",
                "question": f"Question {number}",
                "choices": [
                    {"text": f"Correct {number}", "is_correct": True},
                    {"text": f"Distractor B {number}", "is_correct": False},
                    {"text": f"Distractor C {number}", "is_correct": False},
                    {"text": f"Distractor D {number}", "is_correct": False},
                ],
            }
            for number in range(1, 26)
        ]
        root = self.make_mixed_choice_pack(
            "DLMS_Study_choice_all_a", questions, pack_id="study_choice_all_a"
        )

        report = dlms._validate_staged_content_pack(
            str(root), require_single_select=True
        )

        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(any(
            "25 of 25 single-select questions use position A" in warning
            for warning in report["warnings"]
        ))
        distribution_check = next(
            check for check in report["checks"]
            if check["name"] == "Answer-position distribution"
        )
        self.assertEqual("WARN", distribution_check["status"])

    def test_validation_review_renders_separate_confirmation_and_action_rows(self):
        metadata = {
            "uploaded_name": "DLMS_Study_linux_permissions.zip",
            "file_count": 11,
            "uncompressed_bytes": 209715,
        }
        base_report = {
            "valid": True,
            "pack_name": "DLMS Study — Linux Permissions",
            "dataset_count": 1,
            "checks": [{"status": "PASS", "name": "Manifest", "detail": "Valid"}],
            "errors": [],
            "warnings": [],
        }
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_load_staged_content_pack", return_value=("stage", "pack", metadata)):
            for warnings in ([], ["Optional source note is absent."]):
                with self.subTest(warnings=bool(warnings)):
                    report = dict(base_report, warnings=warnings)
                    with mock.patch.object(dlms, "_validate_staged_content_pack", return_value=report):
                        html = client.get("/content-packs/import/review-token").get_data(as_text=True)
                    self.assertIn('class="dashboard-panel pack-review-summary"', html)
                    self.assertIn('id="packReviewInstallForm"', html)
                    self.assertIn('form="packReviewInstallForm">Install Study Pack', html)
                    self.assertIn('class="pack-review-button-row"', html)
                    self.assertIn('class="pack-review-cancel-form"', html)
                    self.assertIn('class="medical-ai-quiet-link pack-review-back-link"', html)

    def test_invalid_validation_review_keeps_cancel_action_without_install(self):
        metadata = {"uploaded_name": "blocked.zip", "file_count": 2, "uncompressed_bytes": 1024}
        report = {
            "valid": False, "pack_name": "Blocked Pack", "dataset_count": 0,
            "checks": [{"status": "FAIL", "name": "Manifest", "detail": "Invalid"}],
            "errors": ["Blocking problem"], "warnings": [],
        }
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_load_staged_content_pack", return_value=("stage", "pack", metadata)), \
             mock.patch.object(dlms, "_validate_staged_content_pack", return_value=report):
            html = client.get("/content-packs/import/review-token").get_data(as_text=True)
        self.assertIn('class="dashboard-panel pack-review-summary"', html)
        self.assertIn('class="pack-review-blocked-copy"', html)
        self.assertIn('class="pack-review-button-row"', html)
        self.assertIn('class="pack-review-cancel-form"', html)
        self.assertNotIn('id="packReviewInstallForm"', html)
        self.assertNotIn("Install Study Pack</button>", html)

    def test_duplicate_dataset_id_is_blocked(self):
        root = self.make_pack("DLMS_Study_dup")
        manifest = json.loads((root/"manifest.json").read_text())
        manifest["id"] = "study_dup"
        manifest["datasets"].append(dict(manifest["datasets"][0]))
        (root/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
        report = dlms._validate_staged_content_pack(str(root))
        self.assertFalse(report["valid"])
        self.assertTrue(any("duplicate dataset id" in e for e in report["errors"]))

    def _report_with_terms(self, name, terms):
        root = self.make_pack(name)
        data_path = root / "data/terms.json"
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data["terms"] = terms
        data_path.write_text(json.dumps(data), encoding="utf-8")
        return dlms._validate_staged_content_pack(str(root))

    def test_normalized_term_and_definition_collisions_are_blocked_precisely(self):
        report = self._report_with_terms("DLMS_Study_normalized", [
            {"term":"  LAYER   TWO ","definition":"Network level"},
            {"term":"LAYER TWO","definition":"Different answer"},
            {"term":"Frame","definition":"  NETWORK   LEVEL  "},
        ])
        self.assertFalse(report["valid"])
        joined = "\n".join(report["errors"])
        self.assertIn("one term maps to multiple answers", joined)
        self.assertIn("multiple terms map to one answer", joined)
        self.assertIn("item 2", joined)
        self.assertIn("earlier item 1", joined)
        self.assertIn("'LAYER   TWO'", joined)

    def test_case_sensitive_stat_directives_are_distinct_and_non_blocking(self):
        report = self._report_with_terms("DLMS_Study_stat_directives", [
            {
                "term":"stat %a",
                "definition":"A stat format directive that prints permission bits in octal.",
            },
            {
                "term":"stat %A",
                "definition":"A stat format directive that prints permission bits in symbolic form.",
            },
        ])
        self.assertTrue(report["valid"], report["errors"])
        self.assertFalse(any("one term maps to multiple answers" in e for e in report["errors"]))
        self.assertTrue(any(
            "case-only term variants" in warning
            and "'stat %a'" in warning
            and "'stat %A'" in warning
            for warning in report["warnings"]
        ))

    def test_case_sensitive_programming_identifiers_can_coexist(self):
        report = self._report_with_terms("DLMS_Study_identifiers", [
            {"term":"Path","definition":"A programming type representing a filesystem path."},
            {"term":"PATH","definition":"The environment variable used to locate commands."},
            {"term":"path","definition":"A local variable holding a route string."},
        ])
        self.assertTrue(report["valid"], report["errors"])
        self.assertGreaterEqual(
            sum("case-only term variants" in warning for warning in report["warnings"]),
            2,
        )

    def test_exact_and_whitespace_only_term_duplicates_remain_blocking(self):
        exact = self._report_with_terms("DLMS_Study_exact_term", [
            {"term":"chmod","definition":"Changes file modes."},
            {"term":"chmod","definition":"Modifies permissions."},
        ])
        whitespace = self._report_with_terms("DLMS_Study_whitespace_term", [
            {"term":"stat   %a","definition":"Prints octal permissions."},
            {"term":"  stat %a  ","definition":"Prints an octal file mode."},
        ])
        self.assertTrue(any("one term maps to multiple answers" in e for e in exact["errors"]))
        self.assertTrue(any("one term maps to multiple answers" in e for e in whitespace["errors"]))

    def test_case_only_natural_language_terms_receive_non_blocking_warning(self):
        report = self._report_with_terms("DLMS_Study_natural_case", [
            {"term":"Polish","definition":"Relating to Poland."},
            {"term":"polish","definition":"To make a surface smooth or shiny."},
        ])
        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(any("case-only term variants" in warning for warning in report["warnings"]))

    def test_unicode_normalized_collision_and_exact_pair_are_identified(self):
        report = self._report_with_terms("DLMS_Study_unicode", [
            {"term":"Ａlpha","definition":"First value"},
            {"term":"Alpha","definition":"First value"},
        ])
        self.assertFalse(report["valid"])
        joined = "\n".join(report["errors"])
        self.assertIn("exact duplicate pair", joined)
        self.assertIn("earlier item 1", joined)

    def test_duplicate_and_conflicting_record_ids_are_blocked(self):
        duplicate = self._report_with_terms("DLMS_Study_duplicate_record_id", [
            {"id":"Pair  1","term":"Layer","definition":"A level"},
            {"id":" pair 1 ","term":"Layer","definition":"A level"},
        ])
        self.assertTrue(any("duplicate ID" in e for e in duplicate["errors"]))

        conflicting = self._report_with_terms("DLMS_Study_conflicting_record_id", [
            {"id":"PAIR-1","term":"Layer","definition":"A level"},
            {"id":"pair-1","term":"Frame","definition":"A unit"},
        ])
        self.assertTrue(any("conflicting ID" in e for e in conflicting["errors"]))
        self.assertTrue(any("earlier item 1" in e for e in conflicting["errors"]))

    def test_missing_values_and_fewer_than_two_distinct_pairs_are_blocked(self):
        report = self._report_with_terms("DLMS_Study_missing_pair_values", [
            {"term":"Only","definition":""},
        ])
        joined = "\n".join(report["errors"])
        self.assertIn("missing definition", joined)
        self.assertIn("at least two valid distinct pairs", joined)

    def test_distinct_records_and_cross_dataset_term_reuse_are_allowed(self):
        root = self.make_pack("DLMS_Study_cross_dataset")
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["datasets"].append({
            "id":"other_terms","title":"Other Terms","type":"matching","path":"data/other.json"
        })
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        other = {
            "schema_version":1,"id":"other_terms","title":"Other Terms",
            "source":{"organization":"Test","license":"CC0"},
            "terms":[
                {"term":"Layer","definition":"A coating of material."},
                {"term":"Coat","definition":"An outer covering."},
            ],
        }
        (root / "data/other.json").write_text(json.dumps(other), encoding="utf-8")
        report = dlms._validate_staged_content_pack(str(root))
        self.assertTrue(report["valid"], report["errors"])

    def test_runtime_standalone_loader_uses_shared_matching_validation(self):
        root = self.make_pack("DLMS_Study_runtime_matching")
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["id"] = "study_runtime_matching"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        data_path = root / "data/terms.json"
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data["terms"] = [
            {"term":"Alpha","definition":"First"},
            {"term":" Alpha ","definition":"Second"},
        ]
        data_path.write_text(json.dumps(data), encoding="utf-8")
        installed_root = Path(dlms.CONTENT_PACK_FOLDER) / root.name
        root.rename(installed_root)

        with self.assertRaisesRegex(ValueError, "one term maps to multiple answers"):
            dlms.load_content_pack_dataset("study_runtime_matching", "terms")

    def test_runtime_standalone_loader_accepts_distinct_records_and_preserves_ids(self):
        root = self.make_pack("DLMS_Study_runtime_valid")
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["id"] = "study_runtime_valid"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        data_path = root / "data/terms.json"
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data["terms"][0]["id"] = "layer-id"
        data["terms"][1]["id"] = "frame-id"
        data_path.write_text(json.dumps(data), encoding="utf-8")
        installed_root = Path(dlms.CONTENT_PACK_FOLDER) / root.name
        root.rename(installed_root)

        loaded = dlms.load_content_pack_dataset("study_runtime_valid", "terms")
        self.assertEqual(["layer-id", "frame-id"], [item["id"] for item in loaded["terms"]])

    def test_concepts_are_normalized_and_tags_remain_a_compatibility_alias(self):
        root = self.make_pack("DLMS_Study_concepts")
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["id"] = "study_concepts"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        data_path = root / "data/terms.json"
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data["concepts"] = [" chmod ", "CHMOD", "octal-permissions"]
        data["terms"][0]["tags"] = "symbolic-permissions, chmod"
        data_path.write_text(json.dumps(data), encoding="utf-8")
        report = dlms._validate_staged_content_pack(str(root))
        self.assertTrue(report["valid"], report["errors"])
        installed = Path(dlms.CONTENT_PACK_FOLDER) / root.name
        root.rename(installed)
        loaded = dlms.load_content_pack_dataset("study_concepts", "terms")
        self.assertEqual(["chmod", "octal-permissions"], loaded["concepts"])
        self.assertEqual(["symbolic-permissions", "chmod"], loaded["terms"][0]["concepts"])
        self.assertNotIn("tags", loaded["terms"][0])

    def test_malformed_empty_and_over_limit_concepts_are_rejected(self):
        for name, concepts, expected in (
            ("DLMS_Study_bad_concept_shape", {"bad": "shape"}, "must be a string or list of strings"),
            ("DLMS_Study_empty_concept", ["chmod", "  "], "must not be empty"),
            ("DLMS_Study_long_concept", ["x" * 121], "120 characters or fewer"),
            ("DLMS_Study_many_concepts", [f"concept-{i}" for i in range(25)], "at most 24 concepts"),
        ):
            with self.subTest(name=name):
                root = self.make_pack(name)
                path = root / "data/terms.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                data["concepts"] = concepts
                path.write_text(json.dumps(data), encoding="utf-8")
                report = dlms._validate_staged_content_pack(str(root))
                self.assertFalse(report["valid"])
                self.assertIn(expected, "\n".join(report["errors"]))

    def test_standalone_matching_uses_explicit_concepts_not_category(self):
        root = self.make_pack("DLMS_Study_matching_concepts")
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["id"] = "study_matching_concepts"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        data_path = root / "data/terms.json"
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data["category"] = "IT"
        data["terms"][0]["concepts"] = ["chmod"]
        data["terms"][1]["concepts"] = ["octal-permissions", "chmod"]
        data_path.write_text(json.dumps(data), encoding="utf-8")
        installed = Path(dlms.CONTENT_PACK_FOLDER) / root.name
        root.rename(installed)
        loaded = dlms.load_content_pack_dataset("study_matching_concepts", "terms")
        self.assertEqual(["chmod", "octal-permissions"], dlms._standalone_matching_concepts(loaded, context="test"))
        self.assertNotIn("IT", dlms._standalone_matching_concepts(loaded, context="test"))

    def test_case_insensitive_descriptor_id_collision_is_blocked(self):
        root = self.make_pack("DLMS_Study_case_id")
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        duplicate = dict(manifest["datasets"][0])
        duplicate["id"] = "TERMS"
        manifest["datasets"].append(duplicate)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        report = dlms._validate_staged_content_pack(str(root))
        self.assertFalse(report["valid"])
        self.assertTrue(any("earlier descriptor uses 'terms'" in e for e in report["errors"]))

    def test_missing_declared_file_is_blocked(self):
        root = self.make_pack("DLMS_Study_missing")
        manifest = json.loads((root/"manifest.json").read_text())
        manifest["id"] = "study_missing"
        manifest["datasets"][0]["path"] = "data/missing.json"
        (root/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
        report = dlms._validate_staged_content_pack(str(root))
        self.assertFalse(report["valid"])
        self.assertTrue(any("declared dataset file is missing" in e for e in report["errors"]))

    def test_zip_path_traversal_is_blocked(self):
        zpath = Path(_TEMP.name)/"unsafe.zip"
        with zipfile.ZipFile(zpath,"w") as zf:
            zf.writestr("../evil.txt","no")
        with self.assertRaises(ValueError):
            dlms._inspect_content_pack_zip(str(zpath))


class GuidedAIStudyPackImportTests(unittest.TestCase):
    def _zip_pack(self, root, *, pack_id="study_guided", invalid=False, warning=False, questions=None):
        pack = root / f"DLMS_Study_{pack_id}"
        (pack / "data").mkdir(parents=True)
        manifest = {
            "schema_version": 0 if invalid else 1,
            "id": pack_id,
            "name": "Guided Import Pack",
            "version": "1.0.0",
            "content_domain": "general",
            "datasets": [{"id": "terms", "title": "Terms", "type": "matching", "path": "data/terms.json"}],
            "image_datasets": [],
            "quiz_datasets": [],
        }
        if questions is not None:
            manifest["quiz_datasets"] = [{
                "id": "questions", "title": "Questions", "type": "quiz",
                "path": "data/questions.json",
            }]
        data = {
            "schema_version": 1,
            "id": "terms",
            "title": "Terms",
            "source": {} if warning else {"organization": "DLMS Test", "license": "CC0"},
            "concepts": ["guided-import"],
            "terms": [
                {"term": "Alpha", "definition": "First value.", "concepts": ["alpha"]},
                {"term": "Beta", "definition": "Second value.", "concepts": ["beta"]},
            ],
        }
        (pack / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (pack / "data" / "terms.json").write_text(json.dumps(data), encoding="utf-8")
        if questions is not None:
            (pack / "data" / "questions.json").write_text(json.dumps({
                "schema_version": 1,
                "id": "questions",
                "title": "Questions",
                "source": {"organization": "DLMS Test", "license": "CC0"},
                "questions": questions,
            }), encoding="utf-8")
        archive = root / f"{pack_id}.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for path in pack.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(root).as_posix())
        return archive

    def _isolated_paths(self):
        directory = tempfile.TemporaryDirectory(prefix="dlms-guided-pack-tests-")
        root = Path(directory.name)
        patches = (
            mock.patch.object(dlms, "CONTENT_PACK_FOLDER", str(root / "content_packs")),
            mock.patch.object(dlms, "CONTENT_PACK_STAGING_FOLDER", str(root / "content_pack_staging")),
        )
        return directory, root, patches

    def _post_guided_zip(self, client, archive):
        return client.post(
            "/study-packs/ai-builder/import",
            data={
                "csrf_token": csrf_token(client, "/study-packs/ai-builder"),
                "pack_zip": (io.BytesIO(archive.read_bytes()), archive.name),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

    def test_guided_zip_uses_shared_stage_and_installs_to_targeted_study_pack(self):
        directory, root, patches = self._isolated_paths()
        with directory, patches[0], patches[1]:
            os.makedirs(dlms.CONTENT_PACK_FOLDER, exist_ok=True)
            os.makedirs(dlms.CONTENT_PACK_STAGING_FOLDER, exist_ok=True)
            archive = self._zip_pack(root)
            client = dlms.app.test_client()
            response = self._post_guided_zip(client, archive)
            self.assertEqual(302, response.status_code)
            token = response.headers["Location"].rsplit("/", 1)[-1]
            _, _, metadata = dlms._load_staged_content_pack(token)
            self.assertEqual(dlms.CONTENT_PACK_AI_WORKFLOW, metadata.get("workflow"))

            review = client.get(response.headers["Location"])
            self.assertIn("AI STUDY PACK WORKFLOW", review.get_data(as_text=True))
            self.assertIn("Back to AI Study Pack Builder", review.get_data(as_text=True))

            installed = client.post(
                f"/content-packs/import/{token}/install",
                data={"csrf_token": csrf_token(client, response.headers["Location"]), "confirm_install": "yes"},
                follow_redirects=False,
            )
            self.assertEqual(302, installed.status_code)
            self.assertEqual("/study-packs?installed=study_guided", installed.headers["Location"])
            self.assertIn("study_guided", dlms.discover_content_packs())
            self.assertFalse((Path(dlms.CONTENT_PACK_STAGING_FOLDER) / token).exists())
            loaded = dlms.load_content_pack_dataset("study_guided", "terms")
            self.assertEqual(["guided-import"], loaded["concepts"])
            landing = client.get(installed.headers["Location"]).get_data(as_text=True)
            self.assertIn('id="installed-study-pack"', landing)
            self.assertIn("Open Study Pack", landing)

    def test_guided_invalid_and_warning_paths_keep_existing_validation_rules(self):
        directory, root, patches = self._isolated_paths()
        with directory, patches[0], patches[1]:
            os.makedirs(dlms.CONTENT_PACK_FOLDER, exist_ok=True)
            os.makedirs(dlms.CONTENT_PACK_STAGING_FOLDER, exist_ok=True)
            client = dlms.app.test_client()
            invalid = self._post_guided_zip(client, self._zip_pack(root, pack_id="study_invalid", invalid=True))
            invalid_page = client.get(invalid.headers["Location"]).get_data(as_text=True)
            self.assertIn("INSTALL BLOCKED", invalid_page)
            self.assertNotIn('id="packReviewInstallForm"', invalid_page)

            warning = self._post_guided_zip(client, self._zip_pack(root, pack_id="study_warning", warning=True))
            warning_token = warning.headers["Location"].rsplit("/", 1)[-1]
            warning_page = client.get(warning.headers["Location"]).get_data(as_text=True)
            self.assertIn("Warnings", warning_page)
            self.assertIn('id="packReviewInstallForm"', warning_page)
            unconfirmed = client.post(
                f"/content-packs/import/{warning_token}/install",
                data={"csrf_token": csrf_token(client, warning.headers["Location"])},
                follow_redirects=False,
            )
            self.assertEqual(302, unconfirmed.status_code)
            self.assertEqual(warning.headers["Location"], unconfirmed.headers["Location"])
            self.assertFalse((Path(dlms.CONTENT_PACK_FOLDER) / "DLMS_Study_study_warning").exists())

    def test_guided_ai_mcq_requires_single_correct_choice(self):
        directory, root, patches = self._isolated_paths()
        with directory, patches[0], patches[1]:
            os.makedirs(dlms.CONTENT_PACK_FOLDER, exist_ok=True)
            os.makedirs(dlms.CONTENT_PACK_STAGING_FOLDER, exist_ok=True)
            archive = self._zip_pack(root, pack_id="study_ai_multi", questions=[{
                "type": "choice", "question": "Select both.", "choices": [
                    {"text": "One", "is_correct": True},
                    {"text": "Two", "is_correct": True},
                ],
            }])
            client = dlms.app.test_client()
            response = self._post_guided_zip(client, archive)
            page = client.get(response.headers["Location"]).get_data(as_text=True)
            self.assertIn("INSTALL BLOCKED", page)
            self.assertIn("exactly one correct choice", page)

    def test_guided_ai_all_a_choices_are_safely_randomized_with_metadata_intact(self):
        directory, root, patches = self._isolated_paths()
        questions = []
        for number in range(1, 26):
            questions.append({
                "type": "choice",
                "question": f"Question {number}",
                "explanation": f"Explanation {number}",
                "concepts": [f"concept-{number}"],
                "source": {"organization": "DLMS Test", "record": number},
                "provenance": {"source_line": number},
                "choices": [
                    {
                        "text": f"Correct {number}", "is_correct": True,
                        "choice_metadata": {"kind": "answer", "number": number},
                    },
                    {"text": f"Distractor B {number}", "is_correct": False},
                    {"text": f"Distractor C {number}", "is_correct": False},
                    {"text": f"Distractor D {number}", "is_correct": False},
                ],
            })

        with directory, patches[0], patches[1]:
            os.makedirs(dlms.CONTENT_PACK_FOLDER, exist_ok=True)
            os.makedirs(dlms.CONTENT_PACK_STAGING_FOLDER, exist_ok=True)
            client = dlms.app.test_client()
            response = self._post_guided_zip(
                client,
                self._zip_pack(
                    root, pack_id="study_ai_all_a", questions=questions
                ),
            )
            self.assertEqual(302, response.status_code)
            token = response.headers["Location"].rsplit("/", 1)[-1]
            _, pack_root, metadata = dlms._load_staged_content_pack(token)
            staged = json.loads(
                (Path(pack_root) / "data" / "questions.json").read_text(encoding="utf-8")
            )

            positions = []
            for number, question in enumerate(staged["questions"], 1):
                correct_positions = [
                    index for index, choice in enumerate(question["choices"])
                    if choice["is_correct"]
                ]
                self.assertEqual(1, len(correct_positions))
                positions.append(correct_positions[0])
                correct = question["choices"][correct_positions[0]]
                self.assertEqual(f"Correct {number}", correct["text"])
                self.assertEqual(
                    {"kind": "answer", "number": number},
                    correct["choice_metadata"],
                )
                self.assertEqual(f"Explanation {number}", question["explanation"])
                self.assertEqual([f"concept-{number}"], question["concepts"])
                self.assertEqual({"source_line": number}, question["provenance"])

            self.assertGreater(len(set(positions)), 1)
            self.assertLessEqual(max(positions.count(position) for position in set(positions)), 7)
            self.assertTrue(metadata.get("answer_position_corrections"))
            page = client.get(response.headers["Location"]).get_data(as_text=True)
            self.assertIn("safely randomized the choices for 25", page)
            self.assertNotIn("suspicious correct-answer position concentration", page)

    def test_manual_content_pack_import_keeps_legacy_multi_select_compatibility(self):
        directory, root, patches = self._isolated_paths()
        with directory, patches[0], patches[1]:
            os.makedirs(dlms.CONTENT_PACK_FOLDER, exist_ok=True)
            os.makedirs(dlms.CONTENT_PACK_STAGING_FOLDER, exist_ok=True)
            archive = self._zip_pack(root, pack_id="study_manual_multi", questions=[{
                "type": "choice", "question": "Select both.", "choices": [
                    {"text": "One", "is_correct": True},
                    {"text": "Two", "is_correct": True},
                ],
            }])
            client = dlms.app.test_client()
            response = client.post("/content-packs/import", data={
                "csrf_token": csrf_token(client, "/content-packs"),
                "pack_zip": (io.BytesIO(archive.read_bytes()), archive.name),
            }, content_type="multipart/form-data", follow_redirects=False)
            page = client.get(response.headers["Location"]).get_data(as_text=True)
            self.assertIn("READY TO INSTALL", page)
            self.assertIn('id="packReviewInstallForm"', page)

    def test_guided_cancel_only_removes_its_own_stage_and_manual_import_stays_generic(self):
        directory, root, patches = self._isolated_paths()
        with directory, patches[0], patches[1]:
            os.makedirs(dlms.CONTENT_PACK_FOLDER, exist_ok=True)
            os.makedirs(dlms.CONTENT_PACK_STAGING_FOLDER, exist_ok=True)
            archive = self._zip_pack(root)
            client = dlms.app.test_client()
            guided = self._post_guided_zip(client, archive)
            guided_token = guided.headers["Location"].rsplit("/", 1)[-1]
            manual = client.post(
                "/content-packs/import",
                data={
                    "csrf_token": csrf_token(client, "/content-packs"),
                    "pack_zip": (io.BytesIO(archive.read_bytes()), archive.name),
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
            manual_token = manual.headers["Location"].rsplit("/", 1)[-1]
            _, _, manual_metadata = dlms._load_staged_content_pack(manual_token)
            self.assertNotIn("workflow", manual_metadata)

            cancelled = client.post(
                f"/content-packs/import/{guided_token}/cancel",
                data={"csrf_token": csrf_token(client, guided.headers["Location"])},
                follow_redirects=False,
            )
            self.assertEqual("/study-packs/ai-builder", cancelled.headers["Location"])
            self.assertFalse((Path(dlms.CONTENT_PACK_STAGING_FOLDER) / guided_token).exists())
            self.assertTrue((Path(dlms.CONTENT_PACK_STAGING_FOLDER) / manual_token).exists())

    def test_guided_install_failure_keeps_existing_content_unchanged(self):
        directory, root, patches = self._isolated_paths()
        with directory, patches[0], patches[1]:
            os.makedirs(dlms.CONTENT_PACK_FOLDER, exist_ok=True)
            os.makedirs(dlms.CONTENT_PACK_STAGING_FOLDER, exist_ok=True)
            client = dlms.app.test_client()
            response = self._post_guided_zip(client, self._zip_pack(root))
            token = response.headers["Location"].rsplit("/", 1)[-1]
            with mock.patch.object(dlms, "discover_content_packs", return_value={}):
                failed = client.post(
                    f"/content-packs/import/{token}/install",
                    data={"csrf_token": csrf_token(client, response.headers["Location"]), "confirm_install": "yes"},
                    follow_redirects=False,
                )
            self.assertEqual(response.headers["Location"], failed.headers["Location"])
            self.assertFalse((Path(dlms.CONTENT_PACK_FOLDER) / "DLMS_Study_study_guided").exists())
            self.assertTrue((Path(dlms.CONTENT_PACK_STAGING_FOLDER) / token).exists())

if __name__ == "__main__":
    unittest.main()
