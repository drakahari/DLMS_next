"""DLMS-046 regressions for Medical Study Pack concept propagation."""
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-medical-concepts-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms
from tests.csrf_test_utils import csrf_headers, csrf_token


def _bind_paths():
    root = Path(_TEMP.name)
    dlms._initialize_data_root_ownership(str(root))
    dlms.APP_DATA_DIR = str(root)
    dlms.DB_PATH = str(root / "results.db")
    dlms.DATA_FOLDER = str(root / "data")
    dlms.QUIZ_FOLDER = str(root / "quizzes")
    dlms.QUIZ_ASSET_FOLDER = str(root / "quiz_assets")
    dlms.CONFIG_FOLDER = str(root / "config")
    dlms.QUIZ_REGISTRY = str(root / "config" / "quizzes.json")
    dlms.REGISTRY_FILE = dlms.QUIZ_REGISTRY
    dlms.PORTAL_CONFIG = str(root / "config" / "portal.json")
    dlms.CONTENT_PACK_FOLDER = str(root / "content_packs")
    dlms.CONTENT_PACK_STAGING_FOLDER = str(root / "content_pack_staging")
    dlms.LOGO_FOLDER = str(root / "static" / "logos")
    dlms.LOGO_TEMP_FOLDER = str(root / "static" / "logos" / "_temp")
    for path in (
        dlms.DATA_FOLDER,
        dlms.QUIZ_FOLDER,
        dlms.QUIZ_ASSET_FOLDER,
        dlms.CONFIG_FOLDER,
        dlms.CONTENT_PACK_FOLDER,
        dlms.CONTENT_PACK_STAGING_FOLDER,
        dlms.LOGO_FOLDER,
        dlms.LOGO_TEMP_FOLDER,
    ):
        os.makedirs(path, exist_ok=True)


class MedicalStudyPackConceptTests(unittest.TestCase):
    def setUp(self):
        root = Path(_TEMP.name)
        for child in root.iterdir():
            if child.name in {dlms.DLMS_DATA_ROOT_MARKER, ".secret_key"}:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        _bind_paths()
        dlms.ensure_db_initialized()

    def _write_medical_pack(self, *, matching=None, images=None):
        root = Path(dlms.CONTENT_PACK_FOLDER) / "DLMS_Study_medical_concepts"
        (root / "data").mkdir(parents=True)
        (root / "images").mkdir()
        Image.new("RGB", (12, 9), (80, 120, 170)).save(root / "images" / "diagram.png")

        datasets = []
        image_datasets = []
        if matching is not None:
            datasets.append({
                "id": "terms", "title": "Medical Terms", "type": "matching",
                "path": "data/terms.json",
            })
            matching = {
                "schema_version": 1,
                "id": "terms",
                "title": "Medical Terms",
                "category": "Medical Metadata Only",
                "source": {"organization": "DLMS Test", "license": "CC0"},
                "terms": [
                    {"term": "Nephron", "definition": "Functional kidney unit.", "category": "Renal"},
                    {"term": "Glomerulus", "definition": "Capillary filtration tuft.", "category": "Renal"},
                ],
                **matching,
            }
            (root / "data" / "terms.json").write_text(
                json.dumps(matching), encoding="utf-8"
            )

        if images is not None:
            image_datasets.append({
                "id": "anatomy", "title": "Anatomy", "type": "hotspot",
                "path": "data/anatomy.json",
            })
            image_data = {
                "schema_version": 1,
                "id": "anatomy",
                "title": "Anatomy",
                "category": "Medical Metadata Only",
                "source": {"organization": "DLMS Test", "license": "CC0"},
                "images": images,
            }
            (root / "data" / "anatomy.json").write_text(
                json.dumps(image_data), encoding="utf-8"
            )

        manifest = {
            "schema_version": 1,
            "id": "medical_concepts",
            "name": "Medical Concept Regression Pack",
            "version": "1.0.0",
            "content_domain": "medical",
            "datasets": datasets,
            "image_datasets": image_datasets,
            "quiz_datasets": [],
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    @staticmethod
    def _latest_quiz_question():
        conn = dlms.get_db()
        try:
            quiz_id = conn.execute("SELECT id FROM quizzes ORDER BY id DESC LIMIT 1").fetchone()[0]
            question_id = conn.execute(
                "SELECT id FROM questions WHERE quiz_id = ? ORDER BY question_number, id LIMIT 1",
                (quiz_id,),
            ).fetchone()[0]
            return quiz_id, question_id
        finally:
            conn.close()

    def _generate_matching(self):
        client = dlms.app.test_client()
        response = client.post("/medical/generate", data={
            "csrf_token": csrf_token(client, "/medical/matching"),
            "pack_id": "medical_concepts",
            "dataset_id": "terms",
            "round_size": "2",
            "direction": "term_to_definition",
        })
        self.assertEqual(302, response.status_code, response.get_data(as_text=True))
        return client, *self._latest_quiz_question()

    def test_medical_matching_preserves_dataset_concepts_and_tags_alias(self):
        self._write_medical_pack(matching={
            "tags": " renal-filtration, RENAL-FILTRATION, glomerular-filtration ",
        })
        _, quiz_id, question_id = self._generate_matching()

        conn = dlms.get_db()
        try:
            self.assertEqual(
                ["glomerular-filtration", "renal-filtration"],
                dlms._question_concepts(conn.cursor(), question_id),
            )
            self.assertEqual(
                2,
                conn.execute(
                    "SELECT COUNT(*) FROM question_concepts WHERE question_id = ?", (question_id,)
                ).fetchone()[0],
            )
        finally:
            conn.close()

        payload = json.loads(next(Path(dlms.DATA_FOLDER).glob("medical_*.json")).read_text())
        self.assertEqual(["renal-filtration", "glomerular-filtration"], payload[0]["concepts"])
        self.assertNotIn("Medical Metadata Only", payload[0]["concepts"])
        self.assertEqual(quiz_id, self._latest_quiz_question()[0])

    def test_medical_matching_uses_term_fallback_without_category_inference(self):
        self._write_medical_pack(matching={
            "terms": [
                {
                    "term": "Nephron", "definition": "Functional kidney unit.",
                    "category": "Renal", "concepts": ["nephron"],
                },
                {
                    "term": "Glomerulus", "definition": "Capillary filtration tuft.",
                    "category": "Renal", "tags": "glomerulus, nephron",
                },
            ],
        })
        self._generate_matching()
        _, question_id = self._latest_quiz_question()
        conn = dlms.get_db()
        try:
            concepts = dlms._question_concepts(conn.cursor(), question_id)
        finally:
            conn.close()
        self.assertEqual(["glomerulus", "nephron"], concepts)
        self.assertNotIn("Renal", concepts)
        self.assertNotIn("Medical Metadata Only", concepts)

    def test_medical_matching_without_concepts_remains_valid(self):
        self._write_medical_pack(matching={})
        self._generate_matching()
        _, question_id = self._latest_quiz_question()
        conn = dlms.get_db()
        try:
            self.assertEqual([], dlms._question_concepts(conn.cursor(), question_id))
        finally:
            conn.close()

    def test_medical_anatomy_uses_hotspot_image_and_dataset_precedence(self):
        self._write_medical_pack(images=[
            {
                "id": "explicit", "file": "images/diagram.png", "license": "CC0",
                "concepts": ["image-fallback"],
                "hotspots": [{
                    "id": "specific", "label": "Specific target",
                    "concepts": ["hotspot-specific"],
                    "shape": {"type": "circle", "x": 0.2, "y": 0.2, "radius": 0.1},
                }],
            },
            {
                "id": "image-fallback", "file": "images/diagram.png", "license": "CC0",
                "tags": "image-tag",
                "hotspots": [{
                    "id": "image", "label": "Image fallback target",
                    "shape": {"type": "circle", "x": 0.5, "y": 0.5, "radius": 0.1},
                }],
            },
            {
                "id": "dataset-fallback", "file": "images/diagram.png", "license": "CC0",
                "hotspots": [{
                    "id": "dataset", "label": "Dataset fallback target",
                    "shape": {"type": "circle", "x": 0.8, "y": 0.8, "radius": 0.1},
                }],
            },
        ])
        anatomy_path = Path(dlms.CONTENT_PACK_FOLDER) / "DLMS_Study_medical_concepts" / "data" / "anatomy.json"
        anatomy = json.loads(anatomy_path.read_text(encoding="utf-8"))
        anatomy["tags"] = "dataset-tag"
        anatomy_path.write_text(json.dumps(anatomy), encoding="utf-8")

        client = dlms.app.test_client()
        response = client.post("/medical/anatomy/generate", data={
            "csrf_token": csrf_token(client, "/medical/anatomy"),
            "pack_id": "medical_concepts",
            "dataset_id": "anatomy",
        })
        self.assertEqual(302, response.status_code, response.get_data(as_text=True))

        conn = dlms.get_db()
        try:
            rows = conn.execute("""
                SELECT id, question_text FROM questions
                WHERE quiz_id = (SELECT id FROM quizzes ORDER BY id DESC LIMIT 1)
                ORDER BY question_number, id
            """).fetchall()
            concepts_by_text = {
                row["question_text"]: dlms._question_concepts(conn.cursor(), row["id"])
                for row in rows
            }
        finally:
            conn.close()
        self.assertEqual(["hotspot-specific"], concepts_by_text["Identify the Specific target. [Image hotspot]"])
        self.assertEqual(["image-tag"], concepts_by_text["Identify the Image fallback target. [Image hotspot]"])
        self.assertEqual(["dataset-tag"], concepts_by_text["Identify the Dataset fallback target. [Image hotspot]"])
        self.assertTrue(all("Medical Metadata Only" not in values for values in concepts_by_text.values()))

    def test_medical_generated_question_contributes_study_exam_and_smart_review_evidence(self):
        concept = "medical-li-concept"
        self._write_medical_pack(matching={"concepts": [concept]})
        client, quiz_id, question_id = self._generate_matching()

        study = client.post("/api/learning-events/study-response", json={
            "quizId": quiz_id,
            "questionNumber": 1,
            "sessionId": "medical-study-session",
            "wasCorrect": False,
            "questionType": "matching",
            "selected": [],
        }, headers=csrf_headers(client))
        self.assertEqual(200, study.status_code, study.get_data(as_text=True))

        for index in range(5):
            exam = client.post("/record_attempt", json={
                "quizId": quiz_id,
                "quizTitle": "Medical Terms",
                "attemptId": f"medical-exam-{index}",
                "score": 0,
                "total": 1,
                "percent": 0,
                "startedAt": "2026-08-29T10:00:00+00:00",
                "completedAt": "2026-08-29T10:01:00+00:00",
                "mode": "Exam",
                "responseDetails": [{
                    "attemptQuestionNumber": 1,
                    "questionType": "matching",
                    "wasCorrect": False,
                    "selected": [],
                }],
                "missedDetails": [],
            }, headers=csrf_headers(client))
            self.assertEqual(200, exam.status_code, exam.get_data(as_text=True))

        conn = dlms.get_db()
        try:
            cur = conn.cursor()
            events = cur.execute("""
                SELECT event_type, COUNT(*) AS count
                FROM learning_events
                WHERE question_id = ?
                GROUP BY event_type
            """, (question_id,)).fetchall()
            event_counts = {row["event_type"]: row["count"] for row in events}
            topic = next(topic for topic in dlms._learning_intelligence_topics(
                cur, now=datetime.now(timezone.utc)
            ) if topic["name"] == concept)
            candidates, weak = dlms._smart_review_candidates(cur)
        finally:
            conn.close()

        self.assertEqual(1, event_counts["study_answer"])
        self.assertEqual(5, event_counts["exam_answer"])
        self.assertEqual(6, topic["evidence"])
        self.assertEqual("weak", topic["status"])
        self.assertTrue(any(item["name"] == concept for item in weak))
        self.assertTrue(any(candidate["question_id"] == question_id for candidate in candidates))


if __name__ == "__main__":
    unittest.main()
