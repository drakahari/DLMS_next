"""DLMS-133 portable quiz bundle export/import and safety regressions."""

import copy
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services import portable_quiz_bundles as bundles
from tests.csrf_test_utils import csrf_headers
from tests.current_schema import seed_current_quiz


class PortableQuizBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-133-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {
            "APP_DATA_DIR": self.root,
            "DATA_FOLDER": self.root / "data",
            "QUIZ_FOLDER": self.root / "quizzes",
            "CONFIG_FOLDER": self.root / "config",
            "QUIZ_REGISTRY": self.root / "config" / "quizzes.json",
            "DB_PATH": self.root / "results.db",
            "QUIZ_ASSET_FOLDER": self.root / "quiz_assets",
            "CONTENT_PACK_FOLDER": self.root / "content_packs",
            "LOGO_FOLDER": self.root / "static" / "logos",
            "UPLOAD_FOLDER": self.root / "uploads",
            "PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER": self.root / "uploads" / "quiz_bundles",
        }
        for name, path in paths.items():
            patcher = mock.patch.object(dlms, name, str(path))
            patcher.start()
            self.addCleanup(patcher.stop)
            if name not in {"QUIZ_REGISTRY", "DB_PATH", "APP_DATA_DIR"}:
                path.mkdir(parents=True, exist_ok=True)
        self.assertTrue(dlms._initialize_data_root_ownership(str(self.root)))
        dlms.ensure_db_initialized()
        dlms.save_registry([])

    @staticmethod
    def _choice(text="Which neutral option is correct?", *, number=1, image_url=None):
        question = {
            "number": number,
            "type": "choice",
            "question": text,
            "explanation": "A bounded neutral explanation.",
            "concepts": ["Portable concepts"],
            "source": {
                "organization": "Example Organization",
                "dataset": "Neutral Dataset",
                "version": "1",
                "url": "https://example.invalid/source",
                "license": "CC0",
            },
            "choices": [
                {"label": "A", "text": "Expected", "is_correct": True},
                {"label": "B", "text": "Alternative", "is_correct": False},
            ],
        }
        if image_url:
            question.update({
                "image_url": image_url,
                "image_alt": "Neutral diagram",
                "image_edits": [{"type": "rotate", "degrees": 0}],
                "image_source": {"license": "CC0"},
            })
        return question

    @staticmethod
    def _matching(number=1):
        return {
            "number": number,
            "type": "matching",
            "question": "Match each neutral term with its definition.",
            "explanation": "Use each pair once.",
            "concepts": ["Terminology"],
            "round_size": 2,
            "direction": "definition_to_term",
            "pairs": [
                {
                    "left": "Alpha",
                    "right": "First definition",
                    "category": "Letters",
                    "explanation": "First pair.",
                    "verification": {"status": "reviewed"},
                },
                {
                    "left": "Beta",
                    "right": "Second definition",
                    "category": "Letters",
                    "explanation": "Second pair.",
                    "verification": {},
                },
            ],
        }

    def _seed(self, title, source_file, questions, *, folder="Uncategorized", logo=None):
        quiz_id = seed_current_quiz(dlms.get_db, title, source_file, questions)
        registry = dlms.load_registry()
        registry.append({
            "id": quiz_id,
            "title": title,
            "html": source_file,
            "folder": folder,
            "exam_minutes": 35,
            "logo": logo,
        })
        dlms.save_registry(registry)
        return quiz_id

    def _export(self, quiz_ids):
        connection = dlms.get_db()
        try:
            return dlms._build_portable_quiz_bundle(
                connection.cursor(), dlms.load_registry(), quiz_ids
            )
        finally:
            connection.close()

    def _write_bundle(self, manifest, *, members=None):
        path = self.root / "candidate.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                bundles.PORTABLE_QUIZ_BUNDLE_MANIFEST,
                json.dumps(manifest),
            )
            for name, payload in (members or {}).items():
                archive.writestr(name, payload)
        return path

    def _minimal_manifest(self, *, title="Imported Quiz"):
        return {
            "format": bundles.PORTABLE_QUIZ_BUNDLE_FORMAT,
            "schema_version": 1,
            "created_at": "2026-09-13T10:00:00-05:00",
            "created_by": {"application": "DLMS", "version": "3.1.0"},
            "quizzes": [{
                "bundle_id": "quiz-001",
                "title": title,
                "folder": "Imported Folder",
                "exam_minutes": 45,
                "logo": None,
                "assets": [],
                "questions": [{
                    "number": 1,
                    "type": "choice",
                    "question": "Which imported option is correct?",
                    "explanation": "Neutral explanation.",
                    "concepts": ["Imported Concept"],
                    "source": {},
                    "media": {},
                    "choices": [
                        {"label": "A", "text": "Expected", "is_correct": True},
                        {"label": "B", "text": "Alternative", "is_correct": False},
                    ],
                }],
            }],
        }

    def _inspect(self, path):
        return bundles.inspect_portable_quiz_bundle(
            path,
            validate_raster_image=dlms._decode_raster_image,
            allowed_image_extensions=dlms.PASSIVE_PACK_IMAGE_EXTENSIONS,
        )

    def test_single_and_multi_quiz_export_is_inspectable_and_read_only(self):
        choice = self._choice("Which  internal spacing\nand line break is preserved?")
        choice["choices"][0]["text"] = "line one\n    indented line two"
        first_id = self._seed(
            "Choice  Bank", "choice-bank.html", [choice], folder="Science"
        )
        second_id = self._seed(
            "Matching Bank", "matching-bank.html", [self._matching()], folder="Terms"
        )
        connection = dlms.get_db()
        before = tuple(connection.execute(
            "SELECT id, title, source_file FROM quizzes ORDER BY id"
        ).fetchall())
        connection.close()

        single_bytes, _name, single_manifest = self._export([first_id])
        multi_bytes, name, manifest = self._export([first_id, second_id])

        self.assertEqual(1, len(single_manifest["quizzes"]))
        self.assertEqual("DLMS-Quiz-Bundle-", name[:17])
        self.assertEqual(["Choice  Bank", "Matching Bank"], [
            quiz["title"] for quiz in manifest["quizzes"]
        ])
        self.assertEqual(["Science", "Terms"], [
            quiz["folder"] for quiz in manifest["quizzes"]
        ])
        self.assertEqual("matching", manifest["quizzes"][1]["questions"][0]["type"])
        self.assertEqual("definition_to_term", manifest["quizzes"][1]["questions"][0]["direction"])
        self.assertEqual(["Portable concepts"], manifest["quizzes"][0]["questions"][0]["concepts"])
        self.assertEqual(
            "Which  internal spacing\nand line break is preserved?",
            manifest["quizzes"][0]["questions"][0]["question"],
        )
        self.assertEqual(
            "line one\n    indented line two",
            manifest["quizzes"][0]["questions"][0]["choices"][0]["text"],
        )
        manifest_text = json.dumps(manifest).casefold()
        for excluded in (
            "attempt", "score", "learning_event", "schedule", "confidence",
            "composition_sources",
        ):
            self.assertNotIn(excluded, manifest_text)

        for number, payload in enumerate((single_bytes, multi_bytes), 1):
            path = self.root / f"export-{number}.zip"
            path.write_bytes(payload)
            report = self._inspect(path)
            self.assertEqual(number, report["quiz_count"])

        connection = dlms.get_db()
        after = tuple(connection.execute(
            "SELECT id, title, source_file FROM quizzes ORDER BY id"
        ).fetchall())
        connection.close()
        self.assertEqual(before, after)

    def test_choice_matching_metadata_folders_and_media_round_trip_with_collision(self):
        source_bucket = Path(dlms.QUIZ_ASSET_FOLDER) / "source_media"
        source_bucket.mkdir(parents=True)
        image_path = source_bucket / "diagram.png"
        Image.new("RGB", (8, 8), (20, 70, 120)).save(image_path)
        logo_path = Path(dlms.LOGO_FOLDER) / "portable-logo.png"
        Image.new("RGB", (8, 8), (80, 30, 100)).save(logo_path)
        title = "Curated Collection"
        quiz_id = self._seed(
            title,
            "curated.html",
            [
                self._choice(image_url="/quiz-assets/source_media/diagram.png"),
                self._matching(number=2),
            ],
            folder="Portable Folder",
            logo=logo_path.name,
        )
        bundle_bytes, _name, manifest = self._export([quiz_id])
        self.assertEqual(2, len(manifest["quizzes"][0]["assets"]))

        client = dlms.app.test_client()
        response = client.post(
            "/quiz-bundles/import",
            data={"bundle_zip": (io.BytesIO(bundle_bytes), "portable.zip")},
            content_type="multipart/form-data",
            headers=csrf_headers(client, "/quiz-bundles"),
        )
        self.assertEqual(302, response.status_code)
        review_url = response.headers["Location"]
        review = client.get(review_url)
        review_text = review.get_data(as_text=True)
        self.assertEqual(200, review.status_code)
        self.assertIn("Curated Collection (Imported)", review_text)
        self.assertIn("RENAMED", review_text)
        token = review_url.rsplit("/", 1)[-1]
        published = client.post(
            f"/quiz-bundles/import/{token}/confirm",
            data={"confirm_import": "yes"},
            headers=csrf_headers(client, review_url),
        )
        self.assertEqual(302, published.status_code)
        self.assertFalse((Path(dlms.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER) / token).exists())

        registry = dlms.load_registry()
        self.assertEqual(2, len(registry))
        imported_entry = next(item for item in registry if item["id"] != quiz_id)
        self.assertEqual("Curated Collection (Imported)", imported_entry["title"])
        self.assertEqual("Portable Folder", imported_entry["folder"])
        self.assertTrue((Path(dlms.LOGO_FOLDER) / imported_entry["logo"]).is_file())

        connection = dlms.get_db()
        try:
            imported_questions = connection.execute(
                "SELECT id, question_type, media_json FROM questions WHERE quiz_id = ? ORDER BY question_number",
                (imported_entry["id"],),
            ).fetchall()
            concepts = {
                row[0] for row in connection.execute(
                    "SELECT c.name FROM concepts c JOIN question_concepts qc ON qc.concept_id = c.id "
                    "JOIN questions q ON q.id = qc.question_id WHERE q.quiz_id = ?",
                    (imported_entry["id"],),
                ).fetchall()
            }
            pairs = connection.execute(
                "SELECT left_text, right_text FROM matching_pairs WHERE question_id = ? ORDER BY pair_order",
                (imported_questions[1]["id"],),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(["choice", "matching"], [row["question_type"] for row in imported_questions])
        self.assertEqual({"Portable concepts", "Terminology"}, concepts)
        self.assertEqual([("Alpha", "First definition"), ("Beta", "Second definition")], [tuple(row) for row in pairs])
        imported_media = json.loads(imported_questions[0]["media_json"])
        self.assertRegex(imported_media["image_url"], r"^/quiz-assets/portable_quiz_.+/quiz-001/asset-001\.png$")
        imported_file = Path(dlms.QUIZ_ASSET_FOLDER) / imported_media["image_url"].removeprefix("/quiz-assets/")
        self.assertTrue(imported_file.is_file())
        self.assertEqual(hashlib.sha256(image_path.read_bytes()).digest(), hashlib.sha256(imported_file.read_bytes()).digest())

    def test_library_workflow_exports_selected_quiz_and_requires_confirmation(self):
        quiz_id = self._seed("Workflow Bank", "workflow.html", [self._choice()])
        client = dlms.app.test_client()
        page = client.get("/quiz-bundles")
        text = page.get_data(as_text=True)
        self.assertEqual(200, page.status_code)
        self.assertIn("Portable Quiz Bundles", text)
        self.assertIn("Study Packs remain a separate", text)
        self.assertIn("Workflow Bank", text)
        library = client.get("/library").get_data(as_text=True)
        self.assertIn('href="/quiz-bundles">Quiz Bundles</a>', library)

        response = client.post(
            "/quiz-bundles/export",
            data={"quiz_ids": str(quiz_id)},
            headers=csrf_headers(client, "/quiz-bundles"),
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("application/zip", response.mimetype)
        self.assertIn("DLMS-Quiz-Bundle-", response.headers["Content-Disposition"])

        staged = client.post(
            "/quiz-bundles/import",
            data={"bundle_zip": (io.BytesIO(response.data), "round-trip.zip")},
            content_type="multipart/form-data",
            headers=csrf_headers(client, "/quiz-bundles"),
        )
        token = staged.headers["Location"].rsplit("/", 1)[-1]
        refused = client.post(
            f"/quiz-bundles/import/{token}/confirm",
            data={},
            headers=csrf_headers(client, staged.headers["Location"]),
        )
        self.assertEqual(302, refused.status_code)
        connection = dlms.get_db()
        try:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0])
        finally:
            connection.close()

    def test_generated_review_sources_are_not_exportable(self):
        source_id = self._seed("Source Bank", "source.html", [self._choice()])
        generated_id = self._seed(
            "Adaptive Study — Source", "adaptive_study_123.html", [self._choice()]
        )
        connection = dlms.get_db()
        try:
            catalog = bundles.portable_quiz_export_catalog(
                connection.cursor(), dlms.load_registry()
            )
        finally:
            connection.close()
        self.assertEqual([source_id], [item["quiz_id"] for item in catalog["quizzes"]])
        self.assertEqual(1, catalog["excluded_generated_count"])
        with self.assertRaisesRegex(bundles.PortableQuizBundleError, "not exportable"):
            self._export([generated_id])
        with self.assertRaisesRegex(bundles.PortableQuizBundleError, "Select at least one"):
            self._export([])

    def test_manifest_rejects_unsafe_or_unexpected_structure_and_limits(self):
        baseline = self._minimal_manifest()
        cases = []
        malformed = copy.deepcopy(baseline)
        malformed["unexpected"] = True
        cases.append((malformed, "unsupported field"))
        bad_choice = copy.deepcopy(baseline)
        bad_choice["quizzes"][0]["questions"][0]["choices"][0]["is_correct"] = "yes"
        cases.append((bad_choice, "JSON boolean"))
        bad_url = copy.deepcopy(baseline)
        bad_url["quizzes"][0]["questions"][0]["source"] = {"url": "file:///private/data"}
        cases.append((bad_url, "http:// or https://"))
        bad_type = copy.deepcopy(baseline)
        bad_type["quizzes"][0]["questions"][0]["type"] = "essay"
        cases.append((bad_type, "unsupported type"))
        for manifest, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                bundles.PortableQuizBundleError, message
            ):
                bundles.validate_portable_quiz_bundle_manifest(manifest)

        too_many = copy.deepcopy(baseline)
        too_many["quizzes"].append(copy.deepcopy(too_many["quizzes"][0]))
        too_many["quizzes"][1]["bundle_id"] = "quiz-002"
        too_many["quizzes"][1]["title"] = "Second"
        with mock.patch.object(bundles, "PORTABLE_QUIZ_BUNDLE_MAX_QUIZZES", 1), self.assertRaisesRegex(
            bundles.PortableQuizBundleError, "more than 1"
        ):
            bundles.validate_portable_quiz_bundle_manifest(too_many)

        oversized_asset = copy.deepcopy(baseline)
        oversized_asset["quizzes"][0]["assets"] = [{
            "path": "assets/quiz-001/asset-001.png",
            "sha256": "0" * 64,
            "size": 2,
            "role": "question-media",
        }]
        oversized_asset["quizzes"][0]["questions"][0]["media"] = {
            "image_url": "dlms-bundle-asset:assets/quiz-001/asset-001.png"
        }
        with mock.patch.object(bundles, "PORTABLE_QUIZ_BUNDLE_MAX_SINGLE_FILE_BYTES", 1), self.assertRaisesRegex(
            bundles.PortableQuizBundleError, "size is invalid"
        ):
            bundles.validate_portable_quiz_bundle_manifest(oversized_asset)

    def test_archive_rejects_path_traversal_unexpected_files_and_asset_tampering(self):
        baseline = self._minimal_manifest()
        traversal = self.root / "traversal.zip"
        with zipfile.ZipFile(traversal, "w") as archive:
            archive.writestr(bundles.PORTABLE_QUIZ_BUNDLE_MANIFEST, json.dumps(baseline))
            archive.writestr("../outside.txt", "unsafe")
        with self.assertRaisesRegex(bundles.PortableQuizBundleError, "unsafe path"):
            self._inspect(traversal)

        unexpected = self._write_bundle(baseline, members={"notes.txt": b"not allowed"})
        with self.assertRaisesRegex(bundles.PortableQuizBundleError, "unexpected file"):
            self._inspect(unexpected)

        unexpected_directory = self.root / "unexpected-directory.zip"
        with zipfile.ZipFile(unexpected_directory, "w") as archive:
            archive.writestr(bundles.PORTABLE_QUIZ_BUNDLE_MANIFEST, json.dumps(baseline))
            archive.writestr("assets/not-declared/", b"")
        with self.assertRaisesRegex(bundles.PortableQuizBundleError, "unexpected directory"):
            self._inspect(unexpected_directory)

        image = io.BytesIO()
        Image.new("RGB", (4, 4), (10, 20, 30)).save(image, format="PNG")
        payload = image.getvalue()
        tampered_manifest = copy.deepcopy(baseline)
        quiz = tampered_manifest["quizzes"][0]
        path = "assets/quiz-001/asset-001.png"
        quiz["assets"] = [{
            "path": path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "role": "question-media",
        }]
        quiz["questions"][0]["media"] = {
            "image_url": bundles.PORTABLE_QUIZ_BUNDLE_ASSET_REF_PREFIX + path
        }
        tampered = self._write_bundle(tampered_manifest, members={path: payload + b"changed"})
        with self.assertRaisesRegex(bundles.PortableQuizBundleError, "wrong size"):
            self._inspect(tampered)

    def test_title_collisions_are_deterministic_and_never_overwrite(self):
        manifest = bundles.validate_portable_quiz_bundle_manifest(
            self._minimal_manifest(title="Existing Quiz")
        )
        manifest["quizzes"].append(copy.deepcopy(manifest["quizzes"][0]))
        manifest["quizzes"][1]["bundle_id"] = "quiz-002"
        plans = bundles.plan_portable_quiz_bundle_import(
            manifest,
            [" existing   quiz ", "Existing Quiz (Imported)"],
        )
        self.assertEqual(
            ["Existing Quiz (Imported 2)", "Existing Quiz (Imported 3)"],
            [plan["import_title"] for plan in plans],
        )
        self.assertTrue(all(plan["renamed"] for plan in plans))

    def test_multi_quiz_failure_rolls_back_completed_publications_and_keeps_sources(self):
        first = self._seed("First Source", "first.html", [self._choice()])
        second = self._seed(
            "Second Source", "second.html", [self._matching()], folder="Terms"
        )
        archive, _name, _manifest = self._export([first, second])
        client = dlms.app.test_client()
        staged = client.post(
            "/quiz-bundles/import",
            data={"bundle_zip": (io.BytesIO(archive), "two.zip")},
            content_type="multipart/form-data",
            headers=csrf_headers(client, "/quiz-bundles"),
        )
        token = staged.headers["Location"].rsplit("/", 1)[-1]
        original_publish = dlms._publish_quiz
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic second publication failure")
            return original_publish(*args, **kwargs)

        with mock.patch.object(dlms, "_publish_quiz", side_effect=fail_second):
            response = client.post(
                f"/quiz-bundles/import/{token}/confirm",
                data={"confirm_import": "yes"},
                headers=csrf_headers(client, staged.headers["Location"]),
            )
        self.assertEqual(500, response.status_code)
        connection = dlms.get_db()
        try:
            rows = connection.execute(
                "SELECT id, title FROM quizzes ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual([(first, "First Source"), (second, "Second Source")], [tuple(row) for row in rows])
        self.assertEqual([first, second], [entry["id"] for entry in dlms.load_registry()])
        self.assertTrue((Path(dlms.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER) / token).is_dir())
        self.assertEqual([], list(Path(dlms.QUIZ_ASSET_FOLDER).glob("portable_import_*")))


if __name__ == "__main__":
    unittest.main()
