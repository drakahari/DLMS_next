"""Failure-injection coverage for Image Study Pack staging and promotion."""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from werkzeug.utils import secure_filename

from dlms.persistence import json_files
from dlms.services import backups, content_pack_mutations, content_packs


class ImageStudyPackStagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-image-pack-stage-")
        self.root = Path(self.temporary.name)
        self.content_root = self.root / "content_packs"
        self.staging_root = self.root / "content_pack_staging"
        self.draft_root = self.root / "image_builder_drafts" / "draft_12345678"
        self.content_root.mkdir()
        self.staging_root.mkdir()
        self.draft_root.mkdir(parents=True)
        (self.draft_root / "diagram.png").write_bytes(b"test-image-bytes")
        self.events = []
        self.validation_paths = []
        self.atomic_calls = []

    def tearDown(self):
        self.temporary.cleanup()

    @property
    def final_root(self):
        return self.content_root / "DLMS_Study_Crash_Safe_Images_artifact123"

    @staticmethod
    def _safe_child(root, relative):
        root = os.path.realpath(root)
        candidate = os.path.realpath(os.path.join(root, relative))
        if candidate != root and not candidate.startswith(root + os.sep):
            raise ValueError("unsafe child")
        return candidate

    @staticmethod
    def _questions():
        return [{
            "type": "choice",
            "question": "Which image is correct?",
            "image_id": "image_1",
            "choices": [
                {"text": "Café", "is_correct": True},
                {"text": "Other", "is_correct": False},
            ],
            "explanation": "Unicode survives — exactly.",
        }]

    @staticmethod
    def _images():
        return [{
            "id": "image_1",
            "filename": "diagram.png",
            "original_name": "Diagram ü.png",
            "alt_text": "Diagram — overview",
        }]

    def _atomic_write(self, path, payload, **kwargs):
        self.events.append(f"write:{Path(path).name}")
        self.atomic_calls.append((Path(path), payload, kwargs))
        return json_files._atomic_write_json(path, payload, **kwargs)

    def _validate(self, staged_root):
        staged_root = Path(staged_root)
        self.events.append("validate")
        self.validation_paths.append(staged_root)
        self.assertTrue(staged_root.parent.samefile(self.staging_root))
        self.assertTrue(staged_root.name.startswith(".image-builder-"))
        self.assertFalse(self.final_root.exists())
        self.assertTrue((staged_root / "images" / "diagram.png").is_file())
        self.assertTrue((staged_root / "data" / "crash_safe_images.json").is_file())
        self.assertTrue((staged_root / "manifest.json").is_file())
        self.assertEqual(
            {},
            content_packs.discover_content_packs(
                str(self.content_root), expected_schema_version=1
            ),
        )
        manifest = json.loads((staged_root / "manifest.json").read_text(encoding="utf-8"))
        return {"valid": True, "errors": [], "pack_id": manifest["id"]}

    def _promote(self, staged_root, final_root):
        self.events.append("promote")
        self.assertFalse(Path(final_root).exists())
        os.rename(staged_root, final_root)

    def _load(self, pack_id, dataset_id):
        self.events.append("load")
        self.assertTrue(self.final_root.is_dir())
        self.assertEqual("user_crash_safe_images_artifact123", pack_id)
        self.assertEqual("crash_safe_images", dataset_id)
        return json.loads(
            (self.final_root / "data" / "crash_safe_images.json").read_text(
                encoding="utf-8"
            )
        )

    def _runtime(self, pack_id, data):
        self.events.append("runtime")
        return data["questions"], data["questions"]

    def _publish(self, title, runtime, db_questions, **kwargs):
        self.events.append("publish")
        self.assertEqual("Crash Safe Images — Practice", title)
        self.assertEqual(runtime, db_questions)
        self.assertEqual("user_crash_safe_images_artifact123", kwargs["source_pack_id"])
        return 42, "crash_safe_images.html"

    def _create(self, **overrides):
        arguments = {
            "draft_root": str(self.draft_root),
            "title": "Crash Safe Images",
            "subject": "Science",
            "description": "A staged pack",
            "source_note": "Personal source",
            "images_payload": self._images(),
            "questions_payload": self._questions(),
            "artifact_identity": "artifact123",
            "exam_minutes": "25",
            "content_pack_folder": str(self.content_root),
            "staging_folder": str(self.staging_root),
            "safe_pack_child": self._safe_child,
            "secure_filename": secure_filename,
            "validate_hotspot_shape": lambda shape: shape,
            "now": lambda: datetime(2026, 9, 8, 12, 0, 0),
            "atomic_write_json": self._atomic_write,
            "validate_staged_content_pack": self._validate,
            "load_content_pack_quiz_dataset": self._load,
            "quiz_dataset_runtime": self._runtime,
            "publish_quiz": self._publish,
            "promote_directory": self._promote,
            "fsync_directory": lambda path: self.events.append(
                f"fsync:{Path(path).name}"
            ),
        }
        arguments.update(overrides)
        return content_pack_mutations.create_image_study_pack(**arguments)

    def _assert_pre_promotion_failure_is_clean(self):
        self.assertFalse(self.final_root.exists())
        self.assertEqual([], list(self.staging_root.iterdir()))
        self.assertTrue(self.draft_root.is_dir())

    def test_success_stages_validates_promotes_then_publishes(self):
        result = self._create()

        self.assertEqual(
            {
                "pack_id": "user_crash_safe_images_artifact123",
                "pack_root": str(self.final_root),
                "dataset_id": "crash_safe_images",
                "html_name": "crash_safe_images.html",
            },
            result,
        )
        self.assertEqual(
            [
                "fsync:images",
                "write:crash_safe_images.json",
                "write:manifest.json",
                "validate",
                "promote",
                "fsync:content_packs",
                "load",
                "runtime",
                "publish",
            ],
            self.events,
        )
        self.assertFalse(self.draft_root.exists())
        self.assertEqual([], list(self.staging_root.iterdir()))
        self.assertTrue(self.final_root.is_dir())
        self.assertEqual(b"test-image-bytes", (self.final_root / "images" / "diagram.png").read_bytes())
        dataset = json.loads(
            (self.final_root / "data" / "crash_safe_images.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("Café", dataset["questions"][0]["choices"][0]["text"])
        self.assertEqual("Diagram — overview", dataset["images"][0]["alt_text"])
        self.assertTrue(all(call[2]["expected_type"] is dict for call in self.atomic_calls))
        self.assertTrue(all(call[2]["ensure_ascii"] is False for call in self.atomic_calls))
        discovered = content_packs.discover_content_packs(
            str(self.content_root), expected_schema_version=1
        )
        self.assertEqual(["user_crash_safe_images_artifact123"], list(discovered))

    def test_copy_dataset_manifest_and_validation_failures_remove_only_staging(self):
        def copy_failure(_source, _target):
            raise OSError("copy failed")

        with self.subTest(boundary="copy"):
            with self.assertRaisesRegex(OSError, "copy failed"):
                self._create(copy_file=copy_failure)
            self._assert_pre_promotion_failure_is_clean()

        self._reset_draft()

        def dataset_failure(path, payload, **kwargs):
            if Path(path).name == "crash_safe_images.json":
                raise OSError("dataset failed")
            return self._atomic_write(path, payload, **kwargs)

        with self.subTest(boundary="dataset"):
            with self.assertRaisesRegex(OSError, "dataset failed"):
                self._create(atomic_write_json=dataset_failure)
            self._assert_pre_promotion_failure_is_clean()

        self._reset_draft()

        def manifest_failure(path, payload, **kwargs):
            if Path(path).name == "manifest.json":
                raise OSError("manifest failed")
            return self._atomic_write(path, payload, **kwargs)

        with self.subTest(boundary="manifest"):
            with self.assertRaisesRegex(OSError, "manifest failed"):
                self._create(atomic_write_json=manifest_failure)
            self._assert_pre_promotion_failure_is_clean()

        self._reset_draft()
        with self.subTest(boundary="validation"):
            with self.assertRaisesRegex(ValueError, "validation failed: bad candidate"):
                self._create(validate_staged_content_pack=lambda _root: {
                    "valid": False, "errors": ["bad candidate"], "pack_id": "",
                })
            self._assert_pre_promotion_failure_is_clean()

    def _reset_draft(self):
        self.draft_root.mkdir(parents=True, exist_ok=True)
        (self.draft_root / "diagram.png").write_bytes(b"test-image-bytes")

    def test_destination_collision_never_removes_existing_pack(self):
        self.final_root.mkdir()
        marker = self.final_root / "user-content.txt"
        marker.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(FileExistsError, "destination already exists"):
            self._create()

        self.assertEqual("keep", marker.read_text(encoding="utf-8"))
        self.assertEqual([], list(self.staging_root.iterdir()))
        self.assertTrue(self.draft_root.exists())

    def test_promotion_failure_cleans_stage_without_touching_other_packs(self):
        unrelated = self.content_root / "hand-built-invalid-pack"
        unrelated.mkdir()
        marker = unrelated / "notes.txt"
        marker.write_text("user content", encoding="utf-8")

        with self.assertRaisesRegex(OSError, "promotion failed"):
            self._create(promote_directory=lambda _stage, _final: (_ for _ in ()).throw(
                OSError("promotion failed")
            ))

        self._assert_pre_promotion_failure_is_clean()
        self.assertEqual("user content", marker.read_text(encoding="utf-8"))

    def test_collision_appearing_at_promotion_is_not_blindly_deleted(self):
        def collide_then_fail(_stage, final):
            final = Path(final)
            final.mkdir()
            (final / "collision.txt").write_text("unrelated", encoding="utf-8")
            raise FileExistsError("late collision")

        with self.assertRaisesRegex(FileExistsError, "late collision"):
            self._create(promote_directory=collide_then_fail)

        self.assertEqual([], list(self.staging_root.iterdir()))
        self.assertEqual(
            "unrelated", (self.final_root / "collision.txt").read_text(encoding="utf-8")
        )
        self.assertTrue(self.draft_root.exists())

    def test_quiz_publication_failure_removes_owned_valid_pack_and_keeps_draft(self):
        def publish_failure(*_args, **_kwargs):
            self.events.append("publish")
            raise RuntimeError("quiz publication failed")

        with self.assertRaisesRegex(RuntimeError, "quiz publication failed"):
            self._create(publish_quiz=publish_failure)

        self.assertFalse(self.final_root.exists())
        self.assertEqual([], list(self.staging_root.iterdir()))
        self.assertTrue(self.draft_root.exists())
        self.assertIn("validate", self.events)
        self.assertLess(self.events.index("validate"), self.events.index("promote"))
        self.assertLess(self.events.index("promote"), self.events.index("publish"))

    def test_builder_staging_namespace_is_excluded_from_portable_backups(self):
        staged = self.staging_root / ".image-builder-abandoned" / "manifest.json"
        staged.parent.mkdir()
        staged.write_text("{}", encoding="utf-8")
        final = self.content_root / "valid-pack" / "manifest.json"
        final.parent.mkdir()
        final.write_text("{}", encoding="utf-8")
        database = self.root / "results.db"

        inventory = backups.backup_file_inventory(
            str(self.root),
            str(database),
            rel_is_excluded=lambda rel: backups.backup_rel_is_excluded(
                rel,
                data_root_marker=".dlms-data-root",
                excluded_top_level={"content_pack_staging"},
            ),
        )

        relative_paths = [relative for _full, relative in inventory]
        self.assertNotIn(
            "content_pack_staging/.image-builder-abandoned/manifest.json",
            relative_paths,
        )
        self.assertIn("content_packs/valid-pack/manifest.json", relative_paths)


if __name__ == "__main__":
    unittest.main()
