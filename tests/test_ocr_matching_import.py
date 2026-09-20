"""Focused DLMS-131 OCR-assisted terminology/matching coverage."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.parsing.ocr_matching import extract_ocr_matching_pairs
from dlms.services.ocr_matching import build_ocr_matching_review_draft
from tests.csrf_test_utils import csrf_token


def _image_bytes():
    output = BytesIO()
    Image.new("RGB", (800, 600), "white").save(output, "PNG")
    return output.getvalue()


def _scanned_pdf_bytes():
    output = BytesIO()
    first = Image.new("RGB", (800, 1000), "white")
    second = Image.new("RGB", (800, 1000), "#f8f8f8")
    first.save(
        output, "PDF", resolution=144, save_all=True, append_images=[second]
    )
    return output.getvalue()


def _observations(lines, *, source_id="source", page_index=0, width=800):
    """Build neutral word observations; tuples may supply explicit word x positions."""
    output = []
    top = 30
    for line_id, line in enumerate(lines, 1):
        if isinstance(line, str):
            words = []
            left = 50
            for text in line.split():
                word_width = max(16, len(text) * 9)
                words.append((text, left, word_width))
                left += word_width + 8
        else:
            words = line
        for text, left, word_width in words:
            output.append({
                "source_id": source_id,
                "page_index": page_index,
                "source_width": width,
                "source_height": 600,
                "text": text,
                "bounding_box": {
                    "left": left,
                    "top": top,
                    "width": word_width,
                    "height": 22,
                },
                "confidence": 93.0,
                "block_id": 1,
                "paragraph_id": 1,
                "line_id": line_id,
            })
        top += 42
    return tuple(output)


class OCRMatchingParserTests(unittest.TestCase):
    def test_inline_dash_colon_and_labeled_lines_are_extracted(self):
        result = extract_ocr_matching_pairs(_observations([
            "Alpha term — A neutral first definition",
            "Beta term: A neutral second definition",
            "Term: Gamma term",
            "Definition: A neutral third definition",
        ]))
        self.assertEqual(
            ["Alpha term", "Beta term", "Gamma term"],
            [pair["left"] for pair in result["pairs"]],
        )
        self.assertEqual(
            ["inline_dash", "inline_colon", "labeled_lines"],
            [pair["ocr_metadata"]["pattern"] for pair in result["pairs"]],
        )
        self.assertEqual([], result["unassigned"])

    def test_two_column_layout_requires_repeated_aligned_geometry(self):
        aligned = _observations([
            [("Quartz", 40, 65), ("A", 430, 12), ("stable", 450, 50), ("sample", 510, 55)],
            [("Cobalt", 40, 60), ("A", 432, 12), ("second", 452, 55), ("sample", 517, 55)],
        ], width=800)
        result = extract_ocr_matching_pairs(aligned)
        self.assertEqual(["Quartz", "Cobalt"], [pair["left"] for pair in result["pairs"]])
        self.assertTrue(all(
            pair["ocr_metadata"]["pattern"] == "aligned_columns"
            for pair in result["pairs"]
        ))

        isolated = extract_ocr_matching_pairs(_observations([
            [("Ordinary", 40, 70), ("prose", 430, 50)],
        ], width=800))
        self.assertEqual([], isolated["pairs"])
        self.assertEqual("Ordinary prose", isolated["unassigned"][0]["text"])

    def test_ambiguous_and_incomplete_material_is_retained_for_repair(self):
        result = extract_ocr_matching_pairs(_observations([
            "Term: Incomplete term",
            "A free standing note without a supported pairing cue",
        ]), source_name="neutral.png")
        self.assertEqual("Incomplete term", result["pairs"][0]["left"])
        self.assertEqual("", result["pairs"][0]["right"])
        self.assertEqual(
            "A free standing note without a supported pairing cue",
            result["unassigned"][0]["text"],
        )
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn("incomplete_ocr_pair", codes)
        self.assertIn("unassigned_ocr_text", codes)

    def test_duplicate_pairs_remain_visible_and_block_initial_confirmation(self):
        parsed = extract_ocr_matching_pairs(_observations([
            "Repeated: A neutral definition",
            "Repeated: A different neutral definition",
        ]))
        processing = {
            "quiz_title": "Neutral OCR Matching",
            "matching_results": [parsed],
            "ocr_batch": {"sources": [{"original_name": "neutral.png"}]},
        }
        review = build_ocr_matching_review_draft(processing)
        question = review["questions"][0]
        self.assertEqual(2, len(question["pairs"]))
        self.assertEqual("needs_repair", question["validation_state"])
        self.assertIn(
            "duplicate_ocr_pair_side",
            {item["code"] for item in question["validation_issues"]},
        )


class OCRMatchingRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-ocr-matching-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {
            "APP_DATA_DIR": self.root,
            "PDF_IMPORT_DRAFT_FOLDER": self.root / "pdf_import_drafts",
            "OCR_IMPORT_STAGING_FOLDER": self.root / "uploads" / "ocr_screenshots",
            "PDF_OCR_STAGING_FOLDER": self.root / "uploads" / "pdf_ocr",
            "EXTERNAL_AI_DRAFT_FOLDER": self.root / "external_ai_drafts",
            "DATA_FOLDER": self.root / "data",
            "QUIZ_FOLDER": self.root / "quizzes",
            "CONFIG_FOLDER": self.root / "config",
            "QUIZ_REGISTRY": self.root / "config" / "quizzes.json",
            "PORTAL_CONFIG": self.root / "config" / "portal.json",
            "DB_PATH": self.root / "results.db",
            "QUIZ_ASSET_FOLDER": self.root / "quiz_assets",
            "LOGO_FOLDER": self.root / "static" / "logos",
            "LOGO_TEMP_FOLDER": self.root / "static" / "logos" / "_temp",
        }
        for name, value in paths.items():
            patcher = mock.patch.object(dlms, name, str(value))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runtime_patcher = mock.patch.object(
            dlms._ocr_service, "detect_tesseract_runtime", return_value=mock.Mock(version="5.5")
        )
        self.runtime_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)
        dlms._initialize_data_root_ownership(str(self.root))
        for name in (
            "PDF_IMPORT_DRAFT_FOLDER", "OCR_IMPORT_STAGING_FOLDER",
            "PDF_OCR_STAGING_FOLDER", "EXTERNAL_AI_DRAFT_FOLDER", "DATA_FOLDER",
            "QUIZ_FOLDER", "CONFIG_FOLDER", "QUIZ_ASSET_FOLDER", "LOGO_FOLDER",
            "LOGO_TEMP_FOLDER",
        ):
            Path(getattr(dlms, name)).mkdir(parents=True, exist_ok=True)
        dlms.ensure_db_initialized()
        dlms.save_registry([])
        self.client = dlms.app.test_client()

    def _upload_images(self, names):
        return self.client.post(
            "/pdf-import/ocr-matching",
            data={
                "matching_images": [
                    (BytesIO(_image_bytes()), name) for name in names
                ],
                "quiz_title": "Neutral OCR Terms",
                "matching_question": "Match each neutral term.",
                "matching_direction": "term_to_definition",
                "rights_ok": "1",
                "csrf_token": csrf_token(self.client, "/pdf-import"),
            },
            content_type="multipart/form-data",
        )

    @staticmethod
    def _processing_id(response):
        return response.headers["Location"].split("/process/", 1)[1]

    def _process(self, draft_id):
        return self.client.post(
            f"/pdf-import/ocr-matching/process/{draft_id}/next",
            headers={"X-CSRFToken": csrf_token(self.client), "Accept": "application/json"},
        )

    def test_multiple_images_are_combined_in_order_and_removed_after_conversion(self):
        uploaded = self._upload_images(["first.png", "second.png"])
        self.assertEqual(302, uploaded.status_code)
        draft_id = self._processing_id(uploaded)
        staging = Path(dlms.OCR_IMPORT_STAGING_FOLDER, draft_id)

        def recognize(_draft_id, source, _cancel):
            name = "Alpha" if source["index"] == 1 else "Beta"
            return _observations(
                [f"{name}: A neutral definition from source {source['index']}"],
                source_id=source["id"],
                page_index=source["index"] - 1,
            )

        with mock.patch.object(
            dlms, "_recognize_pdf_ocr_matching_source", side_effect=recognize
        ):
            first = self._process(draft_id).get_json()
            second = self._process(draft_id).get_json()
        self.assertEqual("processing", first["status"])
        self.assertEqual("complete", second["status"])
        self.assertIn("/external-ai/review/", second["review_url"])
        self.assertFalse(staging.exists())
        self.assertFalse(Path(dlms.PDF_IMPORT_DRAFT_FOLDER, f"{draft_id}.json").exists())

        body = self.client.get(second["review_url"]).get_data(as_text=True)
        self.assertIn("LOCAL OCR MATCHING · REVIEW", body)
        self.assertLess(body.index("Alpha"), body.index("Beta"))
        self.assertIn("OCR source: first.png", body)
        self.assertNotIn("Raw AI response", body)

    def test_ambiguous_ocr_can_be_corrected_confirmed_and_published(self):
        uploaded = self._upload_images(["repair.png"])
        draft_id = self._processing_id(uploaded)
        observations = _observations([
            "Term: Alpha",
            "Definition: A neutral first item",
            "Term: Beta",
            "Unassigned neutral definition text",
        ])
        with mock.patch.object(
            dlms, "_recognize_pdf_ocr_matching_source", return_value=observations
        ):
            state = self._process(draft_id).get_json()
        review_id = state["review_url"].rsplit("/", 1)[-1]
        stored = dlms._load_external_ai_draft(review_id)
        review = stored["review_draft"]
        self.assertTrue(review["unassigned_text"])
        self.assertEqual("", review["questions"][0]["pairs"][1]["right"])

        pairs = [
            {"left": "Alpha", "right": "A neutral first item", "category": "", "explanation": ""},
            {"left": "Beta", "right": "A repaired second item", "category": "", "explanation": ""},
        ]
        payload = [{
            "index": 0,
            "number": 1,
            "delete": False,
            "question": review["questions"][0]["question"],
            "direction": "term_to_definition",
            "round_size": 2,
            "pairs": pairs,
            "review_confirmed": True,
            "explanation": "",
            "concepts": [],
        }]
        response = self.client.post(
            f"/external-ai/review/{review_id}/publish",
            data={
                "csrf_token": csrf_token(self.client, f"/external-ai/review/{review_id}"),
                "quiz_title": "Repaired OCR Terms",
                "exam_minutes": "30",
                "source_organization": "",
                "source_dataset": review["source"]["dataset"],
                "source_version": "",
                "source_url": "",
                "source_license": "",
                "review_payload": json.dumps(payload),
            },
        )
        self.assertEqual(302, response.status_code)
        quiz_id = int(response.headers["Location"].rsplit("/", 1)[-1])
        connection = dlms.get_db()
        try:
            question = connection.execute(
                "SELECT id, question_type FROM questions WHERE quiz_id = ?", (quiz_id,)
            ).fetchone()
            published = connection.execute(
                "SELECT left_text, right_text FROM matching_pairs WHERE question_id = ? ORDER BY pair_order",
                (question["id"],),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual("matching", question["question_type"])
        self.assertEqual("A repaired second item", published[1]["right_text"])
        self.assertFalse(Path(dlms.EXTERNAL_AI_DRAFT_FOLDER, f"{review_id}.json").exists())

    def test_scanned_pdf_pages_use_existing_renderer_and_are_cleaned(self):
        response = self.client.post(
            "/pdf-import/ocr-matching",
            data={
                "matching_pdf": (BytesIO(_scanned_pdf_bytes()), "neutral-scanned.pdf"),
                "quiz_title": "Scanned Terms",
                "rights_ok": "1",
                "csrf_token": csrf_token(self.client, "/pdf-import"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(302, response.status_code)
        draft_id = self._processing_id(response)
        draft = dlms._load_pdf_import_draft(draft_id)
        self.assertEqual(2, draft["page_count"])

        def recognize(_draft_id, source, _cancel):
            return _observations(
                [f"Page {source['page']} term: A neutral page definition"],
                source_id=source["id"], page_index=source["page"] - 1,
            )

        with mock.patch.object(
            dlms, "_render_pdf_ocr_page", return_value={"width": 800, "height": 1000}
        ) as rendered, mock.patch.object(
            dlms, "_recognize_rendered_pdf_page", side_effect=recognize
        ):
            self._process(draft_id)
            state = self._process(draft_id).get_json()
        self.assertEqual("complete", state["status"])
        self.assertEqual([mock.call(draft_id, 1, mock.ANY), mock.call(draft_id, 2, mock.ANY)], rendered.call_args_list)
        self.assertFalse(Path(dlms.PDF_OCR_STAGING_FOLDER, draft_id).exists())

    def test_images_and_pdf_together_are_rejected_without_staging(self):
        response = self.client.post(
            "/pdf-import/ocr-matching",
            data={
                "matching_images": (BytesIO(_image_bytes()), "neutral.png"),
                "matching_pdf": (BytesIO(_scanned_pdf_bytes()), "neutral.pdf"),
                "rights_ok": "1",
                "csrf_token": csrf_token(self.client, "/pdf-import"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(302, response.status_code)
        self.assertEqual([], list(Path(dlms.PDF_IMPORT_DRAFT_FOLDER).glob("*.json")))

    def test_cancellation_removes_only_the_matching_task_sources_and_draft(self):
        uploaded = self._upload_images(["cancel.png"])
        draft_id = self._processing_id(uploaded)
        task = Path(dlms.OCR_IMPORT_STAGING_FOLDER, draft_id)
        unrelated = Path(dlms.OCR_IMPORT_STAGING_FOLDER, "not-a-task")
        unrelated.mkdir(parents=True)
        (unrelated / "keep.txt").write_text("keep", encoding="utf-8")
        self.assertTrue(task.is_dir())

        response = self.client.post(
            f"/pdf-import/ocr-matching/cancel/{draft_id}",
            headers={"X-CSRFToken": csrf_token(self.client)},
        )
        self.assertEqual(302, response.status_code)
        self.assertFalse(task.exists())
        self.assertFalse(
            Path(dlms.PDF_IMPORT_DRAFT_FOLDER, f"{draft_id}.json").exists()
        )
        self.assertTrue((unrelated / "keep.txt").is_file())


if __name__ == "__main__":
    unittest.main()
