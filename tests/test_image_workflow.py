"""DLMS image workflow regression tests.
Run from the project root inside the DLMS venv:
    python -m unittest tests.test_image_workflow
The suite uses an isolated temporary APP_DATA_DIR and never touches real DLMS data.
"""
import json, os, shutil, tempfile, unittest
from unittest import mock
from pathlib import Path
from PIL import Image

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-image-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms
from tests.csrf_test_utils import csrf_token


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
