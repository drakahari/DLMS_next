"""DLMS image workflow regression tests.
Run from the project root inside the DLMS venv:
    python -m unittest tests.test_image_workflow
The suite uses an isolated temporary APP_DATA_DIR and never touches real DLMS data.
"""
import json, os, shutil, tempfile, unittest
from pathlib import Path

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-image-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms


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
            (root / "images" / name).write_bytes(b"DLMS-test-image")

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
            {"id":"png","file":"images/diagram.png","license":"CC0","source":source,"hotspots":[{"id":"circle","label":"Circle Target","shape":{"type":"circle","x":0.4,"y":0.4,"radius":0.08}}]},
            {"id":"jpg","file":"images/photo.jpg","license":"CC0","source":source,"hotspots":[{"id":"poly","label":"Polygon Target","shape":{"type":"polygon","points":[[0.1,0.1],[0.4,0.1],[0.25,0.4]]}}]},
            {"id":"webp","file":"images/interface.webp","license":"CC0","source":source,"hotspots":[{"id":"edge","label":"Edge Target","shape":{"type":"circle","x":0.95,"y":0.5,"radius":0.04}}]},
        ]
        visual = {"schema_version":1,"id":"visuals","title":"Visuals","type":"hotspot","source":source,"images":images}
        mixed = {
            "schema_version":1,"id":"mixed","title":"Mixed","source":source,
            "images":[images[0]],
            "questions":[
                {"type":"choice","question":"Choose the documented option.","image_id":"png","choices":[{"text":"One","is_correct":True},{"text":"Two","is_correct":False}]},
                {"type":"matching","question":"Match these items.","pairs":[{"left":"A","right":"1"},{"left":"B","right":"2"}]},
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

    def test_invalid_hotspot_geometry_is_rejected(self):
        root = self.make_pack()
        data_path = root / "data" / "visuals.json"
        data = json.loads(data_path.read_text())
        data["images"][0]["hotspots"][0]["shape"]["x"] = 1.5
        data_path.write_text(json.dumps(data), encoding="utf-8")
        report = dlms._validate_staged_content_pack(str(root))
        self.assertFalse(report["valid"])
        self.assertTrue(any("invalid hotspot geometry" in e for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
