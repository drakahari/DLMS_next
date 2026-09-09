import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.pyinstaller_ocr import collect_tesseract_bundle


ROOT = Path(__file__).resolve().parents[1]


class OCRPackagingContractTests(unittest.TestCase):
    def test_optional_main_bundle_is_empty_when_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(collect_tesseract_bundle(), ([], []))

    def test_probe_requires_explicit_bundle_root(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "DLMS_TESSERACT_BUNDLE_ROOT"):
                collect_tesseract_bundle(required=True)

    def test_complete_bundle_maps_executable_data_and_licenses(self):
        with tempfile.TemporaryDirectory(prefix="dlms-ocr-bundle-") as temp:
            root = Path(temp)
            executable = root / "bin" / (
                "tesseract.exe" if sys.platform == "win32" else "tesseract"
            )
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"runtime")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            native_library = root / "bin" / "libtesseract-probe.so.5"
            native_library.write_bytes(b"library")
            (root / "tessdata" / "configs").mkdir(parents=True)
            (root / "tessdata" / "eng.traineddata").write_bytes(b"model")
            (root / "tessdata" / "configs" / "tsv").write_text(
                "tessedit_create_tsv 1\n", encoding="utf-8"
            )
            (root / "licenses").mkdir()
            for name in (
                "tesseract-LICENSE.txt",
                "tessdata-LICENSE.txt",
                "leptonica-LICENSE.txt",
            ):
                (root / "licenses" / name).write_text("license", encoding="utf-8")

            with mock.patch.dict(
                os.environ, {"DLMS_TESSERACT_BUNDLE_ROOT": str(root)}, clear=True
            ):
                binaries, datas = collect_tesseract_bundle(required=True)

        self.assertEqual(
            binaries,
            [
                (str(executable), "ocr/tesseract/bin"),
                (str(native_library), "ocr/tesseract/bin"),
            ],
        )
        destinations = {destination for _source, destination in datas}
        self.assertEqual(
            destinations,
            {
                "ocr/tesseract/tessdata",
                "ocr/tesseract/tessdata/configs",
                "ocr/tesseract/licenses",
            },
        )

    def test_specs_share_the_same_contract_and_frozen_probe_is_path_independent(self):
        main_spec = (ROOT / "DLMS.spec").read_text(encoding="utf-8")
        probe_spec = (ROOT / "DLMS-OCR-Probe.spec").read_text(encoding="utf-8")
        service = (ROOT / "dlms" / "services" / "ocr.py").read_text(encoding="utf-8")
        probe = (ROOT / "tools" / "ocr_packaging_probe.py").read_text(encoding="utf-8")
        self.assertIn("collect_tesseract_bundle()", main_spec)
        self.assertIn("collect_tesseract_bundle(required=True)", probe_spec)
        self.assertIn('"dlms.services.ocr"', main_spec)
        self.assertIn('"pypdfium2"', main_spec)
        self.assertIn('"pypdfium2_raw"', main_spec)
        self.assertIn('copy_metadata("pypdfium2")', main_spec)
        self.assertIn('detected_frozen_root / "ocr" / "tesseract"', service)
        self.assertIn('if not getattr(sys, "frozen", False)', probe)
        self.assertIn("except OCRTimeoutError", probe)
        self.assertIn("except OCRCancelledError", probe)


if __name__ == "__main__":
    unittest.main()
