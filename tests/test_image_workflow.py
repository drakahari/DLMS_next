"""DLMS image workflow regression tests.
Run from the project root inside the DLMS venv:
    python -m unittest tests.test_image_workflow
The suite uses an isolated temporary APP_DATA_DIR and never touches real DLMS data.
"""
import json, os, shutil, tempfile, unittest
from datetime import datetime, timezone
from unittest import mock
from pathlib import Path
from PIL import Image

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-image-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms
from tests.csrf_test_utils import csrf_headers, csrf_token


def _write_test_image(path):
    formats = {".png": "PNG", ".jpg": "JPEG", ".webp": "WEBP"}
    Image.new("RGB", (8, 6), (40, 120, 200)).save(path, format=formats[Path(path).suffix.lower()])


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


class ImageWorkflowTests(unittest.TestCase):
    def setUp(self):
        # The app module may already have been imported by another test module.
        # Rebind its path globals before every test so suite order cannot leak state.
        _bind_dlms_test_paths()
        for name in ("content_packs", "quiz_assets", "data", "quizzes", "config", "content_pack_staging"):
            p = Path(_TEMP.name) / name
            if p.exists():
                shutil.rmtree(p)
            p.mkdir(parents=True, exist_ok=True)
        _bind_dlms_test_paths()

    def make_pack(self):
        root = Path(_TEMP.name) / "content_packs" / "DLMS_Study_images"
        (root / "data").mkdir(parents=True, exist_ok=True)
        (root / "images").mkdir(parents=True, exist_ok=True)
        for name in ("diagram.png", "photo.jpg", "interface.webp"):
            _write_test_image(root / "images" / name)

        manifest = {
            "schema_version": 1,
            "id": "study_images",
            "name": "Image Workflow Test",
            "version": "1.0.0",
            "content_domain": "it_cybersecurity",
            "datasets": [],
            "image_datasets": [{"id":"visuals","title":"Visuals","type":"hotspot","path":"data/visuals.json"}],
            "quiz_datasets": [{"id":"mixed","title":"Mixed","type":"quiz","path":"data/mixed.json"}],
        }
        source = {"organization":"DLMS Test","url":"https://example.invalid/source","license":"CC0","attribution":"Test asset"}
        images = [
            {"id":"png","file":"images/diagram.png","license":"CC0","source":source,"concepts":["diagram-navigation"],"hotspots":[{"id":"circle","label":"Circle Target","concepts":["circle-target"],"shape":{"type":"circle","x":0.4,"y":0.4,"radius":0.08}}]},
            {"id":"jpg","file":"images/photo.jpg","license":"CC0","source":source,"hotspots":[{"id":"poly","label":"Polygon Target","shape":{"type":"polygon","points":[[0.1,0.1],[0.4,0.1],[0.25,0.4]]}}]},
            {"id":"webp","file":"images/interface.webp","license":"CC0","source":source,"hotspots":[{"id":"edge","label":"Edge Target","shape":{"type":"circle","x":0.95,"y":0.5,"radius":0.04}}]},
        ]
        visual = {"schema_version":1,"id":"visuals","title":"Visuals","type":"hotspot","source":source,"images":images}
        mixed = {
            "schema_version":1,"id":"mixed","title":"Mixed","source":source,
            "images":[images[0]],
            "questions":[
                {"type":"choice","question":"Choose the documented option.","image_id":"png","concepts":["choice-skill"],"choices":[{"text":"One","is_correct":True},{"text":"Two","is_correct":False}]},
                {"type":"matching","question":"Match these items.","concepts":["matching-skill"],"pairs":[{"left":"A","right":"1"},{"left":"B","right":"2"}]},
                {"type":"hotspot","question":"Find the target.","image_id":"png","hotspot_id":"circle"},
            ],
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "data" / "visuals.json").write_text(json.dumps(visual), encoding="utf-8")
        (root / "data" / "mixed.json").write_text(json.dumps(mixed), encoding="utf-8")
        (root / "PACK_VALIDATION.json").write_text(json.dumps({"schema_version":1,"pack_id":"study_images","overall_status":"PASS","checks":[]}), encoding="utf-8")
        return root

    def test_png_jpg_webp_and_circle_polygon_hotspots_load(self):
        root = self.make_pack()
        report = dlms._validate_staged_content_pack(str(root))
        self.assertTrue(report["valid"], report["errors"])
        data = dlms.load_content_pack_image_dataset("study_images", "visuals")
        self.assertEqual(3, len(data["images"]))
        self.assertEqual({".png", ".jpg", ".webp"}, {Path(i["file"]).suffix for i in data["images"]})
        self.assertEqual("polygon", data["images"][1]["hotspots"][0]["shape"]["type"])

    def test_mixed_question_dataset_builds_choice_matching_and_hotspot(self):
        self.make_pack()
        data = dlms.load_content_pack_quiz_dataset("study_images", "mixed")
        with dlms.app.test_request_context():
            runtime, db_questions = dlms._quiz_dataset_runtime("study_images", data)
        self.assertEqual(["choice", "matching", "hotspot"], [q["type"] for q in runtime])
        self.assertEqual(3, len(db_questions))
        self.assertTrue(runtime[0]["image_url"].endswith("/images/diagram.png"))
        self.assertEqual(["choice-skill"], runtime[0]["concepts"])
        self.assertEqual(["matching-skill"], runtime[1]["concepts"])
        self.assertEqual(["circle-target"], runtime[2]["concepts"])
        self.assertEqual(["circle-target"], db_questions[2]["concepts"])

    def test_generated_mixed_questions_persist_concepts_through_database_rebuild(self):
        self.make_pack()
        data = dlms.load_content_pack_quiz_dataset("study_images", "mixed")
        with dlms.app.test_request_context():
            runtime, db_questions = dlms._quiz_dataset_runtime("study_images", data)
        quiz_id = dlms.save_quiz_to_db("Tagged mixed pack", "tagged-mixed.html", db_questions)
        conn = dlms.get_db()
        rows = conn.execute("SELECT id, question_number FROM questions WHERE quiz_id=? ORDER BY question_number", (quiz_id,)).fetchall()
        concepts = [dlms._question_concepts(conn.cursor(), row[0]) for row in rows]
        cur = conn.cursor()
        dlms._record_learning_event(
            cur, event_type="exam_answer", quiz_id=quiz_id, question_id=rows[1][0],
            attempt_id="mixed-matching", mode="Exam", was_correct=False,
        )
        dlms._record_learning_event(
            cur, event_type="study_answer", quiz_id=quiz_id, question_id=rows[2][0],
            session_id="mixed-hotspot", mode="Study", was_correct=True,
        )
        for index, was_correct in enumerate((False, False, True, False, False)):
            dlms._record_learning_event(
                cur, event_type="exam_answer", quiz_id=quiz_id, question_id=rows[0][0],
                attempt_id=f"mixed-choice-{index}", mode="Exam", was_correct=was_correct,
            )
        conn.commit()
        topic_names = {
            topic["name"] for topic in dlms._learning_intelligence_topics(
                cur, now=datetime.now(timezone.utc)
            )
        }
        self.assertEqual([["choice-skill"], ["matching-skill"], ["circle-target"]], concepts)
        self.assertEqual(["choice-skill"], runtime[0]["concepts"])
        self.assertTrue({"matching-skill", "circle-target"}.issubset(topic_names))
        candidates, _ = dlms._smart_review_candidates(cur)
        self.assertTrue(any(candidate["question_id"] == rows[0][0] for candidate in candidates))
        conn.close()

    def test_mixed_choice_generation_preserves_mcq_data_and_learning_evidence_end_to_end(self):
        root = self.make_pack()
        mixed_path = root / "data" / "mixed.json"
        mixed = json.loads(mixed_path.read_text(encoding="utf-8"))
        mixed["questions"][0]["question"] = "Which generated MCQ option is documented?"
        mixed["questions"][0]["explanation"] = "The documented option is supported by the source."
        mixed_path.write_text(json.dumps(mixed), encoding="utf-8")
        client = dlms.app.test_client()
        generated = client.post("/study-packs/quiz/generate", data={
            "csrf_token": csrf_token(client, "/study-packs"),
            "pack_id": "study_images",
            "dataset_id": "mixed",
        })
        self.assertEqual(302, generated.status_code, generated.get_data(as_text=True))

        conn = dlms.get_db()
        try:
            quiz = conn.execute(
                "SELECT id FROM quizzes WHERE title = ? ORDER BY id DESC LIMIT 1",
                ("Mixed — Practice",),
            ).fetchone()
            self.assertIsNotNone(quiz)
            quiz_id = quiz["id"]
            question = conn.execute("""
                SELECT id, explanation FROM questions
                WHERE quiz_id = ? AND question_number = 1
            """, (quiz_id,)).fetchone()
            choices = conn.execute("""
                SELECT label, text, is_correct FROM choices
                WHERE question_id = ? ORDER BY label
            """, (question["id"],)).fetchall()
            self.assertEqual(["A", "B"], [row["label"] for row in choices])
            self.assertEqual([True, False], [bool(row["is_correct"]) for row in choices])
            self.assertEqual("The documented option is supported by the source.", question["explanation"])
            self.assertEqual(["choice-skill"], dlms._question_concepts(conn.cursor(), question["id"]))
        finally:
            conn.close()

        self.assertTrue(dlms.rebuild_quiz_json_from_db(quiz_id))
        registry_entry = next(item for item in dlms.load_registry() if item["id"] == quiz_id)
        rebuilt = json.loads((Path(dlms.DATA_FOLDER) / registry_entry["html"].replace(".html", ".json")).read_text())
        self.assertEqual(["A"], rebuilt[0]["correct"])
        self.assertEqual("Which generated MCQ option is documented?", rebuilt[0]["question"])
        self.assertEqual("The documented option is supported by the source.", rebuilt[0]["explanation"])
        self.assertEqual(["choice-skill"], rebuilt[0]["concepts"])
        edit_page = client.get(f"/edit_quiz/{quiz_id}").get_data(as_text=True)
        self.assertIn("Which generated MCQ option is documented?", edit_page)
        self.assertIn("The documented option is supported by the source.", edit_page)
        self.assertIn("choice-skill", edit_page)

        study = client.post("/api/learning-events/study-response", json={
            "quizId": quiz_id, "questionNumber": 1, "sessionId": "mixed-choice-study",
            "wasCorrect": False, "questionType": "choice", "selected": ["B"],
        }, headers=csrf_headers(client))
        self.assertEqual(200, study.status_code, study.get_data(as_text=True))
        for index in range(5):
            exam = client.post("/record_attempt", json={
                "quizId": quiz_id, "quizTitle": "Mixed — Practice", "attemptId": f"mixed-choice-{index}",
                "score": 0, "total": 1, "percent": 0, "mode": "Exam",
                "responseDetails": [{
                    "attemptQuestionNumber": 1, "questionType": "choice",
                    "wasCorrect": False, "selected": ["B"],
                }],
                "missedDetails": [],
            }, headers=csrf_headers(client))
            self.assertEqual(200, exam.status_code, exam.get_data(as_text=True))

        conn = dlms.get_db()
        try:
            cur = conn.cursor()
            event_counts = {
                row["event_type"]: row["count"]
                for row in cur.execute("""
                    SELECT event_type, COUNT(*) AS count FROM learning_events
                    WHERE question_id = ? GROUP BY event_type
                """, (question["id"],)).fetchall()
            }
            topics = dlms._learning_intelligence_topics(cur, now=datetime.now(timezone.utc))
            candidates, weak = dlms._smart_review_candidates(cur)
        finally:
            conn.close()
        topic = next(item for item in topics if item["name"] == "choice-skill")
        self.assertEqual(1, event_counts["study_answer"])
        self.assertEqual(5, event_counts["exam_answer"])
        self.assertEqual("weak", topic["status"])
        self.assertTrue(any(item["name"] == "choice-skill" for item in weak))
        self.assertTrue(any(item["question_id"] == question["id"] for item in candidates))

    def test_image_hotspot_surrogate_uses_explicit_hotspot_concepts(self):
        self.make_pack()
        client = dlms.app.test_client()
        response = client.post("/study-packs/image/generate", data={
            "csrf_token": csrf_token(client, "/study-packs"),
            "pack_id": "study_images",
            "dataset_id": "visuals",
        })
        self.assertEqual(302, response.status_code)
        conn = dlms.get_db()
        row = conn.execute("""
            SELECT questions.id
            FROM questions JOIN quizzes ON quizzes.id = questions.quiz_id
            WHERE quizzes.title = 'Visuals — Image Practice'
              AND questions.question_text LIKE 'Identify Circle Target%'
            ORDER BY questions.id DESC LIMIT 1
        """).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(["circle-target"], dlms._question_concepts(conn.cursor(), row[0]))
        conn.close()

    def test_mixed_matching_ambiguity_is_rejected_by_staged_and_runtime_validation(self):
        root = self.make_pack()
        mixed_path = root / "data" / "mixed.json"
        mixed = json.loads(mixed_path.read_text(encoding="utf-8"))
        mixed["questions"][1]["pairs"] = [
            {"id":"pair-1","left":" Alpha ","right":"First"},
            {"id":"PAIR-1","left":"Alpha","right":"Second"},
        ]
        mixed_path.write_text(json.dumps(mixed), encoding="utf-8")

        report = dlms._validate_staged_content_pack(str(root))
        self.assertFalse(report["valid"])
        joined = "\n".join(report["errors"])
        self.assertIn("matching question 2 'Match these items.'", joined)
        self.assertIn("conflicting ID", joined)
        self.assertIn("one left maps to multiple answers", joined)
        self.assertIn("earlier pair 1", joined)

        with self.assertRaisesRegex(ValueError, "conflicting ID"):
            dlms.load_content_pack_quiz_dataset("study_images", "mixed")

    def test_distinct_mixed_matching_records_remain_accepted(self):
        self.make_pack()
        data = dlms.load_content_pack_quiz_dataset("study_images", "mixed")
        matching = next(q for q in data["questions"] if q["type"] == "matching")
        self.assertEqual(2, len(matching["pairs"]))

    def test_snapshot_survives_source_pack_removal(self):
        root = self.make_pack()
        runtime = [{"number":1,"type":"choice","question":"Image","image_url":"/content-packs/study_images/assets/images/diagram.png","choices":[{"label":"A","text":"One","is_correct":True}],"correct":["A"]}]
        db_questions = [dict(runtime[0])]
        snap_runtime, _, count = dlms._snapshot_runtime_questions("study_images", runtime, db_questions, "snapshot_test")
        self.assertGreater(count, 0)
        self.assertTrue(snap_runtime[0]["image_url"].startswith("/quiz-assets/snapshot_test/"))
        shutil.rmtree(root)
        snap_file = Path(_TEMP.name) / "quiz_assets" / "snapshot_test" / "images" / "diagram.png"
        self.assertTrue(snap_file.is_file())

    def test_quiz_asset_route_uses_url_path_not_os_relpath(self):
        # Regression for Windows packaged builds: os.path.relpath() produces
        # backslashes, which send_from_directory() can reject as unsafe.
        asset = Path(_TEMP.name) / "quiz_assets" / "snapshot_test" / "images" / "diagram.png"
        asset.parent.mkdir(parents=True, exist_ok=True)
        _write_test_image(asset)
        with mock.patch.object(dlms.os.path, "relpath", side_effect=AssertionError("relpath must not be used by quiz_asset")):
            response = dlms.app.test_client().get("/quiz-assets/snapshot_test/images/diagram.png")
        try:
            self.assertEqual(200, response.status_code)
            self.assertTrue(response.data.startswith(b"\x89PNG\r\n\x1a\n"))
        finally:
            response.close()

    def test_invalid_hotspot_geometry_is_rejected(self):
        root = self.make_pack()
        data_path = root / "data" / "visuals.json"
        data = json.loads(data_path.read_text())
        data["images"][0]["hotspots"][0]["shape"]["x"] = 1.5
        data_path.write_text(json.dumps(data), encoding="utf-8")
        report = dlms._validate_staged_content_pack(str(root))
        self.assertFalse(report["valid"])
        self.assertTrue(any("invalid hotspot geometry" in e for e in report["errors"]))

    def test_image_editor_edits_save_valid_json_with_persisted_edits(self):
        root = self.make_pack()
        client = dlms.app.test_client()
        response = client.post(
            "/admin/image-editor/edits/save",
            json={
                "pack_id": "study_images",
                "dataset_id": "visuals",
                "dataset_kind": "hotspot",
                "image_id": "png",
                "edits": [{"type": "mask", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.2, "style": "blur"}],
            },
            headers={"X-CSRFToken": csrf_token(client)},
        )
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        with open(root / "data" / "visuals.json", encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(
            [{"type": "mask", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.2, "style": "blur"}],
            saved["images"][0]["edits"],
        )


if __name__ == "__main__":
    unittest.main()
