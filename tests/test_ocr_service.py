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

    def test_source_mode_uses_environment_override_without_path_discovery(self):
        script = self._script("print('tesseract 5.5.3')\n")
        with mock.patch.dict(
            os.environ,
            {
                "DLMS_TESSERACT_EXECUTABLE": str(script),
                "DLMS_TESSDATA_PREFIX": str(self.tessdata),
            },
            clear=False,
        ), mock.patch.object(ocr.shutil, "which", side_effect=AssertionError("PATH used")):
            configured = ocr.resolve_tesseract_runtime()
        self.assertEqual(configured.executable, script.resolve())
        self.assertEqual(configured.tessdata_dir, self.tessdata.resolve())

    def test_source_mode_path_discovery_uses_a_valid_known_tessdata_location(self):
        executable = self.root / "bin" / "tesseract"
        executable.parent.mkdir()
        executable.write_text(
            f"#!{sys.executable}\nprint('tesseract 5.5.3')\n", encoding="utf-8"
        )
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        system_tessdata = self.root / "share" / "tessdata"
        (system_tessdata / "configs").mkdir(parents=True)
        (system_tessdata / "eng.traineddata").write_bytes(b"model")
        (system_tessdata / "configs" / "tsv").write_text(
            "tessedit_create_tsv 1\n", encoding="utf-8"
        )
        with mock.patch.object(ocr.shutil, "which", return_value=str(executable)), mock.patch.dict(
            os.environ,
            {"DLMS_TESSERACT_EXECUTABLE": "", "DLMS_TESSDATA_PREFIX": ""},
            clear=False,
        ):
            runtime = ocr.resolve_tesseract_runtime()
        self.assertEqual(runtime.executable, executable.resolve())
        self.assertTrue((runtime.tessdata_dir / "eng.traineddata").is_file())
        self.assertTrue((runtime.tessdata_dir / "configs" / "tsv").is_file())

    def test_unavailable_diagnostics_are_safe_and_mode_specific(self):
        missing = self.root / "private" / "missing-tesseract"
        with mock.patch.object(ocr.shutil, "which", return_value=None), mock.patch.dict(
            os.environ,
            {
                "DLMS_TESSERACT_EXECUTABLE": str(missing),
                "DLMS_TESSDATA_PREFIX": str(self.tessdata),
            },
            clear=False,
        ):
            source = ocr.diagnose_tesseract_runtime()
        self.assertFalse(source.available)
        self.assertEqual(source.mode, "source")
        self.assertEqual(source.reason, "executable-unavailable")
        self.assertIn("DLMS_TESSERACT_EXECUTABLE", source.guidance)
        self.assertNotIn(str(missing), source.guidance)

        frozen = ocr.diagnose_tesseract_runtime(frozen_root=self.root / "missing-frozen")
        self.assertFalse(frozen.available)
        self.assertEqual(frozen.mode, "frozen")
        self.assertIn("does not use a system Tesseract fallback", frozen.guidance)
        self.assertNotIn(str(self.root), frozen.guidance)

    def test_incomplete_tessdata_diagnostic_is_actionable(self):
        script = self._script("print('tesseract 5.5.3')\n")
        (self.tessdata / "configs" / "tsv").unlink()
        diagnostic = ocr.diagnose_tesseract_runtime(
            executable=script, tessdata_dir=self.tessdata
        )
        self.assertEqual(diagnostic.reason, "tsv-config-unavailable")
        self.assertIn("English trained data or TSV configuration", diagnostic.guidance)
        self.assertNotIn(str(self.tessdata), diagnostic.guidance)

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

    def test_region_retry_is_one_bounded_composite_and_restores_source_coordinates(self):
        source_bytes = (FIXTURES / "dlms-question.png").read_bytes()
        retry_word = ocr.OCRObservation(
            source_id="retry",
            page_index=0,
            source_width=258,
            source_height=140,
            text="Quartz",
            bounding_box=ocr.OCRBoundingBox(24, 12, 60, 18),
            confidence=92.0,
            block_id=1,
            paragraph_id=1,
            line_id=1,
            engine="tesseract",
            engine_version="5.5.3",
        )
        regions = (
            {"left": 0, "top": 100, "right": 1200, "bottom": 160, "ocr_left": 50, "ocr_right": 300},
            {"left": 0, "top": 200, "right": 1200, "bottom": 260, "ocr_left": 50, "ocr_right": 300},
        )
        with mock.patch.object(
            ocr, "recognize_image_bytes", return_value=(retry_word,)
        ) as recognize:
            recovered = ocr.recognize_image_regions(
                source_bytes,
                regions,
                source_id="source",
                source_width=1200,
                source_height=700,
                runtime=mock.Mock(),
            )

        self.assertEqual(recognize.call_count, 1)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].source_id, "source")
        self.assertEqual(recovered[0].source_width, 1200)
        self.assertEqual(recovered[0].bounding_box.left, 70)
        self.assertEqual(recovered[0].bounding_box.top, 107)

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
