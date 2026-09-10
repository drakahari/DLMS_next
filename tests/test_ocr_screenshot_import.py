"""Product-boundary coverage for DLMS-119 screenshot OCR import."""

from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from PIL import Image

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms
from dlms.services import ocr_screenshots
from tests.csrf_test_utils import csrf_token


def image_bytes(image_format="PNG", *, size=(640, 480), color="white", animated=False):
    output = BytesIO()
    first = Image.new("RGB", size, color)
    if animated:
        second = Image.new("RGB", size, "#eeeeee")
        first.save(output, format=image_format, save_all=True, append_images=[second], duration=100)
    else:
        first.save(output, format=image_format)
    return output.getvalue()


def ocr_observations(source_id, source_index, lines):
    output = []
    top = 30
    for line_number, line in enumerate(lines, 1):
        left = 80
        for word in line.split():
            width = max(15, len(word) * 9)
            output.append(
                {
                    "source_id": source_id,
                    "page_index": source_index - 1,
                    "source_width": 640,
                    "source_height": 480,
                    "text": word,
                    "bounding_box": {"left": left, "top": top, "width": width, "height": 22},
                    "confidence": 94.0,
                    "block_id": 1,
                    "paragraph_id": 1,
                    "line_id": line_number,
                }
            )
            left += width + 8
        top += 45
    return tuple(output)


class OCRScreenshotImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlms-ocr-screenshots-")
        self.root = Path(self.temp.name)
        self.drafts = self.root / "drafts"
        self.banks = self.root / "banks"
        self.staging = self.root / "uploads" / "ocr_screenshots"
        self.runtime = mock.Mock(version="5.5.3")
        self.patchers = [
            mock.patch.object(dlms, "PDF_IMPORT_DRAFT_FOLDER", str(self.drafts)),
            mock.patch.object(dlms, "PDF_QUESTION_BANK_FOLDER", str(self.banks)),
            mock.patch.object(dlms, "OCR_IMPORT_STAGING_FOLDER", str(self.staging)),
            mock.patch.object(
                dlms._ocr_service,
                "detect_tesseract_runtime",
                return_value=self.runtime,
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
        dlms.OCR_SCREENSHOT_CANCELLATIONS = ocr_screenshots.OCRTaskCancellationRegistry()
        self.client = dlms.app.test_client()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def upload(self, files, **fields):
        data = {
            "screenshots": [(BytesIO(payload), name) for name, payload in files],
            "quiz_title": fields.get("quiz_title", "OCR Review"),
            "exam_minutes": "30",
            "rights_ok": "1",
            "csrf_token": csrf_token(self.client, "/pdf-import"),
        }
        return self.client.post(
            "/pdf-import/screenshots",
            data=data,
            content_type="multipart/form-data",
        )

    @staticmethod
    def draft_id(response):
        return response.headers["Location"].split("/process/", 1)[1]

    def recognize(self, _draft_id, source, _cancel_requested):
        return ocr_observations(
            source["id"],
            source["index"],
            [
                f"Which protocol is source {source['index']}?",
                "A. FTP",
                "B. SFTP",
                "C. HTTP",
                "Correct answer: B",
                "Explanation: SFTP is encrypted.",
            ],
        )

    def test_unavailable_landing_explains_source_setup_without_disabling_normal_pdf(self):
        diagnostic = mock.Mock(
            guidance=(
                "Source-mode OCR requires Tesseract 5 on PATH or configured with "
                "DLMS_TESSERACT_EXECUTABLE, plus English trained data and TSV support."
            )
        )
        with mock.patch.object(
            dlms._ocr_service, "detect_tesseract_runtime", return_value=None
        ), mock.patch.object(
            dlms._ocr_service, "diagnose_tesseract_runtime", return_value=diagnostic
        ):
            response = self.client.get("/pdf-import")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("OCR unavailable", body)
        self.assertIn("Normal selectable-text PDF import remains fully available", body)
        self.assertIn("DLMS_TESSERACT_EXECUTABLE", body)
        self.assertIn('form action="/pdf-import/analyze"', body)
        self.assertNotIn('form action="/pdf-import/analyze" disabled', body)
        self.assertIn('name="screenshots"', body)
        self.assertRegex(body, r'name="screenshots"[^>]*disabled')

    def test_ordered_upload_stages_opaque_reencoded_sources_and_exact_duplicates(self):
        first = image_bytes("PNG", color="white")
        second = image_bytes("JPEG", color="blue")
        response = self.upload(
            [("first screenshot.png", first), ("second.jpg", second), ("duplicate.png", first)]
        )
        self.assertEqual(response.status_code, 302)
        draft_id = self.draft_id(response)
        draft = dlms._load_pdf_import_draft(draft_id)
        sources = draft["ocr_batch"]["sources"]
        self.assertEqual([source["index"] for source in sources], [1, 2, 3])
        self.assertEqual([source["original_name"] for source in sources], ["first screenshot.png", "second.jpg", "duplicate.png"])
        self.assertTrue(all(source["id"] not in source["original_name"] for source in sources))
        self.assertEqual(sources[2]["duplicate_of"], sources[0]["id"])
        self.assertTrue((self.staging / draft_id / sources[0]["filename"]).is_file())
        self.assertTrue((self.staging / draft_id / ocr_screenshots.OCR_SCREENSHOT_TASK_MARKER).is_file())

        preview = self.client.get(
            f"/pdf-import/screenshots/source/{draft_id}/{sources[0]['id']}"
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.mimetype, "image/png")
        self.assertEqual(preview.headers["Cache-Control"], "private, no-store")

        draft = dlms._load_pdf_import_draft(draft_id)
        draft["ocr_batch"]["sources"][0]["mime_type"] = "text/html"
        dlms._save_pdf_import_draft(draft)
        preview = self.client.get(
            f"/pdf-import/screenshots/source/{draft_id}/{sources[0]['id']}"
        )
        self.assertEqual(preview.mimetype, "image/png")

    def test_png_jpeg_and_webp_are_supported_but_animated_webp_is_rejected(self):
        files = [
            ("one.png", image_bytes("PNG")),
            ("two.jpeg", image_bytes("JPEG")),
            ("three.webp", image_bytes("WEBP")),
            ("animated.webp", image_bytes("WEBP", animated=True)),
        ]
        response = self.upload(files)
        draft = dlms._load_pdf_import_draft(self.draft_id(response))
        sources = draft["ocr_batch"]["sources"]
        self.assertEqual([source["status"] for source in sources[:3]], ["pending"] * 3)
        self.assertEqual(sources[3]["status"], "validation_failed")
        self.assertIn("animated images are not accepted", sources[3]["error"])

    def test_malformed_mismatched_and_unsupported_sources_report_per_source_errors(self):
        png = image_bytes("PNG")
        response = self.upload(
            [("good.png", png), ("mismatch.jpg", png), ("bad.png", b"not an image"), ("bad.gif", b"GIF89a")]
        )
        draft = dlms._load_pdf_import_draft(self.draft_id(response))
        sources = draft["ocr_batch"]["sources"]
        self.assertEqual(sources[0]["status"], "pending")
        self.assertEqual([source["status"] for source in sources[1:]], ["validation_failed"] * 3)
        self.assertIn("do not match", sources[1]["error"])
        self.assertIn("valid supported raster", sources[2]["error"])
        self.assertIn("use PNG", sources[3]["error"])

    def test_more_than_ten_images_is_rejected_without_staging(self):
        payload = image_bytes("PNG", size=(20, 20))
        response = self.upload([(f"{index}.png", payload) for index in range(11)])
        self.assertEqual(response.status_code, 302)
        self.assertEqual([], list(self.drafts.glob("*.json")))
        self.assertFalse(self.staging.exists() and any(self.staging.iterdir()))
        with self.client.session_transaction() as session:
            messages = [message for _category, message in session.get("_flashes", [])]
        self.assertTrue(any("no more than 10" in message for message in messages))

    def test_ten_images_are_accepted_and_preserve_multipart_order(self):
        payload = image_bytes("PNG", size=(20, 20))
        response = self.upload([(f"source-{index}.png", payload) for index in range(1, 11)])
        draft = dlms._load_pdf_import_draft(self.draft_id(response))
        self.assertEqual(
            [source["original_name"] for source in draft["ocr_batch"]["sources"]],
            [f"source-{index}.png" for index in range(1, 11)],
        )

    def test_per_file_byte_and_dimension_limits_are_reported_on_the_source(self):
        oversized = b"x" * (ocr_screenshots.OCR_SCREENSHOT_MAX_FILE_BYTES + 1)
        response = self.upload([("too-large.png", oversized)])
        draft = dlms._load_pdf_import_draft(self.draft_id(response))
        self.assertEqual(draft["ocr_batch"]["sources"][0]["status"], "validation_failed")
        self.assertIn("16.0 MB limit", draft["ocr_batch"]["sources"][0]["error"])

        too_wide = image_bytes("PNG", size=(ocr_screenshots.OCR_SCREENSHOT_MAX_SIDE + 1, 1))
        response = self.upload([("too-wide.png", too_wide)])
        draft = dlms._load_pdf_import_draft(self.draft_id(response))
        self.assertEqual(draft["ocr_batch"]["sources"][0]["status"], "validation_failed")
        self.assertIn("12000×12000", draft["ocr_batch"]["sources"][0]["error"])

    def test_decompression_bomb_is_rejected_as_a_per_source_validation_error(self):
        with mock.patch.object(
            dlms.Image,
            "open",
            side_effect=Image.DecompressionBombError("synthetic bomb"),
        ):
            response = self.upload([("bomb.png", image_bytes("PNG"))])
        draft = dlms._load_pdf_import_draft(self.draft_id(response))
        source = draft["ocr_batch"]["sources"][0]
        self.assertEqual(source["status"], "validation_failed")
        self.assertIn("valid supported raster", source["error"])

    def test_partial_ocr_failure_continues_and_review_exposes_source_results(self):
        response = self.upload(
            [("bad-ocr.png", image_bytes("PNG", color="red")), ("good.png", image_bytes("PNG", color="white"))]
        )
        draft_id = self.draft_id(response)

        def partial(_draft_id, source, cancel_requested):
            self.assertFalse(cancel_requested())
            if source["index"] == 1:
                raise RuntimeError("private OCR failure")
            return self.recognize(_draft_id, source, cancel_requested)

        with mock.patch.object(dlms, "_recognize_pdf_ocr_source", side_effect=partial):
            first = self.client.post(
                f"/pdf-import/screenshots/process/{draft_id}/next",
                headers={"X-CSRFToken": csrf_token(self.client), "Accept": "application/json"},
            )
            second = self.client.post(
                f"/pdf-import/screenshots/process/{draft_id}/next",
                headers={"X-CSRFToken": csrf_token(self.client), "Accept": "application/json"},
            )
        self.assertEqual(first.get_json()["processed"], 1)
        result = second.get_json()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["failed"], 1)
        self.assertTrue(result["review_url"])
        draft = dlms._load_pdf_import_draft(draft_id)
        self.assertEqual(draft["ocr_batch"]["sources"][0]["error"], "OCR or layout analysis failed for this screenshot.")
        self.assertEqual(len(draft["questions"]), 1)
        html = self.client.get(result["review_url"]).get_data(as_text=True)
        self.assertIn("Screenshot 1 · bad-ocr.png", html)
        self.assertNotIn("private OCR failure", html)
        self.assertIn("Source screenshot 2 for OCR question 1", html)
        self.assertIn("I compared this draft with the source", html)

    def test_successful_review_save_removes_sources_and_never_persists_temporary_metadata(self):
        response = self.upload([("question.png", image_bytes("PNG"))])
        draft_id = self.draft_id(response)
        with mock.patch.object(dlms, "_recognize_pdf_ocr_source", side_effect=self.recognize):
            processed = self.client.post(
                f"/pdf-import/screenshots/process/{draft_id}/next",
                headers={"X-CSRFToken": csrf_token(self.client), "Accept": "application/json"},
            ).get_json()
        self.assertEqual(processed["status"], "complete")
        self.assertTrue((self.staging / draft_id).is_dir())
        payload = [{
            "index": 0,
            "delete": False,
            "question": "Which protocol?",
            "choices": [{"label": "A", "text": "FTP"}, {"label": "B", "text": "SFTP"}],
            "answer_mode": "single",
            "correct_answers": ["B"],
            "correctness_confirmed": True,
            "explanation": "SFTP is encrypted.",
            "feedback": {},
        }]
        saved = self.client.post(
            f"/pdf-import/save/{draft_id}",
            data={
                "quiz_title": "OCR Bank",
                "exam_minutes": "30",
                "review_payload": json.dumps(payload),
                "csrf_token": csrf_token(self.client),
            },
        )
        self.assertEqual(saved.status_code, 302)
        bank = dlms._load_pdf_question_bank(saved.headers["Location"].rsplit("/", 1)[-1])
        self.assertEqual(bank["source_kind"], "user-provided-screenshot-ocr")
        self.assertNotIn("ocr_metadata", bank["questions"][0])
        self.assertFalse((self.staging / draft_id).exists())
        self.assertFalse((self.drafts / f"{draft_id}.json").exists())

    def test_missing_preview_degrades_safely_and_cancel_cleans_only_task_state(self):
        response = self.upload([("question.png", image_bytes("PNG"))])
        draft_id = self.draft_id(response)
        with mock.patch.object(dlms, "_recognize_pdf_ocr_source", side_effect=self.recognize):
            self.client.post(
                f"/pdf-import/screenshots/process/{draft_id}/next",
                headers={"X-CSRFToken": csrf_token(self.client), "Accept": "application/json"},
            )
        draft = dlms._load_pdf_import_draft(draft_id)
        source = draft["ocr_batch"]["sources"][0]
        (self.staging / draft_id / source["filename"]).unlink()
        html = self.client.get(f"/pdf-import/review/{draft_id}").get_data(as_text=True)
        self.assertIn("Source preview no longer available", html)

        unrelated = self.staging / "not-a-task"
        unrelated.mkdir(parents=True)
        (unrelated / "user.txt").write_text("keep", encoding="utf-8")
        cancelled = self.client.post(
            f"/pdf-import/screenshots/cancel/{draft_id}",
            headers={"X-CSRFToken": csrf_token(self.client)},
        )
        self.assertEqual(cancelled.status_code, 302)
        self.assertFalse((self.staging / draft_id).exists())
        self.assertTrue((unrelated / "user.txt").exists())

    def test_screenshot_cancel_cannot_delete_a_normal_pdf_draft(self):
        draft = {
            "id": "normalpdfdraft",
            "source_kind": "user-provided-pdf",
            "document_type": "question_bank",
        }
        dlms._save_pdf_import_draft(draft)
        response = self.client.post(
            "/pdf-import/screenshots/cancel/normalpdfdraft",
            headers={"X-CSRFToken": csrf_token(self.client), "Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue((self.drafts / "normalpdfdraft.json").is_file())

    def test_correctness_confirmation_is_required_for_every_active_ocr_record(self):
        response = self.upload([("question.png", image_bytes("PNG"))])
        draft_id = self.draft_id(response)
        with mock.patch.object(dlms, "_recognize_pdf_ocr_source", side_effect=self.recognize):
            self.client.post(
                f"/pdf-import/screenshots/process/{draft_id}/next",
                headers={"X-CSRFToken": csrf_token(self.client), "Accept": "application/json"},
            )
        draft = dlms._load_pdf_import_draft(draft_id)
        question = draft["questions"][0]
        self.assertTrue(question["correctness_confirmation_required"])
        payload = [{
            "index": 0,
            "delete": False,
            "question": question["question"],
            "choices": question["choices"],
            "answer_mode": question["answer_mode"],
            "correct_answers": question["correct_answers"],
            "correctness_confirmed": False,
            "explanation": question["explanation"],
            "feedback": {},
        }]
        rejected = self.client.post(
            f"/pdf-import/save/{draft_id}",
            data={"quiz_title": "OCR", "review_payload": json.dumps(payload), "csrf_token": csrf_token(self.client)},
        )
        self.assertTrue(rejected.headers["Location"].endswith(f"/pdf-import/review/{draft_id}"))
        self.assertTrue((self.staging / draft_id).exists())

    def test_screenshot_staging_is_outside_the_portable_backup_inventory(self):
        self.assertTrue(
            dlms._backup_rel_is_excluded(
                "uploads/ocr_screenshots/TaskIdentity12/source.png"
            )
        )

    def test_screenshot_upload_requires_csrf_and_is_a_protected_critical_request(self):
        rejected = self.client.post(
            "/pdf-import/screenshots",
            data={
                "screenshots": (BytesIO(image_bytes("PNG")), "question.png"),
                "rights_ok": "1",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(rejected.status_code, 400)

        manager = mock.Mock()
        with mock.patch.object(dlms, "browser_presence_manager", manager):
            accepted = self.upload([("question.png", image_bytes("PNG"))])
        self.assertEqual(accepted.status_code, 302)
        manager.begin_critical_operation.assert_called_once_with()
        manager.end_critical_operation.assert_called_once_with()

    def test_smart_pdf_help_documents_screenshot_and_selective_pdf_ocr(self):
        html = (Path(__file__).parents[1] / "static" / "help-smart-pdf.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("Quiz screenshot OCR", html)
        self.assertIn("OCR runs locally on this device", html)
        self.assertIn("2–26 choices and multiple correct answers", html)
        self.assertIn("Selective scanned-page OCR", html)
        self.assertIn("choose up to 25", html)
        self.assertIn("not glossary extraction", html)

    def test_cancellation_registry_signals_active_owner_without_cross_task_effects(self):
        registry = ocr_screenshots.OCRTaskCancellationRegistry()
        observed = threading.Event()
        release = threading.Event()

        def worker():
            with registry.active("TaskIdentity12") as cancel_requested:
                observed.set()
                release.wait(2)
                self.assertTrue(cancel_requested())

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(observed.wait(1))
        self.assertTrue(registry.request_cancel("TaskIdentity12"))
        self.assertFalse(registry.cancel_requested("OtherIdentity12"))
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_cancellation_registry_allows_only_one_active_source_request(self):
        registry = ocr_screenshots.OCRTaskCancellationRegistry()
        with registry.active("TaskIdentity12"):
            with self.assertRaises(ocr_screenshots.OCRTaskBusyError):
                with registry.active("TaskIdentity12"):
                    self.fail("a second source request must not become active")


class OCRScreenshotStagingTests(unittest.TestCase):
    def test_aggregate_limit_and_stale_cleanup_are_bounded_to_marked_tasks(self):
        with tempfile.TemporaryDirectory(prefix="dlms-ocr-stage-unit-") as temp:
            root = Path(temp)
            uploads = [mock.Mock(filename=f"{index}.png") for index in range(5)]

            def store(_upload, destination, source_id, **_limits):
                path = Path(destination) / f"{source_id}.png"
                path.write_bytes(os.urandom(8))
                return {
                    "filename": path.name,
                    "mime_type": "image/png",
                    "width": 10,
                    "height": 10,
                    "consumed_bytes": 14 * 1024 * 1024,
                }

            with self.assertRaisesRegex(ValueError, "64 MiB"):
                ocr_screenshots.stage_screenshot_batch(
                    root, "AggregateTask12", uploads, store_validated_upload=store
                )
            self.assertFalse((root / "AggregateTask12").exists())

            task = root / "OldMarkedTask12"
            task.mkdir()
            (task / ocr_screenshots.OCR_SCREENSHOT_TASK_MARKER).write_text(
                json.dumps({"kind": "dlms-ocr-screenshot-task", "task_id": task.name}),
                encoding="utf-8",
            )
            os.utime(task, (1, 1))
            unrelated = root / "UnmarkedFolder12"
            unrelated.mkdir()
            os.utime(unrelated, (1, 1))
            removed = ocr_screenshots.prune_stale_screenshot_tasks(
                root, now=lambda: ocr_screenshots.OCR_SCREENSHOT_STALE_SECONDS + 2
            )
            self.assertEqual(removed, 1)
            self.assertFalse(task.exists())
            self.assertTrue(unrelated.exists())

    def test_committed_synthetic_fixture_corpus_is_decodable_and_redistribution_owned(self):
        fixture_root = Path(__file__).parent / "fixtures" / "ocr"
        expected = {
            "screenshot-explicit-abcd.png",
            "screenshot-unlabelled-six.png",
            "screenshot-explicit-eight.png",
            "screenshot-multiple-two.png",
            "screenshot-multiple-three.png",
            "screenshot-ui-chrome.png",
            "screenshot-ambiguous.png",
            "screenshot-unicode.png",
            "screenshot-low-resolution.png",
            "screenshot-rotated.png",
        }
        self.assertEqual(
            {path.name for path in fixture_root.glob("screenshot-*.png")}, expected
        )
        self.assertIn("redistribution-safe", (fixture_root / "README.md").read_text(encoding="utf-8"))
        for filename in sorted(expected):
            with self.subTest(filename=filename), Image.open(fixture_root / filename) as image:
                image.load()
                self.assertEqual(image.format, "PNG")
                self.assertGreater(image.width, 0)
                self.assertGreater(image.height, 0)


if __name__ == "__main__":
    unittest.main()
