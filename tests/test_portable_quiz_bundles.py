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
        # Keep a prior producer version to prove bundles are not tied to the
        # installation that created them or to the current application version.
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
        self.assertEqual(
            {"application": "DLMS", "version": "3.3.0"},
            manifest["created_by"],
        )
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
            "composition_sources", "question_uid", "canonical_question_uid",
            "source_question_uid", "source_question_id", "is_generated_copy",
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
        source_lineage = dlms._question_identity_service.source_question_lineage()
        connection = dlms.get_db()
        try:
            connection.execute(
                """
                UPDATE questions
                SET question_uid = ?, canonical_question_uid = ?
                WHERE quiz_id = ? AND question_number = 1
                """,
                (
                    source_lineage["question_uid"],
                    source_lineage["canonical_question_uid"],
                    quiz_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        bundle_bytes, _name, manifest = self._export([quiz_id])
        self.assertNotIn("question_uid", json.dumps(manifest))
        self.assertNotIn(source_lineage["question_uid"], json.dumps(manifest))
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
                "SELECT id, question_type, media_json, question_uid, canonical_question_uid, "
                "source_question_uid, is_generated_copy FROM questions "
                "WHERE quiz_id = ? ORDER BY question_number",
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
        self.assertNotEqual(
            source_lineage["canonical_question_uid"],
            imported_questions[0]["canonical_question_uid"],
        )
        self.assertEqual(
            imported_questions[0]["question_uid"],
            imported_questions[0]["canonical_question_uid"],
        )
        self.assertIsNone(imported_questions[0]["source_question_uid"])
        self.assertEqual(0, imported_questions[0]["is_generated_copy"])
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

    def test_canonical_hotspot_is_blocked_instead_of_converted_to_choice(self):
        image=Path(dlms.QUIZ_ASSET_FOLDER)/'hotspot/diagram.png'
        image.parent.mkdir()
        Image.new('RGB',(8,8),'navy').save(image)
        surrogate=self._choice('Locate the control [Image hotspot]',image_url='/quiz-assets/hotspot/diagram.png')
        surrogate['choices']=[dict(label='A',text='Control',is_correct=True)]
        quiz=self._seed('Canonical Image Study','image-study.html',[surrogate])
        good=self._seed('Ordinary image choice','ordinary-image.html',[
            self._choice(image_url='/quiz-assets/hotspot/diagram.png')])
        with dlms.get_db() as connection:
            before=list(connection.iterdump())
            report=dlms._preflight_portable_quiz_export(connection.cursor(),dlms.load_registry(),[quiz,good])
            self.assertEqual((0,1),(report['warning_quizzes'],report['blocked_quizzes']))
            issue=report['quizzes'][0]['blockers'][0]
            self.assertEqual((1,1),(issue['position'],issue['number']))
            self.assertIn('Image hotspot targets',issue['reason'])
            self.assertEqual(before,list(connection.iterdump()))
        with self.assertRaisesRegex(bundles.PortableQuizBundleError,'hotspot target geometry'):
            self._export([quiz])
        with zipfile.ZipFile(io.BytesIO(self._export([good])[0])) as archive:
            self.assertEqual(1,len(json.loads(archive.read(bundles.PORTABLE_QUIZ_BUNDLE_MANIFEST))['quizzes']))
        client=dlms.app.test_client()
        response=client.post('/quiz-bundles/export',data={'quiz_ids':[str(quiz),str(good)]},headers=csrf_headers(client,'/quiz-bundles'))
        self.assertEqual(response.status_code,400)
        html=response.get_data(as_text=True)
        self.assertIn('hotspot targets',html)
        self.assertEqual(2,html.count(' checked'))

    def test_no_media_hotspot_surrogate_and_forged_bundles_are_refused(self):
        surrogate=self._choice('Locate the control [Image hotspot]')
        surrogate['choices']=[dict(label='A',text='Control',is_correct=True)]
        quiz=self._seed('Anatomy database surrogate','anatomy.html',[surrogate])
        with dlms.get_db() as connection:
            report=dlms._preflight_portable_quiz_export(connection.cursor(),dlms.load_registry(),[quiz])
            self.assertEqual(1,report['blocked_quizzes'])
        with self.assertRaisesRegex(bundles.PortableQuizBundleError,'hotspot target geometry'):
            self._export([quiz])
        for version in (1,2):
            with self.subTest(version=version):
                manifest=self._minimal_manifest()
                manifest['schema_version']=version
                question=manifest['quizzes'][0]['questions'][0]
                question['question']='Locate the control [Image hotspot]'
                if version==2:
                    for index,choice in enumerate(question['choices']):choice['key']=f'choice-{index+1:03d}'
                with self.assertRaisesRegex(bundles.PortableQuizBundleError,'hotspot target geometry'):
                    bundles.validate_portable_quiz_bundle_manifest(manifest)
                archive=self._write_bundle(manifest)
                client=dlms.app.test_client()
                response=client.post('/quiz-bundles/import',data={'bundle_zip':(io.BytesIO(archive.read_bytes()),'hotspot.zip')},headers=csrf_headers(client,'/quiz-bundles'))
                self.assertEqual(response.status_code,400)
                self.assertIn('not a valid, safe DLMS portable quiz bundle',response.get_data(as_text=True))
                with dlms.get_db() as connection:
                    self.assertEqual(1,connection.execute('SELECT count(*) FROM quizzes').fetchone()[0])
                self.assertEqual([],list(Path(dlms.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER).iterdir()))

    def test_catalog_accounts_for_visibility_types_and_unavailable_entries(self):
        visible = self._seed('Visible source', 'visible.html', [self._choice()])
        hidden = self._seed('Hidden source', 'hidden.html', [self._choice()], folder='Custom')
        matching = self._seed('Matching source', 'matching.html', [self._matching()])
        image = self._seed('Image source', 'image.html', [self._choice(image_url='/media/demo.png')])
        legacy = self._seed('Legacy ordinary', 'legacy.html', [self._choice()])
        generated = self._seed('Due practice', 'generated.html', [self._choice()])
        mixed = self._seed('Curated mixture', 'mixed.html', [self._choice()])
        hotspot = self._seed('Hotspot source', 'hotspot.html', [self._choice()])
        self._seed('Empty source', 'empty.html', [])
        registry = dlms.load_registry()
        next(item for item in registry if item['id'] == hidden)['hidden'] = True
        registry += [{'id': 999999, 'title': 'Unavailable'}, {'id': 'invalid'}]
        dlms.save_registry(registry)
        connection = dlms.get_db()
        try:
            connection.execute("UPDATE quizzes SET generation_kind='source' WHERE id=?", (visible,))
            connection.execute("UPDATE quizzes SET generation_kind='native_spaced_review' WHERE id=?", (generated,))
            connection.execute("UPDATE quizzes SET generation_kind='mixed_quiz' WHERE id=?", (mixed,))
            connection.execute("UPDATE questions SET question_type='hotspot' WHERE quiz_id=?", (hotspot,))
            connection.commit()
            before = list(connection.iterdump())
            catalog = bundles.portable_quiz_export_catalog(connection.cursor(), registry)
            self.assertEqual({visible, hidden, matching, image, legacy}, {q['quiz_id'] for q in catalog['quizzes']})
            self.assertEqual(11, catalog['library_count'])
            self.assertEqual(5, catalog['candidate_count'])
            self.assertEqual(1, catalog['hidden_included'])
            self.assertEqual(2, catalog['excluded_generated_count'])
            self.assertEqual(2, catalog['unavailable'])
            self.assertEqual(1, catalog['empty'])
            self.assertEqual(1, catalog['unsupported'])
            self.assertEqual(before, list(connection.iterdump()))
        finally:
            connection.close()
        html = dlms.app.test_client().get('/quiz-bundles').get_data(as_text=True)
        self.assertIn('5 source quizzes available', html)
        self.assertIn('Hidden quizzes included: 1', html)
        self.assertIn('Browse the pages to see all 5 candidates', html)
        self.assertIn('Folder visibility does not limit export', html)
        with self.assertRaises(bundles.PortableQuizBundleError):
            self._export([hotspot])

    def test_large_catalog_is_not_limited_to_the_visible_scroll_window(self):
        ids = [self._seed(f'Source {index}', f'source-{index}.html', [self._choice()]) for index in range(191)]
        registry = dlms.load_registry()
        for entry in registry[37:]:
            entry['hidden'] = True
        dlms.save_registry(registry)
        html = dlms.app.test_client().get('/quiz-bundles').get_data(as_text=True)
        self.assertEqual(191, html.count('name="quiz_ids"'))
        self.assertIn('191 source quizzes available', html)
        self.assertIn('Hidden quizzes included: 154', html)
        self.assertIn(f'value="{ids[-1]}"', html)

    def test_explicit_generation_metadata_and_legacy_type_normalization(self):
        ordinary = self._seed('Adaptive Study — authored source', 'authored.html', [self._choice()])
        kinds = ('adaptive_study', 'smart_review', 'concept_review', 'native_spaced_review', 'spaced_review', 'mixed_quiz')
        generated = [(self._seed(f'Generated {kind}', f'{kind}.html', [self._choice()]), kind) for kind in kinds]
        connection = dlms.get_db()
        try:
            connection.execute("UPDATE quizzes SET generation_kind='source' WHERE id=?", (ordinary,))
            connection.execute("UPDATE questions SET question_type=' Choice ' WHERE quiz_id=?", (ordinary,))
            connection.executemany('UPDATE quizzes SET generation_kind=? WHERE id=?', [(kind, quiz) for quiz, kind in generated])
            connection.commit()
            catalog = bundles.portable_quiz_export_catalog(connection.cursor(), dlms.load_registry())
            self.assertEqual([ordinary], [quiz['quiz_id'] for quiz in catalog['quizzes']])
            self.assertEqual(6, catalog['excluded_generated_count'])
        finally:
            connection.close()
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

    def _download(self, ids):
        connection = dlms.get_db()
        try:
            return dlms._build_portable_quiz_download(connection.cursor(), dlms.load_registry(), ids)
        finally:
            connection.close()

    def _import_bytes(self, payload):
        client = dlms.app.test_client()
        staged = client.post('/quiz-bundles/import', data={'bundle_zip': (io.BytesIO(payload), 'part.zip')},
                             headers=csrf_headers(client, '/quiz-bundles'))
        self.assertEqual(302, staged.status_code, staged.data[:500])
        url = staged.headers['Location']
        confirmed = client.post(url + '/confirm', data={'confirm_import': 'yes'}, headers=csrf_headers(client, url))
        self.assertEqual(302, confirmed.status_code)

    def test_duplicate_choice_text_identity_round_trip_and_actual_grading(self):
        from dlms.services.attempts import _choice_response
        from dlms.services.content_packs import _content_pack_choice_question_errors
        for correct in ((True, False, False, False), (True, False, True, False)):
            with self.subTest(correct=correct):
                q = self._choice()
                q['choices'] = [{'label': chr(65+i), 'text': text, 'is_correct': correct[i]}
                                for i, text in enumerate(('  Same text  ', 'Same text', 'same TEXT', 'Other'))]
                self.assertTrue(_content_pack_choice_question_errors(q, context='AI authoring'))
                original = self._seed('Repeated text', 'repeat-'+str(len(dlms.load_registry()))+'.html', [q])
                data, _, manifest = self._export([original])
                self.assertEqual([{**c,'key':f'choice-{i:03d}'} for i,c in enumerate(q['choices'],1)], manifest['quizzes'][0]['questions'][0]['choices'])
                old_ids = {e['id'] for e in dlms.load_registry()}
                self._import_bytes(data)
                imported = next(e['id'] for e in dlms.load_registry() if e['id'] not in old_ids)
                with dlms.get_db() as c:
                    question_id = c.execute('SELECT id FROM questions WHERE quiz_id=?', (imported,)).fetchone()[0]
                    choices = c.execute('SELECT label,text,is_correct FROM choices WHERE question_id=? ORDER BY label', (question_id,)).fetchall()
                    self.assertEqual([(x['label'], x['text'], int(x['is_correct'])) for x in q['choices']], [tuple(x) for x in choices])
                    for study in (True, False):
                        expected = [x['label'] for x in q['choices'] if x['is_correct']]
                        self.assertTrue(_choice_response(c.cursor(), question_id, expected, study=study)[1])
                        self.assertFalse(_choice_response(c.cursor(), question_id, ['B', 'D'] if len(expected)==2 else ['B'], study=study)[1])
                    payload = dlms._question_payload_from_db(c.cursor(), question_id)
                    self.assertEqual(expected, payload['correct'])

    def test_collection_count_boundaries_inventory_and_complete_reimport(self):
        ids = [self._seed(f'Synthetic {i}', f'part-{i}.html', [self._choice()], folder='Sample') for i in range(193)]
        for size, counts in ((99,[99]), (100,[100]), (101,[100,1]), (193,[100,93])):
            with self.subTest(size=size):
                job = self._download(ids[:size])
                try:
                    if len(counts)==1:
                        self.assertEqual(counts[0], self._inspect(job.path)['quiz_count'])
                    else:
                        with zipfile.ZipFile(job.path) as collection:
                            inventory = json.loads(collection.read('inventory.json'))
                            self.assertEqual(counts, [p['quiz_count'] for p in inventory['bundles']])
                            got = [q['source_quiz_id'] for part in inventory['bundles'] for q in part['quizzes']]
                            self.assertEqual(ids[:size], got)
                            self.assertEqual(size, len(set(got)))
                            for part in inventory['bundles']:
                                data = collection.read(part['filename'])
                                self.assertEqual(part['sha256'], hashlib.sha256(data).hexdigest())
                                path = self.root / part['filename']; path.write_bytes(data)
                                self.assertEqual(part['quiz_count'], self._inspect(path)['quiz_count'])
                                if size==193:
                                    self._import_bytes(data)
                        with self.assertRaisesRegex(bundles.PortableQuizBundleError, 'manifest|unexpected'):
                            self._inspect(job.path)  # Collection intentionally is not importable.
                finally:
                    root = job.path.parent;job.close();self.assertFalse(root.exists())
        self.assertEqual(386, len(dlms.load_registry()))
        with dlms.get_db() as c:
            self.assertEqual(386, c.execute('SELECT COUNT(*) FROM questions').fetchone()[0])
            self.assertEqual(0, c.execute('SELECT COUNT(*) FROM attempts').fetchone()[0])
            self.assertEqual(0, c.execute('SELECT COUNT(*) FROM study_responses').fetchone()[0])

    def test_collection_splits_question_member_and_manifest_budgets(self):
        ids = [self._seed(f'Budget {i}', f'budget-{i}.html', [self._choice()]) for i in range(5)]
        with mock.patch.object(bundles, 'PORTABLE_QUIZ_BUNDLE_MAX_TOTAL_QUESTIONS', 2):
            job = self._download(ids)
            try:
                with zipfile.ZipFile(job.path) as z:
                    inv = json.loads(z.read('inventory.json'))
                    self.assertEqual([2,2,1], [x['quiz_count'] for x in inv['bundles']])
            finally:job.close()
        from dlms.services import portable_quiz_exports as exports
        manifest = self._minimal_manifest()
        base = len(exports._manifest_bytes(manifest))
        with mock.patch.object(bundles, '_MAX_MANIFEST_BYTES', base-1):
            self.assertFalse(exports._fits(manifest))
        with mock.patch.object(bundles, 'PORTABLE_QUIZ_BUNDLE_UPLOAD_MAX_BYTES', base):
            self.assertFalse(exports._fits(manifest))
        with mock.patch.object(bundles, 'PORTABLE_QUIZ_BUNDLE_MAX_FILES', 0):
            self.assertFalse(exports._fits(manifest))

    def test_actionable_media_error_keeps_selection_filters_and_no_partial_output(self):
        good = self._seed('Good bank', 'good.html', [self._choice()])
        bad = self._seed('Missing diagram', 'bad.html', [self._choice(image_url='/quiz-assets/missing/picture.png')])
        client = dlms.app.test_client()
        response = client.post('/quiz-bundles/export', data={'quiz_ids':[str(good),str(bad)], 'export_search':'diagram', 'export_folder':'Uncategorized'}, headers=csrf_headers(client,'/quiz-bundles'))
        self.assertEqual(400, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn('Missing diagram · quiz ID', html)
        self.assertNotIn(str(self.root), html)
        self.assertEqual(2, html.count(' checked'))
        self.assertIn('value="diagram"', html)
        self.assertEqual([], list((Path(dlms.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER)/'exports').glob('export-*')))
        response = client.post('/quiz-bundles/export', data={},headers=csrf_headers(client,'/quiz-bundles'))
        self.assertEqual(400,response.status_code)
        self.assertIn('Select between 1 and 1,000',response.get_data(as_text=True))

    def test_malformed_question_identified_and_unexpected_error_not_leaked(self):
        quiz = self._seed('Malformed sample', 'broken.html', [self._choice()])
        with dlms.get_db() as c:c.execute('UPDATE choices SET is_correct=0 WHERE question_id IN (SELECT id FROM questions WHERE quiz_id=?)',(quiz,));c.commit()
        client = dlms.app.test_client()
        r = client.post('/quiz-bundles/export', data={'quiz_ids':str(quiz)}, headers=csrf_headers(client,'/quiz-bundles'))
        self.assertEqual(200,r.status_code);r.close()
        # Missing answers are now preservable warnings, not export blockers.
        checked = client.post('/quiz-bundles/export', data={'quiz_ids':str(quiz),'export_action':'check'}, headers=csrf_headers(client,'/quiz-bundles'))
        self.assertIn('No correct answer is marked',checked.get_data(as_text=True))
        self.assertIn('0 blocked',checked.get_data(as_text=True))
        with dlms.get_db() as conn:
            signature=dlms._preflight_portable_quiz_export(conn.cursor(),dlms.load_registry(),[quiz])['signature']
        with mock.patch.object(dlms,'_build_portable_quiz_download',side_effect=OSError('/secret/absolute/path')):
            r = client.post('/quiz-bundles/export',data={'quiz_ids':str(quiz),'export_action':'preserve','warning_snapshot':signature},headers=csrf_headers(client,'/quiz-bundles'))
        self.assertEqual(500,r.status_code);self.assertNotIn('/secret',r.get_data(as_text=True));self.assertIn(' checked',r.get_data(as_text=True))

    def test_interrupted_stream_and_failed_build_release_files_and_export_slot(self):
        from dlms.services import portable_quiz_exports as exports
        quiz = self._seed('Stream fixture', 'stream.html', [self._choice()])
        client=dlms.app.test_client()
        response=client.post('/quiz-bundles/export',data={'quiz_ids':str(quiz)},headers=csrf_headers(client,'/quiz-bundles'),buffered=False)
        self.assertEqual(200,response.status_code);next(iter(response.response));response.close()
        root=Path(dlms.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER)/'exports'
        self.assertEqual([],list(root.glob('export-*')))
        with mock.patch.object(dlms,'_inspect_portable_quiz_bundle',side_effect=OSError('Interrupted validation')):
            with self.assertRaises(OSError):self._download([quiz])
        self.assertEqual([],list(root.glob('export-*')))
        with mock.patch.object(exports,'MAX_DOWNLOAD_BYTES',1):
            with self.assertRaisesRegex(exports.ExportSelectionError,'512 MiB'):self._download([quiz])
        self.assertEqual([],list(root.glob('export-*')))
        self.assertTrue(exports._EXPORT_SLOTS.acquire(blocking=False))
        self.assertTrue(exports._EXPORT_SLOTS.acquire(blocking=False))
        try:
            with self.assertRaises(exports.ExportBusyError):self._download([quiz])
        finally:exports._EXPORT_SLOTS.release();exports._EXPORT_SLOTS.release()

    def test_simultaneous_exports_have_unique_complete_jobs(self):
        from concurrent.futures import ThreadPoolExecutor
        quiz=self._seed('Concurrent fixture','concurrent.html',[self._choice()])
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=list(pool.map(lambda _:self._download([quiz]),range(2)))
        try:
            self.assertNotEqual(jobs[0].path,jobs[1].path)
            for job in jobs:self.assertEqual(1,self._inspect(job.path)['quiz_count'])
        finally:
            for job in jobs:job.close()

    def test_disk_full_is_storage_error_retains_selection_and_cleans_job(self):
        import errno
        quiz = self._seed('Storage sample', 'storage.html', [self._choice()])
        client = dlms.app.test_client()
        with mock.patch.object(dlms, '_build_portable_quiz_bundle', side_effect=OSError(errno.ENOSPC, 'No space', '/private/path')):
            response = client.post('/quiz-bundles/export', data={'quiz_ids': str(quiz), 'export_search': 'Storage'}, headers=csrf_headers(client, '/quiz-bundles'))
        text = response.get_data(as_text=True)
        self.assertEqual(500, response.status_code)
        self.assertIn('storage or server error', text)
        self.assertNotIn('/private/path', text)
        self.assertRegex(text, rf'value="{quiz}"[^>]*checked')
        self.assertIn('value="Storage"', text)
        self.assertEqual([], list((Path(dlms.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER) / 'exports').glob('export-*')))

    def test_collection_media_references_remain_distinct_and_importable(self):
        image = Path(dlms.QUIZ_ASSET_FOLDER) / 'sample' / 'sample.png'
        image.parent.mkdir()
        Image.new('RGB', (12, 12), 'navy').save(image)
        ids = [self._seed(f'Media {n}', f'media-{n}.html', [self._choice(image_url='/quiz-assets/sample/sample.png')]) for n in range(3)]
        old_ids = {entry['id'] for entry in dlms.load_registry()}
        with mock.patch.object(bundles, 'PORTABLE_QUIZ_BUNDLE_MAX_TOTAL_QUESTIONS', 2):
            job = self._download(ids)
        try:
            with zipfile.ZipFile(job.path) as collection:
                inventory = json.loads(collection.read('inventory.json'))
                self.assertEqual([2, 1], [part['quiz_count'] for part in inventory['bundles']])
                for part in inventory['bundles']:
                    self._import_bytes(collection.read(part['filename']))
        finally:
            job.close()
        imported = [entry['id'] for entry in dlms.load_registry() if entry['id'] not in old_ids]
        self.assertEqual(3, len(imported))
        paths = []
        with dlms.get_db() as connection:
            for quiz in imported:
                media = json.loads(connection.execute('SELECT media_json FROM questions WHERE quiz_id=?', (quiz,)).fetchone()[0])
                path = Path(dlms.QUIZ_ASSET_FOLDER) / media['image_url'].removeprefix('/quiz-assets/')
                paths.append(path)
                self.assertEqual(image.read_bytes(), path.read_bytes())
        self.assertEqual(3, len(set(paths)))

    def test_export_rejects_symlink_media_without_reading_outside_assets(self):
        outside = self.root / 'private.png'
        Image.new('RGB', (12, 12), 'navy').save(outside)
        link = Path(dlms.QUIZ_ASSET_FOLDER) / 'sample' / 'linked.png'
        link.parent.mkdir()
        link.symlink_to(outside)
        quiz = self._seed('Linked image', 'linked.html', [self._choice(image_url='/quiz-assets/sample/linked.png')])
        from dlms.services.portable_quiz_exports import ExportSelectionError
        with self.assertRaises(ExportSelectionError) as caught:
            self._download([quiz])
        self.assertEqual(quiz, caught.exception.report['quizzes'][0]['quiz_id'])
        self.assertEqual(1, caught.exception.report['quizzes'][0]['blockers'][0]['position'])
        self.assertTrue(outside.is_file())
        self.assertEqual([], list((Path(dlms.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER) / 'exports').glob('export-*')))

    def test_preserved_choice_raw_length_cannot_bypass_limit(self):
        q=self._minimal_manifest()
        q['quizzes'][0]['questions'][0]['choices'][0]['text']=' '*4000+'x'
        with self.assertRaisesRegex(bundles.PortableQuizBundleError,'character limit'):
            bundles.validate_portable_quiz_bundle_manifest(q)

    def test_cleanup_failure_still_releases_bounded_export_slot(self):
        from dlms.services import portable_quiz_exports as exports
        quiz=self._seed('Cleanup fixture','cleanup.html',[self._choice()])
        with mock.patch.object(dlms,'_inspect_portable_quiz_bundle',side_effect=ValueError('Bad asset')), mock.patch.object(exports.tempfile.TemporaryDirectory,'cleanup',side_effect=OSError('Cleanup interrupted')):
            with self.assertRaisesRegex(OSError,'Cleanup interrupted'):
                self._download([quiz])
        self.assertTrue(exports._EXPORT_SLOTS.acquire(blocking=False))
        self.assertTrue(exports._EXPORT_SLOTS.acquire(blocking=False))
        exports._EXPORT_SLOTS.release();exports._EXPORT_SLOTS.release()

    def test_selection_validation_and_import_limits_remain_strict(self):
        from dlms.services import portable_quiz_exports as exports
        for ids in (['oops'],[-1],[True],list(range(1,1002))):
            with self.subTest(ids_type=type(ids[0]).__name__),self.assertRaises(exports.ExportSelectionError):
                self._download(ids)
        manifest=self._minimal_manifest()
        for field,value in [('label','B'),('is_correct','true'),('text','')]:
            m=copy.deepcopy(manifest);m['quizzes'][0]['questions'][0]['choices'][0][field]=value
            with self.subTest(field=field),self.assertRaises(bundles.PortableQuizBundleError):
                bundles.validate_portable_quiz_bundle_manifest(m)


if __name__ == "__main__":
    unittest.main()
