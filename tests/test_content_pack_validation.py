"""DLMS Study Pack validation regression tests.
Run from the project root with: python -m unittest tests.test_content_pack_validation
The suite uses an isolated temporary APP_DATA_DIR and never touches real DLMS data.
"""
import json, os, tempfile, unittest, zipfile
from pathlib import Path

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-pack-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms

class ContentPackValidationTests(unittest.TestCase):
    def make_pack(self, name="DLMS_Study_test"):
        root = Path(_TEMP.name)/name
        (root/"data").mkdir(parents=True, exist_ok=True)
        manifest = {"schema_version":1,"id":"study_test","name":"Study Test","version":"1.0.0","content_domain":"it_cybersecurity","datasets":[{"id":"terms","title":"Terms","type":"matching","path":"data/terms.json"}],"image_datasets":[],"quiz_datasets":[]}
        data = {"schema_version":1,"id":"terms","title":"Terms","source":{"organization":"Test","license":"CC0"},"terms":[{"term":"Layer","definition":"A level in a model."},{"term":"Frame","definition":"A data-link unit."}]}
        (root/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
        (root/"data/terms.json").write_text(json.dumps(data),encoding="utf-8")
        (root/"PACK_VALIDATION.json").write_text(json.dumps({"schema_version":1,"pack_id":"study_test","overall_status":"PASS","checks":[]}),encoding="utf-8")
        return root

    def test_valid_matching_pack_passes(self):
        root = self.make_pack()
        report = dlms._validate_staged_content_pack(str(root))
        self.assertTrue(report["valid"], report["errors"])

    def test_duplicate_dataset_id_is_blocked(self):
        root = self.make_pack("DLMS_Study_dup")
        manifest = json.loads((root/"manifest.json").read_text())
        manifest["id"] = "study_dup"
        manifest["datasets"].append(dict(manifest["datasets"][0]))
        (root/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
        report = dlms._validate_staged_content_pack(str(root))
        self.assertFalse(report["valid"])
        self.assertTrue(any("duplicate dataset id" in e for e in report["errors"]))

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

if __name__ == "__main__":
    unittest.main()
