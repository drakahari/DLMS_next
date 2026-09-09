import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from dlms.services import ocr


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "ocr"


class OCRServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlms-ocr-service-")
        self.root = Path(self.temp.name)
        self.tessdata = self.root / "tessdata"
        self.tessdata.mkdir()
        (self.tessdata / "eng.traineddata").write_bytes(b"test language data")
        (self.tessdata / "configs").mkdir()
        (self.tessdata / "configs" / "tsv").write_text("tessedit_create_tsv 1\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _script(self, body):
        path = self.root / "tesseract"
        path.write_text(
            f"#!{sys.executable}\n" + textwrap.dedent(body), encoding="utf-8"
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def _runtime(self, script, version="5.5.3"):
        return ocr.OCRRuntime(script, self.tessdata, version, False)

    def test_unavailable_engine_is_feature_detected(self):
        with mock.patch.object(ocr.shutil, "which", return_value=None), mock.patch.dict(
            os.environ,
            {"DLMS_TESSERACT_EXECUTABLE": "", "DLMS_TESSDATA_PREFIX": ""},
            clear=False,
        ):
            self.assertIsNone(ocr.detect_tesseract_runtime())

    def test_version_detection_uses_explicit_trusted_paths(self):
        script = self._script(
            """
            import sys
            if sys.argv[1:] == ["--version"]:
                print("tesseract 5.5.3")
            else:
                raise SystemExit(2)
            """
        )
        runtime = ocr.resolve_tesseract_runtime(
            executable=script, tessdata_dir=self.tessdata
        )
        self.assertEqual(runtime.version, "5.5.3")
        self.assertFalse(runtime.bundled)
        self.assertEqual(runtime.executable, script.resolve())

    def test_version_detection_timeout_reports_unavailable(self):
        script = self._script("print('unused')\n")
        with mock.patch.object(
            ocr.subprocess,
            "run",
            side_effect=ocr.subprocess.TimeoutExpired([str(script), "--version"], 5),
        ):
            with self.assertRaises(ocr.OCRUnavailableError):
                ocr.resolve_tesseract_runtime(
                    executable=script, tessdata_dir=self.tessdata
                )

    def test_frozen_lookup_requires_bundle_and_never_uses_path(self):
        bundle = self.root / "frozen" / "ocr" / "tesseract"
        (bundle / "bin").mkdir(parents=True)
        (bundle / "tessdata").mkdir()
        script = bundle / "bin" / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
        script.write_text(f"#!{sys.executable}\nprint('tesseract 5.5.3')\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        (bundle / "tessdata" / "eng.traineddata").write_bytes(b"data")
        (bundle / "tessdata" / "configs").mkdir()
        (bundle / "tessdata" / "configs" / "tsv").write_text(
            "tessedit_create_tsv 1\n", encoding="utf-8"
        )
        with mock.patch.object(ocr.shutil, "which", side_effect=AssertionError("PATH used")):
            runtime = ocr.resolve_tesseract_runtime(frozen_root=self.root / "frozen")
        self.assertTrue(runtime.bundled)
        self.assertEqual(runtime.executable, script)

    def test_tsv_fixture_parses_coordinates_and_confidence(self):
        observations = ocr.parse_tesseract_tsv(
            (FIXTURES / "dlms-question.expected.tsv").read_bytes(),
            source_id="fixture",
            page_index=0,
            source_width=1200,
            source_height=700,
            engine_version="5.5.3",
        )
        self.assertEqual([item.text for item in observations], ["DLMS", "Which", "A.", "FTP"])
        self.assertEqual(observations[1].bounding_box.left, 120)
        self.assertEqual(observations[1].confidence, 94.2)
        self.assertEqual(observations[1].line_id, 1)

    def test_successful_bounded_invocation_uses_internal_filename_and_no_shell(self):
        tsv = (FIXTURES / "dlms-question.expected.tsv").read_text(encoding="utf-8")
        script = self._script(
            f"""
            import sys
            if '--version' in sys.argv:
                print('tesseract 5.5.3')
            else:
                assert sys.argv[1].endswith('input-image.png')
                print({tsv!r}, end='')
            """
        )
        with mock.patch.object(ocr.subprocess, "Popen", wraps=ocr.subprocess.Popen) as popen:
            observations = ocr.recognize_image_bytes(
                (FIXTURES / "dlms-question.png").read_bytes(),
                source_id="fixture",
                source_width=1200,
                source_height=700,
                runtime=self._runtime(script),
            )
        self.assertTrue(observations)
        args, kwargs = popen.call_args
        self.assertIsInstance(args[0], list)
        self.assertFalse(kwargs["shell"])
        self.assertNotIn("PATH", kwargs["env"])
        self.assertEqual(kwargs["env"]["TESSDATA_PREFIX"], str(self.tessdata))

    def test_timeout_terminates_child(self):
        script = self._script("import time\ntime.sleep(30)\n")
        with self.assertRaises(ocr.OCRTimeoutError):
            ocr.recognize_image_bytes(
                b"image",
                source_id="timeout",
                source_width=10,
                source_height=10,
                runtime=self._runtime(script),
                timeout_seconds=0.05,
            )

    def test_cancellation_terminates_child(self):
        script = self._script("import time\ntime.sleep(30)\n")
        with self.assertRaises(ocr.OCRCancelledError):
            ocr.recognize_image_bytes(
                b"image",
                source_id="cancel",
                source_width=10,
                source_height=10,
                runtime=self._runtime(script),
                cancel_requested=lambda: True,
            )

    def test_nonzero_exit_is_publicly_bounded(self):
        script = self._script("import sys\nprint('private detail', file=sys.stderr)\nraise SystemExit(7)\n")
        with self.assertRaisesRegex(ocr.OCRProcessError, "status 7") as raised:
            ocr.recognize_image_bytes(
                b"image",
                source_id="failure",
                source_width=10,
                source_height=10,
                runtime=self._runtime(script),
            )
        self.assertNotIn("private detail", str(raised.exception))

    def test_process_output_limit_is_enforced(self):
        script = self._script("print('x' * 4096)\n")
        with self.assertRaises(ocr.OCROutputLimitError):
            ocr.recognize_image_bytes(
                b"image",
                source_id="large-output",
                source_width=10,
                source_height=10,
                runtime=self._runtime(script),
                max_output_bytes=128,
            )

    def test_malformed_and_oversized_tsv_are_rejected(self):
        with self.assertRaises(ocr.OCRTSVError):
            ocr.parse_tesseract_tsv(
                b"text\tconf\nword\t99\n",
                source_id="bad",
                page_index=0,
                source_width=10,
                source_height=10,
                engine_version="5",
            )
        with self.assertRaises(ocr.OCROutputLimitError):
            ocr.parse_tesseract_tsv(
                b"x" * (ocr.OCR_MAX_TSV_BYTES + 1),
                source_id="large",
                page_index=0,
                source_width=10,
                source_height=10,
                engine_version="5",
            )


if __name__ == "__main__":
    unittest.main()
